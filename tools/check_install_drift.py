#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安装漂移检查：比对真源 skill 目录与各安装点的副本，逐文件分类差异。

被 install.sh 调用（`./install.sh --check`，以及正常安装前的自动闸门）。
只读，绝不写盘。

四类差异：
  真源更新        真源改了没装（正常，跑一次安装即可）
  副本被本地改过  副本文件 mtime 晚于该安装点 marker 的 installed_at
                  → 危险：copy_to 是 rm -rf + cp -R，下次安装会无声销毁
  仅真源有        副本缺文件（旧安装 / 装漏了）
  仅副本有        真源没有该文件

mtime 判据成立的前提：install.sh 用 `cp -R`（不带 -p），不保留 mtime，
所以装完的文件 mtime ≈ 安装时刻，一定不晚于随后写入的 marker installed_at。
判不准时（marker 缺失 / 损坏 / installed_at=unknown）如实降级为「无法判断」，
不假装能判，也不据此中止安装。

退出码：0 完全一致 / 1 有差异但不危险 / 2 有「副本被本地改过」/ 3 无法检查
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

# 忽略项：Python 缓存与 skill 运行产物。不忽略会恒红——实证：安装副本里的
# __pycache__/*.pyc 会被 Python 运行时重新生成，mtime 必然晚于 installed_at，
# 于是每次安装都被判「副本被本地改过」而中止。恒红的闸门等于没有闸门。
# 运行产物那几项依据仓库 .gitignore 的「skill 运行产物（不入库）」声明。
IGNORE_DIRS = {"__pycache__", ".pytest_cache", "drafts", "xiaohongshu"}
IGNORE_SUFFIXES = (".pyc", ".pyo")
IGNORE_NAMES = {".DS_Store", "preview.html", "review.html", ".nbdpsy-skills-install.json"}

MARKER = ".nbdpsy-skills-install.json"

# 分类键，同时决定输出顺序（危险的排最前）
LOCAL_EDIT = "local_edit"
SRC_NEWER = "src_newer"
ONLY_SRC = "only_src"
ONLY_DEST = "only_dest"
UNKNOWN = "unknown"

LABELS = {
    LOCAL_EDIT: "⚠ 副本被本地改过",
    SRC_NEWER: "真源更新",
    ONLY_SRC: "仅真源有",
    ONLY_DEST: "仅副本有",
    UNKNOWN: "? 有差异但无法判断归属",
}
HINTS = {
    LOCAL_EDIT: "副本里有真源没有的内容，下次安装会 rm -rf 销毁它——先搬回真源，或用 --force 明确覆盖",
    SRC_NEWER: "正常：跑一次安装即可（含副本是旧同步的情况，装它只会前进）",
    ONLY_SRC: "副本缺文件，跑一次安装即可",
    ONLY_DEST: "真源没有这些文件，安装时会被清掉",
    UNKNOWN: "marker 缺失或损坏，判不出是真源更新还是副本被改",
}


def ignored(rel: str) -> bool:
    parts = rel.split(os.sep)
    if any(p in IGNORE_DIRS for p in parts):
        return True
    name = parts[-1]
    return name in IGNORE_NAMES or name.endswith(IGNORE_SUFFIXES)


def list_files(root: str) -> set[str]:
    """相对 root 的文件路径集合（跳过忽略项，不跟随软链）。"""
    out: set[str] = set()
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            if not ignored(rel):
                out.add(rel)
    return out


def sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def same_content(a: str, b: str) -> bool:
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
    except OSError:
        return False  # 读不到就当不同，宁可多报也不漏报
    ha, hb = sha256(a), sha256(b)
    return ha is not None and ha == hb


def blob_sha(path: str) -> str | None:
    """算 git blob 对象名（sha1 of "blob <len>\\0" + 内容），不调 git。"""
    try:
        size = os.path.getsize(path)
        h = hashlib.sha1()
        h.update(("blob %d\0" % size).encode())
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" in fh.read(8192)
    except OSError:
        return True


class GitHistory:
    """查真源里某个路径出现过的全部历史 blob。

    用途：副本 mtime 晚于 installed_at 只说明「它被写过」，而真正要问的是
    「副本里有没有真源不存在的内容」——那才是 rm -rf 会销毁的东西。
    副本内容命中该路径的任一历史版本 ⇒ 它是某次旧的手工同步，装它只会前进。
    """

    def __init__(self, src: str) -> None:
        self.src = src
        self.cache: dict[str, set] = {}
        self.ok = False
        self.shallow = False
        self.reason = ""
        try:
            if subprocess.run(["git", "-C", src, "rev-parse", "--git-dir"],
                              capture_output=True).returncode != 0:
                self.reason = "真源不是 git 仓库"
                return
            out = subprocess.run(["git", "-C", src, "rev-parse", "--is-shallow-repository"],
                                 capture_output=True, text=True)
            self.shallow = out.stdout.strip() == "true"
            if self.shallow:
                self.reason = "真源是浅克隆，历史不全"
            self.ok = True
        except (OSError, subprocess.SubprocessError) as exc:
            self.reason = f"git 不可用（{exc}）"

    def blobs_for(self, rel: str) -> set:
        """该路径出现过的全部 blob 对象名。两次进程调用，只对需要的文件跑。"""
        if rel in self.cache:
            return self.cache[rel]
        result: set = set()
        try:
            commits = subprocess.run(["git", "-C", self.src, "rev-list", "--all", "--", rel],
                                     capture_output=True, text=True, timeout=30)
            specs = "".join(f"{c}:{rel}\n" for c in commits.stdout.split())
            if specs:
                batch = subprocess.run(
                    ["git", "-C", self.src, "cat-file", "--batch-check=%(objectname)"],
                    input=specs, capture_output=True, text=True, timeout=30)
                result = {ln.strip() for ln in batch.stdout.splitlines()
                          if len(ln.strip()) == 40 and " " not in ln.strip()}
        except (OSError, subprocess.SubprocessError):
            pass
        self.cache[rel] = result
        return result


def dest_has_own_lines(src_file: str, dest_file: str) -> bool | None:
    """副本里是否存在真源没有的行。None = 二进制或读不了，判不了。

    这是「安装会销毁什么」的直接回答：没有独有行 ⇒ 真源已包含副本全部内容。
    比 blob 历史弱（行集合忽略顺序），只在 blob 查不到时兜底。
    """
    if is_binary(src_file) or is_binary(dest_file):
        return None
    try:
        with open(src_file, "r", encoding="utf-8", errors="replace") as fh:
            src_lines = set(fh.read().splitlines())
        with open(dest_file, "r", encoding="utf-8", errors="replace") as fh:
            dest_lines = set(fh.read().splitlines())
    except OSError:
        return None
    return bool(dest_lines - src_lines)


def read_marker(dest: str) -> dict:
    """读安装点 marker。返回 {ok, version, commit, installed_at, ts, reason}。"""
    path = os.path.join(dest, MARKER)
    if not os.path.exists(path):
        return {"ok": False, "reason": "marker 缺失"}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return {"ok": False, "reason": f"marker 损坏（{exc}）"}
    raw = str(data.get("installed_at", "") or "")
    info = {
        "version": str(data.get("version", "unknown")),
        "commit": str(data.get("commit", "unknown")),
        "installed_at": raw or "unknown",
        "source": str(data.get("source", "unknown")),
    }
    if not raw or raw == "unknown":
        info.update(ok=False, reason="marker 里 installed_at 为 unknown")
        return info
    try:
        info["ts"] = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        info.update(ok=False, reason=f"marker 里 installed_at 无法解析（{raw}）")
        return info
    info["ok"] = True
    return info


def classify(src_root: str, dest_root: str, skills: list[str], marker: dict,
             hist: "GitHistory") -> dict:
    """逐 skill 逐文件比对，返回 {分类: [(skill, rel, 证据), ...]} 与一致 skill 数。"""
    buckets = {k: [] for k in (LOCAL_EDIT, SRC_NEWER, ONLY_SRC, ONLY_DEST, UNKNOWN)}
    clean_skills = []
    missing_skills = []
    ts = marker.get("ts")

    def mtime_late(path: str) -> bool:
        # 整数秒 floor 比较：cp -R 与随后的 write_marker 常落在同一秒，
        # 用 > 而非 >= 才不会把刚装好的文件误判成被改过。
        if ts is None:
            return False
        try:
            return int(os.stat(path).st_mtime) > int(ts)
        except OSError:
            return False

    def judge(src_file: str, dest_file: str, repo_rel: str):
        """mtime 初筛命中后的二次判定，返回 (分类, 证据)。repo_rel 是相对真源根的路径。

        mtime 只回答「被写过吗」，是代理指标；真正要问的是「副本里有没有真源
        不存在的内容」。两级兜底：命中历史 blob（硬证据）→ 无独有行（软证据）。
        """
        if hist.ok:
            sha = blob_sha(dest_file)
            if sha and sha in hist.blobs_for(repo_rel):
                return SRC_NEWER, "副本是旧同步，命中真源历史版本"
        own = dest_has_own_lines(src_file, dest_file)
        if own is False:
            return SRC_NEWER, "副本内容是真源子集，无独有行"
        if own is None:
            return LOCAL_EDIT, ("二进制文件，比不了行；" +
                                ("历史里查不到这份内容" if hist.ok else hist.reason))
        return LOCAL_EDIT, ("副本有真源没有的行" if hist.ok
                            else f"副本有真源没有的行（{hist.reason}）")

    for s in skills:
        src_dir = os.path.join(src_root, s)
        dest_dir = os.path.join(dest_root, s)
        if not os.path.exists(dest_dir):
            missing_skills.append(s)
            continue
        src_files = list_files(src_dir)
        dest_files = list_files(dest_dir)
        dirty = False

        for rel in sorted(src_files - dest_files):
            buckets[ONLY_SRC].append((s, rel, ""))
            dirty = True
        for rel in sorted(dest_files - src_files):
            # 真源没有这个文件，谈不上「是旧同步」——只能靠 mtime
            if not marker.get("ok"):
                buckets[UNKNOWN].append((s, rel, ""))
            elif mtime_late(os.path.join(dest_dir, rel)):
                buckets[LOCAL_EDIT].append((s, rel, "真源没有此文件，按 mtime 判"))
            else:
                buckets[ONLY_DEST].append((s, rel, ""))
            dirty = True
        for rel in sorted(src_files & dest_files):
            src_file, dst = os.path.join(src_dir, rel), os.path.join(dest_dir, rel)
            if same_content(src_file, dst):
                continue
            dirty = True
            if not marker.get("ok"):
                buckets[UNKNOWN].append((s, rel, ""))
            elif not mtime_late(dst):
                buckets[SRC_NEWER].append((s, rel, ""))
            else:
                key, why = judge(src_file, dst, os.path.join(s, rel))
                buckets[key].append((s, rel, why))

        if not dirty:
            clean_skills.append(s)

    return {"buckets": buckets, "clean": clean_skills, "missing": missing_skills}


def short(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def report_install_points(points: list[tuple[str, str]], codex_dir: str, skills: list[str]) -> None:
    print("━━━ 安装点 ━━━")
    for dest, label in points:
        line = f"  {short(dest):<24}"
        if not os.path.isdir(dest):
            print(line + "不存在")
            continue
        kind = "软链目录 → " + os.path.realpath(dest) if os.path.islink(dest) else "目录"
        m = read_marker(dest)
        if "version" in m:
            stamp = f"v{m['version']} / {m['commit']} / {m['installed_at']} / {m['source']}"
        else:
            stamp = m.get("reason", "marker 缺失")
        print(f"{line}{kind}（{label}）  {stamp}")

    line = f"  {short(codex_dir):<24}"
    if not os.path.isdir(codex_dir):
        print(line + "不存在")
        return
    ok = broken = plain = 0
    for s in skills:
        p = os.path.join(codex_dir, s)
        if os.path.islink(p):
            ok += 1 if os.path.exists(p) else 0
            broken += 0 if os.path.exists(p) else 1
        elif os.path.exists(p):
            plain += 1
    bits = [f"{ok}/{len(skills)} 条软链有效"]
    if broken:
        bits.append(f"{broken} 条断链")
    if plain:
        bits.append(f"{plain} 个实体目录（本该是软链）")
    print(f"{line}软链集 → ~/.agents/skills（Codex 旧路径）  {', '.join(bits)}")
    print("    ⚠️ 软链指向 ~/.agents/skills，那边的差异只在上一段报，本段不重复")


def main() -> int:
    ap = argparse.ArgumentParser(description="NBDpsy skills 安装漂移检查")
    ap.add_argument("--src", required=True, help="真源仓库根目录")
    ap.add_argument("--skills", required=True, help="skill 名，逗号分隔")
    ap.add_argument("--dest", action="append", default=[], metavar="路径=标签",
                    help="要逐文件比对的安装点，可重复")
    ap.add_argument("--overview", action="append", default=[], metavar="路径=标签",
                    help="只在概览里报存在性、不逐文件比对的安装点，可重复")
    ap.add_argument("--codex-dir", default=os.path.join(
        os.environ.get("CODEX_HOME", os.path.join(os.path.expanduser("~"), ".codex")), "skills"))
    ap.add_argument("--gate", action="store_true",
                    help="闸门模式：只在有「副本被本地改过」时刷屏，其余保持安静")
    ap.add_argument("--max-list", type=int, default=12, help="每类最多列几个文件")
    args = ap.parse_args()

    skills = [s for s in args.skills.split(",") if s]

    def parse(specs):
        out = []
        for spec in specs:
            path, _, label = spec.partition("=")
            out.append((os.path.expanduser(path), label or path))
        return out

    points = parse(args.dest)
    if not points:
        print("！没有给出任何安装点", file=sys.stderr)
        return 3
    if not all(os.path.isdir(os.path.join(args.src, s)) for s in skills):
        print(f"！真源不完整：{short(args.src)} 下缺 skill 目录，无法比对", file=sys.stderr)
        return 3

    hist = GitHistory(args.src)
    if not args.gate:
        # 概览覆盖全部安装点（含本次不比对的），逐文件比对只做 --dest 指定的
        seen = {p for p, _ in points}
        overview = points + [x for x in parse(args.overview) if x[0] not in seen]
        report_install_points(overview, args.codex_dir, skills)
        if not hist.ok:
            print(f"  ! {hist.reason}——查不了「副本是不是旧同步」，"
                  f"mtime 晚于 marker 的一律按被本地改过报")
        elif hist.shallow:
            print(f"  ! {hist.reason}——「副本是旧同步」可能查不到，结论偏严")
        print()

    worst = 0          # 0 一致 / 1 有差异 / 2 有本地改动
    checked_any = False
    any_unknown = False
    for dest, label in points:
        if not os.path.isdir(dest):
            if not args.gate:
                print(f"━━━ {label}（{short(dest)}）━━━\n  安装点不存在，跳过\n")
            continue
        checked_any = True
        marker = read_marker(dest)
        res = classify(args.src, dest, skills, marker, hist)
        buckets, clean, missing = res["buckets"], res["clean"], res["missing"]
        has_local = bool(buckets[LOCAL_EDIT])
        any_unknown = any_unknown or bool(buckets[UNKNOWN])
        total_diff = sum(len(v) for v in buckets.values()) + len(missing)

        if has_local:
            worst = 2
        elif total_diff and worst < 1:
            worst = 1
        if args.gate and not has_local:
            continue

        print(f"━━━ {label}（{short(dest)}）━━━")
        if not marker.get("ok"):
            print(f"  ! {marker.get('reason')}——无法判断副本是否被本地改过，"
                  f"下面的差异不再区分「真源更新」与「副本被改」")
        if missing:
            print(f"  未安装的 skill（共 {len(missing)} 个）: {', '.join(missing)}")
        for key in (LOCAL_EDIT, UNKNOWN, SRC_NEWER, ONLY_SRC, ONLY_DEST):
            items = buckets[key]
            if not items:
                continue
            print(f"  {LABELS[key]}（{len(items)} 个文件）— {HINTS[key]}")
            # 带判定理由的排前面：它们是「我判成这样、理由是X」，被截断埋掉就白判了
            for s, rel, why in sorted(items, key=lambda x: not x[2])[:args.max_list]:
                print(f"      {s}/{rel}" + (f"    ← {why}" if why else ""))
            if len(items) > args.max_list:
                print(f"      …… 另有 {len(items) - args.max_list} 个")
        if total_diff == 0:
            print(f"  ✓ {len(clean)} 个 skill 逐文件一致")
        else:
            print(f"  小结：{len(skills)} 个 skill 中 {len(clean)} 个逐文件一致，"
                  f"{len(skills) - len(clean)} 个有差异")
        print()

    if not checked_any:
        # 闸门模式下这就是全新安装的正常起点，别拿它刷屏
        if not args.gate:
            print("！所有安装点都不存在，没什么可比对的（先跑一次安装）", file=sys.stderr)
        return 3

    if args.gate:
        if worst == 2:
            print("↑ 安装会 rm -rf 覆盖上面这些文件。确认要丢弃就加 --force 重跑。")
        return worst

    print(f"（已忽略：{'、'.join(sorted(IGNORE_DIRS))} 目录，"
          f"{'、'.join(IGNORE_SUFFIXES)} 文件，{'、'.join(sorted(IGNORE_NAMES))}）")
    if worst == 0:
        print(f"✓ 全部安装点与真源逐文件一致（{len(skills)} 个 skill）")
    elif worst == 1 and any_unknown:
        # marker 判不了的时候别嘴硬说「没有本地改动」——判不出就是判不出
        print("→ 有差异。marker 缺失/损坏，判不出其中有没有「副本被本地改过」；"
              "要保险就先把安装副本另存一份再跑 ./install.sh")
    elif worst == 1:
        print("→ 有差异，但没有「副本被本地改过」：跑一次 ./install.sh 即可对齐")
    else:
        print("⚠ 有「副本被本地改过」的文件：直接安装会无声销毁它们，"
              "先把改动搬回真源，或确认可丢弃后 ./install.sh --force")
    return worst


if __name__ == "__main__":
    sys.exit(main())

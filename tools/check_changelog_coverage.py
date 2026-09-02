#!/usr/bin/env python3
"""**发版前置闸：自上一版以来的每个提交，都必须在 CHANGELOG.md 里留下 sha。**

🩸 起因（佰亿助理 2026-09-02 派单）：v2.42.0 之后的 7 个提交，CHANGELOG **一个都没记**，
其中 `1998975` 是 feat（服务号群发/删除坐标制），静默积压五天，直到发 v2.43.0 才被人发现。
既有的 `test_version_consistency.py` 守的是「版本号别被写回旧号」，
**管不了「提交有没有被记账」**——两件事之间原本没有任何东西在拦。

## 这道闸守什么、明确不守什么

- 守**漏记**：范围内每个提交的 sha 必须能在 CHANGELOG.md 里找到，或已显式豁免。
- ⛔ **不守记账质量**：sha 写进去了、描述却是「杂项修改」，本闸照样放行。它拦的是「一个字都没写」。
- ⛔ **不守 `[no-changelog]` 被滥用**：谁都能给提交打豁免标。本闸把豁免逐条**打印出来**，
  让它至少是**可见**的，⛔ 不是可拦的。
- ⛔ **不守未提交的工作区改动**：只看提交历史。

## 🔴 为什么按 sha 判，⛔ 不按提交类型白名单

派单原话：**豁免必须显式写在提交信息里**。⛔ 不按 `docs`/`chore` 类型白名单——
这次漏掉的六个里就有 `test(security)` 和 `fix(compliance)`，
**类型标签说明不了这次改动实不实质**。sha 是唯一机器可判、且写的时候没法含糊的锚点。

## 🔴 release 提交的豁免是**带条件**的（⛔ 不是「是发版提交就放过」）

发版提交自己的 sha 要等 `git commit` 之后才存在，而 CHANGELOG 是在 commit **之前**写的
⇒ 它不可能自己记自己的账，只能豁免。但**「是 release 提交」不足以豁免**：
实查 `76b558f release: v2.42.0` 除三个发版文件外，**还夹带了 7 个实质文件**
（`article_ops.py`、`schedule_ops.py`、两个 SKILL.md、两份测试……）。
无条件豁免 release 提交 ⇒ 谁把实质改动塞进发版提交谁就白嫖，**且没有任何人会发现**。

⇒ 豁免条件收紧为**改动文件集 ⊆ 三个发版文件**（见 `发版文件`）。夹带一个别的文件，
就照样要求记账。这是**内容判据**，⛔ 不是类型白名单。

## 🔴 基线为什么这么定

基线 = 沿主干回溯、第一个「不是 HEAD、是 release 提交、**且其版本节仍在 CHANGELOG 里**」的提交。

最后那个条件治的是**被吸收的中间发版**：v2.42.1 发过版（`55258c9` 在主干上），
但 v2.43.0 把 2.42.1 那一节合并掉了、CHANGELOG 里已无此节。
若只认「上一个 release 提交」，基线会落在 `55258c9`，范围只剩发版提交自己
⇒ **闸绿，却一个实质提交都没验到**——那种绿和真绿长得一模一样。
认「CHANGELOG 里仍独立成节的上一版」，被吸收的发版自动跳过，它覆盖的提交重新纳入本次范围。

⛔ 不用「CHANGELOG 里最大的版本号」当基线：发版时顶部刚写上本次的号，
那样算出的基线**就是本次发版自己**，范围恒空 ⇒ 闸恒绿。
⛔ 不用 git tag：本仓 tag 只维护到 v1.17.0，当前已 2.4x，早就不是发版凭据了。

## 用法

    python3 tools/check_changelog_coverage.py

发版前跑（写完 CHANGELOG、commit 之前，或 commit 完 release 之后都可以，两个时机同一套判据）。
非零退出即拦住发版。`tests/test_changelog_coverage.py` 把它挂进了 pytest。
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"

EXEMPT_MARK = "[no-changelog]"
RELEASE_PREFIX = "release:"

# 发版提交「只动了这些」才够格豁免。多一个文件就是夹带，要求记账。
发版文件 = {"CHANGELOG.md",
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json"}

# CHANGELOG 里的 sha 引用：**独立的**十六进制词，7～40 位。
# 🔴 下限 7 是 git 短 sha 的默认长度，⛔ 不能再放低——`2026`、`3bee` 这种四位串正文里遍地都是，
#    放低等于随便一段话都能算"记账"，闸恒绿。
SHA_WORD_RE = re.compile(r"\b[0-9a-f]{7,40}\b")

# CHANGELOG 版本节标题，与 test_version_consistency.py 同一套写法：`## [2.43.0] — 2026-09-02`
版本节_RE = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]", re.M)
# 发版提交信息里的版本号：`release: v2.43.0（…）` / `release: v1.55.2 服务号收尾…`
发版号_RE = re.compile(r"^release:\s*v?(\d+\.\d+\.\d+)")


class 闸门失败(Exception):
    """任何一处判不出来都必须炸，⛔ 不许静默当通过——那是恒绿的头号来源。"""


def _git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise 闸门失败(f"`git {' '.join(args)}` 失败（退出码 {r.returncode}）：{r.stderr.strip()}")
    return r.stdout


def 主干提交(限制: int = 400) -> list[tuple[str, str]]:
    out = _git("log", "--first-parent", "--format=%H%x1f%s", "-n", str(限制))
    提交 = []
    for 行 in out.splitlines():
        sha, _, 标题 = 行.partition("\x1f")
        if sha:
            提交.append((sha, 标题))
    return 提交


def 改动文件(sha: str) -> set[str]:
    return set(_git("show", "--name-only", "--format=", sha).split())


def 是纯发版提交(sha: str, 标题: str) -> bool:
    """只动了三个发版文件的 release 提交。夹带任何别的文件都不算。"""
    if not 标题.startswith(RELEASE_PREFIX):
        return False
    文件 = 改动文件(sha)
    return bool(文件) and 文件 <= 发版文件


def 读CHANGELOG() -> str:
    if not CHANGELOG.is_file():
        raise 闸门失败(f"读不到 {CHANGELOG} ⇒ 无从判定记账，按红处理。")
    return CHANGELOG.read_text(encoding="utf-8")


def 定位基线(正文: str) -> tuple[str, str]:
    """回溯找基线：不是 HEAD、是 release 提交、且其版本节仍在 CHANGELOG 里。"""
    在册版本 = set(版本节_RE.findall(正文))
    if not 在册版本:
        raise 闸门失败("CHANGELOG.md 里一个 `## [x.y.z]` 版本节都没有 ⇒ 基线失去锚点。")

    head = _git("rev-parse", "HEAD").strip()
    跳过的 = []
    for sha, 标题 in 主干提交():
        if sha == head or not 标题.startswith(RELEASE_PREFIX):
            continue
        m = 发版号_RE.match(标题)
        if not m:
            跳过的.append(f"{sha[:7]} 提交信息里解析不出版本号：{标题}")
            continue
        if m.group(1) not in 在册版本:
            跳过的.append(f"{sha[:7]} v{m.group(1)} 的版本节已不在 CHANGELOG 里（被后续发版吸收）")
            continue
        for 条 in 跳过的:
            print(f"  ↷ 跳过 {条}")
        return sha, 标题

    详情 = "；".join(跳过的) if 跳过的 else "一个 release 提交都没遇到"
    raise 闸门失败(
        f"沿主干回溯 400 个提交，找不到「版本节仍在 CHANGELOG 里」的发版提交（{详情}）"
        " ⇒ 本闸失去判据，按红处理，⛔ 不按「没发现问题」放行。")


def 已记账(全sha: str, sha词: set[str]) -> bool:
    """CHANGELOG 里存在某个独立十六进制词，是这个提交完整 sha 的前缀。

    🔴 **为什么是「提取独立词 + 前缀匹配」，⛔ 不是「拿短 sha 去全文搜子串」**：
    CHANGELOG 正文里有热线电话 `4001619995`（出现 18 次）。用子串搜的话，
    任何以 `4001619` 开头的短 sha 都会被这串电话号误命中 ⇒ 那个提交白嫖记账，**没人会发现**。
    先提取完整独立词（拿到的是 10 位的 `4001619995`，⛔ 不是 7 位的 `4001619`），
    再要求提交全 sha 以该词为前缀 ⇒ 要误命中，得有个提交 sha 恰好以 `4001619995` 开头。
    顺带也解决了「CHANGELOG 写 40 位全 sha、这边按 7 位短 sha 比对」对不上的情况。
    """
    return any(全sha.startswith(w) for w in sha词)


def 跑闸() -> int:
    正文 = 读CHANGELOG()
    基线sha, 基线标题 = 定位基线(正文)
    sha词 = set(SHA_WORD_RE.findall(正文))
    提交 = []
    for 行 in _git("log", "--first-parent", "--format=%H%x1f%s",
                   f"{基线sha}..HEAD").splitlines():
        sha, _, 标题 = 行.partition("\x1f")
        if sha:
            提交.append((sha, 标题))

    print(f"  基线：{基线sha[:7]} {基线标题}")
    print(f"  范围：{基线sha[:7]}..HEAD（--first-parent），{len(提交)} 个提交\n")

    # 🔴 范围为空必须红。发版时至少有本次发版提交自己；空范围只可能是基线算错，
    #    而「0 个提交、全部合规」的外显跟真全绿一模一样 ⇒ 这是最像成功的那种失败。
    if not 提交:
        print(f"❌ 范围内 0 个提交 —— 基线 {基线sha[:7]} 算成了 HEAD 本身或其后继。"
              f"\n   闸没有验到任何东西，⛔ 这不是「通过」。")
        return 1

    漏记, 豁免, 记了 = [], [], []
    for sha, 标题 in 提交:
        if EXEMPT_MARK in 标题:
            豁免.append((sha, 标题, f"提交信息显式写了 {EXEMPT_MARK}"))
        elif 是纯发版提交(sha, 标题):
            豁免.append((sha, 标题, "纯发版提交（只动三个发版文件）：sha 在写 CHANGELOG 时尚不存在"))
        elif 已记账(sha, sha词):
            记了.append((sha, 标题))
        else:
            漏记.append((sha, 标题))

    for sha, 标题 in 记了:
        print(f"  ✅ {sha[:7]} {标题}")
    for sha, 标题, 因由 in 豁免:
        print(f"  ⚪ {sha[:7]} {标题}")
        print(f"       └─ 豁免：{因由}")

    if 漏记:
        print(f"\n❌ {len(漏记)} 个提交没在 CHANGELOG.md 里记账：\n")
        for sha, 标题 in 漏记:
            print(f"   · {sha[:7]}  {标题}")
        print(f"""
⇒ 两条路（⛔ 没有第三条）：
   ① 把这些改动写进 CHANGELOG.md 本次发版那一节，**并带上短 sha**（如 `{漏记[0][0][:7]}`）；
   ② 确认它确实不必记账，就把 `{EXEMPT_MARK}` 写进**那个提交自己的提交信息**里。

🔑 ⛔ 别改本脚本的判据来放行。拦的就是「v2.42.0 后 7 个提交零记账、feat 静默积压五天」
   这件事——判据一放宽，下次积压的还是同一批东西。""")
        return 1

    print(f"\n✅ 全部记账：{len(记了)} 个已记 + {len(豁免)} 个豁免 = {len(提交)} 个。")
    if not 记了:
        # 「全是豁免」的绿，和「验过一批实质提交」的绿，退出码一样、外观也像 ⇒ 必须说破。
        print("⚠️ 但**没有一个实质提交被验到**（范围内全是豁免）——"
              "这是空验的绿，⛔ 别当成「记账没问题」。请确认基线是否算对。")
    if 豁免:
        print("⚠️ 豁免是「显式声明」⛔ 不是「审核通过」——上面每条请自己再看一眼够不够格。")
    print(适用边界())
    return 0


def 适用边界() -> str:
    """绿灯时固定打印的适用边界。⛔ 让绿看起来比它实际验到的更强，是这道闸最可能骗人的地方。

    🔴 **两层的行为不一样，⛔ 别混**（佰亿助理 2026-09-02 裁定「不硬堵、把限定写进输出」）：
      · **本脚本**任何时候跑都真跑，⛔ 不 skip；
      · **pytest 那层**只在 HEAD 已是 release 提交时生效，其余 skip。
    ⇒ 真正的漏法是「只跑 pytest、且在 commit release **之前**跑」——那样这道闸一次都不会真的跑，
      而测试报告上是一片绿。所以发版前必须在 commit release **之后**手动跑一次本脚本。
    """
    return """
────────────────────────────────────────────────────────────
⚠️ 这道闸的适用边界（绿灯不比这句话更强）：
   · 本脚本任何时候跑都真跑，⛔ 不会 skip。
   · 但挂在 pytest 里的那条判据**只在 HEAD 已是 release 提交时才生效**，其余情况 skip。
   ⇒ 只跑 `pytest`、且在 commit release **之前**跑的话，这道闸**一次都不会真的跑**，
     而测试报告上看起来是一片绿。
   ⇒ **发版前请在 commit release 之后，再手动跑一次本脚本。**
   另：本闸只管「sha 有没有出现在 CHANGELOG 里」，⛔ 不管记账写得好不好，
   也⛔ 不审 `[no-changelog]` 用得对不对。其余已知缺口见 README 发版规范那节。
────────────────────────────────────────────────────────────"""


def main() -> int:
    argparse.ArgumentParser(
        description="发版前置闸：自上一版以来每个提交都必须在 CHANGELOG.md 里留下 sha").parse_args()
    try:
        return 跑闸()
    except 闸门失败 as e:
        print(f"❌ 闸门无法判定：{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

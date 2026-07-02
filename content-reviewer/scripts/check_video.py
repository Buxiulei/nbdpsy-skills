#!/usr/bin/env python3
"""审查 text-to-video 工作目录的短视频成片：时长合规 + 字幕时间轴健全 + 成片完整。

工作目录约定（对齐 text-to-video 产线真实命名）：
  shot-NN.mp4              每镜成片，两位序号 01 起，编号断档记入 missing
  narr-NN.mp3              每镜旁白，缺失记入 missing
  narr-NN.mp3.cues.json    tts_gen --timed 的字幕时间轴（主命名），
                           兜底旧名 narr-NN.cues.json；缺失记入 cues_issues
  final.mp4                最终成片，缺失即整体 FAIL

检查项：
  1. 每镜 ffprobe 实测时长 ∈ [4,15] ±0.5s（即 [3.5, 15.5]s）
  2. cues 每镜单调递增（后一句 start 不早于前一句 end），且末句 end ≤ 旁白实测时长 +0.2s
  3. final.mp4 实测总时长 ≈ Σ每镜时长 ±10%
  4. 总时长 ∈ [--total-min, --total-max]（默认 30–180s）

输出 JSON（stdout 只有 JSON，进度走 stderr）：
  {"shots": N, "duration_violations": [...], "cues_issues": [...],
   "missing": [...], "total_sec": T, "final_exists": bool, "ok": bool}
exit：0=全部通过；1=任一检查未过；2=参数/目录错误

用法：
  python3 check_video.py --workdir DIR [--total-min 30 --total-max 180]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SHOT_MIN = 4.0        # 每镜时长下限（秒）
SHOT_MAX = 15.0       # 每镜时长上限（秒）
SHOT_TOL = 0.5        # 每镜时长容差 ±0.5s
CUES_TAIL_TOL = 0.2   # 末句 end 允许超出旁白实测时长的余量（秒）
FINAL_SUM_TOL = 0.10  # final 总时长与 Σ每镜时长 的相对容差 ±10%
EPS = 1e-3            # cues 单调判定的浮点余量


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def probe_duration(path: Path) -> float:
    """ffprobe 实测媒体时长（秒）。失败抛异常（审查脚本不静默兜底）。"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def _find_cues(workdir: Path, nn: str) -> Path | None:
    """cues 探测：主命名 narr-NN.mp3.cues.json → 兜底旧名 narr-NN.cues.json。"""
    primary = workdir / f"narr-{nn}.mp3.cues.json"
    if primary.is_file():
        return primary
    fallback = workdir / f"narr-{nn}.cues.json"
    if fallback.is_file():
        return fallback
    return None


def _load_cues(path: Path) -> list[dict]:
    """读取 cues 列表。兼容 tts_gen 的 {"duration","cues"} 与裸数组两种形态。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        cues = data.get("cues")
    else:
        cues = data
    if not isinstance(cues, list):
        raise ValueError("cues 不是数组")
    return cues


def _check_cues(nn: str, cues_path: Path, narr_path: Path,
                cues_issues: list[dict]) -> None:
    """cues 单调 + 末句不超旁白时长。narr_path 缺失时跳过末句检查（缺件已另行上报）。"""
    try:
        cues = _load_cues(cues_path)
    except Exception as e:  # noqa: BLE001 — 结构坏掉必须上报，不静默
        cues_issues.append({"shot": nn, "type": "cues_unreadable",
                            "detail": f"{cues_path.name} 解析失败: {e}"})
        return
    if not cues:
        cues_issues.append({"shot": nn, "type": "cues_empty",
                            "detail": f"{cues_path.name} 无字幕条"})
        return

    prev_end = 0.0
    for i, cue in enumerate(cues):
        try:
            start, end = float(cue["start"]), float(cue["end"])
        except (KeyError, TypeError, ValueError) as e:
            cues_issues.append({"shot": nn, "type": "cues_unreadable",
                                "detail": f"第{i}条缺 start/end: {e}"})
            return
        if end < start - EPS or start < prev_end - EPS:
            cues_issues.append({
                "shot": nn, "type": "not_monotonic",
                "detail": f"第{i}条 [{start:.3f},{end:.3f}] 与上句 end={prev_end:.3f} 交叠或倒退"})
            return
        prev_end = max(prev_end, end)

    if narr_path.is_file():
        narr_dur = probe_duration(narr_path)
        if prev_end > narr_dur + CUES_TAIL_TOL:
            cues_issues.append({
                "shot": nn, "type": "tail_exceeds_narration",
                "detail": f"末句 end={prev_end:.3f}s > 旁白 {narr_dur:.3f}s +{CUES_TAIL_TOL}s"})


def run(workdir: Path, *, total_min: float, total_max: float) -> dict:
    shot_files: dict[int, Path] = {}
    for f in workdir.glob("shot-*.mp4"):
        m = re.fullmatch(r"shot-(\d+)\.mp4", f.name)
        if m:
            shot_files[int(m.group(1))] = f

    duration_violations: list[dict] = []
    cues_issues: list[dict] = []
    missing: list[str] = []
    sum_dur = 0.0

    max_idx = max(shot_files) if shot_files else 0
    for idx in range(1, max_idx + 1):
        nn = f"{idx:02d}"
        shot = shot_files.get(idx)
        if shot is None:
            missing.append(f"shot-{nn}.mp4")
            _err(f"  镜{nn} ✗ 缺 shot-{nn}.mp4（编号断档）")
            continue

        try:
            dur = probe_duration(shot)
        except Exception as e:  # noqa: BLE001 — 探测不了的镜必定不合格
            duration_violations.append({"shot": nn, "file": shot.name, "duration": None,
                                        "expect": "ffprobe 可实测",
                                        "detail": f"ffprobe 失败: {e}"})
            _err(f"  镜{nn} ✗ ffprobe 失败: {e}")
            continue
        sum_dur += dur

        if not (SHOT_MIN - SHOT_TOL <= dur <= SHOT_MAX + SHOT_TOL):
            duration_violations.append({
                "shot": nn, "file": shot.name, "duration": round(dur, 3),
                "expect": f"[{SHOT_MIN - SHOT_TOL},{SHOT_MAX + SHOT_TOL}]s"})

        narr = workdir / f"narr-{nn}.mp3"
        if not narr.is_file():
            missing.append(narr.name)

        cues_path = _find_cues(workdir, nn)
        if cues_path is None:
            cues_issues.append({"shot": nn, "type": "cues_missing",
                                "detail": f"缺 narr-{nn}.mp3.cues.json（含旧名兜底均未找到），"
                                          f"字幕同步无法确定性验证"})
        else:
            _check_cues(nn, cues_path, narr, cues_issues)

        _err(f"  镜{nn} 实测 {dur:.2f}s")

    final = workdir / "final.mp4"
    final_exists = final.is_file()
    if final_exists:
        total_sec = probe_duration(final)
        if shot_files and sum_dur > 0 and abs(total_sec - sum_dur) > FINAL_SUM_TOL * sum_dur:
            duration_violations.append({
                "shot": "final", "file": "final.mp4", "duration": round(total_sec, 3),
                "expect": f"Σ每镜={sum_dur:.2f}s ±{int(FINAL_SUM_TOL * 100)}%"})
    else:
        total_sec = sum_dur
        _err("  ✗ 缺 final.mp4")

    if not (total_min <= total_sec <= total_max):
        duration_violations.append({
            "shot": "total", "duration": round(total_sec, 3),
            "expect": f"[{total_min},{total_max}]s"})

    ok = (final_exists and bool(shot_files)
          and not duration_violations and not cues_issues and not missing)
    return {
        "shots": len(shot_files),
        "duration_violations": duration_violations,
        "cues_issues": cues_issues,
        "missing": missing,
        "total_sec": round(total_sec, 3),
        "final_exists": final_exists,
        "ok": ok,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="短视频成片确定性检查：每镜时长/字幕时间轴/总时长")
    ap.add_argument("--workdir", required=True,
                    help="视频工作目录（含 shot-NN.mp4 / narr-NN.mp3 / final.mp4 等）")
    ap.add_argument("--total-min", type=float, default=30.0, help="总时长下限秒（默认 30）")
    ap.add_argument("--total-max", type=float, default=180.0, help="总时长上限秒（默认 180）")
    a = ap.parse_args()

    workdir = Path(a.workdir)
    if not workdir.is_dir():
        print(json.dumps({"error": f"目录不存在: {workdir}"}, ensure_ascii=False))
        _err(f"Error: 目录不存在: {workdir}")
        sys.exit(2)

    report = run(workdir, total_min=a.total_min, total_max=a.total_max)
    print(json.dumps(report, ensure_ascii=False))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()

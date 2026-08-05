#!/usr/bin/env python3
"""把「一次生成的多镜头长片段」按旁白边界切成 shot-NN.mp4 —— 电影化产线的对齐层。

**产线为什么长这样**：即梦单次能生成 4–30 秒，且支持时间轴格式提示词
（`0-3.6秒画面：全景… / 3.6-6.8秒画面：特写…`），**模型在一个片段内部完成切镜**。
这比「一刀一次提交再本地拼」好得多——同一次生成里人物、光线、风格天然一致，
镜间硬切也由模型处理，不会有拼接痕迹。所以：

    一个 segment = 一次生成（≤30s，内含 5–8 个镜头）
    一个 beat    = 一条旁白（segment 里连续的一段时间）

本脚本做的就是把 segment-NN.mp4 按它覆盖的 beats 时长依次切开，产出 shot-{beat}.mp4。
切完之后 build_manifest.py / compose_video.py **一行都不用改**——它们看到的仍是老契约
「一条旁白配一段画面」。切点落在模型的镜头中间也无所谓：切开再顺序拼回去，视觉上连续。

工作目录契约：
  shots.json           v3 格式：segments[]（含 beats/use/gen/prompt）+ beats[]（旁白）
  segment-{NN}.mp4     每段的生成片（NN=段序号两位）
  narr-{NN}.mp3        每条旁白（NN=beat 序号两位）——切段长度以它的实测时长为准
  shot-{NN}.mp4        **本脚本产出**：与 narr-{NN}.mp3 一一对应的画面段（无音轨）

用法：
  python3 cut_assemble.py --workdir DIR                # 全部段
  python3 cut_assemble.py --workdir DIR --segments 2   # 只重切某段（那段重生成后用）
  python3 cut_assemble.py --workdir DIR --dry-run

输出 stdout JSON；缺件 exit 1 且不产半成品。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return float((out.stdout or "").strip())
    except ValueError:
        return 0.0


def slice_out(src: Path, dst: Path, start: float, length: float) -> None:
    """从 src 的 start 处截 length 秒。重编码而非 -c copy——按关键帧切会漂几百毫秒，
    那在分镜级剪辑里就是一次可见的错位（旁白与画面对不上）。
    -ss 放在 -i 之后是精确定位（慢但准），这条链路上准确性远比速度重要。"""
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(src),
         "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
         "-an",  # 去掉生成片自带音轨，音频统一由 compose 层挂
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         str(dst)],
        check=True, capture_output=True, timeout=900,
    )


def assemble(workdir: Path, only_segs: set[int] | None, dry_run: bool) -> dict[str, Any]:
    data = json.loads((workdir / "shots.json").read_text(encoding="utf-8"))
    segments = data.get("segments")
    if not segments:
        raise SystemExit("shots.json 里没有 segments——本脚本只处理 v3 电影格式")
    beats = {int(b["index"]): b for b in data.get("beats", [])}

    produced, missing, warnings, plan = [], [], [], []
    for seg in segments:
        si = int(seg["index"])
        if only_segs and si not in only_segs:
            continue
        src = workdir / f"segment-{si:02d}.mp4"
        if not src.exists():
            missing.append(f"段 {si}: 缺 {src.name}")
            continue
        have = probe_duration(src)

        # 每条旁白的实测时长决定切多长；旁白才是节奏基准（画面服从声音，不是反过来）
        cuts, cursor = [], 0.0
        for bi in seg["beats"]:
            narr = workdir / f"narr-{bi:02d}.mp3"
            if not narr.exists():
                missing.append(f"段 {si} beat {bi}: 缺 {narr.name}")
                continue
            length = round(probe_duration(narr) + 0.3, 2)
            cuts.append((bi, cursor, length))
            cursor += length
        if any(f"段 {si} " in m for m in missing):
            continue
        if cursor > have + 0.05:
            warnings.append(
                f"段 {si}: 旁白共 {cursor:.1f}s 长于生成片 {have:.1f}s，末段将不足 "
                f"{cursor - have:.1f}s——补法是把该段重生成得更长（gen 调大，上限 30s），"
                f"或把最后一条旁白说短些")
        plan.append({"segment": si, "source_len": round(have, 2),
                     "beats": [{"beat": b, "start": round(s, 2), "len": l} for b, s, l in cuts]})
        if dry_run:
            continue
        for bi, start, length in cuts:
            if start >= have:
                missing.append(f"段 {si} beat {bi}: 起点 {start:.1f}s 已超出生成片 {have:.1f}s")
                continue
            length = min(length, max(0.0, have - start))
            out = workdir / f"shot-{bi:02d}.mp4"
            slice_out(src, out, start, length)
            got = probe_duration(out)
            produced.append({"beat": bi, "file": out.name, "from_segment": si,
                             "start": round(start, 2), "duration": round(got, 2)})
            _err(f"  段{si} → {out.name}  {start:.1f}s起 {got:.1f}s")

    return {"ok": not missing, "produced": produced, "missing": missing,
            "warnings": warnings, "plan": plan if dry_run else []}


def main() -> None:
    ap = argparse.ArgumentParser(description="把多镜头长片段按旁白边界切成 shot-NN.mp4")
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--segments", help="只处理这些段（逗号分隔）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    only = None
    if args.segments:
        only = {int(x) for x in args.segments.replace("，", ",").split(",") if x.strip()}
    result = assemble(args.workdir, only, args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    for w in result["warnings"]:
        _err(f"⚠ {w}")
    for m in result["missing"]:
        _err(f"✗ {m}")
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()

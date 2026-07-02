#!/usr/bin/env python3
"""扫描工作目录，自动拼合 compose_video.py 可直接消费的 manifest.json —— 零手工拼 JSON。

manifest 契约，源自 compose_video.py（本仓库同目录，勿改）：
  顶层字段消费位置——
    output       第368行 manifest.get("output", "final.mp4")
    resolution   第362行 manifest.get("resolution", "720x1280")，格式 "WxH"
    fps          第367行 manifest.get("fps", 30)
    ai_label     第387行 manifest.get("ai_label", "")；docstring 第13行标注"合规显式标识"
    bgm          第388行 manifest.get("bgm")，可选
    bgm_volume   第388行 manifest.get("bgm_volume", 0.15)，可选
    bgm_gap_db   第389行 manifest.get("bgm_gap_db", 12.0)，可选
    segments     第359行 manifest.get("segments")，list
  每镜 segment 字段——由 normalize_segment()（第222-292行）消费：
    video           第230行 seg.get("video")，必需，文件须存在
    narration       第235行 seg.get("narration")，可选路径，存在才计入旁白轨
    narration_text  第251行 seg.get("narration_text")，可选；cues 缺失时按句估算字幕
    subtitle        第252行 seg.get("subtitle")，可选；无旁白/无 narration_text 时的固定字幕
    cues            第255行 seg.get("cues")，可选路径；显式给出则覆盖同名自动探测
                    （自动探测规则是 narration+".cues.json"，与本项目 narr-NN.cues.json
                    的实际落地命名不同名，故本脚本探测到就显式写入 cues，不依赖 compose 兜底探测）
    duration        第234行 seg.get("duration", 5)，可选数字；仅 ffprobe 探测 video 失败时的兜底
  字幕级联语义（第261-268行）：cues > narration_text > subtitle，三者都缺才不烧字幕。

工作目录约定（跨任务契约，Task 8/9/14）：
  shots.json          Task 8 产物：{"video":{"title","ratio","source_note"},
                       "shots":[{"index","page","prompt","subtitle","narration_text",
                       "image","duration"}, ...]}
  shot-{NN}.mp4        每镜成片，两位序号(01起)，必需——缺失则该镜无法合成，计入 missing
  narr-{NN}.mp3        每镜旁白，两位序号，必需——缺失则计入 missing 阻断（本脚本强制检查）。
                       注：compose 层对无旁白/无 cues 时可用 narration_text/subtitle 兜底字幕，
                       但本脚本不放行缺旁白镜段，由调用方决策是否允许缺件合成
  narr-{NN}.cues.json  tts_gen.py --timed 产出的时间轴 sidecar，可选；缺失时 compose 回退
                       narration_text 估算字幕
  bgm.mp3              可选，全局背景音乐

用法：
  python3 build_manifest.py --workdir DIR [--out manifest.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# compose_video.py docstring 第13行给出的默认值示例；本项目心理科普/AI生成内容合规要求
# 显式标注，缺省即保留角标（compose 自身默认是 ""→关闭，这里不沿用那个默认）。
AI_LABEL_DEFAULT = "AI 生成"

# shots.json 的 video.ratio → compose manifest.resolution（"WxH"）；未识别的 ratio 不写
# resolution 键，让 compose 自身默认("720x1280")兜底。
RATIO_TO_RESOLUTION = {
    "9:16": "720x1280",
    "16:9": "1280x720",
    "1:1": "1080x1080",
}


def _shot_files(workdir: Path, index: int) -> dict[str, Path]:
    n = f"{index:02d}"
    return {
        "video": workdir / f"shot-{n}.mp4",
        "narration": workdir / f"narr-{n}.mp3",
        "cues": workdir / f"narr-{n}.cues.json",
    }


def _err(msg: str) -> None:
    """打印到 stderr（兼容 compose_video.py 范式）。"""
    print(msg, file=sys.stderr, flush=True)


def build_manifest(workdir: Path) -> dict[str, Any]:
    """扫描 workdir，按 shots.json 逐镜配齐文件，拼出 compose_video.py 可消费的 manifest dict。
    不落盘（由调用方决定：只有 missing 为空才允许写文件）。"""
    shots_path = workdir / "shots.json"
    if not shots_path.is_file():
        raise FileNotFoundError(f"缺少 {shots_path}")
    data = json.loads(shots_path.read_text(encoding="utf-8"))
    shots = data.get("shots") or []
    video_meta = data.get("video") or {}

    segments: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for i, shot in enumerate(shots):
        idx = shot["index"]
        files = _shot_files(workdir, idx)

        has_video = files["video"].is_file()
        has_narration = files["narration"].is_file()
        has_cues = files["cues"].is_file()

        if not has_video:
            missing.append({"index": idx, "expect": files["video"].name})
        if not has_narration:
            missing.append({"index": idx, "expect": files["narration"].name})

        # stderr: 逐镜进度
        status_icon = "✓" if (has_video and has_narration) else "✗"
        components = []
        if has_video:
            components.append(f"{files['video'].name}")
        if has_narration:
            components.append(f"{files['narration'].name}")
        if has_cues:
            components.append("cues")
        component_str = " + ".join(components) if components else "缺文件"
        missing_str = ""
        if not has_video or not has_narration:
            missing_files = []
            if not has_video:
                missing_files.append(files["video"].name)
            if not has_narration:
                missing_files.append(files["narration"].name)
            missing_str = f"缺 {' + '.join(missing_files)}"

        if status_icon == "✗":
            _err(f"  镜{idx:02d} {status_icon} {missing_str}")
        else:
            _err(f"  镜{idx:02d} {status_icon} {component_str}")

        seg: dict[str, Any] = {"video": str(files["video"])}
        if files["narration"].is_file():
            seg["narration"] = str(files["narration"])
        if files["cues"].is_file():
            seg["cues"] = str(files["cues"])
        narration_text = (shot.get("narration_text") or "").strip()
        if narration_text:
            seg["narration_text"] = narration_text
        subtitle = (shot.get("subtitle") or "").strip()
        if subtitle:
            seg["subtitle"] = subtitle
        duration = shot.get("duration")
        if duration is not None:
            seg["duration"] = duration
        segments.append(seg)

    manifest: dict[str, Any] = {
        "output": str(workdir / "final.mp4"),
        "ai_label": AI_LABEL_DEFAULT,
        "segments": segments,
    }
    resolution = RATIO_TO_RESOLUTION.get(video_meta.get("ratio"))
    if resolution:
        manifest["resolution"] = resolution
    bgm_path = workdir / "bgm.mp3"
    if bgm_path.is_file():
        manifest["bgm"] = str(bgm_path)

    return {"manifest_dict": manifest, "missing": missing, "shots": len(shots)}


def main() -> None:
    p = argparse.ArgumentParser(description="扫描工作目录自动拼 compose_video.py manifest（缺件报明细）")
    p.add_argument("--workdir", required=True, help="工作目录（含 shots.json / shot-NN.mp4 / narr-NN.mp3 等）")
    p.add_argument("--out", help="manifest 输出路径（默认 workdir/manifest.json）")
    a = p.parse_args()

    workdir = Path(a.workdir)
    out = Path(a.out) if a.out else workdir / "manifest.json"

    try:
        result = build_manifest(workdir)
    except FileNotFoundError as e:
        _err(f"error: {e}")
        print(json.dumps({"manifest": None, "shots": 0, "missing": [], "ok": False, "error": str(e)},
                          ensure_ascii=False, indent=2))
        sys.exit(1)

    ok = not result["missing"]
    report: dict[str, Any] = {"manifest": None, "shots": result["shots"], "missing": result["missing"], "ok": ok}

    # stderr: 结尾汇总
    if ok:
        out.write_text(json.dumps(result["manifest_dict"], ensure_ascii=False, indent=2), encoding="utf-8")
        report["manifest"] = str(out)
        _err(f"manifest 已写入 {out}")
    else:
        missing_count = len(result["missing"])
        _err(f"清单完成：{result['shots']} 镜, 缺件 {missing_count}")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

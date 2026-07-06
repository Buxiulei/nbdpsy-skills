import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def probe_duration(path: Path) -> float:
    """获取音频文件时长（秒）。如果失败则抛异常。"""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def run(shots_path: Path, audio_dir: Path, *, min_d: float, max_d: float) -> dict[str, Any]:
    """
    同步旁白时长到 shots.json。

    Args:
        shots_path: shots.json 文件路径
        audio_dir: 音频目录路径
        min_d: 最小时长（秒）
        max_d: 最大时长（秒）

    Returns:
        报告 dict，格式：
        {
            "updated": [{"index": ..., "narration_sec": ..., "duration": ...}, ...],
            "overflow": [{"index": ..., "narration_sec": ..., "hint": "建议拆镜"}, ...],
            "missing": [{"index": N, "expect": "narr-0N.mp3", "reason": "..."}, ...],
            "ok": bool
        }
    """
    # 读取 shots.json
    shots_content = json.loads(shots_path.read_text(encoding="utf-8"))
    shots = shots_content.get("shots", [])

    report = {
        "updated": [],
        "overflow": [],
        "missing": [],
        "ok": True,
    }

    # 处理每个 shot
    for shot in shots:
        idx = shot.get("index")

        # 构造音频文件名（两位序号）
        narr_file = audio_dir / f"narr-{idx:02d}.mp3"

        # 检查文件是否存在
        if not narr_file.exists():
            report["missing"].append({
                "index": idx,
                "expect": narr_file.name,
                "reason": "file not found",
            })
            report["ok"] = False
            print(f"  镜{idx} 缺音频 {narr_file.name}", file=sys.stderr)
            continue

        # 获取音频时长
        try:
            narr_sec = probe_duration(narr_file)
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as e:
            report["missing"].append({
                "index": idx,
                "expect": narr_file.name,
                "reason": "ffprobe failed",
            })
            report["ok"] = False
            print(f"  镜{idx} 缺音频 {narr_file.name}", file=sys.stderr)
            continue

        # 加上 0.3s 后 clamp 到 [min_d, max_d]
        clamped = round(max(min_d, min(max_d, narr_sec + 0.3)), 1)

        # 检查是否 overflow
        if narr_sec + 0.3 > max_d:
            report["overflow"].append({
                "index": idx,
                "narration_sec": round(narr_sec, 1),
                "hint": "建议拆镜",
            })
            report["ok"] = False

        # 更新 duration
        shot["duration"] = clamped
        report["updated"].append({
            "index": idx,
            "narration_sec": round(narr_sec, 1),
            "duration": clamped,
        })
        print(f"  镜{idx} narr={round(narr_sec, 1)}s → duration={clamped}s", file=sys.stderr)

    # 写回 shots.json
    shots_path.write_text(json.dumps(shots_content, ensure_ascii=False, indent=2), encoding="utf-8")

    # 汇总一行结尾
    if report["updated"] or report["overflow"] or report["missing"]:
        status = "FAIL" if not report["ok"] else "OK"
        print(f"同步完成：{len(report['updated'])} 更新、{len(report['overflow'])} 溢出、{len(report['missing'])} 缺失 [{status}]", file=sys.stderr)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="同步旁白时长到 shots.json"
    )
    parser.add_argument("--shots", required=True, help="shots.json 文件路径")
    parser.add_argument("--audio-dir", required=True, dest="audio_dir", help="音频目录路径")
    parser.add_argument("--min", type=float, default=4, dest="min_d", help="最小时长（秒）")
    parser.add_argument("--max", type=float, default=15, dest="max_d", help="最大时长（秒）")

    args = parser.parse_args()

    shots_file = Path(args.shots)
    audio_directory = Path(args.audio_dir)

    result = run(shots_file, audio_directory, min_d=args.min_d, max_d=args.max_d)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)

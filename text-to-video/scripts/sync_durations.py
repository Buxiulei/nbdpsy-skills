import json
import subprocess
from pathlib import Path
from typing import Any


def probe_duration(path: Path) -> float:
    """获取音频文件时长（秒）。"""
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
            "missing": ["index", ...],
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
            report["missing"].append(idx)
            report["ok"] = False
            continue

        # 获取音频时长
        narr_sec = probe_duration(narr_file)

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

    # 写回 shots.json
    shots_path.write_text(json.dumps(shots_content, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


if __name__ == "__main__":
    import sys

    # 简单的 CLI 支持（可选）
    if len(sys.argv) < 3:
        print("Usage: python sync_durations.py <shots.json> <audio_dir> [--min <min_d>] [--max <max_d>]")
        sys.exit(1)

    shots_file = Path(sys.argv[1])
    audio_directory = Path(sys.argv[2])

    min_duration = 4.0
    max_duration = 15.0

    # 解析可选参数
    for i, arg in enumerate(sys.argv[3:]):
        if arg == "--min" and i + 4 < len(sys.argv):
            min_duration = float(sys.argv[i + 4])
        elif arg == "--max" and i + 4 < len(sys.argv):
            max_duration = float(sys.argv[i + 4])

    result = run(shots_file, audio_directory, min_d=min_duration, max_d=max_duration)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)

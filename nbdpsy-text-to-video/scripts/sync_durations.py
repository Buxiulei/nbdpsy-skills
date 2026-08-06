import argparse
import json
import math
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


def run_segments(data: dict, shots_path: Path, audio_dir: Path, *,
                 max_d: float) -> dict[str, Any]:
    """v3：逐段校验并写回 gen。gen = ceil(该段旁白实测总和 + 0.3×beat数)，clamp 到 max_d。
    超 max_d 直接报 overflow（要拆段或压旁白），**绝不静默截短**——截短意味着最后一条
    旁白没画面可配。"""
    report: dict[str, Any] = {"updated": [], "overflow": [], "missing": [], "ok": True}
    for seg in data["segments"]:
        si = seg.get("index")
        need = 0.0
        seg_missing = False
        for bi in seg.get("beats") or []:
            narr = audio_dir / f"narr-{bi:02d}.mp3"
            if not narr.exists():
                report["missing"].append({"segment": si, "beat": bi, "expect": narr.name,
                                          "reason": "file not found"})
                report["ok"] = False
                seg_missing = True
                continue
            try:
                need += probe_duration(narr) + 0.3
            except Exception:
                report["missing"].append({"segment": si, "beat": bi, "expect": narr.name,
                                          "reason": "ffprobe failed"})
                report["ok"] = False
                seg_missing = True
        if seg_missing:
            continue
        gen = int(math.ceil(need))
        if gen > max_d:
            report["overflow"].append({"segment": si, "need": round(need, 1),
                                       "hint": f"该段旁白共 {need:.1f}s 超模型上限 {max_d}s——"
                                               f"把 beat 挪到别的段，或压旁白"})
            report["ok"] = False
            continue
        old = seg.get("gen")
        seg["gen"] = gen
        seg["narr_total"] = round(need, 1)
        report["updated"].append({"segment": si, "narr_total": round(need, 1),
                                  "gen": gen, "was": old})
        print(f"  段{si} 旁白共 {need:.1f}s → gen={gen}s" +
              (f"（原 {old}s 已修正）" if old != gen else ""), file=sys.stderr)
    shots_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def run_beats(data: dict, shots_path: Path, audio_dir: Path, *,
              min_d: float, max_d: float) -> dict[str, Any]:
    """v2 电影格式：把每条旁白的实测时长分配给该 beat 下的各个 cut。

    两个时长分开，别混：
      `use` —— 成片里这一刀实际用多少秒（可以 <4，电影感就靠它切得碎）；
      `gen` —— 提交给即梦生成多少秒（**最短 4 秒是平台硬约束**），默认 5。
    分配按各 cut 的 `weight`（缺省 1）等比切分 `旁白时长 + 0.3s`，再四舍五入到 0.1s，
    尾差补给最后一刀——保证 sum(use) 与 beat 时长严丝合缝，拼完不会与旁白错位。
    """
    report: dict[str, Any] = {"updated": [], "overflow": [], "missing": [], "ok": True}
    for beat in data["beats"]:
        idx = beat.get("index")
        narr_file = audio_dir / f"narr-{idx:02d}.mp3"
        if not narr_file.exists():
            report["missing"].append({"index": idx, "expect": narr_file.name,
                                      "reason": "file not found"})
            report["ok"] = False
            print(f"  beat{idx} 缺音频 {narr_file.name}", file=sys.stderr)
            continue
        try:
            narr_sec = probe_duration(narr_file)
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError):
            report["missing"].append({"index": idx, "expect": narr_file.name,
                                      "reason": "ffprobe failed"})
            report["ok"] = False
            continue

        total = round(narr_sec + 0.3, 2)
        cuts = beat.get("cuts") or []
        if not cuts:
            report["missing"].append({"index": idx, "expect": "cuts[]", "reason": "no cuts"})
            report["ok"] = False
            continue
        weights = [float(c.get("weight") or 1) for c in cuts]
        wsum = sum(weights) or 1.0
        acc = 0.0
        for c, w in zip(cuts[:-1], weights[:-1]):
            use = round(total * w / wsum, 1)
            c["use"] = use
            acc += use
        cuts[-1]["use"] = round(total - acc, 1)  # 尾差全给最后一刀，避免累计误差
        for c in cuts:
            # gen 是提交给即梦的时长：至少 4s（平台下限），且不小于要用的秒数
            c["gen"] = int(max(min_d, math.ceil(c["use"]), c.get("gen") or 0)) or int(min_d)
            if c["gen"] > max_d:
                report["overflow"].append({"index": idx, "cut": c.get("n"),
                                           "hint": f"单刀 {c['use']}s 超出模型上限 {max_d}s，拆刀"})
                report["ok"] = False
        report["updated"].append({
            "index": idx, "narration_sec": round(narr_sec, 1), "duration": total,
            "cuts": [{"n": c.get("n"), "use": c["use"], "gen": c["gen"]} for c in cuts],
        })
        shown = " + ".join(f"{c['use']}s" for c in cuts)
        print(f"  beat{idx} narr={narr_sec:.1f}s → {total}s = {shown}（{len(cuts)} 刀）",
              file=sys.stderr)

    shots_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


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
    if shots_content.get("segments"):
        # v3 电影格式：一段 = 一次生成，段内切割由 cut_assemble 按旁白实测完成。
        # 本步的职责变为**提交前的钱坑校验**：每段 gen 必须 ≥ 该段旁白总长 + 0.3s/beat，
        # 否则生成出来不够切（cut_assemble 只能告警，但那时钱已花了）。
        return run_segments(shots_content, shots_path, audio_dir, max_d=max_d)
    if shots_content.get("beats"):
        # v2 电影格式：一条旁白（beat）挂多个分镜（cut），按 cut 权重把旁白时长分下去
        return run_beats(shots_content, shots_path, audio_dir, min_d=min_d, max_d=max_d)
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

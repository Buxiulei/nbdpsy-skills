#!/usr/bin/env python3
"""审查小红书轮播配图目录：页数齐全 + 尺寸合规。

判定标准（对齐 nbdpsy-xiaohongshu-creator 的竖版轮播交付要求，2026-07-26 更新）：
  - 页数：--pages N 指定应有页数，按文件名页号映射 P01..PN，缺页记入 missing
  - 尺寸：宽高比命中**一组合法比例**之一即合规，各 ±2% 容差 ——
      · 2:3（w/h≈0.6667）：后端 /api/op/consistent-images 原生出图 1024×1536，主力
      · 3:4（w/h=0.75）：运营自己用 Gemini/GPT 出的图、以及历史补边图
    最短边 ≥1024（保证小红书上不糊；原为 1080，会误杀 1024 宽的后端原生图）

输出 JSON（stdout 只有 JSON，进度走 stderr）：
  {"found": M, "expected": N, "missing": ["P03"],
   "wrong_size": [{"file","w","h","ratio","aspect"}], "ok": bool}
exit：0=全部通过；1=缺页或尺寸不合规；2=参数/目录错误

用法：
  python3 check_images.py --dir IMAGES_DIR --pages N
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
# 合法竖版画布（2026-07-26 定案）：后端原生 2:3 与自出图/历史补边图 3:4 皆合规
ALLOWED_ASPECTS = {
    "2:3": 2 / 3,       # ≈0.6667 — 后端 /api/op/consistent-images 原生 1024×1536（主力）
    "3:4": 3 / 4,       # =0.75   — Gemini/GPT 自出图、历史补边图
}
ASPECT_TOL = 0.02       # 比例相对容差 ±2%
MIN_SHORT_SIDE = 1024   # 最短边下限（原 1080 会误杀 1024 宽的后端原生图）
ALLOWED_DESC = f"2:3（0.6667）或 3:4（0.75），各 ±2%；最短边 ≥{MIN_SHORT_SIDE}"


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def page_number(stem: str) -> int | None:
    """从文件名提取页号：优先 P/p 紧跟数字（P01 / cptsd-p1-cover），兜底纯数字名（02）。"""
    m = re.search(r"[Pp](\d+)", stem)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"(\d+)", stem)
    if m:
        return int(m.group(1))
    return None


def match_aspect(w: int, h: int) -> str | None:
    """命中哪个合法比例（±2%），都不命中返回 None。"""
    if h <= 0:
        return None
    ratio = w / h
    for name, target in ALLOWED_ASPECTS.items():
        if abs(ratio - target) / target <= ASPECT_TOL:
            return name
    return None


def check_size(w: int, h: int) -> tuple[bool, str | None, float]:
    """命中 2:3 或 3:4（各 ±2%）且最短边 ≥1024。返回 (是否合规, 命中的比例名, 实际 w/h)。"""
    ratio = round(w / h, 4) if h > 0 else 0.0
    name = match_aspect(w, h)
    return (name is not None and min(w, h) >= MIN_SHORT_SIDE), name, ratio


def run(img_dir: Path, expected_pages: int) -> dict:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        raise RuntimeError("缺依赖 pillow（pip install pillow）")

    files = sorted(p for p in img_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    pages_seen: set[int] = set()
    wrong_size: list[dict] = []

    for f in files:
        try:
            with Image.open(f) as im:
                w, h = im.size
        except Exception as e:  # noqa: BLE001 — 读不出来的图必定不合格，如实上报
            wrong_size.append({"file": f.name, "w": 0, "h": 0, "error": f"无法读取: {e}"})
            _err(f"  ✗ {f.name} 无法读取: {e}")
            continue

        n = page_number(f.stem)
        if n is not None:
            pages_seen.add(n)

        size_ok, aspect, ratio = check_size(w, h)
        if size_ok:
            _err(f"  ✓ {f.name} {w}x{h}（{aspect}）")
        else:
            wrong_size.append({"file": f.name, "w": w, "h": h, "ratio": ratio, "aspect": aspect})
            _err(f"  ✗ {f.name} {w}x{h} 实际比例 {ratio}（要求 {ALLOWED_DESC}）")

    missing = [f"P{n:02d}" for n in range(1, expected_pages + 1) if n not in pages_seen]
    ok = bool(files) and not missing and not wrong_size
    return {
        "found": len(files),
        "expected": expected_pages,
        "missing": missing,
        "wrong_size": wrong_size,
        "ok": ok,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=f"轮播配图确定性检查：页数齐全 + 尺寸合规（{ALLOWED_DESC}）")
    ap.add_argument("--dir", required=True, help="配图目录")
    ap.add_argument("--pages", required=True, type=int, help="应有页数 N（对照 P01..PN）")
    a = ap.parse_args()

    img_dir = Path(a.dir)
    if not img_dir.is_dir():
        print(json.dumps({"error": f"目录不存在: {img_dir}"}, ensure_ascii=False))
        _err(f"Error: 目录不存在: {img_dir}")
        sys.exit(2)
    if a.pages < 1:
        print(json.dumps({"error": f"--pages 须 ≥1，收到 {a.pages}"}, ensure_ascii=False))
        sys.exit(2)

    try:
        report = run(img_dir, a.pages)
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        _err(f"Error: {e}")
        sys.exit(2)

    print(json.dumps(report, ensure_ascii=False))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()

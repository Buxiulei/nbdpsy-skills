#!/usr/bin/env python3
"""审查配图目录：页数齐全 + 尺寸合规。分**竖版（小红书）/ 横版（公众号）**两套画布口径。

  - 页数：--pages N 指定应有页数，按文件名页号映射 P01..PN，缺页记入 missing。
    省略 --pages 即**不校验页数**（公众号是 cover + illus-01… 无页号命名）
  - 尺寸：宽高比命中所选画布的**一组合法比例**之一即合规，各 ±2% 容差

--canvas portrait（默认，小红书竖版轮播，2026-07-26 定案）：
    · 2:3（w/h≈0.6667）：后端 /api/op/consistent-images 原生出图 1024×1536，主力
    · 3:4（w/h=0.75）：运营自己用 Gemini/GPT 出的图、以及历史补边图
  最短边 ≥1024（保证小红书上不糊；原为 1080，会误杀 1024 宽的后端原生图）

--canvas landscape（公众号横版，2026-08-17 补）：
    · 2.35:1（≈2.35）：封面，脚本按实际宽现算高居中裁，实测 1313×559
    · 3:2（=1.5）：正文插图与未裁的 cover-raw，实测 1313×876
  最长边 ≥1200（横版两种比例的短边差一倍，卡短边必顾此失彼；长边在本产线恒为 1313）
  🔴 **不要按 gzh-illustration-spec.md 字面的「16:9」建白名单**——那是传给出图 API 的
     `aspect_ratio` 参数名，**到手画布实为 3:2**（标称 1536×1024 本身就是 3:2，
     去水印等比缩小后 1313×876）。2026-08-17 实测在产 31 张正文插图**比例全为 1.4989、
     零例外**；照文档写 16:9(1.778) 会让每一张都判红——是假红不是问题。

输出 JSON（stdout 只有 JSON，进度走 stderr）：
  {"canvas": "portrait", "found": M, "expected": N, "missing": ["P03"],
   "sizes": [{"file","w","h","ratio","aspect"}],      # 全量，aspect=None 即未命中
   "wrong_size": [{"file","w","h","ratio","aspect"}], "ok": bool}
exit：0=全部通过；1=缺页或尺寸不合规；2=参数/目录错误

用法：
  python3 check_images.py --dir IMAGES_DIR --pages N            # 小红书竖版
  python3 check_images.py --dir IMAGES_DIR --canvas landscape   # 公众号横版
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ASPECT_TOL = 0.02       # 比例相对容差 ±2%

# 画布口径表。floor=(边, 下限)：'short' 卡最短边、'long' 卡最长边。
# 一个画布一套白名单，⛔ 不合并成一张大表——合并后竖版轮播里混进一张横图也会放行，
# 而"混进一张横图"正是这个检查最该抓的错。
CANVAS_PROFILES = {
    "portrait": {
        "aspects": {
            "2:3": 2 / 3,   # ≈0.6667 — 后端 /api/op/consistent-images 原生 1024×1536（主力）
            "3:4": 3 / 4,   # =0.75   — Gemini/GPT 自出图、历史补边图
        },
        "floor": ("short", 1024),   # 原 1080 会误杀 1024 宽的后端原生图
    },
    "landscape": {
        "aspects": {
            "2.35:1": 2.35,  # 公众号封面，居中裁，实测 1313×559（=2.3488）
            "3:2": 3 / 2,    # 正文插图与 cover-raw，实测 1313×876（=1.4989）
                             # 🔴 规格文档写作「16:9」——那是出图 API 参数名，不是到手画布
        },
        "floor": ("long", 1200),    # 两种比例短边差近一倍，只能卡长边（本产线恒 1313）
    },
}
DEFAULT_CANVAS = "portrait"


def allowed_desc(canvas: str) -> str:
    p = CANVAS_PROFILES[canvas]
    names = "或".join(f"{n}（{v:.4g}）" for n, v in p["aspects"].items())
    side, floor = p["floor"]
    return f"{names}，各 ±{ASPECT_TOL:.0%}；最{'短' if side == 'short' else '长'}边 ≥{floor}"


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


def match_aspect(w: int, h: int, canvas: str = DEFAULT_CANVAS) -> str | None:
    """命中该画布哪个合法比例（±2%），都不命中返回 None。"""
    if h <= 0:
        return None
    ratio = w / h
    for name, target in CANVAS_PROFILES[canvas]["aspects"].items():
        if abs(ratio - target) / target <= ASPECT_TOL:
            return name
    return None


def check_size(w: int, h: int, canvas: str = DEFAULT_CANVAS) -> tuple[bool, str | None, float]:
    """命中该画布的合法比例（±2%）且过像素下限。返回 (是否合规, 命中的比例名, 实际 w/h)。"""
    ratio = round(w / h, 4) if h > 0 else 0.0
    name = match_aspect(w, h, canvas)
    side, floor = CANVAS_PROFILES[canvas]["floor"]
    px = min(w, h) if side == "short" else max(w, h)
    return (name is not None and px >= floor), name, ratio


def run(img_dir: Path, expected_pages: int | None, canvas: str = DEFAULT_CANVAS) -> dict:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        raise RuntimeError("缺依赖 pillow（pip install pillow）")

    files = sorted(p for p in img_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    pages_seen: set[int] = set()
    sizes: list[dict] = []
    wrong_size: list[dict] = []
    desc = allowed_desc(canvas)

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

        size_ok, aspect, ratio = check_size(w, h, canvas)
        # 全量 sizes：命中的比例名也留给下游，忘裁封面这类错（cover 标成 3:2 而非 2.35:1）
        # 光看 ok 看不出来，看这一列一眼就见
        sizes.append({"file": f.name, "w": w, "h": h, "ratio": ratio, "aspect": aspect})
        if size_ok:
            _err(f"  ✓ {f.name} {w}x{h}（{aspect}）")
        else:
            wrong_size.append({"file": f.name, "w": w, "h": h, "ratio": ratio, "aspect": aspect})
            _err(f"  ✗ {f.name} {w}x{h} 实际比例 {ratio}（要求 {desc}）")

    missing = ([f"P{n:02d}" for n in range(1, expected_pages + 1) if n not in pages_seen]
               if expected_pages is not None else [])
    ok = bool(files) and not missing and not wrong_size
    return {
        "canvas": canvas,
        "found": len(files),
        "expected": expected_pages,
        "missing": missing,
        "sizes": sizes,
        "wrong_size": wrong_size,
        "ok": ok,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="配图确定性检查：页数齐全 + 尺寸合规")
    ap.add_argument("--dir", required=True, help="配图目录")
    ap.add_argument("--pages", type=int, default=None,
                    help="应有页数 N（对照 P01..PN）；省略即不校验页数（公众号无页号命名）")
    ap.add_argument("--canvas", choices=sorted(CANVAS_PROFILES), default=DEFAULT_CANVAS,
                    help=" | ".join(f"{c}: {allowed_desc(c)}" for c in sorted(CANVAS_PROFILES)))
    a = ap.parse_args()

    img_dir = Path(a.dir)
    if not img_dir.is_dir():
        print(json.dumps({"error": f"目录不存在: {img_dir}"}, ensure_ascii=False))
        _err(f"Error: 目录不存在: {img_dir}")
        sys.exit(2)
    if a.pages is not None and a.pages < 1:
        print(json.dumps({"error": f"--pages 须 ≥1，收到 {a.pages}"}, ensure_ascii=False))
        sys.exit(2)

    try:
        report = run(img_dir, a.pages, a.canvas)
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        _err(f"Error: {e}")
        sys.exit(2)

    print(json.dumps(report, ensure_ascii=False))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()

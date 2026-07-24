#!/usr/bin/env python3
"""把运营提供的咨询师真实照片，本地合成进 P1 封面底图的预留留白区（备选保真路线）。

🔴 铁律：照片只做本地几何合成（等比裁剪 / 圆角 / 品牌色描边），
**绝不喂给任何 AI 生图/重绘**（肖像失真 + 合规风险）。本脚本不联网、不调模型。
照片只上 P1 封面，内页一律不放（2026-07-24 定案）。
发布前须先向运营确认「已获咨询师本人同意用于小红书宣传」，见 references/counselor-note-spec.md。

用法：
  python3 compose_photo.py --base 底图.png --photo 照片.jpg --out 输出.png [--region top|left]

区域（默认 top，对齐 spec 里封面底图的留白提示词）：
  top  = 底图顶部约 1/3 高、左右各留 6% 边距
  left = 底图左侧约 40% 宽
"""
import argparse
import sys

BRAND_STROKE = "#A8B5C4"   # 品牌雾霾蓝灰，照片描边
MARGIN_RATIO = 0.06        # 留白区左右（及顶部）边距 = 底图宽 6%
TOP_HEIGHT_RATIO = 1 / 3   # top 区高度 = 底图高 1/3
LEFT_WIDTH_RATIO = 0.40    # left 区宽度 = 底图宽 40%
RADIUS_RATIO = 0.03        # 圆角半径 = 底图宽 3%
STROKE_RATIO = 0.006       # 描边宽度 = 底图宽 0.6%

_NO_PILLOW_HINT = (
    "缺少 Pillow（图像库），无法合成照片。请先安装：\n"
    "    pip install Pillow\n"
    "或让我跑：python3 scripts/env_check.py --profile xhs --install"
)


def compute_region(base_w: int, base_h: int, region: str = "top"):
    """计算照片目标区 (x, y, w, h)。纯函数，无 Pillow 依赖，便于单测。"""
    margin = round(base_w * MARGIN_RATIO)
    if region == "top":
        # 高度扣掉顶部内缩：照片底边 = margin + h = base_h/3，完整落在底图「顶部 1/3 留白区」内，
        # 不压底图下部版式最顶端的姓名/职称条（此前 h=1/3 会整体下溢 margin 像素）
        return (margin, margin, base_w - 2 * margin, round(base_h * TOP_HEIGHT_RATIO) - margin)
    if region == "left":
        return (margin, margin, round(base_w * LEFT_WIDTH_RATIO), base_h - 2 * margin)
    raise ValueError(f"未知 region：{region}（只支持 top / left）")


def rounded_mask(size, radius: int):
    """生成圆角矩形 L 模式遮罩（角内=255 不透明、角外=0 透明）。"""
    from PIL import Image, ImageDraw
    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    return mask


def _cover_crop(photo, target_w: int, target_h: int):
    """等比缩放到刚好覆盖目标区，再居中裁剪（cover 语义，不变形）。"""
    from PIL import Image
    pw, ph = photo.size
    scale = max(target_w / pw, target_h / ph)
    nw, nh = max(target_w, round(pw * scale)), max(target_h, round(ph * scale))
    resized = photo.resize((nw, nh), Image.LANCZOS)
    left = (nw - target_w) // 2
    top = (nh - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def compose(base_path, photo_path, out_path, region: str = "top"):
    """把照片合成进底图留白区并输出 PNG。返回目标区 (x, y, w, h)。"""
    from PIL import Image, ImageDraw
    base = Image.open(base_path).convert("RGBA")
    photo = Image.open(photo_path).convert("RGBA")

    x, y, w, h = compute_region(base.width, base.height, region)
    radius = round(base.width * RADIUS_RATIO)

    cropped = _cover_crop(photo, w, h)
    mask = rounded_mask((w, h), radius)
    base.paste(cropped, (x, y), mask)

    stroke_w = max(1, round(base.width * STROKE_RATIO))
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([x, y, x + w - 1, y + h - 1],
                           radius=radius, outline=BRAND_STROKE, width=stroke_w)

    base.convert("RGB").save(out_path, "PNG")
    return (x, y, w, h)


def main():
    parser = argparse.ArgumentParser(description="把咨询师照片本地合成进 P1 封面底图留白区（备选保真路线，不经 AI 重绘）")
    parser.add_argument("--base", required=True, help="P1 封面底图（带留白区的 PNG）")
    parser.add_argument("--photo", required=True, help="运营提供的咨询师真实照片")
    parser.add_argument("--out", required=True, help="合成输出 PNG 路径")
    parser.add_argument("--region", choices=["top", "left"], default="top",
                        help="照片放置区（默认 top，对齐 spec 底图留白）")
    args = parser.parse_args()

    try:
        from PIL import Image  # noqa: F401  仅探测是否可用
    except ImportError:
        print(_NO_PILLOW_HINT, file=sys.stderr)
        return 1

    try:
        box = compose(args.base, args.photo, args.out, args.region)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    print(f"✓ 已合成：{args.out}（照片区 x={box[0]} y={box[1]} w={box[2]} h={box[3]}，region={args.region}）",
          file=sys.stderr)
    print(f"提醒：照片文件不要提交进 git，用完请自行保管；发布前确认已获咨询师本人授权。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

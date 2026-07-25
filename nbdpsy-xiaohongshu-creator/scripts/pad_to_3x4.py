#!/usr/bin/env python3
"""把后端出的 1024×1536（2:3）配图补边成严格 3:4（1152×1536），不裁不缩、内容零损失。

**为什么需要这一步**（2026-07-25 实测定案）：
后端 gpt-image 只支持 1024x1024 / 1536x1024 / 1024x1536 三种尺寸，**没有 3:4 选项**
（SDK `image_edit_params.size` 的 Literal 列表即为证）。竖版只能出 1024×1536（2:3），
比 3:4 更高——小红书 feed 预览按 3:4 裁剪时会**从上下切掉**，页脚的危机声明
（12356）与 G2 就医分流句因此在预览里看不见。这不是美观问题，是合规元素不可见。

**为什么不能靠提示词**：运营实测在提示词里写死「底部至少留 100px 安全边距」后重新出图，
底部留白最小值 8px→5px、中位 21px→17px，**毫无改善**——图像模型不遵守像素级版面约束。
所以边距只能靠确定性后处理解决。

**做法**：1536 高对应 3:4 宽度 = 1152，左右各补 64px，用最外一列像素**横向外延**
（edge replicate）填充。平背景下接缝不可见；文字与图形一个像素都不动。

⚠️ **必须在所有重出完成之后再跑**——`gen_images.py` 重出会用新的 1024 宽图覆盖已补边的文件。
本脚本幂等：已是 3:4 的文件会跳过，重复跑安全。

用法：
  python3 pad_to_3x4.py <目录或文件> [...]        # 就地补边
  python3 pad_to_3x4.py {note_dir}/images         # 递归整个 images 目录
  python3 pad_to_3x4.py <目录> --dry-run          # 只报告不改文件
"""
import argparse
import sys
from pathlib import Path

TARGET_RATIO = (3, 4)          # 目标宽高比
RATIO_TOLERANCE = 0.005        # 比例判定容差（避免浮点误差把已达标的图重复补边）
SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

_NO_PILLOW_HINT = (
    "缺少 Pillow（图像库），无法补边。请先安装：\n"
    "    pip install Pillow\n"
    "或让我跑：python3 scripts/env_check.py --profile xhs --install"
)


def target_width(height: int) -> int:
    """给定高度，算出严格 3:4 所需宽度（四舍五入到偶数，避免奇数宽导致左右补不均）。"""
    w = round(height * TARGET_RATIO[0] / TARGET_RATIO[1])
    return w + (w % 2)


def needs_padding(width: int, height: int) -> bool:
    """已是 3:4（容差内）→ 不需要；比 3:4 更宽 → 也不补（补了会变形，交人工判断）。"""
    ratio = width / height
    target = TARGET_RATIO[0] / TARGET_RATIO[1]
    if abs(ratio - target) <= RATIO_TOLERANCE:
        return False
    return ratio < target      # 只处理「比 3:4 更窄/更高」的情形


def pad_image(path: Path, dry_run: bool = False) -> dict:
    """把单张图补成 3:4。返回 {path, action, before, after}。"""
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB") if im.mode not in ("RGB", "RGBA") else im.copy()
        w, h = im.size
        before = f"{w}x{h}"

        if not needs_padding(w, h):
            ratio = w / h
            target = TARGET_RATIO[0] / TARGET_RATIO[1]
            action = "skip:已是3:4" if abs(ratio - target) <= RATIO_TOLERANCE else "skip:比3:4更宽"
            return {"path": str(path), "action": action, "before": before, "after": before}

        tw = target_width(h)
        pad_total = tw - w
        left = pad_total // 2
        right = pad_total - left

        canvas = Image.new(im.mode, (tw, h))
        canvas.paste(im, (left, 0))
        # 边缘外延：把最外一列拉伸成补边条，平背景下接缝不可见
        if left > 0:
            canvas.paste(im.crop((0, 0, 1, h)).resize((left, h)), (0, 0))
        if right > 0:
            canvas.paste(im.crop((w - 1, 0, w, h)).resize((right, h)), (left + w, 0))

        after = f"{tw}x{h}"
        if not dry_run:
            canvas.save(path)
        return {"path": str(path), "action": "padded" if not dry_run else "would-pad",
                "before": before, "after": after, "pad": f"L{left}/R{right}"}


def collect(targets) -> list:
    files = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.suffix.lower() in SUFFIXES))
        elif p.is_file() and p.suffix.lower() in SUFFIXES:
            files.append(p)
        else:
            print(f"跳过（不是图片或不存在）：{p}", file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser(
        description="把 1024×1536(2:3) 配图补边成严格 3:4(1152×1536)，不裁不缩")
    ap.add_argument("targets", nargs="+", help="图片文件或目录（目录会递归）")
    ap.add_argument("--dry-run", action="store_true", help="只报告不改文件")
    a = ap.parse_args()

    try:
        import PIL  # noqa: F401
    except ImportError:
        print(_NO_PILLOW_HINT, file=sys.stderr)
        return 1

    files = collect(a.targets)
    if not files:
        print("没有找到图片", file=sys.stderr)
        return 1

    padded = skipped = 0
    for f in files:
        try:
            r = pad_image(f, a.dry_run)
        except Exception as e:  # 单张失败不影响其余
            print(f"  ✗ {f}: {e}", file=sys.stderr)
            continue
        if r["action"].startswith("skip"):
            skipped += 1
        else:
            padded += 1
            print(f"  ✓ {f.name}  {r['before']} → {r['after']}  ({r['pad']})", file=sys.stderr)

    verb = "将补边" if a.dry_run else "已补边"
    print(f"{verb} {padded} 张，跳过 {skipped} 张（已是 3:4 或更宽）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

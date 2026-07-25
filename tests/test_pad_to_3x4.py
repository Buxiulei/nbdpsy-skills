"""补边脚本 pad_to_3x4 的单测：比例计算 / 幂等 / 边缘复制 / 内容零位移。

背景：后端 gpt-image 只出 1024×1536(2:3)，无 3:4 选项；小红书 feed 按 3:4 从上下裁切，
会切掉页脚的危机声明与 G2 就医分流句。提示词层面控制边距实测无效（运营 2026-07-25 实测：
底部留白中位 21px→17px），故改为确定性后处理补边。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))


def test_target_width_is_strict_3x4():
    import pad_to_3x4
    # 1536 高 → 3:4 宽 = 1152
    assert pad_to_3x4.target_width(1536) == 1152
    assert pad_to_3x4.target_width(1024) == 768
    # 结果恒为偶数，保证左右补边可均分
    assert all(pad_to_3x4.target_width(h) % 2 == 0 for h in (1000, 1001, 1333, 1537))


def test_needs_padding_decision():
    import pad_to_3x4
    assert pad_to_3x4.needs_padding(1024, 1536) is True      # 2:3 比 3:4 窄 → 补
    assert pad_to_3x4.needs_padding(1152, 1536) is False     # 已是 3:4 → 跳过（幂等的根基）
    assert pad_to_3x4.needs_padding(1536, 1024) is False     # 横版比 3:4 宽 → 不动（补了会变形）
    assert pad_to_3x4.needs_padding(1024, 1024) is False     # 1:1 比 3:4 宽 → 不动


def _make(tmp_path, w=1024, h=1536):
    Image = pytest.importorskip("PIL.Image", reason="无 Pillow，跳过")
    from PIL import ImageDraw
    im = Image.new("RGB", (w, h), (232, 216, 196))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 3, h - 1], fill=(200, 0, 0))          # 最左列纯红
    d.rectangle([w - 4, 0, w - 1, h - 1], fill=(0, 0, 200))  # 最右列纯蓝
    d.rectangle([100, h - 16, w - 124, h - 6], fill=(0, 0, 0))  # 底部贴边"文字"
    p = tmp_path / "P01.png"
    im.save(p)
    return p


def test_pad_result_size_and_edge_replicate(tmp_path):
    Image = pytest.importorskip("PIL.Image", reason="无 Pillow，跳过")
    import pad_to_3x4
    p = _make(tmp_path)
    r = pad_to_3x4.pad_image(p)
    assert r["action"] == "padded"

    from PIL import Image as I
    out = I.open(p)
    assert out.size == (1152, 1536)                     # 严格 3:4
    assert out.getpixel((10, 700)) == (200, 0, 0)       # 左补边 = 复制最左列
    assert out.getpixel((1141, 700)) == (0, 0, 200)     # 右补边 = 复制最右列


def test_content_not_shifted_or_scaled(tmp_path):
    """补边不得裁切或缩放原内容：原图整块应原样出现在偏移 64px 处。"""
    Image = pytest.importorskip("PIL.Image", reason="无 Pillow，跳过")
    from PIL import Image as I
    import pad_to_3x4
    p = _make(tmp_path)
    before = I.open(p).convert("RGB").copy()
    pad_to_3x4.pad_image(p)
    after = I.open(p).convert("RGB")
    assert after.crop((64, 0, 64 + 1024, 1536)).tobytes() == before.tobytes()


def test_idempotent(tmp_path):
    """重复跑必须安全——gen_images 重出后会再跑一次，不能补第二遍。"""
    pytest.importorskip("PIL.Image", reason="无 Pillow，跳过")
    from PIL import Image as I
    import pad_to_3x4
    p = _make(tmp_path)
    pad_to_3x4.pad_image(p)
    r2 = pad_to_3x4.pad_image(p)
    assert r2["action"].startswith("skip")
    assert I.open(p).size == (1152, 1536)


def test_dry_run_does_not_write(tmp_path):
    pytest.importorskip("PIL.Image", reason="无 Pillow，跳过")
    from PIL import Image as I
    import pad_to_3x4
    p = _make(tmp_path)
    r = pad_to_3x4.pad_image(p, dry_run=True)
    assert r["action"] == "would-pad"
    assert I.open(p).size == (1024, 1536)   # 文件未被改写

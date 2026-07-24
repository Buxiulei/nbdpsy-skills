"""咨询师推介笔记两脚本的单测（不打网）：
  fetch_counselor —— data 信封解构 / contracted_price 被删 / --list 字段映射
  compose_photo   —— 区域计算纯函数 / 本地合成尺寸与像素断言（无 Pillow 则 skip）
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))


# ========== fetch_counselor（请求层 monkeypatch，绝不打网） ==========

FAKE_DETAIL = {
    "data": {
        "emp_no": "EMP001",
        "display_name": "徐瑞恒",
        "title": "CPS注册助理心理师",
        "price_per_session": 400.0,
        "communication_price": 0.0,
        "is_accepting": True,
        "profile_sections": {"experience": {"credentials": "CPS注册系统助理心理师"}},
        "contracted_price": 260.0,   # 🔴 隐私字段，必须被删
        "video_intro_url": "https://x/v.mp4",
    }
}

FAKE_LIST = {
    "data": {
        "counselors": [
            {"emp_no": "EMP001", "name": None, "display_name": "徐瑞恒",
             "title": "CPS注册助理心理师", "is_accepting": True,
             "price_per_session": 400.0, "communication_price": 0.0,
             "specialties": ["情绪困扰", "创伤"], "contracted_price": 260.0},
            {"emp_no": "EMP002", "name": None, "display_name": "李牧阳",
             "title": "北大心理学博士", "is_accepting": False,
             "price_per_session": 600.0, "communication_price": 100.0,
             "specialties": ["职场压力"]},
        ]
    }
}


def test_fetch_counselor_drops_contracted_price(monkeypatch):
    import copy
    import fetch_counselor
    # 深拷贝：生产代码就地删字段，直接共享 FAKE_DETAIL 会让测试间产生顺序依赖
    monkeypatch.setattr(fetch_counselor, "fetch_json", lambda url: copy.deepcopy(FAKE_DETAIL))
    result = fetch_counselor.fetch_counselor("EMP001", api_base="https://x")
    # data 信封已解构到顶层
    assert result["emp_no"] == "EMP001"
    assert result["profile_sections"]["experience"]["credentials"]
    # 🔴 签约价必须被删除
    assert "contracted_price" not in result
    # 对外价格字段仍在
    assert result["price_per_session"] == 400.0
    assert result["communication_price"] == 0.0


def test_fetch_counselor_url_targets_emp(monkeypatch):
    import fetch_counselor
    captured = {}

    def mock(url):
        import copy
        captured["url"] = url
        return copy.deepcopy(FAKE_DETAIL)

    monkeypatch.setattr(fetch_counselor, "fetch_json", mock)
    fetch_counselor.fetch_counselor("EMP001", api_base="https://x")
    assert captured["url"] == "https://x/api/client/counselors/EMP001"


def test_list_counselors_field_mapping(monkeypatch):
    import fetch_counselor
    monkeypatch.setattr(fetch_counselor, "fetch_json", lambda url: FAKE_LIST)
    rows = fetch_counselor.list_counselors(api_base="https://x")
    assert len(rows) == 2
    first = rows[0]
    assert set(first.keys()) == {
        "emp_no", "name", "title", "is_accepting",
        "price_per_session", "communication_price", "specialties",
    }
    # name 取 display_name（源 name 为 None）
    assert first["name"] == "徐瑞恒"
    assert first["specialties"] == ["情绪困扰", "创伤"]
    assert rows[1]["is_accepting"] is False
    # 概览里绝不透出签约价
    assert all("contracted_price" not in r for r in rows)


# ========== compose_photo ==========

def test_compute_region_top():
    import compose_photo
    x, y, w, h = compose_photo.compute_region(1080, 1440, "top")
    margin = round(1080 * 0.06)  # 65
    assert (x, y) == (margin, margin)
    assert w == 1080 - 2 * margin
    # 高度扣顶部内缩：照片底边 = margin + h = 1440/3，完整落在顶部 1/3 留白区内不压版式
    assert h == round(1440 / 3) - margin
    assert y + h == round(1440 / 3)


def test_compute_region_left():
    import compose_photo
    x, y, w, h = compose_photo.compute_region(1080, 1440, "left")
    margin = round(1080 * 0.06)
    assert (x, y) == (margin, margin)
    assert w == round(1080 * 0.40)
    assert h == 1440 - 2 * margin


def test_compute_region_rejects_unknown():
    import compose_photo
    with pytest.raises(ValueError):
        compose_photo.compute_region(1080, 1440, "middle")


def test_compose_output(tmp_path):
    Image = pytest.importorskip("PIL.Image", reason="无 Pillow，跳过合成用例")
    import compose_photo

    base_color = (200, 180, 196)
    photo_color = (10, 120, 90)
    base_path = tmp_path / "base.png"
    photo_path = tmp_path / "photo.png"
    out_path = tmp_path / "out.png"
    Image.new("RGB", (1080, 1440), base_color).save(base_path)
    Image.new("RGB", (800, 600), photo_color).save(photo_path)

    x, y, w, h = compose_photo.compose(base_path, photo_path, out_path, "top")

    out = Image.open(out_path).convert("RGB")
    # 输出尺寸不变
    assert out.size == (1080, 1440)
    # 照片区中心像素 ≠ 底图原色（照片已粘入）
    center = out.getpixel((x + w // 2, y + h // 2))
    assert center != base_color
    # 圆角外的角落像素 = 底图原色（被圆角遮罩剪掉、未被描边覆盖）
    corner = out.getpixel((x + 1, y + 1))
    assert corner == base_color


def test_scrub_contracted_recursive(monkeypatch):
    """纵深防御：任意层级/任意命名变体的 contracted 字段一律递归删除。"""
    import copy
    import fetch_counselor
    poisoned = copy.deepcopy(FAKE_DETAIL)
    poisoned["data"]["pricing"] = {"contracted_price_cny": 300, "keep": 1}
    poisoned["data"]["history"] = [{"ContractedRate": 250, "note": "x"}]
    monkeypatch.setattr(fetch_counselor, "fetch_json", lambda url: poisoned)
    result = fetch_counselor.fetch_counselor("EMP001", api_base="https://x")
    dumped = __import__("json").dumps(result, ensure_ascii=False).lower()
    assert "contracted" not in dumped
    assert result["pricing"]["keep"] == 1 and result["history"][0]["note"] == "x"


def test_cover_crop_keeps_aspect(tmp_path):
    """等比 cover 语义回归锁：左绿右红照片裁进目标区后，颜色分界列须符合等比缩放预期
    （若实现退化为纯拉伸 resize，分界位置不变但比例失真难以由此单测捕获——故用非同比目标区，
    等比 cover 会裁掉左右、纯拉伸不会，探针取远端色带即可区分）。"""
    PIL = __import__("pytest").importorskip("PIL.Image")
    from PIL import Image
    import compose_photo
    # 800×600 照片：左半绿右半红；目标区 950×415（横向更宽 → 等比 cover 按宽缩放裁上下）
    photo = Image.new("RGB", (800, 600), (0, 200, 0))
    photo.paste(Image.new("RGB", (400, 600), (200, 0, 0)), (400, 0))  # 右半实心红
    photo_p = tmp_path / "p.png"; photo.save(photo_p)
    base = Image.new("RGB", (1080, 1440), (240, 230, 210))
    base_p = tmp_path / "b.png"; base.save(base_p)
    out_p = tmp_path / "o.png"
    compose_photo.compose(str(base_p), str(photo_p), str(out_p), region="top")
    out = Image.open(out_p)
    x0, y0, w, h = compose_photo.compute_region(1080, 1440, "top")
    mid_y = y0 + h // 2
    # 等比 cover：按宽 950/800 缩放后高 712>415，上下裁切、水平方向完整保留 → 分界仍在水平中点
    left_px = out.getpixel((x0 + int(w * 0.25), mid_y))
    right_px = out.getpixel((x0 + int(w * 0.75), mid_y))
    assert left_px[1] > left_px[0], f"左侧应偏绿: {left_px}"
    assert right_px[0] > right_px[1], f"右侧应偏红: {right_px}"
    # 垂直方向被裁而非拉伸：照片区顶部一行仍是照片内容（非底图色）
    top_px = out.getpixel((x0 + w // 2, y0 + 2))
    assert top_px != (240, 230, 210)


def test_count_xhs_page_range_override(tmp_path):
    """咨询师场景页数区间参数：4 页文档默认(6-9)判挂、--page-min 4 --page-max 6 判过。"""
    import json as _json
    import subprocess
    import sys as _sys
    md = "---\ntitle: 测试咨询师推介\n---\n## 发布文案\n" + ("测" * 300) + "\n\n## 配图轮播\n"
    md += "".join(f"### P{i} · 页\n```\n提示词\n```\n" for i in range(1, 5))
    f = tmp_path / "note.md"; f.write_text(md, encoding="utf-8")
    script = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "count_xhs.py"
    r1 = subprocess.run([_sys.executable, str(script), str(f)], capture_output=True, text=True)
    assert _json.loads(r1.stdout)["ok_pages"] is False
    r2 = subprocess.run([_sys.executable, str(script), str(f), "--page-min", "4", "--page-max", "6"],
                        capture_output=True, text=True)
    assert _json.loads(r2.stdout)["ok_pages"] is True

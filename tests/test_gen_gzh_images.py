"""公众号配图生成（gen_gzh_images.py）——提示词解析 / 选张 / 裁剪 / 信封契约。

与小红书 gen_images.py 同源，差异只在三处：横版 16:9、封面裁 2.35:1、
一篇 1 张封面 + 0~3 张插图。测试重点也压在这三处差异与「缺区块必须报错」上。
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-fuwuhao-operator" / "scripts"))

import pytest

import gen_gzh_images as gz

SCRIPT = (Path(__file__).parent.parent / "nbdpsy-fuwuhao-operator" / "scripts"
          / "gen_gzh_images.py")

SAMPLE_MD = """---
title: 测试长文
---

# 测试长文

正文若干。

## 配图

### 封面
```
横版封面提示词，视觉重心居中
```

### 插图1
```
插图一提示词
```

### 插图2
```
插图二提示词
```
"""


# ---- 提示词解析：### 封面 / ### 插图N + 区间内第一个围栏 ----

def test_extract_items_basic():
    items = gz.extract_items(SAMPLE_MD)
    assert [i["label"] for i in items] == ["封面", "插图1", "插图2"]
    assert items[0]["slot"] == "cover" and items[0]["num"] is None
    assert items[1]["slot"] == "illus" and items[1]["num"] == 1
    assert items[0]["prompt"] == "横版封面提示词，视觉重心居中"
    assert items[2]["prompt"] == "插图二提示词"


def test_extract_items_heading_with_suffix_and_language_tag():
    """标题可带 · 说明；围栏可带语言标记。"""
    md = """### 封面 · 主视觉
```text
封面词
```

### 插图1 · 承接第一个小标题
```
插图词
```
"""
    items = gz.extract_items(md)
    assert [i["label"] for i in items] == ["封面", "插图1"]
    assert items[0]["prompt"] == "封面词"
    assert items[1]["prompt"] == "插图词"


def test_extract_items_first_fence_only():
    md = """### 封面
```
第一个围栏
```
```
第二个围栏
```
"""
    assert gz.extract_items(md)[0]["prompt"] == "第一个围栏"


def test_extract_items_empty_input():
    assert gz.extract_items("") == []
    assert gz.extract_items("   \n\n") == []


def test_xhs_page_headings_not_extracted():
    """小红书的 `### P1` 是另一套判据，绝不能被公众号解析器捡走（否则把轮播当插图出横版）。"""
    md = """## 配图轮播

### P1 · 封面
```
小红书封面词
```
"""
    assert gz.extract_items(md) == []


# ---- 缺区块 / 缺围栏 / 缺封面 / 编号重复 都要明确报错，绝不静默 ----

def test_missing_section_raises_with_spec_pointer():
    with pytest.raises(ValueError) as exc:
        gz.validate_complete(gz.extract_items("# 只有正文\n\n没有配图区块。"))
    msg = str(exc.value)
    assert "## 配图" in msg
    assert "gzh-illustration-spec.md" in msg   # 指路规格，不让 agent 自己编


def test_missing_fence_reported_by_label():
    md = """### 封面
```
有围栏
```

### 插图1
提示词但没有围栏

### 插图2
```
有围栏
```
"""
    items = gz.extract_items(md)
    assert items[1]["prompt"] is None
    with pytest.raises(ValueError) as exc:
        gz.validate_complete(items)
    assert "插图1" in str(exc.value) and "插图2" not in str(exc.value)


def test_missing_cover_raises():
    md = """### 插图1
```
只有插图
```
"""
    with pytest.raises(ValueError) as exc:
        gz.validate_complete(gz.extract_items(md))
    assert "封面" in str(exc.value)


def test_duplicate_illus_number_raises():
    md = """### 封面
```
封面
```

### 插图1
```
甲
```

### 插图1
```
乙
```
"""
    with pytest.raises(ValueError) as exc:
        gz.validate_complete(gz.extract_items(md))
    assert "重复" in str(exc.value)


# ---- 选张：cover-only / --pages（只选插图）/ 默认全出 / 越界 ----

def _items():
    return gz.extract_items(SAMPLE_MD)


def test_select_cover_only():
    sel = gz.select_items(_items(), cover_only=True, spec=None)
    assert [i["label"] for i in sel] == ["封面"]


def test_select_default_all():
    sel = gz.select_items(_items(), cover_only=False, spec=None)
    assert [i["label"] for i in sel] == ["封面", "插图1", "插图2"]


def test_select_pages_illus_only_no_cover():
    """--pages 选的是插图编号，绝不把封面捎带出一遍（会白烧一次额度还覆盖已确认的封面）。"""
    sel = gz.select_items(_items(), cover_only=False, spec="2")
    assert [i["label"] for i in sel] == ["插图2"]


def test_parse_illus_spec():
    assert gz.parse_illus_spec("1-3") == [1, 2, 3]
    assert gz.parse_illus_spec("1,3") == [1, 3]
    assert gz.parse_illus_spec("3,1-2,2") == [1, 2, 3]   # 去重保序
    for bad in ("a-3", "1-", "0", "3-1", "", "1,x"):
        with pytest.raises(ValueError):
            gz.parse_illus_spec(bad)


def test_select_pages_out_of_range_raises():
    with pytest.raises(ValueError) as exc:
        gz.select_items(_items(), cover_only=False, spec="1-4")
    msg = str(exc.value)
    assert "插图3" in msg and "插图4" in msg


def test_warnings_anchor_and_too_many():
    items = _items()
    # 不带锚点直接出插图 → 告警
    w = gz.build_warnings(items, cover_only=False, anchor_url=None)
    assert any("anchor-url" in x for x in w)
    # 带了锚点 → 不告警
    assert gz.build_warnings(items, cover_only=False, anchor_url="https://x/a.png") == []
    # cover-only 是产锚点那一步，不告警
    assert gz.build_warnings(items[:1], cover_only=True, anchor_url=None) == []


def test_warning_more_than_three_illus():
    items = [{"slot": "illus", "num": n, "label": f"插图{n}", "prompt": "x"} for n in range(1, 5)]
    w = gz.build_warnings(items, cover_only=False, anchor_url="https://x/a.png")
    assert any("0~3 张" in x for x in w)


# ---- 落盘命名 ----

def test_image_filename():
    assert gz.image_filename({"slot": "cover", "num": None}) == "cover.jpg"
    assert gz.image_filename({"slot": "illus", "num": 1}) == "illus-01.jpg"
    assert gz.image_filename({"slot": "illus", "num": 12}) == "illus-12.jpg"


# ---- 封面裁剪：16:9(1536x1024) → 2.35:1(1536x654) 居中 ----

def test_crop_box_wide_source_crops_height():
    """1536×1024 比 2.35:1 更"高"，所以裁上下、宽度不动。"""
    box = gz.crop_box(1536, 1024, gz.COVER_RATIO)
    left, top, right, bottom = box
    assert (right - left, bottom - top) == (1536, 654)
    assert top == (1024 - 654) // 2 == 185      # 居中：上下各切 185


def test_crop_box_taller_source_crops_width():
    box = gz.crop_box(1000, 100, gz.COVER_RATIO)   # 比 2.35:1 更"宽" → 裁两侧
    left, top, right, bottom = box
    assert (bottom - top) == 100
    assert (right - left) == round(100 * gz.COVER_RATIO)
    assert left == (1000 - (right - left)) // 2


def test_crop_box_rejects_bad_input():
    for bad in ((0, 100, 2.35), (100, 0, 2.35), (100, 100, 0)):
        with pytest.raises(ValueError):
            gz.crop_box(*bad)


def test_process_cover_real_image(tmp_path):
    """端到端：喂一张真的 1536×1024 PNG，产出 cover.jpg(1536×654) + cover-raw.jpg(原尺寸)。"""
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (1536, 1024), (168, 181, 196)).save(buf, "PNG")
    cover_path, raw_path, warnings = gz.process_cover(buf.getvalue(), tmp_path)
    assert Path(cover_path).name == "cover.jpg" and Path(raw_path).name == "cover-raw.jpg"
    with Image.open(cover_path) as im:
        assert im.size == (1536, 654)
    with Image.open(raw_path) as im:
        assert im.size == (1536, 1024)          # 原图不裁，便于重裁
    assert warnings == []
    assert Path(cover_path).stat().st_size <= gz.MAX_IMAGE_BYTES


def test_crop_box_follows_actual_width_not_nominal_1536():
    """⛔ 回归锁：裁剪必须按**到手的图**现算，绝不能认死标称 1536×654。

    服务端去水印工作流会做非整数等比缩小（实测 ×0.855），所以真实到手的是 1313×876
    而不是 1536×1024。写死 1536 会让缩过的图被裁错。三种宽度都必须给出 2.35:1。"""
    for w, h in ((1536, 1024), (1313, 876), (800, 534)):
        left, top, right, bottom = gz.crop_box(w, h, gz.COVER_RATIO)
        cw, ch = right - left, bottom - top
        assert cw == w                       # 宽度不动
        assert ch == round(w / gz.COVER_RATIO)   # 高按实际宽度现算
        assert abs(cw / ch - gz.COVER_RATIO) < 0.01
    # 实测那一组的确切数字（第三次真实出图）
    assert gz.crop_box(1313, 876, gz.COVER_RATIO) == (0, (876 - 559) // 2, 1313, (876 - 559) // 2 + 559)


def test_process_cover_on_shrunk_server_image(tmp_path):
    """端到端：喂服务端实际会给的 1313×876（已缩），产出必须是 1313×559 而非 1536×654。"""
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (1313, 876), (168, 181, 196)).save(buf, "PNG")
    cover_path, raw_path, warnings = gz.process_cover(buf.getvalue(), tmp_path)
    from PIL import Image as I
    with I.open(cover_path) as im:
        assert im.size == (1313, 559)
    with I.open(raw_path) as im:
        assert im.size == (1313, 876)
    assert warnings == []


def test_process_illus_keeps_16_9(tmp_path):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (1536, 1024), (232, 216, 196)).save(buf, "PNG")
    dst = tmp_path / "illus-01.jpg"
    assert gz.process_illus(buf.getvalue(), dst) == []
    with Image.open(dst) as im:
        assert im.size == (1536, 1024)          # 插图不裁


def test_save_jpeg_quality_ladder(tmp_path):
    """尺寸够小时用最高质量；不做无谓降质。"""
    from PIL import Image
    q, size = gz.save_jpeg(Image.new("RGB", (100, 100), (0, 0, 0)), tmp_path / "a.jpg")
    assert q == gz.JPEG_QUALITIES[0] and size <= gz.MAX_IMAGE_BYTES


# ---- 终态映射 + outcome 信封 ----

def test_finalize_maps_urls_and_processes(monkeypatch, tmp_path):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (1536, 1024), (201, 214, 206)).save(buf, "PNG")
    monkeypatch.setattr(gz, "fetch_image", lambda url: buf.getvalue())
    selected = [{"slot": "cover", "num": None, "label": "封面"},
                {"slot": "illus", "num": 1, "label": "插图1"}]
    view = {"status": "done", "result": {"urls": ["/uploads/a/1.png", "/uploads/a/2.png"]}}
    out, warns = gz.finalize(view, selected, tmp_path, "https://mcp.nbdpsy.com")
    assert out[0]["url"] == "https://mcp.nbdpsy.com/uploads/a/1.png"
    assert out[0]["path"].endswith("cover.jpg") and out[0]["raw_path"].endswith("cover-raw.jpg")
    assert out[1]["path"].endswith("illus-01.jpg") and out[1]["raw_path"] is None
    assert warns == []


def test_finalize_failed_item_takes_error(monkeypatch, tmp_path):
    monkeypatch.setattr(gz, "fetch_image", lambda url: b"")
    selected = [{"slot": "cover", "num": None, "label": "封面"},
                {"slot": "illus", "num": 1, "label": "插图1"}]
    view = {"status": "done", "result": {
        "urls": ["", ""], "errors": [None, "openai_image_call_failed: rate limit exceeded"]}}
    out, _ = gz.finalize(view, selected, tmp_path, "https://mcp.nbdpsy.com")
    assert out[0]["url"] is None and "未返回该张图" in out[0]["error"]
    assert "rate limit" in out[1]["error"]


def test_summarize_outcome():
    done = [{"url": "u", "path": "p"}, {"url": "u", "path": "p"}]
    partial = [{"url": "u", "path": "p"}, {"url": None, "path": None}]
    failed = [{"url": None, "path": None}]
    assert gz.summarize_outcome(done) == "done"
    assert gz.summarize_outcome(partial) == "partial"
    assert gz.summarize_outcome(failed) == "failed"
    # 有 url 但落盘失败仍算 partial（图在服务端，--job 可补下）
    assert gz.summarize_outcome([{"url": "u", "path": None}]) == "partial"


def test_retry_hint_points_at_failed_illus_only():
    failed = [{"slot": "illus", "num": 2, "label": "插图2"}]
    hint = gz.retry_hint(failed, "https://x/a.png", cover_only=False)
    assert "--pages 2" in hint and "--anchor-url" in hint


def test_retry_hint_cover_only():
    hint = gz.retry_hint([{"slot": "cover", "label": "封面"}], None, cover_only=True)
    assert "--cover-only" in hint


def test_gone_envelope_says_resend_is_safe():
    env = gz.gone_envelope("s1", 1)
    assert env["outcome"] == "failed" and "重新发起" in env["hint"] and "额度" in env["hint"]
    assert env["images"] == []


def test_pending_envelope_forbids_resend():
    env = gz.pending_envelope("s1", 7, None, [])
    assert env["outcome"] == "pending" and "勿重发" in env["hint"] and "--job 7" in env["hint"]


def test_abs_url():
    base = "https://mcp.nbdpsy.com"
    assert gz.abs_url("/uploads/x/a.png", base) == "https://mcp.nbdpsy.com/uploads/x/a.png"
    assert gz.abs_url("https://cdn.x/y.png", base) == "https://cdn.x/y.png"
    assert gz.abs_url("", base) is None and gz.abs_url(None, base) is None


def test_create_job_prompts_hard_limit():
    with pytest.raises(ValueError) as ei:
        gz.create_job("https://x", "k", ["p"] * 100, None)
    assert "99" in str(ei.value)


def test_create_job_sends_16_9(monkeypatch):
    """核心差异：公众号恒传 aspect_ratio=16:9（拿 1536×1024 横版），不能落回默认 3:4。"""
    sent = {}

    class _Resp:
        status_code = 202
        def json(self): return {"job_id": 1, "session_id": "s1"}

    def _fake(method, url, key, payload=None, timeout=60):
        sent.update(payload=payload, url=url)
        return _Resp()

    monkeypatch.setattr(gz, "send_request", _fake)
    assert gz.create_job("https://x", "k", ["a"], "https://x/anchor.png") == (1, "s1")
    assert sent["payload"]["aspect_ratio"] == "16:9"
    assert sent["payload"]["anchor_url"] == "https://x/anchor.png"
    assert sent["url"].endswith("/api/op/consistent-images")


# ---- CLI 契约（dry-run 离线 + 缺凭据） ----

def _write_md(tmp_path, text=SAMPLE_MD):
    p = tmp_path / "post.md"
    p.write_text(text, encoding="utf-8")
    return p


_OFFLINE_ENV = {"PATH": "/usr/bin:/bin", "NBDPSY_SECRETS": "/tmp/none-gzh.env"}


def test_cli_dry_run_all(tmp_path):
    md = _write_md(tmp_path)
    p = subprocess.run([sys.executable, str(SCRIPT), "--md", str(md), "--dry-run"],
                       capture_output=True, text=True, env=_OFFLINE_ENV)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["outcome"] == "dry_run"
    assert out["selected"] == ["封面", "插图1", "插图2"]
    assert out["payload_preview"]["aspect_ratio"] == "16:9"
    assert out["filenames"] == ["cover.jpg", "illus-01.jpg", "illus-02.jpg"]
    assert "1536x654" in out["cover_crop"]
    assert out["target_url"].endswith("/api/op/consistent-images")
    assert out["images_dir"].endswith("images/post")


def test_cli_dry_run_cover_only(tmp_path):
    md = _write_md(tmp_path)
    p = subprocess.run([sys.executable, str(SCRIPT), "--md", str(md), "--cover-only", "--dry-run"],
                       capture_output=True, text=True, env=_OFFLINE_ENV)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["selected"] == ["封面"]
    assert out["warnings"] == []       # 产锚点那一步，不告警缺锚点


def test_cli_dry_run_missing_section_exit1(tmp_path):
    md = _write_md(tmp_path, "# 只有正文\n\n没有配图区块。\n")
    p = subprocess.run([sys.executable, str(SCRIPT), "--md", str(md), "--dry-run"],
                       capture_output=True, text=True, env=_OFFLINE_ENV)
    assert p.returncode == 1
    out = json.loads(p.stdout)
    assert out["outcome"] == "failed" and "gzh-illustration-spec.md" in out["error"]


def test_cli_missing_key_exit1(tmp_path):
    """非 dry-run 且缺凭据 → MISSING 提示，exit 1（不打网络）。"""
    md = _write_md(tmp_path)
    p = subprocess.run([sys.executable, str(SCRIPT), "--md", str(md), "--cover-only"],
                       capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin",
                            "NBDPSY_SECRETS": str(tmp_path / "none.env"),
                            "NBDPSY_WORKSPACE": str(tmp_path)})
    assert p.returncode == 1
    assert "MISSING:NBDPSY_XHS_API_KEY" in p.stderr

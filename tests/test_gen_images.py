import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import pytest

import gen_images as gi

SCRIPT = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "gen_images.py"
EXAMPLE_NOTE = (Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator"
                / "assets" / "example-xhs-note.md")


# ---- 提取器：判据同后端 extract_slide_prompts（### PN + 页内第一个围栏） ----

def test_extract_pages_basic():
    md = """## 配图轮播

### P1 · 封面
**页面文字**
- 大标题：测试

**绘图提示词**
```
封面提示词
```

### P2 · 内页
```
内页提示词
```
"""
    pages = gi.extract_pages(md)
    assert [p["page"] for p in pages] == ["P1", "P2"]
    assert pages[0]["prompt"] == "封面提示词"
    assert pages[1]["prompt"] == "内页提示词"


def test_extract_pages_fence_with_language_tag():
    md = """### P1 · 封面
```text
带语言标记的提示词
```
"""
    pages = gi.extract_pages(md)
    assert pages[0]["prompt"] == "带语言标记的提示词"


def test_extract_pages_first_fence_only():
    """一页取第一个围栏（后续围栏忽略）。"""
    md = """### P1 · 封面
```
第一个围栏
```
```
第二个围栏
```
"""
    assert gi.extract_pages(md)[0]["prompt"] == "第一个围栏"


def test_extract_pages_empty_input():
    assert gi.extract_pages("") == []
    assert gi.extract_pages("   \n\n") == []


def test_missing_fence_page_reported():
    """缺围栏的页 prompt=None，validate_complete 报错并列出缺哪几页。"""
    md = """### P1 · 封面
```
有围栏
```

### P2 · 内页
提示词但没有围栏

### P3 · 内页
```
有围栏
```
"""
    pages = gi.extract_pages(md)
    assert pages[1]["prompt"] is None
    with pytest.raises(ValueError) as exc:
        gi.validate_complete(pages)
    assert "P2" in str(exc.value)
    assert "P1" not in str(exc.value) and "P3" not in str(exc.value)


def test_validate_complete_rejects_empty():
    with pytest.raises(ValueError):
        gi.validate_complete([])


def test_video_reference_section_not_extracted():
    """「## 视频参考图提示词」节用 **P1** 加粗标记（非 ### PN），绝不能被提取——
    否则页数翻倍、页序错位。轮播页取的是自己的围栏，不是视频节的去文字版。"""
    md = """## 配图轮播

### P1 · 封面
**绘图提示词**
```
轮播P1提示词
```

### P2 · 内页
**绘图提示词**
```
轮播P2提示词
```

## 视频参考图提示词

**P1**
```
视频P1去文字提示词
```

**P2**
```
视频P2去文字提示词
```
"""
    pages = gi.extract_pages(md)
    assert [p["page"] for p in pages] == ["P1", "P2"]  # 只两页，不因视频节翻倍
    assert pages[0]["prompt"] == "轮播P1提示词"
    assert pages[1]["prompt"] == "轮播P2提示词"       # 取自己的围栏，不是视频节的
    assert "视频" not in pages[1]["prompt"]


# ---- 页选择解析：2-9 / 3,5 / 2-4,7 混合 / cover-only / 越界 ----

def test_parse_page_spec_range():
    assert gi.parse_page_spec("2-9") == [2, 3, 4, 5, 6, 7, 8, 9]


def test_parse_page_spec_list():
    assert gi.parse_page_spec("3,5") == [3, 5]


def test_parse_page_spec_mixed():
    assert gi.parse_page_spec("2-4,7") == [2, 3, 4, 7]
    assert gi.parse_page_spec("7,2-4,3") == [2, 3, 4, 7]  # 去重保序


def test_parse_page_spec_open_range():
    """开区间 `2-` ＝第 2 页到末页——批量出图排除已确认封面 P1 的标准写法（SKILL.md 工序③）。
    以前这写法只在文档里有、代码不认，实跑必报错，人一急就把 --pages 整个删掉 → 封面被重出覆盖。"""
    assert gi.parse_page_spec("2-", max_page=6) == [2, 3, 4, 5, 6]
    assert gi.parse_page_spec("2-", max_page=9) == [2, 3, 4, 5, 6, 7, 8, 9]
    assert gi.parse_page_spec("2-", max_page=2) == [2]           # 只两页的稿子＝只出 P2
    assert gi.parse_page_spec("3-,1", max_page=4) == [1, 3, 4]   # 与其它写法混用


def test_parse_page_spec_open_range_needs_max_page():
    """不知道总页数时开区间必须报错，⛔ 不许默认成某个页数（猜错＝静默出错页）。"""
    with pytest.raises(ValueError) as exc:
        gi.parse_page_spec("2-")
    assert "总页数" in str(exc.value)


def test_parse_page_spec_open_range_start_beyond_total():
    with pytest.raises(ValueError) as exc:
        gi.parse_page_spec("7-", max_page=6)
    assert "超出本篇总页数" in str(exc.value)


def test_parse_page_spec_invalid():
    # `-2`（缺起始页）与 `a-`（起始页不是数字）仍是非法：开区间只放开"缺结束页"这一种
    for bad in ("a-3", "-2", "a-", "0", "3-1", "", "1,x"):
        with pytest.raises(ValueError):
            gi.parse_page_spec(bad, max_page=9)


def _pages(n):
    return [{"page": f"P{i}", "prompt": f"提示词{i}"} for i in range(1, n + 1)]


def test_select_cover_only():
    sel = gi.select_pages(_pages(6), cover_only=True, spec=None)
    assert [p["page"] for p in sel] == ["P1"]


def test_select_default_all():
    sel = gi.select_pages(_pages(6), cover_only=False, spec=None)
    assert [p["page"] for p in sel] == ["P1", "P2", "P3", "P4", "P5", "P6"]


def test_select_pages_spec_preserves_doc_order():
    sel = gi.select_pages(_pages(9), cover_only=False, spec="2-4,7")
    assert [p["page"] for p in sel] == ["P2", "P3", "P4", "P7"]


def test_select_pages_out_of_range_raises():
    with pytest.raises(ValueError) as exc:
        gi.select_pages(_pages(6), cover_only=False, spec="2-9")
    msg = str(exc.value)
    assert "P7" in msg and "P8" in msg and "P9" in msg  # 越界页被点名
    assert "6 页" in msg


def test_select_pages_open_range_excludes_cover_whatever_the_length():
    """同一条命令 `--pages 2-` 对 6 页 / 9 页稿子都成立，且都不含 P1（这正是它存在的理由）。"""
    for n in (6, 8, 9):
        sel = gi.select_pages(_pages(n), cover_only=False, spec="2-")
        assert [p["page"] for p in sel] == [f"P{i}" for i in range(2, n + 1)]


# ---- 落盘命名两位数 + 相对 URL 拼绝对 ----

def test_image_filename_two_digits():
    assert gi.image_filename("P1") == "P01.png"
    assert gi.image_filename("P9") == "P09.png"
    assert gi.image_filename("P12") == "P12.png"


def test_abs_url_relative_to_absolute():
    base = "https://mcp.nbdpsy.com"
    assert gi.abs_url("/uploads/x/P01.png", base) == "https://mcp.nbdpsy.com/uploads/x/P01.png"
    assert gi.abs_url("uploads/x/y.png", base) == "https://mcp.nbdpsy.com/uploads/x/y.png"
    assert gi.abs_url("https://cdn.x/y.png", base) == "https://cdn.x/y.png"  # 已绝对不动
    assert gi.abs_url("", base) is None
    assert gi.abs_url(None, base) is None


# ---- 终态映射：urls 对齐页序、命名两位数、失败位取 errors ----

def test_finalize_maps_urls_and_names_files(monkeypatch, tmp_path):
    downloaded = []
    monkeypatch.setattr(gi, "download_image", lambda url, dst: downloaded.append((url, str(dst))))
    selected = [{"page": "P2"}, {"page": "P10"}]
    view = {"status": "done", "result": {"urls": ["/uploads/a/x1.png", "/uploads/a/x2.png"]}}
    out = gi.finalize(view, selected, tmp_path, "https://mcp.nbdpsy.com")
    assert out[0]["url"] == "https://mcp.nbdpsy.com/uploads/a/x1.png"
    assert out[0]["path"].endswith("P02.png") and out[0]["error"] is None
    assert out[1]["path"].endswith("P10.png")   # 已两位数保持
    assert len(downloaded) == 2


def test_finalize_failed_page_takes_error(monkeypatch, tmp_path):
    """额度/限流表现为 done + urls 有缺位 + errors 含文案——该页 url=None、error 透传。"""
    monkeypatch.setattr(gi, "download_image", lambda url, dst: None)
    selected = [{"page": "P1"}, {"page": "P2"}]
    view = {"status": "done", "result": {
        "urls": ["/uploads/a/x1.png", ""],
        "errors": [None, "openai_image_call_failed: rate limit exceeded"]}}
    out = gi.finalize(view, selected, tmp_path, "https://mcp.nbdpsy.com")
    assert out[0]["url"] and out[0]["path"]
    assert out[1]["url"] is None and out[1]["path"] is None
    assert "rate limit" in out[1]["error"]


def test_error_for_tolerant_shapes():
    assert gi._error_for(["", "boom"], 1, "P2") == "boom"                 # 等长消息数组
    assert "缺图" in gi._error_for([{"page": "P2", "error": "缺图"}], 1, "P2")  # 失败记录数组
    assert gi._error_for({"1": "字典按下标"}, 1, "P2") == "字典按下标"        # 字典按下标
    assert gi._error_for({"P2": "字典按页号"}, 1, "P2") == "字典按页号"        # 字典按页号
    assert gi._error_for(None, 0, "P1") is None


def test_summarize_outcome():
    done = [{"url": "u", "path": "p"}, {"url": "u", "path": "p"}]
    partial = [{"url": "u", "path": "p"}, {"url": None, "path": None}]
    failed = [{"url": None, "path": None}, {"url": None, "path": None}]
    assert gi.summarize_outcome(done) == "done"
    assert gi.summarize_outcome(partial) == "partial"
    assert gi.summarize_outcome(failed) == "failed"
    # 有 url 但下载失败（path=None）仍算 partial（图在服务端，可 --job 补下）
    dl_fail = [{"url": "u", "path": "p"}, {"url": "u", "path": None}]
    assert gi.summarize_outcome(dl_fail) == "partial"


# ---- CLI 契约（dry-run 离线 + 缺凭据） ----

def test_cli_dry_run_extracts_all_pages():
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--note", str(EXAMPLE_NOTE), "--dry-run"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "NBDPSY_SECRETS": "/tmp/none.env"})
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["outcome"] == "dry_run"
    assert out["selected_pages"] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert out["target_url"].endswith("/api/op/consistent-images")


def test_cli_dry_run_cover_only():
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--note", str(EXAMPLE_NOTE), "--cover-only", "--dry-run"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "NBDPSY_SECRETS": "/tmp/none.env"})
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["selected_pages"] == ["P1"]
    assert out["warnings"] == []  # cover-only 不告警缺锚点（它就是产锚点的第一步）


def test_cli_missing_key_exit1(tmp_path):
    """非 dry-run 且缺凭据 → MISSING 提示，exit 1（不打网络）。"""
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--note", str(EXAMPLE_NOTE), "--cover-only"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "NBDPSY_SECRETS": str(tmp_path / "none.env"),
             "NBDPSY_WORKSPACE": str(tmp_path)})
    assert p.returncode == 1
    assert "MISSING:NBDPSY_XHS_API_KEY" in p.stderr


# ---- v1.25.0 生图复活：台账 404=gone(可安全重发) + prompts 硬上限 ----

class _Resp404:
    status_code = 404
    text = "x"
    def json(self): return {}


def test_poll_job_404_returns_gone_and_envelope(monkeypatch):
    """台账失效（server 重启，终态只留 2h）→ gone；生图与删除相反，重发安全 → failed 语义引导重发。"""
    import gen_images
    monkeypatch.setattr(gen_images, "send_request", lambda *a, **k: _Resp404())
    assert gen_images.poll_job("https://x", "k", "s1", 1, timeout=0) == {"status": "gone"}
    env = gen_images.gone_envelope("s1", 1)
    assert env["outcome"] == "failed" and "重新发起" in env["hint"] and "额度" in env["hint"]


def test_create_job_prompts_hard_limit():
    """单次 >99 条提示词客户端硬拦（服务端 422）。"""
    import gen_images
    import pytest
    with pytest.raises(ValueError) as ei:
        gen_images.create_job("https://x", "k", ["p"] * 100, None)
    assert "99" in str(ei.value)


# ---- 闸门 A 生产端：凭证记「单出 or 批量顺带」（2026-08-14 复验 S4 证据 3 · 裁决 B）----

COVER_PROMPT = "封面版式：通栏大字压顶，主色 #2F4F4F，图中中文文字「复杂性创伤」"


def _receipt(tmp_path, cover_only, run_pages, prompt=COVER_PROMPT):
    cover = tmp_path / "P01.png"
    cover.write_bytes(b"\x89PNG fake")
    mp, warns = gi.write_cover_receipt(
        cover, prompt, "sess-1", 42, "https://x/anchor.png",
        {"套名": "图文", "version": 3}, cover_only=cover_only, run_pages=run_pages)
    return cover, mp, json.loads(mp.read_text(encoding="utf-8")), warns


def test_receipt_records_cover_only_and_run_pages_single(tmp_path):
    _c, _mp, meta, warns = _receipt(tmp_path, True, "1")
    assert meta["cover_only"] is True and meta["run_pages"] == "1"
    assert not [w for w in warns if "批量顺带" in w]


def test_receipt_records_batch_run_and_warns_on_the_spot(tmp_path):
    """批量顺带出的 P1：凭证如实记 cover_only=false，并当场告知发布会被拒（别等到发布才发现）。"""
    _c, _mp, meta, warns = _receipt(tmp_path, False, "all")
    assert meta["cover_only"] is False and meta["run_pages"] == "all"
    assert any("批量顺带" in w and "--confirm-cover" in w and "--cover-only" in w for w in warns)


def test_run_pages_spec_four_branches():
    """run_pages 是**字符串**证据串，四分支（2026-08-14 契约终稿）：
    传了 --pages 原样记 / --cover-only 记 "1" / 都没传记 "all" / --job 按状态文件页号还原。
    ⛔ --cover-only 不许记 "all"——那是凭证自己说谎（这一跑只请求了 P1）。"""
    assert gi.run_pages_spec(False, "2-8") == "2-8"
    assert gi.run_pages_spec(False, "1,3") == "1,3"
    assert gi.run_pages_spec(True, None) == "1"
    assert gi.run_pages_spec(False, None) == "all"
    assert gi.run_pages_spec(False, None, ["P2", "P3", "P4"]) == "2,3,4"
    assert gi.run_pages_spec(False, None, ["P1"]) == "1"   # 复查一跑只出过 P1 → 仍算单出
    assert gi.run_pages_spec(True, "2-8") == "1"           # 两个都给：以 --cover-only 为准（实际只出 P1）


def test_is_cover_single_derives_from_requested_pages():
    """判据是这一跑请求了哪些页：只请求 P1 ＝单出；批量跑里 P1 出成了不算单出。"""
    assert gi.is_cover_single(False, "1") is True
    assert gi.is_cover_single(True, "all") is True           # 显式 --cover-only
    assert gi.is_cover_single(False, "1,2") is False
    assert gi.is_cover_single(False, "2-8") is False
    assert gi.is_cover_single(False, "all") is False


def test_maybe_write_cover_receipt_passes_run_pages(tmp_path):
    note = tmp_path / "post-01.md"
    note.write_text(
        "---\n故事线: 现象 → 机制\n---\n\n## 配图轮播\n\n"
        f"### P1 · 封面\n**论点行**：一句主张\n\n```\n{COVER_PROMPT}\n```\n",
        encoding="utf-8")
    cover = tmp_path / "P01.png"
    cover.write_bytes(b"\x89PNG fake")
    pages_out = [{"page": "P1", "path": str(cover), "url": "https://x/P01.png", "error": None},
                 {"page": "P2", "path": str(tmp_path / "P02.png"), "url": "u", "error": None}]
    mp, _warns = gi.maybe_write_cover_receipt(
        pages_out, note, "s1", 7, None, None, cover_only=False, run_pages="1,2")
    meta = json.loads(Path(mp).read_text(encoding="utf-8"))
    assert meta["cover_only"] is False and meta["run_pages"] == "1,2"

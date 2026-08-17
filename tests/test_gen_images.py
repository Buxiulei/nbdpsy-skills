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


def test_receipt_records_gates(tmp_path):
    """三闸结论进凭证，发布端/审查端据此核「这次到底走没走」（⛔ 别只能看到"出过图"）。"""
    cover = tmp_path / "P01.png"
    cover.write_bytes(b"\x89PNG fake")
    gates = {"reader": True, "term": True, "seller_view": True}
    mp, warns = gi.write_cover_receipt(
        cover, COVER_PROMPT, "s1", 1, None, {"套名": "图文", "version": 3},
        cover_only=True, run_pages="1", gates=gates)
    meta = json.loads(mp.read_text(encoding="utf-8"))
    assert meta["gates"] == gates
    assert not [w for w in warns if "方法论闸门" in w]


def test_receipt_records_term_gate_skip_and_warns(tmp_path):
    """逃生口不是静默绕过：term=false + term_gate_skipped=true 落进凭证，并当场告警。"""
    cover = tmp_path / "P01.png"
    cover.write_bytes(b"\x89PNG fake")
    gates = {"reader": True, "term": False, "seller_view": True,
             "term_gate_skipped": True, "term_gate_skip_reason": "--skip-term-gate（…）"}
    mp, warns = gi.write_cover_receipt(
        cover, COVER_PROMPT, "s1", 1, None, {"套名": "图文", "version": 3},
        cover_only=True, run_pages="1", gates=gates)
    meta = json.loads(mp.read_text(encoding="utf-8"))
    assert meta["gates"]["term"] is False and meta["gates"]["term_gate_skipped"] is True
    assert any("term_gate_skipped" in w and "可追责" in w for w in warns)


def test_receipt_gates_null_means_not_run(tmp_path):
    """`--job` 复查拿不到稿件时 gates=null ＝**本次没跑过**，⛔ 不等于通过。"""
    _c, _mp, meta, _w = _receipt(tmp_path, True, "1")
    assert meta["gates"] is None


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


# ================= 三条写作方法论闸门（2026-08-17）=================
# 老板令：三条方法论必须**被执行**不是**被写下**。验收口径＝「下一个执行者完全不看规格，
# 会不会被拦住？」——所以每闸两类测试都要有：**拒跑**（真拦得住）+ **合规不误伤**（不乱拦）。

READER_OK = ("身份阶段（刚被上级随口批评、还没跟任何人说起这事的 28 岁职场女性）"
             "｜痛点（一句话就在工位上僵住、事后反复回放，骂自己玻璃心）"
             "｜最容易误解或焦虑的点（以为这是性格缺陷、怕被说矫情所以更晚开口）")
DEFAULT_PAGES = [("P1", "一句方案再改改就在工位上僵住，那不是玻璃心", "- [hero] 不是玻璃心")]


def _note(reader=READER_OK, storyline="现象 → 机制 → 纠错 → 怎么办", pages=None):
    """拼一份最小的、只在被测那一点上有问题的稿件；pages=[(页, 论点行, 页面文字块)]。"""
    fm = ["---"]
    if reader is not None:
        fm.append(f"读者: {reader}")
    if storyline is not None:
        fm.append(f"故事线: {storyline}")
    fm.append("---")
    body = ["", "## 配图轮播", ""]
    for label, claim, page_text in (pages if pages is not None else DEFAULT_PAGES):
        body += [f"### {label} · 页", f"**论点行**：{claim}", ""]
        if page_text:
            body += ["**页面文字**", page_text, ""]
        body += ["**绘图提示词**", "```", "喂给模型的提示词，读者看不到", "```", ""]
    return "\n".join(fm + body)


def _gate(md, **kw):
    """跑 R4 结构闸门，返回 gates；不过则抛 ValueError（＝拒跑）。"""
    return gi.validate_structure(md, gi.extract_pages(md), **kw)


# ---- 闸 1 · 读者必填（方法论③：下笔前先钉死读者是谁）----

def test_reader_gate_rejects_missing_field():
    with pytest.raises(ValueError) as exc:
        _gate(_note(reader=None))
    msg = str(exc.value)
    assert "读者" in msg and "不许立刻动笔" in msg
    assert "身份阶段（…）｜痛点（…）｜最容易误解或焦虑的点（…）" in msg   # 报错要给「怎么改」


def test_reader_gate_rejects_two_segments():
    """三段少一段＝少答了一个决定这篇怎么写的问题。"""
    with pytest.raises(ValueError) as exc:
        _gate(_note(reader="身份阶段（28 岁职场女性，刚被批评）｜痛点（一句话就僵住、反复回放）"))
    assert "三段" in str(exc.value)


def test_reader_gate_rejects_too_short_answer():
    """标签不算答案：`身份阶段（女性）` 整段够长、答案只有两个字。"""
    with pytest.raises(ValueError) as exc:
        _gate(_note(reader="身份阶段（女性）｜痛点（一句话就僵住、反复回放停不下来）"
                           "｜最容易误解或焦虑的点（以为是性格缺陷不敢开口）"))
    msg = str(exc.value)
    assert "第 1 段（身份阶段）" in msg and "≥6 字" in msg


def test_reader_gate_rejects_vague_identity():
    with pytest.raises(ValueError) as exc:
        _gate(_note(reader="身份阶段（对心理感兴趣的人）｜痛点（一句话就僵住、反复回放停不下来）"
                           "｜最容易误解或焦虑的点（以为是性格缺陷不敢开口）"))
    msg = str(exc.value)
    assert "空泛值" in msg and "没定义读者" in msg


def test_reader_gate_passes_concrete_reader():
    assert _gate(_note())["reader"] is True


def test_reader_gate_not_fooled_by_vague_word_inside_specific_identity():
    """误伤控制（实证：黄金范例首版就栽在这）——「还没跟**任何人**说起这事的 28 岁职场女性」
    是全仓最具体的读者定义之一，空泛词出现在长描述**里面**是正常中文，不该拦。"""
    assert _gate(_note())["reader"] is True
    assert "任何人" in READER_OK          # 确认这条测试真的踩在空泛词上，不是空跑


def test_reader_gate_ignores_trailing_yaml_comment():
    """本仓 frontmatter 普遍行尾挂 `# 注释`，剥不掉会被当成第三段的答案（假绿）。"""
    reader = "身份阶段（女）｜痛点（一句话就僵住、反复回放停不下来）｜最容易误解或焦虑的点（怕被说矫情）"
    with pytest.raises(ValueError) as exc:
        _gate(_note(reader=reader + "   # R4 硬顺序第①步"))
    assert "第 1 段（身份阶段）" in str(exc.value)


# ---- 闸 2 · 术语必定义（方法论①：术语只能定义或删除，不许悬空）----

def _term_pages(page_text, label="P1"):
    return [(label, "一句能独立成立的主张，读者带得走", page_text)]


def test_term_gate_rejects_undefined_term():
    with pytest.raises(ValueError) as exc:
        _gate(_note(pages=_term_pages("- 大标题：僵住的那一刻，其实是解离\n- 副标题：身体先替你踩了刹车")))
    msg = str(exc.value)
    assert "P1「解离」" in msg
    assert "删掉这句，读者会少一个事实还是少一个论据" in msg     # 方法论①的判断句原话
    assert "在同页加一句人话定义" in msg and "换成读者自己会说的词" in msg   # 两条路都给


@pytest.mark.parametrize("line", [
    "- 大标题：僵住的那一刻其实是解离（像是从自己身体里飘出去了）",     # 括号内解释
    "- 大标题：解离：像是从自己身体里飘出去了",                       # 冒号后紧跟解释
    "- 大标题：所谓解离，说白了就是像从自己身体里飘出去",             # 定义句式
])
def test_term_gate_accepts_in_page_definition(line):
    assert _gate(_note(pages=_term_pages(line)))["term"] is True


def test_term_gate_only_judges_first_occurrence_page():
    """只判首次出现那一页：P1 已经讲开了，P2 再用不必每页重讲一遍（否则页页返工）。"""
    pages = [("P1", "身体先替你踩了刹车", "- 大标题：解离（像是从自己身体里飘出去了）"),
             ("P2", "它不是你想控制就能控制的", "- 大标题：解离发生时，讲道理是关不掉的")]
    assert _gate(_note(pages=pages))["term"] is True


def test_term_gate_ignores_prompt_fence_and_claim_line():
    """围栏里的术语是**喂模型的**、论点行是写给自己的，读者都看不到 → 不判（误伤控制）。"""
    md = _note(pages=[("P1", "画出解离那一刻的身体感受", None)])
    assert "解离" in md                      # 术语确实在稿子里（论点行 + 围栏外没有页面文字）
    assert _gate(md)["term"] is True


def test_term_gate_ignores_citation_and_book_title():
    """出现在文献名/数据出处里不算拿黑话砸读者（误伤控制）。"""
    pages = _term_pages("- 底部小字：数据来源：《躯体化障碍研究综述》（2019）\n- 大标题：你不是想太多")
    assert _gate(_note(pages=pages))["term"] is True


def test_term_gate_skip_flag_records_but_does_not_block():
    """逃生口默认关闭；用了不拦人，但凭证里记 term_gate_skipped=true（可追责，不是静默绕过）。"""
    md = _note(pages=_term_pages("- 大标题：僵住的那一刻，其实是解离"))
    with pytest.raises(ValueError):
        _gate(md)                                  # 默认：拒跑
    gates = _gate(md, skip_term_gate=True)         # 显式跳过：放行
    assert gates["term"] is False and gates["term_gate_skipped"] is True
    assert "--skip-term-gate" in gates["term_gate_skip_reason"]


# ---- 闸 3 · 禁卖方视角（方法论②：用户关心我的问题有没有被看见）----

def test_seller_gate_rejects_claim_line():
    with pytest.raises(ValueError) as exc:
        _gate(_note(pages=[("P1", "本篇带你了解复杂性创伤的三个特征", "- [hero] 三个特征")]))
    msg = str(exc.value)
    assert "P1 论点行「本篇带你」" in msg and "P1 论点行「带你了解」" in msg   # 命中词点名
    assert "用户不关心你提供什么" in msg and "读者的处境或困惑" in msg


def test_seller_gate_rejects_cover_page_text():
    """封面 hero 就在页面文字块里——卖方腔写在 hero 上，比写在论点行上更致命。"""
    with pytest.raises(ValueError) as exc:
        _gate(_note(pages=[("P1", "一句方案再改改就僵住，那不是玻璃心",
                            "- [hero] 我们的咨询师带你走出创伤")]))
    assert "封面页面文字" in str(exc.value)


def test_seller_gate_allows_negated_teaching():
    """「没人教你怎么跟情绪相处」是**读者的处境**，不是卖方腔——误伤控制。"""
    assert _gate(_note(pages=[("P1", "没人教你怎么跟这种情绪相处，你只好骂自己", "- [hero] 没人教过你")])
                 )["seller_view"] is True


def test_seller_gate_passes_reader_perspective():
    assert _gate(_note())["seller_view"] is True


# ---- 页面文字提取（两闸都建在它上面）----

def test_page_text_two_shapes_and_exclusions():
    md = _note(pages=[("P1", "论点", "- [hero] 不是玻璃心\n> 判断与理由：这句才是 hero")])
    p1 = gi.extract_pages(md)[0]
    assert "不是玻璃心" in p1["page_text"]
    assert "判断与理由" not in p1["page_text"]          # `>` 是写给人看的，不入图
    assert "喂给模型" not in p1["page_text"]            # 围栏内是喂模型的
    inline = ("---\n读者: x\n故事线: y\n---\n\n### P1 · 页\n**论点行**：论点\n"
              "**页面文字**：主标题「先松的是这一环」；副题「六个成分不是齐步走」\n"
              "**绘图提示词**\n```\n提示词\n```\n")
    assert "先松的是这一环" in gi.extract_pages(inline)[0]["page_text"]   # 单行式也认


# ---- CLI 契约：闸门挂在**出图必经**的入口上（不是只挂在函数上）----

def test_cli_dry_run_reports_gates():
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--note", str(EXAMPLE_NOTE), "--dry-run"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "NBDPSY_SECRETS": "/tmp/none.env"})
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["gates"] == {"reader": True, "term": True, "seller_view": True}
    assert out["reader"].startswith("身份阶段（")


def test_cli_rejects_note_without_reader(tmp_path):
    """下一个执行者完全不看规格、直接跑出图 → 在这里被拦住，且拿到「怎么改」。"""
    note = tmp_path / "post-01.md"
    note.write_text(_note(reader=None), encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--note", str(note), "--dry-run"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "NBDPSY_SECRETS": "/tmp/none.env"})
    assert p.returncode == 1
    out = json.loads(p.stdout)
    assert out["outcome"] == "failed" and "缺 `读者` 字段" in out["error"]


# ---- 2026-08-17 干跑报告四条缝的修补（「拦住有没有做」→「拦住做得对不对」） ----

def test_卖方腔同义替换也拦得住_主语判据():
    """缝①：纯词表挡不住同义替换。干跑实测这四句全部溜过，现在必须全拦。"""
    for claim in ["本机构擅长处理这类困扰",
                  "NBDpsy 的咨询师可以陪你走一段",
                  "咨询师能帮你把它整合回来",
                  "专业心理咨询在这件事上是有用的"]:
        pages = [{"page": "P1", "claim": claim, "page_text": "", "prompt": "x"}]
        assert gi.find_seller_voice(pages), f"漏网：{claim}"


def test_读者处境句不被主语判据误伤():
    """反向守卫：句里带否定＝读者的处境，不是卖方腔（误伤会逼人把好句改坏）。"""
    for claim in ["没人教你怎么跟这种情绪相处，你只好骂自己",
                  "谁也没帮你把这件事解释清楚"]:
        pages = [{"page": "P1", "claim": claim, "page_text": "", "prompt": "x"}]
        assert not gi.find_seller_voice(pages), f"误伤：{claim}"


def _reader_ok_md(claim, storyline="现象 → 机制 → 纠错"):
    return ("---\n读者: 身份阶段（刚被上级随口批评的 28 岁职场女性）｜"
            "痛点（一句话就在工位上僵住、事后反复回放）｜"
            f"最容易误解或焦虑的点（以为这是性格缺陷、怕被说矫情）\n故事线: {storyline}\n---\n")


def test_论点行是名词短语或占位词时拒跑():
    """缝②：报错文案一直写着「名词短语不算」，2026-08-17 起真查。"""
    for bad in ["解离", "机制", "解离的神经机制", "待补", "aaa。"]:
        pages = [{"page": "P1", "claim": bad, "page_text": "", "prompt": "x"}]
        with pytest.raises(ValueError, match="论点行不是「一句话」"):
            gi.validate_structure(_reader_ok_md(bad), pages)


def test_好论点行一律不误伤():
    """反向守卫：真实笔记里的好论点行（含动宾短语）必须全过——宁放勿伤。"""
    for good in ["没人教你怎么跟这种情绪相处，你只好骂自己", "深呼吸是在帮倒忙",
                 "呼吸乱掉是结果不是原因", "画出解离那一刻的身体感受"]:
        pages = [{"page": "P1", "claim": good, "page_text": "", "prompt": "x"}]
        gi.validate_structure(_reader_ok_md(good), pages)   # 不抛即通过


def test_围栏内引号文字里的术语也要定义():
    """缝③：把术语全塞进绘图提示词的引号里＝图上照样出现未定义黑话。"""
    pages = [{"page": "P1", "claim": "身体先替你按了静音键，你才发现自己不在场",
              "page_text": "- 大标题：那一刻你不在场",
              "prompt": '暖米白底，标题「解离的神经机制」居中，柔和扁平插画'}]
    assert ("P1", "解离") in gi.find_undefined_terms(pages)


def test_围栏里的画风描述不算图内文字():
    """反向守卫：提示词里的画风/构图/配色是喂模型的，读者看不到，⛔ 不许扫。"""
    pages = [{"page": "P1", "claim": "身体先替你按了静音键，你才发现自己不在场",
              "page_text": "- 大标题：那一刻你不在场",
              "prompt": "画出解离那一刻的身体感受，暖米白底，柔和扁平插画"}]
    assert not gi.find_undefined_terms(pages)


def test_故事线只写主题不成推进时拒跑():
    """缝④：「故事线: 讲清楚解离」照过闸＝那不是故事线是主题。"""
    pages = [{"page": "P1", "claim": "深呼吸其实是在帮倒忙", "page_text": "", "prompt": "x"}]
    with pytest.raises(ValueError, match="不成推进"):
        gi.validate_structure(_reader_ok_md("x", storyline="讲清楚解离"), pages)


def test_两步以上推进的故事线放行():
    pages = [{"page": "P1", "claim": "深呼吸其实是在帮倒忙", "page_text": "", "prompt": "x"}]
    gi.validate_structure(_reader_ok_md("x", storyline="现象 → 机制 → 怎么办"), pages)
    gi.validate_structure(_reader_ok_md("x", storyline="先打翻常识；再讲机制；最后给做法"), pages)


# ---- hint 必须随错误类型变（2026-08-17 服务号线 429 实证） ----

def _hint_for(err_text, cover_only=True):
    pages = [{"page": "P1", "url": None, "path": None, "error": err_text}]
    return gi.retry_hint(["P1"], None, cover_only, pages)


def test_额度耗尽的hint要说充值而不是调提示词():
    """服务号线 15:10 真实回执：hint 说「调提示词后重跑」，照做只会反复撞 429 而不去充钱。
    **不随错误变的 hint 比没有更坏**——它把人导向一条注定失败的路。"""
    h = _hint_for("openai_image_call_failed: Error code: 429 - {'error': {'message': "
                  "'You have no credits remaining.', 'type': 'insufficient_quota', "
                  "'code': 'credit_balance_exhausted'}}")
    assert "充值" in h and "额度" in h
    assert "调提示词无用" in h, "必须明说调提示词没用，否则人还是会去改提示词"
    assert "billing" in h, "要给充值入口"


def test_限流的hint要说等待而不是充值也不是改提示词():
    h = _hint_for("Error code: 429 - {'error': {'message': 'Rate limit reached', "
                  "'type': 'rate_limit_error'}}")
    assert "限流" in h and "重跑" in h
    assert "充值" not in h, "限流不是额度问题，说充值会误导"


def test_内容策略拒绝才该教改提示词():
    h = _hint_for("Your request was rejected as a result of our safety system (content_policy_violation)")
    assert "改提示词" in h or "提示词" in h
    assert "充值" not in h


def test_未知错误保持原通用hint():
    """反向守卫：认不出的错误别乱分流，回到原来的通用建议。"""
    h = _hint_for("connection reset by peer")
    assert "风格闸门第一步" in h


def test_分流对批量出图路径同样生效():
    """cover_only=False 的批量路径也要分流，不能只在封面路径上做。"""
    h = _hint_for("Error code: 429 - insufficient_quota", cover_only=False)
    assert "充值" in h

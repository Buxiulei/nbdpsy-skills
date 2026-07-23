import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import pytest

NOTE = Path(__file__).parent / "fixtures" / "note.md"


def _make_note_tree(tmp_path, pages=3, name="post-01"):
    """临时笔记 + 配图目录（P01…P0N）。"""
    note = tmp_path / f"{name}.md"
    note.write_text(NOTE.read_text(encoding="utf-8"), encoding="utf-8")
    img_dir = tmp_path / "images" / name
    img_dir.mkdir(parents=True)
    for i in range(1, pages + 1):
        (img_dir / f"P{i:02d}.png").write_bytes(b"\x89PNG fakebytes")
    return note, img_dir


# ---- 解析：发布文案块 / 话题拆分 ----

def test_extract_publish_text_and_topics_from_fixture():
    import publish_note
    meta, body = publish_note.parse_frontmatter(NOTE.read_text(encoding="utf-8"))
    text = publish_note.extract_publish_text(body)
    content, topics = publish_note.split_content_topics(text, meta)
    # 正文保留危机声明、剥掉末尾可见标签行（话题单独传 API，避免正文重复）
    assert "12356" in content
    assert not content.rstrip().endswith("#自我觉察")
    # 话题来自 frontmatter hashtags，去 # 去重
    assert topics[0] == "心理科普" and "CPTSD" in topics
    assert all(not t.startswith("#") for t in topics)


def test_topics_fallback_to_tag_line_when_no_frontmatter():
    import publish_note
    content, topics = publish_note.split_content_topics("正文内容\n\n#标签A #标签B", {})
    assert content == "正文内容"
    assert topics == ["标签A", "标签B"]


def test_markdown_emphasis_stripped_before_publish():
    """小红书正文不渲染 Markdown：**加粗**/`code` 必须剥掉，否则笔记出现字面星号。"""
    import publish_note
    content, _ = publish_note.split_content_topics(
        "这可能是**复杂性创伤（CPTSD）**，试试 `深呼吸`，*别慌*。", {})
    assert "**" not in content and "`" not in content
    assert "复杂性创伤（CPTSD）" in content and "深呼吸" in content and "别慌" in content
    # fixture 真实笔记同样干净
    meta, body = publish_note.parse_frontmatter(NOTE.read_text(encoding="utf-8"))
    content2, _ = publish_note.split_content_topics(publish_note.extract_publish_text(body), meta)
    assert "**" not in content2


def test_missing_publish_section_raises():
    import publish_note
    with pytest.raises(ValueError):
        publish_note.extract_publish_text("## 别的块\n没有发布文案")


# ---- 配图收集与 base64 形态 ----

def test_collect_images_sorted_and_b64(tmp_path):
    import publish_note
    note, img_dir = _make_note_tree(tmp_path, pages=3)
    paths = publish_note.collect_images(note, None)
    assert [p.name for p in paths] == ["P01.png", "P02.png", "P03.png"]
    items = publish_note.b64_items(paths)
    assert items[0]["ext"] == "png" and items[0]["b64"]


def test_collect_images_missing_dir_raises(tmp_path):
    import publish_note
    note = tmp_path / "post-09.md"
    note.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        publish_note.collect_images(note, None)


# ---- 约束 warning（服务端静默截断，提前提示） ----

def test_build_warnings_boundaries():
    import publish_note
    w = publish_note.build_warnings("超" * 21, "字" * 901, [str(i) for i in range(11)], [])
    joined = "；".join(w)
    assert "标题" in joined and "正文" in joined and "话题" in joined and "图片" in joined
    assert publish_note.build_warnings("题", "文", ["t"], ["1.png"]) == []


# ---- 错误体两套形状（401/422 detail，403/404/400/500 error） ----

def test_api_error_both_shapes():
    import publish_note
    class R1:
        status_code = 403
        text = "x"
        def json(self): return {"error": "无该账号权限"}
    class R2:
        status_code = 401
        text = "x"
        def json(self): return {"detail": "apikey 无效"}
    class R3:
        status_code = 500
        text = "<html>bad</html>"
        def json(self): raise ValueError
    assert "无该账号权限" in publish_note.api_error(R1())
    assert "apikey 无效" in publish_note.api_error(R2())
    assert "500" in publish_note.api_error(R3())


# ---- 账号解析 ----

def test_resolve_account_digit_fast_path():
    import publish_note
    assert publish_note.resolve_account("https://x", "k", "7")[0] == 7


def test_resolve_account_by_name_and_cookie_warn(monkeypatch):
    import publish_note
    accounts = [{"id": 1, "name": "主号", "nickname": "小红", "cookie_status": "invalid"},
                {"id": 2, "name": "副号", "nickname": "小蓝", "cookie_status": "valid"}]
    monkeypatch.setattr(publish_note, "list_accounts", lambda *a: accounts)
    aid, label, warn = publish_note.resolve_account("https://x", "k", "主号")
    assert aid == 1 and warn and "cookie" in warn
    aid2, _, warn2 = publish_note.resolve_account("https://x", "k", "小蓝")
    assert aid2 == 2 and warn2 is None
    with pytest.raises(ValueError):
        publish_note.resolve_account("https://x", "k", "不存在的号")


# ---- 轮询：终态即停 / 网络异常沙盒提示 ----

def test_poll_job_returns_on_terminal(monkeypatch):
    import publish_note
    views = iter([{"job_id": 5, "status": "publishing"},
                  {"job_id": 5, "status": "published", "note_url": "https://xhs/x"}])
    class R:
        status_code = 200
        def __init__(self, v): self._v = v
        def json(self): return self._v
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: R(next(views)))
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    view = publish_note.poll_job("https://x", "k", 5, timeout=60)
    assert view["status"] == "published" and view["note_url"]


def test_poll_job_tolerates_transient_500_and_network(monkeypatch):
    """一次 5xx/网络抖动绝不能判终态（会诱发重复发布）——容忍后继续轮询到 published。"""
    import publish_note
    class Ok:
        status_code = 200
        def json(self): return {"job_id": 5, "status": "published", "note_url": "https://xhs/x"}
    class Boom:
        status_code = 500
        text = "err"
        def json(self): return {"error": "内部错误"}
    seq = iter(["net", "500", "ok"])
    def fake(*a, **k):
        kind = next(seq)
        if kind == "net":
            raise ConnectionError("timed out")
        return Boom() if kind == "500" else Ok()
    monkeypatch.setattr(publish_note, "send_request", fake)
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    view = publish_note.poll_job("https://x", "k", 5, timeout=60)
    assert view["status"] == "published"


def test_poll_job_permanent_404_raises_immediately(monkeypatch):
    import publish_note
    class R404:
        status_code = 404
        text = "x"
        def json(self): return {"error": "job 不存在"}
    calls = {"n": 0}
    def fake(*a, **k):
        calls["n"] += 1
        return R404()
    monkeypatch.setattr(publish_note, "send_request", fake)
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    with pytest.raises(ValueError):
        publish_note.poll_job("https://x", "k", 5, timeout=60)
    assert calls["n"] == 1  # 永久错误不重试


def test_self_check_ready_and_states(monkeypatch):
    import publish_note
    class R:
        def __init__(self, code, v): self.status_code, self._v = code, v
        def json(self): return self._v
    # whoami ok + 混合 cookie 状态：valid/unknown 可用，invalid 需重登
    accounts = [{"id": 1, "name": "主号", "cookie_status": "valid"},
                {"id": 2, "name": "备号", "cookie_status": "unknown"},
                {"id": 3, "name": "废号", "cookie_status": "invalid"}]
    def fake(method, url, key, payload=None, timeout=60):
        if url.endswith("/api/whoami"):
            return R(200, {"name": "小王", "role": "operator"})
        if url.endswith("/api/accounts"):
            return R(200, {"accounts": accounts})
        raise AssertionError(url)
    monkeypatch.setattr(publish_note, "send_request", fake)
    rep = publish_note.self_check("https://x", "k")
    assert rep["ok"] and rep["ready"]
    assert rep["identity"]["name"] == "小王" and rep["account_count"] == 3
    assert rep["need_relogin"] == ["废号"]


def test_self_check_whoami_401_reports_not_ok(monkeypatch):
    import publish_note
    class R:
        status_code = 401
        text = "x"
        def json(self): return {"detail": "apikey 无效"}
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: R())
    rep = publish_note.self_check("https://x", "k")
    assert rep["ok"] is False and rep["stage"] == "whoami"
    assert "sandbox allow" in rep["hint"]


def test_self_check_accounts_failure_stays_in_selfcheck_envelope(monkeypatch):
    import publish_note
    class Ok:
        status_code = 200
        def json(self): return {"name": "小王", "role": "operator"}
    def fake(method, url, key, payload=None, timeout=60):
        if url.endswith("/api/whoami"):
            return Ok()
        raise ConnectionError("timed out")  # 拉账号时瞬时挂
    monkeypatch.setattr(publish_note, "send_request", fake)
    rep = publish_note.self_check("https://x", "k")
    # 不落 publish 失败信封，保持 self-check 形状
    assert rep["ok"] is False and rep["stage"] == "accounts"
    assert rep["identity"]["name"] == "小王"


def test_self_check_connected_but_no_account_not_ready(monkeypatch):
    import publish_note
    class R:
        def __init__(self, code, v): self.status_code, self._v = code, v
        def json(self): return self._v
    def fake(method, url, key, payload=None, timeout=60):
        if url.endswith("/api/whoami"):
            return R(200, {"name": "小王", "role": "operator"})
        return R(200, {"accounts": []})
    monkeypatch.setattr(publish_note, "send_request", fake)
    rep = publish_note.self_check("https://x", "k")
    assert rep["ok"] and rep["ready"] is False and rep["account_count"] == 0


def test_account_notes_graceful_404_when_endpoint_not_live(monkeypatch):
    import publish_note
    class R404:
        status_code = 404
        text = "not found"
        def json(self): return {"error": "路径不存在"}
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: R404())
    rep = publish_note.account_notes("https://x", "k", 1)
    assert rep["available"] is False and "404" in rep["hint"]


def test_account_notes_returns_data_when_live(monkeypatch):
    import publish_note
    payload = {"notes": [{"title": "A", "views": 100, "likes": 9}], "total": 1}
    class R:
        status_code = 200
        text = "x"
        def json(self): return payload
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: R())
    rep = publish_note.account_notes("https://x", "k", 1)
    assert rep["available"] is True and rep["total"] == 1 and rep["notes"][0]["views"] == 100


def test_account_notes_real_error_raises(monkeypatch):
    import publish_note
    class R500:
        status_code = 500
        text = "boom"
        def json(self): return {"error": "内部错误"}
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: R500())
    with pytest.raises(ValueError):
        publish_note.account_notes("https://x", "k", 1)


def test_extension_info_passthrough(monkeypatch):
    import publish_note
    info = {"download_url": "https://x/downloads/extension.zip?t=1", "version": "0.2.0",
            "install_steps": ["下载", "解压", "加载"], "server_time": "2026-07-13T10:00:00"}
    class R:
        status_code = 200
        def json(self): return info
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: R())
    assert publish_note.extension_info("https://x", "k")["server_time"]


def test_wait_login_polls_until_done(monkeypatch):
    import publish_note
    views = iter([{"done": False, "accounts": []},
                  {"done": True, "accounts": [{"id": 9, "name": "新号"}]}])
    seen_paths = []
    class R:
        status_code = 200
        def __init__(self, v): self._v = v
        def json(self): return self._v
    def fake(method, url, key, payload=None, timeout=60):
        seen_paths.append(url)
        return R(next(views))
    monkeypatch.setattr(publish_note, "send_request", fake)
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    view = publish_note.wait_login("https://x", "k", "2026-07-13T10:00:00", None, timeout=60)
    assert view["done"] and view["accounts"][0]["id"] == 9
    assert "since=2026-07-13T10%3A00%3A00" in seen_paths[0]  # since 已 URL 编码
    # 重登旧号带 account_id
    views2 = iter([{"done": True, "account": {"id": 3}}])
    monkeypatch.setattr(publish_note, "send_request",
                        lambda m, u, k, payload=None, timeout=60: R(next(views2)) if seen_paths.append(u) is None else None)
    publish_note.wait_login("https://x", "k", "t", 3, timeout=60)
    assert "account_id=3" in seen_paths[-1]


def test_check_cookie_202_then_polls_to_terminal(monkeypatch):
    import publish_note
    class R:
        def __init__(self, code, v): self.status_code, self._v = code, v
        def json(self): return self._v
    seq = iter([R(202, {"check_id": "abc", "status": "checking"}),
                R(200, {"status": "checking"}),
                R(200, {"status": "valid", "user_info": {"nickname": "n"}})])
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: next(seq))
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    view = publish_note.check_cookie("https://x", "k", 1)
    assert view["status"] == "valid"


def test_sandbox_hint_on_blocked_network():
    import publish_note
    hint = publish_note.sandbox_hint(Exception("Failed: Host not allowed"))
    assert "sandbox allow" in hint and "dangerouslyDisableSandbox" in hint
    assert publish_note.sandbox_hint(Exception("普通错误")) == "普通错误"


# ---- CLI 契约：--dry-run 输出纯 JSON、不打网络、exit 0 ----

def test_cli_dry_run_contract(tmp_path):
    import subprocess
    note, _ = _make_note_tree(tmp_path, pages=2)
    script = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "publish_note.py"
    env = {"PATH": "/usr/bin:/bin", "NBDPSY_XHS_API_KEY": "test_key_not_real",
           "NBDPSY_SECRETS": str(tmp_path / "none.env"), "NBDPSY_WORKSPACE": str(tmp_path)}
    p = subprocess.run([sys.executable, str(script), "--note", str(note),
                        "--account", "主号", "--dry-run"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["outcome"] == "dry_run" and len(out["images"]) == 2
    assert "test_key_not_real" not in p.stdout + p.stderr  # 密钥值绝不回显


def test_cli_missing_key_exit1(tmp_path):
    import subprocess
    note, _ = _make_note_tree(tmp_path, pages=1)
    script = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "publish_note.py"
    env = {"PATH": "/usr/bin:/bin",
           "NBDPSY_SECRETS": str(tmp_path / "none.env"), "NBDPSY_WORKSPACE": str(tmp_path)}
    p = subprocess.run([sys.executable, str(script), "--note", str(note),
                        "--account", "1", "--dry-run"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 1
    assert "MISSING:NBDPSY_XHS_API_KEY" in p.stderr


# ---- v1.23.0 发布线增强：改期 / 撤稿 / 列任务 / 图床 / whoami ----

class _Resp:
    def __init__(self, code, v): self.status_code, self._v, self.text = code, v, "x"
    def json(self): return self._v


def test_reschedule_sends_patch_schedule_only(monkeypatch):
    """PATCH 只带 schedule_time，绝不多带字段（部分更新契约核心）。"""
    import publish_note
    seen = {}
    def fake(method, url, key, payload=None, timeout=60, files=None):
        seen.update(method=method, url=url, payload=payload)
        return _Resp(200, {"ok": True, "job": {"job_id": 7, "status": "pending"}})
    monkeypatch.setattr(publish_note, "send_request", fake)
    view = publish_note.reschedule_job("https://x", "k", 7, "2026-07-16T09:00:00+08:00")
    assert seen["method"] == "PATCH"
    assert seen["url"].endswith("/api/publish-jobs/7")
    assert seen["payload"] == {"schedule_time": "2026-07-16T09:00:00+08:00"}
    assert view["ok"] is True


def test_reschedule_now_sends_null(monkeypatch):
    """--schedule now → PATCH {"schedule_time": null}（清空转立即发）。"""
    import publish_note
    seen = {}
    def fake(method, url, key, payload=None, timeout=60, files=None):
        seen["payload"] = payload
        return _Resp(200, {"ok": True, "job": {}})
    monkeypatch.setattr(publish_note, "send_request", fake)
    publish_note.reschedule_job("https://x", "k", 7, "now")
    assert seen["payload"] == {"schedule_time": None}


def test_reschedule_non_pending_returns_ok_false(monkeypatch):
    """非 pending → 服务端 {ok:false,status}；函数原样返回，由 main 转非零退出。"""
    import publish_note
    monkeypatch.setattr(publish_note, "send_request",
                        lambda *a, **k: _Resp(200, {"ok": False, "status": "published"}))
    view = publish_note.reschedule_job("https://x", "k", 7, "now")
    assert view["ok"] is False and view["status"] == "published"


def test_schedule_offset_warning():
    import publish_note
    assert publish_note.schedule_offset_warning("2026-07-16T09:00:00+08:00") is None
    assert "偏移" in publish_note.schedule_offset_warning("2026-07-16T09:00:00")
    assert "无法解析" in publish_note.schedule_offset_warning("不是时间")


def test_cancel_job_ok_and_path(monkeypatch):
    import publish_note
    seen = {}
    def fake(method, url, key, payload=None, timeout=60, files=None):
        seen.update(method=method, url=url)
        return _Resp(200, {"ok": True})
    monkeypatch.setattr(publish_note, "send_request", fake)
    assert publish_note.cancel_job("https://x", "k", 9)["ok"] is True
    assert seen["method"] == "POST" and seen["url"].endswith("/api/publish-jobs/9/cancel")


def test_cancel_job_non_pending(monkeypatch):
    import publish_note
    monkeypatch.setattr(publish_note, "send_request",
                        lambda *a, **k: _Resp(200, {"ok": False, "status": "publishing"}))
    v = publish_note.cancel_job("https://x", "k", 9)
    assert v["ok"] is False and v["status"] == "publishing"


def test_list_jobs_query_and_brief_fields(monkeypatch):
    """GET query 组装 + 读 jobs 键 + 精简字段（去掉 retries/note_id 等）。"""
    import publish_note
    seen = {}
    full = {"job_id": 3, "account_id": 1, "title": "T", "status": "pending",
            "schedule_time": None, "note_url": None, "error": None,
            "created_at": "2026-07-16T00:00:00", "retries": 0, "note_id": None,
            "next_retry_at": None}
    def fake(method, url, key, payload=None, timeout=60, files=None):
        seen.update(method=method, url=url)
        return _Resp(200, {"jobs": [full]})
    monkeypatch.setattr(publish_note, "send_request", fake)
    out = publish_note.list_jobs("https://x", "k", account_id=1, status="pending", limit=20)
    assert seen["method"] == "GET" and "/api/publish-jobs?" in seen["url"]
    assert "account_id=1" in seen["url"] and "status=pending" in seen["url"] and "limit=20" in seen["url"]
    j = out["jobs"][0]
    assert j["job_id"] == 3 and j["title"] == "T"
    assert "retries" not in j and "note_id" not in j and "next_retry_at" not in j


def test_collect_upload_paths_dir_sorted(tmp_path):
    import publish_note
    d = tmp_path / "imgs"; d.mkdir()
    for n in ["P03.png", "P01.png", "P02.jpg", "note.txt"]:
        (d / n).write_bytes(b"x")
    paths = publish_note.collect_upload_paths([str(d)])
    assert [p.name for p in paths] == ["P01.png", "P02.jpg", "P03.png"]  # 排序 + 过滤非图


def test_collect_upload_paths_files_order_preserved(tmp_path):
    import publish_note
    a = tmp_path / "a.png"; b = tmp_path / "b.png"
    a.write_bytes(b"x"); b.write_bytes(b"y")
    paths = publish_note.collect_upload_paths([str(b), str(a)])
    assert [p.name for p in paths] == ["b.png", "a.png"]  # 显式文件保留给定顺序


def test_collect_upload_paths_missing_raises(tmp_path):
    import publish_note
    with pytest.raises(ValueError):
        publish_note.collect_upload_paths([str(tmp_path / "nope.png")])


def test_upload_image_batch_multipart_field_and_order(tmp_path, monkeypatch):
    """multipart 字段名统一 files、多文件、顺序。"""
    import publish_note
    seen = {}
    def fake(method, url, key, payload=None, timeout=60, files=None):
        seen.update(method=method, url=url, files=files)
        return _Resp(200, {"batch_id": "b1", "urls": ["https://u/1", "https://u/2"],
                           "expires_at": "2026-07-23"})
    monkeypatch.setattr(publish_note, "send_request", fake)
    p1 = tmp_path / "01.png"; p2 = tmp_path / "02.png"
    p1.write_bytes(b"a"); p2.write_bytes(b"b")
    out = publish_note.upload_image_batch("https://x", "k", [p1, p2])
    assert seen["method"] == "POST" and seen["url"].endswith("/api/uploads/images")
    assert [f[0] for f in seen["files"]] == ["files", "files"]  # 字段名统一 files
    assert seen["files"][0][1][0] == "01.png" and seen["files"][1][1][0] == "02.png"  # 顺序
    assert seen["files"][0][1][2] == "image/png"  # mime 按扩展名
    assert out["batch_id"] == "b1"


def test_upload_image_batch_precheck_bounds(tmp_path):
    """客户端预检 1–18 张：0 张与 19 张都拦截。"""
    import publish_note
    with pytest.raises(ValueError):
        publish_note.upload_image_batch("https://x", "k", [])
    many = []
    for i in range(19):
        p = tmp_path / f"{i:02d}.png"; p.write_bytes(b"x"); many.append(p)
    with pytest.raises(ValueError):
        publish_note.upload_image_batch("https://x", "k", many)


def test_list_uploads_passthrough(monkeypatch):
    import publish_note
    batches = {"batches": [{"batch_id": "b1", "file_count": 3,
                            "created_at": "2026-07-16", "expires_at": "2026-07-23"}]}
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: _Resp(200, batches))
    assert publish_note.list_uploads("https://x", "k")["batches"][0]["file_count"] == 3


def test_self_check_calls_whoami_first_and_includes_identity(monkeypatch):
    """--self-check 第一步先打 GET /api/whoami，{name,role} 并入输出。"""
    import publish_note
    calls = []
    def fake(method, url, key, payload=None, timeout=60, files=None):
        calls.append(url)
        if url.endswith("/api/whoami"):
            return _Resp(200, {"name": "小李", "role": "operator"})
        return _Resp(200, {"accounts": []})
    monkeypatch.setattr(publish_note, "send_request", fake)
    rep = publish_note.self_check("https://x", "k")
    assert calls[0].endswith("/api/whoami")  # whoami 先行
    assert rep["identity"] == {"name": "小李", "role": "operator"}


def test_send_request_multipart_branch(monkeypatch):
    """send_request 本体：files 非空走 multipart（带 Bearer、不带 json 体），空则 JSON 体。"""
    import types
    import publish_note
    calls = []
    def _req(method, url, **kw):
        calls.append((method, url, kw))
        return _Resp(200, {})
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(request=_req))
    publish_note.send_request("POST", "https://x/api/uploads/images", "K1",
                              files=[("files", ("01.png", b"x", "image/png"))])
    _, _, kw = calls[0]
    assert kw["files"] and "json" not in kw
    assert kw["headers"]["Authorization"] == "Bearer K1"
    publish_note.send_request("GET", "https://x/api/whoami", "K1")
    _, _, kw2 = calls[1]
    assert "files" not in kw2 and kw2["json"] is None
    assert kw2["headers"]["Authorization"] == "Bearer K1"


# ---- v1.24.0 删除笔记 + 导出 refresh ----

def test_start_note_deletion_posts_title_and_count(monkeypatch):
    """POST /api/accounts/{id}/note-deletions，payload 恰为 {title,count}。"""
    import publish_note
    seen = {}
    def fake(method, url, key, payload=None, timeout=60, files=None):
        seen.update(method=method, url=url, payload=payload)
        return _Resp(202, {"deletion_id": "del-1", "status": "running"})
    monkeypatch.setattr(publish_note, "send_request", fake)
    did = publish_note.start_note_deletion("https://x", "k", 4, "重复的标题", 3)
    assert did == "del-1"
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/api/accounts/4/note-deletions")
    assert seen["payload"] == {"title": "重复的标题", "count": 3}


def test_start_note_deletion_precheck_count_bounds(monkeypatch):
    """count 0 / 11 客户端预检拒绝（不发网络请求）。"""
    import publish_note
    def boom(*a, **k):
        raise AssertionError("越界 count 不应发起请求")
    monkeypatch.setattr(publish_note, "send_request", boom)
    with pytest.raises(ValueError):
        publish_note.start_note_deletion("https://x", "k", 4, "t", 0)
    with pytest.raises(ValueError):
        publish_note.start_note_deletion("https://x", "k", 4, "t", 11)


def test_delete_note_result_done_with_remaining():
    import publish_note
    out, code = publish_note.delete_note_result(
        {"status": "done", "deleted": 3, "remaining": 1}, "del-1")
    assert code == 0 and out["outcome"] == "done"
    assert out["deleted"] == 3 and out["remaining"] == 1
    assert "1" in out["hint"] and "同题" in out["hint"]
    # remaining=0 时不带 hint
    out2, _ = publish_note.delete_note_result(
        {"status": "done", "deleted": 1, "remaining": 0}, "del-1")
    assert "hint" not in out2


def test_delete_note_result_error_reasons():
    import publish_note
    out1, code1 = publish_note.delete_note_result(
        {"status": "error", "reason": "note_not_found: 未找到"}, "del-1")
    assert code1 == 1 and out1["outcome"] == "failed"
    assert "精确匹配" in out1["hint"] and "--notes" in out1["hint"]
    out2, code2 = publish_note.delete_note_result(
        {"status": "error", "reason": "need_manual_login: 掉线"}, "del-1")
    assert code2 == 1 and "重新扫码" in out2["hint"]


def test_delete_note_result_gone_is_unknown_safe():
    """台账 404 失效（server 重启）→ unknown，绝不盲目重发；hint 含『先』『核对』与不可逆语义。"""
    import publish_note
    out, code = publish_note.delete_note_result({"status": "gone"}, "del-1")
    assert code == 0 and out["outcome"] == "unknown"
    assert out["deletion_id"] == "del-1"
    assert "先" in out["hint"] and "核对" in out["hint"]
    assert "不可逆" in out["hint"] and "重发" in out["hint"]
    assert "--refresh" in out["hint"]


def test_delete_note_result_timeout_running_is_unknown():
    """轮询超时仍 running → 同 unknown 语义，带 deletion_id 与复查提示。"""
    import publish_note
    out, code = publish_note.delete_note_result({"status": "running"}, "del-9")
    assert code == 0 and out["outcome"] == "unknown"
    assert "del-9" in out["hint"] and "核对" in out["hint"] and "不可逆" in out["hint"]


def test_poll_async_task_404_returns_gone(monkeypatch):
    """轮询遇 404（进程内存台账失效）→ {"status":"gone"}，不当永久错误抛。"""
    import publish_note
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: _Resp(404, {"error": "不存在"}))
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    view = publish_note.poll_async_task("https://x", "k", "https://x/api/note-deletions/del-1", timeout=60)
    assert view["status"] == "gone"


def test_poll_async_task_stops_on_done(monkeypatch):
    import publish_note
    views = iter([{"status": "running"}, {"status": "done", "deleted": 1, "remaining": 0}])
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: _Resp(200, next(views)))
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    view = publish_note.poll_async_task("https://x", "k", "https://x/api/note-deletions/d", timeout=60)
    assert view["status"] == "done" and view["deleted"] == 1


def test_refresh_notes_no_data_available_false_exit0(monkeypatch):
    """导出 error 且 reason 含 no_data → available:false + no_data:true，exit 0（不是故障）。"""
    import publish_note
    seen = {}
    def fake(method, url, key, payload=None, timeout=60, files=None):
        if url.endswith("/note-exports"):
            seen["post"] = url
            return _Resp(202, {"export_id": "exp-1", "status": "running"})
        return _Resp(200, {"status": "error", "reason": "no_data: 数据看板暂无笔记数据"})
    monkeypatch.setattr(publish_note, "send_request", fake)
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    out, code = publish_note.refresh_notes("https://x", "k", 4)
    assert seen["post"].endswith("/api/accounts/4/note-exports")
    assert code == 0 and out["available"] is False and out["no_data"] is True


def test_refresh_notes_done_reads_snapshot(monkeypatch):
    """导出 done → 成功链路末尾调 account_notes 读快照。"""
    import publish_note
    calls = []
    def fake(method, url, key, payload=None, timeout=60, files=None):
        calls.append((method, url))
        if url.endswith("/note-exports"):
            return _Resp(202, {"export_id": "exp-1", "status": "running"})
        if "/note-exports/" in url:
            return _Resp(200, {"status": "done", "note_count": 24})
        # account_notes 的 GET /api/accounts/{id}/notes
        return _Resp(200, {"notes": [{"title": "A", "views": 100}], "total": 1})
    monkeypatch.setattr(publish_note, "send_request", fake)
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    out, code = publish_note.refresh_notes("https://x", "k", 4)
    assert code == 0 and out["available"] is True and out["total"] == 1
    assert any(u.endswith("/api/accounts/4/notes") for _, u in calls)  # 末尾读快照


def test_refresh_notes_other_error_raises(monkeypatch):
    """导出其它 error（非 no_data）→ 抛（main 落 failed）。"""
    import publish_note
    def fake(method, url, key, payload=None, timeout=60, files=None):
        if url.endswith("/note-exports"):
            return _Resp(202, {"export_id": "exp-1", "status": "running"})
        return _Resp(200, {"status": "error", "reason": "need_manual_login: 掉线"})
    monkeypatch.setattr(publish_note, "send_request", fake)
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    with pytest.raises(ValueError):
        publish_note.refresh_notes("https://x", "k", 4)


def test_account_notes_404_hint_points_to_refresh(monkeypatch):
    """404 兜底新文案：改为引导 --refresh 触发导出，不再『联系管理员』。"""
    import publish_note
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: _Resp(404, {"error": "无快照"}))
    rep = publish_note.account_notes("https://x", "k", 1)
    assert rep["available"] is False
    assert "--refresh" in rep["hint"] and "联系管理员" not in rep["hint"]


def test_cli_delete_note_requires_account_and_title(tmp_path):
    """--delete-note 缺 --title → argparse 依赖校验 exit 2（不发任何网络请求）。"""
    import subprocess
    script = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "publish_note.py"
    env = {"PATH": "/usr/bin:/bin", "NBDPSY_XHS_API_KEY": "k",
           "NBDPSY_SECRETS": str(tmp_path / "none.env"), "NBDPSY_WORKSPACE": str(tmp_path)}
    p = subprocess.run([sys.executable, str(script), "--delete-note", "--account", "1"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2
    assert "--title" in p.stderr


def test_cli_reschedule_requires_schedule(tmp_path):
    """--reschedule 缺 --schedule → argparse 依赖校验 exit 2（不发任何网络请求）。"""
    import subprocess
    script = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "publish_note.py"
    env = {"PATH": "/usr/bin:/bin", "NBDPSY_XHS_API_KEY": "k",
           "NBDPSY_SECRETS": str(tmp_path / "none.env"), "NBDPSY_WORKSPACE": str(tmp_path)}
    p = subprocess.run([sys.executable, str(script), "--reschedule", "42"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2
    assert "--schedule" in p.stderr


# ---- v1.24.0 安全回归：删除线 202 后异常绝不落 failed（不可逆操作防重发） ----

def test_cli_delete_note_poll_crash_falls_to_unknown(monkeypatch, capsys):
    """高危回归：202 入队后轮询持续网络故障 → unknown + deletion_id + 勿重发 hint，
    绝不落 failed（failed 语义=可修因重试，会诱导 agent 重发不可逆删除）。"""
    import publish_note
    monkeypatch.setattr(sys, "argv",
                        ["publish_note.py", "--delete-note", "--account", "6", "--title", "T"])
    monkeypatch.setattr(publish_note.nbdpsy_common, "get_secret", lambda k: "k")
    monkeypatch.setattr(publish_note, "resolve_account", lambda *a: (6, "看世界", None))
    monkeypatch.setattr(publish_note, "start_note_deletion", lambda *a, **k: "d-123")
    def boom(*a, **k):
        raise ConnectionError("network down")
    monkeypatch.setattr(publish_note, "poll_async_task", boom)
    with pytest.raises(SystemExit) as ei:
        publish_note.main()
    assert ei.value.code == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["outcome"] == "unknown" and out["deletion_id"] == "d-123"
    assert "重发" in out["hint"] and "--delete-status d-123" in out["hint"]


def test_cli_delete_status_done_running_gone(monkeypatch, capsys):
    """--delete-status 权威复查三态：done / running / 404→gone(unknown)。"""
    import publish_note
    monkeypatch.setattr(publish_note.nbdpsy_common, "get_secret", lambda k: "k")

    def run(resp):
        monkeypatch.setattr(sys, "argv", ["publish_note.py", "--delete-status", "d-9"])
        monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: resp)
        with pytest.raises(SystemExit) as ei:
            publish_note.main()
        return json.loads(capsys.readouterr().out.strip().splitlines()[-1]), ei.value.code

    out, code = run(_Resp(200, {"status": "done", "deleted": 2, "remaining": 1}))
    assert code == 0 and out["outcome"] == "done" and out["deleted"] == 2 and out["remaining"] == 1
    out, code = run(_Resp(200, {"status": "running"}))
    assert code == 0 and out["outcome"] == "running"
    out, code = run(_Resp(404, {}))
    assert code == 0 and out["outcome"] == "unknown" and "重发" in out["hint"]


def test_cli_delete_note_requires_account(tmp_path):
    """--delete-note 缺 --account（带 --title）→ argparse exit 2。"""
    import subprocess
    script = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "publish_note.py"
    env = {"PATH": "/usr/bin:/bin", "NBDPSY_XHS_API_KEY": "k",
           "NBDPSY_SECRETS": str(tmp_path / "none.env"), "NBDPSY_WORKSPACE": str(tmp_path)}
    p = subprocess.run([sys.executable, str(script), "--delete-note", "--title", "t"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 2 and "--account" in p.stderr


def test_poll_async_task_tolerates_transient_then_done(monkeypatch):
    """500×2 后 200 done → 正常返回（瞬时容忍）；401 → 立即抛不重试。"""
    import publish_note
    seq = iter([_Resp(500, {}), _Resp(500, {}), _Resp(200, {"status": "done", "deleted": 1})])
    monkeypatch.setattr(publish_note, "send_request", lambda *a, **k: next(seq))
    monkeypatch.setattr(publish_note.time, "sleep", lambda s: None)
    view = publish_note.poll_async_task("https://x", "k", "https://x/u", timeout=60)
    assert view["status"] == "done"
    monkeypatch.setattr(publish_note, "send_request",
                        lambda *a, **k: _Resp(401, {"detail": "bad key"}))
    with pytest.raises(ValueError):
        publish_note.poll_async_task("https://x", "k", "https://x/u", timeout=60)


def test_refresh_notes_gone_raises_with_hint(monkeypatch):
    """导出台账失效（poll 回 gone）→ ValueError 提示重跑 --refresh。"""
    import publish_note
    monkeypatch.setattr(publish_note, "start_note_export", lambda *a, **k: "e-1")
    monkeypatch.setattr(publish_note, "poll_async_task", lambda *a, **k: {"status": "gone"})
    with pytest.raises(ValueError) as ei:
        publish_note.refresh_notes("https://x", "k", 6)
    assert "--refresh" in str(ei.value)


def test_delete_note_result_server_unknown_is_manual_check():
    """server 四态新增 unknown（重启打断删除执行，结果真实未知）→ 人工创作中心核对，勿重发。"""
    import publish_note
    out, code = publish_note.delete_note_result(
        {"status": "unknown", "reason": "restart_interrupted"}, "d-7")
    assert code == 0 and out["outcome"] == "unknown" and out["reason"] == "restart_interrupted"
    assert "人工" in out["hint"] and "重发" in out["hint"] and "不可逆" in out["hint"]

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

import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-youtube-transport" / "scripts"))

import pytest


# ---- URL 预检：只认 youtube.com / youtu.be ----

def test_is_youtube_url_accepts_and_rejects():
    import transport_video as tv
    assert tv.is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert tv.is_youtube_url("https://youtu.be/abc")
    assert tv.is_youtube_url("http://m.youtube.com/watch?v=abc")
    assert not tv.is_youtube_url("https://vimeo.com/123")
    assert not tv.is_youtube_url("https://www.bilibili.com/video/x")
    assert not tv.is_youtube_url("ftp://youtube.com/x")   # 非 http(s)
    assert not tv.is_youtube_url("not a url")
    # 防子串绕过：youtube.com.evil.com 不算 YouTube
    assert not tv.is_youtube_url("https://youtube.com.evil.com/watch?v=x")


# ---- 错误体两套形状（与发布接口同契约） ----

def test_api_error_both_shapes():
    import transport_video as tv
    class R1:
        status_code = 400; text = "x"
        def json(self): return {"error": "只支持 youtube"}
    class R2:
        status_code = 422; text = "x"
        def json(self): return {"detail": "url 非法"}
    class R3:
        status_code = 500; text = "<html>bad</html>"
        def json(self): raise ValueError
    assert "只支持 youtube" in tv.api_error(R1())
    assert "url 非法" in tv.api_error(R2())
    assert "500" in tv.api_error(R3())


# ---- 产物相对路径拼成公网绝对 URL ----

def test_resolve_products_relative_to_absolute():
    import transport_video as tv
    products = {"video_url": "/uploads/vt/1/out.mp4",
                "transcript_zh_srt_url": "/uploads/vt/1/zh.srt",
                "already": "https://cdn.x/y.mp4", "empty": None}
    out = tv.resolve_products(products, "https://xhs.nbdpsy.com")
    assert out["video_url"] == "https://xhs.nbdpsy.com/uploads/vt/1/out.mp4"
    assert out["transcript_zh_srt_url"] == "https://xhs.nbdpsy.com/uploads/vt/1/zh.srt"
    assert out["already"] == "https://cdn.x/y.mp4"   # 已是绝对 URL 不动
    assert out["empty"] is None
    assert tv.resolve_products(None, "https://x") == {}


def test_job_brief_shape():
    import transport_video as tv
    view = {"id": 7, "status": "completed",
            "products": {"video_url": "/uploads/a.mp4"}, "error": None}
    brief = tv.job_brief(view, "https://xhs.nbdpsy.com")
    assert brief["outcome"] == "completed" and brief["job_id"] == 7
    assert brief["products"]["video_url"].startswith("https://xhs.nbdpsy.com/")


# ---- 建任务 payload：voice 缺省不传、烧字幕/分辨率带上 ----

def test_create_job_payload(monkeypatch):
    import transport_video as tv
    captured = {}
    class R:
        status_code = 202
        def json(self): return {"job_id": 11}
    def fake(method, url, key, payload=None, timeout=60):
        captured.update(method=method, url=url, payload=payload)
        return R()
    monkeypatch.setattr(tv, "send_request", fake)
    jid = tv.create_job("https://xhs.nbdpsy.com", "k",
                        "https://youtu.be/x", None, burn_subtitles=True, max_resolution=1080)
    assert jid == 11
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/video-transport/jobs")
    assert captured["payload"] == {"url": "https://youtu.be/x",
                                   "burn_subtitles": True, "max_resolution": 1080}
    assert "voice" not in captured["payload"]   # 缺省不传，服务端用默认牧羊音色
    # 指定音色时才带
    tv.create_job("https://x", "k", "https://youtu.be/x", "S_abc",
                  burn_subtitles=False, max_resolution=720)
    assert captured["payload"]["voice"] == "S_abc" and captured["payload"]["burn_subtitles"] is False


# ---- 轮询：终态即停 / 瞬时容忍 / 永久错误立即抛 ----

def test_poll_job_returns_on_terminal(monkeypatch):
    import transport_video as tv
    views = iter([{"job_id": 5, "status": "running"},
                  {"job_id": 5, "status": "completed", "products": {"video_url": "/u/a.mp4"}}])
    class R:
        status_code = 200
        def __init__(self, v): self._v = v
        def json(self): return self._v
    monkeypatch.setattr(tv, "send_request", lambda *a, **k: R(next(views)))
    monkeypatch.setattr(tv.time, "sleep", lambda s: None)
    view = tv.poll_job("https://x", "k", 5, timeout=60)
    assert view["status"] == "completed"


def test_poll_job_tolerates_transient(monkeypatch):
    """一次 5xx/网络抖动绝不能判终态（会诱发重复搬运）——容忍后继续轮询到 completed。"""
    import transport_video as tv
    class Ok:
        status_code = 200
        def json(self): return {"job_id": 5, "status": "completed", "products": {}}
    class Boom:
        status_code = 500; text = "err"
        def json(self): return {"error": "内部错误"}
    seq = iter(["net", "500", "ok"])
    def fake(*a, **k):
        kind = next(seq)
        if kind == "net":
            raise ConnectionError("timed out")
        return Boom() if kind == "500" else Ok()
    monkeypatch.setattr(tv, "send_request", fake)
    monkeypatch.setattr(tv.time, "sleep", lambda s: None)
    assert tv.poll_job("https://x", "k", 5, timeout=60)["status"] == "completed"


def test_poll_job_permanent_404_raises_immediately(monkeypatch):
    import transport_video as tv
    class R404:
        status_code = 404; text = "x"
        def json(self): return {"error": "job 不存在"}
    calls = {"n": 0}
    def fake(*a, **k):
        calls["n"] += 1
        return R404()
    monkeypatch.setattr(tv, "send_request", fake)
    monkeypatch.setattr(tv.time, "sleep", lambda s: None)
    with pytest.raises(ValueError):
        tv.poll_job("https://x", "k", 5, timeout=60)
    assert calls["n"] == 1   # 永久错误不重试


def test_sandbox_hint_on_blocked_network():
    import transport_video as tv
    hint = tv.sandbox_hint(Exception("Failed: Host not allowed"))
    assert "sandbox allow" in hint and "dangerouslyDisableSandbox" in hint
    assert tv.sandbox_hint(Exception("普通错误")) == "普通错误"


# ---- CLI 契约 ----

SCRIPT = Path(__file__).parent.parent / "nbdpsy-youtube-transport" / "scripts" / "transport_video.py"


def test_cli_rejects_non_youtube_without_network(tmp_path):
    """非 YouTube 链接在建任务前被拒（不打网络），落 failed 信封 exit 1。"""
    import subprocess
    env = {"PATH": "/usr/bin:/bin", "NBDPSY_XHS_API_KEY": "test_key_not_real",
           "NBDPSY_SECRETS": str(tmp_path / "none.env"), "NBDPSY_WORKSPACE": str(tmp_path)}
    p = subprocess.run([sys.executable, str(SCRIPT), "--url", "https://vimeo.com/123"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 1, p.stderr
    out = json.loads(p.stdout)
    assert out["outcome"] == "failed" and out["job_id"] is None
    assert "youtu" in out["error"]
    assert "test_key_not_real" not in p.stdout + p.stderr   # 密钥值绝不回显


def test_cli_missing_key_exit1(tmp_path):
    import subprocess
    env = {"PATH": "/usr/bin:/bin",
           "NBDPSY_SECRETS": str(tmp_path / "none.env"), "NBDPSY_WORKSPACE": str(tmp_path)}
    p = subprocess.run([sys.executable, str(SCRIPT), "--url", "https://youtu.be/x"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 1
    assert "MISSING:NBDPSY_XHS_API_KEY" in p.stderr

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-content-teardown" / "scripts"))

import fetch_xhs_note as fx  # noqa: E402

# 真实 /api/notes/extract 200 响应的精简版（字段名与层级与线上一致）
FAKE_NOTE = {
    "note_id": "6a79c4e0000000002402eab2",
    "note_type": "图文",
    "note_type_raw": "normal",
    "title": "焦虑的本质：没起火，警报却响了一整晚",
    "content": "凌晨一点你躺下，房间很安静，心跳却自己快起来了。\n\n脑子清楚明天没什么大事。身体不信。",
    "topics": ["焦虑", "内耗"],
    "images": [
        {"ordinal": 1, "url": "https://mcp.nbdpsy.com/uploads/hXJE/01.jpg",
         "signed_url": "http://sns-webpic-qc.xhscdn.com/202608112223/sig/spectrum/aaa",
         "permanent_url": "https://sns-img-qc.xhscdn.com/spectrum/aaa",
         "width": 749, "height": 1123, "bytes": 90912},
        {"ordinal": 2, "url": None,
         "signed_url": "http://sns-webpic-qc.xhscdn.com/202608112223/sig/spectrum/bbb",
         "permanent_url": "https://sns-img-qc.xhscdn.com/spectrum/bbb",
         "width": 749, "height": 1123},
    ],
    "video": None,
    "comments": None,
    "comments_complete": False,
    "comments_source": None,
    "interact": {"liked": 7, "collected": 7, "comment": None, "share": None},
    "author": {"nickname": "NBDpsy-我们都有病", "user_id": "5f0d50be0000000001003446",
               "profile_url": "https://www.xiaohongshu.com/user/profile/5f0d50be0000000001003446",
               "ip_location": "北京"},
    "published_at": "2026-08-10T20:32:32+08:00",
    "last_update_at": "2026-08-10T20:32:33+08:00",
    "unavailable": {"comments": "评论不在服务端渲染数据里，纯 HTTP 取不到"},
    "source": {"final_url": "https://www.xiaohongshu.com/explore/6a79c4e0000000002402eab2?xsec_token=YB1%3D",
               "xsec_token": "YB1=", "fetched_at": "2026-08-11T14:23:50.723625+00:00",
               "from_cache": False, "browser_session_used": False},
    "image_batch": {"batch_id": "hXJEBjAd5SN9r6pp", "expires_at": "2026-08-18T14:24:08"},
    "comments_job": None,
}


class FakeResp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text or json.dumps(body, ensure_ascii=False) if body is not None else text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """轮询测试里不要真睡。"""
    monkeypatch.setattr(fx.time, "sleep", lambda *_a, **_k: None)


# ---------- 请求体构造 ----------

def test_build_payload_defaults():
    p = fx.build_payload("https://xhslink.cn/abc")
    assert p == {"url": "https://xhslink.cn/abc", "with_images": True,
                 "with_comments": 0, "refresh": False}
    # 不要评论就不该带 account_id——带了会让人以为消耗了浏览器会话额度
    assert "account_id" not in p


def test_build_payload_with_comments():
    p = fx.build_payload("https://xhslink.cn/abc", with_images=False, comments=5,
                         account_id=9, refresh=True)
    assert p["with_comments"] == 5 and p["account_id"] == 9
    assert p["with_images"] is False and p["refresh"] is True


def test_build_payload_comments_need_account():
    # 服务端会 422，本地先拦住，省一次白跑
    with pytest.raises(ValueError) as e:
        fx.build_payload("https://xhslink.cn/abc", comments=5)
    assert "account" in str(e.value)


@pytest.mark.parametrize("n", [-1, 101])
def test_build_payload_rejects_out_of_range_comments(n):
    with pytest.raises(ValueError):
        fx.build_payload("https://xhslink.cn/abc", comments=n, account_id=9)


def test_build_payload_rejects_empty_url():
    with pytest.raises(ValueError):
        fx.build_payload("   ")


# ---------- 提取与错误码 ----------

def test_extract_returns_body(monkeypatch):
    monkeypatch.setattr(fx, "send_request",
                        lambda m, u, k, payload=None, timeout=180: FakeResp(200, FAKE_NOTE))
    assert fx.extract("https://x", "k", {"url": "u"})["note_id"] == FAKE_NOTE["note_id"]


def test_extract_400_no_xsec_token_message(monkeypatch):
    body = {"error": "这条链接没有 xsec_token,平台不会返回笔记内容(拿到的是空壳页)"}
    monkeypatch.setattr(fx, "send_request",
                        lambda m, u, k, payload=None, timeout=180: FakeResp(400, body))
    with pytest.raises(ValueError) as e:
        fx.extract("https://x", "k", {"url": "u"})
    msg = str(e.value)
    assert "HTTP 400" in msg and "xsec_token" in msg and "分享按钮" in msg  # 服务端原文 + 可操作提示


@pytest.mark.parametrize("status,body,keyword", [
    (401, {"detail": "无效的 apikey"}, "接入配置包"),
    (402, {"error": "额度不足"}, "配额"),
    (403, {"error": "无权限"}, "scope"),
    (404, {"error": "job_id 不存在"}, "不存在"),
    (422, {"detail": "要抓评论必须给 account_id"}, "--account"),
])
def test_extract_error_hints_are_actionable(monkeypatch, status, body, keyword):
    monkeypatch.setattr(fx, "send_request",
                        lambda m, u, k, payload=None, timeout=180: FakeResp(status, body))
    with pytest.raises(ValueError) as e:
        fx.extract("https://x", "k", {"url": "u"})
    assert f"HTTP {status}" in str(e.value) and keyword in str(e.value)


# ---------- 评论任务轮询终态 ----------

def _seq_sender(views):
    """按次序吐视图的假 send_request。"""
    it = iter(views)

    def send(method, url, key, payload=None, timeout=180):
        return next(it)
    return send


def test_poll_runs_to_done(monkeypatch):
    monkeypatch.setattr(fx, "send_request", _seq_sender([
        FakeResp(200, {"status": "queued"}),
        FakeResp(200, {"status": "running"}),
        FakeResp(200, {"status": "done", "comments": [{"author": "a", "text": "t"}],
                       "count": 1, "complete": True, "stop_reason": "reached_limit"}),
    ]))
    view = fx.poll_extract("https://x", "k", "j1", timeout=60)
    assert view["status"] == "done" and view["count"] == 1


@pytest.mark.parametrize("status", ["error", "unknown"])
def test_poll_stops_on_terminal_failures(monkeypatch, status):
    # error / unknown 都是终态：轮下去不会变，别把 unknown 当「还在跑」空转
    monkeypatch.setattr(fx, "send_request", _seq_sender([FakeResp(200, {"status": status})]))
    assert fx.poll_extract("https://x", "k", "j1", timeout=60)["status"] == status


def test_poll_404_is_gone(monkeypatch):
    monkeypatch.setattr(fx, "send_request", _seq_sender([FakeResp(404, {"error": "不存在"})]))
    assert fx.poll_extract("https://x", "k", "j1", timeout=60) == {"status": "gone"}


def test_poll_timeout_reports_honestly(monkeypatch):
    # 超时如实标 timed_out，不许伪装成终态
    monkeypatch.setattr(fx, "send_request",
                        lambda m, u, k, payload=None, timeout=180: FakeResp(200, {"status": "running"}))
    view = fx.poll_extract("https://x", "k", "j1", timeout=0)
    assert view["status"] == "running" and view["timed_out"] is True


def test_poll_tolerates_transient_5xx(monkeypatch):
    # 一次抖动绝不能误判成终态
    monkeypatch.setattr(fx, "send_request", _seq_sender([
        FakeResp(500, {"error": "boom"}),
        FakeResp(200, {"status": "done", "comments": [], "count": 0, "complete": True}),
    ]))
    assert fx.poll_extract("https://x", "k", "j1", timeout=60)["status"] == "done"


def test_poll_gives_up_after_repeated_5xx(monkeypatch):
    monkeypatch.setattr(fx, "send_request",
                        lambda m, u, k, payload=None, timeout=180: FakeResp(500, {"error": "boom"}))
    with pytest.raises(ValueError):
        fx.poll_extract("https://x", "k", "j1", timeout=60)


def test_poll_401_raises_immediately(monkeypatch):
    monkeypatch.setattr(fx, "send_request", _seq_sender([FakeResp(401, {"detail": "无效的 apikey"})]))
    with pytest.raises(ValueError):
        fx.poll_extract("https://x", "k", "j1", timeout=60)


# ---------- note.md 渲染 ----------

def test_render_markdown_core_blocks():
    md = fx.render_markdown(FAKE_NOTE)
    assert md.startswith("# 焦虑的本质：没起火，警报却响了一整晚")
    assert "NBDpsy-我们都有病" in md and "北京" in md
    assert "2026-08-10T20:32:32+08:00" in md
    assert "凌晨一点你躺下" in md          # 正文全文
    assert "#焦虑 #内耗" in md              # 话题标签
    assert "## 图片永久链" in md
    assert "https://sns-img-qc.xhscdn.com/spectrum/aaa" in md
    assert "6a79c4e0000000002402eab2" in md


def test_render_markdown_prefers_permanent_url():
    md = fx.render_markdown(FAKE_NOTE)
    # 永久链进清单，短效签名链不进（存档半年后再看，签名链早死了）
    assert "sns-webpic-qc.xhscdn.com" not in md.split("## 图片永久链")[1].split("\n\n>")[0].split("图床副本")[0]
    assert "2026-08-18T14:24:08 到期" in md   # 图床副本的到期提示要在


def test_render_markdown_missing_counts_render_unknown():
    md = fx.render_markdown(FAKE_NOTE)
    # comment/share 服务端给的是 null，是「没拿到」不是 0
    assert "点赞 7｜收藏 7｜评论 未知｜分享 未知" in md


def test_render_markdown_flags_image_without_permanent_url():
    note = dict(FAKE_NOTE, images=[{"ordinal": 1, "url": None, "signed_url": "http://sig/x",
                                    "permanent_url": None}])
    md = fx.render_markdown(note)
    assert "http://sig/x" in md and "无永久链" in md


def test_render_markdown_comments_section():
    note = dict(FAKE_NOTE, comments=[
        {"author": "NBDpsy", "text": "这个角度很少有人写", "like_count": 3,
         "is_author_reply": False, "sub_comments": [{"author": "路人", "text": "同感"}]},
        {"author": "米之木木", "text": "有想聊聊的可以私信", "like_count": 0,
         "is_author_reply": True, "sub_comments": []},
    ], comments_complete=True)
    md = fx.render_markdown(note)
    assert "## 评论（2 条，已取全）" in md
    assert "这个角度很少有人写" in md and "赞 3" in md
    assert "（作者回复）" in md and "路人：同感" in md


def test_render_markdown_drops_stale_unavailable_note_for_comments():
    # 评论已靠浏览器任务拿到，就不该再留「评论纯 HTTP 取不到」跟评论区自相矛盾
    note = dict(FAKE_NOTE, comments=[{"author": "a", "text": "t", "sub_comments": []}])
    md = fx.render_markdown(note)
    assert "## 评论（1 条" in md and "纯 HTTP 取不到" not in md
    # 没拿到评论时这句仍要保留（它解释了为什么空）
    assert "纯 HTTP 取不到" in fx.render_markdown(FAKE_NOTE)


def test_render_markdown_marks_cache_hit():
    note = dict(FAKE_NOTE, source=dict(FAKE_NOTE["source"], from_cache=True))
    assert "命中 24h 缓存" in fx.render_markdown(note)


def test_render_markdown_survives_empty_note():
    # 服务端偶发只回半份时也要渲染出东西来，而不是抛异常把已拿到的正文一起丢掉
    md = fx.render_markdown({})
    assert "（无标题）" in md and "（无话题标签）" in md and "（无图片）" in md

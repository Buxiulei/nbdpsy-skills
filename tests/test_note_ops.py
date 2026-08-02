"""note_ops.py：已发布笔记台账与操作。

重点钉三类东西——它们都是服务端交接文档里点名"已经害人踩过坑"的地方：
① permission_code 的 null 不是公开；② 单条端点把笔记包在 {"note":{…}} 里（实测形态，
直接读顶层会把公开笔记显示成未知）；③ 非幂等操作（三组件/可见性/评论）失败或未知时
绝不落 failed 诱导重试，逐项 failed 非空就不算成功。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import pytest


class _Resp:
    def __init__(self, code, v): self.status_code, self._v, self.text = code, v, "x"
    def json(self): return self._v


# ---- ① permission_code：只有 0 是公开，null 是未知 ----

@pytest.mark.parametrize("code,expected", [
    (0, "public"), (1, "private"), (None, "unknown"), (2, "private"), (4, "private"),
])
def test_visibility_of_three_states(code, expected):
    import note_ops
    assert note_ops.visibility_of(code) == expected


def test_null_permission_code_is_not_public():
    """`not permission_code` 会把 null 和 0 一起当成公开——服务端据此差点把用户刻意
    隐藏的私密笔记改回公开。null 必须落 unknown，绝不能与 public 同类。"""
    import note_ops
    assert note_ops.visibility_of(None) != note_ops.visibility_of(0)


def test_ledger_marks_visibility_and_counts_page_only(monkeypatch):
    import note_ops
    payload = {"total": 40, "limit": 3, "offset": 0, "notes": [
        {"note_id": "a", "permission_code": 0, "sync_status": "linked"},
        {"note_id": "b", "permission_code": 1, "sync_status": "orphan"},
        {"note_id": "c", "permission_code": None, "sync_status": "pending_id"},
    ]}
    monkeypatch.setattr(note_ops, "send_request", lambda *a, **k: _Resp(200, payload))
    view = note_ops.ledger("http://x", "k", 1, limit=3)
    assert [n["visibility"] for n in view["notes"]] == ["public", "private", "unknown"]
    # 服务端顶层 total（全量 40）不能被本页统计覆盖
    assert view["total"] == 40
    assert view["counts"] == {"in_page": 3, "public": 1, "private": 1, "unknown": 1,
                              "orphan": 1, "pending_id": 1}


def test_ledger_passes_limit_and_offset(monkeypatch):
    import note_ops
    seen = {}

    def fake(method, url, key, payload=None, timeout=60):
        seen["url"] = url
        return _Resp(200, {"notes": []})

    monkeypatch.setattr(note_ops, "send_request", fake)
    note_ops.ledger("http://x", "k", 7, limit=200, offset=200)
    assert "/api/accounts/7/published-notes?" in seen["url"]
    assert "limit=200" in seen["url"] and "offset=200" in seen["url"]


# ---- ② 单条端点的包装层 ----

def test_note_detail_reads_permission_code_inside_note_wrapper(monkeypatch):
    """实测响应是 {"note": {...}}：读顶层 permission_code 恒 None，会把公开笔记标成 unknown。"""
    import note_ops
    payload = {"note": {"note_id": "a", "permission_code": 0, "purpose_source": "inferred",
                        "content_text": "正文"}}
    monkeypatch.setattr(note_ops, "send_request", lambda *a, **k: _Resp(200, payload))
    view = note_ops.note_detail("http://x", "k", "a")
    assert view["visibility"] == "public" and view["available"] is True
    assert "推断" in view["purpose_hint"]


def test_note_detail_also_handles_flat_shape(monkeypatch):
    import note_ops
    monkeypatch.setattr(note_ops, "send_request",
                        lambda *a, **k: _Resp(200, {"note_id": "a", "permission_code": 1}))
    assert note_ops.note_detail("http://x", "k", "a")["visibility"] == "private"


def test_note_detail_404_is_not_an_exception(monkeypatch):
    import note_ops
    monkeypatch.setattr(note_ops, "send_request", lambda *a, **k: _Resp(404, {"error": "nope"}))
    view = note_ops.note_detail("http://x", "k", "zzz")
    assert view["available"] is False and "sync-ledger" in view["hint"]


# ---- ③ 三组件：逐项判定，failed 非空就不算成功 ----

def test_components_done_with_failed_items_is_partial_not_success():
    import note_ops
    out, code = note_ops.components_result(
        {"status": "done", "applied": ["collection_id"], "failed": ["activity_id"]},
        "j1", {"collection_id": "c", "activity_id": "a"})
    assert out["outcome"] == "partial" and code == 1
    assert "只对 failed" in out["hint"]


def test_components_partially_applied_without_failures_counts_as_done():
    import note_ops
    out, code = note_ops.components_result(
        {"status": "partially_applied", "applied": ["collection_id"], "failed": []},
        "j1", {"collection_id": "c"})
    assert out["outcome"] == "done" and code == 0


def test_components_error_with_nothing_applied_is_failed():
    import note_ops
    out, code = note_ops.components_result(
        {"status": "error", "reason": "note_not_locatable", "applied": [], "failed": []},
        "j1", {"collection_id": "c"})
    assert out["outcome"] == "failed" and code == 1
    assert "改用 note_id" in out["hint"]


def test_components_gone_and_timeout_are_unknown_not_failed():
    """非幂等：台账失效或轮询超时一律 unknown（exit 0），落 failed 会诱导 agent 重提交，
    活动重复注入的话题会在正文里只增不减、而且真的发出去。"""
    import note_ops
    for view in ({"status": "gone"}, {"status": "running"}):
        out, code = note_ops.components_result(view, "j1", {"activity_id": "a"})
        assert out["outcome"] == "unknown" and code == 0
        assert "核对" in out["hint"]


def test_components_items_accept_dict_shape():
    import note_ops
    out, _ = note_ops.components_result(
        {"status": "done", "applied": {"collection_id": "ok"}, "failed": {"activity_id": "dropped"}},
        "j1", {})
    assert out["outcome"] == "partial"
    assert out["failed"] == ["activity_id=dropped"]


# ---- 可见性：只收整数 0/1，布尔必须被拒 ----

def test_visibility_rejects_bool_and_out_of_range(monkeypatch):
    """JSON 里传 true，服务端 pydantic 会读成 1 = 悄悄把笔记藏起来。客户端先拒掉。"""
    import note_ops
    monkeypatch.setattr(note_ops, "send_request",
                        lambda *a, **k: _Resp(200, {"change_id": "v1"}))
    for bad in (True, False, 2, 4):
        with pytest.raises(ValueError):
            note_ops.start_visibility("http://x", "k", 1, bad, note_id="a")


def test_visibility_payload_is_int(monkeypatch):
    import note_ops
    seen = {}

    def fake(method, url, key, payload=None, timeout=60):
        seen["payload"] = payload
        return _Resp(200, {"change_id": "v1"})

    monkeypatch.setattr(note_ops, "send_request", fake)
    assert note_ops.start_visibility("http://x", "k", 1, 1, note_id="a") == "v1"
    assert seen["payload"]["target_privacy"] == 1
    assert isinstance(seen["payload"]["target_privacy"], int)
    assert not isinstance(seen["payload"]["target_privacy"], bool)


def test_visibility_error_and_timeout_envelopes(monkeypatch):
    import note_ops
    monkeypatch.setattr(note_ops.time, "sleep", lambda s: None)
    monkeypatch.setattr(note_ops, "poll_task",
                        lambda *a, **k: {"status": "error", "reason": "boom"})
    out, code = note_ops.poll_visibility("http://x", "k", "v1", 1, 1)
    assert out["outcome"] == "failed" and code == 1 and "再次把它藏起来" in out["hint"]

    monkeypatch.setattr(note_ops, "poll_task", lambda *a, **k: {"status": "running"})
    out, code = note_ops.poll_visibility("http://x", "k", "v1", 0, 1)
    assert out["outcome"] == "unknown" and code == 0 and out["target"] == "公开可见"


# ---- 评论：非幂等，未知不冒充失败 ----

def test_comment_error_and_unknown(monkeypatch):
    import note_ops
    monkeypatch.setattr(note_ops, "poll_task", lambda *a, **k: {"status": "error", "reason": "x"})
    out, code = note_ops.poll_comment("http://x", "k", "c1", 1)
    assert out["outcome"] == "failed" and code == 1 and "评论区" in out["hint"]

    monkeypatch.setattr(note_ops, "poll_task", lambda *a, **k: {"status": "gone"})
    out, code = note_ops.poll_comment("http://x", "k", "c1", 1)
    assert out["outcome"] == "unknown" and code == 0


# ---- 轮询：partially_applied 是终态；瞬时故障容忍 ----

def test_poll_task_stops_on_partially_applied(monkeypatch):
    import note_ops
    views = iter([{"status": "running"}, {"status": "partially_applied", "failed": ["a"]}])
    monkeypatch.setattr(note_ops, "send_request", lambda *a, **k: _Resp(200, next(views)))
    monkeypatch.setattr(note_ops.time, "sleep", lambda s: None)
    view = note_ops.poll_task("http://x", "k", "http://x/j", 60, note_ops.COMPONENT_TERMINAL)
    assert view["status"] == "partially_applied"


def test_poll_task_tolerates_transient_then_succeeds(monkeypatch):
    import note_ops
    seq = [_Resp(500, {}), _Resp(200, {"status": "running"}), _Resp(200, {"status": "done"})]
    monkeypatch.setattr(note_ops, "send_request", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(note_ops.time, "sleep", lambda s: None)
    assert note_ops.poll_task("http://x", "k", "http://x/j", 60, {"done", "error"})["status"] == "done"


def test_poll_task_404_means_gone(monkeypatch):
    import note_ops
    monkeypatch.setattr(note_ops, "send_request", lambda *a, **k: _Resp(404, {}))
    assert note_ops.poll_task("http://x", "k", "http://x/j", 60, {"done"})["status"] == "gone"


# ---- main：入队之后的异常绝不落 failed ----

def _run_main(monkeypatch, capsys, argv):
    import note_ops
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(note_ops.nbdpsy_common, "get_secret", lambda k: "key")
    monkeypatch.setattr(note_ops.nbdpsy_common, "xhs_api_base", lambda: "http://x")
    monkeypatch.setattr(note_ops, "resolve_account", lambda *a: (1, "号", None))
    with pytest.raises(SystemExit) as e:
        note_ops.main()
    return json.loads(capsys.readouterr().out), e.value.code


def test_main_comment_network_failure_after_enqueue_stays_unknown(monkeypatch, capsys):
    """评论已经提交出去了，轮询时网络断——这时报 failed 会让 agent 重发，评论区出现两条。"""
    import note_ops

    def boom(*a, **k):
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(note_ops, "start_comment", lambda *a, **k: "c9")
    monkeypatch.setattr(note_ops, "poll_comment", boom)
    out, code = _run_main(monkeypatch, capsys, [
        "note_ops.py", "--comment", "--account", "1", "--title", "标题", "--text", "抱抱"])
    assert out["outcome"] == "unknown" and out["comment_id"] == "c9" and code == 0
    assert "非幂等" in out["hint"]


def test_main_components_network_failure_after_enqueue_stays_unknown(monkeypatch, capsys):
    import note_ops

    def boom(*a, **k):
        raise RuntimeError("timed out")

    monkeypatch.setattr(note_ops, "start_components", lambda *a, **k: "j9")
    monkeypatch.setattr(note_ops, "poll_components", boom)
    out, code = _run_main(monkeypatch, capsys, [
        "note_ops.py", "--set-components", "--account", "1", "--note-id", "n1",
        "--activity-id", "43561"])
    assert out["outcome"] == "unknown" and out["job_id"] == "j9" and code == 0


def test_main_failure_before_enqueue_is_failed(monkeypatch, capsys):
    """还没入队就挂了（如账号解析失败）——这才是真 failed，可以修因重来。"""
    import note_ops

    def boom(*a, **k):
        raise ValueError("账号「x」不存在或未授权")

    monkeypatch.setattr(note_ops, "resolve_account", boom)
    monkeypatch.setattr(sys, "argv", ["note_ops.py", "--comment", "--account", "x",
                                      "--title", "t", "--text", "hi"])
    monkeypatch.setattr(note_ops.nbdpsy_common, "get_secret", lambda k: "key")
    monkeypatch.setattr(note_ops.nbdpsy_common, "xhs_api_base", lambda: "http://x")
    with pytest.raises(SystemExit) as e:
        note_ops.main()
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "failed" and e.value.code == 1


def test_main_set_components_requires_at_least_one_item(monkeypatch, capsys):
    import note_ops
    monkeypatch.setattr(sys, "argv", ["note_ops.py", "--set-components", "--account", "1",
                                      "--note-id", "n1"])
    monkeypatch.setattr(note_ops.nbdpsy_common, "get_secret", lambda k: "key")
    monkeypatch.setattr(note_ops.nbdpsy_common, "xhs_api_base", lambda: "http://x")
    with pytest.raises(SystemExit) as e:
        note_ops.main()
    assert e.value.code == 2  # argparse 用法错误

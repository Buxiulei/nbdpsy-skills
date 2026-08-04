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
    assert "只对没生效的那几项" in out["hint"]


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


def test_applied_is_tristate_null_means_not_requested():
    """applied 是逐项三态：true=生效，false=没生效，**null=本次没请求这项**（不是失败）。
    把 null 当失败会让「只改了标题」的任务被判成部分失败。"""
    import note_ops
    out, code = note_ops.components_result(
        {"status": "done", "applied": {"title": True, "collection": None, "activity": None}},
        "j1", {"title": "新标题"})
    assert out["outcome"] == "done" and code == 0 and out["applied"] == ["title"]

    out, code = note_ops.components_result(
        {"status": "done", "applied": {"title": True, "activity": False}},
        "j1", {"title": "x", "activity_id": "43561"})
    assert out["outcome"] == "partial" and code == 1
    assert out["applied"] == ["title"] and out["not_applied"] == ["activity"]
    assert "08-03" in out["hint"]  # 平台收走了编辑页的关联活动区


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


# ---- 互动补量：提交即返回，绝不轮询；非幂等 ----

def test_backfill_scope_validated_and_payload_shape(monkeypatch):
    import note_ops
    seen = {}

    def fake(method, url, key, payload=None, timeout=60):
        seen["payload"] = payload
        return _Resp(200, {"job_id": "b1"})

    monkeypatch.setattr(note_ops, "send_request", fake)
    assert note_ops.start_interaction_backfill("http://x", "k", "account", target_account_id=5) == "b1"
    assert seen["payload"] == {"scope": "account", "target_account_id": 5}

    note_ops.start_interaction_backfill("http://x", "k", "newcomer", actor_account_id=9)
    assert seen["payload"] == {"scope": "newcomer", "actor_account_id": 9}

    note_ops.start_interaction_backfill("http://x", "k", "all")
    assert seen["payload"] == {"scope": "all"}

    with pytest.raises(ValueError):
        note_ops.start_interaction_backfill("http://x", "k", "everything")


def test_backfill_status_404_and_error_hint(monkeypatch):
    import note_ops
    monkeypatch.setattr(note_ops, "send_request", lambda *a, **k: _Resp(404, {}))
    assert note_ops.interaction_backfill_status("http://x", "k", "b9")["available"] is False

    monkeypatch.setattr(note_ops, "send_request",
                        lambda *a, **k: _Resp(200, {"status": "error", "done": 12}))
    view = note_ops.interaction_backfill_status("http://x", "k", "b1")
    assert "不要盲目重试" in view["hint"] and "restricted" in view["hint"]


def test_main_backfill_submits_without_polling(monkeypatch, capsys):
    """六天的任务守着轮询没意义，超时还会给出误导性的 unknown——提交完就返回。"""
    import note_ops
    called = {"poll": 0}
    monkeypatch.setattr(note_ops, "poll_task",
                        lambda *a, **k: called.__setitem__("poll", called["poll"] + 1))
    monkeypatch.setattr(note_ops, "start_interaction_backfill", lambda *a, **k: "b7")
    monkeypatch.setattr(sys, "argv", ["note_ops.py", "--backfill-interactions", "--scope", "all"])
    monkeypatch.setattr(note_ops.nbdpsy_common, "get_secret", lambda k: "key")
    monkeypatch.setattr(note_ops.nbdpsy_common, "xhs_api_base", lambda: "http://x")
    note_ops.main()  # 走 return 而非 sys.exit
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "submitted" and out["job_id"] == "b7" and called["poll"] == 0
    assert "设计意图" in out["hint"] and "六天" in out["hint"]


def test_main_backfill_account_scope_requires_account(monkeypatch, capsys):
    import note_ops
    monkeypatch.setattr(sys, "argv", ["note_ops.py", "--backfill-interactions",
                                      "--scope", "account"])
    monkeypatch.setattr(note_ops.nbdpsy_common, "get_secret", lambda k: "key")
    monkeypatch.setattr(note_ops.nbdpsy_common, "xhs_api_base", lambda: "http://x")
    with pytest.raises(SystemExit) as e:
        note_ops.main()
    assert e.value.code == 2


# ---- 编辑能力（title/content/images）与 aborted_before_submit ----

def test_aborted_before_submit_is_the_one_safe_retry():
    """整单在提交前中止 = 笔记原样。这是唯一不需要先核对现状就能重试的失败——
    落成普通 failed 会让 agent 白白去人工核对；落成 unknown 又会拦住本可以直接重来的重试。"""
    import note_ops
    out, code = note_ops.components_result(
        {"status": "error", "aborted_before_submit": True,
         "failed": ["content: 超长"], "images_before": 4},
        "j1", {"content": "x" * 10})
    assert out["outcome"] == "aborted" and code == 1
    assert "笔记保持原样" in out["hint"] and "安全重试" in out["hint"]
    assert out["images_before"] == 4


def test_topics_dropped_surfaced_on_success():
    """改正文会丢掉既有话题实体——成功也要把这件事说出来，否则运营发现不了。"""
    import note_ops
    out, code = note_ops.components_result(
        {"status": "done", "applied": {"content": True}, "topics_dropped": ["CPTSD", "情绪内耗"]},
        "j1", {"content": "新正文"})
    assert out["outcome"] == "done" and code == 0
    assert out["topics_dropped"] == ["CPTSD", "情绪内耗"] and "丢掉既有话题" in out["hint"]


def test_image_ops_require_expected_count_guard():
    """动图片必须带防呆闸：少了它服务端 422，但报错时人常搞不清缺什么，所以本地先拦。"""
    import note_ops
    with pytest.raises(ValueError) as ei:
        note_ops.check_component_request({"remove_image_indexes": [2]})
    assert "expected-image-count" in str(ei.value)
    with pytest.raises(ValueError):
        note_ops.check_component_request({"add_images": ["http://x/a.png"]})
    # 给了就放行
    note_ops.check_component_request({"add_images": ["http://x/a.png"], "expected_image_count": 3})


def test_content_length_and_warnings():
    import note_ops
    with pytest.raises(ValueError):
        note_ops.check_component_request({"content": "字" * 901})
    warns = note_ops.check_component_request(
        {"content": "短正文", "activity_id": "1", "collection_id": "c"})
    joined = " ".join(warns)
    assert "丢掉既有话题实体" in joined          # 改正文的代价
    assert "08-03" in joined                      # 活动入口被收走
    assert "collection_chosen_unverifiable" in joined   # 合集该配 --collection-name


def test_quote_no_longer_implicit():
    """引用的隐式推导已被服务端收口：不显式要就一定不挂。批量挂引用最容易在这里静默漏。"""
    import note_ops
    warns = " ".join(note_ops.check_component_request({"collection_id": "c"}))
    assert "不会挂引用" in warns and "--related-counselor" in warns
    # 显式要了就不再啰嗦
    quiet = " ".join(note_ops.check_component_request(
        {"collection_id": "c", "related_counselor": "李宇"}))
    assert "不会挂引用" not in quiet


def test_add_image_rejects_local_path():
    """--add-image 只收直链/uploads 路径，本地路径服务端 422「无法识别的图片项」。"""
    import note_ops
    with pytest.raises(ValueError) as ei:
        note_ops.check_component_request(
            {"add_images": ["/home/roots/x/P01.png"], "expected_image_count": 3})
    assert "--upload-images" in str(ei.value)
    note_ops.check_component_request(
        {"add_images": ["https://x/a.png", "/uploads/b.png"], "expected_image_count": 3})


def test_topic_tags_must_not_have_spaces():
    import note_ops
    warns = " ".join(note_ops.check_component_request(
        {"content": "正文 #A[话题]# #B[话题]#"}))
    assert "不能留空格" in warns and "content_readback_mismatch" in warns


def test_expected_image_count_hint_says_before_not_target():
    import note_ops
    with pytest.raises(ValueError) as ei:
        note_ops.check_component_request({"remove_image_indexes": [1]})
    assert "编辑前" in str(ei.value) and "传目标张数是最常见的理解反了" in str(ei.value)

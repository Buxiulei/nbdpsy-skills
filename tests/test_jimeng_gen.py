"""jimeng_gen 双后端契约测试（全离线：假 requests + 假 dreamina CLI，绝不打网络/不跑真 CLI）。

覆盖：后端解析矩阵 / server 提交 payload 与幂等重发 / server 取片轮询下载 /
fetch 按 id 形态分派 / batch 逐镜独立与回落 / credits 形态 / check_env 后端感知。
"""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"))

import pytest

import jimeng_gen as jg

BASE = "https://mcp.nbdpsy.com"
LOCAL_SID = "3d64c2221c0e07da"      # 本机 CLI 的 submit_id 形态：16 位 hex


# ---------- 夹具与假件 ----------

@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """每个用例从干净状态起跑：探测缓存清空、凭据只认显式 env、绝不读真 secrets/工作区。"""
    jg._PROBE_CACHE.clear()
    for k in (jg.BACKEND_ENV, "NBDPSY_XHS_API_KEY", "NBDPSY_VIDEO_API_BASE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NBDPSY_SECRETS", str(tmp_path / "none.env"))
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setattr(jg.time, "sleep", lambda s: None)
    yield
    jg._PROBE_CACHE.clear()


class FakeResp:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else (
            json.dumps(payload, ensure_ascii=False) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeDownload:
    """requests.get(stream=True) 的最小上下文管理器替身。"""
    def __init__(self, data=b"MP4-BYTES"):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        yield self._data


def fake_requests(monkeypatch, handler, *, downloader=None):
    """把假 requests 模块塞进 jimeng_gen 的惰性 import 点。返回 (calls, mod)。
    mod.exceptions.Timeout / ConnectionError 供用例主动抛出，复刻网络抖动。"""
    mod = types.ModuleType("requests")

    class Timeout(Exception):
        pass

    class ConnErr(Exception):
        pass

    mod.exceptions = types.SimpleNamespace(Timeout=Timeout, ConnectionError=ConnErr)
    calls = []
    downloads = []

    def request(method, url, json=None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "payload": json,
                      "headers": headers, "timeout": timeout})
        return handler(method, url, json)

    def get(url, stream=False, timeout=None):
        downloads.append(url)
        return (downloader or FakeDownload)()

    mod.request = request
    mod.get = get
    mod.downloads = downloads
    monkeypatch.setattr(jg, "_requests", lambda: mod)
    return calls, mod


def with_key(monkeypatch, key="k-test"):
    monkeypatch.setenv("NBDPSY_XHS_API_KEY", key)


def status_handler(logged_in=True, credit=15060, status_code=200, payload=None):
    """只回 /api/dreamina-status 的 handler。"""
    def handler(method, url, body):
        assert url.endswith(jg.EP_DREAMINA_STATUS), url
        if payload is not None or status_code >= 400:
            return FakeResp(status_code, payload)
        return FakeResp(200, {"logged_in": logged_in, "credit": credit,
                              "compliance_confirmed_models": ["seedance2.0fast"]})
    return handler


def fake_local_cli(monkeypatch, submit_id=LOCAL_SID):
    """假的 dreamina CLI：_check_cli 恒可用、_run 回一份干净 JSON。返回调用记录。"""
    monkeypatch.setattr(jg, "_check_cli", lambda: None)
    calls = []

    def _run(args, timeout=180):
        calls.append(args)
        return 0, json.dumps({"submit_id": submit_id, "gen_status": "querying"}), ""

    monkeypatch.setattr(jg, "_run", _run)
    return calls


# ---------- 1. 后端解析矩阵 ----------

def test_no_key_resolves_local_without_touching_network(monkeypatch):
    """没 apikey 时连探测都不该发生（无凭据 = 无 server 可用），直接本机 CLI。"""
    calls, _ = fake_requests(monkeypatch, lambda *a: pytest.fail("不该打网络"))
    assert jg.resolve_backend() == "local"
    assert calls == []
    assert jg.probe_server()["reason"].endswith("NBDPSY_XHS_API_KEY")


def test_key_plus_404_resolves_local(monkeypatch):
    """server 还没上线即梦能力（404/405）→ 回落本机 CLI，不是报错。"""
    with_key(monkeypatch)
    fake_requests(monkeypatch, status_handler(status_code=404, payload={"detail": "Not Found"}))
    assert jg.resolve_backend() == "local"
    assert "404" in jg.probe_server()["reason"]


def test_key_plus_405_resolves_local(monkeypatch):
    with_key(monkeypatch)
    fake_requests(monkeypatch, status_handler(status_code=405, payload={"detail": "Method Not Allowed"}))
    assert jg.resolve_backend() == "local"


def test_key_plus_logged_in_resolves_server(monkeypatch):
    with_key(monkeypatch)
    calls, _ = fake_requests(monkeypatch, status_handler(logged_in=True))
    assert jg.resolve_backend() == "server"
    assert calls[0]["url"] == BASE + jg.EP_DREAMINA_STATUS
    assert calls[0]["headers"]["Authorization"] == "Bearer k-test"   # 家规：Bearer 鉴权


def test_network_error_resolves_local(monkeypatch):
    with_key(monkeypatch)

    def boom(method, url, body):
        raise OSError("Connection refused")

    fake_requests(monkeypatch, boom)
    assert jg.resolve_backend() == "local"


def test_missing_requests_resolves_local(monkeypatch):
    """老机器没装 requests：探测算失败 → 本机 CLI 照跑，绝不炸。"""
    with_key(monkeypatch)

    def no_requests():
        raise ImportError("No module named 'requests'")

    monkeypatch.setattr(jg, "_requests", no_requests)
    assert jg.resolve_backend() == "local"
    assert "requests" in jg.probe_server()["reason"]


def test_logged_out_falls_back_to_local_cli(monkeypatch):
    with_key(monkeypatch)
    fake_requests(monkeypatch, status_handler(logged_in=False))
    monkeypatch.setattr(jg, "_check_cli", lambda: None)   # 本机有 CLI
    assert jg.resolve_backend() == "local"


def test_logged_out_without_local_cli_raises(monkeypatch):
    """server 未登录且本机没 CLI —— 必须明确报错，不许静默降级成"提交了但没反应"。"""
    with_key(monkeypatch)
    fake_requests(monkeypatch, status_handler(logged_in=False))
    monkeypatch.setattr(jg, "_check_cli", lambda: "未找到 dreamina CLI。")
    with pytest.raises(jg.BackendError) as ei:
        jg.resolve_backend()
    assert "logged_in=false" in str(ei.value)


def test_probe_cached_once_per_process(monkeypatch):
    with_key(monkeypatch)
    calls, _ = fake_requests(monkeypatch, status_handler(logged_in=True))
    assert jg.resolve_backend() == "server"
    assert jg.resolve_backend() == "server"
    assert len([c for c in calls if c["url"].endswith(jg.EP_DREAMINA_STATUS)]) == 1


def test_explicit_backend_skips_probe(monkeypatch):
    """显式 --backend 一票决定，连探测都不发（离线也能强制 local）。"""
    with_key(monkeypatch)
    calls, _ = fake_requests(monkeypatch, lambda *a: pytest.fail("显式 backend 不该探测"))
    assert jg.resolve_backend("local") == "local"
    assert jg.resolve_backend("server") == "server"
    assert calls == []


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv(jg.BACKEND_ENV, "server")
    fake_requests(monkeypatch, lambda *a: pytest.fail("环境变量定死后不该探测"))
    assert jg.resolve_backend() == "server"


def test_explicit_beats_env_var(monkeypatch):
    monkeypatch.setenv(jg.BACKEND_ENV, "server")
    assert jg.resolve_backend("local") == "local"


def test_explicit_auto_beats_env_var(monkeypatch):
    """显式写 --backend auto 要压过环境变量，回到自动探测。"""
    monkeypatch.setenv(jg.BACKEND_ENV, "server")
    with_key(monkeypatch)
    fake_requests(monkeypatch, status_handler(logged_in=True))
    assert jg.resolve_backend("auto") == "server"
    jg._PROBE_CACHE.clear()
    fake_requests(monkeypatch, status_handler(status_code=404, payload={"detail": "x"}))
    assert jg.resolve_backend("auto") == "local"


# ---------- 2. server 提交 ----------

def submit_handler(resp_by_call, seen=None):
    """按调用序返回预置响应；元素可以是 FakeResp 或 callable(raise 用)。"""
    it = iter(resp_by_call)

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True, "credit": 100})
        if seen is not None:
            seen.append(body)
        nxt = next(it)
        if callable(nxt):
            return nxt()
        return nxt
    return handler


def test_server_submit_payload_text2video(monkeypatch):
    with_key(monkeypatch)
    seen = []
    calls, _ = fake_requests(monkeypatch, submit_handler([FakeResp(202, {"clip_id": 77})], seen))
    r = jg.submit("text2video", "温暖诊室空镜", backend="server", duration=6,
                  ratio="9:16", model="seedance2.0fast_vip")
    # raw 是服务化之前就有的键（本地 CLI 版回 CLI 原始 JSON）→ server 侧回服务端回执原文，
    # 旧契约读 r["raw"] 的下游不能 KeyError
    assert r == {"success": True, "submit_id": "77", "operation": "text2video",
                 "backend": "server", "client_ref": seen[0]["client_ref"],
                 "raw": {"clip_id": 77}}
    post = [c for c in calls if c["method"] == "POST"][0]
    assert post["url"] == BASE + jg.EP_CLIP_SUBMIT
    assert seen[0]["operation"] == "text2video"
    assert seen[0]["prompt"] == "温暖诊室空镜"
    assert seen[0]["duration"] == 6
    assert seen[0]["model"] == "seedance2.0fast_vip"
    assert seen[0]["ratio"] == "9:16"
    assert len(seen[0]["client_ref"]) == 32     # uuid4 幂等键


def test_server_submit_image2video_never_sends_ratio(monkeypatch):
    """image2video 画幅由输入图推断，带 ratio 服务端 422 —— 客户端就不许放行。"""
    with_key(monkeypatch)
    seen = []
    fake_requests(monkeypatch, submit_handler([FakeResp(202, {"clip_id": "c1"})], seen))
    r = jg.submit("image2video", "镜头缓慢推近", backend="server",
                  images=["/uploads/clips/p01.png"], duration=8, ratio="9:16")
    assert r["success"] is True and r["submit_id"] == "c1"
    assert "ratio" not in seen[0]
    assert seen[0]["image"] == "/uploads/clips/p01.png"


def test_server_submit_text2video_never_sends_image(monkeypatch):
    """text2video 不吃图（本地 CLI 就完全忽略 images，SKILL.md 也明文写了"不补不会吃图"）：
    哪怕给的是 server 取得到的远程图，payload 里也**不许出现 image**，否则服务端可能 422。"""
    with_key(monkeypatch)
    seen = []
    fake_requests(monkeypatch, submit_handler([FakeResp(202, {"clip_id": "t1"})], seen))
    r = jg.submit("text2video", "温暖诊室空镜", backend="server",
                  images=["/uploads/clips/p01.png"], duration=5, ratio="9:16")
    assert r["success"] is True and r["submit_id"] == "t1"
    assert "image" not in seen[0]
    assert seen[0]["ratio"] == "9:16"          # text2video 的 ratio 照旧带


def test_server_submit_multimodal2video_sends_single_remote_image(monkeypatch):
    """multimodal2video 反过来：image 是它唯一能表达媒体的字段，必须带。"""
    with_key(monkeypatch)
    seen = []
    fake_requests(monkeypatch, submit_handler([FakeResp(202, {"clip_id": "m1"})], seen))
    r = jg.submit("multimodal2video", "轻轻点头", backend="server",
                  images=["/uploads/clips/p02.png"], duration=6, ratio="9:16")
    assert r["success"] is True and r["submit_id"] == "m1"
    assert seen[0]["image"] == "/uploads/clips/p02.png"
    assert seen[0]["ratio"] == "9:16"


def test_server_submit_multimodal2video_without_media_is_rejected_locally(monkeypatch):
    """没媒体的 multimodal2video 在本地就拦下（校验不能被上面的改动弄丢），一个请求都不发。"""
    with_key(monkeypatch)
    calls, _ = fake_requests(monkeypatch, submit_handler([]))
    r = jg.submit("multimodal2video", "x", backend="server")
    assert r["success"] is False and "multimodal2video" in r["error"]
    assert [c for c in calls if c["method"] == "POST"] == []


def test_server_submit_5xx_never_resends(monkeypatch):
    """资金安全：5xx 是服务端**已收到**这次提交（可能已入队扣分），重发就是赌服务端幂等 ——
    POST 只能恰好一次，且如实判失败。"""
    with_key(monkeypatch)
    seen = []
    calls, _ = fake_requests(
        monkeypatch, submit_handler([FakeResp(500, {"error": "worker 挂了"}),
                                     FakeResp(202, {"clip_id": "不该有第二次"})], seen))
    r = jg.submit("text2video", "x", backend="server")
    assert r["success"] is False and "500" in r["error"] and "worker 挂了" in r["error"]
    assert len([c for c in calls if c["method"] == "POST"]) == 1
    assert len(seen) == 1


def test_server_submit_4xx_passes_detail_through_without_retry(monkeypatch):
    """HTTP 4xx 是服务端已收到并明确拒绝 —— 绝不重发（重发 = 双倍扣分），原文透出。"""
    with_key(monkeypatch)
    seen = []
    calls, _ = fake_requests(
        monkeypatch, submit_handler([FakeResp(422, {"detail": "image2video 不接受 ratio"})], seen))
    r = jg.submit("text2video", "x", backend="server")
    assert r["success"] is False
    assert "422" in r["error"] and "image2video 不接受 ratio" in r["error"]
    assert len([c for c in calls if c["method"] == "POST"]) == 1
    assert len(seen) == 1


def test_server_submit_409_passes_through(monkeypatch):
    """余额不足以再提交任何一镜 → 409（detail 键），如实透出而不是自作主张重试。"""
    with_key(monkeypatch)
    fake_requests(monkeypatch, submit_handler([FakeResp(409, {"detail": "积分不足"})]))
    r = jg.submit("text2video", "x", backend="server")
    assert r["success"] is False and "409" in r["error"] and "积分不足" in r["error"]


def test_server_submit_compliance_text_passes_through_with_hint(monkeypatch):
    with_key(monkeypatch)
    fake_requests(monkeypatch, submit_handler(
        [FakeResp(400, {"error": "AigcComplianceConfirmationRequired"})]))
    r = jg.submit("text2video", "x", backend="server")
    assert r["success"] is False
    assert "AigcComplianceConfirmationRequired" in r["error"]      # 原文
    assert "Dreamina 网页端" in r["error"] and "一次性授权" in r["error"]


def test_server_submit_network_retry_reuses_client_ref_once(monkeypatch):
    """网络抖动重发**必须复用同一 client_ref**（幂等键防双扣），且只重发一次。"""
    with_key(monkeypatch)
    seen = []
    holder = {}

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        seen.append(body)
        if len(seen) == 1:
            raise holder["mod"].exceptions.ConnectionError("connection reset")
        return FakeResp(202, {"clip_id": 9})

    calls, mod = fake_requests(monkeypatch, handler)
    holder["mod"] = mod
    r = jg.submit("text2video", "x", backend="server")
    assert r["success"] is True and r["submit_id"] == "9"
    assert len(seen) == 2
    assert seen[0]["client_ref"] == seen[1]["client_ref"]     # 同一把幂等键
    assert seen[0] is seen[1] or seen[0] == seen[1]           # 整份 payload 原样复用


def test_server_submit_network_retry_gives_up_after_one(monkeypatch):
    with_key(monkeypatch)
    seen = []
    holder = {}

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        seen.append(body)
        raise holder["mod"].exceptions.Timeout("read timeout")

    _, mod = fake_requests(monkeypatch, handler)
    holder["mod"] = mod
    r = jg.submit("text2video", "x", backend="server")
    assert r["success"] is False
    assert len(seen) == 2                                   # 只重发一次
    assert seen[0]["client_ref"] == seen[1]["client_ref"]
    assert "不会重复扣分" in r["error"]


def test_server_submit_missing_clip_id_is_human_error(monkeypatch):
    with_key(monkeypatch)
    fake_requests(monkeypatch, submit_handler([FakeResp(202, {"queued": True})]))
    r = jg.submit("text2video", "x", backend="server")
    assert r["success"] is False and jg.K_CLIP_ID in r["error"]


def test_server_submit_non_json_is_human_error(monkeypatch):
    with_key(monkeypatch)
    fake_requests(monkeypatch, submit_handler([FakeResp(202, None, text="<html>bad gateway</html>")]))
    r = jg.submit("text2video", "x", backend="server")
    assert r["success"] is False and "不是 JSON" in r["error"]


def test_server_submit_validates_locally_before_spending(monkeypatch):
    """非法 duration/model 在本地就拦下来，一个请求都不发（省钱也省来回）。"""
    with_key(monkeypatch)
    calls, _ = fake_requests(monkeypatch, submit_handler([]))
    r = jg.submit("text2video", "x", backend="server", duration=99)
    assert r["success"] is False and "duration" in r["error"]
    assert [c for c in calls if c["method"] == "POST"] == []


def test_server_submit_local_image_falls_back_to_local_cli(monkeypatch):
    """参考图在本机（server 取不到）→ 整镜回落本地 CLI，而不是把 server 拿不到的路径发过去。"""
    with_key(monkeypatch)
    fake_requests(monkeypatch, submit_handler([]))
    fake_local_cli(monkeypatch)
    r = jg.submit("image2video", "推近", backend="server", images=["./images/P01.png"])
    assert r["success"] is True and r["backend"] == "local" and r["submit_id"] == LOCAL_SID


# ---------- 3. server 取片 ----------

def clip_handler(views, video_url="/uploads/clips/77.mp4", credit=55):
    """按调用序回单镜状态；views 是 status 列表。"""
    it = iter(views)

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        st = next(it)
        data = {"status": st, "model": "seedance2.0fast", "queued_seconds": 90}
        if st == "done":
            data.update({"video_url": video_url, "credit_count": credit,
                         "expires_at": "2026-08-12T00:00:00+08:00"})
        if st == "error":
            data["error"] = "AigcComplianceConfirmationRequired"
        return FakeResp(200, data)
    return handler


def test_server_fetch_polls_to_done_and_downloads(monkeypatch, tmp_path):
    with_key(monkeypatch)
    calls, mod = fake_requests(monkeypatch, clip_handler(["queued", "querying", "done"]))
    r = jg.fetch("77", str(tmp_path), backend="server", interval=0)
    assert r["success"] is True
    assert r["status"] == "success" and r["submit_id"] == "77"
    assert r["credit_count"] == 55 and r["error"] is None and r["backend"] == "server"
    out = tmp_path / "77_video_0.mp4"
    assert r["videos"] == [str(out)]
    assert out.read_bytes() == b"MP4-BYTES"
    assert not list(tmp_path.glob("*.part"))                      # 半截文件不留
    assert mod.downloads == [BASE + "/uploads/clips/77.mp4"]      # 相对路径拼成公网直链
    assert [c["url"] for c in calls if c["method"] == "GET"][-1] == \
        BASE + jg.EP_CLIP_STATUS.format(clip_id="77")


def test_server_fetch_keeps_legacy_meta_key(monkeypatch, tmp_path):
    """meta 是服务化之前 success 分支就有的键（本地 CLI 回 result_json.videos[]）——
    server 侧也必须给，且形状一致（逐片 dict 列表），否则按旧契约读 r["meta"] 的下游 KeyError。"""
    with_key(monkeypatch)
    fake_requests(monkeypatch, clip_handler(["done"]))
    r = jg.fetch("77", str(tmp_path), backend="server", interval=0)
    assert r["meta"] == [{"path": str(tmp_path / "77_video_0.mp4"),
                          "video_url": BASE + "/uploads/clips/77.mp4"}]
    assert [m["path"] for m in r["meta"]] == r["videos"]


def test_server_fetch_absolute_video_url_kept(monkeypatch, tmp_path):
    with_key(monkeypatch)
    _, mod = fake_requests(monkeypatch, clip_handler(["done"], video_url="https://cdn.x/y.mp4"))
    r = jg.fetch("88", str(tmp_path), backend="server", interval=0)
    assert r["success"] is True and mod.downloads == ["https://cdn.x/y.mp4"]


def test_server_fetch_error_status(monkeypatch, tmp_path):
    with_key(monkeypatch)
    fake_requests(monkeypatch, clip_handler(["querying", "error"]))
    r = jg.fetch("77", str(tmp_path), backend="server", interval=0)
    assert r["success"] is False and r["status"] == "error" and r["submit_id"] == "77"
    assert "AigcComplianceConfirmationRequired" in r["error"] and "一次性授权" in r["error"]


def test_server_fetch_timeout_keeps_submit_id(monkeypatch, tmp_path):
    """超时不是失败：submit_id 保住、明说稍后再 fetch 不重复扣分（绝不自动重提）。"""
    with_key(monkeypatch)
    fake_requests(monkeypatch, clip_handler(["querying"]))
    r = jg.fetch("77", str(tmp_path), backend="server", max_wait=0, interval=0)
    assert r["success"] is False and r["timed_out"] is True
    assert r["submit_id"] == "77" and r["status"] == "querying"
    assert "不重复扣分" in r["error"] and "fetch --submit-id 77" in r["error"]


def test_server_fetch_tolerates_transient_then_succeeds(monkeypatch, tmp_path):
    """一次 5xx/网络抖动绝不能判终态（会诱发重复提交 = 烧钱）。"""
    with_key(monkeypatch)
    seq = iter(["net", "500", "done"])

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        kind = next(seq)
        if kind == "net":
            raise OSError("timed out")
        if kind == "500":
            return FakeResp(500, {"error": "内部错误"})
        return FakeResp(200, {"status": "done", "video_url": "/uploads/a.mp4", "credit_count": 25})

    fake_requests(monkeypatch, handler)
    r = jg.fetch("77", str(tmp_path), backend="server", interval=0)
    assert r["success"] is True and r["credit_count"] == 25


def test_server_fetch_download_failure_keeps_link_and_id(monkeypatch, tmp_path):
    """片子已生成、只是没下下来 —— 不能让人以为要重提。"""
    with_key(monkeypatch)

    class Boom(FakeDownload):
        def raise_for_status(self):
            raise OSError("503 from cdn")

    fake_requests(monkeypatch, clip_handler(["done"]), downloader=Boom)
    r = jg.fetch("77", str(tmp_path), backend="server", interval=0)
    assert r["success"] is False and r["submit_id"] == "77"
    assert r["video_url"] == BASE + "/uploads/clips/77.mp4"
    assert "不重复扣分" in r["error"]
    assert not list(tmp_path.glob("*.part"))


def test_server_fetch_non_json_200_is_transient_then_stalls(monkeypatch, tmp_path):
    """200 + 非 JSON 正文（坏代理/网关欢迎页）长得跟「正常排队」一模一样 —— 必须按瞬时失败计数，
    连着 MAX_TRANSIENT+1 次就收工报异常，绝不空转满 max_wait（默认 30 分钟）。"""
    with_key(monkeypatch)
    polls = []

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        polls.append(url)
        # 没修好就会无限轮询（sleep 被夹具打成 no-op，deadline 那支根本走不到）——这里硬刹车
        assert len(polls) <= jg.MAX_TRANSIENT + 1, "非 JSON 响应没被计瞬时失败，空转了"
        return FakeResp(200, None, text="<html>502 Bad Gateway</html>")

    fake_requests(monkeypatch, handler)
    r = jg.fetch("77", str(tmp_path), backend="server", interval=0)
    assert len(polls) == jg.MAX_TRANSIENT + 1
    assert r["success"] is False and r["submit_id"] == "77"        # id 保住，不诱发重提
    assert "非 JSON" in r["error"] and "502 Bad Gateway" in r["error"]
    assert "不重复扣分" in r["error"]
    assert not r.get("timed_out")                                  # 是「查询异常」不是「还在排队」


def test_server_fetch_non_json_recovers_without_counting_as_done(monkeypatch, tmp_path):
    """瞬时非 JSON 之后恢复正常 → 计数清零，照常取片（一次坏网关不能把在跑的任务判死）。"""
    with_key(monkeypatch)
    seq = iter(["bad", "bad", "done"])

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        if next(seq) == "bad":
            return FakeResp(200, None, text="proxy error")
        return FakeResp(200, {"status": "done", "video_url": "/uploads/a.mp4", "credit_count": 25})

    fake_requests(monkeypatch, handler)
    r = jg.fetch("77", str(tmp_path), backend="server", interval=0)
    assert r["success"] is True and r["credit_count"] == 25


def test_server_fetch_sanitizes_clip_id_in_filename(monkeypatch, tmp_path):
    """病态 clip_id（server 返回值不可全信）不许拼进落盘路径造成逃逸；信封里的 submit_id 保持原值。"""
    with_key(monkeypatch)
    fake_requests(monkeypatch, clip_handler(["done"], video_url="/uploads/clips/evil.mp4"))
    out_dir = tmp_path / "clips"
    r = jg.fetch("../evil", str(out_dir), backend="server", interval=0)
    assert r["success"] is True
    assert r["submit_id"] == "../evil"                       # 原值不动
    got = Path(r["videos"][0])
    assert got.parent.resolve() == out_dir.resolve()         # 没逃出 out_dir
    assert got.name == ".._evil_video_0.mp4"                 # 文件名已消毒
    assert got.read_bytes() == b"MP4-BYTES"
    assert r["meta"][0]["path"] == str(got)


def test_server_fetch_404_is_permanent(monkeypatch, tmp_path):
    with_key(monkeypatch)
    calls, _ = fake_requests(monkeypatch, lambda m, u, b:
                             FakeResp(200, {"logged_in": True})
                             if u.endswith(jg.EP_DREAMINA_STATUS)
                             else FakeResp(404, {"error": "clip 不存在"}))
    r = jg.fetch("77", str(tmp_path), backend="server", interval=0)
    assert r["success"] is False and "404" in r["error"]
    assert len([c for c in calls if c["method"] == "GET"]) == 1   # 永久错误不重试


# ---------- 4. fetch 的 auto 分派（先问 server 认不认领，再按 id 形态兜底）----------

def stub_fetches(monkeypatch):
    monkeypatch.setattr(jg, "_local_fetch", lambda sid, out, **kw: {"success": True, "who": "local"})
    monkeypatch.setattr(jg, "_server_fetch", lambda cid, out, **kw: {"success": True, "who": "server"})


def owner_handler(owned):
    """auto fetch 的归属探测：owned 里的 id 回 200（server 认领），其余 404。"""
    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        cid = url.rsplit("/", 1)[-1]
        if cid in owned:
            return FakeResp(200, {"status": "queued"})
        return FakeResp(404, {"error": "clip 不存在"})
    return handler


def test_auto_fetch_goes_to_server_when_server_owns_the_id(monkeypatch, tmp_path):
    """契约只写了 `202 {clip_id}`、没约定形态：若 server 用 token_hex(8)/uuid4().hex[:16]，
    clip_id 恰好是 16 位 hex。只按形态分派会派给本机 CLI 去查一个不存在的任务、空转到 max_wait，
    运营多半判定任务丢了去重跑 gen = 双倍扣分。所以先问 server 认不认领（GET 免费不扣分）。"""
    with_key(monkeypatch)
    calls, _ = fake_requests(monkeypatch, owner_handler({LOCAL_SID}))
    stub_fetches(monkeypatch)
    assert jg.fetch(LOCAL_SID, str(tmp_path))["who"] == "server"
    probe = [c for c in calls if c["method"] == "GET"][-1]
    assert probe["url"] == BASE + jg.EP_CLIP_STATUS.format(clip_id=LOCAL_SID)


def test_auto_fetch_falls_back_to_id_shape_when_server_disowns(monkeypatch, tmp_path):
    """server 明确 404 → 按 id 形态兜底：存量 submit_ids.json 里的老任务照样本机取回。"""
    with_key(monkeypatch)
    fake_requests(monkeypatch, owner_handler(set()))
    stub_fetches(monkeypatch)
    assert jg.fetch(LOCAL_SID, str(tmp_path))["who"] == "local"     # 16 位 hex = 本机 CLI 的 id
    assert jg.fetch("12345", str(tmp_path))["who"] == "server"
    assert jg.fetch("clip_abc", str(tmp_path))["who"] == "server"
    # 长度不对的 hex 不算本机 id
    assert jg.fetch("3d64c222", str(tmp_path))["who"] == "server"


def test_auto_fetch_without_key_uses_id_shape_without_network(monkeypatch, tmp_path):
    """没凭据（纯本地运营）→ 一个请求都不发，形态兜底照旧。"""
    calls, _ = fake_requests(monkeypatch, lambda *a: pytest.fail("没凭据不该探测"))
    stub_fetches(monkeypatch)
    assert jg.fetch(LOCAL_SID, str(tmp_path))["who"] == "local"
    assert jg.fetch("clip_abc", str(tmp_path))["who"] == "server"
    assert calls == []


def test_auto_fetch_local_failure_hints_server_backend(monkeypatch, tmp_path):
    """探测判定不了（没凭据/网络不通）时仍可能派错——本机没取到就要提示「可能是 server clip_id」，
    否则运营只会以为任务丢了去重跑 gen。"""
    fake_requests(monkeypatch, lambda *a: pytest.fail("没凭据不该探测"))
    monkeypatch.setattr(jg, "_local_fetch",
                        lambda sid, out, **kw: {"success": False, "error": "等待 1800s 仍未完成"})
    r = jg.fetch(LOCAL_SID, str(tmp_path))
    assert r["success"] is False
    assert "等待 1800s 仍未完成" in r["error"] and "--backend server" in r["error"]


def test_explicit_backend_skips_owner_probe(monkeypatch, tmp_path):
    """显式 --backend 一票决定，连归属探测都不发。"""
    with_key(monkeypatch)
    calls, _ = fake_requests(monkeypatch, lambda *a: pytest.fail("显式 backend 不该探测"))
    stub_fetches(monkeypatch)
    assert jg.fetch(LOCAL_SID, str(tmp_path), backend="local")["who"] == "local"
    assert calls == []


def test_explicit_backend_beats_id_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(jg, "_local_fetch", lambda sid, out, **kw: {"success": True, "who": "local"})
    monkeypatch.setattr(jg, "_server_fetch", lambda cid, out, **kw: {"success": True, "who": "server"})
    assert jg.fetch(LOCAL_SID, str(tmp_path), backend="server")["who"] == "server"
    assert jg.fetch("12345", str(tmp_path), backend="local")["who"] == "local"


# ---------- 5. batch ----------

def write_plan(tmp_path, shots):
    p = tmp_path / "shots.json"
    p.write_text(json.dumps({"shots": shots}, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_batch_server_submit_only_maps_clip_ids_in_order(monkeypatch, tmp_path):
    """批量一次灌入：clip_ids 按传入顺序回，index 语义与本地路径一致。"""
    with_key(monkeypatch)
    seen = []

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        assert url == BASE + jg.EP_BATCH_SUBMIT
        seen.append(body)
        return FakeResp(202, {"batch_id": 7, "clip_ids": [101, 102]})

    calls, _ = fake_requests(monkeypatch, handler)
    plan = write_plan(tmp_path, [
        {"operation": "text2video", "prompt": "a", "duration": 5},
        {"operation": "image2video", "prompt": "b", "image": "/uploads/p02.png", "duration": 6},
    ])
    out = jg.batch(plan, str(tmp_path), submit_only=True)
    assert out["success"] is True and out["total"] == 2 and out["ok"] == 2
    assert out["backend"] == "server"
    assert [r["index"] for r in out["results"]] == [0, 1]
    assert [r["submit_id"] for r in out["results"]] == ["101", "102"]
    assert all(r["status"] == "submitted" and r["backend"] == "server" for r in out["results"])
    # 一次 POST 灌完两镜，逐镜带各自的幂等键
    assert len([c for c in calls if c["method"] == "POST"]) == 1
    assert [s["prompt"] for s in seen[0]["shots"]] == ["a", "b"]
    assert seen[0]["shots"][0]["client_ref"] != seen[0]["shots"][1]["client_ref"]
    assert "ratio" not in seen[0]["shots"][1]          # image2video 不带 ratio


def test_batch_mixed_backends_do_not_block_each_other(monkeypatch, tmp_path):
    """混合批：本机图那镜回落 local、非法参数那镜自己失败，都不连坐其余镜。"""
    with_key(monkeypatch)

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        return FakeResp(202, {"batch_id": 7, "clip_ids": [201, 202]})

    fake_requests(monkeypatch, handler)
    fake_local_cli(monkeypatch)
    plan = write_plan(tmp_path, [
        {"operation": "text2video", "prompt": "a", "duration": 5},
        {"operation": "image2video", "prompt": "b", "image": "./images/P02.png"},   # 本机图 → local
        {"operation": "image2video", "prompt": "c", "image": "/uploads/p03.png"},
        {"operation": "text2video", "prompt": "d", "duration": 99},                 # 非法 → 只败自己
    ])
    out = jg.batch(plan, str(tmp_path), submit_only=True)
    res = out["results"]
    assert [r["index"] for r in res] == [0, 1, 2, 3]
    assert res[0]["submit_id"] == "201" and res[0]["backend"] == "server"
    assert res[1]["backend"] == "local" and res[1]["submit_id"] == LOCAL_SID
    assert res[2]["submit_id"] == "202" and res[2]["backend"] == "server"
    assert res[3]["success"] is False and "duration" in res[3]["error"]
    assert out["total"] == 4 and out["ok"] == 3 and out["success"] is False


def test_batch_server_fetches_each_clip_when_not_submit_only(monkeypatch, tmp_path):
    with_key(monkeypatch)

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        if method == "POST":
            return FakeResp(202, {"batch_id": 7, "clip_ids": [301, 302]})
        cid = url.rsplit("/", 1)[-1]
        return FakeResp(200, {"status": "done", "video_url": f"/uploads/{cid}.mp4",
                              "credit_count": 25})

    fake_requests(monkeypatch, handler)
    plan = write_plan(tmp_path, [{"operation": "text2video", "prompt": "a"},
                                 {"operation": "text2video", "prompt": "b"}])
    out = jg.batch(plan, str(tmp_path), interval=0)
    assert out["success"] is True
    assert [Path(r["videos"][0]).name for r in out["results"]] == \
        ["301_video_0.mp4", "302_video_0.mp4"]
    assert [r["index"] for r in out["results"]] == [0, 1]


def test_batch_post_failure_does_not_lose_index_semantics(monkeypatch, tmp_path):
    with_key(monkeypatch)

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        return FakeResp(500, {"error": "worker 挂了"})

    fake_requests(monkeypatch, handler)
    plan = write_plan(tmp_path, [{"operation": "text2video", "prompt": "a"},
                                 {"operation": "text2video", "prompt": "b"}])
    out = jg.batch(plan, str(tmp_path), submit_only=True)
    assert out["success"] is False and out["ok"] == 0
    assert [r["index"] for r in out["results"]] == [0, 1]
    assert all("worker 挂了" in r["error"] for r in out["results"])


def test_batch_post_network_error_resends_once_with_same_refs(monkeypatch, tmp_path):
    """批量逐镜 ref 幂等已经 server 验收（2026-08-05 回执：同 refs 重放回原 clip_ids 零新增
    零扣分），网络异常允许重发一次——但必须**复用同一份 payload（同一组 client_ref）**，
    重新生成 ref 就等于新任务、双倍扣分。两次都失败时话术仍要点明幂等键保护。"""
    with_key(monkeypatch)
    posts = []
    holder = {}

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        assert url == BASE + jg.EP_BATCH_SUBMIT
        posts.append(body)
        raise holder["mod"].exceptions.Timeout("read timeout")

    _, mod = fake_requests(monkeypatch, handler)
    holder["mod"] = mod
    plan = write_plan(tmp_path, [{"operation": "text2video", "prompt": "a"},
                                 {"operation": "text2video", "prompt": "b"}])
    out = jg.batch(plan, str(tmp_path), submit_only=True)
    assert len(posts) == 2                                   # 恰好重发一次，不多不少
    refs0 = [s["client_ref"] for s in posts[0]["shots"]]
    refs1 = [s["client_ref"] for s in posts[1]["shots"]]
    assert refs0 == refs1                                    # 同一组幂等键，绝不重新生成
    assert out["success"] is False and out["ok"] == 0
    assert [r["index"] for r in out["results"]] == [0, 1]
    assert all("不会重复扣分" in r["error"] for r in out["results"])


def test_single_submit_still_retries_on_network_error(monkeypatch, tmp_path):
    """对照组：单镜 POST 的 ref 幂等是契约里验收过的，网络异常照旧重发一次（不该被批量的收紧误伤）。"""
    with_key(monkeypatch)
    seen = []
    holder = {}

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        seen.append(body)
        if len(seen) == 1:
            raise holder["mod"].exceptions.Timeout("read timeout")
        return FakeResp(202, {"clip_id": "c9"})

    _, mod = fake_requests(monkeypatch, handler)
    holder["mod"] = mod
    r = jg.submit("text2video", "x", backend="server")
    assert r["success"] is True and r["submit_id"] == "c9" and len(seen) == 2


def test_batch_non_dict_json_receipt_stays_a_json_envelope(monkeypatch, tmp_path):
    """2xx + JSON 顶层非 dict（服务端把回执写成裸数组 / 网关注入字符串）不许裸抛 AttributeError ——
    崩了就没有 stdout JSON 信封，上层 agent 只能看到 traceback。"""
    with_key(monkeypatch)

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        return FakeResp(202, ["c1", "c2"])

    fake_requests(monkeypatch, handler)
    plan = write_plan(tmp_path, [{"operation": "text2video", "prompt": "a"},
                                 {"operation": "text2video", "prompt": "b"}])
    out = jg.batch(plan, str(tmp_path), submit_only=True)
    assert out["success"] is False and out["ok"] == 0
    assert [r["index"] for r in out["results"]] == [0, 1]
    assert all("不是 JSON" in r["error"] for r in out["results"])
    json.dumps(out, ensure_ascii=False)      # 信封必须可序列化


def test_batch_clip_ids_count_mismatch_is_reported(monkeypatch, tmp_path):
    """回执数量对不上就绝不猜映射——错配会把 shot-01 的片当成 shot-02。"""
    with_key(monkeypatch)

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        return FakeResp(202, {"batch_id": 7, "clip_ids": [1]})

    fake_requests(monkeypatch, handler)
    plan = write_plan(tmp_path, [{"operation": "text2video", "prompt": "a"},
                                 {"operation": "text2video", "prompt": "b"}])
    out = jg.batch(plan, str(tmp_path), submit_only=True)
    assert out["success"] is False
    assert all("clip_ids" in r["error"] for r in out["results"])


def test_batch_local_backend_unchanged(monkeypatch, tmp_path):
    """local 后端的批量行为与服务化之前一致（逐镜 submit，index 0 起）。"""
    fake_local_cli(monkeypatch)
    plan = write_plan(tmp_path, [{"operation": "text2video", "prompt": "a"},
                                 {"operation": "text2video", "prompt": "b"}])
    out = jg.batch(plan, str(tmp_path), submit_only=True, backend="local")
    assert out["success"] is True and out["backend"] == "local"
    assert [r["index"] for r in out["results"]] == [0, 1]
    assert all(r["submit_id"] == LOCAL_SID and r["status"] == "submitted"
               for r in out["results"])


# ---------- 6. credits ----------

def test_server_credits_shape_with_total_credit_mirror(monkeypatch):
    with_key(monkeypatch)

    def handler(method, url, body):
        if url.endswith(jg.EP_DREAMINA_STATUS):
            return FakeResp(200, {"logged_in": True})
        assert url == BASE + jg.EP_CREDITS
        return FakeResp(200, {"credit": 15060, "low_threshold_hit": False})

    fake_requests(monkeypatch, handler)
    r = jg.credits()
    assert r == {"success": True, "credit": 15060, "low_threshold_hit": False,
                 "total_credit": 15060, "backend": "server"}


def test_server_credits_low_threshold_passthrough(monkeypatch):
    with_key(monkeypatch)
    fake_requests(monkeypatch, lambda m, u, b:
                  FakeResp(200, {"logged_in": True}) if u.endswith(jg.EP_DREAMINA_STATUS)
                  else FakeResp(200, {"credit": 30, "low_threshold_hit": True}))
    r = jg.credits()
    assert r["low_threshold_hit"] is True and r["credit"] == 30


def test_server_credits_without_key_gives_actionable_error(monkeypatch):
    fake_requests(monkeypatch, lambda *a: pytest.fail("没凭据不该发请求"))
    r = jg.credits(backend="server")
    assert r["success"] is False
    assert "MISSING:NBDPSY_XHS_API_KEY" in r["error"] and "--backend local" in r["error"]


def test_local_credits_tagged(monkeypatch):
    monkeypatch.setattr(jg, "_check_cli", lambda: None)
    monkeypatch.setattr(jg, "_run", lambda args, timeout=60: (
        0, json.dumps({"total_credit": 15060, "vip_credit": 15000}), ""))
    r = jg.credits(backend="local")
    assert r == {"total_credit": 15060, "vip_credit": 15000,
                 "success": True, "backend": "local"}


# ---------- 7. check_env 后端感知 ----------

def _server_probe(logged_in=True, credit=15060):
    return {"available": True, "logged_in": logged_in, "credit": credit,
            "compliance_confirmed_models": [], "reason": None, "base": BASE}


def check_env_result(monkeypatch, probe):
    import check_env
    monkeypatch.setattr(check_env.jimeng_gen, "probe_server", lambda *a, **k: probe)
    monkeypatch.setattr(check_env.jimeng_gen, "resolve_backend", lambda *a, **k: "server")
    return check_env, check_env.check(install=False)


def test_check_env_server_mode_replaces_local_dreamina_checks(monkeypatch):
    check_env, result = check_env_result(monkeypatch, _server_probe())
    names = [c["name"] for c in result["checks"]]
    assert "即梦服务(server)" in names
    assert "dreamina CLI" not in names and "dreamina 登录 & 积分" not in names
    # JSON 结构不变
    assert set(result) == {"ready", "checks"}
    for c in result["checks"]:
        assert set(c) == {"name", "ok", "critical", "detail", "fix"}
    json.dumps(result, ensure_ascii=False)
    srv = next(c for c in result["checks"] if c["name"] == "即梦服务(server)")
    assert srv["ok"] is True and "15060" in srv["detail"]
    info = next(c for c in result["checks"] if c["name"].startswith("本机 dreamina CLI"))
    assert info["critical"] is False and info["ok"] is True


def test_check_env_server_low_credit_warns(monkeypatch):
    _, result = check_env_result(monkeypatch, _server_probe(credit=10))
    srv = next(c for c in result["checks"] if c["name"] == "即梦服务(server)")
    assert srv["ok"] is False and "偏低" in srv["detail"] and result["ready"] is False


def test_check_env_server_logged_out_points_at_admin(monkeypatch):
    _, result = check_env_result(monkeypatch, _server_probe(logged_in=False, credit=None))
    srv = next(c for c in result["checks"] if c["name"] == "即梦服务(server)")
    assert srv["ok"] is False and "logged_in=false" in srv["detail"]
    assert ".dreamina_cli" in srv["fix"]


def test_check_env_forced_local_never_touches_network(monkeypatch):
    """强制 local（离线机器/应急）时自检不该为了一次探测干等到超时 —— 一个网络调用都不许发。"""
    import check_env
    monkeypatch.setenv(jg.BACKEND_ENV, "local")

    def boom(*a, **k):
        raise AssertionError("强制 local 不该探测 server")

    monkeypatch.setattr(check_env.jimeng_gen, "probe_server", boom)
    monkeypatch.setattr(check_env.jimeng_gen, "resolve_backend", boom)
    backend, info = check_env.probe_backend()
    assert backend == "local" and "local" in info["reason"]


def test_check_env_forced_server_probe_failure_shows_real_reason(monkeypatch):
    """强制 server 但探测就没成（404/网络不通）：要报「服务端不可用」这个真因，
    不能落进「未登录（logged_in=false）」把根因盖掉、让运营去折腾扫码登录。"""
    import check_env
    monkeypatch.setenv(jg.BACKEND_ENV, "server")
    down = {"available": False, "logged_in": False, "credit": None,
            "compliance_confirmed_models": [], "base": BASE,
            "reason": "server 尚未上线即梦能力（HTTP 404）"}
    monkeypatch.setattr(check_env.jimeng_gen, "probe_server", lambda *a, **k: down)
    backend, info = check_env.probe_backend()
    assert backend == "server" and info is down
    result = check_env.check(install=False)
    srv = next(c for c in result["checks"] if c["name"] == "即梦服务(server)")
    assert srv["ok"] is False
    assert "HTTP 404" in srv["detail"] and "探测失败" in srv["detail"]
    assert "未登录" not in srv["detail"]
    assert "回 auto" in srv["fix"]


def test_check_env_local_mode_keeps_original_checks(monkeypatch):
    import check_env
    monkeypatch.setattr(check_env.jimeng_gen, "probe_server",
                        lambda *a, **k: {"available": False, "logged_in": False,
                                         "reason": "未配 NBDPSY_XHS_API_KEY", "base": BASE})
    monkeypatch.setattr(check_env.jimeng_gen, "resolve_backend", lambda *a, **k: "local")
    monkeypatch.setattr(check_env, "DREAMINA", "/nonexistent/dreamina")
    result = check_env.check(install=False)
    names = [c["name"] for c in result["checks"]]
    assert "dreamina CLI" in names and "dreamina 登录 & 积分" in names
    assert "即梦服务(server)" not in names
    assert result["ready"] is False

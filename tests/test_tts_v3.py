"""tts_gen.py 豆包 V3(单一 API Key) / V1(旧版 appid+token) 路由与流式拼装测试。
全程 mock requests 层，不打真网络。契约锁定自官方文档：
  https://www.volcengine.com/docs/6561/2528925 （V3 单向流式合成：POST /api/v3/tts/unidirectional，
  header X-Api-Key/X-Api-Resource-Id/X-Api-Request-Id，响应为连续 JSON 对象的 chunked 流，
  每个对象形如 {"code":0,"message":"OK","data":"<base64 音频分片>"}，data 按到达顺序拼接）
  https://www.volcengine.com/docs/6561/1816214 （API Key 用法：header x-api-key）
"""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"))

ENV_KEYS = ["VOLC_TTS_API_KEY", "VOLC_TTS_APPID", "VOLC_TTS_ACCESS_TOKEN", "VOLC_TTS_CLUSTER", "VOLC_TTS_VOICE"]


def _isolate(monkeypatch, tmp_path):
    """清空相关环境变量 + 隔离 secrets/workspace，避免读到本机真实凭据；跳过 skill .env 探测分支。"""
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NBDPSY_SECRETS", str(tmp_path / "secrets.env"))
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(tmp_path / "ws"))
    import tts_gen
    monkeypatch.setattr(tts_gen, "_load_env", lambda: None)
    return tts_gen


class _FakeStreamResponse:
    """模拟 requests.post(..., stream=True) 的返回：status_code + iter_content(chunk_size=None)。"""

    def __init__(self, status_code, chunks, text=""):
        self.status_code = status_code
        self._chunks = chunks
        self.text = text
        self.closed = False

    def iter_content(self, chunk_size=None):
        for c in self._chunks:
            yield c

    def close(self):
        self.closed = True


class _FakeJsonResponse:
    """模拟 requests.post(...) 的返回：非流式，.json() 一次性返回。"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _v3_chunk_bytes(*audio_pieces: bytes) -> list[bytes]:
    """把多段音频编码成 V3 响应的 JSON 对象流，再故意从跨对象边界的位置切成 3 块物理字节，
    验证 buffer 拼装逻辑不依赖 chunk 边界与 JSON 边界对齐。"""
    objs = [json.dumps({"code": 0, "message": "OK", "data": base64.b64encode(p).decode()})
            for p in audio_pieces]
    full = "".join(objs).encode("utf-8")
    if len(objs) < 2:
        return [full]
    cut1 = max(1, len(objs[0].encode("utf-8")) - 5)  # 切在第一个 JSON 对象快结束前，制造跨块
    cut2 = len(objs[0].encode("utf-8")) + 5           # 切在第二个 JSON 对象刚开始处
    return [full[:cut1], full[cut1:cut2], full[cut2:]]


# ---------- 1. V3 路由选择：有 VOLC_TTS_API_KEY → 走 V3 URL + 正确 header ----------

def test_v3_routing_when_api_key_present(tmp_path, monkeypatch):
    tts_gen = _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("VOLC_TTS_API_KEY", "sk-fake-key")

    captured = {}

    def fake_post(url, headers=None, json=None, stream=False, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["stream"] = stream
        audio = b"HELLO-V3-AUDIO"
        return _FakeStreamResponse(200, _v3_chunk_bytes(audio))

    monkeypatch.setattr("requests.post", fake_post)

    out = tmp_path / "out.mp3"
    voice = tts_gen._doubao_synth("你好，这是测试", str(out), None, 0.95)

    assert captured["url"] == tts_gen.DOUBAO_V3_ENDPOINT
    assert captured["stream"] is True
    assert captured["headers"]["X-Api-Key"] == "sk-fake-key"
    assert captured["headers"]["X-Api-Resource-Id"] == "seed-tts-2.0" == tts_gen.DOUBAO_V3_RESOURCE_ID
    assert "X-Api-Request-Id" in captured["headers"]
    assert captured["json"]["req_params"]["speaker"] == voice
    assert voice == tts_gen.DOUBAO_V3_DEFAULT_VOICE  # 未显式指定 --voice → V3 默认「温柔淑女2.0」
    assert out.read_bytes() == b"HELLO-V3-AUDIO"


# ---------- 2. V1 回退路由：无 API Key、有 appid+token → 走旧版 V1 URL ----------

def test_v1_fallback_routing_when_only_legacy_credentials(tmp_path, monkeypatch):
    tts_gen = _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("VOLC_TTS_APPID", "appid-x")
    monkeypatch.setenv("VOLC_TTS_ACCESS_TOKEN", "token-x")

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        audio = b"HELLO-V1-AUDIO"
        payload = {"code": 3000, "data": base64.b64encode(audio).decode()}
        return _FakeJsonResponse(payload)

    monkeypatch.setattr("requests.post", fake_post)

    out = tmp_path / "out.mp3"
    voice = tts_gen._doubao_synth("你好，这是测试", str(out), None, 0.95)

    assert captured["url"] == tts_gen.DOUBAO_ENDPOINT
    assert captured["headers"]["Authorization"] == "Bearer;token-x"
    assert captured["json"]["app"]["appid"] == "appid-x"
    assert voice == tts_gen.DOUBAO_DEFAULT_VOICE  # V1 默认「温柔淑女」(mars_bigtts)
    assert out.read_bytes() == b"HELLO-V1-AUDIO"


# ---------- 3. V3 流式响应拼装：多 chunk（含跨 JSON 边界切块）按序还原完整音频 ----------

def test_v3_streaming_chunks_assemble_correct_bytes(tmp_path, monkeypatch):
    tts_gen = _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("VOLC_TTS_API_KEY", "sk-fake-key")

    piece1, piece2, piece3 = b"AAA-first", b"BBBB-second", b"CC-third"

    def fake_post(url, headers=None, json=None, stream=False, timeout=None):
        return _FakeStreamResponse(200, _v3_chunk_bytes(piece1, piece2, piece3))

    monkeypatch.setattr("requests.post", fake_post)

    out = tmp_path / "out.mp3"
    tts_gen._doubao_synth("测试拼装", str(out), None, 0.95)

    assert out.read_bytes() == piece1 + piece2 + piece3


def test_v3_stream_error_code_raises_readable_message(tmp_path, monkeypatch):
    tts_gen = _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("VOLC_TTS_API_KEY", "sk-fake-key")

    error_chunk = json.dumps({"code": 50000, "message": "speaker not found"}).encode("utf-8")

    def fake_post(url, headers=None, json=None, stream=False, timeout=None):
        return _FakeStreamResponse(200, [error_chunk])

    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(RuntimeError, match="speaker not found"):
        tts_gen._doubao_synth("测试报错", str(tmp_path / "out.mp3"), None, 0.95)


# ---------- 4. 双凭据都缺 → 报错信息含「API Key」引导（且仍保留旧版关键字回归） ----------

def test_both_credentials_missing_error_mentions_api_key(tmp_path, monkeypatch):
    tts_gen = _isolate(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError, match="API Key") as exc_info:
        tts_gen._doubao_synth("测试文本", str(tmp_path / "out.mp3"), None, 0.95)
    assert "VOLC_TTS_APPID" in str(exc_info.value)  # 旧版凭据引导仍保留（向后兼容回归）


# ---------- 5. 错误 message 含多字节中文字符被物理 chunk 边界切断 → 增量解码不丢字 ----------

def test_v3_error_message_multibyte_char_split_across_chunks_not_dropped(tmp_path, monkeypatch):
    tts_gen = _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("VOLC_TTS_API_KEY", "sk-fake-key")

    payload = json.dumps({"code": 50000, "message": "音色不存在"}, ensure_ascii=False).encode("utf-8")
    # 故意把切点落在「音」字（3 字节 UTF-8 序列）中间，制造跨 chunk 的半个字符
    yin_idx = payload.index("音色不存在".encode("utf-8"))
    cut = yin_idx + 1  # 切在「音」字第 1 个字节之后（序列尚未完整）
    chunks = [payload[:cut], payload[cut:]]

    def fake_post(url, headers=None, json=None, stream=False, timeout=None):
        return _FakeStreamResponse(200, chunks)

    monkeypatch.setattr("requests.post", fake_post)

    with pytest.raises(RuntimeError, match="音色不存在"):
        tts_gen._doubao_synth("测试报错", str(tmp_path / "out.mp3"), None, 0.95)


def test_v3_end_of_stream_sentinel_20000000_is_not_an_error(tmp_path, monkeypatch):
    """生产实测：流末尾会追加 {"code":20000000,"message":"OK"} 结束哨兵（公开文档未记载）。
    它不是错误——回归保护：带哨兵的流必须成功落盘全部音频。"""
    tts_gen = _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("VOLC_TTS_API_KEY", "sk-fake-key")

    piece = b"AUDIO-BYTES"
    obj_audio = json.dumps({"code": 0, "message": "OK", "data": base64.b64encode(piece).decode()})
    obj_sentinel = json.dumps({"code": 20000000, "message": "OK"})
    payload = (obj_audio + obj_sentinel).encode("utf-8")

    def fake_post(url, headers=None, json=None, stream=False, timeout=None):
        return _FakeStreamResponse(200, [payload[:20], payload[20:]])

    monkeypatch.setattr("requests.post", fake_post)

    out = tmp_path / "out.mp3"
    tts_gen._doubao_synth("哨兵测试", str(out), None, 0.95)

    assert out.read_bytes() == piece

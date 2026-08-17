"""tts_gen 逐句并行合成：并行度解析、顺序保持、限流退避重试。

背景（2026-08-17 本机对 MiniMax T2A 实测，一次性探测脚本已删）：
  · 同时打 20 发全进，24 发进 20 → 一次能同时挤进去的上限是 20
  · 但把并发压到 1（完全串行）连打，第 29 发照样 1002 → 被限的是**每分钟请求数**
    （实测 100.8s 内 41 发成功 37 发，约 22 次/分），不是"同时在飞几路"
  · 26 次 1002 响应逐条核对：data.audio 为空、extra_info.usage_characters 缺席
    → 限流不合成也不计费，重试安全（鉴权/参数错误依旧一次都不重试）

本文件不打真网络：mock gen_one / requests 层。
"""
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"))

import tts_gen  # noqa: E402


# ---------- 并行度解析 ----------

@pytest.mark.parametrize("engine,expected", [
    ("minimax", tts_gen.MINIMAX_DEFAULT_CONCURRENCY),
    ("doubao", 1),
    ("edge", 1),
])
def test_默认并行度只对minimax放开(engine, expected):
    """只实测过 MiniMax，别的引擎不拿没量过的数当默认值。"""
    assert tts_gen._resolve_concurrency(None, engine, 99) == expected


def test_默认值必须比实测上限保守():
    """实测一次能同时挤进 20 发；默认值独占它会把共用同一把 key 的会话饿死。"""
    assert 1 < tts_gen.MINIMAX_DEFAULT_CONCURRENCY <= 20 // 2


def test_并行度不超过句数也不小于1():
    assert tts_gen._resolve_concurrency(8, "minimax", 3) == 3   # 3 句没必要开 8 路
    assert tts_gen._resolve_concurrency(0, "minimax", 5) == 1
    assert tts_gen._resolve_concurrency(-3, "minimax", 5) == 1
    assert tts_gen._resolve_concurrency(6, "minimax", 20) == 6  # 显式传入压过默认值


# ---------- 顺序保持（并行化最容易静默出错的地方）----------

def _fake_gen_one_factory(delays, calls=None):
    """按句内容决定"合成耗时"，模拟乱序完成。写出的 mp3 内容 = 该句原文（便于核对落位）。"""
    def fake(text, out, **kw):
        if calls is not None:
            calls.append(text)
        time.sleep(delays.get(text, 0))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        return {"success": True, "output": out, "engine": kw.get("engine"), "voice": "v"}
    return fake


def _stub_pcm_by_content(monkeypatch):
    """把 mp3→PCM 解码换成"读回文本、按字数造等长静音"，避免真跑 ffmpeg；
    这样 cue 的时长与句子长度挂钩，落位错了会同时体现在 text 和 duration 上。"""
    def fake_run(cmd, *a, **kw):
        if cmd[0] == "ffmpeg" and "-i" in cmd:
            src = Path(cmd[cmd.index("-i") + 1])
            dst = Path(cmd[-1])
            if src.suffix == ".mp3":  # 解码分句
                import wave
                content = src.read_text(encoding="utf-8")
                with wave.open(str(dst), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(32000)
                    w.writeframes(b"\x00\x00" * (len(content) * 32000))  # 1 字 = 1 秒
            else:                     # 最终编码：把拼好的 wav 原样落地
                dst.write_bytes(src.read_bytes())
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": b""})()
    monkeypatch.setattr(tts_gen.subprocess, "run", fake_run)
    monkeypatch.setattr(tts_gen, "ffprobe_duration", lambda p: 0.0)


def test_乱序完成时cues仍按原句序(monkeypatch, tmp_path):
    """🔴 并行化的核心风险：后面的句子先合成完。产出必须按**原句序**拼，不能按完成顺序。
    这里让最后一句最快、第一句最慢，串行实现下不可能暴露的问题在这里必须暴露。

    句子刻意**长短各不相同**：光比对 cue 文本抓不到"文本对、音频错位"这种更阴的形态
    （cue 文本恒来自 sents[i]，错位的是落在该槽里的音频）。stub 里 1 字 = 1 秒，
    于是每条 cue 的时长直接指认"这一格里躺的到底是哪句的音频"。"""
    text = "一。二二。三三三。四四四四。"
    delays = {"一。": 0.30, "二二。": 0.20, "三三三。": 0.10, "四四四四。": 0.0}
    monkeypatch.setattr(tts_gen, "gen_one", _fake_gen_one_factory(delays))
    _stub_pcm_by_content(monkeypatch)

    out = tmp_path / "n.mp3"
    r = tts_gen.gen_timed(text, str(out), engine="minimax", concurrency=4, gap=0.0)

    assert r["success"], r.get("error")
    assert [c["text"] for c in r["cues"]] == ["一。", "二二。", "三三三。", "四四四四。"]
    # 每格的音频时长必须等于该格文本的字数（错位就对不上）
    for c in r["cues"]:
        assert round(c["end"] - c["start"], 3) == float(len(c["text"])), \
            f"cue {c} 的音频不是这句的（时长对不上字数）"
    # 时间轴必须单调递增且首尾相接（错位拼接会在这里断掉）
    assert r["cues"][0]["start"] == 0.0
    for prev, nxt in zip(r["cues"], r["cues"][1:]):
        assert prev["end"] == nxt["start"], f"{prev} → {nxt} 不相接"
        assert nxt["end"] > nxt["start"]
    # sidecar 落盘内容与返回值一致
    saved = json.loads(Path(r["cues_path"]).read_text(encoding="utf-8"))
    assert [c["text"] for c in saved["cues"]] == [c["text"] for c in r["cues"]]


def test_并行与串行产出逐字节一致(monkeypatch, tmp_path):
    """同一段文本，4 路并行与 1 路串行必须产出同样的音频与同样的 cues——
    并行只该改变"多久出来"，不该改变"出来的是什么"。"""
    text = "甲。乙乙。丙丙丙。丁丁丁丁。戊。"
    delays = {"甲。": 0.25, "乙乙。": 0.05, "丙丙丙。": 0.15, "丁丁丁丁。": 0.0, "戊。": 0.2}
    _stub_pcm_by_content(monkeypatch)

    outs = {}
    for label, workers in (("并行", 5), ("串行", 1)):
        monkeypatch.setattr(tts_gen, "gen_one", _fake_gen_one_factory(delays))
        out = tmp_path / f"{label}.mp3"
        r = tts_gen.gen_timed(text, str(out), engine="minimax", concurrency=workers, gap=0.3)
        assert r["success"], r.get("error")
        outs[label] = (out.read_bytes(), r["cues"])

    assert outs["并行"][1] == outs["串行"][1]
    assert outs["并行"][0] == outs["串行"][0]


def test_并行确实同时在飞(monkeypatch, tmp_path):
    """防"加了参数其实没并行"：4 句各睡 0.2s，4 路并行的墙钟必须显著短于串行。
    另记录同时在飞的峰值，确认真的并起来了。"""
    text = "一。二。三。四。"
    inflight, peak, lock = 0, 0, threading.Lock()

    def fake(text_, out, **kw):
        nonlocal inflight, peak
        with lock:
            inflight += 1
            peak = max(peak, inflight)
        time.sleep(0.2)
        with lock:
            inflight -= 1
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text_, encoding="utf-8")
        return {"success": True, "output": out, "voice": "v"}

    monkeypatch.setattr(tts_gen, "gen_one", fake)
    _stub_pcm_by_content(monkeypatch)
    t0 = time.time()
    r = tts_gen.gen_timed(text, str(tmp_path / "n.mp3"), engine="minimax", concurrency=4, gap=0.0)
    elapsed = time.time() - t0

    assert r["success"], r.get("error")
    assert peak >= 2, f"并行度峰值只有 {peak}，根本没并起来"
    assert elapsed < 0.6, f"4 句各 0.2s、4 路并行却花了 {elapsed:.2f}s，像是在串行"


def test_并行下失败按最小句序报(monkeypatch, tmp_path):
    """并行时可能多句同时失败；报错口径要跟串行时代一致（报最靠前那句）。"""
    def fake(text_, out, **kw):
        if text_ in ("乙。", "丙。"):
            return {"success": False, "error": f"炸了:{text_}"}
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text_, encoding="utf-8")
        return {"success": True, "output": out, "voice": "v"}

    monkeypatch.setattr(tts_gen, "gen_one", fake)
    _stub_pcm_by_content(monkeypatch)
    r = tts_gen.gen_timed("甲。乙。丙。", str(tmp_path / "n.mp3"),
                          engine="minimax", concurrency=3)
    assert r["success"] is False
    assert r["error"].startswith("句1合成失败"), r["error"]


# ---------- 限流退避重试 ----------

class _FakeResp:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _ok_payload():
    return {"base_resp": {"status_code": 0, "status_msg": "success"},
            "data": {"audio": "ffd9"}, "extra_info": {"usage_characters": 6}}


def _ratelimit_payload(code=1002):
    """实测形状：限流时没有 data.audio，也没有 extra_info.usage_characters（=没计费）。"""
    return {"base_resp": {"status_code": code, "status_msg": "rate limit exceeded(RPM)"},
            "trace_id": None}


@pytest.mark.parametrize("code", tts_gen.MINIMAX_RATELIMIT_CODES)
def test_限流会退避重试并最终成功(monkeypatch, tmp_path, code):
    seq = [_FakeResp(_ratelimit_payload(code)), _FakeResp(_ratelimit_payload(code)),
           _FakeResp(_ok_payload())]
    posts, slept = [], []

    def fake_post(url, **kw):
        posts.append(url)
        return seq[len(posts) - 1]

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(tts_gen.time, "sleep", lambda s: slept.append(s))

    out = tmp_path / "a.mp3"
    assert tts_gen._minimax_synth("你好", str(out), "v", 1.0, "k") is True
    assert len(posts) == 3, "限流后应重试到成功"
    assert out.read_bytes() == bytes.fromhex("ffd9")
    assert slept == sorted(slept) and slept[0] >= 1.0, f"退避应递增: {slept}"


def test_退避是指数且带抖动():
    """惊群防护：并行池多路同时撞墙，退避时长必须互不相同。"""
    d1 = [tts_gen._minimax_retry_delay(1) for _ in range(20)]
    assert len(set(d1)) > 1, "退避没有抖动，多路会一起醒来再一起撞墙"
    assert all(1.0 <= d <= 1.25 for d in d1), d1
    assert all(2.0 <= tts_gen._minimax_retry_delay(2) <= 2.5 for _ in range(5))
    assert tts_gen._minimax_retry_delay(9) <= tts_gen.MINIMAX_RETRY_MAX_DELAY * 1.25


def test_重试耗尽后报错点名限流(monkeypatch, tmp_path):
    monkeypatch.setattr("requests.post", lambda url, **kw: _FakeResp(_ratelimit_payload()))
    monkeypatch.setattr(tts_gen.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="1002"):
        tts_gen._minimax_synth("你好", str(tmp_path / "a.mp3"), "v", 1.0, "k", retry_attempts=2)


@pytest.mark.parametrize("code,msg", [
    (1004, "auth failed"),      # 鉴权
    (2013, "invalid params"),   # 参数
    (1042, "invalid chars"),    # 非法字符
])
def test_非限流错误一次都不重试(monkeypatch, tmp_path, code, msg):
    """🔴 资金红线：TTS 按字符计费，只有"实测不计费"的限流码才有重试豁免权。"""
    posts = []

    def fake_post(url, **kw):
        posts.append(url)
        return _FakeResp({"base_resp": {"status_code": code, "status_msg": msg}})

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr(tts_gen.time, "sleep",
                        lambda s: pytest.fail("非限流错误不该退避重试"))
    with pytest.raises(RuntimeError, match=str(code)):
        tts_gen._minimax_synth("你好", str(tmp_path / "a.mp3"), "v", 1.0, "k")
    assert len(posts) == 1, f"非限流错误重发了 {len(posts)} 次 = 重复扣费"


def test_HTTP非200不重试(monkeypatch, tmp_path):
    posts = []

    def fake_post(url, **kw):
        posts.append(url)
        return _FakeResp({"x": 1}, status_code=401)

    monkeypatch.setattr("requests.post", fake_post)
    with pytest.raises(RuntimeError, match="401"):
        tts_gen._minimax_synth("你好", str(tmp_path / "a.mp3"), "v", 1.0, "k")
    assert len(posts) == 1

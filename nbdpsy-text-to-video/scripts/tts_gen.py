#!/usr/bin/env python3
"""中文旁白生成 —— 三引擎：edge-tts(免费无 key) / 火山豆包大模型 TTS(高音质, 需 key)
/ MiniMax T2A(高音质, 需 key)。

把分镜旁白文案转成 mp3，喂给 compose_video.py 的 segments[].narration。

引擎 --engine：
  edge   （默认，免费）edge-tts，音色 --voice zh-CN-XiaoxiaoNeural，语速 --rate "-10%"
  doubao （高音质，需 key）火山豆包 TTS，凭据读 ../.env 的 VOLC_TTS_*，
          音色 --voice 或 VOLC_TTS_VOICE，语速 --speed 0.95(0.8-2.0)。
          两套凭据/接口二选一（按有无 VOLC_TTS_API_KEY 自动路由，互不干扰）：
          · 有 VOLC_TTS_API_KEY（新版控制台单一 Key）→ 走 V3 单向流式接口
            （POST /api/v3/tts/unidirectional，header X-Api-Key/X-Api-Resource-Id，
            默认音色 zh_female_wenroushunv_uranus_bigtts「温柔淑女 2.0」——
            V3 仅认 2.0 系音色（*_uranus_bigtts），旧版 V1 音色如
            zh_female_wenroushunv_mars_bigtts 在 V3 下不可用）。
            · 若音色（--voice / VOLC_TTS_VOICE）以 S_ 开头（火山「声音复刻」克隆音色）→
              同端点换 resource-id=seed-icl-2.0 + 额外带 X-Api-App-Id 头（用 VOLC_TTS_APPID）
              + body 带 user.uid，旁白即用用户克隆的专属声音（缺 appid 直接报错，不静默）。
          · 无 API Key 但有 VOLC_TTS_APPID+VOLC_TTS_ACCESS_TOKEN（旧版双凭据）
            → 走 V1 接口（/api/v1/tts，官方已标"不推荐"但保留向后兼容），
            默认音色仍是 zh_female_wenroushunv_mars_bigtts「温柔淑女」。
          · 都无 → 报错，优先引导配 VOLC_TTS_API_KEY。
  minimax（高音质，需 key）MiniMax 同步 HTTP T2A（POST /v1/t2a_v2，非流式），
          凭据读 MINIMAX_API_KEY（Bearer）/ MINIMAX_VOICE，语速 --speed（范围 0.5-2.0，
          与豆包的 0.8-2.0 不同，越界会 clamp 并在 stderr 提示），模型 --model
          默认 speech-2.8-hd。情绪 --emotion 只在显式传入时才带上——官方原文
          「模型会根据输入文本自动匹配合适的情绪，一般无需手动指定」，不传更自然。
          MINIMAX_GROUP_ID 通常不需要配：官方现行 OpenAPI 规范无此参数；仅旧版/
          国际站账号要求 ?GroupId=xxx，配了才拼进 query（绝不自动试探重试，
          因为 TTS 按字符计费，重试＝重复扣费）。

          **MiniMax 独有的两套文本标记（豆包没有，后续做停顿/气口用这个）**：
          · 停顿标记 `<#x#>`：x 为秒数，0.01-99.99，最多两位小数；不可连续使用多个；
            必须夹在两段可发音文本之间。例：`他愣了一下<#0.8#>然后笑了。`
          · 语气词标签（**仅 speech-2.8-hd / speech-2.8-turbo 支持**）：
            (sighs)(breath)(chuckle)(laughs)(gasps)(exhale)(inhale)(coughs)
            (clear-throat)(groans)(pant)(sniffs)(snorts)(humming)(hissing)
            (emm)(sneezes)(burps)(lip-smacking)
          · 对比：豆包那套方括号语气指令实测是死路——会被原样朗读出来；
            MiniMax 这两套是官方标记，不会被念出来。

**逐句时间轴 --timed（字幕真同步的根，强烈建议开）**：
  默认整段合成时，字幕只能按字数比例估算时长 → 与真实语速错位。
  --timed 会把旁白按句末标点(。！？)切句、每句单独合成、ffprobe 实测时长后拼接，
  并写 sidecar `{out}.cues.json`（每句 text/start/end）。compose_video.py 检测到 cues
  就让字幕严格按每句实测时长显示，旁白讲到哪字幕走到哪，彻底同步。

  **逐句合成是并行的 --concurrency（MiniMax 默认 4 路，其余引擎串行）**：
  2026-08-17 实测这把 key 一次能同时打进 20 发，但被限的其实是每分钟请求数
  （约 20-22 次/分）——压到完全串行照样撞 1002，所以"必须串行"从来不是解药。
  限流码不返音频也不计费，撞上就指数退避重试。拼接与 cues 恒按**原句序**，
  与谁先合成完无关。

豆包大模型音色（本机实测已开通，cluster=volcano_tts）：
  zh_female_wenroushunv_mars_bigtts     温柔淑女（默认·成熟温柔知性，心理科普旁白）
  zh_female_qingxinnvsheng_mars_bigtts  清新女声（清新干净偏年轻）
  zh_female_meilinvyou_moon_bigtts      魅力女友（成熟偏柔，语速偏慢）
  zh_female_shuangkuaisisi_moon_bigtts  爽快思思（明快活泼）
  zh_female_wanwanxiaohe_moon_bigtts    湾湾小何（年轻甜美）
  （BV001/BV700 等经典音色未授权，会报 code=3001 resource not granted）
edge 常用音色：zh-CN-XiaoxiaoNeural(温柔女) / zh-CN-YunxiNeural(沉稳男)

用法：
  python tts_gen.py --engine doubao --text "焦虑不是敌人…" --out tts/1.mp3 --timed
  python tts_gen.py --engine doubao --plan shots.json --out-dir tts/ --timed
  python tts_gen.py --engine minimax --voice <voice_id> --text "焦虑不是敌人…" --out tts/1.mp3 --timed
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import codecs
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EDGE_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
EDGE_DEFAULT_RATE = "-10%"
# V1（appid+token，官方已标"不推荐"，仅向后兼容）默认音色：温柔淑女
DOUBAO_DEFAULT_VOICE = "zh_female_wenroushunv_mars_bigtts"
DOUBAO_ENDPOINT = "https://openspeech.bytedance.com/api/v1/tts"
# V3（单一 API Key，新版首选）默认音色：温柔淑女 2.0——V3 只认 2.0 系音色(*_uranus_bigtts)，
# 是 V1 默认音色「温柔淑女」zh_female_wenroushunv_mars_bigtts 的 2.0 对应版本，人设一致。
# 契约锁定自官方文档 https://www.volcengine.com/docs/6561/2528925 （V3 接口）
# 与 https://www.volcengine.com/docs/6561/1257544 （2.0 音色列表）。
DOUBAO_V3_DEFAULT_VOICE = "zh_female_wenroushunv_uranus_bigtts"
DOUBAO_V3_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DOUBAO_V3_RESOURCE_ID = "seed-tts-2.0"  # 豆包语音合成大模型2.0（默认音色）
# 声音复刻（seed-icl-2.0）：用户在火山「声音复刻」克隆出的专属音色，id 以 S_ 开头。
# 与 seed-tts-2.0 同一个 unidirectional 端点、同一套流式响应格式，仅换 resource-id
# 并额外要求 X-Api-App-Id 头 + body 带 user.uid（实测契约，speaker=S_xxx 出合法 mp3）。
DOUBAO_ICL_RESOURCE_ID = "seed-icl-2.0"

# ---- MiniMax T2A（同步 HTTP，非流式）----
# 契约锁定自 MiniMax 官方 OpenAPI 规范（POST /v1/t2a_v2）。
# 备用域名 https://api-bj.minimaxi.com/v1/t2a_v2 —— 故意不实现自动切换：
# TTS 按字符计费，任何自动重试/换域名重发都可能重复扣费（本仓库资金安全铁律）。
MINIMAX_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"
MINIMAX_DEFAULT_MODEL = "speech-2.8-hd"
MINIMAX_MODELS = (
    "speech-2.8-hd", "speech-2.8-turbo",
    "speech-2.6-hd", "speech-2.6-turbo",
    "speech-02-hd", "speech-02-turbo",
    "speech-01-hd", "speech-01-turbo",
)
MINIMAX_EMOTIONS = (
    "happy", "sad", "angry", "fearful", "disgusted", "surprised",
    "calm", "fluent", "whisper",
)
# whisper（气声）只有 2.6 系支持，2.8 系不支持——本地预检拦掉，省一次白跑（也就省一次计费）
MINIMAX_WHISPER_UNSUPPORTED_PREFIX = "speech-2.8"
MINIMAX_SPEED_MIN, MINIMAX_SPEED_MAX = 0.5, 2.0  # 注意与豆包的 0.8-2.0 不同
# 计费口径（官方）：1 个汉字算 2 字符，其他字符算 1；下表是每万计费字符的人民币价格。
# 只登记已核对过价格的型号，其余型号只打字符数不瞎估价。
MINIMAX_PRICE_PER_10K = {"speech-2.8-hd": 3.5, "speech-2.8-turbo": 2.0}

# ---- 限流退避（只对限流码重试；这是本文件"绝不自动重试"铁律的唯一豁免）----
# 豁免依据是实测而非推测（2026-08-17 本机探测，26 次 1002 响应逐条核对）：
# 限流响应 data.audio 为空、extra_info.usage_characters 缺席 → 服务端没合成也没计费，
# 重试不会重复扣费。鉴权(1004)/参数(2013)/非法字符(1042) 等一律不重试，语义不变。
MINIMAX_RATELIMIT_CODES = (1002, 1039)  # 1002=RPM 限流，1039=TPM 限流
MINIMAX_RETRY_ATTEMPTS = 5              # 首发之外最多再退避重试 5 次
MINIMAX_RETRY_BASE_DELAY = 1.0          # 指数退避基数：1/2/4/8/16 秒（另加抖动）
MINIMAX_RETRY_MAX_DELAY = 16.0


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def _load_env() -> None:
    """把 skill 目录 .env 读进 os.environ（不覆盖已有）。"""
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _secret_fallback(key: str) -> str | None:
    """环境变量/skill .env（_load_env 已合并进 os.environ）都没有时，
    回退到 nbdpsy_common 用户级 secrets（setup.py 凭据向导写入的值）。
    同目录已有 vendored 副本，脚本直跑时 sys.path[0]=脚本目录天然可 import；
    若 tts_gen 被当模块 import 而当时 sys.path 没有脚本目录，容错跳过，
    不影响原有「缺凭据报错」行为。"""
    v = os.environ.get(key)
    if v:
        return v
    try:
        from nbdpsy_common import get_secret
    except ImportError:
        return None
    return get_secret(key)


def resolve_credentials() -> dict:
    """豆包 TTS 凭据解析（纯函数，便于测试）。
    三级链：环境变量 → skill 目录 .env（_load_env 合并进 os.environ，优先级不变）
    → nbdpsy_common 用户级 secrets（workspace .env / setup.py 向导写入）。
    cluster/voice 有内置默认值：显式配置（以上任一层）优先于默认值。
    api_key（新版单一凭据）与 appid/token（旧版双凭据）并存解析，
    由调用方按「有 api_key 优先走 V3」的路由规则二选一（见 _doubao_synth）。"""
    _load_env()
    return {
        "api_key": _secret_fallback("VOLC_TTS_API_KEY"),
        "appid": _secret_fallback("VOLC_TTS_APPID"),
        "token": _secret_fallback("VOLC_TTS_ACCESS_TOKEN"),
        "cluster": _secret_fallback("VOLC_TTS_CLUSTER") or "volcano_tts",
        "voice": _secret_fallback("VOLC_TTS_VOICE"),
    }


def resolve_minimax_credentials() -> dict:
    """MiniMax T2A 凭据解析（纯函数，便于测试）。与 resolve_credentials()（豆包专用）
    互不干扰，各读各的键。三级链同上：环境变量 → skill 目录 .env → nbdpsy_common 用户级 secrets。
    group_id 多数账号为 None（官方现行接口不需要 GroupId），只有旧版/国际站账号才配。"""
    _load_env()
    return {
        "api_key": _secret_fallback("MINIMAX_API_KEY"),
        "group_id": _secret_fallback("MINIMAX_GROUP_ID"),
        "voice": _secret_fallback("MINIMAX_VOICE"),
    }


def ffprobe_duration(path: str) -> float:
    """ffprobe 实测音频时长（秒）。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=60)
        return float((r.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return 0.0


def _split_sentences(text: str) -> list[str]:
    """按句末标点(。！？!?)切句——作为逐句 TTS 与字幕条的统一单元，保证音画同步。"""
    enders = "。！？!?"
    out, buf = [], ""
    for ch in (text or ""):
        buf += ch
        if ch in enders:
            s = buf.strip()
            if s:
                out.append(s)
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out or [(text or "").strip()]


def _split_caption_units(sentence: str) -> list[str]:
    """句内按逗号/顿号/分号/冒号再切成字幕条(≥6字才切，避免太碎)。
    长句(如只有结尾一个句号的整段)靠这个细分，字幕才会滚动而非一条久挂。"""
    seps = "，、；：,;:"
    out, buf = [], ""
    for ch in sentence:
        buf += ch
        if ch in seps and len(buf.strip()) >= 6:
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return [u for u in out if u.strip()] or [sentence]


# ---- edge-tts ----

async def _edge_synth(text: str, out: str, voice: str, rate: str) -> None:
    import edge_tts
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    await edge_tts.Communicate(text, voice, rate=rate).save(out)


# ---- 火山豆包大模型 TTS ----

def _doubao_v3_speech_rate(speed: float) -> int:
    """--speed 0.8-2.0（speed_ratio 语义，1.0=正常语速）换算成 V3 的 speech_rate 整数。
    官方文档：speech_rate 取值 [-50,100]，100=2.0倍速、-50=0.5倍速——
    两端斜率相同（每 1 点=0.01x），即 speed_ratio = 1 + speech_rate*0.01，故反解为线性换算。"""
    return max(-50, min(100, round((speed - 1.0) * 100)))


def _is_cloned_voice(v: str | None) -> bool:
    """是否为火山「声音复刻」克隆音色——克隆音色 id 以 S_ 开头（如 S_moiqVFN72）。
    默认大模型音色都是 zh_*/en_* 等，不以 S_ 打头，故可据此路由到 seed-icl-2.0。"""
    return bool(v) and v.startswith("S_")


def _doubao_v3_synth(text: str, out: str, voice: str, speed: float, api_key: str,
                     appid: str | None = None, emotion: str | None = None,
                     emotion_scale: int | None = None) -> None:
    """V3 单向流式合成（新版单一 API Key）。同一个 unidirectional 端点、同一套流式响应，
    按音色是否为克隆音色（S_ 开头）在请求侧分叉：
      · 默认音色 → resource-id=seed-tts-2.0，body={"req_params":{...,"speech_rate"}}，无 App-Id 头。
        契约锁定自官方文档 https://www.volcengine.com/docs/6561/2528925。
      · 克隆音色（声音复刻 seed-icl-2.0，speaker=S_xxx）→ resource-id=seed-icl-2.0，
        额外加 X-Api-App-Id 头（必需，缺失即报错）+ body 带 user.uid（实测契约）。
    请求头共有：X-Api-Key(必选) / X-Api-Resource-Id(必选) / X-Api-Request-Id(必选，uuid)。
    响应（两种音色同格式）：基于 HTTP Chunked 的连续 JSON 对象流（官方 curl 示例用 -N 免缓冲），
      每个 JSON 对象形如 {"code":0,"message":"OK","data":"<base64 音频分片>","sentence":{...}}，
      data 逐段 base64 解码后按到达顺序拼接即完整音频；末帧 code=20000000 是结束哨兵非错误，
      以 HTTP 响应流关闭（无更多数据）作为结束判定。"""
    import requests
    cloned = _is_cloned_voice(voice)
    if cloned and not appid:
        raise RuntimeError(
            "克隆音色需要 VOLC_TTS_APPID（X-Api-App-Id），"
            "请在后台豆包卡片『AppID』框填火山 appid")
    audio_params = {"format": "mp3", "sample_rate": 24000}
    if emotion:
        # Doubao-Seed-TTS 2.0 / Seed-ICL 2.0 的情感控制（2025-10 起）：emotion 指定情感/风格，
        # emotion_scale 1-5 控制强度。克隆音色（复刻 2.0）官方明确支持情感演绎。
        audio_params["emotion"] = emotion
        audio_params["enable_emotion"] = True
        if emotion_scale is not None:
            audio_params["emotion_scale"] = max(1, min(5, int(emotion_scale)))
    req_params = {
        "text": text,
        "speaker": voice,
        "audio_params": audio_params,
    }
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    # speech_rate 两种音色都传（此前克隆分支漏传）。实测 2026-08-07：放 req_params 顶层
    # 对克隆音色（seed-icl-2.0）不生效——1.05 与 1.15 速时长几乎一样；官方 V3 契约里
    # 它归属 audio_params。双写以兼容两代读法。
    rate_v = _doubao_v3_speech_rate(speed)
    req_params["speech_rate"] = rate_v
    audio_params["speech_rate"] = rate_v
    if cloned:
        headers["X-Api-Resource-Id"] = DOUBAO_ICL_RESOURCE_ID
        headers["X-Api-App-Id"] = appid
        body = {"user": {"uid": "tts"}, "req_params": req_params}
    else:
        headers["X-Api-Resource-Id"] = DOUBAO_V3_RESOURCE_ID
        body = {"req_params": req_params}
    r = requests.post(DOUBAO_V3_ENDPOINT, headers=headers, json=body, stream=True, timeout=120)
    if r.status_code != 200:
        r.close()
        raise RuntimeError(
            f"火山 V3 TTS HTTP {r.status_code}：{r.text[:200]}"
            f"（常见：API Key 无效/未授权、X-Api-Resource-Id 或音色版本不匹配）")
    audio = bytearray()
    buf = ""
    decoder = json.JSONDecoder()
    # 增量 UTF-8 解码器：多字节字符可能被物理 chunk 边界切断，
    # 逐 chunk 独立 decode(errors="ignore") 会把切断的半个字符两侧都静默丢弃，
    # 导致响应里的中文错误文案缺字（如"音色不存在"丢成"色不存在"）。
    text_decoder = codecs.getincrementaldecoder("utf-8")()

    def _drain(buf: str) -> str:
        while buf:
            try:
                obj, idx = decoder.raw_decode(buf)
            except ValueError:
                break  # 本块内 JSON 尚不完整，攒到下一块再解析
            buf = buf[idx:].lstrip()
            code = obj.get("code")
            # 20000000 = 流结束哨兵（生产实测：末帧 {"code":20000000,"message":"OK"}，
            # 公开文档未记载；它不是错误，音频已在之前的 code=0 帧里发完）
            if code not in (0, None, 20000000):
                raise RuntimeError(
                    f"火山 V3 TTS 失败 code={code} msg={obj.get('message')}"
                    f"（常见：模型/音色未在控制台开通 / 音色不是 2.0 系(*_uranus_bigtts) / API Key 无效）")
            data = obj.get("data")
            if data:
                audio.extend(base64.b64decode(data))
        return buf

    try:
        for raw_chunk in r.iter_content(chunk_size=None):
            if not raw_chunk:
                continue
            buf += text_decoder.decode(raw_chunk)
            buf = _drain(buf.lstrip())
        buf += text_decoder.decode(b"", final=True)
        buf = _drain(buf.lstrip())
    finally:
        r.close()
    if not audio:
        raise RuntimeError("火山 V3 TTS 未返回音频数据（可能凭据无效或音色不可用）")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(bytes(audio))


def _doubao_synth(text: str, out: str, voice: str | None, speed: float,
                  emotion: str | None = None, emotion_scale: int | None = None) -> str:
    """豆包 TTS 统一入口：按凭据自动路由 V3(新)/V1(旧，向后兼容)，返回实际使用的音色。
    emotion/emotion_scale 仅 V3 支持（V1 旧接口静默忽略并给 stderr 提示）。"""
    creds = resolve_credentials()
    api_key = creds.get("api_key")
    if api_key:
        resolved_voice = voice or creds["voice"] or DOUBAO_V3_DEFAULT_VOICE
        # appid 仅克隆音色（seed-icl-2.0，S_ 开头）需要作 X-Api-App-Id 头；默认音色忽略
        _doubao_v3_synth(text, out, resolved_voice, speed, api_key, creds.get("appid"),
                         emotion=emotion, emotion_scale=emotion_scale)
        return resolved_voice
    if emotion:
        print("⚠ V1 旧接口不支持 emotion，已忽略（配 VOLC_TTS_API_KEY 走 V3 才生效）",
              file=sys.stderr)

    import requests
    appid, token = creds["appid"], creds["token"]
    if not appid or not token:
        raise RuntimeError(
            "缺豆包 TTS 凭据：优先配 VOLC_TTS_API_KEY"
            "（新版控制台单一 API Key，找管理员要「凭据配置包」，或去火山引擎控制台"
            " speech/new/setting/apikeys 自建）；"
            "也可用旧版 VOLC_TTS_APPID / VOLC_TTS_ACCESS_TOKEN（填进 skill 的 .env，"
            "或跑 setup.py 凭据向导写入用户级 secrets，向后兼容）")
    cluster = creds["cluster"]
    resolved_voice = voice or creds["voice"] or DOUBAO_DEFAULT_VOICE
    body = {
        "app": {"appid": appid, "token": token, "cluster": cluster},
        "user": {"uid": "nbdpsy_t2v"},
        "audio": {"voice_type": resolved_voice, "encoding": "mp3", "speed_ratio": speed},
        "request": {"reqid": str(uuid.uuid4()), "text": text, "operation": "query"},
    }
    # 火山鉴权头是 "Bearer;{token}"（分号分隔，非空格）
    r = requests.post(DOUBAO_ENDPOINT, headers={"Authorization": f"Bearer;{token}"},
                      json=body, timeout=60)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"火山 TTS 非 JSON 响应 HTTP{r.status_code}: {r.text[:200]}")
    if j.get("code") != 3000:
        raise RuntimeError(
            f"火山 TTS 失败 code={j.get('code')} msg={j.get('message') or j.get('Message')}"
            f"（常见：音色未在控制台开通 / 凭据或 cluster 不对）")
    data = j.get("data")
    if not data:
        raise RuntimeError(f"火山 TTS 无音频数据：{str(j)[:200]}")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(base64.b64decode(data))
    return resolved_voice


# ---- MiniMax T2A ----

def _minimax_build_request(text: str, voice: str, speed: float, *,
                           model: str = MINIMAX_DEFAULT_MODEL,
                           emotion: str | None = None,
                           group_id: str | None = None) -> tuple[str, dict]:
    """构造 MiniMax T2A 的 (url, body)。抽成纯函数：不发请求即可断言载荷正确，
    避免为验证参数而真调接口（TTS 按字符计费，白跑一次就是真金白银）。
    本地预检在这里做完（whisper/2.8 冲突、非法 emotion、speed 越界 clamp），
    先于任何网络请求，不合法直接抛错。"""
    if not voice:
        raise RuntimeError(
            "MiniMax 需要音色 voice_id：用 --voice 传入，或配 MINIMAX_VOICE"
            "（官方 schema 无默认值，不代猜）")
    if emotion is not None:
        if emotion not in MINIMAX_EMOTIONS:
            raise RuntimeError(
                f"MiniMax 不认识的 emotion={emotion}，合法值：{'/'.join(MINIMAX_EMOTIONS)}"
                "（官方若新增情感值，请同步更新 MINIMAX_EMOTIONS）")
        if emotion == "whisper" and model.startswith(MINIMAX_WHISPER_UNSUPPORTED_PREFIX):
            raise RuntimeError(
                f"emotion=whisper 仅 2.6 系模型支持，当前 model={model} 不支持——"
                "请换 --model speech-2.6-hd/speech-2.6-turbo，或去掉 --emotion")
    clamped = max(MINIMAX_SPEED_MIN, min(MINIMAX_SPEED_MAX, speed))
    if clamped != speed:
        _err(f"⚠ MiniMax 语速范围 {MINIMAX_SPEED_MIN}-{MINIMAX_SPEED_MAX}（与豆包 0.8-2.0 不同），"
             f"--speed {speed} 已收敛为 {clamped}")
    voice_setting = {
        "voice_id": voice,
        "speed": clamped,
        "vol": 1,      # >0 且 ≤10，暂不暴露到 CLI
        "pitch": 0,    # -12..12 整数，暂不暴露到 CLI
    }
    # emotion 只在调用方显式指定时才带上：官方原文「模型会根据输入文本自动匹配
    # 合适的情绪，一般无需手动指定」，硬塞一个反而把自然的情绪起伏压平。
    if emotion is not None:
        voice_setting["emotion"] = emotion
    body = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": voice_setting,
        # sample_rate 官方 schema 没写 default，显式传，别赌默认值
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        # output_format 用默认 hex（不传该键）——data.audio 因此是 hex 串而非 base64
    }
    # 官方现行 OpenAPI 不需要 GroupId；旧版/国际站才要拼 query。配了才拼，没配不拼，
    # 且绝不做「不带→失败→带上重试」的自动试探（重试＝重复计费）。
    url = f"{MINIMAX_ENDPOINT}?GroupId={group_id}" if group_id else MINIMAX_ENDPOINT
    return url, body


def _minimax_retry_delay(attempt: int) -> float:
    """第 attempt 次失败后的退避秒数（指数 + 抖动）。抖动是必须的：并行池里多路
    同时撞限流，若退避时长一致会一起醒来再一起撞墙（惊群），错开才能陆续挤进去。"""
    base = min(MINIMAX_RETRY_BASE_DELAY * (2 ** (attempt - 1)), MINIMAX_RETRY_MAX_DELAY)
    return base + random.uniform(0, base * 0.25)


def _minimax_synth(text: str, out: str, voice: str, speed: float, api_key: str, *,
                   model: str = MINIMAX_DEFAULT_MODEL, emotion: str | None = None,
                   group_id: str | None = None,
                   retry_attempts: int = MINIMAX_RETRY_ATTEMPTS) -> bool:
    """MiniMax 同步 HTTP 合成（POST /v1/t2a_v2，stream=false，一次请求拿全量音频）。
    响应契约：data.audio 是 **hex 编码**字符串（不是 base64，与豆包不同，用 bytes.fromhex）；
    data.status 1=合成中 2=结束；extra_info.audio_length(ms)/usage_characters(计费字符数)/word_count；
    base_resp.status_code 0=正常，1000 未知 / 1001 超时 / 1002 限流 / 1004 鉴权失败 /
    1039 TPM限流 / 1042 非法字符超10% / 2013 参数不正常。
    **HTTP 200 不代表成功**——这类 API 常在 200 里返错误码，必须查 base_resp（本仓库踩过同类坑）。
    失败一律原文透出、**除限流外绝不自动重试**：TTS 按字符计费（1 汉字=2 字符；
    speech-2.8-hd ¥3.5/万字符、speech-2.8-turbo ¥2.0/万字符），重试就是重复扣费，
    该不该再花钱由调用方决定。唯一豁免是限流码（MINIMAX_RATELIMIT_CODES）——
    实测服务端根本没合成、不返音频也不计费，重试只花时间不花钱（见该常量处的实测依据）。"""
    import requests
    url, body = _minimax_build_request(text, voice, speed, model=model,
                                       emotion=emotion, group_id=group_id)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    group_hint = ("（若你的账号属于旧版/国际站，可配置 MINIMAX_GROUP_ID 后重试）"
                  if not group_id else "")
    for attempt in range(1, retry_attempts + 2):
        r = requests.post(url, headers=headers, json=body, timeout=120)
        if r.status_code != 200:
            auth_hint = group_hint if r.status_code == 401 else ""
            raise RuntimeError(f"MiniMax TTS HTTP {r.status_code}：{r.text[:300]}{auth_hint}")
        try:
            j = r.json()
        except Exception:
            raise RuntimeError(f"MiniMax TTS 非 JSON 响应 HTTP{r.status_code}: {r.text[:300]}")
        base = j.get("base_resp") or {}
        code = base.get("status_code")
        if code in MINIMAX_RATELIMIT_CODES and attempt <= retry_attempts:
            delay = _minimax_retry_delay(attempt)
            _err(f"[tts] MiniMax 限流 status_code={code}（未合成不计费），"
                 f"{delay:.1f}s 后第 {attempt}/{retry_attempts} 次重试")
            time.sleep(delay)
            continue
        break
    if code not in (0, None):
        hint = group_hint if code == 1004 else ""
        exhausted = ("（已退避重试 %d 次仍被限流：说明这把 key 的每分钟额度被占满，"
                     "多半有别的会话在同时用；降低 --concurrency 或错开时间）"
                     % retry_attempts) if code in MINIMAX_RATELIMIT_CODES else ""
        raise RuntimeError(
            f"MiniMax TTS 失败 status_code={code} msg={base.get('status_msg')} "
            f"trace_id={j.get('trace_id')}{hint}{exhausted}")
    audio_hex = ((j.get("data") or {}).get("audio")) or ""
    if not audio_hex:
        raise RuntimeError(f"MiniMax TTS 无音频数据（trace_id={j.get('trace_id')}）：{str(j)[:300]}")
    try:
        audio = bytes.fromhex(audio_hex)
    except ValueError as e:
        raise RuntimeError(f"MiniMax TTS 音频不是合法 hex（{e}），未按预期的 output_format 返回")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(audio)
    # 计费对账：从服务端回执读实际计费字符数，打一行到 stderr，方便事后核对账单
    used = (j.get("extra_info") or {}).get("usage_characters")
    if used is not None:
        price = MINIMAX_PRICE_PER_10K.get(model)
        cost = f"（约 ¥{used / 10000 * price:.2f}）" if price else "（该型号价目未登记）"
        _err(f"[tts] MiniMax 本次计费字符 {used}{cost}")
    return True


# ---- 统一入口 ----

def gen_one(text: str, out: str, *, engine: str = "edge", voice: str | None = None,
            rate: str = EDGE_DEFAULT_RATE, speed: float = 0.95,
            emotion: str | None = None, emotion_scale: int | None = None,
            model: str = MINIMAX_DEFAULT_MODEL) -> dict:
    text = (text or "").strip()
    if not text:
        return {"success": False, "error": "文本为空"}
    resolved_voice = voice or EDGE_DEFAULT_VOICE
    try:
        if engine == "doubao":
            resolved_voice = _doubao_synth(text, out, voice, speed,
                                           emotion=emotion, emotion_scale=emotion_scale)
        elif engine == "minimax":
            creds = resolve_minimax_credentials()
            if not creds["api_key"]:
                raise RuntimeError(
                    "缺 MiniMax TTS 凭据 MINIMAX_API_KEY：填进 skill 的 .env，"
                    "或跑 setup.py 凭据向导写入用户级 secrets")
            resolved_voice = voice or creds["voice"]
            _minimax_synth(text, out, resolved_voice, speed, creds["api_key"],
                           model=model, emotion=emotion, group_id=creds["group_id"])
        else:
            asyncio.run(_edge_synth(text, out, resolved_voice, rate))
    except ModuleNotFoundError as e:
        return {"success": False, "error": f"缺依赖 {e.name}（edge-tts 或 requests）"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    return {"success": True, "output": str(Path(out).resolve()), "engine": engine, "voice": resolved_voice}


# 发音别名：合成时替换为可正确朗读的形式，字幕/cues 保留原文。
# NBDpsy 整词会被模型瞎拼（实测念成 "nbd pas"），空格分开逐字母念。
_SPEAK_ALIASES = {
    "NBDpsy": "N B D P S Y",
}


_DIGIT_ZH = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
             "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"}
# 四位数字 + 年 → 年份，必须逐位念（2026-08-07 老板听出：1946 年被念成
# 「一千九百四十六年」）。只认紧跟「年」的四位数，避免误伤金额/样本量等真数值
# （「149 对」「6973 人」仍按数值念才对）。
_YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(\s*)年")


def _speak_years(text: str) -> str:
    """把「1946 年」改写成「一九四六年」——年份是序号不是数量，逐位念才自然。"""
    return _YEAR_RE.sub(lambda m: "".join(_DIGIT_ZH[c] for c in m.group(1)) + "年", text)


def _speakable(text: str) -> str:
    """应用发音归一化（只影响送 TTS 的文本，不影响字幕原文）：别名 + 年份逐位。"""
    for k, v in _SPEAK_ALIASES.items():
        text = text.replace(k, v)
    return _speak_years(text)


def _make_silence(path: str, seconds: float) -> bool:
    """生成一段静音 mp3（句间垫片用）。"""
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", f"{seconds:.3f}",
         "-i", "anullsrc=r=44100:cl=mono", "-c:a", "libmp3lame", "-q:a", "2", path],
        capture_output=True, text=True, timeout=60)
    return r.returncode == 0


def _concat_mp3(parts: list[str], out: str) -> bool:
    """把多句 mp3 顺序拼成一条（重编码保证帧对齐，避免间隙）。"""
    lst = Path(out).with_suffix(".concat.lst")
    lst.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in parts), encoding="utf-8")
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c:a", "libmp3lame", "-q:a", "2", out],
        capture_output=True, text=True, timeout=300)
    lst.unlink(missing_ok=True)
    return r.returncode == 0


# 逐句合成的并行度默认值。**只对 MiniMax 实测过**（2026-08-17 本机探测）：
# 同时打 20 发全进、24 发进 20，但把并发压到 1（完全串行）照样会撞 1002——
# 说明被限的是「每分钟请求数」（实测约 20-22 次/分），不是「同时在飞几路」。
# 于是并行的收益是**把一个窗口内的额度一次性用掉**（十来句从 ~25s 压到 ~7s），
# 而不是把吞吐拉到无穷；超出额度的部分由 _minimax_synth 的限流退避兜住。
# 默认取 4 而不是实测上限 20：这把 key 是多个会话共用的，实测数字是"整把 key 的",
# 独占它等于把别的会话饿死；4 路已经吃满典型口播的加速空间，还留着大头给别人。
# 其他引擎（edge/doubao）没做过并发实测，默认保持串行——不拿没量过的数当默认值。
MINIMAX_DEFAULT_CONCURRENCY = 4


def _resolve_concurrency(concurrency: int | None, engine: str, n_items: int) -> int:
    """解析实际并行度：显式传入优先；未传时只有 minimax 走并行默认值，其余引擎串行。"""
    if concurrency is None:
        concurrency = MINIMAX_DEFAULT_CONCURRENCY if engine == "minimax" else 1
    return max(1, min(int(concurrency), max(1, n_items)))


def gen_timed(text: str, out: str, *, engine: str = "doubao", voice: str | None = None,
              rate: str = EDGE_DEFAULT_RATE, speed: float = 0.95,
              emotion: str | None = None, emotion_scale: int | None = None,
              model: str = MINIMAX_DEFAULT_MODEL, gap: float = 0.45,
              concurrency: int | None = None) -> dict:
    """逐句合成 + 实测时间轴：每句单独 TTS、ffprobe 实测时长、拼接成 out，
    并写 sidecar {out}.cues.json（[{text,start,end}]），供 compose 做字幕真同步。
    gap = 句间静音秒数（2026-08-07 老板定案：上句说完不能立马抢下句——
    MiniMax 句尾几乎零留白，逐句拼接必须垫间隙；cues 时间轴含间隙偏移）。
    concurrency = 逐句合成的并行路数（见 MINIMAX_DEFAULT_CONCURRENCY）。
    🔴 并行只影响"谁先合成完"，绝不影响"谁排在前面"：拼接与 cues 一律按**原句序**，
    见下方 executor.map 的顺序保证与 test_tts_concurrency.py 的乱序完成用例。"""
    text = (text or "").strip()
    if not text:
        return {"success": False, "error": "文本为空"}
    sents = _split_sentences(text)
    workers = _resolve_concurrency(concurrency, engine, len(sents))
    tmp = tempfile.mkdtemp(prefix="tts_timed_")
    try:
        # ⚠️ 拼接必须走 wav/PCM 域（2026-08-11 修）：mp3 逐段 concat 每段漂 ~46ms 且随句数累积
        # （8 句实测累计 0.41s，字卡/字幕越到后面越早于语音）——与播客线 2026-08-07 定性的
        # 死路同因。正解＝逐段解码为统一采样率 PCM，按**样本数**拼接并构造 cues，最后一次性
        # 编码输出（encoder delay 只发生一次、不随句数累积）。
        import wave
        SR = 32000
        gap = max(0.0, gap)
        gap_frames = int(round(gap * SR))

        def _mp3_to_pcm(mp3_path: str) -> bytes:
            wav_path = mp3_path + ".wav"
            p = subprocess.run(["ffmpeg", "-y", "-i", mp3_path, "-ar", str(SR), "-ac", "1",
                                "-sample_fmt", "s16", wav_path],
                               capture_output=True)
            if p.returncode != 0:
                raise RuntimeError(f"解码失败: {p.stderr.decode()[-200:]}")
            with wave.open(wav_path, "rb") as w:
                return w.readframes(w.getnframes())

        def _synth(i: int) -> dict:
            part = str(Path(tmp) / f"p{i:03d}.mp3")
            # 发音别名只进合成文本；cue 存原文（字幕要显示 NBDpsy 而不是拆开的字母）
            return gen_one(_speakable(sents[i]), part, engine=engine, voice=voice, rate=rate,
                           speed=speed, emotion=emotion, emotion_scale=emotion_scale, model=model)

        # 并行合成：executor.map **按提交顺序**返回结果（与完成先后无关），
        # 所以 parts[i] 恒对应 sents[i]——顺序不靠"谁先回来"，靠下标。
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                parts = list(ex.map(_synth, range(len(sents))))
        else:
            parts = [_synth(i) for i in range(len(sents))]
        # 失败按最小句序报，跟串行时代的报错口径一致（并行下可能多句同时失败）
        for i, r in enumerate(parts):
            if not r.get("success"):
                return {"success": False, "error": f"句{i}合成失败：{r.get('error')}"}

        pcm_chunks, cues, frames_t = [], [], 0
        for i, s in enumerate(sents):
            if i and gap_frames:
                pcm_chunks.append(b"\x00\x00" * gap_frames)
                frames_t += gap_frames
            pcm = _mp3_to_pcm(str(Path(tmp) / f"p{i:03d}.mp3"))
            n = len(pcm) // 2
            # 一句 = 一条字幕（2026-08-07 老板定案：句号翻页、逗号换行）。
            # 句内逗号的换行由 compose 渲染层处理，这里保留原文标点作为换行依据。
            cues.append({"text": s.strip(), "start": round(frames_t / SR, 3),
                         "end": round((frames_t + n) / SR, 3)})
            frames_t += n
            pcm_chunks.append(pcm)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        total_wav = str(Path(tmp) / "total.wav")
        with wave.open(total_wav, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            for c in pcm_chunks:
                w.writeframes(c)
        enc = subprocess.run(["ffmpeg", "-y", "-i", total_wav, "-codec:a", "libmp3lame",
                              "-b:a", "128k", str(out)], capture_output=True)
        if enc.returncode != 0:
            return {"success": False, "error": f"编码输出失败: {enc.stderr.decode()[-200:]}"}
        # 渲染/混音场景优先用无损 wav（连全局 encoder delay 都没有）
        wav_sidecar = str(out) + ".wav"
        shutil.copy(total_wav, wav_sidecar)
        dur = ffprobe_duration(out)
        cues_path = str(out) + ".cues.json"
        # 🔴 **合成参数跟着它产出的东西走**（2026-08-20，助理："八条同参可追溯"）。
        # ⚠️ 参数只留在命令行历史里 ⇒ **一批片子参数不一致也没人发现**——
        #    而语速直接决定每屏停留时长，混了就是一批节奏不齐的片子。
        # ⛔ 别改 `duration`/`cues` 这两个键的名字与位置：下游全靠 `.get("cues", c)` 读。
        Path(cues_path).write_text(
            json.dumps({"duration": dur, "cues": cues,
                        "params": {"engine": engine, "voice": voice, "speed": speed,
                                   "gap": gap, "model": model,
                                   "emotion": emotion, "emotion_scale": emotion_scale}},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        return {"success": True, "output": str(Path(out).resolve()), "engine": engine,
                # 逐句实际解析出的音色（V3/V1 各自默认不同，见 gen_one）。取 parts[-1] 而非
                # "最后一个循环变量"：并行下"最后完成的"不确定，按下标取才可复现。
                "voice": parts[-1].get("voice", voice),
                "duration": dur, "cues": cues, "cues_path": cues_path}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def gen_batch(plan_path: str, out_dir: str, *, engine: str = "edge", voice: str | None = None,
              rate: str = EDGE_DEFAULT_RATE, speed: float = 0.95, timed: bool = False,
              model: str = MINIMAX_DEFAULT_MODEL, gap: float = 0.45,
              concurrency: int | None = None) -> dict:
    """分镜逐条合成。**分镜之间保持串行**：--timed 时每条分镜内部已经按句并行了，
    再在外层套一层并行会把并行度乘起来（4 路 × N 分镜），直接把共用 key 的额度打爆。"""
    try:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"读取 plan 失败：{e}"}
    if isinstance(plan, dict) and "shots" in plan:
        plan = plan["shots"]
    if not isinstance(plan, list) or not plan:
        return {"success": False, "error": "plan 应为分镜数组（或 {shots:[...]})"}

    results = []
    for i, shot in enumerate(plan):
        text = (shot.get("narration_text") or shot.get("subtitle") or "").replace("\n", "").strip()
        out = str(Path(out_dir) / f"{i:03d}.mp3")
        if not text:
            results.append({"index": i, "success": False, "error": "无旁白文案", "output": None})
            _err(f"[tts] 分镜 {i}: 跳过(无文案)")
            continue
        if timed:
            r = gen_timed(text, out, engine=engine, voice=voice, rate=rate, speed=speed,
                          model=model, gap=gap, concurrency=concurrency)
        else:
            r = gen_one(text, out, engine=engine, voice=voice, rate=rate, speed=speed, model=model)
        r["index"] = i
        results.append(r)
        _err(f"[tts] 分镜 {i}: {'✅' if r.get('success') else '❌ ' + r.get('error', '')} {out}"
             f"{' (+cues)' if timed and r.get('success') else ''}")
    ok = sum(1 for r in results if r.get("success"))
    return {"success": ok > 0, "total": len(results), "ok": ok, "results": results}


def main() -> None:
    p = argparse.ArgumentParser(description="中文旁白生成（edge-tts / 火山豆包 / MiniMax）")
    p.add_argument("--engine", default="edge", choices=["edge", "doubao", "minimax"])
    p.add_argument("--text")
    p.add_argument("--out")
    p.add_argument("--plan")
    p.add_argument("--out-dir", default="./tts")
    p.add_argument("--voice", default=None)
    p.add_argument("--rate", default=EDGE_DEFAULT_RATE, help="edge 语速，如 -10%%")
    p.add_argument("--model", default=MINIMAX_DEFAULT_MODEL, choices=list(MINIMAX_MODELS),
                   help=f"MiniMax 模型（仅 --engine minimax 生效），默认 {MINIMAX_DEFAULT_MODEL}")
    p.add_argument("--speed", type=float, default=0.95,
                   help="语速：豆包 speed_ratio 0.8-2.0；MiniMax 0.5-2.0（越界自动收敛）")
    p.add_argument("--emotion", default=None,
                   help="豆包 V3 情感/风格（Seed-TTS/ICL 2.0）：如 sad/happy/pleased/"
                        "novel_dialog 等 28 种；克隆音色官方明确支持情感演绎。"
                        "MiniMax 合法值仅 9 种：happy/sad/angry/fearful/disgusted/"
                        "surprised/calm/fluent/whisper（whisper 仅 2.6 系支持），"
                        "不传则由模型按文本自动匹配情绪（官方建议）")
    p.add_argument("--emotion-scale", type=int, default=None,
                   help="情感强度 1-5（配 --emotion 用）")
    p.add_argument("--timed", action="store_true",
                   help="逐句合成+写 .cues.json 时间轴（字幕真同步，强烈建议）")
    p.add_argument("--gap", type=float, default=0.45,
                   help="--timed 句间静音秒数（默认 0.45；上句说完不抢下句）")
    p.add_argument("--concurrency", type=int, default=None,
                   help=f"--timed 逐句合成的并行路数。MiniMax 默认 {MINIMAX_DEFAULT_CONCURRENCY}，"
                        "其余引擎默认串行（只对 MiniMax 做过并发实测，不拿没量过的数当默认值）。"
                        "2026-08-17 实测：这把 key 一次能同时打进 20 发，但真正被限的是"
                        "每分钟请求数（约 20-22 次/分），压到完全串行照样会撞 1002。"
                        f"默认设 {MINIMAX_DEFAULT_CONCURRENCY} 而不是实测上限 20，是因为额度是"
                        "整把 key 的、多个会话共用，独占它会把别人饿死；限流会自动退避重试。"
                        "🔴 RPM 是**整把 key 共享**的：调小并发并不能替你避开它——"
                        "两个会话各开 2 路，照样一起吃那 20-22 次/分。真正兜住的是退避重试，"
                        "⛔ 不是把路数调低。（2026-08-17 运营线实测佐证：它没有退避，"
                        "3 路连发 12 句 0/3 全灭、2 路 2/2——同一个 RPM 墙，靠压路数只是把撞墙推迟。）"
                        "⚠️ 多条线要同时跑批，正解是**错开批次**，不是各自调小路数")
    a = p.parse_args()

    if a.plan:
        res = gen_batch(a.plan, a.out_dir, engine=a.engine, voice=a.voice, rate=a.rate,
                        speed=a.speed, timed=a.timed, model=a.model, gap=a.gap,
                        concurrency=a.concurrency)
    elif a.text and a.out:
        if a.timed:
            res = gen_timed(a.text, a.out, engine=a.engine, voice=a.voice, rate=a.rate, speed=a.speed,
                            emotion=a.emotion, emotion_scale=a.emotion_scale, model=a.model, gap=a.gap,
                            concurrency=a.concurrency)
        else:
            res = gen_one(a.text, a.out, engine=a.engine, voice=a.voice, rate=a.rate, speed=a.speed,
                          emotion=a.emotion, emotion_scale=a.emotion_scale, model=a.model)
    else:
        p.error("用 --text+--out 单条，或 --plan+--out-dir 批量")
        return
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("success") else 1)


if __name__ == "__main__":
    main()

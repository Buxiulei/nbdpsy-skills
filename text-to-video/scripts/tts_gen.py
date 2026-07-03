#!/usr/bin/env python3
"""中文旁白生成 —— 双引擎：edge-tts(免费无 key) / 火山豆包大模型 TTS(高音质, 需 key)。

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
          · 无 API Key 但有 VOLC_TTS_APPID+VOLC_TTS_ACCESS_TOKEN（旧版双凭据）
            → 走 V1 接口（/api/v1/tts，官方已标"不推荐"但保留向后兼容），
            默认音色仍是 zh_female_wenroushunv_mars_bigtts「温柔淑女」。
          · 都无 → 报错，优先引导配 VOLC_TTS_API_KEY。

**逐句时间轴 --timed（字幕真同步的根，强烈建议开）**：
  默认整段合成时，字幕只能按字数比例估算时长 → 与真实语速错位。
  --timed 会把旁白按句末标点(。！？)切句、每句单独合成、ffprobe 实测时长后拼接，
  并写 sidecar `{out}.cues.json`（每句 text/start/end）。compose_video.py 检测到 cues
  就让字幕严格按每句实测时长显示，旁白讲到哪字幕走到哪，彻底同步。

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
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import codecs
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
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
DOUBAO_V3_RESOURCE_ID = "seed-tts-2.0"  # 豆包语音合成大模型2.0（另有 seed-icl-2.0 用于声音复刻音色，本产线不用）


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


def _doubao_v3_synth(text: str, out: str, voice: str, speed: float, api_key: str) -> None:
    """V3 单向流式合成（新版单一 API Key）。
    契约锁定自官方文档 https://www.volcengine.com/docs/6561/2528925：
      POST https://openspeech.bytedance.com/api/v3/tts/unidirectional
      请求头：X-Api-Key(必选) / X-Api-Resource-Id(必选，seed-tts-2.0) / X-Api-Request-Id(必选，uuid)
      请求体：{"req_params": {"text","speaker","audio_params":{"format","sample_rate"},"speech_rate"}}
      响应：基于 HTTP Chunked 的连续 JSON 对象流（官方 curl 示例用 -N 免缓冲），
      每个 JSON 对象形如 {"code":0,"message":"OK","data":"<base64 音频分片>","sentence":{...}}，
      data 逐段 base64 解码后按到达顺序拼接即完整音频；文档未给出显式"流结束"字段，
      以 HTTP 响应流关闭（无更多数据）作为结束判定。"""
    import requests
    speech_rate = _doubao_v3_speech_rate(speed)
    body = {
        "req_params": {
            "text": text,
            "speaker": voice,
            "audio_params": {"format": "mp3", "sample_rate": 24000},
            "speech_rate": speech_rate,
        }
    }
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": DOUBAO_V3_RESOURCE_ID,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
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
            if code not in (0, None):
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


def _doubao_synth(text: str, out: str, voice: str | None, speed: float) -> str:
    """豆包 TTS 统一入口：按凭据自动路由 V3(新)/V1(旧，向后兼容)，返回实际使用的音色。"""
    creds = resolve_credentials()
    api_key = creds.get("api_key")
    if api_key:
        resolved_voice = voice or creds["voice"] or DOUBAO_V3_DEFAULT_VOICE
        _doubao_v3_synth(text, out, resolved_voice, speed, api_key)
        return resolved_voice

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


# ---- 统一入口 ----

def gen_one(text: str, out: str, *, engine: str = "edge", voice: str | None = None,
            rate: str = EDGE_DEFAULT_RATE, speed: float = 0.95) -> dict:
    text = (text or "").strip()
    if not text:
        return {"success": False, "error": "文本为空"}
    resolved_voice = voice or EDGE_DEFAULT_VOICE
    try:
        if engine == "doubao":
            resolved_voice = _doubao_synth(text, out, voice, speed)
        else:
            asyncio.run(_edge_synth(text, out, resolved_voice, rate))
    except ModuleNotFoundError as e:
        return {"success": False, "error": f"缺依赖 {e.name}（edge-tts 或 requests）"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    return {"success": True, "output": str(Path(out).resolve()), "engine": engine, "voice": resolved_voice}


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


def gen_timed(text: str, out: str, *, engine: str = "doubao", voice: str | None = None,
              rate: str = EDGE_DEFAULT_RATE, speed: float = 0.95) -> dict:
    """逐句合成 + 实测时间轴：每句单独 TTS、ffprobe 实测时长、拼接成 out，
    并写 sidecar {out}.cues.json（[{text,start,end}]），供 compose 做字幕真同步。"""
    text = (text or "").strip()
    if not text:
        return {"success": False, "error": "文本为空"}
    sents = _split_sentences(text)
    tmp = tempfile.mkdtemp(prefix="tts_timed_")
    try:
        parts, cues, t = [], [], 0.0
        for i, s in enumerate(sents):
            part = str(Path(tmp) / f"p{i:03d}.mp3")
            r = gen_one(s, part, engine=engine, voice=voice, rate=rate, speed=speed)
            if not r.get("success"):
                return {"success": False, "error": f"句{i}合成失败：{r.get('error')}"}
            d = ffprobe_duration(part)
            # 句内再按逗号等细分为字幕条，按字数比例分配该句实测时长(滚动更细、不一条久挂；
            # 同步精度仍是句级实测，单句内语速均匀故比例估算误差极小)
            units = _split_caption_units(s)
            ulen = sum(len(u) for u in units) or 1
            ut = t
            for k, u in enumerate(units):
                end = (t + d) if k == len(units) - 1 else (ut + d * (len(u) / ulen))
                cues.append({"text": u.strip(), "start": round(ut, 3), "end": round(end, 3)})
                ut = end
            t += d
            parts.append(part)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        if len(parts) == 1:
            shutil.copy(parts[0], out)
        elif not _concat_mp3(parts, out):
            return {"success": False, "error": "拼接句子音频失败"}
        dur = ffprobe_duration(out)
        cues_path = str(out) + ".cues.json"
        Path(cues_path).write_text(
            json.dumps({"duration": dur, "cues": cues}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return {"success": True, "output": str(Path(out).resolve()), "engine": engine,
                "voice": r.get("voice", voice),  # 逐句实际解析出的音色（V3/V1 各自默认不同，见 gen_one）
                "duration": dur, "cues": cues, "cues_path": cues_path}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def gen_batch(plan_path: str, out_dir: str, *, engine: str = "edge", voice: str | None = None,
              rate: str = EDGE_DEFAULT_RATE, speed: float = 0.95, timed: bool = False) -> dict:
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
            r = gen_timed(text, out, engine=engine, voice=voice, rate=rate, speed=speed)
        else:
            r = gen_one(text, out, engine=engine, voice=voice, rate=rate, speed=speed)
        r["index"] = i
        results.append(r)
        _err(f"[tts] 分镜 {i}: {'✅' if r.get('success') else '❌ ' + r.get('error', '')} {out}"
             f"{' (+cues)' if timed and r.get('success') else ''}")
    ok = sum(1 for r in results if r.get("success"))
    return {"success": ok > 0, "total": len(results), "ok": ok, "results": results}


def main() -> None:
    p = argparse.ArgumentParser(description="中文旁白生成（edge-tts / 火山豆包）")
    p.add_argument("--engine", default="edge", choices=["edge", "doubao"])
    p.add_argument("--text")
    p.add_argument("--out")
    p.add_argument("--plan")
    p.add_argument("--out-dir", default="./tts")
    p.add_argument("--voice", default=None)
    p.add_argument("--rate", default=EDGE_DEFAULT_RATE, help="edge 语速，如 -10%%")
    p.add_argument("--speed", type=float, default=0.95, help="豆包语速 speed_ratio 0.8-2.0")
    p.add_argument("--timed", action="store_true",
                   help="逐句合成+写 .cues.json 时间轴（字幕真同步，强烈建议）")
    a = p.parse_args()

    if a.plan:
        res = gen_batch(a.plan, a.out_dir, engine=a.engine, voice=a.voice, rate=a.rate,
                        speed=a.speed, timed=a.timed)
    elif a.text and a.out:
        if a.timed:
            res = gen_timed(a.text, a.out, engine=a.engine, voice=a.voice, rate=a.rate, speed=a.speed)
        else:
            res = gen_one(a.text, a.out, engine=a.engine, voice=a.voice, rate=a.rate, speed=a.speed)
    else:
        p.error("用 --text+--out 单条，或 --plan+--out-dir 批量")
        return
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("success") else 1)


if __name__ == "__main__":
    main()

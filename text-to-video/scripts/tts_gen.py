#!/usr/bin/env python3
"""中文旁白生成 —— 双引擎：edge-tts(免费无 key) / 火山豆包大模型 TTS(高音质, 需 key)。

把分镜旁白文案转成 mp3，喂给 compose_video.py 的 segments[].narration。

引擎 --engine：
  edge   （默认，免费）edge-tts，音色 --voice zh-CN-XiaoxiaoNeural，语速 --rate "-10%"
  doubao （高音质，需 key）火山大模型 TTS，凭据读 ../.env 的 VOLC_TTS_*，
          音色 --voice 或 VOLC_TTS_VOICE，语速 --speed 0.95(0.8-2.0)

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
# 默认大模型音色：温柔淑女（成熟温柔知性，心理科普旁白；需控制台开通）
DOUBAO_DEFAULT_VOICE = "zh_female_wenroushunv_mars_bigtts"
DOUBAO_ENDPOINT = "https://openspeech.bytedance.com/api/v1/tts"


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

def _doubao_synth(text: str, out: str, voice: str | None, speed: float) -> None:
    import requests
    _load_env()
    appid = os.environ.get("VOLC_TTS_APPID")
    token = os.environ.get("VOLC_TTS_ACCESS_TOKEN")
    if not appid or not token:
        raise RuntimeError("缺 VOLC_TTS_APPID / VOLC_TTS_ACCESS_TOKEN（填进 skill 的 .env）")
    cluster = os.environ.get("VOLC_TTS_CLUSTER") or "volcano_tts"
    voice = voice or os.environ.get("VOLC_TTS_VOICE") or DOUBAO_DEFAULT_VOICE
    body = {
        "app": {"appid": appid, "token": token, "cluster": cluster},
        "user": {"uid": "nbdpsy_t2v"},
        "audio": {"voice_type": voice, "encoding": "mp3", "speed_ratio": speed},
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


# ---- 统一入口 ----

def gen_one(text: str, out: str, *, engine: str = "edge", voice: str | None = None,
            rate: str = EDGE_DEFAULT_RATE, speed: float = 0.95) -> dict:
    text = (text or "").strip()
    if not text:
        return {"success": False, "error": "文本为空"}
    try:
        if engine == "doubao":
            _doubao_synth(text, out, voice, speed)
        else:
            asyncio.run(_edge_synth(text, out, voice or EDGE_DEFAULT_VOICE, rate))
    except ModuleNotFoundError as e:
        return {"success": False, "error": f"缺依赖 {e.name}（edge-tts 或 requests）"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    return {"success": True, "output": str(Path(out).resolve()), "engine": engine,
            "voice": voice or (DOUBAO_DEFAULT_VOICE if engine == "doubao" else EDGE_DEFAULT_VOICE)}


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
                "voice": voice or (DOUBAO_DEFAULT_VOICE if engine == "doubao" else EDGE_DEFAULT_VOICE),
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

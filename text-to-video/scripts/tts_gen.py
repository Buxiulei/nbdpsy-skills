#!/usr/bin/env python3
"""中文旁白生成 —— 双引擎：edge-tts(免费无 key) / 火山豆包大模型 TTS(高音质, 需 key)。

把分镜旁白文案转成 mp3，喂给 compose_video.py 的 segments[].narration。

引擎 --engine：
  edge   （默认，免费）edge-tts，音色 --voice zh-CN-XiaoxiaoNeural，语速 --rate "-10%"
  doubao （高音质，需 key）火山大模型 TTS，凭据读 ../.env 的 VOLC_TTS_*，
          音色 --voice 或 VOLC_TTS_VOICE，语速 --speed 0.95(0.8-2.0)

edge 常用音色：zh-CN-XiaoxiaoNeural(温柔女) / zh-CN-YunxiNeural(沉稳男)
豆包大模型音色示例(需控制台已开通)：zh_female_wanwanxiaohe_moon_bigtts / zh_male_*_bigtts

用法：
  python tts_gen.py --text "焦虑不是敌人…" --out tts/1.mp3
  python tts_gen.py --engine doubao --text "焦虑不是敌人…" --out tts/1.mp3
  python tts_gen.py --plan shots.json --out-dir tts/ --engine doubao
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import uuid
from pathlib import Path

EDGE_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
EDGE_DEFAULT_RATE = "-10%"
DOUBAO_DEFAULT_VOICE = "zh_female_wanwanxiaohe_moon_bigtts"  # 大模型温柔女声(需控制台开通)
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


def gen_batch(plan_path: str, out_dir: str, *, engine: str = "edge", voice: str | None = None,
              rate: str = EDGE_DEFAULT_RATE, speed: float = 0.95) -> dict:
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
        r = gen_one(text, out, engine=engine, voice=voice, rate=rate, speed=speed)
        r["index"] = i
        results.append(r)
        _err(f"[tts] 分镜 {i}: {'✅' if r.get('success') else '❌ ' + r.get('error', '')} {out}")
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
    a = p.parse_args()

    if a.plan:
        res = gen_batch(a.plan, a.out_dir, engine=a.engine, voice=a.voice, rate=a.rate, speed=a.speed)
    elif a.text and a.out:
        res = gen_one(a.text, a.out, engine=a.engine, voice=a.voice, rate=a.rate, speed=a.speed)
    else:
        p.error("用 --text+--out 单条，或 --plan+--out-dir 批量")
        return
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("success") else 1)


if __name__ == "__main__":
    main()

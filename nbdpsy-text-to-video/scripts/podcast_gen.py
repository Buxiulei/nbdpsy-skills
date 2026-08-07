#!/usr/bin/env python3
"""「长文播客」对谈稿驱动器 —— 读 podcast.json，逐行 MiniMax 双声合成，
拼成 podcast.mp3 + 写实测时间轴 podcast.cues.json。

形态规格见 references/podcast-video-spec.md（③ MiniMax 双声合成那一节）。
本脚本只做「稿 → 音轨 + 时间轴」；播放器页与录屏交给 podcast_player.html /
record_podcast.py。

输入 podcast.json：
  {
    "series": "NBDpsy 会客厅", "vol": 1, "title": "本期主题",
    "source": "源长文 slug",
    "lines": [
      {"speaker": "F", "text": "……", "emotion": null, "speed": 1.05, "pause_after": 0.3},
      {"speaker": "M", "text": "……"}
    ]
  }
  speaker 只认 "F"/"M"（其他值直接报错——对谈只有两个人，静默兜底会让整期串音色）。
  speed 缺省 1.05、pause_after 缺省 0.3、emotion 缺省不传（官方建议：不传由模型
  按文本自动匹配情绪，硬指定反而把自然起伏压平）。

用法：
  python3 podcast_gen.py synth podcast.json                 # 合成（断点续跑，已有的跳过）
  python3 podcast_gen.py synth podcast.json --force          # 全部重来（会重复扣费）
  python3 podcast_gen.py synth podcast.json --voice-m "Chinese (Mandarin)_Radio_Host"

产物（默认落在 podcast.json 同目录）：
  lines/line-NN.mp3   每行音频（+ 同名 .txt 存合成指纹，用于幂等判重）
  podcast.mp3         完整音轨
  podcast.cues.json   {"duration":…, "cues":[{speaker,text,start,end}]}

**绝不自动重试**：MiniMax TTS 按字符计费，重试＝重复扣费（本仓库资金安全铁律）。
失败原样抛出，要不要再花钱由人决定。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 同目录 import tts_gen（复用其 minimax 合成与凭据链，不套 subprocess 壳：
# 套壳会丢掉异常类型、多一层进程启动开销，且凭据要经过命令行/环境二次传递）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tts_gen  # noqa: E402

# 双声默认音色：女声=温暖闺蜜（现役，与微电影口播同一把嗓子）；
# 男声=温润男声 Gentleman（规格 §③ 三候选之一，暂定默认，可 --voice-m 覆盖）
DEFAULT_VOICE_F = "Chinese (Mandarin)_Warm_Bestie"
DEFAULT_VOICE_M = "Chinese (Mandarin)_Gentleman"
DEFAULT_SPEED = 1.05
DEFAULT_PAUSE = 0.3
# 静音垫片与 MiniMax 输出保持同采样率/声道，避免 concat 时重采样引入额外偏移
SILENCE_RATE = 32000

# MiniMax 语气词标签（仅 2.8 系支持），合成时要念出气口、但**不能出现在字幕上**
MINIMAX_TAGS = (
    "sighs", "breath", "chuckle", "laughs", "gasps", "exhale", "inhale", "coughs",
    "clear-throat", "groans", "pant", "sniffs", "snorts", "humming", "hissing",
    "emm", "sneezes", "burps", "lip-smacking",
)
_TAG_RE = re.compile(r"\((?:%s)\)" % "|".join(re.escape(t) for t in MINIMAX_TAGS))
_PAUSE_RE = re.compile(r"<#\s*\d+(?:\.\d+)?\s*#>")


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def display_text(raw: str) -> str:
    """把合成用原文清成**上屏字幕文本**：去掉 <#0.8#> 停顿标记与 (sighs) 类语气词标签。
    这两套是给 TTS 的指令、不是台词，漏清就会在大字幕里露出来。"""
    t = _PAUSE_RE.sub("", raw or "")
    t = _TAG_RE.sub("", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def billable_chars(text: str) -> int:
    """MiniMax 计费口径：1 个汉字算 2 字符，其他字符算 1。本地估价用，
    真实账单以服务端回执 usage_characters 为准（_minimax_synth 已打到 stderr）。"""
    return sum(2 if "一" <= ch <= "鿿" else 1 for ch in (text or ""))


def _run(cmd: list[str], what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"{what}失败：{r.stderr[-400:]}")


def _make_silence(seconds: float, out: Path) -> None:
    """anullsrc 生成定长静音，作为行间停顿垫片（方式参考 tts_gen._concat_mp3 的 ffmpeg 用法）。
    直接出 wav：拼接在 wav 域做，见 _to_wav 的说明。"""
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SILENCE_RATE}:cl=mono",
          "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", str(out)], "生成静音")


# 双声响度目标（2026-08-07 老板验收：两个声音音量差太大——实测温暖闺蜜 -31dB vs
# 温润男声 -23.6dB，差 7.5dB）。每行按 mean_volume 归一到统一目标，增益限幅防把底噪泵上来。
TARGET_MEAN_DB = -22.0
GAIN_LIMIT_DB = 12.0


def _mean_volume_db(path: Path) -> float | None:
    """volumedetect 测 mean_volume(dB)，输出在 stderr。"""
    r = subprocess.run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=120)
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", r.stderr)
    return float(m.group(1)) if m else None


def _to_wav(src: Path, dst: Path, gain_db: float = 0.0) -> None:
    """把片段解码成统一规格 wav 再参与拼接（gain_db≠0 时顺带做响度归一）。

    为什么不直接 concat mp3：mp3 每个文件两端都带编码器延迟/补零，拼接重编码时
    这部分被吃掉，于是「各段 ffprobe 时长之和」比拼出来的实际音轨长——实测 4 行就
    差了 0.32s，而且**随行数单调累积**，几十行下来字幕会明显滞后于人声。
    统一转成 pcm wav 后，段长是精确的样本数，累加即全局时间轴，cues 由构造保证准确；
    唯一残留的编码器补零只落在最终 mp3 的末尾，不影响任何一条 cue 的位置。"""
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if abs(gain_db) > 0.05:
        cmd += ["-af", f"volume={gain_db:.1f}dB"]
    cmd += ["-ar", str(SILENCE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst)]
    _run(cmd, f"解码 {src.name}")


def _concat_wav_to_mp3(parts: list[Path], out: Path) -> None:
    """同规格 wav 顺序拼接并一次性编码成 mp3（只编码一次，无级联损失）。"""
    lst = out.with_suffix(".concat.lst")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    try:
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
              "-c:a", "libmp3lame", "-q:a", "2", str(out)], "拼接 podcast.mp3")
    finally:
        lst.unlink(missing_ok=True)


def _fingerprint(line: dict, voice: str, speed: float, emotion: str | None, model: str) -> str:
    """幂等判据写进 line-NN.txt：第一行是原文，第二行是合成参数指纹。
    只比原文不够——改了音色/语速/情绪却复用旧 mp3，会让整期音色不一致且极难排查。"""
    return (f"{line.get('text', '')}\n"
            f"#params voice={voice}|speed={speed}|emotion={emotion}|model={model}\n")


def load_podcast(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        raise RuntimeError("podcast.json 缺 lines 数组（对谈稿至少一行）")
    for i, ln in enumerate(lines):
        sp = ln.get("speaker")
        if sp not in ("F", "M"):
            raise RuntimeError(
                f"第 {i} 行 speaker={sp!r} 非法——对谈只有两个人，只认 \"F\"/\"M\"")
        if not (ln.get("text") or "").strip():
            raise RuntimeError(f"第 {i} 行 text 为空")
    return data


def synth(podcast_path: str, *, workdir: str | None = None,
          voice_f: str = DEFAULT_VOICE_F, voice_m: str = DEFAULT_VOICE_M,
          model: str = tts_gen.MINIMAX_DEFAULT_MODEL, force: bool = False) -> dict:
    """逐行合成 + 垫停顿 + 拼接 + 写实测时间轴。"""
    data = load_podcast(podcast_path)
    lines = data["lines"]
    wd = Path(workdir) if workdir else Path(podcast_path).resolve().parent
    lines_dir = wd / "lines"
    lines_dir.mkdir(parents=True, exist_ok=True)

    creds = tts_gen.resolve_minimax_credentials()
    if not creds["api_key"]:
        raise RuntimeError(
            "缺 MiniMax TTS 凭据 MINIMAX_API_KEY：填进 skill 的 .env，"
            "或跑 setup.py 凭据向导写入用户级 secrets")

    wav_dir = wd / "lines" / ".wav"   # 拼接用中间件，可随时删（下次重建）
    wav_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []            # 待拼接的 wav 片段（行音频 + 停顿静音），按时间顺序
    cues: list[dict] = []
    t = 0.0                           # 拼接后全局时间轴上的累计偏移
    synthesized = skipped = 0
    est_chars = 0
    sil_cache: dict[str, Path] = {}   # 同长度停顿复用同一个静音文件

    for i, ln in enumerate(lines):
        raw = ln["text"].strip()
        voice = voice_f if ln["speaker"] == "F" else voice_m
        speed = float(ln.get("speed") or DEFAULT_SPEED)
        emotion = ln.get("emotion") or None
        mp3 = lines_dir / f"line-{i:02d}.mp3"
        sig = lines_dir / f"line-{i:02d}.txt"
        want = _fingerprint(ln, voice, speed, emotion, model)

        reuse = (not force and mp3.is_file() and mp3.stat().st_size > 0
                 and sig.is_file()
                 and sig.read_text(encoding="utf-8") == want)
        if reuse:
            skipped += 1
            _err(f"[podcast] 行{i:02d} ⏭ 复用已有音频（内容未变，不重复扣费）")
        else:
            _err(f"[podcast] 行{i:02d} 🎙 {ln['speaker']} {voice} speed={speed} …")
            # 直接调 tts_gen 的 minimax 合成：失败原样抛出，绝不自动重试
            tts_gen._minimax_synth(raw, str(mp3), voice, speed, creds["api_key"],
                                   model=model, emotion=emotion,
                                   group_id=creds["group_id"])
            sig.write_text(want, encoding="utf-8")
            synthesized += 1
            est_chars += billable_chars(raw)

        wav = wav_dir / f"line-{i:02d}.wav"
        # 逐行响度归一：不同音色出厂响度差很大（实测双声差 7.5dB），统一拉到 TARGET_MEAN_DB
        mv = _mean_volume_db(mp3)
        gain = 0.0
        if mv is not None:
            gain = max(-GAIN_LIMIT_DB, min(GAIN_LIMIT_DB, TARGET_MEAN_DB - mv))
            if abs(gain) > 0.05:
                _err(f"[podcast] 行{i:02d} 响度 {mv:.1f}dB → 增益 {gain:+.1f}dB")
        _to_wav(mp3, wav, gain_db=gain)
        d = tts_gen.ffprobe_duration(str(wav))
        if d <= 0:
            raise RuntimeError(f"行{i} 音频时长探测为 0，文件可能损坏：{mp3}")
        cues.append({"speaker": ln["speaker"], "text": display_text(raw),
                     "start": round(t, 3), "end": round(t + d, 3)})
        t += d
        parts.append(wav)

        # 行间停顿：最后一行之后不垫——那只会在片尾留一段死气；
        # 片尾的收束交给 record_podcast.py 的 --fade-out。
        pause = float(ln.get("pause_after") if ln.get("pause_after") is not None else DEFAULT_PAUSE)
        if pause > 0 and i < len(lines) - 1:
            key = f"{pause:.3f}"
            sp = sil_cache.get(key)
            if sp is None:
                sp = wav_dir / f"sil-{key}.wav"
                if not sp.is_file():
                    _make_silence(pause, sp)
                sil_cache[key] = sp
            t += tts_gen.ffprobe_duration(str(sp))
            parts.append(sp)

    audio = wd / "podcast.mp3"
    _concat_wav_to_mp3(parts, audio)
    total = tts_gen.ffprobe_duration(str(audio))

    # cues 的时间轴由 wav 样本数累加而来，是精确的；这里只做一次健全性核对：
    # 正常残差只有最终 mp3 末尾那点编码器补零（几十毫秒），超出就说明拼接出了岔子，
    # 宁可大声报出来也不静默出一条字幕全错位的片子。
    if total > 0 and abs(total - t) > 0.15:
        _err(f"[podcast] ⚠ 音轨实测 {total:.3f}s 与时间轴累加 {t:.3f}s 相差 {total - t:+.3f}s，"
             f"超出编码器补零的正常范围，请核对 lines/.wav 下的中间件")

    cues_path = wd / "podcast.cues.json"
    cues_path.write_text(
        json.dumps({"duration": round(total, 3), "cues": cues}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    price = tts_gen.MINIMAX_PRICE_PER_10K.get(model)
    cost = round(est_chars / 10000 * price, 4) if price else None
    return {
        "success": True,
        "audio": str(audio.resolve()),
        "cues": str(cues_path.resolve()),
        "total_duration": round(total, 3),
        "lines": len(lines),
        "synthesized": synthesized,
        "skipped": skipped,
        "estimated_cost_yuan": cost,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="长文播客对谈稿驱动器（MiniMax 双声合成）")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synth", help="逐行合成 + 拼接 + 写时间轴")
    s.add_argument("podcast", help="podcast.json 路径")
    s.add_argument("--workdir", default=None, help="产物目录，默认 podcast.json 同目录")
    s.add_argument("--voice-f", default=DEFAULT_VOICE_F, help=f"女声音色，默认 {DEFAULT_VOICE_F}")
    s.add_argument("--voice-m", default=DEFAULT_VOICE_M, help=f"男声音色，默认 {DEFAULT_VOICE_M}")
    s.add_argument("--model", default=tts_gen.MINIMAX_DEFAULT_MODEL,
                   choices=list(tts_gen.MINIMAX_MODELS))
    s.add_argument("--force", action="store_true",
                   help="忽略已有音频全部重合成（⚠ 重复扣费）")
    a = p.parse_args()

    try:
        res = synth(a.podcast, workdir=a.workdir, voice_f=a.voice_f, voice_m=a.voice_m,
                    model=a.model, force=a.force)
    except Exception as e:  # noqa: BLE001
        res = {"success": False, "error": str(e)}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("success") else 1)


if __name__ == "__main__":
    main()

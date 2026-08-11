#!/usr/bin/env python3
"""ASR 词级时间戳提取（字卡短片 kinetic 模板的词级卡点用）。

用法: python3 extract_word_timings.py <narration.mp3.wav> [out.json]
依赖: pip install --user --break-system-packages faster-whisper（首跑自动下载 small 模型）

⚠️ 三条实战坑（2026-08-11）：
1. 音频源用 tts_gen --timed 产出的 **.wav sidecar**（无损无 encoder delay），别喂 mp3；
2. initial_prompt 必须带「简体中文」引导，否则 whisper 默认输出繁体、下游简体匹配全落空；
   但 prompt ⛔ 含正文原句——否则音频开头会被当 prompt 延续吞掉（实测丢开头 7 词块）；
3. ASR 有错字（帧→针、读→独），下游匹配用「首字+顺序游标」容错，miss 时回退估算值。
"""
import json, sys
from pathlib import Path

def extract(audio: str, out: str | None = None) -> str:
    from faster_whisper import WhisperModel
    m = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = m.transcribe(audio, language="zh", word_timestamps=True,
                           initial_prompt="以下是普通话，简体中文。")
    words = []
    for seg in segs:
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "s": round(float(w.start), 3),
                          "e": round(float(w.end), 3)})
    out = out or str(Path(audio).parent / "word_timings.json")
    Path(out).write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(words)} 词块 → {out}")
    return out

if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

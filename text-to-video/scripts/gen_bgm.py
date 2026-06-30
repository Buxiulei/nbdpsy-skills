#!/usr/bin/env python3
"""自动生成舒缓轻音乐(BGM) —— 纯 Python 合成 + ffmpeg 后处理，零版权零等待。

竖琴/钢琴风拨弦琶音 + 低音 pad，按舒缓和弦进行(默认 C-G-Am-F，卡农式)循环到指定时长，
加空间混响、低通柔化、头尾淡入淡出。产物喂给 compose_video.py 的 manifest.bgm。
比手搓的无旋律正弦 pad 有旋律有层次，适合心理科普/治愈系短视频垫底。

合成原理：每个音符 = 基频 + 谐波叠加 + 指数衰减包络(模拟拨弦)，极快 attack 去爆音；
和弦进行循环，琶音音符在和弦时长内依次拨响并连绵交叠；最后归一化写 16bit PCM wav，
再用 ffmpeg 加混响/低通/淡入淡出转 mp3。

用法：
  python gen_bgm.py --duration 60 --out bgm.mp3
  python gen_bgm.py --duration 60 --out bgm.mp3 --mood calm --chord-dur 3.2
"""
from __future__ import annotations

import argparse
import array
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

SR = 44100
# 音名 → 相对 A4 的半音数
_SEMI = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}

# 舒缓和弦进行库：(低音根音, [琶音音符序列])。默认 calm = C-G-Am-F(卡农式，平静治愈)
PROGRESSIONS = {
    "calm": [
        ("C3", ["C4", "E4", "G4", "C5", "G4", "E4"]),
        ("G2", ["G3", "B3", "D4", "G4", "D4", "B3"]),
        ("A2", ["A3", "C4", "E4", "A4", "E4", "C4"]),
        ("F2", ["F3", "A3", "C4", "F4", "C4", "A3"]),
    ],
    # warm = F-C-G-Am，更温暖一点
    "warm": [
        ("F2", ["F3", "A3", "C4", "F4", "C4", "A3"]),
        ("C3", ["C4", "E4", "G4", "C5", "G4", "E4"]),
        ("G2", ["G3", "B3", "D4", "G4", "D4", "B3"]),
        ("A2", ["A3", "C4", "E4", "A4", "E4", "C4"]),
    ],
}


def _freq(name: str) -> float:
    """音名(如 C4/A2)→频率 Hz。"""
    octave = int(name[-1])
    semis = _SEMI[name[:-1]] + (octave - 4) * 12
    return 440.0 * 2 ** (semis / 12)


def _pluck(freq: float, dur: float, amp: float = 0.5) -> list[float]:
    """单个拨弦音：基频+谐波，指数衰减包络 + 极快 attack(去爆音)。"""
    n = int(dur * SR)
    harm = [(1, 1.0), (2, 0.45), (3, 0.2), (4, 0.1)]
    tau = max(0.25, dur * 0.5)
    twopi = 2 * math.pi
    buf = [0.0] * n
    for i in range(n):
        t = i / SR
        env = math.exp(-t / tau) * (1 - math.exp(-t / 0.008))
        s = 0.0
        for h, ha in harm:
            s += ha * math.sin(twopi * freq * h * t)
        buf[i] = amp * env * s
    return buf


def synth(duration: float, mood: str = "calm", chord_dur: float = 3.2) -> list[float]:
    """按和弦进行合成到 duration 秒，返回归一化 float 样本。"""
    prog = PROGRESSIONS.get(mood, PROGRESSIONS["calm"])
    total = int(duration * SR)
    mix = [0.0] * total

    def add(buf: list[float], start: int) -> None:
        for i, v in enumerate(buf):
            j = start + i
            if 0 <= j < total:
                mix[j] += v

    t, ci = 0.0, 0
    while t < duration:
        root, arp = prog[ci % len(prog)]
        # 低音根音：长衰减，给和弦厚度
        add(_pluck(_freq(root), chord_dur * 1.1, amp=0.35), int(t * SR))
        # 琶音：音符均匀铺在和弦时长内，衰减较长形成连绵交叠
        step = chord_dur / len(arp)
        for k, note in enumerate(arp):
            add(_pluck(_freq(note), chord_dur - step * k * 0.5 + 0.8, amp=0.28),
                int((t + k * step) * SR))
        t += chord_dur
        ci += 1

    peak = max(1e-6, max(abs(v) for v in mix))
    scale = 0.85 / peak
    return [v * scale for v in mix]


def write_wav(samples: list[float], path: str) -> None:
    """float[-1,1] → 16bit 单声道 PCM wav。"""
    arr = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in samples))
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(arr.tobytes())


def generate(duration: float, out: str, *, mood: str = "calm", chord_dur: float = 3.2) -> dict:
    samples = synth(duration + 2.0, mood, chord_dur)  # 多合成 2s，给淡出留尾
    tmp = tempfile.mktemp(suffix=".wav")
    write_wav(samples, tmp)
    fade_out_st = max(0.0, duration - 4.0)
    # 混响(空间感) + 低通(保留泛音的柔化) + 头尾淡入淡出
    af = (f"aecho=0.8:0.85:600|1100:0.3|0.2,lowpass=f=3200,"
          f"afade=t=in:d=3,afade=t=out:st={fade_out_st:.1f}:d=4")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", tmp, "-af", af, "-t", f"{duration}",
         "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-q:a", "2", out],
        capture_output=True, text=True, timeout=300)
    Path(tmp).unlink(missing_ok=True)
    if r.returncode != 0:
        return {"success": False, "error": (r.stderr or "")[-500:]}
    return {"success": True, "output": str(Path(out).resolve()),
            "duration": duration, "mood": mood}


def main() -> None:
    ap = argparse.ArgumentParser(description="自动生成舒缓轻音乐 BGM(纯 Python + ffmpeg)")
    ap.add_argument("--duration", type=float, required=True, help="时长(秒)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mood", default="calm", choices=sorted(PROGRESSIONS.keys()))
    ap.add_argument("--chord-dur", type=float, default=3.2, help="每个和弦时长(秒)")
    a = ap.parse_args()
    res = generate(a.duration, a.out, mood=a.mood, chord_dur=a.chord_dur)
    if res.get("success"):
        print(f"✅ BGM 生成: {res['output']} ({a.duration}s, mood={a.mood})")
    else:
        print(f"❌ {res.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

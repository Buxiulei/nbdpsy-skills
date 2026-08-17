#!/usr/bin/env python3
"""母带响度归一 —— **全形态共享实现，唯一真源**。

## 为什么必须只有一份

2026-08-16 老板实听首片轮播放映片，反馈**「背景音太小」**。根因不是 BGM 压过头，
是整条链路**没有任何一处管绝对响度**：TTS 原始电平 −31.6 LUFS，比平台常态低 15 dB 以上；
BGM 按「口播 − duck」算相对值，口播本身安静，BGM 就更安静（实测 −49.6 LUFS，等于没有）。

当天的修复**只做在 `slideshow_video.py`（轮播放映线）一处**。2026-08-17 体检发现另外三条
出口——`compose_video.py`（笔记微电影，SKILL.md 的默认主线形态）、`record_podcast.py`（播客
视频）、`render_card.py`（字卡短片）——全都还是老的相对响度结构，老板用默认形态出片必然
重现同一个投诉。**「一处修了另几处没修」就是这次事故的形状**，所以实现抽到这里，
⛔ 任何合成出口都不许再抄一份自己的 loudnorm。

## 口径真源

数值口径见 `references/audio-checklist.md`（那份是声音验收的唯一真源，本文件是它的代码落法）：

- **A1 母带 integrated −16 LUFS ±1**
- **A2 真峰 ≤ −1.5 dBTP**（成片实测容差 0.3，留给 AAC 编码）
- **A3 48 kHz / 双声道 / AAC**
- 两遍法：第一遍只分析拿 `measured_*`，第二遍带着测量值线性归一
- BGM 相对口播 −12 ~ −18 LU（**相对量**，与母带**绝对量**是两件事，缺一把尺子就会漏掉这类问题）

## 形态分档（2026-08-17 调研裁决：全部 −16，不分档）

播客视频时长几十分钟，一度怀疑该走播客口径（−19）。调研结论是**不该分**：

- Apple Podcasts 官方播客指标本身就是 **−16 LUFS ±1 / TP ≤ −1 dBFS**（依 ITU-R BS.1770）；
  Spotify 对播客与音乐**统一 −14**（常被引用的 −19 是听众端「安静」播放档偏好，不是制作目标）。
- AES TD1004 给流媒体的区间是 **−20 ~ −16 LUFS**，−16 是上界、不是短视频专属值。
- **没有任何一份规范按「内容时长」分档**，只按平台/媒介分档。而本产线的播客视频是以 MP4
  投到视频平台（视频号/B站/小红书）的，就该跟视频渠道走。

⇒ `FORM_TARGETS` 保留分档的**位置**（哪天真要分，改这一处即可），但当前四个形态同值 −16。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# 母带口径（audio-checklist.md 第一节 A1/A2/A3）
MASTER_LUFS = -16.0     # integrated 目标
MASTER_TP = -1.5        # 真峰上限 dBTP
LUFS_TOLERANCE = 1.0    # ±1 LU
TP_TOLERANCE = 0.3      # 成片实测容差，留给 AAC 编码
SR = 48000              # loudnorm 内部按 192 kHz 工作，输出必须显式指定采样率
BITRATE = "192k"

BGM_DUCK_LU = 14.0
"""BGM 压到口播之下多少 LU（**相对量**，与母带的绝对量是两件事）。

🩸 **这个数是老板 2026-08-16 对着成片实听调出来的**（从 18 调到 14），不是算出来的。
⛔ 改它必须重新实听，别凭「听起来应该」拧。范围 12（音乐要被听见，情绪片/片头片尾）
~ 18（纯气氛垫底，信息密度高的讲解片）。

⚠️ 2026-08-17 统一到这里的原因：此前轮播线用 14、微电影线用 12，**同一个老板会听到一响
一不响的两个形态**，下次听微电影必然重现同一个投诉。上一次事故的形状就是「修复只落在
他点名的那个形态上」，两个默认值分开写就是让它再发生一次。"""

# 形态分档位（当前全部同值，理由见模块 docstring）
FORM_TARGETS: dict[str, float] = {
    "slideshow": MASTER_LUFS,   # 轮播放映
    "microfilm": MASTER_LUFS,   # 笔记微电影（compose_video 通用竖屏线）
    "card": MASTER_LUFS,        # 字卡短片
    "podcast": MASTER_LUFS,     # 播客视频（几十分钟，但投视频平台 ⇒ 跟视频口径）
}


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def _run(cmd: list[str], *, timeout: int = 1800) -> subprocess.CompletedProcess:
    """跑外部命令，失败即抛（带 stderr 尾巴）。⛔ 不吞错误码：
    本仓多次事故是「管道吞退出码 / 失败静默继续」，成片出来了但内容是错的。"""
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"命令失败（exit {p.returncode}）：{' '.join(cmd[:6])} …\n"
                           f"{(p.stderr or '')[-1200:]}")
    return p


# ---------- 量具 ----------

def loudness_stats(path: str | Path, *, target: float = MASTER_LUFS) -> dict:
    """loudnorm 第一遍（分析口）：拿 integrated LUFS / true peak / LRA / 门限 / 偏移。

    ⚠️ 认 LUFS 不认 RMS：LUFS 带 K 计权 + 门控（跳过字间静音），RMS 两样都没有，
    同一条片子两把尺子能差出 7 dB，拿 RMS 判「BGM 压够没有」必然误判（见 audio-checklist.md）。
    """
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"loudnorm=I={target}:TP={MASTER_TP}:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=900)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr or "", re.S)
    if not m:
        raise RuntimeError(f"读不到 {path} 的响度（loudnorm 分析没出 JSON）："
                           f"{(p.stderr or '')[-500:]}")
    raw = json.loads(m[-1])

    def num(key: str, fallback: float) -> float:
        """-inf / nan（全静音、超短素材）不能回传给第二遍 loudnorm，会让 ffmpeg 拒参数。"""
        try:
            v = float(raw.get(key))
        except (TypeError, ValueError):
            return fallback
        return v if v == v and abs(v) != float("inf") else fallback

    return {
        "i": num("input_i", -70.0),
        "tp": num("input_tp", -99.0),
        "lra": num("input_lra", 0.0),
        "thresh": num("input_thresh", -80.0),
        "offset": num("target_offset", 0.0),
    }


def loudness(path: str | Path) -> float:
    return loudness_stats(path)["i"]


def loudnorm_filter(pre: dict, *, target: float, tp: float = MASTER_TP) -> str:
    """第二遍（归一口）的 loudnorm 滤镜串：带上第一遍测得的 `measured_*` 做**线性**归一。

    ⛔ 不能一遍过：单遍 loudnorm 是**流式自适应**的，前几秒还没测准就开始改增益，
    片头响度会飘。`linear=true` 保证全片同一个增益，动态/LRA 不被压。
    """
    return (f"loudnorm=I={target:.2f}:TP={tp}:LRA=11:"
            f"measured_I={pre['i']:.2f}:measured_TP={pre['tp']:.2f}:"
            f"measured_LRA={pre['lra']:.2f}:measured_thresh={pre['thresh']:.2f}:"
            f"offset={pre['offset']:.2f}:linear=true")


# ---------- BGM 相对压低（与母带归一是两件事） ----------

def prepare_bgm(bgm: str, total: float, tmp: Path, *, narration_lufs: float,
                duck_db: float) -> tuple[Path, float]:
    """BGM 归一化 + 压到口播之下 duck_db，返回 (已归一的单声道 wav, 实测 LUFS)。

    `--bgm auto` 走同目录 gen_bgm.py **纯合成**（无版权风险、无外部素材）。
    ⛔ 绝不下载来路不明的音乐：一条商用短视频背一首侵权 BGM，赔的钱比整条产线省的多。

    注意这里定的是**相对差**（口播 − duck_db），绝对响度由母带归一统一负责。
    duck 调不动「整片都小声」——那是母带的事，别在这里加补偿增益（会连口播一起顶到削波）。
    """
    if bgm == "auto":
        src = tmp / "bgm_auto.mp3"
        _run([sys.executable, str(Path(__file__).resolve().parent / "gen_bgm.py"),
              "--duration", f"{total:.2f}", "--out", str(src)], timeout=1800)
    else:
        src = Path(bgm)
        if not src.is_file():
            raise RuntimeError(f"BGM 文件不存在：{src}")
    target = narration_lufs - duck_db
    out = tmp / "bgm_ready.wav"
    # 🩸 **先下混到单声道，再分析、再归一**——分析域必须等于输出域。
    # 2026-08-16 实测：在立体声源上分析、输出时才 `-ac 1`，成品比目标**低 3 dB**
    # （目标 −45.9，实测 −48.9）。宽立体声下混 (L+R)/2 时不相关成分相消，能量掉 ~3 dB，
    # 而口播本来就是单声道、没有这一刀 ⇒ duck 写 14 实际压了 17，BGM 白白又轻 3 dB。
    # 这类偏差不会报错、成片能播，只有回读实测才抓得到（所以下面一定要回读）。
    mono = tmp / "bgm_mono.wav"
    # -stream_loop 兜 BGM 短于成片的情况；-t 截到成片长度。
    _run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src),
          "-t", f"{total:.3f}", "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(mono)])
    # 两遍法：单遍 loudnorm 是流式自适应的，开头还没测准就在改增益。
    pre = loudness_stats(mono, target=target)
    fade_out = max(0.0, total - 1.5)   # 两端 1.5s 淡入淡出，在归一之后做
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(mono),
          "-af", loudnorm_filter(pre, target=target, tp=-2.0) +
                 f",afade=t=in:d=1.5,afade=t=out:st={fade_out:.2f}:d=1.5",
          "-ar", str(SR), "-ac", "1", str(out)])
    # 实测回读：报「目标多少」没用，得报「实际到了多少」。两端淡化会把 integrated 拉低一点点
    # （1.5s×2 相对全片的占比），所以这里的实测值天然略低于目标，看的是**别差到 1 LU 以上**。
    got = loudness_stats(out, target=target)["i"]
    _err(f"[bgm] 口播 {narration_lufs:.1f} LUFS → BGM 目标 {target:.1f}（低 {duck_db:.0f} LU）"
         f"，实测 {got:.1f} LUFS ⇒ 实际压差 {narration_lufs - got:.1f} LU")
    if abs(got - target) > 1.0:
        raise RuntimeError(
            f"BGM 归一没打准：目标 {target:.2f} LUFS，实测 {got:.2f} LUFS（差 {got - target:+.2f} LU）\n"
            f"⛔ 拒跑——差 1 LU 以上说明归一链路有隐性损失（历史元凶：分析域是立体声、"
            f"输出却 -ac 1，下混白丢 3 dB）。别改这个阈值绕过去，去查链路。")
    return out, got


# ---------- 母带归一 ----------

SILENCE_FLOOR = -50.0
"""比这还静就不归一：分析口对全静音回落 −70，照此归一等于给底噪 +54 dB。"""


def master_audio(src: str | Path, dst: str | Path, *, target: float = MASTER_LUFS,
                 channels: int = 2, bitrate: str = BITRATE) -> dict:
    """纯音轨母带归一 → AAC。返回响度凭证。

    两遍法（⛔ 不能一遍过，理由见 `loudnorm_filter`）。
    `-ar` 必须显式给：loudnorm 内部按 192 kHz 工作，不指定会把成片音轨变成 192k。
    """
    pre = loudness_stats(src, target=target)
    _err(f"[master] 混音后 {pre['i']:.2f} LUFS / 真峰 {pre['tp']:.2f} dBTP "
         f"→ 归一到 {target:g} LUFS（提 {target - pre['i']:+.1f} dB）")
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
          "-af", loudnorm_filter(pre, target=target),
          "-ar", str(SR), "-ac", str(channels), "-c:a", "aac", "-b:a", bitrate, str(dst)])
    return {"target_lufs": target, "pre_master": pre,
            "gain_db": round(target - pre["i"], 2)}


def master_video(src: str | Path, dst: str | Path, *, target: float = MASTER_LUFS,
                 channels: int = 2, bitrate: str = BITRATE) -> dict:
    """带画面的成片母带归一：画面 `-c:v copy` 原样过，只重编音轨。

    近似全静音时**跳过归一那一步并告警**（返回 `skipped` 字段），⛔ 不静默：
    照 −70 的回落值归一等于把底噪抬 54 dB，比不归一还糟。
    ⚠️ 跳过的只是 loudnorm，**片子照出**——否则调用方拿不到成片，会退化成一个假的「合成失败」。
    """
    pre = loudness_stats(src, target=target)
    silent = pre["i"] <= SILENCE_FLOOR
    if silent:
        _err(f"[master] ⚠️ 音轨近乎全静音（实测 {pre['i']:.2f} LUFS ≤ {SILENCE_FLOOR:g}），"
             f"**跳过母带归一**——照此归一等于给底噪 +{target - pre['i']:.0f} dB。请查音轨是否丢了。")
    else:
        _err(f"[master] 混音后 {pre['i']:.2f} LUFS / 真峰 {pre['tp']:.2f} dBTP "
             f"→ 归一到 {target:g} LUFS（提 {target - pre['i']:+.1f} dB）")
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c:v", "copy"]
         + ([] if silent else ["-af", loudnorm_filter(pre, target=target)])
         + ["-ar", str(SR), "-ac", str(channels), "-c:a", "aac", "-b:a", bitrate,
            "-movflags", "+faststart", str(dst)])
    return {"target_lufs": target, "pre_master": pre,
            "gain_db": 0.0 if silent else round(target - pre["i"], 2),
            **({"skipped": "silent"} if silent else {})}


# ---------- 收尾自检 ----------

def verify_master(out: str | Path, *, target: float = MASTER_LUFS) -> dict:
    """在**成片**上回读母带响度与真峰（端到端，不是量中间文件报个好看的数）。

    这同时是归一那段代码的**证伪闸门**——归一没生效，这里立刻红。
    返回 `{"passed", "checks": [(标签, 是否通过, 不过会怎样)], ...}`，
    是否 exit 1 由调用方按各自的自检风格决定。
    """
    final = loudness_stats(out, target=target)
    checks: list[tuple[str, bool, str]] = [
        (f"母带响度 {final['i']:.2f} LUFS（目标 {target:g}±{LUFS_TOLERANCE:g}）",
         abs(final["i"] - target) <= LUFS_TOLERANCE,
         "整片响度偏离目标——平台常态 −14~−16 LUFS，低太多就是「手机外放听不清」"),
        (f"真峰 {final['tp']:.2f} dBTP（应 ≤ {MASTER_TP:g}，容差 {TP_TOLERANCE:g} 留给 AAC 编码）",
         final["tp"] <= MASTER_TP + TP_TOLERANCE,
         "真峰过高，转码/平台二次压缩时会削波爆音"),
    ]
    return {"passed": all(c[1] for c in checks), "checks": checks,
            "measured_lufs": round(final["i"], 2), "measured_tp": round(final["tp"], 2),
            "measured_lra": round(final["lra"], 2), "target_lufs": target}

#!/usr/bin/env python3
"""轮播放映视频（第四内容形态 tpl-slideshow）—— 把已产出的小红书轮播图当 PPT 逐张放映，
配口播串联 + 可选 BGM，一条命令出 3:4 竖版 MP4。

定位：轮播图已经把话讲完了（R4「图内自足」），本产线**不重新讲内容**，只做分发形态转换——
口播讲故事线、解释每张图里的小块含义，画面就是原图逐张放映。跑通后所有存量轮播都能低成本转视频。

⛔ **上游闸门**：R4 不达标（没有论点行 / 图讲不清楚）的轮播不得进本产线——
   图讲不清楚，口播救不回来，只会做出一条「配音的糊涂图」。

## 三条设计铁律（每条都对应一次本仓踩过的坑）

1. **🩸 wav 域拼接**：每页放映时长 = 该页口播的**实测样本数 / 采样率**，多页音频按**样本数**在
   PCM 域拼接，绝不逐段拼 mp3（mp3 每段漂 ~46ms 且随段数累积，8 段实测累计 0.41s；
   2026-08-11 字卡线、2026-08-07 播客线两次同因事故）。
   检验法：成片实长 vs 各段累计时长差 > 0.1s ＝拼接路径有漂移，别用。
   本脚本收尾自检（`_verify`）会自己跑这条检验并在超差时**退出码 1**。
2. **零裁切**：信息图裁掉一条边就是裁掉一行字。画面一律 contain 贴合，
   Ken Burns 的缩放上界 = 贴合框本身（见 `_page_canvas` 的 1+kb 超尺寸画布法），
   全程任何时刻都不会有像素被推出画外。⛔ 不要为了「满屏」改成 cover 裁切。
3. **口播段数 == 页数**，不一致直接拒跑并报出缺哪页——半自动对齐（多的那段悄悄丢掉、
   少的那页悄悄留白）是最难发现的错，因为成片能播。

## 输入两选一

- `--narration-dir`：每页一段音频（wav 优先，mp3 也收——收进来先解码成 PCM 再拼，
  「解码 mp3」不是坑，「拼接 mp3」才是）。文件名序 = 页序。
- `--script-file`：分页口播稿，内部逐页调 MiniMax TTS（⚠️ **串行**，限流纪律）。
  格式见 `_parse_script`。TTS 产物带**指纹缓存**：稿子/音色/语速/模型任一变化即重合成，
  没变则复用（省钱）。本仓旧缓存「无指纹、改稿不重出」的坑在这里堵死。

## 用法

```bash
# A) 已有口播音频
python3 slideshow_video.py --images-dir imgs/ --narration-dir narr/ --out slideshow.mp4

# B) 只有口播稿，脚本内部跑 TTS（串行）
python3 slideshow_video.py --images-dir imgs/ --script-file narration.md \
    --engine minimax --voice "Chinese (Mandarin)_Warm_Bestie" --out slideshow.mp4

# C) 加自产 BGM（gen_bgm.py 纯合成，零版权）；--bgm 也可直接给音频文件路径
python3 slideshow_video.py --images-dir imgs/ --script-file narration.md --bgm auto --out slideshow.mp4

# D) 只校验不出片（页数/口播段数/时长预算），不花 TTS 的钱
python3 slideshow_video.py --images-dir imgs/ --script-file narration.md --out x.mp4 --dry-run
```

首版**不加字幕**（老板 2026-08-14 定：字幕会挡住信息图本身的字）。本脚本不生成任何字幕轨，
自检会断言成片里只有 1 路视频 + 1 路音频。要加字幕是**改形态**，不是加个参数。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac"}
# 口播主时钟采样率：全部素材统一重采样到这里，再按样本数拼接。
# 48k 是 AAC 原生率，避免最后混音再变一次率。
SR = 48000
DEFAULT_CANVAS = "1080x1440"          # 3:4，与小红书轮播图原生比例同族
DEFAULT_VOICE = "Chinese (Mandarin)_Warm_Bestie"  # 温暖闺蜜，现役口播音色
# 成片时长与口播累计时长的容差（秒）。0.1 是本仓 wav 域拼接的验收口径，别放宽。
DRIFT_TOLERANCE = 0.10


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


def ffprobe_duration(path: str | Path) -> float:
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(path)], timeout=120)
    return float((p.stdout or "0").strip())


def ffprobe_streams(path: str | Path) -> list[dict]:
    p = _run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)], timeout=120)
    return json.loads(p.stdout).get("streams", [])


# ---------- 输入收集与配对校验 ----------

def _page_num(name: str) -> int | None:
    """从文件名里抽页码（P01.jpg / 01-xxx.wav / page3.mp3 → 1/1/3）。
    抽不出返回 None——抽不出就退回「排序序」配对，但两边都抽得出时**必须**对得上。"""
    m = re.search(r"(\d+)", Path(name).stem)
    return int(m.group(1)) if m else None


def collect_images(d: Path) -> list[Path]:
    files = sorted([p for p in d.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_EXTS],
                   key=lambda p: p.name)
    if not files:
        raise RuntimeError(f"{d} 里没有图片（认 {'/'.join(sorted(IMAGE_EXTS))}）")
    # 🩸 同名双格式陷阱（小红书发图线实证）：P01.jpg 与 P01.png 并存会被当成两页放两遍。
    by_num: dict[int, list[Path]] = {}
    for p in files:
        n = _page_num(p.name)
        if n is not None:
            by_num.setdefault(n, []).append(p)
    dup = {n: [p.name for p in v] for n, v in by_num.items() if len(v) > 1}
    if dup:
        raise RuntimeError(
            f"图片目录里同一页码有多个文件（同名双格式会被放映两遍）：{dup}\n"
            f"请只保留一种格式再跑")
    return files


def collect_audios(d: Path) -> list[Path]:
    files = sorted([p for p in d.iterdir()
                    if p.is_file() and p.suffix.lower() in AUDIO_EXTS
                    and not p.name.endswith(".cues.json")],
                   key=lambda p: p.name)
    if not files:
        raise RuntimeError(f"{d} 里没有音频（认 {'/'.join(sorted(AUDIO_EXTS))}）")
    return files


def pair_pages(images: list[Path], audios: list[Path]) -> None:
    """页数 / 口播段数一致性校验。不一致 → 抛错并**报出具体是哪页**。"""
    if len(images) != len(audios):
        inums = [_page_num(p.name) for p in images]
        anums = [_page_num(p.name) for p in audios]
        detail = ""
        if all(n is not None for n in inums) and all(n is not None for n in anums):
            miss = sorted(set(inums) - set(anums))
            extra = sorted(set(anums) - set(inums))
            if miss:
                detail += f"\n  缺口播的页：{miss}（图有、音频没有）"
            if extra:
                detail += f"\n  多出来的口播段：{extra}（音频有、图没有）"
        raise RuntimeError(
            f"页数与口播段数不一致：图 {len(images)} 页、口播 {len(audios)} 段。{detail}\n"
            f"  图：{[p.name for p in images]}\n"
            f"  音：{[p.name for p in audios]}\n"
            f"⛔ 拒跑——数量对不上时自动对齐只会做出一条『能播但讲错页』的片子")
    inums = [_page_num(p.name) for p in images]
    anums = [_page_num(p.name) for p in audios]
    if all(n is not None for n in inums) and all(n is not None for n in anums):
        if inums != anums:
            raise RuntimeError(
                f"页码顺序对不上（按文件名排序后）：图 {inums} vs 口播 {anums}\n"
                f"⛔ 拒跑——请把文件名页码补齐对齐（如 P01.jpg ↔ P01.wav）")


# ---------- 口播稿解析与 TTS ----------

def _parse_script(path: Path) -> list[str]:
    """分页口播稿 → 每页一段文本。

    Markdown 格式（推荐）：**标题文字以页码打头**才算开一页——`## P1` / `## 第1页` /
    `## 1. 封面` 都认，页码后面可以跟标签。⚠️ 只认页码打头，是为了让文档标题
    （`# H1 过度换气九页`）、说明段、免责声明这些**不被当成页**——按「所有 `##` 都是页」
    解析过一版，文档标题直接多算出一页，报「10 页 vs 9 图」把人引去查图。
        # 这是文档标题，会被忽略
        ## P1
        正文……
        ## P2
        正文……
    JSON 格式（.json 后缀）：`["第一页文本", ...]` 或 `[{"page":1,"text":"..."}, ...]`。
    """
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not data:
            raise RuntimeError(f"{path} 应为非空数组")
        out = []
        for i, it in enumerate(data):
            t = it if isinstance(it, str) else (it or {}).get("text", "")
            if not (t or "").strip():
                raise RuntimeError(f"{path} 第 {i + 1} 段口播文本为空")
            out.append(t.strip())
        return out

    pages: list[list[str]] = []
    header = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
    page_head = re.compile(r"^(?:[Pp]|第)?\s*\d+")
    saw_header = False
    for line in path.read_text(encoding="utf-8").splitlines():
        m = header.match(line)
        if m:
            saw_header = True
            if page_head.match(m.group(1).strip()):
                pages.append([])
            continue
        if pages:
            pages[-1].append(line)
    if not pages:
        raise RuntimeError(
            f"{path} 里没找到任何页标题。页标题必须以页码打头，如 `## P1` / `## 第1页` / `## 1`"
            + ("（文件里有标题，但没有一个是页码打头的）" if saw_header else "")
            + "——口播稿必须逐页分节，否则脚本无法知道哪句话配哪张图")
    texts = []
    for i, buf in enumerate(pages):
        t = "\n".join(buf).strip()
        t = re.sub(r"\n{2,}", "\n", t)
        if not t:
            raise RuntimeError(f"{path} 第 {i + 1} 节（页）正文为空")
        texts.append(t)
    return texts


def _tts_fingerprint(text: str, engine: str, voice: str, speed: float, model: str) -> str:
    """稿子/音色/语速/模型的指纹。任一变化即重合成——
    本仓旧缓存「无指纹、改稿不重出」踩过：改完稿子出来的还是老声音，且完全无提示。"""
    raw = json.dumps([text, engine, voice, speed, model], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tts_pages(texts: list[str], out_dir: Path, *, engine: str, voice: str,
              speed: float, model: str, gap: float) -> list[Path]:
    """逐页合成口播，返回每页的 **wav** 路径（tts_gen 的无损 sidecar）。
    ⚠️ 严格串行：MiniMax 有并发限流，多段并发会被限流；且 TTS 按字符计费，
    失败重试＝重复扣费，所以本函数不做任何自动重试，失败即抛。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tts_gen

    out_dir.mkdir(parents=True, exist_ok=True)
    wavs: list[Path] = []
    for i, text in enumerate(texts, 1):
        stem = f"P{i:02d}"
        mp3 = out_dir / f"{stem}.mp3"
        wav = out_dir / f"{stem}.mp3.wav"          # tts_gen gen_timed 的无损 sidecar
        fp_file = out_dir / f"{stem}.fingerprint.json"
        fp = _tts_fingerprint(text, engine, voice, speed, model)
        if wav.is_file() and fp_file.is_file():
            try:
                if json.loads(fp_file.read_text(encoding="utf-8")).get("fingerprint") == fp:
                    _err(f"[tts] {stem} 命中缓存（指纹一致，不重复计费）")
                    wavs.append(wav)
                    continue
            except Exception:  # noqa: BLE001  缓存文件坏了就当没有，重合成
                pass
        _err(f"[tts] {stem} 合成中…（{len(text)} 字）")
        r = tts_gen.gen_timed(text, str(mp3), engine=engine, voice=voice,
                              speed=speed, model=model, gap=gap)
        if not r.get("success"):
            raise RuntimeError(f"{stem} 口播合成失败：{r.get('error')}"
                               f"（⛔ 不自动重试：TTS 按字符计费，重试＝重复扣费）")
        if not wav.is_file():
            raise RuntimeError(f"{stem} 缺 wav sidecar {wav}——"
                               f"tts_gen 必须是 2026-08-11 之后的 wav 域拼接版本")
        fp_file.write_text(json.dumps({"fingerprint": fp, "chars": len(text)},
                                      ensure_ascii=False), encoding="utf-8")
        wavs.append(wav)
    return wavs


# ---------- 音频：wav 域拼接（本产线的命门） ----------

def _decode_pcm(src: Path, tmp: Path) -> bytes:
    """任意音频 → 统一 SR/单声道/s16 的裸 PCM。
    mp3 源在这里**解码**成 PCM 是安全的；危险的是拿 mp3 直接首尾相接（每段带 encoder delay）。"""
    wav_path = tmp / (src.name + ".norm.wav")
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
          "-ar", str(SR), "-ac", "1", "-sample_fmt", "s16", str(wav_path)])
    with wave.open(str(wav_path), "rb") as w:
        return w.readframes(w.getnframes())


def build_narration(page_wavs: list[Path], out_wav: Path, tmp: Path, *,
                    head: float, gap: float, tail: float) -> list[dict]:
    """按**样本数**拼接各页口播，返回每页的放映窗口（秒 + 样本）。

    时间线（head/gap/tail 都算进它前面那一页的放映时长，所以页面在停顿期间仍然在屏上）：
        [head 静音][P1 口播][gap][P2 口播][gap]…[Pn 口播][tail 静音]
        P1 放映 = head + dur1 + gap
        Pi 放映 = duri + gap          (1 < i < n)
        Pn 放映 = durn + tail
    """
    n = len(page_wavs)
    head_f, gap_f, tail_f = (int(round(x * SR)) for x in (head, gap, tail))
    silence = b"\x00\x00"

    chunks: list[bytes] = []
    pages: list[dict] = []
    cursor = 0

    if head_f:
        chunks.append(silence * head_f)
        cursor += head_f
    for i, w in enumerate(page_wavs):
        pcm = _decode_pcm(w, tmp)
        frames = len(pcm) // 2
        if frames == 0:
            raise RuntimeError(f"{w} 解码后是空音频（0 采样）")
        start = cursor - (head_f if i == 0 else 0)   # 第 1 页的放映窗口从 0 开始（含 head）
        chunks.append(pcm)
        cursor += frames
        pad = tail_f if i == n - 1 else gap_f
        if pad:
            chunks.append(silence * pad)
            cursor += pad
        pages.append({
            "index": i + 1,
            "narration_wav": str(w),
            "speech_frames": frames,
            "speech_sec": round(frames / SR, 4),
            "start_frame": start,
            "display_frames": cursor - start,
            "display_sec": round((cursor - start) / SR, 4),
        })

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        for c in chunks:
            w.writeframes(c)
    return pages


# ---------- 画面 ----------

def _page_canvas(src: Path, dst: Path, *, cw: int, ch: int, kb: float, prescale: int) -> None:
    """把一页图铺到「超尺寸画布」上，供 zoompan 做零裁切 Ken Burns。

    画布尺寸 = 画面 ×(1+kb)×prescale；图按 contain 贴进中央的 画面×prescale 框；
    四周由同图的模糊放大版填充（信息图多是暖米底，模糊填充读起来就是一圈柔和的同色边）。

    为什么要「超尺寸」：zoompan 的 zoom 只能 ≥1（只能往里推），直接对贴合图 zoom-in
    必然把边缘推出画外——信息图裁掉一条边就是裁掉一行字。做大一圈之后，
    z 从 1 走到 1+kb 对应图从 1/(1+kb) 长到 1.0，**上界正好是贴合框**，全程零裁切。
    """
    ow, oh = round(cw * (1 + kb) * prescale), round(ch * (1 + kb) * prescale)
    fw, fh = cw * prescale, ch * prescale
    # 背景：先缩到小图再模糊再放大——同样的观感，比在大图上直接 gblur 快一个量级
    bw, bh = max(2, cw // 4), max(2, ch // 4)
    vf = (
        f"[0:v]scale={bw}:{bh}:force_original_aspect_ratio=increase,"
        f"crop={bw}:{bh},gblur=sigma=16,eq=brightness=-0.04:saturation=0.75,"
        f"scale={ow}:{oh}:flags=bicubic[bg];"
        f"[0:v]scale={fw}:{fh}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
          "-filter_complex", vf, "-frames:v", "1", str(dst)])


def _zoom_expr(i: int, frames: int, kb: float) -> str:
    """Ken Burns 缩放表达式。**确定性**：方向按页序奇偶交替，⛔ 不用随机
    （重渲染必须逐帧一致，这是本仓渲染契约）。用 `on`（输出帧号）直接算绝对值，
    不用 `zoom+0.001` 这种累加式——累加会因逐帧取整而漂，端点也落不准。"""
    if kb <= 0 or frames <= 1:
        return "1"
    span = frames - 1
    if i % 2 == 0:   # 偶数页（P1/P3/…，i 从 0 数）缓推近
        return f"1+{kb:.6f}*on/{span}"
    return f"{1 + kb:.6f}-{kb:.6f}*on/{span}"   # 奇数页缓拉远


def render_segment(canvas: Path, dst: Path, *, frames: int, fps: int,
                   cw: int, ch: int, kb: float, index: int) -> None:
    z = _zoom_expr(index, frames, kb)
    vf = (f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":s={cw}x{ch}:fps={fps},format=yuv420p")
    _run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(fps),
          "-i", str(canvas), "-vf", vf, "-frames:v", str(frames),
          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
          "-pix_fmt", "yuv420p", "-r", str(fps), str(dst)])


def concat_segments(segs: list[Path], dst: Path, tmp: Path) -> None:
    """简切拼接。各段编码参数完全一致 → 直接 `-c copy`，零重编码零画质损失。"""
    lst = tmp / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in segs), encoding="utf-8")
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
          "-i", str(lst), "-c", "copy", str(dst)])


def xfade_segments(segs: list[Path], dst: Path, *, offsets: list[float],
                   xfade: float, fps: int) -> None:
    """交叉淡化拼接。各段已多渲了 xfade 长度的尾巴，
    因此 chain 之后总长 = Σ放映时长（与口播时间线仍然严格对齐）。
    语义：第 i 页与第 i+1 页的淡化**从第 i+1 页口播的起点开始**，持续 xfade 秒。"""
    args: list[str] = ["ffmpeg", "-y", "-v", "error"]
    for p in segs:
        args += ["-i", str(p)]
    parts, cur = [], "[0:v]"
    for k in range(1, len(segs)):
        out = f"[v{k}]" if k < len(segs) - 1 else "[vout]"
        parts.append(f"{cur}[{k}:v]xfade=transition=fade:duration={xfade:.4f}"
                     f":offset={offsets[k - 1]:.4f}{out}")
        cur = out
    args += ["-filter_complex", ";".join(parts), "-map", "[vout]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-r", str(fps), str(dst)]
    _run(args)


# ---------- BGM ----------

def _loudness_stats(path: Path, *, target: float = -16.0) -> dict:
    """loudnorm 第一遍（分析口）：拿 integrated LUFS / true peak / LRA / 门限 / 偏移。

    ⚠️ 认 LUFS 不认 RMS：LUFS 带 K 计权 + 门控（跳过字间静音），RMS 两样都没有，
    同一条片子两把尺子能差出 7 dB，拿 RMS 判「BGM 压够没有」必然误判（见 audio-checklist.md）。
    """
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
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


def _loudness(path: Path) -> float:
    return _loudness_stats(path)["i"]


def prepare_bgm(bgm: str, total: float, tmp: Path, *, narration_lufs: float,
                duck_db: float) -> tuple[Path, float]:
    """BGM 归一化 + 压到口播之下 duck_db。

    `--bgm auto` 走同目录 gen_bgm.py **纯合成**（无版权风险、无外部素材）。
    ⛔ 绝不下载来路不明的音乐：一条商用短视频背一首侵权 BGM，赔的钱比整条产线省的多。

    注意这里定的是**相对差**（口播 − duck_db），绝对响度由 `mix_audio` 的母带归一统一负责。
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
    pre = _loudness_stats(mono, target=target)
    fade_out = max(0.0, total - 1.5)   # 两端 1.5s 淡入淡出，在归一之后做
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(mono),
          "-af", f"loudnorm=I={target:.2f}:TP=-2.0:LRA=11:"
                 f"measured_I={pre['i']:.2f}:measured_TP={pre['tp']:.2f}:"
                 f"measured_LRA={pre['lra']:.2f}:measured_thresh={pre['thresh']:.2f}:"
                 f"offset={pre['offset']:.2f}:linear=true,"
                 f"afade=t=in:d=1.5,afade=t=out:st={fade_out:.2f}:d=1.5",
          "-ar", str(SR), "-ac", "1", str(out)])
    # 实测回读：报「目标多少」没用，得报「实际到了多少」。两端淡化会把 integrated 拉低一点点
    # （1.5s×2 相对全片的占比），所以这里的实测值天然略低于目标，看的是**别差到 1 LU 以上**。
    got = _loudness_stats(out, target=target)["i"]
    _err(f"[bgm] 口播 {narration_lufs:.1f} LUFS → BGM 目标 {target:.1f}（低 {duck_db:.0f} LU）"
         f"，实测 {got:.1f} LUFS ⇒ 实际压差 {narration_lufs - got:.1f} LU")
    if abs(got - target) > 1.0:
        raise RuntimeError(
            f"BGM 归一没打准：目标 {target:.2f} LUFS，实测 {got:.2f} LUFS（差 {got - target:+.2f} LU）\n"
            f"⛔ 拒跑——差 1 LU 以上说明归一链路有隐性损失（历史元凶：分析域是立体声、"
            f"输出却 -ac 1，下混白丢 3 dB）。别改这个阈值绕过去，去查链路。")
    return out, got


def mix_audio(narration: Path, bgm: Path | None, dst: Path, tmp: Path, *,
              master_lufs: float) -> dict:
    """混音（口播 + 可选 BGM）→ **最终母带响度归一** → AAC。返回响度凭证。

    🩸 母带归一是 2026-08-16 补的（老板实听「背景音太小」的真正根因）：
    TTS 原始电平只有 −31.6 LUFS，比平台常态（−14~−16 LUFS）低 15 dB 以上。
    之前整条链路**没有任何一处**把绝对响度提上来——BGM 是按「口播 − duck」算的相对值，
    口播本身安静，BGM 只会更安静（实测落到 −49.6 LUFS，等于没有）。
    调 duck 只能改相对差，改不动「整片都小声」，必须在混音之后做一次绝对归一。

    两遍法（⛔ 不能一遍过）：第一遍只分析拿 measured_*，第二遍带着测量值做线性归一。
    单遍 loudnorm 是**流式自适应**的，前几秒还没测准就开始改增益，开头响度会飘。
    """
    mix = tmp / "mix_raw.wav"
    if bgm is None:
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(narration),
              "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le", str(mix)])
    else:
        # normalize=0 是关键：amix 默认按输入数分摊音量，会把已经调准的口播砍掉 6dB
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(narration), "-i", str(bgm),
              "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]",
              "-map", "[a]", "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s24le", str(mix)])

    pre = _loudness_stats(mix, target=master_lufs)
    _err(f"[master] 混音后 {pre['i']:.2f} LUFS / 真峰 {pre['tp']:.2f} dBTP "
         f"→ 归一到 {master_lufs:g} LUFS（提 {master_lufs - pre['i']:+.1f} dB）")
    # -ar 必须显式给：loudnorm 内部按 192kHz 工作，不指定会把成片音轨变成 192k。
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(mix),
          "-af", f"loudnorm=I={master_lufs}:TP=-1.5:LRA=11:"
                 f"measured_I={pre['i']:.2f}:measured_TP={pre['tp']:.2f}:"
                 f"measured_LRA={pre['lra']:.2f}:measured_thresh={pre['thresh']:.2f}:"
                 f"offset={pre['offset']:.2f}:linear=true",
          "-ar", str(SR), "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(dst)])
    return {"target_lufs": master_lufs, "pre_master": pre,
            "gain_db": round(master_lufs - pre["i"], 2)}


# ---------- 收尾自检 ----------

def _verify(out: Path, pages: list[dict], *, cw: int, ch: int,
            master_lufs: float) -> dict:
    """六道自检，任何一道不过就退出码 1（⛔ 不许「报绿了但没验」）。"""
    streams = ffprobe_streams(out)
    kinds = [s.get("codec_type") for s in streams]
    v = [s for s in streams if s.get("codec_type") == "video"]
    checks: list[tuple[str, bool, str]] = []

    expect = sum(p["display_frames"] for p in pages) / SR
    actual = ffprobe_duration(out)
    drift = abs(actual - expect)
    checks.append((
        f"wav 域时长对齐：成片 {actual:.3f}s vs 口播累计 {expect:.3f}s，差 {drift * 1000:.0f}ms",
        drift <= DRIFT_TOLERANCE,
        f"差值超过 {DRIFT_TOLERANCE}s ＝拼接路径有漂移，别用这条片子"))
    checks.append((f"无字幕轨（流构成 {kinds}）",
                   "subtitle" not in kinds and kinds.count("video") == 1 and kinds.count("audio") == 1,
                   "首版规格是无字幕、单视频单音频"))
    got = (v[0].get("width"), v[0].get("height")) if v else (None, None)
    checks.append((f"画布 {got[0]}x{got[1]}（应为 {cw}x{ch}）", got == (cw, ch), "分辨率不符"))
    checks.append((f"页数 {len(pages)}", len(pages) > 0, "没有页"))

    # 母带响度凭证：在**成片**上量（端到端，不是量中间文件报个好看的数）。
    # 这条同时是母带归一那段代码的证伪闸门——归一没生效，这里立刻红。
    final = _loudness_stats(out, target=master_lufs)
    checks.append((
        f"母带响度 {final['i']:.2f} LUFS（目标 {master_lufs:g}±1）",
        abs(final["i"] - master_lufs) <= 1.0,
        f"整片响度偏离目标——平台常态 −14~−16 LUFS，低太多就是「手机外放听不清」"))
    checks.append((
        f"真峰 {final['tp']:.2f} dBTP（应 ≤ −1.5，容差 0.3 留给 AAC 编码）",
        final["tp"] <= -1.2,
        "真峰过高，转码/平台二次压缩时会削波爆音"))

    ok = True
    for label, passed, why in checks:
        _err(f"  {'✅' if passed else '❌'} {label}" + ("" if passed else f" —— {why}"))
        ok &= passed
    return {"passed": ok, "duration": actual, "expected": expect, "drift": drift,
            "measured_lufs": round(final["i"], 2), "measured_tp": round(final["tp"], 2),
            "measured_lra": round(final["lra"], 2), "target_lufs": master_lufs}


# ---------- 主流程 ----------

def build(a: argparse.Namespace) -> dict:
    cw, ch = (int(x) for x in a.canvas.lower().split("x"))
    images = collect_images(Path(a.images_dir))
    out = Path(a.out).resolve()

    # 1) 口播来源
    if a.script_file:
        texts = _parse_script(Path(a.script_file))
        if len(texts) != len(images):
            raise RuntimeError(
                f"口播稿 {len(texts)} 页 vs 图 {len(images)} 页，对不上。\n"
                f"  图：{[p.name for p in images]}\n"
                f"⛔ 拒跑——请把稿子补齐到每页一节（`## Pn`）")
        if a.dry_run:
            _err(f"[dry-run] 校验通过：{len(images)} 页 / {len(texts)} 段口播，"
                 f"共 {sum(len(t) for t in texts)} 字（未调 TTS、未渲染）")
            return {"success": True, "dry_run": True, "pages": len(images),
                    "chars": sum(len(t) for t in texts)}
        tts_dir = Path(a.tts_dir) if a.tts_dir else out.parent / "narration"
        page_wavs = tts_pages(texts, tts_dir, engine=a.engine, voice=a.voice,
                              speed=a.speed, model=a.model, gap=a.sentence_gap)
    else:
        page_wavs = collect_audios(Path(a.narration_dir))
        pair_pages(images, page_wavs)
        if a.dry_run:
            _err(f"[dry-run] 校验通过：{len(images)} 页 / {len(page_wavs)} 段口播（未渲染）")
            return {"success": True, "dry_run": True, "pages": len(images)}

    tmp = Path(tempfile.mkdtemp(prefix="slideshow_"))
    try:
        # 2) wav 域拼接口播主轨 → 每页放映窗口
        narration = tmp / "narration_master.wav"
        pages = build_narration(page_wavs, narration, tmp,
                                head=a.head, gap=a.page_gap, tail=a.tail)
        total_sec = sum(p["display_frames"] for p in pages) / SR
        _err(f"[audio] 口播主轨 {total_sec:.2f}s，{len(pages)} 页 "
             f"（head {a.head}s / 页间 {a.page_gap}s / 尾 {a.tail}s）")

        # 3) 每页帧数：按**累计时刻**取整，误差不随页数累积（最大偏差半帧）
        fps = a.fps
        cum_f, prev = [], 0
        for p in pages:
            cur = round((p["start_frame"] + p["display_frames"]) / SR * fps)
            cum_f.append(cur - prev)
            p["video_frames"] = cur - prev
            prev = cur
        xf_frames = round(a.xfade * fps)

        # 4) 逐页画布 + 逐页片段
        segs = []
        for i, (img, p) in enumerate(zip(images, pages)):
            canvas = tmp / f"canvas_{i:02d}.png"
            _page_canvas(img, canvas, cw=cw, ch=ch, kb=a.kenburns, prescale=a.prescale)
            n = p["video_frames"] + (xf_frames if i < len(pages) - 1 else 0)
            seg = tmp / f"seg_{i:02d}.mp4"
            render_segment(canvas, seg, frames=n, fps=fps, cw=cw, ch=ch,
                           kb=a.kenburns, index=i)
            segs.append(seg)
            p["image"] = str(img)
            _err(f"[video] P{i + 1:02d} {img.name} → {p['display_sec']:.2f}s "
                 f"({p['video_frames']} 帧)")

        # 5) 拼接
        silent = tmp / "silent.mp4"
        if xf_frames > 0 and len(segs) > 1:
            offs, acc = [], 0
            for p in pages[:-1]:
                acc += p["video_frames"]
                offs.append(acc / fps)
            xfade_segments(segs, silent, offsets=offs, xfade=a.xfade, fps=fps)
        else:
            concat_segments(segs, silent, tmp)

        # 6) 音轨（口播 + 可选 BGM → 母带归一）
        video_sec = ffprobe_duration(silent)
        narr_lufs = _loudness(narration)
        bgm, bgm_lufs = prepare_bgm(a.bgm, video_sec, tmp, narration_lufs=narr_lufs,
                                    duck_db=a.bgm_duck) if a.bgm else (None, None)
        audio = tmp / "audio_mix.m4a"
        master = mix_audio(narration, bgm, audio, tmp, master_lufs=a.master_lufs)

        # 7) 合流
        out.parent.mkdir(parents=True, exist_ok=True)
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(audio),
              "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy",
              "-movflags", "+faststart", str(out)])

        _err("[verify] 收尾自检")
        v = _verify(out, pages, cw=cw, ch=ch, master_lufs=a.master_lufs)
        meta = {
            "success": v["passed"], "output": str(out),
            "canvas": f"{cw}x{ch}", "fps": fps,
            "pages": pages, "verify": v,
            "bgm": a.bgm or None, "kenburns": a.kenburns, "xfade": a.xfade,
            # 响度凭证：改任何音频参数后都要回来核这一段（audio-checklist.md 最后一条）
            "audio": {
                "narration_lufs_raw": round(narr_lufs, 2),
                "bgm_duck_db": a.bgm_duck if bgm else None,
                "bgm_target_lufs": round(narr_lufs - a.bgm_duck, 2) if bgm else None,
                # ★ 实测：BGM 轨归一后真的到了多少，以及由它反推的**实际**压差
                "bgm_measured_lufs": round(bgm_lufs, 2) if bgm else None,
                "bgm_actual_duck_db": round(narr_lufs - bgm_lufs, 2) if bgm else None,
                # 成片里 BGM 的绝对响度（母带是线性增益，故可相加；linear 生效的判据是前后 LRA 不变）
                "bgm_in_film_lufs": round(bgm_lufs + (v["measured_lufs"] - master["pre_master"]["i"]), 2) if bgm else None,
                "master": master,
                "final_lufs": v["measured_lufs"],
                "final_tp_dbtp": v["measured_tp"],
                "final_lra": v["measured_lra"],
            },
            "size_bytes": out.stat().st_size,
        }
        Path(str(out) + ".meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta
    finally:
        if a.keep_temp:
            _err(f"[tmp] 保留中间文件：{tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    p = argparse.ArgumentParser(
        description="轮播放映视频（tpl-slideshow）：轮播图逐张放映 + 口播 + 可选 BGM")
    p.add_argument("--images-dir", required=True, help="轮播图目录，文件名序=页序")
    p.add_argument("--narration-dir", help="每页一段口播音频（与 --script-file 二选一）")
    p.add_argument("--script-file", help="分页口播稿，内部串行调 TTS（与 --narration-dir 二选一）")
    p.add_argument("--out", required=True, help="成片 mp4 路径")
    p.add_argument("--bgm", help="BGM：文件路径，或 auto（gen_bgm.py 纯合成，零版权）")
    p.add_argument("--bgm-duck", type=float, default=14.0,
                   help="BGM 低于口播多少 LU（默认 14，老板 2026-08-16 实听从 18 调下来；"
                        "要更突出音乐用 12，要纯背景用 18）")
    p.add_argument("--master-lufs", type=float, default=-16.0,
                   help="成片母带整体响度目标 LUFS（默认 −16，平台常态 −14~−16）；"
                        "真峰恒定压 −1.5 dBTP")
    p.add_argument("--canvas", default=DEFAULT_CANVAS, help=f"画布，默认 {DEFAULT_CANVAS}（3:4）")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--kenburns", type=float, default=0.03,
                   help="Ken Burns 缩放幅度（默认 0.03=3%%，0 关闭）；上界=贴合框，全程零裁切")
    p.add_argument("--xfade", type=float, default=0.0,
                   help="页间交叉淡化秒数（默认 0=简切，建议 ≤0.3）")
    p.add_argument("--prescale", type=int, default=3,
                   help="Ken Burns 超采样倍数（默认 3），压 zoompan 的整数取整抖动")
    p.add_argument("--head", type=float, default=0.3, help="片头静音（秒）")
    p.add_argument("--page-gap", type=float, default=0.35, help="页间停顿（秒），停顿期间本页仍在屏")
    p.add_argument("--tail", type=float, default=1.2, help="片尾留白（秒），末页多停这么久")
    p.add_argument("--engine", default="minimax", choices=["minimax", "doubao", "edge"])
    p.add_argument("--voice", default=DEFAULT_VOICE)
    p.add_argument("--speed", type=float, default=0.95)
    p.add_argument("--model", default="speech-2.8-hd")
    p.add_argument("--sentence-gap", type=float, default=0.45, help="页内句间停顿（传给 tts_gen）")
    p.add_argument("--tts-dir", help="TTS 产物落盘目录（默认 <out 同级>/narration）")
    p.add_argument("--dry-run", action="store_true", help="只校验页数/口播段数，不调 TTS 不渲染")
    p.add_argument("--keep-temp", action="store_true")
    a = p.parse_args()

    if bool(a.narration_dir) == bool(a.script_file):
        p.error("--narration-dir 与 --script-file 必须二选一")
    try:
        res = build(a)
    except Exception as e:  # noqa: BLE001
        _err(f"❌ {e}")
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("success") else 1)


if __name__ == "__main__":
    main()

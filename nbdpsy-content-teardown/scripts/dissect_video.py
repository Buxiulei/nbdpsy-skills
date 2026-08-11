#!/usr/bin/env python3
"""内容拆解 —— 视频 / 录屏 / 纯音频「一键解剖」。

丢进来一个（或一批）媒体文件，一次跑完扒素材的全部机械活，人只剩下动脑的部分：

    probe.json      ffprobe 元数据（时长 / 分辨率 / 流 / 体积）
    audio.wav       16k 单声道（无音频流则跳过，并在 REPORT 里标注）
    transcript.json 口播转写（faster-whisper small / cpu / int8，语种自动检测）
    transcript.txt  同上的人读版；疑无口播时顶部压一条醒目告警
    frames/fNN.jpg  按 --fps 抽帧并缩到 --frame-width 宽
    sheet.jpg       4x4 帧看板（>16 帧顺延 sheet-2.jpg…，纯 ffmpeg，不依赖 imagemagick）
    REPORT.md       素材单骨架：机器能填的全填好，「形式拆解 / 数据 / 建议」留给人工

用法：
    python3 dissect_video.py a.mp4 b.mp4 [--out teardown-out] [--fps 0.5]
                             [--frame-width 360] [--no-asr]

**幻觉守卫（本脚本存在的头号理由）**：whisper 对纯音乐 / 环境声片段会一本正经地编出内容。
2026-08-11 实测：一条 31.7s 的纯音乐视频号录屏，被转写出 30–55s 的段落（时间轴直接越过
媒体实长）与一串句号。所以转写结果一律先过 hallucination_verdict()：segments 为空、
全部文本去空白后只剩标点 / 单字重复、language_probability < 0.5、段落时间越出媒体实长，
命中任一条就在 transcript.txt 顶部与 REPORT.md 里挂告警，提示「文字稿=字幕稿，去帧看板
逐帧抄字幕层」。**绝不把幻觉当口播喂给下游**。

依赖：ffmpeg / ffprobe 必装（缺了直接报错退出）；faster-whisper 可选，缺了只是没有转写，
其余产物照出（并打印安装提示）。

输出契约：进度打 stderr；stdout 是一份纯 JSON 汇总（每个输入文件一项，含 outputs 与
warnings）。全部成功 exit 0，任一文件失败 exit 1（失败项的 error 字段写明原因，绝不装成功）；
参数非法（--fps 0 / --frame-width 0）或缺 ffmpeg/ffprobe 直接 exit 2。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

TILE_COLS, TILE_ROWS = 4, 4
TILE_CAP = TILE_COLS * TILE_ROWS          # 一张看板最多 16 帧，超出顺延下一张
ASR_MODEL = "small"                        # 兼顾速度与中文准确率；cpu+int8 单线程可跑
ASR_PROMPT = "以下是普通话，简体中文。"      # 逼 whisper 输出简体而非繁体/拼音
WHISPER_INSTALL_HINT = "pip install --user --break-system-packages faster-whisper"
LANG_PROB_FLOOR = 0.5                      # 语种置信度低于此值视为「没听懂」
OVERRUN_TOL = 0.5                          # 段落越界容忍（秒），躲开尾帧取整误差
NO_SPEECH_BANNER = "⚠️ 疑无口播（纯音乐/环境声）：文字稿=字幕稿，请看帧看板逐帧抄录字幕层"

_MODEL_CACHE: dict = {}                    # 一次进程内多文件共用同一个 whisper 实例


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _run(cmd: list[str], timeout: int = 1800) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", f"找不到可执行文件：{cmd[0]}（请先装 ffmpeg）"
    except subprocess.TimeoutExpired:
        return 124, "", f"超时（{timeout}s）：{' '.join(cmd[:3])}…"


# ---------------------------------------------------------------- 纯函数区（可单测）

def normalize_probe(raw: dict, path: Path, size_bytes: int) -> dict:
    """ffprobe 原始 JSON → 精简契约。纯函数，测试直接喂假 raw。"""
    fmt = raw.get("format") or {}
    streams = []
    for s in raw.get("streams") or []:
        item = {"index": s.get("index"),
                "codec_type": s.get("codec_type"),
                "codec_name": s.get("codec_name")}
        if s.get("codec_type") == "video":
            item["width"] = s.get("width")
            item["height"] = s.get("height")
            item["fps"] = _parse_rate(s.get("avg_frame_rate") or s.get("r_frame_rate"))
        elif s.get("codec_type") == "audio":
            item["sample_rate"] = s.get("sample_rate")
            item["channels"] = s.get("channels")
        streams.append(item)

    def _first(kind):
        return next((s for s in streams if s["codec_type"] == kind), None)

    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    return {"file": str(path), "name": path.name,
            "format_name": fmt.get("format_name"),
            "duration": round(duration, 3),
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / 1024 / 1024, 2),
            "streams": streams,
            "video": _first("video"), "audio": _first("audio")}


def _parse_rate(rate) -> float | None:
    """ffprobe 的 '30000/1001' 形式帧率 → 浮点。分母 0 或缺失返回 None。"""
    if not rate or not isinstance(rate, str) or "/" not in rate:
        return None
    num, _, den = rate.partition("/")
    try:
        num_f, den_f = float(num), float(den)
    except ValueError:
        return None
    return round(num_f / den_f, 2) if den_f else None


def _clean(text) -> str:
    """去掉全部空白（Python 的 \\s 对 str 走 Unicode，全角空格 U+3000 也在内）。"""
    return re.sub(r"\s+", "", str(text or ""))


def _is_punct_only(text: str) -> bool:
    """去空白后是否只剩标点 / 符号（whisper 幻觉最典型的产物就是一串「。」）。"""
    if not text:
        return True
    return all(unicodedata.category(ch).startswith(("P", "S", "Z", "C")) for ch in text)


def _is_noise_text(text: str) -> bool:
    """单段是否「无信息量」：空 / 纯标点 / 同一个字符重复（如「啊啊啊啊」「。。。」）。"""
    t = _clean(text)
    return (not t) or _is_punct_only(t) or len(set(t)) == 1


def hallucination_verdict(segments, language_probability, media_duration,
                          *, tol: float = OVERRUN_TOL,
                          prob_floor: float = LANG_PROB_FLOOR) -> dict:
    """幻觉守卫：判定「疑无口播（纯音乐/环境声）」。

    命中任一条即 suspect=True（四条判据都是实测踩出来的，别随手放宽）：
      1. segments 为空 —— 压根没转出东西；
      2. 全部段落去空白后只剩标点 / 单字重复 —— 典型幻觉产物；
      3. language_probability < prob_floor —— 连语种都没听准，内容不可信；
      4. 有段落时间越出媒体实长 —— whisper 在无人声时会把时间轴编到天上去
         （2026-08-11 实测：媒体实长 31.7s，转写出 30–55s 的段）。

    segments 元素支持 dict{start,end,text} 或 [start, end, text] 序列。
    返回 {"suspect": bool, "reasons": [str, ...]}，reasons 直接进 REPORT，人能看懂。
    """
    reasons: list[str] = []
    segs = list(segments or [])

    if not segs:
        reasons.append("转写 segments 为空（一句话都没转出来）")
    else:
        texts = [_seg_field(s, "text", 2) for s in segs]
        if all(_is_noise_text(t) for t in texts):
            reasons.append(f"全部 {len(segs)} 段去空白后只剩标点 / 单字重复")

    if language_probability is not None:
        try:
            prob = float(language_probability)
        except (TypeError, ValueError):
            prob = None
        if prob is not None and prob < prob_floor:
            reasons.append(f"语种置信度 {prob:.2f} < {prob_floor}")

    try:
        dur = float(media_duration or 0)
    except (TypeError, ValueError):
        dur = 0.0
    if dur > 0:
        for i, s in enumerate(segs, 1):
            end = _to_float(_seg_field(s, "end", 1))
            start = _to_float(_seg_field(s, "start", 0))
            if end is not None and end > dur + tol:
                reasons.append(
                    f"第 {i} 段时间 [{start if start is not None else '?'}, {end}] "
                    f"越出媒体实长 {dur:.2f}s")
                break

    return {"suspect": bool(reasons), "reasons": reasons}


def _seg_field(seg, key: str, idx: int):
    """段落取值：既认 dict{'start','end','text'} 也认 [start, end, text]。"""
    if isinstance(seg, dict):
        return seg.get(key)
    try:
        return seg[idx]
    except (TypeError, IndexError, KeyError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_ts(sec) -> str:
    """秒 → mm:ss.s；拿不到值给 --:--。"""
    v = _to_float(sec)
    if v is None:
        return "--:--"
    m, s = divmod(max(v, 0.0), 60)
    return f"{int(m):02d}:{s:04.1f}"


def render_transcript_txt(transcript: dict | None, guard: dict | None) -> str:
    """transcript.txt 正文。纯函数：疑无口播时告警压顶，然后全文 + 时间轴。"""
    lines: list[str] = []
    if guard and guard.get("suspect"):
        lines += [NO_SPEECH_BANNER,
                  "（判据：" + "；".join(guard.get("reasons") or []) + "）", ""]
    if not transcript:
        lines.append("（无转写：跳过了 ASR，或该文件没有音频流，或 faster-whisper 未安装）")
        return "\n".join(lines).rstrip() + "\n"

    segs = transcript.get("segments") or []
    full = "".join(str(_seg_field(s, "text", 2) or "").strip() for s in segs)
    lines += [f"# 全文（language={transcript.get('language')} "
              f"p={transcript.get('language_probability')}）", full or "（空）", "", "# 时间轴"]
    for s in segs:
        lines.append(f"[{_fmt_ts(_seg_field(s, 'start', 0))} → {_fmt_ts(_seg_field(s, 'end', 1))}] "
                     f"{str(_seg_field(s, 'text', 2) or '').strip()}")
    if not segs:
        lines.append("（无段落）")
    return "\n".join(lines).rstrip() + "\n"


def render_report(probe: dict, transcript: dict | None, guard: dict | None,
                  frames: list[str], sheets: list[str], fps: float,
                  warnings: list[str] | None = None) -> str:
    """REPORT.md 骨架。纯函数：喂 probe/transcript 假数据即可单测。

    机器能填的（元数据 / 转写 / 帧清单）全部预填；形式拆解 / 数据 / 建议三节留空给人。
    """
    v, a = probe.get("video"), probe.get("audio")
    dur = probe.get("duration") or 0.0
    res = f"{v['width']}x{v['height']}" if v and v.get("width") else "—（无视频流）"
    if v and v.get("width") and v.get("height"):
        res += " 竖屏" if v["height"] > v["width"] else (" 横屏" if v["height"] < v["width"] else " 方图")
    vline = f"{v.get('codec_name')} {v.get('fps') or '?'}fps" if v else "—"
    aline = (f"{a.get('codec_name')} {a.get('sample_rate')}Hz {a.get('channels')}ch"
             if a else "—（无音频流）")

    out: list[str] = [
        f"# 素材拆解 · {probe.get('name')}",
        "",
        "> 本文件由 `dissect_video.py` 自动生成骨架：0–2 节机器预填，3–5 节请人工补。",
        "",
        "## 0. 基本信息",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 文件 | `{probe.get('file')}` |",
        f"| 时长 | {dur:.2f}s |",
        f"| 分辨率 | {res} |",
        f"| 视频流 | {vline} |",
        f"| 音频流 | {aline} |",
        f"| 容器 | {probe.get('format_name')} |",
        f"| 体积 | {probe.get('size_mb')} MB |",
        "",
    ]

    if warnings:
        out += ["> 抓取告警：" + "；".join(warnings), ""]

    out += ["## 1. 口播文字稿", ""]
    if guard and guard.get("suspect"):
        out += [f"**{NO_SPEECH_BANNER}**", "",
                "判据：" + "；".join(guard.get("reasons") or []), ""]
    if not transcript:
        out += ["（无转写：跳过了 ASR / 无音频流 / faster-whisper 未安装，详见上方告警）", ""]
    else:
        segs = transcript.get("segments") or []
        full = "".join(str(_seg_field(s, "text", 2) or "").strip() for s in segs)
        out += [f"识别语种：`{transcript.get('language')}`（置信度 "
                f"{transcript.get('language_probability')}），共 {len(segs)} 段。", "",
                "### 全文", "", full or "（空）", "", "### 分段时间轴", "",
                "| # | 起 | 止 | 文本 |", "| --- | --- | --- | --- |"]
        for i, s in enumerate(segs, 1):
            text = str(_seg_field(s, "text", 2) or "").strip().replace("|", "\\|")
            out.append(f"| {i} | {_fmt_ts(_seg_field(s, 'start', 0))} | "
                       f"{_fmt_ts(_seg_field(s, 'end', 1))} | {text} |")
        out.append("")

    out += ["## 2. 帧看板", ""]
    if sheets:
        out += [f"看板（{TILE_COLS}x{TILE_ROWS} 拼图，每张至多 {TILE_CAP} 帧）："]
        out += [f"- `{s}`" for s in sheets]
        out.append("")
    else:
        out += ["（无看板：没抽到帧）", ""]
    if frames:
        step = 1.0 / fps if fps else 0.0
        out += [f"抽帧间隔 {step:.1f}s（--fps {fps}），共 {len(frames)} 帧：", "",
                "| 帧 | 约对应时间 |", "| --- | --- |"]
        for i, f in enumerate(frames):
            out.append(f"| `{f}` | {_fmt_ts(i * step)} |")
        out.append("")
    else:
        out += ["（无帧：该文件可能是纯音频）", ""]

    out += [
        "## 3. 形式拆解（人工填写）",
        "",
        "- 开场 3 秒抓人靠什么：",
        "- 镜头 / 画面节奏：",
        "- 字幕层样式（字体、字号、位置、描边）：",
        "- 音乐与音效：",
        "- 结尾 CTA：",
        "",
        "## 4. 数据（人工填写）",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        "| 播放量 |  |",
        "| 点赞 |  |",
        "| 评论 |  |",
        "| 转发 |  |",
        "| 完播率 |  |",
        "",
        "## 5. 建议（人工填写）",
        "",
        "- 可直接复用：",
        "- 不可复用 / 不适合我们：",
        "- 待验证的假设：",
        "",
        "---",
        "",
        "核对某一帧的字幕文字时用全分辨率关键帧（帧看板是缩图，小字会糊）：",
        "",
        f"```bash",
        f"ffmpeg -ss <秒> -i {probe.get('file')} -frames:v 1 -q:v 3 full.jpg",
        f"```",
        "",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------- 外部命令 / 模型

def probe_media(path: Path) -> dict:
    """跑 ffprobe 取元数据。失败直接抛（fail-loud，不返回半截数据）。"""
    rc, out, err = _run([FFPROBE, "-v", "error",
                         "-show_entries", "format=duration,size,format_name",
                         "-show_entries", "stream=index,codec_type,codec_name,width,height,"
                                          "sample_rate,channels,avg_frame_rate,r_frame_rate",
                         "-of", "json", str(path)], timeout=120)
    if rc != 0:
        raise RuntimeError(f"ffprobe 失败(rc={rc})：{err.strip()[:300]}")
    try:
        raw = json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe 输出不是合法 JSON：{e}")
    return normalize_probe(raw, path, path.stat().st_size)


def extract_audio(src: Path, dst: Path) -> None:
    """抽 16k 单声道 wav（whisper 的原生采样率，省一次重采样）。"""
    rc, _, err = _run([FFMPEG, "-v", "error", "-y", "-i", str(src),
                       "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])
    if rc != 0 or not dst.is_file() or dst.stat().st_size == 0:
        raise RuntimeError(f"抽音频失败(rc={rc})：{err.strip()[:300]}")


def extract_frames(src: Path, frames_dir: Path, fps: float, width: int) -> list[str]:
    """按 fps 抽帧并缩到指定宽（高按比例，-2 保证偶数）。返回帧文件名列表。"""
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("f*.jpg"):
        old.unlink()
    rc, _, err = _run([FFMPEG, "-v", "error", "-y", "-i", str(src),
                       "-vf", f"fps={fps},scale={width}:-2", "-q:v", "3",
                       str(frames_dir / "f%04d.jpg")])
    got = sorted(p.name for p in frames_dir.glob("f*.jpg"))
    if rc != 0 and not got:
        raise RuntimeError(f"抽帧失败(rc={rc})：{err.strip()[:300]}")
    return got


def build_sheets(frames_dir: Path, out_dir: Path, frame_count: int) -> list[str]:
    """纯 ffmpeg tile 拼 4x4 看板。>16 帧自动顺延 sheet-2.jpg / sheet-3.jpg…

    tile 滤镜在 EOF 会把不满一格的余帧刷出来，所以最后一张是残缺格也照样出图。
    """
    if frame_count <= 0:
        return []
    for old in list(out_dir.glob("sheet.jpg")) + list(out_dir.glob("sheet-*.jpg")):
        old.unlink()
    rc, _, err = _run([FFMPEG, "-v", "error", "-y", "-framerate", "1", "-start_number", "1",
                       "-i", str(frames_dir / "f%04d.jpg"),
                       "-filter_complex", f"tile={TILE_COLS}x{TILE_ROWS}:padding=4:margin=4",
                       "-fps_mode", "passthrough", "-q:v", "3",
                       str(out_dir / "sheet-%d.jpg")])
    made = sorted(out_dir.glob("sheet-*.jpg"), key=lambda p: int(p.stem.split("-")[1]))
    if rc != 0 and not made:
        raise RuntimeError(f"拼看板失败(rc={rc})：{err.strip()[:300]}")
    names: list[str] = []
    for p in made:
        # 第一张改名 sheet.jpg（约定俗成的主图），其余保持 sheet-N.jpg 顺延
        if p.name == "sheet-1.jpg":
            target = out_dir / "sheet.jpg"
            p.replace(target)
            names.append(target.name)
        else:
            names.append(p.name)
    return names


def load_whisper():
    """懒加载 faster-whisper（一个进程内多文件共用同一实例）。缺依赖返回 None 并给安装提示。"""
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"]
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        _log(f"⚠️ 未安装 faster-whisper，本次跳过转写（其余产物照出）。装它：{WHISPER_INSTALL_HINT}")
        _MODEL_CACHE["model"] = None
        return None
    _log(f"加载 whisper 模型 {ASR_MODEL}（cpu/int8，首次会下载权重）…")
    _MODEL_CACHE["model"] = WhisperModel(ASR_MODEL, device="cpu", compute_type="int8")
    return _MODEL_CACHE["model"]


def transcribe(wav: Path) -> dict | None:
    """转写。返回 {language, language_probability, duration, segments:[{start,end,text}]}。

    语种自动检测（不写死 zh：素材里真有英文/日文片段），initial_prompt 逼简体输出。
    """
    model = load_whisper()
    if model is None:
        return None
    segments, info = model.transcribe(str(wav), language=None, initial_prompt=ASR_PROMPT)
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": (s.text or "").strip()}
            for s in segments]
    return {"language": info.language,
            "language_probability": round(float(info.language_probability), 4),
            "duration": round(float(getattr(info, "duration", 0.0)), 2),
            "model": ASR_MODEL,
            "initial_prompt": ASR_PROMPT,
            "segments": segs}


# ---------------------------------------------------------------- 主流程

_CLAIMED_DIRS: set = set()  # 本次进程内已占用的产物目录（防同 stem 输入静默互覆）


def dissect_one(src: Path, out_root: Path, fps: float, frame_width: int, do_asr: bool) -> dict:
    """解剖单个文件。返回本文件的产物清单；异常由调用方兜住并如实记账。"""
    # 同名 stem（a.mp4 与 a.mov / 不同目录同名录屏切条）绝不静默互覆：撞了就顺延 -2、-3…
    work = out_root / src.stem
    n = 2
    while work in _CLAIMED_DIRS:
        work = out_root / f"{src.stem}-{n}"
        n += 1
    _CLAIMED_DIRS.add(work)
    work.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, object] = {}
    warnings: list[str] = []
    if work.name != src.stem:
        warnings.append(f"同名输入撞目录：本文件产物落 {work.name}/（防静默互覆）")

    _log(f"[{src.name}] 1/5 ffprobe…")
    probe = probe_media(src)
    (work / "probe.json").write_text(json.dumps(probe, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    outputs["probe"] = "probe.json"
    _log(f"[{src.name}]     时长 {probe['duration']}s，"
         f"{(probe.get('video') or {}).get('width', '—')}x"
         f"{(probe.get('video') or {}).get('height', '—')}，{probe['size_mb']}MB")

    # --- 音频 ---
    transcript = None
    if not probe.get("audio"):
        warnings.append("无音频流：跳过 audio.wav 与转写")
        _log(f"[{src.name}] 2/5 无音频流，跳过抽音频")
    else:
        _log(f"[{src.name}] 2/5 抽 16k 单声道 audio.wav…")
        wav = work / "audio.wav"
        extract_audio(src, wav)
        outputs["audio"] = "audio.wav"
        if not do_asr:
            warnings.append("--no-asr：跳过转写")
            _log(f"[{src.name}] 3/5 --no-asr，跳过转写")
        else:
            _log(f"[{src.name}] 3/5 转写中（faster-whisper {ASR_MODEL}）…")
            transcript = transcribe(wav)
            if transcript is None:
                warnings.append(f"faster-whisper 未安装，无转写（{WHISPER_INSTALL_HINT}）")

    guard = None
    if transcript is not None:
        guard = hallucination_verdict(transcript["segments"],
                                      transcript.get("language_probability"),
                                      probe.get("duration"))
        transcript["no_speech_suspect"] = guard["suspect"]
        transcript["no_speech_reasons"] = guard["reasons"]
        (work / "transcript.json").write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs["transcript_json"] = "transcript.json"
        if guard["suspect"]:
            _log(f"[{src.name}]     {NO_SPEECH_BANNER}")
            _log(f"[{src.name}]     判据：" + "；".join(guard["reasons"]))
            warnings.append("疑无口播（幻觉守卫命中）：" + "；".join(guard["reasons"]))
        else:
            _log(f"[{src.name}]     转写 {len(transcript['segments'])} 段，"
                 f"language={transcript['language']} p={transcript['language_probability']}")
    # transcript.txt 永远写：没转写时它就是一行「为什么没有」，比文件缺失好排查
    (work / "transcript.txt").write_text(render_transcript_txt(transcript, guard),
                                         encoding="utf-8")
    outputs["transcript_txt"] = "transcript.txt"

    # --- 画面 ---
    frames: list[str] = []
    sheets: list[str] = []
    if not probe.get("video"):
        warnings.append("无视频流：跳过抽帧与帧看板")
        _log(f"[{src.name}] 4/5 无视频流，跳过抽帧")
    else:
        _log(f"[{src.name}] 4/5 抽帧（fps={fps}，宽 {frame_width}）…")
        frames = extract_frames(src, work / "frames", fps, frame_width)
        outputs["frames"] = [f"frames/{f}" for f in frames]
        _log(f"[{src.name}]     得到 {len(frames)} 帧")
        _log(f"[{src.name}] 5/5 拼帧看板…")
        sheets = build_sheets(work / "frames", work, len(frames))
        outputs["sheets"] = sheets
        _log(f"[{src.name}]     看板 {sheets or '（无）'}")

    report = render_report(probe, transcript, guard,
                           [f"frames/{f}" for f in frames], sheets, fps, warnings)
    (work / "REPORT.md").write_text(report, encoding="utf-8")
    outputs["report"] = "REPORT.md"

    return {"file": str(src), "out_dir": str(work), "ok": True,
            "duration": probe["duration"],
            "no_speech_suspect": bool(guard and guard["suspect"]),
            "outputs": outputs, "warnings": warnings}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="视频/录屏/音频一键解剖：probe + 音轨 + 转写(带幻觉守卫) + 抽帧 + 帧看板 + 素材单骨架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python3 dissect_video.py a.mp4 b.mp4 --out teardown-out --fps 0.5")
    ap.add_argument("media", nargs="+", help="媒体文件（视频/录屏/音频，可多个）")
    ap.add_argument("--out", default="./teardown-out", help="产物根目录（默认 ./teardown-out）")
    ap.add_argument("--fps", type=float, default=0.5, help="抽帧频率，默认 0.5（每 2 秒 1 帧）")
    ap.add_argument("--no-asr", action="store_true", help="跳过 whisper 转写（只要画面与元数据时用）")
    ap.add_argument("--frame-width", type=int, default=360, help="抽帧缩放宽度，默认 360")
    args = ap.parse_args()

    if args.fps <= 0:
        _log("--fps 必须 > 0")
        sys.exit(2)
    if args.frame_width <= 0:
        _log("--frame-width 必须 > 0")
        sys.exit(2)
    if not shutil.which(FFMPEG) and not Path(FFMPEG).is_file():
        _log("找不到 ffmpeg：sudo apt-get install ffmpeg（macOS: brew install ffmpeg）")
        sys.exit(2)

    out_root = Path(args.out).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    results = []
    failed = 0
    for i, raw in enumerate(args.media, 1):
        src = Path(raw).expanduser()
        _log(f"=== [{i}/{len(args.media)}] {src} ===")
        if not src.is_file():
            _log(f"文件不存在：{src}")
            results.append({"file": str(src), "ok": False, "error": "文件不存在"})
            failed += 1
            continue
        try:
            results.append(dissect_one(src.resolve(), out_root, args.fps,
                                       args.frame_width, not args.no_asr))
        except Exception as e:  # 单个文件炸掉不拖垮整批，但要如实记账并影响退出码
            _log(f"✗ {src.name} 解剖失败：{e}")
            results.append({"file": str(src), "ok": False, "error": str(e)})
            failed += 1

    print(json.dumps({"out_dir": str(out_root), "total": len(args.media),
                      "failed": failed, "results": results},
                     ensure_ascii=False, indent=2))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

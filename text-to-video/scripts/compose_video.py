#!/usr/bin/env python3
"""视频合成层 —— 纯 ffmpeg，零 Remotion/Node 依赖。

把即梦生成的若干片段拼成一条成片：
  归一化(统一分辨率/帧率) → 烧中文字幕(Noto Sans CJK SC, ASS 描边) →
  逐段音轨(旁白/原生音/静音) → 拼接 → 叠 AI 生成合规角标 → 可选 BGM 混音。

输入是一份 manifest JSON：
{
  "output": "final.mp4",
  "resolution": "720x1280",     # 画布；Seedance 竖屏默认 720x1280
  "fps": 30,
  "ai_label": "AI 生成",        # 合规显式标识(右上角)；置空字符串可关闭——但投放强烈建议保留
  "bgm": "bgm.mp3",             # 可选；自动按相对响度垫底(比旁白低 bgm_gap_db)
  "bgm_volume": 0.15,           # 可选，0-1；仅响度探测失败时的回退系数
  "bgm_gap_db": 12,             # 可选；BGM 比旁白低多少 dB(默认12，越大越轻)
  "segments": [
    # narration 若有同名 .cues.json(tts_gen --timed 产物)，字幕按实测时间轴真同步；
    # 否则用 narration_text 按句估算；都没有则用 subtitle 固定整段。
    {"video": "clips/a.mp4", "narration": "tts/000.mp3", "narration_text": "第一句。第二句。"},
    {"video": "clips/b.mp4", "subtitle": "无旁白时的固定字幕"}
  ]
}

用法：
  python compose_video.py --manifest shots.json
  python compose_video.py --manifest shots.json --output out.mp4   # 覆盖 output
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
# Noto Sans CJK SC（本机已确认存在）。改字体改这里。
CJK_FONT_FILE = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
CJK_FONT_NAME = "Noto Sans CJK SC"


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _run(cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"ffmpeg 超时({timeout}s)"


def ffprobe_duration(path: str) -> float:
    rc, out, _ = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                       "-of", "default=nw=1:nk=1", path], timeout=60)
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def _has_audio(path: str) -> bool:
    rc, out, _ = _run([FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
                       "stream=index", "-of", "csv=p=0", path], timeout=60)
    return bool(out.strip())


def _mean_volume_db(path: str, pre_filter: str = "") -> Optional[float]:
    """volumedetect 测 mean_volume(dB)；pre_filter 可先过滤(如调音量)再测。输出在 stderr。"""
    af = f"{pre_filter},volumedetect" if pre_filter else "volumedetect"
    _, _, serr = _run([FFMPEG, "-i", path, "-af", af, "-f", "null", "-"], timeout=120)
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", serr)
    return float(m.group(1)) if m else None


def _ass_escape(text: str) -> str:
    """ASS Dialogue 文本转义：硬换行→\\N，去掉会被解析的花括号。"""
    text = (text or "").replace("{", "(").replace("}", ")")
    return text.replace("\r\n", "\n").replace("\n", r"\N")


def build_ass(text: str, duration: float, width: int, height: int, out_ass: str) -> None:
    """生成单段 ASS 字幕：底部居中、白字黑描边、半透明底，整段时长常驻。"""
    # 字号按画布高度自适应（约 5%）
    fontsize = max(28, int(height * 0.052))
    margin_v = int(height * 0.08)
    end = max(0.5, duration)
    eh = int(end // 3600)
    em = int((end % 3600) // 60)
    es = end % 60
    end_ts = f"{eh}:{em:02d}:{es:05.2f}"
    # PlayResX/Y 对齐画布；Alignment=2 底部居中；BorderStyle=1 描边+阴影
    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{CJK_FONT_NAME},{fontsize},&H00FFFFFF,&H00000000,&H80000000,1,1,3,1,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,{end_ts},Default,,0,0,0,,{_ass_escape(text)}
"""
    Path(out_ass).write_text(content, encoding="utf-8")


def _ass_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _split_caption(text: str) -> list[str]:
    """把旁白按句末标点切成多条；过长句再按逗号切。"""
    enders = "。！？!?"
    caps, buf = [], ""
    for ch in text:
        buf += ch
        if ch in enders:
            caps.append(buf.strip()); buf = ""
    if buf.strip():
        caps.append(buf.strip())
    out = []
    for c in caps:
        if len(c) <= 24:
            out.append(c); continue
        sub = ""
        for ch in c:
            sub += ch
            if len(sub) >= 12 and ch in "，、；,;":
                out.append(sub); sub = ""
        if sub:
            out.append(sub)
    return out or [text.strip()]


def _wrap_caption(text: str, per_line: int = 12) -> str:
    """单条字幕过长则折行（每行约 per_line 字，优先在标点处折）。"""
    if len(text) <= per_line:
        return text
    lines, buf = [], ""
    for ch in text:
        buf += ch
        if len(buf) >= per_line and ch in "，。！？、；,!?;":
            lines.append(buf); buf = ""
    if buf:
        lines.append(buf)
    out = []
    for ln in lines:
        while len(ln) > per_line + 4:
            out.append(ln[:per_line]); ln = ln[per_line:]
        out.append(ln)
    return "\n".join(out)


def _ass_header(width: int, height: int) -> str:
    """ASS 头(Script Info + 底部居中白字黑描边样式)，build_timed_ass / build_cued_ass 共用。"""
    fontsize = max(28, int(height * 0.052))
    margin_v = int(height * 0.08)
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{CJK_FONT_NAME},{fontsize},&H00FFFFFF,&H00000000,&H80000000,1,1,3,1,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_timed_ass(text: str, duration: float, width: int, height: int, out_ass: str) -> None:
    """逐字时间轴字幕(估算版)：按句切条、每条按字数比例分配时长。
    这是无 TTS cues 时的回退；有 cues 时优先 build_cued_ass(按实测时长真同步)。"""
    caps = _split_caption(text)
    total = sum(len(c) for c in caps) or 1
    lines, t = [], 0.0
    for i, c in enumerate(caps):
        seg = duration * (len(c) / total)
        start = t
        end = duration if i == len(caps) - 1 else min(duration, t + seg)
        t = end
        lines.append(f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Default,,0,0,0,,{_ass_escape(_wrap_caption(c))}")
    Path(out_ass).write_text(_ass_header(width, height) + "\n".join(lines) + "\n", encoding="utf-8")


def build_cued_ass(cues: list, width: int, height: int, out_ass: str) -> None:
    """按 TTS 实测时间轴 cues([{text,start,end}]) 渲染字幕——旁白讲到哪字幕走到哪，真同步。
    cues 由 tts_gen.py --timed 逐句合成时 ffprobe 实测生成，写在 {narration}.cues.json。"""
    lines = []
    for c in (cues or []):
        start = float(c.get("start", 0.0))
        end = float(c.get("end", start))
        txt = _ass_escape(_wrap_caption((c.get("text") or "").strip()))
        if txt:
            lines.append(f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Default,,0,0,0,,{txt}")
    Path(out_ass).write_text(_ass_header(width, height) + "\n".join(lines) + "\n", encoding="utf-8")


def _filter_path(p: str) -> str:
    """ffmpeg filter 参数里的路径转义（: 和 \\）。"""
    return p.replace("\\", "/").replace(":", r"\:")


def normalize_segment(seg: dict, idx: int, width: int, height: int, fps: int,
                      workdir: str) -> Optional[str]:
    """归一化到统一规格 + 烧字幕 + 配音轨，输出可安全 concat 的中间 mp4。

    旁白时长对齐：成片时长 = max(画面时长, 旁白时长)。
      旁白更长 → 画面 tpad 定格末帧补足（旁白绝不被截）；
      画面更长 → 旁白 apad 补静音到片尾。
    """
    src = seg.get("video")
    if not src or not Path(src).exists():
        _err(f"[normalize] 分镜 {idx} 视频缺失：{src}")
        return None
    video_dur = ffprobe_duration(src) or float(seg.get("duration", 5))
    narration = seg.get("narration")
    use_narr = bool(narration and Path(narration).exists())
    narr_dur = ffprobe_duration(narration) if use_narr else 0.0
    target = max(video_dur, narr_dur) if use_narr else video_dur
    out = str(Path(workdir) / f"seg_{idx:03d}.mp4")

    # 视频链：缩放贴合 + 居中黑边补满
    vchain = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black")
    # 旁白比画面长 → 整段匀速放慢填满旁白时长，画面持续运动（消除末帧定格的“卡住”感，保证连贯）。
    # 根本解是生成视频时就让 duration≈旁白时长，此处仅作兜底，把变速幅度降到最低。
    if use_narr and narr_dur > video_dur + 0.05:
        factor = narr_dur / video_dur
        vchain += f",setpts={factor:.4f}*PTS"
    vchain += f",fps={fps},setsar=1"
    # 字幕：优先 TTS 实测时间轴 cues(讲到哪走到哪·真同步) → 否则按句估算 → 否则固定 subtitle
    narration_text = (seg.get("narration_text") or "").strip()
    subtitle = (seg.get("subtitle") or "").strip()
    cues = None
    if use_narr:
        cues_path = seg.get("cues") or (narration + ".cues.json")
        if Path(cues_path).is_file():
            try:
                cues = (json.loads(Path(cues_path).read_text(encoding="utf-8")) or {}).get("cues")
            except Exception:  # noqa: BLE001
                cues = None
    if cues or narration_text or subtitle:
        ass = str(Path(workdir) / f"seg_{idx:03d}.ass")
        if cues:
            build_cued_ass(cues, width, height, ass)
        elif narration_text:
            build_timed_ass(narration_text, target, width, height, ass)
        else:
            build_ass(subtitle, target, width, height, ass)
        vchain += f",ass={_filter_path(ass)}:fontsdir={_filter_path(os.path.dirname(CJK_FONT_FILE))}"

    cmd = [FFMPEG, "-y", "-i", src]
    if use_narr:
        cmd += ["-i", narration]
        fc = f"[0:v]{vchain}[v];[1:a]apad[a]"   # 旁白补静音到片尾
        amap = ["-map", "[v]", "-map", "[a]"]
    elif _has_audio(src):
        fc = f"[0:v]{vchain}[v]"
        amap = ["-map", "[v]", "-map", "0:a:0"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        fc = f"[0:v]{vchain}[v]"
        amap = ["-map", "[v]", "-map", "1:a:0"]

    cmd += ["-filter_complex", fc, *amap, "-t", f"{target:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", out]

    rc, _, serr = _run(cmd, timeout=600)
    if rc != 0:
        _err(f"[normalize] 分镜 {idx} ffmpeg 失败：\n{serr[-800:]}")
        return None
    return out


def concat_segments(paths: list[str], out: str, workdir: str) -> bool:
    listfile = Path(workdir) / "concat.txt"
    listfile.write_text("".join(f"file '{os.path.abspath(p)}'\n" for p in paths), encoding="utf-8")
    rc, _, serr = _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                        "-c", "copy", out], timeout=600)
    if rc != 0:
        # copy 失败（极少数参数不齐）→ 重编码兜底
        _err("[concat] -c copy 失败，改重编码兜底…")
        rc, _, serr = _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                            "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "192k", out], timeout=900)
    if rc != 0:
        _err(f"[concat] 失败：\n{serr[-800:]}")
    return rc == 0


def finalize(src: str, out: str, *, ai_label: str, bgm: Optional[str],
             bgm_volume: float, width: int, height: int, bgm_gap_db: float = 12.0) -> bool:
    """叠 AI 生成合规角标(右上) + 可选 BGM 混音 → 最终成片(+faststart)。"""
    fontsize = max(20, int(height * 0.030))
    pad = int(height * 0.012)
    cmd = [FFMPEG, "-y", "-i", src]
    has_bgm = bool(bgm and Path(bgm).exists())
    if has_bgm:
        cmd += ["-stream_loop", "-1", "-i", bgm]  # BGM 循环铺满

    filters = []
    if ai_label:
        # 右上角半透明底 + 白字“AI 生成”，合规显式标识
        box = "box=1:boxcolor=black@0.45:boxborderw=8"
        filters.append(
            f"drawtext=fontfile='{CJK_FONT_FILE}':text='{ai_label}':"
            f"fontcolor=white:fontsize={fontsize}:{box}:x=w-tw-{pad}:y={pad}")
    vfilter = ",".join(filters) if filters else "null"

    if has_bgm:
        # BGM 相对响度：测旁白 mean 与 BGM mean，把 BGM 压到比旁白低 bgm_gap_db(默认12dB)。
        # 自动适配任意 BGM 源响度，杜绝"固定系数被淹没/盖过旁白"(实测踩坑)。
        voice_db = _mean_volume_db(src)
        bgm_db = _mean_volume_db(bgm)
        if voice_db is not None and bgm_db is not None:
            gain = (voice_db - bgm_gap_db) - bgm_db
            bgm_vol_expr = f"volume={gain:.1f}dB"
            _err(f"[finalize] BGM 相对响度: 旁白{voice_db:.1f}dB, 目标{voice_db - bgm_gap_db:.1f}dB, 增益{gain:+.1f}dB")
        else:
            bgm_vol_expr = f"volume={max(0.0, bgm_volume)}"
            _err("[finalize] 响度探测失败, 回退固定 bgm_volume")
        # normalize=0 关键：否则 amix 会把旁白+BGM 各压低 ~6dB(实测旁白变小声的 bug)
        fc = (f"[0:v]{vfilter}[v];"
              f"[1:a]{bgm_vol_expr}[bg];"
              f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]")
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-vf", vfilter, "-map", "0:v:0", "-map", "0:a:0?"]

    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out]
    rc, _, serr = _run(cmd, timeout=900)
    if rc != 0:
        _err(f"[finalize] 失败：\n{serr[-800:]}")
    return rc == 0


def compose(manifest: dict, output_override: Optional[str] = None) -> dict:
    segments = manifest.get("segments") or []
    if not segments:
        return {"success": False, "error": "manifest.segments 为空"}
    res = str(manifest.get("resolution", "720x1280"))
    try:
        width, height = (int(x) for x in res.lower().split("x"))
    except ValueError:
        return {"success": False, "error": f"resolution 格式应为 WxH，收到 {res!r}"}
    fps = int(manifest.get("fps", 30))
    output = output_override or manifest.get("output", "final.mp4")
    Path(output).parent.mkdir(parents=True, exist_ok=True)

    workdir = tempfile.mkdtemp(prefix="t2v_compose_")
    try:
        norm = []
        for i, seg in enumerate(segments):
            _err(f"[compose] 归一化分镜 {i + 1}/{len(segments)} …")
            p = normalize_segment(seg, i, width, height, fps, workdir)
            if not p:
                return {"success": False, "error": f"分镜 {i} 归一化失败", "stage": "normalize"}
            norm.append(p)

        merged = str(Path(workdir) / "merged.mp4")
        _err("[compose] 拼接分镜 …")
        if not concat_segments(norm, merged, workdir):
            return {"success": False, "error": "拼接失败", "stage": "concat"}

        _err("[compose] 叠合规标识 / 混 BGM / 导出 …")
        ok = finalize(merged, output, ai_label=manifest.get("ai_label", ""),
                      bgm=manifest.get("bgm"), bgm_volume=float(manifest.get("bgm_volume", 0.15)),
                      width=width, height=height, bgm_gap_db=float(manifest.get("bgm_gap_db", 12.0)))
        if not ok:
            return {"success": False, "error": "导出失败", "stage": "finalize"}

        return {"success": True, "output": os.path.abspath(output),
                "duration": round(ffprobe_duration(output), 2),
                "resolution": f"{width}x{height}", "fps": fps, "segments": len(segments)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main() -> None:
    p = argparse.ArgumentParser(description="纯 ffmpeg 视频合成（中文字幕+AI标识）")
    p.add_argument("--manifest", required=True, help="合成 manifest JSON 路径")
    p.add_argument("--output", help="覆盖 manifest.output")
    a = p.parse_args()
    try:
        manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"success": False, "error": f"读取 manifest 失败：{e}"}, ensure_ascii=False))
        sys.exit(1)
    result = compose(manifest, a.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()

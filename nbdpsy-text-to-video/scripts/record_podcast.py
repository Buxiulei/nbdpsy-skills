#!/usr/bin/env python3
"""「长文播客」录屏合成器 —— Playwright 录 HTML 播放器页的画面，
再与 podcast_gen.py 产出的原始 podcast.mp3 混轨，出 podcast-final.mp4。

形态规格见 references/podcast-video-spec.md §⑤。上游是 podcast_gen.py
（产 podcast.mp3 + podcast.cues.json），模板是 assets/podcast_player.html。

用法：
  python3 record_podcast.py podcast.json
  python3 record_podcast.py podcast.json --cover cover.png --fade-out 1.5

产物：工作目录下 podcast-final.mp4（720×1280，H.264 + AAC 192k，faststart）。

为什么录屏的声道要丢弃：chromium 录制的 webm 音轨是重编码过的，
直接用会白白掉一层音质；画面用录屏、声音用 MiniMax 原始 mp3 才是最优解。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tts_gen  # noqa: E402  复用 ffprobe_duration，不重复造轮子

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "podcast_player.html"
WIDTH, HEIGHT = 720, 1280
FPS = 30
# 检测到 ended 后立刻关页面；轮询间隔越小，尾巴越短、下面的 lead_in 推算越准
POLL_INTERVAL = 0.05
DATA_RE = re.compile(r'(<script id="podcast-data"[^>]*>)(.*?)(</script>)', re.S)
# 播放器主题（规格见 references/podcast-video-spec.md「播放器主题两档」）：
# 真源是模板 <html> 上的 data-theme，页面与 canvas 声纹的颜色全从它派生的 CSS 变量取。
THEMES = ("shenye", "zhishang")
THEME_RE = re.compile(r'(<html\b[^>]*\bdata-theme=")([^"]*)(")')


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def compute_wave(audio: Path, win: float = 0.08) -> dict:
    """离线预计算音量包络（滚动声纹的数据源，2026-08-07 老板选定 C 形态：
    条形=真实音轨逐窗音量、画面中心=当下、随播放滚动）。
    为什么离线算而不用页面里的 Web Audio AnalyserNode：Chromium 把 file:// 音源当
    跨域污染，MediaElementSource 输出全零——声照放、谱全空（实翻车）。
    每窗一个 RMS 值、0-99 量化 → 10 分钟 ≈ 7500 个数字，极小。"""
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-f", "s16le",
         "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-"],
        capture_output=True, timeout=600).stdout
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(16000 * win)
    count = max(1, len(pcm) // n)
    rms = np.array([float(np.sqrt(np.mean(pcm[i * n:(i + 1) * n] ** 2))) for i in range(count)])
    # 对数压缩 + 95 分位归一（防个别爆音把全片压扁），量化 0-99
    arr = np.log1p(rms * 30)
    peak = np.percentile(arr, 95) or 1.0
    arr = np.clip(arr / peak, 0, 1) * 99
    # 心电图形态（2026-08-07 老板定案）要过零摆动的连续描线：每窗取有符号极值对
    # [min,max]（真实波形的上下包络），页面 canvas 交替穿线成心电式轨迹。
    hi = np.array([float(pcm[i * n:(i + 1) * n].max()) for i in range(count)])
    lo = np.array([float(pcm[i * n:(i + 1) * n].min()) for i in range(count)])
    def _q(x):
        y = np.sign(x) * np.log1p(np.abs(x) * 30)
        pk = np.percentile(np.abs(y), 95) or 1.0
        return np.clip(y / pk, -1, 1) * 99
    peaks = np.stack([_q(lo), _q(hi)], axis=1).astype(int)
    return {"win": win, "values": arr.astype(int).tolist(), "peaks": peaks.tolist()}


_SENT_END = "。！？!?…"


def _split_sentences(text: str) -> list[str]:
    """按句末标点切句（标点留在句尾，供下游决定删/留）。
    ⚠ 为什么分页层必须自己切句：短视频那条线的「句号翻页」其实是 **TTS 层**做的
    （tts_gen --timed 一句一条 cue，句号天然是 cue 边界），分页层只管逗号换行。
    播客是**按行合成**（一行 = 一条 cue，行内含多个句子），分页层若不切句，
    compose_video 的管线会把句号当删除字符吞掉，两句话被粘成一句
    （2026-08-07 实翻车：「他回两个字，在忙。我盯着那两个字看了很久」被粘成
    「在忙我盯着那两个字看了很久」）。"""
    out, buf = [], ""
    for ch in (text or ""):
        buf += ch
        if ch in _SENT_END:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out or [(text or "").strip()]


def paginate_cues(cues: list[dict]) -> list[dict]:
    """行级 cues → 页级 cues（2026-08-07 老板定案：播客字幕与短视频同规则——
    逗号换行、句号翻页、每页最多两行超出翻页）。
    三层：① 行内按句末标点切句（= 句号翻页）；② 每句复用 compose_video 的分页管线
    （逗号换行 / 词表折行 / 两行装箱）；③ 时长按显示宽度在行内逐页比例分配。"""
    import compose_video as cv
    out = []
    for c in cues:
        raw = (c.get("text") or "").strip()
        start, end = float(c["start"]), float(c["end"])
        # 先切句，再逐句分页，拼成该行的完整页序列
        pages: list[str] = []
        for sent in _split_sentences(raw):
            pages.extend(cv._render_caption_pages(sent))
        if not pages:
            continue
        weights = [max(1.0, cv._disp_w(p.replace("\n", ""))) for p in pages]
        total = sum(weights)
        t = start
        for i, (p, w) in enumerate(zip(pages, weights)):
            e = end if i == len(pages) - 1 else min(end, t + (end - start) * w / total)
            out.append({"speaker": c.get("speaker", "F"), "text": p,
                        "start": round(t, 3), "end": round(e, 3)})
            t = e
    return out


def build_page(podcast: dict, cues_doc: dict, out_html: Path, wave: dict | None = None,
               theme: str = "shenye") -> None:
    """把 {title, vol, series, duration, cues, wave} 注进模板的 #podcast-data 占位，
    并把主题写进 <html data-theme>。
    页面按同目录相对路径加载 podcast.mp3，所以 out_html 必须与音频同目录。"""
    if theme not in THEMES:
        raise RuntimeError(f"未知主题 {theme!r}，可选：{' / '.join(THEMES)}")
    payload = {
        "title": podcast.get("title", ""),
        "vol": podcast.get("vol"),
        "series": podcast.get("series", ""),
        "duration": cues_doc.get("duration"),
        "cues": paginate_cues(cues_doc.get("cues") or []),
        "wave": wave,
    }
    # "</" 转义：正文里若混进 </script> 会把 script 标签提前闭合，页面直接崩
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    if not DATA_RE.search(html):
        raise RuntimeError("模板里找不到 #podcast-data 注入点，podcast_player.html 被改坏了？")
    if not THEME_RE.search(html):
        raise RuntimeError("模板 <html> 上找不到 data-theme，podcast_player.html 被改坏了？")
    html = DATA_RE.sub(lambda m: m.group(1) + blob + m.group(3), html, count=1)
    html = THEME_RE.sub(lambda m: m.group(1) + theme + m.group(3), html, count=1)
    out_html.write_text(html, encoding="utf-8")


def record(page_url: str, audio_duration: float, video_dir: Path) -> tuple[Path, float]:
    """录屏。返回 (webm 路径, 从 ended 到关页面的尾巴秒数)。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            # 没有这条，脚本触发的 play() 一样会被自动播放策略拒掉
            "--autoplay-policy=no-user-gesture-required",
            "--hide-scrollbars",
            "--mute-audio",  # 录屏音轨反正要丢，静音省一层重编码
        ])
        ctx = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(video_dir),
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        page = ctx.new_page()
        page.goto(page_url, wait_until="load")
        # 故意预滚 0.8s 再开播：让同步掩幕（品红标记）被录进至少十几帧——
        # load 后立刻 __start() 时掩幕在场 <100ms，录屏一帧都拍不到，
        # find_sync_cut 找不到标记只能回退误差几百毫秒的估算（实翻车）。
        time.sleep(0.8)
        page.evaluate("() => window.__start()")
        deadline = time.monotonic() + audio_duration + 60
        ended_at = None
        while time.monotonic() < deadline:
            if page.evaluate("() => window.__done"):
                ended_at = time.monotonic()
                break
            time.sleep(POLL_INTERVAL)
        err = page.evaluate("() => window.__error")
        if err:
            raise RuntimeError(f"播放器页报错：{err}（音频路径/编码不对？）")
        if ended_at is None:
            raise RuntimeError(f"等待播放结束超时（>{audio_duration + 60:.0f}s），"
                               "页面可能没播起来")
        vid = page.video
        ctx.close()   # 必须先 close 才会落盘完整 webm
        closed_at = time.monotonic()
        path = Path(vid.path())
        browser.close()
    return path, closed_at - ended_at


def find_sync_cut(webm: Path, max_scan: float = 8.0) -> float | None:
    """逐帧扫描录屏开头，找同步标记（左上角品红块）消失的时刻 = 音频出声的第一帧。
    这是音画同步的真源（2026-08-07 老板验收：声纹与音频不同步——旧的
    「webm时长−音频时长−尾巴」反推法误差几百毫秒，声纹 80ms 一格跳，错半秒就全对不上）。
    帧级扫描把误差压到一帧（25fps=40ms）。返回 None = 没找到标记（旧版模板），调用方回退估算。"""
    import numpy as np
    tmp = webm.parent / "_syncscan"
    tmp.mkdir(exist_ok=True)
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-t", f"{max_scan}", "-i", str(webm),
             "-vf", "crop=32:32:0:0", str(tmp / "f-%04d.png")],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return None
        from PIL import Image
        frames = sorted(tmp.glob("f-*.png"))
        fps_probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
             "stream=avg_frame_rate", "-of", "default=nw=1:nk=1", str(webm)],
            capture_output=True, text=True, timeout=60).stdout.strip()
        try:
            num, den = fps_probe.split("/")
            fps = float(num) / float(den)
        except Exception:  # noqa: BLE001
            fps = FPS
        last_marker = None
        for i, f in enumerate(frames):
            px = np.asarray(Image.open(f).convert("RGB")).reshape(-1, 3).mean(axis=0)
            if px[0] > 150 and px[2] > 150 and px[1] < 100:  # 品红：R高B高G低
                last_marker = i
        if last_marker is None:
            return None
        return (last_marker + 1) / fps
    finally:
        import shutil as _sh
        _sh.rmtree(tmp, ignore_errors=True)


def mux(webm: Path, audio: Path, out: Path, *, lead_in: float,
        cover: str | None, fade_out: float, audio_duration: float) -> None:
    """录屏画面 + 原始音轨 → 成片。

    时间对齐：lead_in 由 find_sync_cut 帧级标记给出（误差一帧）；标记缺失时
    回退「webm 实测时长 − 音频时长 − 尾巴」估算（误差几百毫秒，仅兜底）。
    录屏帧率与音频还会有几百毫秒漂移：**一律以音频为准**——
    视频先 tpad 定格补长（宁可多几帧定格画面），再靠 -shortest 按音轨长度切齐。"""
    inputs = ["-ss", f"{lead_in:.3f}", "-i", str(webm), "-i", str(audio)]
    cover_idx = None
    if cover:
        if not Path(cover).is_file():
            raise RuntimeError(f"--cover 文件不存在：{cover}")
        cover_idx = 2
        inputs += ["-i", cover]

    parts = [f"[0:v]fps={FPS},scale={WIDTH}:{HEIGHT},setsar=1,"
             f"tpad=stop_mode=clone:stop_duration=10[v0]"]
    cur = "v0"
    if cover_idx is not None:
        # 封面首帧：前 0.1s 盖一张封面图，给平台抓封面用（与 compose_video.finalize 同思路）
        parts.append(f"[{cover_idx}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                     f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black[cvr]")
        parts.append(f"[{cur}][cvr]overlay=0:0:enable='lte(t,0.100)'[vc]")
        cur = "vc"
    if fade_out > 0:
        st = max(0.0, audio_duration - fade_out)
        parts.append(f"[{cur}]fade=t=out:st={st:.2f}:d={fade_out:.2f}[vf]")
        parts.append(f"[1:a]afade=t=out:st={st:.2f}:d={fade_out:.2f}[a]")
        cur, amap = "vf", "[a]"
    else:
        amap = "1:a:0"

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", ";".join(parts), "-map", f"[{cur}]", "-map", amap,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 混轨失败：{r.stderr[-800:]}")


def run(podcast_path: str, *, workdir: str | None = None, audio: str | None = None,
        cues: str | None = None, out: str | None = None,
        cover: str | None = None, fade_out: float = 0.0,
        theme: str = "shenye") -> dict:
    podcast = json.loads(Path(podcast_path).read_text(encoding="utf-8"))
    wd = Path(workdir) if workdir else Path(podcast_path).resolve().parent
    audio_p = Path(audio) if audio else wd / "podcast.mp3"
    cues_p = Path(cues) if cues else wd / "podcast.cues.json"
    out_p = Path(out) if out else wd / "podcast-final.mp4"
    for p in (audio_p, cues_p):
        if not p.is_file():
            raise RuntimeError(f"缺 {p}——先跑 podcast_gen.py synth")

    cues_doc = json.loads(cues_p.read_text(encoding="utf-8"))
    audio_dur = tts_gen.ffprobe_duration(str(audio_p))
    if audio_dur <= 0:
        raise RuntimeError(f"音频时长探测为 0：{audio_p}")

    # 页面必须与 podcast.mp3 同目录（模板按相对路径加载音频）
    page_html = wd / "_podcast_player.html"
    _err("[podcast] 预计算声纹包络 …")
    wave = compute_wave(audio_p)
    build_page(podcast, cues_doc, page_html, wave=wave, theme=theme)
    _err(f"[podcast] 播放器主题：{theme}")

    video_dir = Path(tempfile.mkdtemp(prefix="podcast_rec_"))
    try:
        _err(f"[podcast] 录屏中（音频 {audio_dur:.1f}s）…")
        webm, tail = record(page_html.as_uri(), audio_dur, video_dir)
        sync_cut = find_sync_cut(webm)
        vdur = tts_gen.ffprobe_duration(str(webm))
        if sync_cut is not None:
            lead_in = sync_cut
            _err(f"[podcast] 帧级同步标记：切掉开头 {lead_in:.3f}s（帧扫描，误差≤1帧）")
        else:
            lead_in = max(0.0, min(5.0, vdur - audio_dur - tail))
            _err(f"[podcast] ⚠ 未找到同步标记，回退估算：录屏 {vdur:.2f}s / 音频 {audio_dur:.2f}s"
                 f" / 尾巴 {tail:.2f}s → 切掉开头 {lead_in:.2f}s（误差几百毫秒）")
        mux(webm, audio_p, out_p, lead_in=lead_in, cover=cover,
            fade_out=max(0.0, fade_out), audio_duration=audio_dur)
    finally:
        shutil.rmtree(video_dir, ignore_errors=True)

    dur = tts_gen.ffprobe_duration(str(out_p))
    return {"success": True, "output": str(out_p.resolve()),
            "duration": round(dur, 3), "resolution": f"{WIDTH}x{HEIGHT}", "theme": theme}


def main() -> None:
    p = argparse.ArgumentParser(description="长文播客录屏合成（Playwright + ffmpeg）")
    p.add_argument("podcast", help="podcast.json 路径（取 title/vol/series）")
    p.add_argument("--workdir", default=None, help="产物目录，默认 podcast.json 同目录")
    p.add_argument("--audio", default=None, help="音轨，默认 <workdir>/podcast.mp3")
    p.add_argument("--cues", default=None, help="时间轴，默认 <workdir>/podcast.cues.json")
    p.add_argument("--out", default=None, help="成片，默认 <workdir>/podcast-final.mp4")
    p.add_argument("--cover", default=None, help="封面图，叠在前 0.1s 作首帧")
    p.add_argument("--fade-out", type=float, default=0.0, help="片尾音画同步淡出秒数，如 1.5")
    p.add_argument("--theme", choices=THEMES, default="shenye",
                   help="播放器主题：shenye 深夜电台（默认）/ zhishang 纸上对谈")
    a = p.parse_args()
    try:
        res = run(a.podcast, workdir=a.workdir, audio=a.audio, cues=a.cues, out=a.out,
                  cover=a.cover, fade_out=a.fade_out, theme=a.theme)
    except Exception as e:  # noqa: BLE001
        res = {"success": False, "error": str(e)}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("success") else 1)


if __name__ == "__main__":
    main()

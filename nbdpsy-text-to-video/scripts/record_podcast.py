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


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def build_page(podcast: dict, cues_doc: dict, out_html: Path) -> None:
    """把 {title, vol, series, duration, cues} 注进模板的 #podcast-data 占位。
    页面按同目录相对路径加载 podcast.mp3，所以 out_html 必须与音频同目录。"""
    payload = {
        "title": podcast.get("title", ""),
        "vol": podcast.get("vol"),
        "series": podcast.get("series", ""),
        "duration": cues_doc.get("duration"),
        "cues": cues_doc.get("cues") or [],
    }
    # "</" 转义：正文里若混进 </script> 会把 script 标签提前闭合，页面直接崩
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    if not DATA_RE.search(html):
        raise RuntimeError("模板里找不到 #podcast-data 注入点，podcast_player.html 被改坏了？")
    out_html.write_text(DATA_RE.sub(lambda m: m.group(1) + blob + m.group(3), html, count=1),
                        encoding="utf-8")


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


def mux(webm: Path, audio: Path, out: Path, *, lead_in: float,
        cover: str | None, fade_out: float, audio_duration: float) -> None:
    """录屏画面 + 原始音轨 → 成片。

    时间对齐的取舍：录屏是从页面创建就开始的，__start() 之前那一小段静止画面
    （lead_in）必须切掉，否则字幕会整体比人声晚一拍。lead_in 由
    「webm 实测时长 − 音频时长 − 已测量的尾巴」反推——这是能拿到的最好估计，
    误差量级是轮询间隔（50ms）加 webm 时长本身的精度。
    再者录屏帧率与音频还会有几百毫秒漂移：**一律以音频为准**——
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
        cover: str | None = None, fade_out: float = 0.0) -> dict:
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
    build_page(podcast, cues_doc, page_html)

    video_dir = Path(tempfile.mkdtemp(prefix="podcast_rec_"))
    try:
        _err(f"[podcast] 录屏中（音频 {audio_dur:.1f}s）…")
        webm, tail = record(page_html.as_uri(), audio_dur, video_dir)
        vdur = tts_gen.ffprobe_duration(str(webm))
        lead_in = max(0.0, min(5.0, vdur - audio_dur - tail))
        _err(f"[podcast] 录屏 {vdur:.2f}s / 音频 {audio_dur:.2f}s / 尾巴 {tail:.2f}s "
             f"→ 切掉开头 {lead_in:.2f}s")
        mux(webm, audio_p, out_p, lead_in=lead_in, cover=cover,
            fade_out=max(0.0, fade_out), audio_duration=audio_dur)
    finally:
        shutil.rmtree(video_dir, ignore_errors=True)

    dur = tts_gen.ffprobe_duration(str(out_p))
    return {"success": True, "output": str(out_p.resolve()),
            "duration": round(dur, 3), "resolution": f"{WIDTH}x{HEIGHT}"}


def main() -> None:
    p = argparse.ArgumentParser(description="长文播客录屏合成（Playwright + ffmpeg）")
    p.add_argument("podcast", help="podcast.json 路径（取 title/vol/series）")
    p.add_argument("--workdir", default=None, help="产物目录，默认 podcast.json 同目录")
    p.add_argument("--audio", default=None, help="音轨，默认 <workdir>/podcast.mp3")
    p.add_argument("--cues", default=None, help="时间轴，默认 <workdir>/podcast.cues.json")
    p.add_argument("--out", default=None, help="成片，默认 <workdir>/podcast-final.mp4")
    p.add_argument("--cover", default=None, help="封面图，叠在前 0.1s 作首帧")
    p.add_argument("--fade-out", type=float, default=0.0, help="片尾音画同步淡出秒数，如 1.5")
    a = p.parse_args()
    try:
        res = run(a.podcast, workdir=a.workdir, audio=a.audio, cues=a.cues, out=a.out,
                  cover=a.cover, fade_out=a.fade_out)
    except Exception as e:  # noqa: BLE001
        res = {"success": False, "error": str(e)}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("success") else 1)


if __name__ == "__main__":
    main()

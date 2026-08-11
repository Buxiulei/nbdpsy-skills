#!/usr/bin/env python3
"""参数化逐帧渲染：render_any.py <card.html> <out.mp4>（cues 注入+截帧+ffmpeg 合成混音）。"""
import json, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
FPS = 30

def render(html_name: str, out_name: str) -> str:
    cues = json.load(open(HERE / "narration.mp3.cues.json"))
    if isinstance(cues, dict):
        cues = cues.get("cues", cues)
    src = HERE / html_name
    html = src.read_text(encoding="utf-8").replace("__CUES__", json.dumps(cues, ensure_ascii=False))
    wt = HERE / "word_timings.json"
    words = json.load(open(wt)) if wt.exists() else None
    html = html.replace("__WORDS__", json.dumps(words, ensure_ascii=False))
    rendered = HERE / (src.stem + ".render.html")
    rendered.write_text(html, encoding="utf-8")

    fd = HERE / ("frames_" + src.stem)
    fd.mkdir(exist_ok=True)
    for f in fd.glob("*.png"):
        f.unlink()

    t0 = time.time()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--force-device-scale-factor=1", "--hide-scrollbars"])
        pg = b.new_page(viewport={"width": 1080, "height": 1920})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"file://{rendered.resolve()}")
        pg.wait_for_function("typeof window.SEEK === 'function'", timeout=15000)
        if errs:
            print(f"⚠️ {html_name} 页面错误: {errs[:3]}")
        total = pg.evaluate("window.TOTAL")
        n = int(total * FPS) + 1
        for i in range(n):
            pg.evaluate(f"window.SEEK({i / FPS})")
            pg.screenshot(path=str(fd / f"f{i:05d}.png"))
        b.close()
    print(f"{html_name}: {n} 帧 {time.time()-t0:.0f}s", flush=True)

    out = HERE / out_name
    subprocess.run([
        "ffmpeg", "-y", "-framerate", str(FPS), "-i", str(fd / "f%05d.png"),
        "-i", str(HERE / ("narration.mp3.wav" if (HERE/"narration.mp3.wav").exists() else "narration.mp3")),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19", "-preset", "medium",
        "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out),
    ], check=True, capture_output=True)
    print(f"✅ {out_name} {out.stat().st_size/1048576:.1f}MB", flush=True)
    return str(out)

if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])

#!/usr/bin/env python3
"""参数化逐帧渲染：render_card.py <card.html> <out.mp4>（cues 注入+截帧+ffmpeg 合成混音）。

用法：
  render_card.py <tpl.html> <out.mp4>                 整片渲染 + 混音
  render_card.py <tpl.html> <out.mp4> --shard 1 4     只渲第 1/4 片（跳过混音，帧号仍全局连续）
  render_card.py <tpl.html> --verify-frames [--expect N]   帧连续性校验（缺号/重号/残留）
  render_card.py <tpl.html> <out.mp4> --mux-only      只合帧混音（分片渲完后收口）
  通用 --angle swiftshader|vulkan|egl                 光栅后端，默认 swiftshader（CPU）

⚠️ 路径基准是脚本自身所在目录（HERE），不是 cwd——每条视频必须独立工作目录、各带一份本脚本副本。
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).parent
FPS = 30


def _load_audio_master():
    """定位并加载 `audio_master`（母带响度归一的唯一真源）。

    ⚠️ 本脚本按契约是**被拷进每条视频的工作目录**跑的，`audio_master.py` 不会跟着拷，
    所以不能只 `sys.path.insert(HERE)`（那是「真源≠工作副本」的经典坑）。按序找：
    同目录副本 → 从 HERE 往上找 skill 真源 → 全局安装位。
    ⛔ 全找不到就**抛**，不静默跳过——静默跳过等于把 2026-08-16 那个「整片小声」的 bug 放回来。
    """
    cands = [HERE, *[p / "nbdpsy-text-to-video" / "scripts" for p in HERE.resolve().parents],
             *[Path.home() / d / "skills" / "nbdpsy-text-to-video" / "scripts"
               for d in (".claude", ".agents", ".codex")]]
    for d in cands:
        if (d / "audio_master.py").is_file():
            sys.path.insert(0, str(d))
            import audio_master
            return audio_master
    raise RuntimeError(
        "找不到 audio_master.py（母带响度归一的唯一真源），拒绝出片。\n"
        "⛔ 别绕过：不归一的成片是 −31 LUFS 量级，手机外放听不清（2026-08-16 实听事故）。\n"
        f"处置：把 skill 的 scripts/audio_master.py 拷到本脚本同目录（{HERE}）再跑。")

# 光栅后端**默认 CPU**（headless Chromium 不给 GPU 参数时就是 SwiftShader 软光栅）。
# 不默认开 GPU 的理由（2026-08-12 定）：GPU 与 CPU 是两套字形抗锯齿实现，实测 tpl-basic
# 同模板同 cues 下 222/222 帧全不同、最严重一帧差 30 万像素——而**存量已过审的字卡片全是 CPU 渲的**，
# 默认开 GPU 等于让新片和存量不是一套字。提速走分片（零像素变化），GPU 只在整批都用时显式开。
BASE_ARGS = ["--force-device-scale-factor=1", "--hide-scrollbars"]
GPU_ARGS = ["--enable-gpu", "--ignore-gpu-blocklist"]
# ⚠️ `--use-angle=egl` 不是合法取值，会静默回落 SwiftShader；真正的 EGL 路径叫 gl-egl（实测 2026-08-12）。
ANGLE_BACKEND = {"vulkan": "vulkan", "egl": "gl-egl", "swiftshader": "swiftshader"}


def launch_args(angle: str):
    """按后端拼 Chromium 启动参数。

    swiftshader（默认）走**与存量批次逐字节相同**的原始参数集——一个多余的 --enable-gpu 都可能
    换掉光栅路径，所以这里不图省事跟 GPU 分支合并。
    """
    if angle == "swiftshader":
        return list(BASE_ARGS)
    return BASE_ARGS + GPU_ARGS + [f"--use-angle={ANGLE_BACKEND[angle]}"]

GL_RENDERER_JS = """() => {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
  if (!gl) return 'NO_WEBGL';
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
}"""

WARMUP_SHOTS = 3  # 分片起手的空跑截图数（冲合成器管线，见 render() 内注释）

# --deterministic 用：seek 后等两个 rAF 再截，逼合成器把这一帧提交完再取图。
# 不加它时逐帧截图**不是**逐字节可复现的（实测同配置三跑出两三个不同 md5，差异 ≤6/255、
# 落在 <0.4% 像素上，肉眼与成片无感），加了才能跑「双跑 md5 验确定性」那道闸。代价约 1.7×。
SETTLE_JS = "() => new Promise(res => requestAnimationFrame(() => requestAnimationFrame(res)))"

FRAME_RE = re.compile(r"^f(\d+)\.(?:png|jpe?g)$", re.I)
LOCK_RE = re.compile(r"^\.render\.pid(?:\.s(\d+)of(\d+))?$")

# 模板可声明画布：<meta name="render-canvas" content="1080x1440">。
# 不声明＝1080×1920，与四个存量版式逐字节同一条路径（它们都没有这行）。
CANVAS_RE = re.compile(r"""<meta\s+name=["']render-canvas["']\s+content=["'](\d+)x(\d+)["']""", re.I)
DEFAULT_CANVAS = (1080, 1920)


def read_canvas(html_text: str):
    m = CANVAS_RE.search(html_text)
    return (int(m.group(1)), int(m.group(2))) if m else DEFAULT_CANVAS


# ────────── 分片 ──────────

def shard_range(n_frames: int, i: int, n: int):
    """总帧数按帧域连续切 n 份，返回第 i 片（1-indexed）的半开区间 [lo, hi)。

    除不尽时余数摊给靠前的分片；n > n_frames 时靠后的分片拿到空区间（lo == hi）。
    """
    if n < 1:
        raise ValueError(f"分片总数必须 ≥1，收到 {n}")
    if not 1 <= i <= n:
        raise ValueError(f"分片序号越界：i={i} 不在 1..{n} 内")
    if n_frames < 0:
        raise ValueError(f"总帧数不能为负：{n_frames}")
    base, rem = divmod(n_frames, n)
    lo = (i - 1) * base + min(i - 1, rem)
    return lo, lo + base + (1 if i - 1 < rem else 0)


def slot_label(shard) -> str:
    """槽位的人类可读名：None=整片；(i, n)=第 i/n 片。"""
    return "full" if shard is None else f"{shard[0]}/{shard[1]}"


def slots_conflict(a, b) -> bool:
    """两个渲染槽位是否会写到同一批帧。

    只有「同一 N 的不同分片」互不冲突；其余组合（任一为整片、同片重入、N 不同）一律冲突。
    """
    if a is None or b is None:
        return True
    return not (a[1] == b[1] and a[0] != b[0])


# ────────── 帧目录自锁 ──────────

def lock_filename(shard) -> str:
    return ".render.pid" if shard is None else f".render.pid.s{shard[0]}of{shard[1]}"


def parse_lock_name(name: str):
    """锁文件名 → 槽位（None=整片）；不是锁文件抛 ValueError。"""
    m = LOCK_RE.match(name)
    if not m:
        raise ValueError(f"不是锁文件名：{name}")
    return None if m.group(1) is None else (int(m.group(1)), int(m.group(2)))


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 进程在，只是不归我们管
    return True


def acquire_lock(frame_dir: Path, shard):
    """R15 自锁：会写到同一批帧的活锁存在即拒绝启动，绝不静默清别人的帧。

    锁主已死则打印接管说明后接管。返回锁文件路径，调用方负责在 finally 里 release_lock。
    """
    me = lock_filename(shard)
    for lk in sorted(frame_dir.glob(".render.pid*")):
        try:
            other = parse_lock_name(lk.name)
            pid = int(lk.read_text().splitlines()[0].strip())
        except (ValueError, IndexError, OSError):
            continue  # 不是锁文件 / 锁文件损坏，一律当死锁
        if not pid_alive(pid):
            if lk.name == me:
                print(f"⚠️ 接管帧目录残留锁 {lk.name}（原 pid={pid} 已不存在）", file=sys.stderr)
            continue
        if slots_conflict(shard, other):
            sys.exit(
                f"❌ 帧目录 {frame_dir.name} 已被 pid={pid}（槽位 {slot_label(other)}）持有且进程仍存活，"
                f"本次（槽位 {slot_label(shard)}）会写到同一批帧。拒绝启动——绝不清别人的帧。\n"
                f"   确认那个渲染确实废了，再 kill {pid} 或删 {lk}。"
            )
    p = frame_dir / me
    p.write_text(f"{os.getpid()}\nslot={slot_label(shard)}\nstarted={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
    return p


def release_lock(lock_path: Path):
    try:
        lock_path.unlink()
    except OSError:
        pass


# ────────── 帧连续性 ──────────

def check_frames(names, expect=None):
    """校验帧文件名序列，返回 (missing, dup, extra)。

    names: 帧目录下的文件名列表（只认 f<数字>.png/jpg，其余忽略）
    expect: 期望帧数；None 则按实测最大编号 +1 推断
    dup: 同一编号出现多次（png+jpg 双份、位宽不一致都算）
    extra: 编号 ≥ expect 的残留帧（R15 的「稀疏残留」判据）
    """
    idx = {}
    for nm in names:
        m = FRAME_RE.match(nm)
        if m:
            idx.setdefault(int(m.group(1)), []).append(nm)
    total = expect if expect is not None else (max(idx) + 1 if idx else 0)
    missing = [i for i in range(total) if i not in idx]
    dup = sorted(i for i, v in idx.items() if len(v) > 1)
    extra = sorted(i for i in idx if i >= total)
    return missing, dup, extra


def verify_frames(html_name: str, expect=None) -> int:
    """校验帧目录并打印结论，返回进程退出码。"""
    fd = HERE / ("frames_" + Path(html_name).stem)
    if not fd.is_dir():
        print(f"❌ 帧目录不存在：{fd}", file=sys.stderr)
        return 1
    missing, dup, extra = check_frames([p.name for p in fd.iterdir()], expect)
    n = expect if expect is not None else len(list(fd.glob("f*.png")))
    if missing or dup or extra:
        if missing:
            print(f"❌ 缺 {len(missing)} 帧：{missing[:20]}{' …' if len(missing) > 20 else ''}", file=sys.stderr)
        if dup:
            print(f"❌ 重号 {len(dup)} 处：{dup[:20]}{' …' if len(dup) > 20 else ''}", file=sys.stderr)
        if extra:
            print(f"❌ 残留超界帧 {len(extra)} 个：{extra[:20]}{' …' if len(extra) > 20 else ''}", file=sys.stderr)
        return 1
    print(f"✅ 帧连续 f00000..f{n - 1:05d}（{n} 帧），无缺号无重号", flush=True)
    return 0


# ────────── 渲染 ──────────

def _probe_gl_renderer(page, angle: str):
    """探测实际光栅后端并打进 stderr；落到软光栅时打醒目警告但不中止。"""
    try:
        r = page.evaluate(GL_RENDERER_JS)
    except Exception as e:
        print(f"⚠️ GL_RENDERER 探测失败（{type(e).__name__}），无法确认光栅后端", file=sys.stderr)
        return None
    print(f"GL_RENDERER[--angle={angle}]: {r}", file=sys.stderr)
    is_sw = "swiftshader" in str(r).lower()
    if is_sw and angle != "swiftshader":
        # 用户显式要 GPU 却落到软光栅 = 真降级，醒目警告
        print(
            "⚠️⚠️ GPU 未生效，正在 CPU 软光栅（SwiftShader），速度慢 5-10 倍！\n"
            "     换 --angle egl 再试；仍是 SwiftShader 就先查驱动/Vulkan ICD。\n"
            "     ⛔ 别拿这批帧跟 GPU 渲的帧混进同一批视频——像素差异会让风格漂移。",
            file=sys.stderr,
        )
    elif is_sw:
        # 默认路径：CPU 软光栅是预期态（与存量批次像素一致），中性提示即可
        print("ℹ️ 当前 CPU 光栅（与存量批次一致）。提速用 render_sharded.sh 分片，"
              "或显式 --angle vulkan 开 GPU（⚠️ 开了就整批开，GPU 会改像素）。",
              file=sys.stderr)
    return r


def _mp4_playable(path: Path) -> float | None:
    """成片能不能被下游吃下——返回时长秒数，读不出返回 None。

    🔴 **⛔ 不用「文件存在且非空」当判据**：MP4 的 moov atom 在**末尾**写入，
    混音进行中的半成品同样存在、同样有几 MB（2026-08-18 实测：3.8MB 的半成品
    `ffprobe` 报 `moov atom not found`，写完是 25MB）。
    **拿它当「渲完了」去删帧，会把还在用的帧删掉。**
    """
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def sweep_frames(html_name: str, out_name: str, keep: bool = False) -> str:
    """成片确认可读后删帧目录。🩸 2026-08-18 立，起因是一次跑批前的体积核算。

    **1080×1440 30fps 的 PNG ≈2.3MB/帧，一条 3–6 分钟口播＝12–25GB，12 条并存 241GB。**
    而磁盘是**共享的**——撑爆不只是本线失败，**会连同时在出片的别条线一起死**。
    ⇒ 清帧从「跑批脚本各自记得做」提到**产线默认行为**，⛔ 别再指望每个调用方自觉。

    ⚠️ 三条不删的情况：① `--keep-frames`；② 成片 `ffprobe` 读不出（渲染没成功，
    帧还有用）；③ 分片模式（帧还要给别的片和收口用）——由调用方不调本函数来保证。
    """
    fd = HERE / ("frames_" + Path(html_name).stem)
    if keep:
        return f"🔲 保留帧目录（--keep-frames）：{fd.name}"
    if not fd.is_dir():
        return ""
    dur = _mp4_playable(HERE / out_name)
    if dur is None:
        return (f"⚠️ 成片读不出时长，**帧目录保留**：{fd.name}"
                f"\n   ⛔ 这不是「渲完了」——先查 {out_name} 再决定，别手动删帧")
    n = len(list(fd.glob("f*.png")))
    size = sum(f.stat().st_size for f in fd.glob("f*.png")) / 1e9
    shutil.rmtree(fd)
    return f"🧹 已删帧目录 {fd.name}（{n} 帧 / {size:.1f}GB）——成片 {dur:.1f}s 可读"


def mux(html_name: str, out_name: str) -> str:
    """合帧 + 混音 + **母带响度归一**。分片渲完后由 wrapper 调这条路径收口。

    🩸 母带归一 2026-08-17 补：此前本线只把 narration 原样贴上去，成片响度就是 TTS 原始
    电平（−31 LUFS 量级），比平台常态低 15 dB ＝手机外放听不清。归一在**这一次编码里**做完
    （两遍法：先分析 narration 拿 measured_*，再带着测量值线性归一），⛔ 别改成先编 AAC 再补一遍。
    """
    am = _load_audio_master()
    fd = HERE / ("frames_" + Path(html_name).stem)
    out = HERE / out_name
    narr = HERE / ("narration.mp3.wav" if (HERE / "narration.mp3.wav").exists() else "narration.mp3")
    target = am.FORM_TARGETS["card"]
    pre = am.loudness_stats(narr, target=target)
    print(f"[master] 口播 {pre['i']:.2f} LUFS → 归一到 {target:g} LUFS "
          f"（提 {target - pre['i']:+.1f} dB）", file=sys.stderr, flush=True)
    subprocess.run([
        "ffmpeg", "-y", "-framerate", str(FPS), "-i", str(fd / "f%05d.png"), "-i", str(narr),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19", "-preset", "medium",
        # -ar/-ac 必须显式给：loudnorm 内部按 192kHz 工作，不指定会把音轨留在 192k（A3 口径 48k/双声道）
        "-af", am.loudnorm_filter(pre, target=target),
        "-ar", str(am.SR), "-ac", "2", "-c:a", "aac", "-b:a", am.BITRATE,
        "-shortest", "-movflags", "+faststart", str(out),
    ], check=True, capture_output=True)
    v = am.verify_master(out, target=target)
    for label, passed, why in v["checks"]:
        print(f"  {'✅' if passed else '❌'} {label}" + ("" if passed else f" —— {why}"),
              file=sys.stderr, flush=True)
    if not v["passed"]:
        raise RuntimeError("母带响度自检不过（见上方 ❌ 行）——⛔ 这条片子别发，先查归一链路。")
    print(f"✅ {out_name} {out.stat().st_size/1048576:.1f}MB "
          f"({v['measured_lufs']:.2f} LUFS / {v['measured_tp']:.2f} dBTP)", flush=True)
    return str(out)


def render(html_name: str, out_name: str = None, shard=None, angle: str = "swiftshader",
           deterministic: bool = False) -> str:
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
    lock = acquire_lock(fd, shard)
    try:
        # 分片模式绝不清帧——并行的兄弟分片正往同一目录写。预清由 render_sharded.sh 统一做。
        if shard is None:
            for f in fd.glob("*.png"):
                f.unlink()

        t0 = time.time()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(args=launch_args(angle))
            vw, vh = read_canvas(html)
            if (vw, vh) != DEFAULT_CANVAS:
                print(f"画布 {vw}x{vh}（模板 render-canvas 声明）", file=sys.stderr)
            pg = b.new_page(viewport={"width": vw, "height": vh})
            _probe_gl_renderer(pg, angle)
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"file://{rendered.resolve()}")
            pg.wait_for_function("typeof window.SEEK === 'function'", timeout=15000)
            if errs:
                print(f"⚠️ {html_name} 页面错误: {errs[:3]}")
            total = pg.evaluate("window.TOTAL")
            n = int(total * FPS) + 1
            lo, hi = shard_range(n, *shard) if shard else (0, n)
            # 分片从片中某帧起手，头几张截图会带合成器未落定的 ±1 LSB 抖动（实测 tpl-basic 第 2 片
            # 前 4 帧跑跑不一样）——先空跑几张把管线冲干净，丢弃不落盘。整片模式从帧 0 起手没有这个
            # 起手抖动，也就不加这段，保持与旧版逐字节一致。
            # ⚠️ 这只治「起手」那几帧；逐帧截图整体的可复现性要靠 --deterministic（见 SETTLE_JS 注释）。
            if shard and lo < hi:
                pg.evaluate(f"window.SEEK({lo / FPS})")
                for _ in range(WARMUP_SHOTS):
                    pg.screenshot()
            for i in range(lo, hi):
                pg.evaluate(f"window.SEEK({i / FPS})")
                if deterministic:
                    pg.evaluate(SETTLE_JS)
                pg.screenshot(path=str(fd / f"f{i:05d}.png"))
            b.close()

        if shard:
            el = time.time() - t0
            print(f"{html_name}: 第 {shard[0]}/{shard[1]} 片 帧[{lo},{hi}) 共 {n} 帧 {el:.0f}s", flush=True)
            print(f"SHARD_RESULT shard={shard[0]}/{shard[1]} range={lo}:{hi} total_frames={n} elapsed={el:.1f}",
                  flush=True)
            return str(fd)
        print(f"{html_name}: {n} 帧 {time.time()-t0:.0f}s", flush=True)
        # 混音仍在锁内——期间别人清帧会合出残片
        return mux(html_name, out_name)
    finally:
        release_lock(lock)


def main(argv=None):
    ap = argparse.ArgumentParser(description="字卡短片逐帧渲染（默认 CPU 光栅 + 可分片并行）")
    ap.add_argument("html", help="模板 HTML（相对本脚本所在目录）")
    ap.add_argument("out", nargs="?", help="输出 MP4（相对本脚本所在目录）")
    ap.add_argument("--shard", nargs=2, type=int, metavar=("I", "N"),
                    help="只渲第 I/N 片（I 从 1 起），帧号保持全局连续，跳过混音")
    ap.add_argument("--angle", choices=sorted(ANGLE_BACKEND), default="swiftshader",
                    help="光栅后端：swiftshader(默认 CPU 软光栅，与存量批次像素一致) / "
                         "vulkan(独显 GPU，⚠️ 会改像素、开了就整批开) / egl(GPU 退路)")
    ap.add_argument("--deterministic", action="store_true",
                    help="每帧等两个 rAF 再截，换来逐字节可复现（跑双跑 md5 验收时必开），约慢 1.7×")
    ap.add_argument("--verify-frames", action="store_true", help="只校验帧目录连续性")
    ap.add_argument("--expect", type=int, help="配合 --verify-frames：期望帧数")
    ap.add_argument("--mux-only", action="store_true", help="只合帧混音（分片渲完后收口）")
    ap.add_argument("--keep-frames", action="store_true",
                    help="渲完保留帧目录（调试用）。⚠️ 默认**成片确认可读后自动删**——"
                         "一条 3–6 分钟口播的帧是 12–25GB，磁盘共享，撑爆会连累别条线")
    a = ap.parse_args(argv)

    if a.verify_frames:
        return verify_frames(a.html, a.expect)
    if a.mux_only:
        if not a.out:
            ap.error("--mux-only 需要 out 参数")
        mux(a.html, a.out)
        print(sweep_frames(a.html, a.out, a.keep_frames), file=sys.stderr)
        return 0
    if a.shard is None and not a.out:
        ap.error("整片渲染需要 out 参数")
    if a.shard is not None:
        shard_range(1, *a.shard)  # 提前把 i/N 越界喊出来，别等渲到一半
    render(a.html, a.out, tuple(a.shard) if a.shard else None, a.angle, a.deterministic)
    # ⚠️ 只在整片渲染后清帧——**分片模式绝不能清**：帧还要给别的片和 --mux-only 收口用
    if a.shard is None:
        msg = sweep_frames(a.html, a.out, a.keep_frames)
        if msg:
            print(msg, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

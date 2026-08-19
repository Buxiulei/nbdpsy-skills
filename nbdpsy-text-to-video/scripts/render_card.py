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
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time
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


def _run_ffmpeg(cmd: list[str]) -> None:
    """跑 ffmpeg，失败时**把 stderr 尾巴报出来**。

    🩸 `capture_output=True, check=True` 抛出的 `CalledProcessError` 只会显示
    「returned non-zero exit status 8」和一长串参数——**真正的原因在 stderr 里，而它被吞了**。
    ⚠️ 排查时得手动重跑一遍才看得到，那正是本仓反复踩的「吞 stderr」。
    """
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败（exit {p.returncode}）：\n{(p.stderr or '')[-1500:]}")


BGM_DEFAULT = "auto"
"""字卡线的 BGM 默认档。

🔴 **`auto` ＝ `gen_bgm.py` 纯合成（零版权、零外部素材），⛔ 不下载来路不明的音乐**——
这是本仓 2026-08-16 就拍过的立场（`audio_master.prepare_bgm` 的注释）：
**一条商用短视频背一首侵权 BGM，赔的钱比整条产线省的多**。
⚠️ 要用真实曲子就把文件路径传给 `--bgm`，⛔ 别改这个默认值去指向某个下载来的文件。

🩸 **老板 2026-08-18 22:40 看 X6 12 条成片：「都没有背景音，需要添加」。**
根因不是"没做过 BGM"——**轮播线（slideshow_video）与微电影线（compose_video）一直有**，
`BGM_DUCK_LU=14` 还是老板 2026-08-16 对着成片实听调下来的。
**只有字卡线漏接了。**⚠️ 这正是 `BGM_DUCK_LU` 注释里写的那条教训的第二次现身：
**「修复只落在他点名的那个形态上」** ⇒ 同一个老板在另一个形态上又听到一次同样的问题。
⇒ 本次接线**直接复用 `prepare_bgm`**，⛔ 不为字卡线另写一套混音——三条线必须同一个声音。

🔴 **默认开 ⇒ 整片渲染出的 mp4 就带 BGM 了**（2026-08-19 审稿代理在 kepu-B 上抓到，
与下游「out＝纯净底版／out-bgm＝带 BGM」的约定撞车）。**默认仍然保持开**，理由：
关掉的话明天新渲的片子又没有背景音 ⇒ **同一个投诉第三次**。

⚠️ **那个「纯净底版」的约定不需要一个 mp4 来承载**：
**纯净底版就是 `narration.mp3.wav`（口播原件）**，`remux()` 也正是从它出发重混的
（它显式拒绝拿成片音轨当口播）。⇒ ⛔ 别为了留底版再编一份无 BGM 的 mp4。

⚠️ **新渲的片子⛔ 不用再 remux**——它已经是成品。再 remux 一遍只是**白白多一次 AAC 编码**。
`--remux` 是给**已经渲完的存量片**用的。"""


def _mix_bgm(am, narr: Path, total: float, bgm: str, duck: float, tmp: Path):
    """把 BGM 备好并返回 (ready_wav, 口播 LUFS)；`bgm` 为空/None 表示不加。

    ⚠️ **⛔ 没有 sidechain**（助理 2026-08-18 提过"有人声段再压 4–6 dB"）：
    轮播线与微电影线用的都是**静态压 14 LU**，字卡线单独上 sidechain ＝ **三条线三个声音**，
    正是 `BGM_DUCK_LU` 注释警告过的事。要加就三条线一起加，⛔ 不在这里开分支。
    """
    if not bgm:
        return None, None
    narr_lufs = am.loudness_stats(narr)["i"]
    ready, _ = am.prepare_bgm(bgm, total, tmp, narration_lufs=narr_lufs, duck_db=duck)
    return ready, narr_lufs


def mux(html_name: str, out_name: str, bgm: str = BGM_DEFAULT,
        duck: float = None) -> str:
    """合帧 + 混音 + **母带响度归一**。分片渲完后由 wrapper 调这条路径收口。

    🩸 母带归一 2026-08-17 补：此前本线只把 narration 原样贴上去，成片响度就是 TTS 原始
    电平（−31 LUFS 量级），比平台常态低 15 dB ＝手机外放听不清。归一在**这一次编码里**做完
    （两遍法：先分析 narration 拿 measured_*，再带着测量值线性归一），⛔ 别改成先编 AAC 再补一遍。
    """
    am = _load_audio_master()
    duck = am.BGM_DUCK_LU if duck is None else duck
    fd = HERE / ("frames_" + Path(html_name).stem)
    out = HERE / out_name
    narr = HERE / ("narration.mp3.wav" if (HERE / "narration.mp3.wav").exists() else "narration.mp3")
    target = am.FORM_TARGETS["card"]
    pre = am.loudness_stats(narr, target=target)
    print(f"[master] 口播 {pre['i']:.2f} LUFS → 归一到 {target:g} LUFS "
          f"（提 {target - pre['i']:+.1f} dB）", file=sys.stderr, flush=True)
    n_frames = len(list(fd.glob("f*.png")))
    total = n_frames / FPS
    with tempfile.TemporaryDirectory() as td:
        ready, _ = _mix_bgm(am, narr, total, bgm, duck, Path(td))
        return _encode(am, fd, narr, ready, out, out_name, pre, target,
                       bgm_label=(f"{bgm}（压 {duck:g} LU）" if ready else ""))


def _encode(am, fd, narr, bgm_ready, out: Path, out_name: str, pre: dict, target: float,
            video_src: Path = None, bgm_label: str = "") -> str:
    """最后一次编码：视频（帧目录或已成片）＋ 口播（＋BGM）→ 母带归一 → 自检。

    🔴 **BGM 与母带归一必须在同一次编码里**：先编好口播再补一遍 BGM ＝ 二次编码，
    而且母带量的就不是最终音轨了（**量具与被量对象差一层**）。
    """
    # 🩸 **输入段只放 `-i`，编码选项一律留到所有输入之后**：ffmpeg 把 `-i` 之前的选项
    # 当成**下一个输入的**选项 ⇒ `-i a.mp4 -c:v copy -i b.wav` 里的 `-c:v copy` 被当成
    # b.wav 的输入选项，退出码 8。⚠️ 命令行拼错不会写出一个坏文件，它直接失败——
    # 但**失败信息在 stderr 里，而这一行原本 capture_output=True 把它吞了**，
    # 看到的只有 "returned non-zero exit status 8"（见下方 _run_ffmpeg）。
    vin = (["-i", str(video_src)] if video_src else
           ["-framerate", str(FPS), "-i", str(fd / "f%05d.png")])
    vopt = (["-c:v", "copy"] if video_src else
            ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19", "-preset", "medium"])
    if bgm_ready:
        # ⚠️ normalize=0 是关键：否则 amix 把口播+BGM 各压低 ~6dB（compose_video 实测过的 bug）。
        # BGM 已由 prepare_bgm 归一到「口播 − duck」并铺满/淡化，这里直接混，⛔ 不再调音量。
        # duration=first ⇒ 以口播为准；BGM 已按 total 裁好，⛔ 不会反过来截视频。
        af = ["-filter_complex",
              f"[1:a][2:a]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
              f"{am.loudnorm_filter(pre, target=target)}[a]",
              "-map", "0:v", "-map", "[a]"]
        ain = ["-i", str(narr), "-i", str(bgm_ready)]
    else:
        af = ["-af", am.loudnorm_filter(pre, target=target)]
        ain = ["-i", str(narr)]
    _run_ffmpeg([
        "ffmpeg", "-y", *vin, *ain, *af, *vopt,
        # -ar/-ac 必须显式给：loudnorm 内部按 192kHz 工作，不指定会把音轨留在 192k（A3 口径 48k/双声道）
        "-ar", str(am.SR), "-ac", "2", "-c:a", "aac", "-b:a", am.BITRATE,
        # 🩸 **⛔ 不用 `-shortest`**（2026-08-18 审稿代理实证，12 条全中）：
        # 它让输出取**最短的流**＝音频长，而视频比音频长 `TAIL`（末屏定格 1.4s）
        # ⇒ **TAIL 被整个截掉**：落款只淡入 40–47%（末帧不透明度 63–72%、基本读不出），
        #    末屏「12356」念完立刻黑、**没有定格**。
        # ⇒ 去掉它，输出取**最长流＝视频**，音频结束后自然静音，末屏定格与落款都完整。
        # ⚠️ 只要 `total = end + TAIL` 这条不变，视频必然比音频长，⛔ 不会反过来截视频。
        "-movflags", "+faststart", str(out),
    ])
    v = am.verify_master(out, target=target)
    for label, passed, why in v["checks"]:
        print(f"  {'✅' if passed else '❌'} {label}" + ("" if passed else f" —— {why}"),
              file=sys.stderr, flush=True)
    if not v["passed"]:
        raise RuntimeError("母带响度自检不过（见上方 ❌ 行）——⛔ 这条片子别发，先查归一链路。")
    # 🔴 **两种状态都要打出来**：「带 BGM」与「不带 BGM」必须在成品信息里分得开。
    # 🩸 v2.18.0 把 BGM 默认改成开，**波及所有既有调用方的产物内容，而它们不知道**
    # ⇒ 2026-08-19 审稿代理发现 kepu-B 的 out.mp4 里混进了 BGM，
    #    与下游「out＝纯净底版」的约定撞车。⚠️ 改默认值时**光写 CHANGELOG 不够**，
    #    得让**每一次产出**自己说清它是什么。
    print(f"✅ {out_name} {out.stat().st_size/1048576:.1f}MB "
          f"({v['measured_lufs']:.2f} LUFS / {v['measured_tp']:.2f} dBTP)"
          f"｜{f'背景音 {bgm_label}' if bgm_label else '⛔ 无背景音'}", flush=True)
    return str(out)


def remux(src_mp4: str, out_name: str, bgm: str = BGM_DEFAULT, duck: float = None) -> str:
    """**对已成片重混**：抽视频流原样 copy，重新混口播＋BGM 并重做母带归一。⛔ 不重渲帧。

    🩸 用途：老板 2026-08-18 说 12 条成片「都没有背景音」——那批帧早删了
    （`sweep_frames` 渲完即清），重渲 12 条要 70 分钟，重混只要几分钟。

    ⚠️ **与 `--mux-only` 不是一回事**：`--mux-only` 是「分片渲完后从**帧目录**收口」，
    ⛔ 没改它的语义——改会动到分片渲染那条在产路径。
    """
    am = _load_audio_master()
    duck = am.BGM_DUCK_LU if duck is None else duck
    src = HERE / src_mp4
    if not src.is_file():
        raise RuntimeError(f"要重混的成片不存在：{src}")
    out = HERE / out_name
    if out.resolve() == src.resolve():
        raise RuntimeError(f"⛔ 重混的输出不能覆盖输入（{out_name}）——"
                           f"ffmpeg 边读边写会把源片写坏，且**坏了就没有原件了**")
    narr = HERE / ("narration.mp3.wav" if (HERE / "narration.mp3.wav").exists() else "narration.mp3")
    if not narr.is_file():
        raise RuntimeError(f"重混要口播原件，没找到：{narr}\n"
                           f"⛔ 别拿成片里的音轨当口播——它已经归一过、还可能已经混了 BGM")
    target = am.FORM_TARGETS["card"]
    pre = am.loudness_stats(narr, target=target)
    total = _video_seconds(src)
    print(f"[remux] {src.name} {total:.2f}s ｜口播 {pre['i']:.2f} LUFS ｜BGM {bgm or '（无）'}",
          file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory() as td:
        ready, _ = _mix_bgm(am, narr, total, bgm, duck, Path(td))
        return _encode(am, None, narr, ready, out, out_name, pre, target, video_src=src,
                       bgm_label=(f"{bgm}（压 {duck:g} LU）" if ready else ""))


def _video_seconds(path: Path) -> float:
    """成片时长（**读 ffprobe，⛔ 不按帧数估**——重混对的是这条片子的真实长度）。"""
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True, timeout=120)
    try:
        return float((p.stdout or "").strip())
    except ValueError:
        raise RuntimeError(f"读不到 {path.name} 的时长：{(p.stderr or '')[-300:]}")


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
    ap.add_argument("html", nargs="?", help="模板 HTML（相对本脚本所在目录）；--remux 时不需要")
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
    ap.add_argument("--remux", nargs=2, metavar=("源.mp4", "输出.mp4"),
                    help="**对已成片重混**背景音＋口播并重做母带归一，⛔ 不重渲帧。"
                         "⚠️ 与 --mux-only 不同：那个是从帧目录收口，这个是从成片抽视频流。"
                         "🩸 源与输出都写在这里、⛔ 不借位置参数——借了的话 "
                         "`--remux a.mp4 b.mp4` 会把 b.mp4 当成 html，"
                         "报出来的却是「需要 out 参数」，**把用法错说成缺参数**")
    ap.add_argument("--bgm", default=BGM_DEFAULT,
                    help=f"背景音：auto＝gen_bgm.py 纯合成（默认，零版权），或给音频文件路径。"
                         f"⛔ 别把默认值改成某个下载来的文件")
    ap.add_argument("--no-bgm", action="store_true", help="不加背景音（出纯口播片）")
    ap.add_argument("--bgm-duck", type=float, default=None,
                    help="BGM 低于口播多少 LU（默认走 audio_master.BGM_DUCK_LU＝14，"
                         "老板 2026-08-16 实听调定）。⚠️ 改它要重新实听，⛔ 别凭「听起来应该」拧")
    ap.add_argument("--keep-frames", action="store_true",
                    help="渲完保留帧目录（调试用）。⚠️ 默认**成片确认可读后自动删**——"
                         "一条 3–6 分钟口播的帧是 12–25GB，磁盘共享，撑爆会连累别条线")
    a = ap.parse_args(argv)

    if a.remux:
        remux(a.remux[0], a.remux[1], bgm=("" if a.no_bgm else a.bgm), duck=a.bgm_duck)
        return 0
    if not a.html:
        ap.error("需要 html 参数（除非用 --remux）")
    if a.verify_frames:
        return verify_frames(a.html, a.expect)
    if a.mux_only:
        if not a.out:
            ap.error("--mux-only 需要 out 参数")
        mux(a.html, a.out, bgm=("" if a.no_bgm else a.bgm), duck=a.bgm_duck)
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

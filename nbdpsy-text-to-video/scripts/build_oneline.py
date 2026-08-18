#!/usr/bin/env python3
"""一行字卡（tpl-oneline）实例化 + 单行硬闸门。

  build_oneline.py --cues narration.mp3.cues.json --bg miwen --canvas 3:4 --out 工作目录/

产出 `<out>/card-oneline.html`（连同 gsap.min.js、字体一并就位），随后照常：

  cd 工作目录 && python3 render_card.py card-oneline.html out.mp4

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🩸 **12 字是本脚本的排版量具，⛔ 不是写稿阶段的字数上限**（2026-08-17 老板令）。
   老板原话：「不要为了缩减字数而刻意删减。把事情说清楚才是第一位」。
   写稿只管把事说清楚（判据走 references/narration-spec.md），**拆屏是本脚本的事**；
   放不下就多一屏——**屏数变多是可以的；为了少几屏而把话说半截，不可以。**

本版式的命门是**单行**：一屏一行 ≤12 字，绝不折行、绝不缩字号。
所以这里有两道闸，缺一不可：

  ① 字数闸（本脚本，确定性）：把每句按标点切段；仍超长的段落找软断点再切；
     切不开就**拒绝出片**，并报出是哪一句、建议在第几个字后加逗号。
  ② 像素闸（--check，默认开）：把成品页开进 Chromium 实测每屏渲染宽度。
     ①算的是"几个字"，②量的是"多少像素"——数字、字母、标点的实际宽度只有②知道。

⛔ 闸门报红时的唯一正解是**断句**（加逗号 / 把长句拆成两句）——同一个意思拆到两屏上去。
   调小字号 = 废掉这个版式；**删掉一个论据 = 拿排版理由伤内容，同样禁止**。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import argparse, json, re, shutil, sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_style  # noqa: E402  风格档案（kind=video / form=card）→ 命令行默认值

HERE = Path(__file__).parent
TPL_DIR = HERE.parent / "assets" / "card-templates"
TPL = TPL_DIR / "tpl-oneline.html"

# 版式表。⛔ 默认仍是 oneline——加新版式**不改任何既有默认行为**（在产片子用着它）。
# tpl-paragraph：段落字卡，2026-08-18 老板 G13「模板要撑得住 3 分钟」新立。
#   它与 oneline 共用整条数据管线（断句/像素闸/字体闸），差别只在动效编排层。
TEMPLATES = {
    "oneline":   TPL_DIR / "tpl-oneline.html",
    "paragraph": TPL_DIR / "tpl-paragraph.html",
}
FONT = "ZCOOLKuaiLe-Regular.ttf"
DEPS = ["gsap.min.js", FONT]

# ────────────────────────── 画幅档（加档＝加一条，不动规则） ──────────────────────────
# max_chars 两档默认 12——版式规则不是画幅参数，⛔ 更不是写稿字数上限（见文件头）。
# --max-line-chars 可调 8–14（书名场景 13）：
# 整片统一按「N 个字必须装进安全区」反推字号（font = safe_w/(N+0.34)），⛔ 这不是按行缩字——
# 按行缩字（哪行装不下缩哪行）仍然绝对禁止，闸门语义不变：超上限拒渲染。
# 校验：font*max + 2*stroke ≤ w - 2*pad
CANVAS = {
    "3:4":  dict(w=1080, h=1440, font=80,  pad=40,  max_chars=12, rise=20,
                 brand_px=30, brand_bottom=118),
    "16:9": dict(w=1920, h=1080, font=130, pad=150, max_chars=12, rise=26,
                 brand_px=40, brand_bottom=84),
}

# ────────────────────────── 背景档（加档＝加一组参数，不动规则） ──────────────────────────
# turb: SVG feTurbulence 颗粒（podcast 主题已验证的范式）。freq 越小颗粒越粗。
# 两条踩过的坑，别再走回去（2026-08-16 量具实证，量法见 spec 专节）：
#   ⛔ feDiffuseLighting 浮雕：本尺度下只出平滑渐变，背景区高通标准差 0.92 = 等于没纹理；
#   ⛔ feTurbulence 不去色：出的是 RGB 彩色噪点，看着像彩电雪花不像纸，
#      必须跟一道 feColorMatrix saturate=0。
BG = {
    "liaoyu": dict(  # 疗愈：暖米白，细颗粒纸纹
        label="疗愈（暖米白纸纹）",
        base="#E8D8C4", ink="#26201A",
        vignette="rgba(108,84,56,.20)", brand="rgba(90,72,52,.50)",
        tex_opacity=1.0, tex_scale=240,
        turb=dict(freq=0.80, octaves=4, seed=7, alpha=0.55),
    ),
    "kepu": dict(    # 科普：冷白，较粗折痕
        label="科普（冷白皱纸）",
        base="#EDEFF1", ink="#141C26",
        vignette="rgba(30,44,62,.16)", brand="rgba(60,76,96,.50)",
        tex_opacity=1.0, tex_scale=300,
        turb=dict(freq=0.32, octaves=5, seed=23, alpha=0.62),
    ),
    # 🔴 老板 2026-08-17 G10 批复的 B 档（浅米白·强纹理），字卡的现行首选背景。
    # 七个字段是运营线交出来的**原值**，⛔ 别凭观感重调——老板批的是那一张图，重调出来的是另一张。
    # 尤其 seed=17：换个 seed 就是另一张纹理，它不是随便填的数。
    # 校准图：seo-geo/content/videos/oneline-qiuqiu-jianyao/bg-candidates/B-浅米白-强纹理.png
    # ⚠️ 拿校准图做像素比对前先读 spec 的口径提醒：那图出自候选预览页（纹理层没有 multiply），
    #    比真模板出片更浅更淡，直接比像素会得出「没搬对」的错结论。
    "miwen": dict(  # 浅米白，强纹理（暖调压角）
        label="米纹（浅米白·强纹理）",
        base="#F0E9DC", ink="#241E17",
        vignette="rgba(120,98,70,.18)", brand="rgba(90,72,52,.50)",
        tex_opacity=1.0, tex_scale=320,
        turb=dict(freq=0.24, octaves=5, seed=17, alpha=0.85),
    ),
}

# ────────────────────────── 断句词表 ──────────────────────────
# 硬断点：标点，一律断，且**不上屏**（对标片的屏显文字不带标点）。
HARD = set("，。！？；：、…—,.!?;:")
# 屏显要丢掉的成对符号（口播稿本就禁直接引语，这里只是兜底）
DROP = set("「」『』“”‘’\"'（）()《》〈〉【】[]{}")
# 软断点：段落无标点又超长时才启用。只认"下一段以它开头"或"上一段以它结尾"。
SOFT_HEAD = ("然后", "所以", "因为", "其实", "真正", "根本", "反而", "只是", "而是", "不是",
             "而且", "并且", "如果", "除非", "直到", "一旦", "可能", "应该", "已经", "正在",
             "后来", "现在", "以后", "之后", "之前", "我们", "你们", "他们", "很多", "有的",
             "是", "在", "把", "被", "让", "给", "从", "对", "跟", "和", "与", "就", "都",
             "才", "也", "还", "又", "却", "而", "但", "并", "不", "没", "要", "会", "能",
             "可", "比", "像", "为", "由", "到", "往", "向", "再", "更", "最", "这", "那")
SOFT_TAIL = ("的", "了", "着", "过", "们", "时", "后")
MIN_SOFT = 3      # 软断点切出来的碎片不得短于此（避免"都被""而是"这种孤儿行）
MIN_SEC = 1.0     # 单屏建议下限；低于此只告警（字数上限决定了它并不下去，只能改稿）


# ────────────────────────── 宽度口径 ──────────────────────────

def units(s: str) -> float:
    """屏显宽度，单位＝一个全角字。ASCII 按 0.6 折算（真宽度由像素闸负责兜底）。"""
    return sum(0.6 if ord(c) < 128 else 1.0 for c in s)


def display(s: str) -> str:
    return "".join(c for c in s if c not in HARD and c not in DROP).strip()


# ────────────────────────── 软断点 ──────────────────────────

def soft_ok(seg: str, i: int) -> bool:
    """在 seg 的第 i 个字之前断开是否算合法软断点。"""
    return seg[i:].startswith(SOFT_HEAD) or seg[:i].endswith(SOFT_TAIL)


def soft_split(seg: str, cap: int):
    """把无标点长段切成每片 ≤cap 的若干片，只许在软断点处下刀。

    返回片列表；切不开返回 None。优先片数最少，同片数取长度最匀的那种切法。
    """
    n = len(seg)
    best = {n: (0, 0.0, None)}   # 位置 -> (片数, 长度方差, 下一刀位置)

    def solve(i):
        if i in best:
            return best[i]
        best[i] = None            # 占位防环
        res = None
        for j in range(i + MIN_SOFT, min(n, i + cap) + 1):
            if units(seg[i:j]) > cap:
                break
            if j < n:
                if n - j < MIN_SOFT or not soft_ok(seg, j):
                    continue
            sub = solve(j)
            if sub is None:
                continue
            cand = (sub[0] + 1, sub[1] + (len(seg[i:j]) - cap / 2) ** 2, j)
            if res is None or cand[:2] < res[:2]:
                res = cand
        best[i] = res
        return res

    sys.setrecursionlimit(max(2000, n * 4))
    if solve(0) is None:
        return None
    out, i = [], 0
    while i < n:
        j = best[i][2]
        out.append(seg[i:j])
        i = j
    return out


def suggest(seg: str, cap: int):
    """给切不开的段落挑 3 个"在这儿加个逗号就行"的位置。"""
    cands = []
    for p in range(MIN_SOFT, len(seg) - MIN_SOFT + 1):
        left, right = seg[:p], seg[p:]
        # 加了这一刀之后，两边各自还能不能被自动处理（≤cap 或还能软切）
        ok = all(units(x) <= cap or soft_split(x, cap) for x in (left, right))
        cands.append((0 if ok else 1, abs(units(left) - units(seg) / 2), p))
    cands.sort()
    return [f"{seg[:p]}｜{seg[p:]}" for _, _, p in cands[:3]]


# ────────────────────────── 闸门主体 ──────────────────────────

def split_cue(text: str, cap: int):
    """一句 → 若干屏。返回 (屏文本, 失败清单, 软断记录)。失败清单非空即拒渲染。

    软断（在没有标点的地方下刀）是**兜底不是常态**：它一定会被登记出来给人看一眼，
    ⛔ 绝不静默——断点断得对不对只有写稿的人说了算。
    """
    parts = [p for p in re.split("[" + re.escape("".join(HARD)) + "]", text)]
    screens, fails, softs = [], [], []
    for raw in parts:
        seg = display(raw)
        if not seg:
            continue
        if units(seg) <= cap:
            screens.append(seg)
            continue
        pieces = soft_split(seg, cap)
        if pieces is None:
            fails.append(dict(seg=seg, chars=units(seg), suggest=suggest(seg, cap)))
            screens.append(seg)      # 占位，好让报告里看得见它排在第几屏
        else:
            softs.append(dict(seg=seg, pieces=pieces))
            screens.extend(pieces)
    return screens, fails, softs


def weight(s: str, is_seg_end: bool) -> float:
    """配时权重：字数 + 段末标点的那口气（逗号≈1.6 个字的停顿）。"""
    return units(s) + (1.6 if is_seg_end else 0.0)


def build_screens(cues, cap):
    """cues → 屏序列（含起止时刻）。句边界＝屏边界（零估算）；句内按权重分配。"""
    out, fails, warns = [], [], []
    for ci, c in enumerate(cues):
        texts, f, softs = split_cue(c["text"], cap)
        for x in f:
            x["cue"] = ci
            x["cue_text"] = c["text"]
        fails.extend(f)
        for s in softs:
            warns.append(f"第 {ci + 1} 句在无标点处自动软断：{'｜'.join(s['pieces'])}"
                         f"（断点归写稿人裁决，认可就把逗号补进稿子）")
        if not texts:
            continue
        ws = [weight(t, i == len(texts) - 1) for i, t in enumerate(texts)]
        span, tot = c["end"] - c["start"], sum(ws) or 1.0
        t = c["start"]
        for i, (txt, w) in enumerate(zip(texts, ws)):
            end = c["end"] if i == len(texts) - 1 else t + span * w / tot
            out.append(dict(text=txt, start=round(t, 3), end=round(end, 3), cue=ci))
            if end - t < MIN_SEC:
                warns.append(f"第 {len(out)} 屏「{txt}」仅 {end - t:.2f}s（建议 ≥{MIN_SEC}s）")
            t = end
    return out, fails, warns


# ────────────────────────── 实例化 ──────────────────────────

def paper_url(t):
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'>"
        f"<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='{t['freq']}' "
        f"numOctaves='{t['octaves']}' seed='{t['seed']}'/>"
        "<feColorMatrix type='saturate' values='0'/></filter>"
        f"<rect width='240' height='240' filter='url(#n)' opacity='{t['alpha']}'/></svg>"
    )
    return 'url("data:image/svg+xml,' + quote(svg, safe="") + '")'


def apply_max_chars(cv: dict, max_chars: int) -> dict:
    """按单行上限反推字号：font*(N+0.34) ≤ safe_w（0.34=两侧描边 0.17*2）。
    默认 12 时保持画幅档原字号；调大上限时整片统一缩放，绝不按行缩。"""
    cv = dict(cv)
    if max_chars != cv["max_chars"]:
        safe_w = cv["w"] - 2 * cv["pad"]
        cv["font"] = min(cv["font"], int(safe_w / (max_chars + 0.34)))
        cv["max_chars"] = max_chars
    return cv


def instantiate(screens, cv, bg, bg_name, tpl=None, sec_cues=3):
    stroke = round(cv["font"] * 0.17)
    safe_w = cv["w"] - 2 * cv["pad"]
    need = cv["font"] * cv["max_chars"] + 2 * stroke
    if need > safe_w:
        sys.exit(f"❌ 画幅档 {cv['w']}x{cv['h']} 自相矛盾：{cv['max_chars']} 字需 {need}px > 安全区 {safe_w}px。"
                 f"\n   改 CANVAS 里的 font/pad，⛔ 别改 max_chars 之外的运行期逻辑。")
    sub = {
        "__CANVAS__": f"{cv['w']}x{cv['h']}", "__W__": cv["w"], "__H__": cv["h"],
        "__FONT_PX__": cv["font"], "__STROKE_PX__": stroke, "__SAFE_W__": safe_w,
        "__RISE__": cv["rise"], "__BRAND_PX__": cv["brand_px"],
        "__BRAND_BOTTOM__": cv["brand_bottom"], "__TEX_SCALE__": bg["tex_scale"],
        "__BASE__": bg["base"], "__INK__": bg["ink"], "__VIGNETTE__": bg["vignette"],
        "__BRAND_COLOR__": bg["brand"], "__TEX_OPACITY__": bg["tex_opacity"],
        "__PAPER_URL__": paper_url(bg["turb"]), "__BG_NAME__": bg_name,
        "__SCREENS__": json.dumps(screens, ensure_ascii=False),
        # 段落字卡专用；oneline 模板里没有这个占位符，填了也不会有副作用
        "__SEC_CUES__": sec_cues,
    }
    html = (tpl or TPL).read_text(encoding="utf-8")
    for k, v in sub.items():
        html = html.replace(k, str(v))
    left = re.findall(r"__[A-Z_]+__", html)
    if set(left) - {"__CUES__"}:      # __CUES__ 归 render_card.py 填
        sys.exit(f"❌ 模板还有没填的占位符：{sorted(set(left) - {'__CUES__'})}")
    return html


def pixel_check(path: Path):
    """像素闸：真开一次浏览器量每屏宽度。字数闸算不准的（数字/字母/标点）由它兜。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--force-device-scale-factor=1", "--hide-scrollbars"])
        pg = b.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        # 量宽度不依赖 cues，占位符塞个最小合法值即可
        probe = path.with_suffix(".check.html")
        probe.write_text(path.read_text(encoding="utf-8").replace("__CUES__", "[]"), encoding="utf-8")
        pg.goto(f"file://{probe.resolve()}")
        try:
            pg.wait_for_function("window.ONELINE_REPORT !== undefined", timeout=20000)
            rep = pg.evaluate("window.ONELINE_REPORT")
        except Exception as e:
            b.close()
            sys.exit(f"❌ 像素闸打不开页面（{type(e).__name__}）。页面错误：{errs[:3]}\n"
                     f"   十有八九是 gsap.min.js 或字体没跟着落到同一目录。")
        b.close()
        probe.unlink()
    if errs:
        print(f"⚠️ 页面错误：{errs[:3]}", file=sys.stderr)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="一行字卡实例化（含单行硬闸门）")
    ap.add_argument("--cues", required=True, help="tts_gen --timed 产出的 *.cues.json")
    # --bg / --canvas 不用 required=True：风格档案（--style）也能给。缺了照旧报错退出，
    # 只是把「argparse 报缺参数」换成下面那句人话——⛔ 绝不给它们编一个默认值悄悄出片
    ap.add_argument("--bg", choices=sorted(BG))
    ap.add_argument("--canvas", choices=sorted(CANVAS))
    ap.add_argument("--out", required=True, help="工作目录（card-oneline.html 落这里）")
    ap.add_argument("--max-line-chars", type=int, default=12,
                help="单屏排版拆屏上限（8–14，默认 12；书名场景可 13——整片按安全区统一反推字号，非按行缩字）。"
                     "⛔ 这是排版量具，不是写稿字数上限：写稿只管把事说清楚，装不下就多一屏")
    ap.add_argument("--template", choices=sorted(TEMPLATES), default="oneline",
                help="版式：oneline＝一行字卡（默认，每屏同一动效，刻意极简）｜"
                     "paragraph＝段落字卡（段内统一、段间变化，为 3 分钟以上长片而立）")
    ap.add_argument("--sec-cues", type=int, default=6,
                help="paragraph 版式：每几句算一段（默认 6）。段落边界只落在句边界上，"
                     "⛔ 不在一句话中间换手法。"
                     "⚠️ 默认值有实测依据，⛔ 别凭感觉调：真稿 68 句/185s 实测——"
                     "3→23 段(每段 6.7s，换手法太频繁)｜6→12 段(12.9s)｜9→8 段(19.4s，沉稳)。"
                     "口播语速真值约 3.5 汉字/秒，据此可换算自己稿子的段落时长")
    ap.add_argument("--name", default="card-oneline.html")
    ap.add_argument("--no-check", action="store_true", help="跳过像素闸（⛔ 出片前别用）")
    a = video_style.apply(ap, "card", argv)
    missing = [f"--{k}" for k in ("bg", "canvas") if getattr(a, k) is None]
    if missing:
        sys.exit(f"❌ 缺 {' 和 '.join(missing)}：命令行给，或用 --style 喂一套带 oneline 段的"
                 f"字卡风格档案（style_profile.py --get --form card）")

    cues = json.load(open(a.cues, encoding="utf-8"))
    if isinstance(cues, dict):
        cues = cues.get("cues", cues)
    if not 8 <= a.max_line_chars <= 14:
        sys.exit(f"❌ --max-line-chars 只收 8–14，收到 {a.max_line_chars}")
    cv, bg = apply_max_chars(CANVAS[a.canvas], a.max_line_chars), BG[a.bg]

    screens, fails, warns = build_screens(cues, cv["max_chars"])

    if fails:
        print(f"\n❌ 单行闸门拒绝出片：{len(fails)} 处断不开的超长句（上限 {cv['max_chars']} 字/屏）\n",
              file=sys.stderr)
        for f in fails:
            print(f"  · 第 {f['cue'] + 1} 句：{f['cue_text']}", file=sys.stderr)
            print(f"    断不开的片段：「{f['seg']}」（{f['chars']:.1f} 字）", file=sys.stderr)
            for s in f["suggest"]:
                print(f"    建议断点：{s}", file=sys.stderr)
            print("", file=sys.stderr)
        print("处置：在建议位置加逗号或把句子拆成两句，重跑 tts_gen --timed 后再来。\n"
              "⛔ 不要调小字号——字号是这个版式的身份，缩了就没有这个版式了。\n"
              "⛔ 也不要把话删短——12 字是排版量具不是写稿上限。同一个意思拆成两屏＝对；\n"
              "   删掉一个论据把话说半截＝错。屏数变多是可以的（2026-08-17 老板令）。",
              file=sys.stderr)
        return 1

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for dep in DEPS:
        dst = out_dir / dep
        if not dst.exists():
            shutil.copy(TPL_DIR / dep, dst)
    html_path = out_dir / a.name
    html_path.write_text(
        instantiate(screens, cv, bg, a.bg, TEMPLATES[a.template], a.sec_cues),
        encoding="utf-8")

    n_over = sum(1 for s in screens if units(s["text"]) > cv["max_chars"])
    print(f"✅ {html_path}")
    print(f"   {a.canvas} {cv['w']}x{cv['h']} · {bg['label']} · 字号 {cv['font']}px · "
          f"上限 {cv['max_chars']} 字/屏")
    print(f"   {len(cues)} 句 → {len(screens)} 屏，最长 {max(units(s['text']) for s in screens):.0f} 字，"
          f"超限 {n_over} 屏")
    for w in warns:
        print(f"   ⚠️ {w}")

    if not a.no_check:
        rep = pixel_check(html_path)
        if rep["overflow"]:
            print(f"\n❌ 像素闸拒绝出片：{len(rep['overflow'])} 屏实测超宽（字数闸没算准，多半是数字/字母）",
                  file=sys.stderr)
            for o in rep["overflow"]:
                print(f"  · 第 {o['i'] + 1} 屏「{o['text']}」{o['width']}px > 安全区 {o['limit']}px",
                      file=sys.stderr)
            return 1
        print(f"   ✅ 像素闸：{rep['screens']} 屏全部在安全区内，总时长 {rep['total']:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

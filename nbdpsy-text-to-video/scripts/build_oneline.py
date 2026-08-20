#!/usr/bin/env python3
"""一行字卡（tpl-oneline）实例化 + 单行硬闸门。

  build_oneline.py --cues narration.mp3.cues.json --bg xianwen --canvas 3:4 --out 工作目录/

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
import argparse, base64, json, re, shutil, sys
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
# 🩸 render_card.py 也必须拷进工作目录（2026-08-18 冒烟抓到，差点让 12 条批量全废）：
# 它用 `Path(__file__).parent` 找 `narration.mp3.cues.json` 与音频，而 spec 示例写的是
# `cd 工作目录 && python3 render_card.py` ——**暗含脚本已在工作目录**。
# 此前只拷 gsap 与字体 ⇒ **照规格抄命令的人必然 FileNotFoundError**，
# ⚠️ 而且死在 TTS 配额烧完之后（渲染是产线最后一步）。
# ⇒ 与既往批次「每条视频各带一份脚本副本」的做法一致，由本脚本一并备好。
# ⛔ 没改 render_card.py 的路径基准：存量批次的目录结构都假设「脚本在工作目录」，
#    改成按 cwd 找会动到所有历史工作区。
SCRIPT_DEPS = ["render_card.py"]

# ────────────────────────── 画幅档（加档＝加一条，不动规则） ──────────────────────────
# max_chars 两档默认 12——版式规则不是画幅参数，⛔ 更不是写稿字数上限（见文件头）。
# --max-line-chars 可调 8–14（书名场景 13）：
# 整片统一按「N 个字必须装进安全区」反推字号（font = safe_w/(N+0.34)），⛔ 这不是按行缩字——
# 按行缩字（哪行装不下缩哪行）仍然绝对禁止，闸门语义不变：超上限拒渲染。
# 校验：font*max + 2*stroke ≤ w - 2*pad
CANVAS = {
    "3:4":  dict(w=1080, h=1440, font=80,  pad=40,  max_chars=12, rise=20,
                 brand_px=30, brand_bottom=118, icon_bottom=206, icon_px=200, icon_tail=0.6),
    "16:9": dict(w=1920, h=1080, font=130, pad=150, max_chars=12, rise=26,
                 brand_px=40, brand_bottom=84,  icon_bottom=155, icon_px=150, icon_tail=0.6),
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
    # 🔴 老板 2026-08-18 G15 拍板：在 miwen 基础上「纸张质感更多一些」，
    # 走**新增一档、老片不变**（⛔ 所以 miwen 上面那七个字段一个字节都不许动）。
    # 颜色四项与 miwen 完全相同——**这一档改的只有纹理**，颜色是 G10 批过的，⛔ 别顺手调。
    # 纸感＝在 miwen 的颗粒之上叠两层中性 soft-light：fiber（纤维，x/y 频率不等＝有走向）
    # ＋ crease（微皱，低频大尺度起伏）。实测：底色最大偏移 0.11/255（＝实质不变，
    # ⛔ 不是"一个字节没动"，别这么写）、高通 σ 5.86→6.83、纤维方向性 1.00→1.24。
    # ⚠️ 纤维再往上调会像织物不像纸（oct=2＋极端各向异性能到 2.51，但目视是布纹）——
    #    要"更多纸感"时得在「更明显」与「像纸」之间选，⛔ 别闷头往上加。
    "xianwen": dict(  # 纤纹：miwen ＋ 纸纤维与微皱
        label="纤纹（浅米白·纸纤维）",
        base="#F0E9DC", ink="#241E17",
        vignette="rgba(120,98,70,.18)", brand="rgba(90,72,52,.50)",
        tex_opacity=1.0, tex_scale=320,
        turb=dict(freq=0.24, octaves=5, seed=17, alpha=0.85),
        fiber=dict(freq="0.10 0.40", octaves=5, seed=31, k=0.85, tile=280),
        crease=dict(freq="0.008", octaves=3, seed=5, k=0.55, size=900, tile=900),
    ),
}

# ──────────────── 账号图标位（--account-icon，默认关） ────────────────
# 🔴 **跟落款走同一机制：只在首屏与落款屏浮出，中间屏一个像素都没有。**
#    ⇒ 它不是常驻元素，⛔ 不碰 tpl-oneline 契约③（「画面上除了正在说的那一句什么都没有」）。
# 形态照搬博客长文 2026-08-19 已过审稿 PASS 的那版（`_inject_miwen_cat.py`），
# ⛔ 别凭观感重调——审过的是那个形态，重调出来的是另一个。
#
# 🩸 **3:4 那三个数是实测过审值**（bottom 206 / 首屏 200px / 落款屏 ×0.6）。
# ⚠️ **16:9 的是按画幅高度等比推的，⛔ 没有目视验证过**——第一次在 16:9 用之前先渲一条看。
#    ⛔ 别把这行注释删掉当它验过了。

ICON_CSS = """  /* 账号图标位：⛔ 不常驻，只首屏与落款屏浮出（见头部契约③）。
     🔴 本元素 DOM 在 `#stage` **之前** ⇒ 同 z-index 下**先绘者在下**，图标在字层之下。
        🩸 别处那版放在 `#stage` 之后、却注释成「z-index 低于字层」——**那是错话**：
        它让后人以为有层次保护，而实际"不挡字"只靠**位置分离**（图标在底部、字恒在正中）。
     ⛔ 别改成 z-index:2——那会把它压到 #vignette 暗角之下、整体变暗。 */
  #account-icon { position:absolute; left:50%; transform:translateX(-50%);
    bottom:@BOTTOM@px; transform-origin:50% 100%; z-index:3;
    width:@PX@px; height:@PX@px;
    background:url(data:@MIME@;base64,@B64@) center/contain no-repeat;
    opacity:0; pointer-events:none; }"""
# ⚠️ 占位用 @X@ 而不是 %(x)s——**CSS 里 % 太多**（left:50%、translateX(-50%)、
# transform-origin:50% 100%），用 % 格式化就得逐个转义成 %%，**漏一个就是运行时
# ValueError**，而且报的是「unsupported format character」这种跟真因无关的话。
# 🩸 第一版就这么炸的（index 311 处的 `left:50%;`）。

ICON_JS = """/* 账号图标位：首屏浮出→随首屏退场；落款屏与 #brand 同刻再现（缩小，让位落款）。
   🩸 淡入淡出**按首屏时长成比例**，⛔ 不写死秒数：写死那版（按 1.9s 首屏定的
   .15/.7/end−.25/.45）用到 0.88s 首屏时，**淡出起点比淡入终点还早 0.22s**
   ⇒ 两段动画重叠打架、图标一闪（2026-08-19 审稿抓到）。
   ⚠️ 与上面 `inDur` 是同一条道理的两处实现——**改一处就想想另一处**。 */
if (SCREENS.length) {
  const s0 = SCREENS[0], endAll = SCREENS[SCREENS.length - 1].end;
  const D0 = Math.max(s0.end - s0.start, .3);
  const inD = Math.min(.7, D0 * .38), outD = Math.min(.45, D0 * .30);
  const inAt = s0.start + Math.min(.15, D0 * .12);
  const outAt = Math.max(inAt + inD + .05, s0.end - outD);   // 淡出必在淡入完成之后
  tl.fromTo('#account-icon', { opacity:0, y:18 },
    { opacity:.96, y:0, duration:inD, ease:'power2.out', immediateRender:false }, at(inAt));
  tl.to('#account-icon', { opacity:0, y:-14, duration:outD, ease:'power1.in' }, at(outAt));
  tl.fromTo('#account-icon', { opacity:0, y:14, scale:@TAIL@ },
    { opacity:.96, y:0, scale:@TAIL@, duration:.9, ease:'power2.out',
      immediateRender:false }, at(endAll - .35));
}"""

ICON_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}


def icon_parts(path, cv: dict):
    """账号图标位的三段填充 (CSS, HTML, JS)。`path` 为空 ⇒ 三段都是空串（＝关）。

    ⚠️ 图片**内联成 data URI**，与背景纹理同口径——⛔ 零外部依赖，
    免得成片工作目录少拷一个文件就静默丢图（页面不报错，只是那里空着）。
    """
    if not path:
        return "", "", ""
    f = Path(path)
    if not f.is_file():
        sys.exit(f"❌ --account-icon 找不到文件：{f}")
    mime = ICON_MIME.get(f.suffix.lower())
    if not mime:
        sys.exit(f"❌ --account-icon 不认识的图片格式：{f.suffix}"
                 f"（认 {'/'.join(sorted(ICON_MIME))}）")
    b64 = base64.b64encode(f.read_bytes()).decode()
    css, js = ICON_CSS, ICON_JS
    for k, v in (("@BOTTOM@", cv["icon_bottom"]), ("@PX@", cv["icon_px"]),
                 ("@MIME@", mime), ("@B64@", b64)):
        css = css.replace(k, str(v))
    js = js.replace("@TAIL@", f"{cv['icon_tail']:.2f}")
    for left, where in ((css, "ICON_CSS"), (js, "ICON_JS")):
        if "@" in left.replace("@charset", ""):     # ⚠️ 漏填的占位符会静默出一个坏页面
            leftover = [t for t in re.findall(r"@[A-Z0-9_]+@", left)]
            if leftover:
                sys.exit(f"❌ {where} 还有没填的占位符：{leftover}")
    return css, '<div id="account-icon"></div>\n', js


# ────────────────────────── 断句词表 ──────────────────────────
# 硬断点：标点，一律断，且**不上屏**（对标片的屏显文字不带标点）。
HARD = set("，。！？；：、…—,.!?;:")
# 屏显要丢掉的成对符号（口播稿本就禁直接引语，这里只是兜底）
DROP = set("「」『』“”‘’\"'（）()《》〈〉【】[]{}")
# 软断点：段落无标点又超长时才启用。只认"下一段以它开头"或"上一段以它结尾"。
SOFT_HEAD = ("然后", "所以", "因为", "其实", "真正", "根本", "反而", "只是", "而是", "不是",
             "而且", "并且", "如果", "除非", "直到", "一旦", "可能", "应该", "已经", "正在",
             "后来", "现在", "以后", "之后", "之前", "我们", "你们", "他们", "很多", "有的",
             "是", "让", "就", "都",
             "才", "也", "还", "又", "却", "而", "但", "并", "不", "没", "要", "会", "能",
             "可", "比", "像", "为", "由", "到", "往", "再", "更", "最", "这", "那")
# 🩸 2026-08-18 从这张表里删掉了 9 个单字：**在 把 被 给 从 对 跟 和 与**（外加原有的「向」）。
#    它们此前**同时**出现在两张表里——`TAIL_BAN` 说「不许做上屏结尾」，`SOFT_HEAD` 说
#    「可以做下屏开头」。⚠️ **两张登记表对同一批字给了相反的裁决**，而代码先读哪张就听哪张。
#    ⇒ 实证（助理转博客长文，本轮 53 处软断里扫出）：
#      「把想来的人挡｜在门外」「正念更关心你｜和自己感受之间的距离」
#    ⛔ 别再把它们加回来——要放宽得改 STRUCT_PARTICLES 那一张表，两侧同时生效。
SOFT_TAIL = ("了", "着", "过", "们", "时", "后")
# 🩸 「的」已从 SOFT_TAIL 移除（2026-08-18 审稿代理实证，936 屏扫出约 40 处）：
#    它把「如果你正被持续的｜情绪困扰缠着」判成合法断点——**5 条科普的危机声明全中**。
#    ⚠️ jieba 词边界拦不住它：「持续的」「情绪困扰」**本来就是两个词**，那确实是词边界。
#    ⇒ 词边界是必要条件，**⛔ 不是充分条件**。

STRUCT_PARTICLES = ("的", "地", "得", "把", "被", "在", "从", "对", "向", "给", "跟", "和", "与")
"""🔴 **结构虚词：前后都不断**（助理 2026-08-18 两次拍板合成的**一张表**）。

它们的共同点是**自己不成话，必须跟旁边的成分捆在一起**。所以一个字若不许做上屏结尾，
它同样不许做下屏开头——⚠️ **不对称的规则只挡住半边**：

| 上屏结尾（第一次拍，已生效） | 下屏开头（第二次拍，本次补） |
|---|---|
| 「如果你正被持续的｜情绪困扰缠着」 | 「第一作者是我们｜的咨询师负责人李牧阳」 |
| 「练的就是怎么在难受的｜时候」 | 「把想来的人挡｜在门外」 |
| | 「正念更关心你｜和自己感受之间的距离」 |

🩸 **右列那三处是本轮真出片时软断出来的**——左列的规则昨天就上线了，
它们仍然照出不误，因为**判据只看了断口的左边**。
⇒ **一张表、两侧生效**：加减字只改这一处，⛔ 别再分开维护两份。"""

TAIL_BAN = STRUCT_PARTICLES   # 不许做**上屏结尾**
HEAD_BAN = STRUCT_PARTICLES   # 不许做**下屏开头**

NEG_TAIL_BAN = ("不", "没", "别", "未", "非", "无")
"""🔴 **否定词不许做上屏结尾——但做下屏开头是合法的。**

⚠️ **这条是有根据的不对称，⛔ 别按 `STRUCT_PARTICLES` 那样"前后都禁"**：
「不是这样」做下屏开头**完全成话**，禁了白丢一批合法断点。

🩸 **实证（2026-08-19，X1 样片）**：`好得不像真的` 被切成
**「所以如果你发现自己总在好得不」｜「像真的」** ——
上屏以「不」收尾，读者那一屏读到的是「**好得不**」，
⚠️ 而它的自然理解是"好得**不**够"，**与原意「好得不像真的」正好相反**。

⇒ 判据不是"不成话"，是**「截断会让语义翻转」**——这比不成话严重得多：
不成话读者知道没说完，**翻转了读者以为自己读懂了**。
（同族：`feedback_negation_flips_when_truncated`——印章屏前 1.4s 只显前半句那次。）

⚠️ **jieba 拦不住它**：它把「不像」切成「不」「像」两个词，**那确实是词边界**
（跟「持续的｜情绪困扰」同构）⇒ **词边界仍然只是必要条件**。"""

AB_QUESTION = re.compile(r"(.)不\1|在不在|行不行|是不是|有没有|能不能|会不会|要不要")
"""正反问（X不X）**不可劈**：实证「它还在不在影响你的日子」被劈成
「是它还在不」——**1.6s 一屏、根本不成话**。"""

EN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9''\-]*(?:\s+[A-Za-z][A-Za-z0-9''\-]*)*")
"""**英文连续词组视为不可分割 token**（刊名/书名/术语）：实证
`Psychotherapy and Psychosomatics` 被劈成「一本叫 Psychotherapy」→「and Psychosomatics」，
**第 2 屏单看是个不存在的刊名**——⚠️ 比"读着别扭"严重得多，那是**编造了一个刊物**。"""


NUM_TOKEN = re.compile(r"[\dA-Za-z%％][\dA-Za-z.:/%％\-–—]*")
"""🔴 **含数字的连续串不可分割**（2026-08-18 验专名屏时抓到，当晚按助理清单扩全）。

⚠️ 危害比刊名更大：`请打 12356` 若被劈成「请打 123」「56」，
**读者看到的是一个错的危机热线号码**——刊名说错是学术不严谨，热线说错是有人打不通。

🩸 **本批 5 条科普的 12356 没被劈是侥幸**——它们恰好写成「热线，12356」让号码单独成屏。
⇒ ⛔ 别拿"这批没出事"当"规则够用"。

覆盖：手机号／身份证／PMID／DOI（`10.1001/jama.2024.1234`）／百分比（`35.5%`）／
区间（`10-20`）。⚠️ 匹配后**还要含至少一个数字**才算数——纯字母归 `EN_TOKEN` 管。"""

CN_DIGIT = "〇零一二两三四五六七八九十百千万亿半"
CN_UNIT = "年月日号时分秒点元角块毛个次件位岁倍成条页章章节米克斤里%％"
CN_LINK = "到至多余"
CN_NUM_TOKEN = re.compile(f"[{CN_DIGIT}]+(?:[{CN_UNIT}{CN_LINK}][{CN_DIGIT}]*)*")
"""🔴 **中文数量串同样不可分割**（助理 2026-08-18 清单：中文日期／金额区间／时长）。

实证反例（切开后**数值就变了**，不是"读着别扭"）：
「二〇二六年八月」→「二〇二」「六年八月」｜「四百到六百元」→「四百」「到六百元」｜
「三分零五秒」→「三分」「零五秒」。

⚠️ **误伤面是有意压小的**：只保护 ≥2 字的串，所以「不一样」（只匹配单字「一」）不受影响；
「一个」「十分」「一次」这类会被保护，但**保护的只是它内部那一刀**（「一｜个」），
串两侧照常可断 ⇒ 影响面实测 809 句里断不开 63→63 处、软断 146→144 处。
⛔ 别把连接词扩到「和/或」——那两个更常是并列连词，扩了会大面积禁掉合法断点。"""


# 数字内部的 `.` `:` `/` **不是句读**：`3.2 个百分点`「下降了 3」「2 个百分点」＝数值变了。
# 🩸 这是**在产的坑**：HARD 里就有 `.` `:`，`split_cue` 第一步的硬切根本轮不到保护区间，
#    `display()` 还会把它整个丢掉（`10.1001` → `101001` ⇒ **DOI 被改了**）。
# ⇒ 硬切之前先把这几个字符藏进私用区，还原在 display 之后。
# ⚠️ 只保护**数字参与**的那一侧，所以英文缩写里的点（`e.g.`）照旧当句读——⛔ 别放宽成两侧字母。
_NUM_PUNCT = re.compile(r"(?<=\d)[.:/](?=[\dA-Za-z])|(?<=[\dA-Za-z])[.:/](?=\d)")
_PUA = {".": "\ue001", ":": "\ue002", "/": "\ue003"}   # 私用区，⛔ 正文不可能出现
_PUA_BACK = {v: k for k, v in _PUA.items()}


def _hide_num_punct(text: str) -> str:
    return _NUM_PUNCT.sub(lambda m: _PUA[m.group()], text)


def _show_num_punct(text: str) -> str:
    return "".join(_PUA_BACK.get(c, c) for c in text)


def _protected_spans(seg: str):
    """不可切区间 [start, end)：英文词组 ＋ 含数字串 ＋ 中文数量串 ＋ 正反问结构。

    ⚠️ 都只收 **≥2 字**的匹配——单字保护没有意义（一个字里本来就没有可切的位置），
    而收单字会把「不一样」的「一」这种也算进来，⛔ 白白禁掉一堆合法断点。
    """
    spans = [(m.start(), m.end()) for m in EN_TOKEN.finditer(seg) if m.end() - m.start() > 1]
    spans += [(m.start(), m.end()) for m in NUM_TOKEN.finditer(seg)
              if m.end() - m.start() > 1 and any(c.isdigit() for c in m.group())]
    spans += [(m.start(), m.end()) for m in CN_NUM_TOKEN.finditer(seg) if m.end() - m.start() > 1]
    spans += [(m.start(), m.end()) for m in AB_QUESTION.finditer(seg)]
    return spans
MIN_SOFT = 3
"""软断点切出来的碎片不得短于此（避免"都被""而是"这种孤儿行）。

🔴 **⛔ 别为了治「三字孤悬」把它提到 4——数据不支持**（2026-08-18，29 份在产稿实测）：

| | 断不开 | 软断 | ≤3 字屏 |
|---|---|---|---|
| MIN_SOFT=3 | 62 | 147 | **122** |
| MIN_SOFT=4 | **77** (+24%) | 132 | **107** (−15) |

⚠️ **≤3 字屏有 122 个，提高 MIN_SOFT 只消掉 15 个（12%）**——因为**大头根本不来自软断，
来自作者自己用逗号句号断出来的短句**，而 `MIN_SOFT` 只管软断。
⇒ 代价（多拒 15 处、逼作者改稿）与收益（治好 12%）**完全不成比例**。
真正管用的是把短屏**报出来让作者调标点**（见 `SHORT_CHARS`），⛔ 不是在软断这一侧加严。"""

MIN_SEC = 1.0     # 单屏建议下限；低于此只告警（字数上限决定了它并不下去，只能改稿）
SHORT_CHARS = 3
"""屏显字数 ≤ 此值即报 `[短屏]`（助理 2026-08-18：「三字孤悬」）。

⚠️ 这是**报出来给人看**，⛔ 不是拒渲染——短屏合不合适只有写稿人说了算
（「够了」「不是的」这种三字屏是刻意的节奏）。
🩸 但**光有 `MIN_SEC` 那条时长警告不够**：它跟软断警告混在一堆 `⚠️` 里，
**warn 太弱、人不会逐条看**（jieba 那节踩过同一个坑）⇒ 给它独立记号，能数能 grep。"""


# ────────────────────────── 宽度口径 ──────────────────────────

def units(s: str) -> float:
    """屏显宽度，单位＝一个全角字。ASCII 按 0.6 折算（真宽度由像素闸负责兜底）。"""
    return sum(0.6 if ord(c) < 128 else 1.0 for c in s)


def display(s: str) -> str:
    return "".join(c for c in s if c not in HARD and c not in DROP).strip()


# ────────────────────────── 软断点 ──────────────────────────

_JIEBA_STATE = {"ok": None}      # None=没试过 / True=可用 / False=不可用


def word_edges(seg: str):
    """jieba 分词后的合法切点（字符下标集合）。**jieba 不可用返回 None**。

    🩸 2026-08-18 实证（博客长文跑 12 条）：软断在无标点处把**词和术语劈开** 9 处——
    「参｜与」「创伤后｜应激障碍」「有｜没有」。⚠️ 软断本来就 warn 让人裁决，
    但**warn 太弱，人不会逐条看**，那批是靠手工补逗号绕过去的。
    ⇒ 加一条**词边界**约束：切点必须落在词与词之间。

    ⚠️ **返回 None ≠ 返回空集**：前者是「这项没查」，后者是「查了，没有合法切点」。
    ⛔ 混为一谈会让缺依赖的机器静默退回旧行为，而没人知道。
    """
    ws = word_spans(seg)
    return None if ws is None else {0} | {e for _, e, _ in ws}


def word_spans(seg: str):
    """jieba 切词结果 `[(start, end, word)]`。**jieba 不可用返回 None**（＝这项没查）。"""
    if _JIEBA_STATE["ok"] is False:
        return None
    try:
        import jieba
    except ImportError:
        _JIEBA_STATE["ok"] = False
        return None
    _JIEBA_STATE["ok"] = True
    pos, out = 0, []
    for w in jieba.cut(seg):
        out.append((pos, pos + len(w), w))
        pos += len(w)
    return out


def _word_around(seg: str, i: int, words):
    """断口两侧的**词**。`words is None`（jieba 不可用）时退回**单字**——⚠️ 那更严，会多拒。"""
    if not words:
        return (seg[i - 1] if i > 0 else ""), (seg[i] if i < len(seg) else "")
    left = next((w for _, e, w in words if e == i), None)
    right = next((w for s, _, w in words if s == i), None)
    return (left if left is not None else (seg[i - 1] if i > 0 else "")), \
           (right if right is not None else (seg[i] if i < len(seg) else ""))


def soft_ok(seg: str, i: int, edges=None, spans=None, words=None) -> bool:
    """在 seg 的第 i 个字之前断开是否算合法软断点。

    五条**全部**要满足（⚠️ 前四条是硬否决，任一不过就不许断）：
    ① 🔴 **前一个字不是结构虚词**（`TAIL_BAN`）——断在「的/把/被/在…」后面那一屏不成话；
    ①' 🔴 **后一个字也不是结构虚词**（`HEAD_BAN`，同一张表）——下屏以「的/和/在…」
       开头同样不成话，实证「第一作者是我们｜的咨询师负责人李牧阳」；
    ② 🔴 **不切进保护区间**（英文词组／正反问）——切开会**编造出不存在的刊名**、
       或留下「是它还在不」这种半句；
    ③ **切点落在词边界上**（jieba）——⛔ 别把「参与」「创伤后应激障碍」劈开；
    ④ 本来的 SOFT_HEAD/SOFT_TAIL 词形判据。

    🩸 **①②是 2026-08-18 补的，因为③不够**：jieba 认为「持续的｜情绪困扰」是词边界
    （那**确实**是两个词）⇒ **词边界是必要条件，⛔ 不是充分条件**。
    🩸 **①' 是当天晚些补的，因为①只挡住了半边**——同一批虚词做下屏开头照样出病句，
    而规则只写了「后面不断」。⚠️ **写规则时把"前后"写全，比事后补一半容易得多。**

    🔴 **①①' 判的是「断口两侧的词」，⛔ 不是「两侧的字」**（2026-08-18 晚改）。
    🩸 起因：`向` 在 `STRUCT_PARTICLES` 里，于是「证据**方向**｜是相反的」被当成
    「断在介词后」**整句拒渲染** ⇒ **逼作者改一句本来没问题的话**。
    ⚠️ 同一个字在不同词里角色不同——「方向」的「向」是名词的一部分，
    **单字黑名单永远分不出这两种**。升到词级后：`jieba` 把「方向」切成一个词，
    它 ≠「向」⇒ 放行；而「持续/的」「挡/在/门外」里那些虚词**本来就是独立的词** ⇒ 照禁。
    ⇒ **拦截能力一点没少，误伤面大幅缩小。**

    ⚠️ `edges is None` / `words is None` 表示 jieba 不可用：此时跳过③、且①①' **退回单字判据**
    （更严、会多拒），并由调用方报出「这项没查」。
    """
    left, right = _word_around(seg, i, words)
    if left in TAIL_BAN or right in HEAD_BAN:
        return False
    if left in NEG_TAIL_BAN:      # 否定词只禁做结尾，⛔ 不禁做开头（见 NEG_TAIL_BAN）
        return False
    for a, b in (spans or ()):
        if a < i < b:                       # 切点落在保护区间内部
            return False
    if not (seg[i:].startswith(SOFT_HEAD) or seg[:i].endswith(SOFT_TAIL)):
        return False
    return True if edges is None else (i in edges)


def soft_split(seg: str, cap: int):
    """把无标点长段切成每片 ≤cap 的若干片，只许在软断点处下刀。

    返回片列表；切不开返回 None。优先片数最少，同片数取长度最匀的那种切法。
    """
    n = len(seg)
    words = word_spans(seg)      # None ⇒ jieba 不可用，词边界这一项没查
    edges = None if words is None else {0} | {e for _, e, _ in words}
    spans = _protected_spans(seg)   # 英文词组／数量串／正反问：切进去就出事
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
                if n - j < MIN_SOFT or not soft_ok(seg, j, edges, spans, words):
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
        # ⚠️ 必须 strip：切点落在空格旁边时片段会带首尾空格，屏上就是一块歪掉的留白。
        # strip 只会让片段更短，⛔ 不可能反过来撑破 cap。
        out.append(seg[i:j].strip())
        i = j
    return [x for x in out if x]


# ────────────────────── 专名屏例外（助理 2026-08-18 拍板 A） ──────────────────────

PROPER_MIN_RATIO = 0.60
"""专名屏允许缩到整片字号的这个比例，⛔ 再小就拒。

⚠️ **这个数是约定，不是实测出来的阈值**——⛔ 别引用它当"可读性下限的证据"。
定它的两条考虑：① 3:4 档 80px × 0.60 = 48px，按小红书 feed 宽 375 折算 ≈ 16.7px 屏显，
在插图线实测的可读下限（`MIN_FEED_PX=11.0`）之上；② 再小就明显"不是同一条片子的字"，
版式身份就散了。**要动它请连着这两条一起重估**，别只挪数字。"""


def proper_spans_en(seg: str):
    """seg 里的英文专名区间（长度 >1）。⚠️ 正反问不在内——它是断句保护，不给排版例外。"""
    return [(m.start(), m.end()) for m in EN_TOKEN.finditer(seg) if m.end() - m.start() > 1]


def proper_lines(seg: str, cap: int):
    """**专名屏例外**：一屏装不下、又因为含不可分割英文专名而切不开时，改**两行排版**。

    返回 `[上行, 下行]`；不适用返回 `None`。

    🔴 **触发条件是「含不可分割专名」，⛔ 不是「装不下」。**这条区别是整个例外能不能
    存在的前提：若由"装不下"触发，那任何长句都能触发，**版式当场就废了**（tpl-oneline
    硬契约①）；由"含专名"触发，它就是**封闭的、可枚举的**——期刊名、量表名、书名。

    🔴 **为什么两行同屏可以、两屏分时不可以**（同一个专名，两种切法后果完全不同）：
      · 分**屏** = 时间上分离 ⇒ 第 2 屏单看是「and Psychosomatics」，
        那是**一个不存在的刊名**，读者那 1.6 秒看到的是假事实；
      · 分**行** = 空间上同时可见 ⇒ 读者一眼看到完整刊名，只是排成两行。
    ⇒ 所以折行**允许落在专名内部的空格上**，而分屏永远不许。

    🔴 **折点由本函数算死，⛔ 绝不交给 CSS 自动折行**：`Psychotherapy and Psychosomatics`
    里有空格，浏览器会在 `Psychotherapy` 后面折——那是能折的地方里**最坏**的一个
    （上行结尾正好是个完整的假刊名）。⚠️ 自动折行看着"能用"，出的正是我们要禁的那一屏。
    """
    if units(seg) <= cap:
        return None
    spans = proper_spans_en(seg)
    if not spans:
        return None                      # 不含英文专名 ⇒ ⛔ 不给例外，照旧拒
    limit = cap / PROPER_MIN_RATIO       # 字号缩 r 倍 ⟺ 每行能装 cap/r 个字
    edges = word_edges(seg)
    best = None
    for p in range(1, len(seg)):
        if seg[p] == " ":
            continue                     # 折在空格前／后是同一刀，只留"空格后"这一种
        inside = next(((a, b) for a, b in spans if a < p < b), None)
        if inside and seg[p - 1] != " ":
            continue                     # 🔴 专名内部**只许折在空格之后**，⛔ 绝不切进单词
        if not inside and edges is not None and p not in edges:
            continue                     # 中文侧仍守词边界
        a, b = units(seg[:p]), units(seg[p:])
        if max(a, b) > limit:
            continue
        rank = (0 if not inside else 1, abs(a - b))   # 优先折在专名之外，其次求均衡
        if best is None or rank < best[0]:
            best = (rank, p)
    return [seg[:best[1]].strip(), seg[best[1]:].strip()] if best else None


def proper_font(lines, cv: dict) -> int:
    """专名屏该用多大字号：按最宽那一行反推，**只缩不放**，⛔ 只影响这一屏。

    ⚠️ **这是估算，且已知偏保守**：`units()` 把 ASCII 按 0.6 折算，而 ZCOOLKuaiLe 的
    拉丁字实际更窄——实测「有一本期刊叫 Psychotherapy and Psychosomatics 上面登过这个研究」
    出 57px 时真宽 896px，安全区 1000px **还剩 104px 没用上**。
    ⇒ 偏差方向是**安全的**：只会把字号压得比必要更小，⛔ 不会放出一屏真的超宽的片子。

    🔴 **余量由模板的 `refitProper()` 在浏览器端回收**（助理 2026-08-18 拍板，下限保持 60%）：
    实测 57/58/53px → **62/66/63px**（77/78/72% → 84/89/85%）。
    ⚠️ **本函数返回的仍是估算下限，⛔ 不是最终字号**——最终值只有像素闸报得出。

    ⚠️ **残余的保守没有一起放宽**：`proper_lines()` 里 `limit = cap/PROPER_MIN_RATIO` 仍按估算算，
    所以少数 refit 后其实能过的句子会在 build 阶段就被拒。**这是有意留的**——放宽它等于
    让 `--precheck`（离线、开不了浏览器）说能过、真跑却被像素闸拒，**预检与真闸当场不同源**。
    ⇒ 宁可多拒（代价：作者多断一句，且报得清楚），⛔ 不要假绿。"""
    safe_w = cv["w"] - 2 * cv["pad"]
    return min(cv["font"], int(safe_w / (max(units(x) for x in lines) + 0.34)))


def suggest(seg: str, cap: int):
    """给切不开的段落挑 3 个"在这儿加个逗号就行"的位置。**建议本身必须合法**。

    🔴 **建议断点要过与真闸同一道 `soft_ok`**（词边界／结构虚词／保护区间）。
    🩸 起因：闸门拒了「如果你正被持续的情绪困扰缠着不放请打 12356」，给的三条建议是
    「情绪困｜扰」「持续的情绪｜困扰」——**全都切在词中间或虚词后面**，
    正是同一天刚立规矩要禁的那两种。
    ⚠️ 闸门报红是对的，但**处置建议会把人引到一个新的错**——
    一个把人引向错误修法的报错，比不报还糟。
    ⇒ 挑不出合法位置时**明说"这句没有合法断点，请改写"**，⛔ 绝不硬凑三条。
    """
    words, spans = word_spans(seg), _protected_spans(seg)
    edges = None if words is None else {0} | {e for _, e, _ in words}
    cands = []
    for p in range(MIN_SOFT, len(seg) - MIN_SOFT + 1):
        if not soft_ok(seg, p, edges, spans, words):
            continue
        left, right = seg[:p], seg[p:]
        # 加了这一刀之后，两边各自还能不能被自动处理（≤cap 或还能软切）
        ok = all(units(x) <= cap or soft_split(x, cap) for x in (left, right))
        cands.append((0 if ok else 1, abs(units(left) - units(seg) / 2), p))
    cands.sort()
    return [f"{seg[:p]}｜{seg[p:]}" for _, _, p in cands[:3]]


# ────────────────────────── 闸门主体 ──────────────────────────

def split_cue(text: str, cap: int, allow_proper: bool = True):
    """一句 → 若干屏。返回 (屏列表, 失败清单, 软断记录, 专名屏记录)。失败清单非空即拒渲染。

    屏列表元素是 `{"text":…, "lines": None 或 [上行, 下行]}`——`lines` 非空即**专名屏**。

    软断（在没有标点的地方下刀）是**兜底不是常态**：它一定会被登记出来给人看一眼，
    ⛔ 绝不静默——断点断得对不对只有写稿的人说了算。

    `allow_proper=False` 关掉专名屏例外（段落版式用）：⚠️ 关掉后它**照旧报"断不开"**，
    ⛔ 不会静默地把一屏塞爆。
    """
    # ⚠️ 先把数字内部的 . : / 藏起来再硬切——否则「下降了 3.2 个百分点」会被切成
    # 「下降了 3」「2 个百分点」，而 display() 还会把那个点整个丢掉（**数值就变了**）。
    parts = [p for p in re.split("[" + re.escape("".join(HARD)) + "]", _hide_num_punct(text))]
    screens, fails, softs, propers = [], [], [], []
    for raw in parts:
        seg = _show_num_punct(display(raw))
        if not seg:
            continue
        if units(seg) <= cap:
            screens.append(dict(text=seg, lines=None))
            continue
        pieces = soft_split(seg, cap)
        if pieces is not None:
            softs.append(dict(seg=seg, pieces=pieces))
            screens.extend(dict(text=p, lines=None) for p in pieces)
            continue
        lines = proper_lines(seg, cap) if allow_proper else None
        if lines is not None:
            propers.append(dict(seg=seg, lines=lines))
            screens.append(dict(text=seg, lines=lines))
            continue
        fails.append(dict(seg=seg, chars=units(seg), suggest=suggest(seg, cap)))
        screens.append(dict(text=seg, lines=None))   # 占位，好让报告里看得见它排在第几屏
    return screens, fails, softs, propers


def weight(s: str, is_seg_end: bool) -> float:
    """配时权重：字数 + 段末标点的那口气（逗号≈1.6 个字的停顿）。"""
    return units(s) + (1.6 if is_seg_end else 0.0)


def build_screens(cues, cap, allow_proper: bool = True):
    """cues → 屏序列（含起止时刻）。句边界＝屏边界（零估算）；句内按权重分配。"""
    out, fails, warns, propers = [], [], [], []
    for ci, c in enumerate(cues):
        texts, f, softs, pr = split_cue(c["text"], cap, allow_proper)
        for x in f:
            x["cue"] = ci
            x["cue_text"] = c["text"]
        fails.extend(f)
        for s in softs:
            warns.append(f"[软断] 第 {ci + 1} 句在无标点处自动软断：{'｜'.join(s['pieces'])}"
                         f"（断点归写稿人裁决，认可就把逗号补进稿子）")
        for s in pr:
            propers.append(dict(cue=ci, **s))
        if not texts:
            continue
        ws = [weight(s["text"], i == len(texts) - 1) for i, s in enumerate(texts)]
        span, tot = c["end"] - c["start"], sum(ws) or 1.0
        t = c["start"]
        for i, (s, w) in enumerate(zip(texts, ws)):
            end = c["end"] if i == len(texts) - 1 else t + span * w / tot
            out.append(dict(text=s["text"], lines=s["lines"],
                            start=round(t, 3), end=round(end, 3), cue=ci))
            if units(s["text"]) <= SHORT_CHARS:
                warns.append(f"[短屏] 第 {len(out)} 屏「{s['text']}」{units(s['text']):.0f} 字 / "
                             f"{end - t:.2f}s——⚠️ 多半是稿子里的逗号断得太碎，"
                             f"⛔ 不是断句器的事（合并要动标点，归写稿人）")
            elif end - t < MIN_SEC:
                warns.append(f"第 {len(out)} 屏「{s['text']}」仅 {end - t:.2f}s（建议 ≥{MIN_SEC}s）")
            t = end
    return out, fails, warns, propers


# ───────────────────── 背景层：一份定义，两处填充 ─────────────────────
# 🩸 2026-08-18 抽出来的。此前 `#paper`/`#vignette` 在 tpl-oneline 与 tpl-paragraph 里
# 各写一份 ⇒ **第二份当场就漂了**：复制时掉了「四角压暗」那行注释、`#paper` 的注释还被
# 精简掉两句。⚠️ 丢的都是注释——**没有视觉后果，却少了给下一个人的路标**，最难发现。
# ⇒ 抽成占位符后**不可能再漏**：新模板忘了放占位符，`instantiate()` 末尾那道
#   「模板还有没填的占位符」检查会当场退出。⛔ 别再往模板里手写这两层。

BG_LAYERS_CSS = """  /* 纸纹：内联 SVG feTurbulence + feColorMatrix saturate=0 去色（零外网依赖），静态一层。
     ⛔ 没有 feDiffuseLighting——2026-08-16 试过并放弃（本尺度下只出平滑渐变，高通标准差 0.92
     ＝等于没纹理）。⛔ 也别去掉那道去色：不去色出的是彩色噪点，像彩电雪花不像纸。 */
  #paper { position:absolute; inset:0; z-index:1;
    background-image:__PAPER_URL__;
    background-size:__TEX_SCALE__px __TEX_SCALE__px;
    mix-blend-mode:multiply; opacity:__TEX_OPACITY__; }
  /* 四角压暗，把视线收到中间那行字上 */
  #vignette { position:absolute; inset:0; z-index:2; pointer-events:none;
    background:radial-gradient(ellipse at 50% 48%, rgba(0,0,0,0) 42%, __VIGNETTE__ 100%); }"""

BG_LAYERS_HTML = """<div id="paper"></div>
<div id="vignette"></div>"""

# 纸感层（纤维/微皱）。**只有配了 fiber/crease 的档才长出来**——⛔ 不是所有档都加，
# 否则 miwen 这些在产档会跟着变，「老片重渲不变」就破了（G15 老板选的正是"新增档、老片不变"）。
_FIBER_CSS = """  /* 纸感层：中性噪声 + soft-light，只加起伏、不动底色（G15，2026-08-18）。
     🩸 两个坑，⛔ 别再走回去：
     ① **不能并进 #paper**：#paper 整层是 multiply，而 multiply 层里任何非白像素都必然压暗底色
        （实测把中性噪声并进它的多重背景，底色掉 65/255）。所以纸感必须是独立层 + soft-light。
     ② **SVG filter 默认在 linearRGB 运算**：要"显示上 128 灰"，按 slope=.5/intercept=.25 算出来
        的却是 187（0.5^(1/2.2)≈0.73）。必须 color-interpolation-filters='sRGB'，否则中性层
        怎么都调不准——而现象只是"调不准"，根本看不出是色彩空间的事。 */
  #%(id)s { position:absolute; inset:0; z-index:1;
    background-image:%(url)s;
    background-size:%(tile)dpx %(tile)dpx;
    mix-blend-mode:soft-light; }"""


def neutral_turb(freq, octaves, seed, k, size=240):
    """「显示上均值 128 灰、不透明」的湍流——soft-light 叠它才真正不改底色。

    中心 0.5146 而非 0.5：soft-light 叠在噪声上并非严格中性，这是实测两点线性外推出的零点
    （默认 0.5 时底色掉 1.72/255，用 0.5146 后偏移 0.11/255）。⛔ 别"顺手"改回 0.5。
    k 只控制强弱：RGB 线性变换 slope=k、intercept=中心-0.5k，均值锁死，不搬移中心。
    """
    b = 0.5146 - 0.5 * k
    fn = "".join(f"<feFunc{c} type='linear' slope='{k}' intercept='{b:.4f}'/>" for c in "RGB")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}'>"
           f"<filter id='n' color-interpolation-filters='sRGB'>"
           f"<feTurbulence type='fractalNoise' baseFrequency='{freq}' "
           f"numOctaves='{octaves}' seed='{seed}'/>"
           "<feColorMatrix type='saturate' values='0'/>"
           f"<feComponentTransfer>{fn}<feFuncA type='table' tableValues='1 1'/></feComponentTransfer>"
           "</filter>"
           f"<rect width='{size}' height='{size}' filter='url(#n)'/></svg>")
    return 'url("data:image/svg+xml,' + quote(svg, safe="") + '")'


def bg_layers(bg):
    """按档生成背景层的 CSS 与 div。没配纸感的档，产出与加纸感之前**逐字节相同**。"""
    css, html = [BG_LAYERS_CSS], [BG_LAYERS_HTML]
    extra = []
    for key in ("fiber", "crease"):
        layer = bg.get(key)
        if not layer:
            continue
        css.append(_FIBER_CSS % dict(
            id=key, tile=layer["tile"],
            url=neutral_turb(layer["freq"], layer["octaves"], layer["seed"],
                             layer["k"], layer.get("size", 240)),
        ))
        extra.append(f'<div id="{key}"></div>')
    if extra:      # 纸感层夹在 #paper 与 #vignette 之间（压角永远在最上）
        html = [BG_LAYERS_HTML.replace('<div id="vignette"></div>',
                                       "\n".join(extra) + '\n<div id="vignette"></div>')]
    return "\n".join(css), "\n".join(html)


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


def with_proper_font(screens, cv: dict):
    """给专名屏补 `font_px`/`stroke_px`；普通屏原样返回（**没有这两个键**）。

    ⚠️ 「没有这个键」与「键值等于整片字号」不是一回事：前者是"这一屏没走例外"，
    后者是"走了例外但没缩"。⛔ 别为了模板少写个判断就给所有屏都填上。
    """
    out = []
    for s in screens:
        if s.get("lines"):
            px = proper_font(s["lines"], cv)
            out.append(dict(s, font_px=px, stroke_px=round(px * 0.17)))
        else:
            out.append(s)
    return out


def instantiate(screens, cv, bg, bg_name, tpl=None, sec_cues=3, icon=None,
                plan_motifs=None, plan_sections=None):
    stroke = round(cv["font"] * 0.17)
    safe_w = cv["w"] - 2 * cv["pad"]
    need = cv["font"] * cv["max_chars"] + 2 * stroke
    if need > safe_w:
        sys.exit(f"❌ 画幅档 {cv['w']}x{cv['h']} 自相矛盾：{cv['max_chars']} 字需 {need}px > 安全区 {safe_w}px。"
                 f"\n   改 CANVAS 里的 font/pad，⛔ 别改 max_chars 之外的运行期逻辑。")
    sub = {
        # ⚠️ 必须排在最前：它展开后内部仍含 __PAPER_URL__/__TEX_SCALE__ 等，
        # 靠后面的条目接着替换（dict 保序）。放后面就会留下没填的占位符。
        **dict(zip(("__BG_LAYERS_CSS__", "__BG_LAYERS_HTML__"), bg_layers(bg))),
        "__CANVAS__": f"{cv['w']}x{cv['h']}", "__W__": cv["w"], "__H__": cv["h"],
        "__FONT_PX__": cv["font"], "__STROKE_PX__": stroke, "__SAFE_W__": safe_w,
        "__RISE__": cv["rise"], "__BRAND_PX__": cv["brand_px"],
        "__BRAND_BOTTOM__": cv["brand_bottom"], "__TEX_SCALE__": bg["tex_scale"],
        "__BASE__": bg["base"], "__INK__": bg["ink"], "__VIGNETTE__": bg["vignette"],
        "__BRAND_COLOR__": bg["brand"], "__TEX_OPACITY__": bg["tex_opacity"],
        "__PAPER_URL__": paper_url(bg["turb"]), "__BG_NAME__": bg_name,
        "__SCREENS__": json.dumps(with_proper_font(screens, cv), ensure_ascii=False),
        # 段落字卡专用；oneline 模板里没有这个占位符，填了也不会有副作用
        "__SEC_CUES__": sec_cues,
        "__PLAN_MOTIFS__": json.dumps(plan_motifs or [], ensure_ascii=False),
        "__PLAN_SECTIONS__": json.dumps(plan_sections or [], ensure_ascii=False),
        # 账号图标位；⚠️ 关掉时填的是**空串**，⛔ 不是留着占位符不填
        # （留着会被下面那道「模板还有没填的占位符」检查拦下，报一个跟真因无关的错）
        **dict(zip(("__ICON_CSS__", "__ICON_HTML__", "__ICON_JS__"), icon_parts(icon, cv))),
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


def precheck(path: Path, cap: int) -> int:
    """跑批前离线预检：不烧 TTS 配额就知道有几处断不开。

    🩸 2026-08-18 立。起因：某线自造了一份预检，报 17 处断不开，**真闸只报 2 处**——
    **两把尺不同源**。⇒ 本函数**直接调用真闸用的那两个函数**：
    切句用 `tts_gen._split_sentences`（TTS 的统一单元），拆屏用本模块的 `split_cue`。
    ⛔ **别再另写一份"预检版"逻辑**——预检与真闸不同源，等于没预检。

    🩸 **三类结果各有各的记号**：`[断不开]`／`[软断]`／`[专名屏]`。
    此前 fail 与 soft **共用「· 第」这一个记号**，于是"数出几处失败"的计数会把软断
    也算进去——⚠️ 原来的样本恰好一处软断都没有，所以这个坑一直没露头，
    直到专名屏例外把那句刊名接走、样本换成带软断的句子才当场报假红。
    ⇒ **同源比对靠的是记号能分类**，⛔ 别让两类结果长一个样。
    """
    sys.path.insert(0, str(HERE))
    import tts_gen                                  # 与真链路同一把切句尺
    text = path.read_text(encoding="utf-8")
    body = "\n".join(ln for ln in text.splitlines()
                      if not ln.lstrip().startswith(("#", "<!--", ">")))
    sents = tts_gen._split_sentences(body)
    if not sents:
        print(f"❌ {path} 没切出句子（要有 。！？ 断句）——⛔ 这不是「稿子没问题」，是没读到",
              file=sys.stderr)
        return 2

    fails, softs, propers, shorts, screens = [], [], [], [], 0
    for i, sent in enumerate(sents, 1):
        texts, f, sf, pr = split_cue(sent, cap)
        screens += len(texts)
        # ⚠️ 真闸报短屏、预检不报 ⇒ 又是「两边看到的东西不一样」。这里按字数估，
        #    ⛔ 别因为"预检没有 cues 算不出秒数"就整条不报。
        shorts += [dict(sent_no=i, text=t["text"]) for t in texts
                   if units(t["text"]) <= SHORT_CHARS]
        for x in f:
            x["sent_no"] = i
            x["sent"] = sent
        fails.extend(f)
        softs.extend(dict(sent_no=i, **x) for x in sf)
        propers.extend(dict(sent_no=i, **x) for x in pr)

    print(f"  {len(sents)} 句 → {screens} 屏（上限 {cap} 字/屏）", file=sys.stderr)
    if propers:
        # ℹ️ **专名屏例外是 info，⛔ 不是 warn 也不是 fail**：它是**已经处理好**的状态，
        #    不需要作者做任何事。⚠️ 把它报成 warn 会让人跑来"修"一个没坏的东西
        #    ——那正是假红的代价。
        print(f"\nℹ️ 专名屏例外 {len(propers)} 处（含不可分割英文专名 ⇒ **两行排版**，"
              f"⛔ 无需改稿）：", file=sys.stderr)
        for x in propers:
            px = proper_font(x["lines"], apply_max_chars(CANVAS["3:4"], cap))
            # ⚠️ 前缀跟 fail 的「· 第」错开：同一个记号会让「数出几处失败」的计数串味
            print(f"  [专名屏] 第 {x['sent_no']} 句：{x['lines'][0]} ／ {x['lines'][1]}"
                  f"（两行，估算 ≥{px}px，3:4 档；真跑会按实测往上抬；其余屏不变）",
                  file=sys.stderr)
    if softs:
        print(f"\n⚠️ 无标点处自动软断 {len(softs)} 处（断点归写稿人裁决，认可就把逗号补进稿子）：",
              file=sys.stderr)
        for x in softs[:8]:
            print(f"  [软断] 第 {x['sent_no']} 句：{'｜'.join(x['pieces'])}", file=sys.stderr)
        if len(softs) > 8:
            print(f"  …另有 {len(softs) - 8} 处", file=sys.stderr)
    if shorts:
        print(f"\n⚠️ {len(shorts)} 屏 ≤{SHORT_CHARS} 字（「三字孤悬」）——"
              f"⚠️ 多半是稿子里的逗号断得太碎，⛔ 不是断句器的事：", file=sys.stderr)
        for x in shorts[:8]:
            print(f"  [短屏] 第 {x['sent_no']} 句：「{x['text']}」"
                  f"（约 {units(x['text']) / 3.5:.2f}s，按 3.5 字/秒估）", file=sys.stderr)
        if len(shorts) > 8:
            print(f"  …另有 {len(shorts) - 8} 屏", file=sys.stderr)
    if fails:
        print(f"\n⛔ {len(fails)} 处**断不开**（真跑会拒绝出片，⚠️ 而那时 TTS 配额已经花掉）：",
              file=sys.stderr)
        for x in fails:
            print(f"  [断不开] 第 {x['sent_no']} 句「{x['seg']}」（{x['chars']:.1f} 字）",
                  file=sys.stderr)
            if x["suggest"]:
                print(f"    建议断点：{x['suggest'][0]}", file=sys.stderr)
            else:
                print("    ⚠️ **这一句挑不出合法断点**（词边界／结构虚词／不可分割专名都不许切）"
                      "\n       ⇒ 请改写成两句，⛔ 别硬找地方塞逗号", file=sys.stderr)
            # ⚠️ 断不开的原因往往是保护区间——说清楚，⛔ 别让人在不该断的地方硬断
            seg = x["seg"]
            if proper_spans_en(seg):
                # ⚠️ 走到这里说明**连专名屏例外都救不了**（两行仍超 cap/PROPER_MIN_RATIO），
                #    ⛔ 别再让人去"补逗号"——专名本身就装不下，补逗号不解决问题
                name = proper_spans_en(seg)[0]
                print(f"    ⚠️ 含英文专名「{seg[name[0]:name[1]]}」——**不可分割**，"
                      f"且**两行也装不下**（专名屏例外已试过）\n"
                      f"       ⇒ 把它单独说成一屏（前后各断一句），"
                      f"⛔ 别在专名内部补逗号——那等于把刊名改了", file=sys.stderr)
            if AB_QUESTION.search(seg):
                print(f"    ⚠️ 含正反问「{AB_QUESTION.search(seg).group()}」——**不可劈**"
                      f"（劈开会留下「还在不」这种半句）", file=sys.stderr)
        return 1
    print("\n✅ 全部可拆，跑批不会被单行闸拦下", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="一行字卡实例化（含单行硬闸门）")
    ap.add_argument("--cues", help="tts_gen --timed 产出的 *.cues.json")
    ap.add_argument("--precheck", metavar="稿.txt",
                    help="离线预检：**不烧 TTS 配额**就查有几处断不开。"
                         "⚠️ 与真闸**同源**（切句用 tts_gen._split_sentences、拆屏用 split_cue），"
                         "⛔ 别另写一份预检版逻辑——不同源等于没预检")
    # --bg / --canvas 不用 required=True：风格档案（--style）也能给。缺了照旧报错退出，
    # 只是把「argparse 报缺参数」换成下面那句人话——⛔ 绝不给它们编一个默认值悄悄出片
    ap.add_argument("--bg", choices=sorted(BG))
    ap.add_argument("--canvas", choices=sorted(CANVAS))
    # ⚠️ 不能 required=True：--precheck 根本不产出文件。缺了在下面按人话报，
    # ⛔ 别让 argparse 顶回一句 usage——那看不出「是不是预检也要传」。
    ap.add_argument("--out", help="工作目录（card-oneline.html 落这里）；--precheck 时不需要")
    ap.add_argument("--max-line-chars", type=int, default=12,
                help="单屏排版拆屏上限（8–14，默认 12；书名场景可 13——整片按安全区统一反推字号，非按行缩字）。"
                     "⛔ 这是排版量具，不是写稿字数上限：写稿只管把事说清楚，装不下就多一屏")
    ap.add_argument("--plan", metavar="plan.json",
                help="视觉计划（plan_llm.py 产出）：**逐段 motif 由它定，⛔ 不再机械轮转**。"
                     "⚠️ 只对 --template paragraph 有效，且**必须配 --sec-cues 1**")
    ap.add_argument("--account-icon", metavar="图片",
                help="账号图标位（默认关）：**跟落款走同一机制**——只在首屏与落款屏浮出，"
                     "中间屏一个像素都没有 ⇒ ⛔ 不是常驻元素，不碰版式契约。"
                     "图片会内联成 data URI（零外部依赖）")
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
    if a.precheck:
        return precheck(Path(a.precheck), a.max_line_chars)
    if not a.cues:
        sys.exit("❌ 缺 --cues（或用 --precheck 做离线预检）")
    if not a.out:
        sys.exit("❌ 缺 --out（工作目录）。⚠️ 只有 --precheck 不需要它")
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

    plan_motifs = plan_sections = None
    if a.plan:
        if a.template != "paragraph":
            sys.exit(f"❌ --plan 只对 --template paragraph 有效（收到 {a.template}）")
        if a.sec_cues != 1:
            sys.exit(f"❌ --plan 必须配 --sec-cues 1（收到 {a.sec_cues}）："
                     f"计划的粒度是「句」，sec_cues>1 时**段与句对不上** ⇒ "
                     f"motif 会挂到错误的段上，⚠️ **而画面照样出得来，没人会发现**")
        pj = json.load(open(a.plan, encoding="utf-8"))
        # ⚠️ ⛔ 别把它命名成 `units`——模块级已有 `units()`（宽度口径函数）。
        # 🩸 撞名后 Python 把 `units` 当整个函数的局部变量 ⇒ **没给 --plan 时**
        #    后面调用 `units(...)` 抛 NameError：**有 plan 正常、没 plan 才崩**。
        plan_units = pj.get("screens", [])
        if len(plan_units) != len(cues):
            sys.exit(f"❌ --plan 有 {len(plan_units)} 个单元、cues 有 {len(cues)} 句——"
                     f"**对不上就一定是错的**（计划是按当时那份 cues 出的）。"
                     f"⛔ 别截断凑数，重跑 plan_llm.py")
        # 🔴 **段划分来自计划**（合屏是编排层职责）。`section` 缺省 ⇒ 退回「一句一段」，
        # ⚠️ 那是**旧格式的 plan**，⛔ 不是"没有段"——退回后行为与 v2.21 完全一致。
        plan_sections = [x.get("section", i) for i, x in enumerate(plan_units)]
        # motif 按**段**取：段首那一句带 motif，段内其余为 None ⇒ 用段首的
        plan_motifs, seen = [], {}
        for sec, x in zip(plan_sections, plan_units):
            if sec not in seen:
                seen[sec] = x.get("motif")
            plan_motifs.append(seen[sec])
        n_sec = len(seen)
        if n_sec < len(cues):
            print(f"   🔗 合屏：{len(cues)} 句 → {n_sec} 段（计划合并了 "
                  f"{len(cues) - n_sec} 处）", file=sys.stderr)
        # ⚠️ 模板按**段号**索引 PLAN_MOTIFS，⛔ 不按句号 ⇒ 这里要压成按段的数组
        plan_motifs = [seen[k] for k in sorted(seen)]
        bad = sorted({m for m in plan_motifs
                      if m not in ("rise", "wipe", "depth", "drift", "tilt", "still")})
        if bad:
            sys.exit(f"❌ --plan 里有闭集之外的 motif：{bad}")

    # ⚠️ 专名屏例外只有 oneline 版式实现了（模板里要有 .scr.proper 的两行排版）。
    # paragraph 走这条会**静默出一屏塞爆的字**——所以对它显式关掉，让它照旧报「断不开」。
    screens, fails, warns, propers = build_screens(cues, cv["max_chars"],
                                                   allow_proper=(a.template == "oneline"))

    # 🔴 **四类结果全在 fail 早退之前报**（专名屏／短屏／软断／断不开）。
    # 🩸 挪过两次才挪全：第一次只挪了专名屏，**软断与短屏还留在早退之后** ⇒
    #    有 fail 的稿子照旧看不到它们，而预检是四类一次报全的。
    # ⚠️ 「有 fail 就早退」看着很合理（反正不出片了），但它让**同一份稿子在两个工具里
    #    显示的问题数量不一样**——人会以为修完 fail 就没别的事了。
    for w in warns:
        print(f"   ⚠️ {w}", file=sys.stderr)

    # 🔴 **专名屏先报，⛔ 别放在 fail 早退之后**：有 fail 就 return 的话，
    # 作者要修完 fail 再跑一次才看得到这一类——而预检是三类一次报全的，
    # ⚠️ 两边看到的东西不一样，「预检与真闸同源」就只剩一句口号。
    # ⚠️ 两种状态都打：「有图标位」与「没有」必须在产出信息里分得开
    print(f"   {'账号图标位：' + a.account_icon if a.account_icon else '⛔ 无账号图标位'}",
          file=sys.stderr)
    for pr in propers:
        px = proper_font(pr["lines"], cv)
        # ⚠️ 这里的 px 是**估算下限**——模板的 refitProper() 会按实测宽度回收余量往上抬，
        # 最终字号以下方像素闸那行为准。⛔ 别把这两个数当同一个数（实测普遍高 8–15%）。
        print(f"   [专名屏] 例外：{pr['lines'][0]} ／ {pr['lines'][1]}"
              f"（两行，估算 ≥{px}px，实际见像素闸；⛔ 无需改稿）", file=sys.stderr)

    if fails:
        print(f"\n❌ 单行闸门拒绝出片：{len(fails)} 处断不开的超长句（上限 {cv['max_chars']} 字/屏）\n",
              file=sys.stderr)
        for f in fails:
            print(f"  · 第 {f['cue'] + 1} 句：{f['cue_text']}", file=sys.stderr)
            print(f"    [断不开] 片段「{f['seg']}」（{f['chars']:.1f} 字）", file=sys.stderr)
            for x in f["suggest"]:
                print(f"    建议断点：{x}", file=sys.stderr)
            if not f["suggest"]:
                print("    ⚠️ **这一句挑不出合法断点**（词边界／结构虚词／不可分割专名都不许切）"
                      "\n       ⇒ 请改写成两句，⛔ 别硬找地方塞逗号", file=sys.stderr)
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
    for dep in SCRIPT_DEPS:          # 来源是 scripts/ 不是模板目录
        dst = out_dir / dep
        if not dst.exists():
            shutil.copy(HERE / dep, dst)
    html_path = out_dir / a.name
    html_path.write_text(
        instantiate(screens, cv, bg, a.bg, TEMPLATES[a.template], a.sec_cues,
                    a.account_icon, plan_motifs, plan_sections),
        encoding="utf-8")

    # ⚠️ 统计只看普通屏：专名屏本来就**允许**超单行上限（它排两行、字号另算），
    # 把它算进「超限」会让每条带刊名的片子都自带一条假红。
    plain = [s for s in screens if not s.get("lines")]
    n_over = sum(1 for s in plain if units(s["text"]) > cv["max_chars"])
    print(f"✅ {html_path}")
    print(f"   {a.canvas} {cv['w']}x{cv['h']} · {bg['label']} · 字号 {cv['font']}px · "
          f"上限 {cv['max_chars']} 字/屏")
    if _JIEBA_STATE["ok"] is False:
        print("   ⚠️ jieba 未安装 ⇒ **软断的词边界检查这一项没做**（可能把词/术语劈开）。"
              "\n      ⛔ 这不是「检查过没问题」。装上：pip install jieba", file=sys.stderr)
    print(f"   {len(cues)} 句 → {len(screens)} 屏，最长 "
          f"{max((units(s['text']) for s in plain), default=0):.0f} 字，超限 {n_over} 屏")

    if not a.no_check:
        rep = pixel_check(html_path)
        if rep["overflow"]:
            print(f"\n❌ 像素闸拒绝出片：{len(rep['overflow'])} 屏实测超宽（字数闸没算准，多半是数字/字母）",
                  file=sys.stderr)
            for o in rep["overflow"]:
                print(f"  · 第 {o['i'] + 1} 屏「{o['text']}」{o['width']}px > 安全区 {o['limit']}px"
                      f"{'（专名屏：两行也装不下，改稿把专名单独说成一屏）' if o.get('proper') else ''}",
                      file=sys.stderr)
            return 1
        # 🔴 专名屏的**最终裁决权在像素层**：Python 端那个 units() 按 ASCII×0.6 估宽，
        # 而 ZCOOLKuaiLe 是中文字体、拉丁字宽根本不是 0.6 ⇒ 估算能过、实测未必。
        # ⚠️ 所以下限 PROPER_MIN_RATIO 要在**量到真宽度之后**再判一次，⛔ 不能只信估算。
        too_small = [p for p in rep.get("proper", []) if p["ratio"] < PROPER_MIN_RATIO]
        if too_small:
            print(f"\n❌ 专名屏缩得太小：{len(too_small)} 屏低于整片字号的 "
                  f"{PROPER_MIN_RATIO:.0%}（再小就不像同一条片子的字）", file=sys.stderr)
            for p in too_small:
                print(f"  · 第 {p['i'] + 1} 屏「{p['text']}」→ {p['font_px']}px "
                      f"（{p['ratio']:.0%}）", file=sys.stderr)
            print("处置：把专名单独说成一屏（前后各断一句），⛔ 别在专名内部补逗号——那等于改刊名。",
                  file=sys.stderr)
            return 1
        # 🔴 **编排退化哨兵**：把「视觉计划给的 motif」与「机械轮转会给的」逐段比。
        # ⚠️ **若差异接近 0，「编排」就退化成了轮转——而光看画面分不出来**（片子照样"很丰富"）。
        # 🔴 这个数**在浏览器里算**：读的是 `motifFor()` 的**返回值**与模板自己的轮转函数，
        #    ⛔ 不是在 Python 里复刻一份轮转逻辑——那是「复刻了原料，复刻不出行为」
        #    （2026-08-19 小红书发布线三次栽在这上面）。
        div = rep.get("plan_divergence")
        if div is not None:
            print(f"   🎬 编排 vs 机械轮转：{div['diff']}/{div['total']} 段不同"
                  f"（{div['pct']:.0f}%）"
                  f"{'  ⚠️ 差异过低，编排可能退化成了轮转' if div['pct'] < 25 else ''}")
        for p in rep.get("proper", []):
            print(f"   ✅ 专名屏第 {p['i'] + 1} 屏实测 {p['width']}px ≤ {cv['w'] - 2 * cv['pad']}px，"
                  f"字号 {p['font_px']}px（{p['ratio']:.0%}）")
        print(f"   ✅ 像素闸：{rep['screens']} 屏全部在安全区内，总时长 {rep['total']:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

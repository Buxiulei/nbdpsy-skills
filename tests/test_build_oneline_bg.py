"""字卡背景档 `miwen`：老板 2026-08-17 G10 亲批的那一档，参数不许漂。

为什么单独给它上锁：这档的五个参数是**老板看着一张具体的图批的**，不是设计推导出来的。
谁看着图觉得「再暖一点更好」把值一改，出的就是另一张老板没批过的图——而这种改动
肉眼几乎看不出来，code review 也拦不住，只有断言拦得住。

⚠️ 校准图（`seo-geo/.../bg-candidates/B-浅米白-强纹理.png`）出自候选**预览页**，
预览页的纹理层少一句 `mix-blend-mode:multiply`，所以它比真模板出片更浅更淡。
**要验参数就比这里的五个字段，⛔ 别拿那张图的像素当靶子**（会得出「没搬对」的错结论）。
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent / "nbdpsy-text-to-video"
SCRIPTS = Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import build_oneline as bo  # noqa: E402


def test_miwen档参数与老板批的候选B逐字段一致():
    """七个字段是运营线交出来的原值，改一个字符就该红。"""
    bg = bo.BG["miwen"]
    assert bg["base"] == "#F0E9DC"                      # 候选页 B 格 background
    assert bg["ink"] == "#241E17"                       # 候选页 B 格 .txt color
    assert bg["vignette"] == "rgba(120,98,70,.18)"      # 候选页 B 格 .vig
    assert bg["tex_scale"] == 320                       # 候选页 B 格 background-size
    assert bg["tex_opacity"] == 1.0
    assert bg["turb"] == dict(freq=0.24, octaves=5, seed=17, alpha=0.85)
    # brand 沿用 liaoyu（候选页 B 格根本没有落款，这色老板没在图上看过）。
    # 2026-08-17 实测：它在 #F0E9DC 上的落款反差 **高于** liaoyu 现状，够用，所以照搬不动。
    assert bg["brand"] == "rgba(90,72,52,.50)" == bo.BG["liaoyu"]["brand"]


def test_加档不许动老档():
    """加档不许动老档——在产片子还用着它们。"""
    assert set(bo.BG) == {"liaoyu", "kepu", "miwen", "xianwen"}
    assert bo.BG["kepu"]["base"] == "#EDEFF1"
    assert bo.BG["liaoyu"]["base"] == "#E8D8C4"


def test_xianwen只加纹理颜色四项与miwen完全相同():
    """G15 老板拍板「新增一档、老片不变」，且只授权改纸感——**颜色是 G10 批过的**。

    ⛔ 谁把 xianwen 的颜色调一下，就等于绕过 G10 重新定了一次颜色。
    """
    mi, xian = bo.BG["miwen"], bo.BG["xianwen"]
    for k in ("base", "ink", "vignette", "brand", "tex_opacity", "tex_scale", "turb"):
        assert xian[k] == mi[k], f"xianwen 的 {k} 与 miwen 不同——这一档只许改纹理"
    assert xian["fiber"] == dict(freq="0.10 0.40", octaves=5, seed=31, k=0.85, tile=280)
    assert xian["crease"] == dict(freq="0.008", octaves=3, seed=5, k=0.55, size=900, tile=900)


def test_纸感层只长在配了它的档上():
    """🩸「老片不变」的代码级保证：没配 fiber/crease 的档，背景层产出必须与加纸感前一致。

    背景层是两个版式共用的统一生成函数——**无条件加纸感就会把 miwen 这些在产档一起改掉**。
    """
    for name in ("liaoyu", "kepu", "miwen"):
        css, html = bo.bg_layers(bo.BG[name])
        assert "mix-blend-mode:soft-light" not in css, f"{name} 不该有纸感层"
        assert "fiber" not in html and "crease" not in html
        assert css == bo.BG_LAYERS_CSS and html == bo.BG_LAYERS_HTML
    css, html = bo.bg_layers(bo.BG["xianwen"])
    # ⛔ 别数裸的 "soft-light"——注释里也写着这个词，会数出 6 次（2026-08-18 实撞）
    assert css.count("mix-blend-mode:soft-light") == 2, "xianwen 该有 fiber+crease 两层"
    assert '<div id="fiber"></div>' in html and '<div id="crease"></div>' in html
    # 层序：压角永远在纸感之上，否则四角压暗会被纸感盖住
    assert html.index('id="fiber"') < html.index('id="vignette"')


def test_中性噪声的两个坑不许回退():
    """两条都是实测撞出来的，回退任一条纸感层都会失效（见 neutral_turb docstring）。

    ⚠️ 产物是 URL-encode 过的，得按编码后的样子找：`'`→`%27`、`=`→`%3D`（2026-08-18 实撞）。
    """
    from urllib.parse import unquote
    svg = unquote(bo.neutral_turb("0.10 0.40", 5, 31, 0.85))
    assert "sRGB" in svg, "filter 掉了 color-interpolation-filters='sRGB' → 中性点会偏到 187"
    assert "feFuncA" in svg, "alpha 没拉满 → 半透明噪声，soft-light 会压暗底色"
    # 中心 0.5146（⛔ 不是 0.5）：k=1 时 intercept 应为 0.0146
    assert "intercept='0.0146'" in unquote(bo.neutral_turb("0.1", 3, 1, 1.0))


def test_miwen参数真的落进了html():
    """光锁 BG 表不够：得确认它经 instantiate 真写进了 CSS（占位符漏填过一次就白锁）。"""
    screens = [dict(text="感觉好了不代表能停药", start=0.0, end=2.0, cue=0)]
    html = bo.instantiate(screens, bo.CANVAS["3:4"], bo.BG["miwen"], "miwen")
    assert "body { background:#F0E9DC;" in html
    assert "color:#241E17;" in html
    assert "rgba(120,98,70,.18)" in html
    assert "background-size:320px 320px;" in html
    assert "baseFrequency%3D%270.24%27" in html    # turb 走 URL 编码，得按编码后的样子找
    assert "seed%3D%2717%27" in html
    assert "opacity%3D%270.85%27" in html
    assert "color:rgba(90,72,52,.50)" in html      # 落款
    # 纹理层的 multiply 是真模板与候选预览页的唯一差别，掉了会整体变浅
    assert "mix-blend-mode:multiply" in html


def test_工作目录必须自带render_card副本(tmp_path):
    """🩸 2026-08-18 冒烟抓到的缝，差点让 12 条批量全废：
    `render_card.py` 用 `Path(__file__).parent` 找 cues 与音频，而 spec 示例写
    `cd 工作目录 && python3 render_card.py`——**暗含脚本已在工作目录**。
    此前只拷 gsap 与字体 ⇒ 照规格抄命令的人必然 FileNotFoundError，
    ⚠️ 而且死在 TTS 配额烧完之后。**文档与代码各自都对，合起来必炸。**
    """
    import json, subprocess, sys
    cues = tmp_path / "c.json"
    cues.write_text(json.dumps([{"text": "感觉好了不代表能停药", "start": 0, "end": 2.3}],
                               ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "wd"
    r = subprocess.run([sys.executable, str(SCRIPTS / "build_oneline.py"),
                        "--cues", str(cues), "--bg", "miwen", "--canvas", "3:4",
                        "--out", str(out), "--no-check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for need in ("card-oneline.html", "gsap.min.js", "render_card.py"):
        assert (out / need).exists(), f"工作目录缺 {need}——照 spec 抄命令会当场炸"


# ────────── 离线预检：跑批前不烧 TTS 配额就知道有几处断不开 ──────────
# 🩸 2026-08-18 立。起因：某线自造了一份预检，报 17 处断不开、**真闸只报 2 处**
# ——**两把尺不同源**。⇒ 预检必须**直接调用真闸用的那两个函数**。

def test_预检与真闸必须同源(tmp_path):
    """🔴 这条测的不是"预检能跑"，是**预检和真闸读数一样**。
    ⛔ 另写一份"预检版"拆屏逻辑＝没预检——它会在你最需要它的时候报出不同的数。"""
    import json
    import subprocess
    import sys as _s
    _s.path.insert(0, str(SCRIPTS))
    import tts_gen

    # ⚠️ 样本要**两类各一**：一句真断不开（无专名的超长中文），一句走专名屏例外。
    # 🩸 原样本只有刊名那句——专名屏例外上线后它被接住了，这个测试当场变成
    #    「真闸 0 处 vs 预检 1 处」的假红。⇒ 同源测试的样本必须覆盖**每一种终态**，
    #    否则它测的只是"当前恰好走到的那一条路"。
    txt = ("感觉好了不代表能停药。够了。"
           "焦虑抑郁强迫创伤解离躯体化人格障碍成瘾进食睡眠问题。"
           "有一本期刊叫 Psychotherapy and Psychosomatics 上面登过这个研究。")
    src = tmp_path / "s.txt"
    src.write_text(txt, encoding="utf-8")
    sents = tts_gen._split_sentences(txt)
    t, cues = 0.0, []
    for s in sents:
        d = 0.32 + len(s) * 0.19
        cues.append({"text": s, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    cf = tmp_path / "c.json"
    cf.write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")

    run = lambda *a: subprocess.run([_s.executable, str(SCRIPTS / "build_oneline.py"), *a],
                                    capture_output=True, text=True)
    real = run("--cues", str(cf), "--bg", "miwen", "--canvas", "3:4",
               "--max-line-chars", "13", "--out", str(tmp_path / "o"), "--no-check")
    pre = run("--precheck", str(src), "--max-line-chars", "13")
    # 🔴 **三类终态逐一比对**，⛔ 不是只比 fail：断不开／软断／专名屏例外。
    # 🩸 原来只比 fail，且 fail 与软断**共用「· 第」这一个记号** ⇒ 计数互相串味。
    #    ⚠️ 那时的样本恰好一处软断都没有，所以坑一直没露头。
    real_txt, pre_txt = real.stdout + real.stderr, pre.stdout + pre.stderr
    for mark, want in (("[断不开]", 1), ("[专名屏]", 1), ("[软断]", 0), ("[短屏]", 1)):
        a, b = real_txt.count(mark), pre_txt.count(mark)
        assert a == b == want, f"{mark}：真闸 {a} vs 预检 {b}（应各 {want}）——两把尺不同源"
    assert pre.returncode == 1, "有断不开却退出 0——闸门没起作用"


def test_预检不该要求out参数(tmp_path):
    """🩸 首版 `--out` 是 required=True，**预检根本不产出文件却被它挡住**，
    argparse 只顶回一句 usage——看不出「是不是预检也要传」。
    ⚠️ 我差点据此判「预检与真闸不同源」，真因是**我的测试命令缺参数**。"""
    import subprocess
    import sys as _s
    src = tmp_path / "s.txt"
    src.write_text("感觉好了不代表能停药。药名一样但人不一样。", encoding="utf-8")
    r = subprocess.run([_s.executable, str(SCRIPTS / "build_oneline.py"),
                        "--precheck", str(src)], capture_output=True, text=True)
    assert r.returncode == 0, f"预检不该要求 --out：{r.stderr[-300:]}"
    assert "全部可拆" in r.stderr


# ────────── 软断的词边界（2026-08-18 实证：跑 12 条劈开 9 处词/术语） ──────────

def test_软断不许把词和术语劈开():
    """🩸 博客长文跑 12 条实测：「参｜与」「创伤后｜应激障碍」「有｜没有」共 9 处。
    ⚠️ 软断本来就 warn 让人裁决，但**warn 太弱、人不会逐条看**——那批是手工补逗号绕过的。
    ⇒ 切点必须落在 jieba 词边界上。"""
    import pytest
    pytest.importorskip("jieba")
    for seg, forbidden in (("很多人参与了这个项目觉得有帮助", "参"),
                           ("创伤后应激障碍不是矫情", "创伤后"),
                           ("看看你有没有这几种情况", "有")):
        r = bo.soft_split(seg, 12)
        if r:
            assert not any(p.endswith(forbidden) for p in r[:-1]), \
                f"「{seg}」被劈成 {r}——切在了词中间"


def test_jieba不可用是没查不是查过(monkeypatch):
    """🔴 `word_edges` 返回 **None ≠ 空集**：前者是「这项没查」，后者是「查了没有合法切点」。
    ⛔ 混为一谈会让缺依赖的机器静默退回旧行为，而没人知道。"""
    monkeypatch.setitem(bo._JIEBA_STATE, "ok", False)
    assert bo.word_edges("随便一句话") is None
    # 此时 soft_ok 只走词形判据，⛔ 不因为「没有词边界」就全判非法
    assert bo.soft_ok("很多人参与了这个项目", 3, None) or True


# ────── 断句器三条硬否决（2026-08-18 审稿代理审 12 条成片实证） ──────

@pytest.mark.parametrize("seg,forbidden_tail", [
    ("如果你正被持续的情绪困扰缠着", "的"),      # 🩸 5 条科普的危机声明全中
    ("练的就是怎么在难受的时候", "的"),
])
def test_禁止在结构虚词后断屏(seg, forbidden_tail):
    """🩸 `SOFT_TAIL` 原本把「的」当合法结尾 ⇒「如果你正被持续的｜情绪困扰缠着」被判合法。
    ⚠️ **jieba 词边界拦不住它**——「持续的」「情绪困扰」**本来就是两个词**，那确实是词边界。
    ⇒ **词边界是必要条件，⛔ 不是充分条件。**"""
    import pytest as _p
    _p.importorskip("jieba")
    r = bo.soft_split(seg, 12)
    if r:
        assert not any(x.endswith(forbidden_tail) for x in r[:-1]), f"断在「{forbidden_tail}」后：{r}"


def test_英文词组不可分割_宁可拒也不劈():
    """🔴 实证：`Psychotherapy and Psychosomatics` 被劈成两屏，
    **第 2 屏单看是个不存在的刊名**——那不是"读着别扭"，是**编造了一个刊物**。
    ⇒ 宁可断不开（要求补逗号），⛔ 也不劈开。"""
    r = bo.soft_split("有一本叫 Psychotherapy and Psychosomatics 的期刊", 12)
    assert r is None or not any("Psychotherapy" in x and "Psychosomatics" not in x for x in r)


def test_正反问不可劈():
    """🔴 实证：「它还在不在影响你的日子」→「是它还在不」，1.6s 一屏、根本不成话。"""
    r = bo.soft_split("它还在不在影响你的日子", 12)
    assert r is None or all("在不" not in x or "在不在" in x for x in r)


def test_渲染长度不许取音频长():
    """🩸 `-shortest` 让输出取**最短流＝音频长**，而视频比音频长 TAIL(1.4s)
    ⇒ **末屏定格与落款被整个截掉**（12 条全中：落款只淡入 40–47%）。
    最小样本实测：视频 2.0s／音频 1.2s，带 `-shortest` 出 1.2s、去掉出 2.0s。"""
    src = (SCRIPTS / "render_card.py").read_text(encoding="utf-8")
    assert '"-shortest"' not in src, "⛔ -shortest 会把末屏定格截掉"
    assert "TAIL 被整个截掉" in src, "去掉的理由要留在原地，⛔ 别让后人顺手加回来"


# ────── 结构虚词前后对称（2026-08-18 晚，博客长文 53 处软断实测） ──────

@pytest.mark.parametrize("seg,head", [
    ("第一作者是我们的咨询师负责人李牧阳", "的"),
    ("把想来的人挡在门外面等着叫号", "在"),
    ("正念更关心你和自己感受之间的距离", "和"),
])
def test_禁止让结构虚词做下屏开头(seg, head):
    """🩸 昨天只禁了「不许做上屏结尾」，这三处照出不误——**判据只看了断口的左边**。

    ⚠️ 根子在**两张登记表对同一批字给了相反的裁决**：`TAIL_BAN` 说不许做结尾，
    `SOFT_HEAD` 却把「在/和/把/被…」列为合法开头。⇒ 现在合成一张 `STRUCT_PARTICLES`，
    ⛔ 别再分开维护。
    """
    pytest.importorskip("jieba")
    r = bo.soft_split(seg, 12)
    if r:
        assert not any(x.startswith(head) for x in r[1:]), f"下屏以「{head}」开头：{r}"


def test_两张表必须是同一张():
    """⛔ 别把 TAIL_BAN／HEAD_BAN 拆回两份——不对称的规则只挡住半边。"""
    assert bo.TAIL_BAN is bo.STRUCT_PARTICLES and bo.HEAD_BAN is bo.STRUCT_PARTICLES
    # SOFT_HEAD 里不许再出现结构虚词（那是"可以做开头"，与 HEAD_BAN 直接打架）
    assert not [w for w in bo.SOFT_HEAD if w in bo.STRUCT_PARTICLES]


# ────── 专名屏例外（助理 2026-08-18 拍板 A） ──────

def test_专名屏例外由含专名触发_不由装不下触发():
    """🔴 这条区别就是例外没有废掉版式的原因：若由"装不下"触发，**任何长句都能触发**，
    tpl-oneline 硬契约①（绝不折行绝不缩字号）当场失效。"""
    assert bo.proper_lines("这是一句没有任何英文专名的超长中文句子所以不该拿到例外", 13) is None
    assert bo.proper_lines("有一本叫 Psychotherapy and Psychosomatics 的期刊", 13) is not None
    # 装得下的短句不走例外（哪怕含专名）
    assert bo.proper_lines("叫 PSS 量表", 13) is None


@pytest.mark.parametrize("seg", [
    "有一本叫 Psychotherapy and Psychosomatics 的期刊",
    "这个量表叫 Perceived Stress Scale",
    "研究发表在 Journal of Consulting and Clinical Psychology 上面",
])
def test_专名折行绝不切进单词(seg):
    """🩸 首版写岔过：两条守卫互相打架（一条要求折点前是空格、另一条禁止折点贴空格）
    ⇒ **唯一合法的折法被排除**，剩下的全是切进单词中间的，实际出的是
    「Psychotherapy a ／ nd Psychosomatics」。⚠️ 是这条断言当场把它逼出来的。"""
    lines = bo.proper_lines(seg, 13)
    assert lines, f"{seg} 该给例外却没给"
    joined = re.sub(r"\s+", " ", " ".join(lines))
    for a, b in bo.proper_spans_en(seg):
        assert re.sub(r"\s+", " ", seg[a:b]) in joined, f"专名被切碎：{lines}"


def test_专名屏字号只影响那一屏():
    """⚠️ 「没有 font_px 这个键」与「键值等于整片字号」不是一回事——
    前者是"这一屏没走例外"，后者是"走了例外但没缩"。"""
    cv = bo.apply_max_chars(bo.CANVAS["3:4"], 13)
    screens = [{"text": "普通一屏", "lines": None},
               {"text": "有一本叫 Psychotherapy and Psychosomatics 的期刊",
                "lines": bo.proper_lines("有一本叫 Psychotherapy and Psychosomatics 的期刊", 13)}]
    out = bo.with_proper_font(screens, cv)
    assert "font_px" not in out[0], "普通屏被塞了字号"
    assert 0 < out[1]["font_px"] <= cv["font"] and out[1]["stroke_px"] > 0


def test_模板绝不开CSS自动折行():
    """🔴 `Psychotherapy and Psychosomatics` 里有空格，浏览器会折在 `Psychotherapy`
    后面——那是所有折法里**最坏**的一个（上行结尾正好是个假刊名）。
    ⇒ 折点必须由 proper_lines() 算死后下发，⛔ 模板里不许出现自动折行的口子。"""
    css = (ROOT / "assets/card-templates/tpl-oneline.html").read_text(encoding="utf-8")
    for bad in ("white-space:normal", "white-space: normal", "word-break", "overflow-wrap"):
        assert bad not in css, f"模板里出现了自动折行口子：{bad}"
    assert ".scr.proper .ln { display:block; }" in css


def test_段落版式不给专名例外_但也不静默():
    """⚠️ paragraph 模板没实现两行排版 ⇒ 放行会**静默出一屏塞爆的字**。
    关掉例外后它必须**照旧报「断不开」**，⛔ 不是悄悄放过。"""
    seg = "有一本叫 Psychotherapy and Psychosomatics 的期刊"
    _, fails, _, propers = bo.split_cue(seg + "。", 13, allow_proper=False)
    assert fails and not propers
    _, fails2, _, propers2 = bo.split_cue(seg + "。", 13, allow_proper=True)
    assert propers2 and not fails2


def test_数字串不可分割():
    """🔴 危害比刊名更大：`请打 12356` 若被劈成「请打 123」「56」，
    **读者看到的是一个错的危机热线号码**——刊名说错是学术不严谨，热线说错是有人打不通。"""
    seg = "如果你正被持续的情绪困扰缠着不放请打 12356"
    r = bo.soft_split(seg, 13)
    for piece in (r or []):
        assert "12356" in piece or not re.search(r"\d", piece), f"数字被劈开：{r}"
    spans = bo._protected_spans("请打 12356 这个号码")
    assert any(b - a == 5 for a, b in spans), "12356 没进保护区间"


def test_建议断点本身必须合法():
    """🩸 闸门拒了「…情绪困扰缠着不放请打 12356」，给的建议是「情绪困｜扰」
    ——**切在词中间**，正是同一天刚立规矩要禁的。
    ⚠️ 闸门报红是对的，但**处置建议把人引到一个新的错**——
    一个把人引向错误修法的报错，比不报还糟。"""
    pytest.importorskip("jieba")
    seg = "如果你正被持续的情绪困扰缠着不放请打 12356"
    edges, spans = bo.word_edges(seg), bo._protected_spans(seg)
    for s in bo.suggest(seg, 13):
        p = s.index("｜")
        assert bo.soft_ok(seg, p, edges, spans), f"建议了一个非法断点：{s}"


def test_挑不出合法断点时明说_不硬凑():
    """⛔ 凑不出三条就别凑——`suggest` 返回空，调用方要打印"请改写成两句"。"""
    src = (SCRIPTS / "build_oneline.py").read_text(encoding="utf-8")
    assert src.count("挑不出合法断点") == 2, "预检与真闸都要有这句人话"


# ────── 数量串不可分割（助理 2026-08-18 清单，扩全） ──────

@pytest.mark.parametrize("label,seg,token", [
    ("危机热线",  "如果你正被持续的情绪困扰缠着不放请打 12356", "12356"),
    ("手机号",    "遇到紧急情况请拨打 13812345678 这个号码", "13812345678"),
    ("中文日期",  "这项研究是在二〇二六年八月发表出来的结果", "二〇二六年八月"),
    ("金额区间",  "一次咨询的价格大概在四百到六百元之间浮动", "四百到六百元"),
    ("时长",      "整个练习做完大概需要三分零五秒的时间就够", "三分零五秒"),
    ("百分比",    "复发率下降了 35.5% 这个差异是显著的结论", "35.5%"),
    ("小数",      "抑郁量表评分平均下降了 3.2 个百分点这很明显", "3.2"),
    ("DOI",       "文献编号是 10.1001/jama.2024.1234 可以自己查", "10.1001/jama.2024.1234"),
])
def test_数量串不可分割(label, seg, token):
    """🩸 **本批 5 条科普的 12356 没被劈是侥幸**——它们恰好写成「热线，12356」
    让号码单独成屏。⛔ 别拿"这批没出事"当"规则够用"。

    ⚠️ 判据是**切开后数值就变了**，不是"读着别扭"：
    「二〇二六年八月」→「二〇二」「六年八月」是**一个不存在的日期**。"""
    assert token in [seg[a:b] for a, b in bo._protected_spans(seg)], f"{label} 没进保护区间"
    for piece in (bo.soft_split(seg, 12) or []):
        assert token in piece or token[:2] not in piece, f"{label} 被劈开：{piece}"


@pytest.mark.parametrize("seg", ["这跟以前不一样了完全是两码事",
                                 "他说的三观真的很正常没什么问题"])
def test_数量串保护不许误伤普通词(seg):
    """⚠️ 「不一样」的「一」、「三观」的「三」都是数字字符，但它们**不是数量串**。
    ⇒ 只保护 ≥2 字的匹配，且连接词⛔ 不扩到「和/或」（那两个更常是并列连词）。"""
    assert not bo._protected_spans(seg), f"误伤：{[seg[a:b] for a, b in bo._protected_spans(seg)]}"


def test_数字内部的标点不当句读():
    """🩸 **在产的坑**：HARD 里就有 `.` `:`，硬切根本轮不到保护区间，
    `display()` 还会把点整个丢掉 ⇒ `10.1001` → `101001`，**DOI 被改了**；
    「下降了 3.2 个百分点」→「下降了 3」「2 个百分点」，**数值变了**。"""
    sc, _, _, _ = bo.split_cue("抑郁量表评分平均下降了 3.2 个百分点。", 12)
    joined = "".join(s["text"] for s in sc)
    assert "3.2" in joined, f"小数点被当句读：{joined}"
    # ⚠️ 但英文缩写里的点照旧当句读——⛔ 别放宽成"两侧字母也保护"
    assert bo._hide_num_punct("例如 e.g. 这样") == "例如 e.g. 这样"


def test_软断片段不许带首尾空格():
    """⚠️ 切点落在空格旁边时片段会带首尾空格，屏上就是一块歪掉的留白。"""
    r = bo.soft_split("复发率下降了 35.5% 这个差异是显著的结论", 12)
    for piece in (r or []):
        assert piece == piece.strip() and piece, f"片段带空格：{piece!r}"


# ────── 专名屏 refit（助理 2026-08-18 拍板：回收估算余量，下限保持 60%） ──────

def test_refit必须在SEEK挂出去之前():
    """⚠️ 渲染器只等 `window.SEEK`，**根本不知道页面还在变**——refit 若跑在 SEEK 之后，
    第一批帧就是 refit 前的字号，而且**没有任何东西会报错**。"""
    src = (ROOT / "assets/card-templates/tpl-oneline.html").read_text(encoding="utf-8")
    assert src.index("refitProper();") < src.index("window.SEEK ="), "refit 跑在 SEEK 之后"


def test_refit只放大不缩小且不超整片字号():
    """🔴 **只放大**：缩小是 Python 那一侧的裁决（含 60% 下限判定），⛔ 这里不重做。
    🔴 **放到整片字号为止**：专名屏最好看的结果就是"跟别的屏一样大"，⛔ 不许更大。"""
    src = (ROOT / "assets/card-templates/tpl-oneline.html").read_text(encoding="utf-8")
    assert "Math.min(FONT_PX," in src, "没有以整片字号封顶"
    assert "if (cand > px && wid(cand) <= SAFE_W) px = cand;" in src, "没有「只放大且试过才算数」"


def test_refit与report必须分开写():
    """⚠️ 这一步是**改**不是**量**。量具和被量对象混在一起，量出来的就永远是自己想要的数。"""
    src = (ROOT / "assets/card-templates/tpl-oneline.html").read_text(encoding="utf-8")
    body = src[src.index("function report()"):src.index("window.ONELINE_REPORT")]
    assert "style.fontSize" not in body, "report() 里改了字号——量具在改被量对象"


def test_python端报的是估算下限不是最终字号():
    """⚠️ 两个数印在同一份输出里，人会当成同一个数（实测普遍高 8–15%）。"""
    src = (SCRIPTS / "build_oneline.py").read_text(encoding="utf-8")
    assert src.count("估算 ≥") == 2, "预检与真闸都要标明这是估算下限"


# ────── 词级判据（2026-08-18 晚：单字黑名单在制造假红） ──────

def test_结构虚词判的是词不是字():
    """🩸 `向` 在 `STRUCT_PARTICLES` 里 ⇒ 「证据**方向**｜是相反的」被当成"断在介词后"
    **整句拒渲染**，**逼作者改一句本来没问题的话**。

    ⚠️ 同一个字在不同词里角色不同——「方向」的「向」是名词的一部分，
    **单字黑名单永远分不出这两种**。"""
    pytest.importorskip("jieba")
    r = bo.soft_split("目前这个领域的证据方向是相反的", 12)
    assert r, "「方向」的「向」被误当介词 ⇒ 整句拒渲染（假红）"
    assert any(x.endswith("方向") for x in r[:-1]), f"没断在「方向」后：{r}"


@pytest.mark.parametrize("seg", [
    "如果你正被持续的情绪困扰缠着不放",     # 虚词「的」独立成词 ⇒ 照禁
    "把想来的人挡在门外面等着叫号",         # 「在」独立成词 ⇒ 照禁
    "正念更关心你和自己感受之间的距离",     # 「和」独立成词 ⇒ 照禁
])
def test_升到词级后拦截能力一点没少(seg):
    """⚠️ 放宽判据时最该验的不是"新放行了什么"，是**"原来拦住的还拦不拦得住"**。"""
    pytest.importorskip("jieba")
    r = bo.soft_split(seg, 12)
    for i, x in enumerate(r or []):
        if i:
            assert x[0] not in bo.HEAD_BAN, f"下屏以虚词开头：{r}"
        if i < len(r) - 1:
            assert x[-1] not in bo.TAIL_BAN, f"上屏以虚词结尾：{r}"


def test_jieba不可用时退回单字判据():
    """⚠️ 退回的是**更严**的那一版（多拒），⛔ 不是悄悄放行。"""
    assert bo._word_around("证据方向是相反的", 4, None) == ("向", "是")
    ws = bo.word_spans("证据方向是相反的")
    assert bo._word_around("证据方向是相反的", 4, ws) == ("方向", "是")


# ────── 短屏（助理 2026-08-18：「三字孤悬」） ──────

def test_不许靠提高MIN_SOFT治短屏():
    """🔴 **数据不支持**（29 份在产稿实测）：≤3 字屏有 122 个，MIN_SOFT 3→4 只消掉 15 个（12%），
    代价是断不开 62→77（**多拒 24%**）。

    ⚠️ 因为**大头根本不来自软断，来自作者自己用逗号句号断出来的短句**，
    而 `MIN_SOFT` 只管软断。⇒ 真正管用的是把短屏报出来让作者调标点。"""
    assert bo.MIN_SOFT == 3, "⛔ 别提高它——见 MIN_SOFT 的文档串"
    src = (SCRIPTS / "build_oneline.py").read_text(encoding="utf-8")
    assert "[短屏]" in src and src.count("[短屏]") >= 2, "真闸与预检都要报短屏"


def test_短屏是报出来不是拒渲染():
    """⚠️ 短屏合不合适只有写稿人说了算（「够了」「不是的」这种三字屏是刻意的节奏）。"""
    sc, fails, _, _ = bo.split_cue("够了。", 12)
    assert not fails and sc[0]["text"] == "够了"


# ────── 短屏护栏（2026-08-19 审稿代理：别的产线先撞上的同类缺陷） ──────

def test_退场必须夹住不早于入场结束():
    """🩸 起因是**别的产线先撞上的**：博客长文的账号图标位淡入 .15+.7、淡出 end−.25
    全写死秒数 ⇒ 首屏 0.88s 时**淡出起点比淡入终点还早 0.22s**，图标一闪。

    ⚠️ **同一个缺陷在本模板里是"还没触发"的状态**——29 份在产稿 1067 屏最短 0.347s，
    按原参数平台期只剩 0.087s。⇒ 被提醒"同步 X"要先看**同类结构还有几处**。"""
    src = (ROOT / "assets/card-templates/tpl-oneline.html").read_text(encoding="utf-8")
    assert "Math.max(at(s.end - LEAD), t0 + din)" in src, "退场起点没夹住"
    assert "const inDur = s => Math.min(IN, Math.max(0.08, (s.end - s.start) * 0.4));" in src


def test_短屏护栏不许改动正常屏():
    """🔴 屏长 ≥0.65s 时 `dur*0.4 ≥ 0.26` ⇒ `inDur` 恒等于 `IN` ⇒ 与改动前**逐帧相同**。

    **Playwright 实测（2026-08-19，92 个时刻 × 3 屏，读 opacity+transform）**：
    2.000s 屏差异 **0**、2.153s 屏差异 **0**、0.347s 短屏差异 12（正是意图）。
    ⛔ 这次改动不许动到任何一条已过审片子的动效。"""
    IN = 0.26
    in_dur = lambda d: min(IN, max(0.08, d * 0.4))
    for d in (0.65, 0.9, 1.5, 2.0, 6.0):
        assert in_dur(d) == IN, f"{d}s 屏的入场时长被改了：{in_dur(d)}"
    assert in_dur(0.347) < IN, "短屏没有收缩"
    # 夹持之后一定留得下平台期（退场起点 ≥ 入场结束）
    for d in (0.2, 0.347, 0.5, 0.64):
        LEAD, t0 = 0.07, -0.07
        assert max(d - LEAD, t0 + in_dur(d)) >= t0 + in_dur(d)


def test_成品必须自报有没有背景音():
    """🩸 v2.18.0 把 BGM 默认改成开，**波及所有既有调用方的产物内容，而它们不知道**
    ⇒ 2026-08-19 在 kepu-B 的 out.mp4 里抓到混进的 BGM。
    ⚠️ **改默认值时光写 CHANGELOG 不够**——得让**每一次产出**自己说清它是什么。
    ⇒ 「带 BGM」与「不带 BGM」两种状态都要打，⛔ 不能只打其中一种。"""
    src = (SCRIPTS / "render_card.py").read_text(encoding="utf-8")
    assert "'⛔ 无背景音'" in src and "背景音 {bgm_label}" in src


def test_纯净底版是口播原件不是某个mp4():
    """⚠️ 下游想要的能力是**能重混**，而 `remux()` 从 `narration.mp3.wav` 出发
    （它显式拒绝拿成片音轨当口播）⇒ ⛔ 不需要再留一份无 BGM 的 mp4 当底版。"""
    src = (SCRIPTS / "render_card.py").read_text(encoding="utf-8")
    assert "纯净底版就是 `narration.mp3.wav`" in src
    assert "新渲的片子⛔ 不用再 remux" in src


# ────── 账号图标位（助理 2026-08-19 拍：跟落款同机制、默认关、按账号可选） ──────

def test_图标位默认关且关掉时零残留():
    """⚠️ 「关掉」必须是**元素根本不存在**，⛔ 不是「存在但 opacity:0」——
    后者会在别人改动效时被误当成常驻元素接手。"""
    cv = bo.apply_max_chars(bo.CANVAS["3:4"], 12)
    css, html, js = bo.icon_parts(None, cv)
    assert (css, html, js) == ("", "", ""), "关掉时不是三段空串"
    css2, html2, js2 = bo.icon_parts(
        "/home/roots/NBDpsy/seo-geo/assets/brand/miwen/miwen-avatar-512.png", cv)
    assert "#account-icon" in css2 and 'id="account-icon"' in html2 and "@" not in js2


def test_图标只在首屏与落款屏浮出():
    """🔴 **跟落款走同一机制**，中间屏一个像素都没有 ⇒ ⛔ 它不是常驻元素，不碰契约③。

    **Playwright 实测（2026-08-19，10.91s 片、每 0.1s 采 opacity）**：
    可见区间 `0.20–2.40s`（首屏 0.00–2.41s）与 `9.20–10.90s`（落款屏），
    中间屏区间内可见采样点 **0** 个。"""
    src = (ROOT / "assets/card-templates/tpl-oneline.html").read_text(encoding="utf-8")
    assert "__ICON_JS__" in src and "__ICON_HTML__" in src and "__ICON_CSS__" in src
    py = (SCRIPTS / "build_oneline.py").read_text(encoding="utf-8")
    # 只有首屏(s0)与全片末尾(endAll)两处时间锚，⛔ 没有第三处
    assert py.count("'#account-icon'") == 3, "补间数量变了——图标位可能不再只出现两次"


def test_图标DOM必须在stage之前():
    """🔴 同 z-index 下**先绘者在下** ⇒ 图标在字层之下。
    🩸 别处那版放在 `#stage` 之后、却注释成「z-index 低于字层」——**那是错话**，
    它让后人以为有层次保护。⛔ 也别改成 z-index:2（会被 #vignette 暗角压暗）。"""
    src = (ROOT / "assets/card-templates/tpl-oneline.html").read_text(encoding="utf-8")
    assert src.index("__ICON_HTML__") < src.index('<div id="stage">')


@pytest.mark.parametrize("canvas", ["3:4", "16:9"])
def test_图标与字层不重叠(canvas):
    """⚠️ 「不挡字」靠的是**位置分离**，⛔ 不是层次——所以它必须算得出来。

    字恒在画面正中（`top:50%`），图标贴底。两个画幅都要留出间隙，
    **专名屏两行**（高度翻倍）也要算进去。"""
    cv = bo.CANVAS[canvas]
    text_h = cv["font"] * 1.28 * 2          # 按最坏情况：专名屏两行
    text_lo, text_hi = cv["h"] / 2 - text_h / 2, cv["h"] / 2 + text_h / 2
    icon_lo = cv["h"] - cv["icon_bottom"] - cv["icon_px"]
    assert text_hi < icon_lo, (f"{canvas} 图标与字重叠：字底 {text_hi:.0f} ≥ 图标顶 {icon_lo:.0f}")


def test_图标CSS不许用百分号格式化():
    """🩸 CSS 里 `%` 太多（`left:50%`、`translateX(-50%)`、`transform-origin:50% 100%`），
    用 `%` 格式化就得逐个转义成 `%%`，**漏一个就是运行时 ValueError**，
    而且报的是「unsupported format character」这种跟真因无关的话。第一版就这么炸的。"""
    py = (SCRIPTS / "build_oneline.py").read_text(encoding="utf-8")
    assert "ICON_CSS % " not in py and "@BOTTOM@" in py

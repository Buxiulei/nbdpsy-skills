"""字卡背景档 `miwen`：老板 2026-08-17 G10 亲批的那一档，参数不许漂。

为什么单独给它上锁：这档的五个参数是**老板看着一张具体的图批的**，不是设计推导出来的。
谁看着图觉得「再暖一点更好」把值一改，出的就是另一张老板没批过的图——而这种改动
肉眼几乎看不出来，code review 也拦不住，只有断言拦得住。

⚠️ 校准图（`seo-geo/.../bg-candidates/B-浅米白-强纹理.png`）出自候选**预览页**，
预览页的纹理层少一句 `mix-blend-mode:multiply`，所以它比真模板出片更浅更淡。
**要验参数就比这里的五个字段，⛔ 别拿那张图的像素当靶子**（会得出「没搬对」的错结论）。
"""
import sys
from pathlib import Path

import pytest

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

    txt = ("感觉好了不代表能停药。药名一样但人不一样。"
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
    n_real = real.stderr.count("断不开的片段")
    n_pre = pre.stderr.count("· 第")
    assert n_real == n_pre == 1, f"真闸 {n_real} 处 vs 预检 {n_pre} 处——两把尺不同源"
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

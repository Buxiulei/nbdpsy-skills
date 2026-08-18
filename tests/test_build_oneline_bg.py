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

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


def test_miwen是新片首选档而现有两档原样保留():
    """加档不许动老档——在产片子还用着 liaoyu / kepu。"""
    assert set(bo.BG) == {"liaoyu", "kepu", "miwen"}
    assert bo.BG["kepu"]["base"] == "#EDEFF1"
    assert bo.BG["liaoyu"]["base"] == "#E8D8C4"


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

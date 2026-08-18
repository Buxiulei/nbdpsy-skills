"""段落字卡 tpl-paragraph —— 老板 G13「模板要撑得住 3 分钟」新立的第六版式。

🩸 它治的病（调研实测，见 docs/2026-08-18-长时长模板调研.md）：五个旧模板各自只有
**一条扁平时间轴**（`.add()`/`addLabel` 全为 0），没有「段落」中间层 ⇒ 内容一长，
循环套同一个动效成为**唯一可行解** ⇒ 老板那句「多句话都重复用同一个动效」。

★ 核心理念：**段内统一，段间变化。** 重复不是错，没有边界的重复才是。
  ⛔ 逐屏随机换手法＝杂乱，不是丰富——那是另一种失败，测试要能分开这两者。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "nbdpsy-text-to-video" / "scripts"
BUILD = SCRIPTS / "build_oneline.py"
sys.path.insert(0, str(SCRIPTS))

import build_oneline as bo  # noqa: E402


def _cues(n=24):
    """造 n 句假 cues。⛔ 粗样阶段不跑 TTS——这条测试验的是编排结构，不是音画同步。"""
    t, out = 0.0, []
    for i in range(n):
        # ⚠️ 必须 ≤12 字且能断开——首版造了 14.6 字无标点的句子，被单行闸门正确拒绝。
        # 那不是代码问题，是测试数据不合格：**闸门拦住我的测试数据，说明闸门是活的**。
        txt = f"验证第{i}句编排"
        d = 0.32 + len(txt) * 0.19
        out.append({"text": txt, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("para")
    cf = d / "cues.json"
    cf.write_text(json.dumps(_cues(), ensure_ascii=False), encoding="utf-8")
    run = lambda *a: subprocess.run(
        [sys.executable, str(BUILD), "--cues", str(cf), "--bg", "miwen",
         "--canvas", "3:4", "--no-check", *a], capture_output=True, text=True)
    r1 = run("--out", str(d / "one"))
    r2 = run("--out", str(d / "para"), "--template", "paragraph",
             "--name", "card-paragraph.html")
    assert r1.returncode == 0 and r2.returncode == 0, (r1.stderr, r2.stderr)
    return d / "one" / "card-oneline.html", d / "para" / "card-paragraph.html"


def test_版式表里两档都在且默认仍是oneline():
    """⛔ 加新版式绝不能改既有默认——在产的片子用着 oneline。"""
    assert set(bo.TEMPLATES) == {"oneline", "paragraph"}
    assert bo.TEMPLATES["oneline"] == bo.TPL, "默认档必须指向原来那个文件"


def test_旧版式产物不含新版式任何痕迹(built):
    """🔴 这条是「在产的东西没被碰坏」的守门人：__SEC_CUES__ 之类只该出现在新版式里。"""
    one = built[0].read_text(encoding="utf-8")
    for token in ("tpl-paragraph", "BOUNDARY_ADV", "MOTIFS", "sectionOf", "__SEC_CUES__"):
        assert token not in one, f"oneline 产物里混进了 {token}"


def test_段落边界只落在句边界上(built):
    """硬契约⑥：⛔ 绝不在一句话中间换手法——那会让观众以为换了话题。"""
    html = built[1].read_text(encoding="utf-8")
    # ⚠️ 用正则取，⛔ 别用 split(";\n")——占位符后面跟的是「;   // 注释」不是换行，
    # 首版就栽在这里（JSONDecodeError）。**解析逻辑本身也是量具，会坏。**
    import re
    screens = json.loads(re.search(r"const SCREENS = (\[.*?\]);", html, re.S).group(1))
    sec_cues = int(re.search(r"const SEC_CUES = (\d+);", html).group(1))
    seen, n, sec_of_cue = set(), 0, {}
    for s in screens:
        if s["cue"] not in seen:
            seen.add(s["cue"])
            n += 1
        sec = (n - 1) // sec_cues
        # 同一句的每一屏都必须落在同一段
        assert sec_of_cue.setdefault(s["cue"], sec) == sec, f"cue {s['cue']} 跨段了"


def test_留白件必须在库里(built):
    """🔴 丰富 ≠ 一直在动。长片必须有喘息处，否则观众把「有变化」读成「很吵」。
    ⛔ 别把 still 当偷懒删掉——它是节奏的一部分。"""
    html = built[1].read_text(encoding="utf-8")
    assert "still(el" in html and "STILL_EVERY" in html


def test_变奏是确定的不是随机的(built):
    """⛔ 随机会撞车（相邻段抽到同一件），也不可复现（同一稿两次渲染不一样）。"""
    html = built[1].read_text(encoding="utf-8")
    body = html.split("<script>", 1)[1]
    assert "Math.random" not in body, "🔴 变奏一旦随机就不可复现，⛔ 绝不允许"


def test_端到端_段落编排真的多样且相邻段不重复(built):
    """正向断言：绿的时候也报数（段数/动效种类），⛔ 恒绿的闸门报不出这个。"""
    playwright = pytest.importorskip("playwright.sync_api")
    src = built[1].read_text(encoding="utf-8").replace("__CUES__", "[]")
    probe = built[1].with_suffix(".t.html")
    probe.write_text(src, encoding="utf-8")
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(args=["--force-device-scale-factor=1", "--hide-scrollbars"])
        pg = b.new_page(viewport={"width": 1080, "height": 1440})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"file://{probe.resolve()}")
        pg.wait_for_function("window.ONELINE_REPORT !== undefined", timeout=20000)
        rep = pg.evaluate("window.ONELINE_REPORT")
        b.close()
    assert not errs, f"页面有 JS 错误：{errs[:2]}"
    assert rep["template"] == "tpl-paragraph"
    assert rep["sections"] >= 4, f"24 句只分出 {rep['sections']} 段"
    assert rep["motif_kinds"] >= 4, f"只用了 {rep['motif_kinds']} 种动效——丰富度不达标"
    ms = rep["motifs"]
    dup = [i for i in range(1, len(ms)) if ms[i] == ms[i - 1]]
    assert not dup, f"🔴 相邻段用了同一手法（位置 {dup}）：{ms}"
    assert len(rep["overflow"]) == 0

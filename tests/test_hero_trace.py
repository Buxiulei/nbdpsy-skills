"""hero ↔ 出图数据不一致却没留痕时提个醒（**提示级，⛔ 不是闸门**）。

🔴 这个工具最重要的性质是**它永远不阻断**：压缩是合法的（版式有 ≤6 字 / 字高 9–13% 的硬约束），
缺的只是留痕。⚠️ 做成阻断闸的话，人会去**补一条假留痕**把红灯消掉——
**闸门逼出来的留痕，比没有留痕更坏**：它看起来是证据，实际是为过闸编的。
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_hero_trace as ht  # noqa: E402

DOC = """# 五篇

### A · 账号甲｜标题甲

- **hero**：放纵是躲开 / **善待是走近**
  <br>⚠️ 2026-08-21 排版缩短：定稿为「放纵是躲开难受／对自己好是先承认它」，出图时压成 5+5。
- **副行**：被误解的三件事

### C · 账号丙｜标题丙

- **hero**：夸自己是门手艺 / **不是心理素质**
- **副行**：缺的是语料，不是意愿
"""


def mk(tmp_path, hero, doc=DOC):
    (tmp_path / "doc.md").write_text(doc, encoding="utf-8")
    (tmp_path / "cover.json").write_text(json.dumps({"hero": hero}, ensure_ascii=False),
                                         encoding="utf-8")
    return tmp_path / "doc.md", tmp_path / "cover.json"


# ────────── 三条主判据 ──────────

def test_逐字一致不提示(tmp_path):
    d, c = mk(tmp_path, ["夸自己是门手艺", "不是心理素质"])
    r = ht.check(d, "C", c)
    assert r["same"] is True and r["hint"] is None


def test_不一致但有留痕不提示(tmp_path):
    """**压缩是合法的**——A 篇文档里写了为什么压、压成了什么，那就够了。"""
    d, c = mk(tmp_path, ["放纵是躲开难受", "对自己好是先承认它"])
    r = ht.check(d, "A", c)
    assert r["same"] is False and r["has_trace"] is True and r["hint"] is None


def test_不一致且无留痕才提示(tmp_path):
    d, c = mk(tmp_path, ["夸自己要练", "不是天生的"])
    r = ht.check(d, "C", c)
    assert r["same"] is False and r["has_trace"] is False and r["hint"]
    assert "没有压缩留痕" in r["hint"]
    assert "别为了消掉它去补一句假留痕" in r["hint"], \
        "提示里必须写明⛔别补假留痕——否则这个提示自己就会诱发造假"


# ────────── 提示级：exit 恒 0 ──────────

@pytest.mark.parametrize("hero,sec", [
    (["夸自己要练", "不是天生的"], "C"),      # 会提示
    (["夸自己是门手艺", "不是心理素质"], "C"),  # 不提示
])
def test_exit恒为0(tmp_path, hero, sec, capsys):
    """🔴 **⛔ 绝不能变成闸门**。这条测试红了，说明有人把提示改成了阻断——
    那会逼人补假留痕，而假留痕比没有留痕更坏。"""
    d, c = mk(tmp_path, hero)
    assert ht.main(["--doc", str(d), "--section", sec, "--data", str(c)]) == 0


def test_查不成也不阻断(tmp_path):
    """⚠️ 一个提示工具**⛔ 不该因为自己没查成就让整条产线停下来**。
    而且要把「没查成」和「不一致」分清——⛔ 别把前者渲染成后者。"""
    d, c = mk(tmp_path, ["x"])
    r = ht.check(d, "Z", c)                       # 篇目不存在
    assert "没有篇目" in r["hint"] and r["same"] is None
    r = ht.check(d, "A", Path("/nonexistent.json"))   # 出图数据不存在
    assert "不存在" in r["hint"] and r["same"] is None
    r = ht.check(Path("/nonexistent.md"), "A", c)     # 文档不存在
    assert "不存在" in r["hint"] and r["same"] is None
    assert ht.main(["--doc", str(d), "--section", "Z", "--data", str(c)]) == 0


# ────────── 宽容归一：⛔ 别让它恒响 ──────────

@pytest.mark.parametrize("hero", [
    ["夸自己是门手艺", "不是心理素质"],
    ["夸自己是门手艺 ", " 不是心理素质"],        # 空白
    ["夸自己是门手艺，", "不是心理素质。"],        # 标点
    ["**夸自己是门手艺**", "不是心理素质"],       # markdown
])
def test_标点空白markdown差异不算不一致(tmp_path, hero):
    """🩸 文档里写的是 `放纵是躲开 / **善待是走近**`（带 markdown 与斜杠），
    出图数据里是列表。拿原始串比会**每一篇都提示**，
    而**恒响的提示三天之内就没人看了**——那比没有提示更糟，
    因为它还占着"我们查过了"的位置。"""
    d, c = mk(tmp_path, hero)
    assert ht.check(d, "C", c)["same"] is True


def test_真的换了词就要认出来(tmp_path):
    """⚠️ 反向也要测：归一得太狠就成了恒绿，那才是真的白做。"""
    d, c = mk(tmp_path, ["夸自己是门本事", "不是心理素质"])
    assert ht.check(d, "C", c)["same"] is False


# ────────── 留痕的范围 ──────────

def test_留痕只看这一条hero附近(tmp_path):
    """⛔ 别扫整篇——别处随便提一句「排版」就把这条静音了。"""
    doc = DOC + """
### D · 账号丁｜标题丁

- **hero**：完全不同的话
- 备注：这一篇的排版缩短说明写在别的地方
"""
    d, c = mk(tmp_path, ["另一句"], doc=doc)
    r = ht.check(d, "D", c)
    assert r["same"] is False
    assert r["has_trace"] is True, "同一条 hero 下面的续行里有「排版」，算留痕"
    # A 篇的留痕⛔不该把 C 篇静音
    _, c2 = mk(tmp_path, ["夸自己要练", "不是天生的"], doc=doc)
    assert ht.check(d, "C", c2)["has_trace"] is False, "A 篇的留痕漏到 C 篇了"


def test_hero值不含留痕注记(tmp_path):
    """`<br>` 之后是留痕注记，⛔ 不是 hero 的一部分——混进去会让比对永远不一致。"""
    d, c = mk(tmp_path, ["放纵是躲开", "善待是走近"])
    r = ht.check(d, "A", c)
    # ⚠️ `doc_hero` 保留**文档原文**（含 markdown）——提示里展示时人要能跟文档逐字对上；
    #    去 markdown 只发生在**比对**那一步（`norm`）。
    assert r["doc_hero"] == ["放纵是躲开", "**善待是走近**"]
    assert r["same"] is True


# ────────── 跨线：拒渲文案要带来源 ──────────

def test_拒渲文案带留痕行来源():
    """🔴 `render_cover.py` 是**两条线共用**的（公众号线经 `gen_gzh_images.py` 调它）。
    两条线的稿子**只隔一层目录**，哪天有人在 `wechat/<slug>/` 下放一份 `00-overview.md`，
    公众号出图就会**突然开始拒渲**，而红灯说的是「风格档案对不上档案库」——
    **在公众号线的语境里没人看得懂那是什么**。⇒ 报出"我是从哪读到这句的"。"""
    src = (SCRIPTS / "render_cover.py").read_text(encoding="utf-8")
    assert "def style_source(" in src
    assert "style_source(dpath, args.style_profile)" in src


def test_留痕查找逻辑只有一份():
    """⛔ 别为了拿路径再抄一遍查找逻辑——两处一漂，报出来的来源就是假的。"""
    gen = (SCRIPTS / "gen_images.py").read_text(encoding="utf-8")
    assert gen.count('/ "00-overview.md"') == 1, "查找留痕文件的地方不止一处"
    assert "_style_trace_hit(note)" in gen

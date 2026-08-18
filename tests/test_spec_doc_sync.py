"""`card-video-spec.md` 的两张参数表必须跟代码对得上。

为什么要有这道闸：那两张表漂了半年没人察觉，而且 `16:9` 的「12 字实占 1562」**从写下那天起
就没对过**——它是拿 `3:4` 的描边 13 去算 `16:9` 的（`128×12+2×13`），两档参数混着算的。
这类错肉眼永远发现不了（数字看着都很像那么回事），只有拿公式重算才露馅。
加档的人不会记得回去改文档，但会看到测试红。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🩸 **这道闸自己最容易变恒绿**，改它之前先看清三条：

  ① regex 没匹配到表格行 → 循环体一次都没进 → 全绿。**闸在，但从此再也不会红。**
     所以 `_parse_*` 一行都没读到就 **raise**，⛔ 不返回空 dict；而且下面先断言
     **行数 == len(BG)/len(CANVAS)**，⛔ 不是「parse 出几行就比几行」（那正是恒绿的写法）。
  ② 数值比，⛔ 不比字符串：源码写 `0.80`，Python 存成 `0.8`，字符串比对会报**假红**
     （2026-08-17 踩过，差点照着假红去改一版本来正确的文档）。
  ③ `CANVAS` 那几个数**用公式现算**，⛔ 别抄代码里的字面量——抄字面量的话，
     「两档串行」那种错照样能过（`1562` 抄进来就成了「标准答案」）。
     **测试不能与被测对象共享同一个错。**

⚠️ 本闸只管「文档 ↔ 代码一致」，**不保证公式本身对**（那由 build_oneline 的像素闸兜底：
   它真开一次 Chromium 量每屏渲染宽度）。两者是两层，别指望这一层替那一层。

⛔ 报红时先看是哪一类：**表格数字对不上 → 改文档；表格格式变了 → 改本文件的 parse 规则。**
   ⛔ 别反过来改数据让测试过。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SPEC = ROOT / "nbdpsy-text-to-video" / "references" / "card-video-spec.md"
sys.path.insert(0, str(ROOT / "nbdpsy-text-to-video" / "scripts"))

import build_oneline as bo  # noqa: E402

# 表头认哪张表：档位表认 `--bg`，画幅表认 `--canvas`。
# ⚠️ 不能只认「| 档 |」——落款反差表的表头也是「| 档 |」，会抓错表。
_BG_ROW = re.compile(
    r"\|[^|]*\|\s*\**`(?P<key>[a-z0-9_]+)`\**\s*\|"          # --bg 列
    r"\s*`(?P<base>#[0-9A-Fa-f]{6})`[^|]*\|"                  # 底色
    r"\s*`(?P<ink>#[0-9A-Fa-f]{6})`[^|]*\|"                   # 墨色
    r"[^|]*?`(?P<freq>[.\d]+) / (?P<oct>\d+) / (?P<seed>\d+) / (?P<alpha>[.\d]+)`"
    r"\s*·\s*(?P<scale>\d+)px"                                # 纹理格
)
_CANVAS_ROW = re.compile(
    r"\|\s*`(?P<key>[0-9]+:[0-9]+)`\s*\|"
    r"\s*(?P<w>\d+)×(?P<h>\d+)\s*\|"
    r"\s*(?P<font>\d+)px\s*\|\s*(?P<stroke>\d+)px\s*\|"
    r"\s*(?P<safe>\d+)px\s*\|\s*(?P<need>\d+)px\s*\|"
)


def _table_rows(md: str, header_token: str):
    """取「表头含 header_token」那张表的数据行（跳过表头与 |---| 分隔行）。"""
    rows, in_table = [], False
    for line in md.splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        if header_token in line:
            in_table = True
            continue
        if in_table and not set(line) <= set("|- :"):
            rows.append(line)
    return rows


def _parse_bg_table(md: str) -> dict:
    rows = _table_rows(md, "`--bg`")
    out = {}
    for line in rows:
        m = _BG_ROW.search(line)
        if not m:
            raise AssertionError(
                f"❌ 档位表这一行认不出来了：\n    {line.strip()}\n"
                f"   表格格式变了 → **改本文件的 _BG_ROW 规则**；⛔ 别去改文档里的数"
                f"（那张表可能是对的，错的是这把尺）。"
            )
        out[m["key"]] = dict(
            base=m["base"], ink=m["ink"], tex_scale=int(m["scale"]),
            turb=dict(freq=float(m["freq"]), octaves=int(m["oct"]),
                      seed=int(m["seed"]), alpha=float(m["alpha"])),
        )
    if not out:                       # 🩸 一行都没读到 = 尺子瞎了，⛔ 不许静默放行
        raise AssertionError(
            f"❌ 在 {SPEC.name} 里一行档位表都没读到（表头 `--bg` 那张）。"
            f"\n   要么表没了，要么表头/列序变了 → **改本文件的 parse 规则**。"
            f"\n   ⛔ 这不是「没有档要检查」，恒绿的闸等于没有闸。"
        )
    return out


def _parse_canvas_table(md: str) -> dict:
    rows = _table_rows(md, "`--canvas`")
    out = {}
    for line in rows:
        m = _CANVAS_ROW.search(line)
        if not m:
            raise AssertionError(
                f"❌ 画幅表这一行认不出来了：\n    {line.strip()}\n"
                f"   表格格式变了 → **改本文件的 _CANVAS_ROW 规则**；⛔ 别去改文档里的数。"
            )
        out[m["key"]] = {k: int(m[k]) for k in ("w", "h", "font", "stroke", "safe", "need")}
    if not out:
        raise AssertionError(
            f"❌ 在 {SPEC.name} 里一行画幅表都没读到（表头 `--canvas` 那张）。"
            f"\n   → **改本文件的 parse 规则**；⛔ 恒绿的闸等于没有闸。"
        )
    return out


def _expected_canvas(cv: dict) -> dict:
    """按 instantiate 里那三条公式**现算**，⛔ 不抄代码/文档里的字面量。

    抄字面量就等于把「两档串行」那种错固化成标准答案——测试必须独立复算。
    """
    return dict(
        w=cv["w"], h=cv["h"], font=cv["font"],
        stroke=round(cv["font"] * 0.17),
        safe=cv["w"] - 2 * cv["pad"],
        need=cv["font"] * cv["max_chars"] + 2 * round(cv["font"] * 0.17),
    )


@pytest.fixture(scope="module")
def md():
    return SPEC.read_text(encoding="utf-8")


# ────────────────────────── ① 先证明读到了东西 ──────────────────────────

def test_两张表都读到了且行数与代码一致(md):
    """规模断言必须在前：先证明尺子读到了东西，再谈比对。

    ⛔ 「parse 出几行就比几行」是恒绿写法——一行都没 parse 到时它也全绿。
    """
    bg, canvas = _parse_bg_table(md), _parse_canvas_table(md)
    assert set(bg) == set(bo.BG), (
        f"档位表与 BG 表对不上：文档有 {sorted(bg)}，代码有 {sorted(bo.BG)}。"
        f"\n   加了背景档没在 spec 里补行 → 补文档；删了档 → 删文档那行。"
    )
    assert set(canvas) == set(bo.CANVAS), (
        f"画幅表与 CANVAS 表对不上：文档有 {sorted(canvas)}，代码有 {sorted(bo.CANVAS)}。"
    )


# ────────────────────────── ② 逐项比数值 ──────────────────────────

def test_档位表的底色墨色与turb与代码逐项相等(md):
    """⚠️ 按数值比：源码 `0.80` 在 Python 里是 `0.8`，字符串比会报假红。"""
    doc = _parse_bg_table(md)
    for key, code in bo.BG.items():
        # ⛔ 别写成 doc[key]：漏行时抛 KeyError，报错不可操作（2026-08-18 实撞）
        assert key in doc, f"spec 档位表里没有 `{key}` 那一行——加了背景档要补文档表格"
        d = doc[key]
        assert d["base"].upper() == code["base"].upper(), f"{key} 底色：文档 {d['base']} ≠ 代码 {code['base']}"
        assert d["ink"].upper() == code["ink"].upper(), f"{key} 墨色：文档 {d['ink']} ≠ 代码 {code['ink']}"
        assert d["tex_scale"] == code["tex_scale"], f"{key} 纹理格：文档 {d['tex_scale']} ≠ 代码 {code['tex_scale']}"
        assert d["turb"] == code["turb"], f"{key} turb：文档 {d['turb']} ≠ 代码 {code['turb']}"


def test_画幅表的四个数与公式算出来的相等(md):
    """⛔ 期望值现算，不抄字面量——`16:9` 的 1562 就是抄来的错（拿 3:4 的描边算的）。"""
    doc = _parse_canvas_table(md)
    for key, cv in bo.CANVAS.items():
        assert doc[key] == _expected_canvas(cv), (
            f"{key} 画幅表对不上：\n   文档 {doc[key]}\n   公式 {_expected_canvas(cv)}"
            f"\n   公式：描边=round(字号×0.17)，安全区=w-2×pad，12字实占=字号×12+2×描边"
        )


# ────────────────────────── ③ 元测试：证明这道闸真会红 ──────────────────────────
# 上面三条全绿，可能是「文档确实对」，也可能是「尺子根本没在读」。这一节把后者排除掉。

def test_改一个数就必须红_否则说明尺子没在读(md):
    """把文档里的 `.24` 改成 `.99`，比对必须失败。不失败＝这道闸是恒绿的摆设。"""
    # ⚠️ 变异目标必须在表里唯一：`.24 / 5 / 17 / .85` 现在 miwen 和 xianwen 两行都有，
    # 拿它做变异会改到第一行、却去查第二行（2026-08-18 实撞）。liaoyu 那组是唯一的。
    assert md.count("`.80 / 4 / 7 / .55`") == 1, "变异目标不再唯一，换一个唯一的"
    mutated = md.replace("`.80 / 4 / 7 / .55`", "`.99 / 4 / 7 / .55`", 1)
    assert mutated != md, "变异没生效（表格文案变了？），这条元测试本身要更新"
    doc = _parse_bg_table(mutated)
    assert doc["liaoyu"]["turb"]["freq"] == 0.99, "尺子没读到被改的那个数——parse 规则已失效"
    assert doc["liaoyu"]["turb"] != bo.BG["liaoyu"]["turb"]


def test_画幅表被改也必须红(md):
    """把 `16:9` 的实占改回历史错值 1562，必须与公式算出的 1604 不等。"""
    mutated = md.replace("| 1620px | 1604px |", "| 1620px | 1562px |", 1)
    assert mutated != md, "变异没生效，这条元测试本身要更新"
    doc = _parse_canvas_table(mutated)
    assert doc["16:9"]["need"] == 1562
    assert doc["16:9"] != _expected_canvas(bo.CANVAS["16:9"]), "历史错值居然没被判红"


def test_表格没了要报错而不是静默放行():
    """最要命的那条：表被删/表头改名时，⛔ 不许返回空 dict 全绿。"""
    for parse in (_parse_bg_table, _parse_canvas_table):
        with pytest.raises(AssertionError, match="一行.*都没读到"):
            parse("# 一份没有任何参数表的文档\n\n正文而已。\n")


def test_行认不出来时报的是改尺子而不是改文档():
    """报错要可操作：格式变了该改 parse 规则，⛔ 别让人转头去改本来正确的文档。"""
    broken = ("| 档 | `--bg` | 底色 |\n|---|---|---|\n"
              "| 米纹 | `miwen` | 底色写成了大白话 |\n")
    with pytest.raises(AssertionError, match="改本文件的 _BG_ROW 规则"):
        _parse_bg_table(broken)

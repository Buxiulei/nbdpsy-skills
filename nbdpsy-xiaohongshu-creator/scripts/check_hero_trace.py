#!/usr/bin/env python3
"""交付文档的 hero ↔ 出图数据的 hero：**不一致却没留痕**时提个醒。

    check_hero_trace.py --doc 五篇-封面与正文栏.md --section A --data A/cover.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 **这是提示级，⛔ 不是闸门：exit 恒为 0。**

**压缩是合法的**——文档里定稿的 hero 常常放不进版式（最长行 ≤6 字、字高 9–13%），
排版步有**有限改文案权**，压成 5+5 是正当操作。⇒ 缺的从来不是"别压缩"，是**留痕**。

⚠️ **⛔ 绝不能把它做成阻断闸**：一旦不留痕就发不出去，人会去**补一条假留痕**把红灯消掉
——那时文档里多了一句"已按排版缩短"，而真实过程谁也不知道。
🔴 **闸门逼出来的留痕，比没有留痕更坏**：它看起来是证据，实际是为过闸编的。
（同族判据：`publish_note` 里"⛔ 不让 typeset 写一个不真实的 `cover_only: True` 混过去"。）

## 判据

1. 从交付文档取该篇的 `- **hero**：…` 行；
2. 与出图数据（`cover.json` 的 `hero`）**逐字比**（先做宽容归一，见 `norm`）；
3. 一致 → 不提示；
4. 不一致 **且** 该行附近有**压缩留痕**（「缩短/压缩/排版/压成/改文案」等词）→ 不提示；
5. 不一致 **且** 没有留痕 → **提示**（说清两边分别是什么、该往哪边补）。

🩸 **为什么要做宽容归一**：文档里写的是 `放纵是躲开 / **善待是走近**`（带 markdown 与斜杠），
出图数据里是 `["放纵是躲开", "善待是走近"]`。拿原始串比会**每一篇都提示**，
而**恒响的提示三天之内就没人看了**——那比没有提示更糟，因为它还占着"我们查过了"的位置。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

输出 JSON（stdout 只有 JSON，人话走 stderr）：
  {"section", "doc_hero": [...], "data_hero": [...], "same": bool,
   "has_trace": bool, "hint": str|null, "ok": true}
exit：**恒 0**（提示级）。找不到文档/篇目/数据时 stderr 说明并给 `hint`，exit 仍是 0
      ——⚠️ 一个提示工具**⛔ 不该因为自己没查成就让整条产线停下来**。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: 留痕注记里出现任一即算"这次压缩说清楚了"。⚠️ 宽松是有意的：
#: 判据不是"话说得够不够好"，是"**有没有人在这里写过一句话**"。
TRACE_WORDS = ("缩短", "压缩", "排版", "压成", "改文案", "改过文案", "精简", "截片段")

#: hero 行：`- **hero**：值` / `- **hero**: 值`（全角半角冒号都收）
HERO_LINE = re.compile(r"^\s*[-*]\s*\*\*hero\*\*\s*[:：]\s*(.+)$")
#: 结构化字段行：`- **副行**：…` / `- **身份行**：…`——**hero 这一条目到此为止**
FIELD_LINE = re.compile(r"^\s*[-*]\s*\*\*[^*]+\*\*\s*[:：]")
#: 篇目标题：`### A · 账号名｜标题`
SECTION_LINE = re.compile(r"^#{2,4}\s*([A-Za-z0-9]+)\s*[·．.、]")


def norm(s: str) -> str:
    """归一到"只剩字"：去 markdown 强调、去空白、去分隔与标点。

    ⚠️ **宽容归一是必需的**（见文件头）：文档里是 `放纵是躲开 / **善待是走近**`，
    出图数据里是 `["放纵是躲开", "善待是走近"]`——不归一就每篇都提示。"""
    s = re.sub(r"\*\*|__|`", "", str(s or ""))
    return "".join(c for c in s if not c.isspace()
                   and c not in "／/｜|，。、！？；：（）()【】〔〕—－·…“”‘’,.!?;:[]-'\"")


def doc_sections(text: str) -> dict:
    """把交付文档切成 {篇目字母: 该篇的行列表}。⛔ 不做跨篇匹配——A 的 hero 配 B 的数据
    是个真实会发生的错，切开才发现得了。"""
    out, cur = {}, None
    for line in text.splitlines():
        m = SECTION_LINE.match(line)
        if m:
            cur = m.group(1).upper()
            out[cur] = []
            continue
        if cur:
            out[cur].append(line)
    return out


def hero_of_section(lines: list):
    """返回 (hero 原文, 该 hero 附近有没有压缩留痕)。

    ⚠️ **留痕范围＝这一条目**：从 hero 行到**下一个结构化字段行**（`- **副行**：` 这类）
    或下一个篇目为止。
    🩸 首版只认 `<br>` 续行，⇒ 留痕若写成**独立列表项**（`- ⚠️ 排版缩短：…`，
    真样本里就有这种写法）就不算数 ⇒ **误提示**。而一条会误报的提示，
    三天之内就没人看了——**那比没有提示更糟，因为它还占着"我们查过了"的位置**。
    ⛔ 但也别扫整篇：篇目边界必须切断，否则 A 篇的留痕会把 C 篇静音。"""
    for i, line in enumerate(lines):
        m = HERO_LINE.match(line)
        if not m:
            continue
        raw = m.group(1)
        chunk = [raw]
        for nxt in lines[i + 1:]:
            if SECTION_LINE.match(nxt) or FIELD_LINE.match(nxt):
                break                      # 下一个篇目 / 下一个结构化字段 ⇒ 本条目结束
            chunk.append(nxt)
        blob = "\n".join(chunk)
        # hero 值本身只取 `<br>` 之前那截——`<br>` 之后是留痕注记，⛔ 不是 hero 的一部分
        value = re.split(r"<br\s*/?>", raw, maxsplit=1)[0]
        return value.strip(), any(w in blob for w in TRACE_WORDS)
    return None, False


def split_hero(value: str) -> list:
    """文档里的 hero 用 `/` 或 `／` 分行；出图数据里是列表。统一成列表。"""
    parts = [p.strip() for p in re.split(r"[/／]", str(value or "")) if p.strip()]
    return parts or ([str(value).strip()] if str(value or "").strip() else [])


def data_hero(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    hero = data.get("hero")
    if isinstance(hero, str):
        return split_hero(hero)
    return [str(h).strip() for h in (hero or []) if str(h).strip()]


def check(doc: Path, section: str, data: Path) -> dict:
    out = {"section": section, "doc_hero": None, "data_hero": None,
           "same": None, "has_trace": None, "hint": None, "ok": True}
    if not doc.is_file():
        out["hint"] = f"交付文档不存在：{doc}——⚠️ 这是「没查成」不是「不一致」"
        return out
    secs = doc_sections(doc.read_text(encoding="utf-8"))
    if section.upper() not in secs:
        out["hint"] = (f"文档里没有篇目 {section}（有的是：{'/'.join(sorted(secs)) or '一个都没有'}）"
                       f"——⚠️ 这是「没查成」不是「不一致」")
        return out
    raw, has_trace = hero_of_section(secs[section.upper()])
    if raw is None:
        out["hint"] = f"篇目 {section} 里没有 `- **hero**：` 行——⚠️ 这是「没查成」不是「不一致」"
        return out
    if not data.is_file():
        out["hint"] = f"出图数据不存在：{data}——⚠️ 这是「没查成」不是「不一致」"
        return out
    dh, mh = split_hero(raw), data_hero(data)
    out.update({"doc_hero": dh, "data_hero": mh, "has_trace": has_trace,
                "same": [norm(x) for x in dh] == [norm(x) for x in mh]})
    if out["same"] or has_trace:
        return out
    out["hint"] = (
        f"篇目 {section} 的 hero 与出图数据不一致，**而文档里没有压缩留痕**：\n"
        f"    文档：{dh}\n    出图：{mh}\n"
        f"  ⚠️ 压缩本身是合法的（版式有 ≤6 字/字高 9–13% 的硬约束），"
        f"缺的只是**在文档里写一句为什么压、压成了什么**。\n"
        f"  ⇒ **文档是真源**：要么把出图那版回写进文档，要么在 hero 行下补一句排版缩短说明。\n"
        f"  ⛔ 这是提示不是闸门——**别为了消掉它去补一句假留痕**，那比没有留痕更坏")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="hero ↔ 出图数据 不一致且无留痕时提示（⛔ 不阻断）")
    ap.add_argument("--doc", required=True, help="交付文档（含 `- **hero**：` 行）")
    ap.add_argument("--section", required=True, help="篇目字母，如 A / B / E")
    ap.add_argument("--data", required=True, help="出图数据 cover.json")
    a = ap.parse_args(argv)
    res = check(Path(a.doc), a.section, Path(a.data))
    print(json.dumps(res, ensure_ascii=False))
    if res["hint"]:
        print("⚠️ " + res["hint"], file=sys.stderr)
    elif res["same"]:
        print(f"  [{a.section}] hero 与出图数据逐字一致", file=sys.stderr)
    else:
        print(f"  [{a.section}] hero 与出图数据不一致，但文档里有压缩留痕 ⇒ 不提示",
              file=sys.stderr)
    return 0        # 🔴 恒 0：提示级，⛔ 不阻断


if __name__ == "__main__":
    sys.exit(main())

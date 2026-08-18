#!/usr/bin/env python3
"""视觉计划闸门 —— 六道，随 plan 一起跑。

    check_plan.py --plan plan.json --cues narration.mp3.cues.json [--hold-min 3.5]

## 它治的病（老板 2026-08-18 逐字）

> 「我看到**动画与内容并无关联**，节奏非常快。我希望动画都是与口播讲的东西有相关性的。
>   **不能只是简单的套用模板。**每一页是什么动画，什么特效，需要有 llm 来设计」

🔴 **真正的难点不是让 LLM 生成计划，是让「相关」可被证伪。**
不然它会生成**看起来很合理、实际仍然无关**的计划——而人和审稿代理都只能点头，
**那只是把「套模板」换成了「套措辞」。**

## 判据（可机检、二元，⛔ 不评分）

> **把某屏的 `why` 原样挪到别的屏，如果还成立，它就不算相关。**

⇒ 落成两条：① `why` 必须**逐字引用本屏 `text` 片段**（≥2 字）；
② **跨屏唯一性**：去掉引用后的主干不得雷同（十屏写同一句「气氛转折所以用漂移」
＝ 没有编排）。

⛔ **不做「相关性评分」**：分数会诱人调阈值。**引用了本屏文本＝有依据，没引用＝没依据。**

exit 0 = 全过（可能带 warn）｜1 = 有 fail｜2 = 输入错误。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEMANTICS = ("断言", "反驳", "列举", "对比", "转折", "因果",
             "数据", "比喻", "场景", "提问", "收口", "留白")
MOTIFS = ("rise", "wipe", "depth", "drift", "tilt", "still")
RELATIONS = ("开场", "延续", "切换", "呼应", "收口")
HOLD_MIN = 3.5
"""每屏停留下限。🔴 ⚠️ 停留时长 ⛔ 不由排版层决定——它 ＝ `cue 时长 ÷ 该句拆的屏数`，
而 **cue 时长是 TTS 已经定死的**。⇒ 合并到「一句一屏」仍不够，**那是语速问题**，
出路是重跑 TTS 放慢或加句间停顿，⛔ 别在排版层硬撑。"""

_QUOTE = re.compile(r"[「『\"']([^」』\"']{2,})[」』\"']")


def _cited(why: str, text: str) -> str | None:
    """`why` 里逐字引用了 `text` 的哪一段（≥2 字）。没有返回 None。

    ⚠️ 先认显式引号里的内容（写作习惯），再退回「任意 ≥2 字公共子串」——
    ⛔ 别只认引号：LLM 未必总加引号，那样会把合格的计划判死。
    """
    for m in _QUOTE.finditer(why or ""):
        if m.group(1) in text:
            return m.group(1)
    for n in range(min(len(text), 12), 1, -1):      # 长的优先，更有说服力
        for i in range(len(text) - n + 1):
            if text[i:i + n] in (why or ""):
                return text[i:i + n]
    return None


def _stem(why: str, cite: str | None) -> str:
    """去掉引用片段与标点后的主干——用来判「这句话是不是放哪都成立」。"""
    s = why or ""
    if cite:
        s = s.replace(cite, "")
    return re.sub(r"[「」『』\"'，。、；：！？…—\-\s（）()]+", "", s)


def check(plan: dict, cues: list[dict], hold_min: float = HOLD_MIN) -> dict:
    fails, warns, rows = [], [], []
    screens = plan.get("screens") or []
    if not screens:
        return {"ok": False, "fails": ["plan.screens 为空——⛔ 这不是「没有屏」，是数据没读到"],
                "warns": [], "rows": []}

    cue_texts = [c.get("text", "") for c in cues]
    stems: dict[str, int] = {}
    for s in screens:
        i = s.get("i")
        tag = f"#{i:02d}" if isinstance(i, int) else "#??"
        text = s.get("text", "")

        # ① 文本一致：plan 的屏文本必须能在 cues 里找到（⛔ 别让 LLM 顺手改词）
        if not any(text and text in ct for ct in cue_texts):
            fails.append(f"{tag}：屏文本「{text}」在 cues 里找不到——⛔ 计划不许改动稿子的字")

        # ② 三个闭集
        for key, allowed in (("semantic", SEMANTICS), ("motif", MOTIFS), ("relation", RELATIONS)):
            v = s.get(key)
            if v not in allowed:
                fails.append(f"{tag}：{key}=「{v}」不在闭集内 {allowed}")

        # ③ 强调词必须在本屏文内
        emph = s.get("emphasis")
        if emph and emph not in text:
            fails.append(f"{tag}：emphasis「{emph}」不是屏文本的子串——强调一个没出现的词")

        # ④ 🔴 相关性：why 必须逐字引用本屏文本
        why = s.get("why", "")
        cite = _cited(why, text)
        if not cite:
            fails.append(
                f"{tag}：why 没有引用本屏文本 ——「{why[:40]}」\n"
                f"    ⛔ 这条理由放到任何一屏都成立，那就不是「与内容相关」。\n"
                f"    ⭕ 参照：「『八个阶段』是列举 → 逐项擦出，节奏对应『一项一项』」")

        # ⑤ 跨屏唯一性（warn）：去掉引用后主干雷同 ＝ 套模板的残留
        st = _stem(why, cite)
        if st and st in stems:
            warns.append(f"{tag}：why 主干与 #{stems[st]:02d} 完全相同——疑似套同一句措辞")
        elif st:
            stems[st] = i if isinstance(i, int) else -1

        # ⑥ 停留下限
        hold = round(float(s.get("end", 0)) - float(s.get("start", 0)), 2)
        if hold < hold_min:
            fails.append(
                f"{tag}：停留 {hold}s < 下限 {hold_min}s ——合并相邻屏；\n"
                f"    ⚠️ 若已经是「一句一屏」还不够，**那是语速问题不是排版问题**：\n"
                f"    重跑 TTS 放慢或加句间停顿，⛔ 别在排版层硬撑")
        rows.append({"tag": tag, "hold": hold, "semantic": s.get("semantic"),
                     "motif": s.get("motif"), "emphasis": emph, "cite": cite,
                     "text": text, "why": why})

    return {"ok": not fails, "fails": fails, "warns": warns, "rows": rows,
            "screens": len(screens), "hold_min": hold_min}


def to_md(res: dict) -> str:
    """人读的一屏一行（给内容审稿 agent）。"""
    out = []
    for r in res["rows"]:
        out.append(f"{r['tag']}  {r['hold']}s  {r['semantic']}  {r['motif']}"
                   f"  强调「{r['emphasis'] or '—'}」")
        out.append(f"      「{r['text']}」")
        out.append(f"      why: {r['why']}   [引用:{r['cite'] or '⛔无'}]")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="视觉计划闸门（六道）")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--cues", required=True)
    ap.add_argument("--hold-min", type=float, default=HOLD_MIN)
    ap.add_argument("--md", help="把人读版写到这个路径（给审稿代理）")
    a = ap.parse_args(argv)
    try:
        plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
        cues = json.loads(Path(a.cues).read_text(encoding="utf-8"))
        if isinstance(cues, dict):
            cues = cues.get("cues", cues)
    except Exception as e:
        print(f"❌ 读不到输入：{e}", file=sys.stderr)
        return 2

    res = check(plan, cues, a.hold_min)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"},
                     ensure_ascii=False, indent=2))
    if a.md:
        Path(a.md).write_text(to_md(res), encoding="utf-8")
    for w in res["warns"]:
        print(f"⚠️ {w}", file=sys.stderr)
    if res["fails"]:
        print(f"\n⛔ {len(res['fails'])} 处不过：", file=sys.stderr)
        for f in res["fails"]:
            print(f"  · {f}", file=sys.stderr)
        return 1
    print(f"\n✅ {res['screens']} 屏全过（文本一致/闭集/强调词/相关性/停留下限）"
          f"{'，' + str(len(res['warns'])) + ' 处 warn' if res['warns'] else ''}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

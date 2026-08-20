#!/usr/bin/env python3
"""视觉计划闸门 —— 六道，随 plan 一起跑。

    check_plan.py --plan plan.json --cues narration.mp3.cues.json [--hold-min 3.5]

## 它治的病（老板 2026-08-18 逐字）

> 「我看到**动画与内容并无关联**，节奏非常快。我希望动画都是与口播讲的东西有相关性的。
>   **不能只是简单的套用模板。**每一页是什么动画，什么特效，需要有 llm 来设计」

🔴 **真正的难点不是让 LLM 生成计划，是让「相关」可被证伪。**
不然它会生成**看起来很合理、实际仍然无关**的计划——而人和审稿代理都只能点头，
**那只是把「套模板」换成了「套措辞」。**

## 🔴 一条与层数无关的总判据（交付方 2026-08-18 推出来的，⛔ 别再逐层补闸）

> **任何一层产出物，都要能追到它上一层里那句带限定的原话。**

**为什么要写成"与层数无关"**：同一个病已经在两个接缝上复发过——
① 口播丢正文的对冲（正文「它有**可核对**的结果」→ 口播「后者**有结果**」，撞"不承诺效果"红线）；
② 卡片丢口播的限定（口播「**按创始人机构的描述**，它有八个阶段」→ 卡片「八个阶段」，成了独立断言）。

⇒ **这不是巧合**：**每加一层提炼就多一个接缝**，而**每一层都是"为了更抓眼"而提炼的，
所以丢的总是同一类词**——限定、条件、程度副词，**它们又长又不抓眼**。
⚠️ **可预期的推论**：将来再加一层（卡片 → 标签／话题／封面词），
**同一个病会在新接缝上第三次复发**。⇒ 与其每次事后补一道闸，不如让每层都带上锚。

⭕ **本模块的两条机检其实是同一个形状的两个实例**：
`why` 必须引用本屏文本（相关性）／卡片必须能追到覆盖时段的口播原话（限定语）——
**都是"产出物必须携带它上游的锚"**。三列对照表把上一层原话摆在旁边，就是这条的可审形态。

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
HOLD_BAND = (3.5, 10.0)
"""每屏停留的**目标区间**（小红书发布线 2026-08-18 读代码实算）：

| 切法 | 条数 | 每条时长 | 判 |
|---|---|---|---|
| `tts_gen._split_sentences`（按句） | 107 | **7.2–10.3s**，最长 64 字 | ⛔ 一屏挂不下 |
| `tts_gen._split_caption_units`（按逗号） | 292 | **2.5–3.2s** | ⛔ **正是老板批的"节奏非常快"** |
| **合并到 4–6s/屏** | ~18–22 屏 | ✅ | 目标 |

⇒ **切屏粒度在两者之间**：以 caption units 为**输入粒度**，由 LLM 把相邻条**按语义合并**。
⚠️ 合并点必须落在语义边界——**机械合并会把「一次出色，」从破折号后切走**。
⛔ 落在区间外只 warn（内容有长有短），低于 `HOLD_MIN` 才拒。

🔴 **2026-08-19 从 4–6s 改成 3.5–10s（助理拍板）。改判据的原因是「前提被否了」，
⛔ 不是「嫌它报红」**——这两件事必须分清，否则每一次报红都能被说成"判据不合适"。

**被否的前提**：4–6s 是设计稿在「**可以在句内按语义切分**」的假设下写的
（把 caption units 合并到 4–6s）。而 `tpl-paragraph` 硬契约⑥是
**「段落边界只落在句边界上」**（⛔ 绝不在一句话中间换手法——观众会以为换了话题）。
⇒ **编排单元最小就是「句」**，那个假设不成立。

**新区间贴的是「句」的事实分布**（X1–X4 实测每句 5.8–8.2s 均值、最长 12.0s、最短 2.06s）：
下限沿用 `HOLD_MIN=3.5`（低于它是真的读不完），上限放到 10s（一句本来就可能这么长）。
⚠️ 上限之外仍只 warn，⛔ 下限之外照旧 fail——**放宽的是 warn 的范围，不是 fail 的门槛**。

🔴 **2026-08-19 已用真 cues 重算，这组数据现在是量过的**（15 份在产稿、401 句、
8177 汉字、1933.8s）——⚠️ 但**原来那个 3.5 是错的**，重算后是 **4.23**：

| 口径 | 值 | 用途 |
|---|---|---|
| **句内** `Σ(句 end−start)÷Σ字数` | **4.23** | 「这一屏停多久」 |
| 整片 `(末 end−首 start)÷Σ字数` | 3.88 | 「成片多长」 |

🩸 3.5 是**双重错配**：口径错（整片当句内）＋ 样本是异常值
（出自单条 `oneline-qiuqiu-jianyao`，其句间静音 16.3% 为 15 条之最，其余 6–8%）。
⇒ 按 4.23 折算，`4–6s/屏` ＝ **17–25 汉字**（按 3.5 算是 14–21 字，**偏少 3–4 字**）。
⚠️ **一条样本 + 错口径，出来的数看着很像真值**——⛔ 别再拿单条片子定全线的尺子。"""

SEPS = "，、；：,;:"
"""🔴 **切分字符集的唯一真源。**

🩸 实证（小红书发布线读代码，2026-08-18）：此前有**两处各写一份**且不一致——
`tts_gen._split_caption_units` 是 `，、；：,;:`（**含冒号**），
`tpl-collage-cards.html:259 splitSegs` 是 `[，、； ]`（**不含冒号**）。
⇒ 「很多人会接一句：所以你要等他。」按前者切、按后者不切 ⇒
**先单显前半再补后半，印章说反话那个事故重演**。

⭕ **而在解耦后的新架构里这个 bug 会自动消失**：卡片文字由 **LLM 提炼**，
**⛔ 渲染层不再做任何标点切分**（`splitSegs` 那类逻辑在新版式里根本不存在）。
⇒ **切分只剩一处**（`tts_gen`），也就没有第二份可以漂。
⚠️ 但收 collage 进 skill 仓时**必须确认这一点**——⛔ 别把旧模板的 `splitSegs` 一起搬进来。"""

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


def _speech_in(cues: list[dict], a: float, b: float) -> str:
    """[a,b) 这段时间里念的口播原文（拼接命中的 cue）。解耦模式下它才是"内容"。"""
    return "".join(c.get("text", "") for c in cues
                   if float(c.get("end", 0)) > a and float(c.get("start", 0)) < b)


def _on_boundary(cues: list[dict], t: float, tol: float = 0.12) -> bool:
    """t 是否落在语义边界（某个 cue 的起点或终点）附近。

    🩸 审稿代理 2026-08-18：**卡片切换点必须落在语义边界，⛔ 不在一句话中间切**
    ——中途切换会让观众以为话题变了，而口播还在同一句里。
    """
    for c in cues:
        for edge in (float(c.get("start", 0)), float(c.get("end", 0))):
            if abs(t - edge) <= tol:
                return True
    return False


def check(plan: dict, cues: list[dict], hold_min: float = HOLD_MIN) -> dict:
    fails, warns, rows = [], [], []
    screens = plan.get("screens") or []
    if not screens:
        return {"ok": False, "fails": ["plan.screens 为空——⛔ 这不是「没有屏」，是数据没读到"],
                "warns": [], "rows": []}

    cue_texts = [c.get("text", "") for c in cues]
    stems: dict[str, int] = {}
    for s in screens:
        # ⚠️ 段内非段首的句**没有 motif/why**（同段共用段首那一份）⇒ 跳过，
        # ⛔ 别把"按设计留空"判成"漏填"。
        if "section" in s and not s.get("section_head", True):
            continue
        i = s.get("i")
        tag = f"#{i:02d}" if isinstance(i, int) else "#??"
        # 🔴 解耦模式（collage）：卡片文字 ≠ 口播文字
        #    `card` = 卡片上显示的关键词/短语；`covers` = 它覆盖的口播时段
        #    ⇒ **相关性判据要对着口播原文判**，⛔ 不是对着卡片自己的字判
        #      （卡片是从口播提炼的，拿它自比等于自证）。
        card, covers = s.get("card"), s.get("covers")
        decoupled = card is not None and covers is not None
        if decoupled:
            a, b = float(covers[0]), float(covers[1])
            speech = _speech_in(cues, a, b)
            text = speech
            # ⑦ 卡片必须回贴口播：覆盖时段里得真有话在念
            if not speech.strip():
                fails.append(f"{tag}：covers {covers} 这段时间没有口播——卡片贴在了空白上")
            # ⑧ 切换点必须落在语义边界
            if not _on_boundary(cues, a):
                fails.append(
                    f"{tag}：切换点 {a}s 不在语义边界上（句号/分句）——"
                    f"⛔ 别在一句话中间切卡片，观众会以为话题变了而口播还在同一句里")
        else:
            text = s.get("text", "")

        # ① 文本一致：plan 的屏文本必须能在 cues 里找到（⛔ 别让 LLM 顺手改词）
        #    ⚠️ 解耦模式跳过——那时 text 是从 cues 拼出来的，自比无意义
        if not decoupled and not any(text and text in ct for ct in cue_texts):
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
        # 🔴 **合屏后「屏停多久」＝整段时长，⛔ 不是这一句的时长**（2026-08-20）。
        # ⚠️ 拿句时长判 3.5s 下限，会把已经合好的段照旧报红——**闸门要跟着单元走**。
        hold = round(float(s.get("section_span")
                           or (float(s.get("end", 0)) - float(s.get("start", 0)))), 2)
        if hold < hold_min:
            fails.append(
                f"{tag}：停留 {hold}s < 下限 {hold_min}s ——合并相邻屏；\n"
                f"    ⚠️ 若已经是「一句一屏」还不够，**那是语速问题不是排版问题**：\n"
                f"    重跑 TTS 放慢或加句间停顿，⛔ 别在排版层硬撑")
        # ⑥-b 粒度目标区间（warn）：太碎＝老板批过的"节奏非常快"，太长＝一屏挂不下
        elif not (HOLD_BAND[0] <= hold <= HOLD_BAND[1]):
            warns.append(
                f"{tag}：停留 {hold}s 在目标区间 {HOLD_BAND[0]}–{HOLD_BAND[1]}s 之外"
                f"（{'偏碎，接近老板批过的节奏' if hold < HOLD_BAND[0] else '偏长，一屏可能挂不下'}）")

        rows.append({"tag": tag, "hold": hold, "semantic": s.get("semantic"),
                     "motif": s.get("motif"), "emphasis": emph, "cite": cite,
                     "text": text, "why": why, "card": card, "covers": covers})

    return {"ok": not fails, "fails": fails, "warns": warns, "rows": rows,
            "screens": len(screens), "hold_min": hold_min}


def to_md(res: dict) -> str:
    """人读的一屏一行（给内容审稿 agent）。

    🔴 **审稿代理要分开核两样，⛔ 别从卡片反推口播**（交付方 2026-08-18）：
    ① **那段口播原文单看有没有害**（真正会被截图的是「那一屏画面 ＋ 那一刻声音」）；
    ② **卡片提炼时有没有丢掉限定语** —— ⚠️ 口播「**按创始人机构的描述**，它有八个阶段」
       提炼成卡片「八个阶段」，**限定语没了，卡片就成了一句独立断言**。
       ⇒ 凡口播里带证据边界的词（按…的描述／研究提示／可核对／往往），
       **卡片丢掉它就要报**——这半机器判不了，靠并排列出让人判。
    ⚠️ **⛔ 别让卡片自证**：卡片是从口播提炼的、**天然会挑正向的说**——
    **凡「由 A 产出、再由 A 说明它没问题」的结构，那个说明就没有证据价值。**

    🔴 解耦模式下**必须把「卡片文字 ↔ 它覆盖时段的口播原文」并排列出**
    （审稿代理 2026-08-18 定为必交材料）：**解耦解决了电报体，却引入了新风险——
    卡片与当时念的话对不上，那比装饰性无关更糟**（观众会以为自己听漏了）。
    ⇒ 并排列出来，人一眼就能判"这张卡是不是这段话的关键词"。
    """
    out = []
    for r in res["rows"]:
        out.append(f"{r['tag']}  {r['hold']}s  {r['semantic']}  {r['motif']}"
                   f"  强调「{r['emphasis'] or '—'}」")
        if r.get("card") is not None:
            out.append(f"      卡片：「{r['card']}」   覆盖 {r['covers']}")
            out.append(f"      口播：「{r['text']}」   ← 这段时间真正念的话")
        else:
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

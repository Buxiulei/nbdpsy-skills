#!/usr/bin/env python3
"""视觉编排：让 LLM 给每一屏设计动效（`plan.json` + `plan.md`）。

    plan_llm.py --cues narration.mp3.cues.json --out 工作目录/ [--account 号名] [--max-line-chars 12]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 **⛔ LLM 不决定分屏。**分屏是确定性闸门（`build_oneline.split_cue`）的事，
   LLM 只决定**每屏怎么演**。⚠️ 两者混在一起，会让"断不开"这类硬失败变得不可预测
   （设计稿 §八）。⇒ 本脚本先用同一把尺拆好屏，再把**拆好的屏**交给 LLM 填字段。

🔴 **判据地基（设计稿 §一）**：每屏的 `why`——
   **把这条 `why` 原样挪到别的屏，如果还成立，它就不算相关。**
   落成两条硬检查（由 `check_plan.py` 执行，⛔ 本脚本不另写一份）：
   ① `why` 必须**逐字引用**本屏 `text` 里 ≥2 字的片段；
   ② 跨屏唯一：任意两屏的 `why` 去掉引用片段后主干不得完全相同。
   ⚠️ **没有这条，"LLM 设计"只是把套模板换成了套措辞。**

⚠️ 产出后**自动过一次 `check_plan.py` 六道闸**——⛔ 不过就非零退出，
   别让一份没过闸的 plan 溜到渲染那一步（那时才发现要重跑 LLM）。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_oneline as bo          # noqa: E402  同一把分屏尺
import check_plan as cp             # noqa: E402  同一套闸门与闭集

API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"


def load_key() -> str:
    """与 `zh_native_review.py` 同源的解析顺序：环境变量 → 工作区 .env → 用户级 → 仓库兜底。"""
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    for envfile in (Path.cwd() / ".env",
                    Path.home() / ".config/nbdpsy/secrets.env",
                    Path("/home/roots/NBDpsy/.env")):
        try:
            for line in envfile.read_text().splitlines():
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
        except (FileNotFoundError, PermissionError):
            continue
    sys.exit("❌ 缺 DEEPSEEK_API_KEY：环境变量、./.env、~/.config/nbdpsy/secrets.env "
             "与 /home/roots/NBDpsy/.env 都没有。\n"
             "⛔ 本环节没有人工降级——视觉编排是逐屏设计，手填 20+ 屏不现实。")


SYSTEM = f"""你在给一条心理科普短视频做**视觉编排**：稿子已经拆好屏了，你的唯一职责是**逐屏决定这一屏怎么演**。

🔴 **你决定的是「段」，⛔ 不是「屏」。**两件事必须分清：

| | 是什么 | 归谁 |
|---|---|---|
| **拆屏** | 一句拆成几行（每行 ≤N 字） | **确定性闸门**，⛔ 你不碰 |
| **合屏** | 把**相邻的短句**归成一段 | **你的职责** |

⛔ 句子的文字、起止时刻都已定死，一个字都不要改、不要拆。
⭕ 但**相邻的句子可以归进同一段**——同段共用一个动效，段与段之间才换手法。

【什么时候该合段】

🔴 **一段的总时长 <3.5 秒，观众就来不及读完** ⇒ **必须与相邻段合并**。
输入里每句都给了时长，⚠️ **短句要主动往前一句合**（或往后，看语义哪边更连贯）。

⚠️ 但 ⛔ **别为了凑时长把不相干的句子焊在一起**——段边界应该落在**语义转折处**。
一段说完一件事、下一段换个说法或换个角度，这才是"段"。

⚠️ 合过头也是错：**一段超过 12 秒**，同一个动效撑太久会变成"没有编排"。

每段（**段首那一句**）要填五个字段，段内其余句只填 `section`：

1. `semantic` —— 这一屏在讲什么类型的话。**闭集，只能从这些里选**：
   {"｜".join(cp.SEMANTICS)}
2. `motif` —— 用哪个动效件。**闭集，只能从这些里选**：
   {"｜".join(cp.MOTIFS)}
3. `emphasis` —— 本屏要强调的词。**必须是本屏 text 的连续子串**（逐字对得上），
   没有值得强调的词就填空字符串。
4. `relation` —— 与**上一段**的关系。**闭集只有这五个**：{"｜".join(cp.RELATIONS)}
   ⚠️ ⛔ 别把 `semantic` 的值（转折/因果/对比…）填到这里来——它们是**两个不同的闭集**，
   填串了闸门会当场报「不在闭集内」。第一段用「开场」，最后一段用「收口」。
5. `why` —— **为什么这一屏配这个动效**。

【`why` 是整件事的地基，判据只有一条】

> **把这条 why 原样挪到别的屏，如果还成立，它就不算相关。**

所以两条硬要求：
- **必须逐字引用本屏 text 里 ≥2 字的片段**（用「」括起来），⛔ 不许只说抽象理由；
- **跨屏不许重复主干**：全篇十屏写同一句「气氛转折所以用漂移」＝ 没有编排，
  只是把套模板换成了套措辞。

⭕ 好例：「本屏『**八个阶段**』是列举 → 逐项揭示（wipe），擦出的节奏对应"一项一项"」
⛔ 坏例：「本屏气氛转折 → 用漂移」（放到任何一屏都成立）

【语义 → 手法的建议映射（先验，⛔ 不是硬绑定；偏离要在 why 里说明理由）】

| 语义 | 建议 | 理由 |
|---|---|---|
| 反驳／转折 | wipe | 擦出＝划掉重写 |
| 列举 | wipe（逐项）／drift（并置） | 节奏对应"一项一项" |
| 数据／断言 | depth | 从虚到实＝把结论"对上焦" |
| 比喻／场景 | drift／tilt | 位移＝换一个看的角度 |
| 收口／留白 | still | **丰富 ≠ 一直在动**，收口要让人停一下 |

⚠️ **相邻两屏尽量不要用同一个 motif**——连着用会让"编排"退化成"统一动效"。
⚠️ **still 是留白件**：整片该有几处收口就用几处，⛔ 不要为了凑变化乱撒。

🔴 **`why` 要如实写，⛔ 别让它假装是纯语义驱动的。**
你在选 motif 时其实同时在做两件事：**语义上合适**、以及**与上一屏区分开**。
⚠️ 审稿 2026-08-19 抓到：三类语义已经塌缩成固定映射（收口 5/5 全 still、场景 3/3 全 drift），
**而 `why` 只写了语义那一半** ⇒ 读的人以为每次都是从内容推出来的。
⇒ 若这一屏的选择里**有"避免与上屏重复"的成分，就在 why 里写出来**
（例：「…**且上屏已用 wipe，这里换纵向以免连着两屏同手法**」）。
**如实写不会扣分，假装纯语义才会。**

【输出】

严格 JSON，⛔ 不要 markdown 代码块，⛔ 不要任何解释性文字。格式：

{{"screens":[
  {{"i":0,"section":0,"semantic":"反驳","motif":"wipe","emphasis":"不代表","relation":"开场",
   "why":"本段「不代表」是把前半句划掉再写新的，wipe 的擦出方向正好演这个动作"}},
  {{"i":1,"section":0}},
  {{"i":2,"section":1,"semantic":"数据","motif":"depth","emphasis":"并不一致","relation":"切换",
   "why":"本段「并不一致」是把模糊的印象对上焦，depth 从虚到实正好演这个"}}
]}}

规则：
- `i` 必须与输入的句号**一一对应、不重不漏**；
- `section` 从 **0** 起、**单调不减**、**每次只 +1**（⛔ 不许跳号）；
- **段首那一句**（该段第一个 `i`）必须填全五个字段；
- **段内其余句只填 `i` 和 `section`**，⛔ 别重复填 motif/why（同段共用段首那一份）。"""


MERGE_MIN = 3.5
MERGE_MAX = 10.0
"""合段的下限与上限（秒）。⚠️ 上限是 warn、下限是 fail（见 `check_plan`）。"""


def build_payload(screens: list[dict]) -> str:
    """给 LLM 的输入：句号 + 时长 + 文字，**短句当场标出来**。

    🔴 **「哪些必须合」由确定性算好并标死，⛔ 不靠 LLM 自己去数时长。**
    🩸 2026-08-20 首版只把时长给它、让它自行判断 ⇒ X4 十二句里**它只合了 1 处**，
    而且合的是**两个长句**（合出 21.21s，超上限），**三个短句一个没合**。
    ⇒ 语义判断归它（往前合还是往后合），**发现问题归确定性**——
    ⚠️ 这两件事混在一起时，它会挑容易的那件做。
    """
    lines = [f"以下是已切好的句（⛔ 不要改动文字，⛔ 不要拆；相邻的可以归段）。",
             f"⚠️ 标了 🔴 的句**时长不足 {MERGE_MIN}s，必须与相邻句合成一段**"
             f"（往前还是往后由你按语义定）；",
             f"⚠️ 合并后**一段不要超过 {MERGE_MAX}s**——标了 ⏳ 的句本身就够长，⛔ 别再往上合。\n",
             "句号\t时长\t标记\t文字"]
    for s in screens:
        hold = round(s["end"] - s["start"], 2)
        mark = "🔴必须合" if hold < MERGE_MIN else ("⏳已够长" if hold >= MERGE_MAX else "")
        lines.append(f'{s["i"]}\t{hold:.2f}s\t{mark}\t{s["text"]}')
    return "\n".join(lines)


def call_llm(screens: list[dict], key: str, model: str, timeout: int = 300) -> dict:
    r = requests.post(API, timeout=timeout,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "temperature": 0.7,
                            "response_format": {"type": "json_object"},
                            "messages": [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": build_payload(screens)}]})
    if r.status_code >= 400:
        sys.exit(f"❌ LLM 调用失败 HTTP {r.status_code}：{r.text[:500]}")
    try:
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        sys.exit(f"❌ LLM 回的不是合法 JSON（{type(e).__name__}）：{r.text[:800]}")


def normalize_sections(rows: list[dict]) -> list[dict]:
    """把 LLM 给的 `section` 规整成「从 0 起、单调不减、每次只 +1」。

    🔴 **段号是"哪几句归一段"，⛔ 不是自由编号**：LLM 跳号/回退都会让段划分错乱，
    而**画面照样出得来**（只是动效挂错段）——⚠️ 这类错没有声音，必须在这里当场规整。
    ⛔ 不静默修：改了就报出来。
    """
    fixed, prev_src, cur = [], None, -1
    for r in rows:
        src = r.get("section")
        if src is None:
            src = prev_src if prev_src is not None else 0    # 没给 ⇒ 跟上一句同段
        if prev_src is None or src != prev_src:
            cur += 1
        fixed.append(cur)
        prev_src = src
    return fixed


def force_merge_short(rows: list[dict]) -> list[dict]:
    """把仍然 <`MERGE_MIN` 的段**强制并进相邻段**，并报出来。

    🔴 **发现问题归确定性、语义判断归 LLM——执行也要有确定性兜底。**
    🩸 2026-08-20 实测：即使在输入里把短句标成「🔴 必须合」，
    LLM 十二句里**仍只合了 1 处、漏掉 2 个短句**。⚠️ 它会挑容易的那件做。
    ⇒ 往哪边合由它定（它合过的保留），**它没合的这里兜底**。

    ⚠️ 合并到**前一段**（前段是"主"，motif/why 用它的）；首段没有前段就并入后段。
    ⚠️ 合并可能让段超过 `MERGE_MAX` —— **仍然合**：短段来不及读是硬伤，
    段偏长只是 warn。⛔ 但要报出来，别让它无声发生。
    """
    if len(rows) < 2:
        return rows
    forced = []
    while True:
        span, order = {}, []
        for r in rows:
            sec = r["section"]
            if sec not in span:
                span[sec] = [r["start"], r["end"]]
                order.append(sec)
            else:
                span[sec][1] = r["end"]
        short = [k for k in order if span[k][1] - span[k][0] < MERGE_MIN]
        if not short or len(order) < 2:
            break
        bad = short[0]
        pos = order.index(bad)
        # ⚠️ 选**合并后更短**的那个邻居，⛔ 不是无脑并进前一段。
        # 🩸 首版无脑并前段，把一个本已 21s 的段撑到 23.16s——
        #    短段是消掉了，却制造出一个「同一动效撑 23 秒」的段，
        #    **那正是"编排退化"的另一种形态**。⇒ 消一个问题别造另一个。
        cands = [order[pos - 1]] if pos > 0 else []
        if pos + 1 < len(order):
            cands.append(order[pos + 1])
        into = min(cands, key=lambda k: span[k][1] - span[k][0])
        forced.append((bad, into))
        for r in rows:
            if r["section"] == bad:
                r["section"] = into
                r["section_head"] = False
        # 段号重新压实（⚠️ 必须连续：模板按段号索引 PLAN_MOTIFS）
        remap, nxt = {}, 0
        for r in rows:
            if r["section"] not in remap:
                remap[r["section"]] = nxt
                nxt += 1
        for r in rows:
            r["section"] = remap[r["section"]]
    if forced:
        print(f"  🔗 确定性兜底：强制合并 {len(forced)} 段（LLM 漏掉的短段）"
              f"{['%d→%d' % x for x in forced][:6]}", file=sys.stderr)
    return rows


def merge(screens: list[dict], llm: dict) -> dict:
    """把 LLM 填的字段并回确定性切句。

    🔴 **以切句为准、LLM 为辅**：句号对不上的一律丢弃并报出来，
    ⛔ 绝不按 LLM 给的顺序重排——那等于让它间接改了分屏。

    🔴 **段内只有段首句带 motif/why**（同段共用一个动效＝「段内统一」）。
    ⚠️ 段内其余句若也填了，**以段首为准**并报出来——⛔ 别让一段里出现两个 motif，
    那会让"段"这个概念本身失效。
    """
    by_i = {int(x["i"]): x for x in (llm.get("screens") or []) if "i" in x}
    raw = [by_i.get(s["i"], {}) for s in screens]
    secs = normalize_sections(raw)
    out, missing, dup = [], [], []
    head_of = {}
    for k, (s, f) in enumerate(zip(screens, raw)):
        sec = secs[k]
        is_head = sec not in head_of
        if is_head:
            head_of[sec] = f
            if not f:
                missing.append(s["i"])
        elif f.get("motif") and f.get("motif") != head_of[sec].get("motif"):
            dup.append(s["i"])
        h = head_of[sec]
        out.append({**s, "section": sec, "section_head": is_head,
                    "semantic": h.get("semantic") if is_head else None,
                    "motif": h.get("motif") if is_head else None,
                    "emphasis": (h.get("emphasis", "") if is_head else ""),
                    "relation": h.get("relation") if is_head else None,
                    "why": (h.get("why", "") if is_head else ""), "elements": []})
    if missing:
        print(f"⚠️ LLM 漏填了 {len(missing)} 个**段首**（句号 {missing[:10]}）——"
              f"它们会带着空字段进闸门，⛔ 必然报红。这是**故意的**："
              f"漏填与填错要分得开，⛔ 不给默认值蒙混过去。", file=sys.stderr)
    if dup:
        print(f"⚠️ {len(dup)} 句在段内重复给了 motif（句号 {dup[:10]}），已按段首统一——"
              f"⛔ 一段里两个动效会让「段」这个概念失效。", file=sys.stderr)
    out = force_merge_short(out)

    # 🔴 **段首带 `section_span`＝整段时长**——闸门要判的是「这一段停多久」，
    # ⚠️ 合屏之后**句的时长不再等于屏的停留**，⛔ 别再拿句时长去判 3.5s 下限。
    span = {}
    for r in out:
        sec = r["section"]
        span[sec] = (min(span.get(sec, (r["start"],))[0], r["start"]), r["end"])
    for r in out:
        if r["section_head"]:
            lo, hi = span[r["section"]]
            r["section_span"] = round(hi - lo, 3)
    # ⚠️ 必须在兜底**之后**重算——`head_of` 是兜底前的，直接用会打印陈旧段数
    n_sec = len({r["section"] for r in out})
    short = [r["section"] for r in out
             if r.get("section_head") and r.get("section_span", 9) < 3.5]
    print(f"  {len(screens)} 句 → **{n_sec} 段**（合并了 {len(screens) - n_sec} 处）"
          + (f"｜⚠️ 仍有 {len(short)} 段 <3.5s：{short[:6]}" if short else "｜✅ 无短段"),
          file=sys.stderr)
    return {"screens": out}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="视觉编排：LLM 逐屏设计动效")
    ap.add_argument("--cues", required=True, help="tts_gen --timed 产出的 *.cues.json")
    ap.add_argument("--out", required=True, help="产出目录（plan.json / plan.md 落这里）")
    ap.add_argument("--account", default="", help="账号名，只写进 meta")
    ap.add_argument("--max-line-chars", type=int, default=12,
                    help="分屏上限，⚠️ 必须与真渲染时给 build_oneline.py 的一致")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--template", default="paragraph", choices=sorted(bo.TEMPLATES))
    a = ap.parse_args(argv)

    cues = json.load(open(a.cues, encoding="utf-8"))
    if isinstance(cues, dict):
        cues = cues.get("cues", cues)

    # ⚠️ 先确认**行屏**能拆开——断不开就别谈编排（那时才发现要改稿，LLM 白跑）。
    # 🔴 同一把分屏尺：⛔ 别在这里另写一份拆屏逻辑（不同源等于两份分屏）。
    rows, fails, _, _ = bo.build_screens(
        cues, a.max_line_chars, allow_proper=(a.template == "oneline"))
    if fails:
        print(f"❌ 分屏就没过：{len(fails)} 处断不开——⛔ 先把稿子改到能拆，"
              f"再谈编排（跑 build_oneline.py --precheck 看详情）", file=sys.stderr)
        return 1

    # 🔴 **编排单元是「句」（cue），⛔ 不是「行屏」。**三个粒度别混：
    #
    #   | 粒度 | 大小 | 谁定 |
    #   |---|---|---|
    #   | **行屏** | ≤12 字、约 2s | `split_cue`（确定性） |
    #   | **句/段** | 本批洗稿约 7–9s | ← **编排单元** |
    #   | 段（SEC_CUES>1） | 12s+ | 太粗，看不出"按内容设计" |
    #
    # ⚠️ `tpl-paragraph` 的硬契约⑥：**段落边界只落在句边界上，⛔ 绝不在一句话中间换手法**
    #    （那会让观众以为换了话题）。⇒ 逐**行屏**编排违反它，且违反核心理念「段内统一」。
    # ⚠️ 本批稿是连贯说话体、句子长（X1 十句 367 字 ⇒ 每句约 8.7s），
    #    **一句就是一个语义单元** ⇒ 渲染时配 `--sec-cues 1`。
    screens = [{"i": i, "text": c["text"],
                "start": round(float(c["start"]), 3), "end": round(float(c["end"]), 3)}
               for i, c in enumerate(cues)]
    print(f"  行屏 {len(rows)} 个（≤{a.max_line_chars} 字）→ **编排单元 {len(screens)} 句**",
          file=sys.stderr)

    plan = merge(screens, call_llm(screens, load_key(), a.model))
    plan["meta"] = {"cues": str(a.cues), "template": a.template, "account": a.account,
                    "generated_by": "llm", "model": a.model,
                    "unit": "cue", "rows": len(rows), "sec_cues": 1,
                    # ⚠️ 渲染时必须用同一个值，否则 plan 里的时段与画面对不上
                    "render_hint": f"build_oneline.py --template {a.template} --sec-cues 1"}

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    # ⚠️ 自动过一次六道闸——⛔ 别让没过闸的 plan 溜到渲染那一步
    res = cp.check(plan, cues)
    (out_dir / "plan.md").write_text(cp.to_md(res), encoding="utf-8")
    print(f"✅ {out_dir/'plan.json'} ｜ {out_dir/'plan.md'}（{len(screens)} 屏）")
    for w in res.get("warns", []):
        print(f"   ⚠️ {w}", file=sys.stderr)
    if res.get("fails"):
        print(f"\n⛔ 六道闸 {len(res['fails'])} 处不过：", file=sys.stderr)
        for f in res["fails"]:
            print(f"  · {f}", file=sys.stderr)
        print("\n处置：重跑本命令（LLM 有温度，同一份稿两次结果不同）；"
              "连续多次卡在同一处，就是 prompt 该改了，⛔ 别手改 plan.json 蒙混过闸——"
              "那份 plan 会被当成「LLM 设计的」拿去给老板看。", file=sys.stderr)
        return 1
    print("   ✅ 六道闸全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

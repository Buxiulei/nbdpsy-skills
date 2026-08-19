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

⛔ 你不决定分屏。屏的文字、起止时刻都已定死，一个字都不要改、不要合并、不要拆。

每屏要填五个字段：

1. `semantic` —— 这一屏在讲什么类型的话。**闭集，只能从这些里选**：
   {"｜".join(cp.SEMANTICS)}
2. `motif` —— 用哪个动效件。**闭集，只能从这些里选**：
   {"｜".join(cp.MOTIFS)}
3. `emphasis` —— 本屏要强调的词。**必须是本屏 text 的连续子串**（逐字对得上），
   没有值得强调的词就填空字符串。
4. `relation` —— 与上一屏的关系。**闭集**：{"｜".join(cp.RELATIONS)}
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

【输出】

严格 JSON，⛔ 不要 markdown 代码块，⛔ 不要任何解释性文字。格式：

{{"screens":[{{"i":0,"semantic":"反驳","motif":"wipe","emphasis":"不代表","relation":"开场","why":"本屏「不代表」是把前半句划掉再写新的，wipe 的擦出方向正好演这个动作"}}]}}

`i` 必须与输入的屏号一一对应、不重不漏。"""


def build_payload(screens: list[dict]) -> str:
    """给 LLM 的输入：屏号 + 文字 + 时长。⚠️ 时长要给——它影响该不该用 still。"""
    lines = ["以下是已经拆好的屏（⛔ 不要改动文字与分屏）：\n"]
    for s in screens:
        hold = round(s["end"] - s["start"], 2)
        lines.append(f'{s["i"]}\t{hold:.2f}s\t{s["text"]}')
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


def merge(screens: list[dict], llm: dict) -> dict:
    """把 LLM 填的字段并回确定性分屏。

    🔴 **以分屏为准、LLM 为辅**：屏号对不上的一律丢弃并报出来，
    ⛔ 绝不按 LLM 给的顺序重排——那等于让它间接改了分屏。
    """
    by_i = {int(x["i"]): x for x in (llm.get("screens") or []) if "i" in x}
    out, missing = [], []
    for s in screens:
        f = by_i.get(s["i"])
        if not f:
            missing.append(s["i"])
            f = {}
        out.append({**s,
                    "semantic": f.get("semantic"), "motif": f.get("motif"),
                    "emphasis": f.get("emphasis", ""), "relation": f.get("relation"),
                    "why": f.get("why", ""), "elements": []})
    if missing:
        print(f"⚠️ LLM 漏了 {len(missing)} 屏（屏号 {missing[:10]}）——"
              f"它们会带着空字段进闸门，⛔ 必然报红。这是**故意的**："
              f"漏填与填错要分得开，⛔ 不给默认值蒙混过去。", file=sys.stderr)
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

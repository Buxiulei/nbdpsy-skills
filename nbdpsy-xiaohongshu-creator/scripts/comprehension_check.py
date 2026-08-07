#!/usr/bin/env python3
"""理解性校验：让 DeepSeek 盲读稿件，看它读出来的意思跟你想表达的是不是同一件事。

用法：
    python3 comprehension_check.py <note.md>              # 盲读 + 与稿件声明意图对照
    python3 comprehension_check.py <note.md> --intent "一句话说明你想表达什么"
    python3 comprehension_check.py <note.md> --rounds 3   # 默认 2 轮，取交集降噪

**放在流程哪一步**：写稿之后、**出图之前**。理解不对就迭代文案，别急着烧生图额度——
出完图再发现"读者根本看不懂在说什么"，返工代价是重出整套。

诞生背景（2026-08-07 运营定案，同类错误已两次）：
- 「参加了几十场，自信没涨」——什么几十场？
- 「见第二面就认得这种感觉，正常吗」——见谁的第二面？哪种感觉？
两次都是"写的人脑子里有语境、标题只截了碎片"，而自审看不出来（写的人自带语境）。
所以要一个**没有任何上下文的第三方**来读：它读不懂，读者就读不懂。

与 zh_native_review.py 的分工：那个审**说得地不地道**，这个审**能不能被读懂**。两个都要跑。
"""
import json
import os
import re
import sys
from pathlib import Path

import requests

API = "https://api.deepseek.com/chat/completions"


def load_key() -> str:
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
    print("缺 DEEPSEEK_API_KEY：本环节降级为人工盲读（找一个没看过这篇的人，只给他标题问"
          "『这说的是什么场景』）；要启用机器校验请把 key 写进 ~/.config/nbdpsy/secrets.env",
          file=sys.stderr)
    sys.exit(2)


SYSTEM = """你是一个**第一次看到这篇内容**的普通小红书读者，没有任何背景信息。你的任务不是评价好坏，而是**如实报告你读懂了什么、哪里没读懂**。

请严格按下面的顺序回答：

1. **标题**：只看标题（不看正文），回答三件事——①这是谁、在什么情况下？②说的是什么感受或困扰？③你会不会想点开、为什么？
   ⚠️ **`title_clear` 只看一件事：这三问你能不能答出来。**
   - 三问里**任何一问答不上来、或者只能靠猜** → `title_clear: false`，并在 `title_problem` 写清是哪个词让你不确定（例如「"这种感觉"没说是哪种感觉」）。
   - 三问**都答得出**，但你觉得某个词还能更清楚 → **`title_clear` 仍然是 true**，把建议写进 `title_nitpick`。
   ⛔ 别把"能读懂但我有更好的说法"当成读不懂——那会让这道检查变成噪音，真正读不懂的反而被淹没。

2. **封面**：只看封面上的文字，回答同样三件事。封面比标题更重要——信息流里图先被看到。

3. **正文核心**：读完正文，用**一句话**说这篇到底在讲什么（`core`）。再用一两句说它想让读者明白的最关键那件事（`key_point`）。

4. **逐页**：每一页（P2、P3…）各用一句话说这页在讲什么。**如果某页给了绘图提示词，请一并判断：按那段提示词画出来的图，配上这页文字，读者会理解成什么**——图文对不上就在 `page_issues` 里点名。

5. **看不懂的地方**：把所有让你卡住、需要回头重读、或者有两种解读的句子列进 `confusing`，每条写清楚"卡在哪个词"。

判断尺度：
- 你是普通读者，**不许脑补背景**。作者以为不言自明的东西，你不知道就是不知道。
- 心理学术语如果没有就地解释，算看不懂（写进 confusing）。
- 但也别装傻：常识范围内的省略（"他"指前文提到的伴侣）不算问题。

6. **最后打三个分**（0–10 整数，写进 `scores`）。**每项都要给扣分理由和一条具体的加分建议**，不许只给分不给话。⛔ 别做老好人：7 分以上要真的配得上，虚高的分等于没打。

   **① `native`（中文本土化表达）**——像不像中国人平常说话。
   锚点：3=大量术语腔/翻译腔/生造比喻，读着像机翻；6=基本通顺，但有几处书面腔或专业词硬塞；8=像朋友在跟你讲话，个别地方还能更松；10=每一句都自然，读完不觉得是"文章"。
   扣分点举例：光杆形容词当名词（"强烈9分"）、术语直译（"爱轰炸"不解释）、工程/游戏词硬套感情（"投喂""供糖"）、欧化长句。

   **② `substance`（干货密度／有没有收获）**——看完能带走多少东西。
   锚点：3=只讲道理，没有一条能拿去用的；6=有几条可操作但偏少、或藏在大段文字里不好找；8=条目充足（8条以上）且分了组，一眼能定位；10=信息密到想存下来照着做，每条都具体到能立刻执行。
   注意：**"讲得对"不等于"有干货"**——干货是读者能带走的东西，不是作者讲了多少道理。

   **③ `engagement`（想不想点赞收藏评论）**——分开说清楚是想点赞、想收藏、还是想评论。
   锚点：3=看完就划走；6=有点共鸣但不会动手互动；8=会想点赞或收藏其中之一；10=想收藏（怕以后找不到）+ 想评论（有话要说）+ 想转给某个朋友。
   ⚠️ **收藏的动机是"当下记不住、以后要翻出来看"**——所以判收藏意愿时问自己：这篇有没有值得存下来反复看的东西？没有就别给高分。

输出严格 JSON（不要 markdown 代码块）：
{"title_clear":bool,"title_read":{"who":"","situation":"","feeling":"","would_click":""},"title_problem":"",
 "cover_clear":bool,"cover_read":"","cover_problem":"",
 "core":"","key_point":"",
 "pages":[{"page":"P2","reads_as":"","image_text_match":true,"note":""}],
 "page_issues":[],"confusing":[],"title_nitpick":"","cover_nitpick":"",
 "scores":{"native":{"score":0,"why":"","how_to_improve":""},
           "substance":{"score":0,"why":"","how_to_improve":""},
           "engagement":{"score":0,"why":"","want_to":"点赞/收藏/评论/都不想","how_to_improve":""}}}"""


def extract(md: Path, with_prompts: bool = True) -> str:
    """抽稿件里读者能感知到的一切：标题、封面、正文、各页文字（可选带绘图提示词）。
    ⛔ 刻意不给 frontmatter 的角度/材料/账号等元信息——那正是要检验的『语境』，给了就白测。"""
    text = md.read_text(encoding="utf-8")
    parts = []
    m = re.search(r"^title:\s*(.+)$", text, re.M)
    if m:
        parts.append(f"【笔记标题】{m.group(1).strip()}")
    m = re.search(r"^(?:封面主标题|cover_headline):\s*(.+)$", text, re.M)
    if m:
        parts.append(f"【封面主标题】{m.group(1).strip()}")
    m = re.search(r"^##\s*发布文案[^\n]*\n(.*?)(?=^##\s|\Z)", text, re.S | re.M)
    if m:
        parts.append("【正文】\n" + m.group(1).strip())
    for pm in re.finditer(r"^###\s*(P\d[^\n]*)\n(.*?)(?=^###\s|\Z)", text, re.S | re.M):
        page, body = pm.group(1).strip(), pm.group(2)
        seg = [f"【{page}】"]
        fm = re.search(r"\*\*(?:页面文字|图内文字)\*\*\n(.*?)(?=\*\*|```)", body, re.S)
        if fm:
            seg.append("图上文字：\n" + fm.group(1).strip())
        if with_prompts:
            pm2 = re.search(r"```\n(.*?)```", body, re.S)
            if pm2:
                seg.append("绘图提示词：\n" + pm2.group(1).strip()[:1200])
        parts.append("\n".join(seg))
    return "\n\n".join(parts)


def declared_intent(md: Path) -> str:
    """稿件自己声明的意图——用来和盲读结果对照。"""
    text = md.read_text(encoding="utf-8")
    bits = []
    for key in ("角度", "场景一句话", "核心意图", "material"):
        m = re.search(rf"^{key}:\s*(.+)$", text, re.M)
        if m:
            bits.append(f"{key}：{m.group(1).strip()}")
    return " ｜ ".join(bits)


def ask(content: str, key: str) -> dict:
    r = requests.post(API, timeout=180, headers={"Authorization": f"Bearer {key}"},
        json={"model": "deepseek-chat", "temperature": 0.3,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": content}]})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def main() -> int:
    args = sys.argv[1:]
    rounds, intent, with_prompts = 2, None, True
    for flag, cast in (("--rounds", int), ("--intent", str)):
        if flag in args:
            i = args.index(flag)
            val = cast(args[i + 1])
            if flag == "--rounds":
                rounds = val
            else:
                intent = val
            del args[i:i + 2]
    if "--no-prompts" in args:
        with_prompts = False
        args.remove("--no-prompts")
    if len(args) != 1:
        print(__doc__)
        return 2

    md = Path(args[0])
    content = extract(md, with_prompts)
    if not content:
        print("没抽到可读文本（缺 title/发布文案/页面文字）")
        return 2
    key = load_key()

    reads = [ask(content, key) for _ in range(rounds)]
    # 多数决：标题/封面只要有一轮说读不懂，就算读不懂（宁可误报，不可漏报——
    # 漏报的代价是发出去没人看懂，误报的代价只是我们多看一眼）
    title_clear = all(r.get("title_clear") for r in reads)
    cover_clear = all(r.get("cover_clear") for r in reads)
    confusing, page_issues = [], []
    for r in reads:
        for c in r.get("confusing") or []:
            if c not in confusing:
                confusing.append(c)
        for c in r.get("page_issues") or []:
            if c not in page_issues:
                page_issues.append(c)

    nitpicks = [x for r in reads for x in (r.get("title_nitpick"), r.get("cover_nitpick")) if x]
    # 三项评分取各轮均值（单轮打分波动大）；任一项 < 6 视为不合格
    dims = ("native", "substance", "engagement")
    scores = {}
    for d in dims:
        vals = [(r.get("scores") or {}).get(d, {}).get("score") for r in reads]
        vals = [v for v in vals if isinstance(v, (int, float))]
        scores[d] = {
            "score": round(sum(vals) / len(vals), 1) if vals else None,
            "per_round": vals,
            "why": [(r.get("scores") or {}).get(d, {}).get("why") for r in reads][0],
            "how_to_improve": [(r.get("scores") or {}).get(d, {}).get("how_to_improve") for r in reads][0],
        }
        if d == "engagement":
            scores[d]["want_to"] = [(r.get("scores") or {}).get(d, {}).get("want_to") for r in reads]
    low = [d for d in dims if (scores[d]["score"] or 0) < 6]

    out = {
        "verdict": "pass" if (title_clear and cover_clear and not page_issues and not low) else "fail",
        "rounds": rounds,
        "title_clear": title_clear,
        "cover_clear": cover_clear,
        "blind_read": {
            "title": reads[0].get("title_read"),
            "title_problem": [r.get("title_problem") for r in reads if r.get("title_problem")],
            "cover": [r.get("cover_read") for r in reads],
            "cover_problem": [r.get("cover_problem") for r in reads if r.get("cover_problem")],
            "core": [r.get("core") for r in reads],
            "key_point": [r.get("key_point") for r in reads],
            "pages": reads[0].get("pages"),
        },
        "scores": scores,
        "low_dims": low,
        "page_issues": page_issues,
        "confusing": confusing,
        "nitpicks": nitpicks,
        "declared_intent": intent or declared_intent(md),
        "how_to_read": (
            "① 先看 blind_read.core——它读出来的核心，和你想讲的是同一件事吗？"
            "不是 → 文案要改，别急着出图。"
            "② title_clear/cover_clear 为 false 必须改标题（判据 0，见 xiaohongshu-spec §1）。"
            "③ page_issues 是图文对不上，改绘图提示词。"
            "④ confusing 逐条裁决：术语没解释就补半句；确属常识省略可驳回并写明理由。"
            "⑤ nitpicks 是『能读懂但还能更清楚』，**不阻塞发布**，顺手改则改。"
            "⑥ scores 三项（本土化/干货/互动意愿）：**任一项 <6 即判 fail 要返工**，"
            "全部 ≥7 才算好稿；每项都带 how_to_improve，照着改最省事。"
            "同一批多篇可横向比分，找出最弱那篇优先补。"
        ),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

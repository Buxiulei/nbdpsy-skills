#!/usr/bin/env python3
"""collage 稿件闸门 —— 作者交稿前跑，⛔ 不等 TTS、不等渲染。

    check_collage_script.py --script script-1.txt [--focus 3] [--speed 3.5]

## 明文规格（助理 2026-08-18 拍板；⛔ 此前只有"观察值不是指标"）

| 项 | 值 |
|---|---|
| 句数 | **≤11 句** |
| 总时长 | **30–40s** |
| 每屏停留 | **≥3.5s**，重点句（印章句）**≥4.5s** |
| 印章句 | **第一段单看必须无害**——含转折/否定的句子**整句同显** |

🩸 **规格此前的状态比"没有"更麻烦**：`SKILL.md` 写着「30–40 秒」、
`card-video-spec.md` 写着「典型落在 8-10 句，那是**观察值不是指标**」——
**数给了，但明确声明自己不作数**，于是人看到数也看到免责，各自按经验取值。
⇒ **看起来有规格，实际没有约束力。**现在句数上限由停留下限反推：`总时长 ÷ 3.5`。

## 🔴 为什么要有这个脚本

原话（助理 2026-08-18）：**「今天它三处 15 字超限的自查是『把规则抄一遍打勾』
——能用脚本量的别留给人眼。」**

⇒ 与本仓那条同源：**自检项必须是「产生新证据的动作」**。
**抄一遍规则再打勾，产生的证据是「我读过规则」，⛔ 不是「稿子合格」。**

## ⚠️ 2026-08-18 晚：本脚本的口径即将随「口播/卡片解耦」调整

老板批 X2「前言不搭后语」的根因是 **卡片 ＝ 逐句字幕**（句子被压到 ≤14 字、
一句一卡，论证被剁成电报体）。⇒ 解绑后：**口播写连贯段落（不再按屏裁句）**，
**卡片只显 LLM 提炼的关键词/短语/金句**。

🔴 **那时本脚本的「逐句字数/停留」检查要改成「口播总量（110–140 汉字）＋ 卡片屏数（≤11）」**。
⛔ **在改之前，别拿它去卡解耦后的稿子**——它会按「一句一卡」的旧口径误判。
（仍然适用的：总时长 30–40s、每屏停留 ≥3.5s、印章屏首段单看无害。）

exit 0 = 全过（可能带 warn）｜1 = 有 fail｜2 = 输入错误。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MAX_SENTS = 11
HOLD_MIN = 3.5
HOLD_FOCUS = 4.5
DUR_RANGE = (30.0, 40.0)
SPEED = 3.5
"""口播语速真值（汉字/秒），运营线实测。⛔ 别用 4.5 估——实测偏 29%。
⚠️ 它让「这句会停几秒」在**交稿前**就能算出来，不用先烧 TTS。"""

HANZI = re.compile(r"[一-龥]")
TURN = ("但", "却", "不", "没", "别", "反而", "其实", "并非", "未必", "然而")
"""转折/否定词——含它们的印章句**更危险**（首段单看常与原意相反）。
⚠️ 但它**只是加重提示，⛔ 不是判据**：见下。"""

COMMA = "，,、；;"
"""🔴 **判据是「印章句含逗号」，⛔ 不是「含转折词」。**

🩸 **这条改法本身是被实证证伪出来的**：首版判据写的是"含转折/否定词"，
而审稿代理给的那个真实案例——**X2 印章屏先显半句「所以你要等他，」单显 1.36s**
——**一个转折/否定词都不含**，词表判据当场漏掉了它要抓的那个案例。

⇒ 真正的害是**首段单看意思变了**，而那**不需要转折词**：
「所以你要等他」单看是"被动等着"，完整句「所以你要等他，等他自己说出口」才是有条件的。
⇒ 凡印章句**含逗号就会被分段** ⇒ **一律报出来让人确认首段单看无害**。
⚠️ 这更保守（会多报），但**保守的代价是多看一眼，漏报的代价是读者看到相反的意思**。"""


def hanzi(s: str) -> int:
    return len(HANZI.findall(s or ""))


def check(lines: list[str], focus: int | None, speed: float = SPEED) -> dict:
    fails, warns, rows = [], [], []
    n = len(lines)

    if n == 0:
        return {"ok": False, "fails": ["稿件没有句子——⛔ 这不是「空稿」，是没读到"],
                "warns": [], "rows": [], "n": 0, "total": 0.0}
    if n > MAX_SENTS:
        fails.append(f"共 {n} 句 > 上限 {MAX_SENTS} 句"
                     f"——⚠️ 上限不是拍的：{DUR_RANGE[1]:.0f}s ÷ {HOLD_MIN}s/屏 反推出来的")

    total = 0.0
    for i, ln in enumerate(lines):
        h = hanzi(ln)
        hold = round(h / speed, 2) if speed else 0.0
        total += hold
        is_focus = (focus is not None and i == focus)
        need = HOLD_FOCUS if is_focus else HOLD_MIN
        if hold < need:
            fails.append(
                f"第 {i + 1} 句「{ln[:14]}」{h} 字 ⇒ 约停 {hold}s < {need}s"
                f"{'（印章句）' if is_focus else ''}\n"
                f"    ⇒ 把话说长一点（**⛔ 不是把别的句子说短**）；"
                f"若整篇都偏短，那是语速问题，重跑 TTS 放慢或加句间停顿")
        if is_focus and any(c in ln for c in COMMA):
            head = re.split("[" + re.escape(COMMA) + "]", ln)[0]
            extra = "（且含转折/否定词，**风险更高**）" if any(w in ln for w in TURN) else ""
            warns.append(
                f"第 {i + 1} 句是印章句且**含逗号会被分段**{extra}\n"
                f"      首段单看是：「{head}」——**请确认它单独出现时无害**；\n"
                f"      有疑问就让这句**整句同显**，⛔ 别按逗号先后入场。\n"
                f"      🩸 实证：X2 印章屏首段「所以你要等他，」单显 1.36s，"
                f"读者那 1.36 秒看到的是与原意不同的一句话")
        rows.append({"i": i + 1, "hanzi": h, "hold": hold, "focus": is_focus, "text": ln})

    total = round(total, 1)
    if not (DUR_RANGE[0] <= total <= DUR_RANGE[1]):
        (fails if total > DUR_RANGE[1] else warns).append(
            f"预估总时长 {total}s 不在 {DUR_RANGE[0]:.0f}–{DUR_RANGE[1]:.0f}s 内"
            f"（按语速 {speed} 汉字/秒；⚠️ 这是**估算**，真值以 TTS 为准）")
    if focus is not None and not (0 <= focus < n):
        fails.append(f"印章句索引 {focus} 越界（共 {n} 句，0 起）")

    return {"ok": not fails, "fails": fails, "warns": warns, "rows": rows,
            "n": n, "total": total}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="collage 稿件闸门（交稿前跑，不烧 TTS）")
    ap.add_argument("--script", required=True, help="script-N.txt（一行一句）")
    ap.add_argument("--focus", type=int, help="印章句索引（0 起）")
    ap.add_argument("--speed", type=float, default=SPEED,
                    help=f"语速（汉字/秒，默认 {SPEED} 实测真值；⛔ 别用 4.5，偏 29%%）")
    a = ap.parse_args(argv)
    try:
        lines = [x.strip() for x in Path(a.script).read_text(encoding="utf-8").splitlines()
                 if x.strip()]
    except Exception as e:
        print(f"❌ 读不到 --script：{e}", file=sys.stderr)
        return 2

    res = check(lines, a.focus, a.speed)
    print(f"  {res['n']} 句｜预估总时长 {res['total']}s（语速 {a.speed} 字/秒）", file=sys.stderr)
    for r in res["rows"]:
        mark = "◆" if r["focus"] else " "
        flag = "❌" if r["hold"] < (HOLD_FOCUS if r["focus"] else HOLD_MIN) else "✅"
        print(f"  {flag}{mark} 第{r['i']:2d}句 {r['hanzi']:2d}字 ≈{r['hold']:.2f}s  {r['text'][:20]}",
              file=sys.stderr)
    for w in res["warns"]:
        print(f"\n⚠️ {w}", file=sys.stderr)
    if res["fails"]:
        print(f"\n⛔ {len(res['fails'])} 处不过：", file=sys.stderr)
        for f in res["fails"]:
            print(f"  · {f}", file=sys.stderr)
        return 1
    print("\n✅ 全过（句数/停留/总时长/印章句）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

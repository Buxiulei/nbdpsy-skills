#!/usr/bin/env python3
"""公众号正文插图 · HTML 确定性渲染（⛔ 不走出图 API）。

    render_illust.py --data illust.json --out 工作目录/

## 为什么是 HTML 而不是 AI 出图

① **插图是排版问题不是绘画问题**——步骤、对比、定义都是结构化内容；
② **图内要出现中文短标注**，AI 出图写中文不可控，HTML 想写什么就是什么；
③ 🩸 **现实原因（服务号线 2026-08-18）**：老板充不了 OpenAI（原话「我现在没法给
   openai 充值，网页打不开」）⇒ gpt-image-2 那条路**眼下就是不通的**。

## 数据格式（与 gen_gzh_images.py 的围栏 JSON 同族：插图用 `layout` 键）

```json
{"layout": "steps",
 "title": "蝴蝶拍：六十秒安抚自己",
 "subtitle": "情绪上头时，先让身体慢下来",
 "steps": [
   {"name": "坐好", "desc": "找地方坐下，双脚踏实踩地。",
    "dont": "不用盘腿、不用闭眼，全程睁眼"},
   {"name": "左右轻拍", "desc": "手不离肩，原地轮流轻拍。"}
 ]}
```
⚠️ `dont` **可选**——真稿四步里第 3 步就没有反例（那句是正向引导不是禁止）。
⛔ 别强制每步都有：**逼写稿人硬造一条禁令，比没有禁令更糟——读者会把硬造的
「别做 X」当成真的风险提示。**

## 🔴 两道闸（都拿真稿量出来的，⛔ 不是拍的）

- **溢出闸**：内容高 > 画布高 → 退出码 1。
- **字号下限闸**：`@375px 手机正文宽（≈0.286 倍）下最小的那层 ≥ 11px`。
  🩸 实证：4 步/张时展开句只有 **7.1px**、反例 **6.3px**——**读者截图保存后，
  最要紧的那层是糊的**。改 2 步/张后是 11.4px / 10.9px。
  ⇒ **每张 2 步是这条闸反推出来的结果，⛔ 不是先定的规矩。**

exit 0 = 全过｜1 = 有闸门不过｜2 = 输入错误。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
TPL_DIR = HERE.parent / "assets" / "illust-templates"
TEMPLATES = {"steps": TPL_DIR / "tpl-steps.html"}

# 画幅：⛔ 别信规格里的「16:9」——那是出图 API 的参数名，实产 42 张实测全是 3:2、零例外。
CANVAS = dict(w=1313, h=876)
FEED_W = 375          # 手机公众号正文图宽（pt）——判据落在读者看到的尺寸上
MIN_FEED_PX = 11.0    # 最小那层的下限（服务号线 2026-08-18 定）

# 配色：与静物版同一套（暖米大字 v3）。⛔ 鼠尾草绿 #C9D6CE 未用——
# 它在静物版里是「新芽＝恢复」的语义，步骤图里没有这个位置，**空着就空着，⛔ 不硬塞**。
PALETTE = dict(
    BASE="#E8D8C4",     # 暖米白：底
    INK="#2E3A44",      # 主文字
    INK2="#43525E",     # 展开句
    MUTED="#6B7A86",    # 副题
    ACCENT="#A34B3A",   # 赭红：序号色块。⛔ accent 用色块不用细线——
                        #   细线缩到信息流尺寸会被抹平（实测 0 像素）
    HINT="#A8B5C4",     # 雾霾蓝灰：反例底块
)

# 字号：2 步/张的实测值。⚠️ 改任何一个都要重跑字号下限闸，⛔ 别凭观感调。
SIZES = dict(H1=46, SUB=24, NAME=50, DESC=40, NUM=76, NUMF=40, NUMR=20,
             PAD=56, PADX=64, GAP=46)

STEPS_PER_PAGE = 2
"""🔴 由字号下限闸反推，⛔ 不是先定的规矩：4 步/张时最小层只有 6.3px（糊），
2 步/张才到 10.9px。⚠️ 改这个数必须重跑闸门。"""


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def steps_html(steps: list[dict], base_no: int) -> str:
    out = []
    for i, st in enumerate(steps):
        dont = st.get("dont")
        # ⚠️ 反例槽位允许缺席——没有就不渲这个 div，⛔ 不留空块
        dont_html = f'\n        <div class="dont">{esc(dont)}</div>' if dont else ""
        out.append(
            f'<div class="step">\n      <div class="num">{base_no + i}</div>\n'
            f'      <div class="body">\n'
            f'        <div class="name">{esc(st.get("name", ""))}</div>\n'
            f'        <div class="desc">{esc(st.get("desc", ""))}</div>{dont_html}\n'
            f'      </div>\n    </div>')
    return "\n    ".join(out)


def instantiate(data: dict, steps: list[dict], base_no: int, page: int, pages: int,
                strict_decor: bool = False) -> str:
    sub = esc(data.get("subtitle", ""))
    if pages > 1:
        sub = f"{sub} · 第 {page}／{pages} 张" if sub else f"第 {page}／{pages} 张"
    m = {"__CANVAS__": f"{CANVAS['w']}x{CANVAS['h']}",
         "__W__": CANVAS["w"], "__H__": CANVAS["h"],
         "__FEED_SCALE__": round(FEED_W / CANVAS["w"], 6),
         "__TITLE__": esc(data.get("title", "")), "__SUBTITLE__": sub,
         "__STEPS_HTML__": steps_html(steps, base_no),
         # ⚠️ 参数必须真的生效——写进 --help 却不接线就是假承诺
         "__CONTENT_LAYERS__": json.dumps(
             (["标题", "副题"] if strict_decor else []) + ["动作名", "展开句", "反例"],
             ensure_ascii=False),
         **{f"__{k}__": v for k, v in PALETTE.items()},
         **{f"__{k}__": v for k, v in SIZES.items()}}
    html = TEMPLATES[data["layout"]].read_text(encoding="utf-8")
    for k, v in m.items():
        html = html.replace(k, str(v))
    import re
    left = sorted(set(re.findall(r"__[A-Z_0-9]+__", html)))
    if left:
        sys.exit(f"❌ 模板还有没填的占位符：{left}")
    return html


def render(html_path: Path, png_path: Path) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--force-device-scale-factor=1", "--hide-scrollbars"])
        pg = b.new_page(viewport={"width": CANVAS["w"], "height": CANVAS["h"]})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"file://{html_path.resolve()}")
        pg.wait_for_function("window.ILLUST_REPORT !== undefined", timeout=20000)
        rep = pg.evaluate("window.ILLUST_REPORT")
        pg.screenshot(path=str(png_path))
        b.close()
    rep["page_errors"] = errs
    return rep


def gate(rep: dict, tag: str) -> list[str]:
    """两道闸。⚠️ 返回 fail 清单，⛔ 不在这里退出——所有页都渲完再一起报。"""
    bad = []
    if rep["page_errors"]:
        bad.append(f"{tag}：页面 JS 错误 {rep['page_errors'][:1]}")
    if rep["overflow"]:
        bad.append(f"{tag}：内容溢出画布（底边 {rep['content_bottom']}px > {CANVAS['h']}px）"
                   f"——减少本页步数或缩短展开句，⛔ 别缩字号（那会撞下一条闸）")
    m = rep["min_feed_px"]
    if m is not None and m < MIN_FEED_PX:
        # ⚠️ 只在内容层里挑最差的那个——⛔ 别把装饰层报出来当元凶（那是假红）
        cl = {k: v for k, v in rep["feed_px"].items() if k in rep["content_layers"]}
        worst = min(cl, key=cl.get)
        bad.append(
            f"{tag}：最小的那层「{worst}」在手机正文里只有 {m}px（下限 {MIN_FEED_PX}px）——"
            f"读者截图保存后这一层是糊的。⇒ **减少每张的步数**，⛔ 别缩字号也别砍反例")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="公众号正文插图 · HTML 确定性渲染")
    ap.add_argument("--data", required=True, help="围栏 JSON（layout=steps）")
    ap.add_argument("--out", required=True, help="工作目录")
    ap.add_argument("--strict-decor", action="store_true",
                    help="把标题/副题等装饰层也纳入字号下限判定。"
                         "⚠️ 默认不纳入——它们糊了不影响「照着做」，"
                         "而把它们纳进来会产生**处置建议不成立的假红**（减少步数救不了副题）")
    ap.add_argument("--steps-per-page", type=int, default=STEPS_PER_PAGE,
                    help=f"每张几步（默认 {STEPS_PER_PAGE}）。"
                         f"⚠️ 这个数由字号下限闸反推，⛔ 改大必然撞闸")
    a = ap.parse_args(argv)

    try:
        data = json.loads(Path(a.data).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ 读不到 --data：{e}", file=sys.stderr)
        return 2
    if data.get("layout") not in TEMPLATES:
        print(f"❌ layout 必须是 {sorted(TEMPLATES)}，拿到 {data.get('layout')!r}", file=sys.stderr)
        return 2
    steps = data.get("steps") or []
    if not steps:
        print("❌ steps 为空——⛔ 这不是「没有步骤」，是数据没读到", file=sys.stderr)
        return 2

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    chunks = [steps[i:i + a.steps_per_page] for i in range(0, len(steps), a.steps_per_page)]
    reps, fails, no = [], [], 1
    for pi, chunk in enumerate(chunks, 1):
        hp = out / f"illust-steps-{pi}.html"
        hp.write_text(instantiate(data, chunk, no, pi, len(chunks), a.strict_decor),
                      encoding="utf-8")
        rep = render(hp, out / f"illust-steps-{pi}.png")
        rep["page"] = pi
        reps.append(rep)
        fails += gate(rep, f"第 {pi}/{len(chunks)} 张")
        no += len(chunk)

    print(json.dumps({"ok": not fails, "pages": len(chunks), "reports": reps,
                      "fails": fails}, ensure_ascii=False, indent=2))
    for r in reps:
        print(f"  第 {r['page']} 张：{r['steps']} 步（反例 {r['dont_slots']} 条）"
              f"｜手机正文最小字号 {r['min_feed_px']}px｜底边 {r['content_bottom']}px",
              file=sys.stderr)
    if fails:
        print("\n⛔ 闸门不过：", file=sys.stderr)
        for f in fails:
            print(f"  · {f}", file=sys.stderr)
        return 1
    print(f"\n✅ {len(chunks)} 张全过（溢出闸 + 字号下限闸）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

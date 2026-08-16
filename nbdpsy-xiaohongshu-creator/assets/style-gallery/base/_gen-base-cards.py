"""重出本目录的内容页基底说明图（默认基底色卡 + 基底解剖卡，共 2 张）。

    python3 _gen-base-cards.py      # 直接覆盖本目录同名 .jpg

基底 = 风格档案 `profile.visual` 的 palette / texture / character_card / text_color 四要素，
是"同一个号看起来像同一个设计师"的锚点。这两张卡自己就长成默认基底的样子（暖米白底、
深灰蓝字），运营看图就能对上号，不必读 JSON。

🔴 下面 NUANMI / ANATOMY 里的字段说明、色名、色值、人物卡整句、质感描述**逐字抄自规格文档**，
⛔ 一个字都不许在这里现编：
  references/illustration-spec.md §1「风格基底」——字段映射表 + 调色板表 + 人物卡整句
规格改了就改这里再重跑；⛔ 反过来拿这张图当真源。

⚠️ 色片**不是配比条**：字段映射表只规定每个色的角色（主色 / 背景 / 辅助 / 可选强调），
没有规定配比，所以这里用等宽色片而非 video/ 那种宽度即配比的色带——⛔ 别改成配比条，
那等于凭空发明一个规格里没有的数。
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent

# 默认基底自身的颜色（＝下面卡片要展示的那套，illustration-spec §1 调色板表）
BG, GLOW = "#e8d8c4", "#f3e7d8"
FG, SUB, LINE = "#5a6b7b", "#8b96a3", "#a8b5c4"
ACCENT = "#a34b3a"

# —— 卡一：默认基底色卡 ——（文案逐字抄自 illustration-spec §1 字段映射表 / 调色板表）
NUANMI = dict(
    slug="base-nuanmi", kind="内容页基底", name="暖米", tag="默认＝全矩阵现状",
    swatches=[("雾霾蓝灰 #A8B5C4", "主色", "#a8b5c4"),
              ("暖米白 #E8D8C4", "背景", "#e8d8c4"),
              ("鼠尾草绿 #C9D6CE", "辅助", "#c9d6ce"),
              ("赭砖红 #A34B3A", "可选强调", "#a34b3a")],
    rows=[("文字色", "深灰蓝 #5A6B7B（正文与默认标题）、深钢蓝黑 #2B3A4A（可选加粗标题）、"
                    "赭砖红 #A34B3A（可选点睛）"),
          ("肌理", "柔和扁平矢量插画风、细腻颗粒 / 纸质肌理、柔光无强烈阴影、圆润柔和形体"),
          ("人物卡", "圆脸、齐肩微卷短发的东亚年轻女性，穿燕麦色针织衫，神情温和平静。")],
    note="这四项是<b>「默认配置」的取值——示例不是常量</b>：没有自己档案的运营跟随它，"
         "当前运营档案不同就整套换成他的。<br>"
         "「默认＝全矩阵现状」的凭证：2026-08-16 实读现行「暖米大字」档案，四要素与本卡同值。",
)

# —— 卡二：基底解剖卡 ——（「管哪一处」列逐字抄自字段映射表第 2 列）
ANATOMY = dict(
    slug="base-anatomy", kind="内容页基底", name="四要素各管什么", tag="解剖卡",
    lede="锁住这四项、只换主体画面与文字 —— 一条笔记的 6–9 张图才会像同一个设计师做的。",
    grid=[
        ("palette", "色板", "#a8b5c4",
         "每条提示词的<b>配色行</b>，以及“仅用品牌调色板 / 仅用品牌基底配色”这句话所指的那套色",
         "换掉＝整套画面的颜色全变；页与页之间色值漂移＝整套散架"),
        ("texture", "肌理", "#c9d6ce",
         "<b>质感描述</b>：画风、肌理、光影那一段",
         "换掉＝笔触与手感全变（扁平矢量换成别的画风），但画的内容不变"),
        ("character_card", "人物卡", "#8b96a3",
         "<b>人物卡整句</b>：出现人物时逐字照抄这一句，保证全套是“同一个人”",
         "换掉＝全套换一张脸；漏带这一句就长相漂移"),
        ("text_color", "文字色", "#5a6b7b",
         "<b>文字色</b>：大标题、正文说明、强调字的颜色",
         "换掉＝只有图上中文的颜色变，画面不动"),
    ],
    note="⛔ 四项都是<b>当前运营风格档案</b>里的字段，不是全局常量；某一项缺了就回落到默认配置示例值、"
         "别空着。<br>基底一旦漂移（配色跑偏 / 人物换了张脸 / 出成方图）＝<b>整批全废、全部重出</b>。",
)

CSS_COMMON = """
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; font-family:"Noto Sans CJK SC",sans-serif;
  -webkit-font-smoothing:antialiased; }}
#card {{ width:{W}px; height:{H}px; padding:36px 44px 30px; color:{fg};
  background:radial-gradient(ellipse 620px 420px at 50% 30%, {glow} 0%, {bg} 80%);
  display:flex; flex-direction:column; }}
#top {{ display:flex; align-items:baseline; gap:15px; }}
#kind {{ font-size:18px; letter-spacing:4px; color:{sub}; }}
#name {{ font-size:42px; font-weight:700; letter-spacing:2px; }}
#tag {{ font-size:16px; letter-spacing:2px; color:{bg}; background:{fg};
  padding:4px 12px; border-radius:3px; font-weight:600; }}
#note {{ margin-top:auto; padding-top:13px; border-top:1px solid {line}66;
  font-size:14px; line-height:1.62; color:{sub}; }}
#note b {{ color:{fg}; }}
"""

PAGE_NUANMI = """<!doctype html>
<html><meta charset="utf-8"><style>""" + CSS_COMMON + """
/* 等宽色片：字段映射表只定角色不定配比，⛔ 别做成宽度即配比的色带 */
#chips {{ margin-top:26px; display:flex; gap:14px; }}
.ch {{ flex:1; }}
.ch u {{ display:block; height:56px; border-radius:5px; text-decoration:none;
  box-shadow:0 0 0 1px {line}; }}
.ch b {{ display:block; margin-top:9px; font-size:14px; font-weight:700; }}
.ch i {{ display:block; font-style:normal; font-size:13px; color:{sub}; margin-top:1px; }}
#rows {{ margin-top:26px; }}
.row {{ display:flex; gap:14px; font-size:16px; line-height:1.62; margin-top:11px; }}
.row em {{ font-style:normal; flex:none; width:62px; color:{sub}; font-size:15px;
  letter-spacing:2px; white-space:nowrap; }}
</style><body><div id="card">
  <div id="top"><div id="kind">{kind}</div><div id="name">{name}</div><div id="tag">{tag}</div></div>
  <div id="chips">{chips}</div>
  <div id="rows">{rows}</div>
  <div id="note">{note}</div>
</div></body></html>"""

PAGE_ANATOMY = """<!doctype html>
<html><meta charset="utf-8"><style>""" + CSS_COMMON + """
#lede {{ margin-top:14px; font-size:15px; line-height:1.6; color:{sub}; }}
#grid {{ margin-top:20px; }}
.hd {{ display:flex; gap:14px; font-size:13px; letter-spacing:1px; color:{sub};
  padding-bottom:7px; border-bottom:1px solid {line}66; }}
.it {{ display:flex; gap:14px; padding:11px 0; border-bottom:1px solid {line}33; }}
.c1 {{ flex:none; width:150px; display:flex; gap:8px; align-items:flex-start; }}
.c1 u {{ flex:none; width:11px; height:11px; border-radius:3px; margin-top:4px;
  text-decoration:none; box-shadow:0 0 0 1px {line}55; }}
.c1 b {{ font-size:15px; font-weight:700; display:block; }}
.c1 i {{ font-style:normal; font-size:11.5px; color:{sub}; display:block;
  letter-spacing:0.3px; word-break:break-all; }}
.c2 {{ flex:1; font-size:14px; line-height:1.55; }}
.c3 {{ flex:none; width:216px; font-size:14px; line-height:1.55; color:{accent}; }}
.hd .c1, .hd .c2, .hd .c3 {{ font-size:13px; }}
</style><body><div id="card">
  <div id="top"><div id="kind">{kind}</div><div id="name">{name}</div><div id="tag">{tag}</div></div>
  <div id="lede">{lede}</div>
  <div id="grid">
    <div class="hd"><div class="c1">要素（档案字段）</div><div class="c2">落到提示词的哪一处</div>
      <div class="c3">换掉它，成图变什么</div></div>
    {items}
  </div>
  <div id="note">{note}</div>
</div></body></html>"""


def build_nuanmi(c: dict) -> str:
    chips = "".join(
        f'<div class="ch"><u style="background:{hexv}"></u><b>{label}</b><i>{role}</i></div>'
        for label, role, hexv in c["swatches"])
    rows = "".join(f'<div class="row"><em>{k}</em><span>{v}</span></div>' for k, v in c["rows"])
    return PAGE_NUANMI.format(W=720, H=500, bg=BG, glow=GLOW, fg=FG, sub=SUB, line=LINE,
                              chips=chips, rows=rows,
                              **{k: c[k] for k in ("kind", "name", "tag", "note")})


def build_anatomy(c: dict) -> str:
    items = "".join(
        f'<div class="it"><div class="c1"><u style="background:{hexv}"></u>'
        f'<span><b>{cn}</b><i>{field}</i></span></div>'
        f'<div class="c2">{where}</div><div class="c3">{effect}</div></div>'
        for field, cn, hexv, where, effect in c["grid"])
    return PAGE_ANATOMY.format(W=720, H=590, bg=BG, glow=GLOW, fg=FG, sub=SUB, line=LINE,
                               accent=ACCENT, items=items,
                               **{k: c[k] for k in ("kind", "name", "tag", "lede", "note")})


CARDS = [(NUANMI, build_nuanmi, 720, 500), (ANATOMY, build_anatomy, 720, 590)]

from PIL import Image  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    br = p.chromium.launch(args=["--hide-scrollbars"])
    for c, builder, w, h in CARDS:
        ctx = br.new_context(viewport={"width": w, "height": h}, device_scale_factor=2)
        html = OUT / f"_{c['slug']}.html"
        html.write_text(builder(c), encoding="utf-8")
        pg = ctx.new_page()
        pg.goto(html.as_uri())
        pg.wait_for_timeout(300)
        png = OUT / f"_{c['slug']}.png"
        pg.screenshot(path=str(png))
        pg.close()
        ctx.close()
        im = Image.open(png).convert("RGB").resize((w, h), Image.LANCZOS)
        im.save(OUT / f"{c['slug']}.jpg", "JPEG", quality=92, optimize=True, progressive=True)
        png.unlink()
        html.unlink()
    br.close()
print(json.dumps([c["slug"] for c, _, _, _ in CARDS], ensure_ascii=False))

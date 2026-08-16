"""重出本目录的子风格色卡说明图（微电影三档 + 播客两档，共 5 张）。

    python3 _gen-substyle-cards.py      # 直接覆盖本目录同名 .jpg

每张卡自己就长成那一档的样子（底色/字色照该档取），色板条的**宽度即配比**——
运营看图就能分，不必读 hex。

🔴 下面 CARDS 里的色板、转场、节奏、适用**逐字抄自规格文档**，⛔ 一个字都不许在这里现编：
  微电影三档 → nbdpsy-text-to-video/references/cinematic-direction.md §一之三
  播客两档   → nbdpsy-text-to-video/references/podcast-video-spec.md「播放器主题两档」
规格改了就改这里再重跑；⛔ 反过来拿这张图当真源。

另两张 720×1280 的播放器**真实渲染帧**（bokecast-*-frame.jpg）不由本脚本产——那是拿真实
音轨跑 `record_podcast.py --theme` 各渲一遍取帧，做法见 podcast-video-spec.md 同一节。
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent

W, H = 720, 460

CARDS = [
    dict(
        slug="weidianying-nuanwu", kind="微电影", name="暖雾", tag="默认档",
        bg="#e8d8c4", glow="#f3e7d8", fg="#3f4a52", sub="#6b7681", line="#a8b5c4",
        swatches=[("暖米白 #E8D8C4", "主导", "#e8d8c4", 55, "#3f4a52"),
                  ("雾霾蓝灰 #A8B5C4", "辅助", "#a8b5c4", 33, "#2f3d48"),
                  ("鼠尾草绿 #C9D6CE", "点缀", "#c9d6ce", 12, "#2f3d48")],
        trans="自然镜头切换／淡入淡出",
        rhythm="中速（＝现行基准秒数）",
        fit="疗愈叙事、通用科普——收尾要让人「被理解、能歇口气」",
        note="历史全部成片走的都是这一档（CPTSD 首片即暖雾）",
    ),
    dict(
        slug="weidianying-chenjing", kind="微电影", name="沉静", tag="",
        bg="#3d4956", glow="#4a5866", fg="#e6ebf0", sub="#a8b5c4", line="#7d8b99",
        swatches=[("雾霾蓝灰 #A8B5C4", "主导·压低明度", "#a8b5c4", 70, "#2f3d48"),
                  ("暖米白 #E8D8C4", "极小面积", "#e8d8c4", 22, "#3f4a52"),
                  ("鼠尾草绿 #C9D6CE", "几乎不用", "#c9d6ce", 8, "#2f3d48")],
        trans="淡入淡出／遮罩",
        rhythm="慢（各镜 +1s 左右）",
        fit="创伤、哀伤、重议题——收尾要让人「这份重我不替你翻篇」",
        note="全片压在冷区，⛔ 不做暖包围冷的大反转（也是合规红线）",
    ),
    dict(
        slug="weidianying-chenguang", kind="微电影", name="晨光", tag="",
        bg="#eef3ee", glow="#f7faf6", fg="#3a4a42", sub="#6e7d74", line="#c9d6ce",
        swatches=[("暖米白 #E8D8C4", "主导", "#e8d8c4", 45, "#3f4a52"),
                  ("鼠尾草绿 #C9D6CE", "主导", "#c9d6ce", 42, "#2f3d48"),
                  ("雾霾蓝灰 #A8B5C4", "极少过渡镜", "#a8b5c4", 13, "#2f3d48")],
        trans="动作甩镜／动态接力",
        rhythm="快（各镜 −1s 左右）",
        fit="成长、行动、方法论——收尾要让人「明天可以试试这一步」",
        note="高位起、更高位收，靠光越来越足推进，不靠冷暖翻转",
    ),
    dict(
        slug="bokecast-shenye", kind="播客", name="深夜电台", tag="默认档",
        bg="#000000", glow="#16161a", fg="#f4efe6", sub="#cfc7ba", line="#e8c27a",
        swatches=[("黑底 #000000", "画面底", "#000000", 46, "#e8c27a"),
                  ("暖白 #F4EFE6", "女声字幕", "#f4efe6", 27, "#3f4a52"),
                  ("浅金 #E8C27A", "男声字幕·声纹·进度", "#e8c27a", 27, "#3f2f18")],
        trans="金色心电声纹＋大字幕，说话人只靠颜色分",
        rhythm="record_podcast.py --theme shenye",
        fit="通用——十分钟量级长对谈，夜里听的调子",
        note="历史全部已发期数都是它（会客厅 Vol.1 即深夜电台）",
    ),
    dict(
        slug="bokecast-zhishang", kind="播客", name="纸上对谈", tag="",
        bg="#e8d8c4", glow="#f3e7d8", fg="#3a4a57", sub="#6b6355", line="#3a4a57",
        swatches=[("暖米白纸纹 #E8D8C4", "画面底", "#e8d8c4", 46, "#3a4a57"),
                  ("深灰蓝 #5A6B7B", "女声字幕", "#5a6b7b", 27, "#f2ece2"),
                  ("墨色 #3A4A57", "声纹·进度·标题", "#3a4a57", 27, "#f2ece2")],
        trans="墨色声纹＋纸纹底，与品牌图文同一套语言",
        rhythm="record_podcast.py --theme zhishang",
        fit="轻议题——想让对谈看起来像一页纸，不像深夜直播间",
        note="男声字幕用墨绿 #4A5F55 与女声分色；底纹是极淡的纸颗粒，不是纯色",
    ),
]

PAGE = """<!doctype html>
<html><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; font-family:"Noto Sans CJK SC",sans-serif;
  -webkit-font-smoothing:antialiased; }}
#card {{ width:{W}px; height:{H}px; padding:38px 44px 34px; color:{fg};
  background:radial-gradient(ellipse 620px 420px at 50% 34%, {glow} 0%, {bg} 78%);
  display:flex; flex-direction:column; }}
#top {{ display:flex; align-items:baseline; gap:16px; }}
#kind {{ font-size:19px; letter-spacing:4px; color:{sub}; }}
#name {{ font-size:46px; font-weight:700; letter-spacing:3px; }}
#tag {{ font-size:17px; letter-spacing:2px; color:{bg}; background:{line};
  padding:4px 12px; border-radius:3px; font-weight:600; }}
/* 色带只放颜色、宽度即配比示意；文字全部落到下面的图例，窄色块才不会被裁字 */
#bar {{ margin-top:28px; display:flex; height:64px; border-radius:5px; overflow:hidden; }}
#legend {{ margin-top:13px; display:flex; gap:26px; }}
.lg {{ display:flex; align-items:flex-start; gap:8px; font-size:14px; line-height:1.45; }}
.lg u {{ flex:none; width:13px; height:13px; border-radius:3px; margin-top:3px;
  text-decoration:none; }}
.lg b {{ font-weight:700; }}
.lg i {{ font-style:normal; color:{sub}; }}
#rows {{ margin-top:auto; }}
.row {{ display:flex; gap:16px; font-size:18px; line-height:1.6; margin-top:9px; }}
.row em {{ font-style:normal; flex:none; width:52px; color:{sub}; font-size:16px;
  letter-spacing:2px; padding-top:2px; white-space:nowrap; }}
#note {{ margin-top:18px; padding-top:14px; border-top:1px solid {line}55;
  font-size:14px; line-height:1.6; color:{sub}; }}
</style><body><div id="card">
  <div id="top"><div id="kind">{kind}</div><div id="name">{name}</div>{tag_html}</div>
  <div id="bar">{bar}</div>
  <div id="legend">{legend}</div>
  <div id="rows">
    <div class="row"><em>{trans_label}</em><span>{trans}</span></div>
    <div class="row"><em>{rhythm_label}</em><span>{rhythm}</span></div>
    <div class="row"><em>适用</em><span>{fit}</span></div>
  </div>
  <div id="note">{note}</div>
</div></body></html>"""


def build(c: dict) -> str:
    bar = "".join(f'<div style="width:{pct}%;background:{hexv}"></div>'
                  for _, _, hexv, pct, _ in c["swatches"])
    legend = "".join(
        f'<div class="lg"><u style="background:{hexv};'
        f'box-shadow:0 0 0 1px {c["line"]}66"></u>'
        f'<span><b>{label}</b><br><i>{role}</i></span></div>'
        for label, role, hexv, _pct, _ink in c["swatches"])
    tag_html = f'<div id="tag">{c["tag"]}</div>' if c["tag"] else ""
    # 播客两档没有"转场/节奏"可言，这两行改标"画面/命令"
    is_pod = c["kind"] == "播客"
    return PAGE.format(
        W=W, H=H, bar=bar, legend=legend, tag_html=tag_html,
        trans_label="画面" if is_pod else "转场",
        rhythm_label="命令" if is_pod else "节奏",
        **{k: c[k] for k in ("bg", "glow", "fg", "sub", "line", "kind", "name",
                             "trans", "rhythm", "fit", "note")})


from PIL import Image  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    br = p.chromium.launch(args=["--hide-scrollbars"])
    ctx = br.new_context(viewport={"width": W, "height": H}, device_scale_factor=2)
    for c in CARDS:
        html = OUT / f"_{c['slug']}.html"
        html.write_text(build(c), encoding="utf-8")
        pg = ctx.new_page()
        pg.goto(html.as_uri())
        pg.wait_for_timeout(300)
        png = OUT / f"_{c['slug']}.png"
        pg.screenshot(path=str(png))
        pg.close()
        im = Image.open(png).convert("RGB").resize((W, H), Image.LANCZOS)
        im.save(OUT / f"{c['slug']}.jpg", "JPEG", quality=92, optimize=True, progressive=True)
        png.unlink()
        html.unlink()
    br.close()
print(json.dumps([c["slug"] for c in CARDS], ensure_ascii=False))

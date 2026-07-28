#!/usr/bin/env python3
"""把一篇长文正文排版渲染成「文本排版长图」笔记配图（路线②，2026-07-28 老板定案）。

与路线①（信息图轮播）的根本区别：**这里不生成 AI 图**。
AI 生图渲染不出 2000+ 字无错字的正文排版——路线② 的图是**确定性排版渲染**产物：
markdown → HTML/CSS 排版 → Chromium 渲染 → 按行边界切页 → PNG。
每一个字都来自输入文件，脚本不会改写、不会漏字，也不存在图内错别字。

分页原理（对齐参考样本实测）：正文**允许跨页断句**（一段的后半截可以落到下一页），
但**绝不从半行中间横切**——脚本用 Range.getClientRects() 取每一行的行盒底边当候选切点，
贪心地在不超过页面内容高度的前提下取最靠下的那个切点。另有两条防丑规则：
  · 标题（h1/h2/h3）底边不作候选 → 标题不会孤零零留在页底；
  · 表格内部的行不作候选 → 表格不会被拦腰截断（整表放不下时才整体挪到下一页）。

用法:
    typeset_longimage.py --md body.md                      # 出图到 <md同级>/images/<slug>/
    typeset_longimage.py --md body.md --out DIR --theme paper
    typeset_longimage.py --md body.md --html-only          # 只产 HTML（没装 playwright 时降级）

输入 markdown（frontmatter 可选，命令行同名参数优先）:
    ---
    title: 当感受被真正"看见"：什么是有效化
    theme: clean          # clean=白底红黑黑体 / paper=蓝纸衬线
    xhs_id: 49398056290   # 页脚水印小红书号，不给则不画页脚
    ---
    正文段落…
    ## 二级标题
    ### 三级标题
    - 列表项
    **独立成段的加粗句** → 渲染成红色强调句（带下划线）
    | 表头 | … |  → 表格

输出: <out>/P01.png … <out>/PNN.png + <out>/_typeset.html，stdout 一份 JSON。
"""
import argparse
import html as html_mod
import json
import pathlib
import re
import sys

# ── 画布与版心（1440×2400 = 3:5，对齐参考样本实测尺寸）────────────────────────
PAGE_W, PAGE_H = 1440, 2400
PAD_X = 96          # 左右版心留白
PAD_TOP = 104       # 内容区上边距
PAD_BOTTOM = 190    # 下边距（含页脚水印带）

FONT_SANS = ('"Noto Sans SC","Noto Sans CJK SC","Source Han Sans SC","PingFang SC",'
             '"Microsoft YaHei","WenQuanYi Micro Hei",sans-serif')
FONT_SERIF = ('"Noto Serif SC","Noto Serif CJK SC","Source Han Serif SC","Songti SC",'
              '"AR PL UMing CN","SimSun",serif')
FONT_KAI = ('"Noto Serif SC","AR PL UKai CN","Kaiti SC","KaiTi","STKaiti",' + FONT_SERIF)


# ── markdown → 结构化块 ──────────────────────────────────────────────────────
def split_frontmatter(text):
    m = re.match(r'^---\n(.*?)\n---\n?(.*)$', text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        mm = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', line)
        if mm:
            meta[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    return meta, m.group(2)


def inline(text):
    """行内标记 → HTML。只认加粗与行内代码，其余原样（含中英文标点）。"""
    out = html_mod.escape(text)
    out = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', out)
    out = re.sub(r'`(.+?)`', r'<code>\1</code>', out)
    return out


def parse_blocks(body):
    """把正文切成块。返回 [(kind, payload)]，kind ∈ h2/h3/p/hl/ul/table。"""
    blocks, lines, i = [], body.splitlines(), 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue

        if line.startswith('### '):
            blocks.append(('h3', line[4:].strip()))
            i += 1
        elif line.startswith('## '):
            blocks.append(('h2', line[3:].strip()))
            i += 1
        elif line.startswith('# '):
            # 正文里的 H1 当二级标题处理（H1 只由 frontmatter title 提供）
            blocks.append(('h2', line[2:].strip()))
            i += 1
        elif line.startswith('|') and line.endswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-{2,}:?', c) for c in cells):  # 跳过对齐行
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(('table', rows))
        elif re.match(r'^[-*·○]\s+', line):
            items = []
            while i < len(lines) and re.match(r'^\s*[-*·○]\s+', lines[i]):
                items.append(re.sub(r'^\s*[-*·○]\s+', '', lines[i].strip()))
                i += 1
            blocks.append(('ul', items))
        else:
            buf = []
            while i < len(lines) and lines[i].strip() and not re.match(
                    r'^\s*(#{1,3}\s|[-*·○]\s|\|)', lines[i]):
                buf.append(lines[i].strip())
                i += 1
            para = ''.join(buf)
            # 整段加粗 → 红色强调句
            m = re.fullmatch(r'\*\*(.+)\*\*', para)
            blocks.append(('hl', m.group(1)) if m else ('p', para))
    return blocks


def count_chars(blocks):
    """汉字数（估读时长用），只数正文可见文字。"""
    txt = []
    for kind, payload in blocks:
        if kind == 'table':
            txt += [c for row in payload for c in row]
        elif kind == 'ul':
            txt += payload
        else:
            txt.append(payload)
    plain = re.sub(r'[*`]', '', ''.join(txt))
    return len(re.findall(r'[一-鿿]', plain)), len(plain)


# ── 主题 ────────────────────────────────────────────────────────────────────
PAPER_TEXTURE = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'"
    "%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' "
    "numOctaves='3'/%3E%3C/filter%3E%3Crect width='300' height='300' filter='url(%23n)' "
    "opacity='0.22'/%3E%3C/svg%3E\")"
)

THEMES = {
    # 样本 B：白底 + 红黑黑体，段落不缩进、靠空行分段，承载表格与强调句
    'clean': {
        'font': FONT_SANS, 'h1_font': FONT_SANS,
        'bg': '#ffffff', 'texture': 'none', 'fg': '#252525',
        'accent': '#B3282D', 'accent_soft': '#FBE9E7',
        'body_size': 46, 'body_lh': 1.92, 'indent': '0', 'p_gap': 40,
        'h1_size': 76, 'h1_weight': 900, 'h1_lh': 1.34,
        'h2_size': 52, 'h3_size': 44, 'meta_size': 30,
        'topbar': True,
    },
    # 样本 A：淡蓝纸纹 + 衬线，首行缩进两字、段间距小，书法感标题
    'paper': {
        'font': FONT_SERIF, 'h1_font': FONT_KAI,
        'bg': '#D8E1F3', 'texture': PAPER_TEXTURE, 'fg': '#16181d',
        'accent': '#3A4A7A', 'accent_soft': '#C9D5EE',
        'body_size': 48, 'body_lh': 2.0, 'indent': '2em', 'p_gap': 22,
        'h1_size': 88, 'h1_weight': 700, 'h1_lh': 1.5,
        'h2_size': 54, 'h3_size': 46, 'meta_size': 32,
        'topbar': False,
    },
}


def build_html(title, meta_line, blocks, theme_name, xhs_id):
    t = THEMES[theme_name]
    content_h = PAGE_H - PAD_TOP - PAD_BOTTOM
    parts = []

    if title:
        parts.append(f'<h1>{inline(title)}</h1>')
    if meta_line:
        parts.append(f'<div class="meta">{html_mod.escape(meta_line)}</div>')

    for kind, payload in blocks:
        if kind == 'h2':
            parts.append(f'<h2>{inline(payload)}</h2>')
        elif kind == 'h3':
            parts.append(f'<h3>{inline(payload)}</h3>')
        elif kind == 'hl':
            parts.append(f'<p class="hl">{inline(payload)}</p>')
        elif kind == 'ul':
            lis = ''.join(f'<li>{inline(x)}</li>' for x in payload)
            parts.append(f'<ul>{lis}</ul>')
        elif kind == 'table':
            head, body_rows = payload[0], payload[1:]
            th = ''.join(f'<th>{inline(c)}</th>' for c in head)
            trs = ''.join('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in r) + '</tr>'
                          for r in body_rows)
            parts.append(f'<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>')
        else:
            parts.append(f'<p>{inline(payload)}</p>')

    footer = (f'<div class="footer">小红书号 {html_mod.escape(xhs_id)}</div>') if xhs_id else ''
    topbar = '<div class="topbar"></div>' if t['topbar'] else ''

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html_mod.escape(title or '长图')}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#888; }}
  .viewport {{
    position:relative; width:{PAGE_W}px; height:{PAGE_H}px; overflow:hidden;
    background:{t['bg']}; color:{t['fg']};
    font-family:{t['font']}; font-size:{t['body_size']}px; line-height:{t['body_lh']};
    -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
  }}
  .texture {{ position:absolute; inset:0; background-image:{t['texture']}; background-size:300px 300px;
             mix-blend-mode:multiply; opacity:.5; pointer-events:none; }}
  .topbar {{ position:absolute; top:0; left:0; right:0; height:58px; background:{t['accent_soft']}; }}
  /* stage 是版心裁剪窗：高度只到内容区，页脚留白带绝不会被正文侵占 */
  .stage {{ position:absolute; left:{PAD_X}px; top:{PAD_TOP}px;
            width:{PAGE_W - 2 * PAD_X}px; height:{content_h}px; overflow:hidden; }}
  #flow {{ position:absolute; left:0; top:0; width:100%; }}

  h1 {{ font-family:{t['h1_font']}; font-size:{t['h1_size']}px; font-weight:{t['h1_weight']};
        line-height:{t['h1_lh']}; margin:20px 0 34px;
        {"background:" + t['accent_soft'] + "; border-left:10px solid " + t['accent'] + "; padding:18px 26px;" if theme_name == 'clean' else "text-align:left; letter-spacing:.06em;"} }}
  .meta {{ font-size:{t['meta_size']}px; color:#6b6b6b; margin:0 0 46px;
           border-left:6px solid {t['accent']}; padding-left:18px; line-height:1.5; }}
  h2 {{ font-size:{t['h2_size']}px; font-weight:800; line-height:1.5; margin:56px 0 30px;
        border-left:10px solid {t['accent']}; padding-left:26px; }}
  h3 {{ font-size:{t['h3_size']}px; font-weight:500; line-height:1.55; margin:46px 0 26px;
        border-left:6px solid {t['accent']}; padding-left:22px; letter-spacing:.12em; }}
  p {{ margin:0 0 {t['p_gap']}px; text-indent:{t['indent']}; text-align:justify;
       text-justify:inter-ideograph; }}
  p.hl {{ color:{t['accent']}; font-weight:700; text-indent:0;
          border-bottom:4px solid {t['accent']}; padding-bottom:14px; margin-bottom:{t['p_gap'] + 12}px; }}
  ul {{ list-style:none; margin:0 0 {t['p_gap']}px; }}
  li {{ margin:0 0 22px; padding-left:62px; position:relative; text-align:justify; }}
  li::before {{ content:"○"; position:absolute; left:0; top:0; color:{t['accent']}; }}
  b {{ font-weight:800; }}
  code {{ font-family:{FONT_SANS}; font-size:.94em; }}
  table {{ width:100%; border-collapse:collapse; font-size:32px; line-height:1.7;
           margin:12px 0 {t['p_gap'] + 10}px; border-bottom:4px solid {t['accent']}; }}
  th {{ background:#f2f2f2; font-weight:700; text-align:left; padding:18px 20px;
        border-bottom:2px solid #ddd; }}
  td {{ padding:18px 20px; border-bottom:1px solid #e6e6e6; vertical-align:top; }}
  .footer {{ position:absolute; right:{PAD_X}px; bottom:56px; font-size:28px; color:#9a9a9a;
             letter-spacing:.04em; font-family:{FONT_SANS}; }}
</style></head>
<body><div class="viewport" id="vp">{topbar}<div class="texture"></div>
<div class="stage"><div id="flow">{''.join(parts)}</div></div>{footer}</div>
</body></html>"""


# ── 切点测量（浏览器内执行）──────────────────────────────────────────────────
MEASURE_JS = r"""
() => {
  const flow = document.getElementById('flow');
  const base = flow.getBoundingClientRect().top + window.scrollY;
  const cuts = new Set();
  const isTitle = (el) => el && ['H1','H2','H3'].includes(el.tagName);

  // ① 行盒底边 —— 允许段落跨页，但只在行与行之间切
  const walker = document.createTreeWalker(flow, NodeFilter.SHOW_TEXT, null);
  const range = document.createRange();
  let node;
  while ((node = walker.nextNode())) {
    if (!node.textContent.trim()) continue;
    let p = node.parentElement, blocked = false;
    while (p && p !== flow) {                       // 标题内 / 表格内不可切
      if (p.tagName === 'TABLE' || isTitle(p)) { blocked = true; break; }
      p = p.parentElement;
    }
    if (blocked) continue;
    range.selectNodeContents(node);
    for (const r of range.getClientRects()) {
      if (r.height > 0) cuts.add(Math.round(r.bottom + window.scrollY - base));
    }
  }
  // ② 块底边 —— 表格、列表整体的收口位置；标题底边故意不收（防标题孤行留页底）
  flow.querySelectorAll('p,ul,ol,li,table,.meta').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.height > 0) cuts.add(Math.round(r.bottom + window.scrollY - base));
  });

  // ③ 禁切区：标题起点 → 它后面第一行正文的底边。
  //    落进来的切点会造成「标题孤零零留在页底、正文全在下一页」，一律剔除；
  //    结果是要么整个标题挪到下一页，要么至少带一行正文一起留下。
  const firstLineBottom = (el) => {
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
    const rg = document.createRange();
    let n;
    while ((n = w.nextNode())) {
      if (!n.textContent.trim()) continue;
      rg.selectNodeContents(n);
      const rects = rg.getClientRects();
      if (rects.length) return rects[0].bottom + window.scrollY - base;
    }
    return el.getBoundingClientRect().bottom + window.scrollY - base;
  };
  const forbidden = [];
  flow.querySelectorAll('h1,h2,h3').forEach(h => {
    const from = h.getBoundingClientRect().top + window.scrollY - base - 24;
    const next = h.nextElementSibling;
    forbidden.push([from, next ? firstLineBottom(next)
                               : h.getBoundingClientRect().bottom + window.scrollY - base]);
  });

  const total = flow.scrollHeight;
  cuts.add(total);
  const keep = [...cuts].filter(c =>
    c > 0 && (c === total || !forbidden.some(([a, b]) => c > a && c < b)));
  return { cuts: keep.sort((a, b) => a - b), total };
}
"""


def paginate(cuts, total, content_h):
    """贪心切页：每页尽量塞满，切点必须落在行边界。"""
    pages, cur = [], 0
    while cur < total - 2:
        limit = cur + content_h
        cand = [c for c in cuts if cur < c <= limit]
        nxt = max(cand) if cand else limit      # 单块高于一页时才硬切（表格超高等极端情况）
        pages.append((cur, nxt))
        cur = nxt
    return pages


def main():
    ap = argparse.ArgumentParser(description='长文正文 → 文本排版长图（路线②）')
    ap.add_argument('--md', required=True, help='输入 markdown（已去引用、已口语化的正文）')
    ap.add_argument('--out', help='输出目录，默认 <md同级>/images/<md名>/')
    ap.add_argument('--theme', choices=sorted(THEMES), help='主题，默认取 frontmatter，再默认 clean')
    ap.add_argument('--title', help='首页大标题，默认取 frontmatter title')
    ap.add_argument('--xhs-id', help='页脚小红书号，默认取 frontmatter xhs_id；不给则不画页脚')
    ap.add_argument('--no-meta', action='store_true', help='不渲染「全文N字｜阅读需M分钟」副信息行')
    ap.add_argument('--max-pages', type=int, default=30, help='页数安全上限（默认 30）')
    ap.add_argument('--html-only', action='store_true', help='只产 HTML 不截图（无 playwright 时降级）')
    args = ap.parse_args()

    md_path = pathlib.Path(args.md).expanduser()
    if not md_path.exists():
        print(json.dumps({'ok': False, 'error': f'找不到输入文件：{md_path}'}, ensure_ascii=False))
        return 1

    meta, body = split_frontmatter(md_path.read_text(encoding='utf-8'))
    theme = args.theme or meta.get('theme') or 'clean'
    if theme not in THEMES:
        print(json.dumps({'ok': False, 'error': f'未知主题 {theme}，可选：{sorted(THEMES)}'},
                         ensure_ascii=False))
        return 1
    title = args.title or meta.get('title', '')
    xhs_id = args.xhs_id if args.xhs_id is not None else meta.get('xhs_id', '')

    blocks = parse_blocks(body)
    if not blocks:
        print(json.dumps({'ok': False, 'error': '正文为空，没有可排版的内容'}, ensure_ascii=False))
        return 1

    han, total_chars = count_chars(blocks)
    minutes = max(1, round(total_chars / 330))
    meta_line = '' if args.no_meta else f'全文{total_chars}字｜阅读需{minutes}分钟'

    out_dir = pathlib.Path(args.out).expanduser() if args.out else \
        md_path.parent / 'images' / md_path.stem
    out_dir = out_dir.resolve()          # 相对路径转绝对：下面要用 as_uri() 喂浏览器
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = build_html(title, meta_line, blocks, theme, xhs_id)
    html_path = out_dir / '_typeset.html'
    html_path.write_text(doc, encoding='utf-8')

    if args.html_only:
        print(json.dumps({'ok': True, 'html_only': True, 'html': str(html_path),
                          'theme': theme, 'chars': total_chars, 'han': han},
                         ensure_ascii=False))
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(json.dumps({
            'ok': False,
            'error': '没装 playwright，出不了图。已经把排版 HTML 写好了：' + str(html_path),
            'how_to_fix': ['装一次即可：pip install playwright && python3 -m playwright install chromium',
                           '或者先用浏览器打开上面这个 HTML 看排版效果（它就是成图的样子）'],
            'html': str(html_path)}, ensure_ascii=False))
        return 2

    content_h = PAGE_H - PAD_TOP - PAD_BOTTOM
    files = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': PAGE_W, 'height': PAGE_H},
                                device_scale_factor=1)
        page.goto(html_path.as_uri())
        page.wait_for_timeout(300)                    # 等字体落位，否则行盒测量偏移
        measured = page.evaluate(MEASURE_JS)
        pages = paginate(measured['cuts'], measured['total'], content_h)

        if len(pages) > args.max_pages:
            browser.close()
            print(json.dumps({
                'ok': False,
                'error': f'算出 {len(pages)} 页，超过上限 {args.max_pages} 页——正文太长了',
                'how_to_fix': ['把正文拆成两条笔记，或再精简一轮',
                               f'确实要出这么多页就加 --max-pages {len(pages)}'],
                'html': str(html_path)}, ensure_ascii=False))
            return 1

        for idx, (start, end) in enumerate(pages, 1):
            # stage 高度收到本页实际区间：只上移 flow 的话，切点以下的内容
            # 会继续填满版心剩余空间（下一页的标题会露在本页页底）。
            page.evaluate('([top, h]) => { document.getElementById("flow").style.top = top + "px";'
                          ' document.querySelector(".stage").style.height = h + "px"; }',
                          [-start, end - start])
            fp = out_dir / f'P{idx:02d}.png'
            page.screenshot(path=str(fp), clip={'x': 0, 'y': 0, 'width': PAGE_W, 'height': PAGE_H})
            files.append(str(fp))
        browser.close()

    print(json.dumps({
        'ok': True, 'theme': theme, 'pages': len(files), 'files': files,
        'chars': total_chars, 'han': han, 'reading_minutes': minutes,
        'canvas': f'{PAGE_W}x{PAGE_H}', 'out_dir': str(out_dir), 'html': str(html_path),
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

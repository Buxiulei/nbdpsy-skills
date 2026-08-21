#!/usr/bin/env python3
"""把一篇长文正文排版渲染成「文字版」笔记配图（路线②，2026-07-28 老板定案）。

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
    typeset_longimage.py --md body.md --style 文字版.json   # 按运营自己的那套风格档案渲染
    typeset_longimage.py --md body.md --html-only          # 只产 HTML（没装 playwright 时降级）

输入 markdown（frontmatter 可选，命令行同名参数优先）:
    ---
    title: 当感受被真正"看见"：什么是有效化
    theme: clean          # clean=白底红黑黑体 / paper=蓝纸衬线
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
import base64
import html as html_mod
import json
import mimetypes
import pathlib
import re
import subprocess
import sys

# ── 画布与版心（1080×1920 = 9:16 手机全屏）─────────────────────────────────
# 文字版是**全屏阅读**、自己渲染的，不受路线① 那个 2:3 的约束——
# 那是后端 gpt-image 的出图规格，只管 AI 生图。这里按读者的屏幕来。
PAGE_W, PAGE_H = 1080, 1920
PAD_X = 72          # 左右版心留白
PAD_TOP = 78        # 内容区上边距
PAD_BOTTOM = 143    # 下边距（含页脚水印带）
# 首页封面安全边距：小红书 feed 缩略图按 3:4 裁，上下各切掉 (1920-1440)/2 = 240px。
# PAD_TOP 只有 78，标题会被削掉顶部——补到 240 以上，标题才完整出现在 feed 里。
COVER_SAFE_TOP = 168

FONT_SANS = ('"Noto Sans SC","Noto Sans CJK SC","Source Han Sans SC","PingFang SC",'
             '"Microsoft YaHei","WenQuanYi Micro Hei",sans-serif')
FONT_SERIF = ('"Noto Serif SC","Noto Serif CJK SC","Source Han Serif SC","Songti SC",'
              '"AR PL UMing CN","SimSun",serif')
FONT_KAI = ('"Noto Serif SC","AR PL UKai CN","Kaiti SC","KaiTi","STKaiti",' + FONT_SERIF)

# 风格档案里的 font / title_font 只能落在这三条既有字体链上——档案不新造字体链，
# 否则运营写个装不上的字库名，出图会静默掉回系统默认字体，谁也看不出来。
FONT_FAMILIES = {'sans': FONT_SANS, 'serif': FONT_SERIF, 'kai': FONT_KAI}


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


def strip_comments(body):
    """剥掉 HTML 注释；未填的 TODO 占位单独拎出来（split_longform.py 埋的承接段/预告段）。"""
    todos = re.findall(r'<!--\s*(TODO[^>]*?)\s*-->', body, re.S)
    return re.sub(r'<!--.*?-->', '', body, flags=re.S), todos


def fetch_counselor(emp_no, avatar_dir):
    """取咨询师公开资料 + 系统头像（复用 fetch_counselor.py，不另起一套取数口径）。"""
    script = pathlib.Path(__file__).resolve().parent / 'fetch_counselor.py'
    proc = subprocess.run(
        [sys.executable, str(script), '--emp', emp_no, '--avatar-out', str(avatar_dir)],
        capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f'fetch_counselor.py 退出码 {proc.returncode}')
    return json.loads(proc.stdout)


import compliance_core  # noqa: E402  凭证署名段的唯一真源

COVER_SOURCE = "typeset_longimage"
"""本产线在封面凭证里的 `source`。

🔴 **闸门端必须同步**：`publish_note.py` 的 `COVER_SOURCES` 白名单不加这个值，
**落了凭证照样被拒** —— ⚠️ 那是"看起来做了"的典型：产线端有产物、闸门端不认。
⇒ 两端一起改，⛔ 别只做一端。"""


def write_cover_meta(png_path, *, theme, style_profile, page_w, page_h, pages):
    """渲完 **P01（封面）** 落同名 `.meta.json` 凭证。

    🩸 **这条产线此前零凭证** ⇒ 文字版长图的笔记到闸门 A **全会被拒**
    （7/30 前发的三篇是闸门上线前混过去的）。

    ⚠️ 凭证叫 `<产物名>.meta.json` **不叫 `.json`**——`<产物名>.json` 那个位置
    已经被调用方占了（与 `render_cover` 同一口径，⛔ 别另起一套命名）。

    ⚠️ **`style_profile` 可能是 None**（没传档案时）：如实写 `null`，
    ⛔ 不要编一个默认值——**错标比缺失更毒**：缺失会被闸门拒（有声音），
    错标畅通无阻，而**凭证的意义就是溯源，错标＝溯源断**
    （2026-08-21 实证：13 份凭证标了档案库里不存在的组合，一路绿灯到发布前）。
    """
    meta = {
        "source": COVER_SOURCE,
        "style_profile": style_profile,          # ⚠️ 没有就是 null，⛔ 不编默认值
        "theme": theme,
        # ⚠️ created_at/actor 走 shared 的 receipt_stamp——⛔ 三个写入点别各写各的
        **compliance_core.receipt_stamp(),
        "canvas": {"w": page_w, "h": page_h},
        "pages": pages,
        # ⚠️ 这条产线是**确定性渲染**（发布线实测 37 张重渲 byte 级不变）
        # ⇒ 凭证内容全部来自输入，⛔ 没有一项是"跑出来才知道"的
        "deterministic": True,
    }
    out = png_path.with_suffix(".meta.json")
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def scan_promo_compliance(headline, blurb, out_dir):
    """把推介卡的标题与文案落盘再跑 check_compliance.py。

    ⚠️ 这一步不能省：check_compliance.py 只接受**文件路径**，而 headline/blurb 是命令行
    字符串、从不落盘——所以在此之前，全套图里商业风险最高的这段文字（它带 CTA）
    是**完全绕过**违禁词扫描的。落盘顺带留痕，审查端也能复核。
    `--no-crisis`：危机声明按 G6 不在这张卡上（在发布正文里），这里不该要求它。
    """
    draft = out_dir / 'promo-draft.md'
    draft.write_text(f'{headline}\n\n{blurb}\n', encoding='utf-8')
    script = pathlib.Path(__file__).resolve().parent / 'check_compliance.py'
    proc = subprocess.run([sys.executable, str(script), str(draft), '--no-crisis'],
                          capture_output=True, text=True, timeout=60)
    try:
        return json.loads(proc.stdout), draft
    except json.JSONDecodeError:
        return {'ok': False, 'error': (proc.stderr or proc.stdout).strip()}, draft


def data_uri(path):
    mime = mimetypes.guess_type(str(path))[0] or 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(pathlib.Path(path).read_bytes()).decode()


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
        'body_size': 46, 'body_lh': 1.92, 'indent': '0', 'p_gap': 32,
        'h1_size': 92, 'h1_weight': 900, 'h1_lh': 1.3,
        'h2_size': 50, 'h3_size': 42, 'meta_size': 27,
        'card_bg': '#ffffff', 'promo_bg': '#FBF1F0', 'topbar': True,
    },
    # 样本 A：淡蓝纸纹 + 衬线，首行缩进两字、段间距小，书法感标题
    'paper': {
        'font': FONT_SERIF, 'h1_font': FONT_KAI,
        'bg': '#D8E1F3', 'texture': PAPER_TEXTURE, 'fg': '#16181d',
        'accent': '#3A4A7A', 'accent_soft': '#C9D5EE',
        'body_size': 46, 'body_lh': 2.0, 'indent': '2em', 'p_gap': 18,
        'h1_size': 92, 'h1_weight': 700, 'h1_lh': 1.42,
        'h2_size': 50, 'h3_size': 42, 'meta_size': 28,
        'card_bg': 'rgba(255,255,255,.72)', 'promo_bg': '#CDD8EF', 'topbar': False,
    },
}

TEXTURES = {'none': 'none', 'paper': PAPER_TEXTURE}


# ── 风格档案（--style，运营个人档案里 kind:"typeset" 的那一套）────────────────
def load_style(path):
    """读一份 kind:"typeset" 的**单套**风格档案，返回它的 `typeset` 段（没有则空 dict）。

    两种输入形态都收（与 style_profile.py 的 load_profile 同一口径）：单套 JSON 本身，
    或 `style_profile.py --get --kind typeset` 的整份输出（带 exists/profile 外层）。
    """
    data = json.loads(pathlib.Path(path).expanduser().read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path} 不是 JSON 对象，不是一套风格档案')
    if 'exists' in data and isinstance(data.get('profile'), dict):
        data = data['profile']            # 直接喂 --get 整份输出时自动剥出那一套
    if 'profiles' in data:                # 整份多套档案：这里只吃单套，指路怎么取
        raise ValueError('这是整份多套档案（含 profiles），--style 只吃单套；'
                         '先用 style_profile.py --get --kind typeset 取出文字版那一套')
    if data.get('kind') != 'typeset':
        raise ValueError(f'这套档案 kind={data.get("kind")!r}，不是文字版那一套（kind="typeset"）——'
                         '图文那套（carousel）没有排版字段，用它渲染文字版等于没设置')
    ts = data.get('typeset')
    if ts is None:
        return {}
    if not isinstance(ts, dict):
        raise ValueError('档案里的 typeset 段不是对象，读不出排版字段')
    return ts


def style_overrides(typeset):
    """`typeset` 段 → 覆盖到 THEMES[theme] 上的键值。

    **null / 缺省一律不覆盖**（用主题默认值）——档案里的 null 是「这项我没定，听主题的」，
    把 null 写进 CSS 会渲染成字面量 None，整条属性作废。
    """
    over = {}
    for key in ('bg', 'accent', 'accent_soft'):
        val = typeset.get(key)
        if val is None:
            continue
        if not isinstance(val, str) or re.search(r'[;{}]', val):
            raise ValueError(f'{key} 要是一个颜色值，给的是 {val!r}（不能带 ; {{ }}，那会撑破 CSS）')
        over[key] = val
    font = typeset.get('font')
    if font is not None:
        if font not in ('sans', 'serif'):
            raise ValueError(f'font 只能是 sans / serif，给的是 {font!r}')
        over['font'] = FONT_FAMILIES[font]
    title_font = typeset.get('title_font')
    if title_font is not None:
        if title_font not in FONT_FAMILIES:
            raise ValueError(f'title_font 只能是 sans / serif / kai，给的是 {title_font!r}')
        over['h1_font'] = FONT_FAMILIES[title_font]
    indent = typeset.get('indent')
    if indent is not None:
        if not isinstance(indent, bool):
            raise ValueError(f'indent 只能是 true / false，给的是 {indent!r}')
        over['indent'] = '2em' if indent else '0'
    texture = typeset.get('texture')
    if texture is not None:
        if texture not in TEXTURES:
            raise ValueError(f'texture 只能是 none / paper，给的是 {texture!r}')
        over['texture'] = TEXTURES[texture]
    return over


def resolve_theme(cli_theme, typeset, meta):
    """主题优先级：命令行 --theme > 档案 typeset.theme > frontmatter theme > clean。
    档案里 theme 为 null 时**不参与**（继续往下走 frontmatter），与其余字段同一条 null 语义。"""
    return cli_theme or (typeset or {}).get('theme') or meta.get('theme') or 'clean'


#: 每页右下角的页脚水印。固定品牌名——不写小红书号（换号就废、也没必要对外露）。
FOOTER_BRAND = 'NBDpsy心理咨询工作室'

# ⚠️ 推介卡**不渲染危机声明**：G6（xiaohongshu-spec §1.5）要求危机声明与商业 CTA
# 不同页/不同屏，而这张卡上有品牌行与「目前接受预约」这类 CTA。
# 危机声明按 longform-typeset-spec §5 写在**发布正文**里（那里才是它的位置）。


def build_headline(counselor, explicit=''):
    """推介卡主标题，走「三要素」口径（姓名 + 能力 + 来访画像），
    与 references/counselor-note-spec.md §1 的发布标题同一套写法：

        心理咨询师-{姓名}，{陪你/带你 + 能力动词短语（嵌来访画像的困扰词）}
        例：心理咨询师-李宇，陪你整合创伤与秩序

    好标题是内容判断，脚本写不出「整合创伤与秩序」这种动词短语——所以优先用 agent
    按 spec §1 写好后经 --counselor-headline 传进来；不传时才退到下面这个机械兜底
    （拿第一条擅长方向拼「陪你面对X」，合规但平淡，main() 会 warning 提醒）。
    """
    if explicit:
        return explicit.strip()
    name = counselor.get('display_name') or counselor.get('name', '')
    raw = (counselor.get('profile_sections') or {}).get('specialties') \
        or counselor.get('specialties') or []
    first = ''
    if raw:
        head = raw[0]
        first = head.get('title', '') if isinstance(head, dict) else str(head)
    return f'心理咨询师-{name}，陪你面对{first}' if first else f'心理咨询师-{name}'


def check_headline(text):
    """三要素标题的两条硬红线自检（spec §1.1/§1.2）。返回 warning 列表。"""
    warns = []
    if '老师' in text:
        warns.append(f'推介标题里出现「老师」——spec §1.1 红线：直呼其名，不加「老师」：{text}')
    if len(text) > 24:
        warns.append(f'推介标题 {len(text)} 字偏长（发布标题硬限 20 字，卡片上建议 ≤24），'
                     f'排版会折成两行：{text}')
    return warns


def build_promo(counselor, blurb, t, headline=''):
    """末页咨询师推介卡。**与正文同一套排版语言**（同字体、同色系、同版心）——
    这条路线的图全是排版渲染的，末页若混一张 AI 合成图，风格必裂。"""
    if not counselor:
        return ''
    title_txt = html_mod.escape(counselor.get('title') or counselor.get('highlight', ''))
    # 专长在详情里是 profile_sections.specialties（[{title,desc}]）；--list 那边是字符串数组。两种都收。
    raw_tags = (counselor.get('profile_sections') or {}).get('specialties') \
        or counselor.get('specialties') or []
    tags = ' · '.join(html_mod.escape(s['title'] if isinstance(s, dict) else s)
                      for s in raw_tags if (s.get('title') if isinstance(s, dict) else s))
    intro = html_mod.escape(blurb or counselor.get('introduction', ''))
    avatar = f'<img class="avatar" src="{counselor["_avatar_data_uri"]}" alt="">' \
        if counselor.get('_avatar_data_uri') else ''
    head_txt = html_mod.escape(build_headline(counselor, headline))
    return f"""<div class="promo" id="promo"><div class="promo-inner" id="promoInner">
  <div class="promo-card">
    {avatar}
    <div class="promo-name">{head_txt}<span>{title_txt}</span></div>
    <div class="promo-rule"></div>
    {f'<div class="promo-tags">{tags}</div>' if tags else ''}
    <div class="promo-intro">{intro}</div>
  </div>
  <div class="promo-foot">
    <div class="promo-brand">NBDpsy · 咨询师全员北大硕博 · 纯线上心理咨询</div>
  </div>
</div></div>"""


def build_html(title, meta_line, blocks, theme_name, counselor=None, blurb='', headline='',
               theme_over=None):
    # theme_over = 风格档案覆盖的键（--style）；不传时与主题原样等价，行为一字不变
    t = dict(THEMES[theme_name])
    t.update(theme_over or {})
    content_h = PAGE_H - PAD_TOP - PAD_BOTTOM
    parts = []

    # 首页 = 小红书 feed 封面，标题是唯一的视觉焦点。
    # 副信息行放在标题**上方**（对齐运营给的实拍范本）：它是前置元信息，
    # 压在标题下面会把「标题→正文」这一跳打断，标题就不再是绝对主体。
    if meta_line:
        parts.append(f'<div class="meta">{html_mod.escape(meta_line)}</div>')
    if title:
        parts.append(f'<h1>{inline(title)}</h1>')

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

    footer = f'<div class="footer">{FOOTER_BRAND}</div>'
    topbar = '<div class="topbar"></div>' if t['topbar'] else ''

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html_mod.escape(title or '文字版')}</title>
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
  .topbar {{ position:absolute; top:0; left:0; right:0; height:44px; background:{t['accent_soft']}; }}
  /* stage 是版心裁剪窗：高度只到内容区，页脚留白带绝不会被正文侵占 */
  .stage {{ position:absolute; left:{PAD_X}px; top:{PAD_TOP}px;
            width:{PAGE_W - 2 * PAD_X}px; height:{content_h}px; overflow:hidden; }}
  #flow {{ position:absolute; left:0; top:0; width:100%; }}
  /* 首页 = feed 封面，小红书按 3:4 裁 1080×1920（上下各切掉约 240px）。
     只给 flow 的第一个块加顶部安全边距，把标题整体压进安全区——
     它只出现在第一页，后面几页不受影响。 */
  #flow > :first-child {{ margin-top:{COVER_SAFE_TOP}px; }}

  /* 首页标题 = feed 封面主体：大字号 + 下方大留白，正文离得远才显得标题是"主标题" */
  h1 {{ font-family:{t['h1_font']}; font-size:{t['h1_size']}px; font-weight:{t['h1_weight']};
        line-height:{t['h1_lh']}; margin:0 0 84px; letter-spacing:.01em;
        {"border-left:10px solid " + t['accent'] + "; padding:4px 0 8px 26px;" if theme_name == 'clean' else "text-align:left; letter-spacing:.05em;"} }}
  .meta {{ font-size:{t['meta_size']}px; color:#8a8a8a; margin:0 0 26px; padding-bottom:20px;
           border-bottom:2px solid rgba(0,0,0,.08); line-height:1.5; letter-spacing:.02em; }}
  h2 {{ font-size:{t['h2_size']}px; font-weight:800; line-height:1.5; margin:44px 0 24px;
        border-left:8px solid {t['accent']}; padding-left:20px; }}
  h3 {{ font-size:{t['h3_size']}px; font-weight:500; line-height:1.55; margin:36px 0 20px;
        border-left:5px solid {t['accent']}; padding-left:17px; letter-spacing:.12em; }}
  p {{ margin:0 0 {t['p_gap']}px; text-indent:{t['indent']}; text-align:justify;
       text-justify:inter-ideograph; }}
  p.hl {{ color:{t['accent']}; font-weight:700; text-indent:0;
          border-bottom:3px solid {t['accent']}; padding-bottom:11px; margin-bottom:{t['p_gap'] + 12}px; }}
  ul {{ list-style:none; margin:0 0 {t['p_gap']}px; }}
  li {{ margin:0 0 17px; padding-left:48px; position:relative; text-align:justify; }}
  li::before {{ content:"○"; position:absolute; left:0; top:0; color:{t['accent']}; }}
  b {{ font-weight:800; }}
  code {{ font-family:{FONT_SANS}; font-size:.94em; }}
  table {{ width:100%; border-collapse:collapse; font-size:26px; line-height:1.7;
           margin:12px 0 {t['p_gap'] + 10}px; border-bottom:4px solid {t['accent']}; }}
  th {{ background:#f2f2f2; font-weight:700; text-align:left; padding:14px 15px;
        border-bottom:2px solid #ddd; }}
  td {{ padding:14px 15px; border-bottom:1px solid #e6e6e6; vertical-align:top; }}
  .footer {{ position:absolute; right:{PAD_X}px; bottom:42px; font-size:22px; color:#9a9a9a;
             letter-spacing:.04em; font-family:{FONT_SANS}; }}

  /* 末页咨询师推介卡（可选，--counselor）。整页换淡色底 + 白卡，
     既让卡片浮起来，也标示「这一页性质不同」——它不是正文。 */
  .promo {{ display:none; position:absolute; inset:0; background:{t['promo_bg']};
            padding:{PAD_TOP}px {PAD_X}px {PAD_BOTTOM}px; }}
  /* 整页当成一张卡片：全部居中对齐、整组垂直居中。
     之前三种对齐打架（上半居中 + 简介两端对齐 + 页脚贴底），视觉是散的。 */
  .promo-inner {{ display:flex; flex-direction:column; align-items:center; justify-content:center;
                  height:100%; text-align:center; }}
  /* 卡片容器：给这一页一个实体边界。没有它，居中的字块浮在大片留白里显得散 */
  .promo-card {{ background:{t['card_bg']}; border-radius:32px; padding:58px 48px 62px;
                 width:100%; display:flex; flex-direction:column; align-items:center;
                 box-shadow:0 24px 64px rgba(0,0,0,.09); }}
  .avatar {{ width:240px; height:240px; border-radius:50%; object-fit:cover;
             border:6px solid #fff; box-shadow:0 0 0 2px {t['accent_soft']}, 0 18px 44px rgba(0,0,0,.10);
             margin-bottom:38px; }}
  /* 主标题走三要素（姓名+能力+来访画像），比单个姓名长，字号相应收一档、留出折行空间 */
  .promo-name {{ font-size:42px; font-weight:800; line-height:1.5; letter-spacing:.02em;
                 max-width:800px; }}
  .promo-name span {{ display:block; font-size:26px; font-weight:400; color:{t['accent']};
                      margin-top:14px; letter-spacing:.1em; }}
  .promo-rule {{ width:52px; height:3px; background:{t['accent']}; opacity:.55; margin:32px 0; }}
  .promo-tags {{ font-size:25px; color:#8a8a8a; line-height:1.8; letter-spacing:.04em;
                 max-width:760px; }}
  .promo-intro {{ font-size:27px; line-height:2.05; color:#4a4a4a; margin-top:32px;
                  max-width:780px; text-align:justify; text-align-last:center; }}
  .promo-foot {{ margin-top:60px; }}
  .promo-brand {{ font-size:24px; color:{t['accent']}; letter-spacing:.08em; }}
</style></head>
<body><div class="viewport" id="vp">{topbar}<div class="texture"></div>
<div class="stage" id="stage"><div id="flow">{''.join(parts)}</div></div>
{build_promo(counselor, blurb, t, headline)}{footer}</div>
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
    ap = argparse.ArgumentParser(description='长文正文 → 文字版（路线②）')
    ap.add_argument('--md', required=True, help='输入 markdown（已去引用、已口语化的正文）')
    ap.add_argument('--out', help='输出目录，默认 <md同级>/images/<md名>/')
    ap.add_argument('--theme', choices=sorted(THEMES),
                    help='主题，优先级最高；不给则取风格档案，再 frontmatter，再默认 clean')
    ap.add_argument('--style', metavar='PROFILE.JSON',
                    help='运营个人风格档案里 kind="typeset" 的那一套（style_profile.py --get '
                         '--kind typeset 的产物）；其 typeset 段覆盖主题默认值，null 的字段不覆盖')
    ap.add_argument('--title', help='首页大标题，默认取 frontmatter title')
    ap.add_argument('--no-meta', action='store_true', help='不渲染「全文N字｜阅读需M分钟」副信息行')
    ap.add_argument('--counselor', metavar='EMP_NO',
                    help='末页追加一页咨询师推介（可选）；取数与头像复用 fetch_counselor.py')
    ap.add_argument('--counselor-blurb', default='',
                    help='**针对性**推介文案：说明这位咨询师为什么能陪来访解决本文讲的问题'
                         '（不传则退回官网 introduction 通用介绍，会 warning）')
    ap.add_argument('--counselor-headline', default='',
                    help='推介卡主标题，三要素口径「心理咨询师-{姓名}，{陪你+能力动词短语}」，'
                         '结合本文主题写（不传则机械兜底，会 warning）')
    ap.add_argument('--max-pages', type=int, default=30, help='页数安全上限（默认 30）')
    ap.add_argument('--html-only', action='store_true', help='只产 HTML 不截图（无 playwright 时降级）')
    args = ap.parse_args()

    md_path = pathlib.Path(args.md).expanduser()
    if not md_path.exists():
        print(json.dumps({'ok': False, 'error': f'找不到输入文件：{md_path}'}, ensure_ascii=False))
        return 1

    meta, body = split_frontmatter(md_path.read_text(encoding='utf-8'))

    style_typeset, theme_over = {}, {}
    if args.style:
        try:
            style_typeset = load_style(args.style)
            theme_over = style_overrides(style_typeset)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({
                'ok': False, 'error': f'读风格档案 {args.style} 失败：{exc}',
                'how_to_fix': ['取本人的文字版那套：style_profile.py --get --kind typeset > 文字版.json',
                               '字段口径见 references/longform-typeset-spec.md 的 typeset 段']},
                ensure_ascii=False))
            return 1

    theme = resolve_theme(args.theme, style_typeset, meta)
    if theme not in THEMES:
        print(json.dumps({'ok': False, 'error': f'未知主题 {theme}，可选：{sorted(THEMES)}'},
                         ensure_ascii=False))
        return 1
    title = args.title or meta.get('title', '')

    body, todos = strip_comments(body)
    if todos:
        print(json.dumps({
            'ok': False,
            'error': f'正文里还有 {len(todos)} 处没填的 TODO 占位（split_longform.py 埋的承接段/预告段）',
            'todos': todos,
            'how_to_fix': ['把每处 TODO 换成真正的承接段/预告段，并删掉那行 <!-- --> 注释',
                           '系列篇没有承接段，读者不知道这是第几篇、上一篇讲了什么']},
            ensure_ascii=False))
        return 1

    blocks = parse_blocks(body)
    if not blocks:
        print(json.dumps({'ok': False, 'error': '正文为空，没有可排版的内容'}, ensure_ascii=False))
        return 1

    han, total_chars = count_chars(blocks)
    minutes = max(1, round(total_chars / 330))
    series = ''
    if meta.get('series_index') and meta.get('series_total'):
        series = f'｜系列 {meta["series_index"]}/{meta["series_total"]}'
    meta_line = '' if args.no_meta else f'全文{total_chars}字｜阅读需{minutes}分钟{series}'

    out_dir = pathlib.Path(args.out).expanduser() if args.out else \
        md_path.parent / 'images' / md_path.stem
    out_dir = out_dir.resolve()          # 相对路径转绝对：下面要用 as_uri() 喂浏览器
    out_dir.mkdir(parents=True, exist_ok=True)

    counselor = None
    if args.counselor:
        try:
            counselor = fetch_counselor(args.counselor, out_dir)
            counselor['_avatar_data_uri'] = data_uri(counselor['avatar_local_path'])
        except Exception as exc:                       # 取数/头像失败绝不静默出一套没末页的图
            print(json.dumps({
                'ok': False, 'error': f'取咨询师 {args.counselor} 的资料或头像失败：{exc}',
                'how_to_fix': ['确认工号对得上（fetch_counselor.py --list 查）',
                               '后台没头像就先补头像，或本篇不做推介末页（去掉 --counselor）']},
                ensure_ascii=False))
            return 1

        # 停单的人不做推介：引来了约不上，体验最差（counselor-note-spec §6.2 同口径）
        if not counselor.get('is_accepting'):
            print(json.dumps({
                'ok': False,
                'error': f'{counselor.get("display_name") or args.counselor} 当前停止接单'
                         f'（is_accepting=false），不给他做推介末页',
                'how_to_fix': ['换一位在接单的咨询师（fetch_counselor.py --list 看 is_accepting）',
                               '或本篇不挂推介末页（去掉 --counselor）']},
                ensure_ascii=False))
            return 1

        # 推介文案带 CTA，是全套图里商业风险最高的一段——出图前必须过违禁词扫描
        verdict, draft_path = scan_promo_compliance(
            build_headline(counselor, args.counselor_headline),
            args.counselor_blurb or counselor.get('introduction', ''), out_dir)
        if not verdict.get('ok'):
            print(json.dumps({
                'ok': False,
                'error': '推介卡的标题/文案没过合规扫描',
                'compliance': verdict,
                'draft': str(draft_path),
                'how_to_fix': ['按 violations 改掉命中的词，再重跑',
                               '替换口径见 references/xiaohongshu-spec.md 的禁用词替换表']},
                ensure_ascii=False))
            return 1

    doc = build_html(title, meta_line, blocks, theme, counselor,
                     args.counselor_blurb, args.counselor_headline, theme_over)
    html_path = out_dir / '_typeset.html'
    html_path.write_text(doc, encoding='utf-8')

    if args.html_only:
        # ⚠️ 这条降级路径**不产出正文页与推介页的任何闸门结果**（不跑 warnings、
        # 不跑推介卡溢出检查），所以它不能用来验收推介页——挂了 --counselor 就得走完整出图。
        print(json.dumps({'ok': True, 'html_only': True, 'html': str(html_path),
                          'theme': theme, 'style': args.style,
                          'chars': total_chars, 'han': han,
                          'note': ('--html-only 不跑 warnings 与推介卡溢出检查，'
                                   '不能拿它的 ok=true 当推介页验收依据') if args.counselor else None},
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
            if idx == 1:
                # ⚠️ 套名从**档案本身**取（`load_style` 的产物），⛔ 不另编一个来源：
                #    两个来源迟早漂，而凭证漂了就是错标——比缺失更毒。
                #    档案没传时是 None ⇒ 凭证里如实写 null。
                _sp = (style_typeset or {}).get("name") or (style_typeset or {}).get("profile")
                write_cover_meta(fp, theme=theme, style_profile=_sp,
                                 page_w=PAGE_W, page_h=PAGE_H, pages=len(pages))

        if counselor:                                  # 末页推介：藏正文、显推介卡，再截一张
            overflow = page.evaluate("""() => {
              document.getElementById('stage').style.display = 'none';
              const p = document.getElementById('promo');
              p.style.display = 'block';
              const inner = document.getElementById('promoInner');
              return inner.scrollHeight - inner.clientHeight;   // >0 = 放不下，会被裁
            }""")
            if overflow > 0:
                browser.close()
                print(json.dumps({
                    'ok': False,
                    'error': f'推介卡内容超出一页 {overflow}px，硬出会被裁掉一截',
                    'how_to_fix': [f'传 --counselor-blurb 用一段更短的推介文案覆盖官网 introduction'
                                   f'（当前 {len(args.counselor_blurb or counselor.get("introduction", ""))} 字，'
                                   f'建议 ≤200 字）'],
                    'html': str(html_path)}, ensure_ascii=False))
                return 1
            fp = out_dir / f'P{len(pages) + 1:02d}.png'
            page.screenshot(path=str(fp), clip={'x': 0, 'y': 0, 'width': PAGE_W, 'height': PAGE_H})
            files.append(str(fp))
        browser.close()

    warnings = []
    if counselor:
        head = build_headline(counselor, args.counselor_headline)
        warnings += check_headline(head)
        if not args.counselor_headline:
            warnings.append('推介标题用的是机械兜底，没有结合本文主题——老板要的是**针对性推介**：'
                            '按 counselor-note-spec §1 三要素写一个，用 --counselor-headline 传进来')
        if not args.counselor_blurb:
            warnings.append('推介文案用的是官网通用 introduction，没说明「他为什么能陪来访解决本文这类问题」——'
                            '按 longform-typeset-spec §8 写一段针对性文案，用 --counselor-blurb 传进来')

    print(json.dumps({
        'ok': True, 'theme': theme, 'style': args.style, 'pages': len(files), 'files': files,
        'warnings': warnings,
        'chars': total_chars, 'han': han, 'reading_minutes': minutes,
        'series': series.lstrip('｜') or None,
        'counselor_page': bool(counselor),
        'counselor': (counselor.get('display_name') if counselor else None),
        'canvas': f'{PAGE_W}x{PAGE_H}', 'out_dir': str(out_dir), 'html': str(html_path),
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

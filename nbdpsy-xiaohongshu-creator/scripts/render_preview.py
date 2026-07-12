#!/usr/bin/env python3
"""把拆分产物（00-overview.md + post-*.md）渲染成一个自包含的预览页 HTML。
设计意图（按用户反馈）：区分两类内容——
  · 给人看的（发布文案 / 每页页面文字）→ 暖纸感、衬线、舒适排版，标签做成 pill；
  · 复制给 AI 的绘图提示词 → 深色等宽代码面板「保持原样」，每段带一键复制按钮。
用法: render_preview.py <输出目录> [输出html路径=<输出目录>/<目录名>-preview.html]
输出默认按内容命名（{目录名}-preview.html），不同笔记组的预览页不重名。
零外部依赖（纯标准库），生成单文件 HTML，本地双击即看。
"""
import sys, re, html, pathlib, json

def split_frontmatter(text):
    m = re.match(r'^---\n(.*?)\n---\n(.*)$', text, re.S)
    return (m.group(1), m.group(2)) if m else ('', text)

def parse_fm(fm):
    meta = {}
    mt = re.search(r'^title:\s*(.+)$', fm, re.M);     meta['title'] = mt.group(1).strip() if mt else ''
    mo = re.search(r'^topic:\s*(.+)$', fm, re.M);     meta['topic'] = mo.group(1).strip() if mo else ''
    mi = re.search(r'^post_index:\s*(\d+)', fm, re.M);  meta['idx'] = mi.group(1) if mi else ''
    mh = re.search(r'^hashtags:\s*\[(.*?)\]', fm, re.S)
    meta['tags'] = [t.strip() for t in mh.group(1).split(',')] if mh else []
    mp = re.search(r'^source_pillar:\s*(.+)$', fm, re.M); meta['pillar'] = mp.group(1).strip() if mp else ''
    return meta

def section(body, header_re):
    lines, grab, buf = body.splitlines(), False, []
    for ln in lines:
        if re.match(header_re, ln): grab = True; continue
        if grab and re.match(r'^## ', ln): break
        if grab: buf.append(ln)
    return '\n'.join(buf).strip('\n')

def md_inline(s):
    s = html.escape(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    return s

def render_caption(cap_raw):
    """把发布文案渲染成可读 UI；返回 (html, raw_for_copy)。"""
    blocks = re.split(r'\n\s*\n', cap_raw.strip())
    out = []
    for b in blocks:
        b = b.strip()
        if not b: continue
        if re.match(r'^#\S', b):                                   # 可见标签行 → pills
            tags = re.findall(r'#[^\s#]+', b)
            pills = ''.join(f'<span class="tag">{html.escape(t)}</span>' for t in tags)
            out.append(f'<div class="tags">{pills}</div>')
        elif b.startswith('（') or '12356' in b:                    # 危机声明 → 提示条
            out.append(f'<p class="disclaimer">{md_inline(b)}</p>')
        else:
            out.append('<p>' + md_inline(b).replace('\n', '<br>') + '</p>')
    return '\n'.join(out), cap_raw.strip()

def parse_pages(car):
    lines = car.splitlines()
    note = ''
    idxs = [j for j, ln in enumerate(lines) if ln.startswith('### ')]
    # 轮播区开头的引用说明
    head = lines[:idxs[0]] if idxs else lines
    note = ' '.join(ln.lstrip('> ').strip() for ln in head if ln.strip().startswith('>'))
    pages = []
    for k, start in enumerate(idxs):
        end = idxs[k+1] if k+1 < len(idxs) else len(lines)
        block = lines[start:end]
        title = block[0][4:].strip()
        human, prompt, infence, seen = [], [], False, False
        for ln in block[1:]:
            if ln.strip().startswith('```'):
                infence = not infence; seen = True if infence else seen; continue
            if infence: prompt.append(ln)
            elif not seen:
                if '绘图提示词' in ln: continue          # 丢掉标签行，自己有面板标题
                human.append(ln)
        pages.append({'title': title, 'human': human, 'prompt': '\n'.join(prompt).strip()})
    return note, pages

def render_human(lines):
    out, in_ul = [], False
    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            if in_ul: out.append('</ul>'); in_ul = False
            continue
        if s.lstrip().startswith('- '):
            if not in_ul: out.append('<ul class="pagetext">'); in_ul = True
            item = s.lstrip()[2:]
            if '：' in item:
                k, v = item.split('：', 1)
                out.append(f'<li><b>{md_inline(k)}：</b>{md_inline(v)}</li>')
            else:
                out.append(f'<li>{md_inline(item)}</li>')
        elif s.strip().startswith('**页面文字**'):
            continue
        else:
            if in_ul: out.append('</ul>'); in_ul = False
            out.append(f'<p>{md_inline(s)}</p>')
    if in_ul: out.append('</ul>')
    return '\n'.join(out)

CSS = """
:root{--paper:#FAF7F2;--card:#FFFFFF;--ink:#2E3A43;--muted:#6B7884;--brand:#5A6B7B;
--sage:#C9D6CE;--mist:#A8B5C4;--sand:#E8D8C4;--line:#ECE5DA;--code:#2E3A43;--code-ink:#E9ECEF;}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font-family:Raleway,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.75;}
.wrap{max-width:880px;margin:0 auto;padding:40px 20px 80px;}
h1{font-family:Lora,Georgia,serif;font-weight:700;font-size:1.9rem;color:var(--brand);margin:0 0 6px;}
.sub{color:var(--muted);margin:0 0 24px;font-size:.95rem;}
.legend{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 30px;font-size:.85rem;}
.legend span{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:999px;border:1px solid var(--line);background:var(--card);}
.dot{width:10px;height:10px;border-radius:3px;display:inline-block;}
.dot.read{background:var(--sand);} .dot.ai{background:var(--code);}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 34px;}
.toc a{font-size:.85rem;text-decoration:none;color:var(--brand);border:1px solid var(--line);
background:var(--card);padding:6px 12px;border-radius:8px;transition:background .2s,border-color .2s;}
.toc a:hover{background:var(--sage);border-color:var(--sage);}
.post{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:26px;margin:0 0 30px;
box-shadow:0 1px 2px rgba(46,58,67,.04);scroll-margin-top:20px;}
.phead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 4px;}
.pnum{font-family:Lora,serif;font-weight:700;color:var(--mist);font-size:1.05rem;}
.ptitle{font-family:Lora,serif;font-weight:600;font-size:1.3rem;color:var(--ink);margin:0;}
.ptopic{margin-left:auto;font-size:.78rem;color:var(--muted);background:var(--paper);
border:1px solid var(--line);padding:3px 10px;border-radius:999px;}
.label{display:flex;align-items:center;gap:8px;font-size:.8rem;font-weight:600;letter-spacing:.02em;
color:var(--muted);text-transform:none;margin:22px 0 10px;}
.label .bar{width:3px;height:14px;border-radius:2px;background:var(--sand);}
.label.ai .bar{background:var(--mist);}
.read-panel{background:#FCFAF6;border:1px solid var(--line);border-radius:12px;padding:18px 20px;position:relative;}
.read-panel p{margin:0 0 12px;font-size:1.02rem;}
.read-panel p:last-child{margin-bottom:0;}
.disclaimer{font-size:.82rem!important;color:var(--muted);background:#F3EFE8;border-radius:8px;padding:8px 12px;}
.tags{display:flex;flex-wrap:wrap;gap:7px;margin-top:6px;}
.tag{font-size:.82rem;color:var(--brand);background:#EAF0EC;border:1px solid #DBE5DE;padding:3px 10px;border-radius:999px;}
.page{border-top:1px dashed var(--line);padding-top:16px;margin-top:16px;}
.page:first-of-type{border-top:none;}
.ptitle-sm{font-weight:600;color:var(--brand);margin:0 0 8px;font-size:1rem;}
ul.pagetext{margin:0 0 12px;padding-left:20px;}
ul.pagetext li{margin:2px 0;}
.code-wrap{position:relative;}
pre.prompt{background:var(--code);color:var(--code-ink);border-radius:12px;padding:16px 18px;margin:0;
font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:.86rem;line-height:1.65;
white-space:pre-wrap;word-break:break-word;overflow-x:auto;}
button.copy{position:absolute;top:10px;right:10px;border:none;cursor:pointer;border-radius:8px;
font-size:.8rem;font-weight:600;padding:8px 12px;min-height:34px;transition:background .2s,transform .1s;
background:rgba(255,255,255,.14);color:#fff;}
button.copy:hover{background:rgba(255,255,255,.26);}
button.copy:active{transform:scale(.96);}
button.copy.ok{background:#7FA98C;color:#fff;}
button.copy:focus-visible{outline:2px solid var(--mist);outline-offset:2px;}
.cap-copy{position:static;display:inline-flex;align-items:center;gap:6px;margin-left:auto;
background:var(--brand);color:#fff;}
.cap-copy:hover{background:#4a5a69;}
.cap-copy.ok{background:#7FA98C;}
.label.read{justify-content:flex-start;}
.label-row{display:flex;align-items:center;gap:8px;margin:22px 0 10px;}
.label-row .bar{width:3px;height:14px;border-radius:2px;background:var(--sand);}
.label-row .txt{font-size:.8rem;font-weight:600;color:var(--muted);}
svg.ic{width:14px;height:14px;vertical-align:-2px;}
.ratio-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--card);
border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:0 0 24px;}
.ratio-bar .lbl{font-size:.85rem;font-weight:600;color:var(--brand);}
.ratio-btns{display:inline-flex;background:var(--paper);border:1px solid var(--line);border-radius:999px;padding:3px;}
.ratio-btn{border:none;background:transparent;cursor:pointer;border-radius:999px;padding:6px 14px;
font-size:.82rem;font-weight:600;color:var(--muted);transition:background .2s,color .2s;}
.ratio-btn:hover{color:var(--brand);}
.ratio-btn.on{background:var(--brand);color:#fff;}
.ratio-btn:focus-visible{outline:2px solid var(--mist);outline-offset:2px;}
#ratio-hint{font-size:.8rem;color:var(--muted);margin-left:auto;}
@media (prefers-reduced-motion:reduce){*{transition:none!important;}}
@media (max-width:560px){.wrap{padding:24px 14px 60px;}.post{padding:18px;}
#ratio-hint{margin-left:0;width:100%;}}
"""

JS = """
function flash(btn){var o=btn.dataset.label||btn.textContent;btn.dataset.label=o;
btn.textContent='已复制 ✓';btn.classList.add('ok');
setTimeout(function(){btn.textContent=o;btn.classList.remove('ok');},1500);}
function fallback(text,btn){var ta=document.createElement('textarea');ta.value=text;
ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.focus();ta.select();
try{document.execCommand('copy');flash(btn);}catch(e){alert('复制失败，请手动选择文本');}
document.body.removeChild(ta);}
function copyText(text,btn){if(navigator.clipboard&&navigator.clipboard.writeText){
navigator.clipboard.writeText(text).then(function(){flash(btn);}).catch(function(){fallback(text,btn);});}
else{fallback(text,btn);}}
function copyEl(id,btn){copyText(document.getElementById(id).textContent,btn);}
function copyVal(id,btn){copyText(document.getElementById(id).value,btn);}

/* ---- 出图比例一键切换（小红书 3:4 ↔ Instagram 1:1）----
   只改提示词里的「比例参数」句：背景层/文字层/元素层三层组件原样复用，
   一套素材跨平台产出。复制按钮复制的永远是当前所选比例的版本。 */
var RATIO_RULES = {
  '1:1': [
    /竖版\\s*3:4\\s*构图（1080×1440）[^\\n]*/g,
    '正方形 1:1 构图（1080×1080），主体居中，四周留匀称空白；标题压在上 1/4 区、副标题紧随其下，整体比竖版更紧凑。负面提示：不要竖版长图、不要横版/宽幅、不要裁切文字、不要额外边框或水印。'
  ]
};
function applyRatio(r){
  document.querySelectorAll('pre.prompt').forEach(function(pre){
    var src = pre.dataset.src || pre.textContent;
    if(!pre.dataset.src) pre.dataset.src = src;
    if(r === '1:1'){
      var out = src.replace(RATIO_RULES['1:1'][0], RATIO_RULES['1:1'][1]);
      /* 兜底：提示词没写标准比例句时，末尾追加一行，绝不静默出错比例的图 */
      if(out === src && !/1:1/.test(src)) out = src.replace(/\\s*$/, '') + '\\n画幅：正方形 1:1 构图（1080×1080），主体居中，四周留匀称空白。';
      pre.textContent = out;
    } else {
      pre.textContent = src;   /* 3:4 = 原文 */
    }
  });
  document.querySelectorAll('.ratio-btn').forEach(function(b){
    b.classList.toggle('on', b.dataset.ratio === r);
  });
  var hint = document.getElementById('ratio-hint');
  if(hint) hint.textContent = (r === '1:1')
    ? 'Instagram 1:1（1080×1080）· 方形更矮，副标题请压到 ≤14 字、内容页信息点收到 4–7 个'
    : '小红书 3:4（1080×1440）· 默认，显示面积最大、点击率最高';
  try{ localStorage.setItem('nbdpsy_ratio', r); }catch(e){}
}
window.addEventListener('DOMContentLoaded', function(){
  var saved = ' ';
  try{ saved = localStorage.getItem('nbdpsy_ratio') || '3:4'; }catch(e){ saved = '3:4'; }
  applyRatio(saved === '1:1' ? '1:1' : '3:4');
});
"""

CLIP_SVG = ('<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/>'
            '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>')

def default_out_html(outdir: pathlib.Path) -> pathlib.Path:
    """按内容命名：{目录名}-preview.html，避免所有预览页都叫同一个名字。"""
    return outdir / f"{outdir.name}-preview.html"


def main():
    outdir = pathlib.Path(sys.argv[1]).resolve()
    out_html = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else default_out_html(outdir)
    posts = sorted(p for p in outdir.glob('post-*.md'))
    if not posts:
        print('未找到 post-*.md，先生成拆分产物'); sys.exit(1)

    cards, toc, pillar = [], [], ''
    for p in posts:
        fm, body = split_frontmatter(p.read_text(encoding='utf-8'))
        meta = parse_fm(fm)
        if not pillar: pillar = meta.get('pillar', '')
        cap = section(body, r'^##\s*(发布文案|正文)')
        cap_html, cap_raw = render_caption(cap)
        car = section(body, r'^##\s*配图轮播')
        note, pages = parse_pages(car)
        anchor = f'post{meta["idx"] or p.stem}'
        toc.append(f'<a href="#{anchor}">{html.escape(meta["idx"])} {html.escape(meta["title"])}</a>')

        cap_id = f'cap-{anchor}'
        pages_html = []
        for j, pg in enumerate(pages, 1):
            pid = f'pr-{anchor}-{j}'
            pages_html.append(f'''
      <div class="page">
        <div class="ptitle-sm">{html.escape(pg["title"])}</div>
        {render_human(pg["human"])}
        <div class="label-row ai"><span class="bar" style="background:var(--mist)"></span>
          <span class="txt">绘图提示词 · 复制给 Gemini / GPT</span></div>
        <div class="code-wrap">
          <button class="copy" data-label="复制" onclick="copyEl('{pid}',this)">复制</button>
          <pre class="prompt" id="{pid}">{html.escape(pg["prompt"])}</pre>
        </div>
      </div>''')

        note_html = f'<p class="sub" style="margin:0 0 14px">{html.escape(note)}</p>' if note else ''
        cards.append(f'''
    <section class="post" id="{anchor}">
      <div class="phead">
        <span class="pnum">{html.escape(meta["idx"])}</span>
        <h2 class="ptitle">{html.escape(meta["title"])}</h2>
        {f'<span class="ptopic">{html.escape(meta["topic"])}</span>' if meta["topic"] else ''}
      </div>

      <div class="label-row read">
        <span class="bar"></span><span class="txt">发布文案 · 复制这段发小红书</span>
        <button class="copy cap-copy" data-label="复制文案" onclick="copyVal('{cap_id}',this)">{CLIP_SVG} 复制文案</button>
      </div>
      <textarea id="{cap_id}" hidden>{html.escape(cap_raw)}</textarea>
      <div class="read-panel">{cap_html}</div>

      <div class="label-row"><span class="bar" style="background:var(--mist)"></span>
        <span class="txt">配图轮播 · {len(pages)} 页（每页提示词喂图保持风格一致）</span></div>
      {note_html}
      {''.join(pages_html)}
    </section>''')

    label = pillar or (outdir.parent.name if outdir.name == "outputs" else outdir.name)
    title = f'小红书拆分预览 · {label}'
    doc = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<style>@import url('https://fonts.googleapis.com/css2?family=Lora:wght@500;600;700&family=Raleway:wght@300;400;500;600&display=swap');
{CSS}</style></head>
<body><div class="wrap">
  <h1>{html.escape(title)}</h1>
  <p class="sub">共 {len(posts)} 篇。<b>发布文案</b>整段复制粘进小红书；<b>绘图提示词</b>每段一键复制喂给 Gemini/GPT 出图（首图当封面）。</p>
  <div class="ratio-bar">
    <span class="lbl">出图比例</span>
    <span class="ratio-btns">
      <button class="ratio-btn on" data-ratio="3:4" onclick="applyRatio('3:4')">小红书 3:4</button>
      <button class="ratio-btn" data-ratio="1:1" onclick="applyRatio('1:1')">Instagram 1:1</button>
    </span>
    <span id="ratio-hint">小红书 3:4（1080×1440）· 默认，显示面积最大、点击率最高</span>
  </div>
  <div class="legend">
    <span><i class="dot read"></i> 给人看 · 发布文案 / 页面文字</span>
    <span><i class="dot ai"></i> 复制给 AI · 绘图提示词（切换比例后复制的就是该比例版本）</span>
  </div>
  <div class="toc">{''.join(toc)}</div>
  {''.join(cards)}
</div>
<script>{JS}</script>
</body></html>'''
    out_html.write_text(doc, encoding='utf-8')
    print(f'✓ 预览页已生成: {out_html}  ({len(posts)} 篇)')

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""把 <workdir>/shots.json 渲染成自包含的「分镜确认页」HTML，给运营查看每镜脚本、
一键复制生图提示词、核对参考图回传状态。

用法:
  render_storyboard.py --workdir DIR [--attach-images DIR] [--out HTML]

- 默认输出 <workdir>/<workdir目录名>-storyboard.html（按内容命名，绝不重名）。
- --attach-images DIR：把目录里的 P{页号}.png/jpg/jpeg（P1/P01 均可，大小写不敏感）
  按页号写回 shots.json 每镜的 image 字段（绝对路径），其余字段原样保留，然后再渲染。
- 每镜的「生图提示词」优先取 image_prompt 字段（精修时从笔记「视频参考图提示词」节填入，
  去文字版），没有则回退 prompt 字段并标注。
- 契约：stdout=纯 JSON，stderr=进度；shots 为空 exit 1；shots.json 缺失 exit 2。
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

CSS = """
:root{--paper:#FAF7F2;--card:#FFFFFF;--ink:#2E3A43;--muted:#6B7884;--brand:#5A6B7B;
--sage:#C9D6CE;--mist:#A8B5C4;--sand:#E8D8C4;--line:#ECE5DA;--code:#2E3A43;--code-ink:#E9ECEF;}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.75;}
.wrap{max-width:880px;margin:0 auto;padding:40px 20px 80px;}
h1{font-weight:700;font-size:1.7rem;color:var(--brand);margin:0 0 6px;}
.sub{color:var(--muted);margin:0 0 20px;font-size:.95rem;}
.howto{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px 20px;margin:0 0 28px;font-size:.92rem;}
.howto b{color:var(--brand);}
.shot{background:var(--card);border:1px solid var(--line);border-radius:16px;
padding:22px 24px;margin:0 0 24px;box-shadow:0 1px 2px rgba(46,58,67,.04);}
.shead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 10px;}
.snum{font-weight:700;color:var(--mist);font-size:1.1rem;}
.sdur{font-size:.82rem;color:var(--muted);}
.badge{margin-left:auto;font-size:.76rem;padding:3px 10px;border-radius:999px;border:1px solid var(--line);}
.badge.img{background:#EAF0EC;color:#3E6249;} .badge.txt{background:#F3EFE8;color:var(--brand);}
.badge.miss{background:#F6E8E4;color:#9A5140;}
.label{font-size:.8rem;font-weight:600;color:var(--muted);margin:14px 0 6px;}
.narr{background:#FCFAF6;border:1px solid var(--line);border-radius:10px;padding:12px 16px;font-size:.98rem;}
.subline{font-size:.9rem;color:var(--muted);}
.code-wrap{position:relative;}
pre.prompt{background:var(--code);color:var(--code-ink);border-radius:12px;padding:14px 16px;margin:0;
font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.86rem;line-height:1.6;
white-space:pre-wrap;word-break:break-word;}
button.copy{position:absolute;top:8px;right:8px;border:none;cursor:pointer;border-radius:8px;
font-size:.8rem;font-weight:600;padding:7px 12px;background:rgba(255,255,255,.14);color:#fff;}
button.copy:hover{background:rgba(255,255,255,.26);}
button.copy.ok{background:#7FA98C;}
.imgstate{font-size:.88rem;margin-top:8px;}
.imgstate.ok{color:#3E6249;} .imgstate.miss{color:#9A5140;}
@media (max-width:560px){.wrap{padding:24px 14px 60px;}.shot{padding:16px;}}
"""

JS = """
function flash(b){var o=b.dataset.l||b.textContent;b.dataset.l=o;b.textContent='已复制 ✓';
b.classList.add('ok');setTimeout(function(){b.textContent=o;b.classList.remove('ok');},1500);}
function fb(t,b){var a=document.createElement('textarea');a.value=t;a.style.position='fixed';
a.style.opacity='0';document.body.appendChild(a);a.select();
try{document.execCommand('copy');flash(b);}catch(e){alert('复制失败，请手动选择文本');}
document.body.removeChild(a);}
function copyEl(id,b){var t=document.getElementById(id).textContent;
if(navigator.clipboard&&navigator.clipboard.writeText){
navigator.clipboard.writeText(t).then(function(){flash(b);}).catch(function(){fb(t,b);});}else{fb(t,b);}}
"""

IMG_EXTS = (".png", ".jpg", ".jpeg")


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def find_page_image(images_dir: Path, page: int):
    """按页号找 P{n}/P{0n}.{png,jpg,jpeg}（大小写不敏感），与 parse_note 同语义。"""
    if not images_dir.is_dir():
        return None
    pat = re.compile(rf"^p0*{page}\.(png|jpg|jpeg)$", re.I)
    for f in sorted(images_dir.iterdir()):
        if f.is_file() and pat.match(f.name):
            return f.resolve()
    return None


def attach_images(shots_data: dict, images_dir: Path):
    """把参考图按页号写回每镜 image 字段（原地，其余字段不动）。返回 attach 数。"""
    n = 0
    for shot in shots_data.get("shots", []):
        page = shot.get("page") or shot.get("index")
        try:
            page = int(page)
        except (TypeError, ValueError):
            _err(f"警告：镜 {shot.get('index')} 的 page 字段无法转换为整数（{page!r}），跳过参考图匹配")
            continue
        img = find_page_image(images_dir, page)
        if img is not None:
            shot["image"] = str(img)
            n += 1
    return n


def render(shots_data: dict, workdir: Path) -> str:
    title = shots_data.get("video", {}).get("title") or workdir.name
    shots = shots_data.get("shots", [])
    cards = []
    for shot in shots:
        idx = int(shot.get("index", 0))
        page_raw = shot.get("page") or idx
        try:
            page = int(page_raw)
        except (TypeError, ValueError):
            _err(f"警告：镜 {idx} 的 page 字段无法转换为整数（{page_raw!r}），回退用 index={idx}")
            page = idx
        dur = shot.get("duration")
        dur_txt = f"{dur}s" if dur else "时长待定（旁白合成后写回）"
        image = shot.get("image")
        img_prompt = shot.get("image_prompt")
        prompt = img_prompt or shot.get("prompt") or ""
        prompt_label = "生图提示词（去文字版，复制去生成参考图）" if img_prompt else \
            "提示词（原视频 prompt——如走图生请先在精修时补 image_prompt 去文字版）"
        mode = '<span class="badge img">图生（有参考图）</span>' if image else \
            '<span class="badge txt">待定：文生 / 等参考图</span>'
        if image:
            img_state = f'<div class="imgstate ok">✓ 参考图已就位：{html.escape(Path(image).name)}</div>'
        else:
            img_state = (f'<div class="imgstate miss">参考图待回传：生成后命名 '
                         f'<b>P{page:02d}.png</b> 两位数（写成 <b>P{page}.png</b> 也认）放进 '
                         f'<code>{html.escape(str(workdir / "images"))}</code></div>')
        pid = f"prompt-{idx:02d}"
        cards.append(f"""
<section class="shot" id="shot-{idx:02d}">
  <div class="shead"><span class="snum">镜 {idx:02d}</span>
    <span class="sdur">页 P{page} · {html.escape(dur_txt)}</span>{mode}</div>
  <div class="label">旁白脚本（成片配音就念这段）</div>
  <div class="narr">{html.escape(shot.get("narration_text") or "（待精修）")}</div>
  <div class="label">字幕</div>
  <div class="subline">{html.escape(shot.get("subtitle") or "（跟随旁白逐句）")}</div>
  <div class="label">{html.escape(prompt_label)}</div>
  <div class="code-wrap"><pre class="prompt" id="{pid}">{html.escape(prompt)}</pre>
    <button class="copy" onclick="copyEl('{pid}',this)">复制</button></div>
  {img_state}
</section>""")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · 分镜确认页</title><style>{CSS}</style></head><body>
<div class="wrap">
<h1>{html.escape(title)}</h1>
<p class="sub">分镜确认页 · 共 {len(shots)} 镜 · 目录 {html.escape(str(workdir))}</p>
<div class="howto"><b>怎么用：</b>逐镜检查「旁白脚本」是否顺口；需要参考图的镜，点「复制」把提示词
粘给 Gemini/GPT 生成 <b>9:16 竖版图</b>，下载后按每镜标注的页号命名成 <b>P01.png 两位数（写成 P1.png 也认）</b>，放进上面目录的
<code>images/</code> 文件夹；全部放好后回复 AI「图片好了」。</div>
{''.join(cards)}
</div><script>{JS}</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--attach-images", dest="attach_dir", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    workdir = Path(a.workdir).resolve()
    shots_path = workdir / "shots.json"
    if not shots_path.is_file():
        print(json.dumps({"error": f"文件不存在: {shots_path}"}, ensure_ascii=False))
        _err(f"shots.json 不存在：{shots_path}")
        sys.exit(2)
    shots_data = json.loads(shots_path.read_text(encoding="utf-8"))
    if not shots_data.get("shots"):
        print(json.dumps({"error": "shots 为空，无可渲染分镜"}, ensure_ascii=False))
        _err("shots 为空")
        sys.exit(1)

    attached = 0
    if a.attach_dir:
        attached = attach_images(shots_data, Path(a.attach_dir).resolve())
        shots_path.write_text(json.dumps(shots_data, ensure_ascii=False, indent=2), encoding="utf-8")
        _err(f"参考图写回 {attached} 镜 → shots.json")

    out = Path(a.out) if a.out else workdir / f"{workdir.name}-storyboard.html"
    out.write_text(render(shots_data, workdir), encoding="utf-8")
    _err(f"分镜确认页已写入 {out}")
    print(json.dumps({"html": str(out), "shots": len(shots_data["shots"]), "attached": attached},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

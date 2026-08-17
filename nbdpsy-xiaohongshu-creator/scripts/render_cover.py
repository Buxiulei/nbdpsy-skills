#!/usr/bin/env python3
"""把一份封面文案 JSON 渲染成封面 PNG（确定性排版，⛔ 不走 AI 生图）。

为什么有这个脚本（2026-08-17 立）：封面被连否三轮，返工成本全烧在
「改一句文案 → 重新 AI 生成整张图」上——版式会漂、字会错、还要烧出图额度。
HTML 渲染治的就是这个病：**改文案 = 改 JSON，版式分毫不动、秒出、零额度。**

截图范式复用 typeset_longimage.py：Playwright 起 chromium，viewport 就是画布尺寸，
page.screenshot(clip=…) 精确出尺寸；没装 playwright 时 --html-only 降级只产 HTML。

用法:
    render_cover.py --data cover.json
    render_cover.py --data cover.json --out P01.png
    render_cover.py --data cover.json --html-only        # 没装 playwright 时降级
    # 公众号静物封面（2.35:1 横版、图内零文字）：
    render_cover.py --data gzh-cover.json --canvas 2.35:1 --template still-life --out cover.jpg

两套版式共用这一个脚本，**版式逻辑相反**（见 fuwuhao-operator/references/gzh-illustration-spec.md §2.2）：
    · jinjin（小红书，竖版 876×1313）——封面靠图上的大标题抓人，文案就是主体；
    · still-life（公众号，横版 2.35:1）——**图内零文字**，标题由微信自己渲染压在封面旁边，
      图里再写一遍就是两份标题打架，且信息流里封面缩得很小、字根本看不清。
      所以 still-life 模板**没有文字槽位**，⛔ 这不是「可选参数」。

cover.json（jinjin 版式；字段全部可改，版式不动）:
    {
      "hero":  ["「我这点事"],                          // 只放最扎心的短句，1–2 行
      "subtitle": "还没到要看心理咨询吧」",              // 副题层，= hero × 0.34；可空
      "steps": ["第一行…", "第二行…", "第三行（自动渲成赭红箭头结论行）"],
      "avatar": "photo/avatar-EMP20260109003.jpg",     // 相对本 JSON 所在目录
      "identity": {"name": "刘琼", "line": "本文作者 · 北大临床心理硕士"},
      "ornament": "plant-support",                     // 见模板 ORN 库；或 ornament_svg 给外部文件
      "footer": "NBDpsy 心理科普",
      "canvas": {"w": 876, "h": 1313},                 // 可选
      "theme":  {"hero_min": 56, "step_floor": 22}     // 可选，覆盖调色板与档位闸门
    }

gzh-cover.json（still-life 版式；⛔ 没有任何文字字段）:
    {
      "template": "still-life",
      "icons": ["headphones", "coffee", "sprout"],  // 必须是 assets/svg-library/ 里的文件名
      "accent": "cord",                             // 赭红只落一处：cord=耳机线，或直接写某个 icon 名
      "baseline": true,                             // 画桌面基线（让静物成组而非散落）
      "bg": "warm-paper"                            // 暖米白纸质底
    }

输出:
    <out>.png|.jpg      成图（格式认 --out 的扩展名，收 .png / .jpg / .jpeg）
    <out>.thumb220.*    缩略图（验收用，跟成图同格式）
    <out>.html          排版 HTML（就是成图的样子，可直接用浏览器打开）
    <out>.meta.json     **产出凭证**：输入数据、解析到的模板路径、画布与比例、
                        每张图标的解析来源路径、四角像素采样、校验结论
    stdout              一份 JSON（最后一行），量具与 warnings 都在里面
    ⚠️ 凭证叫 `.meta.json` 不叫 `.json`：`<产物名>.json` 那个位置**已经被调用方占了**
    （gen_gzh_images.py 把喂进来的数据写在 cover.jpg ↔ cover.json），写那儿等于覆盖别人的输入。

出图后的机器校验（比例 ±1% + 四角白边）是**默认行为**，⛔ 没有关掉它的开关。

退出码（三态，⛔ 别只判 0/非 0 就完事）:
    0  成功，且校验全过
    1  **图产出来了，但不合格**——比例超差、四角有白边、图标缺失、画面里有文字等，
       成图与凭证都在盘上，可以直接看图定位问题
    2  参数/环境错误，**压根没出图**——模板不存在、JSON 解析失败、没装 playwright、
       图标名不在素材库、--canvas 写法不认识
"""
import argparse
import base64
import json
import mimetypes
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
TPL_DIR = HERE.parent / 'assets' / 'cover-templates'
SVG_LIB = HERE.parent / 'assets' / 'svg-library'
DEFAULT_TPL = TPL_DIR / 'tpl-cover-jinjin.html'

# 模板别名 → 文件；文件名 stem → 版式 kind。--template 两种写法都收（别名或路径）。
TEMPLATES = {
    'jinjin': TPL_DIR / 'tpl-cover-jinjin.html',
    'still-life': TPL_DIR / 'tpl-gzh-stilllife.html',
}
KIND_BY_STEM = {'tpl-cover-jinjin': 'jinjin', 'tpl-gzh-stilllife': 'still-life'}
# 画布默认值：小红书竖版 876×1313；公众号横版 1313×559（＝ round(1313/2.35)，
# 绝对像素随出图后端实际宽度走，验收看比例不看绝对数字）
KIND_CANVAS = {'jinjin': (876, 1313), 'still-life': (1313, 559)}
# 字体落位探针选择器：零文字的 still-life 也得有个带中文字形的节点可问（它在画布外）
KIND_FONT_SEL = {'jinjin': '.hero .l', 'still-life': '#font-probe'}
# 报告阶段会硬取的 fit 字段。模板版本对不上时**提前报明白**，别等到 KeyError 抛出来
# （见下方版本校验：未接住的异常会把退出码搅成 1，与「出图了但不合格」混为一谈）。
FIT_KEYS = {
    'jinjin': ('hero_fs', 'hero_lines', 'sub_fs', 'step_fs', 'name_fs', 'role_fs',
               'overflow_px', 'safe_3x4_ok', 'crop_3x4'),
    'still-life': ('icons', 'gaps', 'group_ink_w', 'margin_left', 'margin_right', 'margin_top',
                   'baseline_y', 'baseline_drawn', 'baseline_align_dev_px', 'desk_w',
                   'desk_overhang_px', 'accent', 'accent_form', 'accent_spots', 'accent_options',
                   'accent_unknown', 'bg_unknown', 'bg_known', 'cord', 'overlap', 'min_gap',
                   'out_of_canvas', 'margin_asym_px', 'text_in_canvas'),
}


def die(msg, **extra):
    print(json.dumps({'ok': False, 'error': msg, **extra}, ensure_ascii=False))
    return 2


def data_uri(path: pathlib.Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


# 落位字体必须是 Source Han Sans 这一族（Noto Sans SC / Noto Sans CJK SC /
# Source Han Sans SC / PingFang SC 互为同源，字宽一致）。掉到文泉驿或
# Droid fallback 上字宽就变了，线性求解会解出另一个字号、整幅版式静默漂移。
EXPECTED_FONTS = ('Noto Sans SC', 'Noto Sans CJK SC', 'Source Han Sans SC', 'PingFang SC')


def check_fields(data: dict):
    """缺字段以前是静默留白（首版实测缺头像空出 19.3% 版面，零警告）——一律报红。"""
    red = []
    hero = [s for s in (data.get('hero') or []) if str(s).strip()]
    if len(hero) > 2:
        red.append(f'🔴 hero 有 {len(hero)} 行——这个版式规定两行封顶，'
                   f'长句请降到 subtitle 副题层（方案 1），别硬塞进 hero')
    if not str(data.get('avatar') or '').strip():
        red.append('🔴 缺 avatar：头像是这个版式的第 ④ 层，缺了右下角空一大片（首版实测 19.3% 版面）')
    idn = data.get('identity') or {}
    for k, what in (('name', '姓名'), ('line', '身份行')):
        if not str(idn.get(k) or '').strip():
            red.append(f'🔴 缺 identity.{k}（{what}）：头像旁会只剩半边，封面认不出作者是谁')
    if not str(data.get('footer') or '').strip():
        red.append('🔴 缺 footer：底部落款是品牌位，缺了这版式就不成立')
    return red


def platform_fonts(page, selector: str):
    """问 CDP 要**实际落位**的字体族。

    ⛔ 不能用 document.fonts.check()：Chromium 里它对任何名字都返回 true
    （2026-08-17 实测，连 'Totally Fake Font XYZ' 都是 true），拿它当闸门＝恒绿的假闸门。
    CSS.getPlatformFontsForNode 报的是真正拿去光栅化的字体，才是可证伪的判据。
    """
    cdp = page.context.new_cdp_session(page)
    cdp.send('DOM.enable')
    cdp.send('CSS.enable')
    root = cdp.send('DOM.getDocument')['root']['nodeId']
    node = cdp.send('DOM.querySelector', {'nodeId': root, 'selector': selector})['nodeId']
    if not node:
        return []
    fonts = cdp.send('CSS.getPlatformFontsForNode', {'nodeId': node})['fonts']
    return [f['familyName'] for f in sorted(fonts, key=lambda f: -f['glyphCount'])]


def resolve_assets(data: dict, base: pathlib.Path):
    """头像与外部陪衬 SVG 内联进 HTML —— 出图不依赖相对路径，HTML 单文件可搬走。"""
    missing = []
    av = data.get('avatar')
    if av and not str(av).startswith('data:'):
        p = pathlib.Path(av)
        if not p.is_absolute():
            p = base / p
        if p.exists():
            data['avatar'] = data_uri(p)
        else:
            missing.append(f'头像找不到：{p}')
            data['avatar'] = None
    svg = data.get('ornament_svg')
    if svg:
        p = pathlib.Path(svg)
        if not p.is_absolute():
            p = base / p
        if p.exists():
            data['ornament_svg_inline'] = p.read_text(encoding='utf-8')
        else:
            missing.append(f'陪衬 SVG 找不到：{p}')
    return missing


def looks_like_path(value: str) -> bool:
    """`still-life` 是名字，`/x/y.html` 或 `tpl-a.html` 是路径。分清楚才能给对错误提示：
    名字解析不到要列出可用模板名，路径解析不到要报路径。"""
    return '/' in value or value.endswith('.html')


def resolve_template(value: str):
    """--template 收两种写法：别名（jinjin / still-life）或模板文件路径。

    版式 kind 优先认模板自己声明的 <meta name="cover-kind">——⛔ 别靠文件名猜，
    模板被复制改名后文件名就不作数了（KIND_BY_STEM 只是老模板没这行时的兜底）。
    """
    path = TEMPLATES[value] if value in TEMPLATES else pathlib.Path(value).resolve()
    kind = KIND_BY_STEM.get(path.stem, 'jinjin')
    if path.exists():
        m = re.search(r'<meta\s+name=["\']cover-kind["\']\s+content=["\']([\w-]+)["\']',
                      path.read_text(encoding='utf-8')[:4096])
        if m and m.group(1) in KIND_CANVAS:
            kind = m.group(1)
    return path, kind


def parse_canvas(spec: str, base_w: int):
    """--canvas 收 `1313x559` 或 `2.35:1`。给比例时按 round(w / 比例) 算高。

    返回 (w, h, 比例)；比例为 None 表示是直接给的绝对像素。
    """
    s = str(spec).strip().lower()
    m = re.fullmatch(r'(\d+)\s*[x×]\s*(\d+)', s)
    if m:
        return int(m.group(1)), int(m.group(2)), None
    m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)', s)
    if m:
        num, den = float(m.group(1)), float(m.group(2))
        if num <= 0 or den <= 0:
            raise ValueError(f'--canvas 比例不能是 0 或负数：{spec}')
        ratio = num / den
        return base_w, round(base_w / ratio), ratio
    raise ValueError(f'--canvas 看不懂：{spec}（收 `1313x559` 这样的绝对像素，或 `2.35:1` 这样的比例）')


def icon_names():
    return sorted(p.stem for p in SVG_LIB.glob('*.svg'))


def load_icons(data: dict):
    """把 icons 里点名的 SVG 从素材库读出来内联进数据。

    ⛔ 不在库里就报红并列出可选名，**不静默跳过**——静默跳过的后果是版式照画、
    只是少一件静物，验收时谁也看不出来少了什么。
    """
    names = [str(n).strip() for n in (data.get('icons') or []) if str(n).strip()]
    known = icon_names()
    inline, unknown, sources = {}, [], {}
    for n in names:
        # `lucide:headphones` 这种带前缀的写法是从图标站复制来的，库里是裸文件名
        bare = n.split(':', 1)[1] if ':' in n else n
        p = SVG_LIB / f'{bare}.svg'
        if bare != n or not p.exists():
            unknown.append(n)
            continue
        # <!-- 许可证注释 --> 留在 <script type="application/json"> 里会撞上 HTML 的
        # script-data-escaped 解析状态，先剥掉；素材出处的台账真源是 LICENSES.md
        inline[n] = re.sub(r'<!--[\s\S]*?-->', '', p.read_text(encoding='utf-8')).strip()
        sources[n] = str(p)          # 凭证里要写清每个图标**从哪个文件读来的**
    data['icons'] = names
    data['icons_svg'] = inline
    return unknown, known, sources


def verify_image(path: pathlib.Path, target_ratio: float):
    """出图后的机器校验：**默认跑，⛔ 不做可选**。

    a) 宽高比 ≈ 目标（±1%）；b) 四角像素判白边（sum(rgb) > 740 即疑似白边）。
    PIL 缺席时**报红**而不是跳过——量不出来的绿是假绿。
    """
    try:
        from PIL import Image
    except ImportError:
        return {'ran': False, 'reason': '没装 Pillow，比例与白边量不出来（pip install Pillow）'}
    im = Image.open(path).convert('RGB')
    w, h = im.size
    ratio = w / h
    dev = abs(ratio - target_ratio) / target_ratio
    pad = 8
    corners = {}
    for tag, box in (('tl', (0, 0, pad, pad)), ('tr', (w - pad, 0, w, pad)),
                     ('bl', (0, h - pad, pad, h)), ('br', (w - pad, h - pad, w, h))):
        px = list(im.crop(box).getdata())
        mean = [round(sum(c[i] for c in px) / len(px), 1) for i in range(3)]
        corners[tag] = {'rgb': mean, 'sum': round(sum(mean), 1)}
    white = [t for t, v in corners.items() if v['sum'] > 740]
    return {
        'ran': True, 'size': f'{w}x{h}', 'ratio': round(ratio, 4),
        'target_ratio': round(target_ratio, 4), 'ratio_dev_pct': round(dev * 100, 3),
        'ratio_ok': dev <= 0.01, 'corners': corners, 'white_corners': white,
    }


def build_html(tpl: str, data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False)
    # </script> 会提前关掉承载数据的那个标签，必须打断
    blob = blob.replace('</', '<\\/')
    return tpl.replace('__COVER_DATA__', blob)


SUFFIX_FORMAT = {'.png': 'png', '.jpg': 'jpeg', '.jpeg': 'jpeg'}


def flatten_for_jpeg(im, bg=(255, 255, 255)):
    """JPEG 没有 alpha 通道。直接 `.convert('RGB')` 会把透明像素算成**黑色**，
    整张图糊上一层黑底——先拿白底合成掉 alpha 再转，⛔ 别图省事直接 convert。"""
    from PIL import Image
    if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
        rgba = im.convert('RGBA')
        canvas = Image.new('RGB', rgba.size, bg)
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return im.convert('RGB')


def make_thumb(src: pathlib.Path, width: int, fmt: str) -> str:
    """缩略图验收是封面的唯一硬闸——顺手产出来，⛔ 别让人"回头再缩一张看看"。
    格式跟成图走：成图是 .jpg，缩略图也是 .jpg（否则验收看的和发出去的不是一种编码）。"""
    try:
        from PIL import Image
    except ImportError:
        return ''
    im = Image.open(src)
    small = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    out = src.with_suffix(f'.thumb{width}{src.suffix}')
    if fmt == 'jpeg':
        flatten_for_jpeg(small).save(out, 'JPEG', quality=92)
    else:
        small.save(out, 'PNG')
    return str(out)


def write_receipt(path: pathlib.Path, payload: dict):
    """产出凭证：出问题时能**不重跑就定位**。

    ⚠️ 落在 `<产物名>.meta.json`，⛔ 不是 `<产物名>.json`——后者是调用方
    （gen_gzh_images.py）写输入数据的位置（cover.jpg ↔ cover.json），
    写那儿等于把别人喂进来的数据覆盖掉。
    """
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)


def report_still_life(fit, check, landed, warnings, out, thumb, html_path,
                      receipt, receipt_path, W, H):
    """静物式封面的闸门与量具。

    红灯 → **退出码 1**（图产出来了但不合格），⛔ 别让 ok=true 混过验收。
    与「退出码 2＝压根没出图」分开，是为了让调用方一眼分清「去看图」还是「去改参数」。
    """
    if landed and landed[0] not in EXPECTED_FONTS:
        warnings.append(f"🔴 字体没落在预期字族上：实际拿去光栅化的是 {landed[0]}（全部命中：{landed}），"
                        f"预期 {list(EXPECTED_FONTS)} 之一。本版式图内虽零文字，但渲染脚本与小红书那套共用，"
                        f"字体没装好那边会静默漂版式——先装（apt install fonts-noto-cjk）再出图")
    if fit['text_in_canvas']:
        warnings.append(f"🔴 画面里有文字：{fit['text_in_canvas']}——公众号封面的标题由微信自己渲染压在旁边，"
                        f"图里再写就是两份标题打架（gzh-illustration-spec §2.2）")
    if fit['bg_unknown']:
        warnings.append(f"🔴 背景 `{fit['bg_unknown']}` 不在模板底纹库里，已退回 warm-paper。"
                        f"可选：{fit['bg_known']}")
    if fit['accent_unknown']:
        warnings.append(f"🔴 accent `{fit['accent_unknown']}` 既不是 cord、也不是这几件静物之一，"
                        f"**赭红一处都没落**。可选：{fit['accent_options']}")
    elif fit['accent_spots'] != 1:
        warnings.append(f"🔴 赭红落了 {fit['accent_spots']} 处（规格：有且只有一处）")
    if fit['cord'] and not fit['cord']['drawn']:
        warnings.append(f"🔴 耳机线没画出来：{fit['cord']['reason']}")
    if fit['cord'] and fit['cord'].get('degenerate'):
        warnings.append(f"🔴 耳机线两端落差只有 {fit['cord']['drop_px']}px，曲线会摊成一条平线——"
                        f"把主角换成明显更大的那件，或改用「accent 指名某件图标」的形态")
    if fit['overlap']:
        warnings.append(f"🔴 静物之间有重叠（最小间距 {fit['min_gap']}px）——图标太多或画布太窄")
    if fit['out_of_canvas']:
        warnings.append(f"🔴 有静物落到画布外（组左 {fit['group_ink_left']}、组右 {fit['group_ink_right']}、"
                        f"顶 {fit['margin_top']}，画布 {W}x{H}）——减一件或换更小的图标")
    if fit['baseline_align_dev_px'] > 1:
        warnings.append(f"🔴 有静物没压在基线上（最大偏差 {fit['baseline_align_dev_px']}px）")
    if fit['margin_asym_px'] > 2:
        warnings.append(f"🔴 左右留白不均：左 {fit['margin_left']} / 右 {fit['margin_right']}，"
                        f"差 {fit['margin_asym_px']}px")
    if fit['desk_overhang_px'] > 0:
        warnings.append(f"⚠️ 两头的静物各悬出桌沿 {fit['desk_overhang_px']}px（基线 {fit['desk_w']}px "
                        f"短于图标组 {fit['group_ink_w']}px）——静物件数太多，减一两件")
    if fit['margin_top'] < 0.08 * H:
        warnings.append(f"⚠️ 顶部只剩 {fit['margin_top']}px 留白（< 画面高 8%），静物顶到天花板了")

    red = [w for w in warnings if w.startswith('🔴')]
    # ⛔ `ok` 不许在闸门红着的时候说 true。调用方普遍写 `if payload["ok"]`，
    # 一个恒 True 的 ok 会把红灯渲染当成功交出去——退出码 1 拦得住脚本调用方，
    # 拦不住只读 JSON 的那种（本仓「恒绿的假闸门」同族）。两个字段同源，留 gates_ok 是为可读性。
    receipt['gates_ok'] = not red
    receipt['warnings'] = warnings
    receipt['exit_code'] = 1 if red else 0
    print(json.dumps({
        'ok': not red,
        'gates_ok': not red,
        'kind': 'still-life',
        'image': str(out), 'thumb': thumb, 'html': str(html_path),
        'receipt': write_receipt(receipt_path, receipt),
        'canvas': f'{W}x{H}',
        'verify': check,
        'font_landed': landed,
        'icons': fit['icons'],
        'gaps': fit['gaps'],
        'group_ink_w': fit['group_ink_w'],
        'margin_left': fit['margin_left'], 'margin_right': fit['margin_right'],
        'margin_top': fit['margin_top'],
        'baseline_y': fit['baseline_y'], 'baseline_drawn': fit['baseline_drawn'],
        'baseline_align_dev_px': fit['baseline_align_dev_px'],
        'desk_w': fit['desk_w'], 'desk_overhang_px': fit['desk_overhang_px'],
        'accent': fit['accent'], 'accent_form': fit['accent_form'], 'cord': fit['cord'],
        'text_in_canvas': fit['text_in_canvas'],
        'zero_text_criterion': '模板无文字槽位 + 渲染后扫画布内文本节点/SVG <text>/伪元素 content，'
                               '三类全空才算零文字（字体探针在画布外、不计入）',
        'warnings': warnings,
    }, ensure_ascii=False))
    return 1 if red else 0


def main():
    ap = argparse.ArgumentParser(description='封面 JSON → 封面 PNG（确定性排版渲染）')
    ap.add_argument('--data', required=True, help='封面文案 JSON')
    ap.add_argument('--out', help='输出路径，**格式认扩展名**（.png / .jpg / .jpeg），'
                                  '默认 <data 同级>/<data 名>.png')
    ap.add_argument('--template',
                    help=f'模板：别名 {"/".join(TEMPLATES)} 或模板 HTML 路径。'
                         f'不给时认数据里的 template 字段，再没有才回落 tpl-cover-jinjin.html')
    ap.add_argument('--canvas', help='画布：`1313x559` 绝对像素，或 `2.35:1` 比例（比例时高按 round(宽/比例) 算）')
    ap.add_argument('--thumb', type=int, default=220, help='顺带产的缩略图宽度（0=不产），默认 220')
    ap.add_argument('--html-only', action='store_true', help='只产 HTML 不截图（没装 playwright 时降级）')
    args = ap.parse_args()

    dpath = pathlib.Path(args.data).resolve()
    if not dpath.exists():
        return die(f'封面数据文件不存在：{dpath}')
    try:
        data = json.loads(dpath.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        return die(f'封面数据不是合法 JSON：{e}')

    # 数据契约里就写着 template 字段，命令行不给时认它——⛔ 别让两边打架时静默按命令行走：
    # 数据说 still-life 却渲成 jinjin，报出来的是「hero 是空的」，谁也想不到是模板选错了
    want = str(data.get('template') or '').strip()
    picked = args.template or want or str(DEFAULT_TPL)
    tpl_path, kind = resolve_template(picked)
    # ⚠️ 先判「有没有这个模板」，再判「两边打不打架」。反过来的话，`--template stilllife`
    # 这种拼错的名字会先被判成 jinjin 再报「与数据里的 still-life 对不上」，
    # 把人往错误方向引——真正的毛病是压根没有叫 stilllife 的模板。
    if not tpl_path.exists():
        # ⛔ 绝不静默回落到默认模板：那样会让人拿到一张构图完全不同的图却以为成功了
        if not looks_like_path(picked):
            return die(f'没有叫 `{picked}` 的模板——⛔ 不会替你回落到默认模板',
                       templates=sorted(TEMPLATES), template_dir=str(TPL_DIR))
        return die(f'模板文件不存在：{tpl_path}', templates=sorted(TEMPLATES))
    if args.template and want and kind != KIND_BY_STEM.get(want, want):
        return die(f'--template 选的是 `{kind}` 版式，数据里却写着 template="{want}"——'
                   f'两边对不上，先定哪个对再跑')

    icon_sources = {}
    if kind == 'still-life':
        unknown, known, icon_sources = load_icons(data)
        if unknown:
            return die(f'这些图标不在素材库里：{unknown}——⛔ 不会静默跳过，请改成库里的名字'
                       f'（裸文件名，⛔ 别带 lucide: 前缀）',
                       icons_available=known, svg_library=str(SVG_LIB))
        if not data['icons']:
            return die('icons 是空的——静物式封面的主体就是这些图标，没图标就不是这个版式',
                       icons_available=known)
        warnings = []
    else:
        if not data.get('hero'):
            return die('hero 是空的——这个版式的第一层就是通栏大字，没大字就不是这个版式')
        warnings = check_fields(data) + resolve_assets(data, dpath.parent)

    dw, dh = KIND_CANVAS[kind]
    canvas = data.get('canvas') or {}
    W, H = int(canvas.get('w', dw)), int(canvas.get('h', dh))
    ratio_spec = None
    if args.canvas:
        try:
            W, H, ratio_spec = parse_canvas(args.canvas, W)
        except ValueError as e:
            return die(str(e))
    data['canvas'] = {'w': W, 'h': H}
    target_ratio = ratio_spec if ratio_spec else W / H

    out_png = pathlib.Path(args.out).resolve() if args.out else dpath.with_suffix('.png')
    # 扩展名必须给且必须认识。⚠️ 不给扩展名**从来就没能用过**（playwright 自己会抛
    # "Unsupported screenshot mime type"，traceback 出去、退出码还撞上 1），
    # 所以这里报错不是变严，是把一个本来就会崩的入口改成说人话的 2。
    fmt = SUFFIX_FORMAT.get(out_png.suffix.lower())
    if not fmt:
        return die(f'--out 的扩展名 `{out_png.suffix or "(没写)"}` 不支持——格式是按扩展名定的',
                   supported=sorted(SUFFIX_FORMAT))
    receipt_path = out_png.with_suffix('.meta.json')
    if receipt_path == dpath:
        # 凭证写到输入数据头上＝把喂进来的数据抹掉，且不可恢复
        return die(f'产出凭证会写到 {receipt_path}，正好是 --data 那个文件——换个 --out 名字，'
                   f'⛔ 不会覆盖你的输入数据')
    out_png.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_png.with_suffix('.html')
    html_path.write_text(build_html(tpl_path.read_text(encoding='utf-8'), data), encoding='utf-8')

    if args.html_only:
        print(json.dumps({
            'ok': True, 'html_only': True, 'html': str(html_path),
            'warnings': warnings,
            'note': '--html-only 不出图也不跑自适应量具，⛔ 不能拿它的 ok=true 当封面验收依据',
        }, ensure_ascii=False))
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return die('没装 playwright，出不了图。排版 HTML 已经写好：' + str(html_path),
                   how_to_fix=['装一次即可：pip install playwright && python3 -m playwright install chromium',
                               '或者先用浏览器打开上面这个 HTML 看效果（它就是成图的样子）'],
                   html=str(html_path))

    # 直接让 Chromium 编码 JPEG：截图源本来就是不透明的，不经 PIL 的 RGBA→RGB 也就没有黑底风险
    shot = {'clip': {'x': 0, 'y': 0, 'width': W, 'height': H}}
    if fmt == 'jpeg':
        shot.update(type='jpeg', quality=92)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': W, 'height': H}, device_scale_factor=1)
        page.goto(html_path.as_uri())
        page.wait_for_timeout(250)                      # 等字体落位，否则测量偏移
        page.evaluate('document.fonts.ready')
        fit = page.evaluate('window.__fit()')
        if not fit.get('ok'):
            browser.close()
            return die('模板里的自适应引擎没跑起来：' + str(fit.get('error')), html=str(html_path))
        # 模板与脚本必须是同一版：脚本按固定 key 读 fit，模板老一版就会在报告阶段
        # 抛 KeyError——那是个**没被接住的异常**，退出码会撞上「1＝出图了但不合格」，
        # 把版本不同步伪装成质量不合格。⚠️ 这不是假想：真源与安装副本本来就会漂。
        missing = [k for k in FIT_KEYS[kind] if k not in fit]
        if missing:
            browser.close()
            return die(f'模板与脚本版本对不上：`{tpl_path.name}` 没交回 {missing} 这些量具字段——'
                       f'把模板更新到与本脚本同一版（多半是安装副本还是旧的）',
                       template=str(tpl_path))
        landed = platform_fonts(page, KIND_FONT_SEL[kind])
        page.wait_for_timeout(60)
        page.screenshot(path=str(out_png), **shot)
        browser.close()

    thumb = make_thumb(out_png, args.thumb, fmt) if args.thumb else ''
    check = verify_image(out_png, target_ratio)

    # —— 出图后的机器校验（默认跑，⛔ 不做可选）——
    if not check['ran']:
        warnings.append(f"🔴 出图校验没跑起来：{check['reason']}——量不出来的绿是假绿，⛔ 别当验收通过")
    else:
        if not check['ratio_ok']:
            warnings.append(f"🔴 宽高比 {check['ratio']} 偏离目标 {check['target_ratio']} 达 "
                            f"{check['ratio_dev_pct']}%（闸门 ±1%）")
        if check['white_corners']:
            det = '；'.join(f"{t}={check['corners'][t]['rgb']}" for t in check['white_corners'])
            warnings.append(f"🔴 四角疑似白边：{check['white_corners']}（{det}，判据 sum(rgb)>740）——"
                            f"html 与 body **都**要写死目标像素并都铺背景，只设一个就会漏出白底")

    # —— 产出凭证：出问题时不重跑就能定位 ——
    # icons_svg 是内联进去的整段 SVG 源码，几十 KB 且看不出信息，剔掉；
    # 图标真正要留痕的是**从哪个文件读来的**（icons_resolved），一眼看出走没走本地库。
    receipt = {
        'schema': 'render_cover/receipt@1',
        'kind': kind,
        'input': {
            'data_file': str(dpath),
            'data': {k: v for k, v in data.items() if k != 'icons_svg'},
            'argv': {'template': args.template, 'canvas': args.canvas, 'out': args.out},
        },
        'template': {'path': str(tpl_path), 'kind': kind,
                     'alias': args.template if args.template in TEMPLATES else None},
        'canvas': {'w': W, 'h': H, 'ratio': round(W / H, 4),
                   'target_ratio': round(target_ratio, 4),
                   'ratio_spec': args.canvas if ratio_spec else None},
        'icons_resolved': icon_sources,
        'svg_library': str(SVG_LIB) if icon_sources else None,
        'outputs': {'image': str(out_png), 'format': fmt,
                    'thumb': thumb or None, 'html': str(html_path)},
        'verify': check,
        'font_landed': landed,
        'fit': fit,
    }

    if kind == 'still-life':
        return report_still_life(fit, check, landed, warnings, out_png, thumb, html_path,
                                 receipt, receipt_path, W, H)

    # —— 闸门：能量出来的坏消息一律显式报，⛔ 不让它静默混过验收 ——
    if landed and landed[0] not in EXPECTED_FONTS:
        warnings.append(f"🔴 字体没落在预期字族上：实际拿去光栅化的是 {landed[0]}（全部命中：{landed}），"
                        f"预期 {list(EXPECTED_FONTS)} 之一。字宽一变，hero 的线性求解会解出**另一个字号**、"
                        f"整幅版式静默漂移——先装字体（apt install fonts-noto-cjk）再出图")
    if fit.get('orn_unknown'):
        warnings.append(f"🔴 陪衬 `{fit['orn_unknown']}` 不在模板 ORN 库里，右下角**什么都没画**。"
                        f"可选：{fit['orn_known']}（注意是连字符不是下划线）")
    if fit.get('hero_glyph_pct_low'):
        warnings.append(f"🔴 hero 字高只占画面高 {fit['hero_glyph_pct_of_h']}%，低于 §2-b 的 9–13%——"
                        f"hero 太长撑不起来。处置＝把 hero 砍成最扎心的那个短句、"
                        f"剩下的降到 subtitle 副题层（方案 1），⛔ 不是调参数")
    if fit.get('hero_glyph_pct_high'):
        warnings.append(f"⚠️ hero 字高 {fit['hero_glyph_pct_of_h']}% 冲破 §2-b 上限 13%——"
                        f"hero 太短（4 字以内），撑满版心必然超标。这里两条规格天然打架："
                        f"「通栏撑满」与「字高 ≤13%」不可兼得，要么给 hero 加字、要么右侧留白，须人工拍板")
    if fit.get('sub_seg_overflow'):
        warnings.append("副题里有**一整段没有标点**且比版心还宽，已退回自由折行——"
                        "断行会落在词中间。想让它断得好看，在金句里加个逗号")
    if fit.get('ident_orn_overlap'):
        warnings.append("🔴 姓名/身份行仍与右下陪衬重叠——避让算完还是压上了，"
                        "换更窄的陪衬（orn_ratio 调小）或把姓名写短")
    if fit.get('name_below_min'):
        warnings.append(f"🔴 姓名被压到 {fit['name_fs']}px 才躲开陪衬（可读下限 {fit['name_min']}px）——"
                        f"姓名太长，缩略图上会糊掉")
    if fit.get('sub_ratio_ok') is False:
        warnings.append(f"🔴 hero:副题 = {fit['hero_sub_ratio']}:1，低于 §2-b 硬下限 2.5:1，焦点没跳级")
    if fit.get('step_over_sub'):
        warnings.append(f"🔴 递进行 {fit['step_fs']}px 追平/超过副题 {fit['sub_fs']}px，四级字阶塌成三级")
    if fit.get('hero_below_min'):
        warnings.append(f"🔴 hero 太长：撑满版心只解出 {fit['hero_fs']}px，低于缩略图可读下限 {fit['hero_min']}px"
                        f"（220px 卡片上只剩 {fit['hero_thumb_px']}px，会糊成色块）——"
                        f"版式救不了，只能把 hero 缩短")
    if fit.get('role_below_min'):
        warnings.append(f"身份行被压到 {fit['role_fs']}px 才放得下——把身份行写短一点，或换个更窄的陪衬")
    if fit['hero_squeezed']:
        warnings.append(f"递进三行降到下限还塞不下，已回头压 hero 到 {fit['hero_fs']}px——"
                        f"说明整幅文案总量超容，优先删递进行的字，别削 hero")
    if fit['step_at_floor']:
        warnings.append(f"递进行已经压到字号下限 {fit['step_fs']}px，再长就得删字了")
    if fit['overflow_px'] > 1:
        warnings.append(f"仍有 {fit['overflow_px']}px 溢出——文案实在太长，必须删字")
    if not fit['safe_3x4_ok']:
        warnings.append(f"有元素落在 3:4 裁切带里（信息流按 3:4 展示，上下各切 {fit['crop_3x4']['y']}px），"
                        f"会被切掉一截")

    # ⚠️ jinjin 这条路**故意保持退出码恒 0**：小红书线上现有的用法都是「照常出图、
    # 红字交人判断」，把 hero 偏长这类内容判断突然变成硬失败会打断它们。
    # 需要区分度的调用方判 gates_ok（新增字段，纯附加、不改行为）。要不要把这条也
    # 改成退出码 1，是小红书线的口径决定，⛔ 别在这里顺手替它改了。
    red = [w for w in warnings if w.startswith('🔴')]
    receipt['gates_ok'] = not red
    receipt['warnings'] = warnings
    receipt['exit_code'] = 0
    print(json.dumps({
        'ok': True,
        'gates_ok': not red,
        'png': str(out_png), 'thumb': thumb, 'html': str(html_path),
        'receipt': write_receipt(receipt_path, receipt),
        'canvas': f'{W}x{H}',
        'font_landed': landed,
        'hero_fs': fit['hero_fs'],
        'hero_lines': fit['hero_lines'],
        'hero_thumb_px': fit['hero_thumb_px'],
        'hero_glyph_px': fit['hero_glyph_px'],
        'hero_glyph_pct_of_h': fit['hero_glyph_pct_of_h'],
        'sub_fs': fit['sub_fs'],
        'hero_sub_ratio': fit['hero_sub_ratio'],
        'step_fs': fit['step_fs'],
        'name_fs': fit['name_fs'],
        'role_fs': fit['role_fs'],
        'ident_orn_overlap': fit['ident_orn_overlap'],
        'safe_3x4_ok': fit['safe_3x4_ok'],
        'warnings': warnings,
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

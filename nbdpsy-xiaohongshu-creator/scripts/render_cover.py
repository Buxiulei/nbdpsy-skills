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

cover.json（字段全部可改，版式不动）:
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

输出: <out>.png（+ <out>.thumb220.png 缩略图验收用）、<out>.html、stdout 一份 JSON。
"""
import argparse
import base64
import json
import mimetypes
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_TPL = HERE.parent / 'assets' / 'cover-templates' / 'tpl-cover-jinjin.html'


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


def build_html(tpl: str, data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False)
    # </script> 会提前关掉承载数据的那个标签，必须打断
    blob = blob.replace('</', '<\\/')
    return tpl.replace('__COVER_DATA__', blob)


def make_thumb(png: pathlib.Path, width: int) -> str:
    """缩略图验收是封面的唯一硬闸——顺手产出来，⛔ 别让人"回头再缩一张看看"。"""
    try:
        from PIL import Image
    except ImportError:
        return ''
    im = Image.open(png)
    h = round(im.height * width / im.width)
    out = png.with_suffix(f'.thumb{width}.png')
    im.resize((width, h), Image.LANCZOS).save(out)
    return str(out)


def main():
    ap = argparse.ArgumentParser(description='封面 JSON → 封面 PNG（确定性排版渲染）')
    ap.add_argument('--data', required=True, help='封面文案 JSON')
    ap.add_argument('--out', help='输出 PNG 路径，默认 <data 同级>/<data 名>.png')
    ap.add_argument('--template', default=str(DEFAULT_TPL), help='模板 HTML，默认包内 tpl-cover-jinjin.html')
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

    tpl_path = pathlib.Path(args.template).resolve()
    if not tpl_path.exists():
        return die(f'模板不存在：{tpl_path}')

    if not data.get('hero'):
        return die('hero 是空的——这个版式的第一层就是通栏大字，没大字就不是这个版式')

    warnings = check_fields(data) + resolve_assets(data, dpath.parent)

    W = int((data.get('canvas') or {}).get('w', 876))
    H = int((data.get('canvas') or {}).get('h', 1313))

    out_png = pathlib.Path(args.out).resolve() if args.out else dpath.with_suffix('.png')
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
        landed = platform_fonts(page, '.hero .l')
        page.wait_for_timeout(60)
        page.screenshot(path=str(out_png), clip={'x': 0, 'y': 0, 'width': W, 'height': H})
        browser.close()

    thumb = make_thumb(out_png, args.thumb) if args.thumb else ''

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

    print(json.dumps({
        'ok': True,
        'png': str(out_png), 'thumb': thumb, 'html': str(html_path),
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

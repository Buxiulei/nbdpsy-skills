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
still-life 还多两道闸，都在读者真正看到的 220px 信息流尺寸上判（见 measure_feed_thumb）：
    ① 缩略图存活闸——赭红 accent 缩到信息流尺寸后还得看得见（量后果）。
       几何闸门对 cord 全绿而缩略图上赭红是 0 个，这道闸就是补那个洞。
       判据是**占画面的百分比**，⛔ 不是绝对像素数：缩略图定宽 220、高随画幅走，
       绝对数在高画幅上会自动变松。阈值只在 16:9～3:1 之间标定过，出界会显式报 ⚠️。
    ② cord 语义闸——accent=cord 时，线得从一件本来就带线的物件上垂下来（量形式，
       靠 CORD_CAPABLE_ICONS 白名单，**素材库扩张时要人来补表**）。
主体墨迹占比与外接框比例同样在这个尺寸上量，但**只报不拦**（stdout 的 feed_thumb.ink）。

退出码（三态，⛔ 别只判 0/非 0 就完事）:
    🔴 **验收判 `gates_ok`，⛔ 别判退出码**（2026-08-17 订正：此处原写「0 = 成功且校验全过」，
       那句话对 jinjin 是**假的**——jinjin 这条路退出码**恒 0**，闸门红着也是 0）。
       两条路故意不一样，因为它们的调用方不一样：
         · still-life（公众号）——红灯 → 退出码 1，脚本调用方直接被拦住；
         · jinjin（小红书）——**恒 0**，红字交人判断。小红书线现有用法都是「照常出图、
           红字交排版 agent 自解」，把 hero 偏长这类内容判断变成硬失败会打断它们。
       ⇒ 两条路**都**在 stdout 与凭证里给 `gates_ok`（bool）。⛔ 只判退出码的调用方
       会把 jinjin 的红灯当成功收走。要不要把 jinjin 也改成退 1，是小红书线的口径决定。
    0  跑完了。**still-life**：校验全过；**jinjin**：出图了，合格与否看 `gates_ok`
    1  **图产出来了，但不合格**（只有 still-life 会走到这里）——比例超差、四角有白边、图标缺失、画面里有文字、
       赭红在缩略图上没活下来、cord 挂在不带线的物件上等，
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
    # ⚠️ hero_glyph_pct_band / hero_ink_ratio / hero_max / hero_fill_* / steps_count 必须进这张表：
    # 告警文案会硬取它们，模板老一版就会 KeyError——那是个**没被接住的异常**，
    # 退出码会撞上「1＝出图了但不合格」，把版本不同步伪装成质量不合格。
    # 🔴 反面也真出过：`hero_glyph_band_canvas` 随根因修复从模板移除、这张表却还列着它，
    # **每一张都渲不出来**、报「模板与脚本版本对不上」。⇒ 删模板字段时必须同步删这里。
    'jinjin': ('hero_fs', 'hero_lines', 'sub_fs', 'step_fs', 'name_fs', 'role_fs',
               'overflow_px', 'safe_3x4_ok', 'crop_3x4',
               'hero_glyph_pct_band', 'hero_ink_ratio', 'hero_max',
               'hero_fill_pct', 'hero_fill_min', 'hero_fill_low', 'hero_at_max',
               'steps_count'),
    'still-life': ('icons', 'gaps', 'group_ink_w', 'margin_left', 'margin_right', 'margin_top',
                   'baseline_y', 'baseline_drawn', 'baseline_align_dev_px', 'desk_w',
                   'desk_overhang_px', 'accent', 'accent_form', 'accent_spots', 'accent_options',
                   'accent_unknown', 'bg_unknown', 'bg_known', 'cord', 'overlap', 'min_gap',
                   'out_of_canvas', 'margin_asym_px', 'text_in_canvas'),
}


# ── 闸门 A（publish_note.py --check-cover）要的凭据 ──────────────────
# 为什么落在这里：闸门只认「有提示词」那套（prompt_excerpt + 色值 + 具名版式），而确定性渲染
# 压根没有提示词。发布端已按来源分岔（COVER_SOURCES 增了 render_cover 档），⛔ 但缺了这几个
# 键就仍然过不去——于是「如实做发不出去、能发出去的唯一做法正是伪造凭证」。这几个键补的是那个死结。
#
# 🔴 三条红线，⛔ 一条都不许破：
#   ① `layout` 只从**模板 kind** 映射来，⛔ 绝不从 cover.json 抄调用方自己声明的版式——
#      那只是换个地方说谎。⚠️ `still-life` **故意不在表里**：它是公众号横版零文字封面，
#      本就不在小红书的版式白名单内 → 不写 layout → 闸门红，**这是正确结果**。
#      将来 jinjin 长出第二种版式时，必须由模板/数据交回真实版式，⛔ 不许继续写死。
#   ② `palette` 记**实际渲出来的**色值（截图前从 :root 上读已解析的 CSS 变量），⛔ 不从数据里抄。
#   ③ `style_profile` 复用 gen_images 那一份解析，⛔ 不另写——两处口径一漂，闸门就形同虚设。
LAYOUT_BY_KIND = {'jinjin': '通栏大字压顶'}
# 从 :root 上读这几个已解析的 CSS 变量当调色板。⛔ 只收 `#RRGGBB`：
#   · `--paper` 是 `color-mix(...)`，getComputedStyle **不会**把它解析成 hex；
#   · `getComputedStyle(body).backgroundColor` 在当前 Chromium 返回 `color(srgb 0.9458 …)`
#     而**不是** `rgb()`——正则找 `rgb(` 会静默拿到空集，又一个「量不出来却报绿」。
# 所以判据只认声明里本来就是 hex 的那几个，拿不到就是拿不到（闸门会红），⛔ 不猜。
PALETTE_VARS = ('--bg', '--paper', '--accent', '--ink', '--muted', '--sage', '--haze')


def read_palette(page) -> list:
    """从渲染好的页面上读**实际生效**的调色板（⛔ 不是数据里许诺的）。"""
    vals = page.evaluate(
        "(names) => {const cs = getComputedStyle(document.documentElement);"
        " return names.map(n => cs.getPropertyValue(n).trim());}", list(PALETTE_VARS))
    out = []
    for v in vals:
        m = re.fullmatch(r'#([0-9A-Fa-f]{6})', str(v).strip())
        if m and f'#{m.group(1).upper()}' not in out:
            out.append(f'#{m.group(1).upper()}')
    return out


import compliance_core  # noqa: E402  凭证署名段的唯一真源


def resolve_style_profile(data_path: pathlib.Path, override):
    """本批风格档案 —— ⛔ 复用 gen_images 那一份，别另写一份解析。

    口径必须与 gen_images 一模一样：`--style-profile "<套名> v<N>"` 优先，否则从 --data 所在目录
    → 上一级找 `00-overview.md` 的留痕行。都拿不到就**不写**这个键 → 闸门红（fail-closed，
    与 gen_images 同）。⚠️ gen_images 拿不到时会 import 失败/找不到函数——那属于安装不完整，
    ⛔ 不静默当成「没有档案」放行：两者后果完全不同（一个是没配置，一个是装坏了）。

    🩸 **示例串是错标的传播源**（2026-08-21）：本处示例原本写的是 `"图文 v3"`——
    **一个档案库里不存在的组合**（图文只有 v2，v3 是暖米大字的）。
    博客长文**把它当真值抄用**，**13 份凭证错标一路绿灯**，到发布前才被人肉发现。
    ⇒ **文档里的示例会被当成真值抄** ⇒ 示例一律写成**明显的占位符**（`<套名> v<N>`），
    ⛔ 别写任何"看起来能直接用"的具体值。
    ⚠️ 🔴 **本函数目前是纯透传，⛔ 不校验套名是否存在**（待办：resolve 后比对档案库，
    对不上拒渲；离线时 warn 放行并在凭证记「未校验」）——
    **错标比缺失更毒**：缺失会被闸门 A 拒（有声音），错标畅通无阻，
    而**凭证的意义就是溯源，错标＝溯源断**。
    """
    sys.path.insert(0, str(HERE))
    import gen_images                                   # noqa: E402  同目录脚本，⛔ 别复制它的解析
    return gen_images.resolve_style_profile(str(data_path), override)


# ── 凭证校验：**声明的那套档案**对不对得上档案库、**实际渲出的色**对不对得上它 ──────
#
# 🩸 这一段补的是「验了在不在，没验对不对」：凭证里一直同时躺着 `style_profile`（声明）
#    与 `palette`（实测），**从来没人把这两个数相减**。字段在、判据在、每次都过。
#    实证：13 份凭证标着 `图文 v3` 一路绿灯到发布前，而档案库里「图文」**只有 v2**。
#
# 🔴 三条判据，⛔ 一条都别放宽：
#   ① **套名/版本对不上 → 拒渲**（在起浏览器之前就拒，别渲完才说）。这是硬错、且真发生过。
#   ② **色值方向是「档案声明的 ⊆ 实际渲出的」，⛔ 不是反过来。**
#      🩸 实测：jinjin 渲出 6 色，档案「暖米大字」v3 声明 5 色，5 个全中；但模板还有个
#      正当的中性墨蓝 `#2B3A4A` **档案里根本没记**。写成「实测 ⊆ 声明」就恒红，
#      而**恒红的闸门等于没有闸门**（人会绕过去）。
#   ③ **量不出来 ≠ 不匹配**：still-life 的 `:root` 里一个 hex 都没有 ⇒ 实测为空集。
#      空集要记 `null` 不记 `false`——把"没量到"说成"不匹配"，是在自造假红。
#
# ⚠️ 离线（没配 key / 网络不通）**warn 放行**并在凭证记 `verified: null`：
#    这是个**看得见的洞**（断网即可绕过），⛔ 但不能变成静默的洞——所以凭证必须留痕，
#    发布端闸门据此知道"这份没核过"。
def check_style_profile(sp_decl, timeout=20) -> dict:
    """渲染**前**核一次：`sp_decl` 那句「<套名> v<N>」在档案库里存不存在。

    三态，⛔ 不是布尔：`True` 核过且对得上／`False` 档案库说没有这一版（拒渲）／
    `None` 没核成（离线、或压根没声明档案）。

    ⚠️ 主体在 `style_profile.verify_declaration`——**三处凭证产线共用那一份**
    （另两处是 gen_images / typeset_longimage）。⛔ 别在这里复制一份实现：
    要同源，就 import 那个函数本身。"""
    sys.path.insert(0, str(HERE))
    try:
        from style_profile import verify_declaration       # noqa: E402  同目录
    except Exception as e:                                  # 装不全 ≠ 档案错
        return {'verified': None, 'reason': f'读不到档案库客户端（{e}）', 'declared': [],
                'name': None, 'version': None, 'tag': None}
    return verify_declaration(sp_decl, timeout=timeout)


def match_palette(chk: dict, palette: list) -> dict:
    """渲染**后**补上色值比对：档案声明的每个色，是不是真的渲出来了。

    判据方向见上：**声明 ⊆ 实测**。两种「量不出来」一律记 `None`，⛔ 不记 `False`。"""
    # 🔴 **两边必须走同一个规范化**：首版只把实测侧 `.upper()`、声明侧原样比，
    #    `#a34b3a` 与 `#A34B3A` 这两个同一个颜色就会判成"没渲出来"（测试当场抓到）。
    #    ⇒ 要同源，就 import 那个函数本身，⛔ 不是各写一遍自己的大小写处理。
    sys.path.insert(0, str(HERE))
    from style_profile import norm_hex                  # noqa: E402  同目录，⛔ 别复制它
    out = dict(chk)
    norm = lambda seq: [h for h in (norm_hex(c) for c in (seq or [])) if h]   # noqa: E731
    declared, actual = norm(out.get('declared')), norm(palette)
    if not actual:
        out['palette_ok'], out['palette_reason'] = None, '模板没交回可解析的 hex，量不出实际调色板'
    elif not declared:
        out['palette_ok'], out['palette_reason'] = None, '这一版档案没声明任何色值，无从比对'
    else:
        missing = [c for c in declared if c not in actual]
        out['palette_ok'] = not missing
        out['missing_colors'] = missing
        out['palette_reason'] = ('声明的色值全部渲出来了' if not missing
                                 else f'档案声明了 {missing}，实际渲出的调色板里没有')
    return out


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


# 横版豁免的理由，**跟着豁免一起打进 stdout 与凭证**。⛔ 别只打一个字段名列表：
# 光看到 `exempted: ["avatar","identity"]` 的人无从判断这是有意放行还是闸门坏了。
EXEMPT_WHY = ('横版（w > h）用作视频封面：四层版式的第 ④ 层头像层是**为竖版定义**的，'
              '横版下这一层压根不存在，⛔ 不是「缺了」。竖版一个字都没放松。')


def check_fields(data: dict, landscape: bool = False):
    """缺字段以前是静默留白（首版实测缺头像空出 19.3% 版面，零警告）——一律报红。

    返回 (告警列表, 被豁免的判据名列表)。告警列表里 🔴 开头的才算红灯，⚠️ 开头的只是提示。

    ⚠️ **横版豁免头像层**：这套四层版式（hero/递进/头像/落款）本来就是为**竖版**定的，
    那条红字自己说的是「右下角空一大片」——那是竖版布局的说法。横版（视频封面）下第 ④ 层
    压根不存在，⛔ 不是「缺了」。判据取**画布方向**而不是新加一个 flag：方向本身就是
    这套版式适不适用的分界，加 flag 等于让调用方自己声明「我不要这条闸」。

    ⛔ 豁免必须说出来（调用方把 exempted 打进 stdout 与凭证）：**静默豁免与静默失效
    只差一个方向**。⛔ 竖版一个字都不许放松——竖版缺头像是真缺陷（首版实测空掉 19.3% 版面）。
    """
    red, exempted = [], []
    hero = [s for s in (data.get('hero') or []) if str(s).strip()]
    if len(hero) > 2:
        red.append(f'🔴 hero 有 {len(hero)} 行——这个版式规定两行封顶，'
                   f'长句请降到 subtitle 副题层（方案 1），别硬塞进 hero')
    if landscape:
        exempted = ['avatar', 'identity']
        # 🔴 豁免「没传」与吞掉「传了的」是**两件事**，⛔ 不许混成一件（2026-08-17 干跑抓到）：
        # 横版会把第 ④ 层整层收起，所以数据里**真的传了** avatar/identity 时，那份数据
        # 静默消失在成图里，而 gates_ok 照样 true。条件头像闸门规定「署名长文拆解的封面
        # 没有真人头像 = 不过审」——头像传了、图上没有、闸门是绿的，正是那道闸门的反面。
        # ⛔ 不报红：横版收起第 ④ 层是**有意的版式行为**，不是缺陷；但必须说出来。
        got = [k for k in ('avatar', 'identity') if str(
            (data.get(k) if k == 'avatar' else (data.get(k) or {}).get('name')) or '').strip()]
        if got:
            # ⛔ 挂进同一个列表、⛔ 不改返回形状：调用方按 `w.startswith('🔴')` 过红灯，
            # ⚠️ 开头的这条自然只进 warnings 不进 red。改成三元组会重演
            # 「实参个数没变、变的是返回形状」那次全线渲不出图的事故。
            red.append(f'⚠️ 数据里传了 {got}，但横版会把第 ④ 层（头像 + 姓名/身份行）**整层收起**，'
                       f'这些字段**不会出现在成图里**。⛔ 若这是「署名长文拆解」那类必须带真人头像的'
                       f'封面，横版版式不适用——改出竖版，或换一个把头像画进版面的版式。'
                       f'（⛔ 别把这条当红灯：横版收起第 ④ 层是有意的，报出来只是为了'
                       f'让「传了却没渲」不再是静默的）')
    else:
        if not str(data.get('avatar') or '').strip():
            red.append('🔴 缺 avatar：头像是这个版式的第 ④ 层，缺了右下角空一大片（首版实测 19.3% 版面）')
        idn = data.get('identity') or {}
        for k, what in (('name', '姓名'), ('line', '身份行')):
            if not str(idn.get(k) or '').strip():
                red.append(f'🔴 缺 identity.{k}（{what}）：头像旁会只剩半边，封面认不出作者是谁')
    if not str(data.get('footer') or '').strip():
        red.append('🔴 缺 footer：底部落款是品牌位，缺了这版式就不成立')
    return red, exempted


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


def _inline_image(path) -> str:
    """图片 → data URI。⚠️ **零外部依赖**：⛔ 别让成品 HTML 指向本机路径——
    换台机器打开就是个空框，而**页面不会报错**（视频线 2026-08-19 同一条）。"""
    import base64, mimetypes
    f = pathlib.Path(path).expanduser()
    if not f.is_file():
        die(f'--sticker 找不到文件：{f}')
    mime = mimetypes.guess_type(f.name)[0] or 'image/png'
    return f'data:{mime};base64,' + base64.b64encode(f.read_bytes()).decode()


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


# ── 缩略图存活闸的判据常数 ──────────────────────────────────────────
# 为什么有这道闸（2026-08-17 实测）：几何闸门对 cord 全绿（drawn=true、
# degenerate=false、两端落差 99.1px），可**读者真正看到的 220px 信息流缩略图上，
# 赭红像素是 0 个**。机制是 cord 只有 3.6px 粗，缩到 1/6 落在亚像素上被重采样抹平；
# 「指名某件图标整体着色」是面，缩完还是面。**线会消失，面不会**，而任何量形式的
# 闸门（画没画、退化没退化）都照不出这个后果。所以这道闸量的是后果不是形式。
FEED_THUMB_W = 220        # 读者在公众号信息流里实际看到的封面宽度
INK_LUMA_MAX = 200        # 亮度低于此值算「墨迹」；纸底最暗处约 220，留 20 档余量
# r−g 与 r−b **同时** ≥ 这个数才算赭红。50 不是随手取的：赭红 #A34B3A 的 r−g=88、
# 纸底 r−g≈5，所以「r−g ≥ 50」＝「这个像素至少 54% 是赭红」。缩小后活下来的 cord 像素
# 全是 30～45% 的稀释混色（看上去就是一抹脏，不成其为红），而面着色的图标笔画芯部是
# 接近纯色的赭红——**这个 delta 分的正是「糊成一片」与「真的有一笔」**。实测（见下表）：
# delta 从 26 抬到 50，cord 侧 52→0，最弱合法样本才 97→68，两侧同时抬但速度差 10 倍。
ACCENT_HUE_DELTA = 50
# 赭红在信息流缩略图上的存活下限，单位是**占画面的百分比，⛔ 不是绝对像素数**。
# 为什么必须是比例：缩略图**定宽 220、高随画幅走**，2.35:1 是 220×94（20680 px）、
# 16:9 是 220×124（27280 px）。同一个绝对像素数放到更高的画幅上占比自动变小＝闸门自动变松；
# 而「读者看不看得见」取决于占视野的比例，与画面总共多少像素无关。
#
# 🔴 **这里栽过一次，记牢**：第一版写着「cord 侧的 0 是结构性的：CORD_SW_R 与画布同比例，
# 无论出图多大 cord 恒为 ~0.6px」——**错**。同比例的是**画布**，可缩略图是定宽变高的，
# 比例关系在那儿断了。真实关系是：
#       缩略图上的 cord 线宽 = CORD_SW_R × 220 ÷ 宽高比
# 只随**宽高比**变，与画布绝对大小无关。所以 2.35:1 上 0.60px（被抹平＝0 个像素），
# 16:9 上 0.80px 就能活下 26 个像素——同一份数据换个画幅换个结论，当场假绿。
# ⚠️ 教训不在「少测了一档」，在**推理链里换了一次坐标系而没察觉**。
#
# 标定实测（走 measure_feed_thumb 本身，d=50，LANCZOS 缩到 220，⛔ 不经 JPEG 再编码）。
# 两侧都取**实测出来的极值**，⛔ 不是随手挑几个样本：
#     宽高比    缩略图     cord 最强(失败侧)      6 件组末位 stairs(合法侧最弱)
#     3:1      220×73       0px  0.000%              32px  0.199%
#     2.6:1    220×85       0px  0.000%              48px  0.257%
#     2.35:1   220×94       0px  0.000%              54px  0.261%   ← 合法侧全局最低
#     2:1      220×110      2px  0.008%              6 件组已放不下，退回 3 件组 ≈0.9%
#     16:9     220×124     28px  0.103%   ← 失败侧带内最高
#     4:3      220×165     80px  0.220%              6 件组放不下
# 带内（16:9 ～ 3:1）失败侧最高 0.103%、合法侧最低 0.199%，取几何中点 0.16%：
# 距失败侧 1.55 倍、距合法侧 1.24～1.63 倍。**两侧margin都只有 1.5 倍上下，很窄**——
# 窄是事实不是选择：合法侧的最弱样本（6 件组的最小一件）与失败侧的最强样本（cord 在高画幅上）
# 本来就挨得近。⛔ 别为了「看起来安全」把阈值往任一侧挪，那只会把一侧的漏判换成另一侧的误报。
ACCENT_MIN_PCT_FEED = 0.16
# 上面这套数只在这个宽高比区间里验过。⛔ 出了区间**红绿都不作数**，必须显式说出来，
# ⛔ 不许静默沿用——这正是上一版「结构性恒 0」翻车的形状（拿一档的结论推广到所有画幅）。
# 实测越界会怎样：4:3（比例 1.333）上 cord 冒到 0.220% > 0.16%，**假绿**。
ACCENT_CALIBRATED_RATIO = (16 / 9, 3.0)


def count_accent_pixels(im, delta: int = ACCENT_HUE_DELTA) -> int:
    """数画面上还剩多少个赭红像素。**判据是色相，⛔ 不是到 #A34B3A 的 RGB 距离。**

    距离判据实测会把整组静物数成赭红：石板灰 #4A5563 到赭红 #A34B3A 的欧氏距离只有
    98.5，所以 `dist≤100` 在一张**赭红为零**的封面（cover-01 缩略图）上数出 279 个像素，
    那是个恒绿的假闸门。色相判据没这毛病——模板调色板六色全是 r < g（r−g 在 −11～−20），
    纸底 r−g 最多 12，只有赭红 r−g=88 / r−b=105，两头各留着几倍余量。

    ⚠️ delta 同时也是**纯度**闸：见 ACCENT_HUE_DELTA 的注释，抬高 delta 等于只数
    "足够纯"的赭红像素，稀释成一抹脏的那些自然掉出去。
    """
    n = 0
    for r, g, b in im.convert('RGB').getdata():
        if r - g >= delta and r - b >= delta:
            n += 1
    return n


def ink_metrics(im, luma_max: int = INK_LUMA_MAX) -> dict:
    """主体墨迹占了多少画面、外接框有多大。**只报数，⛔ 不设闸门。**

    「主体该多大」是审美与风格档案的事，由持量具的排版方自己解，闸门不替他拍板。
    这里只保证他手上有数：占比 = 墨迹像素 / 全画面；外接框 = 所有墨迹像素的包围盒。
    """
    im = im.convert('RGB')
    w, h = im.size
    xs, ys, n = [], [], 0
    for i, (r, g, b) in enumerate(im.getdata()):
        if 0.299 * r + 0.587 * g + 0.114 * b < luma_max:
            n += 1
            xs.append(i % w)
            ys.append(i // w)
    if not n:
        return {'ink_px': 0, 'ink_pct': 0.0, 'bbox_w_pct': 0.0, 'bbox_h_pct': 0.0, 'bbox': None}
    bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    return {
        'ink_px': n,
        'ink_pct': round(100.0 * n / (w * h), 2),
        'bbox_w_pct': round(100.0 * bw / w, 1),
        'bbox_h_pct': round(100.0 * bh / h, 1),
        'bbox': {'x': min(xs), 'y': min(ys), 'w': bw, 'h': bh},
    }


def measure_feed_thumb(src: pathlib.Path, width: int = FEED_THUMB_W) -> dict:
    """把成图缩到信息流宽度再量——**读者看到的是这个尺寸，闸门就得在这个尺寸上判**。

    ⚠️ 这里自己缩一张（内存里，不落盘），⛔ 不复用 --thumb 产的那个文件：--thumb 可以
    被调成 0 或别的宽度，判据跟着漂就等于这道闸可以被参数关掉。判据宽度恒为 FEED_THUMB_W。
    PIL 缺席时**报红**而不是跳过——量不出来的绿是假绿。
    """
    try:
        from PIL import Image
    except ImportError:
        return {'ran': False, 'reason': '没装 Pillow，缩略图上的赭红存活与墨迹占比都量不出来'
                                        '（pip install Pillow）'}
    im = Image.open(src)
    small = flatten_for_jpeg(im.resize((width, max(1, round(im.height * width / im.width))),
                                       Image.LANCZOS))
    accent_px = count_accent_pixels(small)
    # ⚠️ 阈值、实测值、**以及量它的那块画布多大**，三个必须一起写进凭证：
    # 只看到「26」和「下限 20」，看不出这是"刚好过"还是"稳过"——而这次的坑恰恰藏在
    # 缩略图高度里（220×94 与 220×124 是两套完全不同的分母）。
    return {
        'ran': True, 'width': width, 'size': f'{small.width}x{small.height}',
        'thumb_w': small.width, 'thumb_h': small.height,
        'thumb_px': small.width * small.height,
        'accent_px': accent_px,
        'accent_pct': round(100.0 * accent_px / (small.width * small.height), 3),
        'accent_min_pct': ACCENT_MIN_PCT_FEED, 'hue_delta': ACCENT_HUE_DELTA,
        'ink': ink_metrics(small),
    }


# ── cord 语义闸的白名单 ────────────────────────────────────────────
# accent=cord 会从**第一件**静物垂一根赭红曲线到第二件。判据：那第一件在现实里
# 得本来就拖着一根线/绳，红线才读得成「它自己的线」；否则就是一条无来由的红曲线
# （cover-03 把线画在 door-open 上，起笔处还紧挨门把手小圆点，第一眼像画错了）。
#
# ⚠️ **这张表随图标库扩张需要人来补，⛔ 它不会自己长。** 素材库正在从 66 枚扩到几万枚，
# 新进来的带线物件（电话、充电器、熨斗、水壶、吊灯、点滴……）不补进来就会被误判成红。
# 补表判据：这件东西在现实里本来就拖着一根线/绳/管，且那根线是它的显著特征。
# ⛔ 表放在这里而不是 svg 文件头里，是因为素材库由别的线维护，本闸门不往那边写字段。
CORD_CAPABLE_ICONS = frozenset({
    'headphones',   # 耳机线——参考封面用的就是它
    'lamp',         # 台灯电源线
    'anchor',       # 锚链
    'life-buoy',    # 救生圈牵引绳
})


def cord_semantic_problem(cord, names):
    """accent=cord 时，线得从一件**本来就带线**的物件上垂下来。不满足就返回红字。"""
    if not cord or not cord.get('drawn'):
        return None                       # 线压根没画，另有闸门管（cord.drawn）
    origin = cord.get('from')
    if origin in CORD_CAPABLE_ICONS:
        return None
    movable = [n for n in names if n in CORD_CAPABLE_ICONS]
    if movable:
        fix = (f'把 `{movable[0]}` 挪到 icons 第一位——线是从第一件垂到第二件的')
    else:
        fix = (f'这组静物里没有一件带线的（本表认得的：{sorted(CORD_CAPABLE_ICONS)}），'
               f'换一件带线物件当主角，或把 accent 改成指名某个 icon 整体着色')
    return (f'🔴 accent=cord 的线挂在 `{origin}` 上，可这东西本来不带线——'
            f'画出来就是一条不属于任何物件的红曲线。{fix}。'
            f'（若 `{origin}` 确实是带线物件，那是 render_cover.py 的 '
            f'CORD_CAPABLE_ICONS 该补了，⛔ 这张表不会自己跟上素材库扩张）')


def write_receipt(path: pathlib.Path, payload: dict):
    """产出凭证：出问题时能**不重跑就定位**。

    ⚠️ 落在 `<产物名>.meta.json`，⛔ 不是 `<产物名>.json`——后者是调用方
    （gen_gzh_images.py）写输入数据的位置（cover.jpg ↔ cover.json），
    写那儿等于把别人喂进来的数据覆盖掉。
    """
    # 🔴 **机器档也要署名**（2026-08-21 捞法演练）：`manual_confirmed` 人工档有
    # `confirmed_by`+`confirmed_at`，而机器档因为"是工具出的"就不记
    # ⇒ 13 份「图文 v3」错标追责任线时，**靠的是当事人自己承认，⛔ 不是凭证追出来的**。
    # ⚠️ 加在这里（唯一出口）⇒ 所有调用点一次覆盖，⛔ 不用每处各写一遍。
    # ⚠️ 已有同名键时**不覆盖调用方给的值**——调用方比这里更知道自己是谁。
    stamp = {k: v for k, v in compliance_core.receipt_stamp().items() if k not in payload}
    path.write_text(json.dumps({**payload, **stamp}, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    return str(path)


def report_still_life(fit, check, feed, landed, warnings, out, thumb, html_path,
                      receipt, receipt_path, W, H):
    """静物式封面的闸门与量具。

    红灯 → **退出码 1**（图产出来了但不合格），⛔ 别让 ok=true 混过验收。
    与「退出码 2＝压根没出图」分开，是为了让调用方一眼分清「去看图」还是「去改参数」。
    """
    receipt['feed_thumb'] = feed          # 信息流尺寸的实测，只有这个版式量（见 main()）
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
    # ② cord 语义闸：线得从一件本来就带线的物件上垂下来（量形式，随素材库扩张要补表）
    cord_sem = cord_semantic_problem(fit['cord'], [i['name'] for i in fit['icons']])
    if cord_sem:
        warnings.append(cord_sem)
    # ① 缩略图存活闸：赭红在读者真正看到的 220px 上还剩几个像素（量后果，不随素材库变化）
    if not feed['ran']:
        warnings.append(f"🔴 缩略图存活闸没跑起来：{feed['reason']}——量不出来的绿是假绿，⛔ 别当验收通过")
    elif fit['accent_spots'] == 1 and feed['accent_pct'] < ACCENT_MIN_PCT_FEED:
        warnings.append(f"🔴 赭红在 {feed['size']} 的信息流缩略图上只占 {feed['accent_pct']}%"
                        f"（{feed['accent_px']}/{feed['thumb_px']} px，下限 {ACCENT_MIN_PCT_FEED}%）——"
                        f"accent 是画面里唯一讲故事的那一处，读者那个尺寸上等于不存在。"
                        f"当前形态 `{fit['accent_form']}`：细线缩到信息流尺寸会落在亚像素上被重采样抹平"
                        f"（缩略图上的线宽 = CORD_SW_R×220÷宽高比，这张是 "
                        f"{0.00644 * 220 / (W / H):.2f}px），"
                        f"改用「accent 指名某个 icon 整体着色」——面缩完还是面")
    # ⚠️ 比容差：画布高是 round() 出来的整数，`--canvas 16:9` 实际落成 1313×739＝1.7767，
    # 比名义上的 1.7778 低一丝。拿严格不等号比会把**正好在端点上的那一档**判成越界
    # （实测就是 16:9 自己被喊了狼来了）。±1% 与出图比例校验同一个容差口径。
    lo, hi = ACCENT_CALIBRATED_RATIO
    if feed['ran'] and not (lo * 0.99 <= W / H <= hi * 1.01):
        warnings.append(f"⚠️ 画布宽高比 {W / H:.3f} 落在存活闸的标定区间 "
                        f"[{lo:.3f}, {hi:.3f}] 之外——阈值 {ACCENT_MIN_PCT_FEED}% 只在那个区间里实测过，"
                        f"**这张图的红绿都不作数**。机制：缩略图定宽 220、高随画幅走，画幅越高 cord "
                        f"在缩略图上越粗（实测 4:3 上 cord 能冒到 0.220% 而假绿）。"
                        f"要在这个比例上用这道闸，得先按 ACCENT_MIN_PCT_FEED 的注释重标一遍")
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
        # 信息流缩略图上的实测：accent_px 是闸门判据；ink 那三个数**只报不拦**——
        # 「主体该多大」是审美与风格档案的事，做决定的人要看数，闸门不替他拍板。
        'feed_thumb': feed,
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
    ap.add_argument('--thumb', type=int, default=220,
                    help='顺带产的缩略图**文件**宽度（0=不产），默认 220。'
                         '⚠️ 缩略图存活闸不吃这个值——它恒在 220px 上判，改这里关不掉它')
    ap.add_argument('--html-only', action='store_true', help='只产 HTML 不截图（没装 playwright 时降级）')
    ap.add_argument('--style-profile', metavar='"套名 vN"',
                    help='本批风格档案，写进凭证的 style_profile（闸门 A 要）。'
                         '不给就从 --data 同级 → 上一级的 00-overview.md 留痕行读；'
                         '⚠️ 都拿不到就**不写**这个键，发布时闸门 A 会拒（与 gen_images 同口径）。'
                         '🔴 v2.28.0 起会**联网核**这个套名/版本在不在档案库里，对不上直接拒渲')
    ap.add_argument('--style-timeout', type=float, default=20,
                    help='核档案库的超时（秒，默认 20）。⚠️ 超时按「没核成」处理：'
                         'warn 放行 + 凭证记 verified:null，⛔ 不会当成核过')
    ap.add_argument('--sticker', metavar='图片',
                    help='账号贴图（咪问猫等）：贴在封面角落，**与 avatar 并存**。'
                         '⚠️ 图片会内联成 data URI（零外部依赖）。'
                         '⛔ 不传时输出与不带本参数**逐字节相同**')
    ap.add_argument('--sticker-pos', choices=('tr', 'tl', 'br', 'bl'), default='tr',
                    help='贴图角位：tr=右上（默认，本版式唯一常空的角）/tl/br/bl。'
                         '⚠️ 「不挡内容」靠**位置分离**，⛔ 不靠层次')
    ap.add_argument('--sticker-size', type=int, default=200, help='贴图边长 px（默认 200）')
    args = ap.parse_args()

    dpath = pathlib.Path(args.data).resolve()
    if not dpath.exists():
        return die(f'封面数据文件不存在：{dpath}')
    try:
        data = json.loads(dpath.read_text(encoding='utf-8'))
        # 🔴 **账号贴图位**（2026-08-21 牧阳助理立项，选②：模板加次级位、⛔ 不改渲染器成合成器）
        # 🩸 起因：咪问「每条带猫」，现状是在**过闸底图上 PIL 手工叠猫** ⇒ 产物**没有管线凭证**
        #    ⇒ 闸门 A 必拒，已连卡两批（靠手写 manual_confirmed 止血）。
        # ⚠️ **⛔ 不能占 avatar 位**：kepu 批的 avatar 被**真人署名头像**占着
        #    （拆解/科普署名规范要求真人头像，⛔ 不能拿猫顶掉）。
        # ⚠️ **不传 --sticker 时这三个键一个都不写** ⇒ 模板条件渲染整个元素不存在
        #    ⇒ **输出与改动前逐字节相同**（⛔ 这是验收硬条件，已实测）。
        if args.sticker:
            data['sticker'] = _inline_image(args.sticker)
            data['sticker_pos'] = args.sticker_pos
            data['sticker_size'] = args.sticker_size
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

    # ⚠️ 字段体检**必须排在画布定下来之后**：豁免哪几条判据取决于画布是横是竖，
    # 而画布可能被 --canvas 覆盖（`--canvas 16:9` 时数据里根本没有 canvas 字段）。
    # 排在前面就只能拿数据里的名义画布判，`--canvas` 一给就判反。
    exempted = []
    if kind != 'still-life':
        red_fields, exempted = check_fields(data, landscape=W > H)
        warnings = red_fields + resolve_assets(data, dpath.parent)

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
    # —— 声明的那套档案在不在档案库里：**起浏览器之前就核**，⛔ 别渲完才说 ——
    # 拒渲而不是"渲完记个红"，是因为**错标比缺失更毒**：缺失会被闸门 A 拒（有声音），
    # 错标畅通无阻，而凭证的意义就是溯源——错标＝溯源断。
    style_profile = resolve_style_profile(dpath, args.style_profile)
    sp_check = check_style_profile(style_profile, timeout=args.style_timeout)
    if sp_check['verified'] is False:
        return die(f"风格档案对不上档案库：凭证要写的是「{sp_check.get('tag')}」，但 {sp_check['reason']}"
                   f"——⛔ 已拒渲。先 `python3 style_profile.py --list-profiles` 看他到底有哪几套、"
                   f"各是第几版，再改 --style-profile 或 00-overview.md 的留痕行",
                   style_profile=style_profile, style_profile_check=sp_check)
    if sp_check['verified'] is None and style_profile:
        warnings.append(f"⚠️ 这批没核过档案库（{sp_check['reason']}）——凭证会记 `verified: null`，"
                        f"⛔ 别当成「核过且对得上」")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_png.with_suffix('.html')
    html_path.write_text(build_html(tpl_path.read_text(encoding='utf-8'), data), encoding='utf-8')

    if args.html_only:
        print(json.dumps({
            'ok': True, 'html_only': True, 'html': str(html_path),
            'warnings': warnings,
            # 这条路也要报豁免：⛔ 别让「换个参数就看不见豁免了」成为一条暗路
            'landscape': W > H,
            'exempted': exempted,
            'exempted_why': EXEMPT_WHY if exempted else None,
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
        # ⚠️ 必须在关浏览器**之前**读：调色板要的是**实际渲出来**的色值，
        # 页面一关就只剩数据里许诺的那份了（那正是闸门要防的东西）。
        palette = read_palette(page)
        page.wait_for_timeout(60)
        page.screenshot(path=str(out_png), **shot)
        browser.close()

    thumb = make_thumb(out_png, args.thumb, fmt) if args.thumb else ''
    check = verify_image(out_png, target_ratio)
    # 信息流尺寸上的实测（自己缩，不吃 --thumb）：赭红存活是闸门，墨迹两数只报不拦。
    # ⛔ 只给 still-life 量：jinjin 没有 accent 这个概念，往它的凭证里塞个 accent_px
    # 只会让人以为那是个有意义的数——小红书线要不要这几个量具，是它自己的口径。
    feed = measure_feed_thumb(out_png) if kind == 'still-life' else None

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
    # 闸门 A 要的四样（见 LAYOUT_BY_KIND 那段的三条红线）。⛔ 不写进 receipt 的话，
    # 照文档主路径出的封面**发不出去**，而唯一能发出去的做法就是手搓一份假凭证。
    # 声明 vs 实测的那一次相减（`style_profile` 与 `sp_check` 都在起浏览器之前就备好了）
    sp_check = match_palette(sp_check, palette)
    receipt = {
        'schema': 'render_cover/receipt@1',
        'kind': kind,
        # schema 本身就是证据：这份凭证只可能由本脚本写出来
        'source': 'render_cover',
        # 一次渲染只出一张图 —— 天然单出。⚠️ 缺这个键闸门 fail-closed 会判「不是单出」直接拒
        'cover_only': True,
        # ⛔ 从模板 kind 映射，⛔ 不从数据里抄；still-life 不在表里 → 不写这个键 → 闸门红（对的）
        **({'layout': LAYOUT_BY_KIND[kind]} if kind in LAYOUT_BY_KIND else {}),
        # 实际渲出来的调色板（截图前从 :root 读的已解析值）
        'palette': palette,
        # 拿不到就不写 → 闸门红（与 gen_images 同口径的 fail-closed），⛔ 不填个空壳糊弄
        **({'style_profile': style_profile} if style_profile else {}),
        # 上面那句声明**核过没有**：verified 三态 + 声明的色是不是真渲出来了。
        # ⚠️ 声明了档案才写这个键——没声明时整段不写，让「没声明」与「声明了但没核成」
        #    在凭证里长得不一样（**缺失 ≠ 值为空**）。
        **({'style_profile_check': sp_check} if style_profile else {}),
        'input': {
            'data_file': str(dpath),
            # ⚠️ **内联的大字段一律剔除**：`icons_svg` 与 `sticker`（data URI）
            # 🩸 2026-08-21 实测：把猫的 data URI 塞进 data 后，凭证从 60KB 涨到 **513KB**
            #    —— **凭证是给人读的**，撑成半兆就没人会打开它，等于又回到"捞不出来"。
            # ⛔ 别新写一份剔除逻辑：加内联字段时**在这一行加名字**。
            'data': {k: v for k, v in data.items()
                     if k not in ('icons_svg', 'sticker')},
            'argv': {'template': args.template, 'canvas': args.canvas, 'out': args.out},
        },
        # 🔴 **贴图进凭证：记文件名/位置/尺寸，⛔ 不记 data URI**（三条验收硬要求之一）。
        # ⚠️ 没贴图时写 `None` 而不是省略键：**「这张没贴」与「这版本还不支持贴图」
        #    必须分得开** —— 省略键会让老凭证和新凭证长得一样。
        'sticker': ({'file': pathlib.Path(args.sticker).name,
                     'pos': args.sticker_pos, 'size': args.sticker_size}
                    if getattr(args, 'sticker', None) else None),
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
        return report_still_life(fit, check, feed, landed, warnings, out_png, thumb, html_path,
                                 receipt, receipt_path, W, H)

    # —— 闸门：能量出来的坏消息一律显式报，⛔ 不让它静默混过验收 ——
    # 色值对不上**不拒渲**（图已经在磁盘上了，拒也拒不回来），但要留声音 + 让凭证判红：
    # 换模板 / 模板加了个中性色都可能让它响，那属于"要人来看一眼"，⛔ 不属于"该拦下重来"。
    if sp_check.get('palette_ok') is False:
        warnings.append(
            f"🔴 声明的档案「{sp_check.get('tag')}」与实际渲出的配色对不上："
            f"{sp_check['palette_reason']}（实测 {palette}）——"
            f"⚠️ 凭证声明的是这一套、渲出来的却不是它的色，**溯源就断在这里**。"
            f"要么换对模板，要么把档案里那几个色更到与模板一致")
    if landed and landed[0] not in EXPECTED_FONTS:
        warnings.append(f"🔴 字体没落在预期字族上：实际拿去光栅化的是 {landed[0]}（全部命中：{landed}），"
                        f"预期 {list(EXPECTED_FONTS)} 之一。字宽一变，hero 的线性求解会解出**另一个字号**、"
                        f"整幅版式静默漂移——先装字体（apt install fonts-noto-cjk）再出图")
    if fit.get('orn_unknown'):
        warnings.append(f"🔴 陪衬 `{fit['orn_unknown']}` 不在模板 ORN 库里，右下角**什么都没画**。"
                        f"可选：{fit['orn_known']}（注意是连字符不是下划线）")
    if fit.get('hero_glyph_pct_low'):
        lo, hi = fit['hero_glyph_pct_band']
        ml = fit.get('hero_max_line')
        warnings.append(
            f"🔴 hero 字高只占画面高 {fit['hero_glyph_pct_of_h']}%，低于 §2-b 的 {lo}–{hi}%——"
            f"**最长那一行 {ml} 字**（上限 6，想稳在 11% 就 ≤5）。\n"
            f"   ⇒ **重新断行，或把最长那行换成更短的词**；"
            f"⛔ **砍总字数不解决问题**——实测 10 字拆成 3+7 只有 8.00%，"
            f"而 10 字拆成 5+5 有 11.12%。\n"
            f"   ⚠️ 真放不下才把次要半句降到 subtitle 副题层，⛔ 不是调参数。")
    # 上限告警**两个画幅同一句**。⛔ 别再按画幅分岔——分岔是上一版为绕开根因加的：
    # 那时 HERO_MAX 拿 0.86 反推，夹取处字高恒 14.2～14.7%，13% 在横版恒被冲破。
    # 现在 HERO_MAX 由二分实测解出，夹取处字高由构造 ≤13.00%（580 样本实扫，越线 0 个），
    # 于是这条**默认参数下打不出来**，能打出来的只剩「字号被设大了」这一类真异常。
    # 🔴 旧文案「hero 太短（4 字以内），加字让字号落回甜区」已删：修复后 4 字不再超标，
    # 那句话描述的是一个**不会再发生的场景**，留着就是一条误导人去改文案的死文案。
    if fit.get('hero_glyph_pct_high'):
        warnings.append(f"⚠️ hero 字高 {fit['hero_glyph_pct_of_h']}% 冲破 §2-b 上限 "
                        f"{fit['hero_glyph_pct_band'][1]}%（字号 {fit['hero_fs']}px，"
                        f"引擎解出的上限 {fit['hero_max']}px，实测墨迹比 {fit['hero_ink_ratio']}）——"
                        f"⛔ 这条与文案长短无关：字号上限是按「字高＝画面高 13%」在真实字号上二分解出来的，"
                        f"默认参数下顶不破。能顶破只有两种可能：① theme.hero_max 被显式调大了；"
                        f"② 字体没落在 Noto Sans SC 那一族、墨迹比变了。"
                        f"处置＝去掉/调回 theme.hero_max，或核对 font_landed。⛔ 不是改文案")
    # 横版「hero 太短」的真正落点：⛔ 不在字高（夹取区间内字高恒 12.96%），在**占版心宽**。
    # ⛔ 别让「短到版面空」在横版无人看管——字高那条量不出它。
    if fit.get('hero_fill_low'):
        warnings.append(f"⚠️ 横版 hero 只占版心宽 {fit['hero_fill_pct']}%（下限 {fit['hero_fill_min']}%）——"
                        f"横版画布太宽，这么短的 hero 撑不起通栏：大字比副题还窄，焦点不成立"
                        f"（实测 16:9：4 字 35%／5 字 44%／6 字 53%／10 字 87%）。"
                        f"处置＝从金句里多留两三个字。⚠️ 注意这里加字**不会改字号**"
                        f"（横版字号被 HERO_MAX 顶死），它只加宽——横版下加字唯一管用的就是这个维度")
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
    # ⛔ 三条 steps 告警全部先判「有没有 steps」：整份不传 steps 时求解器照样解出一个
    # stepFs，那三条会对着**画面上不存在的层**报红，且处置无从执行（同本次要治的病）。
    has_steps = (fit.get('steps_count') or 0) > 0
    if has_steps and fit.get('step_over_sub'):
        warnings.append(f"🔴 递进行 {fit['step_fs']}px 追平/超过副题 {fit['sub_fs']}px，四级字阶塌成三级")
    if fit.get('hero_below_min'):
        warnings.append(f"🔴 hero 太长：撑满版心只解出 {fit['hero_fs']}px，低于缩略图可读下限 {fit['hero_min']}px"
                        f"（220px 卡片上只剩 {fit['hero_thumb_px']}px，会糊成色块）——"
                        f"版式救不了，只能把 hero 缩短")
    if fit.get('role_below_min'):
        warnings.append(f"身份行被压到 {fit['role_fs']}px 才放得下——把身份行写短一点，或换个更窄的陪衬")
    if fit['hero_squeezed']:
        # ⛔ 处置得跟着「有没有 steps」走：没有递进行时叫人「删递进行的字」是句做不到的话
        cut = ("优先删递进行的字，别削 hero" if has_steps
               else "这份数据没有递进行，超容的是副题——把 subtitle 写短，别削 hero")
        warnings.append(f"递进三行降到下限还塞不下，已回头压 hero 到 {fit['hero_fs']}px——"
                        f"说明整幅文案总量超容，{cut}")
    if has_steps and fit['step_at_floor']:
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
    # ⛔ 豁免必须**看得见**：静默豁免和静默失效只差一个方向——两者都是「闸门没响」，
    # 一个是有意的、一个是坏了，凭证里不写就分不出是哪个。所以豁免了什么、凭什么豁免，
    # 一起打进 stdout 与凭证。空列表也照常出字段，⛔ 别只在非空时才出现（那样竖版的
    # 「一条都没豁免」就成了看不见的默认值，读的人无从确认闸门确实全开着）。
    receipt['exempted'] = exempted
    receipt['exempted_why'] = EXEMPT_WHY if exempted else None
    receipt['exit_code'] = 0
    print(json.dumps({
        'ok': True,
        'gates_ok': not red,
        'landscape': W > H,
        'exempted': exempted,
        'exempted_why': EXEMPT_WHY if exempted else None,
        # 版面上是否真把第 ④ 层收起来了（从 DOM 量来，⛔ 不是这里假定的）。
        # 与 exempted 分开报：一个说「闸门放了行」，一个说「版面真收了」，⛔ 别拿一个当另一个。
        'landscape_layer4_hidden': fit.get('landscape_layer4_hidden'),
        'content_center_pct': fit.get('content_center_pct'),
        'png': str(out_png), 'thumb': thumb, 'html': str(html_path),
        'receipt': write_receipt(receipt_path, receipt),
        'canvas': f'{W}x{H}',
        'font_landed': landed,
        'hero_fs': fit['hero_fs'],
        'hero_lines': fit['hero_lines'],
        'hero_thumb_px': fit['hero_thumb_px'],
        'hero_glyph_px': fit['hero_glyph_px'],
        'hero_glyph_pct_of_h': fit['hero_glyph_pct_of_h'],
        # 判据带与**标定画幅**跟着实测值一起交出去：只看到「14.44% 超了 13%」的人，
        # 无从判断这个 13 对这张画布成不成立——本次翻车的正是这一点。
        'hero_glyph_pct_band': fit['hero_glyph_pct_band'],
        # 上限是**解出来的**不是写死的：把解它用的墨迹比和解出的字号上限一起交出去，
        # 「为什么这张图的上限是 147px」才查得到（⛔ 别让它变成一个不可复核的黑数）。
        'hero_ink_ratio': fit['hero_ink_ratio'],
        'hero_max': fit['hero_max'],
        # 横版才有值（竖版 null）：横版下「hero 太短」的后果落在占宽上，⛔ 不落在字高上
        'hero_fill_pct': fit['hero_fill_pct'],
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

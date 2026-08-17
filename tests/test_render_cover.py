"""render_cover.py 的纯函数、契约与**调用处签名漂移**。

为什么有这个文件（2026-08-17 立）：此前全仓没有一个测试引用 render_cover.py，
于是改 `make_thumb` 签名、调用处忘了跟上，pytest 照样全绿，脚本却一跑就
`TypeError: make_thumb() missing 1 required positional argument`——
「绿必须是被验证过的绿」的标准形状。下面 test_内部调用处的实参个数与函数签名一致
就是专门抓这一类的，纯 ast 静态检查、不起浏览器、毫秒级。

⛔ 照本仓惯例，这里**不跑真渲染**（要浏览器）：出图链路的验收在 SKILL 实跑冒烟里。
"""
import ast
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"
SCRIPT = SCRIPTS / "render_cover.py"
sys.path.insert(0, str(SCRIPTS))

import render_cover as rc  # noqa: E402


# ────────── 调用处签名漂移（这个文件存在的头号理由）──────────

def _call_arity_problems(src: str):
    """把模块内对**本模块自己定义的函数**的调用，逐个拿实参个数对签名。

    只查本模块函数（`foo(...)` 这种裸名调用），⛔ 不碰 `x.foo(...)` 方法调用与外部库。
    """
    tree = ast.parse(src)
    sigs = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            a = node.args
            names = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
            sigs[node.name] = {
                "required": len(a.posonlyargs) + len(a.args) - len(a.defaults),
                "max_pos": None if a.vararg else len(a.posonlyargs) + len(a.args),
                "names": set(names),
                "takes_kwargs": a.kwarg is not None,       # def f(x, **extra)
            }

    problems = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        sig = sigs.get(node.func.id)
        if sig is None or any(isinstance(x, ast.Starred) for x in node.args):
            continue                                        # *args 展开，静态数不出来
        name, where = node.func.id, node.lineno
        n_pos = len(node.args)
        kw = [k.arg for k in node.keywords]
        if sig["max_pos"] is not None and n_pos > sig["max_pos"]:
            problems.append(f"第 {where} 行 {name}() 给了 {n_pos} 个位置实参，最多收 {sig['max_pos']} 个")
        if None in kw:                                      # f(**d) 展开，数不出来
            continue
        if n_pos + sum(1 for k in kw if k in sig["names"]) < sig["required"]:
            problems.append(f"第 {where} 行 {name}() 只给了 {n_pos + len(kw)} 个实参，"
                            f"签名至少要 {sig['required']} 个")
        if not sig["takes_kwargs"]:
            for k in kw:
                if k not in sig["names"]:
                    problems.append(f"第 {where} 行 {name}() 传了签名里没有的关键字 {k}=")
    return problems


def test_内部调用处的实参个数与函数签名一致():
    assert _call_arity_problems(SCRIPT.read_text(encoding="utf-8")) == []


def test_arity检查本身能抓到漏传参数():
    """⛔ 恒绿的闸门等于没有闸门——拿真出过事的那个形状反证它会红。"""
    bad = "def make_thumb(src, width, fmt):\n    return 1\n\ndef main():\n    make_thumb('a', 220)\n"
    assert _call_arity_problems(bad), "漏传 fmt 必须被抓出来"


# ────────── --canvas 解析 ──────────

def test_canvas_收绝对像素():
    assert rc.parse_canvas("1313x559", 999) == (1313, 559, None)


def test_canvas_收比例_高按round宽除比例算():
    # 公众号封面口径：比例恒定、绝对像素随实际宽度走
    assert rc.parse_canvas("2.35:1", 1313) == (1313, 559, 2.35)
    assert rc.parse_canvas("2.35:1", 1500) == (1500, 638, 2.35)


@pytest.mark.parametrize("spec", ["十六比九", "2.35", "0:1", "-1x5", ""])
def test_canvas_看不懂就抛而不是猜一个(spec):
    with pytest.raises(ValueError):
        rc.parse_canvas(spec, 1313)


# ────────── 模板解析：名字 vs 路径 ──────────

@pytest.mark.parametrize("v,is_path", [
    ("still-life", False), ("jinjin", False), ("stilllife", False),
    ("/abs/tpl.html", True), ("tpl-x.html", True), ("a/b", True),
])
def test_名字与路径分得开(v, is_path):
    assert rc.looks_like_path(v) is is_path


def test_两个别名都解析得到真实文件且kind取自模板自报():
    for alias, kind in (("jinjin", "jinjin"), ("still-life", "still-life")):
        path, got = rc.resolve_template(alias)
        assert path.exists(), f"{alias} 指向的模板文件不存在：{path}"
        assert got == kind


def test_still_life模板必须自报kind():
    """kind 认 <meta name="cover-kind">，⛔ 不靠文件名猜——复制改名后文件名就不作数了。"""
    src = rc.TEMPLATES["still-life"].read_text(encoding="utf-8")
    assert 'name="cover-kind" content="still-life"' in src


# ────────── 图标必须来自素材库 ──────────

def test_图标不在库里要报出来而不是静默跳过():
    data = {"icons": ["headphones", "teacup", "lucide:coffee"]}
    unknown, known, sources = rc.load_icons(data)
    assert unknown == ["teacup", "lucide:coffee"], "带 lucide: 前缀的也要拦"
    assert "headphones" in known and len(known) > 50
    assert set(sources) == {"headphones"}


def test_内联进去的svg剥掉了注释():
    """许可证 <!-- --> 留在 <script type="application/json"> 里会撞 HTML 的
    script-data-escaped 解析状态；出处台账真源是 LICENSES.md。"""
    data = {"icons": ["headphones"]}
    rc.load_icons(data)
    svg = data["icons_svg"]["headphones"]
    assert "<!--" not in svg and svg.startswith("<svg")


def test_图标解析来源是绝对路径且落在素材库里():
    data = {"icons": ["coffee"]}
    _, _, sources = rc.load_icons(data)
    p = Path(sources["coffee"])
    assert p.is_absolute() and p.parent == rc.SVG_LIB and p.exists()


# ────────── 出图格式 ──────────

def test_只认三种扩展名():
    assert set(rc.SUFFIX_FORMAT) == {".png", ".jpg", ".jpeg"}
    assert rc.SUFFIX_FORMAT[".jpg"] == rc.SUFFIX_FORMAT[".jpeg"] == "jpeg"


def test_透明像素转jpeg要合成白底不能出黑底():
    """裸 im.convert('RGB') 会把透明算成黑色，整张糊一层黑底。"""
    Image = pytest.importorskip("PIL.Image")
    im = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    im.putpixel((0, 0), (163, 75, 58, 255))
    assert im.convert("RGB").getpixel((2, 2)) == (0, 0, 0), "先证明陷阱确实存在"
    fixed = rc.flatten_for_jpeg(im)
    assert fixed.getpixel((2, 2)) == (255, 255, 255)
    assert fixed.getpixel((0, 0)) == (163, 75, 58), "实色像素不许被动"


# ────────── 与调用方的 CLI 契约 ──────────

def test_help里有调用方要探的四个flag():
    """gen_gzh_images.py 出图前先探 --help，探不到就拒跑（_RENDER_FLAGS_ALWAYS）。"""
    out = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                         capture_output=True, text=True, timeout=60).stdout
    for flag in ("--data", "--out", "--canvas", "--template"):
        assert flag in out, f"--help 里没有 {flag}，调用方会直接拒跑"


def test_模板量具字段与脚本要读的对得上():
    """FIT_KEYS 是脚本硬取的字段，模板里没交回就会 KeyError。
    这里做静态对照，真值在实跑冒烟里（此处不起浏览器）。"""
    src = rc.TEMPLATES["still-life"].read_text(encoding="utf-8")
    missing = [k for k in rc.FIT_KEYS["still-life"] if f"{k}:" not in src]
    assert missing == [], f"模板没交回这些量具：{missing}"


def test_退出码文档与实现是三态():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "return 1 if red else 0" in src, "红灯要退 1（出图了但不合格）"
    assert "return 3" not in src, "3 是历史码，已并入 1"
    assert inspect.getdoc(rc).count("退出码") >= 1


# ══════════ 缩略图存活闸 ══════════
# 为什么有这道闸（2026-08-17 实测）：几何闸门对 cord 全绿（drawn/degenerate 都合格），
# 可读者真正看到的 220px 信息流缩略图上赭红是 **0 个像素**——细线缩到 1/6 落在亚像素上
# 被重采样抹平，而整块着色缩完还是块。闸门量的是这个**后果**，不是"画没画"这个形式。
#
# ⛔ 下面全部喂**手工拼的小图**，不起浏览器、不依赖样张文件存在（本仓惯例）。

PAPER = (247, 242, 233)      # 模板纸底最亮处
ACCENT = (163, 75, 58)       # 模板里的 ACCENT 常量
SLATE = (74, 85, 99)         # 调色板首色 #4A5563——距离判据的头号陷阱


def _img(size, bg, spots=()):
    """拼一张已知成分的小图：底色 bg，再按 [(x, y, 颜色)] 点几个像素。"""
    Image = pytest.importorskip("PIL.Image")
    im = Image.new("RGB", size, bg)
    for x, y, c in spots:
        im.putpixel((x, y), c)
    return im


def _blend(t, fg=ACCENT, bg=PAPER):
    """t 比例的 fg 混 bg——模拟缩放后被稀释的赭红像素。"""
    return tuple(round(fg[i] * t + bg[i] * (1 - t)) for i in range(3))


def test_赭红像素数得准():
    im = _img((20, 10), PAPER, [(x, 3, ACCENT) for x in range(7)])
    assert rc.count_accent_pixels(im) == 7


def test_不能把石板灰静物数成赭红():
    """⛔ 这就是不用欧氏距离的理由：#4A5563 到 #A34B3A 的距离只有 98.5，
    `dist≤100` 会在一张赭红为零的封面上数出 279 个像素（实测），是恒绿的假闸门。"""
    im = _img((20, 10), PAPER, [(x, y, SLATE) for x in range(20) for y in range(10)])
    assert rc.count_accent_pixels(im) == 0, "整幅石板灰不许被数成赭红"


def test_纸底自己不算赭红():
    """纸底最暗处 #E7DBC7 的 r−b 有 32，单看 r−b 会误判；r−g 只有 12，两个都要求才拦得住。"""
    for paper in (PAPER, (241, 234, 221), (231, 219, 199)):
        assert rc.count_accent_pixels(_img((12, 6), paper)) == 0, f"{paper} 不是赭红"


def test_delta是纯度闸_稀释成一抹脏的不算数():
    """缩放后活下来的 cord 像素是 30～45% 的稀释混色，看上去只是一抹脏、不成其为红。
    这个纯度门槛正是「糊成一片」与「真的有一笔」的分界。"""
    im = _img((10, 10), PAPER, [(1, 1, _blend(0.40)), (2, 2, _blend(0.50))])
    assert rc.count_accent_pixels(im) == 0, "四五成的稀释混色不该算赭红还活着"
    im2 = _img((10, 10), PAPER, [(1, 1, _blend(0.70)), (2, 2, _blend(1.0))])
    assert rc.count_accent_pixels(im2) == 2, "七成以上到纯色必须数进来"


def test_墨迹占比与外接框():
    """『主体该多大』是审美的事——这两个数**只报不拦**，但必须报得准。"""
    spots = [(x, y, SLATE) for x in range(20, 30) for y in range(10, 16)]
    m = rc.ink_metrics(_img((100, 50), PAPER, spots))
    assert m["ink_px"] == 60
    assert m["ink_pct"] == 1.2                      # 60 / 5000
    assert (m["bbox_w_pct"], m["bbox_h_pct"]) == (10.0, 12.0)
    assert m["bbox"] == {"x": 20, "y": 10, "w": 10, "h": 6}


def test_纸底不该被算成墨迹():
    """墨迹阈值 luma<200，纸底最暗处 luma≈220——留着这 20 档余量，否则外接框会诈成满画布。"""
    assert rc.ink_metrics(_img((30, 20), (231, 219, 199)))["ink_px"] == 0


def test_存活闸恒在220px上判_不吃thumb参数():
    """--thumb 能被调成 0 或别的宽度；判据宽度要是跟着漂，这道闸就等于可以被参数关掉。"""
    assert rc.FEED_THUMB_W == 220


def test_measure_feed_thumb把任意尺寸的成图缩到220再量(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    src = tmp_path / "big.png"
    im = Image.new("RGB", (1313, 559), PAPER)
    for x in range(400, 700):                        # 一大块赭红，缩完必然还在
        for y in range(200, 400):
            im.putpixel((x, y), ACCENT)
    im.save(src)
    got = rc.measure_feed_thumb(src)
    assert got["ran"] and got["size"] == "220x94" and got["width"] == 220
    assert got["accent_pct"] > rc.ACCENT_MIN_PCT_FEED
    assert got["ink"]["ink_pct"] > 0


def test_凭证要同时给出实测值_阈值_和量它的画布尺寸(tmp_path):
    """⚠️ 只看到「26」和「下限 20」，看不出是"刚好过"还是"稳过"——这次的坑恰恰
    藏在缩略图高度里（220×94 与 220×124 是两套完全不同的分母）。三个数缺一不可。"""
    Image = pytest.importorskip("PIL.Image")
    src = tmp_path / "a.png"
    Image.new("RGB", (1313, 739), PAPER).save(src)       # 16:9
    got = rc.measure_feed_thumb(src)
    assert (got["thumb_w"], got["thumb_h"]) == (220, 124), "缩略图实际尺寸要打进凭证"
    assert got["thumb_px"] == 220 * 124
    assert got["accent_min_pct"] == rc.ACCENT_MIN_PCT_FEED
    assert "accent_pct" in got


# ══════════ cord 语义闸 ══════════

def test_cord挂在带线物件上才放行():
    assert rc.cord_semantic_problem(
        {"drawn": True, "from": "headphones", "to": "coffee"},
        ["headphones", "coffee", "sprout"]) is None


def test_cord挂在不带线的物件上要报红():
    """cover-03 的真实形状：线画在 door-open 上，那条线不属于任何东西。"""
    got = rc.cord_semantic_problem(
        {"drawn": True, "from": "door-open", "to": "route"},
        ["door-open", "route", "clock"])
    assert got and got.startswith("🔴") and "door-open" in got


def test_组里有带线物件但没排在第一位_提示挪位置():
    """线是从第一件垂到第二件的——带线的那件不在首位，红线照样挂错东西。"""
    got = rc.cord_semantic_problem(
        {"drawn": True, "from": "coffee", "to": "headphones"},
        ["coffee", "headphones", "sprout"])
    assert got and "headphones" in got and "第一位" in got


def test_线压根没画时不归这道闸管():
    """cord.drawn=false 另有闸门报（『耳机线没画出来』），⛔ 别一个毛病报两条红。"""
    assert rc.cord_semantic_problem({"drawn": False, "reason": "只有一件"}, ["headphones"]) is None
    assert rc.cord_semantic_problem(None, ["book", "lamp"]) is None


def test_白名单里的图标都真在素材库里():
    """白名单是**手工维护**的（素材库归别的线扩），至少保证它没写错名字、没指向已删的图标。"""
    lib = set(rc.icon_names())
    assert lib, "素材库空了？"
    missing = sorted(rc.CORD_CAPABLE_ICONS - lib)
    assert missing == [], f"白名单点名了素材库里没有的图标：{missing}"


def test_白名单必须写明要人维护():
    """⛔ 别假装它自动：素材库正从 66 枚扩到几万枚，这张表不补就会误判新的带线物件。"""
    src = SCRIPT.read_text(encoding="utf-8")
    head = src.split("CORD_CAPABLE_ICONS = frozenset")[0]
    assert "不会自己长" in head or "需要人来补" in head


# ══════════ 两道闸真的接上了 report_still_life（⛔ 不是另写一遍判断逻辑）══════════

def _fit(**over):
    """一份全绿的 still-life 量具，再按需覆盖成违规样本。"""
    base = {
        "icons": [{"name": "headphones"}, {"name": "coffee"}, {"name": "sprout"}],
        "gaps": [80.0, 60.0], "min_gap": 60.0, "overlap": False,
        "group_ink_w": 599.6, "group_ink_left": 356.7, "group_ink_right": 956.3,
        "margin_left": 356.7, "margin_right": 356.7, "margin_asym_px": 0.0,
        "margin_top": 218.7, "baseline_y": 392.0, "baseline_drawn": True,
        "baseline_align_dev_px": 0.0, "desk_w": 880.0, "desk_overhang_px": 0.0,
        "accent": "cord", "accent_form": "cord", "accent_spots": 1,
        "accent_options": ["cord"], "accent_unknown": None,
        "bg_unknown": None, "bg_known": ["warm-paper"],
        "cord": {"drawn": True, "degenerate": False, "from": "headphones",
                 "to": "coffee", "drop_px": 99.1},
        "out_of_canvas": False, "text_in_canvas": [],
    }
    base.update(over)
    return base


def _run_report(tmp_path, fit, feed, W=1313, H=559):
    """真的调 report_still_life，拿它的退出码与红字——⛔ 不重写一遍判断逻辑，
    否则测的是测试自己，接线断了照样全绿。W/H 默认 2.35:1。"""
    receipt = {}
    code = rc.report_still_life(
        fit, {"ran": True}, feed, ["Noto Sans SC"], [],
        tmp_path / "o.jpg", "", tmp_path / "o.html",
        receipt, tmp_path / "o.meta.json", W, H)
    return code, receipt["warnings"]


def _feed(accent_px, thumb_h=94):
    """⚠️ 分母跟着画幅走：2.35:1 是 220×94，16:9 是 220×124。绝对像素数相同、
    占比却不同——这正是闸门必须判比例而不是判像素数的原因。"""
    total = 220 * thumb_h
    return {"ran": True, "width": 220, "size": f"220x{thumb_h}",
            "thumb_w": 220, "thumb_h": thumb_h, "thumb_px": total,
            "accent_px": accent_px, "accent_pct": round(100.0 * accent_px / total, 3),
            "accent_min_pct": rc.ACCENT_MIN_PCT_FEED, "hue_delta": rc.ACCENT_HUE_DELTA,
            "ink": {"ink_px": 696, "ink_pct": 3.37, "bbox_w_pct": 45.9,
                    "bbox_h_pct": 34.0, "bbox": {"x": 59, "y": 36, "w": 101, "h": 32}}}


def test_赭红在缩略图上没活下来要退1(tmp_path):
    """cover-01 的真实形状：cord 几何全绿（drawn ✓ degenerate ✗），缩略图上却是 0 个像素。"""
    code, warns = _run_report(tmp_path, _fit(), _feed(0))
    assert code == 1
    assert any("信息流缩略图" in w and w.startswith("🔴") for w in warns)


def test_cover02那种整体着色不许被误伤(tmp_path):
    """实测 137px——闸门不能把正常的『指名图标整体着色』判红。"""
    code, warns = _run_report(
        tmp_path,
        _fit(accent="lamp", accent_form="icon", cord=None,
             icons=[{"name": "book"}, {"name": "lamp"}, {"name": "plant-stake"}]),
        _feed(137))
    assert code == 0, f"cover-02 被误伤了：{warns}"
    assert warns == []


@pytest.mark.parametrize("pct,red", [(0.15, True), (0.16, False), (0.17, False)])
def test_闸门就卡在下限上(pct, red, tmp_path):
    px = round(pct / 100 * 20680) + 1                     # 换算成 220×94 上的像素数
    code, _ = _run_report(tmp_path, _fit(), _feed(px))
    assert (code == 1) is red, f"{pct}% 应当{'红' if red else '绿'}"


# ── 画幅回归：同一张图换个画幅换个结论（⛔ 这是已知会漂的那一处）──
# 上一版阈值写的是绝对像素数（20 px @220×94），16:9 的缩略图是 220×124、分母大 32%，
# 同一条 cord 多活下 26 个点就**假绿**了。判比例才不吃这一套。

def test_cord在16比9上必须判红_这是已知会漂的那一处(tmp_path):
    """🔴 实测：cord 在 2.35:1 上 0 个像素、在 16:9 上 26 个像素（0.095%）。
    绝对阈值 20px 会放它过去，比例阈值 0.16% 拦得住。⛔ 别让它漂回来。"""
    code, warns = _run_report(tmp_path, _fit(), _feed(26, thumb_h=124))
    assert code == 1, "cord@16:9 必须红"
    assert any("信息流缩略图" in w and w.startswith("🔴") for w in warns)


def test_同样26个像素在两个画幅上判得一样(tmp_path):
    """26px 在 220×94 上是 0.126%、在 220×124 上是 0.095%——都低于 0.16%，**都该红**。
    绝对像素判据会让它们一个红一个绿，比例判据不会。"""
    for h in (94, 124):
        code, _ = _run_report(tmp_path, _fit(), _feed(26, thumb_h=h))
        assert code == 1, f"220×{h} 上 26px 该红"


def test_阈值必须是比例不是绝对像素数():
    """⛔ 绝对像素数在更高的画幅上会自动变松（分母变大），等于闸门随画幅悄悄放宽。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert not hasattr(rc, "ACCENT_MIN_PX_220"), "旧的绝对像素阈值必须已被移除"
    assert "feed['accent_pct'] < ACCENT_MIN_PCT_FEED" in src


def test_出了标定区间要显式说红绿不作数(tmp_path):
    """⚠️ 上一版就是拿 2.35:1 一档的结论推广到所有画幅才翻的车。
    实测 4:3 上 cord 冒到 0.220% > 0.16% 会假绿——⛔ 不许静默沿用，必须说出来。"""
    code, warns = _run_report(tmp_path, _fit(accent="lamp", accent_form="icon", cord=None),
                              _feed(500, thumb_h=165), W=1313, H=985)      # 4:3
    assert any("标定区间" in w and w.startswith("⚠️") for w in warns)
    assert code == 0, "出界只警告、⛔ 不拦——拦了就成了恒红的闸门"


@pytest.mark.parametrize("w,h", [(1313, 559), (1313, 739), (1313, 657)])
def test_标定区间内不该有越界告警(w, h, tmp_path):
    """2.35:1 / 16:9 / 2:1 都在实测过的区间里，⛔ 别对它们喊狼来了。"""
    _, warns = _run_report(tmp_path, _fit(accent="lamp", accent_form="icon", cord=None),
                           _feed(500, thumb_h=round(220 * h / w)), W=w, H=h)
    assert not any("标定区间" in x for x in warns), f"{w}x{h} 在区间内不该告警"


def test_量不出来时报红而不是跳过(tmp_path):
    """没装 Pillow 就量不了——量不出来的绿是假绿，⛔ 不许静默放行。"""
    code, warns = _run_report(tmp_path, _fit(), {"ran": False, "reason": "没装 Pillow"})
    assert code == 1 and any("假绿" in w for w in warns)


def test_压根没落赭红时不重复报红(tmp_path):
    """accent 都没落成，已有闸门（accent_spots≠1）会报；存活闸⛔ 别再叠一条红。"""
    code, warns = _run_report(
        tmp_path, _fit(accent="", accent_form=None, accent_spots=0, cord=None), _feed(0))
    assert code == 1
    assert not any("信息流缩略图" in w for w in warns), "一个毛病只报一条"


def test_cord语义闸接进了report(tmp_path):
    """cover-03 的真实形状：门上挂了根线，且赭红在缩略图上也没了——两条红都要报。"""
    code, warns = _run_report(
        tmp_path,
        _fit(cord={"drawn": True, "degenerate": False, "from": "door-open",
                   "to": "route", "drop_px": 99.1},
             icons=[{"name": "door-open"}, {"name": "route"}, {"name": "clock"}]),
        _feed(0))
    assert code == 1
    assert any("本来不带线" in w for w in warns)
    assert any("信息流缩略图" in w for w in warns)


def test_墨迹两数只报不拦(tmp_path):
    """『主体该多大』由持量具的排版方自己解，⛔ 闸门不替他拍板——数照报，红不许因它而起。"""
    feed = _feed(137)
    feed["ink"] = {"ink_px": 60, "ink_pct": 0.3, "bbox_w_pct": 8.0,
                   "bbox_h_pct": 6.0, "bbox": {"x": 0, "y": 0, "w": 10, "h": 6}}
    code, warns = _run_report(
        tmp_path, _fit(accent="lamp", accent_form="icon", cord=None), feed)
    assert code == 0 and warns == [], "墨迹小得离谱也不该由闸门拦"


def test_墨迹两数必须进凭证与stdout(tmp_path):
    """做决定的人要看数——量了不报等于没量。"""
    feed = _feed(137)
    receipt = {}
    rc.report_still_life(_fit(accent="lamp", accent_form="icon", cord=None),
                         {"ran": True}, feed, ["Noto Sans SC"], [],
                         tmp_path / "o.jpg", "", tmp_path / "o.html",
                         receipt, tmp_path / "o.meta.json", 1313, 559)
    assert receipt["feed_thumb"] == feed, "凭证里要留下实测"
    assert "'feed_thumb': feed," in SCRIPT.read_text(encoding="utf-8"), "stdout 也要带上"


def test_jinjin版式不量这几个数():
    """jinjin 没有 accent 这个概念——往它的凭证里塞 accent_px 只会让人以为那是个有意义的数。"""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "measure_feed_thumb(out_png) if kind == 'still-life' else None" in src


# ══════════ 横版（视频封面）：豁免第 ④ 层 + 内容组垂直居中 ══════════
# 背景：老板 2026-08-17 16:36 打回两条视频封面——「我要的是封面，不是几个元素的凑数。。。
# 需要封面、标题、金句啊！」。竖版那套四层版式（hero / 递进行 / 头像 / 落款）搬到横版后，
# 第 ③④ 层不存在，弹簧把内容全顶到上方、下半 60% 空白，还误报一条「🔴 缺 avatar」。
#
# ⛔ 这一节的负例（横版**不**豁免 footer / hero 行数、竖版一条都不放松）与正例同等重要：
# 只测「横版会不会通过」，测的是它会不会通过，⛔ 不是它会不会**乱**通过。

TPL_JINJIN = (SCRIPTS.parent / "assets" / "cover-templates" / "tpl-cover-jinjin.html")

_LAND_OK = {"hero": ["你不是想太多"], "subtitle": "深夜停不下来地想", "footer": "NBDpsy 心理科普"}


def _fields(**over):
    d = {"hero": ["标题"], "subtitle": "副题",
         "avatar": "a.jpg", "identity": {"name": "刘琼", "line": "本文作者"},
         "footer": "NBDpsy 心理科普"}
    d.update(over)
    return d


# ────────── 竖版：一条都不许放松（这是「⛔ 竖版一个像素都不许变」的判据面）──────────

def test_竖版缺avatar仍然报红():
    red, exempted = rc.check_fields(_fields(avatar=""), landscape=False)
    assert any("avatar" in w for w in red), "竖版缺头像是真缺陷（首版实测空掉 19.3% 版面）"
    assert exempted == [], "竖版一条都不该被豁免"


@pytest.mark.parametrize("k", ["name", "line"])
def test_竖版缺identity仍然报红(k):
    idn = {"name": "刘琼", "line": "本文作者"}
    idn[k] = ""
    red, exempted = rc.check_fields(_fields(identity=idn), landscape=False)
    assert any(f"identity.{k}" in w for w in red)
    assert exempted == []


def test_不传landscape就按竖版判():
    """⛔ 默认值不许把闸门关掉：漏传参数的调用方必须拿到**严的**那一档。"""
    red, exempted = rc.check_fields(_fields(avatar=""))
    assert any("avatar" in w for w in red), "默认必须是竖版口径"
    assert exempted == []


# ────────── 横版：只豁免第 ④ 层，别的一条不动 ──────────

def test_横版豁免avatar与identity():
    red, exempted = rc.check_fields(dict(_LAND_OK), landscape=True)
    assert exempted == ["avatar", "identity"]
    assert not any("avatar" in w or "identity" in w for w in red), \
        "横版第 ④ 层压根不存在，⛔ 不是「缺了」"
    assert red == [], f"这份数据在横版下该全绿，实际：{red}"


def test_横版不豁免footer():
    """负例：footer 是品牌位，横版照样必须有——豁免⛔ 不是一张免死金牌。"""
    red, exempted = rc.check_fields(dict(_LAND_OK, footer=""), landscape=True)
    assert any("footer" in w for w in red), "横版漏了 footer 必须照报"
    assert exempted == ["avatar", "identity"], "豁免范围⛔ 不许因为别的字段缺了就扩大"


def test_横版不豁免hero行数上限():
    """负例：两行封顶是版式硬约束，与画布方向无关。"""
    red, _ = rc.check_fields(dict(_LAND_OK, hero=["一", "二", "三"]), landscape=True)
    assert any("hero" in w for w in red)


def test_豁免清单是白名单而不是全放行():
    """⛔ 别把「横版」实现成「横版什么都不查」。"""
    red, exempted = rc.check_fields({"hero": ["只有大字"]}, landscape=True)
    assert any("footer" in w for w in red), "横版缺 footer 仍要报"
    assert set(exempted) == {"avatar", "identity"}


def test_check_fields返回二元组():
    """这次真出的事：check_fields 改成返回 (红字, 豁免) 后，调用处仍写着
    `check_fields(data) + resolve_assets(...)`，tuple + list 直接 TypeError，
    **每一张竖版封面都渲不出来**；而 pytest 58 条全绿、0.12s。
    arity 检查抓不到它——实参个数没变，变的是**返回形状**。"""
    out = rc.check_fields(_fields())
    assert isinstance(out, tuple) and len(out) == 2
    assert isinstance(out[0], list) and isinstance(out[1], list)


# ────────── 端到端冒烟：--html-only 走完整个 main()，且⛔ 不需要浏览器 ──────────
# 这一条就是上面那个 TypeError 的克星：它真的把脚本跑起来。
# ⛔ 别用 `python -c "import render_cover"` 代替——导入不经过 main()，照样绿。

def _run(tmp_path, data, *extra):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--data", str(p),
                        "--out", str(tmp_path / "o.png"), "--html-only", *extra],
                       capture_output=True, text=True)
    return r, (json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None)


def test_竖版能真的跑起来(tmp_path):
    r, out = _run(tmp_path, _fields(avatar=""))
    assert r.returncode == 0, f"竖版渲染整条路都断了：\n{r.stderr}"
    assert out["landscape"] is False
    assert out["exempted"] == [], "竖版⛔ 不豁免任何一条"
    assert any("avatar" in w for w in out["warnings"]), "竖版缺头像的红字必须一路传到 stdout"


def test_横版能真的跑起来且豁免写在明面上(tmp_path):
    r, out = _run(tmp_path, dict(_LAND_OK), "--canvas", "1920x1080")
    assert r.returncode == 0, r.stderr
    assert out["landscape"] is True
    assert out["exempted"] == ["avatar", "identity"]
    assert out["exempted_why"], "⛔ 只报字段名不报理由＝读的人分不出「有意放行」还是「闸门坏了」"
    assert not any("avatar" in w for w in out["warnings"]), "横版⛔ 不该再误报缺头像"


def test_豁免判据认最终画布而不是数据里的名义画布(tmp_path):
    """`--canvas` 能把竖版数据翻成横版；体检若排在画布定下来之前就会判反。"""
    _, out = _run(tmp_path, _fields(avatar="", canvas={"w": 876, "h": 1313}),
                  "--canvas", "1920x1080")
    assert out["landscape"] is True and out["exempted"] == ["avatar", "identity"]


# ────────── 几何断言：真起浏览器跑 __fit()，量内容组落在哪 ──────────
# ⚠️ 本文件其余部分照惯例不起浏览器；**唯独居中这件事量不出来就没法验收**——
# 「下半 60% 空白」正是老板打回的那个后果，⛔ 拿静态检查代替等于没验。
# ⛔ 浏览器缺席时 skip：skip ⛔ 不是绿，是「这条没验」。

def _fit_geometry(data, W, H):
    """把模板按真实画布渲一遍并调 __fit()，返回它吐出的量具。"""
    pytest.importorskip("playwright.sync_api",
                        reason="没装 playwright——⛔ 居中几何这条等于没验，别当它绿了")
    from playwright.sync_api import sync_playwright
    data = dict(data, canvas={"w": W, "h": H})
    html = rc.build_html(TPL_JINJIN.read_text(encoding="utf-8"), data)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": W, "height": H})
            pg.set_content(html)
            pg.evaluate("document.fonts.ready")
            fit = pg.evaluate("window.__fit()")
            hidden = pg.evaluate(
                "() => { const e = document.getElementById('bottom');"
                "        return !e || getComputedStyle(e).display === 'none'; }")
            box = pg.evaluate(
                "() => { const r = ['hero','sub'].map(i => document.getElementById(i))"
                "          .filter(Boolean).map(e => e.getBoundingClientRect());"
                "        return {top: Math.min(...r.map(x => x.top)),"
                "                bottom: Math.max(...r.map(x => x.bottom)),"
                "                left: Math.min(...r.map(x => x.left)),"
                "                right: Math.max(...r.map(x => x.right))}; }")
        finally:
            b.close()
    return fit, hidden, box


@pytest.mark.parametrize("W,H", [(1920, 1080), (1280, 720)])
def test_横版内容组垂直居中而不是顶在上边(W, H):
    fit, hidden, box = _fit_geometry(_LAND_OK, W, H)
    assert fit["landscape"] is True
    assert hidden, "第 ④ 层必须整层收起——只豁免闸门却照旧渲染会留下一个半拉子头像层"
    assert fit["landscape_layer4_hidden"] is True
    # 视觉中心略高于几何中心（0.45H），符合阅读习惯；给 ±4% 的活口容字号求解的抖动
    assert 41 <= fit["content_center_pct"] <= 49, \
        f"内容组中心落在 {fit['content_center_pct']}%（改动前实测 24.4%＝顶在上边、下半大片空白）"
    # 正文列宽收在画布的 70–80%：⛔ 别让金句一行拉到贴右边
    col = (box["right"] - box["left"]) / W
    assert 0.70 <= col <= 0.80, f"正文列宽占画布 {col:.1%}，出了 70–80% 的区间"


def test_竖版不走横版那套():
    """负例：竖版必须**整段跳过**——landscape 量具为空、第 ④ 层照常在。"""
    fit, hidden, _box = _fit_geometry(_fields(avatar=""), 876, 1313)
    assert fit["landscape"] is False
    assert fit["content_center_pct"] is None, "竖版⛔ 不该被平移，量具也不该有值"
    assert fit["landscape_layer4_hidden"] is False
    assert not hidden, "竖版第 ④ 层必须照常渲染"


# ══════════ hero 字高判据带：竖版 13% / 横版 15.5%，各标各的 ══════════
# 背景（2026-08-17）：`hero_glyph_pct_high` 在横版下**恒报**，且它给的处置做不到。
# 机制：字号 = min(HERO_MAX, 版心宽/行宽系数, 竖向余量)，HERO_MAX = H×0.13/0.86，
# 而真实墨迹/字号 = 0.955～0.975 ——HERO_MAX 一饱和，字高就恒 ≈14.2～14.7% > 13%。
# 竖版版心只有 756px，≥4 字就轮到宽度约束，所以那条上限只对极短 hero 报、且加字真的管用；
# 横版版心 ≈0.87W，要 ≥11 字宽度才接管，于是 2–10 字**字号分毫不动**，加字对字高零影响。
# 🔴 与 accent 存活闸的 20px 是同一个形状：**常数被搬出了它的标定条件**。
#
# ⛔ 本节每条阈值都配一条「把它改坏 → 必须变红/变绿」的证伪：恒绿的闸门等于没闸门，
# 恒报的闸门更坏（会把人训练成「那条不用看」）。

_LAND_POOL = "你不是想太多只是那句话把你整个人都卷进去了从此夜里再也停不下来了啊"


@pytest.fixture(scope="module")
def _browser():
    """一个模块共用一个 chromium。⛔ 页面**不复用**（见 _fit_band）。"""
    pytest.importorskip("playwright.sync_api",
                        reason="没装 playwright——⛔ 字高标定这一整节等于没验，别当它绿了")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def _cover(n, **over):
    """复刻真实视频封面的数据形态：hero + 副题 + 落款，⛔ 无 steps 层。"""
    d = {"hero": [_LAND_POOL[:n]],
         "subtitle": "深夜停不下来地想，不是你想太多，是你被那句话卷进去了",
         "footer": "NBDpsy 心理科普", "identity": {"name": "NBDpsy", "line": "心理科普"}}
    d.update(over)
    return d


def _fit_band(browser, data, W, H, tpl_patch=None):
    """跑一遍 __fit() 拿量具。tpl_patch=(旧串, 新串) 时先把模板改坏——证伪用。

    ⚠️ **每次都开一张新 page**：同一张 page 连着 set_content 跑第二遍，__fit() 会
    直接抛 `Cannot read properties of null`（2026-08-17 标定时实测），量具变成假失败。
    """
    src = TPL_JINJIN.read_text(encoding="utf-8")
    if tpl_patch:
        old, new = tpl_patch
        assert src.count(old) == 1, f"证伪要改的那句在模板里出现了 {src.count(old)} 次：{old}"
        src = src.replace(old, new)
    pg = browser.new_page(viewport={"width": W, "height": H})
    try:
        pg.set_content(rc.build_html(src, dict(data, canvas={"w": W, "h": H})))
        pg.evaluate("document.fonts.ready")
        return pg.evaluate("window.__fit()")
    finally:
        pg.close()


# ────────── 横版：正常文案不许报，真异常必须报 ──────────

@pytest.mark.parametrize("n", [5, 6, 8])
def test_横版正常文案的字高不报(_browser, n):
    """老板打回的那一条：6–7 字的正常金句被报「hero 太短（4 字以内）」。"""
    fit = _fit_band(_browser, _cover(n), 1920, 1080)
    assert fit["hero_glyph_pct_high"] is False, \
        f"{n} 字横版实测字高 {fit['hero_glyph_pct_of_h']}%，正常文案⛔ 不该报"
    assert fit["hero_glyph_pct_low"] is False
    assert fit["hero_fill_low"] is False, f"{n} 字占版心宽 {fit['hero_fill_pct']}%，够撑"


@pytest.mark.parametrize("W,H", [(1280, 720), (1920, 1080), (2560, 1440)])
def test_横版三档画布同判(_browser, W, H):
    """字高% 只随**宽高比**走，与画布绝对大小无关——三档必须给同一个结论。
    ⛔ 别拿一档的结论推广到所有画幅（accent 闸门就是这么翻的车）。"""
    fit = _fit_band(_browser, _cover(6), W, H)
    assert fit["hero_glyph_pct_high"] is False
    assert 14.0 <= fit["hero_glyph_pct_of_h"] <= 14.8, \
        f"{W}x{H} 实测 {fit['hero_glyph_pct_of_h']}%，出了 HERO_MAX 饱和档的实测带"


def test_横版加字确实不改字号(_browser):
    """这是那条告警「做不到」的直接证据：2→10 字字号分毫不动。
    ⛔ 只要这条还成立，横版就不许再叫人「多留两个字让字号落回甜区」。"""
    fs = [_fit_band(_browser, _cover(n), 1920, 1080)["hero_fs"] for n in (2, 6, 10)]
    assert len(set(fs)) == 1, f"2/6/10 字的字号 {fs} 不再相同——机制变了，本节阈值要重标"


def test_横版超长hero字被压小要报(_browser):
    """真异常①：20 字的 hero，字高 7.5%——这条的处置（砍字降到副题）在横版**成立**。"""
    fit = _fit_band(_browser, _cover(20), 1920, 1080)
    assert fit["hero_glyph_pct_low"] is True, f"20 字实测 {fit['hero_glyph_pct_of_h']}%"
    assert fit["hero_glyph_pct_high"] is False


def test_横版字号被显式调大要报(_browser):
    """真异常②：默认参数下横版字高顶不破 14.74%，能顶破只有 theme.hero_max 被调大
    （或字族换了）。⛔ 这就是「15.5% 不是死闸门」的可达路径。"""
    fit = _fit_band(_browser, _cover(6, theme={"hero_max": 200}), 1920, 1080)
    assert fit["hero_fs"] == 200
    assert fit["hero_glyph_pct_high"] is True, f"实测 {fit['hero_glyph_pct_of_h']}%"


@pytest.mark.parametrize("n,fill_low", [(3, True), (4, True), (6, False), (10, False)])
def test_横版短hero撑不住通栏要报占宽(_browser, n, fill_low):
    """真异常③：横版下「hero 太短」的后果**不落在字高上**（2–10 字恒 14.4%），
    落在占宽上。4 字只占 39%，大字比副题还窄；6 字 59% 起才立得住。"""
    fit = _fit_band(_browser, _cover(n), 1920, 1080)
    assert fit["hero_fill_low"] is fill_low, \
        f"{n} 字占版心宽 {fit['hero_fill_pct']}%（下限 {fit['hero_fill_min']}%）"
    assert fit["hero_glyph_pct_high"] is False, "字高⛔ 不该替占宽背这口锅"


def test_占宽告警只在字号顶在上限时才出(_browser):
    """⛔ 别把「给的处置做不到」换个地方再犯一次：字号已经被压下来时（小画布/带 steps 的横版），
    「加字」只会把字压得更小。实测 876×493 + 三行递进：字号 57 < HERO_MAX 75、占宽 44.9%。"""
    squeezed = _cover(6, steps=["一直复盘白天说错的话", "越想越清醒", "第二天更累"])
    fit = _fit_band(_browser, squeezed, 876, 493)
    assert fit["hero_at_max"] is False and fit["hero_fill_pct"] < 45, \
        f"这个样本本来就该是「压下来且占宽不足」，实测 {fit['hero_fs']}px / {fit['hero_fill_pct']}%"
    assert fit["hero_fill_low"] is False, "字号没顶在上限时⛔ 不许再叫人加字"


def test_判据带与标定画幅一起交出去(_browser):
    """⛔ 别让阈值再变成裸数字：读的人得能当场判断这个数对不对这张画布成立。"""
    land = _fit_band(_browser, _cover(6), 1920, 1080)
    port = _fit_band(_browser, _fields(avatar=""), 876, 1313)
    assert land["hero_glyph_pct_band"] == [9, 15.5]
    assert port["hero_glyph_pct_band"] == [9, 13]
    assert "16:9" in land["hero_glyph_band_canvas"]
    assert "876" in port["hero_glyph_band_canvas"]
    assert port["hero_fill_pct"] is None and port["hero_fill_low"] is None, \
        "竖版⛔ 不判占宽——恒 null，⛔ 不是 0（0 会被读成「量到了，占 0%」）"


# ────────── 竖版三档回归：13%/9% 一个字不许动 ──────────

@pytest.mark.parametrize("n,high,low", [(3, True, False), (5, False, False),
                                        (6, False, False), (8, False, True)])
def test_竖版三档字高判据原样不动(_browser, n, high, low):
    """锁死竖版没被横版那档带偏：3 字仍报上限、5/6 字全绿、8 字仍报下限。"""
    fit = _fit_band(_browser, _cover(n), 876, 1313)
    assert fit["hero_glyph_pct_high"] is high, f"{n} 字竖版实测 {fit['hero_glyph_pct_of_h']}%"
    assert fit["hero_glyph_pct_low"] is low, f"{n} 字竖版实测 {fit['hero_glyph_pct_of_h']}%"


# ────────── 逐条证伪：把阈值改坏，对应的闸门必须变色 ──────────

def test_证伪_横版上限退回13就会恒报(_browser):
    """这条同时是**病症复现**：把横版那档改回竖版的 13，正常 6 字文案立刻恒报。"""
    fit = _fit_band(_browser, _cover(6), 1920, 1080,
                    tpl_patch=("LANDSCAPE ? 15.5 : 13", "LANDSCAPE ? 13 : 13"))
    assert fit["hero_glyph_pct_high"] is True, "改坏了还不红＝这条上限压根没在判"


def test_证伪_竖版上限放到99就不该再报(_browser):
    """竖版那档确实在判 13，⛔ 不是恒报。"""
    fit = _fit_band(_browser, _cover(3), 876, 1313,
                    tpl_patch=("LANDSCAPE ? 15.5 : 13", "LANDSCAPE ? 15.5 : 99"))
    assert fit["hero_glyph_pct_high"] is False, "把上限放到 99 还报＝这条是恒报的假闸门"


def test_证伪_下限清零就不该再报(_browser):
    fit = _fit_band(_browser, _cover(20), 1920, 1080,
                    tpl_patch=("const GLYPH_PCT_LOW  = 9;", "const GLYPH_PCT_LOW  = 0;"))
    assert fit["hero_glyph_pct_low"] is False, "把下限清零还报＝这条是恒报的假闸门"


def test_证伪_占宽下限清零就不该再报(_browser):
    fit = _fit_band(_browser, _cover(3), 1920, 1080,
                    tpl_patch=("const HERO_FILL_MIN = 45;", "const HERO_FILL_MIN = 0;"))
    assert fit["hero_fill_low"] is False, "把占宽下限清零还报＝这条是恒报的假闸门"


def test_证伪_占宽下限抬到100就该连撑满的也报(_browser):
    fit = _fit_band(_browser, _cover(10), 1920, 1080,
                    tpl_patch=("const HERO_FILL_MIN = 45;", "const HERO_FILL_MIN = 100;"))
    assert fit["hero_fill_low"] is True, "把下限抬到 100 还不报＝这条是恒绿的死闸门"


# ────────── 告警文案分岔：横版⛔ 不许再说「hero 太短，加字」 ──────────
# ⛔ 这一段必须走**真脚本**（要出图，所以要 playwright + Pillow）：
# 文案是在 render_cover.py 里拼的，只跑 __fit() 验不到它。

def _run_real(tmp_path, data, *extra):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--data", str(p),
                        "--out", str(tmp_path / "o.png"), *extra],
                       capture_output=True, text=True)
    return r, (json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None)


def _need_render():
    pytest.importorskip("playwright.sync_api", reason="没装 playwright——⛔ 这条等于没验")
    pytest.importorskip("PIL", reason="没装 Pillow——⛔ 这条等于没验")


def test_横版正常文案一条字高告警都不出(tmp_path):
    """老板打回的那张（hero「你不是想太多」1920×1080）现在必须干干净净。"""
    _need_render()
    r, out = _run_real(tmp_path, _cover(6), "--canvas", "1920x1080")
    assert r.returncode == 0, r.stderr
    assert [w for w in out["warnings"] if "字高" in w or "版心宽" in w] == [], \
        f"横版正常文案还在报：{out['warnings']}"
    assert out["hero_glyph_pct_band"] == [9, 15.5]
    assert out["hero_fill_pct"] == pytest.approx(58.6, abs=1.0)


def test_横版上限告警不许再叫人改文案(tmp_path):
    """⛔ 横版这条的处置只能是「调回 theme.hero_max / 核对字体」——
    「多留两个字让字号落回甜区」在横版是**做不到**的动作（字号被 HERO_MAX 顶死）。"""
    _need_render()
    _r, out = _run_real(tmp_path, _cover(6, theme={"hero_max": 200}), "--canvas", "1920x1080")
    hit = [w for w in out["warnings"] if "字高" in w]
    assert len(hit) == 1, f"该报且只报一条，实际：{out['warnings']}"
    assert "hero_max" in hit[0] and "顶不上来" in hit[0]
    for banned in ("太短", "多留两个字", "4 字以内"):
        assert banned not in hit[0], f"横版告警里还留着做不到的处置「{banned}」：{hit[0]}"


def test_横版短hero的处置说清了加字只加宽不改字号(tmp_path):
    """⛔ 「加字」这个动作本身没错，错在上一版把它挂到了字高上。挂到占宽上才是真的。"""
    _need_render()
    _r, out = _run_real(tmp_path, _cover(3), "--canvas", "1920x1080")
    hit = [w for w in out["warnings"] if "版心宽" in w]
    assert len(hit) == 1, f"3 字横版该报占宽，实际：{out['warnings']}"
    assert "不会改字号" in hit[0], "⛔ 不说清这一点，排版方会以为加字能把字高也解掉"


def test_横版下限告警引用的区间也跟着画幅走(tmp_path):
    """下限 9% 两个画幅通用，但**引用的区间**得跟着走——照抄「§2-b 的 9–13%」
    就是在同一条告警里又搬了一次常数。"""
    _need_render()
    _r, out = _run_real(tmp_path, _cover(20), "--canvas", "1920x1080")
    hit = [w for w in out["warnings"] if "字高只占画面高" in w]
    assert len(hit) == 1, f"20 字横版该报下限，实际：{out['warnings']}"
    assert "9–15.5%" in hit[0] and "16:9" in hit[0]
    assert "§2-b 的 9–13%" not in hit[0]


def test_竖版下限告警一个字没动(tmp_path):
    """竖版这条逐字不动：还是「低于 §2-b 的 9–13%」。"""
    _need_render()
    _r, out = _run_real(tmp_path, _cover(9))
    hit = [w for w in out["warnings"] if "字高只占画面高" in w]
    assert len(hit) == 1, f"9 字竖版该报下限，实际：{out['warnings']}"
    assert "低于 §2-b 的 9–13%——hero 太长撑不起来" in hit[0]


def test_竖版上限告警一个字没动(tmp_path):
    """竖版这条是老板验收过的，⛔ 逐字不动——连「hero 太短（4 字以内）」都照旧。"""
    _need_render()
    _r, out = _run_real(tmp_path, _cover(3))
    hit = [w for w in out["warnings"] if "字高" in w]
    assert len(hit) == 1
    assert "hero 太短（4 字以内），撑满版心必然超标" in hit[0]
    assert "冲破 §2-b 上限 13%" in hit[0]
    assert out["hero_fill_pct"] is None, "竖版⛔ 不出占宽这条"


def test_阈值旁边必须写清标定画幅():
    """这次的病根就是**常数被搬出了它的标定条件**。⛔ 别再犯一次：
    判据带那一段代码里必须同时点名两个画幅，否则下一个人还是照搬。"""
    src = TPL_JINJIN.read_text(encoding="utf-8")
    i = src.index("const GLYPH_PCT_LOW")
    block = src[max(0, i - 3000):i]
    assert "876×1313" in block, "上限/下限旁边没写清竖版那档是在 876×1313 上标的"
    assert "16:9" in block, "上限/下限旁边没写清横版那档是在 16:9 上标的"

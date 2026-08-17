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

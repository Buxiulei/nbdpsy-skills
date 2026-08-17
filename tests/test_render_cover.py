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

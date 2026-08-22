"""封面凭证的风格档案校验：**声明的那套** vs **档案库** vs **实际渲出的色**。

为什么有这个文件（2026-08-22 立）：凭证里一直同时躺着 `style_profile`（声明用了哪套）
与 `palette`（实测渲出什么色），而**从来没人把这两个数相减**。字段在、判据在、每次都过
——这是「验了在不在，没验对不对」，连"量不出来"的迹象都不给。
🩸 实证：13 份凭证标着 `图文 v3` 一路绿灯到发布前才被人肉发现，而档案库里「图文」只有 v2。

⛔ 照本仓惯例：不联网、不起浏览器。网络一律 stub。
"""
import ast
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import render_cover as rc  # noqa: E402
import style_profile as sp  # noqa: E402


# ────────── norm_hex：不是颜色的东西**不许**混进调色板 ──────────

@pytest.mark.parametrize("raw,want", [
    ("#A34B3A", "#A34B3A"),
    ("#a34b3a", "#A34B3A"),          # 大小写是同一个颜色
    ("#ABC", "#AABBCC"),             # 三位简写是同一个颜色
    ("A34B3A", "#A34B3A"),           # 缺 # 也认
    ("  #A34B3A  ", "#A34B3A"),
])
def test_norm_hex_认得出的写法(raw, want):
    assert sp.norm_hex(raw) == want


@pytest.mark.parametrize("raw", [
    None, "", "透明", "rgb(163,75,58)",
    "color-mix(in srgb, var(--bg) 60%, #FFF6E9)",   # --paper 就长这样，读不出 hex
    "color(srgb 0.9458 0.8471 0.7686)",             # 当前 Chromium 的 backgroundColor 长这样
    "#A34B3",                                        # 五位，不是颜色
])
def test_norm_hex_不是颜色的一律None(raw):
    """⛔ 绝不能返回原串：那会让"不是颜色"混进调色板参与比对，
    比对不上时人还以为是配色错了——又一次「响错理由」。"""
    assert sp.norm_hex(raw) is None


# ────────── declared_palette：档案**声明**了哪些色 ──────────

CAROUSEL = {"visual": {
    "palette": [{"name": "雾霾蓝灰", "hex": "#A8B5C4"}, {"name": "暖米白", "hex": "#E8D8C4"}],
    "text_color": "#5A6B7B", "accent_color": "#A34B3A"}}


def test_declared_palette_图文那类三处都收():
    assert sp.declared_palette(CAROUSEL) == ["#A8B5C4", "#E8D8C4", "#5A6B7B", "#A34B3A"]


def test_declared_palette_去重保序():
    d = {"visual": {"palette": [{"hex": "#A34B3A"}], "accent_color": "#a34b3a"}}
    assert sp.declared_palette(d) == ["#A34B3A"]


def test_declared_palette_文字版那类读typeset段():
    d = {"typeset": {"bg": "#FFFDF8", "accent": "#A34B3A", "accent_soft": None, "theme": "clean"}}
    assert sp.declared_palette(d) == ["#FFFDF8", "#A34B3A"]


def test_declared_palette_null是合法值不是错():
    """typeset 的 null ＝「听主题的、不覆盖」，⛔ 不是缺字段。跳过即可，别报错也别塞空串。"""
    d = {"typeset": {k: None for k in ("bg", "accent", "accent_soft")}}
    assert sp.declared_palette(d) == []


@pytest.mark.parametrize("bad", [None, "图文 v3", 3, [], {"visual": "不是对象"}])
def test_declared_palette_坏输入不炸(bad):
    assert sp.declared_palette(bad) == []


# ────────── match_palette：判据方向 + 三态 ──────────
#
# 🔴 方向是**「档案声明的 ⊆ 实际渲出的」**，⛔ 不是反过来。
#    实测：jinjin 渲 6 色、档案声明 5 色全中，但模板另有个正当的中性墨蓝 #2B3A4A
#    档案里根本没记。写成「实测 ⊆ 声明」就恒红，而**恒红的闸门等于没有闸门**。

REAL_ACTUAL = ["#E8D8C4", "#A34B3A", "#2B3A4A", "#5A6B7B", "#C9D6CE", "#A8B5C4"]
REAL_DECLARED = ["#A8B5C4", "#E8D8C4", "#C9D6CE", "#5A6B7B", "#A34B3A"]


def test_声明的色全渲出来了就是绿():
    out = rc.match_palette({"declared": REAL_DECLARED}, REAL_ACTUAL)
    assert out["palette_ok"] is True
    assert out["missing_colors"] == []


def test_模板多出的中性色不算错():
    """🔴 **防方向写反的锚**：#2B3A4A 在实测里、不在声明里。
    这条一红就说明有人把判据改成了「实测 ⊆ 声明」——那会让每一张正常的图都报红。"""
    assert "#2B3A4A" in REAL_ACTUAL and "#2B3A4A" not in REAL_DECLARED
    assert rc.match_palette({"declared": REAL_DECLARED}, REAL_ACTUAL)["palette_ok"] is True


def test_档案声明的色没渲出来就是红():
    """模板换了色、档案没跟着更 —— 闸门要**指名道姓**说丢的是哪个色。"""
    mutated = [c for c in REAL_ACTUAL if c != "#C9D6CE"] + ["#B7D1B0"]
    out = rc.match_palette({"declared": REAL_DECLARED}, mutated)
    assert out["palette_ok"] is False
    assert out["missing_colors"] == ["#C9D6CE"]


def test_大小写不影响比对():
    out = rc.match_palette({"declared": ["#a34b3a"]}, ["#A34B3A"])
    assert out["palette_ok"] is True


def test_实测为空是None不是False():
    """🔴 **量不出来 ≠ 不匹配**。still-life 的 :root 里一个 hex 都没有 ⇒ 实测空集。
    把"没量到"说成"不匹配"，是在自造假红。"""
    out = rc.match_palette({"declared": REAL_DECLARED}, [])
    assert out["palette_ok"] is None
    assert out.get("missing_colors") is None


def test_声明为空是None不是True():
    """⛔ 同样不能反过来：档案没声明色 ⇒ 无从比对，记 None。
    记 True 等于让一份什么都没声明的档案拿到一个"配色核过"的绿灯。"""
    assert rc.match_palette({"declared": []}, REAL_ACTUAL)["palette_ok"] is None


# ────────── fetch_declared：404 与「没答上来」是两件事 ──────────

class _StubUnreachable(Exception):
    pass


def test_404版本不存在是found_false(monkeypatch):
    """这正是 13 份凭证那次：套在、版本不在。"""
    monkeypatch.setattr(sp, "call", lambda *a, **k: (_ for _ in ()).throw(
        ValueError("HTTP 404: 风格档案版本 v3 不存在")))
    hit = sp.fetch_declared("图文", "3", "k", "https://x", timeout=1)
    assert hit["found"] is False and "v3 不存在" in hit["reason"]


def test_404套不存在是found_false(monkeypatch):
    monkeypatch.setattr(sp, "call", lambda *a, **k: (_ for _ in ()).throw(
        ValueError("HTTP 404: 风格档案套「查无此套」不存在")))
    assert sp.fetch_declared("查无此套", "1", "k", "https://x", timeout=1)["found"] is False


@pytest.mark.parametrize("err", [
    "HTTP 530: <!doctype html> Cloudflare 源站不可达",   # 🩸 2026-08-22 实测撞上的那个
    "HTTP 502: bad gateway",
    "HTTP 500: internal error",
    "HTTP 400: bad request",
    "HTTP 422: unprocessable",
])
def test_非404一律抛Unreachable而不是说档案错(monkeypatch, err):
    """🔴 **「响错理由」的回归锚**：源站抖一下回 530，首版把它并进「档案库说没有这一版」
    ⇒ 一张完全正常的图被拒渲，红灯却写着「风格档案对不上档案库」。
    照那个红去查，人会去改留痕行、改档案，而**真正的问题是源站挂了**。"""
    monkeypatch.setattr(sp, "call", lambda *a, **k: (_ for _ in ()).throw(ValueError(err)))
    with pytest.raises(sp.Unreachable):
        sp.fetch_declared("图文", "2", "k", "https://x", timeout=1)


def test_v0走默认配置而不是放行(monkeypatch):
    """v0 ＝ 新运营还没有自己的档案（留痕行就写 v0）。它照样有一份调色板可比 ——
    ⛔ 直接放行等于留一个「写 v0 就绕过校验」的洞。"""
    seen = {}

    def fake_call(method, path, *a, **k):
        seen["path"] = path
        return {"profile": CAROUSEL}
    monkeypatch.setattr(sp, "call", fake_call)
    hit = sp.fetch_declared("图文", "0", "k", "https://x", timeout=1)
    assert sp.ADMIN_DEFAULT_PATH in seen["path"], "v0 必须查默认配置，⛔ 不是查 /versions/0"
    assert hit["found"] is True and hit["palette"] == sp.declared_palette(CAROUSEL)


# ────────── check_style_profile：三态，⛔ 不是布尔 ──────────

def test_没声明档案时不核也不拦():
    out = rc.check_style_profile(None)
    assert out["verified"] is None and out["declared"] == []


def test_没配key是没核成不是档案错(monkeypatch):
    """🔴 离线 warn 放行，凭证记 verified:null。
    ⛔ 绝不能记 False —— 那会把「这次没核」说成「档案是错的」，然后拒掉一张好图。"""
    import nbdpsy_common
    monkeypatch.setattr(nbdpsy_common, "get_secret", lambda *a, **k: None)
    out = rc.check_style_profile({"套名": "图文", "version": "2"})
    assert out["verified"] is None
    assert "没核过" in out["reason"] or "没配" in out["reason"]


def test_连不上是没核成不是档案错(monkeypatch):
    monkeypatch.setattr(sp, "fetch_declared", lambda *a, **k: (_ for _ in ()).throw(
        sp.Unreachable("network", "connection refused", "查网络")))
    import nbdpsy_common
    monkeypatch.setattr(nbdpsy_common, "get_secret", lambda *a, **k: "fake-key")
    out = rc.check_style_profile({"套名": "图文", "version": "2"})
    assert out["verified"] is None, "连不上 ≠ 档案错，⛔ 别合并成一件事"


def test_档案库说没有才是False(monkeypatch):
    monkeypatch.setattr(sp, "fetch_declared", lambda *a, **k: {
        "found": False, "reason": "HTTP 404: 风格档案版本 v3 不存在", "profile": None,
        "palette": []})
    import nbdpsy_common
    monkeypatch.setattr(nbdpsy_common, "get_secret", lambda *a, **k: "fake-key")
    assert rc.check_style_profile({"套名": "图文", "version": "3"})["verified"] is False


# ────────── 接线：光有函数没接上，等于没做 ──────────

SRC = (SCRIPTS / "render_cover.py").read_text(encoding="utf-8")


def test_核对发生在起浏览器之前():
    """「拒渲」要名副其实：渲完才说，图已经在磁盘上了。"""
    assert SRC.index("sp_check = check_style_profile(") < SRC.index("sync_playwright()")


def test_verified_False_会拒渲():
    assert "if sp_check['verified'] is False:" in SRC
    tail = SRC[SRC.index("if sp_check['verified'] is False:"):][:400]
    assert "return die(" in tail, "对不上必须 die，⛔ 不是记个 warning 就渲下去"


def test_比色发生在读到实测palette之后():
    assert SRC.index("palette = read_palette(page)") < SRC.index("sp_check = match_palette(")


def test_凭证里带着这次的核对结果():
    assert "'style_profile_check': sp_check" in SRC


def test_没声明档案时整段不写这个键():
    """**缺失 ≠ 值为空**：省略键会让「没声明」与「声明了但没核成」在凭证里长得一样。"""
    assert "**({'style_profile_check': sp_check} if style_profile else {})" in SRC


def test_色值对不上会进warnings():
    assert "sp_check.get('palette_ok') is False" in SRC


def test_没有跳过校验的逃生门():
    """⛔ 不给 `--skip-style-check`：逃生门一开就会变成默认习惯，闸门当场作废。
    离线自动 warn 放行已经是唯一的、且**在凭证里留痕**的那个洞。"""
    tree = ast.parse(SRC)
    flags = {n.args[0].value for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "add_argument"
             and n.args and isinstance(n.args[0], ast.Constant)}
    assert not [f for f in flags if "skip" in f and "style" in f]
    assert "--style-timeout" in flags

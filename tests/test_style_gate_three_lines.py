"""风格档案闸门在**三条封面产线**上的一致性：render_cover / gen_images / typeset_longimage。

三处凭证都写 `style_profile`，此前**没有一处核过它对不对**（形态⑤：验了在不在，没验对不对）。
本文件钉的是「三处口径必须同源」——⛔ 别各写一遍，口径一漂闸门就形同虚设。
"""
import ast
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import gen_images  # noqa: E402
import publish_note as pn  # noqa: E402
import style_profile as sp  # noqa: E402
import typeset_longimage as tl  # noqa: E402

GEN_SRC = (SCRIPTS / "gen_images.py").read_text(encoding="utf-8")
TL_SRC = (SCRIPTS / "typeset_longimage.py").read_text(encoding="utf-8")
RC_SRC = (SCRIPTS / "render_cover.py").read_text(encoding="utf-8")


# ────────── 同源：三处都调那一个函数，⛔ 不各写一遍 ──────────

@pytest.mark.parametrize("src,name", [
    (GEN_SRC, "gen_images"), (TL_SRC, "typeset_longimage"), (RC_SRC, "render_cover")])
def test_三处都用同一个校验函数(src, name):
    assert "verify_declaration" in src, f"{name} 没接上共用校验——口径一漂闸门就形同虚设"


def test_共用函数只有一份实现():
    """⛔ 别复制实现：要同源，就 import 那个函数本身。"""
    impl = [f for f in SCRIPTS.glob("*.py")
            if "def verify_declaration" in f.read_text(encoding="utf-8")]
    assert [f.name for f in impl] == ["style_profile.py"]


# ────────── gen_images：拦在花钱之前 ──────────

def test_gen_images_拦在create_job之前():
    """🔴 出图是**花钱**的。R4 结构闸门就在这个位置「拒跑，⛔ 不出图不烧额度」，
    档案闸门必须并列在它旁边，⛔ 不能等出完图才说。"""
    assert GEN_SRC.index("sp_check = style_gate(") < GEN_SRC.index("jid, sid = create_job(")


def test_gen_images_只有明确说没有才拦():
    """⚠️ 离线/超时/5xx 一律放行——「这次没核成」⛔ 不等于「档案是错的」，
    拿它拦人会拒掉一张好图，而且红灯指向错的地方。"""
    assert 'if sp_check["verified"] is False:' in GEN_SRC


def test_gen_images_拒跑文案要说清没烧额度():
    tail = GEN_SRC[GEN_SRC.index('if sp_check["verified"] is False:'):][:600]
    assert "没烧额度" in tail or "一张图都没出" in tail


def test_复查路径不拦但仍写凭证():
    """⚠️ `--job` 复查时**钱已经花了**，拦了只是让人拿不到图。
    但溯源还是要——所以那条路径自己补核一次，只写凭证不拦人。"""
    assert "if style_check is None:" in GEN_SRC
    i = GEN_SRC.index("if style_check is None:")
    seg = GEN_SRC[max(0, i - 400):i + 200]        # 注释在这一行**之前**
    assert "不用来拦人" in seg or "只为把溯源写进凭证" in seg


def test_gen_images凭证带核对结果():
    assert '"style_profile_check": style_check,' in GEN_SRC


def test_style_gate_没档案时不炸(monkeypatch):
    monkeypatch.setattr(gen_images, "resolve_style_profile", lambda *a, **k: None)
    assert gen_images.style_gate(None, None)["verified"] is None


# ────────── typeset：套名字符串 → {套名, version} ──────────

def test_load_style_meta_从get整份输出取身份(tmp_path):
    """🩸 `load_style` 剥掉 `--get` 外壳时把 `set`/`version` 一起丢了——
    而**身份就在那层壳上**。"""
    f = tmp_path / "wenziban.json"
    f.write_text(json.dumps({"exists": True, "set": "文字版", "version": 1,
                             "profile": {"kind": "typeset", "typeset": {"theme": "clean"}}},
                            ensure_ascii=False), encoding="utf-8")
    assert tl.load_style_meta(f) == {"套名": "文字版", "version": "1"}


def test_load_style_meta_命令行优先(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"set": "文字版", "version": 1}), encoding="utf-8")
    assert tl.load_style_meta(f, "暖米大字 v3") == {"套名": "暖米大字", "version": "3"}


@pytest.mark.parametrize("payload", [
    {"kind": "typeset", "typeset": {"theme": "clean"}},   # 裸单套：没有身份
    {"set": "文字版"},                                     # 有套名没版本
    {"version": 1},                                        # 有版本没套名
    [],
])
def test_load_style_meta_拿不到就空dict(tmp_path, payload):
    """⚠️ 拿不到就返回 `{}` → 凭证里这一项缺 → 闸门 A 拒（fail-closed，与另两处同）。
    ⛔ 别编一个默认值——**错标比缺失更毒**。"""
    f = tmp_path / "x.json"
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert tl.load_style_meta(f) == {}


def test_load_style_meta_文件坏了不炸(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{ 不是 JSON", encoding="utf-8")
    assert tl.load_style_meta(f) == {}


def test_typeset不再从typeset段取name():
    """🩸 typeset 段的键只有 theme/bg/accent/accent_soft/font/title_font/indent/texture
    ——**压根没有 `name`** ⇒ 旧写法 `style_profile` **恒为 null** ⇒ 闸门 A **恒拒**。
    🔴 **一条恒响的闸门等于没有闸门**：这条线的封面此前根本发不出去。"""
    # ⚠️ **判据要抓位置不抓词**：文件里讲那次事故的注释本身就含 `get("name")`，
    #    拿裸子串判会把"讲事故的注释"当成"又犯了那个错"。⇒ 只看**可执行行**。
    code = [ln for ln in TL_SRC.splitlines()
            if 'get("name")' in ln and not ln.lstrip().startswith("#")
            and "原来取的是" not in ln and "于是这条线" not in ln]
    assert not code, f"又从 typeset 段取 name 了：{code}"
    assert "name" not in sp.typeset_skeleton()["typeset"], "骨架变了就得重审这条判据"


def test_typeset凭证带核对结果():
    assert '"style_profile_check": style_check,' in TL_SRC


def test_typeset对不上就拒渲():
    assert 'if _sp_check["verified"] is False:' in TL_SRC
    assert TL_SRC.index("_sp_check = _spmod.verify_declaration") < TL_SRC.index("theme = resolve_theme(")


# ────────── 闸门 A：类型防御 ──────────

def _receipt(tmp_path, style_profile):
    """造一份**能走到 style_profile 判据那一步**的凭证。

    ⚠️ 用 `gen_images` 档：它的必填字段最少却仍**逐项判**，能干净地走到 style_profile 那一行。
    （typeset 档现在也过得去了——见 `test_typeset凭证能过闸门A`——但它走的是另一条分岔，
      拿它测这里会同时验到两件事，红了分不清是哪件坏的。）"""
    cover = tmp_path / "P01.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\n")
    pn.cover_meta_path(cover).write_text(json.dumps({
        "source": "gen_images", "job_id": 1, "session_id": "s1",
        "cover_only": True, "style_profile": style_profile,
        "prompt_excerpt": f"底色 #E8D8C4，{pn.COVER_LAYOUTS[0]}",
    }, ensure_ascii=False), encoding="utf-8")
    return cover


def test_闸门A遇到字符串给拒绝理由而不是崩溃(tmp_path):
    """🩸 `typeset_longimage` 一度把 style_profile 写成**套名字符串**。
    字符串没有 `.get` ⇒ 闸门抛 **AttributeError**。
    ⚠️ 那是**崩溃**不是**拒绝**——给的是一条堆栈，人看不出"凭证格式不对"，
    更看不出该去修哪条产线。"""
    with pytest.raises(ValueError) as e:
        pn.check_cover_receipt(_receipt(tmp_path, "文字版"))
    assert "而不是对象" in str(e.value), "要给能照着修的理由，⛔ 不是 AttributeError"


def test_闸门A仍要求套名和版本都在(tmp_path):
    with pytest.raises(ValueError) as e:
        pn.check_cover_receipt(_receipt(tmp_path, {"套名": "文字版"}))
    assert "套名 + version" in str(e.value)


def test_闸门A对齐全的dict放行(tmp_path):
    """⚠️ 反向也要测：只测"拒"不测"放行"，闸门可能已经变成恒红了。"""
    r = pn.check_cover_receipt(_receipt(tmp_path, {"套名": "文字版", "version": "1"}))
    assert r["ok"] is True and r["style_profile"]["套名"] == "文字版"


def _typeset_receipt(tmp_path, **over):
    """用**产线真函数**造 typeset 凭证，⛔ 不手搓——手搓的凭证证明不了产线真会写成这样。"""
    cover = tmp_path / "P01.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\n")
    tl.write_cover_meta(cover, theme="clean", style_profile={"套名": "文字版", "version": "1"},
                        page_w=1080, page_h=1920, pages=8, theme_over={},
                        style_check={"verified": True, "reason": "ok", "declared": []})
    if over:
        mp = pn.cover_meta_path(cover)
        m = json.loads(mp.read_text(encoding="utf-8")); m.update(over)
        mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return cover


def test_typeset凭证能过闸门A(tmp_path):
    """🩸 **此前这条产线一张封面都发不出去**（第二个恒拒）：`typeset_longimage` 一直在
    `COVER_SOURCES` 白名单里，却**没开分岔** ⇒ 被要求 `confirmed_by`/`confirmed_at`/
    `prompt_excerpt`，而它是确定性排版渲染、**压根没有提示词**。
    ⚠️ 闸门自己的注释当时就写着「⛔ 别对 HTML 路要一段不存在的提示词」——
    **规则写对了，只有一条路被接上**。⇒ 这就是「提醒只保护它点名的那一处」。"""
    r = pn.check_cover_receipt(_typeset_receipt(tmp_path))
    assert r["ok"] is True and r["theme"] == "clean" and r["palette"]


@pytest.mark.parametrize("src_val,extra", [
    ("manual_confirmed", {}),
    ("gen_images", {"job_id": 1, "session_id": "s1"}),
])
def test_豁免不外溢到别的来源(tmp_path, src_val, extra):
    """🔴 豁免只给**确定性渲染**那两条路。⛔ 别让它变成一句"换个 source 就免检"。"""
    with pytest.raises(ValueError):
        pn.check_cover_receipt(_typeset_receipt(tmp_path, source=src_val, **extra))


@pytest.mark.parametrize("over,why", [
    ({"palette": []}, "没有调色板就没有凭据"),
    ({"theme": ""}, "主题是这条路的版式背书"),
    ({"cover_file": "P09.png"}, "张冠李戴"),
    ({"style_profile": {"套名": "文字版"}}, "缺 version 判不了按哪一版出的"),
])
def test_豁免不是旁路(tmp_path, over, why):
    """⚠️ 免的是**确认戳与提示词**，⛔ 不是免凭据——确定性字段一个都不能少。
    「字段缺失＝放行」正是闸门最常见的死法。"""
    with pytest.raises(ValueError):
        pn.check_cover_receipt(_typeset_receipt(tmp_path, **over))


def test_确定性来源免确认戳但只免这两条():
    src = (SCRIPTS / "publish_note.py").read_text(encoding="utf-8")
    assert 'DETERMINISTIC_SOURCES = ("render_cover", "typeset_longimage")' in src
    assert "elif source in DETERMINISTIC_SOURCES:" in src


def test_单出闸只给typeset免不给render_cover免():
    """🩸 首版把 `cover_only` 免除给了整个 `DETERMINISTIC_SOURCES`，
    **连带削弱了 render_cover** —— 而它一次渲染只出一张图，写的 `cover_only: True`
    是**真话**、本来就过得去。⇒ **能靠说真话过的，就别给它开豁免。**
    （被 `test_render_cover_still_needs_style_profile_and_single_out` 当场抓住。）"""
    src = (SCRIPTS / "publish_note.py").read_text(encoding="utf-8")
    i = src.index("confirmed_by = str(meta.get")
    seg = src[i:i + 900]
    assert 'if source == "typeset_longimage":' in seg
    assert "if source in DETERMINISTIC_SOURCES:" not in seg, "又把单出闸免给 render_cover 了"


def test_typeset不谎报cover_only():
    """🔴 **⛔ 不让产线写一个不真实的 `cover_only: True` 混过闸**——它一次出 N 页，那是谎。
    逼产线编一个好看的值来过闸，**正是这条闸门要防的东西本身：造假留痕**。
    ⇒ 宁可在闸门那边显式免除并写明理由。"""
    assert '"cover_only"' not in TL_SRC, "typeset 开始写 cover_only 了——检查是不是在谎报单出"


def test_typeset凭证带得出溯源三件套():
    """确定性渲染没有提示词，凭据换成：**给哪张图 / 哪个主题 / 实际什么色**。"""
    for k in ('"cover_file": png_path.name', '"palette": theme_palette(', '"theme": theme'):
        assert k in TL_SRC, f"凭证少了 {k}"


def test_palette取的是实际生效那份而不是主题默认():
    """⚠️ 档案覆盖了 accent，凭证里就该是覆盖后的色——否则凭证记的是"许诺"不是"实际"。"""
    assert tl.theme_palette("clean")[2] == "#B3282D"
    assert tl.theme_palette("clean", {"accent": "#A34B3A"})[2] == "#A34B3A"


# ────────── 示例串：⛔ 不写"看起来能直接用"的具体值 ──────────

def test_告警与示例里不留可抄的错标组合():
    """🩸 `图文 v3` 是**档案库里不存在的组合**（「图文」只有 v2）。
    2026-08-21 十三份凭证就是把文档里的示例串当真值抄走的，
    而它一度还长在 `gen_images` 的**告警文本**里——人看到告警照抄就错。
    ⚠️ 判据只查**会被当值抄走的位置**，⛔ 不查事故复盘里的引用（那是在讲那次事故）。"""
    for src, name in ((GEN_SRC, "gen_images.py"), (RC_SRC, "render_cover.py")):
        for line in src.splitlines():
            if "图文 v3" not in line:
                continue
            assert any(k in line for k in ("份", "错标", "只有 v2", "当真值抄")), \
                f"{name} 有一处可被照抄的错标示例：{line.strip()[:70]}"

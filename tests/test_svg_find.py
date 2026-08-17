"""svg_find.py 的检索、族别判定、取图与**闸门不被扩库弄松**。

为什么有这个文件（2026-08-17 立）：素材库从 66 个手工件扩到 6 个集合、3 万多枚图标。
扩库最容易出的两类事故，这里各钉一组：
  ① **闸门被弄松**——render_cover.py 只认平铺 `*.svg`，collections/ 在子目录里它看不见。
     要是哪天有人把集合摊平进平铺目录，3 万枚图标就绕过了「必须在台账内」这道校验。
     test_gate_* 就是守这个的。
  ② **「没查到」被当成「没有」**——中文缺词时若静默返回空表，用图的人会以为库里没有，
     转头去 AI 生图。test_zh_missing_* 守的是「必须明说缺的是映射不是图标」。

⛔ 这里不测 happy path 就收工：缺词、坏参数、未入库集合、填充族给线宽参数，都要有预期行为。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "nbdpsy-xiaohongshu-creator"
SCRIPTS = SKILL / "scripts"
SVG_LIB = SKILL / "assets" / "svg-library"
COLL_DIR = SVG_LIB / "collections"
SCRIPT = SCRIPTS / "svg_find.py"
sys.path.insert(0, str(SCRIPTS))

import svg_find as sf  # noqa: E402


def run(*args):
    """跑一次 CLI，交出 (退出码, stdout, stderr)。"""
    p = subprocess.run([sys.executable, str(SCRIPT), *args],
                       capture_output=True, text=True, cwd=str(ROOT))
    return p.returncode, p.stdout, p.stderr


@pytest.fixture(scope="module")
def corpus():
    data, missing = sf.load_all()
    assert not missing, f"集合文件缺失：{missing}"
    manifest, orphans = sf.scan_local()
    return data, manifest, orphans


@pytest.fixture(scope="module")
def name_blob(corpus):
    """全部图标名连成一个大字符串，给「词是否命中」做 C 级子串检索用。"""
    data, _, orphans = corpus
    names = [o["name"] for o in orphans]
    for pack in data.values():
        names += list(pack["icons"].get("icons", {}))
        names += list(pack["icons"].get("aliases", {}))
    return "\n".join(names)


def find(query, corpus, **kw):
    data, manifest, orphans = corpus
    terms = sf.zh_expand(query)[0] if sf.is_chinese(query) else [query.lower()]
    return sf.search(terms, data, manifest, orphans, limit=kw.get("limit", 12))


# ────────── ① 闸门：扩库不许把 render_cover 的校验弄松 ──────────

def test_gate_collections_are_invisible_to_flat_glob():
    """collections/ 下的 3 万枚图标**不得**被 render_cover 的平铺 glob 看见。"""
    import render_cover as rc
    flat = set(rc.icon_names())
    assert len(flat) < 200, (
        f"平铺目录里有 {len(flat)} 个 svg——集合包疑似被摊平进来了，"
        f"闸门等于对 3 万枚图标全开")
    lucide = json.loads((COLL_DIR / "lucide" / "icons.json").read_text(encoding="utf-8"))
    # 随便挑几个集合里有、但没落地过的名字，必须不在平铺目录里
    for n in ["a-arrow-down", "airplay", "album"]:
        assert n in lucide["icons"], f"lucide 里应该有 {n}，集合包可能不完整"
        assert n not in flat, f"{n} 不该出现在平铺目录里（闸门被弄松了）"


def test_gate_still_rejects_unknown_and_prefixed_names():
    """闸门原有的两条判据必须原样保留：不在库报红、带 `前缀:` 的名字报红。"""
    import render_cover as rc
    d = {"icons": ["lucide:coffee", "根本没有这个图", "a-arrow-down"]}
    unknown, known, _ = rc.load_icons(d)
    assert unknown == ["lucide:coffee", "根本没有这个图", "a-arrow-down"], (
        f"闸门放行了本该报红的名字，实际 unknown={unknown}")
    assert "coffee" in known


def test_gate_admits_installed_icons(tmp_path):
    """--install 落地后，同一道闸门必须认得——这是扩库能被 render_cover 用上的唯一通路。"""
    import importlib

    import render_cover as rc
    out = SVG_LIB / "lucide-anchor-gatetest.svg"
    try:
        pack = sf.load_collection("lucide")
        svg, meta = sf.build_svg("lucide", "anchor", pack)
        out.write_text(sf.install_header("lucide", meta, "测试") + svg + "\n",
                       encoding="utf-8")
        importlib.reload(rc)
        unknown, known, sources = rc.load_icons({"icons": [out.stem]})
        assert unknown == [], f"落地件没被闸门认出来：{unknown}"
        assert sources[out.stem] == str(out)
    finally:
        out.unlink(missing_ok=True)


# ────────── ② 检索：中文 / 英文 / 缺词 ──────────

def test_zh_hit(corpus):
    hits = find("咖啡杯", corpus)
    assert hits, "「咖啡杯」应该有命中"
    assert any(h["id"] == "lucide:coffee" for h in hits)


def test_zh_multichar_falls_back_to_shorter_key():
    """「咖啡杯」自身有键；「今天想喝咖啡」没有，得靠子串回退到「咖啡」。"""
    terms, used = sf.zh_expand("今天想喝咖啡")
    assert "coffee" in terms
    assert "咖啡" in used


def test_en_hit(corpus):
    hits = find("coffee", corpus)
    assert hits
    assert all("coffee" in h["name"] for h in hits)


def test_zh_missing_word_says_so_and_exits_1():
    """⛔ 中文缺词必须明说「缺的是映射」，不许静默返回空表当成「库里没有」。"""
    code, out, err = run("霸王别姬")
    assert code == 1, f"缺词该退 1，实际 {code}"
    assert "没有中文映射" in err
    assert "英文" in err
    assert out.strip() == "", f"缺词时不该往 stdout 打结果：{out!r}"


def test_zh_missing_word_json_is_explicit():
    """--json 下同样要能分辨「缺映射」与「真没有」，⛔ 不能只给个空数组。"""
    code, out, err = run("霸王别姬", "--json")
    assert code == 1
    payload = json.loads(out)
    assert payload["zh_mapping"] is False
    assert payload["hits"] == []
    assert "不等于" in payload["reason"]


def test_zh_missing_word_offers_near_keys():
    near = sf.zh_near_misses("咖啡机")
    assert "咖啡" in near or "咖啡杯" in near


def test_en_zero_hit_exits_1_and_says_offline():
    """零命中要说清「本脚本不联网」，⛔ 不假装查过全网。"""
    code, out, err = run("zzzzqqqnothing")
    assert code == 1
    assert "不联网" in err


def test_no_network_flag_exists_nowhere():
    """⛔ 联网兜底**没有实现**，就不许出现假装能联网的开关。"""
    code, out, err = run("--help")
    assert code == 0
    assert "--online" not in out and "--fetch" not in out


# ────────── ③ 许可证：集合级台账靠「用的时候逐条显示」补上 ──────────

def test_every_hit_carries_a_license(corpus):
    for q in ["coffee", "heart", "brain", "plant", "door"]:
        hits = find(q, corpus)
        assert hits, f"{q} 应该有命中"
        for h in hits:
            assert h["license"] and h["license"] != "?", f"{h['id']} 许可证列是空的"


def test_license_comes_from_ledger_not_stale_info_json():
    """⛔ 不采信 info.json：mdi 的 info.json 写着 Apache-2.0，台账才是真源。"""
    info = json.loads((COLL_DIR / "mdi" / "info.json").read_text(encoding="utf-8"))
    assert sf.license_of("mdi", info) == sf.COLL_BY_PREFIX["mdi"]["spdx"]


def test_ledger_has_a_row_for_every_bundled_collection():
    """LICENSES.md 必须逐集合有一行——它是免责依据，漏一个就是裸奔。"""
    text = (SVG_LIB / "LICENSES.md").read_text(encoding="utf-8")
    for c in sf.COLLECTIONS:
        if c["bundled"]:
            assert f"`{c['prefix']}`" in text, f"LICENSES.md 里没有 {c['prefix']} 这一行"


def test_upstream_license_texts_are_kept():
    """MIT / ISC / Apache-2.0 都要求再分发时保留许可证全文。"""
    got = {p.name.split("-")[0] for p in (SVG_LIB / "licenses").glob("*.txt")}
    for c in sf.COLLECTIONS:
        if c["bundled"]:
            key = {"ph": "phosphor"}.get(c["prefix"], c["prefix"])
            assert key in got, f"licenses/ 里缺 {c['prefix']} 的许可证全文，实际有 {got}"


def test_unbundled_collection_is_explicit_not_silent():
    """故意没入库的集合，要能说出为什么 + 怎么加，⛔ 不许查不到就当没有。"""
    ri = sf.COLL_BY_PREFIX["ri"]
    assert ri["bundled"] is False
    assert ri["reason"] and ri["add_cmd"]
    code, out, err = run("--emit", "ri:heart")
    assert code == 2
    assert "没有入库" in err and "要加库" in err


# ────────── ④ 族别标记 ──────────

@pytest.mark.parametrize("spec,want", [
    ("lucide:coffee", sf.FAM_SAME),        # 描边 2/24 = house style
    ("tabler:coffee", sf.FAM_SAME),
    ("iconoir:coffee-cup", sf.FAM_KIN),    # 描边但 1.5，要归一
    ("ph:coffee", sf.FAM_ALIEN),           # 纯填充
    ("mdi:coffee", sf.FAM_ALIEN),
    ("tabler:heart-filled", sf.FAM_ALIEN),  # 同一集合内也有填充件，⛔ 不能按集合一刀切
])
def test_family_classification(spec, want):
    prefix, name = spec.split(":")
    pack = sf.load_collection(prefix)
    icons = pack["icons"]
    spec_d = icons["icons"][name]
    grid = int(spec_d.get("width") or icons.get("width") or 24)
    fam, sw, _ = sf.classify(spec_d["body"], grid)
    assert fam == want, f"{spec} 判成了 {fam}（线宽 {sw}，网格 {grid}）"


def test_fill_family_note_warns_stroke_width_is_locked():
    """填充族的关键差别是「线宽调不动」，标记要把这句说出来。"""
    note = sf.family_note(sf.FAM_ALIEN, None, 256)
    assert "线宽不可调" in note


def test_kin_family_note_asks_for_normalization():
    assert "归一" in sf.family_note(sf.FAM_KIN, 1.5, 24)


def test_family_filter_same_excludes_fill(corpus):
    data, manifest, orphans = corpus
    hits = sf.search(["coffee"], data, manifest, orphans, family_filter="same", limit=30)
    assert hits
    assert all(h["family"] == sf.FAM_SAME for h in hits)
    assert not any(h["prefix"] == "ph" for h in hits)


# ────────── ⑤ 已入库优先 ──────────

def test_installed_icons_are_flagged_with_local_path(corpus):
    hits = find("coffee", corpus)
    top = hits[0]
    assert top["id"] == "lucide:coffee", f"手工件应该排第一，实际第一是 {top['id']}"
    assert top["installed"] == "coffee.svg"
    assert Path(top["installed_path"]).exists()


def test_hand_made_orphans_are_searchable(corpus):
    """自绘件（集合里根本没有）也必须查得到——否则「骨牌」会查空，而库里明明有。"""
    hits = find("骨牌", corpus)
    assert hits, "「骨牌」查空了"
    assert hits[0]["id"] == "local:domino-fall"
    assert hits[0]["installed"] == "domino-fall.svg"
    assert "NBDpsy" in hits[0]["license"]


def test_orphans_are_only_the_self_drawn_ones(corpus):
    """有上游的手工件不该重复成 local: 条目，只应在集合那条上打「已入库」。"""
    _, manifest, orphans = corpus
    names = {o["name"] for o in orphans}
    assert "domino-fall" in names and "plant-stake" in names
    assert "coffee" not in names, "coffee 有上游，不该被当成自绘件"
    assert ("lucide", "coffee") in manifest
    assert ("tabler", "heart-filled") in manifest, "Tabler filled/ 的命名同一化坏了"


# ────────── ⑥ 取图与线宽归一 ──────────

def test_emit_is_parseable_and_carries_class():
    import xml.etree.ElementTree as ET
    code, out, err = run("--emit", "lucide:coffee")
    assert code == 0, err
    root = ET.fromstring(out)
    assert root.tag.endswith("svg")
    assert root.attrib["class"] == "nbd-svg-icon"
    assert root.attrib["viewBox"] == "0 0 24 24"
    assert len(list(root)) > 0, "出来的 SVG 是空壳"


def test_emit_fill_family_uses_currentcolor():
    import xml.etree.ElementTree as ET
    code, out, err = run("--emit", "ph:coffee")
    assert code == 0, err
    root = ET.fromstring(out)
    assert root.attrib["fill"] == "currentColor", "填充族不跟 color 走就没法上品牌色"
    assert root.attrib["viewBox"] == "0 0 256 256", "Phosphor 是 256 网格"


def test_stroke_width_normalization_actually_changes_the_number():
    """⛔ 不能只改根上的数字：body 里的 stroke-width 也得跟着走，否则渲染不变。"""
    code, before, _ = run("--emit", "iconoir:coffee-cup")
    code2, after, _ = run("--emit", "iconoir:coffee-cup", "--stroke-width", "2")
    assert code == 0 and code2 == 0
    assert 'stroke-width="1.5"' in before
    assert 'stroke-width="2"' in after
    assert "1.5" not in re.sub(r'\bd="[^"]*"', "", after), "还有 1.5 的残留线宽没归一"


def test_stroke_width_normalization_keeps_geometry():
    """归一只改线宽，⛔ 不许动路径数据（动了就是变形）。"""
    _, before, _ = run("--emit", "iconoir:coffee-cup")
    _, after, _ = run("--emit", "iconoir:coffee-cup", "--stroke-width", "2")
    paths = lambda s: re.findall(r'\bd="([^"]*)"', s)  # noqa: E731
    assert paths(before) == paths(after)


def test_stroke_width_scales_with_grid():
    """非 24 网格要按比例折算，保证**视觉粗细**一致而不是数字一致。"""
    pack = sf.load_collection("heroicons")
    svg, meta = sf.build_svg("heroicons", "academic-cap", pack, stroke_width=2)
    assert 'viewBox="0 0 24 24"' in svg
    assert meta["stroke_width"] == "2"


def test_fill_family_warns_instead_of_silently_ignoring_stroke_width():
    """⛔ 填充族给了 --stroke-width 不能默默无视——调用方会以为归一成功了。"""
    code, out, err = run("--emit", "ph:coffee", "--stroke-width", "2")
    assert code == 0
    assert "填充族" in err and "无效" in err


def test_emit_resolves_aliases():
    icons = json.loads((COLL_DIR / "lucide" / "icons.json").read_text(encoding="utf-8"))
    alias, parent = next(iter(icons["aliases"].items()))
    pack = sf.load_collection("lucide")
    svg, meta = sf.build_svg("lucide", alias, pack)
    assert svg is not None
    assert meta["resolved"] == parent["parent"]


def test_emit_local_hand_made_file_strips_header():
    code, out, err = run("--emit", "local:domino-fall")
    assert code == 0, err
    assert out.startswith("<svg"), "手工件的版权注释头没剥掉"
    assert "nbd-svg-icon" in out


@pytest.mark.parametrize("args,why", [
    (["--emit", "lucide"], "没写冒号"),
    (["--emit", "nosuchset:heart"], "集合不存在"),
    (["--emit", "lucide:根本没有这个图"], "图标不存在"),
])
def test_emit_bad_input_exits_2(args, why):
    code, out, err = run(*args)
    assert code == 2, f"{why} 该退 2，实际 {code}"
    assert out.strip() == ""


def test_emit_does_not_guess_near_names():
    """⛔ 名字错了就报错，不许自作主张给个相似的——静默换图比报错难查得多。"""
    code, out, err = run("--emit", "lucide:coffeee")
    assert code == 2
    assert "不会替你猜" in err


def test_install_writes_prefixed_filename_and_header(tmp_path):
    out = SVG_LIB / "lucide-lamp-installtest.svg"
    try:
        pack = sf.load_collection("lucide")
        svg, meta = sf.build_svg("lucide", "lamp", pack)
        text = sf.install_header("lucide", meta, "夜里的灯") + svg
        out.write_text(text, encoding="utf-8")
        head = out.read_text(encoding="utf-8")
        assert "NBDpsy 封面素材库" in head
        assert "许可证：ISC" in head
        assert "夜里的灯" in head
        # 落地件的文件头必须能被自己的扫描器重新认出来（否则「已入库」标记会失效）
        manifest, orphans = sf.scan_local()
        assert ("lucide", "lamp") in manifest
        assert "lucide-lamp-installtest" not in {o["name"] for o in orphans}
    finally:
        out.unlink(missing_ok=True)


def test_installed_filenames_never_collide_with_hand_made(corpus):
    """落地件一律带集合前缀，⛔ 不能覆盖同名手工件。"""
    _, manifest, _ = corpus
    for (prefix, name), fname in manifest.items():
        if fname.startswith(f"{prefix}-"):
            assert (SVG_LIB / f"{name}.svg").name != fname


# ────────── ⑦ 中文映射表本身 ──────────

def test_zh_keyword_table_size():
    assert len(sf.ZH_KEYWORDS) >= 300, f"中文映射只有 {len(sf.ZH_KEYWORDS)} 条，说好的 300"


def test_no_dead_zh_keywords(name_blob):
    """每个中文词至少要能落到一个真实存在的图标名上，⛔ 不许有查了必空的死词。"""
    dead = [k for k, terms in sf.ZH_KEYWORDS.items()
            if not any(t in name_blob for t in terms)]
    assert not dead, f"这些中文词映射到的英文名在库里一个都不存在：{dead}"


def test_zh_keyword_terms_are_lowercase_ascii():
    bad = [k for k, terms in sf.ZH_KEYWORDS.items()
           if any(t != t.lower() or not t.isascii() for t in terms)]
    assert not bad, f"这些词的英文映射不是小写 ASCII：{bad}"


def test_zh_keywords_are_actually_chinese():
    bad = [k for k in sf.ZH_KEYWORDS if not sf.is_chinese(k)]
    assert not bad, f"这些键不是中文，放错表了：{bad}"


# ────────── ⑧ 集合完整性 ──────────

def test_bundled_collections_are_on_disk():
    for c in sf.COLLECTIONS:
        d = COLL_DIR / c["prefix"]
        if c["bundled"]:
            assert (d / "icons.json").exists(), f"{c['prefix']} 的 icons.json 缺席"
            assert (d / "info.json").exists(), f"{c['prefix']} 的 info.json 缺席"
        else:
            assert not (d / "icons.json").exists(), (
                f"{c['prefix']} 标着未入库，盘上却有 icons.json——台账与实际打架")


def test_collection_totals_match_ledger():
    """LICENSES.md 上写的图标数必须等于 icons.json 实际数，⛔ 不许是拍脑袋的约数。"""
    text = (SVG_LIB / "LICENSES.md").read_text(encoding="utf-8")
    for c in sf.COLLECTIONS:
        if not c["bundled"]:
            continue
        ic = json.loads((COLL_DIR / c["prefix"] / "icons.json").read_text(encoding="utf-8"))
        n = len(ic.get("icons", {})) + len(ic.get("aliases", {}))
        row = [ln for ln in text.splitlines() if f"`{c['prefix']}`" in ln]
        assert row, f"LICENSES.md 缺 {c['prefix']} 的行"
        assert any(f"{n:,}" in ln or str(n) in ln for ln in row), (
            f"{c['prefix']} 台账上的图标数与实际 {n} 对不上：{row}")


def test_list_collections_reports_unbundled_status():
    code, out, err = run("--list-collections")
    assert code == 0
    assert "未入库" in out
    for c in sf.COLLECTIONS:
        assert c["prefix"] in out


def test_json_output_shape(corpus):
    code, out, err = run("咖啡杯", "--json", "--limit", "3")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["zh_mapping"] is True
    assert payload["count"] <= 3
    for h in payload["hits"]:
        for key in ("id", "license", "family", "family_label", "grid", "installed"):
            assert key in h, f"JSON 少了 {key} 字段"

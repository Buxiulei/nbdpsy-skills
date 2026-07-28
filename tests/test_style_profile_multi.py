"""style_profile.py 多套风格档案（profiles-v1）回归。全程本地 dict + stub，⛔ 绝不打网络。

盯死四条（按翻车概率排序）：

1. **`--get` 不带 `--profile` / `--kind` 时的输出与多套化之前一模一样**——老格式原样、新格式给
   active 那套，且不许多漏一个新键出去。创作端 / 审查端 / guide / pipeline 四处都按老键读，
   这条一破就是全线断链，所以下面用「整份键集合相等」钉死，不是只挑几个字段看。
2. **老格式只读不写回**：没有 `schema` 键的存量档案读成一套「图文」，读操作一个请求都不该发 PUT。
3. **删到只剩一套要拒**：把运营的风格清空是不可逆的。
4. 写操作照旧强制 `--base-version`，且版本号对不上时**连 PUT 都不发**（提前拦成 409 口径）。
5. **`--put` 不许拿一份单套 body 覆盖多套档案**（第十节）：这是「裸 `--get` → 改 → `--put`」的
   必然产物，从前 exit 0 报「✓ 已整份覆盖」而其余几套永久消失，事后只有 `dropped_keys` 一个信号，
   且它给的补救话术恰恰就是产生这份坏 body 的那条命令（死循环）。现在必须**拒绝 + 一个 PUT 都不发**。
6. **`--version N` 能配 `--profile` / `--kind` 取到单套**（第十一节）：审查端按留痕行取回某一版再读
   `profile.visual.*`，多套化后整份容器里这一路恒 undefined。挑套必须与 `--get` 走同一份实现。
7. **合法多套容器不许被误报 density 缺失**（第十二节）：容器顶层本来就没有 density 段，
   每次正确操作都甩假警报 = 狼来了，运营以后就不看这条警告了。
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import pytest

import style_profile as sp

# 老的平铺单套（线上真实档案 v3 就是这个形状：顶层 visual/density/tone/structure）
FLAT = {
    "visual": {"palette": [{"name": "雾霾蓝灰", "hex": "#A8B5C4"}], "text_color": "#5A6B7B",
               "character_card": "短发女性，米色针织衫"},
    "density": {"信息密度档位": "默认", "每页文字量": "200–400 字", "每页信息点": "6–10 个",
                "版式档": "满版", "运营原话": "—"},
    "tone": {"person": "第二人称", "emoji_target": "8–14"},
    "structure": {"title_structure": "痛点 + 数字", "hook_type": "提问", "ending": "邀请评论"},
}

CAROUSEL_SET = dict(FLAT, kind="carousel")
TYPESET_SET = {
    "kind": "typeset",
    "typeset": {"theme": "paper", "bg": None, "accent": "#3A4A7A", "accent_soft": None,
                "font": "serif", "title_font": "kai", "indent": True, "texture": "paper"},
    "tone": {"person": "第二人称", "emoji_target": "0–2"},
    "structure": {"title_structure": "书名号 + 副题", "hook_type": "引言", "ending": "留白"},
}


def multi(active="图文", sets=None) -> dict:
    """造一份多套容器（每次新建副本，免得测试之间互相污染）。"""
    if sets is None:
        sets = {"图文": json.loads(json.dumps(CAROUSEL_SET)),
                "文字版": json.loads(json.dumps(TYPESET_SET))}
    return {"schema": "profiles-v1", "active": active, "profiles": sets}


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    @property
    def text(self):
        return json.dumps(self._body, ensure_ascii=False)

    def json(self):
        return self._body


def _main_ok(monkeypatch, capsys, argv, responses=None, sender=None, key="k"):
    """正常路径（main() 不 sys.exit）。返回 (stdout JSON, stderr, 调用记录)。"""
    calls = []
    monkeypatch.setattr(sys, "argv", ["style_profile.py", "--api-base", "https://stub.test"] + argv)
    monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: key)

    def default_sender(method, url, k, payload=None, timeout=30):
        calls.append({"method": method, "url": url, "payload": payload})
        return responses[len(calls) - 1]

    monkeypatch.setattr(sp, "send_request", sender or default_sender)
    sp.main()
    cap = capsys.readouterr()
    return json.loads(cap.out.strip().splitlines()[-1]), cap.err, calls


def _run(monkeypatch, capsys, argv, responses=None, key="k"):
    """失败路径（main() sys.exit）。返回 (stdout JSON 或 None, exit code, stderr, 调用记录)。"""
    calls = []
    monkeypatch.setattr(sys, "argv", ["style_profile.py", "--api-base", "https://stub.test"] + argv)
    monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: key)

    def default_sender(method, url, k, payload=None, timeout=30):
        calls.append({"method": method, "url": url, "payload": payload})
        return responses[len(calls) - 1]

    monkeypatch.setattr(sp, "send_request", default_sender)
    with pytest.raises(SystemExit) as ei:
        sp.main()
    cap = capsys.readouterr()
    out = json.loads(cap.out.strip().splitlines()[-1]) if cap.out.strip() else None
    return out, ei.value.code, cap.err, calls


def _get(body):
    return _Resp(200, body)


def _puts(calls):
    return [c for c in calls if c["method"] == "PUT"]


# ============================ 一、纯函数：读（只读，不写回） ============================

def test_legacy_flat_reads_as_one_carousel_set():
    """没有 schema 键 = 老格式：读成一套「图文」（kind=carousel），且**内容原样**。"""
    assert sp.is_multi(FLAT) is False
    v = sp.profiles_view(FLAT)
    assert v["legacy"] is True and v["active"] == "图文" and list(v["sets"]) == ["图文"]
    assert v["sets"]["图文"] is FLAT          # 同一个对象，没复制没改写
    assert "kind" not in FLAT                 # ⛔ 绝不往老档案里注入 kind（--get 就不是原档案了）
    assert sp.set_kind(FLAT) == "carousel"    # 形态靠默认判定，不靠改数据


def test_legacy_list_sets_shows_exactly_one():
    listing = sp.list_sets(FLAT)
    assert listing == {"legacy": True, "active": "图文",
                       "profiles": [{"name": "图文", "kind": "carousel", "active": True}]}


def test_multi_list_sets_marks_active():
    listing = sp.list_sets(multi(active="文字版"))
    assert listing["legacy"] is False and listing["active"] == "文字版"
    assert listing["profiles"] == [{"name": "图文", "kind": "carousel", "active": False},
                                   {"name": "文字版", "kind": "typeset", "active": True}]


def test_select_default_is_active_set():
    """不给 name / kind = active 那套（这就是 --get 不带新参数时走的那条路）。"""
    sel = sp.select_set(multi(active="文字版"))
    assert sel["outcome"] == "ok" and sel["name"] == "文字版" and sel["kind"] == "typeset"
    assert sel["content"]["typeset"]["theme"] == "paper"


def test_select_by_kind_prefers_active_when_kind_matches():
    sets = {"图文A": dict(CAROUSEL_SET), "图文B": dict(CAROUSEL_SET, note="B")}
    sel = sp.select_set(multi(active="图文B", sets=sets), kind="carousel")
    assert sel["name"] == "图文B", "active 的 kind 对得上就用 active，别每次都拿第一套"


def test_select_by_kind_falls_back_to_first_of_that_kind():
    """active 是图文那套、但要的是文字版 → 取该 kind 的第一套。"""
    sel = sp.select_set(multi(active="图文"), kind="typeset")
    assert sel["outcome"] == "ok" and sel["name"] == "文字版" and sel["kind"] == "typeset"


def test_select_by_kind_no_match_returns_none():
    """一套都没有 → content=None，由上层提示可以新建（不是报错，也不许静默拿别的形态顶包）。"""
    sel = sp.select_set(FLAT, kind="typeset")
    assert sel["outcome"] == "no_kind_match" and sel["content"] is None and sel["name"] is None
    assert sel["names"] == ["图文"]


def test_select_by_name_hit_and_miss():
    m = multi()
    assert sp.select_set(m, name="文字版")["content"]["kind"] == "typeset"
    miss = sp.select_set(m, name="水墨风")
    assert miss["outcome"] == "not_found" and miss["content"] is None
    assert miss["names"] == ["图文", "文字版"]


def test_active_pointing_at_missing_set_falls_back_to_first():
    """active 指了个不存在的名字（人工改坏 / 删剩的残留）：退到第一套，别整份读空。"""
    sel = sp.select_set(multi(active="早没了"))
    assert sel["outcome"] == "ok" and sel["name"] == "图文" and sel["active"] == "图文"


def test_reading_never_mutates_the_stored_profile():
    """读操作不许改原 dict——老格式一旦被读改，下一次 --put 就把改动带上去了。"""
    before = json.dumps(FLAT, ensure_ascii=False, sort_keys=True)
    sp.profiles_view(FLAT), sp.list_sets(FLAT), sp.select_set(FLAT, kind="typeset")
    assert json.dumps(FLAT, ensure_ascii=False, sort_keys=True) == before


# ============================ 二、纯函数：写（迁移与四个动作） ============================

def test_to_multi_migrates_flat_content_verbatim():
    """迁移 = 原内容整块挪进「图文」，一个字不改，只加 kind。"""
    container, migrated = sp.to_multi(FLAT)
    assert migrated is True
    assert container["schema"] == "profiles-v1" and container["active"] == "图文"
    inner = container["profiles"]["图文"]
    assert inner["kind"] == "carousel"
    assert {k: v for k, v in inner.items() if k != "kind"} == FLAT
    assert "kind" not in FLAT, "to_multi 不许改调用方传进来的原 dict"


def test_to_multi_is_noop_on_multi_format():
    container, migrated = sp.to_multi(multi())
    assert migrated is False and list(container["profiles"]) == ["图文", "文字版"]


def test_to_multi_repairs_dangling_active():
    container, _ = sp.to_multi(multi(active="早没了"))
    assert container["active"] == "图文"


def test_typeset_skeleton_is_clean_theme_with_nulls_and_inherited_tone():
    """契约定死的骨架：theme=clean、其余 7 个 null（null = 听主题的，不覆盖）；tone/structure 沿用图文。"""
    sk = sp.typeset_skeleton(FLAT["tone"], FLAT["structure"])
    assert sk["kind"] == "typeset"
    assert sk["typeset"]["theme"] == "clean"
    assert set(sk["typeset"]) == {"theme", "bg", "accent", "accent_soft", "font",
                                  "title_font", "indent", "texture"}
    assert all(sk["typeset"][k] is None for k in sp.TYPESET_NULLABLE)
    assert sk["tone"] == FLAT["tone"] and sk["structure"] == FLAT["structure"]
    assert sk["tone"] is not FLAT["tone"], "要拷一份，别与图文那套共享同一个 dict"
    assert "visual" not in sk and "density" not in sk  # 文字版没有插画、没有信息点


def test_carousel_skeleton_comes_from_default_config():
    """图文骨架 = --get-default 那份，⛔ 不自己编一份。"""
    sk = sp.carousel_skeleton(FLAT)
    assert sk == dict(FLAT, kind="carousel")
    # 默认配置万一自己也是多套容器，取它 active 那套
    assert sp.carousel_skeleton(multi(active="图文"))["visual"] == FLAT["visual"]


def test_add_rename_delete_set_active():
    c, _ = sp.to_multi(multi())
    sp.add_set(c, "水墨风", "carousel", {"visual": {"texture": "宣纸"}})
    assert c["profiles"]["水墨风"]["kind"] == "carousel"
    sp.set_active_set(c, "水墨风")
    assert c["active"] == "水墨风"
    sp.rename_set(c, "水墨风", "国风")
    assert "水墨风" not in c["profiles"] and c["active"] == "国风"
    assert list(c["profiles"]) == ["图文", "文字版", "国风"], "改名不该把它挪到最后"
    sp.delete_set(c, "国风")
    assert c["active"] == "图文", "删掉默认那套后，默认要顺延到剩下的第一套"


def test_delete_last_set_is_refused():
    """⛔ 删到只剩一套时拒绝——一套不剩等于把运营清空了，且不可撤销。"""
    c, _ = sp.to_multi(FLAT)
    with pytest.raises(ValueError, match="最后一套"):
        sp.delete_set(c, "图文")
    assert list(c["profiles"]) == ["图文"], "拒绝之后容器要原封不动"


def test_add_duplicate_name_is_refused():
    c, _ = sp.to_multi(multi())
    with pytest.raises(ValueError, match="已经有一套"):
        sp.add_set(c, "文字版", "typeset", {"typeset": {"theme": "clean"}})


def test_rename_and_delete_unknown_name_refused():
    c, _ = sp.to_multi(multi())
    with pytest.raises(ValueError, match="没有叫"):
        sp.rename_set(c, "不存在", "新名")
    with pytest.raises(ValueError, match="已经有一套"):
        sp.rename_set(c, "图文", "文字版")
    with pytest.raises(ValueError, match="没有叫"):
        sp.delete_set(c, "不存在")
    with pytest.raises(ValueError, match="没有叫"):
        sp.set_active_set(c, "不存在")


def test_container_warnings_only_checks_carousel_sets():
    """density 五个中文 key 只对图文那类套查——拿它去要求文字版是误报（狼来了）。"""
    c = multi(sets={"图文": dict(CAROUSEL_SET), "文字版": dict(TYPESET_SET)})
    assert sp.container_warnings(c) == []
    bad = multi(sets={"图文": {"kind": "carousel", "density": {"level": "默认"}},
                      "文字版": dict(TYPESET_SET)})
    w = "；".join(sp.container_warnings(bad))
    assert "「图文」这套" in w and "信息密度档位" in w and "文字版" not in w


def test_load_set_file_rejects_whole_container(tmp_path):
    """--file 只收**一套**；喂整份多套档案会套娃出一个坏档案。"""
    f = tmp_path / "c.json"
    f.write_text(json.dumps(multi(), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="整份多套档案"):
        sp.load_set_file(f)


def test_load_set_file_unwraps_get_envelope(tmp_path, capsys):
    f = tmp_path / "e.json"
    f.write_text(json.dumps({"exists": True, "version": 3, "profile": TYPESET_SET},
                            ensure_ascii=False), encoding="utf-8")
    assert sp.load_set_file(f) == TYPESET_SET


# ================= 三、CLI：--get 不带新参数，行为与多套化之前一模一样 =================

OLD_KEYS = {"exists", "version", "source", "note", "updated_at", "profile",
            "base_version", "base_version_source", "layer", "say", "trace_line"}
NEW_KEYS = {"profile_name", "profile_kind", "active_profile", "profile_names",
            "outcome", "profiles_legacy"}


def test_get_no_args_on_legacy_is_unchanged(monkeypatch, capsys):
    """老格式 + 裸 --get：profile 原样、留痕行不带套名、**一个新键都不许漏出去**。"""
    body = {"exists": True, "version": 3, "source": "manual", "note": None,
            "updated_at": "2026-07-27T10:00:00", "profile": FLAT}
    out, err, calls = _main_ok(monkeypatch, capsys, ["--get"], [_get(body)])
    assert len(calls) == 1 and calls[0]["method"] == "GET"   # 读操作绝不写回
    assert out["profile"] == FLAT
    assert out["say"] == "这是你的风格档案（v3），我回读一遍，你确认下"
    assert out["trace_line"].startswith("风格档案：v3（本人档案，读取于 ")
    assert set(out) == OLD_KEYS
    assert not (set(out) & NEW_KEYS), "裸 --get 的键集合必须与多套化之前完全一致"


def test_get_no_args_on_multi_returns_active_set_content(monkeypatch, capsys):
    """新格式 + 裸 --get：给 active 那套的**内容**（不是整个容器），键集合照旧。"""
    body = {"exists": True, "version": 5, "source": "manual", "note": None,
            "updated_at": "2026-07-28T10:00:00", "profile": multi(active="图文")}
    out, err, _ = _main_ok(monkeypatch, capsys, ["--get"], [_get(body)])
    assert out["profile"] == CAROUSEL_SET
    assert "schema" not in out["profile"] and "profiles" not in out["profile"]
    assert out["trace_line"].startswith("风格档案：v5（本人档案，读取于 ")
    assert set(out) == OLD_KEYS


def test_get_no_args_on_multi_active_typeset(monkeypatch, capsys):
    """active 是文字版那套时，裸 --get 就给文字版那套（active 是「没点明形态时的兜底」）。"""
    body = {"exists": True, "version": 5, "profile": multi(active="文字版")}
    out, _, _ = _main_ok(monkeypatch, capsys, ["--get"], [_get(body)])
    assert out["profile"] == TYPESET_SET


def test_get_no_args_exists_false_unchanged(monkeypatch, capsys):
    """exists:false 的两句话与 base_version=0 也一字不动。"""
    body = {"exists": False, "profile": FLAT}
    out, err, _ = _main_ok(monkeypatch, capsys, ["--get"], [_get(body)])
    assert out["say"] == "你还没有自己的风格档案，先用默认配置，可以吗？"
    assert out["base_version"] == 0 and out["profile"] == FLAT
    assert out["trace_line"].startswith("风格档案：v0（默认配置，读取于 ")
    assert not (set(out) & NEW_KEYS)


# ============================ 四、CLI：--get --profile / --kind ============================

def test_get_by_kind_typeset(monkeypatch, capsys):
    body = {"exists": True, "version": 6, "profile": multi(active="图文")}
    out, err, calls = _main_ok(monkeypatch, capsys, ["--get", "--kind", "typeset"], [_get(body)])
    assert len(calls) == 1 and calls[0]["method"] == "GET"
    assert out["profile"] == TYPESET_SET and out["outcome"] == "ok"
    assert out["profile_name"] == "文字版" and out["profile_kind"] == "typeset"
    assert out["active_profile"] == "图文" and out["profile_names"] == ["图文", "文字版"]
    # 留痕行加套名（审查端按这一行认版本），say 保持契约那句逐字不动
    assert out["trace_line"].startswith("风格档案：文字版 v6（本人档案，读取于 ")
    assert out["say"] == "这是你的风格档案（v6），我回读一遍，你确认下"
    assert "文字版" in err


def test_get_by_kind_carousel_on_legacy_returns_flat_verbatim(monkeypatch, capsys):
    """老格式按图文形态取 → 就是原来那份平铺内容（没被注入 kind），留痕行带套名「图文」。"""
    body = {"exists": True, "version": 3, "profile": FLAT}
    out, err, _ = _main_ok(monkeypatch, capsys, ["--get", "--kind", "carousel"], [_get(body)])
    assert out["profile"] == FLAT and "kind" not in out["profile"]
    assert out["profile_name"] == "图文" and out["profiles_legacy"] is True
    assert out["trace_line"].startswith("风格档案：图文 v3（本人档案，读取于 ")
    assert "只读不改" in err


def test_get_by_kind_no_match_returns_null_profile_and_exit_0(monkeypatch, capsys):
    """一套都没有 → profile:null + 提示可新建 + 留痕落到「内置兜底」（实际会用内置默认风格）。"""
    body = {"exists": True, "version": 3, "profile": FLAT}
    out, err, calls = _main_ok(monkeypatch, capsys, ["--get", "--kind", "typeset"], [_get(body)])
    assert out["profile"] is None and out["outcome"] == "no_kind_match"
    assert out["profile_name"] is None and out["profile_names"] == ["图文"]
    assert "还没有「文字版」那套风格" in out["say"] and "建一套" in out["say"]
    assert out["layer"] == "builtin_fallback" and out["reason"] == "no_kind_match"
    # 留痕行必须带上「他要的那套」的名字：审查端把**没有套名**的行当存量批次按「图文」判，
    # 文字版的批次留一行没名的，就会被拿图文的标准去判（配色/信息点全对不上）
    assert out["trace_line"].startswith("风格档案：文字版 v—（内置兜底")
    assert len(calls) == 1, "没挑中也绝不能顺手写回一套"


def test_get_by_name_hit_and_miss(monkeypatch, capsys):
    body = {"exists": True, "version": 7, "profile": multi()}
    out, _, _ = _main_ok(monkeypatch, capsys, ["--get", "--profile", "文字版"], [_get(body)])
    assert out["profile"] == TYPESET_SET and out["profile_name"] == "文字版"
    assert out["trace_line"].startswith("风格档案：文字版 v7（本人档案，读取于 ")

    miss, err, _ = _main_ok(monkeypatch, capsys, ["--get", "--profile", "水墨风"], [_get(body)])
    assert miss["profile"] is None and miss["outcome"] == "not_found"
    assert "没有「水墨风」这一套" in miss["say"] and "图文、文字版" in miss["say"]
    assert miss["layer"] == "builtin_fallback"


def test_get_by_kind_on_admin_default_keeps_say_missing(monkeypatch, capsys):
    """exists:false 时按形态取也照样能取（默认配置读成一套图文），那两句话不许串。"""
    body = {"exists": False, "profile": FLAT}
    out, err, _ = _main_ok(monkeypatch, capsys, ["--get", "--kind", "carousel"], [_get(body)])
    assert out["say"] == "你还没有自己的风格档案，先用默认配置，可以吗？"
    assert out["trace_line"].startswith("风格档案：图文 v0（默认配置，读取于 ")


def test_profile_and_kind_are_mutually_exclusive(monkeypatch, capsys):
    _, code, err, calls = _run(monkeypatch, capsys,
                               ["--get", "--profile", "图文", "--kind", "typeset"], [])
    assert code == 4 and calls == [] and "二选一" in err


def test_profile_flag_only_with_get(monkeypatch, capsys, tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(FLAT, ensure_ascii=False), encoding="utf-8")
    _, code, err, calls = _run(monkeypatch, capsys,
                               ["--put", str(f), "--base-version", "1", "--profile", "图文"], [])
    assert code == 4 and calls == [] and "--profile 只能配 --get" in err


# ============================ 五、CLI：--list-profiles ============================

def test_list_profiles_on_multi(monkeypatch, capsys):
    body = {"exists": True, "version": 5, "profile": multi(active="文字版")}
    out, err, calls = _main_ok(monkeypatch, capsys, ["--list-profiles"], [_get(body)])
    assert len(calls) == 1 and calls[0]["method"] == "GET"
    assert out["count"] == 2 and out["active_profile"] == "文字版"
    assert out["profiles"] == [{"name": "图文", "kind": "carousel", "active": False},
                               {"name": "文字版", "kind": "typeset", "active": True}]
    assert out["base_version"] == 5 and "profile" not in out   # 列表不带全文
    assert "你有 2 套风格" in out["say"] and "文字版" in err


def test_list_profiles_on_legacy_says_one_and_not_migrated(monkeypatch, capsys):
    body = {"exists": True, "version": 3, "profile": FLAT}
    out, err, calls = _main_ok(monkeypatch, capsys, ["--list-profiles"], [_get(body)])
    assert out["count"] == 1 and out["profiles_legacy"] is True
    assert out["profiles"] == [{"name": "图文", "kind": "carousel", "active": True}]
    assert len(calls) == 1, "只读，绝不趁机迁移写回"
    assert "没有动它" in err


def test_list_profiles_exists_false_keeps_say_missing(monkeypatch, capsys):
    """没有个人档案时，say 仍是契约那句逐字不动——绝不能说成「你有 1 套风格」。"""
    out, err, _ = _main_ok(monkeypatch, capsys, ["--list-profiles"],
                           [_get({"exists": False, "profile": FLAT})])
    assert out["say"] == "你还没有自己的风格档案，先用默认配置，可以吗？"
    assert out["count"] == 1 and out["base_version"] == 0


# ============================ 六、CLI：新建一套（三种来源） ============================

def test_new_profile_carousel_uses_default_config_skeleton(monkeypatch, capsys):
    """不给 --from/--file 的图文套 = 默认配置那份骨架（⛔ 别自己编）。"""
    responses = [_get({"exists": True, "version": 3, "profile": multi()}),
                 _get({"admin_default_version": 4, "profile": FLAT}),
                 _get({"exists": True, "version": 4, "dropped_keys": []})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--new-profile", "水墨风", "--kind", "carousel",
                                "--base-version", "3"], responses)
    assert [c["method"] for c in calls] == ["GET", "GET", "PUT"]
    assert calls[1]["url"].endswith("/api/style-profile/admin-default")
    sent = calls[2]["payload"]
    assert sent["base_version"] == 3
    assert sent["profile"]["profiles"]["水墨风"] == dict(FLAT, kind="carousel")
    assert list(sent["profile"]["profiles"]) == ["图文", "文字版", "水墨风"]
    assert sent["profile"]["active"] == "图文", "新建不改默认（要切默认用 --set-active）"
    assert "默认配置 v4 的骨架" in sent["note"]
    assert out["profiles"][-1] == {"name": "水墨风", "kind": "carousel", "active": False}
    assert out["migrated"] is False


def test_new_profile_typeset_inherits_tone_from_his_carousel(monkeypatch, capsys):
    """文字版骨架 = clean 主题 + 沿用他图文那套的 tone/structure；他自己有图文就不必去问默认配置。"""
    responses = [_get({"exists": True, "version": 3, "profile": FLAT}),
                 _get({"exists": True, "version": 4, "dropped_keys": ["visual", "density"]})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--new-profile", "文字版", "--kind", "typeset",
                                "--base-version", "3"], responses)
    assert [c["method"] for c in calls] == ["GET", "PUT"], "有他自己的图文套就别再拉默认配置"
    sets = calls[1]["payload"]["profile"]["profiles"]
    assert sets["文字版"]["typeset"]["theme"] == "clean"
    assert all(sets["文字版"]["typeset"][k] is None for k in sp.TYPESET_NULLABLE)
    assert sets["文字版"]["tone"] == FLAT["tone"]
    assert sets["文字版"]["structure"] == FLAT["structure"]
    # 老格式这一次顺带迁移：原内容原样进「图文」
    assert {k: v for k, v in sets["图文"].items() if k != "kind"} == FLAT
    assert out["migrated"] is True


def test_new_profile_typeset_falls_back_to_default_tone(monkeypatch, capsys):
    """他一套图文都没有（只有文字版）→ 语气去默认配置里取，别留个空 tone。"""
    only_typeset = multi(active="文字版", sets={"文字版": dict(TYPESET_SET)})
    responses = [_get({"exists": True, "version": 3, "profile": only_typeset}),
                 _get({"admin_default_version": 4, "profile": FLAT}),
                 _get({"exists": True, "version": 4})]
    _, err, calls = _main_ok(monkeypatch, capsys,
                             ["--new-profile", "文字版2", "--kind", "typeset",
                              "--base-version", "3"], responses)
    assert [c["method"] for c in calls] == ["GET", "GET", "PUT"]
    assert calls[2]["payload"]["profile"]["profiles"]["文字版2"]["tone"] == FLAT["tone"]


def test_new_profile_from_copies_existing_set(monkeypatch, capsys):
    responses = [_get({"exists": True, "version": 3, "profile": multi()}),
                 _get({"exists": True, "version": 4})]
    _, err, calls = _main_ok(monkeypatch, capsys,
                             ["--new-profile", "图文备份", "--kind", "carousel",
                              "--from", "图文", "--base-version", "3"], responses)
    assert [c["method"] for c in calls] == ["GET", "PUT"]
    sets = calls[1]["payload"]["profile"]["profiles"]
    assert sets["图文备份"] == CAROUSEL_SET and sets["图文"] == CAROUSEL_SET
    assert "复制自「图文」" in calls[1]["payload"]["note"]


def test_new_profile_from_kind_mismatch_is_refused(monkeypatch, capsys):
    """把图文那套复制成文字版 = 造一套字段对不上的坏档案（Owner B 的排版脚本会读空）→ 拒。"""
    responses = [_get({"exists": True, "version": 3, "profile": multi()})]
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "文字版", "--kind", "typeset",
                                  "--from", "图文", "--base-version", "3"], responses)
    assert code == 1 and _puts(calls) == []
    assert "不能复制成" in out["error"]


def test_new_profile_from_file_is_the_reference_sample_path(monkeypatch, capsys, tmp_path):
    """参考图拆解产物走 --file：内容照收，形态以 --kind 为准。"""
    f = tmp_path / "sample.json"
    f.write_text(json.dumps(dict(TYPESET_SET, kind="carousel"), ensure_ascii=False),
                 encoding="utf-8")
    responses = [_get({"exists": True, "version": 3, "profile": multi()}),
                 _get({"exists": True, "version": 4})]
    _, err, calls = _main_ok(monkeypatch, capsys,
                             ["--new-profile", "样刊风", "--kind", "typeset",
                              "--file", str(f), "--base-version", "3",
                              "--source", "reference_sample"], responses)
    sent = calls[1]["payload"]
    assert sent["source"] == "reference_sample"
    assert sent["profile"]["profiles"]["样刊风"]["kind"] == "typeset"   # 命令行说了算
    assert sent["profile"]["profiles"]["样刊风"]["typeset"]["theme"] == "paper"
    assert "按命令行算" in err


def test_new_profile_duplicate_name_refused_before_put(monkeypatch, capsys):
    responses = [_get({"exists": True, "version": 3, "profile": multi()})]
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "文字版", "--kind", "typeset",
                                  "--base-version", "3"], responses)
    assert code == 1 and _puts(calls) == [] and "已经有一套" in out["error"]


def test_new_profile_without_kind_is_usage_error(monkeypatch, capsys):
    _, code, err, calls = _run(monkeypatch, capsys,
                               ["--new-profile", "水墨风", "--base-version", "3"], [])
    assert code == 4 and calls == [] and "--kind" in err


def test_new_profile_without_base_version_sends_nothing(monkeypatch, capsys):
    _, code, err, calls = _run(monkeypatch, capsys,
                               ["--new-profile", "水墨风", "--kind", "carousel"], [])
    assert code == 4 and calls == [] and "--base-version" in err


def test_from_and_file_are_mutually_exclusive(monkeypatch, capsys, tmp_path):
    f = tmp_path / "s.json"
    f.write_text("{}", encoding="utf-8")
    _, code, err, calls = _run(monkeypatch, capsys,
                               ["--new-profile", "x", "--kind", "carousel", "--from", "图文",
                                "--file", str(f), "--base-version", "1"], [])
    assert code == 4 and calls == [] and "二选一" in err


# ============================ 七、CLI：切默认 / 改名 / 删除 ============================

def test_set_active(monkeypatch, capsys):
    responses = [_get({"exists": True, "version": 3, "profile": multi(active="图文")}),
                 _get({"exists": True, "version": 4, "dropped_keys": []})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--set-active", "文字版", "--base-version", "3"], responses)
    assert calls[1]["payload"]["profile"]["active"] == "文字版"
    assert out["active_profile"] == "文字版" and "默认已切到「文字版」" in err


def test_rename_profile_keeps_order_and_follows_active(monkeypatch, capsys):
    responses = [_get({"exists": True, "version": 3, "profile": multi(active="文字版")}),
                 _get({"exists": True, "version": 4})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--rename-profile", "文字版", "水墨文字版", "--base-version", "3"],
                               responses)
    sent = calls[1]["payload"]["profile"]
    assert list(sent["profiles"]) == ["图文", "水墨文字版"]
    assert sent["active"] == "水墨文字版", "改的正好是默认那套时，active 要跟着改名"


def test_delete_profile_reassigns_active(monkeypatch, capsys):
    responses = [_get({"exists": True, "version": 3, "profile": multi(active="文字版")}),
                 _get({"exists": True, "version": 4})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--delete-profile", "文字版", "--base-version", "3"], responses)
    sent = calls[1]["payload"]["profile"]
    assert list(sent["profiles"]) == ["图文"] and sent["active"] == "图文"
    assert "默认已顺延到「图文」" in err


def test_delete_last_profile_is_refused_without_put(monkeypatch, capsys):
    """老格式只有一套 → 删它就等于清空，必须拒，且**一个 PUT 都不发**。"""
    responses = [_get({"exists": True, "version": 3, "profile": FLAT})]
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--delete-profile", "图文", "--base-version", "3"], responses)
    assert code == 1 and _puts(calls) == []
    assert "最后一套" in out["error"] and out["ok"] is False


# ============================ 八、写操作的乐观锁与迁移告知 ============================

def test_base_version_mismatch_conflicts_without_put(monkeypatch, capsys):
    """--base-version 与服务端当前版本对不上 → 走 409 口径（exit 3），连 PUT 都不发。"""
    responses = [_get({"exists": True, "version": 9, "base_version": 9, "profile": multi()})]
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--set-active", "文字版", "--base-version", "3"], responses)
    assert code == sp.EXIT_CONFLICT == 3
    assert _puts(calls) == [], "版本对不上还硬写，就会覆盖掉别人的改动"
    assert out["outcome"] == "conflict" and out["current_version"] == 9
    assert out["base_version"] == 3 and "重新 --get" in err


def test_migration_is_announced_and_dropped_keys_explained(monkeypatch, capsys):
    """老格式第一次被写 → 迁移。必须**事先**说清「原内容原样进图文」，且解释 dropped_keys 属预期。"""
    responses = [_get({"exists": True, "version": 3, "profile": FLAT}),
                 _get({"exists": True, "version": 4,
                       "dropped_keys": ["visual", "density", "tone", "structure"]})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--new-profile", "文字版", "--kind", "typeset",
                                "--base-version", "3"], responses)
    assert out["migrated"] is True
    assert "老的单套格式" in err and "原样" in err and "属预期" in err
    assert "不是丢了" in err
    assert "本次覆盖丢掉了" in err and "visual" in err     # 原有的警告照旧不能少


def test_write_on_admin_default_announces_creating_own_profile(monkeypatch, capsys):
    """还在跟随默认配置的人第一次建套 = 从此有了自己的档案（不再跟着运营老大变）——必须先说。"""
    responses = [_get({"exists": False, "base_version": 0, "profile": FLAT}),
                 _get({"exists": True, "version": 1, "dropped_keys": []})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--new-profile", "文字版", "--kind", "typeset",
                                "--base-version", "0"], responses)
    assert calls[1]["payload"]["base_version"] == 0
    assert "给他建一份自己的" in err and "不会影响他" in err


def test_write_note_can_be_overridden(monkeypatch, capsys):
    responses = [_get({"exists": True, "version": 3, "profile": multi()}),
                 _get({"exists": True, "version": 4})]
    _, _, calls = _main_ok(monkeypatch, capsys,
                           ["--set-active", "文字版", "--base-version", "3",
                            "--note", "老板说文字版为主"], responses)
    assert calls[1]["payload"]["note"] == "老板说文字版为主"


# ============================ 九、输出契约：stdout 仍是单行纯 JSON ============================

def test_stdout_is_single_line_json_on_new_commands(monkeypatch, capsys, tmp_path):
    """新子命令一律沿用老契约：stdout **只有一行** JSON，人话全走 stderr。"""
    f = tmp_path / "s.json"
    f.write_text(json.dumps(TYPESET_SET, ensure_ascii=False), encoding="utf-8")
    cases = [
        (["--list-profiles"], [_get({"exists": True, "version": 3, "profile": multi()})]),
        (["--get", "--kind", "typeset"],
         [_get({"exists": True, "version": 3, "profile": multi()})]),
        (["--get", "--kind", "typeset"], [_get({"exists": True, "version": 3, "profile": FLAT})]),
        (["--get", "--profile", "图文"], [_get({"exists": True, "version": 3, "profile": FLAT})]),
        (["--new-profile", "样刊风", "--kind", "typeset", "--file", str(f), "--base-version", "3"],
         [_get({"exists": True, "version": 3, "profile": multi()}),
          _get({"exists": True, "version": 4, "dropped_keys": []})]),
        (["--set-active", "文字版", "--base-version", "3"],
         [_get({"exists": True, "version": 3, "profile": multi()}),
          _get({"exists": True, "version": 4})]),
        (["--rename-profile", "文字版", "水墨文字版", "--base-version", "3"],
         [_get({"exists": True, "version": 3, "profile": multi()}),
          _get({"exists": True, "version": 4})]),
        (["--delete-profile", "文字版", "--base-version", "3"],
         [_get({"exists": True, "version": 3, "profile": multi()}),
          _get({"exists": True, "version": 4})]),
    ]
    for argv, responses in cases:
        calls = []
        monkeypatch.setattr(sys, "argv",
                            ["style_profile.py", "--api-base", "https://stub.test"] + argv)
        monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: "k")

        def sender(method, url, k, payload=None, timeout=30, _r=responses, _c=calls):
            _c.append(1)
            return _r[len(_c) - 1]

        monkeypatch.setattr(sp, "send_request", sender)
        sp.main()
        out = capsys.readouterr().out
        assert out.count("\n") == 1, f"{argv} 的 stdout 不是单行：{out!r}"
        json.loads(out)   # 整份可解析，没混进人话


def test_miss_by_name_trace_line_carries_the_requested_name(monkeypatch, capsys):
    body = {"exists": True, "version": 3, "profile": multi()}
    out, _, _ = _main_ok(monkeypatch, capsys, ["--get", "--profile", "水墨风"], [_get(body)])
    assert out["trace_line"].startswith("风格档案：水墨风 v—（内置兜底")


def test_offline_trace_line_carries_requested_set_but_bare_get_unchanged(monkeypatch, capsys):
    """服务挂了时也要把套名写进留痕行；**裸 --get 的那一行仍是老格式**（不许多个套名出来）。"""
    def boom(*a, **k):
        raise ConnectionError("Max retries exceeded")

    for argv, expect in ([["--get", "--kind", "typeset"], "风格档案：文字版 v—（内置兜底"],
                         [["--get", "--profile", "水墨风"], "风格档案：水墨风 v—（内置兜底"],
                         [["--get"], "风格档案：v—（内置兜底"]):
        monkeypatch.setattr(sys, "argv",
                            ["style_profile.py", "--api-base", "https://stub.test"] + argv)
        monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: "k")
        monkeypatch.setattr(sp, "send_request", boom)
        with pytest.raises(SystemExit) as ei:
            sp.main()
        out = json.loads(capsys.readouterr().out)
        assert ei.value.code == 2 and out["trace_line"].startswith(expect), argv


def test_new_commands_still_degrade_when_service_is_down(monkeypatch, capsys):
    """读不到服务时照旧 exit 2 + 明说「没连上风格档案服务」（第 ③ 层降级链没被新命令绕开）。"""
    monkeypatch.setattr(sys, "argv",
                        ["style_profile.py", "--api-base", "https://stub.test", "--list-profiles"])
    monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: "k")

    def boom(*a, **k):
        raise ConnectionError("Max retries exceeded")

    monkeypatch.setattr(sp, "send_request", boom)
    with pytest.raises(SystemExit) as ei:
        sp.main()
    cap = capsys.readouterr()
    assert ei.value.code == sp.EXIT_UNREACHABLE == 2
    assert "没连上风格档案服务" in cap.err
    assert json.loads(cap.out)["layer"] == "builtin_fallback"


# ========== 十、`--put` 守卫：多套档案绝不能被一份单套 body 整份覆盖（数据丢失） ==========

def _archive3():
    """线上那份翻车档案：3 套，默认「图文」。"""
    return multi(active="图文",
                 sets={"图文": json.loads(json.dumps(CAROUSEL_SET)),
                       "文字版": json.loads(json.dumps(TYPESET_SET)),
                       "水墨风": dict(json.loads(json.dumps(CAROUSEL_SET)), note="宣纸")})


def _write(tmp_path, obj, name="profile-new.json"):
    f = tmp_path / name
    f.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return f


def test_put_single_set_body_over_multi_archive_is_refused_without_put(monkeypatch, capsys,
                                                                      tmp_path):
    """实录复现：存 3 套 → 裸 `--get`（只给 active 那**一套的内容**）→ 改一个字段 → `--put`。

    从前：exit 0、「✓ 已整份覆盖」，存档顶层变成 density/kind/structure/tone/visual，
    `profiles` 键没了、另外两套**永久消失**。现在：拒绝、exit 1、**一个 PUT 都不发**。"""
    body = json.loads(json.dumps(CAROUSEL_SET))
    body["visual"]["text_color"] = "#333333"          # 就是「改一个字段」那一步
    f = _write(tmp_path, body)
    responses = [_get({"exists": True, "version": 7, "base_version": 7, "profile": _archive3()})]
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--put", str(f), "--base-version", "7"], responses)
    assert code == 1 and out["ok"] is False
    assert _puts(calls) == [], "服务端不校验语义：发出去就存进去了，必须拦在 PUT 之前"
    assert [c["method"] for c in calls] == ["GET"], "守卫复用那次 GET，别多发请求"
    # 报文要点名：几套、都叫什么、会丢几套
    assert "你有 3 套" in out["error"] and "图文、文字版、水墨风" in out["error"]
    assert "其余 2 套会被抹掉" in out["error"] and "已拒绝" in out["error"]
    assert "这份 body 只有一套" in out["error"]
    assert "失败" in err and "图文、文字版、水墨风" in err


def test_put_guard_points_at_version_not_at_the_command_that_caused_it(monkeypatch, capsys,
                                                                      tmp_path):
    """补救话术必须指向 `--version <当前版本>`（能拿到整份的那条），
    ⛔ 绝不能再说「先 --get 拿全量再重发」——`--get` 正是产生这份坏 body 的命令，说了就是死循环。"""
    f = _write(tmp_path, json.loads(json.dumps(CAROUSEL_SET)))
    responses = [_get({"exists": True, "version": 7, "base_version": 7, "profile": _archive3()})]
    out, code, _, _ = _run(monkeypatch, capsys, ["--put", str(f), "--base-version", "7"],
                           responses)
    assert code == 1
    assert "--version 7" in out["error"], "要用 server 下发的 base_version，不是自己编一个"
    assert "拿全量再重发" not in out["error"]
    assert "别再拿 `--get` 的输出去 `--put`" in out["error"]


def test_put_whole_container_over_multi_archive_is_allowed(monkeypatch, capsys, tmp_path):
    """带 schema/profiles 的整份容器照旧放行——这才是多套的正确改法，守卫不能把它也拦了。"""
    archive = multi()
    changed = json.loads(json.dumps(archive))
    changed["profiles"]["图文"]["visual"]["text_color"] = "#333333"
    f = _write(tmp_path, changed)
    responses = [_get({"exists": True, "version": 7, "base_version": 7, "profile": archive}),
                 _get({"exists": True, "version": 8, "dropped_keys": []})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--put", str(f), "--base-version", "7"], responses)
    assert [c["method"] for c in calls] == ["GET", "PUT"]
    assert calls[1]["payload"] == {"base_version": 7, "profile": changed, "source": "manual"}
    assert out["version"] == 8


def test_put_on_legacy_flat_archive_is_unchanged(monkeypatch, capsys, tmp_path):
    """存量的老平铺档案（就一套）→ 守卫放行，行为与守卫之前一字不差。"""
    body = dict(json.loads(json.dumps(FLAT)), tone={"person": "第一人称"})
    f = _write(tmp_path, body)
    responses = [_get({"exists": True, "version": 3, "base_version": 3, "profile": FLAT}),
                 _get({"exists": True, "version": 4, "dropped_keys": []})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--put", str(f), "--base-version", "3"], responses)
    assert [c["method"] for c in calls] == ["GET", "PUT"]
    assert calls[1]["payload"]["profile"] == body


def test_put_single_set_over_multi_admin_default_is_refused(monkeypatch, capsys, tmp_path):
    """还没有个人档案、跟随的默认配置是多套 → 发一份单套照样只剩一套：拒，
    且补救话术要指向 `--get-default`（他没有自己的版本历史，`--version` 那条路对他是死的）。"""
    f = _write(tmp_path, json.loads(json.dumps(CAROUSEL_SET)))
    responses = [_get({"exists": False, "base_version": 0, "profile": multi()})]
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--put", str(f), "--base-version", "0"], responses)
    assert code == 1 and _puts(calls) == []
    assert "你现在跟随的默认配置有 2 套" in out["error"]
    assert "--get-default" in out["error"] and "--version" not in out["error"]


def test_put_container_with_one_set_still_refuses_flat_body(monkeypatch, capsys, tmp_path):
    """容器里只有一套时也拦：单套 body 会把 schema/active/profiles 打平回老格式（结构没了）。"""
    one = multi(active="图文", sets={"图文": json.loads(json.dumps(CAROUSEL_SET))})
    f = _write(tmp_path, json.loads(json.dumps(CAROUSEL_SET)))
    responses = [_get({"exists": True, "version": 4, "base_version": 4, "profile": one})]
    out, code, _, calls = _run(monkeypatch, capsys,
                               ["--put", str(f), "--base-version", "4"], responses)
    assert code == 1 and _puts(calls) == []
    assert "打平回老的单套格式" in out["error"] and "其余" not in out["error"]


def test_put_version_envelope_is_unwrapped_and_accepted(monkeypatch, capsys, tmp_path):
    """拿 `--version` 的输出**整份连壳**喂 --put：剥壳认得出这个信封（version+source），
    自动取里面的 profile 再发——存进去的是那个多套容器本身，不是 {version,source,profile}。

    这是 guide 教的主路径（"用 --version 取整份、改完再 --put"）：运营存下 stdout 直接改直接发，
    不该要求他先手工剥一层。"""
    f = _write(tmp_path, {"version": 7, "source": "manual", "profile": _archive3()})
    responses = [_get({"exists": True, "version": 7, "base_version": 7, "profile": _archive3()}),
                 _Resp(200, {"exists": True, "version": 8, "dropped_keys": []})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--put", str(f), "--base-version", "7"], responses)
    assert _puts(calls)[0]["payload"]["profile"] == _archive3()      # 存的是容器本体
    assert "信封" in err                                              # 剥壳有提示，不静默


def test_put_still_refuses_empty_profile_before_any_request(monkeypatch, capsys, tmp_path):
    """空对象照旧本地拒，且**连守卫那次 GET 都不发**（本地就能判死的别浪费一个来回）。"""
    f = _write(tmp_path, {})
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--put", str(f), "--base-version", "1"], [])
    assert code == 1 and calls == [] and "清空" in out["error"]


# ============ 十一、`--version N` 配 `--profile` / `--kind`：取回某一版里的某一套 ============

def _version_body(profile, version=3):
    """`GET /api/style-profile/versions/{N}` 的响应形状：**没有 `exists` 键**。"""
    return {"version": version, "source": "manual", "note": None,
            "created_at": "2026-07-24T09:00:00", "created_by": 7, "profile": profile}


def test_version_bare_still_passes_through_whole_container(monkeypatch, capsys):
    """不带 --profile/--kind 时原样透传整份——多套的「取整份 → 改 → --put」全靠这条路，别动。"""
    body = _version_body(multi())
    out, err, calls = _main_ok(monkeypatch, capsys, ["--version", "3"], [_get(body)])
    assert out == body and calls[0]["url"].endswith("/api/style-profile/versions/3")
    assert "没动当前档案" in err


def test_version_with_kind_selects_that_set(monkeypatch, capsys):
    """审查端按留痕行回溯要能直接读到那一套的字段；多套化后整份容器里 profile.typeset 恒 undefined。"""
    out, err, calls = _main_ok(monkeypatch, capsys, ["--version", "3", "--kind", "typeset"],
                               [_get(_version_body(multi(active="图文")))])
    assert len(calls) == 1 and calls[0]["method"] == "GET"
    assert out["profile"] == TYPESET_SET and out["outcome"] == "ok"
    assert out["profile"]["typeset"]["theme"] == "paper"     # 这一路以前是 undefined
    assert out["profile_name"] == "文字版" and out["profile_kind"] == "typeset"
    assert out["active_profile"] == "图文" and out["profile_names"] == ["图文", "文字版"]
    assert out["version"] == 3 and out["source"] == "manual"  # 原字段照旧透出
    # 留痕行按**这一版**写（写成 v0/默认配置，审查端就会拿错档案判）
    assert out["trace_line"].startswith("风格档案：文字版 v3（本人档案，读取于 ")
    assert "文字版" in err


def test_version_with_profile_name_selects_that_set(monkeypatch, capsys):
    out, err, _ = _main_ok(monkeypatch, capsys, ["--version", "5", "--profile", "图文"],
                           [_get(_version_body(multi(active="文字版"), version=5))])
    assert out["profile"] == CAROUSEL_SET and out["profile_name"] == "图文"
    assert out["profile"]["visual"]["palette"][0]["hex"] == "#A8B5C4"
    assert out["trace_line"].startswith("风格档案：图文 v5（本人档案，读取于 ")


def test_version_with_kind_on_legacy_version_returns_flat_verbatim(monkeypatch, capsys):
    """老格式的历史版本（那时还没多套）→ 原样那份平铺内容，留痕行带套名「图文」。"""
    out, err, _ = _main_ok(monkeypatch, capsys, ["--version", "2", "--kind", "carousel"],
                           [_get(_version_body(FLAT, version=2))])
    assert out["profile"] == FLAT and "kind" not in out["profile"]
    assert out["profiles_legacy"] is True
    assert out["trace_line"].startswith("风格档案：图文 v2（本人档案，读取于 ")
    assert "只读不改" in err


def test_version_with_unknown_set_falls_back_to_builtin(monkeypatch, capsys):
    """那一版里没有这一套 → profile:null + 内置兜底留痕（别拿别的套顶包去判）。"""
    out, err, calls = _main_ok(monkeypatch, capsys, ["--version", "3", "--profile", "水墨风"],
                               [_get(_version_body(multi()))])
    assert out["profile"] is None and out["outcome"] == "not_found"
    assert out["layer"] == "builtin_fallback"
    assert out["trace_line"].startswith("风格档案：水墨风 v—（内置兜底")
    assert len(calls) == 1


def test_version_and_get_use_the_same_selection_logic(monkeypatch, capsys):
    """同一份档案：`--get --kind X` 与 `--version N --kind X` 挑套结果必须逐字一致
    （两处各写一份实现 → 两种 outcome / 两种留痕行，审查端口径就散了）。"""
    archive = multi(active="图文")
    a, _, _ = _main_ok(monkeypatch, capsys, ["--get", "--kind", "typeset"],
                       [_get({"exists": True, "version": 3, "profile": archive})])
    b, _, _ = _main_ok(monkeypatch, capsys, ["--version", "3", "--kind", "typeset"],
                       [_get(_version_body(archive))])
    keys = ["profile", "profile_name", "profile_kind", "active_profile", "profile_names",
            "outcome", "profiles_legacy", "trace_line"]
    assert {k: a[k] for k in keys} == {k: b[k] for k in keys}


def test_version_selection_is_single_line_json(monkeypatch, capsys):
    for argv in (["--version", "3", "--kind", "typeset"], ["--version", "3", "--profile", "水墨风"]):
        monkeypatch.setattr(sys, "argv",
                            ["style_profile.py", "--api-base", "https://stub.test"] + argv)
        monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: "k")
        monkeypatch.setattr(sp, "send_request",
                            lambda *a, **k: _get(_version_body(multi())))
        sp.main()
        out = capsys.readouterr().out
        assert out.count("\n") == 1, f"{argv} 的 stdout 不是单行：{out!r}"
        json.loads(out)


def test_version_offline_trace_line_carries_the_requested_set(monkeypatch, capsys):
    """服务挂了时，`--version N --kind` 的留痕行也要带套名（没套名会被审查端当图文判）。"""
    def boom(*a, **k):
        raise ConnectionError("Max retries exceeded")

    monkeypatch.setattr(sys, "argv", ["style_profile.py", "--api-base", "https://stub.test",
                                      "--version", "3", "--kind", "typeset"])
    monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: "k")
    monkeypatch.setattr(sp, "send_request", boom)
    with pytest.raises(SystemExit) as ei:
        sp.main()
    out = json.loads(capsys.readouterr().out)
    assert ei.value.code == 2
    assert out["trace_line"].startswith("风格档案：文字版 v—（内置兜底")


def test_version_with_profile_and_kind_still_mutually_exclusive(monkeypatch, capsys):
    _, code, err, calls = _run(monkeypatch, capsys,
                               ["--version", "3", "--profile", "图文", "--kind", "typeset"], [])
    assert code == 4 and calls == [] and "二选一" in err


# ============ 十二、合法多套容器不许被误报 density 缺失（狼来了） ============

def test_profile_warnings_routes_container_to_container_rules():
    """`profile_warnings` 遇到多套容器要分流给 `container_warnings`：
    容器顶层本来就没有 density 段，直接拿去查 = 每次正确操作都甩一条假警报。"""
    assert sp.profile_warnings(multi()) == []
    assert sp.profile_warnings(FLAT) == []          # 单套照旧走原逻辑
    bad = multi(sets={"图文": {"kind": "carousel"}, "文字版": dict(TYPESET_SET)})
    w = "；".join(sp.profile_warnings(bad))
    assert "「图文」这套" in w and "density" in w    # 真缺 density 的那一套照样报
    assert "文字版" not in w                        # 文字版没有插画/信息点，拿 density 要求它是误报


def test_put_multi_container_gets_no_fake_density_warning(monkeypatch, capsys, tmp_path):
    """CLI 侧钉死：`--put` 一份合法多套容器，stderr 不许出现「没有 density 段」。"""
    archive = multi()
    f = _write(tmp_path, archive)
    responses = [_get({"exists": True, "version": 7, "base_version": 7, "profile": archive}),
                 _get({"exists": True, "version": 8, "dropped_keys": []})]
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--put", str(f), "--base-version", "7"], responses)
    assert out["warnings"] == []
    assert "没有 density 段" not in err and "⚠" not in err
    assert _puts(calls)[0]["payload"]["profile"] == archive


def test_put_container_still_warns_on_broken_carousel_set(monkeypatch, capsys, tmp_path):
    """真出问题时照样报（别把警告一刀切掉）：图文那套的 density 被改成英文 key → 警告点名那一套。"""
    archive = multi(sets={"图文": {"kind": "carousel", "density": {"level": "默认"}},
                          "文字版": dict(TYPESET_SET)})
    f = _write(tmp_path, archive)
    responses = [_get({"exists": True, "version": 7, "base_version": 7, "profile": archive}),
                 _get({"exists": True, "version": 8, "dropped_keys": []})]
    out, err, _ = _main_ok(monkeypatch, capsys,
                           ["--put", str(f), "--base-version", "7"], responses)
    joined = "；".join(out["warnings"])
    assert "「图文」这套" in joined and "信息密度档位" in joined and "⚠" in err

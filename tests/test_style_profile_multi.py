"""style_profile.py 多套风格档案回归（**服务端原生多套**，nbdpsy-server v0.17.0）。全程 stub，⛔ 绝不打网络。

2026-07-29 整体重写：上一版 78 条全部建立在「`profile` JSON 内部塞 profiles-v1 容器」之上，
容器方案已随服务端原生化整个下线（十个纯函数 + 两道守卫一并删除），故按新端点重写。

盯死六条（按翻车概率排序）：

1. **`--get` 不带 `--profile` / `--kind` 的输出逐字段与今天一致**——它只是把服务端那份原样透传
   再补 base_version / layer / say / trace_line 四项。创作端 / 审查端 / guide / pipeline
   四处都按这些键读，这条一破就是全线断链，所以用「整份键集合相等」钉死，不是只挑几个字段看。
2. **每条多套命令打的是哪个 method + 哪个 path + 什么 payload**：CLI 对运营没变，变的全在底层，
   这一层错了运营看不出来（命令照跑、话照说），只有测试拦得住。
3. **`--delete-profile` 撞 409 要翻成人话**，而不是把服务端 JSON 甩给运营；且**不能冒充版本冲突**
   （409 在这里是「只剩一套」，走 exit 3 会把上层引去「重新 --get 再来」的死路）。
4. **`--get --kind` 无匹配 → `profile: null` + say，exit 仍是 0**：上层据此用内置默认继续做内容，
   退非 0 会被当成「服务挂了」而走错降级层。
5. **套名进 URL 必须转义**：中文 / 空格套名不转义就拼坏请求（服务端只禁 / 和 ?）。
6. **三层降级与 exit 码语义没被动过**：exit 2 = 没连上、exit 3 = 版本冲突、exit 4 = 用法错。
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import pytest

import style_profile as sp

# 一套「图文」的内容（线上真实档案就是这个形状）
CAROUSEL = {
    "kind": "carousel",
    "visual": {"palette": [{"name": "雾霾蓝灰", "hex": "#A8B5C4"}], "text_color": "#5A6B7B",
               "character_card": "短发女性，米色针织衫"},
    "density": {"信息密度档位": "默认", "每页文字量": "200–400 字", "每页信息点": "6–10 个",
                "版式档": "满版", "运营原话": "—"},
    "tone": {"person": "第二人称", "emoji_target": "8–14"},
    "structure": {"title_structure": "痛点 + 数字", "hook_type": "提问", "ending": "邀请评论"},
}
# 一套「文字版」的内容：**没有 density 段**（它没有插画、没有信息点）
TYPESET = {
    "kind": "typeset",
    "typeset": {"theme": "paper", "bg": None, "accent": "#3A4A7A", "accent_soft": None,
                "font": None, "title_font": None, "indent": None, "texture": None},
    "tone": {"person": "第二人称"},
    "structure": {"title_structure": "痛点 + 数字"},
}

# GET /sets 的行（服务端字段：name / kind / is_active / version / updated_at）
S_CAROUSEL = {"name": "图文", "kind": "carousel", "is_active": True, "version": 3,
              "updated_at": "2026-07-28T10:00:00"}
S_TYPESET = {"name": "文字版", "kind": "typeset", "is_active": False, "version": 1,
             "updated_at": "2026-07-28T11:00:00"}


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    @property
    def text(self):
        return json.dumps(self._body, ensure_ascii=False)

    def json(self):
        return self._body


def _route(sets=None, admin_sets=None, content=None, overrides=None):
    """按 (method, path) 派发的假服务端，行为对齐实测过的 nbdpsy-server v0.17.0。
    overrides 可对某条路由给定制响应（测错误码用）。

    刻意**不**做成"顺序返回列表"：多套命令的请求条数本来就是这次改动的一部分，
    顺序列表会让「多打 / 少打一个请求」悄悄通过。"""
    sets = [dict(s) for s in (sets if sets is not None else [S_CAROUSEL, S_TYPESET])]
    admin_sets = [dict(s) for s in (admin_sets if admin_sets is not None else [S_CAROUSEL])]
    content = content if content is not None else {"图文": CAROUSEL, "文字版": TYPESET}
    overrides = overrides or {}
    calls = []

    def sender(method, url, key, payload=None, timeout=30):
        from urllib.parse import urlparse, parse_qs, unquote
        u = urlparse(url)
        path, query = u.path, parse_qs(u.query)
        calls.append({"method": method, "path": unquote(path),
                      "query": {k: v[0] for k, v in query.items()},
                      "url": url, "payload": payload})
        if (method, unquote(path)) in overrides:
            return overrides[(method, unquote(path))]
        scope = query.get("scope", ["self"])[0]
        want = query.get("set", [None])[0]

        if path == "/api/style-profile/sets":
            if method == "GET":
                return _Resp(200, {"sets": admin_sets if scope == "admin-default" else sets})
            row = {"name": payload["name"], "kind": payload["kind"], "is_active": not sets,
                   "version": 1, "updated_at": "2026-07-29T00:00:00"}
            sets.append(row)
            return _Resp(200, dict(row))
        if path.startswith("/api/style-profile/sets/"):
            name = unquote(path.rsplit("/", 1)[1])
            row = next((s for s in sets if s["name"] == name), None)
            if row is None:
                return _Resp(404, {"error": f"风格档案套「{name}」不存在"})
            if method == "DELETE":
                sets.remove(row)
                return _Resp(200, {"deleted": name})
            if payload.get("new_name"):
                row["name"] = payload["new_name"]
            if payload.get("is_active"):
                for s in sets:
                    s["is_active"] = s is row
            return _Resp(200, dict(row))
        if path == "/api/style-profile":
            if method == "PUT":
                row = (next((x for x in sets if x["name"] == want), None) if want
                       else next((x for x in sets if x["is_active"]), None))
                if row is None:
                    return _Resp(404, {"error": f"风格档案套「{want}」不存在"})
                row["version"] += 1
                return _Resp(200, {"exists": True, "version": row["version"],
                                   "set": row["name"], "kind": row["kind"],
                                   "dropped_keys": []})
            if not sets:
                # 实测：零套运营带 set 也**忽略 set**，回落默认配置的 is_active 套
                a = next((s for s in admin_sets if s["is_active"]), None)
                if a is None:
                    return _Resp(200, {"exists": False, "base_version": 0, "set": None,
                                       "kind": None, "admin_default_version": 0, "profile": {}})
                return _Resp(200, {"exists": False, "source": "admin_default", "base_version": 0,
                                   "set": a["name"], "kind": a["kind"],
                                   "admin_default_version": 4, "updated_at": a["updated_at"],
                                   "profile": content[a["name"]]})
            row = (next((s for s in sets if s["name"] == want), None) if want
                   else next(s for s in sets if s["is_active"]))
            if row is None:
                return _Resp(404, {"error": f"风格档案套「{want}」不存在"})
            return _Resp(200, {"exists": True, "version": row["version"],
                               "base_version": row["version"], "source": "manual", "note": None,
                               "set": row["name"], "kind": row["kind"],
                               "updated_at": row["updated_at"], "profile": content[row["name"]]})
        if path == "/api/style-profile/admin-default":
            row = (next((s for s in admin_sets if s["name"] == want), None) if want
                   else next((s for s in admin_sets if s["is_active"]), None))
            if row is None:
                return _Resp(404, {"error": f"管理员默认套「{want}」不存在"})
            return _Resp(200, {"profile": content[row["name"]], "admin_default_version": 4,
                               "set": row["name"], "kind": row["kind"],
                               "updated_at": row["updated_at"]})
        if path == "/api/style-profile/versions":
            row = (next((x for x in sets if x["name"] == want), None) if want
                   else next((x for x in sets if x["is_active"]), None))
            if row is None:
                return _Resp(404, {"error": f"风格档案套「{want}」不存在"})
            return _Resp(200, {"versions": [{"version": v, "source": "manual", "note": None,
                                             "created_at": "2026-07-20T09:00:00"}
                                            for v in range(row["version"], 0, -1)],
                               "total": row["version"], "set": row["name"], "kind": row["kind"]})
        if path == "/api/style-profile/rollback":
            row = (next((x for x in sets if x["name"] == want), None) if want
                   else next((x for x in sets if x["is_active"]), None))
            if row is None:
                return _Resp(404, {"error": f"风格档案套「{want}」不存在"})
            row["version"] += 1
            return _Resp(200, {"exists": True, "version": row["version"],
                               "set": row["name"], "kind": row["kind"], "dropped_keys": []})
        if path.startswith("/api/style-profile/versions/"):
            v = int(path.rsplit("/", 1)[1])
            row = (next((s for s in sets if s["name"] == want), None) if want
                   else next((s for s in sets if s["is_active"]), None))
            if row is None:
                return _Resp(404, {"error": f"风格档案套「{want}」不存在"})
            return _Resp(200, {"version": v, "source": "manual", "note": None,
                               "created_at": "2026-07-20T09:00:00", "created_by": 7,
                               "set": row["name"], "kind": row["kind"],
                               "profile": content[row["name"]]})
        return _Resp(404, {"error": f"no route {path}"})

    sender.calls = calls
    sender.sets = sets
    return sender


def _run(monkeypatch, capsys, argv, sender, key="k"):
    """跑一次 CLI，返回 (stdout JSON, exit code, stderr, 请求记录)。exit 0 的正常路径不抛。"""
    monkeypatch.setattr(sys, "argv",
                        ["style_profile.py", "--api-base", "https://stub.test"] + argv)
    monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: key)
    monkeypatch.setattr(sp, "send_request", sender)
    code = 0
    try:
        sp.main()
    except SystemExit as e:
        code = e.code
    cap = capsys.readouterr()
    out = json.loads(cap.out.strip().splitlines()[-1]) if cap.out.strip() else None
    return out, code, cap.err, sender.calls


def _paths(calls):
    return [(c["method"], c["path"]) for c in calls]


# =====================================================================
# 一、`--get` 不带参数：下游四处按它读，逐字段钉死
# =====================================================================

def test_bare_get_passes_server_view_through_untouched(monkeypatch, capsys):
    """裸 `--get` = 服务端那份**原样** + 四个补充字段，一个键都不许多、不许少。

    服务端原生多套后它直接给 is_active 那套的内容（外加 set/kind 两个增字段），
    客户端不再做任何挑套 / 剥壳动作。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys, ["--get"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile")], "裸 --get 只该打一个请求"
    assert calls[0]["query"] == {}, "不带 --profile/--kind 时不该往 URL 里塞 set"
    # 键集合 = 服务端下发的 9 个 + 客户端补的 4 个，逐字钉死
    assert set(out) == {"exists", "version", "base_version", "source", "note", "set", "kind",
                        "updated_at", "profile", "layer", "say", "trace_line",
                        "base_version_source"}
    assert out["profile"] == CAROUSEL, "给的就是那一套的内容，不是什么容器"
    assert out["exists"] is True and out["version"] == 3 and out["base_version"] == 3
    assert out["base_version_source"] == "server" and out["layer"] == "user_profile"
    assert out["say"] == "这是你的风格档案（v3），我回读一遍，你确认下"
    assert out["trace_line"].startswith("风格档案：v3（本人档案，读取于 ")
    # 容器时代的字段绝不能回潮
    for gone in ("schema", "active", "profiles", "profiles_legacy"):
        assert gone not in out


def test_bare_get_for_operator_without_profile(monkeypatch, capsys):
    """还没建档的人：exists:false + 默认配置那套的内容 + base_version 0，两句话不能串。"""
    s = _route(sets=[])
    out, code, err, calls = _run(monkeypatch, capsys, ["--get"], s)
    assert code == 0 and _paths(calls) == [("GET", "/api/style-profile")]
    assert out["exists"] is False and out["base_version"] == 0
    assert out["layer"] == "admin_default" and out["admin_default_version"] == 4
    assert out["say"] == "你还没有自己的风格档案，先用默认配置，可以吗？"
    assert out["trace_line"].startswith("风格档案：v0（默认配置，读取于 ")
    assert "别说成是他的" in err


# =====================================================================
# 二、`--get --profile 套名` / `--get --kind 形态`
# =====================================================================

def test_get_by_profile_name_hits_set_query(monkeypatch, capsys):
    """`--get --profile 文字版` → `GET /api/style-profile?set=文字版`，一个请求，套名已转义。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--profile", "文字版"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile")]
    assert calls[0]["query"] == {"set": "文字版"}
    assert "%E6%96%87%E5%AD%97%E7%89%88" in calls[0]["url"], "中文套名必须 URL 转义"
    assert out["profile"] == TYPESET and out["profile_name"] == "文字版"
    assert out["profile_kind"] == "typeset" and out["outcome"] == "ok"
    assert out["base_version"] == 1, "base_version 是**这一套自己的**版本号"
    assert out["trace_line"].startswith("风格档案：文字版 v1（本人档案，读取于 ")


def test_get_by_kind_lists_sets_then_fetches_that_one(monkeypatch, capsys):
    """`--get --kind typeset` → 先 `GET /sets` 挑，再 `GET ?set=挑中的名字`。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--kind", "typeset"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile/sets"),
                             ("GET", "/api/style-profile")]
    assert calls[1]["query"] == {"set": "文字版"}
    assert out["profile"] == TYPESET and out["profile_name"] == "文字版"
    assert out["profile_names"] == ["图文", "文字版"] and out["active_profile"] == "图文"


def test_get_by_kind_prefers_active_set(monkeypatch, capsys):
    """同形态有多套时**优先 is_active 那套**（契约点名的挑法），不是列表里第一套。"""
    first = dict(S_CAROUSEL, name="水墨风", is_active=False, version=9)
    active = dict(S_CAROUSEL, name="图文", is_active=True, version=3)
    s = _route(sets=[first, active], content={"水墨风": CAROUSEL, "图文": CAROUSEL})
    out, code, _, calls = _run(monkeypatch, capsys, ["--get", "--kind", "carousel"], s)
    assert code == 0 and calls[1]["query"] == {"set": "图文"}
    assert out["profile_name"] == "图文"


def test_get_by_kind_falls_back_to_first_when_no_active_match(monkeypatch, capsys):
    """is_active 那套形态对不上时，取该形态的第一套。"""
    s = _route(sets=[dict(S_CAROUSEL, is_active=True),
                     dict(S_TYPESET, name="甲", is_active=False),
                     dict(S_TYPESET, name="乙", is_active=False)],
               content={"图文": CAROUSEL, "甲": TYPESET, "乙": TYPESET})
    out, code, _, calls = _run(monkeypatch, capsys, ["--get", "--kind", "typeset"], s)
    assert code == 0 and calls[1]["query"] == {"set": "甲"} and out["profile_name"] == "甲"


def test_get_by_kind_no_match_returns_null_profile_and_exit_0(monkeypatch, capsys):
    """这个形态一套都没有 → `profile: null` + say 提示可新建，**exit 仍是 0**。

    退非 0 会被上层当成「服务挂了」而走错降级层；上层要的是「用内置默认继续做内容」。"""
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": CAROUSEL})
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--kind", "typeset"], s)
    assert code == 0, "没挑中不是错误，上层要照常用内置默认继续"
    assert _paths(calls) == [("GET", "/api/style-profile/sets")], "没挑中就别再去取内容"
    assert out["profile"] is None and out["outcome"] == "no_kind_match"
    assert out["layer"] == "builtin_fallback"
    assert out["say"] == "你还没有「文字版」那套风格（现有：图文），这次先用内置默认；要不要现在建一套？"
    assert out["profile_names"] == ["图文"]
    # 留痕行必须带上「他要的那一套」的名字：没套名的行会被审查端当存量批次按「图文」判
    assert out["trace_line"].startswith("风格档案：文字版 v—（内置兜底，读取于 ")
    assert out["base_version"] is None, "没挑中就没有'哪一套'可写，给数字会让上层写错套"
    assert "内置兜底" in err


def test_get_by_profile_name_not_found_lists_existing(monkeypatch, capsys):
    """点名的套不存在（服务端 404）→ 这时才列一次套，好把「现有哪几套」念给运营听；exit 0。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--profile", "水墨风"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile"),
                             ("GET", "/api/style-profile/sets")]
    assert out["profile"] is None and out["outcome"] == "not_found"
    assert out["say"] == "你的档案里没有「水墨风」这一套风格（现有：图文、文字版），要不要现在建一套？"
    assert out["trace_line"].startswith("风格档案：水墨风 v—（内置兜底，读取于 ")


def test_get_by_profile_name_zero_sets_does_not_mistake_fallback_for_a_hit(monkeypatch, capsys):
    """⚠️ 服务端实测行为：**一套都没有**的运营 `GET ?set=文字版` 不会 404，而是**忽略 set**
    回落到默认配置的 is_active 套（返回 exists:false + set:"图文"）。

    照单全收就会把「图文」的内容当成他要的「文字版」发给创作端——必须按没挑中处理。"""
    s = _route(sets=[])
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--profile", "文字版"], s)
    assert code == 0
    assert out["profile"] is None and out["outcome"] == "not_found"
    assert out["trace_line"].startswith("风格档案：文字版 v—（内置兜底")


def test_get_by_profile_name_zero_sets_matching_fallback_is_a_hit(monkeypatch, capsys):
    """回落到的正好就是他点名的那个名字（「图文」）→ 算挑中，内容是默认配置那套，exists:false。
    这与多套化之前「老格式读成一套『图文』」的行为一致。"""
    s = _route(sets=[])
    out, code, _, _ = _run(monkeypatch, capsys, ["--get", "--profile", "图文"], s)
    assert out["outcome"] == "ok" and out["exists"] is False
    assert out["profile"] == CAROUSEL and out["profile_name"] == "图文"
    assert out["say"] == "你还没有自己的风格档案，先用默认配置，可以吗？"
    assert out["trace_line"].startswith("风格档案：图文 v0（默认配置，读取于 ")


def test_get_by_kind_zero_sets_matches_followed_default(monkeypatch, capsys):
    """还没建档的人 `--get --kind carousel`：/sets 是空的 → 退到裸 GET 看他跟随的默认配置
    那套形态对不对得上（对得上就给，这与多套化之前一致）。"""
    s = _route(sets=[])
    out, code, _, calls = _run(monkeypatch, capsys, ["--get", "--kind", "carousel"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile/sets"), ("GET", "/api/style-profile")]
    assert out["outcome"] == "ok" and out["exists"] is False and out["profile"] == CAROUSEL
    assert out["trace_line"].startswith("风格档案：图文 v0（默认配置，读取于 ")


def test_get_by_kind_zero_sets_no_match(monkeypatch, capsys):
    """还没建档、且默认配置里在用的那套形态也对不上 → 没挑中（exit 0）。"""
    s = _route(sets=[])
    out, code, _, _ = _run(monkeypatch, capsys, ["--get", "--kind", "typeset"], s)
    assert code == 0 and out["profile"] is None and out["outcome"] == "no_kind_match"


def test_profile_and_kind_are_mutually_exclusive(monkeypatch, capsys):
    s = _route()
    _, code, err, calls = _run(monkeypatch, capsys,
                               ["--get", "--profile", "图文", "--kind", "carousel"], s)
    assert code == 4 and calls == [] and "二选一" in err


# =====================================================================
# 三、`--list-profiles`
# =====================================================================

def test_list_profiles_hits_sets_endpoint(monkeypatch, capsys):
    """`--list-profiles` → 一个 `GET /sets`，行原样透出（服务端字段 name/kind/is_active/...）。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys, ["--list-profiles"], s)
    assert code == 0 and _paths(calls) == [("GET", "/api/style-profile/sets")]
    assert out["exists"] is True and out["count"] == 2
    assert out["profiles"] == [S_CAROUSEL, S_TYPESET]
    assert out["active_profile"] == "图文"
    assert out["say"] == "你有 2 套风格：图文·默认、文字版；现在默认用「图文」"


def test_list_profiles_for_operator_without_profile_shows_default_config(monkeypatch, capsys):
    """还没建档的人：列出来的是**他跟随的那份默认配置**有几套，say 保持 SAY_MISSING 逐字不动。"""
    s = _route(sets=[], admin_sets=[S_CAROUSEL, S_TYPESET])
    out, code, err, calls = _run(monkeypatch, capsys, ["--list-profiles"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile/sets"),
                             ("GET", "/api/style-profile/sets")]
    assert calls[1]["query"] == {"scope": "admin-default"}
    assert out["exists"] is False and out["count"] == 2
    assert out["say"] == sp.SAY_MISSING
    assert "--init-sets" in err, "该指路让他按默认套数建齐自己的"


# =====================================================================
# 四、建套 `--new-profile`
# =====================================================================

def test_new_profile_posts_to_sets_with_default_config_content(monkeypatch, capsys):
    """不带 --from/--file：内容取**默认配置里同形态那套**，然后 POST /sets。"""
    s = _route(admin_sets=[S_CAROUSEL])
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "水墨风", "--kind", "carousel"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile/sets"),
                             ("GET", "/api/style-profile/admin-default"),
                             ("POST", "/api/style-profile/sets"),
                             ("GET", "/api/style-profile/sets")]
    assert calls[0]["query"] == {"scope": "admin-default"}
    assert calls[1]["query"] == {"set": "图文"}
    body = calls[2]["payload"]
    assert body["name"] == "水墨风" and body["kind"] == "carousel"
    assert body["profile"]["visual"] == CAROUSEL["visual"]
    assert "base_version" not in body, "建套是独立资源，服务端不收 base_version（实测）"
    assert "from" not in body
    assert "已新建「水墨风」" in err


def test_new_profile_typeset_falls_back_to_skeleton(monkeypatch, capsys):
    """默认配置里没有「文字版」那类套 → clean 主题骨架 + 沿用他在用那套的语气。"""
    s = _route(admin_sets=[S_CAROUSEL])
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "文字版", "--kind", "typeset"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile/sets"),
                             ("GET", "/api/style-profile"),
                             ("POST", "/api/style-profile/sets"),
                             ("GET", "/api/style-profile/sets")]
    body = calls[2]["payload"]["profile"]
    assert body["kind"] == "typeset" and body["typeset"]["theme"] == "clean"
    assert all(body["typeset"][k] is None for k in sp.TYPESET_NULLABLE)
    assert body["tone"] == CAROUSEL["tone"], "语气沿用他在用的那套"
    # 文字版没有插画、没有信息点：**绝不能**拿 density 五字段去报它缺段（狼来了）
    assert "density" not in err


def test_new_profile_uses_server_side_from(monkeypatch, capsys):
    """`--from` 把复制交给服务端做（body 带 from，不自己搬内容），先列一次套核形态。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "水墨风", "--kind", "carousel",
                                  "--from", "图文"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile/sets"),
                             ("POST", "/api/style-profile/sets"),
                             ("GET", "/api/style-profile/sets")]
    assert calls[1]["payload"] == {"name": "水墨风", "kind": "carousel", "from": "图文"}
    assert "复制自「图文」" in err


def test_new_profile_from_rejects_kind_mismatch(monkeypatch, capsys):
    """图文复制成文字版 = 一套确定坏掉的档案（字段根本不是一回事）→ 本地拒，**一个写请求都不发**。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "甲", "--kind", "typeset", "--from", "图文"], s)
    assert code == 1
    assert _paths(calls) == [("GET", "/api/style-profile/sets")]
    assert "不能复制成「文字版」" in out["error"]


def test_new_profile_from_missing_source(monkeypatch, capsys):
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "甲", "--kind", "carousel",
                                  "--from", "不存在"], s)
    assert code == 1 and _paths(calls) == [("GET", "/api/style-profile/sets")]
    assert "没有叫「不存在」的风格可复制" in out["error"] and "图文、文字版" in out["error"]


def test_new_profile_from_file(monkeypatch, capsys, tmp_path):
    """`--file` 用给定 JSON 当内容；形态以命令行 --kind 为准（文件里写错了也不听它）。"""
    f = tmp_path / "set.json"
    f.write_text(json.dumps(dict(CAROUSEL, kind="typeset"), ensure_ascii=False), encoding="utf-8")
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "水墨风", "--kind", "carousel",
                                  "--file", str(f)], s)
    assert code == 0
    assert _paths(calls) == [("POST", "/api/style-profile/sets"),
                             ("GET", "/api/style-profile/sets")]
    assert calls[0]["payload"]["profile"]["kind"] == "carousel"
    assert "按命令行算" in err


def test_new_profile_file_unwraps_get_envelope(monkeypatch, capsys, tmp_path):
    """喂 `--get` 的整份输出 → 自动剥出 profile，否则会把 exists/version 当档案内容存进去。"""
    f = tmp_path / "e.json"
    f.write_text(json.dumps({"exists": True, "version": 3, "profile": CAROUSEL},
                            ensure_ascii=False), encoding="utf-8")
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "甲", "--kind", "carousel", "--file", str(f)], s)
    assert code == 0 and "exists" not in calls[0]["payload"]["profile"]
    assert calls[0]["payload"]["profile"]["visual"] == CAROUSEL["visual"]


def test_new_profile_file_rejects_empty(monkeypatch, capsys, tmp_path):
    f = tmp_path / "empty.json"
    f.write_text("{}", encoding="utf-8")
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "甲", "--kind", "carousel", "--file", str(f)], s)
    assert code == 1 and calls == [] and "空对象" in out["error"]


def test_new_profile_duplicate_name_409_is_human_not_version_conflict(monkeypatch, capsys):
    """重名 409 **不是版本冲突**：翻成人话 + exit 1；绝不能走 exit 3 那条「重新 --get 再来」的路。"""
    s = _route(overrides={("POST", "/api/style-profile/sets"):
                          _Resp(409, {"detail": "套名「图文」已存在"})})
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "图文", "--kind", "carousel",
                                  "--from", "图文"], s)
    assert code == sp.EXIT_ERROR == 1
    assert code != sp.EXIT_CONFLICT
    assert "你已经有一套叫「图文」的风格了" in out["error"] and "换个名字" in out["error"]
    assert out.get("outcome") != "conflict"


def test_new_profile_requires_kind(monkeypatch, capsys):
    s = _route()
    _, code, err, calls = _run(monkeypatch, capsys, ["--new-profile", "甲"], s)
    assert code == 4 and calls == [] and "--kind" in err


def test_new_profile_no_longer_requires_base_version(monkeypatch, capsys):
    """服务端实测：建套端点不收 base_version（没有乐观锁）→ 不传也能建，**不再报用法错**。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "甲", "--kind", "carousel", "--from", "图文"], s)
    assert code == 0 and ("POST", "/api/style-profile/sets") in _paths(calls)


def test_base_version_on_set_management_is_ignored_but_announced(monkeypatch, capsys):
    """老文档还会传 --base-version：吃掉它照常干活，但**必须说一句**——
    静默接受会让运营以为这几步有并发保护（服务端根本没有），那是假承诺。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--new-profile", "甲", "--kind", "carousel",
                                  "--from", "图文", "--base-version", "3"], s)
    assert code == 0
    assert "不需要 --base-version" in err
    assert "base_version" not in calls[1]["payload"]


# =====================================================================
# 五、切默认 / 改名 / 删套
# =====================================================================

def test_set_active_patches_that_set(monkeypatch, capsys):
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys, ["--set-active", "文字版"], s)
    assert code == 0
    assert _paths(calls) == [("PATCH", "/api/style-profile/sets/文字版"),
                             ("GET", "/api/style-profile/sets")]
    assert calls[0]["payload"] == {"is_active": True}
    assert "%E6%96%87%E5%AD%97%E7%89%88" in calls[0]["url"], "套名进 path 必须转义"
    assert "默认已切到「文字版」" in err


def test_rename_profile_patches_new_name(monkeypatch, capsys):
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--rename-profile", "文字版", "长文版"], s)
    assert code == 0
    assert calls[0]["method"] == "PATCH" and calls[0]["path"] == "/api/style-profile/sets/文字版"
    assert calls[0]["payload"] == {"new_name": "长文版"}
    assert "「文字版」已改名为「长文版」" in err


def test_rename_duplicate_409_is_human(monkeypatch, capsys):
    s = _route(overrides={("PATCH", "/api/style-profile/sets/文字版"):
                          _Resp(409, {"detail": "套名「图文」已存在"})})
    out, code, err, _ = _run(monkeypatch, capsys, ["--rename-profile", "文字版", "图文"], s)
    assert code == 1 and "已经有一套叫「图文」了，换个名字" in out["error"]


def test_delete_profile_calls_delete(monkeypatch, capsys):
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys, ["--delete-profile", "文字版"], s)
    assert code == 0
    assert calls[0]["method"] == "DELETE" and calls[0]["path"] == "/api/style-profile/sets/文字版"
    assert calls[0]["payload"] is None
    assert out["deleted"] == "文字版"
    assert "已删掉「文字版」" in err


def test_delete_last_set_409_becomes_human_words(monkeypatch, capsys):
    """删到只剩一套 → 服务端 409。**必须翻成人话**，不能把服务端 JSON 甩给运营，
    也不能冒充版本冲突（走 exit 3 会把上层引去「重新 --get 再删」，重来一次还是同样结果）。"""
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": CAROUSEL},
               overrides={("DELETE", "/api/style-profile/sets/图文"):
                          _Resp(409, {"detail": "至少保留一套风格档案,不能删除仅剩的一套"})})
    out, code, err, calls = _run(monkeypatch, capsys, ["--delete-profile", "图文"], s)
    assert code == sp.EXIT_ERROR == 1
    assert code != sp.EXIT_CONFLICT, "这不是版本冲突，别让上层去重新 --get"
    assert "「图文」是你最后一套风格，删不得" in out["error"]
    assert "先新建一套再删这套" in out["error"], "得给他一条出路"
    assert out.get("outcome") != "conflict" and "current_version" not in out
    assert "别重试同一份 body" not in err


def test_delete_missing_set_404(monkeypatch, capsys):
    s = _route()
    out, code, err, _ = _run(monkeypatch, capsys, ["--delete-profile", "水墨风"], s)
    assert code == 1 and "风格档案套「水墨风」不存在" in out["error"]


def test_set_management_sends_no_guard_get(monkeypatch, capsys):
    """守卫 GET 已下线：这三个写动作**第一个请求就是写**（不先读一次当前档案）。"""
    for argv, method in ([["--set-active", "文字版"], "PATCH"],
                         [["--rename-profile", "文字版", "甲"], "PATCH"],
                         [["--delete-profile", "文字版"], "DELETE"]):
        s = _route()
        _run(monkeypatch, capsys, argv, s)
        assert s.calls[0]["method"] == method, f"{argv} 不该先 GET 一次"


# =====================================================================
# 六、`--init-sets`（新运营按默认配置的套数建齐）
# =====================================================================

def test_init_sets_creates_one_per_default_set(monkeypatch, capsys):
    """服务端不给新运营预建套；`from` 又跨不了 scope（实测 404），所以走
    「读默认配置那套的内容 → 带内容 POST」。is_active 那套**先建**（首套自动成默认）。"""
    s = _route(sets=[], admin_sets=[dict(S_TYPESET, is_active=False),
                                    dict(S_CAROUSEL, is_active=True)])
    out, code, err, calls = _run(monkeypatch, capsys, ["--init-sets"], s)
    assert code == 0
    assert _paths(calls) == [
        ("GET", "/api/style-profile/sets"),           # 默认配置有几套
        ("GET", "/api/style-profile/sets"),           # 他自己有几套
        ("GET", "/api/style-profile/admin-default"),  # 图文（is_active）的内容
        ("POST", "/api/style-profile/sets"),
        ("GET", "/api/style-profile/admin-default"),  # 文字版的内容
        ("POST", "/api/style-profile/sets"),
        ("GET", "/api/style-profile/sets"),           # 建完回读
    ]
    assert calls[0]["query"] == {"scope": "admin-default"}
    assert calls[2]["query"] == {"set": "图文"}, "is_active 那套必须先建，否则默认套落到别人头上"
    assert calls[3]["payload"] == {"name": "图文", "kind": "carousel", "profile": CAROUSEL}
    assert calls[5]["payload"] == {"name": "文字版", "kind": "typeset", "profile": TYPESET}
    assert out["created"] == ["图文", "文字版"] and out["skipped"] == []
    assert "建好了 2 套" in err


def test_init_sets_never_uses_cross_scope_from(monkeypatch, capsys):
    """⚠️ 实测：`from` 只在**同一个人名下**找套，指默认配置的套会 404。
    所以 POST body 里绝不能出现 from —— 出现了就是每次 onboarding 必挂。"""
    s = _route(sets=[], admin_sets=[S_CAROUSEL, S_TYPESET])
    _run(monkeypatch, capsys, ["--init-sets"], s)
    for c in s.calls:
        if c["method"] == "POST":
            assert "from" not in c["payload"]
            assert isinstance(c["payload"]["profile"], dict) and c["payload"]["profile"]


def test_init_sets_skips_existing_names(monkeypatch, capsys):
    """已有同名的套**跳过不覆盖**（覆盖别人已经调好的风格是不可逆的）。"""
    s = _route(sets=[dict(S_CAROUSEL)], admin_sets=[S_CAROUSEL, S_TYPESET])
    out, code, err, calls = _run(monkeypatch, capsys, ["--init-sets"], s)
    assert code == 0 and out["created"] == ["文字版"] and out["skipped"] == ["图文"]
    posts = [c for c in calls if c["method"] == "POST"]
    assert len(posts) == 1 and posts[0]["payload"]["name"] == "文字版"
    assert "原样没碰：图文" in err


def test_init_sets_when_nothing_to_do(monkeypatch, capsys):
    s = _route(sets=[dict(S_CAROUSEL), dict(S_TYPESET)], admin_sets=[S_CAROUSEL, S_TYPESET])
    out, code, err, calls = _run(monkeypatch, capsys, ["--init-sets"], s)
    assert code == 0 and out["created"] == [] and out["skipped"] == ["图文", "文字版"]
    assert not [c for c in calls if c["method"] == "POST"]
    assert "一套都没动" in out["say"]


def test_init_sets_refuses_when_default_config_empty(monkeypatch, capsys):
    """默认配置一套都没有 → 报人话 + 指路手动建，⛔ 绝不静默建出空套。"""
    s = _route(sets=[], admin_sets=[])
    out, code, err, calls = _run(monkeypatch, capsys, ["--init-sets"], s)
    assert code == 1
    assert not [c for c in calls if c["method"] == "POST"]
    assert "默认配置里一套风格都没有" in out["error"] and "--new-profile" in out["error"]


def test_init_sets_refuses_empty_default_content(monkeypatch, capsys):
    """默认配置那套内容是空的 → 同样拒绝（建出来的空套看不出坏，比报错危险得多）。"""
    s = _route(sets=[], admin_sets=[S_CAROUSEL], content={"图文": {}})
    out, code, err, calls = _run(monkeypatch, capsys, ["--init-sets"], s)
    assert code == 1
    assert not [c for c in calls if c["method"] == "POST"]
    assert "那套是空的" in out["error"]


# =====================================================================
# 七、`--version N` 配 `--profile` / `--kind`
# =====================================================================

def test_version_with_profile_uses_set_query(monkeypatch, capsys):
    """审查端按留痕行回溯：`--version 2 --profile 文字版` → `GET /versions/2?set=文字版`，
    服务端直接给**那一套**的那一版，`profile.visual.*` 可直读（不再有容器要剥）。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--version", "2", "--profile", "文字版"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile/versions/2")]
    assert calls[0]["query"] == {"set": "文字版"}
    assert out["profile"] == TYPESET and out["version"] == 2
    assert out["profile_name"] == "文字版" and out["outcome"] == "ok"
    # `--version` 端点不返 exists，留痕行必须按版本号写「本人档案 vN」而不是 v0
    assert out["trace_line"].startswith("风格档案：文字版 v2（本人档案，读取于 ")


def test_version_with_kind_lists_sets_first(monkeypatch, capsys):
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--version", "5", "--kind", "typeset"], s)
    assert code == 0
    assert _paths(calls) == [("GET", "/api/style-profile/sets"),
                             ("GET", "/api/style-profile/versions/5")]
    assert calls[1]["query"] == {"set": "文字版"}
    assert out["trace_line"].startswith("风格档案：文字版 v5（本人档案，读取于 ")


def test_version_with_kind_no_match_exit_0(monkeypatch, capsys):
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": CAROUSEL})
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--version", "5", "--kind", "typeset"], s)
    assert code == 0 and out["profile"] is None and out["outcome"] == "no_kind_match"
    assert _paths(calls) == [("GET", "/api/style-profile/sets")]


def test_bare_version_sends_no_set(monkeypatch, capsys):
    """不带 --profile/--kind 时不塞 set（服务端给 is_active 那套），输出原样透传。"""
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys, ["--version", "3"], s)
    assert code == 0 and calls[0]["query"] == {}
    assert out["profile"] == CAROUSEL
    assert "profile_name" not in out, "不点名就不该多出挑套字段"


def test_version_missing_set_is_server_error(monkeypatch, capsys):
    """点名的套不存在 → 服务端 404 → exit 1 说清楚。

    ⛔ 不能悄悄给 `profile: null` 让审查端拿内置默认去判老批次——那会判错。"""
    s = _route()
    out, code, err, _ = _run(monkeypatch, capsys, ["--version", "2", "--profile", "水墨风"], s)
    assert code == 1 and "风格档案套「水墨风」不存在" in out["error"]


# =====================================================================
# 八、`--put`：多套单套一个写法，守卫已下线
# =====================================================================

def test_put_sends_single_set_body_without_any_guard_get(monkeypatch, capsys, tmp_path):
    """`--get` 给哪一套、`--put` 就发回哪一套：body 是**单套内容**，且第一个请求就是 PUT。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(TYPESET, ensure_ascii=False), encoding="utf-8")
    s = _route()
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--put", str(f), "--base-version", "1"], s)
    assert code == 0
    assert _paths(calls) == [("PUT", "/api/style-profile")], "守卫 GET 已下线"
    assert calls[0]["payload"]["profile"] == TYPESET
    assert calls[0]["payload"]["base_version"] == 1


def test_put_named_set_goes_to_that_set(monkeypatch, capsys, tmp_path):
    """点名哪一套就写哪一套——`--put --profile 文字版` 必须把套名拼进 `?set=`。

    ⛔ 不拼 = 服务端落到 is_active 那套：运营以为在改文字版、实际改的是图文，
    响应照样 200、照样报「✓ 已整份覆盖」，要等下一批图出来才发现。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(TYPESET, ensure_ascii=False), encoding="utf-8")
    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--put", str(f), "--base-version", "1", "--profile", "文字版"], _route())
    assert code == 0
    assert _paths(calls)[0] == ("PUT", "/api/style-profile")
    assert calls[0]["query"]["set"] == "文字版"                       # 点名的套进了 ?set=
    assert "set=%E6%96%87%E5%AD%97%E7%89%88" in calls[0]["url"]      # 中文套名 URL 转义
    assert "文字版" in err                                            # 成功那行要说清写的是哪一套


def test_put_aborts_when_server_wrote_a_different_set(monkeypatch, capsys, tmp_path):
    """服务端回的 `set` 与点名的不一致 → 停下报错，绝不打「✓ 已整份覆盖」。

    这是静默错套的最后一道闸：`?set=` 拼错或被忽略时，响应仍是 200。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(TYPESET, ensure_ascii=False), encoding="utf-8")
    # 服务端"答非所问"：点名文字版，它却回 set=图文（?set= 被忽略 / 拼错时的真实形态）
    sender = _route(overrides={("PUT", "/api/style-profile"):
                               _Resp(200, {"exists": True, "version": 2, "set": "图文",
                                           "dropped_keys": []})})
    out, code, err, _ = _run(
        monkeypatch, capsys,
        ["--put", str(f), "--base-version", "1", "--profile", "文字版"], sender)
    assert code == 1
    assert "文字版" in out["error"] and "图文" in out["error"]
    assert "✓ 已整份覆盖" not in err


def test_rollback_and_versions_carry_the_named_set(monkeypatch, capsys):
    """回退与列历史也要点名——每套各有各的版本链，不点名就退/列了默认那套。"""
    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--versions", "--profile", "文字版"], _route())
    assert code == 0 and calls[0]["query"]["set"] == "文字版"

    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--rollback", "1", "--base-version", "2", "--profile", "文字版"], _route())
    assert code == 0
    assert _paths(calls)[0][0] == "POST" and calls[0]["query"]["set"] == "文字版"


def test_put_typeset_content_does_not_warn_about_density(monkeypatch, capsys, tmp_path):
    """文字版那套没有 density 段是**正常的**，别报它缺段——假警报看几次运营就再也不看警告了。"""
    f = tmp_path / "t.json"
    f.write_text(json.dumps(TYPESET, ensure_ascii=False), encoding="utf-8")
    s = _route()
    out, code, err, _ = _run(monkeypatch, capsys, ["--put", str(f), "--base-version", "1"], s)
    assert code == 0 and out["warnings"] == [] and "density" not in err


def test_put_carousel_missing_density_still_warns(monkeypatch, capsys, tmp_path):
    """图文那套缺 density 仍要警告（那是真断链）。"""
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"kind": "carousel", "visual": {}}, ensure_ascii=False),
                 encoding="utf-8")
    s = _route()
    out, code, err, _ = _run(monkeypatch, capsys, ["--put", str(f), "--base-version", "1"], s)
    assert code == 0 and any("density" in w for w in out["warnings"])


def test_put_still_requires_base_version(monkeypatch, capsys, tmp_path):
    """硬约束没被动过：`--put` 缺 --base-version → exit 4 且一个请求都不发。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(CAROUSEL, ensure_ascii=False), encoding="utf-8")
    s = _route()
    _, code, err, calls = _run(monkeypatch, capsys, ["--put", str(f)], s)
    assert code == sp.EXIT_USAGE == 4 and calls == [] and "--base-version" in err


def test_put_409_is_still_a_version_conflict(monkeypatch, capsys, tmp_path):
    """`--put` 的 409 是**真·乐观锁冲突**：仍走 exit 3 + current_version + 「别重试」。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(CAROUSEL, ensure_ascii=False), encoding="utf-8")
    s = _route(overrides={("PUT", "/api/style-profile"):
                          _Resp(409, {"detail": {"error": "版本冲突", "current_version": 5,
                                                 "updated_at": "2026-07-28T12:00:00"}})})
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--put", str(f), "--base-version", "3"], s)
    assert code == sp.EXIT_CONFLICT == 3
    assert out["outcome"] == "conflict" and out["current_version"] == 5
    assert len([c for c in calls if c["method"] == "PUT"]) == 1, "409 后绝不重发同一份 body"


def test_dropped_keys_advice_is_the_plain_one(monkeypatch, capsys, tmp_path):
    """dropped_keys 回到套内部字段级，补救话术也回到最朴素那句
    （容器时代那句「先 --version 取整份」已随容器下线）。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(CAROUSEL, ensure_ascii=False), encoding="utf-8")
    s = _route(overrides={("PUT", "/api/style-profile"):
                          _Resp(200, {"exists": True, "version": 4,
                                      "dropped_keys": ["visual"]})})
    out, code, err, _ = _run(monkeypatch, capsys, ["--put", str(f), "--base-version", "3"], s)
    assert code == 0 and out["dropped_keys"] == ["visual"]
    assert "本次覆盖丢掉了：visual" in err
    assert "先 `--get` 拿全量再重发" in err
    assert "--version" not in err.split("本次覆盖丢掉了")[1]


# =====================================================================
# 九、容器方案的遗产必须彻底消失
# =====================================================================

@pytest.mark.parametrize("gone", [
    "is_multi", "profiles_view", "select_set", "to_multi", "add_set", "set_active_set",
    "rename_set", "delete_set", "container_warnings", "guard_flat_put_over_multi",
])
def test_container_helpers_are_deleted(gone):
    """契约点名下线的十个函数：留着就会有人接着用，容器方案就永远走不干净。"""
    assert not hasattr(sp, gone), f"{gone} 应随 profiles-v1 容器方案一起删除"


def test_no_container_payload_ever_leaves_the_client(monkeypatch, capsys, tmp_path):
    """服务端有 B5 哨兵：顶层同时含 schema=="profiles-v1" 且有 profiles 键 → 400。
    客户端任何写路径都不该再拼出这种 body。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(CAROUSEL, ensure_ascii=False), encoding="utf-8")
    for argv in (["--put", str(f), "--base-version", "3"],
                 ["--new-profile", "甲", "--kind", "carousel"],
                 ["--set-active", "文字版"]):
        s = _route()
        _run(monkeypatch, capsys, argv, s)
        for c in s.calls:
            body = c["payload"] or {}
            profile = body.get("profile") if isinstance(body, dict) else None
            if isinstance(profile, dict):
                assert not (profile.get("schema") == "profiles-v1" and "profiles" in profile)


# =====================================================================
# 十、降级链与 exit 码没被动过
# =====================================================================

def test_network_failure_on_set_command_exits_2_with_named_trace_line(monkeypatch, capsys):
    """读不到服务 → exit 2 + 「没连上风格档案服务」；留痕行要**带上他点名的那一套**。"""
    def boom(*a, **k):
        raise ConnectionError("Max retries exceeded")

    monkeypatch.setattr(sys, "argv", ["style_profile.py", "--api-base", "https://stub.test",
                                      "--get", "--profile", "文字版"])
    monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: "k")
    monkeypatch.setattr(sp, "send_request", boom)
    with pytest.raises(SystemExit) as ei:
        sp.main()
    cap = capsys.readouterr()
    out = json.loads(cap.out.strip().splitlines()[-1])
    assert ei.value.code == sp.EXIT_UNREACHABLE == 2
    assert "没连上风格档案服务" in cap.err
    assert out["layer"] == "builtin_fallback" and out["say"] == sp.SAY_OFFLINE
    assert out["trace_line"].startswith("风格档案：文字版 v—（内置兜底")


def test_network_failure_with_kind_names_the_form_in_chinese(monkeypatch, capsys):
    """`--kind typeset` 挂掉时留痕行写「文字版」——⛔ 别把 typeset 这种英文取值写给运营看。"""
    def boom(*a, **k):
        raise ConnectionError("nope")

    monkeypatch.setattr(sys, "argv", ["style_profile.py", "--api-base", "https://stub.test",
                                      "--get", "--kind", "typeset"])
    monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: "k")
    monkeypatch.setattr(sp, "send_request", boom)
    with pytest.raises(SystemExit) as ei:
        sp.main()
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert ei.value.code == 2
    assert out["trace_line"].startswith("风格档案：文字版 v—（内置兜底")
    assert "typeset" not in out["trace_line"]


def test_401_on_set_endpoints_still_exits_2(monkeypatch, capsys):
    """套管理端点的 401/403 仍按「这把 key 读不到档案服务」走 exit 2 + 第 ③ 层。"""
    s = _route(overrides={("GET", "/api/style-profile/sets"):
                          _Resp(401, {"detail": "无效的 apikey"})})
    out, code, err, _ = _run(monkeypatch, capsys, ["--list-profiles"], s)
    assert code == sp.EXIT_UNREACHABLE == 2 and out["reason"] == "unauthorized"
    assert "没连上风格档案服务" in err


def test_exactly_one_action(monkeypatch, capsys):
    s = _route()
    _, code, err, calls = _run(monkeypatch, capsys, ["--list-profiles", "--init-sets"], s)
    assert code == 4 and calls == [] and "恰好指定一个动作" in err


def test_stdout_is_single_line_json_on_every_set_command(monkeypatch, capsys, tmp_path):
    """输出契约：stdout **只有一行** JSON，人话一律走 stderr（上层直接 json.loads 全量）。"""
    f = tmp_path / "set.json"
    f.write_text(json.dumps(CAROUSEL, ensure_ascii=False), encoding="utf-8")
    cases = [
        ["--list-profiles"],
        ["--get", "--profile", "文字版"],
        ["--get", "--profile", "水墨风"],
        ["--get", "--kind", "typeset"],
        ["--version", "2", "--profile", "文字版"],
        ["--new-profile", "甲", "--kind", "carousel", "--file", str(f)],
        ["--set-active", "文字版"],
        ["--rename-profile", "文字版", "乙"],
        ["--delete-profile", "文字版"],
        ["--init-sets"],
    ]
    for argv in cases:
        s = _route()
        monkeypatch.setattr(sys, "argv",
                            ["style_profile.py", "--api-base", "https://stub.test"] + argv)
        monkeypatch.setattr(sp.nbdpsy_common, "get_secret", lambda k: "k")
        monkeypatch.setattr(sp, "send_request", s)
        try:
            sp.main()
        except SystemExit as e:
            assert e.code == 0, f"{argv} 不该失败"
        out = capsys.readouterr().out
        assert out.count("\n") == 1, f"{argv} 的 stdout 不是单行：{out!r}"
        json.loads(out)


# =====================================================================
# 十一、运营视角话术：不许漏英文取值
# =====================================================================

@pytest.mark.parametrize("argv", [
    ["--list-profiles"],
    ["--get", "--kind", "typeset"],
    ["--new-profile", "水墨风", "--kind", "typeset"],
])
def test_no_english_kind_words_in_operator_facing_text(monkeypatch, capsys, argv):
    """⛔ 跟运营说话不许出现 carousel / typeset / scope 这些词，一律说「图文那套」「文字版那套」。"""
    s = _route(sets=[dict(S_CAROUSEL)], admin_sets=[dict(S_CAROUSEL)],
               content={"图文": CAROUSEL})
    out, code, err, _ = _run(monkeypatch, capsys, argv, s)
    say = (out or {}).get("say", "")
    for bad in ("carousel", "typeset", "scope"):
        assert bad not in say, f"{argv} 的 say 里混进了 {bad}：{say}"

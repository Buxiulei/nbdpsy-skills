"""style_profile.py 的第三种形态 `kind=video`（四个子形态）与「按上次」本机记忆。
全程 stub，⛔ 绝不打网络、⛔ 绝不碰真正的 ~/.config。

盯死五条（按翻车概率排序）：

1. **档案里不许有没人读的字段**（老板 2026-08-16 原话：「而不是一个死链，永远闲置不被调用」）。
   下面 `test_每个骨架字段都指得到一个消费者` 把这条做成可执行闸门：骨架里的每一个字段
   要么在 `video_style.FIELD_MAP` 里（有脚本读），要么在本文件的 `工序消费` 白名单里
   （有 SKILL.md 的必经工序读，且注明落点）。加字段不登记就红。
2. **子形态挑套要真的按 `video.form` 挑**：子形态在档案内容里、不在 `/sets` 列表里，
   所以只能逐套取回来看。挑错套 = 拿播客的旋钮去跑放映，脚本会安静地全用默认值出片。
3. **裸 `--get` 不受本机记忆影响**：创作端/审查端/guide/pipeline 四处都按裸 `--get` 读，
   让一个别人看不见的本地文件去改它，等于同一条命令在两台机器上出两种档案。
4. **本机记忆的三种坏情况都要优雅退回**（没文件 / 文件坏了 / 记的套已被删），
   ⛔ 不许抛、不许非零退出——「按上次」是省事用的，它自己出毛病不该让人今天做不成内容。
5. **视频那类不许报 density 假警报**（与文字版同一条道理：狼来了会让运营连真警告也不看）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"))

import pytest

import style_profile as sp
import video_style

CAROUSEL = {"kind": "carousel", "visual": {}, "density": {k: "x" for k in sp.DENSITY_KEYS}}
PODCAST = sp.video_skeleton("podcast")
MICROFILM = sp.video_skeleton("microfilm")
SLIDESHOW = sp.video_skeleton("slideshow")

S_CAROUSEL = {"name": "图文", "kind": "carousel", "is_active": True, "version": 3,
              "updated_at": "2026-08-01T10:00:00"}
S_PODCAST = {"name": "播客", "kind": "video", "is_active": False, "version": 2,
             "updated_at": "2026-08-16T10:00:00"}
S_MICROFILM = {"name": "微电影", "kind": "video", "is_active": False, "version": 1,
               "updated_at": "2026-08-16T11:00:00"}
ALL_SETS = [S_CAROUSEL, S_PODCAST, S_MICROFILM]
ALL_CONTENT = {"图文": CAROUSEL, "播客": PODCAST, "微电影": MICROFILM}


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    @property
    def text(self):
        return json.dumps(self._body, ensure_ascii=False)

    def json(self):
        return self._body


def _route(sets=None, content=None, admin_sets=None, admin_content=None, overrides=None):
    """按 (method, path) 派发的假服务端，行为对齐 nbdpsy-server v0.17.0（与多套那份同款）。"""
    sets = [dict(s) for s in (sets if sets is not None else ALL_SETS)]
    content = dict(content if content is not None else ALL_CONTENT)
    admin_sets = [dict(s) for s in (admin_sets if admin_sets is not None else [S_CAROUSEL])]
    admin_content = dict(admin_content if admin_content is not None else {"图文": CAROUSEL})
    overrides = overrides or {}
    calls = []

    def sender(method, url, key, payload=None, timeout=30):
        from urllib.parse import urlparse, parse_qs, unquote
        u = urlparse(url)
        path, query = unquote(u.path), parse_qs(u.query)
        calls.append({"method": method, "path": path,
                      "query": {k: v[0] for k, v in query.items()}, "payload": payload})
        if (method, path) in overrides:
            return overrides[(method, path)]
        scope = query.get("scope", ["self"])[0]
        want = query.get("set", [None])[0]

        if path == "/api/style-profile/sets":
            if method == "GET":
                return _Resp(200, {"sets": admin_sets if scope == "admin-default" else sets})
            row = {"name": payload["name"], "kind": payload["kind"], "is_active": not sets,
                   "version": 1, "updated_at": "2026-08-17T00:00:00"}
            sets.append(row)
            if payload.get("profile") is not None:
                content[row["name"]] = payload["profile"]
            return _Resp(200, dict(row))
        if path == "/api/style-profile":
            if method == "PUT":
                row = (next((x for x in sets if x["name"] == want), None) if want
                       else next((x for x in sets if x["is_active"]), None))
                if row is None:
                    return _Resp(404, {"error": f"风格档案套「{want}」不存在"})
                row["version"] += 1
                return _Resp(200, {"exists": True, "version": row["version"],
                                   "set": row["name"], "kind": row["kind"], "dropped_keys": []})
            if not sets:
                a = next((s for s in admin_sets if s["is_active"]), None)
                return _Resp(200, {"exists": False, "source": "admin_default", "base_version": 0,
                                   "set": a["name"], "kind": a["kind"],
                                   "admin_default_version": 4, "updated_at": a["updated_at"],
                                   "profile": admin_content[a["name"]]})
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
            return _Resp(200, {"profile": admin_content[row["name"]], "admin_default_version": 4,
                               "set": row["name"], "kind": row["kind"],
                               "updated_at": row["updated_at"]})
        if path == "/api/style-profile/versions":
            row = (next((x for x in sets if x["name"] == want), None) if want
                   else next((x for x in sets if x["is_active"]), None))
            if row is None:
                return _Resp(404, {"error": f"风格档案套「{want}」不存在"})
            return _Resp(200, {"versions": [], "total": 0, "set": row["name"],
                               "kind": row["kind"]})
        if path.startswith("/api/style-profile/versions/"):
            row = (next((s for s in sets if s["name"] == want), None) if want
                   else next((s for s in sets if s["is_active"]), None))
            if row is None:
                return _Resp(404, {"error": f"风格档案套「{want}」不存在"})
            return _Resp(200, {"version": int(path.rsplit("/", 1)[1]), "source": "manual",
                               "set": row["name"], "kind": row["kind"],
                               "profile": content[row["name"]]})
        return _Resp(404, {"error": f"no route {path}"})

    sender.calls = calls
    sender.sets = sets
    return sender


@pytest.fixture(autouse=True)
def _isolated_last_choice(monkeypatch, tmp_path):
    """⛔ 每条用例都把本机记忆指到 tmp：绝不许测试读写运营真正的 ~/.config/nbdpsy。"""
    monkeypatch.setattr(sp, "LAST_CHOICE_PATH", tmp_path / "last-choice.json")
    return tmp_path / "last-choice.json"


def _run(monkeypatch, capsys, argv, sender, key="k"):
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


def _leaves(d, prefix=()):
    """把嵌套 dict 摊平成叶子路径集合：{("narration","voice"), ...}。"""
    out = set()
    for k, v in d.items():
        if isinstance(v, dict):
            out |= _leaves(v, prefix + (k,))
        else:
            out.add(prefix + (k,))
    return out


# =====================================================================
# 一、⛔ 不许有死字段：每个骨架字段都要指得到一个真读它的地方
# =====================================================================

#: 没有「一条命令收口」的入口脚本、由 SKILL.md 必经工序读的字段。
#: **加一条就要写清落点**——写不出落点的字段就是死链，不许进骨架。
工序消费 = {
    "card": {
        ("template",): "card-video-spec.md 产线第④步「选版式模板」",
        ("narration", "voice"): "card-video-spec.md 产线第②步 tts_gen --voice",
        ("narration", "speed"): "card-video-spec.md 产线第②步 tts_gen --speed",
    },
    "microfilm": {
        ("look",): "cinematic-direction.md §一之三 落盘 direction.md 第一行「子风格：X」",
        ("ratio",): "SKILL.md 第2步 shots.json 的 video.ratio → build_manifest.py",
        ("ai_label",): "SKILL.md 第2步 shots.json 的 video.ai_label → build_manifest.py",
        ("narration", "engine"): "SKILL.md 第3步 tts_gen --engine",
        ("narration", "voice"): "SKILL.md 第3步 tts_gen --voice",
        ("narration", "speed"): "SKILL.md 第3步 tts_gen --speed",
        ("bgm", "mood"): "SKILL.md 第7步 gen_bgm.py --mood",
    },
}


@pytest.mark.parametrize("form", sp.VIDEO_FORMS)
def test_每个骨架字段都指得到一个消费者(form):
    """老板 2026-08-16：加一个没人读的字段就是新造一条死链。这条把它做成闸门。

    ⛔ 往 VIDEO_SKELETONS 加字段而不登记消费者（video_style.FIELD_MAP 或上面的 `工序消费`），
    这条就红——那正是要拦的事。"""
    有代码消费 = set(video_style.FIELD_MAP[form])
    有工序消费 = set(工序消费.get(form, {}))
    没人读 = _leaves(sp.VIDEO_SKELETONS[form]) - 有代码消费 - 有工序消费
    assert not 没人读, (f"「{sp.FORM_CN[form]}」骨架里这些字段没登记消费者："
                        f"{sorted('.'.join(p) for p in 没人读)}")


@pytest.mark.parametrize("form", sp.VIDEO_FORMS)
def test_骨架自己不触发任何警告(form):
    """刚建出来的套必须是干净的：骨架自己就报警等于第一天就教会运营无视警告。"""
    assert sp.video_warnings(sp.video_skeleton(form)) == []


@pytest.mark.parametrize("form", sp.VIDEO_FORMS)
def test_骨架形状(form):
    sk = sp.video_skeleton(form, tone={"person": "第二人称"}, structure={"ending": "邀请评论"})
    assert sk["kind"] == "video" and sk["video"]["form"] == form
    assert sk["tone"] == {"person": "第二人称"} and sk["structure"] == {"ending": "邀请评论"}
    assert sp.profile_form(sk) == form


def test_骨架之间互不共享可变对象():
    """两次建套拿到的必须是各自独立的 dict——共享同一个嵌套 dict，改一套会连带改另一套。"""
    a, b = sp.video_skeleton("slideshow"), sp.video_skeleton("slideshow")
    a["video"]["narration"]["voice"] = "改了"
    assert b["video"]["narration"]["voice"] != "改了"
    assert sp.VIDEO_SKELETONS["slideshow"]["narration"]["voice"] != "改了"


# =====================================================================
# 二、video_warnings：只报真死链，⛔ 不报「你没填 X」
# =====================================================================

def test_警告_缺video段():
    w = sp.video_warnings({"kind": "video"})
    assert len(w) == 1 and "没有 video 段" in w[0]


def test_警告_缺form():
    w = sp.video_warnings({"video": {"narration": {}}})
    assert len(w) == 1 and "没有 form" in w[0]


def test_警告_form拼错():
    w = sp.video_warnings({"video": {"form": "podcasts"}})
    assert len(w) == 1 and "podcasts" in w[0]


def test_警告_串了别条产线的字段():
    """从别的子形态复制过来的字段：这条产线一行都不读 = 死字段，必须点名。"""
    prof = sp.video_skeleton("podcast")
    prof["video"]["page_gap"] = 0.35            # 放映的旋钮，播客不读
    w = sp.video_warnings(prof)
    assert len(w) == 1 and "page_gap" in w[0]


def test_警告_oneline段挂在非oneline版式上():
    prof = sp.video_skeleton("card")
    prof["video"]["oneline"] = {"bg": "kepu"}
    w = sp.video_warnings(prof)
    assert len(w) == 1 and "tpl-oneline" in w[0]


def test_警告_oneline版式却没有oneline段():
    prof = sp.video_skeleton("card")
    prof["video"]["template"] = "tpl-oneline"
    w = sp.video_warnings(prof)
    assert len(w) == 1 and "build_oneline.py" in w[0]


def test_oneline段挂在oneline版式上不报警():
    prof = sp.video_skeleton("card")
    prof["video"]["template"] = "tpl-oneline"
    prof["video"]["oneline"] = {"bg": "kepu", "canvas": "3:4", "max_line_chars": 12}
    assert sp.video_warnings(prof) == []


def test_视频档案不报density假警报(monkeypatch, capsys, tmp_path):
    """视频那类没有 density 段是**正常的**（它没有插画、没有信息点），
    与文字版同一条道理：假警报看几次，运营以后连真警告也不看了。"""
    f = tmp_path / "v.json"
    f.write_text(json.dumps(PODCAST, ensure_ascii=False), encoding="utf-8")
    out, code, err, _ = _run(monkeypatch, capsys,
                             ["--put", str(f), "--base-version", "2", "--form", "podcast"],
                             _route())
    assert code == 0 and out["warnings"] == [] and "density" not in err


# =====================================================================
# 三、`--form` 挑套：子形态在内容里，不在 /sets 列表里
# =====================================================================

def test_按子形态取套(monkeypatch, capsys):
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--form", "podcast"], _route())
    assert code == 0
    assert out["profile_name"] == "播客" and out["profile"] == PODCAST
    assert out["outcome"] == "ok"
    # 列一次套 + 逐套取内容（播客排在微电影前面，一次就中）
    assert _paths(calls)[0] == ("GET", "/api/style-profile/sets")
    assert calls[1]["query"]["set"] == "播客"


def test_按子形态取套要逐套找到对的那条产线(monkeypatch, capsys):
    """列表里两套 kind 都是 video，只有内容里的 form 分得开它们——
    ⛔ 挑错套 = 拿播客的旋钮去跑微电影，脚本会安安静静地全用默认值出片。"""
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--form", "microfilm"], _route())
    assert code == 0 and out["profile_name"] == "微电影"
    assert sp.profile_form(out["profile"]) == "microfilm"
    assert [c["query"].get("set") for c in calls[1:]] == ["播客", "微电影"], "应逐套取回来看"


def test_按子形态优先取默认那套(monkeypatch, capsys):
    """两套同子形态时 is_active 优先（与 --kind 同一口径）。"""
    a = dict(S_PODCAST, name="播客A", is_active=True)
    b = dict(S_PODCAST, name="播客B", is_active=False)
    s = _route(sets=[b, a], content={"播客A": PODCAST, "播客B": PODCAST})
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--form", "podcast"], s)
    assert code == 0 and out["profile_name"] == "播客A"
    assert calls[1]["query"]["set"] == "播客A", "第一次就该问 is_active 那套"


def test_按子形态没匹配上_给null且exit0(monkeypatch, capsys):
    """没这条产线的套 → profile:null + 一句人话，**exit 仍是 0**：
    上层据此用内置默认继续做内容，退非 0 会被当成「服务挂了」而走错降级层。"""
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": CAROUSEL})
    out, code, err, _ = _run(monkeypatch, capsys, ["--get", "--form", "microfilm"], s)
    assert code == 0 and out["profile"] is None and out["outcome"] == "no_form_match"
    assert "微电影" in out["say"] and "微电影" in out["trace_line"]


def test_零套运营按子形态回落到默认配置(monkeypatch, capsys):
    """他一套都没有：裸 GET 拿他跟随的默认配置那套，子形态对得上才算挑中。"""
    s = _route(sets=[], admin_sets=[dict(S_PODCAST, is_active=True)],
               admin_content={"播客": PODCAST})
    out, code, err, _ = _run(monkeypatch, capsys, ["--get", "--form", "podcast"], s)
    assert code == 0 and out["outcome"] == "ok" and out["profile"] == PODCAST

    s2 = _route(sets=[], admin_sets=[dict(S_CAROUSEL)], admin_content={"图文": CAROUSEL})
    out2, code2, _, _ = _run(monkeypatch, capsys, ["--get", "--form", "podcast"], s2)
    assert code2 == 0 and out2["profile"] is None, "默认配置是图文那套，别冒充播客那套"


def test_写命令也能按子形态点名(monkeypatch, capsys, tmp_path):
    """⛔ 读能点名而写不能点名 = 运营以为在改播客、实际改的是默认那套（静默错套）。"""
    f = tmp_path / "v.json"
    f.write_text(json.dumps(MICROFILM, ensure_ascii=False), encoding="utf-8")
    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--put", str(f), "--base-version", "1", "--form", "microfilm"], _route())
    assert code == 0
    assert calls[-1]["method"] == "PUT" and calls[-1]["query"]["set"] == "微电影"


def test_按子形态列历史与回退(monkeypatch, capsys):
    out, code, err, calls = _run(monkeypatch, capsys, ["--versions", "--form", "podcast"], _route())
    assert code == 0 and calls[-1]["query"]["set"] == "播客"


def test_按子形态取某一版(monkeypatch, capsys):
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--version", "2", "--form", "podcast"], _route())
    assert code == 0 and out["profile_name"] == "播客"
    assert calls[-1]["path"] == "/api/style-profile/versions/2"
    assert calls[-1]["query"]["set"] == "播客"
    assert "播客 v2" in out["trace_line"], "审查端按留痕行回溯，套名与版本都不能丢"


def test_按子形态取某一版没匹配_exit0(monkeypatch, capsys):
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": CAROUSEL})
    out, code, err, _ = _run(monkeypatch, capsys, ["--version", "2", "--form", "podcast"], s)
    assert code == 0 and out["profile"] is None and out["outcome"] == "no_form_match"


def test_运营老大按子形态改默认配置(monkeypatch, capsys, tmp_path):
    """`--admin-default --form` 要在**默认配置的套**里挑（scope=admin-default），
    ⛔ 别去他自己名下挑——挑出来的名字拿去写默认配置，会写到同名的另一套上。"""
    f = tmp_path / "v.json"
    f.write_text(json.dumps(PODCAST, ensure_ascii=False), encoding="utf-8")
    s = _route(admin_sets=[dict(S_CAROUSEL), dict(S_PODCAST)],
               admin_content={"图文": CAROUSEL, "播客": PODCAST})
    out, code, err, calls = _run(monkeypatch, capsys,
                                 ["--admin-default", str(f), "--form", "podcast"], s)
    assert code == 0
    assert calls[0]["query"].get("scope") == "admin-default", "要列默认配置的套"
    assert calls[-1]["method"] == "PUT" and calls[-1]["query"]["set"] == "播客"


def test_没有这条产线的套时改它要报人话(monkeypatch, capsys, tmp_path):
    f = tmp_path / "v.json"
    f.write_text(json.dumps(PODCAST, ensure_ascii=False), encoding="utf-8")
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": CAROUSEL})
    out, code, err, _ = _run(
        monkeypatch, capsys, ["--put", str(f), "--base-version", "1", "--form", "podcast"], s)
    assert code == 1 and "播客" in out["error"] and "--new-profile" in out["error"]


# =====================================================================
# 四、建套：视频那类必须点明子形态
# =====================================================================

def test_建视频套必须带form(monkeypatch, capsys):
    out, code, err, _ = _run(monkeypatch, capsys,
                             ["--new-profile", "我的播客", "--kind", "video"], _route())
    assert code == sp.EXIT_USAGE and "--form" in err


def test_建视频套用该子形态的骨架(monkeypatch, capsys):
    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--new-profile", "我的微电影", "--kind", "video", "--form", "microfilm"], _route())
    assert code == 0
    post = next(c for c in calls if c["method"] == "POST")
    assert post["payload"]["kind"] == "video"
    assert post["payload"]["profile"]["video"]["form"] == "microfilm"
    assert post["payload"]["profile"]["video"]["look"] == "暖雾"
    assert "微电影" in err and "视频" not in err.split("已新建")[1][:20], "报子形态不报「视频」"


def test_建视频套沿用他在用那套的语气(monkeypatch, capsys):
    """tone / structure 跟形态无关（契约定的），别让他每建一套就重写一遍语气。"""
    mine = dict(CAROUSEL, tone={"person": "第二人称"}, structure={"ending": "邀请评论"})
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": mine})
    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--new-profile", "放映", "--kind", "video", "--form", "slideshow"], s)
    assert code == 0
    post = next(c for c in calls if c["method"] == "POST")
    assert post["payload"]["profile"]["tone"] == {"person": "第二人称"}


def test_建视频套优先用默认配置里同子形态那套(monkeypatch, capsys):
    """⛔ 别自己编一份：默认配置里有同子形态的套就照抄它。"""
    admin_pod = dict(PODCAST)
    admin_pod["video"] = dict(admin_pod["video"], player={"theme": "zhishang", "fade_out": 1.5})
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": CAROUSEL},
               admin_sets=[dict(S_PODCAST, is_active=True)], admin_content={"播客": admin_pod})
    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--new-profile", "我的播客", "--kind", "video", "--form", "podcast"], s)
    assert code == 0
    post = next(c for c in calls if c["method"] == "POST")
    assert post["payload"]["profile"]["video"]["player"]["theme"] == "zhishang"


def test_默认配置里是别的子形态时退回骨架(monkeypatch, capsys):
    """默认配置里的视频套若是别条产线的，拿来当骨架 = 给他一套「播客的旋钮 + 放映的名字」。"""
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": CAROUSEL},
               admin_sets=[dict(S_PODCAST, is_active=True)], admin_content={"播客": PODCAST})
    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--new-profile", "放映", "--kind", "video", "--form", "slideshow"], s)
    assert code == 0
    post = next(c for c in calls if c["method"] == "POST")
    assert post["payload"]["profile"]["video"]["form"] == "slideshow"
    assert "page_gap" in json.dumps(post["payload"]["profile"], ensure_ascii=False)


def test_复制跨子形态被拒(monkeypatch, capsys):
    """服务端的 from 是原样复制内容：拿播客那套复制成「微电影」，建出来的套 form 仍是
    podcast，`--form microfilm` 永远挑不中它（运营会以为「建了但没生效」）。"""
    out, code, err, _ = _run(
        monkeypatch, capsys,
        ["--new-profile", "新微电影", "--kind", "video", "--form", "microfilm",
         "--from", "播客"], _route())
    assert code == 1 and "播客" in out["error"] and "微电影" in out["error"]


def test_复制同子形态放行(monkeypatch, capsys):
    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--new-profile", "播客二号", "--kind", "video", "--form", "podcast",
         "--from", "播客"], _route())
    assert code == 0
    post = next(c for c in calls if c["method"] == "POST")
    assert post["payload"]["from"] == "播客"


def test_从文件建套时命令行的子形态说了算(monkeypatch, capsys, tmp_path):
    """文件里的 form 与命令行不一致：按命令行算并**改写内容里的 form**——
    不改写就会建出一套 `--form` 永远挑不中的套。"""
    f = tmp_path / "s.json"
    f.write_text(json.dumps(PODCAST, ensure_ascii=False), encoding="utf-8")
    out, code, err, calls = _run(
        monkeypatch, capsys,
        ["--new-profile", "放映", "--kind", "video", "--form", "slideshow",
         "--file", str(f)], _route())
    assert code == 0
    post = next(c for c in calls if c["method"] == "POST")
    assert post["payload"]["profile"]["video"]["form"] == "slideshow"
    assert "按命令行算" in err


# =====================================================================
# 五、用法闸门
# =====================================================================

@pytest.mark.parametrize("argv,片段", [
    (["--get", "--form", "podcast", "--profile", "播客"], "二选一"),
    (["--get", "--form", "podcast", "--kind", "typeset"], "没有子形态"),
    (["--list-profiles", "--form", "podcast"], "--form 只能配"),
    (["--get", "--last", "--profile", "播客"], "二选一"),
    (["--list-profiles", "--last"], "--last 只能配 --get"),
])
def test_用法错误退4(monkeypatch, capsys, argv, 片段):
    """用法错误退 4 不退 2——2 是「没连上风格档案服务」的专用信号，退 2 会让上层误判降级。"""
    out, code, err, _ = _run(monkeypatch, capsys, argv, _route())
    assert code == sp.EXIT_USAGE and 片段 in err


def test_kind_video配form只是多余不报错(monkeypatch, capsys):
    out, code, err, _ = _run(monkeypatch, capsys,
                             ["--get", "--kind", "video", "--form", "podcast"], _route())
    assert code == 0 and out["profile_name"] == "播客" and "多余" in err


@pytest.mark.parametrize("argv", [
    ["--get", "--form", "podcast"],
    ["--get", "--form", "microfilm"],
    ["--new-profile", "我的放映", "--kind", "video", "--form", "slideshow"],
])
def test_不跟运营说英文取值(monkeypatch, capsys, argv):
    """⛔ 跟运营说话不许出现 video / slideshow / podcast 这些词，一律说「放映」「播客」。"""
    out, code, err, _ = _run(monkeypatch, capsys, argv, _route())
    say = (out or {}).get("say", "")
    for bad in ("video", "slideshow", "podcast", "microfilm", "carousel"):
        assert bad not in say, f"{argv} 的 say 里混进了 {bad}：{say}"


# =====================================================================
# 六、「按上次」本机记忆
# =====================================================================

def test_记忆往返(_isolated_last_choice):
    assert sp.write_last_choice("播客", "video", "podcast") is True
    got = sp.read_last_choice()
    assert got["name"] == "播客" and got["kind"] == "video" and got["form"] == "podcast"
    assert got["at"]


def test_取档案后会记下这次用的那一套(monkeypatch, capsys, _isolated_last_choice):
    out, code, err, _ = _run(monkeypatch, capsys, ["--get", "--form", "podcast"], _route())
    assert code == 0
    got = sp.read_last_choice()
    assert got["name"] == "播客" and got["form"] == "podcast"


def test_没挑中时不记(monkeypatch, capsys, _isolated_last_choice):
    """没挑中 = 实际用的是内置默认。记下来的话，下次 --last 会取到一套他这次根本没用上的风格。"""
    s = _route(sets=[dict(S_CAROUSEL)], content={"图文": CAROUSEL})
    out, code, err, _ = _run(monkeypatch, capsys, ["--get", "--form", "podcast"], s)
    assert code == 0 and out["profile"] is None
    assert sp.read_last_choice() is None


def test_按上次命中(monkeypatch, capsys, _isolated_last_choice):
    sp.write_last_choice("微电影", "video", "microfilm")
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--last"], _route())
    assert code == 0 and out["profile_name"] == "微电影"
    assert calls[0]["query"]["set"] == "微电影", "直接问那一套，不必先列套"
    assert "按上次" in err


def test_按上次_没有记录时退回默认那套(monkeypatch, capsys, _isolated_last_choice):
    """降级①：新机器 / 头一次用。⛔ 不报错、不非零退出。"""
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--last"], _route())
    assert code == 0 and out["profile"] == CAROUSEL          # 服务端 is_active 那套
    assert "没有" in err and _paths(calls) == [("GET", "/api/style-profile")]


@pytest.mark.parametrize("坏内容", ["", "{不是 json", "[]", '{"kind":"video"}', '{"name":""}'])
def test_按上次_记录坏了退回默认那套(monkeypatch, capsys, _isolated_last_choice, 坏内容):
    """降级②：文件被别的东西覆盖 / 残缺 / 没有 name。五种坏法都只能优雅退回。

    退回之后这一次照样算「用过一套」，坏文件会被这次的记录**原地治好**——
    ⛔ 不许留着坏文件让它每次都走降级（那就成了一个永远治不好的毛病）。"""
    _isolated_last_choice.write_text(坏内容, encoding="utf-8")
    assert sp.read_last_choice() is None, "坏文件必须一律当作没有记录"
    out, code, err, _ = _run(monkeypatch, capsys, ["--get", "--last"], _route())
    assert code == 0 and out["profile"] == CAROUSEL
    assert sp.read_last_choice()["name"] == "图文"


def test_按上次_记的那套已被删退回默认那套(monkeypatch, capsys, _isolated_last_choice):
    """降级③：改名 / 删了 / 换了个账号的 key。"""
    sp.write_last_choice("已经删掉的套", "video", "podcast")
    out, code, err, calls = _run(monkeypatch, capsys, ["--get", "--last"], _route())
    assert code == 0 and out["profile"] == CAROUSEL
    assert "已经不在" in err
    assert _paths(calls) == [("GET", "/api/style-profile"), ("GET", "/api/style-profile")]


def test_按上次_零套运营记到同名默认套不算命中(monkeypatch, capsys, _isolated_last_choice):
    """零套运营带 set 会被服务端忽略而回落默认配置那套：名字对不上就不算命中，
    ⛔ 否则会把「图文」的内容当成他要的那一套。"""
    sp.write_last_choice("播客", "video", "podcast")
    s = _route(sets=[], admin_sets=[dict(S_CAROUSEL)], admin_content={"图文": CAROUSEL})
    out, code, err, _ = _run(monkeypatch, capsys, ["--get", "--last"], s)
    assert code == 0 and out["profile"] == CAROUSEL and out.get("profile_name") is None


def test_按上次_服务端500照旧报错不当成没记录(monkeypatch, capsys, _isolated_last_choice):
    """只吞 404（那套没了）。别的 4xx/5xx 是真故障，糊成「没记录」会把故障藏起来。"""
    sp.write_last_choice("播客", "video", "podcast")
    s = _route(overrides={("GET", "/api/style-profile"): _Resp(500, {"error": "boom"})})
    out, code, err, _ = _run(monkeypatch, capsys, ["--get", "--last"], s)
    assert code == 1 and "500" in out["error"]


def test_裸get不受本机记忆影响(monkeypatch, capsys, _isolated_last_choice):
    """**这条是本机记忆与 is_active 的裁决**：没人点名时一律听服务端的 is_active。

    创作端 / 审查端 / guide / pipeline 四处都按裸 `--get` 读，让一个别人看不见的本地文件
    去改它，等于同一条命令在两台机器上出两种档案。"""
    sp.write_last_choice("微电影", "video", "microfilm")
    out, code, err, calls = _run(monkeypatch, capsys, ["--get"], _route())
    assert code == 0 and out["profile"] == CAROUSEL          # is_active 那套，不是记忆那套
    assert _paths(calls) == [("GET", "/api/style-profile")]
    assert "set" not in calls[0]["query"]


def test_点名优先于本机记忆(monkeypatch, capsys, _isolated_last_choice):
    sp.write_last_choice("微电影", "video", "microfilm")
    out, code, err, _ = _run(monkeypatch, capsys, ["--get", "--profile", "播客"], _route())
    assert code == 0 and out["profile_name"] == "播客"
    assert sp.read_last_choice()["name"] == "播客", "点名之后记忆要跟着更新"


def test_写不进去也不打断(monkeypatch, capsys, tmp_path):
    """磁盘满 / 只读 home / 没有 ~/.config 权限，都不该让一条已经成功的 --get 变成失败。"""
    挡路的文件 = tmp_path / "占位"
    挡路的文件.write_text("我不是目录", encoding="utf-8")
    monkeypatch.setattr(sp, "LAST_CHOICE_PATH", 挡路的文件 / "last-choice.json")
    assert sp.write_last_choice("播客", "video", "podcast") is False
    out, code, err, _ = _run(monkeypatch, capsys, ["--get", "--form", "podcast"], _route())
    assert code == 0 and out["profile_name"] == "播客"
    assert "没能记住" in err


def test_读不动也不抛(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "LAST_CHOICE_PATH", tmp_path)      # 指到一个目录上
    assert sp.read_last_choice() is None

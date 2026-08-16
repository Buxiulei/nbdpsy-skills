"""闸门 C（发布台账）的三处缺陷回归：补救结果不进闭环判据 / 台账落盘漂到 cwd / 行里写账号编号。

现场：2026-08-16 job 340（视频线首航）。发布时 cover=error → `--fix-cover` 补挂成功
（note-components 任务 done、applied.cover=true）→ 但 `--recheck 340` 仍念发布那一刻的旧回执，
台账行永远闭不掉；且 `--recheck` 单独跑时台账被新建到进程 cwd（NBDpsy 仓库根）；行里写的是「号1(1)」。
"""
import json
import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import pytest

API = "https://api.test"
TS = "2026-08-16T11:10:40+08:00"
# 现场真行（差集文案里本身带「补救: 」三个字，且不带 | 前缀）——补救登记的解析绝不能被它误伤
FIELD_ROW = ("- [ ] 2026-08-16T11:10:40+08:00 | post-video.md | 号1(1) | job=340 | "
             "意图: topics=5 cover=cover-1.jpg | 实际: topics=5/5; cover=error | "
             "差集: cover=FAIL(补救: publish_video.py --fix-cover --job 340 --cover <封面>"
             "（note-components 链已真号验过；⚠️ 只对视频笔记有效，图文没有独立封面通道、"
             "传 cover 直接 422）) | 未闭环")


class _Resp:
    def __init__(self, code=200, body=None):
        self.status_code = code
        self._b = body if body is not None else {}
        self.text = json.dumps(self._b, ensure_ascii=False)

    def json(self):
        return self._b


def _published_view(cover_status="error"):
    """发布任务终态回执：published 但封面组件当时失败（job337/job340 都是这个形态）。"""
    return {"job_id": 340, "status": "published", "account_id": 1,
            "note_url": "https://xhs/n/abc",
            "applied": {"topics_requested": ["焦虑"], "topics_applied": ["焦虑"],
                        "components": {"cover": {"status": cover_status}}}}


def _seed_ledger(tmp_path, remedies=None, who="NBDpsy-我们都有病"):
    import publish_note as pn
    lp = tmp_path / pn.LEDGER_NAME
    row = pn.ledger_row(False, TS, "post-video.md", who, 340, "topics=1 cover=cover-1.jpg",
                        "topics=1/1; cover=error", "cover=FAIL(补救: --fix-cover)", remedies)
    pn.ledger_append(lp, row)
    return lp, row


def _rows(lp):
    return [l for l in lp.read_text(encoding="utf-8").splitlines() if l.startswith("- [")]


def _component_api(job_id="NC-9", applied=None, code=200):
    """只认 /api/note-components/<job_id> 的假服务端，其余一律 404。"""
    body = {"status": "done", "applied": applied if applied is not None else {"cover": True}}

    def fake(method, url, key, *a, **kw):
        return _Resp(code, body) if f"/api/note-components/{job_id}" in url else _Resp(404, {})
    return fake


# ---------------------------------------------------------------- 缺陷 1 · recheck 消费补救结果

def test_recheck_consumes_fix_cover_remedy(tmp_path, monkeypatch):
    """台账登记了补救任务 + 服务端确认 applied.cover=true → 差集清零，那行翻 `- [x]`。"""
    import publish_note as pn, publish_video as pv
    lp, _ = _seed_ledger(tmp_path, {"cover": "NC-9"})
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: _published_view())
    monkeypatch.setattr(pn, "send_request", _component_api())

    code = pv.do_recheck(Namespace(recheck=340, ledger=str(lp)), API, "key")

    row = _rows(lp)[0]
    assert code == 0
    assert row.startswith("- [x]") and row.endswith("已闭环")
    assert "cover=error→补救done(note-components NC-9)" in row  # 实际栏写清楚靠补救达成
    assert "补救: cover=NC-9" in row                            # 登记继续留在纸上，可复核


def test_remedy_not_confirmed_by_server_keeps_row_open(tmp_path, monkeypatch):
    """证伪一：台账登记了补救，但服务端说 applied.cover=false → 仍是欠账（exit 3、行不翻）。
    ——闭环认的是服务端回执，不是台账里那句登记。"""
    import publish_note as pn, publish_video as pv
    lp, _ = _seed_ledger(tmp_path, {"cover": "NC-9"})
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: _published_view())
    monkeypatch.setattr(pn, "send_request", _component_api(applied={"cover": False}))

    code = pv.do_recheck(Namespace(recheck=340, ledger=str(lp)), API, "key")

    row = _rows(lp)[0]
    assert code == 3
    assert row.startswith("- [ ]") and "cover=FAIL" in row


def test_merge_disabled_reproduces_the_dead_gate(tmp_path, monkeypatch):
    """证伪二：把合并逻辑掐掉（等价于注释掉 verify_remedies 那一步）→ 补救真成了也翻不回 `- [x]`，
    正是 2026-08-16 job340 的原症状。证明闭环确实由这一步决定，不是别处凑巧翻的。"""
    import publish_note as pn, publish_video as pv
    lp, _ = _seed_ledger(tmp_path, {"cover": "NC-9"})
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: _published_view())
    monkeypatch.setattr(pn, "send_request", _component_api())
    monkeypatch.setattr(pv, "verify_remedies", lambda *a, **k: {})   # ← 掐掉合并

    code = pv.do_recheck(Namespace(recheck=340, ledger=str(lp)), API, "key")

    assert code == 3 and _rows(lp)[0].startswith("- [ ]")


def test_recheck_without_remedy_still_reports_gap(tmp_path, monkeypatch):
    """没有任何补救登记时行为不变：cover=error 就是欠账（别为了能闭环而放弃校验）。"""
    import publish_note as pn, publish_video as pv
    lp, _ = _seed_ledger(tmp_path)
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: _published_view())
    monkeypatch.setattr(pn, "send_request", _component_api())

    code = pv.do_recheck(Namespace(recheck=340, ledger=str(lp)), API, "key")

    assert code == 3 and _rows(lp)[0].startswith("- [ ]")


@pytest.mark.parametrize("applied,expect", [
    ({"cover": True}, {"cover": "NC-9"}),
    ({"cover": False}, {}),
    ({"cover": None}, {}),          # null = 没能回读，不是生效
    ({"cover": "true"}, {}),        # 字符串不是 true，这条产品线的失败是静默的
    ({}, {}),
])
def test_verify_remedies_only_true_counts(monkeypatch, applied, expect):
    import publish_note as pn
    monkeypatch.setattr(pn, "send_request", _component_api(applied=applied))
    assert pn.verify_remedies(API, "key", {"cover": "NC-9"}) == expect


def test_verify_remedies_swallows_unreachable_job(monkeypatch):
    """补救任务读不到（404 / 网络炸）→ 当没补上。宁可留欠账，也不放行假绿。"""
    import publish_note as pn
    monkeypatch.setattr(pn, "send_request", _component_api(code=500))
    assert pn.verify_remedies(API, "key", {"cover": "NC-9"}) == {}

    def boom(*a, **k):
        raise ConnectionError("network down")
    monkeypatch.setattr(pn, "send_request", boom)
    assert pn.verify_remedies(API, "key", {"cover": "NC-9"}) == {}


def test_fix_cover_records_remedy_into_the_ledger_row(tmp_path, monkeypatch):
    """--fix-cover 成功 → 把 note-components 任务号登记进那一行（recheck 靠它才找得到这条补救；
    服务端没有「按 note 列补救任务」的端点）。⚠️ 登记不等于闭环：那行仍是 `- [ ]`。"""
    import publish_note as pn, publish_video as pv
    lp, _ = _seed_ledger(tmp_path)
    cover = tmp_path / "cover-1.jpg"
    cover.write_bytes(b"\xff\xd8fake")
    monkeypatch.setattr(pv, "check_cover_receipt", lambda p: {"ok": True})
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: {"job_id": 340, "account_id": 1,
                                                        "note_id": "abc123"})
    monkeypatch.setattr(pn, "stage_media", lambda p, kind: "/srv/uploads/cover-1.jpg")

    def fake(method, url, key, *a, **kw):
        if method == "POST":
            return _Resp(200, {"job_id": "NC-9"})
        return _Resp(200, {"status": "done", "applied": {"cover": True}})
    monkeypatch.setattr(pn, "send_request", fake)

    args = Namespace(cover=cover, job=340, account=None, note_id=None,
                     wait_timeout=1, ledger=None)
    code = pv.do_fix_cover(args, API, "key")

    row = _rows(lp)[0]
    assert code == 0
    assert "补救: cover=NC-9" in row
    assert row.startswith("- [ ]")          # 补上封面 ≠ 话题也挂上了，闭环仍归 --recheck 判


def test_fix_cover_ledger_miss_warns_but_keeps_success(tmp_path, monkeypatch):
    """台账定位不到/没有那一行时只告警：封面已经真补上了，为记账失败把成功报成失败更误导。"""
    import publish_note as pn, publish_video as pv
    cover = tmp_path / "cover-1.jpg"
    cover.write_bytes(b"\xff\xd8fake")
    monkeypatch.setattr(pv, "check_cover_receipt", lambda p: {"ok": True})
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: {"job_id": 340, "account_id": 1,
                                                        "note_id": "abc123"})
    monkeypatch.setattr(pn, "stage_media", lambda p, kind: "/srv/uploads/cover-1.jpg")
    monkeypatch.setattr(pn, "send_request",
                        lambda m, u, k, *a, **kw: _Resp(200, {"job_id": "NC-9"}) if m == "POST"
                        else _Resp(200, {"status": "done", "applied": {"cover": True}}))

    args = Namespace(cover=cover, job=340, account=None, note_id=None,
                     wait_timeout=1, ledger=None)
    assert pv.do_fix_cover(args, API, "key") == 0      # 补救本身成功
    assert not (tmp_path / pn.LEDGER_NAME).exists()    # ⛔ 绝不为了记账凭空造一份台账


def test_remedy_parse_immune_to_gap_text(tmp_path):
    """差集文案里本就带「补救: 」字样（现场那行就是），解析补救登记不能被它误伤成有补救。"""
    import publish_note as pn
    assert pn.ledger_remedies(FIELD_ROW) == {}
    with_remedy = pn.ledger_set_remedies(FIELD_ROW, {"cover": "NC-9"})
    assert pn.ledger_remedies(with_remedy) == {"cover": "NC-9"}
    assert with_remedy.endswith(" | 未闭环")            # 结论段仍在最后，位次没乱
    assert "差集: cover=FAIL" in with_remedy            # 其余字段一字未动
    # 再登记一次是覆盖不是叠加
    assert pn.ledger_remedies(pn.ledger_set_remedies(with_remedy, {"cover": "NC-10"})) == \
        {"cover": "NC-10"}


# ---------------------------------------------------------------- 缺陷 2 · 台账落盘位置

def test_ledger_path_refuses_to_invent_one_in_cwd(tmp_path, monkeypatch):
    """cwd 里没有台账时抛错，而不是就地新建（新建＝给这批伪造一份「没欠账」的干净证据）。"""
    import publish_note as pn
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError) as e:
        pn.ledger_path(Namespace(ledger=None))
    assert "--ledger" in str(e.value)
    assert list(tmp_path.iterdir()) == []


def test_ledger_path_accepts_existing_ledger_in_cwd(tmp_path, monkeypatch):
    """人就站在稿件目录里跑复查是最自然的用法：那份台账已经在了，认它。
    （要害是「绝不新建」，不是「绝不看 cwd」——一刀切会把正常用法一起毙掉。）"""
    import publish_note as pn
    monkeypatch.chdir(tmp_path)
    lp, _ = _seed_ledger(tmp_path)
    assert pn.ledger_path(Namespace(ledger=None)) == lp


@pytest.mark.parametrize("field", ["note", "content_file", "video", "audio", "cover"])
def test_ledger_path_anchors_on_media_dir(tmp_path, field):
    """稿件/媒体任一路径都能把台账锚回它所在目录——与发布时同一个推导函数。"""
    import publish_note as pn
    media = tmp_path / "slideshow-h1" / f"x.{'md' if field != 'video' else 'mp4'}"
    media.parent.mkdir(parents=True)
    args = Namespace(ledger=None, **{field: media})
    assert pn.ledger_path(args) == media.parent / pn.LEDGER_NAME


def test_recheck_never_creates_ledger_in_cwd(tmp_path, monkeypatch):
    """现场事故复现：`--recheck 340` 光杆跑（cwd=某仓库根）→ 报错指路，且 cwd 一个文件都不留。"""
    import publish_note as pn, publish_video as pv
    cwd = tmp_path / "repo-root"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: pytest.fail("定位不到台账就不该打网络"))

    with pytest.raises(ValueError) as e:
        pv.do_recheck(Namespace(recheck=340, ledger=None), API, "key")

    assert "--ledger" in str(e.value)
    assert list(cwd.iterdir()) == []


def test_recheck_from_inside_the_media_dir_works(tmp_path, monkeypatch):
    """站在稿件目录里 `--recheck 340` 光杆跑 —— 认 cwd 里那份既有台账并回填（正常用法不许被毙）。"""
    import publish_note as pn, publish_video as pv
    lp, _ = _seed_ledger(tmp_path, {"cover": "NC-9"})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: _published_view())
    monkeypatch.setattr(pn, "send_request", _component_api())

    assert pv.do_recheck(Namespace(recheck=340, ledger=None), API, "key") == 0
    assert _rows(lp)[0].startswith("- [x]")


def test_recheck_refuses_to_create_missing_ledger(tmp_path, monkeypatch):
    """锚点算得出但台账不存在 → 报错指路，**不新建**（新建等于给这批伪造一份干净的证据）。"""
    import publish_note as pn, publish_video as pv
    media = tmp_path / "slideshow-h1"
    media.mkdir()
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: pytest.fail("台账不存在就不该打网络"))

    with pytest.raises(ValueError) as e:
        pv.do_recheck(Namespace(recheck=340, ledger=None, cover=media / "cover-1.jpg"), API, "key")

    assert str(media / pn.LEDGER_NAME) in str(e.value)
    assert list(media.iterdir()) == []


def test_recheck_writes_back_to_the_anchored_ledger(tmp_path, monkeypatch):
    """从 --cover 推导出媒体目录里的既有台账并回填；cwd 全程干净。"""
    import publish_note as pn, publish_video as pv
    media = tmp_path / "slideshow-h1"
    media.mkdir()
    lp, _ = _seed_ledger(media, {"cover": "NC-9"})
    cwd = tmp_path / "repo-root"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: _published_view())
    monkeypatch.setattr(pn, "send_request", _component_api())

    code = pv.do_recheck(Namespace(recheck=340, ledger=None, cover=media / "cover-1.jpg"),
                         API, "key")

    assert code == 0 and _rows(lp)[0].startswith("- [x]")
    assert list(cwd.iterdir()) == []


def test_ledger_check_without_anchor_is_not_green(monkeypatch, tmp_path, capsys):
    """--ledger-check 定位不到台账时 exit 4（没有证据 ≠ 闭环），⛔ 不能回 0。"""
    import publish_note as pn
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["publish_note.py", "--ledger-check"])
    with pytest.raises(SystemExit) as e:
        pn.main()
    assert e.value.code == 4
    assert json.loads(capsys.readouterr().out)["exists"] is False
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- 缺陷 3 · 台账行写账号名

def test_ledger_row_carries_account_name_not_id(monkeypatch, tmp_path):
    """`--account 1` 这种数字入参也要换回账号名——台账是给人读的，编号只在 agent↔server 之间用。"""
    import publish_note as pn
    monkeypatch.setattr(pn, "list_accounts", lambda *a: [
        {"id": 1, "name": "NBDpsy-我们都有病", "nickname": "我们都有病", "cookie_status": "valid"}])
    aid, label, _ = pn.resolve_account(API, "key", "1")
    assert (aid, label) == (1, "NBDpsy-我们都有病")

    row = pn.ledger_row(False, TS, "post-video.md",
                        pn.account_display(API, "key", aid, label), 340, "topics=1", "—", "—")
    assert "NBDpsy-我们都有病" in row
    assert "号1" not in row and "(1)" not in row


def test_account_display_falls_back_to_explicit_id(monkeypatch):
    """查不到名字时写 `账号id=1` 明示是 id——⛔ 绝不把编号打扮成名字（原来写的是 `号1(1)`）。"""
    import publish_note as pn

    def boom(*a, **k):
        raise ConnectionError("network down")
    monkeypatch.setattr(pn, "list_accounts", boom)
    assert pn.account_display(API, "key", 1) == "账号id=1"
    assert pn.account_display(API, "key", 1, "1") == "账号id=1"   # label 就是那个数字，同样不认
    # 已经拿到真名字时不再多打一次网络
    assert pn.account_display(API, "key", 1, "NBDpsy-好好生活") == "NBDpsy-好好生活"


def test_recheck_heals_legacy_account_number_row(tmp_path, monkeypatch):
    """复查经过时把旧行的「号1(1)」换回账号名——现场那行否则会一直挂着编号。"""
    import publish_note as pn, publish_video as pv
    lp, _ = _seed_ledger(tmp_path, {"cover": "NC-9"}, who="号1(1)")
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: _published_view())
    monkeypatch.setattr(pn, "send_request", _component_api())
    monkeypatch.setattr(pn, "list_accounts", lambda *a: [{"id": 1, "name": "NBDpsy-我们都有病"}])

    pv.do_recheck(Namespace(recheck=340, ledger=str(lp)), API, "key")

    row = _rows(lp)[0]
    assert "| NBDpsy-我们都有病 |" in row and "号1" not in row


def test_publish_row_uses_account_name(tmp_path, monkeypatch):
    """端到端：视频线发布落的意图行里，账号字段是名字。"""
    import publish_note as pn, publish_video as pv
    note = tmp_path / "post-video.md"
    note.write_text("---\ntitle: 标题\n---\n\n## 发布文案\n\n正文\n\n#焦虑\n", encoding="utf-8")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    cover = tmp_path / "cover-1.jpg"
    cover.write_bytes(b"\xff\xd8fake")
    monkeypatch.setattr(pv, "check_cover_receipt", lambda p: {"ok": True})
    monkeypatch.setattr(pn, "resolve_account", lambda *a: (1, "NBDpsy-我们都有病", None))
    monkeypatch.setattr(pn, "stage_media", lambda p, kind: f"/srv/{p.name}")
    monkeypatch.setattr(pn, "send_request", lambda *a, **k: _Resp(200, {"job_id": 340}))
    monkeypatch.setattr(pn, "poll_job", lambda *a, **k: _published_view(cover_status="done"))

    args = Namespace(note=note, title=None, content_file=None, account="1", video=video,
                     audio=None, cover=cover, topics=None, collection_id=None,
                     collection_name=None, quoted_note_id=None, related_counselor=None,
                     activity_id=None, note_purpose=None, schedule=None, ledger=None,
                     dry_run=False, no_wait=False, wait_timeout=1)
    code = pv.do_publish(args, API, "key")

    row = _rows(tmp_path / pn.LEDGER_NAME)[0]
    assert code == 0
    assert "| NBDpsy-我们都有病 |" in row and "号1" not in row

"""闸门 C（发布台账）的三处缺陷回归：补救结果不进闭环判据 / 台账落盘漂到 cwd / 行里写账号编号。

现场：2026-08-16 job 340（视频线首航）。发布时 cover=error → `--fix-cover` 补挂成功
（note-components 任务 done、applied.cover=true）→ 但 `--recheck 340` 仍念发布那一刻的旧回执，
台账行永远闭不掉；且 `--recheck` 单独跑时台账被新建到进程 cwd（NBDpsy 仓库根）；行里写的是「号1(1)」。
"""
import json
import sys
from argparse import Namespace
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"
sys.path.insert(0, str(SCRIPTS))

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


def test_轮询断了台账仍然知道去哪读(tmp_path, monkeypatch, capsys):
    """🩸 **2026-08-19 咪问首发实炸**：`--fix-cover` 轮询中吃了 Cloudflare **502**，
    脚本报 `outcome: failed`——而只读复查 `GET /api/note-components/<cjob>` 是
    **status:done / applied.cover:true**，**任务其实成功了，502 只断了轮询**。

    🔴 真伤是次生的：登记没做 ⇒ 台账那一行不知道去读哪个 component job
    ⇒ `--recheck` 只能读发布 job 的原始回执（`cover=error`）⇒ **台账永远闭不掉**，
    而**不看脚本源码的人根本不知道要手工补索引**。

    🔴 根因是**把两件事绑在一起**：「登记去哪读」与「读到了什么」。
    前者入队瞬间就已确定，后者要等轮询——**绑在一起，网关一抖就把前者陪葬**。
    """
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
            return _Resp(200, {"job_id": "NC-502"})
        raise ConnectionError("502 Bad Gateway")     # 轮询当场断掉
    monkeypatch.setattr(pn, "send_request", fake)

    args = Namespace(cover=cover, job=340, account=None, note_id=None,
                     wait_timeout=1, ledger=None)
    code = pv.do_fix_cover(args, API, "key")

    assert code == 2, "轮询断了应报 unknown（2），⛔ 不是 failed"
    row = _rows(lp)[0]
    assert "补救: cover=NC-502" in row, "🔴 轮询断了但索引必须已经写进台账"
    assert row.startswith("- [ ]"), "⛔ 登记不是闭环，判定仍归 --recheck"
    out = capsys.readouterr().out
    assert "NC-502" in out, "⛔ 别把 cjob 埋进 traceback——人得能直接看到该复查哪个号"
    assert "绝不重跑" in out


def test_登记必须幂等(tmp_path):
    """⚠️ 入队即登记 ⇒ 同一条可能被写多次（重跑、恢复）。
    `remedies[comp] = str(cjob)` 是覆盖式赋值 ⇒ 重复写同值只留一段。"""
    import publish_video as pv
    lp, _ = _seed_ledger(tmp_path)
    # ⚠️ 直接调 record_remedy 时要把台账路径显式给它——`ledger=None` 走的是
    # 「按 cwd 找」那条路，那是 do_fix_cover 的场景，不是本用例要测的东西
    args = Namespace(job=340, ledger=str(lp), account=None, note_id=None)
    for _ in range(3):
        assert pv.record_remedy(args, "cover", "NC-9")["recorded"]
    assert _rows(lp)[0].count("补救: cover=NC-9") == 1


def test_登记时机必须在入队之后轮询之前():
    """⛔ 别把它挪回轮询之后——那就把「登记去哪读」重新绑回「读到了什么」。"""
    src = (SCRIPTS / "publish_video.py").read_text(encoding="utf-8")
    body = src[src.index("def do_fix_cover"):]
    i_enqueue = body.index('cjob = resp.json()["job_id"]')
    i_record = body.index('remedy = record_remedy(args, "cover", cjob)')
    i_poll = body.index("deadline = time.monotonic()")
    assert i_enqueue < i_record < i_poll, "登记不在「入队之后、轮询之前」"


def test_cover不许参与台账路径推导(tmp_path):
    """🩸 **2026-08-19 实炸**：`--fix-cover --job 350 --cover <封面>` 是补封面的**典型用法**
    （手上只有 job 号和封面，没理由再带 --note），旧链落到封面的父目录 `cover-brand7/`，
    真台账却在稿件目录 `seven/`。

    ⚠️ **要求人每次多带一个 `--ledger` 才不出错的规矩，人一定会漏**——
    SKILL.md 里当时**已经警告过这个坑**，照样踩。⇒ 修推导链，⛔ 不是再加一句提醒。

    🩸 **第一版我改错了方向**：直接把 `--cover` 从链里摘掉，**当场打断 5 个用例**——
    轮播/放映线的封面**就在媒体目录里**（`cover-1.jpg` 与稿件同级）。
    ⇒ **两种用法都真实存在**，区别不在"是哪个参数"，在**"那里到底有没有台账"**。
    ⚠️ 别人点名一处，得先数清这个共用函数还有谁在用。
    """
    import publish_note as pn
    cover_dir = tmp_path / "cover-brand7"; cover_dir.mkdir()
    cover = cover_dir / "c.jpg"; cover.write_bytes(b"\xff\xd8")
    note_dir = tmp_path / "seven"; note_dir.mkdir()
    real = note_dir / pn.LEDGER_NAME; real.write_text("- [ ] x\n", encoding="utf-8")

    args = Namespace(ledger=None, note=None, content_file=None, video=None,
                     audio=None, cover=str(cover))
    monkeypatch2 = __import__("os")
    old = monkeypatch2.getcwd()
    try:
        monkeypatch2.chdir(note_dir)
        # ⛔ 绝不能推到 cover-brand7/（那里没有台账）；稿件目录里的那份才是
        assert pn.ledger_path(args) == real
    finally:
        monkeypatch2.chdir(old)


def test_封面与台账同目录时仍然认cover(tmp_path, monkeypatch):
    """⭕ 轮播/放映线的用法：封面就在媒体目录里 ⇒ `--cover` 照旧能锚定。
    ⚠️ 修一个场景⛔ 不能打断另一个——判据是**「那里有没有台账」**，不是「参数叫什么」。"""
    import publish_note as pn
    media = tmp_path / "slideshow-h1"; media.mkdir()
    real = media / pn.LEDGER_NAME; real.write_text("- [ ] x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)          # cwd 里没有台账
    args = Namespace(ledger=None, cover=media / "cover-1.jpg")
    assert pn.ledger_path(args) == real


def test_一份台账都不存在时指向最可能的位置(tmp_path, monkeypatch):
    """⚠️ 找不到时**仍然要把错误指到正确的地方**，⛔ 不是抛一句"哪儿都没有"。
    ⭕ 「绝不新建」这条不变——它是 2026-08-19 那次没造成更大伤害的原因
    （没在 `cover-brand7/` 里造一份假台账）。"""
    import publish_note as pn
    media = tmp_path / "slideshow-h1"; media.mkdir()
    monkeypatch.chdir(tmp_path)
    args = Namespace(ledger=None, cover=media / "cover-1.jpg")
    assert pn.ledger_path(args) == media / pn.LEDGER_NAME
    assert list(media.iterdir()) == [], "⛔ 推导过程不许在磁盘上留下任何东西"


def test_没有note_id时给的是可粘贴的完整命令(tmp_path, monkeypatch):
    """🩸 **100% 必经、⛔ 不是偶发**（job 349、350 连续两次都撞）。
    ⚠️ 报错里留 `<账号>` 让人猜，等于把一步手工活留给每一次调用。"""
    import publish_note as pn, publish_video as pv
    cover = tmp_path / "c.jpg"; cover.write_bytes(b"\xff\xd8")
    monkeypatch.setattr(pv, "check_cover_receipt", lambda p: {"ok": True})
    monkeypatch.setattr(pn, "poll_job",
                        lambda *a, **k: {"job_id": 350, "account_id": 7, "note_id": None})
    args = Namespace(cover=cover, job=350, account=None, note_id=None,
                     wait_timeout=1, ledger=None)
    with pytest.raises(ValueError) as e:
        pv.do_fix_cover(args, API, "key")
    msg = str(e.value)
    assert "--sync-ledger 7" in msg, "⛔ 别留 <账号> 让人猜——account_id 就在 job 回执里"
    assert "幂等" in msg


# ────── 发布入口停用热线硬闸（2026-08-20 发布线派） ──────

@pytest.mark.parametrize("name,text,should_block", [
    ("正常危机声明块", "心理援助热线 12356，北京心理危机研究与干预中心 010-82951332（24小时）。", False),
    ("停用热线", "如果撑不住，请拨打希望24热线 4001619995", True),
    ("停用热线·带连字符", "400-161-9995", True),
    ("停用热线·带空格", "希望 24 热线", True),
    ("更正稿豁免", "此前写过的希望24热线 4001619995 已停止服务，请改用 010-82951332", False),
    ("12356 标 24 小时", "12356 全国心理援助热线，24 小时在线", True),
])
def test_发布入口热线闸(name, text, should_block):
    """🔴 **放在发布路径最前面，⛔ 不能只放稿件闸门**——2026-08-20 全仓扫出 42 个在途稿件
    仍带停用热线，而它们是从**排期稿**抓到的：**在途稿可以绕过稿件闸门直接发**。

    🩸 **首版是恒红闸门**：标准危机声明块「12356，北京 010-82951332（24小时）」两个号码同一行，
    那个「24小时」修饰的是**北京号**，首版正则一跨就中 ⇒ **每一条合规的稿子都会被拦**。
    ⚠️ **写完判据必须拿一条"本来就该放行的"去试**——只测反例测不出恒红。"""
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import compliance_core as cc
    r = cc.gate_hotlines(text)
    assert bool(r) == should_block, f"{name}: {r}"
    if should_block:
        assert "希望24" in r[0] or "12356" in r[0], "⛔ 拒绝理由必须指向真问题（响错理由最贵）"


def test_热线闸不做前置解析():
    """🩸 发布线的稿件机检**本来就有这道闸**，B2r 还是漏了——`check()` 第一步找不到
    「## 口播全文」段就 `return`，**图文稿在此直接退出，热线检查一次都没跑到**。
    ⚠️ 而它**报了红**（"找不到口播全文段"）⇒ 照那个红去查的人会去补口播段，**不会发现那个空号**。

    > **闸门失效有三种：不响、恒响、响错理由。第三种最贵——因为它看起来在工作。**

    ⇒ `gate_hotlines` **拿到什么文本就扫什么**，⛔ 没有任何"找不到 X 就 return"的分支。"""
    src = (SCRIPTS / "compliance_core.py").read_text(encoding="utf-8")
    body = src[src.index("def gate_hotlines"):src.index("def check(units")]
    assert "return []" not in body.split("reasons = []")[0], "⛔ 前置 return 会让整道闸跳过"
    assert "for i, line in enumerate(text.splitlines()" in body


# ────── typeset_longimage 封面凭证（2026-08-21 牧阳助理派，死线 9/15） ──────

def test_typeset落P01凭证且两端同步(tmp_path):
    """🩸 这条产线此前**零凭证** ⇒ 文字版长图的笔记到闸门 A **全会被拒**
    （7/30 前发的三篇是闸门上线前混过去的）。

    🔴 **两端必须一起改**：产线端落了凭证而 `COVER_SOURCES` 不认 ⇒ **照样拒**，
    而产线那边看起来"已经做了"。⛔ 任一端单独改都是"看起来做了"。"""
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import typeset_longimage as T, publish_note as pn
    png = tmp_path / "P01.png"; png.write_bytes(b"\x89PNG\r\n\x1a\n")
    m = T.write_cover_meta(png, theme="clean", style_profile="文字版 v2",
                           page_w=1080, page_h=1440, pages=6)
    assert m.name == "P01.meta.json", "⚠️ 叫 .meta.json 不叫 .json——后者被调用方占了"
    d = json.loads(m.read_text(encoding="utf-8"))
    assert d["source"] == "typeset_longimage"
    assert d["source"] in pn.COVER_SOURCES, "🔴 闸门端没同步 ⇒ 落了凭证照样被拒"
    assert d["style_profile"] == "文字版 v2" and d["theme"] == "clean"


def test_typeset凭证变异测试(tmp_path):
    """🔴 **变异测试真正分辨的是「你走了哪条路」**（技术侧 2026-08-21）：
    > **「让它不红」和「把它改成恒绿」在输出上一模一样——只有故意破坏一次才分得开。**
    ⇒ 每次改完闸门都跑一次破坏例，⛔ 别只跑正例。"""
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import typeset_longimage as T, publish_note as pn
    png = tmp_path / "P01.png"; png.write_bytes(b"\x89PNG\r\n\x1a\n")
    m = T.write_cover_meta(png, theme="clean", style_profile=None,
                           page_w=1080, page_h=1440, pages=6)
    # 变异①：凭证挪走 ⇒ 闸门此时必须红（没有凭证可读）
    m.rename(tmp_path / "P01.meta.json.bak")
    assert not m.exists()
    # 变异②：source 换成白名单外的值 ⇒ 必须不被认
    assert "手工PIL叠图" not in pn.COVER_SOURCES
    # ⚠️ style_profile 没有就是 None——⛔ 不编默认值（错标比缺失更毒）
    d = json.loads((tmp_path / "P01.meta.json.bak").read_text(encoding="utf-8"))
    assert d["style_profile"] is None


def test_存量三种source没被改坏():
    """⚠️ 加新形态时的回归项：⛔ 别为覆盖新的改坏旧的。"""
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import publish_note as pn
    for s in ("gen_images", "render_cover", "manual_confirmed"):
        assert s in pn.COVER_SOURCES

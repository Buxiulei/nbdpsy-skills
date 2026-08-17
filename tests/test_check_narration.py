"""口播闸门的证伪测试 —— 每条规则都要有「违规样本必须报」+「合法样本必须不报」两半。

⛔ 只测「违规样本报出来」是不够的：那样测不出「见字就叫」的闸门。恒红的闸门等于没有闸门
（人会开始绕过去），所以放行样本这一半才是这份测试的重点。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"
SCRIPT = SCRIPTS / "check_narration.py"
sys.path.insert(0, str(SCRIPTS))

import check_narration as cn  # noqa: E402


def rules(text: str) -> set[str]:
    return {f["rule"] for f in cn.soft_findings(text)}


# ---------- 硬闸门：字数（narration-spec §九） ----------

def test_hanzi_count_ignores_punctuation_and_latin():
    """数汉字不是 len(str)：标点/英文/数字不计入。"""
    assert cn.hanzi_count("一" * 99 + "，。！？ABCdef123（）「」——") == 99


def test_hard_gate_rejects_over_limit():
    res = cn.check([("第1镜", "一" * 101)])
    assert res["ok"] is False
    assert res["over"][0]["hanzi"] == 101 and res["over"][0]["over"] == 1


def test_hard_gate_passes_at_boundary():
    """100 字整是**放行**边界，不是拒收边界。"""
    assert cn.check([("第1镜", "一" * 100)])["ok"] is True


def test_hard_gate_reports_which_shot():
    res = cn.check([("第1镜", "短句。"), ("第2镜", "一" * 130)])
    assert [o["label"] for o in res["over"]] == ["第2镜"]
    assert res["over"][0]["over"] == 30


# ---------- 软提醒·第三律：书面连接词 ----------

def test_written_connectives_flagged():
    assert "书面连接词" in rules("他不但没睡好，而且一整天都在复盘。")
    assert "书面连接词" in rules("综上，这几种反应都指向同一件事。")


def test_spoken_connectives_not_flagged():
    """⭕ 口语衔接词是规范推荐的写法，⛔ 绝不能被报成违规。"""
    assert rules("所以说，你发现没，说白了就是他一直在警戒。") == set()


# ---------- 软提醒·第三律：「该」只拦代词用法 ----------

def test_gai_as_pronoun_flagged():
    assert "书面连接词" in rules("该机构在一九八九年发过一份急诊报告。")   # 句首
    assert "书面连接词" in rules("我们看那个数据，该研究只跟了一个月。")   # 句中


def test_gai_as_verb_not_flagged():
    """「该」作动词/助动词是正常口语，见字就叫会把这些全报成违规。"""
    for legal in ("夜里两点了，你该睡了。",
                  "他觉得自己不该这么想。",
                  "那接下来该怎么办呢。",
                  "你应该先去医院排除心和肺的问题。",
                  "他不觉得自己活该受这些。",
                  "该走了，别再等他回消息。"):
        assert rules(legal) == set(), legal


# ---------- 软提醒·第五律：破折号 ----------

def test_dash_flagged_and_comma_not():
    assert "破折号" in rules("这五种情况都别在原地扛——")
    assert rules("这五种情况，别在原地扛。") == set()


# ---------- 软提醒·第八律：完整引语（单字引号是文档化的例外） ----------

def test_full_quote_flagged():
    assert "完整引语" in rules("医生说「这是焦虑」，那是排除之后的结论。")


def test_single_char_quote_not_flagged():
    """narration-spec §三 实测：单字引号不触发 TTS 角色扮演 ⇒ 不算违规。"""
    assert rules("他只回了一个「不」字。") == set()


def test_paraphrase_not_flagged():
    assert rules("说是焦虑，那是医生排除掉心和肺之后才能下的结论。") == set()


# ---------- 三态：「没读到」不许冒充「没超标」 ----------

def test_all_empty_is_observation_failure_not_a_pass():
    """🩸 字段名一改、shots.json 结构一漂，每镜都读成空串 ⇒ 全算 0 汉字 ⇒ 全部放行，
    闸门恒绿且一声不吭。实测过：两镜各 300 字、字段名写成 `narration`，旧版判 ok=True。
    ⛔ 「没找到」必须与「没超标」可区分。"""
    res = cn.check([("第1镜", ""), ("第2镜", "")])
    assert res["ok"] is False and res["blind"] is True


def test_all_empty_passes_when_explicitly_allowed():
    """真是一条无口播的片子，得有一扇明写的门——⛔ 否则闸门会被整个绕过去。"""
    res = cn.check([("第1镜", ""), ("第2镜", "")], allow_empty=True)
    assert res["ok"] is True and res["blind"] is False


def test_non_chinese_narration_is_read_not_blind():
    """🩸 判「有没有读到」看**原串是否为空**，⛔ 不看汉字数是否为 0。
    「n1」「hello」这类非汉字文案是**读到了、只是 0 汉字**，合法通过。
    第一版拿汉字数当判据，把它们全误报成观测失败——既有的 test_build_manifest 当场抓到。"""
    for legal in ("n1", "hello world", "TODO"):
        res = cn.check([("第1镜", legal)])
        assert res["blind"] is False and res["ok"] is True, legal


def test_whitespace_only_counts_as_not_read():
    assert cn.check([("第1镜", "   \n  ")])["blind"] is True


def test_single_empty_shot_is_legal():
    """单镜空是合法的（无旁白镜靠 subtitle 兜底），⛔ 别做成见零就叫。"""
    res = cn.check([("第1镜", ""), ("第2镜", "所以说，先把结论放在前面。")])
    assert res["ok"] is True and res["blind"] is False


def test_empty_shot_list_is_not_blind():
    assert cn.check([])["blind"] is False


def test_cli_exit_1_on_wrong_field_name(tmp_path):
    """端到端：字段名写错时 CLI 必须非零退出，⛔ 不许静默放行 300 字的稿子。"""
    p = tmp_path / "shots.json"
    p.write_text(json.dumps({"shots": [{"index": 1, "narration": "一" * 300}]},
                            ensure_ascii=False), encoding="utf-8")
    r = _run(["--shots", str(p)])
    assert r.returncode == 1
    assert json.loads(r.stdout)["blind"] is True
    assert _run(["--shots", str(p), "--allow-empty"]).returncode == 0


# ---------- 软提醒绝不能变成硬闸门 ----------

def test_soft_findings_never_fail_the_gate():
    """踩满四条软规则、但字数合规 ⇒ 必须 ok=True。⛔ 软的一旦变硬就成了恒红闸门。"""
    dirty = "该机构说「这是焦虑」——不但如此，其中还有别的，因此要小心。"
    res = cn.check([("第1镜", dirty)])
    assert res["ok"] is True
    assert len(res["warnings"]) >= 4


# ---------- CLI 契约：退出码 ----------

def _run(args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_cli_exit_0_on_pass():
    r = _run(["--text", "所以说，先把结论放在前面：深呼吸，是在帮倒忙。"])
    assert r.returncode == 0
    assert json.loads(r.stdout)["ok"] is True


def test_cli_exit_1_on_over_limit():
    r = _run(["--text", "一" * 101])
    assert r.returncode == 1
    assert json.loads(r.stdout)["over"][0]["over"] == 1


def test_cli_exit_2_on_missing_file():
    r = _run(["--shots", "/nonexistent/shots.json"])
    assert r.returncode == 2


def test_cli_reads_shots_and_beats(tmp_path):
    """v1 的 shots 与 v3 的 beats 同构，两种都要认（与 build_manifest 同一套读法）。"""
    for key in ("shots", "beats"):
        p = tmp_path / f"{key}.json"
        p.write_text(json.dumps({key: [{"index": 1, "narration_text": "一" * 101}]},
                                ensure_ascii=False), encoding="utf-8")
        r = _run(["--shots", str(p)])
        assert r.returncode == 1, key
        assert json.loads(r.stdout)["over"][0]["label"] == "第1镜"


# ────────── 结构自证（§八 骨架三段；写完稿回头粘原句） ──────────
# 🩸 它治的病：判断类规范不阻塞任何一步，所以不被读（2026-08-17 实证：某线写三稿，
# 上墙十条一次没读，却把「12 字」实现成了量字脚本——因为 12 字是个可执行的数）。
# ⇒ 让答案变成**可字符串比对的原句**，判断类规范才获得同样的质地。

_ITEMS = [("P01", "对自己好一点，压根不是放过自己。"),
          ("P02", "有人把它理解成少干活多休息，结果越歇越空。"),
          ("P03", "我认识一个人，她每天下班先躺四十分钟，躺完更累。"),
          ("P04", "后来她改成下班先走二十分钟，反而睡得着了。"),
          ("P05", "研究里那组人练了一个月才有变化，当场是没感觉的。"),
          ("P06", "它是一个月的功课，不是当场的开关。")]
_OK = {"hook": "对自己好一点，压根不是放过自己。",
       "scene": "她每天下班先躺四十分钟，躺完更累。",
       "closing": "它是一个月的功课，不是当场的开关。"}


def test_自证三句都在稿里且位置对():
    r = cn.check_intent(_ITEMS, _OK)
    assert r["ok"] and not r["fail"]
    assert r["hook"]["at"] == "P01" and r["closing"]["at"] == "P06"


def test_自证句子压根不在稿里_报不在():
    r = cn.check_intent(_ITEMS, {**_OK, "hook": "这句我编的根本没写过。"})
    assert not r["ok"] and "不在稿里" in r["fail"][0]
    assert r["hook"]["near"] is None, "真编造的句子⛔ 不该有 near"


def test_自证粘歪了标点_与压根没写必须分开报():
    """⚠️ 两者都报「不在稿里」的话，写手会以为漏写而**转头去补一句**——那就写重了。"""
    r = cn.check_intent(_ITEMS, {**_OK, "hook": "对自己好一点,压根不是放过自己。"})
    assert not r["ok"]
    assert r["hook"]["near"] == "P01" and "字面对不上" in r["fail"][0]


def test_自证位置错要报出来():
    hook_late = cn.check_intent(_ITEMS, {**_OK, "hook": _ITEMS[4][1]})
    assert not hook_late["ok"] and "不在前 2 项内" in hook_late["fail"][0]
    close_early = cn.check_intent(_ITEMS, {**_OK, "closing": _ITEMS[1][1]})
    assert not close_early["ok"] and "不在后 3 项内" in close_early["fail"][0]


def test_自证漏声明一项也是不过():
    r = cn.check_intent(_ITEMS, {k: v for k, v in _OK.items() if k != "scene"})
    assert not r["ok"] and "scene：未声明" in r["fail"]
    assert r["scene"] == {"declared": False}


def test_项数不足5时不判位置_否则是恒真恒假的假闸门():
    """前 2 与后 3 在短稿里重叠，判了等于没判——本仓「恒报红的闸门等于没报」同族。"""
    short = _ITEMS[:3]
    r = cn.check_intent(short, {"hook": short[0][1], "scene": short[1][1],
                                "closing": short[0][1]})
    assert r["judge_position"] is False and r["ok"], "短稿只验存在性"
    assert "position_ok" not in r["closing"], "⛔ 没判就别留这个键，留了会被读成判过了"


def _run_intent(tmp_path, intent=None):
    """⚠️ 名字必须避开本文件上面已有的 `_run(args)`——在文件末尾追加时同名函数会**静默覆盖**
    前面的定义，让前面的用例改用后来的实现。这次撞上了（5 个老用例报 TypeError），
    但那是**运气**：签名若恰好兼容，它们会静默地用错实现跑、照样报绿。
    ⇒ 往测试文件尾部追加辅助函数前，先 grep 一遍同名。"""
    md = tmp_path / "n.md"
    md.write_text("".join(f"## {lb}\n{tx}\n\n" for lb, tx in _ITEMS), encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), "--script-file", str(md)]
    if intent is not None:
        f = tmp_path / "i.json"
        f.write_text(json.dumps(intent, ensure_ascii=False), encoding="utf-8")
        cmd += ["--intent-file", str(f)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout), p.stderr


def test_端到端_自证不过要真的拦停(tmp_path):
    code, out, err = _run_intent(tmp_path, {**_OK, "hook": "这句我编的根本没写过。"})
    assert code == 1, "声明了就得对得上，自证不过与超字数同级"
    assert out["intent"]["ok"] is False and out["ok"] is False


def test_端到端_没传自证时JSON里不能有intent键(tmp_path):
    """🔴「没做」与「做了没问题」必须分得开：给 False 会被读成判过了没问题。"""
    code, out, err = _run_intent(tmp_path)
    assert code == 0 and "intent" not in out
    assert "未做结构自证" in err and "不是「查过了没问题」" in err


# ────────── 连续稿模式（oneline 字卡线：不分页的一整篇） ──────────
# 🩸 2026-08-17 实测缺口：oneline 的稿子**两种模式都跑不了**——--script-file 要 `## P1`
# 页标题（连续稿没有）、--text 把整篇当一镜必爆 100 字上限。根因是形态不匹配：
# 分页形态一页一镜，oneline 是一整篇，分屏由 build_oneline.py 事后按 cues 自动断。

_CONT = ("对自己好一点，压根不是放过自己。有人把它理解成少干活多休息，结果越歇越空。"
         "我认识一个人，她每天下班先躺四十分钟，躺完更累。后来她改成下班先走二十分钟，"
         "反而睡得着了。研究里那组人练了一个月才有变化，当场是没感觉的。"
         "它是一个月的功课，不是当场的开关。")


def test_连续稿按句末标点切句(tmp_path):
    f = tmp_path / "c.md"
    f.write_text("# 标题行不算口播\n\n" + _CONT, encoding="utf-8")
    items = cn.from_continuous(f)
    assert len(items) == 6 and items[0][0] == "第1句"
    assert items[0][1] == "对自己好一点，压根不是放过自己。"
    assert not any("标题行不算口播" in t for _, t in items), "# 开头的行是标题，⛔ 不是口播"


def test_连续稿显式关掉字数闸_而不是把阈值调大():
    """⛔ 调大阈值＝闸还在但恒绿；limit=None 才读得出「这一项没判」。"""
    res = cn.check([("第1句", "字" * 300)], limit=None)
    assert res["ok"] is True and res["limit"] is None
    assert res["over"] == [] and res["shots"][0]["over"] == 0


def test_连续稿切句失败要报错_不许伪装成一篇短稿(tmp_path):
    """🔴 全篇缺中文句末标点时会切成 1 句，此时三句自证都能在那唯一一句里「找到」、
    且项数 <5 连位置都不判 ⇒ **全过**。这是恒绿，必须在入口就拦。"""
    for body in ("整篇没有任何中文句末标点的一段话",
                 "半角句点也不认.第二句同样如此.第三句还是."):
        f = tmp_path / "bad.md"
        f.write_text(body, encoding="utf-8")
        with pytest.raises(RuntimeError, match="多半是断句失败"):
            cn.from_continuous(f)


def test_端到端_连续稿位置判据真的会报红(tmp_path):
    f = tmp_path / "c.md"
    f.write_text(_CONT, encoding="utf-8")
    i = tmp_path / "i.json"
    i.write_text(json.dumps({"hook": "对自己好一点，压根不是放过自己。",
                             "scene": "她每天下班先躺四十分钟，躺完更累。",
                             "closing": "有人把它理解成少干活多休息，结果越歇越空。"},
                            ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPT), "--continuous-file", str(f),
                        "--intent-file", str(i)], capture_output=True, text=True)
    assert p.returncode == 1, "closing 落在第 2 句，位置判据必须报红"
    assert "不在后 3 项内" in p.stderr
    assert "本模式**不判字数**" in p.stderr, "⛔ 必须明写字数闸没跑"


def test_自证值跨了多句_要与压根没写分开报():
    """🔴 第三种失败：值跨了 ≥2 句。此前它和「稿里真没有」共用一句报错，实测需求方的
    第一反应是「脚本坏了」——**而那个反应会让人去改脚本或绕过闸门**。
    跨句在任何模式下都必然找不到（比对按单条做），所以这条提示不分模式。"""
    r = cn.check_intent(_ITEMS, {**_OK, "closing": "研究里那组人练了一个月才有变化，"
                                                   "当场是没感觉的。它是一个月的功课，"
                                                   "不是当场的开关。"})
    assert not r["ok"] and "含 2 个句子" in r["fail"][0] and "只粘其中一句" in r["fail"][0]
    assert r["closing"]["sentences"] == 2


def test_单句末尾带句号不算跨句():
    """⛔ 见标点就叫会把每一条正常声明都报成跨句——末尾那个句末标点不算。"""
    assert cn._sentence_span("它是一个月的功课，不是当场的开关。") == 1
    assert cn._sentence_span("它是一个月的功课，不是当场的开关") == 1
    assert cn._sentence_span("真的吗？我不信。") == 2

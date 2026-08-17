"""口播闸门的证伪测试 —— 每条规则都要有「违规样本必须报」+「合法样本必须不报」两半。

⛔ 只测「违规样本报出来」是不够的：那样测不出「见字就叫」的闸门。恒红的闸门等于没有闸门
（人会开始绕过去），所以放行样本这一半才是这份测试的重点。
"""
import json
import subprocess
import sys
from pathlib import Path

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

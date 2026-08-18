"""视觉计划闸门 —— 六道。

🔴 这套测试的重点是**第四道（相关性）**：它是整个设计的地基。
老板原话「动画与内容并无关联……不能只是简单的套用模板」。
⇒ 判据：**把某屏的 why 挪到别的屏若还成立，它就不算相关。**
⛔ 二元判据，不评分——分数会诱人调阈值。
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_plan as cp  # noqa: E402

CUES = [{"text": "感觉好了不代表能停药", "start": 0, "end": 4.0},
        {"text": "它有八个阶段眼动只出现在中间那一步", "start": 4.0, "end": 9.0}]


def _scr(**over):
    d = {"i": 0, "text": "感觉好了不代表能停药", "start": 0, "end": 4.0,
         "semantic": "反驳", "motif": "wipe", "emphasis": "不代表",
         "relation": "开场",
         "why": "「不代表」是把前半句划掉再写新的，wipe 的擦出正好演这个动作"}
    d.update(over)
    return d


def test_合格计划全过():
    r = cp.check({"screens": [_scr()]}, CUES)
    assert r["ok"] and not r["fails"], r["fails"]
    assert r["rows"][0]["cite"] == "不代表"


def test_why没引用本屏文本必须拒(  ):
    """🔴 地基那条：这句话放到任何一屏都成立 ⇒ 不算相关。"""
    r = cp.check({"screens": [_scr(why="本屏气氛转折，所以用漂移")]}, CUES)
    assert not r["ok"] and "没有引用本屏文本" in r["fails"][0]


def test_引用不必带引号():
    """⛔ 别只认引号：LLM 未必总加引号，那样会把合格计划判死。"""
    r = cp.check({"screens": [_scr(why="不代表三个字是在划掉前半句，用 wipe 演它")]}, CUES)
    assert r["ok"], r["fails"]


def test_跨屏主干雷同只报warn():
    """⚠️ 短片里少量重复可能合理 ⇒ warn 不拦；但必须报出来（那是套模板的残留）。"""
    a = _scr(i=0)
    b = _scr(i=1, text="它有八个阶段眼动只出现在中间那一步", start=4.0, end=9.0,
             emphasis="八个阶段", semantic="列举",
             why="「八个阶段」是把前半句划掉再写新的，wipe 的擦出正好演这个动作")
    r = cp.check({"screens": [a, b]}, CUES)
    assert r["ok"], r["fails"]
    assert r["warns"] and "主干与 #00 完全相同" in r["warns"][0]


def test_闭集与强调词():
    assert "不在闭集内" in cp.check({"screens": [_scr(motif="fancy")]}, CUES)["fails"][0]
    assert "不在闭集内" in cp.check({"screens": [_scr(semantic="随便")]}, CUES)["fails"][0]
    bad = cp.check({"screens": [_scr(emphasis="根本没这词")]}, CUES)["fails"][0]
    assert "不是屏文本的子串" in bad


def test_屏文本不许改动稿子():
    r = cp.check({"screens": [_scr(text="感觉好了就能停药")]}, CUES)
    assert not r["ok"] and "在 cues 里找不到" in r["fails"][0]


def test_停留下限不够时要指出是语速问题():
    """⚠️ 停留时长 ⛔ 不由排版层决定——合并到「一句一屏」仍不够就是语速问题。
    报错必须说出这一层，否则人会在排版层徒劳地改。"""
    r = cp.check({"screens": [_scr(end=2.9)]}, CUES)
    assert not r["ok"]
    f = [x for x in r["fails"] if "停留" in x][0]
    assert "语速问题不是排版问题" in f and "重跑 TTS" in f


def test_空计划不许当通过():
    r = cp.check({"screens": []}, CUES)
    assert not r["ok"] and "不是「没有屏」" in r["fails"][0]


def test_端到端退出码(tmp_path):
    p, c = tmp_path / "p.json", tmp_path / "c.json"
    c.write_text(json.dumps(CUES, ensure_ascii=False), encoding="utf-8")
    p.write_text(json.dumps({"screens": [_scr()]}, ensure_ascii=False), encoding="utf-8")
    run = lambda: subprocess.run([sys.executable, str(SCRIPTS / "check_plan.py"),
                                  "--plan", str(p), "--cues", str(c)],
                                 capture_output=True, text=True)
    assert run().returncode == 0
    p.write_text(json.dumps({"screens": [_scr(why="气氛转折所以漂移")]}, ensure_ascii=False),
                 encoding="utf-8")
    assert run().returncode == 1


# ────────── 解耦模式（collage）：卡片文字 ≠ 口播文字 ──────────
# 🩸 解耦解决了「电报体」，却引入新风险（审稿代理 2026-08-18）：
# **卡片与当时念的话对不上，比装饰性无关更糟**——观众会以为自己听漏了。

def _dec(**over):
    d = {"i": 0, "card": "不代表能停药", "covers": [0, 4.0], "start": 0, "end": 4.0,
         "semantic": "反驳", "motif": "wipe", "emphasis": "不代表", "relation": "开场",
         "why": "「不代表」是把前半句划掉重写，wipe 演这个动作"}
    d.update(over)
    return d


def test_解耦模式相关性对着口播原文判():
    """🔴 ⛔ 不是对着卡片自己的字判——卡片是从口播提炼的，拿它自比等于自证。"""
    r = cp.check({"screens": [_dec()]}, CUES)
    assert r["ok"], r["fails"]
    assert r["rows"][0]["text"] == "感觉好了不代表能停药", "text 应是覆盖时段的口播原文"


def test_卡片切换点必须落在语义边界():
    """⛔ 别在一句话中间切——观众会以为话题变了，而口播还在同一句里。"""
    r = cp.check({"screens": [_dec(covers=[1.7, 4.0], start=1.7)]}, CUES)
    assert not r["ok"] and "不在语义边界" in r["fails"][0]


def test_卡片不许贴在没有口播的时段上():
    r = cp.check({"screens": [_dec(covers=[20.0, 24.0], start=20.0, end=24.0)]}, CUES)
    assert any("没有口播" in f for f in r["fails"]), "卡片贴在空白上却没报"


def test_审稿材料必须并排列出卡片与口播():
    """🔴 这是审稿必交材料：人一眼就能判「这张卡是不是这段话的关键词」。"""
    md = cp.to_md(cp.check({"screens": [_dec()]}, CUES))
    assert "卡片：「不代表能停药」" in md
    assert "口播：「感觉好了不代表能停药」" in md and "这段时间真正念的话" in md

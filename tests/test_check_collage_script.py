"""collage 稿件闸门。规格：≤11 句／30–40s／每屏 ≥3.5s（印章句 ≥4.5s）／印章句首段单看无害。

🩸 规格此前的状态**比"没有"更麻烦**：数写在 SKILL 里，却标着「观察值不是指标」
——**看起来有规格，实际没有约束力**。现在句数上限由停留下限反推（40 ÷ 3.5）。
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_collage_script as cc  # noqa: E402


def test_印章句含逗号必须报_哪怕不含转折词():
    """🔴 **这条是被实证证伪出来的判据**：首版写的是「含转折/否定词才报」，
    而真实事故案例——X2 印章屏首段「所以你要等他，」单显 1.36s——
    **一个转折词都不含**，词表判据当场漏掉了它要抓的那个案例。
    ⇒ 判据改成「含逗号就会被分段 ⇒ 一律让人确认首段单看无害」。"""
    lines = ["随便一句话说得足够长可以撑过三秒半吧", "所以你要等他，等他自己说出口再决定"]
    r = cc.check(lines, focus=1)
    assert r["warns"], "印章句含逗号却没报——正是实证漏掉的那一格"
    w = r["warns"][0]
    assert "所以你要等他" in w and "首段单看" in w
    assert "转折" not in w.split("首段")[0], "这句不含转折词，⛔ 别说它含"


def test_含转折词的印章句要加重提示():
    lines = ["随便一句话说得足够长可以撑过三秒半吧", "他说会改，但一次也没有做到过"]
    w = cc.check(lines, focus=1)["warns"][0]
    assert "风险更高" in w


def test_印章句无逗号不报():
    """⚠️ 断言只看**印章句那一类** warn——⛔ 别用 `not warns`：
    两句稿子必然还有「总时长不足 30s」那条，那是另一回事（首版测试就栽在这）。"""
    lines = ["随便一句话说得足够长可以撑过三秒半吧", "这四个答案都写在你的处方单子上面"]
    ws = [w for w in cc.check(lines, focus=1)["warns"] if "印章句" in w]
    assert not ws


def test_停留下限_印章句更严():
    short = ["短句子不够长的", "另一句也不够长啊"]
    r = cc.check(short, focus=1)
    assert not r["ok"]
    focus_fail = [f for f in r["fails"] if "印章句" in f]
    assert focus_fail and "4.5s" in focus_fail[0]


def test_停留不够的处置是铺多屏_不是改稿():
    """🔴 处置随「口播/卡片解耦」变了：以前写"把这句说长"，现在是**"这句铺成多屏"**
    ——卡片只显关键词，一句本来就能铺多屏。⛔ 别再让人改稿子迁就排版。"""
    f = cc.check(["短句", "也短"], focus=0)["fails"][0]
    assert "铺成多屏" in f and "别改稿子迁就排版" in f


def test_写稿阶段不设句数与时长上限():
    """🔴 老板 2026-08-18（继 G9 后第二次强调）：
    **「不能因为字数限制而缩减文字，导致完全看不懂在说啥！口播稿长就长一些！」**
    ⇒ 半小时前拍的「≤11 句／30–40s」作废——它们本来就是写稿阶段的数字上限。
    ⛔ 本脚本只查渲染层能不能承受。"""
    lines = ["这是一句足够长的话可以撑过三秒半的"] * 30      # 30 句、远超 40s
    r = cc.check(lines, None)
    assert r["ok"], f"不该因为句多/太长而拒：{r['fails']}"
    assert not any("上限" in x or "总时长" in x for x in r["fails"] + r["warns"])


def test_空稿不许当通过():
    r = cc.check([], None)
    assert not r["ok"] and "不是「空稿」" in r["fails"][0]


def test_索引越界要报():
    assert any("越界" in f for f in cc.check(["够长的一句话撑过三秒半吧"], focus=9)["fails"])

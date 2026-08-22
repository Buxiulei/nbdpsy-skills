"""判-6 危机声明闸门：声明在不在 + 豁免有没有可核的证据。

⛔ 这个闸门**不判**"这条片该不该有声明"（那是语义，判据在 checklist-video.md 判-6a/6b）。
它只做两件确定性的事：声明在不在、人引的那句处置权句是不是真在正文里。
⇒ **语义判断留给人，「人说的话是否属实」变成确定性检查。**

文件里每条测试都对着一个 2026-08-22 定判-6 那天**实撞的坑**，⛔ 不是想象出来的用例。
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "nbdpsy-content-reviewer" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_video_crisis as cvc  # noqa: E402

DECL = "如果你正被持续的情绪困扰缠着，一个人扛不住，请寻求专业帮助，全国统一心理援助热线，12356。"
DECL_CN = "也可以打这个热线。全国统一心理援助热线。号码是一二三五六。"
TRIGGER_BODY = "很多人不知道，抑郁症的诊断是医生按标准下的。"


def wd(tmp_path, name="narration.txt", body=""):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


# ────────── 坑 1：中文数字写法 ──────────

def test_阿拉伯数字写法认得出(tmp_path):
    assert cvc.check(wd(tmp_path, body=TRIGGER_BODY + DECL))["verdict"] == "ok"


def test_中文数字写法也认得出(tmp_path):
    """🩸 `oneline-qiuqiu-chiyao` / `jianyao` 两条**涉药片**被 `grep "12356"` 判成"没有声明"，
    实际声明完整存在——口播稿写的是「号码是**一二三五六**」（TTS 要念出来）。
    ⚠️ 照那个假缺失去补，会给一条合规片补出**重复声明**。"""
    r = cvc.check(wd(tmp_path, body=TRIGGER_BODY + DECL_CN))
    assert r["verdict"] == "ok" and r["declaration_found"] is True


# ────────── 坑 2：⛔ 不许 rglob 全目录 ──────────

def test_脚本源码里的常量不算这条片有声明(tmp_path):
    """🩸 `grep -rl "12356" brand-haohaoshenghuo/` 命中的是 **`render_card.py`**——
    工作目录里拷的**脚本源码常量**，⛔ 不是那条片的内容。
    一次全目录 grep 把 **12 条**片子误判成"有声明"。"""
    (tmp_path / "render_card.py").write_text(
        'CRISIS = "全国统一心理援助热线 12356"\n', encoding="utf-8")
    r = cvc.check(wd(tmp_path, body=TRIGGER_BODY))
    assert r["declaration_found"] is False, "⛔ 脚本源码不是口播稿"
    assert r["verdict"] == "needs_exemption"


def test_笔记正文里的声明不算视频有声明(tmp_path):
    """🩸 `slideshow-h1` 的命中在 `post-video.md`（**笔记正文**），视频口播里并没有。"""
    (tmp_path / "post-video.md").write_text(DECL, encoding="utf-8")
    assert cvc.check(wd(tmp_path, body=TRIGGER_BODY))["declaration_found"] is False


# ────────── 坑 3：量不出来 ≠ 没有 ──────────

def test_找不到口播稿是量不出不是没声明(tmp_path):
    """🔴 `benchmark-*`（对标样本，别人的片）属于这一类；放映线的声明可能**烧在图上**，
    文本量具本来就够不着。**报「没有」会让人去给一条其实合规的片子补声明。**"""
    (tmp_path / "readme.md").write_text("对标样本", encoding="utf-8")
    r = cvc.check(tmp_path)
    assert r["verdict"] == "unmeasurable"
    assert r["declaration_found"] is None, "⛔ 不许写 False——那是「没有」，这是「不知道」"
    assert r["ok"] is None


def test_量不出来退2不退1():
    """exit 1 = 没声明（要处理）；exit 2 = 量不出（别照它去补）。⛔ 两者不许合并。"""
    import subprocess
    r = subprocess.run(["python3", str(SCRIPTS / "check_video_crisis.py"),
                        "--workdir", "/nonexistent-dir-xyz"], capture_output=True, text=True)
    assert r.returncode == 2


# ────────── 触发词：高召回，⛔ 不做终判 ──────────

def test_命中触发词无声明且无依据是红(tmp_path):
    r = cvc.check(wd(tmp_path, body=TRIGGER_BODY))
    assert r["verdict"] == "needs_exemption" and r["ok"] is False


def test_没命中触发词不判红(tmp_path):
    """⚠️ 但要留话：词表是高召回**不是全覆盖**，人仍要按 6-b 判一遍。"""
    r = cvc.check(wd(tmp_path, body="你手里的异性样本太少，一个人代表了一整类。"))
    assert r["verdict"] == "no_trigger" and r["ok"] is True
    assert "仍要按 6-b 人工判" in r["reason"]


def test_伤害自己才算自伤而伤害不算(tmp_path):
    """🔴 **词边界是必要条件，⛔ 不是充分条件**：把「伤害」放进自伤词表，
    会命中 `xigao-collage-01/script-2` 讲依恋机制的正常句子。"""
    body = "亲近曾经和伤害绑在一起，于是他用更用力的动作压下去。"
    assert cvc.find_triggers(body) == []
    assert "自伤自杀:伤害自己" in cvc.find_triggers("如果现在有伤害自己的念头。")


def test_品牌片提及诊断名词也会命中这是已知误报(tmp_path):
    """⚠️ 实测：「创伤后应激」在 **7 条 brand 品牌片**里全部命中——「聊创伤」这类账号
    **自我介绍**时会说自己聊什么。**提及 ≠ 让观众对号入座**，而这个区分脚本判不了。
    ⇒ 所以命中只产生 `needs_exemption`（要人给依据），**⛔ 绝不能直接判 FAIL**。"""
    r = cvc.check(wd(tmp_path, body="我们这个号聊创伤后应激，也聊日常里的小事。"))
    assert r["verdict"] == "needs_exemption", "要人看一眼"
    assert "不等于" in r["reason"], "红灯里必须写明这不是必然违规，否则会被当成误杀而习惯性无视"


# ────────── 豁免：人说的话是否属实，变成确定性检查 ──────────

QUOTE = "先问自己一句：这件事我自己扛了多久了"


def test_豁免句真在正文里就放行(tmp_path):
    r = cvc.check(wd(tmp_path, body="我们聊创伤后应激。" + QUOTE), exempt_quote=QUOTE)
    assert r["verdict"] == "exempt" and r["ok"] is True and r["exempt_quote_found"] is True


def test_豁免句不在正文里就拒(tmp_path):
    """🔴 **引一句片子里没有的话，豁免不成立**——否则豁免就是一句自我声明，
    等于这条闸门在这次审查里没存在过。"""
    r = cvc.check(wd(tmp_path, body="我们聊创伤后应激。"), exempt_quote=QUOTE)
    assert r["verdict"] == "exempt_quote_missing" and r["ok"] is False


def test_正文删掉该句后豁免立刻失效(tmp_path):
    """收口人点名的第三个变异：豁免片删掉处置权句 → 红。"""
    r = cvc.check(wd(tmp_path, body="我们聊创伤后应激。先想想吧"), exempt_quote=QUOTE)
    assert r["ok"] is False


@pytest.mark.parametrize("quote", [
    "先问自己一句,这件事我自己扛了多久了。",     # 半角逗号 + 多个句号
    "先问自己一句： 这件事我自己扛了多久了",       # 多一个空格
    "先问自己一句这件事我自己扛了多久了",          # 标点全去掉
])
def test_标点与空白差异不影响比对(tmp_path, quote):
    """🩸 变异测试当场抓到：首版字符类里只有全角「，」，人抄那句话时输入法出了个
    **半角逗号**就判不匹配——而红灯写的是「你引的句子不在正文里」，
    照它去查会以为**引错了句子**，实际只差一个标点的宽窄。⚠️ 又一次「响错理由」。"""
    r = cvc.check(wd(tmp_path, body="我们聊创伤后应激。" + QUOTE), exempt_quote=quote)
    assert r["verdict"] == "exempt", f"标点差异不该让豁免失效：{quote}"


def test_有声明时不需要豁免句(tmp_path):
    r = cvc.check(wd(tmp_path, body=TRIGGER_BODY + DECL), exempt_quote="随便什么")
    assert r["verdict"] == "ok"


# ────────── 24 小时红线 ──────────

def test_12356标24小时是红(tmp_path):
    r = cvc.check(wd(tmp_path, body="全国统一心理援助热线 12356，24 小时都在。"))
    assert r["verdict"] == "h24_violation" and r["ok"] is False


def test_标准声明里的24小时归010不误伤(tmp_path):
    """⛔ 别拿逗号当边界：标准声明「…12356，或…010-82951332（24 小时）」里
    两者同行，但 24 小时归 010。"""
    body = "热线 12356，或北京 010-82951332（24 小时）。"
    assert cvc.check(wd(tmp_path, body=body))["verdict"] == "ok"


# ────────── 取文本：多文件要合并 ──────────

def test_洗稿线四段脚本要合并读(tmp_path):
    """🔴 `script-1..4.txt` 是**一条片的四段**，只读第一段会把后面几段里的声明漏掉。"""
    (tmp_path / "script-1.txt").write_text("他要么是神，要么是坑。", encoding="utf-8")
    (tmp_path / "script-4.txt").write_text(DECL, encoding="utf-8")
    r = cvc.check(tmp_path)
    assert r["declaration_found"] is True
    assert "script-4.txt" in r["source"] and "script-1.txt" in r["source"]


def test_cues_json也能取到文本(tmp_path):
    (tmp_path / "narration.mp3.cues.json").write_text(
        json.dumps([{"text": TRIGGER_BODY}, {"text": DECL}], ensure_ascii=False),
        encoding="utf-8")
    assert cvc.check(tmp_path)["verdict"] == "ok"


def test_shots_json取narration_text(tmp_path):
    (tmp_path / "shots.json").write_text(
        json.dumps({"shots": [{"narration_text": TRIGGER_BODY + DECL}]}, ensure_ascii=False),
        encoding="utf-8")
    assert cvc.check(tmp_path)["verdict"] == "ok"


def test_source字段要写明读的哪个文件(tmp_path):
    """⚠️ 三次量具事故都源于「不知道它读了什么」。凭证里必须写明来源。"""
    assert cvc.check(wd(tmp_path, body=DECL))["source"] == "narration.txt"

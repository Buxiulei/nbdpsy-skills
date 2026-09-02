"""shared/compliance_core.py 的测试。

这个模块的存在理由是一句实测发现的话：**扫描域被工具的输入形态决定，而不是被
「什么东西会上线」决定**。公众号的 `digest`（摘要）是建草稿时单独传的参数、不在
任何文件里，所以**所有读文件的扫描器都永远扫不到它**——而它是读者在信息流里
第一眼看到的那行字。没有人做过「摘要不用扫」这个决定，它是工具形态的副产品。
⚠️ 最阴的一点：md 扫干净了，所有人都会以为扫完了——缺口被一份真实的绿色报告盖住。

所以第一条测试就是那个缺口本身（test_只有digest违规也必须抓到）：⛔ 它红了就说明
这次改造白做了。
"""
import importlib.util
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parent.parent / "shared" / "compliance_core.py"
_spec = importlib.util.spec_from_file_location("compliance_core_under_test", _SRC)
cc = importlib.util.module_from_spec(_spec)
sys.modules["compliance_core_under_test"] = cc
_spec.loader.exec_module(cc)


def _rules(items):
    return sorted({i["rule"] for i in items})


def _locs(items):
    return sorted({i["loc"] for i in items})


# ── 这次改造的存在理由 ────────────────────────────────────────────
def test_只有digest违规也必须抓到():
    """模拟公众号 payload：正文干净、**只有摘要违规**。

    读文件的扫描器在这一场景下会全绿——因为 digest 根本不在文件里。
    """
    units = [
        ("title", "复杂性创伤的日常困境"),
        ("digest", "六周彻底摆脱情绪闪回"),      # ← 唯一的违规，且它不在任何文件里
        ("body", "这是一段干净的正文，不构成医疗建议；危机请拨打 12356。"),
        ("author", "胡佰亿"),
    ]
    r = cc.check(units, crisis_scope="skip")

    assert r["ok"] is False, "只有 digest 违规时必须判 fatal——否则这次改造白做了"
    assert _locs(r["fatal"]) == ["digest"], r["fatal"]
    assert "R7-abs" in _rules(r["fatal"])


def test_全部干净时放行():
    """反面控制组：同一批字段全干净必须绿。⛔ 只测「会不会响」证明不了「会不会乱响」。"""
    units = [
        ("title", "复杂性创伤的日常困境"),
        ("digest", "会上被一句话击中，散会手还在抖——这叫情绪闪回。"),
        ("body", "本文不构成医疗建议；如处于心理危机请拨打 12356 或 010-82951332。"),
        ("author", "胡佰亿"),
    ]
    r = cc.check(units, crisis_scope="skip")
    assert r["ok"] is True, r["fatal"]
    assert r["fatal"] == []


# ── ⛔ 不收文件路径（这是判据不是实现细节）────────────────────────
def test_不接受文件路径当输入():
    """只要它收路径，扫描域就被文件边界锁死了——而 digest 恰好在边界外。

    传一个路径字符串进来，它会被当成 (loc, text) 解包失败或整串当文本，
    ⛔ 都不该被当成「读这个文件」。这里断言 API 里根本没有读文件的入口。
    """
    import inspect
    src = inspect.getsource(cc)
    for forbidden in ("open(", "Path(", "read_text", "read_bytes"):
        assert forbidden not in src, (
            f"compliance_core 里出现了 {forbidden}——它一旦能读文件，"
            "扫描域就会被文件边界锁死，这个模块的存在理由就没了")


# ── R7 两级严重度 ────────────────────────────────────────────────
@pytest.mark.parametrize("word", ["根治", "彻底摆脱", "100%"])
def test_绝对化词判fatal(word):
    r = cc.check([("body", f"这套方法可以{word}焦虑")], crisis_scope="skip")
    assert r["ok"] is False
    assert "R7-abs" in _rules(r["fatal"])


def test_医疗词只warning不拦():
    """医疗口径词是提示不是红线——学术转述里合法（「认知行为疗法」的研究文献）。"""
    r = cc.check([("body", "创伤后应激障碍的治疗研究显示…")], crisis_scope="skip")
    assert r["ok"] is True, "医疗词不该拦住发布"
    assert "R7-med" in _rules(r["warnings"])


# ── R8 停用热线：更正稿豁免（丢了会造成实际伤害）──────────────────
def test_停用热线推荐写法判fatal():
    r = cc.check([("body", "如处于心理危机请拨打希望24热线 4001619995")], crisis_scope="skip")
    assert "R8-dead-hotline" in _rules(r["fatal"])


def test_更正声明放行():
    """更正段**必须写出那个号码**，不写读者不知道更正的是哪条热线。

    ⚠️ 危险不在被拦，在下一步：有人照闸门去「修」会把号码删掉，
    于是更正废了、闸门反而变绿。
    """
    r = cc.check([("body", "我们此前写过「希望 24 热线 4001619995」，这条热线已经停止服务，在此更正。")],
                 crisis_scope="skip")
    assert r["fatal"] == [], r["fatal"]


def test_声明词在别行不豁免():
    """声明词必须与号码**同行**——否则文末一句「已停用」会豁免全篇。"""
    text = "危机可拨希望24热线 4001619995\n\n（顺带一提，某些旧热线已经停止服务。）"
    r = cc.check([("body", text)], crisis_scope="skip")
    assert "R8-dead-hotline" in _rules(r["fatal"])


def test_自相矛盾写法不豁免():
    """有声明词，但仍在叫人拨那个号 → 拦。"""
    r = cc.check([("body", "这条热线已停止服务，请拨打 4001619995 求助。")], crisis_scope="skip")
    assert "R8-dead-hotline" in _rules(r["fatal"])


def test_skip不豁免停用热线():
    """crisis_scope='skip' 只豁免「声明在位」，⛔ 绝不豁免错号码。

    可以不带危机声明（标题、摘要本来就不带），但不能带一个拨不通的号码——
    照着拨打不通，伤害与场景无关。
    """
    r = cc.check([("digest", "危机可拨 4001619995")], crisis_scope="skip")
    assert "R8-dead-hotline" in _rules(r["fatal"])
    assert r["crisis"] is None


# ── crisis_scope 三态 ────────────────────────────────────────────
def test_joined把单元拼起来判三要素():
    """三要素分散在不同单元里也算在位——它们本来就分散在整篇不同位置。"""
    units = [("body1", "本文不构成医疗建议。"),
             ("body2", "危机请拨 12356，或 010-82951332。")]
    r = cc.check(units, crisis_scope="joined")
    assert r["crisis"]["missing"] == [], r["crisis"]


def test_joined缺要素时报出来():
    r = cc.check([("body", "本文仅供参考。")], crisis_scope="joined")
    assert r["crisis"]["missing"], "缺三要素必须报"


def test_非法scope抛错不静默回落():
    """⛔ 静默回落会让调用方以为检查关了其实没关（或反之），是最难发现的一类假绿。"""
    with pytest.raises(ValueError):
        cc.check([("body", "x")], crisis_scope="per-unit")


# ── 词表唯一真源 ─────────────────────────────────────────────────
def test_调用方不许自带词表副本():
    """词表复制出去就会漂——今天一致，下次改了对面不知道。

    ⚠️ vendored 副本（各 skill 的 scripts/compliance_core.py）由
    tests/test_shared_sync.py 逐字节比对，这里查的是**别处有没有另抄一份词表**。
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    probes = ["彻底摆脱", "药到病除"]
    offenders = []
    for py in root.rglob("*.py"):
        if py.name == "compliance_core.py" or py.resolve() == pathlib.Path(__file__).resolve():
            continue
        if "__pycache__" in py.parts or ".git" in py.parts:
            continue
        txt = py.read_text(encoding="utf-8", errors="ignore")
        if all(p in txt for p in probes):
            offenders.append(str(py.relative_to(root)))
    assert not offenders, (
        f"这些文件里另抄了一份绝对化词表：{offenders}——"
        "⛔ 改成 import compliance_core，两边各存一份必漂")


# ── 停用热线·更正稿豁免（2026-08-29 审稿判据 1.5 订正后）────────────────────
# 旧判据是「同一行**无**推荐动词」⇒ 最自然的更正写法「已停止服务，请拨打 12356」
# 被拦，而「请改拨 12356」放行（只因「改拨」不在动词表）。同一件事因措辞不同结果相反。
# 新判据：有声明词 **且推荐动词之后不再出现任何死号变体**。

def test_更正稿推荐替代号码放行():
    """🔑 审稿 1.5 订正的核心用例：更正段推荐的是**替代**号码，不是死号。

    ⚠️ 必须用「拨打」⛔ 不许换成「改拨」——「改拨」是**碰巧**躲开动词表才放行的，
    用它验会把「碰巧」当成「因此」（内容线 8/29 指出，已写进判据 1.5）。
    """
    r = cc.check([("body", "希望热线 4001619995 已停止服务，请拨打 12356")], crisis_scope="skip")
    assert r["fatal"] == [], r["fatal"]


def test_推荐动词之后仍出现死号不豁免():
    """边界：声明词有、也推荐了好号码，但**之后又把死号列上了** ⇒ 真的在推荐它。"""
    r = cc.check([("body", "已停止服务，请拨打 12356 或 4001619995")], crisis_scope="skip")
    assert "R8-dead-hotline" in _rules(r["fatal"])


def test_劝阻式写法会假红是已知代价不是缺陷():
    """⚠️ **这条钉的是一个有意接受的代价，⛔ 不是在描述一个待修的 bug。**

    「不要再拨打 4001619995」＝劝阻，但「拨打」在动词表、其后有死号 ⇒ 判为推荐 ⇒ 假红。
    审稿 1.5 明令：**⛔ 不为它加否定前缀识别**——更正段场景稀少，穷举否定写法只会让
    规则越来越脆。遇到即按假红**回审稿线复判**，⛔ 实施方不自行绕过。

    ⇒ 若将来有人"顺手修好"了它，本测试会红——**那时该做的是回去看 1.5 是否已改口径，
    ⛔ 不是直接把这条测试删掉**。

    🩸 附一个精确度问题（8/29 实测）：审稿判据里举的样本是「⛔ 不要再**拨** 4001619995」，
    而**单独的「拨」不在动词表**（表里是 拨打/拨号/致电/打）⇒ 那个样本**碰巧放行**、
    验不出假红。真会假红的是「不要再**拨打**」「别再**致电**」「不必再**联系**」。

    🩸 **2026-09-02 复判并订正**：「拨」已加进动词表 ⇒ 上面那个样本现在也假红。
    起因是声明词表加了「不再推荐」，而「不再推荐，请**拨** 4001619995」在旧动词表下
    **静默放行**——自相矛盾句漏网。**口径没变**（劝阻式假红仍是已知代价），变的是覆盖面：
    原先那条「碰巧放行」是疏漏，不是给劝阻式留的豁免。⛔ 别据此认为劝阻式已被支持。
    """
    for text in ["已停止服务，请不要再拨打 4001619995",
                 "已停止服务，⛔ 别再致电 4001619995",
                 "已停止服务，不必再联系 4001619995",
                 "已停止服务，⛔ 不要再拨 4001619995"]:   # 末条 9/2 起同样假红（见上）
        r = cc.check([("body", text)], crisis_scope="skip")
        assert "R8-dead-hotline" in _rules(r["fatal"]), f"预期假红但放行了：{text}"


# ── 停用热线·新措辞「不再推荐」（2026-09-02 审稿判定：改闸门 ⛔ 改措辞）──────────
# 旧措辞「已停止服务」是推断级结论（官网停更 + 机构自述接通率，查无官方停服公告），
# 今后一律写「多次无法接通、不再推荐，请改拨 12356」。闸门原先不认「不再推荐」⇒ 把
# **唯一还准写**的那句话拦掉；红了之后人该做的事（把号码删掉或改回过度断言的措辞）
# 都不是真该做的事 ⇒ 那道闸红得不对。

def test_不再推荐是声明词_带死号的更正句放行():
    """B 措辞：写出死号 + 「不再推荐」+ 把读者引向 12356 ⇒ 放行。"""
    r = cc.check([("body", "希望24热线 4001619995 多次无法接通、不再推荐，请改拨 12356")],
                 crisis_scope="skip")
    assert r["fatal"] == [], r["fatal"]


def test_不再推荐不豁免裸推荐死号():
    """C：没有任何声明词，纯推荐死号 ⇒ 照红。声明词表放宽不得漏掉这一类。"""
    r = cc.check([("body", "如处于危机请拨打希望24热线 4001619995")], crisis_scope="skip")
    assert "R8-dead-hotline" in _rules(r["fatal"])


def test_不再推荐后仍叫人拨死号不豁免():
    """D：声明词在，但推荐动词之后仍出现死号 ⇒ 它仍在推荐那个号，照红。

    ⚠️ 这条正是「不再推荐」入表带出的新漏洞：旧动词表不认单独的「请拨」，
    本行会**静默放行**。故同批把「拨」补进 `DEAD_HOTLINE_RECOMMEND`（收紧）。
    """
    r = cc.check([("body", "不再推荐，请拨 4001619995")], crisis_scope="skip")
    assert "R8-dead-hotline" in _rules(r["fatal"])


def test_无法接通不单独构成停用声明():
    """⛔ 「无法接通」是症状不是声明：单凭它不得豁免——那行仍在把死号递给读者。"""
    r = cc.check([("body", "4001619995 偶尔无法接通，多打几次就好")], crisis_scope="skip")
    assert "R8-dead-hotline" in _rules(r["fatal"])

"""**「哪些算不可逆」的文档必须跟代码一致**——漏一个动作，人就会照文档去重试它。

🩸 起因（佰亿助理 2026-08-27 派单）：老板定案 **freepublish（发布）按不可逆办**——删了换链接、
数据清零、已分享的链接变死链。查下来本仓是**代码对、文档滞后**：

| 层 | 发布 freepublish | 结论 |
|---|---|---|
| `article_ops.py:400`（立即发布） | 已传 `irreversible=True` | ✅ |
| `schedule_ops.py:141`（定时发布走 `submit_job`） | 已传 `irreversible=True` | ✅ |
| `wechat_api.py` 两桶口径 | 已写「发布 / 群发 / 删除三件事都不可逆」 | ✅ |
| `capabilities.md` / `SKILL.md` / `wechat-oa-spec.md` 若干处 | **只列群发、删除** | ❌ 本文件钉的就是它 |

⇒ 危害**不是**「unknown 时真的会重发」（代码把那条路关死了），而是
**人读文档去改代码**：文档说不可逆只有群发和删除，下一个人就会把发布的
`irreversible=True` 当成手误"顺手清掉"，而那一刻**没有任何东西会红**。
这正是 [判据写进注释就会过期] 的反面——把清单钉进测试，改错才有人拦。

## 🔴 这四条判据各守什么、明确不守什么

- 判据 1 守**枚举漏项**（「群发、删除」这种并列里少了发布）——⛔ 不守属性挂错对象。
- 判据 2 守**属性挂错对象**（`wechat-oa-spec` 对照表里「不可逆」只挂在群发那半边，
  而「发布」两个字在同一行出现，所以判据 1 对它天然无效）。
- 判据 3 守**清单本身**必须三样齐全，且写明真源是代码里的 `irreversible=True`。
- 判据 4 守**「硬闸门」步骤在不在主流程表里**（零上下文干跑抓到的，见文末）。
- ⛔ 四条都**不守「发前要不要二次确认」**——发布那侧已由 `--approval` 留痕闸接管
  （判据在 `test_fuwuhao_ops.py::Test发布必须带批复坐标`），但**那道闸只保证坐标成形、
  ⛔ 不保证那个件真的批了**；群发/删除走的仍是 `--confirm` 拦截式。写在这里是为了
  让下一个人知道**哪些维度没有人管**，⛔ 别看见本文件全绿就以为都守住了。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FUWUHAO = ROOT / "nbdpsy-fuwuhao-operator"
CAPABILITIES = FUWUHAO / "references" / "capabilities.md"
OA_SPEC = FUWUHAO / "references" / "wechat-oa-spec.md"
SKILL = FUWUHAO / "SKILL.md"

# 不可逆动作的真源＝脚本里传 irreversible=True 的那些动作。本仓当前三样：
# 发布(freepublish，含定时发布) / 群发(mass) / 删除已发布(delete)。
# ⚠️ 视频号发布虽也是不可逆，但本仓**无实现面**（text-to-video/SKILL.md 已实调定案：
#    视频号无内容发布 API、只能人工发）⇒ ⛔ 不进本清单，免得钉一个不存在的东西。
ACTIONS = ("发布", "群发", "删除")

# 「正在讲不可逆 / 正在讲失败要不要重试」的语境词
IRREVERSIBLE_CTX = ("不可逆", "撤不回", "不可撤销")
RETRY_CTX = ("不自动重试", "不要重试", "绝不重试", "绝不盲目", "绝不自动重试", "失败不自动")

DOCS = [CAPABILITIES, OA_SPEC, SKILL]


def enumerating_lines(path):
    """挑出「在不可逆/重试语境下枚举动作」的行：含语境词 + 同时点名群发与删除。"""
    out = []
    for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        ctx = any(k in ln for k in IRREVERSIBLE_CTX) or any(k in ln for k in RETRY_CTX)
        if ctx and "群发" in ln and "删除" in ln:
            out.append((i, ln))
    return out


# ── 判据 1：枚举漏项 ────────────────────────────────────────────────────
def test_不可逆与重试语境的枚举必须含发布():
    bad = []
    for doc in DOCS:
        for i, ln in enumerating_lines(doc):
            if "发布" not in ln:
                bad.append(f"{doc.relative_to(ROOT)}:{i} {ln.strip()[:78]}")
    assert not bad, (
        "这些行在讲「不可逆」或「失败别重试」时只枚举了群发和删除，**漏了发布(freepublish)**。\n"
        "代码里发布早就是 irreversible=True，文档漏列会让下一个人把它当手误清掉：\n  "
        + "\n  ".join(bad))


def test_判据1至少扫到过东西():
    """🔴 量具自检：判据 1 靠「同时含群发与删除」定位，若哪天文档改了写法导致一行都
    选不中，它会**恒绿**——恒绿的扫描比没有扫描更糟，它占着「我们查过了」的位置。"""
    total = sum(len(enumerating_lines(d)) for d in DOCS)
    assert total >= 2, f"判据 1 在三份文档里只选中 {total} 行，疑似定位条件失效（恒绿）"


# ── 判据 2：属性挂错对象（判据 1 对它天然无效）────────────────────────
# 「发布**自己**也不可逆」的语义锚点。⛔ 不能只查这行含不含「不可逆」——
# 原文「群发**每自然月仅 4 次且不可逆**」本来就含这三个字，只是挂在群发那半边。
# 🩸 我第一版判据正是这么写的：名字叫「属性挂错对象」，实现却在查「有没有这个词」，
#    于是它**对着要抓的那一行返回了绿**。闸门存在、名字也对、检查的维度差一格——
#    这比没有闸门更糟，因为下一个人会以为有人管了。
# ⇒ 钉**语义特征**：必须出现「两者/都/同样…不可逆」这类把不可逆也扣在发布头上的说法。
#    新写法就往这里加一个，⛔ 别把这条判据删掉。
BOTH_IRREVERSIBLE = ("两者都不可逆", "都不可逆", "均不可逆", "发布同样不可逆",
                     "发布也不可逆", "同样不可逆", "两者皆不可逆")


def test_对照表里发布那行必须自己声明不可逆():
    """🩸 `wechat-oa-spec.md` 的对照表原文是：
        | **发布(freepublish) ≠ 群发(mass)** | 发布不推送粉丝、不占次数；群发**每自然月仅 4 次且不可逆** |
    「发布」两个字就在这行里，所以判据 1 放行；「不可逆」也在这行里，所以「查有没有这个词」
    同样放行——但它**挂在群发那半边**，读者拿走的结论恰好是「发布是可逆的」。
    ⇒ 这一维必须用语义锚点单独钉。"""
    lines = OA_SPEC.read_text(encoding="utf-8").splitlines()
    hits = [ln for ln in lines if "freepublish" in ln and "≠" in ln]
    assert hits, "对照表里找不到 freepublish 那行——判据锚点失效（结构变了就来改这条，⛔ 别删）"
    for ln in hits:
        assert any(k in ln for k in BOTH_IRREVERSIBLE), (
            "freepublish 与群发的对照行里，「不可逆」只挂给了群发那半边，会被读成「发布可逆」。\n"
            f"请写明发布同样不可逆（可用词：{BOTH_IRREVERSIBLE[:3]}…）：\n  " + ln.strip())


# ── 判据 3：清单本身 ───────────────────────────────────────────────────
def test_能力档里有一份三样齐全的不可逆清单():
    text = CAPABILITIES.read_text(encoding="utf-8")
    seg = [ln for ln in text.splitlines()
           if any(k in ln for k in IRREVERSIBLE_CTX) and all(a in ln for a in ACTIONS)]
    assert seg, (
        f"`capabilities.md` 里没有一行同时点齐 {ACTIONS} 三样的不可逆清单。"
        "⇒ 各处只能各自枚举，而各自枚举必然漂移（本次事故就是这么来的）。")


def test_清单写明真源是代码():
    """判据会过期，而过期时没有东西会红 ⇒ 清单必须写明「谁保证这三样是对的」。"""
    text = CAPABILITIES.read_text(encoding="utf-8")
    assert "irreversible=True" in text, (
        "不可逆清单没写出处。⇒ 下一个人无法判断该不该往里加动作，"
        "而清单一旦与代码脱节，没有任何东西会红。请写明真源＝脚本里传 `irreversible=True` 的调用点。")


# ── 量具自检：坏样本必抓、好样本必放 ──────────────────────────────────
_BAD = [
    "2. **不可逆动作失败时不要重试**。群发、删除失败若拿到 `outcome: unknown`，意味着…",
    "### ⑤ 群发 / 删除**失败不自动重试**——先分清哪种败相",
    # 🩸 这里原本还放了 `SKILL.md:140`「涉及群发/删除的，红线①/②已当面复述并拿到确认」，
    #    自检当场红——**判据没错，是我把样本放错了维度**：那句讲的是「发前要不要确认」，
    #    而本文件头已写明三条判据都不守确认维度。同族教训：一条用例断言了不属于它那一维的
    #    东西，红灯就会指向错的地方，让人去改本来对的判据。确认维度待设计定案后另立判据。
]
_GOOD = [
    "非幂等动作（发布 / 群发 / 删除）的败相按**这次到底成没成**分两种",   # 仓内现成的正确写法
    "2. **不可逆动作失败时不要重试**。发布、群发、删除失败若拿到 unknown…",
    "群发每自然月仅 4 次",                       # 没有不可逆/重试语境 ⇒ 不该被选中
]


@pytest.mark.parametrize("line", _BAD)
def test_量具自检_漏发布的写法必须被选中并判红(line):
    ctx = any(k in line for k in IRREVERSIBLE_CTX) or any(k in line for k in RETRY_CTX)
    assert ctx and "群发" in line and "删除" in line, f"判据选不中这行：{line[:50]}"
    assert "发布" not in line, "坏样本自身要求不含发布"


@pytest.mark.parametrize("line", _GOOD)
def test_量具自检_正确写法必须放行(line):
    ctx = any(k in line for k in IRREVERSIBLE_CTX) or any(k in line for k in RETRY_CTX)
    selected = ctx and "群发" in line and "删除" in line
    assert (not selected) or ("发布" in line), f"误伤正确写法：{line[:50]}"


# ── 判据 4：叫「硬闸门」的步骤必须出现在唯一会被完整执行的那张流程表里 ────────
def test_硬闸门步骤必须进主流程表():
    """🩸 零上下文干跑（2026-08-28）抓到：`zh_review.py`（中文本土化终审）文档里叫
    「硬闸门」「每篇必过」，但**主流程表从 2.5 直接跳到 3**，它只活在下面的散文段落里；
    而代码层**零处调用**（`md2wechat` / `article_ops` 都不检查）。

    ⇒ 两个保障一个都不存在：**既没有代码强制，也不在那张「一眼过一遍」的表里**。
    照表走的人会完整跳过它且不会看到任何报错。
    ⚠️ 本判据只守「它在不在表里」——**⛔ 不守「代码有没有强制」**（那是另一件事，
    已上报收口人另立）。⛔ 别看见这条绿就以为外审这一步有人管了。"""
    text = SKILL.read_text(encoding="utf-8")
    i = text.index("## 完整流程")
    table = text[i:i + 2000]
    assert "2.7" in table, (
        "主流程表里没有 2.7（中文本土化终审）。它在别处被称作「硬闸门」，"
        "而代码零处强制 ⇒ 不在这张表里就等于不存在。")
    assert "没有任何代码会替你跑这一步" in table, (
        "2.7 那行要写明**没有代码兜底**——否则读者会以为漏了会有东西报错。")

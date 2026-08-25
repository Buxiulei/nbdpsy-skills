"""开头段落的 GEO 结构原则（Princeton KDD 2024 / arXiv:2311.09735）。

三条原则里**只有两条能机检**，第三条明说判不了——⛔ 不混成一条含糊 warn：
| 条 | 谁判 |
|---|---|
| ① 首句非铺垫/非设问 | ✅ 机检 |
| ③ 无**自夸式**形容词 | ✅ 机检 |
| ② 可验证参数 | 🔴 机器判不了 → `manual` |

⚠️ ② 判不了的理由：机器能数出「4 步」是数字，**⛔ 判不出它是否属实**——
"3 步"与"7 步"哪个是事实，机器看不见。⇒ 与本仓既有的 R3 数字真实性、R4 专家引语同档。
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "nbdpsy-seo-artical-creator" / "scripts"
SPEC = ROOT / "nbdpsy-seo-artical-creator" / "references" / "pillar-spec.md"
sys.path.insert(0, str(SCRIPTS))

import preflight as pf  # noqa: E402


# ────────── 机检两条：坏样本必报 ──────────

@pytest.mark.parametrize("first,why", [
    ("在当今这个快节奏的社会，越来越多人开始关注睡眠问题。", "时代背景铺垫"),
    ("随着生活节奏的加快，失眠人群逐年上升。", "随着…的加快"),
    ("说到心理咨询，很多人第一反应是「那是有病的人才去的」。", "话题引入式"),
    ("提起创伤，你会想到什么？", "提起…＋设问"),
    ("你是否也有过这样的体验：明明很累，却怎么也睡不着？", "设问开场"),
    ("我们拥有业内领先的资深专家团队。", "自夸：业内领先"),
    ("本机构是国内第一的心理服务平台。", "自夸：国内第一"),
    ("我们的方案能彻底解决你的失眠困扰。", "自夸：彻底解决"),
])
def test_坏开头必须报(first, why):
    assert pf.geo_open_issues(first), f"漏报（{why}）：{first[:24]}"


# ────────── 机检两条：正当写法⛔不许误伤 ──────────

@pytest.mark.parametrize("first,why", [
    ("首次心理咨询通常分 4 步：预约建档、50 分钟初诊会谈、匹配咨询师、确定后续频率。",
     "标准合格开头（含可验证参数）"),
    ("倦怠不是模糊的「好累」。心理学家 Christina Maslach 把它拆成三个可识别的维度。",
     "本站真实存量写法：命名实体开头"),
    ("内在批判者是脑中那个不断贬低、苛责、要求你完美的声音。",
     "🔴「完美」在描述**对象**，⛔ 不是自夸"),
    ("沉默是一块最好的幕布：他给的现实信息越少，你投射得越多。",
     "🔴「最好的幕布」是比喻，⛔ 不是自夸"),
    ("也正因为没有画面，它极其隐蔽，常被当事人误读成「我情绪化」。",
     "🔴「极其隐蔽」在描述**现象**，⛔ 不是自夸"),
    ("很多人以为创伤只来自车祸、灾难这类「大事件」。但有一类创伤，来自长期的关系环境。",
     "🔴**先破后立**：首句就在给结论，⛔ 不是铺垫"),
    ("认知行为疗法对轻中度抑郁的有效率在 50%~60% 之间（NICE 指南 CG90），疗程 12~20 次。",
     "统计数据开头"),
])
def test_正当写法不许误伤(first, why):
    """🩸 判据初版拿**裸词表**（完美/最好/极其/显著…）判，
    **88 篇存量实测误伤 16 篇（18%）**——而上面这些都是本站的正当写法。
    改成**搭配式**（`业内领先`／`效果显著`／`最好的方案`…）后降到 **1%**。
    ⇒ **定这类判据必须拿存量真稿校准，⛔ 不能只用手造样本**——
    手造的样本不会告诉你本站的正当写法长什么样。"""
    assert not pf.geo_open_issues(first), f"误伤（{why}）：{pf.geo_open_issues(first)}"


# ────────── frontmatter 必须先剥 ──────────

def test_首段提取要先剥frontmatter():
    """🩸 直接把发布态全文喂给 `_intro_first_para` 会把 YAML 当成首段——
    88 篇实测有 4 篇因此误报，抓到的"首段"是 `author_name: …`。"""
    # 🔴 **样本必须无 H1**——发布态正文的 H1 已被剥，那 4 篇误报的正是这种形态。
    #    ⚠️ 带 H1 的样本**测不出这个 bug**：`_intro_first_para` 从 H1 之后取，
    #    YAML 在 H1 之前，剥不剥都对（🩸 首版测试就是这么写的，变异「不剥 frontmatter」竟然存活）。
    md = ("---\nauthor_name: 李冠阳\ncategory_slug: emotion-self\n---\n\n"
          "首次心理咨询通常分 4 步：预约建档、50 分钟初诊会谈、匹配咨询师、确定后续频率。\n")
    assert not pf.RE_H1.search(md), "样本一旦有 H1 就绕过了本条要测的场景"
    # 不剥的话会把 YAML 当首段（这正是 88 篇里 4 篇误报的成因）
    assert "author_name" in pf._intro_first_para(md)[0], "前提变了：请重审本测试"
    first = pf.geo_first_para(md)
    assert first.startswith("首次心理咨询"), f"没剥干净：{first[:40]!r}"
    assert "author_name" not in first


# ────────── 三条原则的机检/人工分界 ──────────

SRC = (SCRIPTS / "preflight.py").read_text(encoding="utf-8")


def test_可验证参数标manual而不是混进机检():
    """🔴 收口人 2026-08-25 点名：**能机检的就机检、判不了的写成人工自检项并明说判不了**，
    ⛔ 别混成一条含糊的 warn。"""
    assert '"geo-verifiable-params", "manual"' in SRC
    i = SRC.index('"geo-verifiable-params"')
    seg = SRC[i:i + 600]
    assert "机器判不了" in seg, "必须明说判不了，⛔ 不能含糊带过"
    assert "关键词堆砌" in seg, "反例要在同一条里给出"


def test_机检那条不假装判了可验证参数():
    i = SRC.index('"geo-open-structure"')
    seg = SRC[i:i + 900]
    assert "机检两条" in seg, "pass 文案要说清只过了两条，⛔ 别让人以为三条全过"


# ────────── 证据出处：逐字进规格，且⛔不压缩成区间 ──────────

#: 🔴 **真源唯一**：本仓 `seo-geo/research/02-GEO-海外引擎.md` §2.1
#: （Princeton GEO，KDD 2024，arXiv:2311.09735 v3，带 ACM DOI 双链接）。
RESEARCH = ROOT.parent / "NBDpsy" / "seo-geo" / "research" / "02-GEO-海外引擎.md"


def test_证据出处逐字在规格里():
    """🔴 出处逐字进规格，理由是**下一个人会问「凭什么」**——
    没有出处的规格条目最容易在下一次改版被人凭手感删掉。
    ⚠️ 而**「下一个人」真的来了**：2026-08-25 服务号线核规格时发现数字对不上（见下条）。"""
    spec = SPEC.read_text(encoding="utf-8")
    for token in ("arXiv:2311.09735", "+41%", "+28%", "−10%", "关键词堆砌"):
        assert token in spec, f"规格里缺证据要素：{token}"


def test_数字必须与本仓研究原文一致():
    """🩸 **我把这张表写错过一次**（2026-08-25）：写成「引用来源 +31%／统计数据 +31%／
    引述 +41%」——**两项对调、一项凭空**。而当时我还"拦下"了一个 28%，理由是
    「全文仅此一处、证据表里查无」——**28% 恰恰是 quotation addition 的值**。

    🔴 **根因：`2311.09735` 在本仓有两个来源文件，我只 grep 了其中一个**，
    就下了「全文查无」的结论。⚠️ 更该早发现的是 `pillar-spec.md` **第 3 行**
    早就写着「统计 +41%、引语 +28%」，**与我在同一文件 310 行新写的数字当场矛盾**。

    ⇒ 本测试改为**直接比对研究原文**，⛔ 不再钉死字面量——
    **判据要挂在真源上，⛔ 不是挂在我记得的那个数上。**"""
    if not RESEARCH.is_file():
        pytest.skip(f"研究原文不在（{RESEARCH}）——⚠️ 这是「没查成」⛔ 不是「一致」")
    research = RESEARCH.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    for token in ("+41%", "+28%", "-10%"):
        assert token in research, f"研究原文里没有 {token}，请重审本测试的前提"
    # 规格里的三个数必须都是研究原文里有的（−10% 规格用全角负号，另判）
    assert "+41%" in spec and "+28%" in spec and "−10%" in spec
    # ⛔ 编出来的 +31% 不许**当作规格**再出现；⭕ 但**留档叙述**（讲我写错过什么）要放行——
    # ⚠️ 判据要区分「在陈述规格」与「在讲那次错误」，⛔ 抓词会把留档一起删掉，
    #    而留档正是下一个人知道"这里踩过坑"的唯一线索。
    EXEMPT = ("写成", "曾", "写错", "对调", "凭空", "留档")
    for i, ln in enumerate(spec.splitlines()):
        if "+31%" not in ln:
            continue
        ctx = "\n".join(spec.splitlines()[max(0, i - 2):i + 1])
        assert any(k in ctx for k in EXEMPT), f"写错过的 +31% 又被当规格写回来了：{ln.strip()[:60]}"


def test_带条件的收益不许写成裸百分比():
    """🔴 「引用权威外部来源」在论文里是**带条件**的：
    **低排名页面最高 +115%，第 1 位页面几乎无变化**。
    ⚠️ 写成裸的「加引用来源 +X%」会让读规格的人以为**对任何页面都有效**
    ——收益取决于页面当前排名。（服务号线 2026-08-25 指出，比数字错更值得改的一处。）"""
    spec = SPEC.read_text(encoding="utf-8")
    if "115" in spec:
        i = spec.index("115")
        seg = spec[max(0, i - 120):i + 160]
        assert "低排名" in seg or "第 1 位" in seg, "+115% 必须带条件，⛔ 不许写成裸百分比"


def test_机检与人工的分界也写进了规格():
    spec = SPEC.read_text(encoding="utf-8")
    assert "机器判不了" in spec and "manual" in spec


# ────────── 小红书侧：只落两条，且**未验证的前提必须写在规格里** ──────────

XHS_SPEC = ROOT / "nbdpsy-xiaohongshu-creator" / "references" / "xiaohongshu-spec.md"


def test_小红书侧写明第一条不适用及理由():
    """两条原则**方向相反不是矛盾，是不同战场的不同解**：
    GEO 优化机器抓取引用，三段式优化人在信息流 3 秒内滑不滑走。"""
    spec = XHS_SPEC.read_text(encoding="utf-8")
    assert "arXiv:2311.09735" in spec, "证据出处要在（下一个人会问「凭什么」）"
    assert "不适用" in spec and "三段式" in spec, "要写明①不适用及其理由"
    assert "业务结构" in spec, "理由要落到「它是业务结构」，⛔ 不是「我们觉得不合适」"


def test_未验证的前提必须留在规格里():
    """🔴 **这条规格的正确性挂在一个尚未实测的前提上**：
    「小红书笔记正文不在 AI 引擎的主要抓取面」。

    ⚠️ **前提不写下来，将来它失效时没人知道该回头改哪一条** ——
    本仓已在 `MIN(发起+72h, 开始−8h)` 与「预约待确认」上各栽过一次，
    两次都是**变更发生了、而依赖它的下游没人知道**。

    ⇒ 本测试钉住三样：前提本身、「尚未实测」的自认、以及「失效时须重议」的出口。
    ⛔ 谁把它们删掉（把 A 变成没人敢碰的黑箱），这条立刻红。"""
    spec = XHS_SPEC.read_text(encoding="utf-8")
    assert "不在 AI 引擎的主要抓取面" in spec, "前提本身被删了"
    assert "须重议" in spec, "要留失效时的出口，否则没人知道该回头改哪一条"
    # 🩸 **判据返工过一次**：初版只断言子串「尚未实测」，而它在文中有 **2 处**
    #    （小节标题 + 正文那句）⇒ 变异删掉**正文那句自认**，测试照样绿。
    #    ⚠️ 子串"存在"证明不了"那句话还在说它该说的事"。
    # ⇒ 改钉**完整的自认句**，⛔ 不是钉一个词。
    assert "该前提尚未实测" in spec, "⛔ 不许把未验证的前提写成既定事实（那句自认被改掉了）"
    assert spec.count("尚未实测") >= 2, "标题与正文两处自认都要在"


def test_旁证要标明是旁证不是证明():
    """⚠️ 2026-08-24 GEO 基线只测了**品牌词**，⛔ 推不出「小红书内容永不被引」。
    把旁证写成证明，等于把「没测过」渲染成「测过了」。"""
    spec = XHS_SPEC.read_text(encoding="utf-8")
    assert "旁证" in spec and "不是证明" in spec
    assert "只测了品牌词" in spec, "要写明旁证的覆盖边界"

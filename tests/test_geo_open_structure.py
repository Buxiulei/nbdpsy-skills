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

#: 🔴 **真源＝论文原表**（`arxiv.org/html/2311.09735v3` 表 1／表 2／表 5）。
#: ⚠️ 本仓的二手转写（`seo-geo/research/02-GEO-海外引擎.md` §2.1、
#:    `docs/secretary/调研-…-20260825.md`）**两份都错了**，⛔ 别再拿它们当真源。

#: 论文表 2（按 SERP 排名）——**唯一能直接引用的相对百分比**
PAPER_TABLE2 = {
    "Cite Sources":      {"rank1": -30.3, "rank5": 115.1},
    "Quotation Addition": {"rank1": -22.9, "rank5": 99.7},
    "Statistics Addition": {"rank1": -20.6, "rank5": 97.9},
    "Keyword Stuffing":  {"rank1": -6.0,  "rank5": 6.1},
}


def test_证据出处逐字在规格里():
    """🔴 出处逐字进规格，理由是**下一个人会问「凭什么」**。
    ⚠️ 而「下一个人」真的来了**两次**——服务号线两轮都核出我写错了数字（见下）。"""
    spec = SPEC.read_text(encoding="utf-8")
    for token in ("2311.09735", "115.1", "−30.3", "表 2"):
        assert token in spec, f"规格里缺证据要素：{token}"


#: 🔴 **所有落了 GEO 原则的规格文件**——判据要覆盖它们**全部**。
#: 🩸 变异实测：判据只查 `SPEC` 时，往 `DIST` 里写方向错的话**照样绿**
#:    （「③抽掉头条裁定 / ④方向说反 / ⑤把单次确认的分值写回去」三项变异全部存活）。
#:    ⇒ **判据的覆盖面本身要被审视** —— 与 [[量具失明族⑦：「全文」只是一个文件]] 同族。
def _geo_specs():
    out = []
    for f in (SPEC, DIST, ROOT / "nbdpsy-xiaohongshu-creator" / "references" / "xiaohongshu-spec.md"):
        if f.is_file() and "2311.09735" in f.read_text(encoding="utf-8"):
            out.append(f)
    assert len(out) >= 3, f"落了 GEO 原则的规格文件只找到 {len(out)} 个，请重审覆盖面"
    return out


def test_Rank1为负的方向不许说反():
    """🔴 **这是这组测试里最要紧的一条** —— 它防的是**方向错**，⛔ 不是数字不准。

    🩸 规格一度写着「加引用来源：低排名页最高 +115%，**第 1 位页面几乎无变化**」。
    论文表 2 实际：**Cite Sources 在 Rank-1 是 −30.3%**，三个主策略在 Rank-1 **全为负**。
    ⇒ 那句话告诉写作者「高排名页加引用来源无害，加就加吧」，
    而论文说**那正是伤害最大的情形** —— **照着做会主动损害我们排名最好的页面。**

    ⚠️ **我上一版的测试会放行这个错误**：它只断言「出现 115 时附近要有『低排名/第 1 位』字样」
    —— **条件说明在，但说反了**。**判据钉住了"有没有说"，没钉住"说得对不对"**
    （服务号线 2026-08-25 指出）。⇒ 本条改为**钉方向**。"""
    for f in _geo_specs():                      # ⛔ 不只查 pillar-spec
      spec = f.read_text(encoding="utf-8")
      assert "−30.3" in spec, f"{f.name}：Rank-1 的负值必须出现，⛔ 不能只说「低排名页受益」"
      # ⛔ 不许把负值说成中性——⚠️ 但**禁令句本身**要放行：判据钉的是「有没有人当作事实这么写」。
      for bad in ("几乎无变化", "几乎没有变化", "影响不大", "基本无影响"):
        for i, ln in enumerate(spec.splitlines()):
            if bad not in ln:
                continue
            ctx = "\n".join(spec.splitlines()[max(0, i - 2):i + 1])
            assert any(k in ctx for k in ("⛔ 别写成", "别写成", "方向错", "写错", "曾")), \
                f"{f.name}：方向错的措辞被当作事实写回来了：{ln.strip()[:60]}"
      # 「Rank-1 有害」这件事必须被明说。
    # 🩸 **判据一度是三选一（全为负/反受损/有害），删掉其中一个仍绿** ——
    #    冗余表述救了它，但**那是运气不是判据**。⇒ 改为**三项都要在**：
    #    「全为负」给事实、「反受损/弱者武器」给结论、「⛔ 别对已排第一的页面用」给动作。
      for must in ("全为负", "反受损"):
        assert must in spec, f"{f.name}：必须明说高排名页会受损（缺「{must}」）"
      assert "弱者武器" in spec, f"{f.name}：要给出可执行结论 GEO 是弱者武器"


def test_绝对分值不许当百分比引用():
    """🩸 我第二版把表 1／表 5 的**绝对分值**（24.9／27.8／25.9）当成了百分比，
    写出「统计 +41%／引语 +28%」——**那两个数论文里根本不存在**。
    ⇒ 规格必须写明表 1/5 是绝对分值。"""
    spec = SPEC.read_text(encoding="utf-8")
    assert "绝对分值" in spec, "要写明表 1/表 5 是绝对分值⛔不是百分比"
    for ghost in ("+41%", "+28%", "+31%"):
        for i, ln in enumerate(spec.splitlines()):
            if ghost not in ln:
                continue
            ctx = "\n".join(spec.splitlines()[max(0, i - 3):i + 1])
            assert any(k in ctx for k in ("写成", "曾", "写错", "对调", "凭空", "留档",
                                          "仍是错", "以为", "也是错", "已一并改正")), \
                f"论文里不存在的 {ghost} 又被当规格写回来了：{ln.strip()[:60]}"


def test_数字要标到表号():
    """⚠️ 论文按 domain/position/引擎分了多组，**不标出处就是各取一组**：
    表 1 引语>统计、表 5 统计>引语 —— **相对顺序相反**。
    ⇒ 不标明取自哪张表，「谁更有效」这个结论本身就不成立。"""
    spec = SPEC.read_text(encoding="utf-8")
    # ⚠️ `115.1` 在文中出现多处（首行依据句 + 正文证据表）——**至少一处**标明表号即可，
    #    ⛔ 别用 `index()` 只看第一处（🩸 首版就是这么写的，把标了表号的正文漏掉了）。
    spots = [i for i in range(len(spec)) if spec.startswith("115.1", i)]
    assert spots, "规格里没有 +115.1%"
    assert any("表 2" in spec[max(0, i - 400):i + 400] for i in spots), \
        "+115.1% 至少要有一处标明来自表 2"

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


# ────────── 分发稿（公众号/头条/知乎）：落 distribution-spec，⛔ 不落发布线 ──────────

DIST = ROOT / "nbdpsy-seo-artical-creator" / "references" / "distribution-spec.md"


def test_公众号那条落在写稿人会读到的文件里():
    """🩸 我一度要把公众号那条派给**服务号线**（`nbdpsy-fuwuhao-operator`）——
    而那个 skill **不写稿、只发稿**，它的 references 是端点清单/能力阐述/配图规格，
    **没有一份是写作规格**。公众号的文字来自 `distribution-spec.md` 的 gzh 段。
    ⇒ 落错文件的话，**写稿的人根本不会读到，等于规范放了等于没放**
    （服务号线 2026-08-25 查落点时发现）。
    ⚠️ 同族：**work 不在会被读到的位置＝work 不存在**。"""
    dist = DIST.read_text(encoding="utf-8")
    assert "2311.09735" in dist, "GEO 原则没落进分发规格"
    assert "首句给完整结论" in dist


@pytest.mark.parametrize("platform", ["公众号", "头条号", "知乎"])
def test_三平台各自裁定过(platform):
    """⛔ 不一刀切：三平台既有要求本就不同（知乎「第一句直接给答案」一直就是对的、
    头条「首段 100 字内点明价值」同向、公众号有「共情场景钩子」需与①合并读）。"""
    dist = DIST.read_text(encoding="utf-8")
    i = dist.index("三平台怎么落")
    seg = dist[i:i + 900]
    assert platform in seg, f"{platform} 没在裁定表里"
    # ⛔ 光出现名字不够：每行必须给出「落不落 ①」与理由
    row = next((l for l in seg.splitlines() if platform in l and "|" in l), None)
    assert row and row.count("|") >= 4, f"{platform} 那行不是完整裁定行（要有 ①/②③/理由）"


def test_公众号共情钩子与首句结论是合并不是二选一():
    """⚠️ 公众号既有规范「开头 3 行内有共情场景钩子」与 ① 不是二选一：
    **首句给结论，共情场景紧跟其后**，⛔ 别把场景放在结论前面当铺垫。"""
    dist = DIST.read_text(encoding="utf-8")
    assert "合并读" in dist and "⛔ 不是二选一" in dist


def test_不写只被单次读取确认过的分值():
    """🔴 **这条钉的是一次自律**：表 1/表 5 的绝对分值，**本线与服务号线两次独立抓取
    读出的结果不一致**（一次读成百分比、一次读成分值）⇒ 小模型读那两张表不稳定。

    ⇒ 规格里**只写「那是绝对分值⛔不是百分比」这句警告，不写具体分值** ——
    警告的作用不需要分值也成立；写上就是**又引入一组只被单次读取确认过的数字**，
    正是这条警告本身要防的事（🩸 我在同一组数上已经错过两版）。

    ⚠️ 与之相对：**表 2 那组数两次独立抓取完全一致 ⇒ 可用**。
    ⇒ **判据不是「不写数字」，是「不写只被单次确认过的数字」。**"""
    for f in (SPEC, DIST, ROOT / "nbdpsy-xiaohongshu-creator" / "references" / "xiaohongshu-spec.md"):
        t = f.read_text(encoding="utf-8")
        if "2311.09735" not in t:
            continue
        for ghost in ("24.9", "27.8", "25.9", "29.1", "26.2", "21.9"):
            assert ghost not in t, f"{f.name} 写了只被单次读取确认过的分值 {ghost}"
        assert "115.1" in t, f"{f.name} 缺表 2 那组两次一致、可用的数"


# ────────── 同一文件的多个小节，不许互相矛盾 ──────────

def test_同一原则在同一文件的各小节要一致():
    """🩸 **同一形状降了两层**（2026-08-25 一天之内）：
    1. 「『全文』只是一个文件」—— 我 grep 一个文件就下「全文查无」结论；
    2. 「判据的"全仓"只是一个文件」—— 判据只查 `pillar-spec`，`distribution-spec` 里写错也绿；
    3. **本条：「判据的"全文件"只是一个小节」** ——
       GEO 节（§18）写了「首句给结论」，而**「各平台要求·公众号版」（§66）仍原样写着
       「开头 3 行内有共情场景钩子」**，单独读就是"开头先写共情场景"。

    🔴 **而写稿的人最可能读的正是后一节** —— 它叫「各平台要求」，是全文最像操作清单的地方、
    且在文件更后面。⇒ **有人跳到那里照着写，前面那句「⛔ 别把场景放在结论前面当铺垫」
    他根本不会看到**（服务号线 2026-08-25 独立核对时抓到）。

    ⚠️ **问题不在措辞不清，在另一节没说这句话。**"""
    dist = DIST.read_text(encoding="utf-8")
    # 「各平台要求」小节里，凡提到"开头/首句"的行，⛔ 不许出现"场景在前"的孤立写法
    i = dist.index("## 各平台要求")
    section = dist[i:]
    for j, ln in enumerate(section.splitlines()):
        if "开头" not in ln and "首句" not in ln:
            continue
        if "共情" not in ln and "场景" not in ln:
            continue
        assert ("首句给完整结论" in ln or "紧跟其后" in ln
                or "GEO 结构" in ln), \
            f"「各平台要求」里这行单独读会让人先写场景，⛔ 与 GEO 节矛盾：{ln.strip()[:70]}"

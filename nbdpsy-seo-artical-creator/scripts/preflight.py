#!/usr/bin/env python3
"""Pillar 长文发布前统一预检管道（一条命令逐项机检 pillar-spec 全部可判定项）。

动机（2026-07 真实事故）：pillar-spec 十条硬性要求此前分散在多个脚本与"人工自觉"之间，
R3「带出处统计块」被静默跳过、靠人工遵守失守（有文章引 8 篇实证研究却零数据点）。
本管道把**所有可机检项**收进一条命令：任一 fail 拦住发布；不可机检项（引文可达性/数字口径
联网核实/专家引语真实性）明确标 manual，绝不假装能测。

用法:
  preflight.py <draft.md> [--online]
契约: stdout=纯 JSON {"ok","summary","checks":[{id,rule,status,detail,fix?}]}
      status ∈ pass|fail|warn|manual；任一 fail → exit 1；文件缺失 → exit 2。
      --online 时对 R6 参考文献 URL、R9 内链 /blog/ slug、F1 tags 标签库做联网校验
      （死链 404/5xx → fail；网络异常/反爬 → warn，宽容降级）。

实现复用同目录脚本函数（不 subprocess 套娃）：count_hanzi / lint_markdown / publish_post.parse_frontmatter。
每条检查在注释标注对应 pillar-spec 的 R 编号（references/pillar-spec.md 硬性要求清单）。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# 同目录 vendored 依赖
sys.path.insert(0, str(Path(__file__).resolve().parent))
import count_hanzi          # noqa: E402  R1 纯汉字计数
import lint_markdown        # noqa: E402  R3/渲染合规
import compliance_core      # noqa: E402  R7 词表 + R8 热线判据的唯一真源（shared/）
from publish_post import parse_frontmatter  # noqa: E402  frontmatter 解析（复用发布口径）

# ── 本地常量（与 references/pillar-spec.md 保持一致，改动须两边同步） ──
# 固定分类清单（category_slug 只能六选一，服务端对未知 slug 返 400）
CATEGORY_SLUGS = {
    "trauma-healing", "emotion-self", "relationships",
    "workplace", "overseas-students", "psych-101",
}
# 分类 slug → 中文分类名（R7/F1 判据：tag 不得与所选分类名重复）
CATEGORY_NAMES = {
    "trauma-healing": "创伤与疗愈",
    "emotion-self": "情绪与自我",
    "relationships": "亲密与家庭",
    "workplace": "职场心理",
    "overseas-students": "留学生心理",
    "psych-101": "心理科普",
}
# R7 两级敏感词与 R8 停用热线判据都在 shared/compliance_core.py（唯一真源），
# ⛔ 别在这里再抄一份词表——两边各存一份必漂，今天一致下次改了对面不知道。
# R9 锚文本黑名单（泛指代，出现即 fail）
ANCHOR_BLACKLIST = {"点击这里", "点此", "戳这里"}

DEFAULT_API_BASE = os.environ.get("NBDPSY_API_BASE", "https://database.nbdpsy.com")

# 内链形态（R9）——兼容本站绝对 URL 前缀 https?://(www.)?nbdpsy.com
RE_INTERNAL = re.compile(
    r"\]\((?:https?://(?:www\.)?nbdpsy\.com)?"
    r"(/blog/[a-z0-9][a-z0-9-]*|/services[^\s)]*|/counselors[^\s)]*)\)")
RE_BLOG_SLUG = re.compile(
    r"\]\((?:https?://(?:www\.)?nbdpsy\.com)?/blog/([a-z0-9][a-z0-9-]*)\)")
# markdown 链接锚文本（用于黑名单检测）
RE_ANCHOR = re.compile(r"\[([^\]\[]*)\]\(")
# markdown 表格分隔行（|---|---|）
RE_TABLE_SEP = re.compile(r"^\s*\|?[\s:\-|]*-{3,}[\s:\-|]*\|?\s*$")
RE_H1 = re.compile(r"^#\s")
RE_H2 = re.compile(r"^##(?!#)\s")
# 文内数字标注 [[n]](url)（preflight 自扫引用完整性用；不改 lint_markdown 的 RE_MARKER 契约）
RE_CITE = re.compile(r"\[\[(\d+)\]\]\((https?://[^)]+)\)")
# 正文 FAQ / 参考文献小节标题
RE_FAQ_H2 = re.compile(r"^##(?!#)\s*.*(?:FAQ|常见问题)", re.I)
RE_REFS_H2 = re.compile(r"^##(?!#)\s*参考文献")
# 正文 FAQ 段落里的问句行（**Q：** / ### Q： / Q1： 等形态）
RE_FAQ_Q = re.compile(r"^\s*(?:#{1,6}\s*)?\*{0,2}Q\d*\s*[：:]", re.I)


def _slug_ok(slug) -> bool:
    return isinstance(slug, str) and bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug))


def _hanzi(text: str) -> int:
    return len(re.findall(r"[一-龥]", text or ""))


def _norm_url(u) -> str:
    """URL 归一：两侧 strip、去末尾 /，用于引用标注 URL 与 citations 一致性比对。"""
    return (u or "").strip().rstrip("/") if isinstance(u, str) else ""


def _section_span(lines, head_re):
    """定位 head_re 匹配的 H2 小节 [start, end)（end=下一个 H2 或文末）；无匹配返回 None。"""
    start = next((i for i, l in enumerate(lines) if head_re.match(l)), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if RE_H2.match(lines[j])), len(lines))
    return start, end


def _trim_faq_refs(body: str) -> str:
    """截去正文 FAQ 小节与「## 参考文献」小节（R1 口径：正文字数不含 FAQ 与参考文献）。"""
    lines = body.splitlines()
    drop = set()
    for hr in (RE_FAQ_H2, RE_REFS_H2):
        span = _section_span(lines, hr)
        if span:
            drop.update(range(span[0], span[1]))
    return "\n".join(l for i, l in enumerate(lines) if i not in drop)


def _intro_first_para(body: str):
    """返回 (首个非空段落文本, H1→首 H2 之间整段文本)。
    有 H1（草稿态首行 `# 标题`）从 H1 之后取；无 H1（发布后正文首行 H1 已被剥）从正文起始取。
    首段=紧跟标题的第一段（连续非空行），是 R2 TL;DR 直答段的判据主体。"""
    lines = body.splitlines()
    h1 = next((i for i, l in enumerate(lines) if RE_H1.match(l)), None)
    start = h1 + 1 if h1 is not None else 0
    h2 = next((i for i in range(start, len(lines)) if RE_H2.match(lines[i])), len(lines))
    region = lines[start:h2]
    i = 0
    while i < len(region) and not region[i].strip():
        i += 1
    para = []
    while i < len(region) and region[i].strip():
        para.append(region[i])
        i += 1
    return "\n".join(para), "\n".join(region)


# ── R2-geo：开头段落的 GEO 结构原则（Princeton KDD 2024 受控实验）────────────
#
# 真源：`docs/secretary/调研-GEO打法可行性与方法论优化-20260825.md`（commit a2d5dea98）
# 证据：**Princeton KDD 2024，arXiv:2311.09735** 受控实验，被 AI 引擎引用率实测：
#   **加引用来源 +31% ／ 加统计数据 +31% ／ 加引述 +41%**；
#   ⚠️ 反例：**关键词堆砌是负收益 −8%~−10%** —— 顺带纠正一种常见做法。
# ⛔ 逐项写、**不压缩成区间**：区间只给「做了就涨」的模糊感，
#    逐项才告诉写作者「引用来源／统计数据／引述」是**三个分别有收益的动作**。
# 🩸 真源自己一度把三项压成「+28%~+41%」，而 28% 全文仅此一处、证据表里查无
#    ——**一个在证据表里查不到的数写进规格，下一个人核对时会发现对不上，
#    那时整条规格的可信度一起掉，比没有数字更糟**（2026-08-25 拦下，收口人已回改真源）。
#
# 🔴 **三条原则里只有两条能机检，第三条明说判不了**（⛔ 不混成一条含糊 warn）：
#   ① 首句给完整结论（⛔ 不铺垫、⛔ 不设问开场）      → 机检（下面两个正则）
#   ② 嵌入可验证参数（流程步数/响应时长/资质编号…）    → **机器判不了**，manual
#   ③ 去掉主观形容词                                   → 机检**自夸式那一类**
#
# ⚠️ ② 为什么判不了：机器能数出「4 步」是个数字，**⛔ 判不出它是不是真的、是不是可核**——
#    "3 步"与"很多步"的差别机器看得见，"3 步"与"7 步"哪个是事实机器看不见。
#    ⇒ 与本文件既有的 R3 数字真实性、R4 专家引语同档：**标 manual，绝不假装能测**。
RE_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.S)

#: 铺垫式开场。🩸 存量 88 篇实测校准过：初版含「很多人/不少人」，
#: 会误伤本站标准写法（`很多人以为创伤只来自车祸…但有一类创伤` 是**先破后立**、首句已给结论）。
#: ⇒ 只留**纯铺垫**句式（时代背景、话题引入），⛔ 不拦「很多人以为 X，但 Y」这种带转折的。
GEO_PADDING_OPEN = re.compile(
    r"^\s*(?:你是否|你有没有|有没有过|是不是也|想过吗|你可能|也许你|"
    r"在(?:当今|如今|这个|当下).{0,12}(?:社会|时代|年代)|"
    r"随着.{0,12}(?:的发展|的普及|的加快|的提高)|"
    r"说到.{0,10}[，,]|提起.{0,10}[，,])")
#: 设问开场：首句就是问句（40 字内出现 ？）
GEO_QUESTION_OPEN = re.compile(r"^[^。！？]{0,40}[？?]")
#: 🔴 **只反「自夸式」形容词**，⛔ 不禁一切程度词。
#: 🩸 存量实测校准：初版拿裸词表（完美/最好/极其/显著…）判，88 篇误伤 16 篇（18%）——
#:    而「要求你**完美**的声音」「最好的幕布」「**极其**隐蔽」都是**描述对象**的正当用词。
#:    ⇒ 原则反的是**夸我们自己**（服务/效果/团队），改成搭配式后误伤降到 1%。
GEO_BOAST = re.compile(
    r"(?:最(?:好|佳|强|专业|权威)的(?:选择|方案|方法|机构|平台|咨询)"
    r"|(?:业内|行业|国内|全网)(?:领先|顶尖|一流|第一)"
    r"|(?:非常|极其|十分)(?:专业|权威|有效|靠谱)"
    r"|(?:效果|疗效)(?:显著|惊人|卓越)"
    r"|(?:资深|顶尖|权威)(?:专家|团队|咨询师)团队?"
    r"|(?:完美|彻底)(?:解决|治愈|改善))")


def geo_open_issues(first_para: str):
    """开头段落的可机检问题。返回 [(码, 人话)]；空列表＝这两条过了。

    ⚠️ 调用方**必须先剥 frontmatter**（见 `geo_first_para`）——
    🩸 直接把发布态全文喂给 `_intro_first_para` 会把 YAML 当成首段，
    实测 88 篇里有 4 篇因此误报（抓到的"首段"是 `author_name: …`）。
    """
    s = (first_para or "").strip()
    out = []
    if GEO_PADDING_OPEN.match(s):
        out.append(("padding-open", "首句是铺垫式开场（时代背景/话题引入），⛔ 不是结论"))
    if GEO_QUESTION_OPEN.match(s):
        out.append(("question-open", "首句是设问开场——AI 引擎抓不到可引用的结论"))
    m = GEO_BOAST.search(s)
    if m:
        out.append(("boast-adj", f"开头段有自夸式形容词「{m.group(0)}」"))
    return out


def geo_first_para(md_text: str):
    """剥掉 frontmatter 再取首段（⛔ 别直接拿全文喂 `_intro_first_para`，见上）。"""
    return _intro_first_para(RE_FRONTMATTER.sub("", md_text, count=1))[0]


def _faq_body(body: str):
    """正文 FAQ 段：返回 (是否存在 FAQ/常见问题 H2 小节, 该节 Q 问句条数)。"""
    lines = body.splitlines()
    span = _section_span(lines, RE_FAQ_H2)
    if not span:
        return False, 0
    q = sum(1 for l in lines[span[0]:span[1]] if RE_FAQ_Q.match(l))
    return True, q


def _scan_units(meta, body):
    """产出 (定位标签, 文本) 序列供敏感词扫描：正文逐行 + 会随文上线的 frontmatter 字段
    （excerpt / meta_description / faq 各条 q,a）。frontmatter 字段用字段名定位（非行号）。"""
    units = [(f"行{i}", line) for i, line in enumerate(body.splitlines(), 1)]
    if isinstance(meta.get("excerpt"), str):
        units.append(("excerpt", meta["excerpt"]))
    if isinstance(meta.get("meta_description"), str):
        units.append(("meta_description", meta["meta_description"]))
    faq = meta.get("faq")
    if isinstance(faq, list):
        for i, item in enumerate(faq):
            if isinstance(item, dict):
                if item.get("q"):
                    units.append((f"faq[{i}].q", str(item["q"])))
                if item.get("a"):
                    units.append((f"faq[{i}].a", str(item["a"])))
    return units


def _blog_slug_exists(slug: str, api_base: str, timeout: int = 10):
    """联网校验 /blog/<slug> 是否真实存在。返回 True/False/None（None=网络失败，宽容）。"""
    import requests
    try:
        r = requests.get(f"{api_base}/api/public/blog/posts/{slug}", timeout=timeout,
                          headers={"User-Agent": "nbdpsy-preflight/1.0"})
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            return False
        return None
    except requests.RequestException:
        return None


def _tag_library(api_base: str, timeout: int = 10):
    """联网拉取现有标签库名集合；网络/解析失败返回 None（宽容跳过）。"""
    import requests
    try:
        r = requests.get(f"{api_base}/api/public/blog/tags", timeout=timeout,
                          headers={"User-Agent": "nbdpsy-preflight/1.0"})
        if r.status_code != 200:
            return None
        data = r.json()
        raw = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(raw, dict):
            raw = raw.get("tags", [])
        names = set()
        for t in raw or []:
            if isinstance(t, dict):
                nm = t.get("name") or t.get("slug")
                if nm:
                    names.add(str(nm))
            elif isinstance(t, str):
                names.add(t)
        return names
    except Exception:
        return None


def run(md_text: str, online: bool = False, api_base: str = DEFAULT_API_BASE):
    checks = []

    def add(cid, rule, status, detail, fix=None):
        c = {"id": cid, "rule": rule, "status": status, "detail": detail}
        if fix:
            c["fix"] = fix
        checks.append(c)

    # ── frontmatter 解析（失败则记 fail，仍继续跑纯文本类检查；正文剥掉 frontmatter 再扫） ──
    fm_ok = True
    try:
        meta, body = parse_frontmatter(md_text)
    except ValueError as e:
        fm_ok = False
        meta, body = {}, count_hanzi.strip_frontmatter(md_text)
        add("F0", "frontmatter", "fail", f"frontmatter 解析失败：{e}",
            "文件须以 `---` 开头的 YAML frontmatter 起始（见 pillar-spec「交付格式」）")

    # ===== R1 篇幅：纯汉字 4000–6000（截去正文 FAQ 与参考文献小节后计） =====
    n = _hanzi(_trim_faq_refs(body))
    if 4000 <= n <= 6000:
        add("R1", "word-count", "pass", f"正文纯汉字 {n}（区间 4000–6000，已截去 FAQ 与参考文献小节）")
    else:
        add("R1", "word-count", "fail",
            f"正文纯汉字 {n}，区间外（要求 4000–6000，已截去 FAQ 与参考文献小节）",
            "不足按缺口补真实内容（多一分论点/表/共情段），超出压缩低信息密度段落；不靠注水或砍参考文献凑数")

    # ===== R2 答案前置：H1 后首段 80–120 字直答（<80 fail；>120 warn；语义 manual） =====
    first_para, intro = _intro_first_para(body)
    fp = _hanzi(first_para)
    total_intro = _hanzi(intro)
    if fp >= 80:
        if fp <= 120:
            add("R2", "answer-first", "pass",
                f"H1 后首段直答约 {fp} 字（80–120）；语义质量无法机检——请人工确认这段能脱离上下文独立回答标题问题")
        else:
            add("R2", "answer-first", "warn",
                f"H1 后首段直答约 {fp} 字（>120，略长）；TL;DR 建议压到 80–120 字，AI 引用更爱抓紧凑的直答段",
                "把首段精简为 80–120 字、能独立回答标题问题的结论")
    else:
        if total_intro >= 80:
            add("R2", "answer-first", "fail",
                f"H1 后首段仅 {fp} 字（<80）不足以独立直答；H1 至首个 H2 共 {total_intro} 字但首段形态不合——"
                "TL;DR 须是紧跟标题的**单段** 80–120 字直答，不能拆成零碎短段",
                "在 H1 之后紧跟一段 80–120 字、能独立回答标题问题的结论（AI 引用最爱抓这段）")
        else:
            add("R2", "answer-first", "fail",
                f"H1 与首个 H2 之间仅 {total_intro} 字（要求 ≥80 的 TL;DR 直答段）",
                "在 H1 之后紧跟一段 80–120 字、能独立回答标题问题的结论（AI 引用最爱抓这段）")

    # ===== R2-geo 开头结构（Princeton KDD 2024 / arXiv:2311.09735）=====
    # 机检两条：首句非铺垫/非设问、无自夸式形容词。第三条「可验证参数」机器判不了 → manual。
    geo_first = geo_first_para(md_text)
    geo_bad = geo_open_issues(geo_first)
    if geo_bad:
        add("R2-geo", "geo-open-structure", "fail",
            "开头段落不合 GEO 结构原则：" + "；".join(m for _, m in geo_bad)
            + "。实测（arXiv:2311.09735 受控实验）首句给完整结论 + 嵌可验证参数 + 去主观形容词，"
              "被 AI 引擎引用率：加引用来源 +31%／加统计数据 +31%／加引述 +41%",
            "首句直接给完整结论（⛔ 不铺垫、⛔ 不设问），把自夸形容词换成可核对的具体值")
    else:
        add("R2-geo", "geo-open-structure", "pass",
            "开头段落：首句非铺垫/非设问、无自夸式形容词（机检两条过）")
    # 第三条**明说判不了**，⛔ 不混进上面那条含糊带过
    add("R2-geo", "geo-verifiable-params", "manual",
        "**可验证参数机器判不了**——能数出「4 步」是数字，⛔ 判不出它是否属实、是否可核。"
        "请人工确认开头段落嵌入了**能被核对的具体值**（流程步数／平均响应时长／资质编号／"
        "带出处的统计数字），⛔ 不是形容词。"
        "⚠️ 反例：**关键词堆砌是负收益 −8%~−10%**（同一受控实验）——⛔ 别靠塞关键词凑")

    # ===== R3 / 渲染合规：一次 lint 拿全部 violation（只喂正文，剥掉 frontmatter） =====
    citations = meta.get("citations") if isinstance(meta.get("citations"), list) else []
    cit_dicts = [c for c in citations if isinstance(c, dict)]
    cit_count = len(cit_dicts)
    violations, _cited = lint_markdown.lint(body, cit_count or None, stats_min=3)
    v_stat = [v for v in violations if v["rule"] == "stat-block"]
    v_bold = [v for v in violations if v["rule"] == "bold-flanking"]
    v_cite = [v for v in violations if v["rule"] == "citation-marker"]

    if v_stat:
        add("R3", "stat-block", "fail", v_stat[0]["text"], v_stat[0].get("fix"))
    else:
        add("R3", "stat-block", "pass",
            "带出处统计块 ≥3（数字+%/‰/倍/相关效应量，同行紧跟 [[n]](url)）；"
            "注意：本机只验统计形态与同行标注，**数字真实性须联网人工核实**（严禁编造数值/DOI/PMID）")

    # ===== 引用标注完整性（HIGH）：正文 [[n]](url) 的 n 须在界内、URL 须与 citations[n-1] 一致 =====
    # 用 raw citations（文末参考文献有序列表的真实序号）定界与取 URL，不用 dict 过滤后的列表（防序号错位）。
    ref_n = len(citations)
    oob, mism = [], []
    for m in RE_CITE.finditer(body):
        num = int(m.group(1))
        url = m.group(2)
        if num < 1 or num > ref_n:
            oob.append((num, url))
        else:
            entry = citations[num - 1]
            exp = entry.get("url") if isinstance(entry, dict) else None
            if _norm_url(url) != _norm_url(exp):
                mism.append((num, url, exp))
    if oob or mism:
        parts = []
        if oob:
            parts.append("编号越界：" + "；".join(f"[[{n1}]]（citations 仅 {ref_n} 条）" for n1, _ in oob))
        if mism:
            parts.append("URL 与 citations 不一致：" + "；".join(
                f"[[{n1}]] 标注 {u} ≠ citations[{n1}] {e}" for n1, u, e in mism[:8]))
        add("CITE-MATCH", "citation-integrity", "fail", "；".join(parts),
            "文内 [[n]](url)：n 须对应文末参考文献序号（1..N），URL 须与该条 citations 的 url 逐字一致")
    else:
        add("CITE-MATCH", "citation-integrity", "pass",
            "文内 [[n]](url) 标注编号均在界内，URL 与 frontmatter citations 一致")

    # ===== R4 专家引语：manual（列引号句计数供参考） =====
    quote_pairs = len(re.findall(r"[「“][^」”]{1,120}[」”]", body))
    add("R4", "expert-quote", "manual",
        f"正文含引号句约 {quote_pairs} 处（仅供参考）；需 ≥2 处**真实**专家原话/紧密转述且注明出处——"
        "真实性无法机检，请人工核对每条引语确出自已发表文献/公开演讲，绝不把虚构引语安到胡佰亿或任何咨询师名下")

    # ===== R5 FAQ：frontmatter faq 5–8 条，q/a 均非空 =====
    faq = meta.get("faq")
    if isinstance(faq, list):
        good = [x for x in faq if isinstance(x, dict) and x.get("q") and x.get("a")]
        if 5 <= len(good) <= 8:
            add("R5", "faq", "pass",
                f"FAQ {len(good)} 条（q/a 均非空，区间 5–8）；语义无法机检——Q 须用用户真实搜索短语、A 第一句直答，请人工确认")
        else:
            add("R5", "faq", "fail", f"有效 FAQ {len(good)} 条（要求 5–8，q/a 均非空；原始 {len(faq)} 条）",
                "文末补足 5–8 个 Q&A：Q 用用户真实搜索短语，A 第一句直答；frontmatter faq 与正文一致")
    else:
        add("R5", "faq", "fail", "frontmatter 缺 faq 数组（要求 5–8 条）",
            "在 frontmatter 加 faq: [{q,a}]，5–8 条，q/a 均非空")

    # ===== R5-body 正文 FAQ 段：须有「常见问题/FAQ」H2 且 Q 条数 == frontmatter faq 条数 =====
    has_faq_sec, q_count = _faq_body(body)
    faq_n = len(faq) if isinstance(faq, list) else 0
    if has_faq_sec and isinstance(faq, list) and faq_n > 0 and q_count == faq_n:
        add("R5-body", "faq-body-consistency", "pass",
            f"正文 FAQ 段 {q_count} 问，与 frontmatter faq {faq_n} 条数量一致；"
            "**Q/A 语义一致性**（同一批问题、A 首句直答）须人工核对")
    elif not has_faq_sec:
        add("R5-body", "faq-body-consistency", "fail",
            "正文缺少 FAQ 小节（H2『常见问题』或『FAQ』）——frontmatter faq 会渲染 FAQPage schema，正文也须有对应 Q&A 段",
            "正文补『## 常见问题』段，逐条 Q&A 与 frontmatter faq 一致（Q 用真实搜索短语、A 首句直答）")
    else:
        add("R5-body", "faq-body-consistency", "fail",
            f"正文 FAQ 段 {q_count} 问 ≠ frontmatter faq {faq_n} 条，两处须一一对应",
            "对齐正文『## 常见问题』段与 frontmatter faq 的条数与内容")

    # ===== R6 参考文献：≥6 条且每条含 http(s) URL；可达性 online 分级/否则 manual =====
    def _url_of(c):
        u = c.get("url") if isinstance(c, dict) else None
        return u if isinstance(u, str) and re.match(r"https?://", u) else None
    with_url = [c for c in citations if _url_of(c)]
    if len(with_url) >= 6:
        if online:
            import check_links
            dead, suspect, neterr = [], [], []
            for c in with_url:
                u = _url_of(c)
                st = check_links.probe(u, 10)
                if st is None:
                    neterr.append(u)
                elif st == 404 or (isinstance(st, int) and st >= 500):
                    dead.append(u)
                elif st in (401, 403, 429):
                    suspect.append(u)
            notes = ""
            if suspect:
                notes += f"；{len(suspect)} 条疑似反爬(401/403/429，人工确认)"
            if neterr:
                notes += f"；{len(neterr)} 条联网失败(网络问题，人工确认)"
            if dead:
                add("R6", "citations", "fail",
                    f"参考文献 {len(with_url)} 条，{len(dead)} 条死链(404/5xx)：{dead}{notes}",
                    "逐条打开网页确认可达且口径正确；死链换权威源")
            elif suspect or neterr:
                add("R6", "citations", "warn",
                    f"参考文献 {len(with_url)} 条，联网抽测无 404/5xx 死链{notes}",
                    "对反爬/联网失败的条目逐条人工打开确认可达且口径正确")
            else:
                add("R6", "citations", "pass",
                    f"参考文献 {len(with_url)} 条（≥6，均含 URL），联网抽测无死链；语义口径仍须逐条打开网页核实")
        else:
            add("R6", "citations", "pass",
                f"参考文献 {len(with_url)} 条（≥6，均含 http(s) URL）；"
                "可达性与口径正确性无法机检（manual）——加 --online 分级抽测可达性，语义口径仍须逐条打开网页核实")
    else:
        add("R6", "citations", "fail",
            f"含 URL 的参考文献仅 {len(with_url)} 条（要求 ≥6，且每条含 http(s) URL；原始 {len(citations)} 条）",
            "补足真实可点参考文献（DSM-5-TR/ICD-11 官方页、PubMed/DOI、权威机构指南），逐条网络核实后写入")

    # ===== R7 敏感词两级（扫描域含正文 + 会上线的 frontmatter 字段） =====
    units = _scan_units(meta, body)
    # 判据全部来自 compliance_core：绝对化词 fatal、医疗口径词 warning、
    # 「最有效」同单元含 [[n]](url) 视为文献转述豁免——三条都在模块里，此处只做展示。
    # crisis_scope="skip"：R8 的三要素在位另按**正文**判（见下方 R8 段），
    # ⛔ 不能把 excerpt/faq 里的 12356 算成正文有声明。
    core = compliance_core.check(units, crisis_scope="skip")
    abs_hits = [h for h in core["fatal"] if h["rule"] == "R7-abs"]
    warn_hits = [h for h in core["warnings"] if h["rule"] == "R7-med"]
    if abs_hits:
        add("R7-abs", "sensitive-absolute", "fail",
            "命中绝对化/夸大红线词：" + "；".join(f"{h['word']}({h['loc']})" for h in abs_hits),
            # ⛔ 词表从 compliance_core 现取，别在这里手写一遍——手写的帮助文案不会
            # 跟着词表更新，日后 core 加了词，这行还在教人只防旧的那几个（漂的是人不是代码）。
            "删除或改写——禁「" + "/".join(compliance_core.ABSOLUTE_WORDS) + "」等绝对化承诺"
            "（『最有效』仅在同行有 [[n]](url) 文献转述时豁免）")
    else:
        add("R7-abs", "sensitive-absolute", "pass", "无绝对化/夸大红线词")
    if warn_hits:
        add("R7-med", "sensitive-medical", "warn",
            "出现医疗口径词（学术转述可人工豁免）：" + "；".join(f"{h['word']}({h['loc']})" for h in warn_hits[:20]),
            "若在描述本工作室服务须改「咨询/干预/评估/陪伴」；仅学术名词/文献转述（PTSD/CBT/EMDR）可保留")
    else:
        add("R7-med", "sensitive-medical", "pass", "无医疗口径敏感词")

    # ===== R8 危机声明：须含 12356 + 不构成医疗建议；停用热线回流即 fail；缺 010-82951332 仅 warn =====
    CRISIS_FIX = ("文末固定加：本文不构成医疗建议；如处于心理危机请拨打全国统一心理援助热线 12356 "
                  "或北京心理危机研究与干预中心热线 010-82951332（24小时）；紧急情况拨打 110/120")
    # 三要素在位 + 停用热线回流都判**正文**：故单喂一个 ("正文", body) 单元走
    # crisis_scope="joined"。⛔ 不复用上面那次 check(units)——那批含 frontmatter
    # excerpt/faq，把它们算进危机声明会让「摘要里提了 12356」冒充「正文有声明」。
    # 停用热线的逐行「同行」语义由 compliance_core 内部保证（整段喂也按行判）。
    crisis_core = compliance_core.check([("正文", body)], crisis_scope="joined")
    cr = crisis_core["crisis"]
    dead_hits = [h for h in crisis_core["fatal"] if h["rule"] == "R8-dead-hotline"]
    if dead_hits:
        add("R8", "crisis-statement", "fail", compliance_core.DEAD_HOTLINE_DETAIL, CRISIS_FIX)
    elif cr["missing"]:
        add("R8", "crisis-statement", "fail", "危机声明缺要素：" + "、".join(cr["missing"]), CRISIS_FIX)
    elif not cr["has_bj_hotline"]:
        add("R8", "crisis-statement", "warn",
            "危机声明缺北京心理危机研究与干预中心热线 010-82951332（24小时）——12356 官方口径为每日≥18小时，不可标注 24 小时",
            CRISIS_FIX)
    else:
        add("R8", "crisis-statement", "pass",
            "危机声明要素在位（12356 + 010-82951332 + 不构成医疗建议）")

    # ===== R9 内链：/blog/、/services、/counselors 计 2–4 + 锚文本黑名单 =====
    internal = RE_INTERNAL.findall(body)
    ic = len(internal)
    bad_anchor = sorted({a.strip() for a in RE_ANCHOR.findall(body) if a.strip() in ANCHOR_BLACKLIST})
    probs = []
    if not (2 <= ic <= 4):
        probs.append(f"站内链接 {ic} 处，区间外（要求 2–4：/blog/{{slug}}、/services/*、/counselors，兼容本站绝对 URL）")
    if bad_anchor:
        probs.append(f"命中锚文本黑名单 {bad_anchor}（禁泛指代，锚文本须用精确关键词）")
    r9_status = "fail" if probs else "pass"
    r9_detail = "；".join(probs) if probs else \
        f"站内链接 {ic} 处（区间 2–4），锚文本无黑名单词；锚文本须用**精确关键词**（非「点击这里」），人工确认相关性"
    if online and ic:
        missing, neterr = [], []
        for slug in set(RE_BLOG_SLUG.findall(body)):
            ex = _blog_slug_exists(slug, api_base)
            if ex is False:
                missing.append(slug)
            elif ex is None:
                neterr.append(slug)
        if missing:  # slug 不存在=真缺陷
            r9_status = "fail"
            r9_detail += f"；/blog/ 目标 slug 不存在：{missing}"
        if neterr:
            r9_detail += f"；{len(neterr)} 个 slug 联网校验失败（网络问题，人工确认）"
    add("R9", "internal-links", r9_status, r9_detail,
        None if r9_status == "pass" else
        "锚文本用精确关键词（禁「点击这里/点此/戳这里」），自然嵌 2–4 处站内链接，与相邻 pillar 交叉内链")

    # ===== R10 结构：H2 ≥4 + 对比表（段落长度另作 warn 级软判据） =====
    lines = body.splitlines()
    h2_count = sum(1 for l in lines if RE_H2.match(l))
    has_table = any(RE_TABLE_SEP.match(l) and "-" in l and l.count("|") >= 1 for l in lines)
    if h2_count >= 4 and has_table:
        add("R10", "structure", "pass",
            f"H2 {h2_count} 个（≥4），含 markdown 对比表；H2 须用**用户真实搜索短语**作小标题（语义无法机检，人工确认）")
    else:
        probs = []
        if h2_count < 4:
            probs.append(f"H2 仅 {h2_count} 个（要求 ≥4，用用户搜索短语作小标题）")
        if not has_table:
            probs.append("缺 markdown 对比表（至少一张，如 PTSD vs CPTSD）")
        add("R10", "structure", "fail", "；".join(probs), "补足 H2 小标题与至少一张对比表格")
    # 段落 ≤150 字（软判据，warn 级——长段落受 markdown 行结构影响且存量普遍，硬拦会误伤）
    long_paras = [i for i, l in enumerate(lines, 1)
                  if not l.startswith(("#", "|", ">", "-", "*", "```")) and _hanzi(l) > 150]
    if long_paras:
        add("R10-para", "paragraph-length", "warn",
            f"{len(long_paras)} 个段落超 150 字（行号 {long_paras[:10]}）",
            "手机竖屏可读性：拆分长段落到 ≤150 字（建议级，非硬拦）")

    # ===== F1 frontmatter 完备（逐字段） =====
    if fm_ok:
        title = meta.get("title")
        if isinstance(title, str) and title.strip() and len(title) <= 30:
            add("F1-title", "fm-title", "pass", f"title 长度 {len(title)}（≤30）")
        else:
            add("F1-title", "fm-title", "fail",
                f"title 缺失或超长（当前 {len(title) if isinstance(title, str) else 'None'}，要求非空且 ≤30 字）",
                "title 为 H1、≤30 字、含核心关键词")

        slug = meta.get("slug")
        if _slug_ok(slug):
            add("F1-slug", "fm-slug", "pass", f"slug={slug}（ASCII 连字符）")
        else:
            add("F1-slug", "fm-slug", "fail", f"slug 非法：{slug!r}（须小写 ASCII + 连字符分隔）",
                "slug 用拼音 ASCII，仅小写字母/数字/连字符，如 fuzaxing-chuangshang-cptsd")

        excerpt = meta.get("excerpt")
        if isinstance(excerpt, str) and excerpt.strip() and len(excerpt) <= 150:
            add("F1-excerpt", "fm-excerpt", "pass", f"excerpt 长度 {len(excerpt)}（≤150）")
        else:
            add("F1-excerpt", "fm-excerpt", "fail",
                f"excerpt 缺失或超 150 字（当前 {len(excerpt) if isinstance(excerpt, str) else 'None'}）",
                "excerpt ≤150 字摘要")

        md = meta.get("meta_description")
        if isinstance(md, str) and 120 <= len(md) <= 160:
            add("F1-meta_description", "fm-meta-desc", "pass", f"meta_description 长度 {len(md)}（120–160）")
        else:
            add("F1-meta_description", "fm-meta-desc", "fail",
                f"meta_description 长度 {len(md) if isinstance(md, str) else 'None'}（要求 120–160 字）",
                "meta_description 写 120–160 字，含长尾词 + 直接回答句")

        cat = meta.get("category_slug")
        if cat in CATEGORY_SLUGS:
            add("F1-category", "fm-category", "pass", f"category_slug={cat}")
        else:
            add("F1-category", "fm-category", "fail",
                f"category_slug={cat!r} 不在固定六分类内",
                f"从固定清单六选一：{sorted(CATEGORY_SLUGS)}（勿自造，服务端 400）")

        tags = meta.get("tags")
        if isinstance(tags, list) and 3 <= len(tags) <= 6 and all(
                isinstance(t, str) and "#" not in t for t in tags):
            add("F1-tags", "fm-tags", "pass", f"tags {len(tags)} 个（3–6，无 #）")
        else:
            bad = "非列表/数量越界/含 #" if not (isinstance(tags, list)) else \
                  ("含 # 号" if any(isinstance(t, str) and "#" in t for t in tags) else f"数量 {len(tags)} 越界")
            add("F1-tags", "fm-tags", "fail", f"tags 不合规（{bad}）：{tags!r}",
                "tags 3–6 个中文名词短语，不带 #（那是小红书写法），优先复用现有标签库")

        # F1-tag-category：tag 不得与所选分类名重复（分类已承载的词不必再打成标签）
        cat_name = CATEGORY_NAMES.get(cat)
        if isinstance(tags, list) and cat_name:
            dup = [t for t in tags if isinstance(t, str) and t.strip() == cat_name]
            if dup:
                add("F1-tag-category", "fm-tag-category-dup", "fail",
                    f"tag 与所选分类名『{cat_name}』重复：{dup}",
                    "去掉与分类名重复的 tag，换更细粒度的主题/人群/方法词")
            else:
                add("F1-tag-category", "fm-tag-category-dup", "pass", "tags 未与分类名重复")

        tk = meta.get("target_keywords")
        if isinstance(tk, list) and any(isinstance(x, str) and x.strip() for x in tk):
            add("F1-target_keywords", "fm-target-kw", "pass", f"target_keywords {len(tk)} 个")
        else:
            add("F1-target_keywords", "fm-target-kw", "fail", f"target_keywords 缺失或空：{tk!r}",
                "target_keywords 列主词 + 长尾词（指导撰写，不入库但必填）")

        author = meta.get("author_name")
        if isinstance(author, str) and author.strip():
            add("F1-author", "fm-author", "pass", f"author_name={author}")
        else:
            add("F1-author", "fm-author", "fail", "author_name 缺失",
                "author_name 默认胡佰亿（真人署名）")

        # F1-internal_links：缺失 warn（仅指导撰写，不入库）
        il = meta.get("internal_links")
        if isinstance(il, list) and il:
            add("F1-internal_links", "fm-internal-links", "pass", f"internal_links {len(il)} 条")
        else:
            add("F1-internal_links", "fm-internal-links", "warn",
                "frontmatter 缺 internal_links（仅指导撰写、不入库；建议列 2–4 条内链关键词→URL 与正文内链对齐）",
                "补 internal_links: [{keyword, url}]")

        # F1-h1：正文首行须为 `# {title}` 且与 title 一致（publish_post 剥首行 H1 依赖此约定）
        first_line = body.lstrip("\n").split("\n", 1)[0] if body.strip() else ""
        if RE_H1.match(first_line) and isinstance(title, str):
            h1_text = first_line.lstrip("#").strip()
            if h1_text == title.strip():
                add("F1-h1", "body-h1-title", "pass", "正文首行为 `# {title}`，与 frontmatter title 一致")
            else:
                add("F1-h1", "body-h1-title", "fail",
                    f"正文首行 H1『{h1_text}』与 frontmatter title『{title}』不一致",
                    "正文首行改为 `# {title}`（与 frontmatter title 逐字一致）")
        else:
            add("F1-h1", "body-h1-title", "fail",
                "正文首行不是 `# {title}` 形态——publish_post 发布时剥首行 H1 依赖此约定，缺失会误剥正文首行",
                "正文首行写 `# {title}`，与 frontmatter title 逐字一致")

        # ===== F2 标签规则：至少 1 个 tag 命中 target_keywords（warn 级） =====
        if isinstance(tags, list) and isinstance(tk, list) and tags and tk:
            tset = [t for t in tags if isinstance(t, str)]
            kset = [k for k in tk if isinstance(k, str)]
            hit = any(t == k or t in k or k in t for t in tset for k in kset)
            if hit:
                add("F2", "tag-keyword-align", "pass", "至少 1 个 tag 与 target_keywords 对齐")
            else:
                add("F2", "tag-keyword-align", "warn",
                    "无 tag 命中 target_keywords（标签页是长尾词聚合着陆面，建议至少 1 个对齐）",
                    "让 3–6 个 tag 里至少 1 个取自 target_keywords 的核心长尾词")

        # F1-tags-lib（online）：抽查 tags 命中现有标签库比例，0 命中 → warn（疑似全新造词/同义分裂）
        if online and isinstance(tags, list) and tags:
            lib = _tag_library(api_base)
            if lib is not None:
                hits = [t for t in tags if isinstance(t, str) and t in lib]
                if not hits:
                    add("F1-tags-lib", "fm-tags-library", "warn",
                        f"{len(tags)} 个 tag 全部未命中现有标签库（疑似全新造词——确认非同义分裂，"
                        "同义概念须复用库里原词，如已有「自我关怀」勿再造「自我照顾」）",
                        "对照 /api/public/blog/tags，同义 tag 改用库中原词，仅真新概念才新造")

    # ===== 渲染合规：bold-flanking + citation-marker（复用 lint） =====
    if v_bold:
        add("RENDER-bold", "bold-flanking", "fail",
            f"{len(v_bold)} 处中文加粗侧翼违规（首例行{v_bold[0]['line']}: {v_bold[0]['text']}）",
            v_bold[0].get("fix"))
    else:
        add("RENDER-bold", "bold-flanking", "pass", "无中文加粗侧翼违规")
    if cit_count:
        if v_cite:
            add("RENDER-cite", "citation-marker", "fail", v_cite[0]["text"], v_cite[0].get("fix"))
        else:
            add("RENDER-cite", "citation-marker", "pass",
                f"文内 [[n]](url) 标注覆盖全部 {cit_count} 条参考文献")

    # ── 汇总 ──
    counts = {"pass": 0, "fail": 0, "warn": 0, "manual": 0}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    ok = counts["fail"] == 0
    summary = (f"{counts['pass']} pass / {counts['fail']} fail / "
               f"{counts['warn']} warn / {counts['manual']} manual")
    return {"ok": ok, "summary": summary, "checks": checks}


def main():
    ap = argparse.ArgumentParser(description="Pillar 长文发布前统一预检")
    ap.add_argument("file")
    ap.add_argument("--online", action="store_true",
                    help="联网校验 R6 参考文献可达性(死链 fail/反爬·网络失败 warn) + R9 内链 slug 存在性 + F1 tags 标签库")
    ap.add_argument("--api-base", default=DEFAULT_API_BASE, help="公开 API 基址（默认生产）")
    a = ap.parse_args()
    path = Path(a.file)
    if not path.is_file():
        print(json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False))
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(2)
    result = run(path.read_text(encoding="utf-8"), online=a.online, api_base=a.api_base)
    # 人类可读摘要走 stderr，stdout 保持纯 JSON
    for c in result["checks"]:
        if c["status"] != "pass":
            mark = {"fail": "✗", "warn": "!", "manual": "?"}[c["status"]]
            print(f"  {mark} [{c['id']} {c['rule']}] {c['detail']}", file=sys.stderr)
    warn_n = sum(1 for c in result["checks"] if c["status"] == "warn")
    if result["ok"]:
        head = "✓ 全绿" if warn_n == 0 else f"✓ 无 fail（{warn_n} 个 warn 待人工裁决）"
    else:
        head = "✗ 有 fail"
    print(f"{head} — {result['summary']}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()

"""preflight.py 发布前统一管道测试。

构造最小合格文档（全绿）与逐项违规文档；每条 R 规则至少一例 fail/warn 断言。
不测 --online（联网路径不在单测范围）。
"""
import json
import subprocess
import sys
import copy
from pathlib import Path

import yaml

SCRIPT = Path(__file__).parent.parent / "nbdpsy-seo-artical-creator" / "scripts" / "preflight.py"

# ── 合格 frontmatter（各字段刚好达标） ──
GOOD_META = {
    "title": "恋爱脑是什么意思依恋理论解读",          # ≤30
    "slug": "lianainao-yilian-jiedu",              # ASCII 连字符
    "excerpt": "从依恋理论解释谈恋爱就失去自我的心理机制，以及可以开始的自我调节步骤。",  # ≤150
    "meta_description": (
        "恋爱脑不是道德问题而是依恋系统的过度激活。本文用依恋理论解释谈恋爱就失去自我的心理成因，"
        "系统对比焦虑型与回避型依恋在亲密关系中的不同表现，并给出可操作的自我调节练习与关系修复步骤，"
        "帮助你在爱一个人的同时也不弄丢自己，重新在关系里找回稳定的自我边界与安全感。"
    ),  # 120–160 字
    "category_slug": "relationships",
    "tags": ["依恋", "情绪内耗", "自我关怀"],          # 3–6，无 #
    "target_keywords": ["恋爱脑怎么办", "自我关怀"],    # 含 tag「自我关怀」→ F2 命中
    "author_name": "胡佰亿",
    "internal_links": [
        {"keyword": "依恋修复", "url": "/blog/yilian-xiufu"},
        {"keyword": "咨询服务", "url": "/services/qinmi"},
    ],
    "citations": [
        {"title": f"来源{i}", "url": f"https://ref{i}.example.com/x", "source": f"机构{i} 2024"}
        for i in range(1, 7)
    ],  # 6 条，均含 URL
    "faq": [{"q": f"问题{i}", "a": f"回答{i}"} for i in range(1, 6)],  # 5 条
}

TLDR = (
    "恋爱脑指的是一进入亲密关系就把对方当成全部、不断为对方让渡自我边界的状态。"
    "它的根源往往不是意志力薄弱，而是早年依恋经验塑造出来的情绪反应模式，"
    "理解这一点是开始改变的第一步，也是本文要讲清楚的核心。"
)

STAT_BLOCK = (
    "研究显示约 68.0% 的人在关系中报告过类似的自我丧失感 [[1]](https://ref1.example.com/x)。\n"
    "一项干预数据表明调节练习后满意度提升约 74.0% [[2]](https://ref2.example.com/x)。\n"
    "焦虑型个体的分手复合率约为对照组的 2 倍 [[3]](https://ref3.example.com/x)。\n"
)

TABLE = "| 依恋类型 | 关系中表现 | 调节方向 |\n|---|---|---|\n| 焦虑型 | 过度靠近 | 自我安抚 |\n| 回避型 | 情感疏离 | 允许亲近 |\n"

LINKS = "延伸了解可看 [咨询服务](/services/qinmi) 与 [咨询师团队](/counselors)，也可读 [相关长文](/blog/yilian-xiufu)。\n"

CRISIS = "本文不构成医疗建议；如处于心理危机请拨打希望24热线 4001619995 或全国统一心理援助热线 12356。\n"

# 一句约 40 汉字的填充句（≤150，避免 R10-para warn）
FILLER = "在亲密关系里学会辨识自己的情绪并练习用更温和的方式照顾内在的需要是一个需要耐心和反复练习的漫长过程\n"


def build_faq_section(n=5):
    """正文『## 常见问题』段（R5-body 判据：Q 条数须与 frontmatter faq 一致）。"""
    parts = ["## 常见问题\n"]
    for i in range(1, n + 1):
        parts.append(f"**Q：问题{i}**\nA：回答{i}\n")
    return "\n".join(parts)


def build_body(*, tldr=True, stats=True, table=True, crisis=True, crisis_text=CRISIS,
               links=LINKS, markers456=True, prepend="", h1=True, faq_section=True, faq_q=5):
    parts = []
    if h1:
        parts.append("# 恋爱脑是什么意思依恋理论解读\n")
    if tldr:
        parts.append(TLDR + "\n")
    if prepend:  # 违规注入段：放在 TLDR 之后，不冲掉首段直答判据
        parts.append(prepend + "\n")
    parts.append("## 恋爱脑的心理成因\n")
    if stats:
        parts.append(STAT_BLOCK)
    else:
        # 有引用标注但无统计数字（R3 失守形态）
        parts.append("这种现象在临床观察中很常见 [[1]](https://ref1.example.com/x)。\n"
                     "很多人都经历过类似的挣扎 [[2]](https://ref2.example.com/x)。\n"
                     "理解它需要一些时间 [[3]](https://ref3.example.com/x)。\n")
    if table:
        parts.append(TABLE)
    parts.append(links)
    parts.append("## 焦虑型与回避型的区别\n理论支持见文献 [[4]](https://ref4.example.com/x)。\n")
    parts.append("## 如何重新找回自己\n综述指出该模式可调节 [[5]](https://ref5.example.com/x)。\n" if markers456
                 else "## 如何重新找回自己\n综述指出该模式可调节。\n")
    parts.append("## 常见误区\n历史研究亦有记载 [[6]](https://ref6.example.com/x)。\n" if markers456
                 else "## 常见误区\n历史研究亦有记载。\n")
    parts.append("## 延伸阅读\n")
    parts.extend([FILLER] * 80)  # 约 3900 汉字，凑够 R1 区间
    if faq_section:
        parts.append(build_faq_section(faq_q))  # R1 计数会截去本段
    if crisis:
        parts.append("## 结语与提醒\n" + crisis_text)
    return "\n".join(parts)


def build_doc(meta_overrides=None, **body_kwargs):
    meta = copy.deepcopy(GOOD_META)
    if meta_overrides:
        for k, v in meta_overrides.items():
            if v is _DELETE:
                meta.pop(k, None)
            else:
                meta[k] = v
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    return f"---\n{fm}---\n\n{build_body(**body_kwargs)}"


_DELETE = object()


def run(doc, tmp_path):
    f = tmp_path / "draft.md"
    f.write_text(doc, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    return r, json.loads(r.stdout)


def status_of(data, cid):
    return next((c["status"] for c in data["checks"] if c["id"] == cid), None)


# ========== 最小合格文档：全绿 ==========

def test_good_doc_passes_all(tmp_path):
    r, d = run(build_doc(), tmp_path)
    assert d["ok"] is True and r.returncode == 0, d["summary"]
    # 无任何 fail
    assert not [c for c in d["checks"] if c["status"] == "fail"], \
        [c["id"] for c in d["checks"] if c["status"] == "fail"]


def test_good_doc_r1_in_range(tmp_path):
    _, d = run(build_doc(), tmp_path)
    assert status_of(d, "R1") == "pass"


# ========== 逐项违规 ==========

def test_r1_too_short_fails(tmp_path):
    doc = build_doc()
    # 砍掉填充段落 → 汉字不足
    doc = doc.replace(FILLER, "", 79)
    r, d = run(doc, tmp_path)
    assert status_of(d, "R1") == "fail" and r.returncode == 1


def test_r2_missing_tldr_fails(tmp_path):
    _, d = run(build_doc(tldr=False), tmp_path)
    assert status_of(d, "R2") == "fail"


def test_r3_cited_but_no_stats_fails(tmp_path):
    _, d = run(build_doc(stats=False), tmp_path)
    assert status_of(d, "R3") == "fail"


def test_r5_faq_too_few_fails(tmp_path):
    _, d = run(build_doc({"faq": [{"q": "a", "a": "b"}]}), tmp_path)
    assert status_of(d, "R5") == "fail"


def test_r6_too_few_citations_fails(tmp_path):
    few = [{"title": "t", "url": "https://x.example.com", "source": "s"} for _ in range(4)]
    _, d = run(build_doc({"citations": few}), tmp_path)
    assert status_of(d, "R6") == "fail"


def test_r6_citation_without_url_fails(tmp_path):
    no_url = [{"title": f"t{i}", "source": "s"} for i in range(6)]
    _, d = run(build_doc({"citations": no_url}), tmp_path)
    assert status_of(d, "R6") == "fail"


def test_r7_absolute_word_fails(tmp_path):
    _, d = run(build_doc(prepend="我们的咨询能根治所有心理问题。"), tmp_path)
    assert status_of(d, "R7-abs") == "fail"


def test_r7_medical_word_warns_not_fail(tmp_path):
    # 医疗口径词只 warn，不拦发布
    r, d = run(build_doc(prepend="有来访者曾在医院就诊。"), tmp_path)
    assert status_of(d, "R7-med") == "warn"
    assert status_of(d, "R7-abs") == "pass"


def test_r8_missing_crisis_fails(tmp_path):
    _, d = run(build_doc(crisis=False), tmp_path)
    assert status_of(d, "R8") == "fail"


def test_r9_too_few_links_fails(tmp_path):
    _, d = run(build_doc(links="仅一个 [服务](/services/a)。\n"), tmp_path)
    assert status_of(d, "R9") == "fail"


def test_r9_too_many_links_fails(tmp_path):
    many = ("[a](/services/a) [b](/counselors) [c](/blog/x) "
            "[d](/blog/y) [e](/services/b)。\n")
    _, d = run(build_doc(links=many), tmp_path)
    assert status_of(d, "R9") == "fail"


def test_r10_no_table_fails(tmp_path):
    _, d = run(build_doc(table=False), tmp_path)
    assert status_of(d, "R10") == "fail"


# ---- frontmatter 校验 ----

def test_f1_bad_category_fails(tmp_path):
    _, d = run(build_doc({"category_slug": "not-a-real-category"}), tmp_path)
    assert status_of(d, "F1-category") == "fail"


def test_f1_meta_description_too_short_fails(tmp_path):
    _, d = run(build_doc({"meta_description": "太短了"}), tmp_path)
    assert status_of(d, "F1-meta_description") == "fail"


def test_f1_tags_too_many_fails(tmp_path):
    _, d = run(build_doc({"tags": ["a", "b", "c", "d", "e", "f", "g"]}), tmp_path)
    assert status_of(d, "F1-tags") == "fail"


def test_f1_tags_with_hash_fails(tmp_path):
    _, d = run(build_doc({"tags": ["#依恋", "情绪", "自我关怀"]}), tmp_path)
    assert status_of(d, "F1-tags") == "fail"


def test_f1_title_too_long_fails(tmp_path):
    _, d = run(build_doc({"title": "这是一个远远超过三十个字上限的超长标题" * 3}), tmp_path)
    assert status_of(d, "F1-title") == "fail"


def test_f1_bad_slug_fails(tmp_path):
    _, d = run(build_doc({"slug": "中文Slug_不合法"}), tmp_path)
    assert status_of(d, "F1-slug") == "fail"


# ---- F2 标签对齐（warn 级） ----

def test_f2_no_tag_in_keywords_warns(tmp_path):
    _, d = run(build_doc({"tags": ["甲", "乙", "丙"],
                          "target_keywords": ["完全不相关的词"]}), tmp_path)
    assert status_of(d, "F2") == "warn"
    # warn 不拦发布：其余全绿时 ok 仍为 True
    assert d["ok"] is True


# ---- 渲染合规 ----

def test_render_bold_flanking_fails(tmp_path):
    # 闭合 ** 后紧跟正文（生产事故形态）
    _, d = run(build_doc(prepend="这是重点。**紧跟正文不换行会渲染成裸星号。"), tmp_path)
    assert status_of(d, "RENDER-bold") == "fail"


def test_render_citation_marker_missing_fails(tmp_path):
    # 参考文献 6 条但正文只标了 1..3（4/5/6 缺）
    _, d = run(build_doc(markers456=False), tmp_path)
    assert status_of(d, "RENDER-cite") == "fail"


# ---- 引用标注完整性（CITE-MATCH，HIGH） ----

def test_citation_marker_out_of_bounds_fails(tmp_path):
    # citations 6 条，但正文出现 [[9]](url) 越界
    _, d = run(build_doc(prepend="越界标注见此 [[9]](https://ref9.example.com/x)。"), tmp_path)
    assert status_of(d, "CITE-MATCH") == "fail"


def test_citation_marker_url_mismatch_fails(tmp_path):
    # [[2]] 指向的 URL 与 citations[1].url 不一致
    _, d = run(build_doc(prepend="数据见此 [[2]](https://wrong.example.com/zzz)。"), tmp_path)
    assert status_of(d, "CITE-MATCH") == "fail"


def test_citation_markers_consistent_passes(tmp_path):
    _, d = run(build_doc(), tmp_path)
    assert status_of(d, "CITE-MATCH") == "pass"


# ---- R8 危机声明三要素 ----

CRISIS_NO_NUMBER = "本文不构成医疗建议；如处于心理危机请拨打全国统一心理援助热线 12356。\n"      # 无 4001619995/希望24
CRISIS_NO_DISCLAIMER = "如处于心理危机请拨打希望24热线 4001619995 或全国统一心理援助热线 12356。\n"  # 无免责句
CRISIS_NO_12356 = "本文不构成医疗建议；如处于心理危机请拨打希望24热线 4001619995。\n"                # 无 12356


def test_r8_missing_hotline_number_fails(tmp_path):
    _, d = run(build_doc(crisis_text=CRISIS_NO_NUMBER), tmp_path)
    assert status_of(d, "R8") == "fail"


def test_r8_missing_disclaimer_fails(tmp_path):
    _, d = run(build_doc(crisis_text=CRISIS_NO_DISCLAIMER), tmp_path)
    assert status_of(d, "R8") == "fail"


def test_r8_missing_12356_fails(tmp_path):
    _, d = run(build_doc(crisis_text=CRISIS_NO_12356), tmp_path)
    assert status_of(d, "R8") == "fail"


# ---- R7 扫描域扩到 frontmatter + 「最有效」豁免 ----

def test_r7_faq_absolute_word_fails(tmp_path):
    # 绝对化红线词藏在 frontmatter faq 里（会随文上线）也要拦住
    bad_faq = [{"q": "能根治吗", "a": "我们保证根治所有心理问题"}] + \
              [{"q": f"问题{i}", "a": f"回答{i}"} for i in range(2, 6)]
    _, d = run(build_doc({"faq": bad_faq}), tmp_path)
    assert status_of(d, "R7-abs") == "fail"


def test_r7_zuiyouxiao_with_marker_exempt(tmp_path):
    # 「最有效」同行含 [[n]](url) 文献转述 → 豁免，不 fail
    _, d = run(build_doc(prepend="一项综述称这是最有效的干预之一 [[1]](https://ref1.example.com/x)。"), tmp_path)
    assert status_of(d, "R7-abs") == "pass"


def test_r7_zuiyouxiao_without_marker_fails(tmp_path):
    # 「最有效」无文献标注 → fail
    _, d = run(build_doc(prepend="我们的方案是最有效的。"), tmp_path)
    assert status_of(d, "R7-abs") == "fail"


# ---- R9 锚文本黑名单 + 本站绝对 URL 内链 ----

def test_r9_blacklist_anchor_fails(tmp_path):
    _, d = run(build_doc(links="想了解更多请 [点击这里](/services/a) 或看 [咨询师](/counselors)。\n"), tmp_path)
    assert status_of(d, "R9") == "fail"


def test_r9_absolute_site_links_counted(tmp_path):
    links = ("详见 [依恋修复](https://www.nbdpsy.com/blog/yilian-xiufu) 与 "
             "[咨询服务](https://nbdpsy.com/services/qinmi) 及 [咨询师团队](/counselors)。\n")
    _, d = run(build_doc(links=links), tmp_path)
    assert status_of(d, "R9") == "pass"


# ---- R2 首段判据校正 ----

def test_r2_no_h1_direct_answer_passes(tmp_path):
    # 正文首行直接是 ≥80 字直答段（无 # 标题行，如 fetch 产物）→ R2 pass
    body = "甲" * 100 + "\n\n## 小节标题\n正文内容。\n"
    fm = yaml.safe_dump(GOOD_META, allow_unicode=True, sort_keys=False)
    _, d = run(f"---\n{fm}---\n\n{body}", tmp_path)
    assert status_of(d, "R2") == "pass"


def test_r2_first_para_short_but_total_enough_fails(tmp_path):
    # 首段 <80 但 H1→首 H2 总量 ≥80 → 仍 fail，detail 说明首段形态不合
    body = "# 标题\n\n" + "甲" * 45 + "\n\n" + "乙" * 45 + "\n\n## 小节\n正文\n"
    fm = yaml.safe_dump(GOOD_META, allow_unicode=True, sort_keys=False)
    _, d = run(f"---\n{fm}---\n\n{body}", tmp_path)
    r2 = next(c for c in d["checks"] if c["id"] == "R2")
    assert r2["status"] == "fail" and "首段" in r2["detail"]


def test_r2_first_para_too_long_warns(tmp_path):
    # 首段 >120 → warn（不拦发布）
    body = "# 标题\n\n" + "甲" * 130 + "\n\n## 小节\n正文\n"
    fm = yaml.safe_dump(GOOD_META, allow_unicode=True, sort_keys=False)
    _, d = run(f"---\n{fm}---\n\n{body}", tmp_path)
    assert status_of(d, "R2") == "warn"


# ---- R5-body 正文 FAQ 段一致性 ----

def test_r5_body_faq_missing_fails(tmp_path):
    _, d = run(build_doc(faq_section=False), tmp_path)
    assert status_of(d, "R5-body") == "fail"


def test_r5_body_faq_count_mismatch_fails(tmp_path):
    # 正文 FAQ 3 问，但 frontmatter faq 5 条 → 不一致
    _, d = run(build_doc(faq_q=3), tmp_path)
    assert status_of(d, "R5-body") == "fail"


# ---- F1 孤儿项：tag↔分类名重复 / 正文首行 H1 ----

def test_f1_tag_equals_category_name_fails(tmp_path):
    # category=relationships → 分类名「亲密与家庭」；tag 与之重复
    _, d = run(build_doc({"tags": ["亲密与家庭", "依恋", "自我关怀"]}), tmp_path)
    assert status_of(d, "F1-tag-category") == "fail"


def test_f1_missing_body_h1_fails(tmp_path):
    _, d = run(build_doc(h1=False), tmp_path)
    assert status_of(d, "F1-h1") == "fail"


# ---- 补齐字段级 fail（item 17） ----

def test_f0_no_frontmatter_fails(tmp_path):
    r, d = run("没有 frontmatter 的裸正文。\n", tmp_path)
    assert status_of(d, "F0") == "fail" and r.returncode == 1


def test_f1_excerpt_missing_fails(tmp_path):
    _, d = run(build_doc({"excerpt": _DELETE}), tmp_path)
    assert status_of(d, "F1-excerpt") == "fail"


def test_f1_target_keywords_missing_fails(tmp_path):
    _, d = run(build_doc({"target_keywords": _DELETE}), tmp_path)
    assert status_of(d, "F1-target_keywords") == "fail"


def test_f1_author_missing_fails(tmp_path):
    _, d = run(build_doc({"author_name": _DELETE}), tmp_path)
    assert status_of(d, "F1-author") == "fail"


def test_r5_faq_not_list_fails(tmp_path):
    _, d = run(build_doc({"faq": "不是列表"}), tmp_path)
    assert status_of(d, "R5") == "fail"


def test_r10_only_three_h2_fails(tmp_path):
    body = "# 标题\n\n" + TLDR + "\n\n## 一\n内容\n\n## 二\n内容\n\n## 三\n内容\n" + TABLE
    fm = yaml.safe_dump(GOOD_META, allow_unicode=True, sort_keys=False)
    _, d = run(f"---\n{fm}---\n\n{body}", tmp_path)
    assert status_of(d, "R10") == "fail"


def test_r10_paragraph_too_long_warns(tmp_path):
    _, d = run(build_doc(prepend="这" * 160), tmp_path)  # 单段 160 字 > 150
    assert status_of(d, "R10-para") == "warn"


# ---- 契约 ----

def test_missing_file_exit2(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "nope.md")],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "error" in json.loads(r.stdout)


def test_stdout_is_pure_json(tmp_path):
    r, d = run(build_doc(), tmp_path)
    # stdout 必须是可解析的纯 JSON（无多余打印）
    assert set(d.keys()) == {"ok", "summary", "checks"}

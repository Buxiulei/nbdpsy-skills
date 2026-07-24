import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "nbdpsy-seo-artical-creator" / "scripts" / "lint_markdown.py"


def run(md_text, tmp_path, *args):
    f = tmp_path / "a.md"
    f.write_text(md_text, encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), str(f), *args], capture_output=True, text=True)


# ---------- 加粗右翼/左翼违规（CommonMark 与中文排版冲突） ----------

def test_bold_ending_fullwidth_punct_followed_by_text_is_violation(tmp_path):
    r = run("**第一句：「我允许。」**很多人做不到。\n", tmp_path)
    d = json.loads(r.stdout)
    assert r.returncode == 1 and d["ok"] is False
    assert any(v["rule"] == "bold-flanking" for v in d["violations"])


def test_bold_ending_punct_at_line_end_is_ok(tmp_path):
    # 行尾（后随换行/EOF）右翼成立，能正常渲染
    r = run("**真正的独立是有选择地独立。**\n\n下一段。\n", tmp_path)
    assert json.loads(r.stdout)["ok"] is True and r.returncode == 0


def test_bold_ending_letter_is_ok(tmp_path):
    r = run("**一句话先说结论**：前者是病。\n", tmp_path)
    assert json.loads(r.stdout)["ok"] is True


def test_bold_opening_quote_preceded_by_text_is_violation(tmp_path):
    # 左翼对称：字后紧贴 **「 → 不成立
    r = run("他说**「我可以」**然后离开。\n", tmp_path)
    d = json.loads(r.stdout)
    assert r.returncode == 1
    assert any(v["rule"] == "bold-flanking" for v in d["violations"])


def test_violation_reports_real_line_number(tmp_path):
    md = "第一行正常。\n\n**结尾句号。**紧跟正文的违规行。\n"
    d = json.loads(run(md, tmp_path).stdout)
    v = [x for x in d["violations"] if x["rule"] == "bold-flanking"][0]
    assert v["line"] == 3


def test_fenced_code_not_scanned(tmp_path):
    md = "正常段落。\n\n```\n**代码块里。**不算违规\n```\n"
    assert json.loads(run(md, tmp_path).stdout)["ok"] is True


# ---------- 文内数字引用标注 [[n]](url) ----------

GOOD_CITED = (
    "统计显示患病率约 6.8%[[1]](https://a.com/x)，另一项研究[[2]](https://b.org/y)也证实。\n\n"
    "## 参考文献\n\n1. 来源甲。https://a.com/x\n2. 来源乙。https://b.org/y\n"
)


def test_citations_check_passes_when_all_marked(tmp_path):
    r = run(GOOD_CITED, tmp_path, "--citations", "2")
    d = json.loads(r.stdout)
    assert r.returncode == 0 and d["ok"] is True and d["cited"] == [1, 2]


def test_citations_check_fails_when_body_has_none(tmp_path):
    md = "正文只说了 6.8% 没有任何标注。\n\n## 参考文献\n\n1. 来源。https://a.com\n"
    r = run(md, tmp_path, "--citations", "1")
    d = json.loads(r.stdout)
    assert r.returncode == 1 and any(v["rule"] == "citation-marker" for v in d["violations"])


def test_citations_markers_after_reference_section_do_not_count(tmp_path):
    md = "正文没有标注。\n\n## 参考文献\n\n1. 来源[[1]](https://a.com)。\n"
    r = run(md, tmp_path, "--citations", "1")
    assert r.returncode == 1


def test_citations_missing_number_listed(tmp_path):
    md = "只标了一处[[1]](https://a.com)。\n\n## 参考文献\n\n1. 甲 https://a.com\n2. 乙 https://b.com\n"
    d = json.loads(run(md, tmp_path, "--citations", "2").stdout)
    v = [x for x in d["violations"] if x["rule"] == "citation-marker"][0]
    assert "2" in v["text"]


def test_missing_file_error_json_exit2(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "nope.md")], capture_output=True, text=True)
    assert r.returncode == 2 and "error" in json.loads(r.stdout)


# ---- stat-block：pillar-spec R3「带出处统计块 >=3」的可执行判据 ----

def test_stats_min_fails_without_cited_stats(tmp_path):
    """有引用标注但零统计数字 → stat-block 违规（恋爱脑一文的真实事故形态）。"""
    p = run("研究显示这类现象很普遍 [[1]](https://x.org/a)。\n\n## 参考文献\n1. X\n",
            tmp_path, "--citations", "1", "--stats-min", "3")
    out = json.loads(p.stdout)
    assert p.returncode == 1
    assert any(v["rule"] == "stat-block" for v in out["violations"])


def test_stats_min_passes_with_three_cited_stats(tmp_path):
    p = run("干预后 74.0% 不再符合诊断 [[1]](https://x.org/a)。\n"
            "另有 87.7% 改善 [[1]](https://x.org/a)。\n"
            "脱落率约 16%（对照 2 倍差异）[[1]](https://x.org/a)。\n\n## 参考文献\n1. X\n",
            tmp_path, "--citations", "1", "--stats-min", "3")
    assert p.returncode == 0


def test_stats_without_marker_do_not_count(tmp_path):
    """统计数字不带同行引用标注 → 不计入（R3 要求紧跟来源）。"""
    p = run("有 80% 的人如此。另有 70% 类似。还有 3 倍差距。\n"
            "结论句 [[1]](https://x.org/a)。\n\n## 参考文献\n1. X\n",
            tmp_path, "--citations", "1", "--stats-min", "3")
    out = json.loads(p.stdout)
    assert p.returncode == 1
    assert any(v["rule"] == "stat-block" and "共 3 处" in v["text"] for v in out["violations"])

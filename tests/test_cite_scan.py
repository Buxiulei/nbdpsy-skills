"""cite_scan.py 回归测试（2026-07-26 引用职责分离）。

覆盖三类曾经翻车/易翻车的行为：
  1. `【引言】`「【引用】」这类正常中文词不得误报（原 `RE_LEAD = "【引"` 不含冒号导致）；
  2. frontmatter 与围栏代码块内的标记字面量不算残留（范文/规范文档里会举例展示写作态标记）；
  3. `--expect-empty` 的发布态闸门语义（残留即 exit 1）。
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (Path(__file__).parent.parent
          / "nbdpsy-seo-artical-creator" / "scripts" / "cite_scan.py")


def _run(path: Path, *args):
    r = subprocess.run([sys.executable, str(SCRIPT), str(path), *args],
                       capture_output=True, text=True)
    return r, (json.loads(r.stdout) if r.stdout.strip() else None)


def _write(tmp_path: Path, body: str, name: str = "draft.md") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_normal_chinese_words_not_flagged(tmp_path):
    """`【引言】`/`【引用】`/`【引证】` 是正常中文词，不是标记——不得误报（旧版 exit 1）。"""
    f = _write(tmp_path, "【引言】本文讨论 CPTSD。\n研究显示【引用文献如下】。\n又见【引证】。\n")
    r, out = _run(f)
    assert r.returncode == 0
    assert out["total"] == 0
    assert out["malformed"] == []


def test_scan_dedups_and_orders_by_first_occurrence(tmp_path):
    """同一文献多处引用合并为一条；候选编号按正文首现顺序。"""
    f = _write(tmp_path, (
        "一句【引: WHO 2019, ICD-11 6B41】。\n"
        "二句【引: Herman 1992, Trauma and Recovery】。\n"
        "三句又引【引: WHO 2019, ICD-11 6B41】。\n"
    ))
    r, out = _run(f)
    assert r.returncode == 0
    assert out["total"] == 3 and out["unique"] == 2
    who = next(m for m in out["markers"] if m["author"] == "WHO")
    assert who["count"] == 2 and who["n_suggested"] == 1


def test_fullwidth_colon_and_locator(tmp_path):
    """全角冒号照常识别；页码/章节收进 locators（发布态归参考文献条目末尾）。"""
    f = _write(tmp_path, "见【引：Herman 1992, 创伤与复原, 第 3 章】。\n")
    r, out = _run(f)
    assert r.returncode == 0 and out["unique"] == 1
    assert "第 3 章" in "".join(out["markers"][0]["locators"])


def test_frontmatter_literal_is_not_residue(tmp_path):
    """frontmatter 里的说明性字面量不算残留——否则范文自己过不了自己的闸。"""
    f = _write(tmp_path, (
        "---\ntitle: 范文\nnote: 写作态形态见 【引: 作者 年份, 简称】\n---\n\n正文没有标记。\n"
    ))
    r, out = _run(f, "--expect-empty")
    assert r.returncode == 0
    assert out["total"] == 0


def test_fenced_code_block_example_is_not_residue(tmp_path):
    """围栏代码块内的示例是"内容"不是残留（与审查端 checklist-article 判据同源）。"""
    f = _write(tmp_path, (
        "正文一句。\n\n```markdown\n示例：【引: Herman 1992, Trauma and Recovery】\n```\n\n正文二句。\n"
    ))
    r, out = _run(f, "--expect-empty")
    assert r.returncode == 0
    assert out["total"] == 0


def test_expect_empty_catches_real_residue(tmp_path):
    """正文里的真残留必须被 --expect-empty 抓住（引用落地没跑完）。"""
    f = _write(tmp_path, "正文残留一处【引: WHO 2019, ICD-11 6B41】。\n")
    r, out = _run(f, "--expect-empty")
    assert r.returncode == 1
    assert out["total"] == 1


def test_line_numbers_are_original_file_lines(tmp_path):
    """剥 frontmatter 用空行占位，报的行号须仍等于原文件行号（便于按行号定位）。"""
    f = _write(tmp_path, "---\ntitle: t\n---\n\n第 5 行有标记【引: WHO 2019, ICD-11】。\n")
    r, out = _run(f)
    assert r.returncode == 0
    assert out["markers"][0]["first_line"] == 5


def test_missing_file_exits_2(tmp_path):
    r, _ = _run(tmp_path / "不存在.md")
    assert r.returncode == 2

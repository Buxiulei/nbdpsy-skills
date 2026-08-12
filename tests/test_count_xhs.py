import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "count_xhs.py"
FIXTURE = Path(__file__).parent / "fixtures" / "note.md"

def test_fixture_note_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 0 and d["ok"] is True and 6 <= d["pages"] <= 9

def test_too_few_pages_fails(tmp_path):
    bad = FIXTURE.read_text(encoding="utf-8")
    bad = bad.split("### P3")[0]          # 截掉 P3 之后 → 页数不足
    f = tmp_path / "bad.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    assert r.returncode == 2 and json.loads(r.stdout)["ok_pages"] is False

def test_body_min_max_override(tmp_path):
    """--body-min/--body-max 覆盖默认正文区间：500 字正文默认（210–450）超上限判 ok_body False，
    传 --body-min 400 --body-max 800（推介笔记区间）落在区间内判 ok_body True。"""
    body = "创" * 500                       # 500 个汉字（一-龥 内），超默认上限 450
    doc = "## 发布文案\n\n" + body + "\n\n## 配图轮播\n"
    f = tmp_path / "long_body.md"; f.write_text(doc, encoding="utf-8")
    # 默认区间 210–450：500 超上限 → ok_body False
    r1 = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d1 = json.loads(r1.stdout)
    assert d1["body_chars"] == 500 and d1["ok_body"] is False
    # 推介区间 400–800：500 在区间内 → ok_body True
    r2 = subprocess.run([sys.executable, str(SCRIPT), str(f),
                         "--body-min", "400", "--body-max", "800"], capture_output=True, text=True)
    d2 = json.loads(r2.stdout)
    assert d2["body_chars"] == 500 and d2["ok_body"] is True


def _retitle(tmp_path, new_title, name="retitled.md"):
    """复用 fixture 正文，只换 frontmatter 的 title。"""
    src = FIXTURE.read_text(encoding="utf-8")
    out = re.sub(r"^title:.*$", f"title: {new_title}", src, count=1, flags=re.MULTILINE)
    f = tmp_path / name
    f.write_text(out, encoding="utf-8")
    return f


def _run(*argv):
    r = subprocess.run([sys.executable, str(SCRIPT), *map(str, argv)],
                       capture_output=True, text=True)
    return r, json.loads(r.stdout)


def test_title_keyword_not_passed_is_backward_compatible():
    """不传 --title-keyword 时行为与历史版本一致：fixture 标题里关键词在末尾也照样 ok。"""
    r, d = _run(FIXTURE)
    assert r.returncode == 0 and d["ok"] is True and d["ok_title"] is True
    assert d["title_keyword"] == "" and d["title_keyword_pos"] is None and d["title_reason"] == ""


def test_title_keyword_in_head_passes(tmp_path):
    """关键词完整落在前 10 字内 → ok_title True；大小写不敏感（cptsd 命中 CPTSD）。"""
    f = _retitle(tmp_path, "CPTSD 和创伤后应激有什么不同")
    r, d = _run(f, "--title-keyword", "cptsd")
    assert r.returncode == 0 and d["ok_title"] is True
    assert d["title_keyword_pos"] == 0 and d["title_reason"] == ""


def test_title_keyword_after_head_fails():
    """关键词被钩子挤到 10 字之后 → ok_title False + title_reason 说明原因（fixture 原标题即此形态）。"""
    r, d = _run(FIXTURE, "--title-keyword", "复杂性创伤")
    assert r.returncode == 2 and d["ok_title"] is False and d["ok"] is False
    assert d["title_keyword_pos"] == 13 and "前 10 字" in d["title_reason"]


def test_title_keyword_absent_fails():
    """关键词根本不在标题里 → pos = -1 + 对应原因。"""
    r, d = _run(FIXTURE, "--title-keyword", "童年情感忽视")
    assert r.returncode == 2 and d["ok_title"] is False
    assert d["title_keyword_pos"] == -1 and "未出现在标题里" in d["title_reason"]


def test_title_keyword_without_frontmatter_fails(tmp_path):
    """显式要求校验关键词、却没有 title 可校 → 不静默放行（无参数时仍按历史放行）。"""
    f = tmp_path / "no_fm.md"
    f.write_text("## 发布文案\n\n" + "创" * 300 + "\n", encoding="utf-8")
    _, d_with = _run(f, "--title-keyword", "童年情感忽视")
    assert d_with["ok_title"] is False and "无法校验" in d_with["title_reason"]
    _, d_without = _run(f)
    assert d_without["ok_title"] is True and d_without["title_reason"] == ""


def test_missing_file_errors_to_stdout(tmp_path):
    missing = tmp_path / "does_not_exist.md"
    r = subprocess.run([sys.executable, str(SCRIPT), str(missing)], capture_output=True, text=True)
    d = json.loads(r.stdout)          # 错误 JSON 打 stdout，而非 stderr
    assert r.returncode == 2 and "error" in d and r.stderr.strip() != ""


def _inflate_fixture(tmp_path, extra):
    """在 fixture 正文节首插入 extra 个汉字，其余结构（页数/标题）保持合法。"""
    fx = FIXTURE.read_text(encoding="utf-8")
    m = re.search(r"^## *(发布文案|正文).*$", fx, re.M)
    t = fx[:m.end()] + "\n" + "字" * extra + fx[m.end():]
    f = tmp_path / "inflated.md"
    f.write_text(t, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout)


def test_body_over_reference_warns_but_passes(tmp_path):
    """2026-08-12 老板定性：450 是参考值不判 FAIL（硬上限逼出压句病文）；只有平台 900 才硬。"""
    rc, out = _inflate_fixture(tmp_path, 300)   # 正文 ~600 字
    assert rc == 0 and out["ok"] is True and out["ok_body"] is False
    assert "参考区间" in out["body_warn"] and "删段落" in out["body_warn"]


def test_body_over_platform_safe_fails(tmp_path):
    rc, out = _inflate_fixture(tmp_path, 700)   # 正文 ~1000 字，超平台安全值
    assert rc == 2 and out["ok"] is False and out["ok_platform"] is False
    assert "平台安全值 900" in out["title_reason"]

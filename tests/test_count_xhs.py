import json
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


def test_missing_file_errors_to_stdout(tmp_path):
    missing = tmp_path / "does_not_exist.md"
    r = subprocess.run([sys.executable, str(SCRIPT), str(missing)], capture_output=True, text=True)
    d = json.loads(r.stdout)          # 错误 JSON 打 stdout，而非 stderr
    assert r.returncode == 2 and "error" in d and r.stderr.strip() != ""

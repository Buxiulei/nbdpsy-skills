import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "xiaohongshu-creator" / "scripts" / "count_xhs.py"
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

def test_missing_file_errors_to_stdout(tmp_path):
    missing = tmp_path / "does_not_exist.md"
    r = subprocess.run([sys.executable, str(SCRIPT), str(missing)], capture_output=True, text=True)
    d = json.loads(r.stdout)          # 错误 JSON 打 stdout，而非 stderr
    assert r.returncode == 2 and "error" in d and r.stderr.strip() != ""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "xiaohongshu-creator" / "scripts" / "check_compliance.py"
FIXTURE = Path(__file__).parent / "fixtures" / "note.md"

def test_fixture_clean():
    r = subprocess.run([sys.executable, str(SCRIPT), str(FIXTURE)], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["ok"] is True

def test_violation_detected(tmp_path):
    bad = FIXTURE.read_text(encoding="utf-8").replace("## 发布文案（复制这一段直接发布）\n\n姐妹", "## 发布文案（复制这一段直接发布）\n\n本方法可治愈创伤，加微信咨询。\n\n姐妹", 1)
    f = tmp_path / "bad.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1 and len(d["violations"]) >= 2   # 治愈 + 微信

def test_fenced_prompt_not_scanned(tmp_path):
    bad = FIXTURE.read_text(encoding="utf-8") + "\n```\n画面中不要出现二维码和微信\n```\n"
    f = tmp_path / "b.md"; f.write_text(bad, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    assert r.returncode == 0   # 围栏内负向指令不误伤

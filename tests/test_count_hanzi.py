import json, subprocess, sys
from pathlib import Path
SCRIPT = Path(__file__).parent.parent / "seo-artical-creator" / "scripts" / "count_hanzi.py"

def run(md_text, tmp_path, *args):
    f = tmp_path / "a.md"; f.write_text(md_text, encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), str(f), *args], capture_output=True, text=True)

def test_strips_frontmatter_and_counts(tmp_path):
    r = run("---\ntitle: 测试标题很多字\n---\n\n正文四个字\n", tmp_path, "--min", "1", "--max", "10")
    d = json.loads(r.stdout)
    assert d["hanzi"] == 5 and d["ok"] is True and r.returncode == 0  # 「正文四个字」5字，frontmatter 不计

def test_out_of_range_exit2(tmp_path):
    r = run("---\nt: x\n---\n短\n", tmp_path)   # 默认 3000-5000
    assert r.returncode == 2 and json.loads(r.stdout)["ok"] is False

def test_fixture_pillar_in_range(tmp_path):
    fx = Path(__file__).parent / "fixtures" / "pillar.md"
    r = subprocess.run([sys.executable, str(SCRIPT), str(fx)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout   # 范文必须达标

def test_missing_file_exit2(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), "/nonexistent/path/file.md"], capture_output=True, text=True)
    assert r.returncode == 2
    d = json.loads(r.stdout)
    assert "error" in d

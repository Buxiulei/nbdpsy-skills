import json, subprocess, sys
from pathlib import Path
SCRIPT = Path(__file__).parent.parent / "nbdpsy-seo-artical-creator" / "scripts" / "check_links.py"

def test_extract_and_classify(tmp_path, monkeypatch):
    sys.path.insert(0, str(SCRIPT.parent))
    import check_links
    assert check_links.classify(200) == "ok"
    assert check_links.classify(404) == "dead"
    assert check_links.classify(None) == "dead"      # 网络失败
    assert check_links.classify(403) == "suspect"
    urls = check_links.extract_urls("见 https://a.com/x 和 (https://b.org/y) 结尾")
    assert urls == ["https://a.com/x", "https://b.org/y"]

def test_dead_link_exit1(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("链接 http://127.0.0.1:1/dead 应判死\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f), "--timeout", "2"], capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert r.returncode == 1 and len(d["dead"]) == 1

def test_missing_file_exit2(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), "/nonexistent/path/file.md"], capture_output=True, text=True)
    assert r.returncode == 2
    d = json.loads(r.stdout)
    assert "error" in d

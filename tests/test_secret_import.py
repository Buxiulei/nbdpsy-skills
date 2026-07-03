import sys
from importlib import reload
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))


def _fresh(monkeypatch, tmp_path):
    secrets = tmp_path / "secrets.env"
    monkeypatch.setenv("NBDPSY_SECRETS", str(secrets))
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(tmp_path / "ws"))
    import nbdpsy_common
    reload(nbdpsy_common)
    return nbdpsy_common, secrets


def test_import_writes_allowlisted(monkeypatch, tmp_path):
    m, secrets = _fresh(monkeypatch, tmp_path)
    bundle = tmp_path / "b.txt"
    bundle.write_text(
        "# ===== 配置包 =====\nNBDPSY_BLOG_API_KEY=nbdblog_secret\n"
        "VOLC_TTS_APPID=appid123\n# 即梦扫码...\n", encoding="utf-8")
    written, skipped = m.import_bundle(bundle)
    assert "NBDPSY_BLOG_API_KEY" in written and "VOLC_TTS_APPID" in written
    assert m.get_secret("NBDPSY_BLOG_API_KEY") == "nbdblog_secret"


def test_import_rejects_non_allowlist(monkeypatch, tmp_path):
    m, secrets = _fresh(monkeypatch, tmp_path)
    bundle = tmp_path / "b.txt"
    bundle.write_text("EVIL_KEY=pwned\nPATH=/tmp/evil\nNBDPSY_BLOG_API_KEY=ok\n", encoding="utf-8")
    written, skipped = m.import_bundle(bundle)
    assert "EVIL_KEY" in skipped and "PATH" in skipped
    assert m.get_secret("EVIL_KEY") is None
    assert "EVIL_KEY" not in secrets.read_text(encoding="utf-8")  # 确实没落库


def test_import_output_no_values(monkeypatch, tmp_path, capsys):
    m, _ = _fresh(monkeypatch, tmp_path)
    bundle = tmp_path / "b.txt"
    bundle.write_text("NBDPSY_BLOG_API_KEY=nbdblog_supersecret\n", encoding="utf-8")
    rc = m.main(["secret", "import", str(bundle)])
    out = capsys.readouterr()
    assert rc == 0
    assert "nbdblog_supersecret" not in out.out
    assert "nbdblog_supersecret" not in out.err

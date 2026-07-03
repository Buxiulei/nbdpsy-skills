import sys
from importlib import reload
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))


def _fresh(monkeypatch, tmp_path, secrets_body: str):
    secrets = tmp_path / "secrets.env"
    secrets.write_text(secrets_body, encoding="utf-8")
    monkeypatch.setenv("NBDPSY_SECRETS", str(secrets))
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(tmp_path / "ws"))  # 隔离工作区 .env
    for k in ("NBDPSY_BLOG_API_KEY", "VOLC_TTS_APPID", "VOLC_TTS_ACCESS_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    import nbdpsy_common
    reload(nbdpsy_common)
    return nbdpsy_common


def test_doctor_all_present(monkeypatch, tmp_path):
    m = _fresh(monkeypatch, tmp_path,
               "NBDPSY_BLOG_API_KEY=nbdblog_x\nVOLC_TTS_APPID=a\nVOLC_TTS_ACCESS_TOKEN=t\n")
    report, code = m.doctor()
    assert code == 0
    assert report["ok"] is True
    assert report["doubao_ready"] is True


def test_doctor_missing_blog_key(monkeypatch, tmp_path):
    m = _fresh(monkeypatch, tmp_path, "VOLC_TTS_APPID=a\n")
    report, code = m.doctor()
    assert code == 1
    assert report["ok"] is False
    assert "NBDPSY_BLOG_API_KEY" in report["required_missing"]
    assert any("API Keys" in n for n in report["notes"])


def test_doctor_doubao_optional(monkeypatch, tmp_path):
    m = _fresh(monkeypatch, tmp_path, "NBDPSY_BLOG_API_KEY=nbdblog_x\n")
    report, code = m.doctor()
    assert code == 0
    assert report["ok"] is True
    assert report["doubao_ready"] is False

import sys
from importlib import reload
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))


def _fresh(monkeypatch, tmp_path, secrets_body: str):
    secrets = tmp_path / "secrets.env"
    secrets.write_text(secrets_body, encoding="utf-8")
    monkeypatch.setenv("NBDPSY_SECRETS", str(secrets))
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(tmp_path / "ws"))  # 隔离工作区 .env
    for k in ("NBDPSY_BLOG_API_KEY", "NBDPSY_STRATEGY_API_KEY",
              "VOLC_TTS_API_KEY", "VOLC_TTS_APPID", "VOLC_TTS_ACCESS_TOKEN"):
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


# ---- 战略报告凭据：默认复用发文 key，运营只配一把 ----

def test_doctor_strategy_ready_falls_back_to_blog_key(monkeypatch, tmp_path):
    """只配了发文 key（没有 NBDPSY_STRATEGY_API_KEY）也算就绪——一把 key 天然可同时持有
    blog:write + strategy:write。把 strategy_api_key 改回只读 STRATEGY 本用例即变红。"""
    m = _fresh(monkeypatch, tmp_path, "NBDPSY_BLOG_API_KEY=nbdblog_x\n")
    report, code = m.doctor()
    assert code == 0
    assert report["strategy_ready"] is True
    assert m.strategy_api_key() == "nbdblog_x"


def test_doctor_strategy_note_does_not_overclaim(monkeypatch, tmp_path):
    """就绪 ≠ 一定发得出去：notes 必须点明权限由服务端 scope 判定、没勾 strategy:write 会 403。"""
    m = _fresh(monkeypatch, tmp_path, "NBDPSY_BLOG_API_KEY=nbdblog_x\n")
    report, _ = m.doctor()
    note = next(n for n in report["notes"] if "战略规划报告" in n)
    assert "scope" in note and "strategy:write" in note and "403" in note
    assert "API Keys" in note                      # 指到后台那个页面，给可行动指引


def test_doctor_explicit_strategy_key_takes_precedence(monkeypatch, tmp_path):
    m = _fresh(monkeypatch, tmp_path,
               "NBDPSY_BLOG_API_KEY=nbdblog_x\nNBDPSY_STRATEGY_API_KEY=nbdstrat_y\n")
    report, _ = m.doctor()
    assert report["strategy_ready"] is True
    assert m.strategy_api_key() == "nbdstrat_y"


def test_doctor_strategy_not_ready_without_any_key(monkeypatch, tmp_path):
    """两把都没有才算不可用，且提示指向「配发文 key 即可」，不再要求单配一把。"""
    m = _fresh(monkeypatch, tmp_path, "VOLC_TTS_API_KEY=sk-x\n")
    report, _ = m.doctor()
    assert report["strategy_ready"] is False
    assert m.strategy_api_key() is None
    note = next(n for n in report["notes"] if "战略规划报告" in n)
    assert "NBDPSY_BLOG_API_KEY" in note


# ---- 安装版本标记：有则报版本，没有也只是 info，绝不判 fail ----

def _isolate_marker(monkeypatch, m, tmp_path):
    """把标记查找完全关进 tmp：__file__ 指向假 skills 树、HOME 指向空家目录。
    返回假 skills 根（标记该落在这层）。"""
    fake_home = tmp_path / "home"
    (fake_home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    skills_root = tmp_path / "skills"
    scripts = skills_root / "nbdpsy-content-pipeline" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(m, "__file__", str(scripts / "nbdpsy_common.py"))
    return skills_root


def test_doctor_reports_toolkit_version_from_marker(monkeypatch, tmp_path):
    """装过新版安装器 → doctor 报出 版本/commit/安装日期。"""
    m = _fresh(monkeypatch, tmp_path, "NBDPSY_BLOG_API_KEY=nbdblog_x\n")
    skills_root = _isolate_marker(monkeypatch, m, tmp_path)
    (skills_root / ".nbdpsy-skills-install.json").write_text(
        '{"version": "1.41.0", "commit": "b4c5812", '
        '"installed_at": "2026-07-28T11:05:00+08:00", "source": "local-repo"}',
        encoding="utf-8")
    report, code = m.doctor()
    assert code == 0
    note = next(n for n in report["notes"] if n.startswith("工具包 v"))
    assert "1.41.0" in note and "b4c5812" in note and "2026-07-28" in note
    assert "11:05" not in note                      # 只报日期部分，不报时分秒
    assert report["install_marker"]["source"] == "local-repo"


def test_doctor_missing_marker_is_info_not_fail(monkeypatch, tmp_path):
    """存量机器全都没有这个文件——必须只给 info 提示，ok/exit code 一个都不能变红。"""
    m = _fresh(monkeypatch, tmp_path, "NBDPSY_BLOG_API_KEY=nbdblog_x\n")
    _isolate_marker(monkeypatch, m, tmp_path)      # 不写标记
    report, code = m.doctor()
    assert code == 0
    assert report["ok"] is True
    assert report["install_marker"] is None
    note = next(n for n in report["notes"] if "版本标记缺失" in n)
    assert "install.sh" in note                    # 给出可行动的补救办法


def test_doctor_doubao_ready_via_api_key_only(monkeypatch, tmp_path):
    """新版单一凭据 VOLC_TTS_API_KEY 单独齐备（无 appid/token）也应判定 doubao_ready=True。"""
    m = _fresh(monkeypatch, tmp_path, "NBDPSY_BLOG_API_KEY=nbdblog_x\nVOLC_TTS_API_KEY=sk-x\n")
    report, code = m.doctor()
    assert code == 0
    assert report["ok"] is True
    assert report["doubao_ready"] is True

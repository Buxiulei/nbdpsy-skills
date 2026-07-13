import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

import nbdpsy_common


def _use(tmp_path, monkeypatch, content=None):
    p = tmp_path / "settings.json"
    if content is not None:
        p.write_text(content, encoding="utf-8")
    monkeypatch.setenv("NBDPSY_CLAUDE_SETTINGS", str(p))
    return p


def test_fresh_file_created_with_domains_and_permissions(tmp_path, monkeypatch):
    p = _use(tmp_path, monkeypatch)
    changed, path, err = nbdpsy_common.sandbox_allow()
    assert changed and err is None and path == p
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "mcp.nbdpsy.com" in data["sandbox"]["network"]["allowedDomains"]
    assert "WebFetch(domain:mcp.nbdpsy.com)" in data["permissions"]["allow"]
    # 不擅自开沙盒
    assert "enabled" not in data["sandbox"]


def test_merge_preserves_existing_and_idempotent(tmp_path, monkeypatch):
    existing = {"sandbox": {"enabled": True, "network": {"allowedDomains": ["a.com"]}},
                "permissions": {"allow": ["Bash(ls)"]}, "model": "opus"}
    p = _use(tmp_path, monkeypatch, json.dumps(existing))
    changed, _, err = nbdpsy_common.sandbox_allow()
    assert changed and err is None
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["sandbox"]["enabled"] is True          # 用户原配置不动
    assert data["model"] == "opus"
    assert data["sandbox"]["network"]["allowedDomains"][0] == "a.com"  # 追加不覆盖
    assert "mcp.nbdpsy.com" in data["sandbox"]["network"]["allowedDomains"]
    assert "Bash(ls)" in data["permissions"]["allow"]
    # 幂等：第二次跑无改动
    changed2, _, _ = nbdpsy_common.sandbox_allow()
    assert changed2 is False


def test_broken_json_refuses_to_write(tmp_path, monkeypatch):
    p = _use(tmp_path, monkeypatch, "{broken json")
    changed, _, err = nbdpsy_common.sandbox_allow()
    assert changed is False and err and "解析失败" in err
    assert p.read_text(encoding="utf-8") == "{broken json"  # 原文件一字未动


def test_type_conflict_skips_that_branch(tmp_path, monkeypatch):
    # sandbox 是布尔（类型冲突）→ 不动它，但 permissions 正常合并
    p = _use(tmp_path, monkeypatch, json.dumps({"sandbox": True}))
    changed, _, err = nbdpsy_common.sandbox_allow()
    assert changed and err is None
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["sandbox"] is True
    assert "WebFetch(domain:mcp.nbdpsy.com)" in data["permissions"]["allow"]


def test_doctor_reports_xhs_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("NBDPSY_SECRETS", str(tmp_path / "s.env"))
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("NBDPSY_XHS_API_KEY", raising=False)
    report, _ = nbdpsy_common.doctor()
    assert report["xhs_ready"] is False
    assert any("NBDPSY_XHS_API_KEY" in n for n in report["notes"])
    monkeypatch.setenv("NBDPSY_XHS_API_KEY", "k")
    report2, _ = nbdpsy_common.doctor()
    assert report2["xhs_ready"] is True

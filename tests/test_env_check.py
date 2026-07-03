"""env_check.py CLI 契约测试：JSON 字段齐全 / 模块探测 / --install 映射 / 凭据判定 / warn 不阻塞 / 真实子进程跑一次。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
import env_check  # noqa: E402


# ---------- 1. JSON 契约字段齐全、可解析 ----------

@pytest.mark.parametrize("profile", sorted(env_check.PROFILES))
def test_json_contract_fields(profile):
    result = env_check.run(profile, install=False)
    assert set(result.keys()) == {"ready", "profile", "checks"}
    assert result["profile"] == profile
    assert isinstance(result["ready"], bool)
    assert isinstance(result["checks"], list) and result["checks"]
    for c in result["checks"]:
        assert set(c.keys()) == {"name", "status", "detail", "fix"}
        assert c["status"] in ("ok", "missing", "warn")
    json.dumps(result, ensure_ascii=False)  # 必须可序列化


def test_pipeline_profile_includes_text_to_video_note():
    result = env_check.run("pipeline", install=False)
    note = next(c for c in result["checks"] if c["name"] == "text-to-video 视频链依赖")
    assert note["status"] == "warn"
    assert "check_env.py" in note["detail"]


# ---------- 2. 模块缺失检测 ----------

def test_module_missing_marks_seo_ready_false(monkeypatch):
    monkeypatch.setattr(env_check.importlib.util, "find_spec", lambda name: None)
    result = env_check.run("seo", install=False)
    yaml_check = next(c for c in result["checks"] if c["name"] == "yaml")
    assert yaml_check["status"] == "missing"
    assert result["ready"] is False


# ---------- 3. --install 走 pip install --user，PIL→pillow 映射正确 ----------

def test_install_calls_pip_with_pillow_mapping(monkeypatch):
    monkeypatch.setattr(env_check.importlib.util, "find_spec", lambda name: None)
    calls = []

    class _FakeCompletedProcess:
        stdout = ""

    def fake_run(cmd, *a, **kw):
        calls.append(cmd)
        return _FakeCompletedProcess()

    monkeypatch.setattr(env_check.subprocess, "run", fake_run)
    env_check.run("reviewer", install=True)  # reviewer 需要 PIL
    assert [sys.executable, "-m", "pip", "install", "--user", "pillow"] in calls


# ---------- 3b. --install 路径下 pip 子进程噪音不得污染 stdout（回归） ----------

def test_install_pip_noise_does_not_leak_into_stdout_json(monkeypatch, capsys):
    """回归：pip 子进程的任何输出（如 "Looking in indexes" "Requirement already
    satisfied" 等信息行）必须全部落在 stderr；main() 最终打到 stdout 的仍必须是
    可被 json.loads 解析的纯 JSON 单行，不能混入 pip 的噪音文本。"""
    monkeypatch.setattr(env_check.importlib.util, "find_spec", lambda name: None)

    class _FakeCompletedProcess:
        stdout = "Looking in indexes: https://pypi.org/simple\nRequirement already satisfied: pyyaml\n"

    def fake_run(cmd, *a, **kw):
        return _FakeCompletedProcess()

    monkeypatch.setattr(env_check.subprocess, "run", fake_run)
    rc = env_check.main(["--profile", "xhs", "--install"])
    captured = capsys.readouterr()

    assert rc == 1  # find_spec 恒 None → 模块仍判缺，ready=False
    payload = json.loads(captured.out.strip())  # stdout 必须是纯 JSON，噪音不能混入
    assert payload["profile"] == "xhs"
    assert "Requirement already satisfied" not in captured.out
    assert "Requirement already satisfied" in captured.err


# ---------- 4. 凭据：seo 必需缺失 → ready=false；xhs 无凭据要求 → ready=true ----------

def _isolate_credentials(tmp_path, monkeypatch):
    empty_secrets = tmp_path / "empty.env"
    empty_secrets.write_text("", encoding="utf-8")
    monkeypatch.setenv("NBDPSY_SECRETS", str(empty_secrets))
    monkeypatch.delenv("NBDPSY_BLOG_API_KEY", raising=False)
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(ws))  # 无 .env 的临时目录


def test_seo_profile_missing_credential_blocks_ready(tmp_path, monkeypatch):
    _isolate_credentials(tmp_path, monkeypatch)
    result = env_check.run("seo", install=False)
    cred = next(c for c in result["checks"] if c["name"] == "NBDPSY_BLOG_API_KEY")
    assert cred["status"] == "missing"
    assert result["ready"] is False


def test_xhs_profile_has_no_credential_requirement(tmp_path, monkeypatch):
    _isolate_credentials(tmp_path, monkeypatch)
    result = env_check.run("xhs", install=False)
    assert not any(c["name"] == "NBDPSY_BLOG_API_KEY" for c in result["checks"])
    assert result["ready"] is True  # 本机模块齐全


# ---------- 5. reviewer profile：ffmpeg 缺失记 warn，不阻塞 ready ----------

def test_reviewer_ffmpeg_missing_is_warn_not_blocking(monkeypatch):
    monkeypatch.setattr(env_check.shutil, "which", lambda name: None)
    result = env_check.run("reviewer", install=False)
    ffmpeg_check = next(c for c in result["checks"] if c["name"] == "ffmpeg")
    assert ffmpeg_check["status"] == "warn"
    assert result["ready"] is True


# ---------- 6. subprocess 真跑一次本机 xhs profile ----------

def test_subprocess_real_xhs_profile_exits_zero_with_pure_json_stdout():
    script = Path(__file__).parent.parent / "shared" / "env_check.py"
    r = subprocess.run(
        [sys.executable, str(script), "--profile", "xhs"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    payload = json.loads(r.stdout)  # stdout 必须是纯 JSON，无杂散文本
    assert payload["ready"] is True
    assert payload["profile"] == "xhs"

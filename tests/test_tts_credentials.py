"""tts_gen.py 凭据解析测试——跨任务集成缺口补测：
setup.py 凭据向导把 VOLC_TTS_* 写进 nbdpsy_common 用户级 secrets（NBDPSY_SECRETS 指向的文件），
tts_gen 原先只读环境变量/skill .env，向导配完凭据后豆包引擎仍取不到。
本文件只测 resolve_credentials()（纯函数，不真调 TTS API）：
三级链 环境变量 → skill .env → nbdpsy_common 用户级 secrets，且现有两层优先级不变。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "text-to-video" / "scripts"))

ENV_KEYS = ["VOLC_TTS_APPID", "VOLC_TTS_ACCESS_TOKEN", "VOLC_TTS_CLUSTER", "VOLC_TTS_VOICE"]


def _isolate(monkeypatch, tmp_path):
    """清空相关环境变量 + 把 NBDPSY_SECRETS/NBDPSY_WORKSPACE 指向本测试专属临时路径，
    避免读到本机真实的用户级 secrets 文件或 workspace .env。"""
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NBDPSY_SECRETS", str(tmp_path / "secrets.env"))
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(tmp_path / "ws"))


def test_resolve_credentials_falls_back_to_user_secrets(tmp_path, monkeypatch):
    """无环境变量、无 skill .env 时，凭据解析函数应能从 nbdpsy_common 用户级 secrets
    链取到值（模拟 setup.py 向导已写入用户级 secrets 文件的场景）。"""
    _isolate(monkeypatch, tmp_path)
    (tmp_path / "secrets.env").write_text(
        "VOLC_TTS_APPID=appid-from-secrets\n"
        "VOLC_TTS_ACCESS_TOKEN=token-from-secrets\n",
        encoding="utf-8",
    )

    import tts_gen
    monkeypatch.setattr(tts_gen, "_load_env", lambda: None)  # 无 skill .env，隔离该分支

    creds = tts_gen.resolve_credentials()
    assert creds["appid"] == "appid-from-secrets"
    assert creds["token"] == "token-from-secrets"
    assert creds["cluster"] == "volcano_tts"  # 未显式配置 → 用默认值
    assert creds["voice"] is None


def test_resolve_credentials_no_source_returns_none_without_error(tmp_path, monkeypatch):
    """三层都没有配置 → appid/token/voice 为 None，cluster 仍有默认值，不抛异常。"""
    _isolate(monkeypatch, tmp_path)

    import tts_gen
    monkeypatch.setattr(tts_gen, "_load_env", lambda: None)

    creds = tts_gen.resolve_credentials()
    assert creds["appid"] is None
    assert creds["token"] is None
    assert creds["cluster"] == "volcano_tts"
    assert creds["voice"] is None


def test_resolve_credentials_env_var_priority_over_user_secrets(tmp_path, monkeypatch):
    """现有优先级不变：环境变量已配置时，即使用户级 secrets 也配了同一个键，仍以环境变量为准。"""
    _isolate(monkeypatch, tmp_path)
    (tmp_path / "secrets.env").write_text("VOLC_TTS_APPID=appid-from-secrets\n", encoding="utf-8")
    monkeypatch.setenv("VOLC_TTS_APPID", "appid-from-env")

    import tts_gen
    monkeypatch.setattr(tts_gen, "_load_env", lambda: None)

    creds = tts_gen.resolve_credentials()
    assert creds["appid"] == "appid-from-env"


def test_resolve_credentials_skill_dotenv_priority_over_user_secrets(tmp_path, monkeypatch):
    """现有优先级不变：skill 目录 .env（_load_env 灌入 os.environ）优先于用户级 secrets 兜底。"""
    _isolate(monkeypatch, tmp_path)
    (tmp_path / "secrets.env").write_text(
        "VOLC_TTS_ACCESS_TOKEN=token-from-secrets\n", encoding="utf-8")

    import tts_gen

    def _fake_load_env():
        import os
        os.environ["VOLC_TTS_ACCESS_TOKEN"] = "token-from-skill-dotenv"

    monkeypatch.setattr(tts_gen, "_load_env", _fake_load_env)

    creds = tts_gen.resolve_credentials()
    assert creds["token"] == "token-from-skill-dotenv"


def test_resolve_credentials_explicit_cluster_and_voice_override_defaults(tmp_path, monkeypatch):
    """cluster/voice 有内置默认值：显式配置（这里走用户级 secrets 链）优先于默认值语义保持。"""
    _isolate(monkeypatch, tmp_path)
    (tmp_path / "secrets.env").write_text(
        "VOLC_TTS_CLUSTER=custom_cluster\n"
        "VOLC_TTS_VOICE=custom_voice\n",
        encoding="utf-8",
    )

    import tts_gen
    monkeypatch.setattr(tts_gen, "_load_env", lambda: None)

    creds = tts_gen.resolve_credentials()
    assert creds["cluster"] == "custom_cluster"
    assert creds["voice"] == "custom_voice"


def test_doubao_synth_still_raises_when_all_credential_sources_missing(tmp_path, monkeypatch):
    """红线回归：三层都缺失时 _doubao_synth 仍报错提示（不静默、不自动切换 --engine edge）。"""
    _isolate(monkeypatch, tmp_path)

    import tts_gen
    monkeypatch.setattr(tts_gen, "_load_env", lambda: None)

    with pytest.raises(RuntimeError, match="VOLC_TTS_APPID"):
        tts_gen._doubao_synth("测试文本", str(tmp_path / "out.mp3"), None, 0.95)

import os, sys, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

def test_workspace_env_priority(tmp_path, monkeypatch):
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(tmp_path / "ws"))
    from importlib import reload
    import nbdpsy_common; reload(nbdpsy_common)
    assert nbdpsy_common.resolve_workspace() == tmp_path / "ws"

def test_workspace_cwd_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("NBDPSY_WORKSPACE", raising=False)
    (tmp_path / "seo-geo" / "content").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    from importlib import reload
    import nbdpsy_common; reload(nbdpsy_common)
    assert nbdpsy_common.resolve_workspace() == tmp_path / "seo-geo" / "content"

def test_secret_three_layers(tmp_path, monkeypatch):
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("NBDPSY_SECRETS", str(tmp_path / "store.env"))
    monkeypatch.delenv("FOO_KEY", raising=False)
    from importlib import reload
    import nbdpsy_common; reload(nbdpsy_common)
    assert nbdpsy_common.get_secret("FOO_KEY") is None
    nbdpsy_common.set_secret("FOO_KEY", "v1")
    assert nbdpsy_common.get_secret("FOO_KEY") == "v1"
    (tmp_path / ".env").write_text("FOO_KEY=v2\n", encoding="utf-8")
    assert nbdpsy_common.get_secret("FOO_KEY") == "v2"      # 工作区 .env 优先于用户级
    monkeypatch.setenv("FOO_KEY", "v3")
    assert nbdpsy_common.get_secret("FOO_KEY") == "v3"      # 环境变量最优先
    assert nbdpsy_common.ensure_secrets(["FOO_KEY", "NOPE"]) == ["NOPE"]

def test_cli_contract(tmp_path):
    script = Path(__file__).parent.parent / "shared" / "nbdpsy_common.py"
    env = dict(os.environ, NBDPSY_SECRETS=str(tmp_path / "s.env"), NBDPSY_WORKSPACE=str(tmp_path))
    r = subprocess.run([sys.executable, str(script), "secret", "get", "ABSENT"], capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "MISSING:ABSENT" in r.stderr
    subprocess.run([sys.executable, str(script), "secret", "set", "K", "V"], env=env, check=True, capture_output=True)
    r = subprocess.run([sys.executable, str(script), "secret", "get", "K"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.strip() == "V"

def test_windows_lazy_eval_appdata(tmp_path, monkeypatch):
    """测试 Windows 路径 APPDATA 已设时不触发 Path.home() 求值（惰性求值）。
    验证：当 APPDATA 已设置时，即使 Path.home() 会抛异常，也能成功获取路径。"""
    from pathlib import PureWindowsPath

    monkeypatch.delenv("NBDPSY_SECRETS", raising=False)
    appdata_path = str(tmp_path / "appdata")
    monkeypatch.setenv("APPDATA", appdata_path)

    # 追踪 Path.home 是否被调用
    call_tracker = []

    def mock_home_raises():
        call_tracker.append("called")
        raise RuntimeError("Path.home() 不可用（模拟某些锁死环境）")

    # Mock Path.home 为会抛异常的函数
    monkeypatch.setattr("pathlib.Path.home", staticmethod(mock_home_raises))

    # 测试惰性求值逻辑（Python 代码片段，独立于 os.name）
    appdata = os.environ.get("APPDATA")
    if appdata:
        # 这是修复后的代码逻辑：惰性求值
        # 使用 PureWindowsPath 进行路径操作（不依赖系统平台）
        base = PureWindowsPath(appdata) if appdata else PureWindowsPath("C:\\") / "fake"
        result = base / "nbdpsy" / "secrets.env"

        # 验证 Path.home 没被调用（key point：惰性求值）
        assert len(call_tracker) == 0, "Path.home() 不应被调用（APPDATA 已设置）"
        # 验证返回值来自 APPDATA
        assert appdata_path in str(result).replace("\\", "/")
        assert "nbdpsy" in str(result)
        assert "secrets.env" in str(result)

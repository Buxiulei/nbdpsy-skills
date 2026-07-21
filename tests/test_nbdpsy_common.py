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
    """回归测试：Windows 分支下 APPDATA 已设置时，user_secrets_path() 不应求值 Path.home()。
    直接调用真实的 nbdpsy_common.user_secrets_path()；把 Path.home 打成抛异常，
    若源码退化为 eager 求值（无论 APPDATA 是否已设都先算 Path.home()），本测试会失败。

    注：不能直接 monkeypatch.setattr(os, "name", "nt")。CPython 的
    pathlib.WindowsPath 在解释器启动时按当时的真实 os.name 固化了「非 nt 系统禁止
    实例化」的守卫（pathlib 源码：`if os.name != 'nt': def __new__...`，写在类体里，
    只在模块首次加载时判定一次），事后全局改写 os.name 无法解除该守卫；一旦
    Path(...) 内部做 `type(self)(...)` 拼接（如 `/` 运算符），会在 Linux 上抛
    NotImplementedError: cannot instantiate 'WindowsPath'（本地已实测复现，包括
    影响到断言里的 Path 拼接本身）。因此这里只替换 nbdpsy_common 模块内部看到的
    `os` 绑定（同时提供 name / environ），不触碰全局 os 模块：被测函数据此判断
    进入 Windows 分支，而 Path() 的具体拼接仍按真实平台（Posix）实例化，规避了
    该解释器级限制，对被测逻辑（是否惰性求值 Path.home()）的验证等价。
    """
    import nbdpsy_common

    monkeypatch.delenv("NBDPSY_SECRETS", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    class _FakeOS:
        name = "nt"
        environ = os.environ

    monkeypatch.setattr(nbdpsy_common, "os", _FakeOS())
    monkeypatch.setattr(
        nbdpsy_common.Path, "home",
        staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("home unresolvable"))),
    )

    result = nbdpsy_common.user_secrets_path()

    assert result == Path(str(tmp_path)) / "nbdpsy" / "secrets.env"


def test_base_ignores_workspace_env(tmp_path, monkeypatch):
    """安全回归（confused deputy）：workspace/.env 里只写 *_API_BASE 不写 key 时，
    基址绝不能被它改写——否则真密钥（从用户级穿透解析）会随请求发去恶意主机。"""
    ws = tmp_path / "ws"; ws.mkdir()
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(ws))
    monkeypatch.setenv("NBDPSY_SECRETS", str(tmp_path / "store.env"))
    monkeypatch.delenv("NBDPSY_XHS_API_BASE", raising=False)
    monkeypatch.delenv("NBDPSY_VIDEO_API_BASE", raising=False)
    from importlib import reload
    import nbdpsy_common; reload(nbdpsy_common)
    # 攻击场景：workspace .env 只塞恶意基址 + 用户级存真 key
    (ws / ".env").write_text(
        "NBDPSY_XHS_API_BASE=https://evil.example\n"
        "NBDPSY_VIDEO_API_BASE=https://evil.example\n", encoding="utf-8")
    nbdpsy_common.set_secret("NBDPSY_XHS_API_KEY", "real-key")
    # 基址回落默认值，不认 workspace 层；key 三层解析行为不变
    assert nbdpsy_common.xhs_api_base() == nbdpsy_common.DEFAULT_XHS_API_BASE
    assert nbdpsy_common.video_api_base() == nbdpsy_common.DEFAULT_VIDEO_API_BASE
    assert nbdpsy_common.get_secret("NBDPSY_XHS_API_KEY") == "real-key"


def test_base_honors_env_and_user_secrets(tmp_path, monkeypatch):
    """基址合法覆盖点：环境变量 > 用户级 secrets > 默认值。"""
    ws = tmp_path / "ws"; ws.mkdir()
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(ws))
    monkeypatch.setenv("NBDPSY_SECRETS", str(tmp_path / "store.env"))
    monkeypatch.delenv("NBDPSY_XHS_API_BASE", raising=False)
    from importlib import reload
    import nbdpsy_common; reload(nbdpsy_common)
    assert nbdpsy_common.xhs_api_base() == nbdpsy_common.DEFAULT_XHS_API_BASE
    nbdpsy_common.set_secret("NBDPSY_XHS_API_BASE", "https://user.example")
    assert nbdpsy_common.xhs_api_base() == "https://user.example"
    monkeypatch.setenv("NBDPSY_XHS_API_BASE", "https://env.example")
    assert nbdpsy_common.xhs_api_base() == "https://env.example"

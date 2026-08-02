"""服务号运营（nbdpsy-fuwuhao-operator）在共享层的凭据/基址契约。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

ROOT = Path(__file__).parent.parent


def test_fuwuhao_registered_in_installers_and_plugin():
    """skill 目录在仓库里 ≠ 装得到：漏进清单就是「本地跑得通、运营装完没有」。"""
    assert "nbdpsy-fuwuhao-operator" in (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "./nbdpsy-fuwuhao-operator" in (
        ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")


def _fresh(tmp_path, monkeypatch):
    """把凭据与工作区都关进 tmp，再拿一份干净的模块。"""
    ws = tmp_path / "ws"; ws.mkdir(exist_ok=True)
    monkeypatch.setenv("NBDPSY_WORKSPACE", str(ws))
    monkeypatch.setenv("NBDPSY_SECRETS", str(tmp_path / "store.env"))
    monkeypatch.delenv("NBDPSY_WECHAT_API_BASE", raising=False)
    from importlib import reload
    import nbdpsy_common; reload(nbdpsy_common)
    return nbdpsy_common, ws


def test_wechat_api_base_default(tmp_path, monkeypatch):
    """默认基址是生产后端——微信换 token 认它的固定出口 IP，指错主机必被 40164 拦。"""
    nc, _ = _fresh(tmp_path, monkeypatch)
    assert nc.DEFAULT_WECHAT_API_BASE == "https://database.nbdpsy.com"
    assert nc.wechat_api_base() == "https://database.nbdpsy.com"
    assert nc.WECHAT_API_KEY == "NBDPSY_WECHAT_API_KEY"
    assert nc.WECHAT_API_BASE_KEY == "NBDPSY_WECHAT_API_BASE"


def test_wechat_api_base_honors_env_and_user_secrets(tmp_path, monkeypatch):
    """合法覆盖点：环境变量 > 用户级 secrets > 默认值。"""
    nc, _ = _fresh(tmp_path, monkeypatch)
    nc.set_secret("NBDPSY_WECHAT_API_BASE", "https://user.example")
    assert nc.wechat_api_base() == "https://user.example"
    monkeypatch.setenv("NBDPSY_WECHAT_API_BASE", "https://env.example")
    assert nc.wechat_api_base() == "https://env.example"


def test_wechat_api_base_ignores_workspace_env(tmp_path, monkeypatch):
    """confused deputy：工作区 .env 可能随内容产物到达，绝不能靠它改写基址，
    否则只写 base、不写 key 的恶意 .env 就能把用户级真 key 送去别人的主机。"""
    nc, ws = _fresh(tmp_path, monkeypatch)
    (ws / ".env").write_text(
        "NBDPSY_TEST_DUMMY=x\n"                              # 正向对照，见下
        "NBDPSY_WECHAT_API_BASE=https://evil.example\n", encoding="utf-8")
    nc.set_secret("NBDPSY_WECHAT_API_KEY", "real-key")
    # 正向对照：先证明这个 .env 确实在读取路径上（读得到里面的普通键），
    # 否则「基址没被改写」可能只是因为文件压根没被读，负向断言会空绿。
    assert nc.get_secret("NBDPSY_TEST_DUMMY") == "x"
    assert nc.wechat_api_base() == nc.DEFAULT_WECHAT_API_BASE  # .env 生效，基址仍不被它改写
    assert nc.get_secret("NBDPSY_WECHAT_API_KEY") == "real-key"   # key 仍走三层解析，行为不变

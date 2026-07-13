"""setup.py 纯探测函数测试：detect() / PKG_CMDS 结构 / 凭据向导缺失路径。
不真装任何系统包，只测不产生副作用（或副作用限定在 tmp_path）的纯函数。"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup as s


# ---------- detect() ----------

def test_detect_linux_with_apt(monkeypatch):
    monkeypatch.setattr(s.platform, "system", lambda: "Linux")
    monkeypatch.setattr(s.shutil, "which", lambda exe: "/usr/bin/apt-get" if exe == "apt-get" else None)
    result = s.detect()
    assert result == {"os": "linux", "pkg": "apt"}


def test_detect_darwin_with_brew(monkeypatch):
    monkeypatch.setattr(s.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(s.shutil, "which", lambda exe: "/usr/local/bin/brew" if exe == "brew" else None)
    result = s.detect()
    assert result == {"os": "darwin", "pkg": "brew"}


def test_detect_windows_with_winget(monkeypatch):
    monkeypatch.setattr(s.platform, "system", lambda: "Windows")
    monkeypatch.setattr(s.shutil, "which", lambda exe: "winget.exe" if exe == "winget" else None)
    result = s.detect()
    assert result == {"os": "windows", "pkg": "winget"}


def test_detect_windows_falls_back_to_choco(monkeypatch):
    """winget 不存在但 choco 存在时，应选 choco。"""
    monkeypatch.setattr(s.platform, "system", lambda: "Windows")
    monkeypatch.setattr(s.shutil, "which", lambda exe: "choco.exe" if exe == "choco" else None)
    result = s.detect()
    assert result == {"os": "windows", "pkg": "choco"}


def test_detect_no_pkg_manager(monkeypatch):
    """三平台都探测不到包管理器时 pkg 应为 'none'，不应抛异常。"""
    monkeypatch.setattr(s.platform, "system", lambda: "Linux")
    monkeypatch.setattr(s.shutil, "which", lambda exe: None)
    result = s.detect()
    assert result == {"os": "linux", "pkg": "none"}


def test_detect_returns_dict_with_expected_keys(monkeypatch):
    monkeypatch.setattr(s.platform, "system", lambda: "Linux")
    monkeypatch.setattr(s.shutil, "which", lambda exe: None)
    result = s.detect()
    assert set(result.keys()) == {"os", "pkg"}


# ---------- PKG_CMDS / FONT_HINTS 结构 ----------

def test_pkg_cmds_covers_three_platform_keys():
    """PKG_CMDS 每一项的安装命令字典必须覆盖 apt/brew/winget/choco 四个包管理器键。"""
    required_keys = {"apt", "brew", "winget", "choco"}
    assert len(s.PKG_CMDS) > 0
    for name, (exe, cmds) in s.PKG_CMDS.items():
        assert isinstance(exe, str) and exe
        assert required_keys.issubset(cmds.keys()), f"{name} 缺少安装命令键：{required_keys - cmds.keys()}"
        for pkg, cmd in cmds.items():
            assert isinstance(cmd, str) and cmd.strip()


def test_font_hints_covers_apt_brew_winget():
    assert set(s.FONT_HINTS.keys()) >= {"apt", "brew", "winget"}
    for pkg, hint in s.FONT_HINTS.items():
        assert isinstance(hint, str) and hint.strip()


def test_credentials_structure():
    """CREDENTIALS 每项是 (KEY, 是否必需:bool, 说明:str)，且必需项至少含 NBDPSY_BLOG_API_KEY。"""
    keys = {k for k, _, _ in s.CREDENTIALS}
    assert "NBDPSY_BLOG_API_KEY" in keys
    required = {k for k, req, _ in s.CREDENTIALS if req}
    assert "NBDPSY_BLOG_API_KEY" in required
    for key, required_flag, desc in s.CREDENTIALS:
        assert isinstance(key, str) and key
        assert isinstance(required_flag, bool)
        assert isinstance(desc, str) and desc


def test_volc_credentials_describe_edge_engine_fallback():
    """控制器契约更正：VOLC 各项说明文案必须提到显式 --engine edge，不能暗示"自动回退"。
    三项：新版单一 VOLC_TTS_API_KEY + 旧版 VOLC_TTS_APPID/VOLC_TTS_ACCESS_TOKEN。"""
    volc_descs = [desc for k, _, desc in s.CREDENTIALS if k.startswith("VOLC_TTS_")]
    assert len(volc_descs) == 3
    for desc in volc_descs:
        assert "--engine edge" in desc
        assert "跳过" in desc


def test_volc_api_key_credential_precedes_legacy_pair():
    """VOLC_TTS_API_KEY 是新版单一凭据，应排在旧版 appid/token 之前（向导优先问新凭据）。"""
    keys = [k for k, _, _ in s.CREDENTIALS]
    assert keys.index("VOLC_TTS_API_KEY") < keys.index("VOLC_TTS_APPID") < keys.index("VOLC_TTS_ACCESS_TOKEN")


# ---------- 凭据向导缺失路径 ----------

def test_credential_wizard_reports_missing_required_as_fail(tmp_path, monkeypatch):
    """必需凭据缺失、非交互模式（interactive=False）→ 标记 ✗，且绝不调用 input()。"""
    secrets_file = tmp_path / "secrets.env"
    monkeypatch.setenv("NBDPSY_SECRETS", str(secrets_file))
    monkeypatch.delenv("NBDPSY_BLOG_API_KEY", raising=False)
    monkeypatch.delenv("VOLC_TTS_API_KEY", raising=False)
    monkeypatch.delenv("VOLC_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLC_TTS_ACCESS_TOKEN", raising=False)

    def _boom(prompt=""):
        raise AssertionError("非交互模式不应调用 input()")

    monkeypatch.setattr(s, "input", _boom, raising=False)
    monkeypatch.setattr("builtins.input", _boom)

    results = s.credential_wizard(interactive=False)
    by_key = {k: (mark, detail) for k, mark, detail in results}
    assert by_key["NBDPSY_BLOG_API_KEY"][0] == "✗"
    assert by_key["VOLC_TTS_API_KEY"][0] == "跳过"
    assert by_key["VOLC_TTS_APPID"][0] == "跳过"
    assert by_key["VOLC_TTS_ACCESS_TOKEN"][0] == "跳过"


def test_credential_wizard_interactive_records_input(tmp_path, monkeypatch):
    """交互模式下缺失凭据 → input() 明文输入 → set_secret 写入用户级凭据文件 → 再次 get_secret 命中。"""
    secrets_file = tmp_path / "secrets.env"
    monkeypatch.setenv("NBDPSY_SECRETS", str(secrets_file))
    monkeypatch.delenv("NBDPSY_BLOG_API_KEY", raising=False)
    monkeypatch.delenv("VOLC_TTS_API_KEY", raising=False)
    monkeypatch.delenv("VOLC_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLC_TTS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("NBDPSY_XHS_API_KEY", raising=False)

    answers = iter([""] * (len(s.CREDENTIALS) - 1))  # 除第一项外全部留空跳过
    monkeypatch.setattr("builtins.input",
                        lambda prompt="": "sk-test-12345" if "NBDPSY_BLOG_API_KEY" in prompt else next(answers))

    results = s.credential_wizard(interactive=True)
    by_key = {k: (mark, detail) for k, mark, detail in results}
    assert by_key["NBDPSY_BLOG_API_KEY"][0] == "✓"
    assert by_key["VOLC_TTS_API_KEY"][0] == "跳过"  # 可选项留空 → 跳过而非 ✗
    assert by_key["VOLC_TTS_APPID"][0] == "跳过"  # 可选项留空 → 跳过而非 ✗
    assert by_key["NBDPSY_XHS_API_KEY"][0] == "跳过"  # 可选项留空 → 跳过而非 ✗

    # 凭据已落盘到用户级文件，且第二次探测能读到（不重复问）
    assert secrets_file.is_file()
    assert "NBDPSY_BLOG_API_KEY=sk-test-12345" in secrets_file.read_text(encoding="utf-8")
    assert s.nbdpsy_common.get_secret("NBDPSY_BLOG_API_KEY") == "sk-test-12345"


def test_credential_wizard_never_echoes_existing_value(tmp_path, monkeypatch):
    """已存在的凭据只报「已配置」，绝不在 detail 里回显真实值；且不会为它重新调用 input()
    （其余未配置的可选项仍允许被询问，此处一律留空跳过）。"""
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("NBDPSY_BLOG_API_KEY=super-secret-value\n", encoding="utf-8")
    monkeypatch.setenv("NBDPSY_SECRETS", str(secrets_file))
    monkeypatch.delenv("VOLC_TTS_APPID", raising=False)
    monkeypatch.delenv("VOLC_TTS_ACCESS_TOKEN", raising=False)

    def _fake_input(prompt=""):
        assert "NBDPSY_BLOG_API_KEY" not in prompt, "已配置的凭据不应再询问"
        return ""

    monkeypatch.setattr("builtins.input", _fake_input)

    results = s.credential_wizard(interactive=True)
    by_key = {k: (mark, detail) for k, mark, detail in results}
    mark, detail = by_key["NBDPSY_BLOG_API_KEY"]
    assert mark == "✓"
    assert "super-secret-value" not in detail
    assert detail == "已配置"


# ---------- 小工具函数 ----------

def test_pick_cmd_prefers_detected_pkg():
    cmds = {"apt": "A", "brew": "B", "winget": "W", "choco": "C"}
    assert s._pick_cmd(cmds, {"os": "linux", "pkg": "apt"}) == "A"


def test_pick_cmd_falls_back_when_no_pkg_manager():
    """pkg == 'none' 时按操作系统的常见包管理器给提示，而不是抛异常。"""
    cmds = {"apt": "A", "brew": "B", "winget": "W", "choco": "C"}
    assert s._pick_cmd(cmds, {"os": "linux", "pkg": "none"}) == "A"
    assert s._pick_cmd(cmds, {"os": "darwin", "pkg": "none"}) == "B"
    assert s._pick_cmd(cmds, {"os": "windows", "pkg": "none"}) == "W"


def test_maybe_noninteractive_sudo_interactive_mode_no_flag():
    """交互模式（interactive=True）时，sudo 命令保留普通形式，不加 -n。"""
    cmd = "sudo apt-get install -y ffmpeg"
    assert s._maybe_noninteractive_sudo(cmd, interactive=True) == cmd


def test_maybe_noninteractive_sudo_noninteractive_mode_adds_flag():
    """非交互模式（interactive=False）时，sudo 命令加 -n 标志。"""
    cmd = "sudo apt-get install -y ffmpeg"
    assert s._maybe_noninteractive_sudo(cmd, interactive=False) == "sudo -n apt-get install -y ffmpeg"


def test_maybe_noninteractive_sudo_leaves_non_sudo_commands_untouched():
    """非 sudo 命令无论何种模式都不改。"""
    assert s._maybe_noninteractive_sudo("brew install ffmpeg", interactive=True) == "brew install ffmpeg"
    assert s._maybe_noninteractive_sudo("brew install ffmpeg", interactive=False) == "brew install ffmpeg"
    assert s._maybe_noninteractive_sudo("winget install --id Gyan.FFmpeg -e", interactive=True) == "winget install --id Gyan.FFmpeg -e"
    assert s._maybe_noninteractive_sudo("winget install --id Gyan.FFmpeg -e", interactive=False) == "winget install --id Gyan.FFmpeg -e"

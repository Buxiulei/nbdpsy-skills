import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"))

import dreamina_login

# headless 模式设备流的真实样例输出（每行一项，管道读到的是完整逻辑行）。
# 注意 verification_uri 的值本身内含 URL 编码的 user_code%3D... 与 verification_uri=...，
# 用来验证解析既不被折行截断、也不误配到内嵌子串。
SAMPLE = (
    "用浏览器完成 OAuth Device Flow 登录。\n"
    "verification_uri: https://jimeng.jianying.com/xxx/cli-auth?"
    "verification_uri=https%3A%2F%2Fexample%2Fauth%3Fuser_code%3Df0ae9d9c98366db7f4fd780faf079501\n"
    "user_code: f0ae9d9c98366db7f4fd780faf079501\n"
    "device_code: 9291866a924a3b61768d8ec250b21b55\n"
    "interval: 1s\n"
    "expires_at: 2026-07-20T18:01:24+08:00\n"
)


def test_parse_extracts_full_uri_and_code():
    f = dreamina_login.parse_device_flow(SAMPLE)
    # 完整 URL：起始正确、内嵌 user_code 参数完整未被折行截断
    assert f["verification_uri"].startswith("https://jimeng.jianying.com/xxx/cli-auth?")
    assert "user_code%3Df0ae9d9c98366db7f4fd780faf079501" in f["verification_uri"]
    assert f["user_code"] == "f0ae9d9c98366db7f4fd780faf079501"


def test_parse_ignores_distractors_and_missing():
    f = dreamina_login.parse_device_flow("随便一行\nfoo: bar\ndevice_code: abc\n")
    assert f["verification_uri"] is None and f["user_code"] is None


def test_parse_partial_only_user_code():
    f = dreamina_login.parse_device_flow("user_code: abc123\n")
    assert f["user_code"] == "abc123" and f["verification_uri"] is None


def test_select_mode_windows():
    # Windows：无论有无 DISPLAY 都走 browser
    assert dreamina_login.select_mode(os_name="nt", platform="win32", env={}) == "browser"
    assert dreamina_login.select_mode(os_name="nt", platform="win32",
                                      env={"DISPLAY": ":0"}) == "browser"


def test_select_mode_macos():
    assert dreamina_login.select_mode(os_name="posix", platform="darwin", env={}) == "browser"


def test_select_mode_linux_with_display():
    assert dreamina_login.select_mode(os_name="posix", platform="linux",
                                      env={"DISPLAY": ":0"}) == "browser"


def test_select_mode_linux_wayland():
    assert dreamina_login.select_mode(os_name="posix", platform="linux",
                                      env={"WAYLAND_DISPLAY": "wayland-0"}) == "browser"


def test_select_mode_linux_headless():
    assert dreamina_login.select_mode(os_name="posix", platform="linux", env={}) == "headless"

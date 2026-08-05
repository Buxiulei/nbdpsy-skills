"""dreamina_login OAuth Device Flow 测试（全离线：假子进程 + 假浏览器，绝不跑真 CLI/不弹窗）。

钉死的是 2026-08-05 实测的新版 CLI（a857341 起）stdout 形态：脚本抓 verification_uri
开给用户 → 等 CLI 自己轮询到授权完成并退出 → 用 user_credit 复核登录态。
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"))

import pytest

import dreamina_login as dl

# 2026-08-05 实测新版 CLI 的 stdout 原文形态（授权网址自身的查询参数里也带 verification_uri=）
REAL_URI = ("https://jimeng.jianying.com/ai-tool/cli-auth"
            "?verification_uri=https%3A%2F%2Fjimeng.jianying.com%2Fai-tool%2Fcli-auth"
            "&user_code=bf065a38aa2909467cd784c523709763")
REAL_CODE = "bf065a38aa2909467cd784c523709763"
REAL_EXPIRES = "2026-08-05T15:56:26+08:00"
REAL_LINES = [
    "请使用浏览器完成 OAuth Device Flow 登录。\n",
    f"verification_uri: {REAL_URI}\n",
    f"user_code: {REAL_CODE}\n",
    "poll_interval: 1s\n",
    f"expires_at: {REAL_EXPIRES}\n",
]
EXPIRED_TAIL = "登录已过期，请重新执行 dreamina login\n"
CREDIT = {"total_credit": 15060, "vip_level": 3}


# ---------- 假件 ----------

class _Stdout:
    """可迭代 stdout：喂完预置行后，block 秒内不关闭（模拟 CLI 还在跑、还没退出）。"""

    def __init__(self, lines, block=None):
        self._lines, self._block = list(lines), block

    def __iter__(self):
        for line in self._lines:
            yield line
        if self._block:
            threading.Event().wait(self._block)


class FakeProc:
    """假 dreamina login 子进程。block 非空 = 进程还活着（poll 回 None）。"""

    def __init__(self, lines, returncode=0, block=None):
        self.stdout = _Stdout(lines, block)
        self.returncode = returncode
        self._alive = block is not None
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else self.returncode

    def wait(self, timeout=None):
        if self._alive:
            raise subprocess.TimeoutExpired("dreamina", timeout or 0)
        return self.returncode

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True


def fake_popen(monkeypatch, lines, returncode=0, *, block=None):
    """把 dreamina login 换成假子进程，返回记录（argv / proc）。"""
    rec = {}

    def _popen(argv, **kw):
        rec["argv"] = argv
        rec["proc"] = FakeProc(lines, returncode, block=block)
        return rec["proc"]

    monkeypatch.setattr(dl.subprocess, "Popen", _popen)
    return rec


def fake_browser(monkeypatch, result=True, boom=False):
    """假浏览器：记录被开的网址；boom=True 复刻无图形环境下 webbrowser.open 直接抛异常。"""
    opened = []

    def _open(url, *a, **kw):
        opened.append(url)
        if boom:
            raise RuntimeError("could not locate runnable browser")
        return result

    monkeypatch.setattr(dl.webbrowser, "open", _open)
    return opened


def fake_credit(monkeypatch, data=None):
    monkeypatch.setattr(dl, "query_credit", lambda *a, **k: data)


# ---------- 1. 解析实测 stdout ----------

def test_parse_real_cli_output_extracts_url_code_and_expiry():
    info = {}
    for line in REAL_LINES:
        dl.parse_login_line(line, info)
    assert info["verification_uri"] == REAL_URI      # 整条网址（含查询参数）一字不落
    assert info["user_code"] == REAL_CODE
    assert info["expires_at"] == REAL_EXPIRES


def test_parse_requires_scheme_and_ignores_noise():
    """只认 `verification_uri: http(s)://…`：日志噪声行与网址自身的 `verification_uri=` 参数
    都不许被当成网址截出来（截错了用户打开的就是半个链接）。"""
    info = {}
    dl.parse_login_line("INFO 正在准备 verification_uri: 稍候\n", info)
    dl.parse_login_line("callback verification_uri=https://evil.example/x\n", info)
    assert "verification_uri" not in info
    dl.parse_login_line(f"verification_uri: {REAL_URI}\n", info)
    assert info["verification_uri"] == REAL_URI


def test_parse_keeps_first_hit():
    """一次登录只有一组码；后来的行不许覆盖已抓到的（CLI 重印或噪声不该换掉用户手上那个）。"""
    info = {"user_code": REAL_CODE}
    dl.parse_login_line("user_code: 0000\n", info)
    assert info["user_code"] == REAL_CODE


# ---------- 2. 成功链：开页 → 等退出 → user_credit 复核 ----------

def test_login_presents_url_and_verifies_with_user_credit(monkeypatch, capsys):
    rec = fake_popen(monkeypatch, REAL_LINES, 0)
    opened = fake_browser(monkeypatch)
    fake_credit(monkeypatch, CREDIT)

    result = dl.login()

    assert result == {"success": True, "total_credit": 15060, "vip_level": 3}
    assert rec["argv"] == [dl.DREAMINA, "login"]
    assert opened == [REAL_URI]                         # 尽力弹本机浏览器
    err = capsys.readouterr().err
    assert REAL_URI in err                              # 网址完整单独一行，供任何设备打开
    assert "任何设备" in err and "抖音 App" in err
    assert "10 分钟" in err and REAL_EXPIRES in err     # 过期提示带上 expires_at
    assert REAL_CODE in err


def test_login_succeeds_even_if_browser_cannot_open(monkeypatch, capsys):
    """没图形环境（服务器/WSL）时 webbrowser.open 抛异常不算失败——网址照样给到人。"""
    fake_popen(monkeypatch, REAL_LINES, 0)
    fake_browser(monkeypatch, boom=True)
    fake_credit(monkeypatch, CREDIT)

    result = dl.login()

    assert result["success"] is True
    err = capsys.readouterr().err
    assert REAL_URI in err and "手动打开" in err


def test_login_exit_zero_but_credit_unreadable_is_failure(monkeypatch):
    """退出码 0 不等于登录成功——登录态一律以能不能读到积分为准。"""
    fake_popen(monkeypatch, REAL_LINES, 0)
    fake_browser(monkeypatch)
    fake_credit(monkeypatch, None)
    result = dl.login()
    assert result["success"] is False and result["hint"] == dl.RERUN_HINT


# ---------- 3. 过期链 ----------

def test_login_expired_reports_cli_reason_and_rerun_hint(monkeypatch):
    fake_popen(monkeypatch, REAL_LINES + [EXPIRED_TAIL], 1)
    fake_browser(monkeypatch)
    fake_credit(monkeypatch, None)

    result = dl.login()

    assert result["success"] is False
    assert "登录已过期" in result["error"]               # CLI 尾行原文透出
    assert result["hint"] == dl.RERUN_HINT
    assert "total_credit" not in result


def test_login_times_out_waiting_for_authorization(monkeypatch):
    """用户一直不授权：不能挂死，收工并让人重跑拿新码；子进程必须被结束掉。"""
    rec = fake_popen(monkeypatch, REAL_LINES, 0, block=5)
    fake_browser(monkeypatch)
    fake_credit(monkeypatch, None)

    result = dl.login(login_wait=0.2)

    assert result["success"] is False and "等待授权" in result["error"]
    assert result["hint"] == dl.RERUN_HINT
    assert rec["proc"].terminated is True


# ---------- 4. 老版 CLI / 异常：给升级命令 ----------

def test_no_verification_uri_within_timeout_points_at_upgrade(monkeypatch):
    """30s 没等到 verification_uri = 这版 CLI 还是旧回调流（或异常）——必须给升级命令，
    不能让运营对着一个永远不出网址的进程干等。"""
    rec = fake_popen(monkeypatch, ["[RunLogin] start login flow port=60713\n"], 0, block=5)
    opened = fake_browser(monkeypatch)
    fake_credit(monkeypatch, None)

    result = dl.login(url_wait=0.2)

    assert result["success"] is False
    assert "verification_uri" in result["error"]
    assert dl.INSTALL_CMD in result["hint"]
    assert opened == [], "没网址就没有可开的页面"
    assert rec["proc"].terminated is True


def test_exits_without_url_and_without_login_points_at_upgrade(monkeypatch):
    fake_popen(monkeypatch, ["unknown command: login\n"], 2)
    fake_browser(monkeypatch)
    fake_credit(monkeypatch, None)
    result = dl.login()
    assert result["success"] is False and dl.INSTALL_CMD in result["hint"]


def test_exits_without_url_but_already_logged_in_is_success(monkeypatch, capsys):
    """幂等重跑：本来就登录着的话 CLI 可能不走授权直接退出——复核到积分就当成功，别报错。"""
    fake_popen(monkeypatch, [], 0)
    opened = fake_browser(monkeypatch)
    fake_credit(monkeypatch, CREDIT)

    result = dl.login()

    assert result == {"success": True, "total_credit": 15060, "vip_level": 3}
    assert opened == []
    assert "已是登录态" in capsys.readouterr().err


def test_launch_failure_is_reported_not_raised(monkeypatch):
    def _boom(argv, **kw):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(dl.subprocess, "Popen", _boom)
    result = dl.login()
    assert result["success"] is False and "启动 dreamina login 失败" in result["error"]


# ---------- 5. query_credit：登录态判据 ----------

def test_query_credit_parses_user_credit_json(monkeypatch):
    monkeypatch.setattr(dl.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0] if a else [], 0, json.dumps(CREDIT), ""))
    assert dl.query_credit() == CREDIT


@pytest.mark.parametrize("stdout", ["", "not json", "{}", '{"total_credit": null}', "[]"])
def test_query_credit_returns_none_when_not_logged_in(monkeypatch, stdout):
    monkeypatch.setattr(dl.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0] if a else [], 1, stdout, "not logged in"))
    assert dl.query_credit() is None


def test_query_credit_survives_cli_blowing_up(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired("dreamina", 30)

    monkeypatch.setattr(dl.subprocess, "run", _boom)
    assert dl.query_credit() is None


# ---------- 6. main：CLI 未装 / --check-only / 退出码 ----------

def run_main(monkeypatch, capsys, argv):
    monkeypatch.setattr(sys, "argv", ["dreamina_login.py", *argv])
    with pytest.raises(SystemExit) as exc:
        dl.main()
    return exc.value.code, json.loads(capsys.readouterr().out)


def test_main_without_cli_installed_gives_install_command(monkeypatch, capsys):
    monkeypatch.setattr(dl, "cli_installed", lambda: False)
    code, out = run_main(monkeypatch, capsys, [])
    assert code == 1 and out["success"] is False
    assert dl.INSTALL_CMD in out["hint"]


def test_main_check_only_logged_in(monkeypatch, capsys):
    monkeypatch.setattr(dl, "cli_installed", lambda: True)
    fake_credit(monkeypatch, CREDIT)
    monkeypatch.setattr(dl, "login", lambda *a, **k: pytest.fail("--check-only 不该发起登录"))
    code, out = run_main(monkeypatch, capsys, ["--check-only"])
    assert code == 0
    assert out == {"success": True, "total_credit": 15060, "vip_level": 3}


def test_main_check_only_logged_out(monkeypatch, capsys):
    monkeypatch.setattr(dl, "cli_installed", lambda: True)
    fake_credit(monkeypatch, None)
    code, out = run_main(monkeypatch, capsys, ["--check-only"])
    assert code == 1 and out["success"] is False and out["error"] == "未登录"


def test_main_login_success_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(dl, "cli_installed", lambda: True)
    monkeypatch.setattr(dl, "login", lambda *a, **k: {"success": True, "total_credit": 1,
                                                     "vip_level": 0})
    code, out = run_main(monkeypatch, capsys, [])
    assert code == 0 and out["success"] is True


# ---------- 7. 旧回调流不许复活 ----------

def test_callback_flow_helpers_are_gone():
    """旧版那套（本地 127.0.0.1 回调服务器 + opener shim 拦 xdg-open + 日志抓 port +
    credential.json 拼网址）对新 CLI 全部无效——复活它就是让运营对着死链扫码。"""
    for dead in ("install_opener_shim", "read_captured_url", "find_login_port",
                 "read_secret_key", "rebuild_login_url", "build_login_url", "OPENER_NAMES"):
        assert not hasattr(dl, dead), dead

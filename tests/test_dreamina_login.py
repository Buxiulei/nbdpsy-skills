import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-text-to-video" / "scripts"))

import dreamina_login

# 2026-07-29 实测拦到的真实登录网址（隔离 HOME 跑 dreamina login，PATH 前置假 xdg-open）。
# 端口 60713 与 secret 同时出现在日志与 credential.json 里——本文件就是钉死这份对应关系。
REAL_URL = ("https://jimeng.jianying.com/ai-tool/login"
            "?callback=http%3A%2F%2F127.0.0.1%3A60713%2Fdreamina%2Fcallback%2Fsave_session"
            "&from=cli&random_secret_key=02517e9c0d60060d11f3165602616e4b")
REAL_SECRET = "02517e9c0d60060d11f3165602616e4b"
REAL_LOG_LINE = ("INFO 2026-07-29T11:27:34+08:00 service.go:199 [RunLogin] start login flow "
                 "mode=reuse_if_valid port=60713 debug=false logid=2026072911273419 submit_id=-")


def _log_line(ts: datetime, port: int) -> str:
    return (f"INFO {ts.isoformat()} service.go:199 [RunLogin] start login flow "
            f"mode=reuse_if_valid port={port} debug=false logid=x submit_id=-")


# ---------- 网址拼装：与实测字节级一致 ----------

def test_build_url_matches_real_capture():
    assert dreamina_login.build_login_url(60713, REAL_SECRET) == REAL_URL


def test_build_url_encodes_callback_wholesale():
    # callback 必须整体百分号编码（连 :// 一起），漏编即梦侧会当成另一个回调地址
    url = dreamina_login.build_login_url(1234, "s")
    assert "callback=http%3A%2F%2F127.0.0.1%3A1234%2F" in url
    assert "callback=http://" not in url


# ---------- 日志取端口：只认本次登录流 ----------

def test_find_port_reads_real_log_line(tmp_path):
    (tmp_path / "a.log").write_text(REAL_LOG_LINE + "\n", encoding="utf-8")
    since = datetime.fromisoformat("2026-07-29T11:00:00+08:00")
    assert dreamina_login.find_login_port(since, logdir=tmp_path) == 60713


def test_find_port_ignores_previous_run(tmp_path):
    """同一小时的日志里压着上一次登录的旧端口——照旧端口拼网址会让用户扫完仍卡住。"""
    now = datetime.now().astimezone()
    (tmp_path / "11.log").write_text(
        _log_line(now - timedelta(minutes=30), 50001) + "\n"
        + _log_line(now, 60713) + "\n", encoding="utf-8")
    assert dreamina_login.find_login_port(now - timedelta(seconds=5), logdir=tmp_path) == 60713


def test_find_port_survives_second_granularity(tmp_path):
    """日志时间戳只到秒，since 带微秒：同一秒写下的本次端口不能被当成旧行丢掉
    （真踩过——兜底路会静默拿不到网址）。"""
    now = datetime.now().astimezone()
    (tmp_path / "11.log").write_text(_log_line(now.replace(microsecond=0), 60713) + "\n",
                                     encoding="utf-8")
    since = now.replace(microsecond=900000)  # 比日志行"晚" 0.9 秒，但属同一秒
    assert dreamina_login.find_login_port(since, logdir=tmp_path) == 60713


def test_find_port_returns_none_when_all_stale(tmp_path):
    now = datetime.now().astimezone()
    (tmp_path / "11.log").write_text(_log_line(now - timedelta(hours=2), 50001) + "\n",
                                     encoding="utf-8")
    assert dreamina_login.find_login_port(now, logdir=tmp_path) is None


def test_find_port_ignores_unrelated_lines(tmp_path):
    now = datetime.now().astimezone()
    (tmp_path / "11.log").write_text(
        f"INFO {now.isoformat()} service.go:250 [runBrowserLogin] start browser login port=9999\n"
        f"ERROR {now.isoformat()} service.go:359 [fetchAccountSummary] parse auth token failed\n",
        encoding="utf-8")
    assert dreamina_login.find_login_port(now - timedelta(seconds=5), logdir=tmp_path) is None


def test_find_port_missing_logdir():
    assert dreamina_login.find_login_port(datetime.now().astimezone(),
                                          logdir=Path("/nonexistent-log-dir")) is None


# ---------- credential.json 取 secret ----------

def test_read_secret_from_real_shape(tmp_path):
    f = tmp_path / "credential.json"
    f.write_text(json.dumps({"random_secret_key": REAL_SECRET}), encoding="utf-8")
    assert dreamina_login.read_secret_key(f) == REAL_SECRET


def test_read_secret_tolerates_missing_or_broken(tmp_path):
    assert dreamina_login.read_secret_key(tmp_path / "nope.json") is None
    half = tmp_path / "half.json"
    half.write_text('{"random_secret_key": "ab', encoding="utf-8")  # 半写入
    assert dreamina_login.read_secret_key(half) is None
    empty = tmp_path / "empty.json"
    empty.write_text('{"random_secret_key": ""}', encoding="utf-8")
    assert dreamina_login.read_secret_key(empty) is None


# ---------- 磁盘重建：两者齐全才算数 ----------

def test_rebuild_needs_both_parts(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".dreamina_cli" / "logs").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    now = datetime.now().astimezone()
    since = now - timedelta(seconds=5)

    # 只有日志没 secret → 不拼半个网址出来
    (home / ".dreamina_cli" / "logs" / "11.log").write_text(_log_line(now, 60713) + "\n",
                                                            encoding="utf-8")
    assert dreamina_login.rebuild_login_url(since) is None

    # 补上 secret → 拼出与实测一致的网址
    (home / ".dreamina_cli" / "credential.json").write_text(
        json.dumps({"random_secret_key": REAL_SECRET}), encoding="utf-8")
    assert dreamina_login.rebuild_login_url(since) == REAL_URL


# ---------- opener shim：真的能拦住并拿到网址 ----------

def test_opener_shim_captures_url(tmp_path):
    """端到端验 shim：装好后直接以子进程调 xdg-open，网址应落进捕获文件且不被转发。"""
    if os.name == "nt":
        return  # Windows 不装 shim，见 install_opener_shim
    shim = dreamina_login.install_opener_shim(tmp_path)
    assert shim is not None
    env_patch, capture = shim
    assert dreamina_login.read_captured_url(capture) is None  # 还没调过

    env = dict(os.environ)
    env.update(env_patch)
    subprocess.run(["xdg-open", REAL_URL], env=env, check=True, timeout=30)
    assert dreamina_login.read_captured_url(capture) == REAL_URL


def test_opener_shim_covers_all_opener_names(tmp_path):
    """CLI 按序试多个 opener，漏 shim 任何一个都会让它绕过拦截自己开浏览器。"""
    if os.name == "nt":
        return
    shim = dreamina_login.install_opener_shim(tmp_path)
    assert shim is not None
    bindir = tmp_path / "opener-shim"
    for name in dreamina_login.OPENER_NAMES:
        f = bindir / name
        assert f.exists() and os.access(f, os.X_OK), name


def test_read_captured_url_skips_noise(tmp_path):
    cap = tmp_path / "c.txt"
    cap.write_text("\n\n不是网址\n" + REAL_URL + "\n", encoding="utf-8")
    assert dreamina_login.read_captured_url(cap) == REAL_URL


def test_read_captured_url_missing_file(tmp_path):
    assert dreamina_login.read_captured_url(tmp_path / "nope.txt") is None


# ---------- 已删掉的东西不许复活 ----------

def test_headless_and_device_flow_are_gone():
    """--headless 与"设备流"解析都是已证伪的路：headless 字符二维码是 Windows 事故根因，
    verification_uri / user_code 在即梦二进制里根本不存在。"""
    for dead in ("parse_device_flow", "select_mode", "make_qr", "_chrome_missing"):
        assert not hasattr(dreamina_login, dead), dead
    src = Path(dreamina_login.__file__).read_text(encoding="utf-8")
    assert '"--headless"' not in src and "'--headless'" not in src

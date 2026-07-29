#!/usr/bin/env python3
"""nbdpsy-text-to-video skill · 即梦(dreamina) 一键登录助手。

**脚本负责把登录页开到用户面前，用户唯一动作是在页面上用抖音 App 扫码。**

## 真实登录流（2026-07-29 实测取证，勿凭想象改回"设备流"）

`dreamina login` 起一个 `127.0.0.1:<回调端口>` 的服务器（实测三次都是 60713，但**不硬编码**：
端口一律现取，被占用时官方换端口我们也不会跟丢），再调系统 opener 打开：

    https://jimeng.jianying.com/ai-tool/login
        ?callback=http%3A%2F%2F127.0.0.1%3A<端口>%2Fdreamina%2Fcallback%2Fsave_session
        &from=cli&random_secret_key=<32位hex>

用户在**这台电脑的浏览器**里扫页面上的抖音二维码 → 页面回调本地端口 → CLI 落
`~/.dreamina_cli/credential.json`。CLI 终端只印一句「已尝试打开默认浏览器」，
**不打印这个网址**，所以要自己开页面就得自己把网址弄到手。

两条已作废的路（写清楚免得再走一遍）：

- ⛔ **没有 OAuth 设备流**：整个二进制 `strings` 全扫，`verification_uri` / `user_code`
  出现 0 次。历史版本按这两个字段解析 CLI 输出，那段代码从未触发过——所谓"脚本自己开
  浏览器"一直是空转，真正开浏览器的是 CLI 自己。
- ⛔ **不再提供 `--headless`**：那是"无头 Chrome 载入登录页 + 终端画字符二维码"，要装
  google-chrome，且字符画在 Windows 终端显示不全 —— 运营反复登录失败的事故根因。
  用户都在有屏个人电脑上用，这条路整个删掉。

## 拿网址的两条路（互为备份，谁先到用谁）

A. **opener shim**（POSIX）：把假的 `xdg-open` / `open` 放进 PATH 最前，CLI 调它时把网址
   写进捕获文件。shim **只记录不转发** → 浏览器由本脚本开，全程恰好开一次。
B. **磁盘重建**（全平台兜底）：日志 `[RunLogin] start login flow ... port=<端口>` 取端口 +
   `credential.json` 的 `random_secret_key`，按固定模板拼回同一个网址。Windows 没法 shim
   系统 opener，走这条；此时 CLI 已自己开好浏览器，脚本只补网址文本，不重复弹窗。

## 为什么不生成二维码

网址里的 callback 是 `http://127.0.0.1:<端口>`。手机扫走这个网址 = 在手机浏览器登录，
回调打的是**手机自己的** 127.0.0.1，永远回不到电脑上的 CLI —— 是条死路。要扫的二维码是
即梦登录页**自己渲染的那张**，用户在电脑浏览器打开页面后用抖音扫它。

约定同目录其他脚本：stdout=最终 JSON / stderr=中文进度。

用法：
  python3 dreamina_login.py               # 开登录页等扫码（超时自动重开）
  python3 dreamina_login.py --check-only  # 只查登录态与积分，不发起登录
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def _dreamina_path() -> str:
    """dreamina 可执行路径：PATH 优先，否则平台默认落地位置（POSIX ~/.local/bin/dreamina；Windows ~/bin/dreamina.exe）。"""
    p = shutil.which("dreamina")
    if p:
        return p
    for c in ("~/.local/bin/dreamina", "~/bin/dreamina.exe"):
        e = os.path.expanduser(c)
        if Path(e).exists():
            return e
    return os.path.expanduser("~/.local/bin/dreamina")  # 占位（不存在即判未装）


DREAMINA = _dreamina_path()
POLL_INTERVAL = 4  # 轮询 user_credit 间隔（秒）
URL_TEMPLATE = ("https://jimeng.jianying.com/ai-tool/login"
                "?callback={callback}&from=cli&random_secret_key={secret}")
CALLBACK_TEMPLATE = "http://127.0.0.1:{port}/dreamina/callback/save_session"
# CLI 在 POSIX 上按序试这几个 opener，第一个成功就停；全 shim 掉才能保证由本脚本开页面
OPENER_NAMES = ("xdg-open", "open", "x-www-browser", "www-browser", "sensible-browser")
# 日志行样例：INFO 2026-07-29T11:27:34+08:00 service.go:199 [RunLogin] start login flow mode=... port=60713 ...
LOG_PORT_RE = re.compile(r"^\w+\s+(\S+)\s+\S+\s+\[RunLogin\] start login flow\b.*?\bport=(\d+)")


def cred_dir() -> Path:
    """凭据与日志目录。每次现算（不做模块级常量）：测试与隔离环境靠改 HOME 生效。"""
    return Path(os.path.expanduser("~")) / ".dreamina_cli"


def cli_installed() -> bool:
    return Path(DREAMINA).exists()


def query_credit(timeout: int = 30) -> int | None:
    """跑 dreamina user_credit，返回 total_credit（int）或 None（未登录/读不到）。"""
    try:
        p = subprocess.run([DREAMINA, "user_credit"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except Exception:  # noqa: BLE001 任何执行失败一律视作"读不到"
        return None
    try:
        credit = (json.loads(p.stdout) or {}).get("total_credit")
    except Exception:  # noqa: BLE001
        return None
    return credit if isinstance(credit, int) else None


def build_login_url(port: int | str, secret: str) -> str:
    """按实测模板拼登录网址。callback 整体百分号编码（safe="" 连 :// 一起编），
    与 CLI 自己生成的字节级一致——改这里前先重新取证，别照 URL 直觉改。"""
    callback = quote(CALLBACK_TEMPLATE.format(port=port), safe="")
    return URL_TEMPLATE.format(callback=callback, secret=secret)


def install_opener_shim(workdir: Path) -> tuple[dict, Path] | None:
    """在 workdir 造一批假 opener 并返回 (环境变量补丁, 捕获文件路径)。

    Windows 上 CLI 走系统 start/rundll32，没法用 PATH 拦（也不该拦——那儿默认浏览器
    关联本来就可靠），返回 None 表示走磁盘重建那条路。
    """
    if os.name == "nt":
        return None
    bindir = workdir / "opener-shim"
    capture = workdir / "opened-url.txt"
    try:
        bindir.mkdir(parents=True, exist_ok=True)
        for name in OPENER_NAMES:
            f = bindir / name
            f.write_text('#!/bin/sh\nprintf \'%s\\n\' "$1" >> "$DREAMINA_LOGIN_CAPTURE"\n',
                         encoding="utf-8")
            f.chmod(0o755)
    except Exception as e:  # noqa: BLE001 造不出来就降级，不算错误
        _err(f"[login] 无法安装 opener 拦截（降级为读日志重建网址）：{e}")
        return None
    env = {"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
           "DREAMINA_LOGIN_CAPTURE": str(capture)}
    return env, capture


def read_captured_url(capture: Path) -> str | None:
    """从 shim 捕获文件读第一条 http(s) 网址。"""
    try:
        text = capture.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("http"):
            return line
    return None


def _recent_logs(logdir: Path, limit: int = 3) -> list[Path]:
    """按 mtime 取最近几个日志文件（日志按 日期/小时.log 切分，跨小时会换文件）。"""
    try:
        files = [p for p in logdir.rglob("*.log") if p.is_file()]
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def find_login_port(since: datetime, logdir: Path | None = None) -> int | None:
    """从日志里找**本次**登录流的回调端口。

    只认时间戳 >= since 的行：同一个小时的日志文件里可能还压着上一次登录的旧端口，
    照旧端口拼出来的网址回调打不到当前进程，会让用户扫完了却一直卡在等待。

    ⚠️ since 先截到整秒再比：日志时间戳只精确到秒，而调用方给的是带微秒的启动时刻，
    直接比会把「与启动同一秒写下的本次端口」误判成旧行整条丢掉——兜底路会静默失效
    （2026-07-29 端到端实测踩到，单元测试因用自造时间戳而看不见）。
    """
    since = since.replace(microsecond=0)
    logdir = (cred_dir() / "logs") if logdir is None else logdir
    port: int | None = None
    for path in _recent_logs(logdir):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = LOG_PORT_RE.match(line.strip())
            if not m:
                continue
            try:
                ts = datetime.fromisoformat(m.group(1))
            except ValueError:
                continue
            if ts >= since:
                port = int(m.group(2))  # 同一文件内后出现的更新，直接覆盖
    return port


def read_secret_key(cred_file: Path | None = None) -> str | None:
    """读 credential.json 里的 random_secret_key（登录流开始时由 CLI 写入）。"""
    cred_file = (cred_dir() / "credential.json") if cred_file is None else cred_file
    try:
        data = json.loads(cred_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 文件不存在/半写入/非 JSON 都当"还没就绪"
        return None
    secret = (data or {}).get("random_secret_key")
    return secret if isinstance(secret, str) and secret else None


def rebuild_login_url(since: datetime) -> str | None:
    """磁盘重建登录网址：日志给端口，credential.json 给 secret，两者齐全才算数。"""
    port = find_login_port(since)
    secret = read_secret_key()
    if port is None or secret is None:
        return None
    return build_login_url(port, secret)


def _terminate(proc: subprocess.Popen) -> None:
    """确保子进程被结束（先 terminate，超时再 kill）。"""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _reader(proc: subprocess.Popen, q: queue.Queue) -> None:
    """后台逐行读子进程合并输出，读完投 None 哨兵。"""
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            q.put(line)
    finally:
        q.put(None)


def _present_url(url: str, shimmed: bool) -> None:
    """把登录页送到用户眼前。

    shimmed=True：CLI 的 opener 已被拦下，浏览器必须由我们开。
    shimmed=False：CLI 自己已经开过一次（Windows），再开就是第二个窗口，只补文本。
    """
    if shimmed:
        opened = False
        try:
            opened = webbrowser.open(url)
        except Exception as e:  # noqa: BLE001
            _err(f"[login] 打开浏览器失败：{e}")
        if opened:
            _err("[login] 已在你的浏览器打开即梦登录页，请用**抖音 App 扫页面上的二维码**完成登录…")
        else:
            _err("[login] 没能自动打开浏览器，请手动复制下面的网址在本机浏览器打开。")
    else:
        _err("[login] 即梦已打开默认浏览器，请用**抖音 App 扫页面上的二维码**完成登录…")
    # 完整逻辑行输出，天然免疫终端折行截断（Windows 手抄 URL 丢参数是老事故）
    _err("[login] 登录网址（没弹出就复制这一整行，**必须在这台电脑上打开**）：")
    _err(url)


def _run_attempt(timeout: int) -> dict:
    """单次登录尝试：起 dreamina login，拿到网址就开页面，轮询 user_credit 判成功
    （不依赖退出码）。返回内部结果字典。"""
    result: dict = {"logged_in": False, "credit": None, "login_url": None,
                    "url_source": None, "timed_out": False, "launch_error": None}
    started = datetime.now().astimezone()

    with tempfile.TemporaryDirectory(prefix="dreamina-login-") as tmp:
        shim = install_opener_shim(Path(tmp))
        env = dict(os.environ)
        capture: Path | None = None
        if shim:
            env.update(shim[0])
            capture = shim[1]
        try:
            proc = subprocess.Popen([DREAMINA, "login"], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", bufsize=1, env=env)
        except Exception as e:  # noqa: BLE001
            _err(f"[login] 启动 dreamina login 失败：{e}")
            result["launch_error"] = str(e)
            return result

        q: queue.Queue = queue.Queue()
        threading.Thread(target=_reader, args=(proc, q), daemon=True).start()

        raw_lines: list[str] = []
        start = time.monotonic()
        last_poll = 0.0
        stream_done = False
        try:
            while True:
                if time.monotonic() - start > timeout:
                    result["timed_out"] = True
                    break
                # 排空管道已到达的行（只为失败时回显排障，网址不从这里来——CLI 不印）
                drained = False
                while True:
                    try:
                        line = q.get_nowait()
                    except queue.Empty:
                        break
                    drained = True
                    if line is None:
                        stream_done = True
                        continue
                    raw_lines.append(line)

                if not result["login_url"]:
                    url = read_captured_url(capture) if capture else None
                    source = "opener 拦截" if url else None
                    if not url:
                        url = rebuild_login_url(started)
                        source = "日志重建" if url else None
                    if url:
                        result["login_url"], result["url_source"] = url, source
                        _err(f"[login] 已取到登录网址（{source}）。")
                        _present_url(url, shimmed=bool(capture))

                # 轮询 user_credit：拿到 total_credit 即登录成功（权威判据）
                now = time.monotonic()
                if now - last_poll >= POLL_INTERVAL:
                    last_poll = now
                    credit = query_credit()
                    if credit is not None:
                        result["logged_in"], result["credit"] = True, credit
                        break
                # 子进程先正常退出：立即复查一次再结束本次尝试
                if proc.poll() is not None and stream_done:
                    credit = query_credit()
                    if credit is not None:
                        result["logged_in"], result["credit"] = True, credit
                    break
                if not drained:
                    time.sleep(0.5)
        finally:
            _terminate(proc)

    if not result["logged_in"]:
        tail = [l.rstrip()[:200] for l in raw_lines if l.strip()][-8:]
        if tail:
            _err("[login] dreamina 输出尾部（排障用）：")
            for l in tail:
                _err("  " + l)
    return result


def login(timeout: int, retries: int) -> dict:
    """驱动整套登录流程。返回对外 JSON 结果字典。"""
    credit = query_credit()  # 幂等：已登录直接返回
    if credit is not None:
        _err(f"[login] 检测到已登录，积分 {credit}，无需重新登录。")
        return {"logged_in": True, "credit": credit, "login_url": None,
                "url_source": "already", "attempts": 0, "error": None}

    last: dict = {}
    for attempt in range(1, retries + 1):
        if attempt > 1:
            _err(f"[login] 页面二维码已过期，自动开一张新的重试（第 {attempt}/{retries} 次）…")
        _err("[login] 正在启动即梦登录流程，拿到网址后会自动在你的浏览器打开…")

        last = _run_attempt(timeout)

        if last["logged_in"]:
            _err(f"[login] 登录成功！积分 {last['credit']}。")
            return {"logged_in": True, "credit": last["credit"],
                    "login_url": last["login_url"], "url_source": last["url_source"],
                    "attempts": attempt, "error": None}
        if last["launch_error"]:
            return {"logged_in": False, "credit": None, "login_url": None,
                    "url_source": None, "attempts": attempt,
                    "error": f"启动 dreamina login 失败：{last['launch_error']}"}

    err = f"等待扫码超时（{retries} 次尝试均未完成）"
    if not last.get("login_url"):
        # 网址一次都没取到：两条路同时哑火，多半是 CLI 输出/日志格式变了，得重新取证
        err += "；且始终没能取到登录网址（opener 拦截与日志重建均无结果），请检查即梦 CLI 是否升级过"
    return {"logged_in": False, "credit": None, "login_url": last.get("login_url"),
            "url_source": last.get("url_source"), "attempts": retries, "error": err}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="即梦(dreamina) 一键登录：脚本自己打开登录页，用户只需抖音 App 扫页面二维码")
    ap.add_argument("--timeout", type=int, default=240, help="单次尝试等待扫码秒数（默认 240，页面二维码几分钟过期）")
    ap.add_argument("--retries", type=int, default=3, help="超时后自动重开登录页的次数（默认 3）")
    ap.add_argument("--check-only", action="store_true", help="只查登录态与积分，不发起登录")
    a = ap.parse_args()

    if not cli_installed():
        fix = str(Path(__file__).resolve().parent / "check_env.py")
        _err(f"[login] 未检测到 dreamina CLI。请先跑：python3 {fix} --install")
        print(json.dumps({"logged_in": False, "credit": None, "login_url": None,
                          "url_source": None, "attempts": 0, "error": "CLI 未安装"},
                         ensure_ascii=False))
        sys.exit(2)

    if a.check_only:
        credit = query_credit()
        logged = credit is not None
        _err(f"[login] {'已登录，积分 ' + str(credit) if logged else '未登录'}")
        print(json.dumps({"logged_in": logged, "credit": credit, "login_url": None,
                          "url_source": "already" if logged else None, "attempts": 0,
                          "error": None}, ensure_ascii=False))
        sys.exit(0 if logged else 1)

    result = login(a.timeout, a.retries)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["logged_in"] else 1)


if __name__ == "__main__":
    main()

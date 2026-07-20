#!/usr/bin/env python3
"""nbdpsy-text-to-video skill · 即梦(dreamina) 一键登录助手。

登录全程由 agent 包办，用户唯一动作是在弹出的浏览器页面 / 二维码图片上用**抖音 App 扫码或点确认**。

事故动机：Windows 小白运营被旧文案引导跑 `dreamina login --headless`，终端字符二维码显示不出
（headless 需 google-chrome + 终端字体），PowerShell 折行又把 verification_uri 里的 user_code 参数
截断（浏览器报"没有 user_code"），每次重跑还生成新码作废旧网址——反复登录失败。而有屏机器根本
不该用 `--headless`：`dreamina login` 默认模式本就会自动弹默认浏览器完成登录。

本脚本据此分流：有屏机器走默认浏览器模式；无屏服务器才走 headless 并把抖音二维码渲染成 PNG 图片
交给 agent 展示。浏览器模式下 CLI 若弹不开浏览器（设备流回退），脚本从管道拿到**完整逻辑行**的
verification_uri 自己 webbrowser.open()——天然免疫终端折行截断。

约定同目录其他脚本：stdout=最终 JSON / stderr=中文进度。

用法：
  python3 dreamina_login.py               # auto：自动判断弹浏览器/出二维码
  python3 dreamina_login.py --mode headless  # 强制无屏二维码模式
  python3 dreamina_login.py --check-only  # 只查登录态与积分，不发起登录
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path


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


def select_mode(os_name: str | None = None, platform: str | None = None,
                env: dict | None = None) -> str:
    """auto 模式决策：返回 'browser' 或 'headless'。
    Windows（os.name=='nt'）或 macOS 视为有 GUI → browser；
    Linux 看 DISPLAY / WAYLAND_DISPLAY，有 → browser，无 → headless。
    参数可显式传入便于单测，缺省读当前运行环境。"""
    os_name = os.name if os_name is None else os_name
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    if os_name == "nt" or platform == "darwin":
        return "browser"
    if env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return "browser"
    return "headless"


def parse_device_flow(text: str) -> dict:
    """从 dreamina login --headless 的输出里提取设备流字段。
    输出每行形如 `verification_uri: https://...`；返回 {'verification_uri':..., 'user_code':...}
    （缺的键值为 None）。管道读到的是完整逻辑行，天然免疫终端折行截断——这正是根治
    Windows 复制 user_code 被截断事故的关键。"""
    fields: dict = {"verification_uri": None, "user_code": None}
    for line in text.splitlines():
        line = line.strip()
        for key in fields:
            prefix = key + ":"
            if line.startswith(prefix):
                val = line[len(prefix):].strip()
                if val:
                    fields[key] = val
    return fields


def make_qr(uri: str) -> str | None:
    """把 verification_uri 生成二维码 PNG，返回路径；缺 qrcode 库先尝试 pip 装，
    仍失败则返回 None（降级为只给 URL，不算错误）。"""
    out = Path(tempfile.gettempdir()) / "dreamina_login_qr.png"

    def _gen() -> str:
        import qrcode  # type: ignore  # 可选增强依赖
        qrcode.make(uri).save(str(out))
        return str(out)

    try:
        return _gen()
    except ImportError:
        _err("[login] 未装 qrcode 库，尝试 pip 安装 qrcode[pil] …")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "qrcode[pil]"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
        except Exception:  # noqa: BLE001 装不上就降级
            pass
        try:
            return _gen()
        except Exception as e:  # noqa: BLE001
            _err(f"[login] 二维码生成失败（降级为只给网址）：{e}")
            return None
    except Exception as e:  # noqa: BLE001
        _err(f"[login] 二维码生成失败（降级为只给网址）：{e}")
        return None


def _chrome_missing(text: str) -> bool:
    """尽力而为地从子进程输出判断 headless 缺 google-chrome。"""
    low = text.lower()
    if "google-chrome" not in low and "chromium" not in low:
        return False
    return any(k in low for k in ("not found", "no such", "cannot find",
                                  "executable", "未找到", "不存在", "找不到"))


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


def _run_attempt(mode: str, timeout: int) -> dict:
    """单次登录尝试。返回内部结果字典（logged_in / credit / qr_image / verification_uri /
    chrome_missing / timed_out / launch_error）。轮询 user_credit 判成功，不依赖退出码。"""
    result: dict = {"logged_in": False, "credit": None, "qr_image": None,
                    "verification_uri": None, "chrome_missing": False,
                    "timed_out": False, "launch_error": None}
    args = [DREAMINA, "login"] + (["--headless"] if mode == "headless" else [])
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
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
            # 排空管道已到达的行
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
            if drained:
                joined = "".join(raw_lines)
                if _chrome_missing(joined):
                    result["chrome_missing"] = True
                fields = parse_device_flow(joined)
                if fields["verification_uri"] and not result["verification_uri"]:
                    result["verification_uri"] = fields["verification_uri"]
                    _on_verification_uri(mode, fields["verification_uri"], result)
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
    # 失败时回显子进程输出尾部供排障（跳过二维码字符画，每行截 200 字符防刷屏）
    if not result["logged_in"]:
        tail = [l.rstrip()[:200] for l in raw_lines if l.strip() and "█" not in l][-8:]
        if tail:
            _err("[login] dreamina 输出尾部（排障用）：")
            for l in tail:
                _err("  " + l)
    return result


def _on_verification_uri(mode: str, uri: str, result: dict) -> None:
    """设备流网址就绪时的处理：headless 出二维码图片；browser 是 CLI 弹不开浏览器的回退，脚本自己打开。"""
    if mode == "headless":
        result["qr_image"] = make_qr(uri)
        if result["qr_image"]:
            _err(f"[login] 已生成登录二维码图片：{result['qr_image']}")
            _err("[login] 请用**抖音 App** 扫这张二维码图片完成登录（无屏服务器模式）。")
        else:
            _err(f"[login] 二维码库不可用；请用抖音 App 打开此网址完成登录：\n{uri}")
    else:
        _err("[login] CLI 未能自动弹出浏览器，脚本改用设备流网址自动打开浏览器…")
        try:
            webbrowser.open(uri)
        except Exception:  # noqa: BLE001
            pass
        _err(f"[login] 若浏览器没弹出，请手动打开（这是完整网址，勿手抄以免截断）：\n{uri}")


def login(mode: str, timeout: int, retries: int) -> dict:
    """驱动整套登录流程。返回对外 JSON 结果字典。"""
    credit = query_credit()  # 幂等：已登录直接返回
    if credit is not None:
        _err(f"[login] 检测到已登录，积分 {credit}，无需重新登录。")
        return {"logged_in": True, "credit": credit, "mode": "already",
                "qr_image": None, "verification_uri": None, "attempts": 0, "error": None}

    resolved = select_mode() if mode == "auto" else mode
    _err(f"[login] 登录模式：{resolved}"
         + ("（有屏机器，自动弹浏览器）" if resolved == "browser" else "（无屏服务器，出二维码图片）"))

    last: dict = {}
    for attempt in range(1, retries + 1):
        if attempt > 1:
            _err(f"[login] 二维码已过期，自动换新码重试（第 {attempt}/{retries} 次）…")
        if resolved == "browser":
            _err("[login] 已自动打开浏览器登录页，请在弹出的页面用**抖音 App 扫码或点确认**…")
        else:
            _err("[login] 正在生成登录二维码（无屏服务器模式），稍候把图片给你扫…")

        last = _run_attempt(resolved, timeout)

        if last["logged_in"]:
            _err(f"[login] 登录成功！积分 {last['credit']}。")
            return {"logged_in": True, "credit": last["credit"], "mode": resolved,
                    "qr_image": last["qr_image"], "verification_uri": last["verification_uri"],
                    "attempts": attempt, "error": None}
        if last["launch_error"]:
            return {"logged_in": False, "credit": None, "mode": resolved,
                    "qr_image": None, "verification_uri": None, "attempts": attempt,
                    "error": f"启动 dreamina login 失败：{last['launch_error']}"}
        if last["chrome_missing"]:  # headless 缺 chrome：重试也没用，直接失败
            return {"logged_in": False, "credit": None, "mode": resolved,
                    "qr_image": last["qr_image"], "verification_uri": last["verification_uri"],
                    "attempts": attempt,
                    "error": "headless 模式需要 google-chrome（未检测到）；请在有屏机器上重跑，或先安装 google-chrome"}

    return {"logged_in": False, "credit": None, "mode": resolved,
            "qr_image": last.get("qr_image"), "verification_uri": last.get("verification_uri"),
            "attempts": retries, "error": f"等待扫码超时（{retries}次尝试均未完成）"}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="即梦(dreamina) 一键登录：自动弹浏览器/出二维码，用户只需抖音 App 扫码")
    ap.add_argument("--mode", choices=["auto", "browser", "headless"], default="auto",
                    help="auto 自动判断（默认）/ browser 弹浏览器 / headless 无屏出二维码")
    ap.add_argument("--timeout", type=int, default=240, help="单次尝试等待扫码秒数（默认 240，二维码几分钟过期）")
    ap.add_argument("--retries", type=int, default=3, help="超时后自动换新码重试次数（默认 3）")
    ap.add_argument("--check-only", action="store_true", help="只查登录态与积分，不发起登录")
    a = ap.parse_args()

    if not cli_installed():
        fix = str(Path(__file__).resolve().parent / "check_env.py")
        _err(f"[login] 未检测到 dreamina CLI。请先跑：python3 {fix} --install")
        print(json.dumps({"logged_in": False, "credit": None, "mode": a.mode,
                          "qr_image": None, "verification_uri": None, "attempts": 0,
                          "error": "CLI 未安装"}, ensure_ascii=False))
        sys.exit(2)

    if a.check_only:
        credit = query_credit()
        logged = credit is not None
        _err(f"[login] {'已登录，积分 ' + str(credit) if logged else '未登录'}")
        print(json.dumps({"logged_in": logged, "credit": credit,
                          "mode": "already" if logged else a.mode, "qr_image": None,
                          "verification_uri": None, "attempts": 0, "error": None},
                         ensure_ascii=False))
        sys.exit(0 if logged else 1)

    result = login(a.mode, a.timeout, a.retries)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["logged_in"] else 1)


if __name__ == "__main__":
    main()

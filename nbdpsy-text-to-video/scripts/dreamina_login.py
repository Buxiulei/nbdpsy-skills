#!/usr/bin/env python3
"""nbdpsy-text-to-video skill · 即梦(dreamina) 登录助手 —— OAuth Device Flow（CLI a857341 起）。

**脚本负责把授权网址送到用户面前，用户唯一动作是用抖音 App 扫码/点确认。**

## 真实登录流（2026-08-05 实测新版 CLI，stdout 原样如下）

    请使用浏览器完成 OAuth Device Flow 登录。
    verification_uri: https://jimeng.jianying.com/ai-tool/cli-auth?verification_uri=...
    user_code: bf065a38aa2909467cd784c523709763
    poll_interval: 1s
    expires_at: 2026-08-05T15:56:26+08:00

打完这几行后 **CLI 自己按 poll_interval 轮询授权状态**，用户授权完成即落
`~/.local/share/dreamina/byted_cli_user_token.json` 并退出（退出码 0）；码约 10 分钟不授权
就退出并在尾行印「登录已过期，请重新执行 dreamina login」。

所以本脚本只做三件事：**抓网址开给用户 → 等 CLI 退出 → 用 `user_credit` 复核登录态**
（退出码只是信号，登录态以能读到积分为准）。

## 与旧版（127.0.0.1 回调流）的差别 —— 别把老代码搬回来

- 授权页**任何设备都能打开**（手机也行）：网址里不再有 `callback=http://127.0.0.1:<端口>`，
  旧版「必须在这台电脑的浏览器里打开」的死结没了。
- 新 CLI **不起本地回调服务器、不写 `~/.dreamina_cli/`**，所以旧脚本那套 opener shim 拦
  `xdg-open`、从日志抓 `port=`、读 `credential.json` 的 `random_secret_key` 拼网址，
  对新 CLI 全部无效（网址是 CLI 自己印在 stdout 上的，直接读就行）。
- 升级 CLI 会让旧登录态一次性失效，需重扫一次。

约定同目录其他脚本：stdout=最终 JSON / stderr=中文进度。

用法：
  python3 dreamina_login.py               # 起登录、开授权页、等用户授权
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
import threading
import time
import webbrowser
from pathlib import Path


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def _dreamina_path() -> str:
    """dreamina 可执行路径：PATH 优先，否则平台默认落地位置（与 jimeng_gen.py 同法）。"""
    p = shutil.which("dreamina")
    if p:
        return p
    for c in ("~/.local/bin/dreamina", "~/bin/dreamina.exe"):
        e = os.path.expanduser(c)
        if Path(e).exists():
            return e
    return os.path.expanduser("~/.local/bin/dreamina")  # 占位（不存在即判未装）


DREAMINA = _dreamina_path()
INSTALL_CMD = "curl -fsSL https://jimeng.jianying.com/cli | bash"
URL_WAIT = 30       # 抓 verification_uri 的等待上限（秒）：正常一两秒就印出来
COMPANION_WAIT = 2  # 抓到网址后再收 user_code / expires_at 的宽限（秒）：它们与网址同批印出
LOGIN_WAIT = 900    # 等用户授权的上限（秒）：码本身约 10 分钟过期，留点余量给 CLI 自己收尾
RERUN_HINT = "重跑本脚本生成新码"

# 网址正则连 scheme 一起要，既锚住标签又挡掉噪声行（网址自身的查询参数里也有
# verification_uri= ，用 `:` 分隔符区分，不会误截）
FIELDS = (("verification_uri", re.compile(r"verification_uri:\s*(https?://\S+)")),
          ("user_code", re.compile(r"user_code:\s*(\S+)")),
          ("expires_at", re.compile(r"expires_at:\s*(\S+)")))


def cli_installed() -> bool:
    return Path(DREAMINA).exists()


def query_credit(timeout: int = 30) -> dict | None:
    """跑 `dreamina user_credit` 复核登录态：返回回执 dict，未登录/读不到回 None。

    登录成败以**能不能读到积分**为准（退出码只是信号）——这条在旧版就验过，别改成信退出码。
    """
    try:
        p = subprocess.run([DREAMINA, "user_credit"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except Exception:  # noqa: BLE001 任何执行失败一律视作"读不到"
        return None
    try:
        data = json.loads(p.stdout)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict) or not isinstance(data.get("total_credit"), int):
        return None
    return data


def parse_login_line(line: str, info: dict) -> dict:
    """把一行 CLI stdout 里的 device flow 字段抓进 info（就地更新并返回）。先到先得，不覆盖。"""
    for key, pattern in FIELDS:
        if key not in info:
            m = pattern.search(line)
            if m:
                info[key] = m.group(1)
    return info


def present_url(info: dict) -> bool:
    """把授权页送到用户面前：尽力弹本机浏览器（失败不致命），网址一律完整打进 stderr。"""
    url = info["verification_uri"]
    opened = False
    try:
        opened = bool(webbrowser.open(url))
    except Exception as e:  # noqa: BLE001 没有图形环境很正常，用户自己打开就行
        _err(f"[login] 打开浏览器失败（不影响，照下面网址手动打开即可）：{e}")
    _err("[login] 已在本机浏览器打开即梦授权页。" if opened
         else "[login] 没能自动打开浏览器，请照下面网址手动打开。")
    _err("[login] 授权网址（**任何设备都能打开**，手机也行；用抖音 App 扫码/点确认完成授权）：")
    _err(url)                      # 完整逻辑行单独一行，免疫终端折行截断（手抄 URL 丢参数是老事故）
    if info.get("user_code"):
        _err(f"[login] user_code：{info['user_code']}（页面要求核对时用）")
    _err("[login] 授权码约 10 分钟过期"
         + (f"（expires_at {info['expires_at']}）" if info.get("expires_at") else "")
         + f"，过期就{RERUN_HINT}。等待授权中…")
    return opened


def _reader(proc: subprocess.Popen, q: queue.Queue) -> None:
    """后台逐行读子进程合并输出，读完投 None 哨兵。"""
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            q.put(line)
    finally:
        q.put(None)


def _lines(q: queue.Queue, deadline: float):
    """按 deadline 产出子进程输出行；产出 None 表示 stdout 已关闭（进程结束）。超时即停止产出。"""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            item = q.get(timeout=min(0.5, remaining))
        except queue.Empty:
            continue
        yield item
        if item is None:
            return


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


def _tail(lines: list[str], n: int = 8) -> list[str]:
    return [l.rstrip()[:200] for l in lines if l.strip()][-n:]


def _dump_tail(lines: list[str]) -> None:
    tail = _tail(lines)
    if tail:
        _err("[login] dreamina 输出尾部（排障用）：")
        for l in tail:
            _err("  " + l)


def _ok(data: dict) -> dict:
    return {"success": True, "total_credit": data.get("total_credit"),
            "vip_level": data.get("vip_level")}


def _fail(error: str, hint: str = RERUN_HINT) -> dict:
    return {"success": False, "error": error, "hint": hint}


def login(url_wait: int = URL_WAIT, login_wait: int = LOGIN_WAIT) -> dict:
    """跑完整 device flow，返回对外 JSON 结果字典。"""
    _err("[login] 正在启动即梦 OAuth Device Flow 登录…")
    try:
        proc = subprocess.Popen([DREAMINA, "login"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", bufsize=1)
    except Exception as e:  # noqa: BLE001
        return _fail(f"启动 dreamina login 失败：{e}",
                     hint=f"确认 {DREAMINA} 可执行，或重装：{INSTALL_CMD}")

    q: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(proc, q), daemon=True).start()
    lines: list[str] = []
    info: dict = {}
    stream_done = False

    try:
        # 阶段一：抓 verification_uri（正常一两秒就印出来）
        for item in _lines(q, time.monotonic() + url_wait):
            if item is None:
                stream_done = True
                break
            lines.append(item)
            if parse_login_line(item, info).get("verification_uri"):
                break

        if not info.get("verification_uri"):
            _dump_tail(lines)
            if stream_done:
                # CLI 没出网址就自己退了：可能本来就登录着（幂等重跑），复核一下再判
                data = query_credit()
                if data:
                    _err(f"[login] 无需授权：已是登录态，积分 {data.get('total_credit')}。")
                    return _ok(data)
                return _fail("dreamina login 没打印 verification_uri 就退出了，登录态也没建立",
                             hint=f"多半是 CLI 版本过旧（Device Flow 是 a857341 起）；升级：{INSTALL_CMD}")
            return _fail(f"{url_wait}s 内没等到 verification_uri —— 这版 CLI 不是 OAuth Device Flow",
                         hint=f"升级即梦 CLI 后重试：{INSTALL_CMD}")

        # user_code / expires_at 与网址是同一批输出，抓到网址就收工会把它们丢掉，
        # 用户既看不到要核对的码、也不知道还剩多久过期
        if not stream_done:
            for item in _lines(q, time.monotonic() + COMPANION_WAIT):
                if item is None:
                    stream_done = True
                    break
                lines.append(item)
                if all(k in parse_login_line(item, info) for k, _ in FIELDS):
                    break

        present_url(info)

        # 阶段二：CLI 自己轮询授权状态，我们等它退出（stdout 已关就是已经退了，不用再等）
        if not stream_done:
            for item in _lines(q, time.monotonic() + login_wait):
                if item is None:      # stdout 关闭 = 进程已结束或正在收尾
                    stream_done = True
                    break
                lines.append(item)
            if not stream_done:
                return _fail(f"等待授权超过 {login_wait}s 仍未完成（授权码约 10 分钟过期）",
                             hint=RERUN_HINT)
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            rc = None             # stdout 关了却迟迟不退，罕见；下面照样以积分为准判成败
    finally:
        _terminate(proc)

    data = query_credit()
    if data:
        _err(f"[login] 登录成功！积分 {data.get('total_credit')}"
             + (f"，会员等级 {data['vip_level']}" if data.get("vip_level") is not None else "") + "。")
        return _ok(data)

    _dump_tail(lines)
    tail = _tail(lines)
    reason = tail[-1] if tail else f"dreamina login 异常退出（退出码 {rc}）"
    return _fail(f"授权未完成：{reason}", hint=RERUN_HINT)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="即梦(dreamina) 登录：脚本抓 OAuth Device Flow 授权网址开给用户，"
                    "用户在任何设备上用抖音 App 扫码/确认")
    ap.add_argument("--check-only", action="store_true", help="只查登录态与积分，不发起登录")
    a = ap.parse_args()

    if not cli_installed():
        _err(f"[login] 未检测到 dreamina CLI（{DREAMINA}）。安装：{INSTALL_CMD}")
        result = _fail("dreamina CLI 未安装", hint=f"装 CLI 后重跑本脚本：{INSTALL_CMD}")
    elif a.check_only:
        data = query_credit()
        _err(f"[login] {'已登录，积分 ' + str(data.get('total_credit')) if data else '未登录'}")
        result = _ok(data) if data else _fail("未登录", hint="跑 dreamina_login.py（不带 --check-only）授权")
    else:
        result = login()

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""NBDpsy skills 环境自检：按 profile 探测 Python 模块 / CLI 工具 / 必需凭据是否就绪。
此文件真源在仓库 shared/，由 tools/sync_shared.py 同步到各 skill 的 scripts/，勿单独改副本。

用法：
  python3 env_check.py --profile {seo|xhs|reviewer|pipeline} [--install]

输出契约：
  stdout = 纯 JSON {"ready": bool, "profile": str,
                    "checks": [{"name","status":"ok|missing|warn","detail","fix"}]}
  stderr = 人类可读逐项 ✓/✗/⚠ + 收尾一行结论
  ready=true → exit 0；否则 exit 1

判定：status=missing 的模块/必需凭据 → ready=false；status=warn 不影响 ready。
--install 只对缺失的 Python 模块执行 pip install --user（不碰系统包/凭据，二者只在 fix 里给指引）。
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import shutil
import site
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import nbdpsy_common  # noqa: E402  同目录 import，sys.path[0] 即脚本目录

# 模块探测名 → pip 安装名（find_spec 用左边，pip install 用右边）
MODULE_PIP_NAME = {"yaml": "pyyaml", "PIL": "pillow", "requests": "requests"}

# profile → 需求：Python 模块 / 必需凭据 / 可选 CLI 工具（CLI 缺失只 warn，不阻塞 ready）
PROFILES = {
    "seo": {"modules": ["yaml", "requests"], "credentials": ["NBDPSY_BLOG_API_KEY"], "cli": []},
    "xhs": {"modules": ["yaml", "requests"], "credentials": [], "cli": []},
    "reviewer": {"modules": ["yaml", "requests", "PIL"], "credentials": [], "cli": ["ffmpeg", "ffprobe"]},
    "pipeline": {"modules": ["yaml", "requests", "PIL"], "credentials": ["NBDPSY_BLOG_API_KEY"],
                 "cli": ["ffmpeg", "ffprobe"]},
}

_SYSTEM_FIX = "系统依赖：运行仓库根 setup.py 或让我现场执行"


def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _check_module(name: str) -> dict:
    pip_name = MODULE_PIP_NAME.get(name, name)
    present = _module_present(name)
    return {
        "name": name,
        "status": "ok" if present else "missing",
        "detail": "已安装" if present else "未安装",
        "fix": "" if present else f"pip install --user {pip_name}",
    }


def _check_credential(key: str) -> dict:
    present = bool(nbdpsy_common.get_secret(key))
    return {
        "name": key,
        "status": "ok" if present else "missing",
        "detail": "已配置" if present else "未配置",
        "fix": "" if present else
               f"凭据：python3 {_HERE}/nbdpsy_common.py doctor 查看，"
               "向管理员索要「凭据配置包」后 secret import 导入",
    }


def _check_cli(name: str) -> dict:
    present = shutil.which(name) is not None
    return {
        "name": name,
        "status": "ok" if present else "warn",
        "detail": "已安装" if present else "未安装（仅审视频需要，不阻塞就绪）",
        "fix": "" if present else _SYSTEM_FIX,
    }


def _pip_install(pip_name: str) -> None:
    """pip install --user；子进程的全部输出转发到 stderr，保证本进程 stdout 恒为纯 JSON。"""
    print(f"[install] pip install --user {pip_name} …", file=sys.stderr, flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--user", pip_name],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    if result.stdout:
        sys.stderr.write(result.stdout)
        sys.stderr.flush()
    # user-site 目录可能是本次 pip install 才创建的；Python 启动时若该目录不存在
    # 就不会被加入 sys.path，导致同进程内立即复测 find_spec 出现假阴性——这里补挂一次。
    usersite = site.getusersitepackages()
    if usersite not in sys.path:
        site.addsitedir(usersite)
    importlib.invalidate_caches()


def run(profile: str, install: bool) -> dict:
    spec = PROFILES[profile]
    checks = []

    for mod in spec["modules"]:
        c = _check_module(mod)
        if install and c["status"] == "missing":
            pip_name = MODULE_PIP_NAME.get(mod, mod)
            _pip_install(pip_name)
            c = _check_module(mod)
        checks.append(c)

    for key in spec["credentials"]:
        checks.append(_check_credential(key))

    for tool in spec["cli"]:
        checks.append(_check_cli(tool))

    if profile == "pipeline":
        checks.append({
            "name": "nbdpsy-text-to-video 视频链依赖",
            "status": "warn",
            "detail": "视频链依赖由 nbdpsy-text-to-video 第 0 步 check_env.py 自检",
            "fix": "",
        })

    ready = not any(c["status"] == "missing" for c in checks)
    return {"ready": ready, "profile": profile, "checks": checks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NBDpsy skills 环境自检")
    ap.add_argument("--profile", required=True, choices=sorted(PROFILES))
    ap.add_argument("--install", action="store_true", help="尝试自动安装缺失的 Python 模块")
    args = ap.parse_args(argv)

    result = run(args.profile, args.install)

    print(f"\n=== 环境自检（profile={result['profile']}）===", file=sys.stderr)
    mark = {"ok": "✓", "missing": "✗", "warn": "⚠"}
    for c in result["checks"]:
        print(f"{mark[c['status']]} {c['name']}: {c['detail']}", file=sys.stderr)
        if c["fix"]:
            print(f"    修复：{c['fix']}", file=sys.stderr)
    print(f"\n{'✓ 环境就绪' if result['ready'] else '✗ 有缺失，按上面修复后重试'}\n", file=sys.stderr)

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())

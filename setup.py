#!/usr/bin/env python3
"""nbdpsy-skills 环境安装向导（跨平台）。非 setuptools 脚本，直接运行。
步骤：系统探测 → 系统依赖(ffmpeg/字体) → Python 依赖 → dreamina → 凭据向导 → 终检报告。幂等可反复跑。"""
import argparse
import json
import os, platform, shutil, subprocess, sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
import nbdpsy_common


def detect() -> dict:
    """返回 {"os": "linux|darwin|windows", "pkg": "apt|brew|winget|choco|none"}"""
    osname = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}[platform.system()]
    order = {"linux": ["apt-get"], "darwin": ["brew"], "windows": ["winget", "choco"]}[osname]
    pkg = next((p for p in order if shutil.which(p)), "none")
    return {"os": osname, "pkg": {"apt-get": "apt"}.get(pkg, pkg)}


PKG_CMDS = {  # 每项: (检测可执行, {pkg管理器: 安装命令})
    "ffmpeg": ("ffmpeg", {"apt": "sudo apt-get install -y ffmpeg", "brew": "brew install ffmpeg",
                           "winget": "winget install --id Gyan.FFmpeg -e", "choco": "choco install ffmpeg -y"}),
}
FONT_HINTS = {"apt": "sudo apt-get install -y fonts-noto-cjk", "brew": "brew install --cask font-noto-sans-cjk-sc",
              "winget": "Windows 自带微软雅黑可直接用；如需 Noto 请手动安装 Noto Sans CJK SC"}
CREDENTIALS = [  # (KEY, 是否必需, 说明)
    ("NBDPSY_BLOG_API_KEY", True,
     "博客发布 API Key —— 请向管理员索要『凭据配置包』一键导入（secret import）；"
     "管理员生成入口：manage.nbdpsy.com → 博客 → API Keys → 生成凭据配置包"),
    ("VOLC_TTS_API_KEY", False,
     "火山豆包 TTS 新版单一凭据（优先于下面两条 appid/token）—— 找管理员要（凭据配置包会一并带上），"
     "或去火山控制台 speech/new/setting/apikeys 自建；三者都可跳过，跳过后旁白改用 --engine edge（免费 edge-tts）"),
    ("VOLC_TTS_APPID", False,
     "火山豆包 TTS（旧版，已有 VOLC_TTS_API_KEY 可不填）—— 找管理员要（凭据配置包会一并带上）；"
     "可跳过，跳过后旁白改用 --engine edge（免费 edge-tts）"),
    ("VOLC_TTS_ACCESS_TOKEN", False,
     "火山豆包 TTS（旧版，已有 VOLC_TTS_API_KEY 可不填）—— 找管理员要（凭据配置包会一并带上）；"
     "可跳过，跳过后旁白改用 --engine edge（免费 edge-tts）"),
]

_OS_DEFAULT_PKG = {"linux": "apt", "darwin": "brew", "windows": "winget"}


def _pick_cmd(cmds: dict, state: dict) -> str:
    """按当前探测到的包管理器选安装命令；探测不到包管理器（pkg == 'none'）时，
    退回该操作系统最常见的包管理器方案做提示（仅用于打印，不会真的执行）。"""
    return cmds.get(state["pkg"]) or cmds.get(_OS_DEFAULT_PKG[state["os"]], "（无自动安装命令，请自行安装）")


def _maybe_noninteractive_sudo(cmd: str, interactive: bool) -> str:
    """交互/非交互模式下的 sudo 命令改写。
    - interactive=True: 普通 sudo（允许终端询问密码）
    - interactive=False: sudo -n（非交互，无缓存凭据时直接失败）
    """
    if not cmd.startswith("sudo "):
        return cmd
    if interactive:
        return cmd  # 交互模式，保留普通 sudo
    # 非交互模式（--yes/CI）才加 -n
    return "sudo -n " + cmd[len("sudo "):]


def _run(cmd, timeout=300):
    """跑一条命令，永不向上抛异常——找不到可执行文件 / 超时都当作失败处理，
    交给调用方按返回码判断，报告里给手动修复命令而不是让整个向导崩掉。
    cmd 是 str 时按 shell 执行（用于系统包管理器命令），是 list 时按参数数组执行。"""
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


REPORT: list[tuple[str, str, str]] = []  # [(项目, ✓/✗/跳过, 说明)]，主流程按顺序追加，终检时整表打印


def _mark_icon(mark: str) -> str:
    return {"✓": "✅", "✗": "❌", "跳过": "⚠️"}[mark]


def report(item: str, mark: str, detail: str) -> None:
    REPORT.append((item, mark, detail))
    print(f"{_mark_icon(mark)} {item}: {detail}")


# ---------- 系统依赖（ffmpeg 等） ----------

def step_system_deps(state: dict, interactive: bool) -> None:
    print("\n=== 系统依赖 ===")
    for name, (exe, cmds) in PKG_CMDS.items():
        found = shutil.which(exe)
        if found:
            report(name, "✓", f"已装（{found}）")
            continue
        cmd = _pick_cmd(cmds, state)
        if state["pkg"] == "none":
            report(name, "✗", f"未装，且未检测到包管理器，请手动安装：{cmd}")
            continue
        print(f"  → 尝试自动安装 {name}：{cmd}")
        rc, _out, _err = _run(_maybe_noninteractive_sudo(cmd, interactive))
        found = shutil.which(exe)
        if rc == 0 and found:
            report(name, "✓", f"自动安装成功（{found}）")
        else:
            report(name, "✗", f"自动安装失败（可能缺 sudo 权限），请手动执行：{cmd}")


# ---------- 中文字幕字体 ----------

def step_font(state: dict) -> None:
    print("\n=== 中文字幕字体 ===")
    sys.path.insert(0, str(REPO_ROOT / "nbdpsy-text-to-video" / "scripts"))
    from compose_video import resolve_font  # 复用 nbdpsy-text-to-video 的跨平台字体解析，避免重复实现
    try:
        path = resolve_font()
        report("中文字幕字体", "✓", path)
    except RuntimeError:
        hint = _pick_cmd(FONT_HINTS, state)
        report("中文字幕字体", "✗", f"未找到 Noto Sans CJK / 微软雅黑，请手动安装：{hint}")


# ---------- Python 依赖 ----------

def step_python_deps() -> None:
    print("\n=== Python 依赖 ===")
    req = REPO_ROOT / "requirements.txt"
    cmd = [sys.executable, "-m", "pip", "install", "--user", "-r", str(req)]
    rc, _out, err = _run(cmd, timeout=300)
    used_break_system_packages = False
    if rc != 0 and "externally-managed-environment" in err:
        # Debian/Ubuntu 较新版本（PEP 668）默认锁住系统 pip；这是 pip 自己报错里建议的逃生舱，
        # 只在探测到这条具体错误信息时才追加，不影响其它平台/环境。
        used_break_system_packages = True
        rc, _out, err = _run(cmd + ["--break-system-packages"], timeout=300)
    if rc == 0:
        detail = f"已安装 {req.name} 全部依赖"
        if used_break_system_packages:
            detail += "（已绕过系统包管理保护 PEP 668，装入用户目录）"
        report("Python 依赖", "✓", detail)
    else:
        tail = err.strip().splitlines()[-1] if err.strip() else "未知错误"
        report("Python 依赖", "✗", f"pip install 失败：{tail}")


# ---------- dreamina CLI（视频生成，可选） ----------

def step_dreamina(state: dict, interactive: bool) -> None:
    print("\n=== dreamina CLI（视频生成，可选） ===")
    fallback = str(Path.home() / ".local" / "bin" / "dreamina")
    exe = shutil.which("dreamina") or (fallback if Path(fallback).exists() else None)
    if exe:
        rc, out, err = _run([exe, "--version"], timeout=30)
        raw = (out or err).strip() or "已安装"
        try:
            ver = json.loads(out).get("version")
            detail = f"{exe}（version {ver}）" if ver else raw
        except (json.JSONDecodeError, AttributeError):
            detail = raw.splitlines()[0] if raw else "已安装"  # 单行化，避免撑破报告表
        report("dreamina CLI", "✓", detail)
        print("  提示：若未登录，请运行 dreamina login --headless，用抖音 App 扫码（该步骤无法代扫）")
        return

    if state["os"] == "windows":
        report("dreamina CLI", "跳过", "dreamina CLI 官方暂未验证 Windows，视频生成建议 WSL")
        return

    install_cmd = "curl -fsSL https://jimeng.jianying.com/cli | bash"
    print(f"  未检测到 dreamina CLI，自动安装：{install_cmd}")
    _run(["bash", "-c", install_cmd], timeout=300)
    exe = shutil.which("dreamina") or (fallback if Path(fallback).exists() else None)
    if exe:
        report("dreamina CLI", "✓", "安装完成，请在终端运行 dreamina login --headless 用抖音 App 扫码登录（无法代扫）")
    else:
        report("dreamina CLI", "跳过", f"自动安装未成功，可稍后手动执行：{install_cmd}")


# ---------- 凭据向导 ----------

def credential_wizard(interactive: bool) -> list:
    """对 CREDENTIALS 逐项检查/询问，返回 [(key, ✓/✗/跳过, 说明), ...]。
    纯函数（不碰全局 REPORT/print 之外的状态），方便单测。
    绝不读取/回显已存在凭据的真实值——已配置只报「已配置」。"""
    results = []
    for key, required, desc in CREDENTIALS:
        val = nbdpsy_common.get_secret(key)
        if val:
            results.append((key, "✓", "已配置"))
            continue
        if interactive:
            entered = input(f"{key}（{desc}）\n请输入，留空跳过：").strip()
            if entered:
                nbdpsy_common.set_secret(key, entered)
                results.append((key, "✓", "已录入（存到用户级凭据文件，不入库）"))
                continue
        results.append((key, "✗" if required else "跳过", desc))
    return results


def step_credentials(interactive: bool) -> None:
    print("\n=== 凭据向导 ===")
    results = credential_wizard(interactive)
    for key, mark, detail in results:
        report(f"凭据 {key}", mark, detail)
    if not interactive and any(mark != "✓" for _, mark, _ in results):
        print("  提示：非交互模式未逐项询问。请向管理员索要「凭据配置包」，"
              "然后运行 python3 nbdpsy_common.py secret import <凭据包文件> 一键导入。")


# ---------- 每 skill 冒烟测试 ----------

def step_smoke_tests() -> None:
    print("\n=== Skill 冒烟测试 ===")
    cmds = [
        ("nbdpsy-seo-artical-creator", [sys.executable, str(REPO_ROOT / "nbdpsy-seo-artical-creator" / "scripts" / "count_hanzi.py"), "--help"]),
        ("nbdpsy-xiaohongshu-creator", [sys.executable, str(REPO_ROOT / "nbdpsy-xiaohongshu-creator" / "scripts" / "fetch_post.py"), "--help"]),
        ("nbdpsy-text-to-video", [sys.executable, str(REPO_ROOT / "nbdpsy-text-to-video" / "scripts" / "check_env.py"), "--help"]),
    ]
    for skill, cmd in cmds:
        rc, _out, err = _run(cmd, timeout=30)
        cmd_str = " ".join(cmd)
        if rc == 0:
            report(f"冒烟：{skill}", "✓", cmd_str)
        else:
            report(f"冒烟：{skill}", "✗", f"{cmd_str} 失败：{(err.strip().splitlines() or ['未知错误'])[-1]}")


def print_final_report() -> None:
    print("\n" + "=" * 64)
    print("终检报告")
    print("=" * 64)
    width = max((len(item) for item, _, _ in REPORT), default=10)
    for item, mark, detail in REPORT:
        print(f"{_mark_icon(mark)} {item.ljust(width)}  {detail}")
    print("=" * 64)


def main() -> None:
    ap = argparse.ArgumentParser(description="nbdpsy-skills 环境安装向导（跨平台）")
    ap.add_argument("--yes", action="store_true", help="非交互：能装的都装（含 dreamina CLI 自动安装），凭据只报缺不问")
    ap.add_argument("--skip-credentials", action="store_true", help="跳过凭据向导（只报缺，不问）")
    args = ap.parse_args()

    interactive = not args.yes
    state = detect()
    print(f"检测到系统：{state['os']}，包管理器：{state['pkg']}")

    step_system_deps(state, interactive=interactive)
    step_font(state)
    step_python_deps()
    step_dreamina(state, interactive=interactive)
    step_credentials(interactive=not (args.yes or args.skip_credentials))
    step_smoke_tests()
    print_final_report()

    has_failure = any(mark == "✗" for _, mark, _ in REPORT)
    sys.exit(1 if has_failure else 0)


if __name__ == "__main__":
    main()

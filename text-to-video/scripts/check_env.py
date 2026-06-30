#!/usr/bin/env python3
"""text-to-video skill 环境自检 / 自装。

检测并(可选)自动安装整条文本转视频产线所需依赖：
  dreamina CLI(+登录态+积分) / ffmpeg / ffprobe / Noto Sans CJK SC 字体。

输出结构化 JSON 到 stdout（agent 解析），可读进度到 stderr。

用法：
  python check_env.py            # 只检测，给修复命令
  python check_env.py --install  # 尝试自动安装缺失项(dreamina 用 curl 自动；系统包给 sudo 命令)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DREAMINA = shutil.which("dreamina") or os.path.expanduser("~/.local/bin/dreamina")
CJK_FONT_FILE = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
MIN_CREDIT_WARN = 200  # 低于此积分给警告(一条短片量级)


def _err(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


def check(install: bool) -> dict:
    checks = []

    def add(name, ok, detail, fix="", critical=True):
        checks.append({"name": name, "ok": bool(ok), "critical": critical,
                       "detail": detail, "fix": fix})

    # 1) dreamina CLI
    dreamina = DREAMINA if Path(DREAMINA).exists() else None
    if not dreamina and install:
        _err("[install] 安装 dreamina CLI …")
        _run(["bash", "-c", "curl -fsSL https://jimeng.jianying.com/cli | bash"], timeout=300)
        cand = os.path.expanduser("~/.local/bin/dreamina")
        dreamina = shutil.which("dreamina") or (cand if Path(cand).exists() else None)
    if dreamina:
        rc, out, _ = _run([dreamina, "version"], timeout=30)
        ver = ""
        try:
            ver = (json.loads(out) or {}).get("version", "")
        except Exception:  # noqa: BLE001
            ver = out.strip()[:40]
        add("dreamina CLI", True, f"{dreamina} (version {ver or '?'})")
    else:
        add("dreamina CLI", False, "未安装",
            fix="curl -fsSL https://jimeng.jianying.com/cli | bash")

    # 2) 登录态 + 积分（仅当 CLI 在）
    if dreamina:
        rc, out, serr = _run([dreamina, "user_credit"], timeout=60)
        credit = None
        try:
            credit = (json.loads(out) or {}).get("total_credit")
        except Exception:  # noqa: BLE001
            credit = None
        if isinstance(credit, int):
            low = credit < MIN_CREDIT_WARN
            add("dreamina 登录 & 积分", not low,
                f"已登录，积分 {credit}" + ("（偏低，注意够不够本次产量）" if low else ""),
                fix="充值会员或减少本批产量" if low else "")
        else:
            add("dreamina 登录 & 积分", False, "未登录或无法读取积分",
                fix="dreamina login --headless  # 抖音 App 扫码")
    else:
        add("dreamina 登录 & 积分", False, "CLI 未装，跳过", fix="先装 dreamina")

    # 3) ffmpeg / ffprobe
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if not path and install:
            _err(f"[install] 尝试 apt 安装 {tool} (需 sudo) …")
            _run(["sudo", "-n", "apt-get", "install", "-y", "ffmpeg"], timeout=300)
            path = shutil.which(tool)
        add(tool, bool(path), path or "未安装",
            fix="sudo apt-get install -y ffmpeg  (macOS: brew install ffmpeg)")

    # 4) Noto Sans CJK SC 字体（中文字幕铁律）
    font_ok = Path(CJK_FONT_FILE).exists()
    if not font_ok:
        rc, out, _ = _run(["bash", "-c", "fc-list | grep -i 'sans cjk sc'"], timeout=30)
        font_ok = bool(out.strip())
    if not font_ok and install:
        _err("[install] 尝试 apt 安装 fonts-noto-cjk (需 sudo) …")
        _run(["sudo", "-n", "apt-get", "install", "-y", "fonts-noto-cjk"], timeout=300)
        font_ok = Path(CJK_FONT_FILE).exists()
    add("Noto Sans CJK SC 字体", font_ok,
        CJK_FONT_FILE if font_ok else "未找到（中文字幕会变豆腐块）",
        fix="sudo apt-get install -y fonts-noto-cjk  (macOS: brew install font-noto-sans-cjk-sc)")

    # 5) edge-tts 中文旁白（可选——纯字幕+BGM 可不装）
    rc, _, _ = _run([sys.executable, "-c", "import edge_tts"], timeout=30)
    has_tts = rc == 0
    if not has_tts and install:
        _err("[install] pip 安装 edge-tts …")
        _run([sys.executable, "-m", "pip", "install", "-q", "edge-tts"], timeout=300)
        rc, _, _ = _run([sys.executable, "-c", "import edge_tts"], timeout=30)
        has_tts = rc == 0
    add("edge-tts 旁白(可选)", has_tts, "已装" if has_tts else "未装；纯字幕+BGM 可不装",
        fix="pip install edge-tts", critical=False)

    ready = all(c["ok"] for c in checks if c["critical"])
    return {"ready": ready, "checks": checks}


def main() -> None:
    ap = argparse.ArgumentParser(description="text-to-video 环境自检/自装")
    ap.add_argument("--install", action="store_true", help="尝试自动安装缺失依赖")
    a = ap.parse_args()
    result = check(a.install)
    # 可读摘要到 stderr
    _err("\n=== 环境自检 ===")
    for c in result["checks"]:
        mark = "✅" if c["ok"] else ("❌" if c["critical"] else "⚠️")
        _err(f"{mark} {c['name']}: {c['detail']}")
        if not c["ok"] and c["fix"]:
            _err(f"     修复：{c['fix']}")
    _err(f"\n{'✅ 环境就绪' if result['ready'] else '❌ 有缺失，按上面修复后重试'}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ready"] else 1)


if __name__ == "__main__":
    main()

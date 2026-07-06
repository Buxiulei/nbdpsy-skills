#!/usr/bin/env python3
"""即梦(Dreamina)CLI 视频生成引擎 —— nbdpsy-text-to-video skill 的核心。

把字节官方 `dreamina` CLI 封装成稳健、可批量、对 agent 友好的接口：
  提交(text2video / image2video / multimodal2video) → 轮询 query_result → 下载 MP4。

设计依据（均为本机实测，非二手）：
  - `dreamina` 输出默认是干净 JSON；
  - 任务对象顶层有 `submit_id`，状态在 `gen_status`(querying/success/...)；
  - `query_result --submit_id=X --download_dir=Y` 成功后返回
    `result_json.videos[].path`（已下载到本地的真实路径，命名 {submit_id}_video_N.mp4），
    并带 `credit_count`（该任务消耗的积分）；
  - Seedance 2.0 family 在 CLI 里只有 720p；image2video 的画幅由输入图推断（无 --ratio）。

所有结构化结果打到 **stdout(JSON)**，人类可读进度打到 **stderr**，方便上层 agent 解析。

用法示例：
  python jimeng_gen.py credits
  python jimeng_gen.py gen --operation text2video --prompt "温暖诊室空镜，晨光缓缓移过沙发" \
      --duration 5 --ratio 9:16 --model seedance2.0fast --out-dir ./clips
  python jimeng_gen.py gen --operation image2video --image ./counselor.png \
      --prompt "镜头缓慢推近，人物轻轻点头" --duration 8 --out-dir ./clips
  python jimeng_gen.py submit --operation text2video --prompt "..." --duration 5   # 只提交，拿 submit_id
  python jimeng_gen.py fetch --submit-id 3d64c2221c0e07da --out-dir ./clips        # 取回已提交任务
  python jimeng_gen.py batch --plan shots.json --out-dir ./clips                   # 批量(支持 --submit-only)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

# ---- 常量 -------------------------------------------------------------------

DREAMINA = shutil.which("dreamina") or os.path.expanduser("~/.local/bin/dreamina")

# Seedance 2.0 家族（CLI 暴露的四个档位）。standard 质量最高，fast 性价比高，
# _vip 走加速通道（额外积分换更短排队）。
SEEDANCE_MODELS = {
    "seedance2.0",
    "seedance2.0fast",
    "seedance2.0_vip",
    "seedance2.0fast_vip",
}
DEFAULT_MODEL = "seedance2.0fast"
RATIOS = {"1:1", "3:4", "16:9", "4:3", "9:16", "21:9"}
# duration 合法区间（Seedance 家族 4-15s）
DUR_MIN, DUR_MAX = 4, 15

_SUBMIT_ID_RE = re.compile(r"[0-9a-f]{16}")
_COMPLIANCE_HINT = "AigcComplianceConfirmationRequired"


# ---- 底层：跑 dreamina 子命令 -----------------------------------------------

def _err(msg: str) -> None:
    """进度/诊断打到 stderr，不污染 stdout 的 JSON。"""
    print(msg, file=sys.stderr, flush=True)


def _check_cli() -> Optional[str]:
    if not (DREAMINA and Path(DREAMINA).exists()):
        return ("未找到 dreamina CLI。安装：curl -fsSL https://jimeng.jianying.com/cli | bash"
                "（装到 ~/.local/bin/dreamina）")
    return None


def _run(args: list[str], timeout: int = 180) -> tuple[int, str, str]:
    """运行 `dreamina <args>`，返回 (returncode, stdout, stderr)。"""
    try:
        proc = subprocess.run(
            [DREAMINA, *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"dreamina {args[0] if args else ''} 超时({timeout}s)"
    except FileNotFoundError:
        return 127, "", "dreamina 不可执行"


def _parse_json(text: str) -> Any:
    """容错解析 dreamina 输出。优先整体 json.loads；失败则截取首个 { 或 [ 到末尾再试。"""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1] or [-1])
    if start != -1:
        for end in (text.rfind("}"), text.rfind("]")):
            if end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue
    return None


def _extract_submit_id(obj: Any, raw: str) -> Optional[str]:
    """从已解析对象里找 submit_id；找不到则在原始文本里正则兜底(16 位 hex)。"""
    def walk(o: Any) -> Optional[str]:
        if isinstance(o, dict):
            v = o.get("submit_id")
            if isinstance(v, str) and v:
                return v
            for vv in o.values():
                r = walk(vv)
                if r:
                    return r
        elif isinstance(o, list):
            for vv in o:
                r = walk(vv)
                if r:
                    return r
        return None

    sid = walk(obj)
    if sid:
        return sid
    m = _SUBMIT_ID_RE.search(raw or "")
    return m.group(0) if m else None


# ---- 公开能力 ---------------------------------------------------------------

def credits() -> dict:
    """查询当前登录会员的积分余额。"""
    err = _check_cli()
    if err:
        return {"success": False, "error": err}
    rc, out, serr = _run(["user_credit"], timeout=60)
    data = _parse_json(out)
    if rc != 0 or not isinstance(data, dict):
        return {"success": False, "error": (serr or out or "user_credit 失败").strip(),
                "hint": "未登录请先跑：dreamina login --headless（抖音 App 扫码）"}
    data["success"] = True
    return data


def _build_gen_args(operation: str, prompt: str, *, model: str, duration: int,
                    ratio: Optional[str], images: list[str], videos: list[str],
                    audios: list[str], poll: int) -> tuple[Optional[list[str]], Optional[str]]:
    """组装生成子命令参数；返回 (args, error)。"""
    if model not in SEEDANCE_MODELS:
        return None, f"model 必须是 {sorted(SEEDANCE_MODELS)} 之一，收到 {model!r}"
    if not (DUR_MIN <= duration <= DUR_MAX):
        return None, f"duration 必须在 {DUR_MIN}-{DUR_MAX}s（Seedance 家族），收到 {duration}"
    if ratio and ratio not in RATIOS:
        return None, f"ratio 必须是 {sorted(RATIOS)} 之一，收到 {ratio!r}"

    common = [
        f"--prompt={prompt}",
        f"--duration={duration}",
        f"--model_version={model}",
        f"--video_resolution=720p",   # Seedance 家族仅 720p
        f"--poll={poll}",
    ]
    if operation == "text2video":
        args = ["text2video", *common]
        if ratio:
            args.append(f"--ratio={ratio}")
    elif operation == "image2video":
        # image2video：单首帧图，画幅由图推断（无 --ratio）
        if len(images) != 1:
            return None, "image2video 需要且仅需要 1 张 --image"
        args = ["image2video", f"--image={images[0]}", *common]
    elif operation == "multimodal2video":
        if not images and not videos:
            return None, "multimodal2video 至少需要 1 个 --image 或 --video"
        if len(images) > 9 or len(videos) > 3 or len(audios) > 3:
            return None, "多模态上限：图≤9 / 视频≤3 / 音频≤3"
        args = ["multimodal2video"]
        for p in images:
            args.append(f"--image={p}")
        for p in videos:
            args.append(f"--video={p}")
        for p in audios:
            args.append(f"--audio={p}")
        args += common
        if ratio:
            args.append(f"--ratio={ratio}")
    else:
        return None, f"未知 operation：{operation!r}（text2video/image2video/multimodal2video）"
    return args, None


def submit(operation: str, prompt: str, *, model: str = DEFAULT_MODEL, duration: int = 5,
           ratio: Optional[str] = "9:16", images: Optional[list[str]] = None,
           videos: Optional[list[str]] = None, audios: Optional[list[str]] = None,
           poll: int = 0) -> dict:
    """提交一个生成任务，返回 {success, submit_id, ...}。poll=0 即纯提交不等待。"""
    err = _check_cli()
    if err:
        return {"success": False, "error": err}
    args, berr = _build_gen_args(operation, prompt, model=model, duration=duration, ratio=ratio,
                                 images=images or [], videos=videos or [], audios=audios or [],
                                 poll=poll)
    if berr:
        return {"success": False, "error": berr}

    _err(f"[submit] {operation} model={model} dur={duration}s ratio={ratio or 'auto'} …")
    rc, out, serr = _run(args, timeout=max(120, poll + 60))
    blob = (out + "\n" + serr)
    if _COMPLIANCE_HINT in blob:
        return {"success": False, "error": "需先在 Dreamina 网页端完成该模型的一次性授权"
                "（返回了 AigcComplianceConfirmationRequired），授权后重试。"}
    data = _parse_json(out)
    sid = _extract_submit_id(data, blob)
    if not sid:
        return {"success": False, "error": (serr or out or "提交失败，未拿到 submit_id").strip()}
    return {"success": True, "submit_id": sid, "operation": operation, "raw": data}


def fetch(submit_id: str, out_dir: str, *, max_wait: int = 1800, interval: int = 15) -> dict:
    """轮询一个任务直到 success 并下载 MP4。超时返回 status 让上层稍后再 fetch。"""
    err = _check_cli()
    if err:
        return {"success": False, "error": err}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max_wait
    last_status = "unknown"
    while True:
        rc, out, serr = _run(
            ["query_result", f"--submit_id={submit_id}", f"--download_dir={out_dir}"], timeout=300)
        data = _parse_json(out)
        if isinstance(data, dict):
            last_status = data.get("gen_status", last_status)
            if last_status == "success":
                vids = (data.get("result_json") or {}).get("videos") or []
                paths = [v.get("path") for v in vids if v.get("path")]
                return {"success": bool(paths), "submit_id": submit_id, "status": "success",
                        "videos": paths, "credit_count": data.get("credit_count"),
                        "meta": vids, "error": None if paths else "success 但未取到视频路径"}
            if last_status in ("failed", "fail", "error", "not_pass", "rejected"):
                return {"success": False, "submit_id": submit_id, "status": last_status,
                        "error": data.get("fail_reason") or f"任务 {last_status}"}
        if time.time() >= deadline:
            return {"success": False, "submit_id": submit_id, "status": last_status,
                    "timed_out": True,
                    "error": f"等待 {max_wait}s 仍未完成（即梦排队常达数小时）。submit_id 已保留，"
                             f"稍后用 fetch --submit-id {submit_id} 取回，无需重新生成、不重复扣分。"}
        _err(f"[fetch] {submit_id} 状态={last_status}，{interval}s 后重试…")
        time.sleep(interval)


def generate(operation: str, prompt: str, *, out_dir: str, submit_only: bool = False,
             max_wait: int = 1800, interval: int = 15, **kw) -> dict:
    """提交 + （除非 submit_only）轮询下载，一步到位。"""
    s = submit(operation, prompt, poll=0, **kw)
    if not s.get("success"):
        return s
    sid = s["submit_id"]
    _err(f"[generate] 已提交 submit_id={sid}")
    if submit_only:
        return {"success": True, "submit_id": sid, "status": "submitted",
                "note": "仅提交。稍后 fetch --submit-id 取回。"}
    return fetch(sid, out_dir, max_wait=max_wait, interval=interval)


def batch(plan_path: str, out_dir: str, *, submit_only: bool = False,
          max_wait: int = 1800, interval: int = 15) -> dict:
    """批量执行分镜计划。plan = [{operation, prompt, duration, ratio, model, images?, ...}, ...]"""
    try:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except Exception as e:
        return {"success": False, "error": f"读取 plan 失败：{e}"}
    if isinstance(plan, dict) and "shots" in plan:
        plan = plan["shots"]
    if not isinstance(plan, list) or not plan:
        return {"success": False, "error": "plan 应为分镜数组（或 {shots:[...]})"}

    results = []
    for i, shot in enumerate(plan):
        _err(f"\n=== 分镜 {i + 1}/{len(plan)} ===")
        op = shot.get("operation", "text2video")
        prompt = shot.get("prompt", "")
        r = generate(
            op, prompt, out_dir=out_dir, submit_only=submit_only,
            max_wait=max_wait, interval=interval,
            model=shot.get("model", DEFAULT_MODEL),
            duration=int(shot.get("duration", 5)),
            ratio=shot.get("ratio", "9:16"),
            images=shot.get("images") or ([shot["image"]] if shot.get("image") else []),
            videos=shot.get("videos") or [],
            audios=shot.get("audios") or [],
        )
        r["index"] = i
        results.append(r)
    ok = sum(1 for r in results if r.get("success"))
    return {"success": ok == len(results), "total": len(results), "ok": ok,
            "results": results}


# ---- CLI --------------------------------------------------------------------

def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(0 if obj.get("success", True) else 1)


def main() -> None:
    p = argparse.ArgumentParser(description="即梦 Seedance 2.0 视频生成引擎")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("credits", help="查会员积分余额")

    def add_gen_flags(sp):
        sp.add_argument("--operation", default="text2video",
                        choices=["text2video", "image2video", "multimodal2video"])
        sp.add_argument("--prompt", required=True)
        sp.add_argument("--duration", type=int, default=5)
        sp.add_argument("--ratio", default="9:16")
        sp.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(SEEDANCE_MODELS))
        sp.add_argument("--image", action="append", default=[], help="可重复")
        sp.add_argument("--video", action="append", default=[], help="可重复")
        sp.add_argument("--audio", action="append", default=[], help="可重复")
        sp.add_argument("--out-dir", default="./clips")
        sp.add_argument("--max-wait", type=int, default=1800)
        sp.add_argument("--interval", type=int, default=15)

    g = sub.add_parser("gen", help="生成一条（提交+等待+下载）")
    add_gen_flags(g)

    s = sub.add_parser("submit", help="只提交，拿 submit_id")
    add_gen_flags(s)

    f = sub.add_parser("fetch", help="取回已提交任务并下载")
    f.add_argument("--submit-id", required=True)
    f.add_argument("--out-dir", default="./clips")
    f.add_argument("--max-wait", type=int, default=1800)
    f.add_argument("--interval", type=int, default=15)

    b = sub.add_parser("batch", help="批量执行分镜计划 JSON")
    b.add_argument("--plan", required=True)
    b.add_argument("--out-dir", default="./clips")
    b.add_argument("--submit-only", action="store_true")
    b.add_argument("--max-wait", type=int, default=1800)
    b.add_argument("--interval", type=int, default=15)

    a = p.parse_args()
    if a.cmd == "credits":
        _emit(credits())
    elif a.cmd in ("gen", "submit"):
        _emit(generate(
            a.operation, a.prompt, out_dir=a.out_dir, submit_only=(a.cmd == "submit"),
            max_wait=a.max_wait, interval=a.interval, model=a.model, duration=a.duration,
            ratio=a.ratio, images=a.image, videos=a.video, audios=a.audio))
    elif a.cmd == "fetch":
        _emit(fetch(a.submit_id, a.out_dir, max_wait=a.max_wait, interval=a.interval))
    elif a.cmd == "batch":
        _emit(batch(a.plan, a.out_dir, submit_only=a.submit_only,
                    max_wait=a.max_wait, interval=a.interval))


if __name__ == "__main__":
    main()

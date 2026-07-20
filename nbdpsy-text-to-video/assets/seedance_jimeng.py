"""Seedance 2.0 (ByteDance) video generation via the official 即梦/Dreamina CLI.

进阶可选 provider —— 让 OpenMontage 的 Seedance 槽位改吃**即梦会员积分**而非
按秒计费的美元（fal.ai / Replicate）。与 tools/video/seedance_video.py 是同一模型家族，
区别只在计费来源：本工具走本机已登录的 `dreamina` CLI（会员积分），cost_usd 恒为 0。

部署：把本文件放到 OpenMontage 的 `tools/video/` 目录即可被自动发现注册。
前置：`dreamina` 已安装并登录（curl -fsSL https://jimeng.jianying.com/cli | bash；
       登录跑 nbdpsy-text-to-video/scripts/dreamina_login.py 一键完成——自动弹浏览器/出二维码，抖音 App 扫码）。
       `dreamina user_credit` 应能看到积分。

实测约束（即梦 CLI，Seedance 2.0 家族）：
  - 分辨率仅 720p；duration 4-15s；
  - image_to_video 画幅由输入图推断（不接受 aspect_ratio）；
  - 生成异步、排队可能数小时 —— execute 阻塞轮询有超时，超时返回 submit_id 供稍后取回。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

_DREAMINA = shutil.which("dreamina") or os.path.expanduser("~/.local/bin/dreamina")
_SEEDANCE_MODELS = {"seedance2.0", "seedance2.0fast", "seedance2.0_vip", "seedance2.0fast_vip"}
_RATIOS = {"1:1", "3:4", "16:9", "4:3", "9:16", "21:9"}
_SUBMIT_ID_RE = re.compile(r"[0-9a-f]{16}")
_COMPLIANCE = "AigcComplianceConfirmationRequired"


class SeedanceJimeng(BaseTool):
    name = "seedance_jimeng"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    # 独立 provider 名（非 "seedance"）→ 不与 fal/replicate 版互相去重，可共存、可显式选用。
    provider = "seedance_jimeng"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:dreamina"]
    install_instructions = (
        "Install the official 即梦/Dreamina CLI and log in:\n"
        "  curl -fsSL https://jimeng.jianying.com/cli | bash\n"
        "  python3 nbdpsy-text-to-video/scripts/dreamina_login.py   # auto-opens browser / QR image; scan with the Douyin app\n"
        "  dreamina user_credit        # confirm membership credits\n"
        "Generation spends your membership credits (cost_usd is reported as 0)."
    )
    agent_skills = ["seedance-2-0", "ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video", "multimodal_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "reference_to_video": True,
        "multiple_reference_images": True,
        "native_audio": True,
        "cinematic_quality": True,
        "camera_direction": True,
        "lip_sync": True,
        "multi_shot": True,
        "aspect_ratio": True,
        "chinese_native": True,
        "seed": False,
    }
    best_for = [
        "preferred video gen when a 即梦 membership is available (spends credits, not USD)",
        "Chinese-native prompts, dialogue, and the strongest Mandarin lip-sync",
        "cinematic clips with native synchronized audio",
        "reference-conditioned generation (up to 9 images + 3 video + 3 audio)",
    ]
    not_good_for = [
        "1080p/2K output (CLI Seedance family is 720p only)",
        "low-latency or unattended pipelines (membership queue can be hours)",
    ]
    # 排队/可用性不稳时优雅降级到按量付费的同族工具。
    fallback_tools = ["seedance_video", "seedance_replicate", "veo_video", "kling_video"]
    quality_score = 0.95

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video", "multimodal_to_video"],
                "default": "text_to_video",
            },
            "model_variant": {
                "type": "string",
                "enum": ["seedance2.0", "seedance2.0fast", "seedance2.0_vip", "seedance2.0fast_vip"],
                "default": "seedance2.0fast",
                "description": "fast = 性价比, standard = 最高质量, _vip = 加速通道(更多积分换更短排队)",
            },
            "duration": {
                "type": "string",
                "enum": ["4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"],
                "default": "5",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["1:1", "3:4", "16:9", "4:3", "9:16", "21:9"],
                "default": "9:16",
                "description": "text/multimodal 生效；image_to_video 画幅由输入图推断、此项忽略",
            },
            "image_path": {"type": "string", "description": "image_to_video 的首帧本地图片"},
            "image_paths": {
                "type": "array", "items": {"type": "string"},
                "description": "multimodal_to_video 参考图(≤9)",
            },
            "video_paths": {
                "type": "array", "items": {"type": "string"},
                "description": "multimodal_to_video 参考视频(≤3)",
            },
            "audio_paths": {
                "type": "array", "items": {"type": "string"},
                "description": "multimodal_to_video 参考音频(≤3，2-15s)",
            },
            "poll_timeout_seconds": {
                "type": "integer", "default": 1800,
                "description": "阻塞等待上限；超时返回 submit_id 供稍后取回(不重复扣分)",
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["prompt", "model_variant", "operation", "duration", "aspect_ratio"]
    side_effects = ["writes video file to output_path", "spends 即梦 membership credits"]
    user_visible_verification = [
        "Watch generated clip for motion coherence, Mandarin lip-sync, and visual quality"
    ]

    # ---- helpers ----

    def _run(self, args: list[str], timeout: int) -> tuple[int, str, str]:
        try:
            p = subprocess.run([_DREAMINA, *args], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
            return p.returncode, p.stdout or "", p.stderr or ""
        except subprocess.TimeoutExpired:
            return 124, "", f"dreamina timeout ({timeout}s)"
        except FileNotFoundError:
            return 127, "", "dreamina not executable"

    @staticmethod
    def _json(text: str) -> Any:
        text = (text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if 0 <= start < end:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    return None
        return None

    # ---- contract ----

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # 走会员积分，不占 OpenMontage 的美元预算。实际积分消耗在结果 data.credit_count 里回报。
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 600.0  # 含排队的粗略预期；实际可能远超(数小时)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not (_DREAMINA and Path(_DREAMINA).exists()):
            return ToolResult(success=False, error="dreamina CLI not found. " + self.install_instructions)

        start = time.time()
        op = inputs.get("operation", "text_to_video")
        prompt = inputs.get("prompt", "")
        model = inputs.get("model_variant", "seedance2.0fast")
        duration = str(inputs.get("duration", "5"))
        ratio = inputs.get("aspect_ratio", "9:16")
        if model not in _SEEDANCE_MODELS:
            return ToolResult(success=False, error=f"model_variant must be one of {sorted(_SEEDANCE_MODELS)}")
        if ratio and ratio not in _RATIOS:
            return ToolResult(success=False, error=f"aspect_ratio must be one of {sorted(_RATIOS)}")

        common = [f"--prompt={prompt}", f"--duration={duration}",
                  f"--model_version={model}", "--video_resolution=720p", "--poll=0"]
        if op == "text_to_video":
            args = ["text2video", *common, f"--ratio={ratio}"]
        elif op == "image_to_video":
            img = inputs.get("image_path")
            if not img or not Path(img).exists():
                return ToolResult(success=False, error="image_to_video requires a valid image_path")
            args = ["image2video", f"--image={img}", *common]  # 画幅由图推断，无 --ratio
        elif op == "multimodal_to_video":
            imgs = list(inputs.get("image_paths") or [])
            vids = list(inputs.get("video_paths") or [])
            auds = list(inputs.get("audio_paths") or [])
            if not imgs and not vids:
                return ToolResult(success=False, error="multimodal_to_video needs at least one image or video")
            if len(imgs) > 9 or len(vids) > 3 or len(auds) > 3:
                return ToolResult(success=False, error="limits: images<=9, videos<=3, audio<=3")
            args = ["multimodal2video"]
            args += [f"--image={p}" for p in imgs]
            args += [f"--video={p}" for p in vids]
            args += [f"--audio={p}" for p in auds]
            args += [*common, f"--ratio={ratio}"]
        else:
            return ToolResult(success=False, error=f"unknown operation: {op!r}")

        # 1) 提交
        rc, out, serr = self._run(args, timeout=180)
        blob = out + "\n" + serr
        if _COMPLIANCE in blob:
            return ToolResult(success=False, error="需先在 Dreamina 网页端完成该模型一次性授权"
                              "(AigcComplianceConfirmationRequired)，授权后重试。")
        parsed = self._json(out)
        sid = None
        if isinstance(parsed, dict):
            sid = parsed.get("submit_id")
        if not sid:
            m = _SUBMIT_ID_RE.search(blob)
            sid = m.group(0) if m else None
        if not sid:
            return ToolResult(success=False, error=(serr or out or "submit failed").strip())

        # 2) 轮询下载
        out_path = Path(inputs.get("output_path", "seedance_jimeng_output.mp4"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        dl_dir = out_path.parent
        deadline = time.time() + int(inputs.get("poll_timeout_seconds", 1800))
        status = "unknown"
        while True:
            rc, out, serr = self._run(
                ["query_result", f"--submit_id={sid}", f"--download_dir={dl_dir}"], timeout=300)
            data = self._json(out)
            if isinstance(data, dict):
                status = data.get("gen_status", status)
                if status == "success":
                    vids = (data.get("result_json") or {}).get("videos") or []
                    paths = [v.get("path") for v in vids if v.get("path")]
                    if not paths:
                        return ToolResult(success=False, error="success but no video path returned")
                    # 落到约定的 output_path
                    final = str(out_path)
                    if os.path.abspath(paths[0]) != os.path.abspath(final):
                        shutil.move(paths[0], final)
                    meta = vids[0]
                    return ToolResult(
                        success=True,
                        data={
                            "provider": "seedance_jimeng",
                            "gateway": "jimeng_cli",
                            "model": model,
                            "prompt": prompt,
                            "operation": op,
                            "aspect_ratio": ratio,
                            "resolution": "720p",
                            "submit_id": sid,
                            "credit_count": data.get("credit_count"),
                            "width": meta.get("width"),
                            "height": meta.get("height"),
                            "fps": meta.get("fps"),
                            "duration_probed": meta.get("duration"),
                            "output": final,
                            "output_path": final,
                            "format": "mp4",
                        },
                        artifacts=[final],
                        cost_usd=0.0,
                        duration_seconds=round(time.time() - start, 2),
                        model=model,
                    )
                if status in ("failed", "fail", "error", "not_pass", "rejected"):
                    return ToolResult(success=False,
                                      error=f"task {status}: {data.get('fail_reason') or ''} (submit_id={sid})")
            if time.time() >= deadline:
                return ToolResult(
                    success=False,
                    error=(f"timed out after waiting; 即梦排队常达数小时。submit_id={sid} 已保留，"
                           f"稍后用 `dreamina query_result --submit_id={sid} --download_dir=<dir>` "
                           f"取回，不会重复扣分。"))
            time.sleep(15)

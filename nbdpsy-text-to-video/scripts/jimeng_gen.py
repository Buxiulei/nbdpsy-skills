#!/usr/bin/env python3
"""即梦(Dreamina)视频生成引擎 —— nbdpsy-text-to-video skill 的核心（双后端薄客户端）。

两条后端，子命令 stdout JSON 契约**向后兼容**：服务化之前的键**一个不少**（success / submit_id /
operation / status / videos / credit_count / meta / raw / error），server 侧另附几个新键
（`backend` 恒有，视子命令还有 `client_ref` / `video_url` / `expires_at` / `batch_id` /
`low_threshold_hit`）——老解析按需忽略即可：
  - **server**：调 nbdpsy-server 的即梦 REST 面（`/api/video-clips` 等）。登录态、dreamina CLI、
    积分全在 server 一份（公司号）——运营免装 CLI、免扫码，排队也不用挂着本机会话。
  - **local**：本机 `dreamina` CLI，行为与服务化之前**逐字一致**（无网/未上线时的兜底）。

后端选择：`--backend server|local|auto`（默认 auto；环境变量 `NBDPSY_JIMENG_BACKEND` 改默认，
显式 `--backend` 优先于环境变量）。auto 规则（进程内探测一次并缓存）：
  - 没有 NBDPSY_XHS_API_KEY → local；
  - `GET /api/dreamina-status` 200 且 `logged_in` 为真 → server；
  - 200 但 `logged_in` 假 → 有本机 CLI 则回落 local（stderr 提示），本机也没 CLI 则明确报错（不静默）；
  - 404/405（server 未上线该能力）或网络异常/没装 requests → local + stderr 一行提示。

资金安全（这条产线「重复提交」不是浪费时间而是**烧钱**：submit 即占队列位、success 即扣积分）：
  - 每次 submit 生成一个 `client_ref`(uuid4) 幂等键；**单镜 POST** 只有 requests 网络异常才重发一次，
    且**复用同一个 client_ref**（服务端按 ref 回已有 clip_id，不新建、不二次扣分）；
    HTTP 4xx/5xx 一律不重发，把 detail/error 原文透出。
  - **批量 POST（/api/video-clip-batches）同样只在网络异常时重发一次且复用同一组 ref**：
    批量端点的逐镜 ref 去重已经 server 验收（2026-08-05 回执：同 shots 同 refs 重放 →
    原 clip_ids 零新增零扣分，且去重先于登录/积分闸），重发是安全的。
  - 任何代码路径都**不会**对卡 querying 的任务自动重提；fetch 超时保留 submit_id、提示稍后再取
    （不重复扣分）。重提是运营的决策，不是脚本的。

本地 CLI 侧设计依据（均为本机实测，非二手）：
  - `dreamina` 输出默认是干净 JSON；
  - 任务对象顶层有 `submit_id`，状态在 `gen_status`(querying/success/...)；
  - `query_result --submit_id=X --download_dir=Y` 成功后返回
    `result_json.videos[].path`（已下载到本地的真实路径，命名 {submit_id}_video_N.mp4），
    并带 `credit_count`（该任务消耗的积分）；
  - `--video_resolution` 必填且逐档严格校验，各档支持的分辨率并不一致（2.5 只有 480p/720p、
    seedance2.0_vip 到 4k、其余只有 720p），**720p 是唯一对全家族都合法的一档**，故统一传它；
    image2video 的画幅由输入图推断（无 --ratio）。

所有结构化结果打到 **stdout(JSON)**，人类可读进度打到 **stderr**，方便上层 agent 解析。

用法示例：
  python jimeng_gen.py credits
  python jimeng_gen.py gen --operation text2video --prompt "温暖诊室空镜，晨光缓缓移过沙发" \
      --duration 5 --ratio 9:16 --model seedance2.5 --out-dir ./clips
  python jimeng_gen.py gen --operation image2video --image ./counselor.png \
      --prompt "镜头缓慢推近，人物轻轻点头" --duration 8 --out-dir ./clips
  python jimeng_gen.py submit --operation text2video --prompt "..." --duration 5   # 只提交，拿 submit_id
  python jimeng_gen.py fetch --submit-id 3d64c2221c0e07da --out-dir ./clips        # 取回已提交任务
  python jimeng_gen.py batch --plan shots.json --out-dir ./clips                   # 批量(支持 --submit-only)
  python jimeng_gen.py credits --backend local                                     # 强制本机 CLI
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
import uuid
from pathlib import Path
from typing import Any, Optional

# 同目录 vendored 副本（凭据/服务基址三层解析，真源在仓库 shared/）
import nbdpsy_common

# ---- 常量 -------------------------------------------------------------------

DREAMINA = shutil.which("dreamina") or os.path.expanduser("~/.local/bin/dreamina")

# Seedance 家族（CLI 暴露的六个档位）。2.0 系：standard 质量最高，fast 性价比高，
# _vip 走加速通道（额外积分换更短排队），mini 是轻量档；**seedance2.5 是新一代，没有
# fast / vip 变体**，且是 VIP-only。
SEEDANCE_MODELS = {
    "seedance2.0",
    "seedance2.0fast",
    "seedance2.0_vip",
    "seedance2.0fast_vip",
    "seedance2.0mini",
    "seedance2.5",
}
DEFAULT_MODEL = "seedance2.5"
RATIOS = {"1:1", "3:4", "16:9", "4:3", "9:16", "21:9"}
OPERATIONS = ("text2video", "image2video", "multimodal2video", "frames2video", "multiframe2video")
# duration 合法区间：下限全家族 4s；上限**只有 seedance2.5 到 30s**，其余仍是 15s。
DUR_MIN, DUR_MAX = 4, 30
_DUR_MAX_DEFAULT = 15
_DUR_MAX_BY_MODEL = {"seedance2.5": 30}


def max_duration(model: str) -> int:
    """该模型的单镜时长上限（秒）。未知档按家族默认 15s 判——宁可窄不宜宽，放宽只会让一条
    CLI/服务端必拒的镜白跑一趟提交。"""
    return _DUR_MAX_BY_MODEL.get(model, _DUR_MAX_DEFAULT)

# 图片参考张数上限（server 2026-08-06 回执确认，与 CLI help 一致）：2.5 是 30，2.0 家族是 9。
# 未知档按 9 判——宁可窄不宜宽，放宽只会让一镜白跑一趟提交。
_MULTI_IMAGE_CAP = {"seedance2.5": 30}
_MULTI_IMAGE_CAP_DEFAULT = 9
# 视频/音频参考条数上限（同 images 的宁窄勿宽原则）
_MULTI_AV_CAP = {"seedance2.5": 10}
_MULTI_AV_CAP_DEFAULT = 3

_SUBMIT_ID_RE = re.compile(r"[0-9a-f]{16}")
_COMPLIANCE_HINT = "AigcComplianceConfirmationRequired"

# ---- server 端点 / 回执字段（**改这一块即可跟上服务端命名微调**）--------------

EP_CLIP_SUBMIT = "/api/video-clips"                       # POST → 202 {clip_id}
EP_CLIP_STATUS = "/api/video-clips/{clip_id}"             # GET  → 单镜状态
EP_BATCH_SUBMIT = "/api/video-clip-batches"               # POST {shots:[...]} → 202 {batch_id, clip_ids[]}
EP_BATCH_STATUS = "/api/video-clip-batches/{batch_id}"    # GET  → 逐镜状态汇总（本脚本按镜轮询，备用）
EP_CREDITS = "/api/video-credits"                         # GET  → {credit, low_threshold_hit}
EP_DREAMINA_STATUS = "/api/dreamina-status"               # GET  → {logged_in, credit, compliance_confirmed_models}
EP_UPLOAD_IMAGES = "/api/uploads/images"                  # POST multipart(files) → {batch_id, urls, expires_at}

K_CLIP_ID = "clip_id"
K_CLIP_IDS = "clip_ids"
K_BATCH_ID = "batch_id"
K_SHOTS = "shots"
K_STATUS = "status"
K_VIDEO_URL = "video_url"
K_CREDIT = "credit"
K_CREDIT_COUNT = "credit_count"
K_LOW_THRESHOLD = "low_threshold_hit"
K_QUEUED_SECONDS = "queued_seconds"
K_EXPIRES_AT = "expires_at"
K_LOGGED_IN = "logged_in"
K_COMPLIANCE_MODELS = "compliance_confirmed_models"
K_URLS = "urls"
# 服务端单镜状态机：queued|submitted|querying|done|error
SRV_DONE = "done"
SRV_ERROR = "error"

# 后端选择
BACKEND_ENV = "NBDPSY_JIMENG_BACKEND"
BACKEND_CHOICES = ("server", "local", "auto")
PROBE_TIMEOUT = 10          # /api/dreamina-status 探测超时（秒）
MAX_TRANSIENT = 3           # 轮询期瞬时故障容忍次数——一次抖动绝不能把在跑的任务判成终态
_PROBE_CACHE: dict[str, dict] = {}   # 进程内按 base 缓存探测结果（auto 只探一次）


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


# ---- 底层：调 nbdpsy-server ---------------------------------------------------

class BackendError(Exception):
    """后端不可用且没有安全兜底——消息本身就是给运营看的人话，绝不静默降级。"""


def _requests():
    """**惰性 import** requests：老机器没装它也不能炸掉本地 CLI 路径（credits/gen 全本地可用）。"""
    import requests
    return requests


def _server_request(method: str, url: str, key: str, payload=None, timeout: int = 60):
    """带 apikey 鉴权调 nbdpsy-server（与 nbdpsy-youtube-transport 同款 Bearer 惯例）。
    网络异常向上抛，由调用方按「是否已提交」决定语义。"""
    requests = _requests()
    headers = {"Authorization": f"Bearer {key}"}
    return requests.request(method, url, json=payload, headers=headers, timeout=timeout)


def _resp_text(resp) -> str:
    try:
        return (resp.text or "")[:200]
    except Exception:  # noqa: BLE001 — 取不到正文不能反过来炸掉错误处理
        return ""


def _resp_json(resp) -> Any:
    """解析响应体；非 JSON 返回 None（调用方给人话错误，绝不裸抛）。"""
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _api_error(resp) -> str:
    """错误契约（nbdpsy-server）：400/401/403/404 键是 error；409/422 键是 detail。双键兼容。"""
    data = _resp_json(resp)
    msg = None
    if isinstance(data, dict):
        msg = data.get("error") or data.get("detail")
    if not msg:
        msg = _resp_text(resp)
    return _with_compliance(f"HTTP {resp.status_code}: {msg}")


def _with_compliance(msg: str) -> str:
    """服务端透传的 AigcComplianceConfirmationRequired 要**原文保留 + 给人话下一步**：
    这是要人去 Dreamina 网页端点一次性授权的（账号级），服务端/客户端重试都无意义。"""
    if _COMPLIANCE_HINT in (msg or ""):
        return (f"{msg} —— 需先在 Dreamina 网页端完成该模型的一次性授权"
                "（返回了 AigcComplianceConfirmationRequired），授权后重试。")
    return msg


def _api_ctx(api_base: Optional[str] = None) -> tuple[Optional[str], str]:
    """(apikey, base)。凭据与视频服务基址都复用 youtube-transport 那套（同一台 server、同一把 key）。"""
    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    base = (api_base or nbdpsy_common.video_api_base()).rstrip("/")
    return key, base


def _server_key_or_error(api_base: Optional[str] = None):
    """server 路径入口：拿 (key, base)；没凭据时返回可直接 _emit 的错误信封。"""
    key, base = _api_ctx(api_base)
    if not key:
        return None, base, {
            "success": False, "backend": "server",
            "error": f"MISSING:{nbdpsy_common.XHS_API_KEY} —— server 模式需要 nbdpsy-server apikey"
                     "（与小红书自动发布同一把）。找管理员要「运营接入配置包」，"
                     "`nbdpsy_common.py secret import <配置包>` 导入后重试；"
                     "或加 --backend local 走本机 dreamina CLI。"}
    return key, base, None


def _abs_url(url: str, base: str) -> str:
    """产物相对路径（/uploads/…）拼成公网绝对 URL；已是 http(s) 的原样保留。"""
    return url if url.startswith(("http://", "https://")) else base + "/" + url.lstrip("/")


def probe_server(api_base: Optional[str] = None, *, timeout: int = PROBE_TIMEOUT) -> dict:
    """探测 server 侧即梦能力（GET /api/dreamina-status），**进程内按 base 只探一次**。

    返回 {available, logged_in, credit, compliance_confirmed_models, reason, base}：
    available=True 只代表「server 上线了这个能力且回了 JSON」，登录态另看 logged_in。
    """
    key, base = _api_ctx(api_base)
    cached = _PROBE_CACHE.get(base)
    if cached is not None:
        return cached
    info = {"available": False, "logged_in": False, "credit": None,
            "compliance_confirmed_models": [], "reason": None, "base": base}
    if not key:
        info["reason"] = f"未配 {nbdpsy_common.XHS_API_KEY}"
    else:
        try:
            resp = _server_request("GET", base + EP_DREAMINA_STATUS, key, timeout=timeout)
        except ImportError:
            info["reason"] = "本机没装 requests（pip install requests）"
        except Exception as e:  # noqa: BLE001 — 网络不通不是错误，是「走本地」的信号
            info["reason"] = f"探测 {base}{EP_DREAMINA_STATUS} 失败：{str(e)[:120]}"
        else:
            if resp.status_code in (404, 405):
                info["reason"] = f"server 尚未上线即梦能力（HTTP {resp.status_code}）"
            elif resp.status_code >= 400:
                info["reason"] = _api_error(resp)
            else:
                data = _resp_json(resp)
                if not isinstance(data, dict):
                    info["reason"] = f"{EP_DREAMINA_STATUS} 返回的不是 JSON：{_resp_text(resp)}"
                else:
                    info.update(available=True,
                                logged_in=bool(data.get(K_LOGGED_IN)),
                                credit=data.get(K_CREDIT),
                                compliance_confirmed_models=data.get(K_COMPLIANCE_MODELS) or [])
    _PROBE_CACHE[base] = info
    return info


def _backend_choice(explicit: Optional[str] = None) -> str:
    """不打网络的后端意向：显式 --backend > 环境变量 > auto。"""
    c = (explicit or os.environ.get(BACKEND_ENV) or "auto").strip().lower()
    return c if c in BACKEND_CHOICES else "auto"


def resolve_backend(explicit: Optional[str] = None, api_base: Optional[str] = None) -> str:
    """定后端，返回 "server" / "local"；无安全兜底时抛 BackendError（绝不静默）。"""
    choice = _backend_choice(explicit)
    if choice != "auto":
        return choice
    info = probe_server(api_base)
    notify = not info.get("_notified")
    info["_notified"] = True
    if info["available"] and info["logged_in"]:
        return "server"
    if info["available"]:   # 服务在，但登录态没了（管理员要重迁 ~/.dreamina_cli/）
        if _check_cli() is None:
            if notify:
                _err("[backend] server 侧即梦未登录（logged_in=false），已回落本机 dreamina CLI；"
                     "请管理员把登录态迁到 server。")
            return "local"
        raise BackendError(
            "server 侧即梦未登录（/api/dreamina-status.logged_in=false），本机也没装 dreamina CLI —— "
            "请管理员把 ~/.dreamina_cli/ 登录态迁到 server；或本机装 CLI 后用 --backend local。")
    if notify:
        _err(f"[backend] 用本机 dreamina CLI（{info['reason']}）")
    return "local"


# ---- server：单镜提交 ---------------------------------------------------------

def _validate_basics(model: str, duration: int, ratio: Optional[str]) -> Optional[str]:
    """model / duration / ratio 三项通用校验（两个后端共用，话术与本地 CLI 版逐字一致）。"""
    if model not in SEEDANCE_MODELS:
        return f"model 必须是 {sorted(SEEDANCE_MODELS)} 之一，收到 {model!r}"
    ceiling = max_duration(model)
    if not (DUR_MIN <= duration <= ceiling):
        return (f"duration 必须在 {DUR_MIN}-{ceiling}s（{model}），收到 {duration}。"
                f"仅 seedance2.5 支持到 {DUR_MAX}s，其余模型上限 {_DUR_MAX_DEFAULT}s")
    if ratio and ratio not in RATIOS:
        return f"ratio 必须是 {sorted(RATIOS)} 之一，收到 {ratio!r}"
    return None


def _is_remote(ref: Any) -> bool:
    """server 能自取的媒体：图床直链 或 本服务 /uploads 路径（比照 note-components 的 add_images，
    不收 base64 大包）。本机文件路径 server 拿不到，只能回落本地 CLI。"""
    return isinstance(ref, str) and ref.startswith(("http://", "https://", "/uploads"))


def _shot_server_capable(images: list, videos: list, audios: list) -> tuple[bool, str]:
    """这一镜能否交给 server 跑。不能跑的**整镜回落本地 CLI**（而不是静默丢掉媒体）。"""
    # videos[]/audios[] 自 2026-08-06 晚起 server 已开放（multimodal2video），不再回落。
    # 与图不同：视频/音频没有「本机文件换直链」的上传端点，本机路径仍须回落本地 CLI。
    bad_av = [r for r in (list(videos) + list(audios)) if not _is_remote(r)]
    if bad_av:
        return False, f"参考视频/音频是本机路径（{bad_av[0]}），server 取不到（图床只收图片）"
    bad = [r for r in images if not _is_remote(r)]
    if bad:
        return False, f"参考图是本机路径（{bad[0]}），server 取不到"
    return True, ""


# 图床按扩展名判 MIME（服务端另用 Pillow 真解字节流定落盘扩展名，这里只是 multipart 的申报值）
_UPLOAD_MIME = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _upload_ref_image(path: str, key: Optional[str], base: str,
                      *, timeout: int = 60) -> tuple[Optional[str], Optional[str]]:
    """本机参考图 → POST /api/uploads/images（multipart，字段名 `files`）换图床直链。
    返回 (url, error)。

    **网络异常直接重试一次，不需要幂等键** —— 与 `_post_idempotent` 的提交类 POST 语义相反：
    上传免费、不占即梦队列、不扣积分，重复一次至多在图床多留一个批次（server 侧带 TTL 自清），
    而提交类 POST 重复一次就是双倍扣分，所以那边只敢在复用 client_ref 的前提下重发。
    """
    if not key:
        return None, f"未配 {nbdpsy_common.XHS_API_KEY}，无法上传图床"
    p = Path(path)
    if not p.is_file():
        return None, f"参考图不存在：{path}"
    mime = _UPLOAD_MIME.get(p.suffix.lower())
    if not mime:
        return None, f"图床只收 png/jpg/jpeg/webp，本图是 {p.suffix or '无扩展名'}：{path}"
    try:
        data = p.read_bytes()
    except OSError as e:
        return None, f"读取参考图失败（{path}）：{str(e)[:150]}"
    try:
        requests = _requests()
    except ImportError as e:
        return None, f"上传图床需要 requests（pip install requests）：{e}"

    url = base + EP_UPLOAD_IMAGES
    headers = {"Authorization": f"Bearer {key}"}
    files = {"files": (p.name, data, mime)}   # 字段名固定 files（server multipart 契约，可多值）
    neterrs = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
    last = None
    for attempt in range(2):
        try:
            resp = requests.post(url, files=files, headers=headers, timeout=timeout)
        except neterrs as e:
            last = e
            if attempt == 0:
                _err(f"[upload] {p.name} 网络异常（{str(e)[:120]}），重试一次"
                     "（上传免费无副作用，重试不会多花钱）…")
            continue
        except Exception as e:  # noqa: BLE001 — 非网络异常不重试
            return None, f"上传失败：{str(e)[:200]}"
        if resp.status_code >= 400:
            return None, _api_error(resp)
        data_j = _resp_json(resp)
        if not isinstance(data_j, dict):
            return None, f"{EP_UPLOAD_IMAGES} 返回的不是 JSON：{_resp_text(resp)}"
        urls = data_j.get(K_URLS)
        if not isinstance(urls, list) or not urls or not isinstance(urls[0], str) or not urls[0]:
            return None, (f"上传回执没带可用的 {K_URLS}："
                          f"{json.dumps(data_j, ensure_ascii=False)[:200]}")
        _err(f"[upload] {p.name} → {urls[0]}")
        return urls[0], None
    return None, f"上传失败（网络异常，已重试 1 次）：{str(last)[:200]}"


def _prepare_server_shot(operation: str, images: list, videos: list, audios: list,
                         key: Optional[str], base: str) -> tuple[list, bool, str]:
    """server 路径的媒体预处理：本机参考图先传图床换直链，让这一镜留在 server 上跑。
    返回 (images, capable, why)。

    处理「image2video / multimodal2video + 本机图 + 无 video/audio」：本机图逐张换直链，
    **顺序原样保持**（数组第 N 张 = 提示词里的 @图片N，换成直链后编号不能变）。
    带 video/audio 的镜 server 契约还表达不了，维持整镜回落本机 CLI 不变。
    任一张上传失败即整镜回落（保留原有安全网）——半数换成直链、半数还是本机路径的混合态
    会让 @图片N 编号对不上，比回落更糟。
    """
    capable, why = _shot_server_capable(images, videos, audios)
    if capable:
        return images, True, ""
    # 非字符串的 image（plan JSON 写歪了）交回原路：本地 CLI 那边会如实报错，
    # 而不是在这里 Path(123) 裸抛把整批崩成 traceback（stdout 就没 JSON 信封了）
    if (operation not in ("image2video", "multimodal2video")
            or videos or audios or not images
            or not all(isinstance(x, str) for x in images)):
        return images, False, why
    if operation == "image2video" and len(images) != 1:
        return images, False, why      # image2video 就该只有 1 张，多的交回原路报错
    out = []
    for ref in images:
        if _is_remote(ref):
            out.append(ref)             # 已是直链的原位保留，不重复上传
            continue
        url, uerr = _upload_ref_image(ref, key, base)
        if uerr:
            return images, False, f"参考图上传图床失败（{ref}：{uerr}）"
        out.append(url)
    return out, True, ""


def _shot_payload(operation: str, prompt: str, *, model: str, duration: int,
                  ratio: Optional[str], images: list,
                  videos: Optional[list] = None, audios: Optional[list] = None,
                  transition_prompts: Optional[list] = None,
                  transition_durations: Optional[list] = None,
                  ) -> tuple[Optional[dict], Optional[str]]:
    """组装单镜 server payload；返回 (payload, error)。

    `client_ref` 在这里生成一次（uuid4 幂等键）——重发时**整份 payload 原样复用**，绝不重新生成，
    否则同一次提交会在服务端变成两个任务、双倍扣积分。
    """
    videos, audios = videos or [], audios or []
    berr = _validate_basics(model, duration, ratio)
    if berr:
        return None, berr
    if operation not in OPERATIONS:
        return None, f"未知 operation：{operation!r}（{'/'.join(OPERATIONS)}）"
    if operation == "frames2video":
        # 首尾帧：first/last 成对必填；ratio 由首帧图推断，传了 server 422
        if len(images) != 2:
            return None, "frames2video 需要恰好 2 张图：首帧 + 尾帧（按顺序传 --image 两次）"
        return {"operation": operation, "prompt": prompt, "duration": duration,
                "model": model, "client_ref": uuid.uuid4().hex,
                "first_image": images[0], "last_image": images[1]}, None
    if operation == "multiframe2video":
        # 多帧故事：2–20 张故事帧 + N-1 段转场；模型平台固定（传 model 422）、长式不收 prompt
        if not 2 <= len(images) <= 20:
            return None, f"multiframe2video 需要 2–20 张故事帧，收到 {len(images)} 张"
        payload = {"operation": operation, "client_ref": uuid.uuid4().hex,
                   "images": list(images)}
        if transition_prompts:
            if len(transition_prompts) != len(images) - 1:
                return None, (f"transition_prompts 须恰好 {len(images)-1} 段"
                              f"（N 张图 N-1 段），收到 {len(transition_prompts)}")
            payload["transition_prompts"] = list(transition_prompts)
        if transition_durations:
            if len(transition_durations) != len(images) - 1:
                return None, f"transition_durations 须恰好 {len(images)-1} 段"
            payload["transition_durations"] = [float(x) for x in transition_durations]
        return payload, None
    payload = {"operation": operation, "prompt": prompt, "duration": duration,
               "model": model, "client_ref": uuid.uuid4().hex}
    if operation == "image2video":
        if len(images) != 1:
            return None, "image2video 需要且仅需要 1 张 --image"
        payload["image"] = images[0]
        # image2video 画幅由输入图推断，**一律不带 ratio 字段**（服务端收到就 422）
    else:
        if operation == "multimodal2video":
            if not (images or videos or audios):
                return None, "multimodal2video 至少需要一个参考（--image/--video/--audio）"
            if not images and not videos and model != "seedance2.5":
                return None, "纯音频输入仅 seedance2.5 支持（2.0 家族至少要 1 个 image 或 video）"
            cap = _MULTI_IMAGE_CAP.get(model, _MULTI_IMAGE_CAP_DEFAULT)
            if len(images) > cap:
                return None, (f"{model} 的图片参考上限 {cap} 张，本镜给了 {len(images)} 张"
                              f"（2.5 是 30、2.0 家族是 9）")
            av_cap = _MULTI_AV_CAP.get(model, _MULTI_AV_CAP_DEFAULT)
            if len(videos) > av_cap:
                return None, f"{model} 的视频参考上限 {av_cap} 条，本镜给了 {len(videos)}"
            if len(audios) > av_cap:
                return None, f"{model} 的音频参考上限 {av_cap} 条，本镜给了 {len(audios)}"
            # **顺序即语义**：@图片N/@视频N/@音频N 各按数组序号；保序不去重（server 回归锁）。
            if images:
                payload["images"] = list(images)
            if videos:
                payload["videos"] = list(videos)
            if audios:
                payload["audios"] = list(audios)
        # text2video **一律不带 image**：本地 CLI 的 text2video 完全忽略 images（远程图也照样忽略），
        # 契约里 image 字段也只标了「image2video 用」，带上去 server 可能 422
        if ratio:
            payload["ratio"] = ratio
    return payload, None


def _post_idempotent(url: str, key: str, payload: dict, *, timeout: int = 60,
                     retry_on_neterr: bool = True):
    """提交类 POST。返回 (resp, error)。

    **只在 requests 网络异常（Timeout/ConnectionError）时重发一次，且复用同一份 payload**
    ——即同一个 client_ref，服务端按 ref 回已有 clip_id，不新建任务、不二次扣分。
    HTTP 4xx/5xx **一律不重发**：那是服务端已收到并明确拒绝，重发只会烧钱。

    `retry_on_neterr=False` 保留给「服务端幂等未经验收」的端点：ReadTimeout 说明请求可能已
    到服务端入队，此时自动重发是在赌服务端按 ref 去重，赌输就是双倍扣分。批量端点曾因此关闭
    重发；2026-08-05 server 回执已验收「同 shots 同 refs 批量重放 → 原 clip_ids 零新增零扣分」
    （逐镜 (created_by, client_ref) 唯一键 + 去重先于登录/积分闸），批量已恢复重发。
    """
    try:
        requests = _requests()
    except ImportError as e:
        return None, f"server 模式需要 requests（pip install requests）：{e}"
    neterrs = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
    attempts = 2 if retry_on_neterr else 1
    last = None
    for attempt in range(attempts):
        try:
            return _server_request("POST", url, key, payload, timeout=timeout), None
        except neterrs as e:
            last = e
            if attempt + 1 < attempts:
                _err(f"[submit] 网络异常（{str(e)[:120]}），复用同一 client_ref 重发一次（幂等键防重复扣分）…")
        except Exception as e:  # noqa: BLE001 — 非网络异常不重发
            return None, f"提交失败：{str(e)[:200]}"
    if retry_on_neterr:
        return None, (f"提交失败（网络异常，已带同一 client_ref 重试 1 次，不会重复扣分）：{str(last)[:200]}")
    return None, (f"批量提交网络异常（未自动重发）：{str(last)[:200]}。"
                  "请求可能已到达服务端、整批已入队——**先别重跑本批**（批量端点的逐镜幂等未验收，"
                  "重发可能双倍扣分且排队中无法取消）：先查 server 侧任务与积分，确认没入队再重提。")


def _server_submit(operation: str, prompt: str, *, api_base: Optional[str], model: str,
                   duration: int, ratio: Optional[str], images: list,
                   videos: Optional[list] = None, audios: Optional[list] = None,
                   transition_prompts: Optional[list] = None,
                   transition_durations: Optional[list] = None) -> dict:
    """POST /api/video-clips 提交单镜 → {success, submit_id(=clip_id 字符串), operation, backend}。
    submit_id 对上层保持**不透明句柄**语义：本地是 16 位 hex、server 是 clip_id，都只用于 fetch。"""
    key, base, kerr = _server_key_or_error(api_base)
    if kerr:
        return kerr
    payload, perr = _shot_payload(operation, prompt, model=model, duration=duration,
                                  ratio=ratio, images=images, videos=videos, audios=audios,
                                  transition_prompts=transition_prompts,
                                  transition_durations=transition_durations)
    if perr:
        return {"success": False, "error": perr, "backend": "server"}
    _err(f"[submit] {operation} model={model} dur={duration}s "
         f"ratio={payload.get('ratio') or 'auto'} → server …")
    resp, neterr = _post_idempotent(base + EP_CLIP_SUBMIT, key, payload)
    if neterr:
        return {"success": False, "error": neterr, "backend": "server"}
    if resp.status_code >= 400:
        return {"success": False, "error": _api_error(resp), "backend": "server"}
    data = _resp_json(resp)
    if not isinstance(data, dict):
        return {"success": False, "backend": "server",
                "error": f"server 返回的不是 JSON（HTTP {resp.status_code}）：{_resp_text(resp)}"}
    if data.get("warning"):   # 低积分守卫：只提示不拦截（扣费 success 才结算，排队中还有变数）
        _err(f"[submit] server 提示：{data['warning']}")
    cid = data.get(K_CLIP_ID)
    if cid in (None, ""):
        return {"success": False, "backend": "server",
                "error": f"server 回了 HTTP {resp.status_code} 但没带 {K_CLIP_ID}："
                         f"{json.dumps(data, ensure_ascii=False)[:200]}"}
    # raw 是服务化之前就有的键（本地 CLI 版回 CLI 原始 JSON）——server 侧回服务端回执原文，
    # 保证「旧键一个不少」，按旧契约读 r["raw"] 的下游不会 KeyError。
    return {"success": True, "submit_id": str(cid), "operation": operation,
            "backend": "server", "client_ref": payload["client_ref"], "raw": data}


# ---- server：取片 -------------------------------------------------------------

def _download(url: str, dst: Path, *, timeout: int = 300) -> None:
    """流式下载到 `.part` 再原子改名；失败清理半截文件（产物是免鉴权直链，不带 Authorization）。"""
    requests = _requests()
    tmp = dst.with_name(dst.name + ".part")
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
        os.replace(tmp, dst)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _server_fetch(clip_id: str, out_dir: str, *, api_base: Optional[str] = None,
                  max_wait: int = 1800, interval: int = 15) -> dict:
    """轮询 GET /api/video-clips/{clip_id} 到 done 并下载 MP4；超时保留 submit_id 让上层稍后再取。
    **任何分支都不会重新提交**——重提是烧钱，只能由运营决策。"""
    key, base, kerr = _server_key_or_error(api_base)
    if kerr:
        return kerr
    try:
        _requests()   # 取片全程要它，先给人话错误而不是让轮询把 ImportError 当网络抖动
    except ImportError as e:
        return {"success": False, "submit_id": clip_id, "backend": "server",
                "error": f"server 模式需要 requests（pip install requests）：{e}"}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    url = base + EP_CLIP_STATUS.format(clip_id=clip_id)
    deadline = time.time() + max_wait
    last_status = "unknown"
    transient = 0
    while True:
        queued = None
        try:
            resp = _server_request("GET", url, key, timeout=60)
        except Exception as e:  # noqa: BLE001 — 网络抖动算瞬时，绝不当终态
            transient += 1
            if transient > MAX_TRANSIENT:
                return _fetch_stalled(clip_id, last_status, f"连续查询失败：{str(e)[:150]}")
            _err(f"[fetch] {clip_id} 查询瞬时失败（{transient}/{MAX_TRANSIENT}）：{str(e)[:120]}")
            time.sleep(interval)
            continue
        if resp.status_code >= 500:
            transient += 1
            if transient > MAX_TRANSIENT:
                return _fetch_stalled(clip_id, last_status, _api_error(resp))
            _err(f"[fetch] {clip_id} 服务端瞬时故障（{transient}/{MAX_TRANSIENT}）：{_api_error(resp)}")
            time.sleep(interval)
            continue
        if resp.status_code >= 400:   # 401/403/404 是永久错误，立即返回
            return {"success": False, "submit_id": clip_id, "status": last_status,
                    "error": _api_error(resp), "backend": "server"}
        data = _resp_json(resp)
        if not isinstance(data, dict):
            # 200 但正文不是 JSON（坏代理/网关欢迎页）：这是**查询接口异常**，不是「在排队」。
            # 不计瞬时失败的话，它长得跟正常排队一模一样，会把人空转满 max_wait（默认 30 分钟）。
            transient += 1
            body = _resp_text(resp)[:100]
            if transient > MAX_TRANSIENT:
                return _fetch_stalled(clip_id, last_status, f"连续拿到非 JSON 响应：{body}")
            _err(f"[fetch] {clip_id} 响应不是 JSON（{transient}/{MAX_TRANSIENT}）：{body}")
            time.sleep(interval)
            continue
        transient = 0
        last_status = data.get(K_STATUS, last_status)
        queued = data.get(K_QUEUED_SECONDS)
        if last_status == SRV_DONE:
            return _download_done(clip_id, data, out_dir, base)
        if last_status == SRV_ERROR:
            return {"success": False, "submit_id": clip_id, "status": last_status,
                    "error": _with_compliance(data.get("error") or "任务 error"),
                    "backend": "server"}
        if time.time() >= deadline:
            return {"success": False, "submit_id": clip_id, "status": last_status,
                    "timed_out": True, "backend": "server",
                    "error": f"等待 {max_wait}s 仍未完成（即梦排队常达数小时）。submit_id 已保留，"
                             f"稍后用 fetch --submit-id {clip_id} 取回，无需重新生成、不重复扣分。"}
        _err(f"[fetch] {clip_id} 状态={last_status}"
             + (f" 排队 {queued}s" if queued is not None else "")
             + f"，{interval}s 后重试…")
        time.sleep(interval)


def _fetch_stalled(clip_id: str, last_status: str, why: str) -> dict:
    """查询侧连续失败（异常）——与「在排队（正常）」区分开，但同样**保住 submit_id**。"""
    return {"success": False, "submit_id": clip_id, "status": last_status, "backend": "server",
            "error": f"{why}。submit_id 已保留，稍后用 fetch --submit-id {clip_id} 取回，"
                     "无需重新生成、不重复扣分。"}


def _download_done(clip_id: str, data: dict, out_dir: str, base: str) -> dict:
    """done 分支：拉直链落盘，返回与本地 CLI success 分支同形的信封。"""
    raw = data.get(K_VIDEO_URL)
    credit = data.get(K_CREDIT_COUNT)
    if not isinstance(raw, str) or not raw:
        return {"success": False, "submit_id": clip_id, "status": "success", "videos": [],
                "credit_count": credit, "backend": "server",
                "error": f"done 但没带 {K_VIDEO_URL}，无法取片"}
    url = _abs_url(raw, base)
    # clip_id 是入口边界数据（server 返回值 / 运营手敲的 --submit-id），拼文件名前先消毒：
    # 含 ../ 或 / 的病态 id 会路径逃逸、Windows 非法字符会落盘失败。信封里的 submit_id 保持原值。
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", clip_id)
    dst = Path(out_dir) / f"{safe_id}_video_0.mp4"
    try:
        _download(url, dst)
    except Exception as e:  # noqa: BLE001 — 片子已生成，下载失败不该让人重提
        return {"success": False, "submit_id": clip_id, "status": "success", "videos": [],
                "credit_count": credit, "backend": "server", "video_url": url,
                "error": f"视频已生成但下载失败（{str(e)[:150]}）；直链仍可用，"
                         f"稍后重跑 fetch --submit-id {clip_id} 即可，不重复扣分"}
    return {"success": True, "submit_id": clip_id, "status": "success", "videos": [str(dst)],
            "credit_count": credit,
            # meta 是服务化之前就有的键（本地 CLI 版回 result_json.videos[]）——server 单镜只出一条片，
            # 按同形状（逐片 dict 列表）给一条，旧契约读 r["meta"] 的下游照样能跑。
            "meta": [{"path": str(dst), "video_url": url}],
            "error": None, "backend": "server",
            "video_url": url, "expires_at": data.get(K_EXPIRES_AT)}


def _server_owns_clip(clip_id: str, api_base: Optional[str] = None) -> bool:
    """server 上到底有没有这个 id —— 一次 GET，**免费、不提交、不扣分**。

    只在 server 明确认领（HTTP <400）时回 True；404 / 没凭据 / 没装 requests / 网络或鉴权异常
    一律回 False，交给调用方按 id 形态兜底。
    """
    key, base = _api_ctx(api_base)
    if not key:
        return False
    try:
        resp = _server_request("GET", base + EP_CLIP_STATUS.format(clip_id=clip_id), key,
                               timeout=PROBE_TIMEOUT)
    except Exception:  # noqa: BLE001 — 判定不了就退回形态兜底，绝不因此中断取片
        return False
    return resp.status_code < 400


# ---- server：积分 -------------------------------------------------------------

def _server_credits(api_base: Optional[str] = None) -> dict:
    key, base, kerr = _server_key_or_error(api_base)
    if kerr:
        return kerr
    try:
        resp = _server_request("GET", base + EP_CREDITS, key, timeout=30)
    except ImportError as e:
        return {"success": False, "backend": "server",
                "error": f"server 模式需要 requests（pip install requests）：{e}"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "backend": "server",
                "error": f"查询 {base}{EP_CREDITS} 失败：{str(e)[:200]}"}
    if resp.status_code >= 400:
        return {"success": False, "error": _api_error(resp), "backend": "server"}
    data = _resp_json(resp)
    if not isinstance(data, dict):
        return {"success": False, "backend": "server",
                "error": f"{EP_CREDITS} 返回的不是 JSON：{_resp_text(resp)}"}
    credit = data.get(K_CREDIT)
    return {"success": True, "credit": credit,
            "low_threshold_hit": bool(data.get(K_LOW_THRESHOLD)),
            # 镜像键：本地 CLI 的 user_credit 回的是 total_credit，兼容读它的老调用（check_env 等）
            "total_credit": credit,
            "backend": "server"}


# ---- 本地 CLI 能力（行为与服务化之前逐字一致）---------------------------------

def _local_credits() -> dict:
    """查询当前登录会员的积分余额。"""
    err = _check_cli()
    if err:
        return {"success": False, "error": err}
    rc, out, serr = _run(["user_credit"], timeout=60)
    data = _parse_json(out)
    if rc != 0 or not isinstance(data, dict):
        return {"success": False, "error": (serr or out or "user_credit 失败").strip(),
                "hint": "未登录请让 agent 跑 scripts/dreamina_login.py（自动弹浏览器，抖音 App 扫码）"}
    data["success"] = True
    return data


def _build_gen_args(operation: str, prompt: str, *, model: str, duration: int,
                    ratio: Optional[str], images: list[str], videos: list[str],
                    audios: list[str], poll: int) -> tuple[Optional[list[str]], Optional[str]]:
    """组装生成子命令参数；返回 (args, error)。"""
    videos, audios = videos or [], audios or []
    berr = _validate_basics(model, duration, ratio)
    if berr:
        return None, berr

    common = [
        f"--prompt={prompt}",
        f"--duration={duration}",
        f"--model_version={model}",
        f"--video_resolution=720p",   # 必填且逐档校验；720p 是唯一对全家族都合法的一档
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


_SERVER_ONLY_OPS = ("frames2video", "multiframe2video")   # 本地 CLI 封装未实现，走 server


def _local_submit(operation: str, prompt: str, *, model: str = DEFAULT_MODEL, duration: int = 5,
                  ratio: Optional[str] = "9:16", images: Optional[list[str]] = None,
                  videos: Optional[list[str]] = None, audios: Optional[list[str]] = None,
                  poll: int = 0) -> dict:
    """提交一个生成任务，返回 {success, submit_id, ...}。poll=0 即纯提交不等待。"""
    if operation in _SERVER_ONLY_OPS:
        return {"success": False, "backend": "local",
                "error": f"{operation} 的本机 CLI 封装未实现，请走 server 后端"
                         "（--backend server；server 已于 2026-08-06 上线该能力）"}
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


def _local_fetch(submit_id: str, out_dir: str, *, max_wait: int = 1800, interval: int = 15) -> dict:
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


# ---- 公开能力（按后端分派）---------------------------------------------------

def _tag(result: dict, backend: str) -> dict:
    result["backend"] = backend
    return result


def credits(*, backend: Optional[str] = None, api_base: Optional[str] = None) -> dict:
    """查积分余额。server 走 /api/video-credits（公司号集中可观测），local 走 dreamina user_credit。"""
    try:
        b = resolve_backend(backend, api_base)
    except BackendError as e:
        return {"success": False, "error": str(e)}
    if b == "server":
        return _server_credits(api_base)
    return _tag(_local_credits(), "local")


def submit(operation: str, prompt: str, *, backend: Optional[str] = None,
           api_base: Optional[str] = None, model: str = DEFAULT_MODEL, duration: int = 5,
           ratio: Optional[str] = "9:16", images: Optional[list[str]] = None,
           videos: Optional[list[str]] = None, audios: Optional[list[str]] = None,
           transition_prompts: Optional[list[str]] = None,
           transition_durations: Optional[list[float]] = None,
           poll: int = 0) -> dict:
    """提交一个生成任务，返回 {success, submit_id, ...}。poll=0 即纯提交不等待（server 恒异步）。"""
    try:
        b = resolve_backend(backend, api_base)
    except BackendError as e:
        return {"success": False, "error": str(e)}
    images, videos, audios = images or [], videos or [], audios or []
    if b == "server":
        # 本机参考图先传图床换直链（没凭据/上传失败才回落）；回落用的仍是原始本机路径
        key, base, _ = _server_key_or_error(api_base)
        srv_images, capable, why = _prepare_server_shot(operation, images, videos, audios,
                                                        key, base)
        if capable:
            return _server_submit(operation, prompt, api_base=api_base, model=model,
                                  duration=duration, ratio=ratio, images=srv_images,
                                  videos=videos, audios=audios,
                                  transition_prompts=transition_prompts,
                                  transition_durations=transition_durations)
        _err(f"[backend] 本镜回落本机 dreamina CLI：{why}")
    return _tag(_local_submit(operation, prompt, model=model, duration=duration, ratio=ratio,
                              images=images, videos=videos, audios=audios, poll=poll), "local")


def fetch(submit_id: str, out_dir: str, *, max_wait: int = 1800, interval: int = 15,
          backend: Optional[str] = None, api_base: Optional[str] = None) -> dict:
    """取回已提交任务并下载 MP4。

    auto 时**先问 server「这个 id 在不在」**（一次 GET，免费不扣分）：认领了就走 server；没认领
    才按 id 形态兜底（本机 CLI 的 submit_id 是 16 位 hex → local，其余 → server，让 server 给人话 404）。
    契约只写了 `202 {clip_id}`、**没约定 clip_id 形态**，若服务端用 token_hex(8)/uuid4().hex[:16]
    生成，只按形态分派就会把 server 的 clip_id 派给本机 CLI 去查一个不存在的任务——空转到 max_wait
    （默认 30 分钟）后运营多半判定任务丢了去重跑 gen，那是双倍扣分。存量 submit_ids.json 里的老任务
    照旧：server 不认领 → 形态命中 → 本机取回。
    """
    choice = _backend_choice(backend)
    auto = choice == "auto"
    if auto:
        sid = str(submit_id).strip()
        if _server_owns_clip(sid, api_base):
            choice = "server"
        else:
            choice = "local" if _SUBMIT_ID_RE.fullmatch(sid) else "server"
        _err(f"[backend] fetch {submit_id} → {choice}")
    if choice == "server":
        return _server_fetch(str(submit_id), out_dir, api_base=api_base,
                             max_wait=max_wait, interval=interval)
    r = _tag(_local_fetch(submit_id, out_dir, max_wait=max_wait, interval=interval), "local")
    if auto and not r.get("success"):
        # 自动派到本机却没取到：可能这 id 本就是 server 侧 clip_id（探测那步没凭据/网络不通）
        r["error"] = (f"{r.get('error') or '取片失败'}"
                      "（若该 id 是 server 侧 clip_id，加 --backend server 再试一次）")
    return r


def generate(operation: str, prompt: str, *, out_dir: str, submit_only: bool = False,
             max_wait: int = 1800, interval: int = 15, backend: Optional[str] = None,
             api_base: Optional[str] = None, **kw) -> dict:
    """提交 + （除非 submit_only）轮询下载，一步到位。"""
    try:
        b = resolve_backend(backend, api_base)
    except BackendError as e:
        return {"success": False, "error": str(e)}
    s = submit(operation, prompt, backend=b, api_base=api_base, poll=0, **kw)
    if not s.get("success"):
        return s
    sid = s["submit_id"]
    _err(f"[generate] 已提交 submit_id={sid}")
    if submit_only:
        return {"success": True, "submit_id": sid, "status": "submitted",
                "note": "仅提交。稍后 fetch --submit-id 取回。", "backend": s.get("backend", b)}
    # 提交走了哪个后端，就用哪个后端取回（回落镜不能拿本机 id 去问 server）
    return fetch(sid, out_dir, max_wait=max_wait, interval=interval,
                 backend=s.get("backend", b), api_base=api_base)


def _shot_media(shot: dict) -> tuple[list, list, list]:
    """分镜里的媒体三件套（兼容 image 单数键与 images 复数键）。"""
    images = shot.get("images") or ([shot["image"]] if shot.get("image") else [])
    return images, shot.get("videos") or [], shot.get("audios") or []


def _local_shot(i: int, shot: dict, out_dir: str, *, submit_only: bool,
                max_wait: int, interval: int) -> dict:
    """跑一镜本地 CLI（批量的本地路径 / server 批里回落镜共用）。"""
    images, videos, audios = _shot_media(shot)
    r = generate(
        shot.get("operation", "text2video"), shot.get("prompt", ""),
        out_dir=out_dir, submit_only=submit_only, max_wait=max_wait, interval=interval,
        backend="local",
        model=shot.get("model", DEFAULT_MODEL),
        duration=int(shot.get("duration", 5)),
        ratio=shot.get("ratio", "9:16"),
        images=images, videos=videos, audios=audios,
    )
    r["index"] = i
    return r


def _server_batch(plan: list, out_dir: str, *, api_base: Optional[str], submit_only: bool,
                  max_wait: int, interval: int, max_credits: Optional[int] = None) -> list:
    """server 批量：能交 server 的镜**一次 POST 全灌进队列**（不串行等待），媒体在本机的镜整镜
    回落本地 CLI。逐镜独立、一镜失败不连坐；结果按传入顺序（index）映射，与本地路径语义一致。"""
    results: list[Optional[dict]] = [None] * len(plan)
    key, base, kerr = _server_key_or_error(api_base)
    srv_idx, payloads = [], []
    for i, shot in enumerate(plan):
        images, videos, audios = _shot_media(shot)
        # 上传发生在组 payload 之前：整批的 payload（含 client_ref 与已换好的图床 url）组好后
        # 才 POST，网络异常重发复用同一份 payload —— 不会二次上传，也不会变出新的 ref
        images, capable, why = _prepare_server_shot(shot.get("operation", "text2video"),
                                                    images, videos, audios, key, base)
        if not capable:
            _err(f"[batch] 分镜 {i + 1}/{len(plan)} 回落本机 CLI：{why}")
            continue      # 留到 server 那批灌完队列后再跑，别让本地慢镜挡住排队
        payload, perr = _shot_payload(shot.get("operation", "text2video"), shot.get("prompt", ""),
                                      model=shot.get("model", DEFAULT_MODEL),
                                      duration=int(shot.get("duration", 5)),
                                      ratio=shot.get("ratio", "9:16"), images=images,
                                      videos=shot.get("videos"), audios=shot.get("audios"),
                                      transition_prompts=shot.get("transition_prompts"),
                                      transition_durations=shot.get("transition_durations"))
        if perr:
            results[i] = {"success": False, "error": perr, "index": i, "backend": "server"}
            continue
        srv_idx.append(i)
        payloads.append(payload)

    clip_ids: dict[int, str] = {}
    if srv_idx:
        if kerr:
            for i in srv_idx:
                results[i] = dict(kerr, index=i)
        else:
            _err(f"[batch] 提交 {len(srv_idx)} 镜到 server（一次灌入，逐镜独立）…")
            # 批量逐镜 ref 幂等已经 server 验收（2026-08-05 回执：同 refs 重放回原 clip_ids
            # 零新增零扣分），网络异常复用同一份 payload（同一组 client_ref）重发一次是安全的
            body = {K_SHOTS: payloads}
            if max_credits is not None:
                # 预算护栏（server 2026-08-06 上线）：整批预估超限 → 409 整批拒绝、零任务零扣分。
                # 花钱的决定必须显式——调用方带上老板核准的数，而不是靠余额撞墙。
                body["max_credits"] = int(max_credits)
            resp, neterr = _post_idempotent(base + EP_BATCH_SUBMIT, key, body)
            berr = neterr
            data = None
            if not berr and resp.status_code >= 400:
                berr = _api_error(resp)
            elif not berr:
                data = _resp_json(resp)
                if not isinstance(data, dict):
                    berr = f"批量提交返回的不是 JSON（HTTP {resp.status_code}）：{_resp_text(resp)}"
            # 顶层非 dict（裸数组/字符串）时 .get 会裸抛 AttributeError，把整个 batch 崩成
            # traceback、stdout 一行 JSON 都没有 —— 破坏本模块「stdout 恒 JSON 信封」的自述契约
            ids = data.get(K_CLIP_IDS) if isinstance(data, dict) else None
            if not berr and (not isinstance(ids, list) or len(ids) != len(srv_idx)):
                berr = (f"批量提交回执 {K_CLIP_IDS} 不可用（期望 {len(srv_idx)} 个，"
                        f"收到 {ids!r}），无法映射分镜")
            if berr:
                for i in srv_idx:
                    results[i] = {"success": False, "error": berr, "index": i, "backend": "server"}
            else:
                batch_id = (data or {}).get(K_BATCH_ID)
                for n, i in enumerate(srv_idx):
                    cid = str(ids[n])
                    clip_ids[i] = cid
                    results[i] = {"success": True, "submit_id": cid, "status": "submitted",
                                  "note": "仅提交。稍后 fetch --submit-id 取回。",
                                  "index": i, "backend": "server", "batch_id": batch_id}

    # 媒体在本机的镜：整镜走本地 CLI（与现版 batch 行为一致），不影响其余镜
    for i, shot in enumerate(plan):
        if results[i] is None:
            _err(f"\n=== 分镜 {i + 1}/{len(plan)}（本机 CLI） ===")
            results[i] = _local_shot(i, shot, out_dir, submit_only=submit_only,
                                     max_wait=max_wait, interval=interval)

    if not submit_only:
        for i, cid in clip_ids.items():
            _err(f"\n=== 取片 {i + 1}/{len(plan)} clip={cid} ===")
            r = _server_fetch(cid, out_dir, api_base=api_base, max_wait=max_wait, interval=interval)
            r["index"] = i
            results[i] = r
    return results


def batch(plan_path: str, out_dir: str, *, submit_only: bool = False,
          max_wait: int = 1800, interval: int = 15, backend: Optional[str] = None,
          api_base: Optional[str] = None, max_credits: Optional[int] = None) -> dict:
    """批量执行分镜计划。plan = [{operation, prompt, duration, ratio, model, images?, ...}, ...]"""
    try:
        plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except Exception as e:
        return {"success": False, "error": f"读取 plan 失败：{e}"}
    seg_index: list[int] = []   # v3 专用：results 下标 → segment 序号
    if isinstance(plan, dict) and plan.get("segments"):
        # v3 电影格式：一段 = 一次生成（≤30s），时间轴提示词让**模型在段内自己切镜**。
        # 不在这里把镜头拆开逐条提交——那样镜间的人物/光线一致性要靠运气，
        # 同一次生成里则是天然一致的（这是即梦这条产线最关键的用法差异）。
        flat = []
        for seg in plan["segments"]:
            shot = dict(seg)
            shot["duration"] = int(seg.get("gen") or 30)
            shot.setdefault("operation", "image2video" if seg.get("image") else "text2video")
            flat.append(shot)
            seg_index.append(int(seg["index"]))
        plan = flat
    elif isinstance(plan, dict) and "shots" in plan:
        plan = plan["shots"]
    if not isinstance(plan, list) or not plan:
        return {"success": False, "error": "plan 应为分镜数组（或 {shots:[...]} / {beats:[...]}）"}
    try:
        b = resolve_backend(backend, api_base)
    except BackendError as e:
        return {"success": False, "error": str(e)}

    if b == "server":
        results = _server_batch(plan, out_dir, api_base=api_base, submit_only=submit_only,
                                max_wait=max_wait, interval=interval, max_credits=max_credits)
    else:
        results = []
        for i, shot in enumerate(plan):
            _err(f"\n=== 分镜 {i + 1}/{len(plan)} ===")
            results.append(_local_shot(i, shot, out_dir, submit_only=submit_only,
                                       max_wait=max_wait, interval=interval))
    if seg_index:
        # 回填段号：取片后按 segment-NN.mp4 改名，cut_assemble 再按旁白边界切开
        for r, si in zip(results, seg_index):
            r["segment"] = si
            r["target_name"] = f"segment-{si:02d}.mp4"
    ok = sum(1 for r in results if r.get("success"))
    return {"success": ok == len(results), "total": len(results), "ok": ok,
            "results": results, "backend": b}


# ---- CLI --------------------------------------------------------------------

def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(0 if obj.get("success", True) else 1)


def _add_backend_flags(sp) -> None:
    """两个后端的公共开关。default=None 才能区分「用户显式写了 auto」与「没写」——
    显式 --backend 要压过环境变量 NBDPSY_JIMENG_BACKEND。"""
    sp.add_argument("--backend", choices=list(BACKEND_CHOICES), default=None,
                    help=f"server(nbdpsy-server REST) / local(本机 dreamina CLI) / "
                         f"auto(默认，自动探测；环境变量 {BACKEND_ENV} 可改默认)")
    sp.add_argument("--api-base", default=None,
                    help="server 基址（默认 NBDPSY_VIDEO_API_BASE 或 https://mcp.nbdpsy.com）")


def main() -> None:
    p = argparse.ArgumentParser(description="即梦 Seedance 2.0 视频生成引擎（server REST / 本机 CLI 双后端）")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("credits", help="查会员积分余额")
    _add_backend_flags(c)

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
        _add_backend_flags(sp)

    g = sub.add_parser("gen", help="生成一条（提交+等待+下载）")
    add_gen_flags(g)

    s = sub.add_parser("submit", help="只提交，拿 submit_id")
    add_gen_flags(s)

    f = sub.add_parser("fetch", help="取回已提交任务并下载")
    f.add_argument("--submit-id", required=True)
    f.add_argument("--out-dir", default="./clips")
    f.add_argument("--max-wait", type=int, default=1800)
    f.add_argument("--interval", type=int, default=15)
    _add_backend_flags(f)

    b = sub.add_parser("batch", help="批量执行分镜计划 JSON")
    b.add_argument("--plan", required=True)
    b.add_argument("--out-dir", default="./clips")
    b.add_argument("--submit-only", action="store_true")
    b.add_argument("--max-wait", type=int, default=1800)
    b.add_argument("--interval", type=int, default=15)
    b.add_argument("--max-credits", type=int, default=None,
                   help="预算护栏：整批预估积分超过它就整批 409 拒绝（零任务零扣分）。"
                        "批量提交前先与老板核准预算，不传=不设限")
    _add_backend_flags(b)

    a = p.parse_args()
    if a.cmd == "credits":
        _emit(credits(backend=a.backend, api_base=a.api_base))
    elif a.cmd in ("gen", "submit"):
        _emit(generate(
            a.operation, a.prompt, out_dir=a.out_dir, submit_only=(a.cmd == "submit"),
            max_wait=a.max_wait, interval=a.interval, backend=a.backend, api_base=a.api_base,
            model=a.model, duration=a.duration,
            ratio=a.ratio, images=a.image, videos=a.video, audios=a.audio))
    elif a.cmd == "fetch":
        _emit(fetch(a.submit_id, a.out_dir, max_wait=a.max_wait, interval=a.interval,
                    backend=a.backend, api_base=a.api_base))
    elif a.cmd == "batch":
        _emit(batch(a.plan, a.out_dir, submit_only=a.submit_only,
                    max_wait=a.max_wait, interval=a.interval,
                    backend=a.backend, api_base=a.api_base, max_credits=a.max_credits))


if __name__ == "__main__":
    main()

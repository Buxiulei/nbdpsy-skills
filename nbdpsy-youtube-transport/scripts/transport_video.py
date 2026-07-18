#!/usr/bin/env python3
"""把 YouTube 视频搬运成带中文字幕/配音的成片（经小红书运营工具的 video-transport REST API）。

服务端全自动：下载 → 转写 → qwen-mt 翻译 → 豆包配音 → 音画同步 → 烧字幕 → 出成片；
成片自动带 NBDpsy 品牌 logo（右下角）+ 片头版权声明，调用方无需传任何额外参数。
本脚本只负责建任务、轮询、取产物公网链接（可选下载到本地工作区）。

用法：
    python3 transport_video.py --url https://www.youtube.com/watch?v=xxx
        [--voice 音色] [--no-burn-subtitles] [--max-resolution 1080]
        [--api-base URL] [--no-wait] [--wait-timeout 1800] [--download] [--out-dir DIR]
    python3 transport_video.py --job 42        # 只查该搬运任务状态/产物
    python3 transport_video.py --list          # 列出我的搬运任务
    python3 transport_video.py --retry 42      # 重试失败任务（重跑并轮询）
    python3 transport_video.py --delete 42     # 删除任务

凭据：复用 NBDPSY_XHS_API_KEY（与小红书自动发布同一把运营接入 JWT，无需另发）；
NBDPSY_VIDEO_API_BASE（可选，默认 https://xhs.nbdpsy.com），均由 nbdpsy_common 三层解析。

约束：只放行 youtube.com / youtu.be 链接（本脚本先做客户端预检，服务端也会拒绝其它域名）。

输出契约：stdout 纯 JSON。
{"outcome": "completed|running|pending|failed|unknown", "job_id",
 "products": {video_url, transcript_zh_srt_url, transcript_en_srt_url, transcript_bilingual_url}
             （相对 /uploads/… 已拼成公网绝对 URL，免鉴权可直接下载/播放），
 "downloaded": {…本地路径…}（仅 --download 时），"error", "hint"}。
failed exit 1，completed/中间态/unknown exit 0。
unknown = 任务已入队但状态未确认（网络抖动等）——带真实 job_id 与复查提示，**绝不据此重建任务**；
--no-wait 或轮询超时后仍在跑同理，稍后用 --job 复查。搬运耗时按视频时长几分钟级，默认轮询到终态。
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

# 同目录 vendored 副本
import nbdpsy_common

TERMINAL_STATUSES = {"completed", "failed"}
# 服务端产物键（值为相对 /uploads/… 路径）
PRODUCT_KEYS = ("video_url", "transcript_zh_srt_url", "transcript_en_srt_url",
                "transcript_bilingual_url")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com",
                  "music.youtube.com", "youtu.be"}


def is_youtube_url(url: str) -> bool:
    """只认 youtube.com / youtu.be（含常见子域）。服务端也会拒绝，这里提前给清晰报错。"""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower()
    return host in _YOUTUBE_HOSTS


def send_request(method: str, url: str, key: str, payload=None, timeout=60):
    """带 Bearer 鉴权调 video-transport API。网络异常向上抛，由调用方统一转 failed/unknown。"""
    import requests
    headers = {"Authorization": f"Bearer {key}"}
    return requests.request(method, url, json=payload, headers=headers, timeout=timeout)


def api_error(resp) -> str:
    """错误体两套形状：401/422 键是 detail，403/404/400/500 键是 error（与发布接口同契约）。"""
    try:
        data = resp.json()
        msg = data.get("error") or data.get("detail") or resp.text[:200]
    except Exception:
        msg = resp.text[:200]
    return f"HTTP {resp.status_code}: {msg}"


def sandbox_hint(exc) -> str:
    """网络被拦时给 agent 可执行的下一步（Claude 沙盒拦网是已知场景）。"""
    s = str(exc)
    if any(k in s for k in ("Host not allowed", "ProxyError", "Connection refused",
                            "ConnectionError", "timed out", "Max retries")):
        return ("网络请求失败。若在 Claude Code 沙盒内被拦（典型报错 Host not allowed），"
                "先跑 `python3 scripts/nbdpsy_common.py sandbox allow` 写入放行名单并重启 "
                "Claude Code；单次命令也可用 Bash 工具参数 dangerouslyDisableSandbox 重试。"
                f"原始错误：{s[:200]}")
    return s[:300]


def resolve_products(products, api_base: str) -> dict:
    """把产物里的相对 /uploads/… 路径拼成公网绝对 URL（免鉴权可直接下载/播放）。
    已是 http(s) 的原样保留；非字符串或空值跳过。"""
    if not isinstance(products, dict):
        return {}
    out = {}
    for k, v in products.items():
        if isinstance(v, str) and v:
            out[k] = v if v.startswith(("http://", "https://")) else api_base + "/" + v.lstrip("/")
        else:
            out[k] = v
    return out


def job_brief(view: dict, api_base: str) -> dict:
    return {"outcome": view.get("status"), "job_id": view.get("job_id") or view.get("id"),
            "products": resolve_products(view.get("products") or {}, api_base),
            "error": view.get("error")}


def poll_job(api_base: str, key: str, job_id: int, timeout: float,
             interval: float = 15.0, max_transient: int = 3):
    """轮询到终态或超时；瞬时故障（网络异常/5xx）连续容忍 max_transient 次——
    一次抖动绝不能把仍在服务端跑的任务判成终态。401/403/404 是永久错误立即抛。
    超时返回最后一次视图（不算失败，可 --job 复查）。"""
    deadline = time.monotonic() + timeout
    transient = 0
    while True:
        try:
            resp = send_request("GET", f"{api_base}/api/video-transport/jobs/{job_id}", key)
        except Exception as e:  # 网络抖动 → 瞬时
            transient += 1
            if transient > max_transient:
                raise
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {e}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code >= 500:  # 服务端瞬时故障
            transient += 1
            if transient > max_transient:
                raise ValueError(api_error(resp))
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {api_error(resp)}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code >= 400:  # 401/403/404 永久错误
            raise ValueError(api_error(resp))
        transient = 0
        view = resp.json()
        status = view.get("status")
        print(f"  job {job_id}: {status}", file=sys.stderr)
        if status in TERMINAL_STATUSES or time.monotonic() >= deadline:
            return view
        time.sleep(interval)


def create_job(api_base: str, key: str, url: str, voice, burn_subtitles: bool,
               max_resolution: int) -> int:
    payload = {"url": url, "burn_subtitles": burn_subtitles, "max_resolution": max_resolution}
    if voice:
        payload["voice"] = voice
    resp = send_request("POST", f"{api_base}/api/video-transport/jobs", key, payload, timeout=60)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    data = resp.json()
    return data.get("job_id") or data.get("id")


def list_jobs(api_base: str, key: str) -> list:
    resp = send_request("GET", f"{api_base}/api/video-transport/jobs", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    data = resp.json()
    return data.get("jobs", data) if isinstance(data, dict) else data


def retry_job(api_base: str, key: str, job_id: int) -> dict:
    resp = send_request("POST", f"{api_base}/api/video-transport/jobs/{job_id}/retry", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json() if resp.text.strip() else {"job_id": job_id, "status": "pending"}


def delete_job(api_base: str, key: str, job_id: int) -> dict:
    resp = send_request("DELETE", f"{api_base}/api/video-transport/jobs/{job_id}", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return {"deleted": True, "job_id": job_id}


def download_products(products_abs: dict, out_dir: Path) -> dict:
    """产物是公网免鉴权链接，逐个下载到 out_dir。返回 {键: 本地路径}；单个失败不影响其它。"""
    import requests
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = {}
    for k, url in products_abs.items():
        if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
            continue
        name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or k
        dst = out_dir / name
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(dst, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            f.write(chunk)
            saved[k] = str(dst)
        except Exception as e:  # noqa: BLE001 — 下载失败仅记录，产物 URL 仍可用
            print(f"  ⚠ 下载 {k} 失败（公网链接仍可用）：{e}", file=sys.stderr)
    return saved


def main():
    ap = argparse.ArgumentParser(description="把 YouTube 视频搬运成带中文字幕/配音的成片（异步）")
    ap.add_argument("--url", help="YouTube 视频链接（youtube.com / youtu.be）")
    ap.add_argument("--voice", help="服务端配音音色（不传 = 默认牧羊音色）")
    ap.add_argument("--no-burn-subtitles", action="store_true",
                    help="不把字幕烧进画面（默认烧录中文字幕）")
    ap.add_argument("--max-resolution", type=int, default=1080,
                    help="成片最高分辨率（默认 1080）")
    ap.add_argument("--api-base", help="API base（默认 NBDPSY_VIDEO_API_BASE 或 https://xhs.nbdpsy.com）")
    ap.add_argument("--no-wait", action="store_true", help="提交后不等结果（稍后 --job 查询）")
    ap.add_argument("--wait-timeout", type=float, default=1800, help="轮询等待上限秒数（默认 1800）")
    ap.add_argument("--download", action="store_true",
                    help="终态 completed 后把产物下载到本地（默认只回公网链接，视频较大）")
    ap.add_argument("--out-dir", type=Path, help="--download 落盘目录（默认 <工作区>/video-transport/job-N/）")
    ap.add_argument("--job", type=int, help="只查询该搬运任务状态/产物")
    ap.add_argument("--list", action="store_true", help="列出我的搬运任务")
    ap.add_argument("--retry", type=int, metavar="JOB_ID", help="重试失败任务（重跑并轮询）")
    ap.add_argument("--delete", type=int, metavar="JOB_ID", help="删除任务")
    args = ap.parse_args()

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.XHS_API_KEY} 找管理员要「运营接入配置包」，"
              "secret import 导入后重试（与小红书自动发布同一把凭据）", file=sys.stderr)
        sys.exit(1)
    api_base = (args.api_base or nbdpsy_common.video_api_base()).rstrip("/")

    def _download_if_asked(job_id, brief):
        if args.download and brief["outcome"] == "completed" and brief["products"]:
            out_dir = args.out_dir or (nbdpsy_common.resolve_workspace()
                                       / "video-transport" / f"job-{job_id}")
            brief["downloaded"] = download_products(brief["products"], out_dir)
        return brief

    submitted_job_id = None  # 已入队的任务号——之后任何异常都不能丢它，否则会诱发重复建任务
    try:
        if args.list:
            print(json.dumps({"jobs": list_jobs(api_base, key)}, ensure_ascii=False))
            return
        if args.delete is not None:
            print(json.dumps(delete_job(api_base, key, args.delete), ensure_ascii=False))
            return
        if args.job is not None:
            submitted_job_id = args.job
            view = poll_job(api_base, key, args.job, timeout=0)
            brief = _download_if_asked(args.job, job_brief(view, api_base))
            print(json.dumps(brief, ensure_ascii=False))
            sys.exit(1 if brief["outcome"] == "failed" else 0)
        if args.retry is not None:
            submitted_job_id = args.retry
            retry_job(api_base, key, args.retry)
            print(f"  已提交重试 job_id={args.retry}", file=sys.stderr)
            if args.no_wait:
                print(json.dumps({"outcome": "pending", "job_id": args.retry,
                                  "products": {}, "error": None}, ensure_ascii=False))
                return
            view = poll_job(api_base, key, args.retry, timeout=args.wait_timeout)
            brief = _download_if_asked(args.retry, job_brief(view, api_base))
            if brief["outcome"] not in TERMINAL_STATUSES:
                brief["hint"] = f"仍在搬运中，稍后 python3 transport_video.py --job {args.retry} 复查"
            print(json.dumps(brief, ensure_ascii=False))
            sys.exit(1 if brief["outcome"] == "failed" else 0)

        if not args.url:
            ap.error("搬运需要 --url（或改用 --job / --list / --retry / --delete）")
        if not is_youtube_url(args.url):
            raise ValueError(f"仅支持 youtube.com / youtu.be 链接：{args.url}")

        print(f"提交搬运：{args.url} …", file=sys.stderr)
        job_id = create_job(api_base, key, args.url, args.voice,
                            burn_subtitles=not args.no_burn_subtitles,
                            max_resolution=args.max_resolution)
        submitted_job_id = job_id
        print(f"  已入队 job_id={job_id}", file=sys.stderr)

        if args.no_wait:
            print(json.dumps({"outcome": "pending", "job_id": job_id, "products": {},
                              "error": None}, ensure_ascii=False))
            return

        view = poll_job(api_base, key, job_id, timeout=args.wait_timeout)
        brief = _download_if_asked(job_id, job_brief(view, api_base))
        if brief["outcome"] not in TERMINAL_STATUSES:
            brief["hint"] = f"仍在搬运中，稍后 python3 transport_video.py --job {job_id} 复查"
        print(json.dumps(brief, ensure_ascii=False))
        sys.exit(1 if brief["outcome"] == "failed" else 0)

    except Exception as e:
        msg = sandbox_hint(e)
        if submitted_job_id is not None:
            # 任务已在服务端入队/重跑，绝不判 failed——那会让 agent 重复建任务
            print(f"  → 状态未知: {msg}", file=sys.stderr)
            print(json.dumps({
                "outcome": "unknown", "job_id": submitted_job_id, "products": {}, "error": msg,
                "hint": f"任务可能仍在服务端跑，先用 --job {submitted_job_id} 复查，勿直接重建以免重复搬运",
            }, ensure_ascii=False))
            sys.exit(0)
        # 未入队的异常（URL 非法/建任务失败）才是真 failed
        print(f"  → 失败: {msg}", file=sys.stderr)
        print(json.dumps({"outcome": "failed", "job_id": None, "products": {},
                          "error": msg}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""把 nbdpsy-xiaohongshu-creator 产出的图文笔记发布到小红书（经 nbdpsy-api，纯 REST）。

流程：解析 post-NN.md 的 frontmatter + 「## 发布文案」块 → 收集配图（base64 内联）→
POST {base}/api/publish-jobs（异步 202 拿 job_id）→ 轮询 GET /api/publish-jobs/{job_id} 到终态。

用法：
    python3 publish_note.py --note post-01.md --account 账号名或ID
        [--images-dir DIR] [--schedule "2026-07-14T09:00:00+08:00"]
        [--api-base URL] [--no-wait] [--wait-timeout 900] [--dry-run]
    python3 publish_note.py --job 42            # 只查已提交任务的状态
    python3 publish_note.py --list-accounts     # 列出我可操作的小红书账号
    python3 publish_note.py --self-check        # 一键接入自检：连通性+身份+账号+就绪（可反复跑）
    python3 publish_note.py --notes 账号名或ID   # 拉该账号已发布笔记数据（供分析；server 端上线中）
    python3 publish_note.py --extension-info    # chrome 插件下载地址+安装步骤+server_time
    python3 publish_note.py --wait-login --since <server_time> [--account-id N]
                                                # 等运营扫码登录完成（新号不传 account-id）
    python3 publish_note.py --check-cookie 账号名或ID   # 触发 cookie 验活并轮询到结果

凭据：NBDPSY_XHS_API_KEY（必需）、NBDPSY_XHS_API_BASE（可选，默认 https://mcp.nbdpsy.com），
由 nbdpsy_common 三层解析（环境变量 > workspace/.env > 用户级 secrets.env），
来自管理员发的「运营接入配置包」，secret import 导入后即用。

约束（服务端超限会静默截断，这里提前给 warning）：图片 1–18 张；标题≤20 字；
正文≤900 字；话题≤10 个；定时发布 schedule_time 务必带时区偏移（如 +08:00）。

输出契约：stdout 纯 JSON。发布 = {"outcome": "published|publishing|pending|failed|canceled|unknown",
"job_id", "note_url", "error", "warnings"}；failed/canceled exit 1，其余 exit 0。
unknown = 任务已入队但状态未确认（网络抖动等）——带真实 job_id 与复查提示，**绝不据此重发**；
--no-wait 或轮询超时后仍在跑同理，稍后用 --job 复查。正文发布前会剥离 Markdown 强调符（**/*/`）。
接入辅助命令 exit 码：--wait-login done=0/未等到=1；--check-cookie valid=0/其余=1
（error 是基础设施失败≠cookie 失效，别据此让人重新扫码）。
"""
import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

# 同目录 vendored 副本
import nbdpsy_common

TERMINAL_STATUSES = {"published", "failed", "canceled"}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

def _fallback_meta(raw: str) -> dict:
    """笔记 frontmatter 惯用 `hashtags: [#a, #b]`——`#` 在 YAML 流序列里开注释，
    严格解析必炸；这里按行退化解析发布所需的键（title/hashtags 等简单标量）。"""
    meta = {}
    for line in raw.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "hashtags":
            meta[key] = [t for t in re.split(r"[\s,\[\]]+", val) if t.startswith("#")]
        elif key and val:
            meta[key] = val
    return meta


def parse_frontmatter(text: str):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("缺 frontmatter")
    raw = m.group(1)
    try:
        import yaml  # type: ignore
        meta = yaml.safe_load(raw)
        if isinstance(meta, dict):
            return meta, m.group(2)
    except ModuleNotFoundError:
        sys.exit("需要 python3-yaml（pyyaml）")
    except Exception:
        pass  # 含 #标签 流序列等非法 YAML → 走退化解析
    return _fallback_meta(raw), m.group(2)


def extract_publish_text(body: str) -> str:
    """取「## 发布文案」块正文（到下一个 ## 或文末）。"""
    m = re.search(r"^##\s*发布文案[^\n]*\n(.*?)(?=^##\s|\Z)", body, re.S | re.M)
    if not m:
        raise ValueError("笔记缺「## 发布文案」块")
    return m.group(1).strip()


_HASHTAG_LINE = re.compile(r"^\s*(#\S+\s*)+$")

# 小红书正文不渲染 Markdown：发布前剥掉强调符，否则笔记里出现字面 **/*/` 号
_EMPHASIS_PATTERNS = [
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"\1"),
    (re.compile(r"\*(.+?)\*", re.S), r"\1"),
    (re.compile(r"`([^`\n]+)`"), r"\1"),
]

def strip_markdown_emphasis(text: str) -> str:
    for pat, rep in _EMPHASIS_PATTERNS:
        text = pat.sub(rep, text)
    return text

def split_content_topics(publish_text: str, meta: dict):
    """正文末尾的纯 #标签 行拆出来当话题（API 单独收 topics，避免正文重复一遍）。
    话题优先取 frontmatter hashtags，标签行仅作兜底来源。"""
    lines = publish_text.rstrip().splitlines()
    tag_line_topics = []
    while lines and _HASHTAG_LINE.match(lines[-1]):
        tag_line_topics = [t.lstrip("#") for t in lines[-1].split() if t.lstrip("#")] + tag_line_topics
        lines.pop()
    content = strip_markdown_emphasis("\n".join(lines).rstrip())
    hashtags = meta.get("hashtags")
    if isinstance(hashtags, list) and hashtags:
        topics = [str(t).lstrip("#").strip() for t in hashtags if str(t).lstrip("#").strip()]
    else:
        topics = tag_line_topics
    # 去重保序
    seen, uniq = set(), []
    for t in topics:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return content, uniq


def collect_images(note_path: Path, images_dir):
    """默认取笔记同目录 images/<note名>/ 下的图片，按文件名排序（P01→PNN 即页序）。"""
    d = Path(images_dir) if images_dir else note_path.parent / "images" / note_path.stem
    if not d.is_dir():
        raise ValueError(f"配图目录不存在: {d}（先出图，或用 --images-dir 指定）")
    paths = sorted(p for p in d.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not paths:
        raise ValueError(f"配图目录里没有图片: {d}")
    return paths


def b64_items(paths):
    """图片转 API 的 {b64, ext} 形态（服务端无上传端点，图随 JSON 内联）。"""
    items = []
    for p in paths:
        items.append({"b64": base64.b64encode(p.read_bytes()).decode("ascii"),
                      "ext": p.suffix.lstrip(".").lower()})
    return items


def build_warnings(title: str, content: str, topics, image_paths):
    w = []
    if len(title) > 20:
        w.append(f"标题 {len(title)} 字超 20，服务端会静默截断")
    if len(content) > 900:
        w.append(f"正文 {len(content)} 字超 900，服务端会静默截断")
    if len(topics) > 10:
        w.append(f"话题 {len(topics)} 个超 10，服务端会静默截断")
    if not 1 <= len(image_paths) <= 18:
        w.append(f"图片 {len(image_paths)} 张不在 1–18 范围，服务端会拒绝（400）")
    return w


def send_request(method: str, url: str, key: str, payload=None, timeout=60):
    """带 Bearer 鉴权调 nbdpsy-api。网络异常向上抛，由调用方统一转 failed。"""
    import requests
    headers = {"Authorization": f"Bearer {key}"}
    return requests.request(method, url, json=payload, headers=headers, timeout=timeout)


def api_error(resp) -> str:
    """nbdpsy-api 错误体：401/422 键是 detail，403/404/400/500 键是 error。"""
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


def list_accounts(api_base: str, key: str):
    resp = send_request("GET", f"{api_base}/api/accounts", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    accounts = resp.json().get("accounts", [])
    return [{"id": a.get("id"), "name": a.get("name"), "nickname": a.get("nickname"),
             "cookie_status": a.get("cookie_status")} for a in accounts]


def resolve_account(api_base: str, key: str, account: str):
    """--account 支持数字 id 或 名称/昵称 精确匹配；歧义/未命中时列出可选项。"""
    if account.isdigit():
        return int(account), account, None
    accounts = list_accounts(api_base, key)
    hits = [a for a in accounts if account in (a["name"], a["nickname"])]
    if len(hits) == 1:
        a = hits[0]
        warn = None
        if a.get("cookie_status") == "invalid":
            warn = f"账号「{account}」cookie 已失效，发布大概率失败，先用 chrome 插件重新扫码登录"
        return a["id"], a["name"] or account, warn
    avail = "、".join(f'{a["name"]}(id={a["id"]})' for a in accounts) or "（无可用账号）"
    raise ValueError(f"账号「{account}」{'匹配到多个' if hits else '不存在或未授权'}；可用：{avail}")


def extension_info(api_base: str, key: str) -> dict:
    """chrome 插件包信息：download_url（免鉴权可下）/version/install_steps/server_time。
    server_time 是 --wait-login 的 since 起点——必须在运营扫码**之前**取。"""
    resp = send_request("GET", f"{api_base}/api/extension", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def wait_login(api_base: str, key: str, since: str, account_id=None,
               timeout: float = 600, interval: float = 5.0) -> dict:
    """轮询 GET /api/login/poll 等运营扫码完成。登新号不传 account_id（done 时带新号列表），
    重登旧号传 account_id。返回最后一次 poll 响应（done 布尔）。"""
    deadline = time.monotonic() + timeout
    path = f"/api/login/poll?since={quote(since)}"
    if account_id is not None:
        path += f"&account_id={account_id}"
    while True:
        resp = send_request("GET", f"{api_base}{path}", key)
        if resp.status_code >= 400:
            raise ValueError(api_error(resp))
        view = resp.json()
        if view.get("done") or time.monotonic() >= deadline:
            return view
        print("  等待扫码登录…", file=sys.stderr)
        time.sleep(interval)


def check_cookie(api_base: str, key: str, account_id: int,
                 timeout: float = 120, interval: float = 4.0) -> dict:
    """触发 cookie 活性检测（202 拿 check_id）并轮询到结果。
    五态：checking/valid/invalid/captcha/error——error 是基础设施失败≠cookie 失效。"""
    resp = send_request("POST", f"{api_base}/api/accounts/{account_id}/cookie-checks", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    check_id = resp.json()["check_id"]
    deadline = time.monotonic() + timeout
    while True:
        r = send_request("GET", f"{api_base}/api/cookie-checks/{check_id}", key)
        if r.status_code >= 400:
            raise ValueError(api_error(r))
        view = r.json()
        status = view.get("status")
        print(f"  cookie 检测: {status}", file=sys.stderr)
        if status != "checking" or time.monotonic() >= deadline:
            return view
        time.sleep(interval)


def self_check(api_base: str, key: str) -> dict:
    """一键接入自检（REST 侧）：连通性 + 身份 + 被授权账号 + 就绪判定。
    可反复调用——运营任何时候想确认「我配好了吗」都跑这个。凭据是否就绪由 doctor 管（本地侧）。"""
    try:
        who = send_request("GET", f"{api_base}/api/whoami", key)
    except Exception as e:  # 网络/沙盒拦截
        return {"ok": False, "stage": "whoami", "error": sandbox_hint(e),
                "hint": "网络或沙盒拦截：跑 nbdpsy_common.py sandbox allow 后重启 Claude 再试"}
    if who.status_code >= 400:
        return {"ok": False, "stage": "whoami", "error": api_error(who),
                "hint": "401=apikey 无效/已轮换（找管理员重发接入包）；000/超时=网络或沙盒拦截"
                        "（跑 nbdpsy_common.py sandbox allow 后重启 Claude）"}
    identity = who.json()
    try:
        accounts = list_accounts(api_base, key)
    except Exception as e:  # whoami 过了 accounts 却挂，多半瞬时——保持 self-check 信封而非落 publish 失败信封
        return {"ok": False, "stage": "accounts", "error": sandbox_hint(e),
                "identity": {"name": identity.get("name"), "role": identity.get("role")},
                "hint": "身份验证通过但拉账号列表失败，多半是瞬时故障，稍后重跑 --self-check"}
    # cookie_status: valid=可发；unknown=没验过（不算失败，发布前 --check-cookie 一下）；
    # invalid/captcha=需重新扫码；error=检测本身失败≠cookie 失效，稍后复验（不催重扫）
    usable = [a for a in accounts if a.get("cookie_status") in ("valid", "unknown")]
    need_login = [a for a in accounts if a.get("cookie_status") in ("invalid", "captcha")]
    ready = bool(accounts) and bool(usable)
    return {
        "ok": True, "ready": ready,
        "identity": {"name": identity.get("name"), "role": identity.get("role")},
        "account_count": len(accounts),
        "accounts": accounts,
        "need_relogin": [a.get("name") or a.get("id") for a in need_login],
        "verdict": (
            "接入正常，可以开始发布" if ready
            else "已连上但没有被授权任何账号（找管理员在后台『调配账号』补授）" if not accounts
            else "没有可用账号：登录态失效的重新扫码，cookie 检测异常的稍后 --check-cookie 复验"
        ),
    }


def account_notes(api_base: str, key: str, account_id: int) -> dict:
    """拉某账号已发布笔记的清单与互动数据（供 Claude 分析）。
    server 端该端点正在上线中——404 时优雅降级为『还没上线』而非报错。
    假定路径 GET /api/accounts/{id}/notes；server 若最终用别的路径，改这一处即可。"""
    resp = send_request("GET", f"{api_base}/api/accounts/{account_id}/notes", key)
    if resp.status_code == 404:
        return {"available": False,
                "hint": "『笔记数据拉取』接口 server 端还在上线中，等管理员通知后即可用（不是故障）"}
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    data = resp.json() if resp.text.strip() else {}
    return {"available": True, **(data if isinstance(data, dict) else {"notes": data})}


def job_brief(view: dict) -> dict:
    return {"outcome": view.get("status"), "job_id": view.get("job_id"),
            "note_url": view.get("note_url"), "error": view.get("error")}


def poll_job(api_base: str, key: str, job_id: int, timeout: float,
             interval: float = 10.0, max_transient: int = 3):
    """轮询到终态或超时；瞬时故障（网络异常/5xx）连续容忍 max_transient 次——
    一次抖动绝不能把仍在服务端跑的任务判成终态（会诱发重复发布）。
    401/403/404 是永久错误立即抛。超时返回最后一次视图（不算失败，可 --job 复查）。"""
    deadline = time.monotonic() + timeout
    transient = 0
    while True:
        try:
            resp = send_request("GET", f"{api_base}/api/publish-jobs/{job_id}", key)
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


def main():
    ap = argparse.ArgumentParser(description="经 nbdpsy-api 发布小红书图文笔记（异步）")
    ap.add_argument("--note", type=Path, help="笔记文件（post-NN.md，须含「## 发布文案」块）")
    ap.add_argument("--account", help="小红书账号：数字 id 或账号名/昵称")
    ap.add_argument("--images-dir", type=Path, help="配图目录（默认 <笔记同目录>/images/<笔记名>/）")
    ap.add_argument("--schedule", help="定时发布，ISO8601 带时区偏移，如 2026-07-14T09:00:00+08:00")
    ap.add_argument("--api-base", help="API base（默认凭据 NBDPSY_XHS_API_BASE 或 https://mcp.nbdpsy.com）")
    ap.add_argument("--no-wait", action="store_true", help="提交后不等结果（稍后 --job 查询）")
    ap.add_argument("--wait-timeout", type=float, default=900, help="轮询等待上限秒数（默认 900）")
    ap.add_argument("--dry-run", action="store_true", help="只打 payload 摘要，不发请求")
    ap.add_argument("--job", type=int, help="只查询该发布任务状态")
    ap.add_argument("--list-accounts", action="store_true", help="列出可操作账号")
    ap.add_argument("--self-check", action="store_true",
                    help="一键接入自检：连通性+身份+被授权账号+就绪判定（可反复跑）")
    ap.add_argument("--extension-info", action="store_true",
                    help="chrome 插件下载地址+安装步骤+server_time（登录前先取）")
    ap.add_argument("--wait-login", action="store_true",
                    help="等运营扫码登录完成（须配 --since；重登旧号加 --account-id）")
    ap.add_argument("--since", help="--wait-login 用：--extension-info 返回的 server_time")
    ap.add_argument("--account-id", type=int, help="--wait-login 重登旧号时指定账号 id")
    ap.add_argument("--login-timeout", type=float, default=600, help="等登录上限秒数（默认 600）")
    ap.add_argument("--check-cookie", metavar="账号名或ID", help="触发该账号 cookie 验活并轮询到结果")
    ap.add_argument("--notes", metavar="账号名或ID",
                    help="拉该账号已发布笔记的清单与互动数据（供分析；server 端上线中，未上线优雅提示）")
    args = ap.parse_args()

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.XHS_API_KEY} 找管理员要「运营接入配置包」，"
              "secret import 导入后重试", file=sys.stderr)
        sys.exit(1)
    api_base = (args.api_base or nbdpsy_common.xhs_api_base()).rstrip("/")

    submitted_job_id = None  # 已入队的任务号——之后的任何异常都不能丢它，否则会诱发重复发布
    try:
        if args.list_accounts:
            print(json.dumps({"accounts": list_accounts(api_base, key)}, ensure_ascii=False))
            return
        if args.self_check:
            report = self_check(api_base, key)
            if report.get("ok"):
                print(f"✓ 已接入：{report['identity']['name']}，"
                      f"可操作 {report['account_count']} 个账号；{report['verdict']}", file=sys.stderr)
            else:
                print(f"✗ 接入自检未通过（{report.get('stage')}）：{report.get('error')}", file=sys.stderr)
            print(json.dumps(report, ensure_ascii=False))
            sys.exit(0 if report.get("ok") and report.get("ready") else 1)
        if args.extension_info:
            print(json.dumps(extension_info(api_base, key), ensure_ascii=False))
            return
        if args.wait_login:
            if not args.since:
                ap.error("--wait-login 需要 --since <server_time>（先跑 --extension-info 取）")
            view = wait_login(api_base, key, args.since, args.account_id,
                              timeout=args.login_timeout)
            if not view.get("done"):
                view["hint"] = "还没等到登录完成：确认运营已装插件并在无痕窗扫码，然后重跑本命令"
            print(json.dumps(view, ensure_ascii=False))
            sys.exit(0 if view.get("done") else 1)
        if args.check_cookie:
            aid, label, _ = resolve_account(api_base, key, args.check_cookie)
            view = check_cookie(api_base, key, aid)
            view["account"] = {"id": aid, "name": label}
            print(json.dumps(view, ensure_ascii=False))
            # valid=0；invalid/captcha 需人工处理=1；error 是基础设施失败≠失效，也回 1 但别让人重登
            sys.exit(0 if view.get("status") == "valid" else 1)
        if args.notes:
            aid, label, _ = resolve_account(api_base, key, args.notes)
            view = account_notes(api_base, key, aid)
            view["account"] = {"id": aid, "name": label}
            print(json.dumps(view, ensure_ascii=False))
            return  # available=false（未上线）不算失败，exit 0
        if args.job is not None:
            submitted_job_id = args.job
            view = poll_job(api_base, key, args.job, timeout=0)
            print(json.dumps(job_brief(view), ensure_ascii=False))
            sys.exit(1 if view.get("status") in ("failed", "canceled") else 0)

        if not args.note or not args.account:
            ap.error("发布需要 --note 与 --account（或改用 --job / --list-accounts）")

        meta, body = parse_frontmatter(args.note.read_text(encoding="utf-8"))
        title = str(meta.get("title") or "").strip()
        if not title:
            raise ValueError("frontmatter 缺 title")
        content, topics = split_content_topics(extract_publish_text(body), meta)
        image_paths = collect_images(args.note, args.images_dir)
        warnings = build_warnings(title, content, topics, image_paths)
        for w in warnings:
            print(f"⚠ {w}", file=sys.stderr)

        if args.dry_run:
            print(json.dumps({
                "outcome": "dry_run", "title": title, "content_chars": len(content),
                "topics": topics, "images": [str(p) for p in image_paths],
                "account": args.account, "schedule_time": args.schedule,
                "warnings": warnings,
            }, ensure_ascii=False, indent=2))
            return

        account_id, account_label, acc_warn = resolve_account(api_base, key, args.account)
        if acc_warn:
            warnings.append(acc_warn)
            print(f"⚠ {acc_warn}", file=sys.stderr)

        payload = {"account_id": account_id, "title": title, "content": content,
                   "images": b64_items(image_paths), "topics": topics}
        if args.schedule:
            payload["schedule_time"] = args.schedule

        print(f"提交发布：{args.note.name} → 账号 {account_label}（{len(image_paths)} 图）…",
              file=sys.stderr)
        resp = send_request("POST", f"{api_base}/api/publish-jobs", key, payload, timeout=180)
        if resp.status_code >= 400:
            raise ValueError(api_error(resp))
        job_id = resp.json()["job_id"]
        submitted_job_id = job_id
        print(f"  已入队 job_id={job_id}", file=sys.stderr)

        if args.no_wait:
            print(json.dumps({"outcome": "pending", "job_id": job_id, "note_url": None,
                              "error": None, "warnings": warnings}, ensure_ascii=False))
            return

        view = poll_job(api_base, key, job_id, timeout=args.wait_timeout)
        out = job_brief(view)
        out["warnings"] = warnings
        if out["outcome"] not in TERMINAL_STATUSES:
            out["hint"] = f"仍在发布中，稍后 python3 publish_note.py --job {job_id} 复查"
        print(json.dumps(out, ensure_ascii=False))
        sys.exit(1 if out["outcome"] in ("failed", "canceled") else 0)

    except Exception as e:
        msg = sandbox_hint(e)
        if submitted_job_id is not None:
            # 任务已在服务端入队（还会自动重试），绝不判 failed——那会让 agent 重发同一篇
            print(f"  → 状态未知: {msg}", file=sys.stderr)
            print(json.dumps({
                "outcome": "unknown", "job_id": submitted_job_id, "note_url": None, "error": msg,
                "hint": f"任务可能仍在服务端跑（自动重试最长约 40 分钟），"
                        f"先用 --job {submitted_job_id} 复查，勿直接重发以免重复发布",
            }, ensure_ascii=False))
            sys.exit(0)
        # 未入队的异常（解析/账号/建任务失败）才是真 failed
        print(f"  → 失败: {msg}", file=sys.stderr)
        print(json.dumps({"outcome": "failed", "job_id": None, "note_url": None,
                          "error": msg}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()

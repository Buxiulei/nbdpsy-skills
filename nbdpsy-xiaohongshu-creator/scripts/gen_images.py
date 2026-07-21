#!/usr/bin/env python3
"""用后端 gpt-image 锚点法给一篇小红书笔记出「一致性」轮播配图（经运营工具 op API）。

一致性原理：先出 post-01 的 P1 封面过风格闸门（`--cover-only`），运营确认配色/人物/比例/图内
中文无误后，把这张 P1 当**锚点参考图**（`--anchor-url`）喂给之后**所有篇所有页**——每页独立锚定
生成，既不重画 P1 也不整批漂移，整个号调性统一。P1 未确认就批量出 = 风格跑偏后 30~70 张全废。

流程：本地解析 post-NN.md「## 配图轮播」每页提示词（判据同后端 extract_slide_prompts：行首
`### P<数字>` 定位页 + 页区间内第一个完整 ``` 围栏块）→ POST {base}/api/op/consistent-images
（不传 draft_id，后端自动开临时容器；202 拿 job_id + session_id）→ 轮询
GET {base}/api/op/drafts/{session_id}/jobs/{job_id} 到终态 → done 后逐页下载
（result.urls 顺序与提交的 prompts 对齐，相对 /uploads/… 公开免鉴权）。

用法：
    python3 gen_images.py --note post-01.md --cover-only            # 只出 P1 封面（风格闸门第一步）
    python3 gen_images.py --note post-01.md --anchor-url <URL>      # 出该篇全部页（各页锚定同一 anchor）
    python3 gen_images.py --note post-01.md --pages 2-9 --anchor-url <URL>  # 出指定页（批量/失败页重试）
    python3 gen_images.py --note post-01.md --job <id> [--session <id>]     # 复查已入队任务并补下载
        [--images-dir DIR] [--api-base URL] [--no-wait] [--wait-timeout N] [--dry-run]

凭据：复用 NBDPSY_XHS_API_KEY（与小红书发布 / 视频搬运同一把运营接入 JWT，无需另发）；
base 用 NBDPSY_VIDEO_API_BASE（可选，默认 https://xhs.nbdpsy.com，与视频搬运同服务），
均由 nbdpsy_common 三层解析；`--api-base` 可覆盖。缺凭据找管理员要「运营接入配置包」secret import。

输出契约：stdout 纯 JSON。
{"outcome": "done|partial|failed|pending|unknown", "session_id", "job_id",
 "pages": [{"page": "P1", "url": 绝对URL|null, "path": 本地路径|null, "error": null|文案}],
 "anchor_url": <cover-only 时=P1 的绝对URL，方便直接取用；否则=本次所用锚点>,
 "error", "hint", "warnings"}。
exit：done=0；partial/failed=1（hint 教「--pages 只重出失败页 + 带同一 --anchor-url」）；
pending/unknown=0（任务已入队仍在跑，hint 教 --job 复查，**绝不重发**以免重复生成/烧额度）。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common

TERMINAL_STATUSES = {"done", "failed"}
STATE_FILE = ".gen_images_state.json"

# 页标题：行首 ### + 空白 + P<数字>（与后端 extract_slide_prompts / 配图轮播计数契约一致；
# 「## 视频参考图提示词」节用 **P1** 加粗标记，不是 ### PN，天然不会被这里匹配到）。
_PAGE_HEADING = re.compile(r"^###\s+(P\d+)\b")


def _first_fenced_block(block_lines):
    """取一段行里第一个完整 ``` 围栏块内容（strip 首尾空行）。
    开围栏行可带语言标记（```text 等），闭围栏为纯 ```；开而未闭 / 无围栏 → 返回 None。"""
    in_fence = False
    collected = []
    for line in block_lines:
        is_fence = line.strip().startswith("```")
        if is_fence and not in_fence:
            in_fence = True
            continue
        if is_fence and in_fence:
            return "\n".join(collected).strip()
        if in_fence:
            collected.append(line)
    return None


def extract_pages(md_text):
    """逐页提取绘图提示词，判据同后端 extract_slide_prompts。
    与后端唯一差异：无围栏的页 prompt=None（不静默丢弃）——后端会静默跳过缺围栏页导致页序错位，
    这里保留下来交给 validate_complete 拦截并列出缺页。返回 [{"page": "P1", "prompt": str|None}, ...]。"""
    if not md_text or not md_text.strip():
        return []
    lines = md_text.splitlines()
    heads = []
    for idx, line in enumerate(lines):
        m = _PAGE_HEADING.match(line)
        if m:
            heads.append((m.group(1), idx))
    pages = []
    for k, (label, start) in enumerate(heads):
        end = heads[k + 1][1] if k + 1 < len(heads) else len(lines)
        pages.append({"page": label, "prompt": _first_fenced_block(lines[start + 1:end])})
    return pages


def validate_complete(all_pages):
    """完整性校验：至少一页，且每个 ### PN 页都有围栏提示词。缺则抛 ValueError 列出缺页。"""
    if not all_pages:
        raise ValueError("未找到任何 `### PN` 配图页——检查笔记「## 配图轮播」区块是否规范（页标题须是 ### P1 …）")
    missing = [p["page"] for p in all_pages if p["prompt"] is None]
    if missing:
        raise ValueError(
            f"以下页缺绘图提示词围栏（``` 代码块），无法出图：{', '.join(missing)}"
            "（后端会静默跳过缺围栏页导致页序错位，故在此拦截；请补全围栏后重试）")


def parse_page_spec(spec):
    """解析 --pages：'2-9' / '3,5' / '2-4,7' 混合 → 升序去重的页号列表。非法格式抛 ValueError。"""
    nums = set()
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            a, _, b = tok.partition("-")
            a, b = a.strip(), b.strip()
            if not (a.isdigit() and b.isdigit()):
                raise ValueError(f"页区间格式非法：{tok!r}（应形如 2-9）")
            lo, hi = int(a), int(b)
            if lo < 1 or hi < lo:
                raise ValueError(f"页区间非法：{tok!r}（须 1 ≤ 起 ≤ 止）")
            nums.update(range(lo, hi + 1))
        else:
            if not tok.isdigit() or int(tok) < 1:
                raise ValueError(f"页号格式非法：{tok!r}")
            nums.add(int(tok))
    if not nums:
        raise ValueError("--pages 未解析出任何页")
    return sorted(nums)


def select_pages(all_pages, cover_only, spec):
    """按 --cover-only / --pages 选页，返回选中页 dict 列表（保持文档序）。
    请求了本篇不存在的页号 → 报错（防手滑选到越界页）。"""
    label_num = {p["page"]: int(p["page"][1:]) for p in all_pages}
    available = set(label_num.values())
    if cover_only:
        wanted = [1]
    elif spec:
        wanted = parse_page_spec(spec)
    else:
        wanted = sorted(available)
    missing = [n for n in wanted if n not in available]
    if missing:
        raise ValueError(
            f"请求的页不存在：{', '.join('P' + str(n) for n in missing)}"
            f"（本篇共 {len(all_pages)} 页：{', '.join(p['page'] for p in all_pages)}）")
    wset = set(wanted)
    return [p for p in all_pages if label_num[p["page"]] in wset]


def build_warnings(selected, cover_only, anchor_url):
    w = []
    if not cover_only and len(selected) > 1 and not anchor_url:
        w.append("未带锚点参考图（--anchor-url），整套一致性无保障；正常流程应先 --cover-only 出封面过风格闸门，"
                 "运营确认后用返回的 anchor_url 再批量出图")
    if len(selected) > 10:
        w.append(f"本次 {len(selected)} 页超服务端建议上限 10 页/次，建议拆成多次 --pages 出")
    return w


def image_filename(label):
    """页 label（P1/P12）→ 落盘文件名 P01.png / P12.png（序号固定两位数，与页号对应）。"""
    return f"P{int(label[1:]):02d}.png"


def abs_url(u, api_base):
    """相对 /uploads/… 拼成公网绝对 URL（免鉴权可直接下载）；已是 http(s) 原样；空/非串 → None。"""
    if not (isinstance(u, str) and u.strip()):
        return None
    return u if u.startswith(("http://", "https://")) else api_base + "/" + u.lstrip("/")


def send_request(method, url, key, payload=None, timeout=60):
    """带 Bearer 鉴权调 op API。网络异常向上抛，由调用方统一转 failed/unknown。"""
    import requests
    headers = {"Authorization": f"Bearer {key}"}
    return requests.request(method, url, json=payload, headers=headers, timeout=timeout)


def api_error(resp):
    """错误体两套形状：401/422 键是 detail，403/404/400/500 键是 error（与发布/搬运同契约）。"""
    try:
        data = resp.json()
        msg = data.get("error") or data.get("detail") or resp.text[:200]
    except Exception:
        msg = resp.text[:200]
    return f"HTTP {resp.status_code}: {msg}"


def sandbox_hint(exc):
    """网络被拦时给 agent 可执行的下一步（Claude 沙盒拦网是已知场景）。"""
    s = str(exc)
    if any(k in s for k in ("Host not allowed", "ProxyError", "Connection refused",
                            "ConnectionError", "timed out", "Max retries")):
        return ("网络请求失败。若在 Claude Code 沙盒内被拦（典型报错 Host not allowed），"
                "先跑 `python3 scripts/nbdpsy_common.py sandbox allow` 写入放行名单并重启 "
                "Claude Code；单次命令也可用 Bash 工具参数 dangerouslyDisableSandbox 重试。"
                f"原始错误：{s[:200]}")
    return s[:300]


def create_job(api_base, key, prompts, anchor_url):
    """建一致性生图任务（不传 draft_id，后端自动开临时容器）。返回 (job_id, session_id)。"""
    payload = {"prompts": prompts}
    if anchor_url:
        payload["anchor_url"] = anchor_url
    resp = send_request("POST", f"{api_base}/api/op/consistent-images", key, payload, timeout=60)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    data = resp.json()
    return data.get("job_id"), data.get("session_id")


def poll_job(api_base, key, session_id, job_id, timeout, interval=10.0, max_transient=3):
    """轮询到终态或超时；瞬时故障（网络异常/5xx）连续容忍 max_transient 次——
    一次抖动绝不能把仍在跑的任务判成终态。401/403/404 是永久错误立即抛。
    超时返回最后一次视图（不算失败，可 --job 复查）。"""
    deadline = time.monotonic() + timeout
    url = f"{api_base}/api/op/drafts/{session_id}/jobs/{job_id}"
    transient = 0
    while True:
        try:
            resp = send_request("GET", url, key)
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


def _error_for(errors, i, page):
    """从 result.errors 里为第 i 页（label=page）找失败文案，形态宽容：
    ①与 urls 等长的消息数组（该位为空=成功）②仅失败记录的对象数组（按 index/page 匹配）
    ③按下标/页号索引的对象 ④整段字符串。找不到 → None。"""
    if not errors:
        return None
    if isinstance(errors, list):
        if i < len(errors) and isinstance(errors[i], str) and errors[i].strip():
            return errors[i]
        for e in errors:
            if isinstance(e, dict) and (e.get("index") == i or e.get("page") == page):
                return e.get("error") or e.get("message") or json.dumps(e, ensure_ascii=False)
        return None
    if isinstance(errors, dict):
        for k in (str(i), i, page):
            if k in errors and errors[k]:
                v = errors[k]
                return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        return None
    if isinstance(errors, str):
        return errors
    return None


def download_image(url_abs, dst):
    """下载单页图（/uploads/ 公开免鉴权）。失败向上抛，由调用方记 error 不炸整体。"""
    import requests
    dst.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url_abs, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)


def finalize(view, selected_pages, images_dir, api_base):
    """把终态 view.result 的 urls/errors 映射到每页并下载。
    返回 [{"page","url","path","error"}]，与 selected_pages 对齐（第 i 个 prompt ↔ 第 i 页）。"""
    result = view.get("result") or {}
    urls = result.get("urls") or []
    errors = result.get("errors")
    out = []
    for i, pg in enumerate(selected_pages):
        label = pg["page"]
        rec = {"page": label, "url": None, "path": None, "error": None}
        u = abs_url(urls[i] if i < len(urls) else None, api_base)
        if u:
            rec["url"] = u
            dst = images_dir / image_filename(label)
            try:
                download_image(u, dst)
                rec["path"] = str(dst)
            except Exception as e:  # noqa: BLE001 — 图在服务端仍可用，--job 复查可补下
                rec["error"] = f"下载失败（图在服务端仍可用，--job 复查可补下）：{sandbox_hint(e)}"
                print(f"  ⚠ {label} {rec['error']}", file=sys.stderr)
        else:
            rec["error"] = _error_for(errors, i, label) or "服务端未返回该页图 URL（生成失败）"
            print(f"  ⚠ {label} 生成失败：{rec['error']}", file=sys.stderr)
        out.append(rec)
    return out


def summarize_outcome(pages_out):
    """有图有落盘=done；部分成功=partial；一张 URL 都没拿到=failed。"""
    have_url = [p for p in pages_out if p["url"]]
    ok = [p for p in pages_out if p["url"] and p["path"]]
    if not have_url:
        return "failed"
    return "done" if len(ok) == len(pages_out) else "partial"


def retry_hint(failed_labels, anchor_url, cover_only):
    if cover_only:
        return "封面页未出成，调提示词后重跑 --cover-only（这是风格闸门第一步，确认后再批量出）"
    nums = ",".join(str(int(l[1:])) for l in failed_labels)
    tail = f" --anchor-url {anchor_url}" if anchor_url else ""
    return f"部分页未出成，用 --pages {nums}{tail} 只重出失败页（带同一锚点保持一致性）"


def pending_envelope(sid, jid, anchor, warnings):
    return {
        "outcome": "pending", "session_id": sid, "job_id": jid,
        "pages": [], "anchor_url": anchor, "error": None,
        "hint": f"任务已入队仍在生成（每页约 50s），稍后用 --job {jid} --session {sid} 复查并补下载，勿重发",
        "warnings": warnings,
    }


def emit_result(pages_out, sid, jid, cover_only, anchor, warnings):
    """打印终态结果信封并按 outcome 退出（done=0 / partial|failed=1）。"""
    outcome = summarize_outcome(pages_out)
    # cover-only 时把 P1 的绝对 URL 直接回给 agent，方便下一步批量出图直接当锚点
    out_anchor = pages_out[0]["url"] if (cover_only and pages_out and pages_out[0]["url"]) else anchor
    out = {"outcome": outcome, "session_id": sid, "job_id": jid,
           "pages": pages_out, "anchor_url": out_anchor,
           "error": None, "hint": None, "warnings": warnings}
    if outcome != "done":
        failed_labels = [p["page"] for p in pages_out if not p["path"]]
        out["hint"] = retry_hint(failed_labels, anchor, cover_only)
        if outcome == "failed":
            out["error"] = "全部页未出成（服务端未返回图 URL；可能触发额度/限流，见各页 error）"
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(1 if outcome in ("partial", "failed") else 0)


def resolve_images_dir(note, images_dir):
    if images_dir:
        return Path(images_dir)
    if note:
        return note.parent / "images" / note.stem  # 与 publish_note.collect_images 默认一致
    return None


def read_state(images_dir):
    p = images_dir / STATE_FILE
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_state(images_dir, sid, jid, page_labels, anchor):
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / STATE_FILE).write_text(
        json.dumps({"session_id": sid, "job_id": jid, "pages": page_labels, "anchor_url": anchor},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")


def _truncate(s, n=60):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def run_dry(args, note, images_dir, api_base):
    """离线打印将发送的 payload（提示词截断）与目标 URL，不打网络、不需要凭据。"""
    if not note:
        sys.exit("--dry-run 需要 --note")
    all_pages = extract_pages(note.read_text(encoding="utf-8"))
    try:
        validate_complete(all_pages)
        selected = select_pages(all_pages, args.cover_only, args.pages)
        warnings = build_warnings(selected, args.cover_only, args.anchor_url)
    except ValueError as e:
        print(json.dumps({"outcome": "failed", "error": str(e),
                          "pages_detected": [p["page"] for p in all_pages]},
                         ensure_ascii=False, indent=2))
        sys.exit(1)
    payload = {"prompts": [_truncate(p["prompt"]) for p in selected]}
    if args.anchor_url:
        payload["anchor_url"] = args.anchor_url
    print(json.dumps({
        "outcome": "dry_run",
        "target_url": f"{api_base}/api/op/consistent-images",
        "note": str(note),
        "pages_detected": [p["page"] for p in all_pages],
        "selected_pages": [p["page"] for p in selected],
        "images_dir": str(images_dir) if images_dir else None,
        "payload_preview": payload,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="用后端 gpt-image 锚点法给小红书笔记出一致性轮播配图（异步）")
    ap.add_argument("--note", type=Path, help="笔记文件（post-NN.md，须含「## 配图轮播」）")
    ap.add_argument("--cover-only", action="store_true", help="只出 P1 封面（风格闸门第一步）")
    ap.add_argument("--anchor-url", help="锚点参考图 URL（P1 确认后的封面），各页据此锚定生成保持一致")
    ap.add_argument("--pages", help="只出指定页：'2-9' / '3,5' / '2-4,7' 混合（默认全部页）")
    ap.add_argument("--images-dir", type=Path, help="落盘目录（默认 <笔记同目录>/images/<笔记名>/）")
    ap.add_argument("--api-base", help="API base（默认 NBDPSY_VIDEO_API_BASE 或 https://xhs.nbdpsy.com）")
    ap.add_argument("--no-wait", action="store_true", help="提交后不等结果（稍后 --job 复查）")
    ap.add_argument("--wait-timeout", type=float,
                    help="轮询等待上限秒数（默认 max(180, 页数×90)）")
    ap.add_argument("--dry-run", action="store_true", help="只打 payload 摘要与目标 URL，不发请求")
    ap.add_argument("--job", type=int, help="复查该已入队任务并补下载（配 --note 或 --images-dir 定位目录）")
    ap.add_argument("--session", help="--job 复查用的 session_id（缺省则从状态文件恢复）")
    args = ap.parse_args()

    note = args.note
    images_dir = resolve_images_dir(note, args.images_dir)
    api_base = (args.api_base or nbdpsy_common.video_api_base()).rstrip("/")

    # dry-run 离线，不需要凭据
    if args.dry_run:
        run_dry(args, note, images_dir, api_base)
        return

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.XHS_API_KEY} 找管理员要「运营接入配置包」，"
              "secret import 导入后重试（与小红书发布 / 视频搬运同一把凭据）", file=sys.stderr)
        sys.exit(1)

    sid = jid = None  # 已入队的 session/job——之后任何异常都不能丢它，否则会诱发重复生成
    try:
        # ---- --job 复查已入队任务并补下载 ----
        if args.job is not None:
            if images_dir is None:
                raise ValueError("--job 复查需要 --note 或 --images-dir 以定位图片目录与状态文件")
            state = read_state(images_dir)
            jid = args.job
            sid = args.session or state.get("session_id")
            if not sid:
                raise ValueError("缺 --session，且状态文件里没有 session_id；请补 --session <id>")
            page_labels = state.get("pages") or []
            anchor = state.get("anchor_url")
            if not page_labels:
                raise ValueError("状态文件缺页映射（pages），无法对齐下载；请重新出图而非复查")
            selected = [{"page": l} for l in page_labels]
            cover_only = page_labels == ["P1"] and not anchor
            view = poll_job(api_base, key, sid, jid, timeout=0)  # 单次探测
            if view.get("status") not in TERMINAL_STATUSES:
                print(json.dumps(pending_envelope(sid, jid, anchor, []), ensure_ascii=False))
                sys.exit(0)
            pages_out = finalize(view, selected, images_dir, api_base)
            emit_result(pages_out, sid, jid, cover_only, anchor, [])

        # ---- 正常出图 ----
        if not note:
            ap.error("出图需要 --note（或用 --job 复查已入队任务）")
        all_pages = extract_pages(note.read_text(encoding="utf-8"))
        validate_complete(all_pages)
        selected = select_pages(all_pages, args.cover_only, args.pages)
        cover_only = args.cover_only
        anchor = args.anchor_url
        warnings = build_warnings(selected, cover_only, anchor)
        for w in warnings:
            print(f"⚠ {w}", file=sys.stderr)

        prompts = [p["prompt"] for p in selected]
        page_labels = [p["page"] for p in selected]
        print(f"提交出图：{note.name} {len(selected)} 页（{', '.join(page_labels)}）→ {api_base} …",
              file=sys.stderr)
        jid, sid = create_job(api_base, key, prompts, anchor)
        if not jid or not sid:
            raise ValueError(f"建任务响应缺 job_id/session_id：job_id={jid} session_id={sid}")
        print(f"  已入队 job_id={jid} session_id={sid}", file=sys.stderr)
        write_state(images_dir, sid, jid, page_labels, anchor)

        if args.no_wait:
            print(json.dumps(pending_envelope(sid, jid, anchor, warnings), ensure_ascii=False))
            return

        timeout = args.wait_timeout if args.wait_timeout is not None else max(180, len(selected) * 90)
        view = poll_job(api_base, key, sid, jid, timeout=timeout)
        if view.get("status") not in TERMINAL_STATUSES:  # 超时仍在跑
            print(json.dumps(pending_envelope(sid, jid, anchor, warnings), ensure_ascii=False))
            return
        pages_out = finalize(view, selected, images_dir, api_base)
        emit_result(pages_out, sid, jid, cover_only, anchor, warnings)

    except Exception as e:
        msg = sandbox_hint(e)
        if sid is not None and jid is not None:
            # 任务已在服务端入队，绝不判 failed——那会让 agent 重发同一批（重复生成/烧额度）
            print(f"  → 状态未知: {msg}", file=sys.stderr)
            print(json.dumps({
                "outcome": "unknown", "session_id": sid, "job_id": jid, "pages": [],
                "anchor_url": args.anchor_url, "error": msg,
                "hint": f"任务可能仍在服务端跑，先用 --job {jid} --session {sid} 复查，勿直接重发以免重复生成",
            }, ensure_ascii=False))
            sys.exit(0)
        # 未入队的异常（解析/选页/建任务失败）才是真 failed
        print(f"  → 失败: {msg}", file=sys.stderr)
        print(json.dumps({"outcome": "failed", "session_id": None, "job_id": None,
                          "pages": [], "error": msg}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()

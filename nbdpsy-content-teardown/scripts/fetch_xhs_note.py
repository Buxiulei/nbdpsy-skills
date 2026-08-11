#!/usr/bin/env python3
"""抓一篇小红书笔记（他人的也行）的全文、图片与互动数，落成可读的拆解素材。

走 nbdpsy-api 的 POST /api/notes/extract（正文**同步返回**，不用轮询）；只有要评论时
（--comments N）服务端才另起一次浏览器会话，返回 job_id 交给 GET /api/note-extracts/{job_id}
轮询——**轮询只为评论存在**。

用法：
    python3 fetch_xhs_note.py <笔记URL> [--out DIR]
                              [--comments N --account 账号名或ID]  # 取前 N 条评论
                              [--no-images] [--refresh] [--api-base URL] [--wait-timeout 秒]

产出（默认落 ./teardown-out/xhs-<note_id>/）：
    note.json   服务端原始响应（要评论时把轮询回来的评论回填进 comments 字段）
    note.md     人读版：标题/作者/发布时间/互动数/正文全文/话题标签/图片永久链清单/评论

**入参必须是带 xsec_token 的完整链接或分享短链**。直接从浏览器地址栏复制的
`https://www.xiaohongshu.com/explore/<note_id>` 裸链会被服务端 400 拒掉（平台对无 token 的
请求只吐空壳页，没有正文）。正确姿势：小红书 App／网页版点分享按钮生成 xhslink.cn/... 短链，
或复制带 ?xsec_token=... 的完整链接，**不要手工精简 URL**（精简掉的参数还影响商品笔记判定）。

凭据：NBDPSY_XHS_API_KEY（nbdpsy_common 三层解析：环境变量 > 工作区 .env > 用户级 secrets）；
基址 NBDPSY_XHS_API_BASE，默认 https://mcp.nbdpsy.com。

图片有三种链，别搞混（note.md 里以永久链为准）：
    permanent_url  平台永久图链，**拆解存档用这个**
    signed_url     带时效签名的 CDN 直链，几小时就死
    url            代下到自家图床的副本，image_batch.expires_at 到期即清（默认 7 天）

退出码：0 成功；1 失败（HTTP 报错 / 轮询超时 / 落盘失败，一律 fail-loud）。
"""
import argparse
import json
import sys
import time
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common

# 评论任务终态。unknown 也是终态——服务端明说它是「真的不知道」，轮下去也不会变。
EXTRACT_TERMINAL = {"done", "error", "unknown"}
# 各 HTTP 码的中文可操作提示（服务端自己的 error/detail 文案照样透传，这里是补「该怎么办」）
STATUS_HINTS = {
    400: "请求被服务端拒了。最常见的是链接没带 xsec_token：请用小红书 App／网页版的**分享按钮**"
         "生成原始链接（xhslink.cn/... 短链，或带 ?xsec_token=... 的完整链接），不要复制地址栏"
         "里的 /explore/<note_id> 裸链、也不要手工精简 URL。",
    401: "apikey 无效或缺失。找管理员要「运营接入配置包」，用 "
         "`python3 scripts/nbdpsy_common.py secret import <包>` 导入后重试。",
    402: "配额/额度不足（笔记提取或浏览器会话额度用尽）。等额度刷新，或找管理员调额；"
         "不带 --comments 重跑只取正文不消耗会话额度。",
    403: "没有权限。你这把 key 的 scope 里没有笔记提取，或 --account 指定的账号没授权给你。"
         "可用 nbdpsy-xiaohongshu-creator 技能的 note_ops.py（`python3 <该skill目录>/scripts/"
         "note_ops.py --ledger <你的账号>`）确认能看到哪些号，再找管理员开权限。",
    404: "对象不存在（job_id 写错，或任务过期被清理）。重跑一次提取拿新的 job_id。",
    422: "参数不合法。最常见的是要评论却没给 --account（评论只能靠真实浏览器会话拿到，"
         "建议用非品牌号）；其次是 --comments 超出 0-100。",
}


def send_request(method: str, url: str, key: str, payload=None, timeout=180):
    """带 Bearer 鉴权调 nbdpsy-api。网络异常向上抛，由调用方决定怎么报。"""
    import requests
    headers = {"Authorization": f"Bearer {key}"}
    return requests.request(method, url, json=payload, headers=headers, timeout=timeout)


def api_error(resp) -> str:
    """nbdpsy-api 错误体：401/422 键是 detail，400/403/404/500 键是 error。附中文可操作提示。"""
    try:
        data = resp.json()
        msg = data.get("error") or data.get("detail") or resp.text[:300]
    except Exception:
        msg = resp.text[:300]
    if not isinstance(msg, str):
        msg = json.dumps(msg, ensure_ascii=False)
    hint = STATUS_HINTS.get(resp.status_code)
    return f"HTTP {resp.status_code}: {msg}" + (f"\n  → {hint}" if hint else "")


def sandbox_hint(exc) -> str:
    """网络被拦时给 agent 可执行的下一步（Claude 沙盒拦网是已知场景）。"""
    s = str(exc)
    if any(k in s for k in ("Host not allowed", "ProxyError", "Connection refused",
                            "ConnectionError", "timed out", "Max retries")):
        return ("网络请求失败。若在 Claude Code 沙盒内被拦（典型报错 Host not allowed），"
                "先跑 `python3 scripts/nbdpsy_common.py sandbox allow` 写入放行名单并重启 "
                "Claude Code；单次命令也可用 Bash 工具参数 dangerouslyDisableSandbox 重试。"
                f"原始错误：{s[:200]}")
    return s[:400]


def build_payload(url: str, with_images: bool = True, comments: int = 0,
                  account_id=None, refresh: bool = False) -> dict:
    """构造 /api/notes/extract 请求体（纯函数）。

    只带服务端认识的五个字段；account_id 仅在真要评论时才带——不要评论却带着它，
    会让人以为这次消耗了会话额度。
    """
    if not url or not url.strip():
        raise ValueError("没给笔记链接")
    if not 0 <= comments <= 100:
        raise ValueError(f"--comments 只能是 0-100，给的是 {comments}")
    payload = {
        "url": url.strip(),
        "with_images": bool(with_images),
        "with_comments": int(comments),
        "refresh": bool(refresh),
    }
    if comments > 0:
        if account_id is None:
            raise ValueError("要抓评论必须给 --account（评论只能靠真实浏览器会话拿到，建议用非品牌号）")
        payload["account_id"] = int(account_id)
    return payload


def resolve_account(api_base: str, key: str, account: str):
    """--account 支持数字 id 或 名称/昵称 精确匹配；歧义/未命中时列出可选项。"""
    if str(account).isdigit():
        return int(account)
    resp = send_request("GET", f"{api_base}/api/accounts", key, timeout=60)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    accounts = resp.json().get("accounts", [])
    hits = [a for a in accounts if account in (a.get("name"), a.get("nickname"))]
    if len(hits) == 1:
        return hits[0]["id"]
    avail = "、".join(f'{a.get("name")}(id={a.get("id")})' for a in accounts) or "（无可用账号）"
    raise ValueError(f"账号「{account}」{'匹配到多个' if hits else '不存在或未授权'}；可用：{avail}")


def extract(api_base: str, key: str, payload: dict) -> dict:
    """提交提取请求。正文同步就回来了；要评论时响应里带 comments_job。"""
    resp = send_request("POST", f"{api_base}/api/notes/extract", key, payload)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def poll_extract(api_base: str, key: str, job_id: str, timeout: float,
                 interval: float = 4.0, max_transient: int = 3) -> dict:
    """轮询评论任务到终态（范式抄 note_ops.poll_task）。

    返回终态视图 / {"status":"gone"}（404）/ 超时时最后一次视图。网络抖动与 5xx 连续容忍
    max_transient 次（一次抖动绝不误判成终态）；401/403 这类永久错误立即抛。
    """
    url = f"{api_base}/api/note-extracts/{job_id}"
    deadline = time.monotonic() + timeout
    transient = 0
    last = {"status": "running"}
    while True:
        try:
            resp = send_request("GET", url, key, timeout=60)
        except Exception as e:
            transient += 1
            if transient > max_transient:
                raise
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {e}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code == 404:
            return {"status": "gone"}
        if resp.status_code >= 500:
            transient += 1
            if transient > max_transient:
                raise ValueError(api_error(resp))
            print(f"  轮询瞬时失败（{transient}/{max_transient}）: {api_error(resp)}", file=sys.stderr)
            time.sleep(interval)
            continue
        if resp.status_code >= 400:
            raise ValueError(api_error(resp))
        transient = 0
        last = resp.json()
        status = last.get("status")
        print(f"  评论任务: {status}", file=sys.stderr)
        if status in EXTRACT_TERMINAL:
            return last
        if time.monotonic() >= deadline:
            last = dict(last)
            last["timed_out"] = True
            return last
        time.sleep(interval)


def _num(v):
    """互动数展示：None 是「没拿到」，**不是 0**——渲染成「未知」，别让缺失值静默变零。"""
    return "未知" if v is None else v


def render_markdown(note: dict) -> str:
    """note.json → 人读版 note.md（纯函数，不打网络）。"""
    author = note.get("author") or {}
    interact = note.get("interact") or {}
    src = note.get("source") or {}
    batch = note.get("image_batch") or {}
    lines = []

    lines.append(f"# {note.get('title') or '（无标题）'}")
    lines.append("")
    lines.append(f"- 作者：{author.get('nickname') or '未知'}"
                 + (f"（IP 属地 {author['ip_location']}）" if author.get("ip_location") else ""))
    if author.get("profile_url"):
        lines.append(f"- 作者主页：{author['profile_url']}")
    lines.append(f"- 发布时间：{note.get('published_at') or '未知'}")
    if note.get("last_update_at") and note.get("last_update_at") != note.get("published_at"):
        lines.append(f"- 最后修改：{note['last_update_at']}")
    lines.append(f"- 互动：点赞 {_num(interact.get('liked'))}｜收藏 {_num(interact.get('collected'))}"
                 f"｜评论 {_num(interact.get('comment'))}｜分享 {_num(interact.get('share'))}")
    lines.append(f"- 笔记类型：{note.get('note_type') or '未知'}"
                 + (f"（{note['note_type_raw']}）" if note.get("note_type_raw") else ""))
    lines.append(f"- note_id：{note.get('note_id') or '未知'}")
    if src.get("final_url"):
        lines.append(f"- 来源链接：{src['final_url']}")
    if src.get("fetched_at"):
        lines.append(f"- 抓取时间：{src['fetched_at']}"
                     + ("（**命中 24h 缓存**，数字可能不是此刻的；要最新数据加 --refresh）"
                        if src.get("from_cache") else ""))
    lines.append("")

    lines.append("## 正文")
    lines.append("")
    lines.append(note.get("content") or "（服务端没返回正文）")
    lines.append("")

    lines.append("## 话题标签")
    lines.append("")
    topics = note.get("topics") or []
    lines.append(" ".join(f"#{t}" for t in topics) if topics else "（无话题标签）")
    lines.append("")

    lines.append("## 图片永久链")
    lines.append("")
    images = note.get("images") or []
    if not images:
        lines.append("（无图片）")
    else:
        for img in images:
            size = (f"（{img.get('width')}×{img.get('height')}）"
                    if img.get("width") and img.get("height") else "")
            link = img.get("permanent_url") or img.get("signed_url") or img.get("url") or "（无链接）"
            mark = "" if img.get("permanent_url") else "　⚠️ 无永久链，这条是短效链，尽快另存"
            lines.append(f"{img.get('ordinal')}. {link}{size}{mark}")
            if img.get("url"):
                lines.append(f"   - 图床副本：{img['url']}")
    if batch.get("expires_at"):
        lines.append("")
        lines.append(f"> 图床副本（batch {batch.get('batch_id')}）{batch['expires_at']} 到期清理；"
                     "长期存档请用上面的永久链。")
    lines.append("")

    video = note.get("video")
    if video:
        lines.append("## 视频")
        lines.append("")
        lines.append(f"```json\n{json.dumps(video, ensure_ascii=False, indent=2)}\n```")
        lines.append("")

    comments = note.get("comments")
    if comments:
        complete = note.get("comments_complete")
        lines.append(f"## 评论（{len(comments)} 条"
                     f"{'，已取全' if complete else '，未取全'}）")
        lines.append("")
        for c in comments:
            flag = "（作者回复）" if c.get("is_author_reply") else ""
            likes = c.get("like_count")
            like_txt = f"｜赞 {likes}" if isinstance(likes, int) and likes > 0 else ""
            lines.append(f"- **{c.get('author') or '匿名'}**{flag}：{c.get('text') or ''}{like_txt}")
            for sub in c.get("sub_comments") or []:
                lines.append(f"  - {sub.get('author') or '匿名'}：{sub.get('text') or ''}")
        lines.append("")

    unavailable = dict(note.get("unavailable") or {})
    # 评论已经靠浏览器任务拿到了，就别再留一句「评论纯 HTTP 取不到」跟上面的评论区自相矛盾
    if comments:
        unavailable.pop("comments", None)
    if unavailable:
        lines.append("## 服务端说明拿不到的部分")
        lines.append("")
        for k, v in unavailable.items():
            lines.append(f"- **{k}**：{v}")
        lines.append("")

    return "\n".join(lines)


def dump(out_dir: Path, note: dict) -> None:
    """落盘 note.json + note.md（重复调用就是覆盖重写）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "note.json").write_text(
        json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "note.md").write_text(render_markdown(note), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="抓一篇小红书笔记的全文/图片/互动数（经 nbdpsy-api）")
    ap.add_argument("url", help="笔记链接（分享短链 xhslink.cn/... 或带 xsec_token 的完整链接）")
    ap.add_argument("--out", help="产物目录（默认 ./teardown-out/xhs-<note_id>）")
    ap.add_argument("--comments", type=int, default=0, metavar="N",
                    help="取前 N 条评论（0-100，>0 需 --account，会消耗一次浏览器会话额度）")
    ap.add_argument("--account", help="--comments 用哪个号去抓（名称或 id，建议用非品牌号）")
    ap.add_argument("--no-images", action="store_true", help="不代下图片进自家图床（永久链照样给）")
    ap.add_argument("--refresh", action="store_true", help="跳过服务端 24h 缓存强制重抓")
    ap.add_argument("--api-base", help="覆盖 API 根地址")
    ap.add_argument("--wait-timeout", type=float, default=300,
                    help="评论任务轮询上限秒数（默认 300）")
    args = ap.parse_args()

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.XHS_API_KEY} 找管理员要「运营接入配置包」，"
              "secret import 导入后重试", file=sys.stderr)
        sys.exit(1)
    api_base = (args.api_base or nbdpsy_common.xhs_api_base()).rstrip("/")

    out_dir = None
    try:
        account_id = resolve_account(api_base, key, args.account) if args.account else None
        payload = build_payload(args.url, not args.no_images, args.comments, account_id, args.refresh)

        print(f"→ 提取笔记：{args.url[:100]}", file=sys.stderr)
        note = extract(api_base, key, payload)
        print(f"  正文已同步返回：《{note.get('title')}》"
              f"／{len(note.get('images') or [])} 图", file=sys.stderr)

        note_id = note.get("note_id") or "unknown"
        out_dir = Path(args.out) if args.out else Path("teardown-out") / f"xhs-{note_id}"
        # 先落一份：抓评论要烧浏览器会话额度，磁盘不可写这种错必须在烧之前就炸出来
        dump(out_dir, note)

        job = note.get("comments_job") or {}
        if job.get("job_id"):
            print(f"  评论另起浏览器任务 job_id={job['job_id']}（{job.get('session_cost') or ''}）",
                  file=sys.stderr)
            view = poll_extract(api_base, key, job["job_id"], args.wait_timeout)
            note["comments_job_result"] = view
            status = view.get("status")
            if status == "done":
                # 服务端把 comments/comments_complete 留空就是等这一步回填，不是我们自造字段
                note["comments"] = view.get("comments")
                note["comments_complete"] = view.get("complete")
                note["comments_source"] = f"job:{job['job_id']}"
                print(f"  评论 {view.get('count')} 条"
                      f"（complete={view.get('complete')} stop_reason={view.get('stop_reason')}）",
                      file=sys.stderr)
            elif view.get("timed_out"):
                print(f"⚠️ 评论轮询超过 {args.wait_timeout}s 仍是 {status}，正文照常落盘，评论留空。"
                      f"稍后自己查：GET {api_base}/api/note-extracts/{job['job_id']}", file=sys.stderr)
            else:
                print(f"⚠️ 评论任务终态 {status}，评论没拿到（正文照常落盘）："
                      f"{json.dumps(view, ensure_ascii=False)[:300]}", file=sys.stderr)

            dump(out_dir, note)  # 评论回填后覆盖重写
    except Exception as e:
        print(f"✗ 抓取失败：{sandbox_hint(e)}", file=sys.stderr)
        if out_dir and (out_dir / "note.json").is_file():
            # 正文已经落过盘了（评论轮询半路挂掉属于这种）——别让人以为整趟白跑又重抓一遍
            print(f"  正文已经落在 {out_dir / 'note.json'}，只是评论没补上", file=sys.stderr)
        sys.exit(1)

    print(f"\n✓ 原始 → {out_dir / 'note.json'}", file=sys.stderr)
    print(f"✓ 人读 → {out_dir / 'note.md'}", file=sys.stderr)
    interact = note.get("interact") or {}
    print(f"  {(note.get('author') or {}).get('nickname')}｜{note.get('published_at')}"
          f"｜赞 {_num(interact.get('liked'))} 藏 {_num(interact.get('collected'))}", file=sys.stderr)
    print(json.dumps({"note_id": note.get("note_id"), "title": note.get("title"),
                      "out_dir": str(out_dir), "images": len(note.get("images") or []),
                      "comments": len(note.get("comments") or [])}, ensure_ascii=False))


if __name__ == "__main__":
    main()

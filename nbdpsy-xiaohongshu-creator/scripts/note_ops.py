#!/usr/bin/env python3
"""已发布笔记的台账查询与操作（经 nbdpsy-api，纯 REST）。

发布走 publish_note.py；**笔记发出去之后**的事都在这里：查台账、改合集/引用/活动、
切公开或私密、发评论、手工触发同步与目的回填。

用法：
    python3 note_ops.py --ledger 账号名或ID [--limit 50] [--offset 0]
                                             # 平台上现存哪些笔记（台账，权威）
    python3 note_ops.py --note <note_id>     # 单条详情（**只有这里返回正文 content_text**）
    python3 note_ops.py --collections 账号名或ID          # 该号的合集
    python3 note_ops.py --activities 账号名或ID [--keyword 心理]   # 可关联的活动
    python3 note_ops.py --set-components --account 号 --note-id ID
        [--collection-id N] [--quoted-note-id ID] [--activity-id N] [--related-counselor 姓名]
    python3 note_ops.py --set-visibility --account 号 --privacy 0|1 [--note-id ID|--title 标题]
    python3 note_ops.py --comment --account 号 --text "评论文案" [--title 标题] [--publisher-user-id X]
    python3 note_ops.py --sync-ledger 账号名或ID      # 手工触发一次台账同步（幂等，可放心重试）
    python3 note_ops.py --backfill-purpose 账号名或ID  # 手工触发核心目的回填（幂等，可放心重试）

凭据同 publish_note.py：NBDPSY_XHS_API_KEY / NBDPSY_XHS_API_BASE（nbdpsy_common 三层解析）。

四条硬规矩（都是踩过坑换来的，代码里已按此实现，改动时别绕开）：

1. **permission_code 的 null 不是公开。** 只有 `== 0` 才是公开，`1` 是仅自己可见，
   `null` 是未知。本脚本一律输出 `visibility: public|private|unknown` 三态，
   绝不把 unknown 当 public——服务端那边真发生过据此差点把用户刻意隐藏的私密笔记改公开。
2. **published_notes ≠ publish_jobs。** 问「平台上现在有什么」查本脚本 --ledger；
   问「我们提交过什么」查 publish_note.py --list-jobs。笔记被删后 publish_jobs 仍是
   published 不回滚（实证：某号 20 条 published，平台只剩 17 篇）。
3. **success 不等于生效。** 这条产品线的失败普遍是静默的（私密笔记的合集绑定会被平台
   静默丢弃、活动关联按钮首次点击无声失效）。三组件必须逐项看 applied / failed，
   本脚本 outcome=partial 就是「有的成了有的没成」，**不是成功**。
4. **非幂等操作失败不要盲目重试**：可见性切换 / 评论 / 三组件（活动还会重复往正文注入话题）。
   本脚本对这三类一律不自动重试，异常与超时都落 outcome=unknown + 「先核对当前实际状态」。
   幂等可安全重试的只有 --sync-ledger / --backfill-purpose。

两条业务规则（不是技术偏好，是绩效归属）：笔记只引用**本账号**的推介笔记，跨账号引用会把
客户导到别的运营名下、抢同事 KPI；矩阵号评论零引流指向，转化引导只由笔记所属账号本人发。
唯一例外「接待员联系方式」笔记由服务端配置指定，调用方不用管。

输出契约：stdout 纯 JSON。
查询类 = 服务端视图透传 + 计算字段（列表加 visibility，账号信息在 "account"）；exit 0。
写操作 = {"outcome":"done|partial|failed|unknown", "<id字段>", "applied"?, "failed"?, "hint"?}：
done exit 0；partial/failed exit 1；unknown exit 0（真实未知，绝不冒充失败诱导重试）。
"""
import argparse
import json
import sys
import time
from urllib.parse import urlencode

# 同目录 vendored 副本
import nbdpsy_common

# 三组件任务的终态。partially_applied 也是终态——轮询到它就该停，不是还没跑完。
COMPONENT_TERMINAL = {"done", "error", "partially_applied"}
# 可见性档位：服务端只开放这两档（仅互关好友/部分人可见/部分人不可见未验证，传其他值 422）。
PRIVACY_LABELS = {0: "公开可见", 1: "仅自己可见"}


def send_request(method: str, url: str, key: str, payload=None, timeout=60):
    """带 Bearer 鉴权调 nbdpsy-api。网络异常向上抛，由调用方按操作性质决定信封。"""
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
    """--account 支持数字 id 或 名称/昵称 精确匹配；歧义/未命中时列出可选项。
    cookie_status=restricted（账号被挂了风控验证墙，cookie 本身没失效）会给 warning——
    这类号派活会全部失败，恢复方式是用手机小红书 App 扫码验证身份后重新检测。"""
    if account.isdigit():
        return int(account), account, None
    accounts = list_accounts(api_base, key)
    hits = [a for a in accounts if account in (a["name"], a["nickname"])]
    if len(hits) == 1:
        a = hits[0]
        warn = None
        if a.get("cookie_status") == "invalid":
            warn = f"账号「{account}」cookie 已失效，操作大概率失败，先用 chrome 插件重新扫码登录"
        elif a.get("cookie_status") == "restricted":
            warn = (f"账号「{account}」被小红书挂了风控验证墙（cookie 没失效），派活会失败："
                    "让运营用手机小红书 App 扫码验证身份后重新检测；若提示『请求太频繁』先晾一阵")
        return a["id"], a["name"] or account, warn
    avail = "、".join(f'{a["name"]}(id={a["id"]})' for a in accounts) or "（无可用账号）"
    raise ValueError(f"账号「{account}」{'匹配到多个' if hits else '不存在或未授权'}；可用：{avail}")


def visibility_of(permission_code) -> str:
    """permission_code → 三态可见性。**只有 0 才是公开**；null 是未知，绝不当公开。
    写 `not permission_code` 会把 null 误判成公开——这是服务端出过事故的那个写法。"""
    if permission_code == 0:
        return "public"
    if permission_code is None:
        return "unknown"
    return "private"


def ledger(api_base: str, key: str, account_id: int, limit=50, offset=None) -> dict:
    """台账列表：平台上**当前存在**哪些笔记（按发布时间倒序，单页上限 200）。
    列表不返回 content_text（响应过大），要正文用 --note <note_id>。"""
    params = {}
    if limit:
        params["limit"] = limit
    if offset:
        params["offset"] = offset
    qs = f"?{urlencode(params)}" if params else ""
    resp = send_request("GET", f"{api_base}/api/accounts/{account_id}/published-notes{qs}", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    data = resp.json()
    notes = data.get("notes", data if isinstance(data, list) else [])
    for n in notes:
        n["visibility"] = visibility_of(n.get("permission_code"))
    view = data if isinstance(data, dict) else {}
    view["notes"] = notes
    # 只统计本页（服务端顶层 total 是全量条数，别混为一谈）
    view["counts"] = {
        "in_page": len(notes),
        "public": sum(1 for n in notes if n["visibility"] == "public"),
        "private": sum(1 for n in notes if n["visibility"] == "private"),
        "unknown": sum(1 for n in notes if n["visibility"] == "unknown"),
        "orphan": sum(1 for n in notes if n.get("sync_status") == "orphan"),
        "pending_id": sum(1 for n in notes if n.get("sync_status") == "pending_id"),
    }
    return view


def note_detail(api_base: str, key: str, note_id: str) -> dict:
    """按平台 note_id 取单条（含 content_text 与 note_purpose）。"""
    resp = send_request("GET", f"{api_base}/api/published-notes/{note_id}", key)
    if resp.status_code == 404:
        return {"available": False, "note_id": note_id,
                "hint": "台账里没有这条 note_id：可能是别号的笔记（无权访问会 403 不是 404）、"
                        "note_id 敲错，或该笔记还没同步进台账——先 --sync-ledger <账号> 再查"}
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    view = resp.json()
    # 单条端点把笔记包在 {"note": {...}} 里（列表端点是 {"notes": [...]}）——直接读顶层
    # permission_code 会恒拿到 None，正好落进「null 当未知」那条规则，把公开笔记显示成未知。
    note = view["note"] if isinstance(view.get("note"), dict) else view
    view["available"] = True
    view["visibility"] = visibility_of(note.get("permission_code"))
    if note.get("purpose_source") == "inferred":
        view["purpose_hint"] = "note_purpose 是服务端从正文推断的（LLM 分类），留余地；declared 才是发布时声明的"
    return view


def collections(api_base: str, key: str, account_id: int) -> dict:
    resp = send_request("GET", f"{api_base}/api/accounts/{account_id}/collections", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def activities(api_base: str, key: str, account_id: int, keyword=None) -> dict:
    qs = f"?{urlencode({'keyword': keyword})}" if keyword else ""
    resp = send_request("GET", f"{api_base}/api/accounts/{account_id}/activities{qs}", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json()


def poll_task(api_base: str, key: str, url: str, timeout: float, terminal,
              interval: float = 4.0, max_transient: int = 3) -> dict:
    """轮询异步任务到终态。返回视图 dict：终态视图 / {"status":"gone"}（404 台账失效）/
    超时时最后一次视图。网络抖动与 5xx 连续容忍 max_transient 次（一次抖动绝不误判成终态——
    对非幂等操作，误判会诱发重复评论、重复注入话题）；401/403 永久错误立即抛。"""
    deadline = time.monotonic() + timeout
    transient = 0
    last = {"status": "running"}
    while True:
        try:
            resp = send_request("GET", url, key)
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
        print(f"  任务: {status}", file=sys.stderr)
        if status in terminal or time.monotonic() >= deadline:
            return last
        time.sleep(interval)


def _items(view: dict, key: str):
    """applied / failed 兼容 list 与 dict 两种承载形态，一律归一成 list 便于计数。"""
    v = view.get(key)
    if isinstance(v, dict):
        return [f"{k}={json.dumps(val, ensure_ascii=False)}" if not isinstance(val, str) else f"{k}={val}"
                for k, val in v.items()]
    return list(v) if isinstance(v, list) else []


def components_result(view: dict, job_id: str, requested: dict):
    """三组件终态视图 → 信封 + exit code。
    **逐项判定**：failed 非空即不算成功（服务端 status 可能是 done 但个别项被平台静默丢弃）。"""
    status = view.get("status")
    applied, failed = _items(view, "applied"), _items(view, "failed")
    if status == "gone":
        return {"outcome": "unknown", "job_id": job_id, "requested": requested,
                "hint": "任务台账查不到了（server 可能重启）：三组件非幂等（活动会重复往正文注入话题），"
                        "先用 --note <note_id> 核对当前实际生效情况，再决定要不要重提交"}, 0
    if status == "error" and not applied:
        out = {"outcome": "failed", "job_id": job_id, "requested": requested,
               "reason": view.get("reason"), "failed": failed}
        reason = view.get("reason") or ""
        if "note_not_locatable" in reason:
            out["hint"] = "笔记定位不了（空标题或同号重复标题无法区分）——重试也不会变得可定位，改用 note_id"
        else:
            out["hint"] = "一项都没生效，可以修因后重提交；重提交前先 --note <note_id> 核对现状"
        return out, 1
    if failed:
        return {"outcome": "partial", "job_id": job_id, "requested": requested,
                "applied": applied, "failed": failed, "reason": view.get("reason"),
                "hint": "部分生效：**只对 failed 的那几项**单独重提交，别整包重发（活动会重复注入话题）。"
                        "私密笔记加合集会被平台静默丢弃，这类先把笔记转公开再加"}, 1
    if status in ("done", "partially_applied"):
        return {"outcome": "done", "job_id": job_id, "requested": requested,
                "applied": applied}, 0
    # running：轮询超时未达终态
    return {"outcome": "unknown", "job_id": job_id, "requested": requested,
            "hint": f"轮询超时仍未出终态（任务可能仍在跑）。三组件非幂等：先用 --note <note_id> "
                    f"核对实际生效情况，绝不盲目重提交"}, 0


def start_components(api_base: str, key: str, account_id: int, note_id: str,
                     requested: dict) -> str:
    """提交三组件任务，返回 job_id。**非幂等**：重复提交会重复执行，活动还会把话题重复注入正文
    （换活动会取消旧活动，但旧话题留在正文里不删、只增不减）。提交与轮询分开，是为了让调用方
    在拿到 id 的那一刻就记住它——轮询期间的任何异常都不能把已入队的任务说成「没发生」。"""
    payload = {"note_id": note_id, **requested}
    resp = send_request("POST", f"{api_base}/api/accounts/{account_id}/note-components", key, payload)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    job_id = resp.json()["job_id"]
    print(f"  已入队 job_id={job_id}", file=sys.stderr)
    return job_id


def poll_components(api_base: str, key: str, job_id: str, requested: dict, timeout: float):
    view = poll_task(api_base, key, f"{api_base}/api/note-components/{job_id}", timeout,
                     COMPONENT_TERMINAL)
    return components_result(view, job_id, requested)


def start_visibility(api_base: str, key: str, account_id: int, target_privacy: int,
                     note_id=None, title=None) -> str:
    """提交可见性切换，返回 change_id。**只支持 0 和 1**（另外三档接口未验证、不开放，传其他值 422）。
    target_privacy 必须是整数：JSON 里传 true 在服务端 pydantic 会被读成 1（=悄悄把笔记藏起来）。"""
    if target_privacy not in PRIVACY_LABELS or isinstance(target_privacy, bool):
        raise ValueError(f"target_privacy 只能是整数 0（公开可见）或 1（仅自己可见），"
                         f"收到 {target_privacy!r}；布尔值会被服务端读成 1 = 悄悄藏起来")
    payload = {"target_privacy": int(target_privacy)}
    if note_id:
        payload["note_id"] = note_id
    if title:
        payload["title"] = title
    resp = send_request("POST", f"{api_base}/api/accounts/{account_id}/note-visibility-changes",
                        key, payload)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    change_id = resp.json()["change_id"]
    print(f"  已入队 change_id={change_id}", file=sys.stderr)
    return change_id


def poll_visibility(api_base: str, key: str, change_id: str, target_privacy: int, timeout: float):
    view = poll_task(api_base, key, f"{api_base}/api/note-visibility-changes/{change_id}",
                     timeout, {"done", "error"})
    status = view.get("status")
    target = PRIVACY_LABELS[target_privacy]
    if status == "done":
        return {"outcome": "done", "change_id": change_id, "target": target}, 0
    if status == "error":
        reason = view.get("reason") or ""
        out = {"outcome": "failed", "change_id": change_id, "target": target, "reason": reason}
        out["hint"] = ("笔记定位不了（空标题或同号重复标题无法区分）——重试也不会变得可定位，改用 note_id"
                       if "note_not_locatable" in reason else
                       "切换没生效。**非幂等**：先 --note <note_id> 核对当前可见性再决定，"
                       "期间若运营已手工改回，重试会再次把它藏起来")
        return out, 1
    return {"outcome": "unknown", "change_id": change_id, "target": target,
            "hint": "结果未知（台账失效或轮询超时）。可见性切换非幂等：先用 --note <note_id> "
                    "核对当前 visibility，与目标一致就别再动手"}, 0


def start_comment(api_base: str, key: str, account_id: int, text: str,
                  title=None, publisher_user_id=None) -> str:
    """提交单篇笔记评论，返回 comment_id。**非幂等**：重复调会发出重复评论。
    服务端成功判据是回读校验（输入框清空 + 文案出现在评论列表），不是「点了发送就算成功」。
    合规：评论区不能放链接（`@` 只能提用户、`#` 是死字符、URL 只存成不可点纯文本，
    且放链接本身即违规导流特征）；矩阵号评论零引流指向。"""
    payload = {"text": text}
    if title:
        payload["title"] = title
    if publisher_user_id:
        payload["publisher_user_id"] = publisher_user_id
    resp = send_request("POST", f"{api_base}/api/accounts/{account_id}/note-comments", key, payload)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    comment_id = resp.json()["comment_id"]
    print(f"  已入队 comment_id={comment_id}", file=sys.stderr)
    return comment_id


def poll_comment(api_base: str, key: str, comment_id: str, timeout: float):
    view = poll_task(api_base, key, f"{api_base}/api/note-comments/{comment_id}",
                     timeout, {"done", "error"})
    status = view.get("status")
    if status == "done":
        return {"outcome": "done", "comment_id": comment_id}, 0
    if status == "error":
        reason = view.get("reason") or ""
        out = {"outcome": "failed", "comment_id": comment_id, "reason": reason}
        out["hint"] = ("笔记定位不了（空标题或同号重复标题无法区分）——重试也不会变得可定位"
                       if "note_not_locatable" in reason else
                       "评论没发出去。**非幂等**：重发前先人工看一眼该笔记评论区有没有已经发出去的那条")
        return out, 1
    return {"outcome": "unknown", "comment_id": comment_id,
            "hint": "结果未知（台账失效或轮询超时）。评论非幂等：先人工看该笔记评论区，"
                    "确认没发出去再考虑重发，否则会重复评论"}, 0


def trigger_idempotent(api_base: str, key: str, account_id: int, kind: str, timeout: float):
    """手工触发台账同步 / 核心目的回填。这两个**幂等**，失败可以放心重跑。"""
    paths = {"sync": ("note-ledger-syncs", "sync_id", "note-ledger-syncs"),
             "backfill": ("note-purpose-backfills", "backfill_id", "note-purpose-backfills")}
    path, id_key, poll_path = paths[kind]
    resp = send_request("POST", f"{api_base}/api/accounts/{account_id}/{path}", key)
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    task_id = resp.json()[id_key]
    print(f"  已入队 {id_key}={task_id}", file=sys.stderr)
    view = poll_task(api_base, key, f"{api_base}/api/{poll_path}/{task_id}", timeout,
                     {"done", "error"})
    status = view.get("status")
    out = {"outcome": "done" if status == "done" else
                      "failed" if status == "error" else "unknown",
           id_key: task_id, "detail": view}
    if out["outcome"] != "done":
        out["hint"] = "本操作幂等，失败或超时都可以直接重跑"
    return out, 1 if out["outcome"] == "failed" else 0


def main():
    ap = argparse.ArgumentParser(description="已发布笔记的台账查询与操作（nbdpsy-api）")
    ap.add_argument("--ledger", metavar="账号名或ID", help="台账列表：平台上当前存在哪些笔记")
    ap.add_argument("--note", metavar="NOTE_ID", help="单条详情（只有这里返回正文 content_text）")
    ap.add_argument("--collections", metavar="账号名或ID", help="列该号的合集")
    ap.add_argument("--activities", metavar="账号名或ID", help="列可关联的活动")
    ap.add_argument("--keyword", help="--activities 的筛选关键词（如 心理）")
    ap.add_argument("--set-components", action="store_true",
                    help="改已发布笔记的合集/引用/活动（非幂等；须配 --account 与 --note-id）")
    ap.add_argument("--set-visibility", action="store_true",
                    help="切换公开/仅自己可见（非幂等；须配 --account 与 --privacy）")
    ap.add_argument("--comment", action="store_true",
                    help="给单篇笔记发评论（非幂等；须配 --account 与 --text）")
    ap.add_argument("--sync-ledger", metavar="账号名或ID", help="手工触发台账同步（幂等）")
    ap.add_argument("--backfill-purpose", metavar="账号名或ID", help="手工触发核心目的回填（幂等）")
    ap.add_argument("--account", help="操作类命令的目标账号（名称或 id）")
    ap.add_argument("--note-id", help="笔记的平台 note_id（有它就用它，标题只是兜底）")
    ap.add_argument("--title", help="按标题定位（空标题或同号重复标题会 note_not_locatable）")
    ap.add_argument("--collection-id", help="--set-components：加入该合集")
    ap.add_argument("--quoted-note-id", help="--set-components：引用该笔记（限本账号内）")
    ap.add_argument("--activity-id", help="--set-components：关联该活动（会往正文追加话题）")
    ap.add_argument("--related-counselor", help="--set-components：关联咨询师姓名（驱动引用自动推导）")
    ap.add_argument("--privacy", type=int, choices=[0, 1],
                    help="--set-visibility 目标可见性：0=公开可见 / 1=仅自己可见（只开放这两档）")
    ap.add_argument("--text", help="--comment 的评论文案")
    ap.add_argument("--publisher-user-id", help="--comment 定位用（笔记发布者 user id）")
    ap.add_argument("--limit", type=int, default=50, help="--ledger 取前 N 条（默认 50，上限 200）")
    ap.add_argument("--offset", type=int, help="--ledger 分页偏移")
    ap.add_argument("--wait-timeout", type=float, default=300, help="异步任务轮询上限秒数（默认 300）")
    ap.add_argument("--api-base", help="覆盖 API 根地址")
    args = ap.parse_args()

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.XHS_API_KEY} 找管理员要「运营接入配置包」，"
              "secret import 导入后重试", file=sys.stderr)
        sys.exit(1)
    api_base = (args.api_base or nbdpsy_common.xhs_api_base()).rstrip("/")

    # 已入队的非幂等任务号——之后任何异常都不能丢它，否则 agent 会重发（重复评论/重复注入话题）
    inflight = None
    try:
        if args.ledger:
            aid, label, warn = resolve_account(api_base, key, args.ledger)
            view = ledger(api_base, key, aid, args.limit, args.offset)
            view["account"] = {"id": aid, "name": label}
            if warn:
                view["warning"] = warn
            print(json.dumps(view, ensure_ascii=False))
            return
        if args.note:
            print(json.dumps(note_detail(api_base, key, args.note), ensure_ascii=False))
            return
        if args.collections:
            aid, label, _ = resolve_account(api_base, key, args.collections)
            view = collections(api_base, key, aid)
            view = view if isinstance(view, dict) else {"collections": view}
            view["account"] = {"id": aid, "name": label}
            print(json.dumps(view, ensure_ascii=False))
            return
        if args.activities:
            aid, label, _ = resolve_account(api_base, key, args.activities)
            view = activities(api_base, key, aid, args.keyword)
            view = view if isinstance(view, dict) else {"activities": view}
            view["account"] = {"id": aid, "name": label}
            print(json.dumps(view, ensure_ascii=False))
            return
        if args.sync_ledger or args.backfill_purpose:
            target = args.sync_ledger or args.backfill_purpose
            kind = "sync" if args.sync_ledger else "backfill"
            aid, label, warn = resolve_account(api_base, key, target)
            if warn:
                print(f"⚠ {warn}", file=sys.stderr)
            out, code = trigger_idempotent(api_base, key, aid, kind, args.wait_timeout)
            out["account"] = {"id": aid, "name": label}
            print(json.dumps(out, ensure_ascii=False))
            sys.exit(code)

        if args.set_components:
            if not args.account or not args.note_id:
                ap.error("--set-components 需要 --account 与 --note-id（组件操作只按 note_id 定位）")
            requested = {k: v for k, v in (
                ("collection_id", args.collection_id), ("quoted_note_id", args.quoted_note_id),
                ("activity_id", args.activity_id), ("related_counselor", args.related_counselor),
            ) if v not in (None, "")}
            if not requested:
                ap.error("--set-components 至少要给一项：--collection-id / --quoted-note-id / "
                         "--activity-id / --related-counselor")
            if args.activity_id:
                print("⚠ 关联活动会往正文末尾追加活动话题并真的发出去；换活动会取消旧活动但"
                      "旧话题留在正文里不删——别反复切换活动", file=sys.stderr)
            aid, label, warn = resolve_account(api_base, key, args.account)
            if warn:
                print(f"⚠ {warn}", file=sys.stderr)
            job_id = start_components(api_base, key, aid, args.note_id, requested)
            inflight = ("job_id", job_id)  # 入队即记住：轮询期的任何异常都不能说成「没发生」
            out, code = poll_components(api_base, key, job_id, requested, args.wait_timeout)
            out["account"] = {"id": aid, "name": label}
            print(json.dumps(out, ensure_ascii=False))
            sys.exit(code)

        if args.set_visibility:
            if not args.account or args.privacy is None:
                ap.error("--set-visibility 需要 --account 与 --privacy 0|1")
            if not args.note_id and not args.title:
                ap.error("--set-visibility 需要 --note-id 或 --title 定位笔记")
            aid, label, warn = resolve_account(api_base, key, args.account)
            if warn:
                print(f"⚠ {warn}", file=sys.stderr)
            change_id = start_visibility(api_base, key, aid, args.privacy,
                                         args.note_id, args.title)
            inflight = ("change_id", change_id)
            out, code = poll_visibility(api_base, key, change_id, args.privacy, args.wait_timeout)
            out["account"] = {"id": aid, "name": label}
            print(json.dumps(out, ensure_ascii=False))
            sys.exit(code)

        if args.comment:
            if not args.account or not args.text:
                ap.error("--comment 需要 --account 与 --text")
            if not args.title and not args.publisher_user_id:
                ap.error("--comment 需要 --title 或 --publisher-user-id 定位笔记")
            aid, label, warn = resolve_account(api_base, key, args.account)
            if warn:
                print(f"⚠ {warn}", file=sys.stderr)
            comment_id = start_comment(api_base, key, aid, args.text, args.title,
                                       args.publisher_user_id)
            inflight = ("comment_id", comment_id)
            out, code = poll_comment(api_base, key, comment_id, args.wait_timeout)
            out["account"] = {"id": aid, "name": label}
            print(json.dumps(out, ensure_ascii=False))
            sys.exit(code)

        ap.error("没给要做什么：--ledger / --note / --collections / --activities / "
                 "--set-components / --set-visibility / --comment / --sync-ledger / --backfill-purpose")

    except Exception as e:
        msg = sandbox_hint(e)
        print(f"  → 出错: {msg}", file=sys.stderr)
        if inflight:
            # 任务已在服务端入队且不依赖本地连接——非幂等操作绝不落 failed（那会诱导 agent 重发）
            id_key, task_id = inflight
            print(json.dumps({
                "outcome": "unknown", id_key: task_id, "error": msg,
                "hint": "任务可能已在服务端执行（不依赖本地连接）。本操作非幂等：先用 "
                        "--note <note_id> 或人工看笔记核对当前实际状态，再决定要不要重来",
            }, ensure_ascii=False))
            sys.exit(0)
        print(json.dumps({"outcome": "failed", "error": msg}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()

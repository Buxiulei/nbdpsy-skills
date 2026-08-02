#!/usr/bin/env python3
"""服务号定时任务：定时发布 / 定时群发（高危）/ 查队列 / 撤销。

微信 API **没有原生定时参数**——定时全靠服务端队列（每分钟扫一次，到点执行）。
所以「这条到底排上没有」的唯一权威是 `--list`，⛔ 不是公众平台后台，也不是对话记忆。

用法:
    # 定时发布（到点发布：文章上线可搜到，但**不推送粉丝、不占群发次数**）
    python3 schedule_ops.py --submit-publish <media_id> --at "2026-08-03T09:00:00+08:00"

    # 定时群发（高危：不可逆 + 每自然月仅 4 次；到点直接推送给全部粉丝）
    python3 schedule_ops.py --submit-mass <media_id> --at "..."            # 只查配额，**零入队**
    python3 schedule_ops.py --submit-mass <media_id> --at "..." --confirm \\
        --note "运营张三确认，8月推送第2条"

    # 队列
    python3 schedule_ops.py --list [--status pending]
    python3 schedule_ops.py --cancel <队列 id>          # 只有还没到点的（pending）能撤

输出（stdout 纯 JSON；人话警示走 stderr）:
    --list                查询视图 + 人话状态，exit 0。
    提交 / 撤销            `{"outcome":"done|failed|unknown", ...}`：done exit 0；failed exit 1；
                          **unknown exit 0**——结果未确认，先 `--list` 核实，⛔ 绝不直接重提交
                          （重复入队 = 到点发两次）。两桶口径见 wechat_api.py。
    `--submit-mass` 不带 `--confirm` 一律 failed exit 1：那不是故障，是「本次没入队」的闸门。

两条红线在本脚本里的落点:
  · **红线①**（群发不可逆 + 每自然月仅 4 次）：定时群发**同样占配额**。不带 `--confirm` 时
    **一条队列都不入**，只查本月配额现状；真入队必须带 `--note`（谁拍板的问责留痕）。
    服务端入队时校验一次配额，到点执行前再校验一次。
  · **run_at 必须带时区**：不带时区的时间串服务端按 UTC 解析，会比运营想的**早 8 小时**发出去。
    所以本脚本在本地就拒收无时区输入，并把补好 `+08:00` 的完整串给出来。
    提交成功后回执里的 `run_at_label` 是「几月几号周几几点（北京时间）」——
    **原样念给运营核对**，run_at 写错一天是这条线上最常见的事故。

凭据: NBDPSY_WECHAT_API_KEY；基址默认 database.nbdpsy.com，可用 --api-base 覆盖。
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import wechat_api
from wechat_api import OpFailed, OpUnknown

# 北京时间。中国自 1991 年起不再实行夏令时，固定 +08:00 恒成立，
# 故不用 zoneinfo（Windows 上没装 tzdata 会直接抛 ZoneInfoNotFoundError）。
CN_TZ = timezone(timedelta(hours=8))
WEEKDAYS = "一二三四五六日"

# 队列每分钟扫一次：排在这个窗口内的时间点很可能刚好错过本轮
NEAR_FUTURE = timedelta(minutes=2)

JOB_STATUS_LABELS = {
    "pending": "待执行（还没到点，可以 --cancel 撤）",
    "running": "执行中（已经开始跑了，撤不掉）",
    "done": "已执行完成（看 result）",
    "failed": "执行失败（看 fail_reason）",
    "cancelled": "已取消（不会再执行）",
}
JOB_TYPE_LABELS = {
    "publish": "定时发布（到点上线，不推送粉丝、不占群发次数）",
    "mass_send": "定时群发（到点**推送给全部粉丝**，占用当月 4 次配额之一，不可逆）",
}

# 与 article_ops.py 同源的配额话术：复述配额时**必须**把这句一并说出来
QUOTA_CAVEAT = ("台账的月计数**只统计经本系统发的**：运营若在公众平台后台手动群发过，"
                "实际剩余次数可能更少——复述配额时必须把这句一并说出来，"
                "别让运营以为 4 次是精确保证。")

SUBMIT_UNKNOWN_HINT = ("结果未确认：这条定时任务**可能已经入队了**。① 先 `schedule_ops.py --list` "
                       "看队列里有没有它（对一遍 run_at 与 media_id）；② 确认**确实没有**再重提交；"
                       "⛔ 绝不直接重跑同一条命令——重复入队会到点发两次。")


# ── 时间 ────────────────────────────────────────────────────────────────
def label(dt: datetime) -> str:
    """按北京时间讲人话。日期和星期都念出来——run_at 写错一天是这条线上最常见的事故。"""
    local = dt.astimezone(CN_TZ)
    return (f"{local.year}年{local.month}月{local.day}日（周{WEEKDAYS[local.weekday()]}）"
            f"{local:%H:%M}（北京时间）")


def parse_iso(raw):
    """宽松解析 RFC3339 / ISO 8601，解析不出来回 None（用于展示服务端回的时间，不做闸门）。"""
    text = (raw or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_run_at(raw):
    """把 --at 的时间串解析成**带时区**的 datetime。无时区一律拒收。

    为什么必须带时区：服务端按 RFC3339 解析，裸 `2026-08-03 09:00` 会被当成 UTC，
    真正发出去的时刻比运营想的**早 8 小时**（8 月 3 日凌晨 1 点）。这种错发出去就收不回来，
    所以在本地就挡住，并把补好 `+08:00` 的完整串直接给出来。
    """
    text = (raw or "").strip()
    if not text:
        raise OpFailed('缺时间：请给 `--at "2026-08-03T09:00:00+08:00"`（北京时间 8 月 3 日上午 9 点）。')
    dt = parse_iso(text)
    if dt is None:
        raise OpFailed(f"看不懂的时间「{text}」——要 RFC3339 形状且**带时区**，"
                       '例如 `--at "2026-08-03T09:00:00+08:00"`（北京时间 8 月 3 日上午 9 点）。')
    if dt.tzinfo is None:
        fixed = dt.replace(tzinfo=CN_TZ).isoformat()
        raise OpFailed(f"时间「{text}」**没带时区**——服务端会当成 UTC 解析，"
                       f"实际发出时刻比你想的**早 8 小时**。北京时间请写成 `--at \"{fixed}\"`。")
    return dt


def resolve_run_at(raw):
    """解析 + 过去时刻本地先拒，返回 (datetime, warnings)。坏时间不浪费一次请求。"""
    dt = parse_run_at(raw)
    now = datetime.now(timezone.utc)
    if dt <= now:
        raise OpFailed(f"这个时间已经过去了：{label(dt)}，现在是 {label(now)}。"
                       "定时任务只能排在未来——是不是年份/月份写错了，或者忘了改成明天？"
                       "（要立刻发请用 `article_ops.py --publish`，别把定时任务当立即执行使。）")
    warnings = []
    if dt - now < NEAR_FUTURE:
        warnings.append(f"离现在只有 {int((dt - now).total_seconds())} 秒：队列每分钟扫一次，"
                        "可能刚好错过这一轮，实际执行会晚 1 分钟左右。")
    return dt, warnings


# ── 提交 ────────────────────────────────────────────────────────────────
def submit_job(api_base, key, body, timeout):
    """入队一条定时任务。**不可逆动作**：请求发出后结果不明时绝不能报 failed 诱导重提交
    ——重复入队会到点发两次，群发型还要多烧一次月配额。
    """
    try:
        return wechat_api.request_json("POST", f"{api_base}/api/external/wechat/schedule", key,
                                       body, timeout, irreversible=True)
    except OpUnknown as e:
        # 只改通用那句处置提示（查队列而不是查台账）；45028 那类专属 hint 是钉死的，不能动
        if e.hint == wechat_api.UNKNOWN_HINT:
            e.hint = SUBMIT_UNKNOWN_HINT
        raise


def job_id_of(data):
    """服务端回的队列 id。字段名 T15 联调时收紧，这里两种都认，拿不到就如实回 None。"""
    for field in ("job_id", "id"):
        if data.get(field) is not None:
            return data.get(field)
    return None


def submitted(data, job_type, media_id, run_at, warnings, extra_hint):
    job_id = job_id_of(data)
    cancel = f"`--cancel {job_id}`" if job_id is not None else "`--list` 找到 id 再 `--cancel <id>`"
    return {"outcome": "done", "job_id": job_id, "job_type": job_type,
            "job_type_label": JOB_TYPE_LABELS.get(job_type, job_type),
            "media_id": media_id, "run_at": run_at.isoformat(), "run_at_label": label(run_at),
            "warnings": warnings,
            "server": {k: v for k, v in data.items() if k != "success"},
            "hint": f"已排进队列。**把时间原样念给运营核对**：{label(run_at)}"
                    f"——run_at 写错一天是这条线上最常见的事故。{extra_hint}"
                    f"到点前要反悔：{cancel}（只有还没执行的能撤）。"}, 0


def do_submit_publish(args, api_base, key):
    media_id = (args.submit_publish or "").strip()
    if not media_id:
        raise OpFailed("--submit-publish 需要 media_id（`article_ops.py --draft-add` 回的那个）。")
    run_at, warnings = resolve_run_at(args.at)
    data = submit_job(api_base, key,
                      {"job_type": "publish", "run_at": run_at.isoformat(),
                       "payload": {"media_id": media_id}}, args.timeout)
    return submitted(data, "publish", media_id, run_at, warnings,
                     "本次是**发布**（freepublish）：到点文章上线、可被搜到，"
                     "但**不推送粉丝、不占群发次数**；到点后几分钟用 "
                     "`article_ops.py --ledger` 查终态与链接。")


def do_submit_mass(args, api_base, key):
    media_id = (args.submit_mass or "").strip()
    if not media_id:
        raise OpFailed("--submit-mass 需要 media_id（`article_ops.py --draft-add` 回的那个）。")
    run_at, warnings = resolve_run_at(args.at)      # 时间先过闸：坏时间连一次请求都不该发

    if not args.confirm:
        # 红线警示**先打**：下面那次配额查询万一失败，这几条也照样得让运营看见
        wechat_api.warn("⚠ 这次**没有入队任何定时任务**（缺 --confirm），只查了本月配额。")
        wechat_api.warn(f"  · 到点（{label(run_at)}）会**直接推送到每个粉丝的对话框**，且**不可逆**。")
        wechat_api.warn("  · 群发**每自然月只有 4 次**，定时群发同样占配额。")
        wechat_api.warn(f"  · {QUOTA_CAVEAT}")
        # 配额现状走 mass-send 的预检（confirm≠true 时服务端**不发**，只回配额），本身是只读的
        data = wechat_api.request_json("POST", f"{api_base}/api/external/wechat/mass-send", key,
                                       {"media_id": media_id, "confirm": False}, args.timeout)
        return {"outcome": "failed",
                "error": "未带 --confirm：本次**没有入队**，只查了本月配额"
                         "（这是安全闸门，不是故障）。",
                "media_id": media_id, "run_at": run_at.isoformat(), "run_at_label": label(run_at),
                "warnings": warnings,
                "server": {k: v for k, v in data.items() if k != "success"},
                "hint": "把本月配额现状复述给运营（「本月已用 X/4 次，这条到点发出去就是第 X+1 次」）"
                        f"、把执行时间 {label(run_at)} 一并念一遍，拿到明确确认后，再带 "
                        f"`--confirm --note \"谁在什么场景下拍的板\"` 重跑。{QUOTA_CAVEAT}"}, 1

    note = (args.note or "").strip()
    if not note:
        raise OpFailed("--submit-mass --confirm 必须带 --note：这是**问责留痕**——"
                       "写清是谁在什么场景下拍的板（如 \"运营张三确认，8月推送第2条\"）。")
    data = submit_job(api_base, key,
                      {"job_type": "mass_send", "run_at": run_at.isoformat(),
                       "payload": {"media_id": media_id}, "confirm": True, "note": note},
                      args.timeout)
    payload, code = submitted(data, "mass_send", media_id, run_at, warnings,
                              "本次是**群发**：到点直接推送给全部粉丝、不可逆，"
                              f"当月 4 次配额到点时扣一次（服务端执行前会再校验一次配额）。{QUOTA_CAVEAT}")
    payload["note"] = note
    return payload, code


# ── 队列查询 / 撤销 ──────────────────────────────────────────────────────
def job_view(row):
    """给队列行补人话：状态、执行时刻（北京时间）、还撤不撤得掉。"""
    row["status_label"] = JOB_STATUS_LABELS.get(row.get("status"),
                                                f"未收录的状态「{row.get('status')}」")
    row["job_type_label"] = JOB_TYPE_LABELS.get(row.get("job_type"), row.get("job_type"))
    run_at = parse_iso(row.get("run_at"))
    row["run_at_label"] = label(run_at) if run_at else None
    row["can_cancel"] = row.get("status") == "pending"
    return row


def do_list(args, api_base, key):
    qs = f"?{urlencode({'status': args.status})}" if args.status else ""
    data = wechat_api.request_json("GET", f"{api_base}/api/external/wechat/schedule{qs}",
                                   key, None, args.timeout)
    items = [job_view(row) for row in (data.get("items") or []) if isinstance(row, dict)]
    by_status = {}
    for row in items:
        by_status[row.get("status")] = by_status.get(row.get("status"), 0) + 1
    view = dict(data)
    view["items"] = items
    # 只统计本次返回的这些行；服务端若带了顶层 total，那是全量条数，别混为一谈
    view["counts"] = {"in_page": len(items), "by_status": by_status,
                      "mass_send": sum(1 for r in items if r.get("job_type") == "mass_send")}
    view["note"] = ("队列是「到底排上没有」的唯一权威——微信没有原生定时功能，"
                    "公众平台后台看不到这些任务。run_at_label 是北京时间，念给运营核对。")
    return view, 0


def do_cancel(args, api_base, key):
    try:
        data = wechat_api.request_json("POST", f"{api_base}/api/external/wechat/schedule/cancel",
                                       key, {"id": args.cancel}, args.timeout)
    except OpFailed as e:
        # 服务端约定：只有 pending 能撤，撤不到行回 409。这里把它翻成运营能处置的人话。
        if e.error.startswith("HTTP 409"):
            raise OpFailed(
                f"撤不掉 id={args.cancel}：**只有还没到点的（pending）能撤**。可能是"
                "①已经到点执行了 ②已经过期 ③上一次取消其实已经成功了（网络报错但服务端已处理）。"
                "先 `--list` 看它现在是什么 status；若是群发且已经执行，"
                "推送收不回来、配额也已经花掉，按红线②（改＝删+重发，换链接、数据清零）"
                "跟运营把代价讲清楚。", **e.extra) from e
        raise
    return {"outcome": "done", "job_id": args.cancel,
            "server": {k: v for k, v in data.items() if k != "success"},
            "hint": "已取消，到点不会再执行。用 `--list` 复核一眼它现在是 cancelled。"}, 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="服务号定时任务：定时发布 / 定时群发 / 队列 / 撤销")
    ap.add_argument("--submit-publish", dest="submit_publish", metavar="media_id",
                    help="提交定时发布（不推送粉丝、不占群发次数）")
    ap.add_argument("--submit-mass", dest="submit_mass", metavar="media_id",
                    help="提交定时群发（高危：不可逆 + 每自然月仅 4 次）")
    ap.add_argument("--list", action="store_true", help="查定时队列")
    ap.add_argument("--cancel", type=int, metavar="队列id", help="撤销定时任务（只有 pending 能撤）")

    ap.add_argument("--at", "--run-at", dest="at", metavar="时间",
                    help='执行时刻，**必须带时区**，如 "2026-08-03T09:00:00+08:00"')
    ap.add_argument("--status", help="--list 的过滤：pending/running/done/failed/cancelled")
    ap.add_argument("--note", help="--submit-mass --confirm 的问责留痕：谁在什么场景下拍的板")
    ap.add_argument("--confirm", action="store_true",
                    help="真正入队定时群发；不带它只查配额、一条都不入")
    ap.add_argument("--api-base", dest="api_base", help="覆盖服务基址（默认走凭据/内置默认）")
    ap.add_argument("--timeout", type=float, default=wechat_api.DEFAULT_TIMEOUT, help="单次请求超时秒数")
    args = ap.parse_args(argv)

    actions = [(args.submit_publish, do_submit_publish), (args.submit_mass, do_submit_mass),
               (args.list, do_list), (args.cancel is not None, do_cancel)]
    chosen = [fn for flag, fn in actions if flag]
    if len(chosen) != 1:
        ap.error("四选一：--submit-publish <media_id> --at <时间> / --submit-mass <media_id> --at <时间> / "
                 "--list / --cancel <id>")

    def action():
        api_base, key = wechat_api.credentials(args.api_base)
        return chosen[0](args, api_base, key)

    return wechat_api.run(action)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""服务号数据：涨粉/阅读概况 / 单篇逐日曲线 / 原始快照导出。

查的是**服务端每日快照**（每天 08:30 抓前一天），所以**可以跨任意区间**——微信 datacube
原生接口跨度上限 1~30 天不等，快照把这条限制兜住了。

两件必须跟运营说清楚、脚本也会写进 `warnings` 的事:
  · **当天数据查不到是正常的**：微信 T+1，次日 8 点后才稳。运营问「今天发的怎么样」→
    如实说「明天才有数据」，⛔ 别拿别的指标凑数糊弄过去。
  · **新口径数据只有 2025-11-01 起**的，更早的区间根本没有快照，不是故障。

用法:
    python3 stats_ops.py --overview --from 2026-07-01 --to 2026-07-31   # 涨粉 + 全号阅读概况
    python3 stats_ops.py --article <msgid> [--from ... --to ...]        # 单篇逐日序列 + 转化率
    python3 stats_ops.py --export --from ... --to ... [--stat-type ...] [--out 文件.json]

输出: stdout 纯 JSON（查询类不带 outcome，exit 0；`--export` 是写文件，回 done 信封）。
      `warnings` 同时也打到 stderr——这几条正是最容易被略过、又最容易让运营误判的地方。

⛔ **缺字段绝不报 0**：某个指标在这段区间的快照里一次都没出现时，值给 `null` 并在 warnings 里
点名（可能是区间早于数据起点、快照任务刚上线、或服务端换了字段名）。把「查不到」说成「0 涨粉」
是这条线上最容易造成误判的错，宁可说不知道。

凭据: NBDPSY_WECHAT_API_KEY；基址默认 database.nbdpsy.com，可用 --api-base 覆盖。
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import nbdpsy_common
import wechat_api
from wechat_api import OpFailed

CN_TZ = timezone(timedelta(hours=8))     # 北京时间固定 +08:00（1991 年起无夏令时）
DATA_START = date(2025, 11, 1)           # 新口径数据起点，更早的区间没有快照
SNAPSHOT_AT = "08:30"                    # 服务端每日快照时刻（抓前一天）

# 快照 stat_type（与服务端每日快照任务落库的取值一致）
TYPE_USER = "getusersummary"             # 用户增减：new_user / cancel_user
TYPE_CUMULATE = "getusercumulate"        # 累计关注
TYPE_BIZ = "getbizsummary"               # 全号图文阅读/分享汇总
TYPE_ARTICLE_READ = "getarticleread"
TYPE_ARTICLE_SHARE = "getarticleshare"
TYPE_ARTICLE_DETAIL = "getarticletotaldetail"   # 单篇逐日明细
ALL_TYPES = (TYPE_USER, TYPE_CUMULATE, TYPE_BIZ,
             TYPE_ARTICLE_READ, TYPE_ARTICLE_SHARE, TYPE_ARTICLE_DETAIL)

# 微信 datacube 字段 → 人话。**不在这张表里的数值字段照样汇总**（放进 other_fields），
# 微信加字段时不至于静默漏掉，只是没有中文名。
FIELD_LABELS = {
    "new_user": "新增关注人数", "cancel_user": "取消关注人数", "cumulate_user": "累计关注人数",
    "int_page_read_user": "图文页阅读人数", "int_page_read_count": "图文页阅读次数",
    "ori_page_read_user": "原文页阅读人数", "ori_page_read_count": "原文页阅读次数",
    "share_user": "分享转发人数", "share_count": "分享转发次数",
    "add_to_fav_user": "收藏人数", "add_to_fav_count": "收藏次数",
    "target_user": "送达人数",
}
# 维度/标识字段：它们不可加，求和出来是垃圾数（user_source 尤其典型——它是来源枚举值不是人数）
NON_METRIC = {"ref_date", "stat_date", "msgid", "user_source", "title", "stat_type",
              "publish_date", "is_delay", "index", "id"}

# 概况关心的字段（缺了要点名，不能当 0）
FOLLOWER_FIELDS = ("new_user", "cancel_user")
ENGAGEMENT_FIELDS = ("int_page_read_user", "int_page_read_count", "ori_page_read_user",
                     "ori_page_read_count", "share_user", "share_count",
                     "add_to_fav_user", "add_to_fav_count")

MAX_DAILY_ROWS = 62      # 逐日明细超过这个天数就省略：糊满几百行对判断没有帮助

# 微信 datacube **没有**「读完率/完读率」这个字段。公众平台后台那个数取不到，
# 这里只给数据算得出来的转化率，并且明说它不是读完率——冒充一个不存在的指标是最坏的糊弄。
NO_FINISH_RATE = ("微信 datacube 接口**不提供**「读完率/完读率」（公众平台后台看到的那个数取不到）。"
                  "下面 rates 给的是能算出来的转化率：送达→阅读、阅读→点开原文、阅读→分享。"
                  "⛔ 别把它们当读完率报给运营。")


# ── 纯计算（不碰网络，单测直接喂 rows） ──────────────────────────────────
def iter_records(rows):
    """快照行 → 逐条记录 `(快照日期, 记录 dict)`。

    payload 的形状以服务端快照任务落库为准，这里把几种都收下：
    `{"list":[...]}`（datacube 原始响应）/ `{"details":[...]}`（单篇总数据）/ 裸数组 / 单条 dict。
    真出现认不出来的形状时，结果是「有快照行但一个字段都没汇总到」——调用方据此报
    「有 N 行快照却找不到字段」的警告，**不会静默变成 0**。
    """
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload")
        if isinstance(payload, dict):
            items = payload.get("list") or payload.get("details") or [payload]
        elif isinstance(payload, list):
            items = payload
        else:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                yield row.get("ref_date"), item


def add_metrics(bucket: dict, item: dict):
    """把一条记录里的数值字段累加进 bucket（跳过维度字段与布尔值）。"""
    for k, v in item.items():
        if k in NON_METRIC or isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        bucket[k] = bucket.get(k, 0) + v
    return bucket


def daily_totals(rows):
    """按日期汇总：`{日期: {字段: 合计}}`。日期优先取记录自带的 stat_date/ref_date。"""
    out = {}
    for ref_date, item in iter_records(rows):
        day = item.get("stat_date") or item.get("ref_date") or ref_date
        add_metrics(out.setdefault(day, {}), item)
    return out


def sum_all(daily: dict):
    """逐日合计再汇总成区间合计。**一次都没出现过的字段不会出现在结果里**——
    调用方据此区分「0」和「查不到」，绝不把缺字段填成 0。"""
    total = {}
    for bucket in daily.values():
        for k, v in bucket.items():
            total[k] = total.get(k, 0) + v
    return total


def latest_series(rows):
    """单篇逐日序列：按 stat_date 去重，**同一天以更新的快照为准**。

    getarticletotal 每天回的是这篇文章**整段历史**（后一天的快照会修订前几天的数字），
    照单全收会把同一天的阅读数重复累加成好几倍。
    """
    series = {}
    for ref_date, item in sorted(iter_records(rows), key=lambda x: str(x[0] or "")):
        day = item.get("stat_date") or item.get("ref_date") or ref_date
        series[day] = dict(item, stat_date=day)
    return [series[day] for day in sorted(series, key=str)]


def pick(totals: dict, fields):
    """取出关心的字段：**缺的给 None 不给 0**。返回 (值字典, 缺席字段列表)。"""
    picked, missing = {}, []
    for f in fields:
        if f in totals:
            picked[f] = totals[f]
        else:
            picked[f] = None
            missing.append(f)
    return picked, missing


def ratio(numerator, denominator):
    """转化率：分子分母任一缺席或分母为 0 时回 None，绝不拿 0 顶数。"""
    if not isinstance(numerator, (int, float)) or not isinstance(denominator, (int, float)):
        return None
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def labels_for(*dicts):
    """本次输出里出现过的字段的中文名（只放出现过的，免得糊一大张表）。"""
    out = {}
    for d in dicts:
        for k in d or {}:
            if k in FIELD_LABELS:
                out[k] = FIELD_LABELS[k]
    return out


def other_fields(totals: dict, known):
    """已知字段之外的数值合计原样带出：微信加字段时不至于被静默吞掉。"""
    return {k: v for k, v in totals.items() if k not in known}


def missing_warning(missing, stat_type, row_count):
    if not missing:
        return None
    names = "、".join(f"{FIELD_LABELS.get(f, f)}（{f}）" for f in missing)
    if not row_count:
        return (f"这段区间里 `{stat_type}` **一行快照都没有**，所以 {names} 给的是 null 而不是 0："
                f"可能区间早于数据起点 {DATA_START}、也可能服务端快照任务还没跑到这段。"
                "⛔ 别当成「没涨粉/没人看」报给运营。")
    return (f"`{stat_type}` 有 {row_count} 行快照，但里面找不到 {names}——值给的是 null 不是 0，"
            "多半是服务端换了字段名。⛔ 别当成 0 报给运营，先找开发核对。")


# ── 区间与日期 ──────────────────────────────────────────────────────────
def parse_date(raw, flag):
    try:
        return date.fromisoformat((raw or "").strip())
    except (ValueError, AttributeError):
        raise OpFailed(f"{flag} 要 `YYYY-MM-DD` 形状的日期（你给的是「{raw}」）。")


def require_range(args, who):
    if not args.date_from or not args.date_to:
        raise OpFailed(f"{who} 需要 `--from YYYY-MM-DD --to YYYY-MM-DD`。"
                       "查的是服务端每日快照，**跨任意区间都可以**（不受微信 1~30 天跨度限制）。")
    d_from, d_to = parse_date(args.date_from, "--from"), parse_date(args.date_to, "--to")
    if d_from > d_to:
        raise OpFailed(f"--from（{d_from}）比 --to（{d_to}）还晚，是不是写反了？")
    return d_from, d_to


def range_warnings(d_from, d_to):
    """把「查不到不是故障」的两种情形提前说清楚。"""
    out = []
    now = datetime.now(CN_TZ)
    today = now.date()
    if d_from < DATA_START:
        out.append(f"新口径数据只有 {DATA_START} 起的：{d_from} 到 {DATA_START} 这段**根本没有快照**，"
                   "查不到不是故障。")
    if d_to >= today:
        out.append(f"区间含今天（{today}）：微信数据 **T+1**，今天的要等明天 {SNAPSHOT_AT} 快照抓完才有。"
                   "运营问「今天发的怎么样」→ 如实说明天才有数据，⛔ 别拿别的指标凑数。")
    elif d_to == today - timedelta(days=1) and now.strftime("%H:%M") < SNAPSHOT_AT:
        out.append(f"区间到昨天（{d_to}）：快照每天 {SNAPSHOT_AT} 抓前一天，现在 "
                   f"{now:%H:%M} 还没抓，昨天的数据可能要过一会儿才有。")
    return out


# ── 取数 ────────────────────────────────────────────────────────────────
def fetch_stats(api_base, key, stat_type, timeout, d_from=None, d_to=None, msgid=None):
    """查快照端点。纯读操作——5xx 如实报失败让运营直接重试，没有「可能已生效」的风险。"""
    params = {"stat_type": stat_type}
    if d_from:
        params["from"] = str(d_from)
    if d_to:
        params["to"] = str(d_to)
    if msgid:
        params["msgid"] = msgid
    data = wechat_api.request_json("GET",
                                   f"{api_base}/api/external/wechat/stats?{urlencode(params)}",
                                   key, None, timeout)
    return data.get("items") or []


# ── --overview ─────────────────────────────────────────────────────────
def do_overview(args, api_base, key):
    d_from, d_to = require_range(args, "--overview")
    warnings = range_warnings(d_from, d_to)

    user_rows = fetch_stats(api_base, key, TYPE_USER, args.timeout, d_from, d_to)
    biz_rows = fetch_stats(api_base, key, TYPE_BIZ, args.timeout, d_from, d_to)

    user_daily, biz_daily = daily_totals(user_rows), daily_totals(biz_rows)
    user_total, biz_total = sum_all(user_daily), sum_all(biz_daily)

    followers, missing_f = pick(user_total, FOLLOWER_FIELDS)
    engagement, missing_e = pick(biz_total, ENGAGEMENT_FIELDS)
    for w in (missing_warning(missing_f, TYPE_USER, len(user_rows)),
              missing_warning(missing_e, TYPE_BIZ, len(biz_rows))):
        if w:
            warnings.append(w)

    # 净增：任一侧缺席就给 null——拿 0 去减会算出一个看着很确定的假数
    followers["net_user"] = (None if followers["new_user"] is None or followers["cancel_user"] is None
                             else followers["new_user"] - followers["cancel_user"])

    days = (d_to - d_from).days + 1
    daily = None
    daily_note = None
    if days <= MAX_DAILY_ROWS:
        merged = {}
        # 两类快照按日期并到一行：涨粉字段与阅读字段不重名，真重名时以阅读侧为准
        for day in sorted(set(user_daily) | set(biz_daily), key=str):
            row = {"ref_date": day}
            row.update(user_daily.get(day, {}))
            row.update(biz_daily.get(day, {}))
            if "new_user" in row and "cancel_user" in row:
                row["net_user"] = row["new_user"] - row["cancel_user"]
            merged[day] = row
        daily = list(merged.values())
    else:
        daily_note = (f"区间 {days} 天超过 {MAX_DAILY_ROWS} 天，已省略逐日明细（只给合计）——"
                      "要明细请缩小区间，或用 `--export` 落文件慢慢看。")

    payload = {
        "range": {"from": str(d_from), "to": str(d_to), "days": days},
        "followers": followers,
        "engagement": engagement,
        "other_fields": {TYPE_USER: other_fields(user_total, FOLLOWER_FIELDS),
                         TYPE_BIZ: other_fields(biz_total, ENGAGEMENT_FIELDS)},
        "labels": labels_for(followers, engagement),
        "daily": daily, "daily_note": daily_note,
        "snapshot_rows": {TYPE_USER: len(user_rows), TYPE_BIZ: len(biz_rows)},
        "warnings": warnings,
        "hint": "数据来自服务端每日快照（每天 "
                f"{SNAPSHOT_AT} 抓前一天），跨任意区间都能查。null 表示**这段区间里没有这个字段**"
                "，不是 0。单篇表现看 `--article <msgid>`。",
    }
    return payload, 0


# ── --article ──────────────────────────────────────────────────────────
def article_title(rows):
    for row in rows:
        payload = row.get("payload") if isinstance(row, dict) else None
        if isinstance(payload, dict) and payload.get("title"):
            return payload["title"]
    return None


def do_article(args, api_base, key):
    msgid = (args.article or "").strip()
    if not msgid:
        raise OpFailed("--article 需要 msgid（群发消息 id，`article_ops.py --ledger` 里那条的 msg_id）。")
    d_from = parse_date(args.date_from, "--from") if args.date_from else None
    d_to = parse_date(args.date_to, "--to") if args.date_to else None
    if d_from and d_to and d_from > d_to:
        raise OpFailed(f"--from（{d_from}）比 --to（{d_to}）还晚，是不是写反了？")
    warnings = range_warnings(d_from, d_to) if (d_from and d_to) else []

    rows = fetch_stats(api_base, key, TYPE_ARTICLE_DETAIL, args.timeout, d_from, d_to, msgid)
    series = latest_series(rows)
    totals = {}
    for item in series:
        add_metrics(totals, item)

    if not rows:
        warnings.append(f"msgid={msgid} 一行快照都没有：可能这篇**没有群发过**（只发布不群发的文章"
                        "没有单篇群发数据）、msgid 写错了、或者才发出去不到一天（微信 T+1）。"
                        "⛔ 别把「查不到」说成「没人看」。")

    known = ("target_user", "int_page_read_user", "int_page_read_count",
             "ori_page_read_user", "ori_page_read_count", "share_user", "share_count",
             "add_to_fav_user", "add_to_fav_count")
    picked, missing = pick(totals, known)
    rates = {
        "送达→阅读（人数）": ratio(picked["int_page_read_user"], picked["target_user"]),
        "阅读→点开原文（人数）": ratio(picked["ori_page_read_user"], picked["int_page_read_user"]),
        "阅读→分享（人数）": ratio(picked["share_user"], picked["int_page_read_user"]),
    }
    warnings.append(NO_FINISH_RATE)
    if rows and missing:
        warnings.append(missing_warning(missing, TYPE_ARTICLE_DETAIL, len(rows)))

    payload = {
        "msgid": msgid, "title": article_title(rows),
        "range": {"from": str(d_from) if d_from else None, "to": str(d_to) if d_to else None},
        "totals": picked, "rates": rates,
        "other_fields": other_fields(totals, known),
        "labels": labels_for(picked),
        "daily": series, "days_covered": len(series), "snapshot_rows": len(rows),
        "warnings": warnings,
        "hint": "daily 是这篇的逐日序列（同一天以最新一次快照为准——微信每天回的是整段历史，"
                "照单累加会把同一天算好几遍）。totals 是逐日相加的区间合计。",
    }
    return payload, 0


# ── --export ───────────────────────────────────────────────────────────
def export_path(args, d_from, d_to):
    if args.out:
        return Path(args.out).expanduser()
    return nbdpsy_common.resolve_workspace() / "wechat" / f"stats-{d_from}_{d_to}.json"


def do_export(args, api_base, key):
    d_from, d_to = require_range(args, "--export")
    warnings = range_warnings(d_from, d_to)
    types = [args.stat_type] if args.stat_type else list(ALL_TYPES)

    bundle, counts = {}, {}
    for stat_type in types:
        rows = fetch_stats(api_base, key, stat_type, args.timeout, d_from, d_to, args.msgid)
        bundle[stat_type] = rows
        counts[stat_type] = len(rows)

    path = export_path(args, d_from, d_to)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"range": {"from": str(d_from), "to": str(d_to)}, "stats": bundle},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        raise OpFailed(f"写不出导出文件（{path}）：{type(e).__name__}: {e}")

    if not any(counts.values()):
        warnings.append("导出的是**空的**：这段区间一行快照都没有（区间早于数据起点 "
                        f"{DATA_START}？或服务端快照任务还没跑到）。")
    return {"outcome": "done", "path": str(path), "counts": counts,
            "range": {"from": str(d_from), "to": str(d_to)}, "warnings": warnings,
            "hint": "导出的是**服务端快照原始 payload**（微信 datacube 原样字段），没有做任何换算。"}, 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="服务号数据：概况 / 单篇 / 导出")
    ap.add_argument("--overview", action="store_true", help="涨粉 + 全号阅读概况（需 --from/--to）")
    ap.add_argument("--article", metavar="msgid", help="单篇逐日序列 + 转化率")
    ap.add_argument("--export", action="store_true", help="把区间内的原始快照落成 JSON 文件")

    ap.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="区间起（含）")
    ap.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="区间止（含）")
    ap.add_argument("--stat-type", dest="stat_type", help=f"--export 只导某一类：{'/'.join(ALL_TYPES)}")
    ap.add_argument("--msgid", help="--export 按单篇过滤（可选）")
    ap.add_argument("--out", help="--export 的落盘路径（默认 {workspace}/wechat/stats-起_止.json）")
    ap.add_argument("--api-base", dest="api_base", help="覆盖服务基址（默认走凭据/内置默认）")
    ap.add_argument("--timeout", type=float, default=wechat_api.DEFAULT_TIMEOUT, help="单次请求超时秒数")
    args = ap.parse_args(argv)

    actions = [(args.overview, do_overview), (args.article, do_article), (args.export, do_export)]
    chosen = [fn for flag, fn in actions if flag]
    if len(chosen) != 1:
        ap.error("三选一：--overview --from ... --to ... / --article <msgid> / --export --from ... --to ...")

    def action():
        api_base, key = wechat_api.credentials(args.api_base)
        payload, code = chosen[0](args, api_base, key)
        # warnings 同时打 stderr：这几条最容易被略过，而略过的代价是把「查不到」当成「0」
        for w in payload.get("warnings") or []:
            wechat_api.warn(f"⚠ {w}")
        return payload, code

    return wechat_api.run(action)


if __name__ == "__main__":
    sys.exit(main())

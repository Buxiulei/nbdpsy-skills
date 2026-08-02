"""md2wechat 编译器：微信白名单沙盒硬约束 + 图片上传钩子 + CLI 信封。

这里钉的都不是审美偏好，是「发出去会掉图 / 变形 / 被静默吞掉」的硬失败：
微信正文是 HTML 白名单沙盒（无 class/id、无 <style>/<script>/<iframe>、无 position 定位、
无 CSS 动画），图片必须先换成 mmbiz 域名 URL，正文 <2万字符且 <1MB。
静默失败是这条链路最贵的错——编译时看着好好的，发出去才发现整篇没有样式或全是空图。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-fuwuhao-operator" / "scripts"))

import md2wechat as M  # noqa: E402

SCRIPT = Path(__file__).parent.parent / "nbdpsy-fuwuhao-operator" / "scripts" / "md2wechat.py"


class TestSandbox:
    def test_产物无微信禁用构件(self, tmp_path):
        md = tmp_path / "a.md"
        md.write_text("# 标题\n\n正文**加粗**\n\n> 引用\n\n- 条目一\n", encoding="utf-8")
        result = M.compile_markdown(md.read_text(encoding="utf-8"), upload=None)
        html = result["html"]
        for banned in ("<script", "<style", "class=", "position:", "<iframe"):
            assert banned not in html
        assert 'style="' in html          # 全内联样式
        assert "加粗" in html and "引用" in html

    def test_代码块不带language类名(self):
        """mistune 原生 block_code 会输出 class="language-python"——class 在白名单外，必须覆写掉。"""
        r = M.compile_markdown("```python\nprint(1)\n```\n")
        assert "class=" not in r["html"]
        assert "print(1)" in r["html"]
        assert M.scan_forbidden(r["html"]) == []

    def test_原始HTML片段被转义并警告(self):
        """秀米/135 片段灌进 Markdown 是常见操作，必须当纯文本转义掉，并明确告知运营。"""
        r = M.compile_markdown(
            '正文\n\n<div class="x" style="position:absolute">秀米片段</div>\n\n'
            "<script>alert(1)</script>\n")
        html = r["html"]
        assert "<script" not in html and "<div" not in html
        assert "&lt;script&gt;" in html
        assert any("HTML" in w for w in r["warnings"])
        assert M.scan_forbidden(html) == []

    def test_正文里出现class字样不误判为违规(self):
        """正向对照：扫描器只看标签内部。否则一篇讲 HTML 的稿子会被自己的闸门误杀——
        而这个闸门是**硬失败**（整篇编译不出来），误杀的代价比漏杀还高。"""
        r = M.compile_markdown("讲个技术细节：写 class= 或 position: 或 javascript: 会被微信吞掉。\n")
        assert "class=" in r["html"]              # 文字确实进了正文（证明扫描确有内容可扫）
        assert M.scan_forbidden(r["html"]) == []

    def test_扫描器认得出真违规(self):
        """负向对照：扫描器不是摆设，标签属性里的 class/position 必须被抓到。"""
        assert M.scan_forbidden('<p class="x">a</p>')
        assert M.scan_forbidden('<p style="position:absolute">a</p>')
        assert M.scan_forbidden('<p style="animation:fade 1s">a</p>')
        assert M.scan_forbidden("<script>x</script>")
        assert M.scan_forbidden('<img src="a.png" onerror="x()" />')
        assert M.scan_forbidden('<a href="javascript:alert(1)">x</a>')

    def test_属性值里的文字不误杀(self):
        """alt/href 的**值**在标签内部，扫原串会让 `![讲 class= 用法](a.png)` 整篇硬失败。
        结构类规则只扫属性值清空后的串，取值类规则只扫它该管的那类属性。"""
        r = M.compile_markdown("![这里讲 class= 与 javascript: 的用法](a.png)\n")
        assert "class=" in r["html"]              # alt 里的原文确实留着（证明有东西可误杀）
        assert M.scan_forbidden(r["html"]) == []
        assert M.scan_forbidden('<img src="a.png" alt="讲 class= 用法" style="max-width:100%" />') == []

    def test_表格渲染成带样式的table(self):
        """pillar 长文里普遍有对照表；不接表格插件，整张表会变成一行行竖线原文。"""
        html = M.compile_markdown("| 表头A | 表头B |\n| --- | ---: |\n| 甲 | 乙 |\n")["html"]
        assert '<table style="' in html and '<th style="' in html and '<td style="' in html
        assert "text-align:right" in html          # 对齐语法没被丢掉
        assert "| 表头A |" not in html             # 没退化成竖线原文
        assert M.scan_forbidden(html) == []

    def test_块级元素都带内联样式(self):
        md = "## 二级\n\n段落\n\n> 引用\n\n- 项\n\n1. 一\n\n---\n"
        html = M.compile_markdown(md)["html"]
        for tag in ("<p ", "<h2 ", "<blockquote ", "<ul ", "<ol ", "<li ", "<hr "):
            assert tag in html, f"{tag} 没渲染出来"
            start = html.index(tag)
            assert 'style="' in html[start:html.index(">", start)], f"{tag} 少了内联样式"


class TestCjkStrong:
    def test_中文标点旁的加粗不漏成星号(self):
        """`叫**复杂性创伤（CPTSD）**的东西`：CommonMark flanking 规则判不成加粗，
        星号会原样发出去。已发布文章微信不能改，改一个星号要删+重发。"""
        r = M.compile_markdown("这是一种叫**复杂性创伤（CPTSD）**的东西，在替你喊疼。\n")
        assert "**" not in r["html"]
        assert '<strong style="' in r["html"] and "复杂性创伤（CPTSD）" in r["html"]
        assert any("加粗" in w for w in r["warnings"])

    def test_正常加粗不被重复处理(self):
        r = M.compile_markdown("正文 **加粗** 收尾\n")
        assert r["html"].count("<strong") == 1
        assert not any("自动修正" in w for w in r["warnings"])

    def test_不闭合的星号只警告不瞎改(self):
        r = M.compile_markdown("这里有个孤零零的 ** 星号。\n")
        assert "**" in r["html"]
        assert any("残留" in w for w in r["warnings"])

    def test_代码里的星号是字面量不许动(self):
        """`<code>`/`<pre>` 里的星号是作者要展示的内容，改了就是篡改代码；
        `<strong>` 塞进 `<code>` 里也不是作者的意思。那里的残留也不该报警。"""
        r = M.compile_markdown("行内 `**字面量**` 与代码块：\n\n```\na **b** c\n```\n")
        assert "<strong" not in r["html"]
        assert r["html"].count("**") == 4          # 行内 2 处 + 代码块 2 处，一个没动
        assert not any("残留" in w or "自动修正" in w for w in r["warnings"])


class TestImages:
    def test_图片经上传钩子换链接(self):
        calls = []

        def fake_upload(path_or_url):
            calls.append(path_or_url)
            return "https://mmbiz.qpic.cn/fake"

        result = M.compile_markdown("![图](local.png)", upload=fake_upload)
        assert calls == ["local.png"]
        assert 'src="https://mmbiz.qpic.cn/fake"' in result["html"]
        assert result["images"] == [{"src": "local.png", "wx_url": "https://mmbiz.qpic.cn/fake"}]

    def test_无钩子时保留原地址并明确警告掉图(self):
        """--dry-run 只是本地预排版。不警告的话，运营会拿着满是本地路径的 HTML 去发布。"""
        r = M.compile_markdown("![图](local.png)", upload=None)
        assert 'src="local.png"' in r["html"]
        assert r["images"] == [{"src": "local.png", "wx_url": None}]
        assert any("掉图" in w for w in r["warnings"])

    def test_同一张图只上传一次(self):
        """同一张图在文里出现多次是常态（题图复用）；每次都传 = 白烧素材库配额。"""
        calls = []

        def fake_upload(src):
            calls.append(src)
            return "https://mmbiz.qpic.cn/1"

        r = M.compile_markdown("![a](x.png)\n\n![a](x.png)\n", upload=fake_upload)
        assert calls == ["x.png"]
        assert r["html"].count("https://mmbiz.qpic.cn/1") == 2
        assert len(r["images"]) == 1


class TestUploader:
    def test_已是mmbiz的图直接复用不重传(self, tmp_path, monkeypatch):
        """重编译一篇已排版过的稿子不该再烧一次素材配额。"""
        monkeypatch.setattr(M, "_post_multipart",
                            lambda *a, **k: pytest.fail("已是 mmbiz 的图不该再上传"))
        up = M.make_uploader("https://api.example", "k", tmp_path)
        url = "https://mmbiz.qpic.cn/mmbiz_png/abc/0?wx_fmt=png"
        assert up(url) == url

    def test_本地图上传后返回mmbiz链接(self, tmp_path, monkeypatch):
        (tmp_path / "a.png").write_bytes(b"\x89PNG" + b"0" * 100)
        seen = {}

        def fake_post(url, api_key, filename, data, mime, timeout=60):
            seen.update(url=url, api_key=api_key, filename=filename, size=len(data), mime=mime)
            return {"success": True, "data": {"url": "https://mmbiz.qpic.cn/x"}}

        monkeypatch.setattr(M, "_post_multipart", fake_post)
        up = M.make_uploader("https://api.example", "k", tmp_path)
        assert up("a.png") == "https://mmbiz.qpic.cn/x"
        assert seen["url"] == "https://api.example/api/external/wechat/upload-image"
        assert seen["api_key"] == "k" and seen["filename"] == "a.png" and seen["mime"] == "image/png"

    def test_超1MB与非jpgpng当场失败(self, tmp_path):
        (tmp_path / "big.png").write_bytes(b"0" * (M.MAX_IMAGE_BYTES + 1))
        (tmp_path / "a.gif").write_bytes(b"GIF89a")
        up = M.make_uploader("https://api.example", "k", tmp_path)
        with pytest.raises(M.CompileError) as big:
            up("big.png")
        assert "1MB" in str(big.value)
        with pytest.raises(M.CompileError) as fmt:
            up("a.gif")
        assert "jpg" in str(fmt.value)

    def test_图片文件不存在时报人话(self, tmp_path):
        up = M.make_uploader("https://api.example", "k", tmp_path)
        with pytest.raises(M.CompileError) as e:
            up("missing.png")
        assert "missing.png" in str(e.value)

    def test_服务端没给URL时不静默通过(self, tmp_path, monkeypatch):
        """拿不到 mmbiz 地址就是失败——绝不把 None 塞进 src 让整篇变空图。"""
        (tmp_path / "a.png").write_bytes(b"\x89PNG" + b"0" * 10)
        monkeypatch.setattr(M, "_post_multipart", lambda *a, **k: {"success": True, "data": {}})
        up = M.make_uploader("https://api.example", "k", tmp_path)
        with pytest.raises(M.CompileError):
            up("a.png")

    def test_微信侧错误原样透出且不当成功(self, tmp_path, monkeypatch):
        """服务端把微信错误透出时 HTTP 仍是 200；当成功用会把空图发出去。"""
        (tmp_path / "a.png").write_bytes(b"\x89PNG" + b"0" * 10)

        class FakeResp:
            status_code = 200

            @staticmethod
            def json():
                return {"success": False, "wechat_errcode": 40164,
                        "wechat_errmsg": "invalid ip", "hint": "找管理员核对出口 IP"}

        import types
        # _post_multipart 是在函数里 import requests 的，替掉 sys.modules 就能走真实解析分支
        monkeypatch.setitem(sys.modules, "requests",
                            types.SimpleNamespace(post=lambda *a, **k: FakeResp()))
        up = M.make_uploader("https://api.example", "k", tmp_path)
        with pytest.raises(M.CompileError) as e:
            up("a.png")
        assert "40164" in str(e.value) and "出口 IP" in str(e.value)

    def test_封面走素材库拿永久media_id(self, tmp_path, monkeypatch):
        (tmp_path / "c.jpg").write_bytes(b"\xff\xd8" + b"0" * 100)

        def fake_post(url, api_key, filename, data, mime, timeout=60):
            assert url == "https://api.example/api/external/wechat/upload-material?type=thumb"
            return {"success": True, "data": {"media_id": "MID-1"}}

        monkeypatch.setattr(M, "_post_multipart", fake_post)
        assert M.upload_thumb(tmp_path / "c.jpg", "https://api.example", "k") == "MID-1"


class TestLinks:
    def test_外链保留href并提示可能不可点(self):
        r = M.compile_markdown("看[官网](https://www.nbdpsy.com/blog/x)")
        assert 'href="https://www.nbdpsy.com/blog/x"' in r["html"]
        assert any("外链" in w for w in r["warnings"])

    def test_javascript伪协议不落进产物(self):
        r = M.compile_markdown("[点我](javascript:alert(1))")
        assert "javascript:" not in r["html"]
        assert M.scan_forbidden(r["html"]) == []


class TestFrontmatterTitle:
    def test_frontmatter剥掉且标题抽出(self):
        """公众号分发稿（--gzh.md）就是这个形状；不剥掉，正文开头会出现 platform: gzh。"""
        r = M.compile_markdown("---\ntitle: 我的标题\nplatform: gzh\n---\n\n# 我的标题\n\n正文\n")
        assert r["title"] == "我的标题"
        assert "platform" not in r["html"] and "gzh" not in r["html"]
        assert "我的标题" not in r["html"]   # 微信标题建草稿时单独设，正文再放一遍会显示两遍
        assert "正文" in r["html"]

    def test_没有frontmatter时取首个H1当标题(self):
        r = M.compile_markdown("# 只有H1\n\n正文\n")
        assert r["title"] == "只有H1"
        assert "只有H1" not in r["html"]
        assert any("标题" in w for w in r["warnings"])

    def test_H1与frontmatter标题不一致时说清正文少了哪句(self):
        """删掉的那行不能闷声吞掉——运营得知道正文少了什么、标题最终用的是谁。"""
        r = M.compile_markdown("---\ntitle: 正式标题\n---\n\n# 草稿标题\n\n正文\n")
        assert r["title"] == "正式标题"
        assert "草稿标题" not in r["html"]
        assert any("草稿标题" in w and "正式标题" in w for w in r["warnings"])

    def test_正文不以H1开头时一字不动(self):
        r = M.compile_markdown("先来一段导语\n\n# 中间的H1\n")
        assert r["title"] == ""
        assert "中间的H1" in r["html"]

    def test_抽不到标题要出声不能静默给空串(self):
        """空串会一路带到建草稿；微信标题发出去就定死，改它＝删+重发。"""
        r = M.compile_markdown("正文\n\nsetext 式标题\n=====\n")
        assert r["title"] == ""
        assert any("--title" in w for w in r["warnings"])


class TestLimits:
    def test_超两万字符给出警告不静默(self):
        r = M.compile_markdown("正文段落。\n\n" * 3000)
        assert len(r["html"]) > M.MAX_CONTENT_CHARS
        assert any("2万" in w for w in r["warnings"])


class TestCLI:
    def _run(self, args, env=None):
        return subprocess.run([sys.executable, str(SCRIPT)] + args,
                              capture_output=True, text=True, env=env)

    def test_dry_run输出纯JSON并落文件(self, tmp_path):
        md = tmp_path / "post.md"
        md.write_text("---\ntitle: 标题\n---\n\n# 标题\n\n正文\n", encoding="utf-8")
        out, htm = tmp_path / "compiled.json", tmp_path / "content.html"
        p = self._run([str(md), "--dry-run", "--out", str(out), "--html-out", str(htm)])
        assert p.returncode == 0, p.stderr
        data = json.loads(p.stdout)
        assert data["outcome"] == "done"
        assert data["thumb_media_id"] is None and data["title"] == "标题"
        assert "<p " in data["html"]
        assert htm.read_text(encoding="utf-8") == data["html"]
        assert json.loads(out.read_text(encoding="utf-8"))["html"] == data["html"]

    def test_输入文件不存在时failed信封exit1(self, tmp_path):
        p = self._run([str(tmp_path / "nope.md"), "--dry-run"])
        assert p.returncode == 1
        assert json.loads(p.stdout)["outcome"] == "failed"

    def test_非UTF8稿子也回合法JSON不甩traceback(self, tmp_path):
        """GBK 存的稿子会在 read_text 抛 UnicodeDecodeError。裸 traceback ＝ stdout 零字节，
        消费方 json.loads 当场崩，而且看不出到底怎么了。"""
        md = tmp_path / "gbk.md"
        md.write_bytes("# 标题\n\n中文正文\n".encode("gbk"))
        p = self._run([str(md), "--dry-run"])
        assert p.returncode == 1
        data = json.loads(p.stdout)              # 必须是合法 JSON
        assert data["outcome"] == "failed" and "UTF-8" in data["error"]

    def test_html_out路径不可写时保住回执(self, tmp_path):
        """真实场景里此刻图片可能已经传上去了——回执里的 html 重跑也拿不回来，不能被吞掉。"""
        md = tmp_path / "post.md"
        md.write_text("正文\n", encoding="utf-8")
        blocker = tmp_path / "blocker"
        blocker.write_text("我是文件不是目录", encoding="utf-8")   # 父目录建不出来
        p = self._run([str(md), "--dry-run", "--html-out", str(blocker / "sub" / "c.html")])
        data = json.loads(p.stdout)              # 只有一份 JSON，且合法
        assert p.returncode == 1 and data["outcome"] == "failed"
        assert "<p " in data["html"]             # 回执里的正文仍在
        assert "不必重传" in data["error"]

    def test_out指向已存在目录时保住回执(self, tmp_path):
        md = tmp_path / "post.md"
        md.write_text("正文\n", encoding="utf-8")
        (tmp_path / "adir").mkdir()
        p = self._run([str(md), "--dry-run", "--out", str(tmp_path / "adir")])
        data = json.loads(p.stdout)
        assert p.returncode == 1 and data["outcome"] == "failed"
        assert "<p " in data["html"] and "--out" in data["error"]

    def test_缺凭据时确定失败不静默通过(self, tmp_path):
        """请求根本发不出去 = 结果已确定失败（红线⑤），必须 exit 1 并点名缺哪个键。"""
        import os
        md = tmp_path / "post.md"
        md.write_text("正文\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "NBDPSY_WECHAT_API_KEY"}
        env["NBDPSY_SECRETS"] = str(tmp_path / "empty.env")
        env["NBDPSY_WORKSPACE"] = str(tmp_path / "ws")
        p = self._run([str(md)], env=env)
        assert p.returncode == 1
        data = json.loads(p.stdout)
        assert data["outcome"] == "failed" and "NBDPSY_WECHAT_API_KEY" in data["error"]

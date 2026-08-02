"""menu_ops / article_ops / schedule_ops / stats_ops / wechat_api：服务号运营脚本。

钉六类东西——都是「说错一句话就赔上不可逆代价」的地方：
① **两桶口径**（红线⑤）：请求没发出/微信明确拒绝 = failed exit 1；已发出但结果不明
   （超时/断连/5xx **含 502**/响应读不懂）= unknown exit 0。publish 的 502 报 failed 会
   诱导二次发布，45028 报 failed 会诱导白烧一次月配额。
② **高危动作的 confirm 闸门**：`--delete-published` 无 confirm **一个请求都不发**（假 session
   断言零调用），`--mass-send` / `--submit-mass` 无 confirm 只查配额、绝不带 confirm:true 出门。
③ **红线③**：外部 HTML（class/style/script/iframe/on* 事件）不许灌进正文，且不能误杀属性值里的文案。
④ **draft/update 是整篇替换**：漏给的字段会被清空，所以必须先读回原文再覆盖。
⑤ **定时时间必须带时区**：裸 `2026-08-03 09:00` 会被服务端当 UTC，早发 8 小时——本地就得拦。
⑥ **统计缺字段给 null 不给 0**：把「查不到」说成「0 涨粉」是这条线上最容易造成误判的错。
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-fuwuhao-operator" / "scripts"))

import article_ops as A          # noqa: E402
import menu_ops as M             # noqa: E402
import schedule_ops as S         # noqa: E402
import stats_ops as ST           # noqa: E402
import wechat_api as W           # noqa: E402


class FakeResp:
    """假 Response：payload=None 表示响应体不是 JSON（axum 的 413/422 就是裸 text/plain）。"""

    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else (
            json.dumps(payload, ensure_ascii=False) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class FakeRequests:
    """假 requests 模块：记录每次调用，按顺序回预置响应（Exception 实例则抛出）。"""

    def __init__(self, *responses):
        self.queue = list(responses)
        self.calls = []

    def request(self, method, url, json=None, headers=None, timeout=None):   # noqa: A002
        self.calls.append({"method": method, "url": url, "body": json, "timeout": timeout})
        if not self.queue:
            raise AssertionError(f"没有预置更多响应，但脚本又发了一次请求：{method} {url}")
        nxt = self.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def paths(self):
        """透传调用里的微信 path（其余端点回 None），用来断言「到底动了哪个接口」。"""
        return [(c["body"] or {}).get("path") for c in self.calls]


@pytest.fixture
def net(monkeypatch):
    """装一份假网络层；测试用 net.serve(...) 预置响应，net.calls 断言到底发了什么。"""
    holder = FakeRequests()
    monkeypatch.setattr(W, "_requests", lambda: holder)
    monkeypatch.setattr(W, "credentials", lambda api_base=None: ("http://svc", "k"))
    holder.serve = lambda *rs: holder.queue.extend(rs)
    return holder


def run_cli(module, argv, capsys):
    """跑一次 main()，回 (exit_code, stdout 解析出的 JSON, stderr)。"""
    code = module.main(argv)
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err


# ══════════════ ① 两桶口径（wechat_api） ══════════════

class Test两桶口径:
    def test_401与403是确定失败并给出改配置的提示(self, net):
        net.serve(FakeResp(401, {"success": False, "error": "无效的 API Key"}))
        with pytest.raises(W.OpFailed) as e:
            W.request_json("GET", "http://svc/x", "k")
        assert "重发凭据配置包" in e.value.error and "401" in e.value.error

        net.serve(FakeResp(403, {"success": False, "error": "该 API Key 无权访问微信服务号接口"}))
        with pytest.raises(W.OpFailed) as e:
            W.request_json("GET", "http://svc/x", "k", irreversible=True)   # 不可逆也仍是确定失败
        assert "wechat:operate" in e.value.error

    def test_413与422是裸文本不是JSON也要给人话(self, net):
        """axum 的 body limit / 反序列化拒绝回 text/plain，裸 .json() 会抛，
        把「字段写错了」变成看不懂的解析错误。"""
        net.serve(FakeResp(422, payload=None, text="Failed to deserialize the JSON body"))
        with pytest.raises(W.OpFailed) as e:
            W.request_json("POST", "http://svc/x", "k", {})
        assert "422" in e.value.error and "必填字段" in e.value.error

        net.serve(FakeResp(413, payload=None, text="length limit exceeded"))
        with pytest.raises(W.OpFailed) as e:
            W.request_json("POST", "http://svc/x", "k", {})
        assert "413" in e.value.error and "压缩" in e.value.error

    def test_不可逆动作的502没有sent判别位时按结果未确认(self, net):
        """旧版服务端不带 sent 字段：502 = 可能已经替你转给微信了。报 failed 会诱导二次发布。
        缺失**必须**退回 unknown——判成 failed 正好搞反最贵的那一侧。"""
        net.serve(FakeResp(502, {"success": False, "error": "微信接口不可达"}))
        with pytest.raises(W.OpUnknown) as e:
            W.request_json("POST", "http://svc/publish", "k", {}, irreversible=True)
        assert "拿不准" in e.value.error
        assert e.value.envelope()["outcome"] == "unknown"

    def test_502带sent_true仍是结果未确认(self, net):
        net.serve(FakeResp(502, {"success": False, "sent": True,
                                 "error": "已发给微信但没读到回复"}))
        with pytest.raises(W.OpUnknown):
            W.request_json("POST", "http://svc/publish", "k", {}, irreversible=True)

    def test_502带sent_false是确定失败且明说不用查台账(self, net):
        """服务端确知请求没转出去时，含糊成 unknown 只会让运营白查一次必然为空的台账。"""
        net.serve(FakeResp(502, {"success": False, "sent": False,
                                 "error": "微信 token 接口返回 errcode=40013"}))
        with pytest.raises(W.OpFailed) as e:
            W.request_json("POST", "http://svc/publish", "k", {}, irreversible=True)
        assert "sent=false" in e.value.error and "不用查台账" in e.value.error
        assert e.value.envelope()["outcome"] == "failed"

    def test_sent为null或读不懂的响应体一律退回结果未确认(self, net):
        """`not data.get("sent")` 那种写法会把 null/缺失当成没发出去——判据必须是 `is False`。"""
        net.serve(FakeResp(500, {"success": False, "sent": None, "error": "内部错误"}))
        with pytest.raises(W.OpUnknown):
            W.request_json("POST", "http://svc/publish", "k", {}, irreversible=True)
        net.serve(FakeResp(502, payload=None, text="<html>网关错误页</html>"))
        with pytest.raises(W.OpUnknown):
            W.request_json("POST", "http://svc/publish", "k", {}, irreversible=True)

    def test_查询类的5xx照常算失败(self, net):
        """读操作没有「可能已生效」的风险，含糊成 unknown 只会让人去查一个必然为空的台账。"""
        net.serve(FakeResp(502, {"success": False, "error": "微信接口不可达"}))
        with pytest.raises(W.OpFailed):
            W.request_json("GET", "http://svc/ledger", "k")

    def test_微信确定拒绝归失败并原样透出errcode(self, net):
        net.serve(FakeResp(200, {"success": False, "wechat_errcode": 45009,
                                 "wechat_errmsg": "reach max api daily quota limit",
                                 "hint": "等一会儿再试"}))
        with pytest.raises(W.OpFailed) as e:
            W.request_json("POST", "http://svc/x", "k", {}, irreversible=True)
        env = e.value.envelope()
        assert env["wechat_errcode"] == 45009 and env["hint"] == "等一会儿再试"
        assert env["wechat_errmsg"] == "reach max api daily quota limit"

    def test_45028是唯一归unknown的errcode且hint照SKILL钉死(self, net):
        net.serve(FakeResp(200, {"success": False, "wechat_errcode": 45028,
                                 "wechat_errmsg": "mass send protect", "hint": "服务端自带的提示"}))
        with pytest.raises(W.OpUnknown) as e:
            W.request_json("POST", "http://svc/mass-send", "k", {}, irreversible=True)
        env = e.value.envelope()
        assert env["outcome"] == "unknown"
        assert env["hint"] == W.MASS_PROTECT_HINT and "30 分钟" in env["hint"]
        assert env["wechat_errcode"] == 45028

    def test_没有errcode的success_false是服务端拒的不是微信拒的(self, net):
        net.serve(FakeResp(200, {"success": False, "error": "缺少 confirm"}))
        with pytest.raises(W.OpFailed) as e:
            W.request_json("POST", "http://svc/x", "k", {})
        assert "服务端拒绝" in e.value.error and "微信拒绝" not in e.value.error

    def test_响应读不懂时不可逆动作落unknown(self, net):
        net.serve(FakeResp(200, payload=None, text="<html>网关的错误页</html>"))
        with pytest.raises(W.OpUnknown):
            W.request_json("POST", "http://svc/publish", "k", {}, irreversible=True)
        net.serve(FakeResp(200, payload=None, text="<html>网关的错误页</html>"))
        with pytest.raises(W.OpFailed):
            W.request_json("GET", "http://svc/ledger", "k")

    @pytest.mark.parametrize("marker", [
        "Host not allowed", "NewConnectionError(...): Connection refused",
        "Max retries exceeded ... ConnectTimeoutError", "ProxyError('Cannot connect')",
        # --api-base 打错（少了 https:// 之类）：requests 在建连之前就抛，这次一定没发出去
        "Invalid URL 'database.nbdpsy.com': No scheme supplied",
        "MissingSchema: Invalid URL", "InvalidSchema: No connection adapters were found",
    ])
    def test_连接没建起来即使不可逆也是确定失败(self, net, marker):
        """连接都没建立 = 请求没发出去 = 一定没生效，含糊成 unknown 只会让运营白查台账。"""
        net.serve(RuntimeError(marker))
        with pytest.raises(W.OpFailed):
            W.request_json("POST", "http://svc/publish", "k", {}, irreversible=True)

    def test_读响应超时对不可逆动作是结果未确认(self, net):
        """请求已经发出去了，只是没读到回复——重发就可能是第二次群发。"""
        net.serve(RuntimeError("HTTPSConnectionPool(host='svc'): Read timed out. (read timeout=60)"))
        with pytest.raises(W.OpUnknown) as e:
            W.request_json("POST", "http://svc/mass-send", "k", {}, irreversible=True)
        assert "先" in e.value.hint and "台账" in e.value.hint

    def test_run把三类结局转成信封且stdout恒为一份JSON(self, capsys):
        assert W.run(lambda: (_ for _ in ()).throw(W.OpFailed("坏了", wechat_errcode=40164))) == 1
        assert json.loads(capsys.readouterr().out)["wechat_errcode"] == 40164

        assert W.run(lambda: (_ for _ in ()).throw(W.OpUnknown("不确定"))) == 0
        assert json.loads(capsys.readouterr().out)["outcome"] == "unknown"

        # 漏网异常也必须是合法 JSON：甩 traceback ＝ stdout 零字节，消费方 json.loads 当场崩
        assert W.run(lambda: (_ for _ in ()).throw(KeyError("boom"))) == 1
        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "failed" and "未预期的错误" in data["error"]

    def test_缺凭据是确定失败且点名缺哪个键(self, monkeypatch):
        monkeypatch.setattr(W.nbdpsy_common, "get_secret", lambda k: None)
        with pytest.raises(W.OpFailed) as e:
            W.credentials()
        assert "NBDPSY_WECHAT_API_KEY" in e.value.error and "secret get" in e.value.error


# ══════════════ ② 菜单 ══════════════

MENU_ONLINE = {"menu": {"button": [
    {"name": "找咨询师", "sub_button": [
        {"name": "看介绍", "type": "view", "url": "https://a/1"},
        {"name": "约时间", "type": "view", "url": "https://a/2"}]},
    {"name": "了解我们", "type": "view", "url": "https://a/about"},
]}}


def _menu_file(tmp_path, buttons):
    p = tmp_path / "menu.json"
    p.write_text(json.dumps({"button": buttons}, ensure_ascii=False), encoding="utf-8")
    return str(p)


class Test菜单校验:
    def test_超过三个一级菜单直接拒发不浪费一次调用(self):
        with pytest.raises(M.OpFailed) as e:
            M.validate([{"name": f"菜单{i}", "type": "click", "key": "k"} for i in range(4)])
        assert "上限 3" in e.value.error

    def test_二级超过五个也拒发(self):
        subs = [{"name": f"项{i}", "type": "view", "url": "https://a"} for i in range(6)]
        with pytest.raises(M.OpFailed) as e:
            M.validate([{"name": "更多", "sub_button": subs}])
        assert "上限 5" in e.value.error

    def test_没有三级菜单(self):
        with pytest.raises(M.OpFailed) as e:
            M.validate([{"name": "一", "sub_button": [
                {"name": "二", "sub_button": [{"name": "三", "type": "view", "url": "u"}]}]}])
        assert "三级" in e.value.error

    def test_点了没反应的按钮拒发(self):
        with pytest.raises(M.OpFailed) as e:
            M.validate([{"name": "空按钮"}])
        assert "不会有任何反应" in e.value.error
        with pytest.raises(M.OpFailed) as e:
            M.validate([{"name": "跳转", "type": "view"}])
        assert "没有 url" in e.value.error

    def test_空菜单要说清删除的正确姿势(self):
        with pytest.raises(M.OpFailed) as e:
            M.validate([])
        assert "--delete --confirm" in e.value.error

    def test_名字过长只警告不拦(self):
        """微信只是截断显示，不是拒收——拦下来等于替运营做决定。"""
        w = M.validate([{"name": "这是五个字啊", "type": "view", "url": "https://a"}])
        assert any("截断" in x for x in w)


class Test菜单diff:
    def test_逐条给出人话变更(self):
        new = [
            {"name": "找咨询师", "sub_button": [
                {"name": "看介绍", "type": "view", "url": "https://a/1"},
                {"name": "约时间", "type": "view", "url": "https://NEW"},
                {"name": "怎么收费", "type": "view", "url": "https://a/3"}]},
            {"name": "心理测评", "type": "view", "url": "https://a/test"},
        ]
        lines = M.menu_diff(MENU_ONLINE["menu"]["button"], new)["lines"]
        joined = "｜".join(lines)
        assert "新增一级菜单「心理测评」" in joined
        assert "删除一级菜单「了解我们」" in joined
        assert "下新增二级「怎么收费」" in joined
        assert "二级「约时间」动作变更" in joined
        assert "「看介绍」" not in joined            # 没动的不要刷屏

    def test_一模一样时changed为假(self):
        online = MENU_ONLINE["menu"]["button"]
        assert M.menu_diff(online, json.loads(json.dumps(online)))["changed"] is False


class Test菜单CLI:
    """菜单文件落 tmp_path；每个用例自带 net（假网络层）与 capsys。"""

    def test_get输出可直接编辑再apply的菜单本身(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "data": MENU_ONLINE}))
        code, data, err = run_cli(M, ["--get"], capsys)
        assert code == 0 and data == {"button": MENU_ONLINE["menu"]["button"]}
        assert "24 小时" in err                      # 缓存提示走 stderr，不污染管道

    def test_线上还没菜单时给空骨架而不是报错(self, net, capsys):
        net.serve(FakeResp(200, {"success": False, "wechat_errcode": 46003,
                                 "wechat_errmsg": "menu no exist"}))
        code, data, err = run_cli(M, ["--get"], capsys)
        assert code == 0 and data == {"button": []}
        assert "46003" in err and "后台手动配过菜单" in err

    def test_apply不带confirm只读现状不发create(self, net, tmp_path, capsys):
        new = [{"name": "新入口", "type": "view", "url": "https://a/x"}]
        net.serve(FakeResp(200, {"success": True, "data": MENU_ONLINE}))
        code, data, err = run_cli(M, ["--apply", _menu_file(tmp_path, new)], capsys)
        assert code == 1 and data["outcome"] == "failed"
        assert "安全闸门" in data["error"]
        assert "/cgi-bin/menu/create" not in net.paths()        # ⛔ 一次写调用都没发
        assert net.paths() == ["/cgi-bin/menu/get"]
        assert any("新增一级菜单「新入口」" in x for x in data["diff"]["lines"])
        assert "念给运营" in err and "整体覆盖" in err

    def test_apply带confirm才真的发create(self, net, tmp_path, capsys):
        new = [{"name": "新入口", "type": "view", "url": "https://a/x"}]
        net.serve(FakeResp(200, {"success": True, "data": MENU_ONLINE}),
                  FakeResp(200, {"success": True, "data": {"errcode": 0, "errmsg": "ok"}}))
        code, data, _ = run_cli(M, ["--apply", _menu_file(tmp_path, new), "--confirm"], capsys)
        assert code == 0 and data["outcome"] == "done"
        assert net.paths() == ["/cgi-bin/menu/get", "/cgi-bin/menu/create"]
        assert net.calls[-1]["body"]["body"] == {"button": new}
        assert "24 小时" in data["hint"]

    def test_apply硬约束不过时连现状都不去读(self, net, tmp_path, capsys):
        bad = [{"name": f"菜单{i}", "type": "click", "key": "k"} for i in range(4)]
        code, data, _ = run_cli(M, ["--apply", _menu_file(tmp_path, bad)], capsys)
        assert code == 1 and data["outcome"] == "failed" and net.calls == []

    def test_拿线上现状失败也不挡住apply但要说清没有diff(self, net, tmp_path, capsys):
        new = [{"name": "新入口", "type": "view", "url": "https://a/x"}]
        net.serve(FakeResp(502, {"success": False, "error": "微信不可达"}),
                  FakeResp(200, {"success": True, "data": {"errcode": 0}}))
        code, data, _ = run_cli(M, ["--apply", _menu_file(tmp_path, new), "--confirm"], capsys)
        assert code == 0 and data["diff"] is None and "没能拉到线上现状" in data["baseline_note"]

    def test_apply的文件是上次的失败回执时说人话(self, net, tmp_path, capsys):
        p = tmp_path / "menu.json"
        p.write_text(json.dumps({"outcome": "failed", "error": "..."}), encoding="utf-8")
        code, data, _ = run_cli(M, ["--apply", str(p)], capsys)
        assert code == 1 and "脚本回执" in data["error"] and net.calls == []

    def test_delete不带confirm不删只警示(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "data": MENU_ONLINE}))
        code, data, err = run_cli(M, ["--delete"], capsys)
        assert code == 1 and data["outcome"] == "failed"
        assert "/cgi-bin/menu/delete" not in net.paths()
        assert data["current_top_level"] == ["找咨询师", "了解我们"]
        assert "回滚基线" in data["hint"] and "立刻" in err

    def test_delete带confirm才真删(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "data": MENU_ONLINE}),
                  FakeResp(200, {"success": True, "data": {"errcode": 0}}))
        code, data, _ = run_cli(M, ["--delete", "--confirm"], capsys)
        assert code == 0 and data["outcome"] == "done"
        assert net.paths() == ["/cgi-bin/menu/get", "/cgi-bin/menu/delete"]


# ══════════════ ③ 文章 ══════════════

CLEAN_HTML = ('<section style="font-size:16px"><p style="margin:0">正文'
              '<img src="https://mmbiz.qpic.cn/a.png" /></p></section>')


def _html(tmp_path, body=CLEAN_HTML, name="content.html"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


class Test红线三正文闸门:
    def test_秀米式HTML直接拒收(self, tmp_path):
        for bad, why in (('<section class="xiumi">正文</section>', "class"),
                         ('<style>p{color:red}</style><p>正文</p>', "style"),
                         ('<p>正文</p><script>alert(1)</script>', "script"),
                         ('<iframe src="https://v.qq.com"></iframe>', "iframe")):
            with pytest.raises(A.OpFailed) as e:
                A.read_content(_html(tmp_path, bad, f"{why}.html"))
            assert "md2wechat" in e.value.error and "改＝删+重发" in e.value.error

    def test_属性值里的文案不误杀(self, tmp_path):
        """`![讲 class= 用法](a.png)` 的 alt 就在标签内部，扫原串会把合法产物整篇卡死。"""
        ok = '<p style="m"><img src="https://mmbiz.qpic.cn/a.png" alt="这段讲 class= 怎么用" /></p>'
        assert A.read_content(_html(tmp_path, ok)) == ok

    def test_误把Markdown原文当正文时说清该干嘛(self, tmp_path):
        with pytest.raises(A.OpFailed) as e:
            A.read_content(_html(tmp_path, "# 标题\n\n正文段落\n", "post.md"))
        assert "md2wechat.py" in e.value.error and "Markdown" in e.value.error

    def test_dry_run产物掉图会被警告(self):
        w = A.content_warnings('<p><img src="/local/a.png" /></p>')
        assert any("mmbiz" in x and "dry-run" in x for x in w)

    def test_残留星号要警告(self):
        assert any("星号" in x for x in A.content_warnings("<p>叫**复杂性创伤**的东西</p>"))

    def test_代码块里的星号是字面量不算残留(self):
        """md2wechat 刻意不动 code/pre 里的星号（改了就是篡改代码），这里当然也不能拿它警告
        ——一句「回源稿改掉」会让运营真的去改代码。"""
        assert A.content_warnings('<pre style="x"><code>a = b ** 2</code></pre>') == []
        # 代码块外仍有残留时照样要报
        assert any("星号" in x for x in A.content_warnings(
            '<pre><code>b ** 2</code></pre><p>叫**创伤**的东西</p>'))

    def test_内联事件属性也拒收(self, tmp_path):
        """红线③的精简副本要和 md2wechat.scan_forbidden 对齐：onclick 溜过去就等于放 JS 进正文。"""
        with pytest.raises(A.OpFailed) as e:
            A.read_content(_html(tmp_path, '<p style="m" onclick="alert(1)">正文</p>', "on.html"))
        assert "事件属性" in e.value.error
        assert M.OpFailed is A.OpFailed        # 两脚本共用 wechat_api 的异常，不是各抄一份

    def test_单引号属性值同样不误杀且撇号不吞掉真违规(self, tmp_path):
        ok = "<p style='m'><img src='https://mmbiz.qpic.cn/a.png' alt='这段讲 class= 怎么用' /></p>"
        assert A.read_content(_html(tmp_path, ok, "sq.html")) == ok
        # 正文里的英文撇号不能把后面真正的 class= 一起抹掉（裸扫引号的经典漏判）
        with pytest.raises(A.OpFailed):
            A.read_content(_html(tmp_path, "<p>it's</p><p class=\"xiumi\">don't</p>", "apos.html"))


class Test草稿:
    def test_建草稿必须有标题(self, net, tmp_path, capsys):
        code, data, _ = run_cli(A, ["--draft-add", "--content", _html(tmp_path)], capsys)
        assert code == 1 and "定死" in data["error"] and net.calls == []

    def test_建草稿把字段拼进articles并回media_id(self, net, tmp_path, capsys):
        net.serve(FakeResp(200, {"success": True, "data": {"media_id": "M1"}}))
        code, data, _ = run_cli(A, ["--draft-add", "--content", _html(tmp_path), "--title", "标题",
                                    "--author", "胡佰亿", "--digest", "摘要",
                                    "--thumb-media-id", "T1"], capsys)
        assert code == 0 and data["media_id"] == "M1"
        sent = net.calls[0]["body"]
        assert sent["path"] == "/cgi-bin/draft/add"
        art = sent["body"]["articles"][0]
        assert art["title"] == "标题" and art["author"] == "胡佰亿" and art["thumb_media_id"] == "T1"
        assert "--publish --media-id M1" in data["hint"]

    def test_没封面要警告不拦(self, net, tmp_path, capsys):
        net.serve(FakeResp(200, {"success": True, "data": {"media_id": "M1"}}))
        code, data, _ = run_cli(A, ["--draft-add", "--content", _html(tmp_path),
                                    "--title", "标题"], capsys)
        assert code == 0 and any("thumb" in w for w in data["warnings"])

    def test_微信没回media_id时不静默成功(self, net, tmp_path, capsys):
        net.serve(FakeResp(200, {"success": True, "data": {"errcode": 0}}))
        code, data, _ = run_cli(A, ["--draft-add", "--content", _html(tmp_path),
                                    "--title", "标题"], capsys)
        assert code == 1 and "没回 media_id" in data["error"]

    def test_查草稿不打印正文只给字数(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "data": {"news_item": [
            {"title": "标题", "author": "胡佰亿", "content": "x" * 5000, "thumb_media_id": "T1"}]}}))
        code, data, _ = run_cli(A, ["--draft-get", "--media-id", "M1"], capsys)
        assert code == 0
        assert data["news_item"][0]["content"] is None
        assert data["news_item"][0]["content_chars"] == 5000
        assert data["news_item"][0]["title"] == "标题"

    def test_改草稿先读回原文再覆盖免得清空作者和封面(self, net, tmp_path, capsys):
        """draft/update 是**整篇替换**：只送 content 的话，作者/封面/摘要会被清空。"""
        net.serve(FakeResp(200, {"success": True, "data": {"news_item": [
            {"title": "老标题", "author": "胡佰亿", "digest": "老摘要", "content": "<p>老正文</p>",
             "thumb_media_id": "T1", "url": "https://mp.weixin.qq.com/s/x"}]}}),
            FakeResp(200, {"success": True, "data": {"errcode": 0}}))
        code, data, _ = run_cli(A, ["--draft-update", "--media-id", "M1",
                                    "--content", _html(tmp_path)], capsys)
        assert code == 0 and data["updated_fields"] == ["content"]
        body = net.calls[1]["body"]["body"]
        assert body["media_id"] == "M1" and body["index"] == 0
        art = body["articles"]
        assert art["author"] == "胡佰亿" and art["thumb_media_id"] == "T1" and art["digest"] == "老摘要"
        assert art["content"] == CLEAN_HTML
        assert "url" not in art        # 只送微信认的字段，读回来的只读字段不回灌

    def test_改草稿什么都没给时拒绝并零调用(self, net, capsys):
        code, data, _ = run_cli(A, ["--draft-update", "--media-id", "M1"], capsys)
        assert code == 1 and net.calls == []

    def test_media_id写错时给出排查方向(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "data": {"news_item": []}}))
        code, data, _ = run_cli(A, ["--draft-get", "--media-id", "错的"], capsys)
        assert code == 1 and "台账 id" in data["error"]


class Test发布与台账:
    def test_发布成功给出异步与查终态的下一步(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "ledger_id": 7, "publish_id": "100000001"}))
        code, data, _ = run_cli(A, ["--publish", "--media-id", "M1"], capsys)
        assert code == 0 and data["ledger_id"] == 7 and data["publish_id"] == "100000001"
        assert net.calls[0]["url"].endswith("/api/external/wechat/publish")
        assert "--status --id 7" in data["hint"] and "不占群发次数" in data["hint"]

    def test_发布遇502落unknown且exit0(self, net, capsys):
        """T4 交接的硬契约：submit 可能已经发出去了，报 failed 会诱导二次发布。"""
        net.serve(FakeResp(502, {"success": False, "error": "微信接口不可达"}))
        code, data, _ = run_cli(A, ["--publish", "--media-id", "M1"], capsys)
        assert code == 0 and data["outcome"] == "unknown"
        assert "台账" in data["hint"]

    def test_发布遇502但服务端说没发出去时如实报失败(self, net, capsys):
        net.serve(FakeResp(502, {"success": False, "sent": False,
                                 "error": "微信 token 接口返回 errcode=40013"}))
        code, data, _ = run_cli(A, ["--publish", "--media-id", "M1"], capsys)
        assert code == 1 and data["outcome"] == "failed"
        assert "不用查台账" in data["error"]

    def test_发布被微信明确拒绝是失败要改再来(self, net, capsys):
        net.serve(FakeResp(200, {"success": False, "wechat_errcode": 53501,
                                 "wechat_errmsg": "freq control", "hint": "隔开时间再发"}))
        code, data, _ = run_cli(A, ["--publish", "--media-id", "M1"], capsys)
        assert code == 1 and data["outcome"] == "failed" and data["wechat_errcode"] == 53501

    def test_台账透传并补人话状态与本页统计(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "total": 40, "limit": 2, "offset": 0, "items": [
            {"id": 9, "status": "published", "url": "https://mp/x", "msg_id": "2247"},
            {"id": 8, "status": "publishing", "url": None, "msg_id": None}]}))
        code, data, _ = run_cli(A, ["--ledger", "--limit", "2", "--status", "published"], capsys)
        assert code == 0 and data["total"] == 40                 # 顶层 total 不被本页统计覆盖
        assert data["items"][0]["mass_sent"] is True and data["items"][1]["mass_sent"] is False
        assert "已发布" in data["items"][0]["status_label"]
        assert data["counts"] == {"in_page": 2, "by_status": {"published": 1, "publishing": 1},
                                  "mass_sent": 1}
        assert "status=published" in net.calls[0]["url"] and "limit=2" in net.calls[0]["url"]

    def test_查单篇会翻页找并在找不到时点出常见错认(self, net, capsys):
        page1 = [{"id": i, "status": "published"} for i in range(200, 100, -1)]
        net.serve(FakeResp(200, {"success": True, "total": 150, "items": page1}),
                  FakeResp(200, {"success": True, "total": 150,
                                 "items": [{"id": 50, "status": "published", "url": "https://mp/x"}]}))
        code, data, _ = run_cli(A, ["--status", "--id", "50"], capsys)
        assert code == 0 and data["id"] == 50 and "已发布" in data["status_label"]

        net.serve(FakeResp(200, {"success": True, "total": 1,
                                 "items": [{"id": 9, "status": "published"}]}))
        code, data, _ = run_cli(A, ["--status", "--id", "999"], capsys)
        # 两种可能都要点出来：认错了 id，或者这行太旧翻不到（翻页找的固有边界）
        assert code == 1 and "media_id" in data["error"] and "翻页范围" in data["error"]

    def test_把ledger的过滤条件写成单篇查询时给纠正(self, net, capsys):
        code, data, _ = run_cli(A, ["--status", "published"], capsys)
        assert code == 1 and "--ledger --status published" in data["error"] and net.calls == []

    def test_发布中要说清不是故障(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "total": 1,
                                 "items": [{"id": 3, "status": "publishing"}]}))
        code, data, _ = run_cli(A, ["--status", "--id", "3"], capsys)
        assert code == 0 and "不是故障" in data["hint"]


class Test群发红线一:
    def test_不带confirm只查配额且绝不带confirm出门(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "month_used": 2, "month_quota": 4}))
        code, data, err = run_cli(A, ["--mass-send", "--ledger-id", "7", "--to-all"], capsys)
        assert code == 1 and data["outcome"] == "failed"
        # 预检也必须带 filter：服务端参数校验先于配额预检，漏了连配额都查不到
        assert net.calls[0]["body"] == {"article_ledger_id": 7, "filter": {"is_to_all": True},
                                        "confirm": False}
        assert data["server"]["month_used"] == 2
        assert "本月已用 X/4" in data["hint"] and "后台手动群发" in data["hint"]
        assert "每自然月只有 4 次" in err and "全部粉丝" in err

    def test_带confirm但没写谁拍板的直接拒发(self, net, capsys):
        code, data, _ = run_cli(A, ["--mass-send", "--ledger-id", "7", "--to-all", "--confirm"],
                                capsys)
        assert code == 1 and "问责留痕" in data["error"] and net.calls == []

    def test_带confirm和note才真发(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "msg_id": "2247483647"}))
        code, data, _ = run_cli(A, ["--mass-send", "--ledger-id", "7", "--to-all", "--confirm",
                                    "--note", "运营张三确认，8月第2条"], capsys)
        assert code == 0 and data["outcome"] == "done" and data["msg_id"] == "2247483647"
        assert net.calls[0]["body"]["confirm"] is True
        assert net.calls[0]["body"]["filter"] == {"is_to_all": True}
        assert net.calls[0]["body"]["note"] == "运营张三确认，8月第2条"
        assert "全部粉丝" in data["hint"]

    def test_群发保护落unknown而不是失败(self, net, capsys):
        """看到报错就重发正是白烧一次月配额的典型场景。"""
        net.serve(FakeResp(200, {"success": False, "wechat_errcode": 45028,
                                 "wechat_errmsg": "mass send protect"}))
        code, data, _ = run_cli(A, ["--mass-send", "--ledger-id", "7", "--to-all", "--confirm",
                                    "--note", "运营张三确认"], capsys)
        assert code == 0 and data["outcome"] == "unknown"
        assert data["hint"] == W.MASS_PROTECT_HINT

    def test_没给对象时不发请求(self, net, capsys):
        code, data, _ = run_cli(A, ["--mass-send"], capsys)
        assert code == 1 and net.calls == []


class Test群发受众闸门:
    """`filter` 是服务端必填，而这条约束的**意义**是不让「漏填」等于「悄悄推给全部粉丝」。
    所以本地就要选一个，且两个都给时不替运营猜。"""

    def test_没说发给谁时零请求并要求二选一(self, net, capsys):
        code, data, _ = run_cli(A, ["--mass-send", "--ledger-id", "7"], capsys)
        assert code == 1 and net.calls == []
        assert "--to-all" in data["error"] and "--tag-id" in data["error"]
        assert "默认成全员群发" in data["error"]

    def test_两个受众都给了不替运营猜(self, net, capsys):
        code, data, _ = run_cli(A, ["--mass-send", "--ledger-id", "7", "--to-all",
                                    "--tag-id", "102"], capsys)
        assert code == 1 and net.calls == [] and "只能给一个" in data["error"]

    def test_标签分组映射成is_to_all为假(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "msg_id": "M"}))
        code, data, _ = run_cli(A, ["--mass-send", "--media-id", "MID", "--tag-id", "102",
                                    "--confirm", "--note", "运营张三确认"], capsys)
        assert code == 0
        assert net.calls[0]["body"]["filter"] == {"is_to_all": False, "tag_id": 102}
        assert net.calls[0]["body"]["media_id"] == "MID"
        assert "tag_id=102" in data["audience"]

    def test_受众闸门是即时群发与定时群发共用的一份(self):
        """两处各抄一份，迟早一边漏掉闸门变成「悄悄全员群发」。"""
        assert A.wechat_api.mass_filter is S.wechat_api.mass_filter
        assert A.QUOTA_CAVEAT == S.QUOTA_CAVEAT == W.QUOTA_CAVEAT


class Test删除已发布红线二:
    def test_不带confirm时一个请求都不发(self, net, capsys):
        code, data, err = run_cli(A, ["--delete-published", "--article-id", "ART1"], capsys)
        assert code == 1 and data["outcome"] == "failed"
        assert net.calls == []                        # ⛔ 零调用：删除不可逆，警示阶段不碰网络
        assert "没有发出任何请求" in data["error"]
        assert "链接立刻失效" in err and "清零" in err

    def test_带confirm才真删并带上confirm字段(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "deleted": True}))
        code, data, _ = run_cli(A, ["--delete-published", "--article-id", "ART1",
                                    "--index", "0", "--confirm"], capsys)
        assert code == 0 and data["outcome"] == "done"
        assert net.calls[0]["url"].endswith("/api/external/wechat/article-delete")
        assert net.calls[0]["body"] == {"article_id": "ART1", "confirm": True, "index": 0}
        assert "新链接" in data["hint"]

    def test_删除时断连落unknown提醒先核实别重删(self, net, capsys):
        net.serve(RuntimeError("Connection aborted, RemoteDisconnected"))
        code, data, _ = run_cli(A, ["--delete-published", "--article-id", "ART1", "--confirm"],
                                capsys)
        assert code == 0 and data["outcome"] == "unknown" and "台账" in data["hint"]

    def test_缺article_id时不发请求(self, net, capsys):
        code, data, _ = run_cli(A, ["--delete-published", "--confirm"], capsys)
        assert code == 1 and net.calls == []

    def test_配额查询失败时红线警示照样得说出来(self, net, capsys):
        """警示写在请求之前：查配额这一步挂了，「不可逆 + 每月 4 次」也不能跟着一起消失。"""
        net.serve(FakeResp(502, {"success": False, "error": "服务端炸了"}))
        code, data, err = run_cli(A, ["--mass-send", "--ledger-id", "7", "--to-all"], capsys)
        assert code == 1 and "每自然月只有 4 次" in err and "后台手动群发" in err


# ══════════════ ④ 定时任务（schedule_ops） ══════════════

def _future(hours=24):
    """一个必定在未来、且带 +08:00 的时间串。"""
    return (datetime.now(S.CN_TZ) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


class Test定时时间闸门:
    """run_at 写错的两种事故：忘了时区（早发 8 小时）、写错日期（发早了/发晚了一天）。"""

    def test_没带时区直接拒收并把补好的完整串给出来(self, net, capsys):
        code, data, _ = run_cli(S, ["--submit-publish", "M1", "--at", "2026-08-03 09:00"], capsys)
        assert code == 1 and net.calls == []           # 坏时间连一次请求都不发
        assert "没带时区" in data["error"] and "早 8 小时" in data["error"]
        assert '--at "2026-08-03T09:00:00+08:00"' in data["error"]

    def test_看不懂的时间也不发请求(self, net, capsys):
        code, data, _ = run_cli(S, ["--submit-publish", "M1", "--at", "明早九点"], capsys)
        assert code == 1 and net.calls == [] and "RFC3339" in data["error"]

    def test_压根没给时间时点名要什么(self, net, capsys):
        code, data, _ = run_cli(S, ["--submit-publish", "M1"], capsys)
        assert code == 1 and net.calls == [] and "+08:00" in data["error"]

    def test_过去时刻本地就拒并提示立即发布走别处(self, net, capsys):
        past = (datetime.now(S.CN_TZ) - timedelta(days=1)).replace(microsecond=0).isoformat()
        code, data, _ = run_cli(S, ["--submit-publish", "M1", "--at", past], capsys)
        assert code == 1 and net.calls == []
        assert "已经过去了" in data["error"] and "--publish" in data["error"]

    def test_Z后缀与空格分隔都认(self):
        assert S.parse_run_at("2026-08-03T01:00:00Z").utcoffset() == timedelta(0)
        assert S.parse_run_at("2026-08-03 09:00:00+08:00").utcoffset() == timedelta(hours=8)

    def test_人话时间带年月日星期(self):
        text = S.label(datetime(2026, 8, 3, 9, 0, tzinfo=S.CN_TZ))
        assert "2026年8月3日" in text and "周一" in text and "09:00" in text and "北京时间" in text

    def test_UTC时刻按北京时间念(self):
        """服务端存的是 UTC，念给运营时必须换算——差 8 小时就是差一天早上还是前一天晚上。"""
        assert "8月3日" in S.label(datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc))
        assert "09:00" in S.label(datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc))

    def test_离现在太近要提醒可能错过这一轮(self):
        _, warnings = S.resolve_run_at((datetime.now(S.CN_TZ) + timedelta(seconds=30)).isoformat())
        assert any("每分钟扫一次" in w for w in warnings)


class Test定时提交:
    def test_定时发布的body形状与念给运营的时间(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "job_id": 12}))
        at = _future()
        code, data, _ = run_cli(S, ["--submit-publish", "M1", "--at", at], capsys)
        assert code == 0 and data["outcome"] == "done" and data["job_id"] == 12
        assert net.calls[0]["url"].endswith("/api/external/wechat/schedule")
        assert net.calls[0]["body"] == {"job_type": "publish", "run_at": at,
                                        "payload": {"media_id": "M1"}}
        assert "北京时间" in data["run_at_label"] and data["run_at_label"] in data["hint"]
        assert "不占群发次数" in data["hint"] and "--cancel 12" in data["hint"]

    def test_入队结果未确认时叫人查队列而不是查台账(self, net, capsys):
        """重复入队 = 到点发两次。通用那句「查台账」在这条线上是错的处置。"""
        net.serve(RuntimeError("HTTPSConnectionPool(host='svc'): Read timed out."))
        code, data, _ = run_cli(S, ["--submit-publish", "M1", "--at", _future()], capsys)
        assert code == 0 and data["outcome"] == "unknown"
        assert "--list" in data["hint"] and "重复入队" in data["hint"]

    def test_服务端没回id时不拼出跑不通的取消命令(self, net, capsys):
        net.serve(FakeResp(200, {"success": True}))
        code, data, _ = run_cli(S, ["--submit-publish", "M1", "--at", _future()], capsys)
        assert code == 0 and data["job_id"] is None and "--cancel <id>" in data["hint"]

    def test_定时群发不带confirm一条都不入队只查配额(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "confirmed": False,
                                 "quota_used": 2, "quota_total": 4}))
        code, data, err = run_cli(S, ["--submit-mass", "M1", "--at", _future(), "--to-all"], capsys)
        assert code == 1 and data["outcome"] == "failed"
        assert len(net.calls) == 1                                   # ⛔ 只查配额
        assert net.calls[0]["url"].endswith("/api/external/wechat/mass-send")
        # 预检同样要带 filter：服务端参数校验先于预检
        assert net.calls[0]["body"] == {"media_id": "M1", "filter": {"is_to_all": True},
                                        "confirm": False}
        assert "schedule" not in net.calls[0]["url"]                 # ⛔ 一条队列都没入
        assert data["server"]["quota_used"] == 2
        assert "每自然月只有 4 次" in err and "全部粉丝" in err
        assert data["run_at_label"] in err                           # 到点几号几点也要当面说
        assert "本月已用 X/4" in data["hint"] and "后台手动群发" in data["hint"]

    def test_定时群发时间不合法时连配额都不查(self, net, capsys):
        code, data, _ = run_cli(S, ["--submit-mass", "M1", "--at", "2026-08-03 09:00",
                                    "--to-all"], capsys)
        assert code == 1 and net.calls == []

    def test_定时群发没说发给谁时零请求(self, net, capsys):
        """到点自动执行的任务尤其不能让受众靠默认值兜底——真发的时候人不在场。"""
        code, data, _ = run_cli(S, ["--submit-mass", "M1", "--at", _future()], capsys)
        assert code == 1 and net.calls == [] and "--to-all" in data["error"]

    def test_定时群发带confirm但没写谁拍板的直接拒发(self, net, capsys):
        code, data, _ = run_cli(S, ["--submit-mass", "M1", "--at", _future(), "--to-all",
                                    "--confirm"], capsys)
        assert code == 1 and "问责留痕" in data["error"] and net.calls == []

    def test_定时群发带confirm和note才入队且受众跟着进队列(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "job_id": 31}))
        at = _future()
        code, data, _ = run_cli(S, ["--submit-mass", "M1", "--at", at, "--tag-id", "102",
                                    "--confirm", "--note", "运营张三确认，8月第2条"], capsys)
        assert code == 0 and data["outcome"] == "done" and data["job_id"] == 31
        assert net.calls[0]["body"] == {
            "job_type": "mass_send", "run_at": at,
            "payload": {"media_id": "M1", "filter": {"is_to_all": False, "tag_id": 102}},
            "confirm": True, "note": "运营张三确认，8月第2条"}
        assert "tag_id=102" in data["hint"] and "后台手动群发" in data["hint"]
        assert data["note"] == "运营张三确认，8月第2条"

    def test_群发保护的钉死hint不被队列提示顶掉(self, net, capsys):
        """45028 的处置是「等管理员手机确认」，换成「去查队列」就把话说反了。"""
        net.serve(FakeResp(200, {"success": False, "wechat_errcode": 45028,
                                 "wechat_errmsg": "mass send protect"}))
        code, data, _ = run_cli(S, ["--submit-mass", "M1", "--at", _future(), "--to-all",
                                    "--confirm", "--note", "运营张三确认"], capsys)
        assert code == 0 and data["outcome"] == "unknown"
        assert data["hint"] == W.MASS_PROTECT_HINT


class Test队列查询与撤销:
    QUEUE = {"success": True, "total": 2, "items": [
        {"id": 12, "job_type": "publish", "status": "pending",
         "run_at": "2026-08-03T09:00:00+08:00", "payload": {"media_id": "M1"}},
        {"id": 11, "job_type": "mass_send", "status": "done",
         "run_at": "2026-07-30T10:00:00+08:00", "payload": {"media_id": "M0"}},
    ]}

    def test_list补人话状态与能不能撤(self, net, capsys):
        net.serve(FakeResp(200, self.QUEUE))
        code, data, _ = run_cli(S, ["--list", "--status", "pending"], capsys)
        assert code == 0 and "status=pending" in net.calls[0]["url"]
        assert data["items"][0]["can_cancel"] is True
        assert data["items"][1]["can_cancel"] is False
        assert "2026年8月3日" in data["items"][0]["run_at_label"] and "周一" in data["items"][0]["run_at_label"]
        assert "推送给全部粉丝" in data["items"][1]["job_type_label"]
        assert data["counts"] == {"in_page": 2, "by_status": {"pending": 1, "done": 1},
                                  "mass_send": 1}
        assert data["total"] == 2                     # 顶层字段不被本页统计覆盖

    def test_服务端时间读不懂时如实给null而不是瞎猜(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "items": [
            {"id": 5, "job_type": "publish", "status": "pending", "run_at": "谁知道呢"}]}))
        code, data, _ = run_cli(S, ["--list"], capsys)
        assert code == 0 and data["items"][0]["run_at_label"] is None

    def test_cancel成功(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "cancelled": True}))
        code, data, _ = run_cli(S, ["--cancel", "12"], capsys)
        assert code == 0 and data["outcome"] == "done"
        assert net.calls[0]["url"].endswith("/api/external/wechat/schedule/cancel")
        assert net.calls[0]["body"] == {"id": 12}

    def test_撤不掉时把三种可能和代价都讲清楚(self, net, capsys):
        net.serve(FakeResp(409, {"success": False, "error": "任务已不是 pending"}))
        code, data, _ = run_cli(S, ["--cancel", "12"], capsys)
        assert code == 1 and data["outcome"] == "failed"
        assert "只有还没到点" in data["error"] and "--list" in data["error"]
        assert "上一次取消其实已经成功了" in data["error"]

    def test_四个动作互斥(self, net, capsys):
        with pytest.raises(SystemExit):
            S.main([])


# ══════════════ ⑤ 数据统计（stats_ops） ══════════════

class Test快照聚合:
    """纯函数，不碰网络。快照 payload 的形状由服务端落库决定，这里钉住三件事：
    形状变了不静默算空、维度字段不当指标加、单篇不重复累加。"""

    def test_payload三种形状都收得下(self):
        rows = [{"ref_date": "2026-07-01", "payload": {"list": [{"new_user": 3}, {"new_user": 2}]}},
                {"ref_date": "2026-07-02", "payload": [{"new_user": 4}]},
                {"ref_date": "2026-07-03", "payload": {"new_user": 1}}]
        assert ST.sum_all(ST.daily_totals(rows))["new_user"] == 10

    def test_维度字段不进合计(self):
        """user_source 是来源枚举（0=其他/1=公众号搜索…），相加出来是个看着像人数的垃圾数。"""
        rows = [{"ref_date": "2026-07-01", "payload": {"list": [
            {"user_source": 0, "new_user": 3, "cancel_user": 1},
            {"user_source": 17, "new_user": 2, "cancel_user": 0}]}}]
        total = ST.sum_all(ST.daily_totals(rows))
        assert total == {"new_user": 5, "cancel_user": 1}

    def test_读不懂的payload计不进来也不炸(self):
        rows = [{"ref_date": "2026-07-01", "payload": None},
                {"ref_date": "2026-07-02", "payload": "坏了"},
                {"ref_date": "2026-07-03", "payload": {"new_user": 2}}]
        assert ST.sum_all(ST.daily_totals(rows)) == {"new_user": 2}

    def test_缺字段给null不给零(self):
        picked, missing = ST.pick({"new_user": 5}, ("new_user", "cancel_user"))
        assert picked == {"new_user": 5, "cancel_user": None} and missing == ["cancel_user"]

    def test_单篇同一天以最新快照为准(self):
        """getarticletotaldetail 每天回的是整段历史：照单累加会把同一天算好几遍。"""
        rows = [
            {"ref_date": "2026-07-02", "payload": {"msgid": "1", "title": "标题", "detail_list": [
                {"stat_date": "2026-07-01", "read_user": 100}]}},
            {"ref_date": "2026-07-03", "payload": {"msgid": "1", "title": "标题", "detail_list": [
                {"stat_date": "2026-07-01", "read_user": 130},
                {"stat_date": "2026-07-02", "read_user": 40}]}},
        ]
        series = ST.latest_series(rows)
        assert [r["stat_date"] for r in series] == ["2026-07-01", "2026-07-02"]
        assert series[0]["read_user"] == 130                  # 修订后的值，不是 100 也不是 230
        totals = {}
        for item in series:
            ST.add_metrics(totals, item)
        assert totals["read_user"] == 170

    def test_新口径两层嵌套list里的detail_list也摊得开(self):
        """官方形状是 {"list":[{msgid,title,detail_list:[逐日]}]}——只认一层会把整篇算成空。"""
        rows = [{"ref_date": "2026-07-03", "payload": {"list": [
            {"msgid": "2247", "title": "CPTSD 是什么", "detail_list": [
                {"stat_date": "2026-07-01", "read_user": 200},
                {"stat_date": "2026-07-02", "read_user": 50}]}]}}]
        assert [r["read_user"] for r in ST.latest_series(rows)] == [200, 50]
        assert ST.article_title(rows) == "CPTSD 是什么"        # 标题挂在 detail_list 外层

    def test_费率与均值绝不进求和(self):
        """40%+50%+60%=150% 这种数看着像指标、其实和把 user_source 加起来是同一类垃圾。"""
        totals = {}
        for day in ({"read_user": 100, "read_finish_rate": 0.4, "read_avg_activetime": 30},
                    {"read_user": 300, "read_finish_rate": 0.6, "read_avg_activetime": 50}):
            ST.add_metrics(totals, day)
        assert totals == {"read_user": 400}
        assert "read_finish_rate" in ST.NON_METRIC and "read_avg_activetime" in ST.NON_METRIC

    def test_完成率按阅读人数加权而不是简单平均(self):
        series = [{"read_user": 100, "read_finish_rate": 0.4},
                  {"read_user": 300, "read_finish_rate": 0.6}]
        got = ST.weighted_mean(series, "read_finish_rate")
        assert got["value"] == 0.55 and got["days"] == 2      # 简单平均会算成 0.5
        assert "加权" in got["how"]

    def test_没有权重时退回简单平均但如实说明(self):
        got = ST.weighted_mean([{"read_finish_rate": 0.4}, {"read_finish_rate": 0.6}],
                               "read_finish_rate")
        assert got["value"] == 0.5 and "简单平均" in got["how"]
        assert ST.weighted_mean([{"read_user": 5}], "read_finish_rate") is None

    def test_转化率分母缺失或为零时回null(self):
        assert ST.ratio(5, 0) is None and ST.ratio(5, None) is None and ST.ratio(None, 5) is None
        assert ST.ratio(3, 4) == 0.75


class Test统计CLI:
    USER_ROWS = {"success": True, "items": [
        {"ref_date": "2026-07-01", "stat_type": "getusersummary",
         "payload": {"list": [{"ref_date": "2026-07-01", "user_source": 0,
                               "new_user": 10, "cancel_user": 2}]}},
        {"ref_date": "2026-07-02", "stat_type": "getusersummary",
         "payload": {"list": [{"ref_date": "2026-07-02", "user_source": 0,
                               "new_user": 6, "cancel_user": 4}]}},
    ]}
    # getbizsummary 同属新口径「发表内容」系列，字段名跟着单篇那套走
    BIZ_ROWS = {"success": True, "items": [
        {"ref_date": "2026-07-01", "stat_type": "getbizsummary",
         "payload": {"read_user": 120, "share_user": 8, "zaikan_user": 14,
                     "like_user": 11, "comment_count": 2}},
        {"ref_date": "2026-07-02", "stat_type": "getbizsummary",
         "payload": {"read_user": 80, "share_user": 2, "zaikan_user": 6,
                     "like_user": 4, "comment_count": 1}},
    ]}

    def test_overview逐日相加涨粉与阅读(self, net, capsys):
        net.serve(FakeResp(200, self.USER_ROWS), FakeResp(200, self.BIZ_ROWS))
        code, data, _ = run_cli(ST, ["--overview", "--from", "2026-07-01",
                                     "--to", "2026-07-02"], capsys)
        assert code == 0
        assert "stat_type=getusersummary" in net.calls[0]["url"]
        assert "from=2026-07-01" in net.calls[0]["url"] and "to=2026-07-02" in net.calls[0]["url"]
        assert "stat_type=getbizsummary" in net.calls[1]["url"]
        assert data["followers"] == {"new_user": 16, "cancel_user": 6, "net_user": 10}
        assert data["engagement"]["read_user"] == 200
        assert data["engagement"]["zaikan_user"] == 20
        assert data["engagement"]["collection_user"] is None          # 没这个字段就是 null
        assert data["range"] == {"from": "2026-07-01", "to": "2026-07-02", "days": 2}
        assert [r["ref_date"] for r in data["daily"]] == ["2026-07-01", "2026-07-02"]
        assert data["daily"][0]["net_user"] == 8
        assert data["labels"]["new_user"] == "新增关注人数"

    def test_一行快照都没有时给null并明说别当成零(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "items": []}),
                  FakeResp(200, {"success": True, "items": []}))
        code, data, err = run_cli(ST, ["--overview", "--from", "2026-07-01",
                                       "--to", "2026-07-02"], capsys)
        assert code == 0
        assert data["followers"] == {"new_user": None, "cancel_user": None, "net_user": None}
        assert any("一行快照都没有" in w and "别当成" in w for w in data["warnings"])
        assert "别当成" in err                       # warnings 同时也吼到 stderr

    def test_服务端换了字段名时点名而不是悄悄算零(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "items": [
            {"ref_date": "2026-07-01", "payload": {"新增": 5}}]}),
            FakeResp(200, {"success": True, "items": []}))
        code, data, _ = run_cli(ST, ["--overview", "--from", "2026-07-01",
                                     "--to", "2026-07-02"], capsys)
        assert data["followers"]["new_user"] is None
        assert any("换了字段名" in w for w in data["warnings"])
        assert data["other_fields"]["getusersummary"] == {"新增": 5}   # 不认识的字段也不丢

    def test_区间早于数据起点要说清那段根本没有(self, net, capsys):
        net.serve(FakeResp(200, self.USER_ROWS), FakeResp(200, self.BIZ_ROWS))
        code, data, _ = run_cli(ST, ["--overview", "--from", "2025-06-01",
                                     "--to", "2025-07-01"], capsys)
        assert any("2025-11-01" in w and "不是故障" in w for w in data["warnings"])

    def test_区间含今天要说明天才有数据(self, net, capsys):
        today = datetime.now(ST.CN_TZ).date()
        net.serve(FakeResp(200, self.USER_ROWS), FakeResp(200, self.BIZ_ROWS))
        code, data, _ = run_cli(ST, ["--overview", "--from", str(today), "--to", str(today)],
                                capsys)
        assert any("T+1" in w and "别拿别的指标凑数" in w for w in data["warnings"])

    def test_长区间省略逐日明细但仍给合计(self, net, capsys):
        net.serve(FakeResp(200, self.USER_ROWS), FakeResp(200, self.BIZ_ROWS))
        code, data, _ = run_cli(ST, ["--overview", "--from", "2026-01-01",
                                     "--to", "2026-07-02"], capsys)
        assert data["daily"] is None and "--export" in data["daily_note"]
        assert data["followers"]["new_user"] == 16

    def test_日期形状不对或写反时不发请求(self, net, capsys):
        code, data, _ = run_cli(ST, ["--overview", "--from", "2026/07/01",
                                     "--to", "2026-07-02"], capsys)
        assert code == 1 and net.calls == [] and "YYYY-MM-DD" in data["error"]

        code, data, _ = run_cli(ST, ["--overview", "--from", "2026-07-09",
                                     "--to", "2026-07-02"], capsys)
        assert code == 1 and net.calls == [] and "写反" in data["error"]

    def test_没给区间时说清跨任意区间都行(self, net, capsys):
        code, data, _ = run_cli(ST, ["--overview"], capsys)
        assert code == 1 and net.calls == [] and "跨任意区间" in data["error"]

    # 新口径 getarticletotaldetail 的真实形状：list[] 外层挂 msgid/title，detail_list[] 是逐日
    ARTICLE_ROWS = {"success": True, "items": [
        {"ref_date": "2026-07-03", "msgid": "2247483647", "payload": {"list": [
            {"msgid": "2247483647", "title": "CPTSD 是什么", "detail_list": [
                {"stat_date": "2026-07-01", "read_user": 200, "share_user": 20,
                 "collection_user": 12, "zaikan_user": 30, "like_user": 25,
                 "comment_count": 4, "read_subscribe_user": 7,
                 "read_finish_rate": 0.4, "read_delivery_rate": 0.82,
                 "read_avg_activetime": 63.5, "read_jump_position": 0.55},
                {"stat_date": "2026-07-02", "read_user": 600, "share_user": 5,
                 "collection_user": 3, "zaikan_user": 8, "like_user": 6,
                 "comment_count": 1, "read_subscribe_user": 2,
                 "read_finish_rate": 0.6, "read_delivery_rate": 0.9,
                 "read_avg_activetime": 71.0, "read_jump_position": 0.6}]}]}}]}

    def test_单篇出新口径计数与完成率(self, net, capsys):
        net.serve(FakeResp(200, self.ARTICLE_ROWS))
        code, data, err = run_cli(ST, ["--article", "2247483647"], capsys)
        assert code == 0 and "msgid=2247483647" in net.calls[0]["url"]
        assert "stat_type=getarticletotaldetail" in net.calls[0]["url"]
        assert data["title"] == "CPTSD 是什么" and data["days_covered"] == 2
        assert data["totals"]["read_user"] == 800
        assert data["totals"]["zaikan_user"] == 38 and data["totals"]["like_user"] == 31
        assert data["totals"]["comment_count"] == 5
        # 完成率是微信直接给的字段，按阅读人数加权（简单平均会算成 0.5）
        assert data["averages"]["read_finish_rate"]["value"] == 0.55
        assert "加权" in data["averages"]["read_finish_rate"]["how"]
        assert data["averages"]["read_avg_activetime"]["value"] == round(
            (63.5 * 200 + 71.0 * 600) / 800, 4)
        # ⛔ 费率不许出现在求和口径里
        assert "read_finish_rate" not in data["totals"]
        assert "read_finish_rate" not in data["other_fields"]
        assert data["labels"]["read_finish_rate"] == "阅读完成率"
        assert data["daily"][0]["read_finish_rate"] == 0.4     # 逐日照样看得到
        assert any("阅读完成率" in w and "不是求和" in w for w in data["warnings"])
        assert "阅读完成率" in err

    def test_算不出来的转化率置null而不是硬凑(self, net, capsys):
        net.serve(FakeResp(200, self.ARTICLE_ROWS))
        code, data, _ = run_cli(ST, ["--article", "2247483647"], capsys)
        assert data["rates"]["阅读→分享（人数）"] == round(25 / 800, 4)
        assert data["rates"]["送达→阅读（人数）"] is None       # 新口径不给送达数
        assert data["rates"]["阅读→点开原文（人数）"] is None   # 新口径没有原文页
        assert "read_delivery_rate" in data["rates_note"]

    def test_没给区间也要说清数据起点与T加一(self, net, capsys):
        net.serve(FakeResp(200, self.ARTICLE_ROWS))
        code, data, _ = run_cli(ST, ["--article", "2247483647"], capsys)
        assert any("2025-11-01" in w for w in data["warnings"])
        assert any("T+1" in w for w in data["warnings"])

    def test_单篇查不到时先说三十天窗口再说msgid写错(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "items": []}))
        code, data, _ = run_cli(ST, ["--article", "999"], capsys)
        assert code == 0 and data["totals"]["read_user"] is None
        joined = "｜".join(data["warnings"])
        assert "30 天" in joined and "没有群发过" in joined and "msgid 写错" in joined
        assert "别把「查不到」说成「没人看」" in joined
        # 老文章查空是合法结果这句，任何时候都在（不只是查空的时候）
        assert any("发布后 30 天" in w and "属正常" in w for w in data["warnings"])

    def test_单篇缺msgid不发请求(self, net, capsys):
        code, data, _ = run_cli(ST, ["--article", "  "], capsys)
        assert code == 1 and net.calls == []

    def test_导出落文件并回条数(self, net, tmp_path, capsys):
        out = tmp_path / "sub" / "stats.json"
        net.serve(FakeResp(200, self.USER_ROWS))
        code, data, _ = run_cli(ST, ["--export", "--from", "2026-07-01", "--to", "2026-07-02",
                                     "--stat-type", "getusersummary", "--out", str(out)], capsys)
        assert code == 0 and data["outcome"] == "done" and data["path"] == str(out)
        assert data["counts"] == {"getusersummary": 2}
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["stats"]["getusersummary"][0]["payload"]["list"][0]["new_user"] == 10

    def test_导出为空时说清是没快照不是导错(self, net, tmp_path, capsys):
        out = tmp_path / "empty.json"
        net.serve(FakeResp(200, {"success": True, "items": []}))
        code, data, _ = run_cli(ST, ["--export", "--from", "2026-07-01", "--to", "2026-07-02",
                                     "--stat-type", "getusersummary", "--out", str(out)], capsys)
        assert code == 0 and any("空的" in w for w in data["warnings"])

    def test_统计的5xx照常算失败让人直接重试(self, net, capsys):
        """查询没有「可能已生效」的风险，含糊成 unknown 只会让运营白等。"""
        net.serve(FakeResp(502, {"success": False, "error": "服务端炸了"}))
        code, data, _ = run_cli(ST, ["--overview", "--from", "2026-07-01",
                                     "--to", "2026-07-02"], capsys)
        assert code == 1 and data["outcome"] == "failed"

    def test_三个动作互斥(self, net, capsys):
        with pytest.raises(SystemExit):
            ST.main([])

"""menu_ops.py / article_ops.py / wechat_api.py：服务号运营脚本。

钉四类东西——都是「说错一句话就赔上不可逆代价」的地方：
① **两桶口径**（红线⑤）：请求没发出/微信明确拒绝 = failed exit 1；已发出但结果不明
   （超时/断连/5xx **含 502**/响应读不懂）= unknown exit 0。publish 的 502 报 failed 会
   诱导二次发布，45028 报 failed 会诱导白烧一次月配额。
② **高危动作的 confirm 闸门**：`--delete-published` 无 confirm **一个请求都不发**（假 session
   断言零调用），`--mass-send` 无 confirm 只查配额、绝不带 confirm:true 出门。
③ **红线③**：外部 HTML（class/style/script/iframe）不许灌进正文，且不能误杀属性值里的文案。
④ **draft/update 是整篇替换**：漏给的字段会被清空，所以必须先读回原文再覆盖。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-fuwuhao-operator" / "scripts"))

import article_ops as A          # noqa: E402
import menu_ops as M             # noqa: E402
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
        assert code == 1 and "media_id" in data["error"]

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
        code, data, err = run_cli(A, ["--mass-send", "--ledger-id", "7"], capsys)
        assert code == 1 and data["outcome"] == "failed"
        assert net.calls[0]["body"] == {"article_ledger_id": 7, "confirm": False}
        assert data["server"]["month_used"] == 2
        assert "本月已用 X/4" in data["hint"] and "后台手动群发" in data["hint"]
        assert "每自然月只有 4 次" in err

    def test_带confirm但没写谁拍板的直接拒发(self, net, capsys):
        code, data, _ = run_cli(A, ["--mass-send", "--ledger-id", "7", "--confirm"], capsys)
        assert code == 1 and "问责留痕" in data["error"] and net.calls == []

    def test_带confirm和note才真发(self, net, capsys):
        net.serve(FakeResp(200, {"success": True, "msg_id": "2247483647"}))
        code, data, _ = run_cli(A, ["--mass-send", "--ledger-id", "7", "--confirm",
                                    "--note", "运营张三确认，8月第2条"], capsys)
        assert code == 0 and data["outcome"] == "done" and data["msg_id"] == "2247483647"
        assert net.calls[0]["body"]["confirm"] is True
        assert net.calls[0]["body"]["note"] == "运营张三确认，8月第2条"

    def test_群发保护落unknown而不是失败(self, net, capsys):
        """看到报错就重发正是白烧一次月配额的典型场景。"""
        net.serve(FakeResp(200, {"success": False, "wechat_errcode": 45028,
                                 "wechat_errmsg": "mass send protect"}))
        code, data, _ = run_cli(A, ["--mass-send", "--ledger-id", "7", "--confirm",
                                    "--note", "运营张三确认"], capsys)
        assert code == 0 and data["outcome"] == "unknown"
        assert data["hint"] == W.MASS_PROTECT_HINT

    def test_没给对象时不发请求(self, net, capsys):
        code, data, _ = run_cli(A, ["--mass-send"], capsys)
        assert code == 1 and net.calls == []


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

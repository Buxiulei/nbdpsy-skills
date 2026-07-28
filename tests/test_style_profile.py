"""style_profile.py（每用户风格档案 CLI）回归。全程 stub，绝不打真 API。

盯死三条硬约束：exists 两句话不能串；--put 缺 --base-version 直接报错（不猜版本号）；
409 不重试同一份 body 且 exit 3。外加降级链第 ③ 层（读不到服务 → exit 2）。

server v0.11.0 起另盯四处：base_version 透传优先于本地派生；dropped_keys 非空必须警告；
--versions 分页参数透传；--admin-default 的 403 是「你不是运营老大」不是「服务挂了」（exit 1 不是 2）。

术语（2026-07-26）：role=admin 的运营叫**运营老大**、role=operator 叫**一般用户**、没有个人档案时
跟随的那份叫**默认配置**；「管理员」只指登录管理后台的系统管理员。`admin_default` / `--admin-default`
是接口标识不是称呼，照旧。
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts"))

import pytest

SCRIPT = Path(__file__).parent.parent / "nbdpsy-xiaohongshu-creator" / "scripts" / "style_profile.py"

PROFILE = {
    "visual": {"palette": [{"name": "雾霾蓝灰", "hex": "#A8B5C4"}], "text_color": "#5A6B7B"},
    "density": {"信息密度档位": "默认", "每页文字量": "200–400 字", "每页信息点": "6–10 个",
                "版式档": "满版", "运营原话": "—"},
    "tone": {"emoji_target": "8–14"},
}


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    @property
    def text(self):
        return json.dumps(self._body, ensure_ascii=False)

    def json(self):
        return self._body


def _run(monkeypatch, capsys, argv, responses=None, sender=None, key="k"):
    """跑一次 CLI，返回 (stdout JSON, exit code, stderr, 调用记录)。
    responses 为顺序返回的 _Resp 列表；sender 可自定义（用于抛异常/断言 payload）。"""
    import style_profile
    calls = []
    monkeypatch.setattr(sys, "argv", ["style_profile.py", "--api-base", "https://stub.test"] + argv)
    monkeypatch.setattr(style_profile.nbdpsy_common, "get_secret", lambda k: key)

    def default_sender(method, url, k, payload=None, timeout=30):
        calls.append({"method": method, "url": url, "payload": payload})
        return responses[len(calls) - 1]

    monkeypatch.setattr(style_profile, "send_request", sender or default_sender)
    with pytest.raises(SystemExit) as ei:
        style_profile.main()
    cap = capsys.readouterr()
    out = json.loads(cap.out.strip().splitlines()[-1]) if cap.out.strip() else None
    return out, ei.value.code, cap.err, calls


def _cur(profile=None, version=3):
    """`--put` 发之前那次守卫 GET 的响应（守卫要看当前档案是不是多套，见 test_style_profile_multi）。
    单套档案 → 守卫放行，行为与加守卫之前一致。"""
    return _Resp(200, {"exists": True, "version": version,
                       "profile": PROFILE if profile is None else profile})


def _never_called():
    """记账式 sender：断言「一个请求都没发」时用计数器判，别靠抛异常——
    call() 会把任意异常吞成 Unreachable，抛出来的 AssertionError 会被吃掉，测试假绿。"""
    seen = []

    def sender(method, url, k, payload=None, timeout=30):
        seen.append({"method": method, "url": url, "payload": payload})
        return _Resp(200, {"exists": True, "version": 99, "profile": PROFILE})

    return sender, seen


def _main_ok(monkeypatch, capsys, argv, responses=None, sender=None, key="k"):
    """main() 正常路径不 sys.exit（直接 return），单独包一层。"""
    import style_profile
    calls = []
    monkeypatch.setattr(sys, "argv", ["style_profile.py", "--api-base", "https://stub.test"] + argv)
    monkeypatch.setattr(style_profile.nbdpsy_common, "get_secret", lambda k: key)

    def default_sender(method, url, k, payload=None, timeout=30):
        calls.append({"method": method, "url": url, "payload": payload})
        return responses[len(calls) - 1]

    monkeypatch.setattr(style_profile, "send_request", sender or default_sender)
    style_profile.main()
    cap = capsys.readouterr()
    return json.loads(cap.out.strip().splitlines()[-1]), cap.err, calls


# ---- 硬约束 1：exists 两句话不能说错 ----

def test_get_exists_true_is_his_own_profile(monkeypatch, capsys):
    """exists:true → 「这是你的风格档案（v3）」+ 第 ① 层 + base_version=version。"""
    body = {"exists": True, "version": 3, "source": "manual", "note": "改了配色",
            "updated_at": "2026-07-26T10:00:00", "profile": PROFILE}
    out, err, calls = _main_ok(monkeypatch, capsys, ["--get"], [_Resp(200, body)])
    assert calls[0]["method"] == "GET" and calls[0]["url"].endswith("/api/style-profile")
    assert out["exists"] is True and out["version"] == 3 and out["profile"] == PROFILE
    assert out["base_version"] == 3 and out["layer"] == "user_profile"
    assert out["say"] == "这是你的风格档案（v3），我回读一遍，你确认下"
    assert "你还没有自己的风格档案" not in out["say"]  # 两句话绝不能串
    assert out["trace_line"].startswith("风格档案：v3（本人档案，读取于 ")
    assert "这是你的风格档案（v3）" in err and "第 ① 层" in err


def test_get_exists_false_is_admin_default(monkeypatch, capsys):
    """exists:false → 「你还没有自己的风格档案，先用默认配置，可以吗？」+ 第 ② 层 + base_version=0。

    layer 值 `admin_default` 是接口标识、照旧；面向运营的话术改说「默认配置」（「管理员」这个词
    留给登录管理后台的系统管理员，写进话术会跟它混淆）。"""
    body = {"exists": False, "source": "admin_default", "profile": PROFILE}
    out, err, _ = _main_ok(monkeypatch, capsys, ["--get"], [_Resp(200, body)])
    assert out["exists"] is False and out["layer"] == "admin_default"
    assert out["say"] == "你还没有自己的风格档案，先用默认配置，可以吗？"
    assert "这是你的风格档案" not in out["say"]  # 说成"他的"会让运营误以为默认配置归他了
    assert "管理员" not in out["say"]            # 术语已统一，别让旧说法回潮
    # server 在 exists:false 时不返 version：首次 PUT 必须传 0，不能留空让上层猜
    assert "version" not in body and out["base_version"] == 0
    # 留痕行是创作端 → 审查端的接口，逐字定死（旧写法「管理员默认」由审查端向后兼容识别）
    assert out["trace_line"].startswith("风格档案：v0（默认配置，读取于 ")
    assert "默认配置" in err and "别说成是他的" in err


def test_get_two_sentences_are_mutually_exclusive(monkeypatch, capsys):
    """同一套输入换 exists 布尔，说辞必须整句不同（防止上层复制粘贴串台）。"""
    a, _, _ = _main_ok(monkeypatch, capsys, ["--get"],
                       [_Resp(200, {"exists": True, "version": 1, "profile": PROFILE})])
    b, _, _ = _main_ok(monkeypatch, capsys, ["--get"],
                       [_Resp(200, {"exists": False, "source": "admin_default", "profile": PROFILE})])
    assert a["say"] != b["say"] and a["layer"] != b["layer"] and a["trace_line"] != b["trace_line"]


# ---- 硬约束 2：--put / --rollback 强制 --base-version，绝不猜 ----

def test_put_without_base_version_errors_before_any_request(monkeypatch, capsys, tmp_path):
    """缺 --base-version → exit 4 且**一个请求都不发**（猜版本号会覆盖掉别人的改动）。"""
    import style_profile
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    sender, seen = _never_called()
    out, code, err, _ = _run(monkeypatch, capsys, ["--put", str(f)], sender=sender)
    assert code == style_profile.EXIT_USAGE == 4
    assert seen == [], "缺 --base-version 时绝不该发请求（猜版本号会覆盖别人的改动）"
    assert "--base-version" in err and out is None


def test_rollback_without_base_version_errors(monkeypatch, capsys):
    sender, seen = _never_called()
    _, code, err, _ = _run(monkeypatch, capsys, ["--rollback", "3"], sender=sender)
    assert code == 4 and seen == [] and "--base-version" in err


def test_usage_error_exit_code_is_not_2(tmp_path):
    """子进程实跑：用法错误退 4 —— 2 是「没连上」的专用信号，撞码会让上层误降级。"""
    import subprocess
    env = {"PATH": "/usr/bin:/bin", "NBDPSY_XHS_API_KEY": "k",
           "NBDPSY_SECRETS": str(tmp_path / "none.env"), "NBDPSY_WORKSPACE": str(tmp_path)}
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPT), "--put", str(f)],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 4 and "--base-version" in p.stderr
    # 没指定动作同理
    p2 = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=env)
    assert p2.returncode == 4


def test_put_sends_whole_profile_with_base_version(monkeypatch, capsys, tmp_path):
    """PUT 体 = {base_version, profile 全量, source, note}，整份覆盖不是打补丁。
    （守卫 GET 在前，PUT 是第二个请求；单套档案下守卫放行。）"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    resp = _Resp(200, {"exists": True, "version": 4, "source": "reference_sample",
                       "note": "按参考样本更新", "updated_at": "2026-07-26T11:00:00"})
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--put", str(f), "--base-version", "3",
                                "--source", "reference_sample", "--note", "按参考样本更新"],
                               [_cur(), resp])
    assert [c["method"] for c in calls] == ["GET", "PUT"]
    assert calls[1]["url"].endswith("/api/style-profile")
    body = calls[1]["payload"]
    assert body == {"base_version": 3, "profile": PROFILE,
                    "source": "reference_sample", "note": "按参考样本更新"}
    assert out["version"] == 4 and out["warnings"] == []


def test_put_unwraps_get_envelope(monkeypatch, capsys, tmp_path):
    """喂 --get 的整份输出时自动剥出 profile —— 否则会把 {exists,version,...} 当档案存进去。"""
    f = tmp_path / "envelope.json"
    f.write_text(json.dumps({"exists": True, "version": 3, "layer": "user_profile",
                             "profile": PROFILE}, ensure_ascii=False), encoding="utf-8")
    _, err, calls = _main_ok(monkeypatch, capsys, ["--put", str(f), "--base-version", "3"],
                             [_cur(), _Resp(200, {"exists": True, "version": 4})])
    assert calls[1]["payload"]["profile"] == PROFILE
    assert "exists" not in calls[1]["payload"]["profile"]


def test_put_rejects_empty_profile(monkeypatch, capsys, tmp_path):
    """空对象整份覆盖 = 清空档案 → 本地拒绝（exit 1），不发请求。"""
    f = tmp_path / "empty.json"
    f.write_text("{}", encoding="utf-8")
    sender, seen = _never_called()
    out, code, err, _ = _run(monkeypatch, capsys, ["--put", str(f), "--base-version", "1"],
                             sender=sender)
    assert code == 1 and seen == [] and out["ok"] is False and "清空" in out["error"]


def test_put_warns_when_density_keys_renamed_to_english(monkeypatch, capsys, tmp_path):
    """density 五个中文 key 被改写成英文 → 警告（跨端接口，改名即断链），但不拦截上传。"""
    bad = {"visual": {}, "density": {"level": "默认", "chars_per_page": "200–400 字"}}
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    out, err, calls = _main_ok(monkeypatch, capsys, ["--put", str(f), "--base-version", "0"],
                               [_cur(), _Resp(200, {"exists": True, "version": 1})])
    joined = "；".join(out["warnings"])
    assert "信息密度档位" in joined and "每页文字量" in joined and "中文" in joined
    assert "⚠" in err and calls[1]["payload"]["profile"] == bad  # 只警告不改写用户数据


def test_put_warns_when_density_section_missing(monkeypatch, capsys, tmp_path):
    f = tmp_path / "nod.json"
    f.write_text(json.dumps({"visual": {"text_color": "#000"}}, ensure_ascii=False), encoding="utf-8")
    out, _, _ = _main_ok(monkeypatch, capsys, ["--put", str(f), "--base-version", "0"],
                         [_cur(), _Resp(200, {"exists": True, "version": 1})])
    assert any("density" in w for w in out["warnings"])


# ---- 硬约束 3：409 不重试，exit 3，透出 current_version ----

def _conflict_resp():
    return _Resp(409, {"detail": {"error": "风格档案版本冲突：当前 version=5，请重新读取后再改",
                                  "current_version": 5, "updated_at": "2026-07-26T12:00:00"}})


def test_put_409_does_not_retry_and_exits_3(monkeypatch, capsys, tmp_path):
    import style_profile
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    calls = []

    def sender(method, url, k, payload=None, timeout=30):
        if method == "GET":         # 守卫那次读（单套 → 放行），冲突发生在真正的 PUT 上
            return _cur()
        calls.append(payload)
        return _conflict_resp()

    out, code, err, _ = _run(monkeypatch, capsys,
                             ["--put", str(f), "--base-version", "3"], sender=sender)
    assert len(calls) == 1, "409 后绝不能重发同一份 body"
    assert code == style_profile.EXIT_CONFLICT == 3
    assert out["outcome"] == "conflict"
    assert out["base_version"] == 3 and out["current_version"] == 5
    assert out["updated_at"] == "2026-07-26T12:00:00"
    assert out["say"] == "你的风格档案在别处被改过（v3 → v5），我重新读一遍再改"
    assert "别重试同一份 body" in out["hint"] and "--get" in out["hint"]
    assert "v3 → v5" in err and "重新 --get" in err


def test_rollback_409_does_not_retry_and_exits_3(monkeypatch, capsys):
    calls = []

    def sender(method, url, k, payload=None, timeout=30):
        calls.append(payload)
        return _conflict_resp()

    out, code, _, _ = _run(monkeypatch, capsys,
                           ["--rollback", "3", "--base-version", "7"], sender=sender)
    assert len(calls) == 1 and code == 3 and out["current_version"] == 5
    assert out["base_version"] == 7


def test_conflict_detail_tolerates_flat_body(monkeypatch, capsys, tmp_path):
    """409 体万一不是 {detail:{...}} 也要能捞出 current_version（别把冲突降级成普通报错）。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    resp = _Resp(409, {"current_version": 9})
    out, code, _, _ = _run(monkeypatch, capsys, ["--put", str(f), "--base-version", "2"],
                           sender=lambda m, *a, **k: _cur() if m == "GET" else resp)
    assert code == 3 and out["current_version"] == 9


# ---- 降级链第 ③ 层：读不到服务 → exit 2 + 明说「没连上风格档案服务」 ----

def test_network_failure_exits_2_and_says_offline(monkeypatch, capsys):
    import style_profile

    def boom(*a, **k):
        raise ConnectionError("Max retries exceeded")

    out, code, err, _ = _run(monkeypatch, capsys, ["--get"], sender=boom)
    assert code == style_profile.EXIT_UNREACHABLE == 2
    assert "没连上风格档案服务" in err
    assert out["layer"] == "builtin_fallback" and out["reason"] == "network"
    assert out["say"] == style_profile.SAY_OFFLINE and "内置的默认风格" in out["say"]
    assert out["trace_line"].startswith("风格档案：v—（内置兜底")


def test_missing_key_exits_2_without_request(monkeypatch, capsys):
    """NBDPSY_XHS_API_KEY 是可选凭据：没配也得让运营继续做内容（第 ③ 层），不是致命错。"""
    sender, seen = _never_called()
    out, code, err, _ = _run(monkeypatch, capsys, ["--get"], sender=sender, key=None)
    assert code == 2 and seen == [] and out["reason"] == "no_key"
    assert "没连上风格档案服务" in err and "MISSING:NBDPSY_XHS_API_KEY" in out["error"]


def test_unauthorized_exits_2(monkeypatch, capsys):
    """401 = 这把 key 读不到档案服务 → 同样走第 ③ 层（但 hint 指向重发接入包，不是网络）。"""
    out, code, err, _ = _run(monkeypatch, capsys, ["--get"],
                             sender=lambda *a, **k: _Resp(401, {"detail": "apikey 无效"}))
    assert code == 2 and out["reason"] == "unauthorized"
    assert "没连上风格档案服务" in err and "接入配置包" in out["hint"]


# ---- 其余端点：透传与参数 ----

def test_versions_passthrough(monkeypatch, capsys):
    body = {"versions": [{"version": 2, "source": "manual", "note": "改配色",
                          "created_at": "2026-07-25T09:00:00", "created_by": 7},
                         {"version": 1, "source": "inherited_admin", "note": None,
                          "created_at": "2026-07-20T09:00:00", "created_by": 7}]}
    out, err, calls = _main_ok(monkeypatch, capsys, ["--versions"], [_Resp(200, body)])
    assert calls[0]["url"].endswith("/api/style-profile/versions") and calls[0]["payload"] is None
    assert out == body and "2 个" in err


def test_version_detail_passthrough(monkeypatch, capsys):
    body = {"version": 3, "source": "manual", "note": None, "created_at": "2026-07-24T09:00:00",
            "created_by": 7, "profile": PROFILE}
    out, err, calls = _main_ok(monkeypatch, capsys, ["--version", "3"], [_Resp(200, body)])
    assert calls[0]["url"].endswith("/api/style-profile/versions/3")
    assert out == body and "没动当前档案" in err


def test_version_not_found_exits_1(monkeypatch, capsys):
    out, code, err, _ = _run(monkeypatch, capsys, ["--version", "9"],
                             sender=lambda *a, **k: _Resp(404, {"error": "版本不存在"}))
    assert code == 1 and out["ok"] is False and "404" in out["error"]


def test_rollback_params_and_hint(monkeypatch, capsys):
    """--rollback N --base-version M → POST {to_version:N, base_version:M}，并说清「造新版本」。"""
    resp = _Resp(200, {"exists": True, "version": 8, "source": "rollback", "note": None,
                       "updated_at": "2026-07-26T13:00:00"})
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--rollback", "3", "--base-version", "7"], [resp])
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/api/style-profile/rollback")
    assert calls[0]["payload"] == {"to_version": 3, "base_version": 7}
    assert out["version"] == 8 and out["source"] == "rollback"
    assert "造新版本" in out["hint"] and "再退回去" in out["hint"]
    assert "v8" in err


def test_only_one_action_allowed(monkeypatch, capsys):
    sender, seen = _never_called()
    _, code, err, _ = _run(monkeypatch, capsys, ["--get", "--versions"], sender=sender)
    assert code == 4 and seen == [] and "恰好指定一个动作" in err


# ---- server v0.11.0：base_version 以 server 下发的为准（唯一真源），别再自己派生 ----

def test_get_base_version_prefers_server_value_over_derived(monkeypatch, capsys):
    """server 下发的 base_version 必须压过本地派生。

    这里故意让 base_version(5) ≠ version(3)：只要输出是 5，就证明走的是透传而不是
    「out['base_version'] = view['version']」那条老派生路。派生值一旦与 server 不符，
    下一次 PUT 就会拿错版本号撞 409（甚至覆盖别人的改动）。"""
    body = {"exists": True, "version": 3, "base_version": 5, "profile": PROFILE}
    out, err, _ = _main_ok(monkeypatch, capsys, ["--get"], [_Resp(200, body)])
    assert out["base_version"] == 5 and out["base_version_source"] == "server"
    assert "base_version=5" in err and "server 下发" in err
    assert out["version"] == 3  # 原字段原样透出，没被改写


def test_get_falls_back_to_derived_when_server_omits_base_version(monkeypatch, capsys):
    """老 server 不下发 base_version → 回落派生（exists→version，不 exists→0），并在 stderr 注明来源。"""
    a, err_a, _ = _main_ok(monkeypatch, capsys, ["--get"],
                           [_Resp(200, {"exists": True, "version": 7, "profile": PROFILE})])
    assert a["base_version"] == 7 and a["base_version_source"] == "derived"
    assert "base_version=7" in err_a and "本地派生" in err_a

    b, err_b, _ = _main_ok(monkeypatch, capsys, ["--get"],
                           [_Resp(200, {"exists": False, "profile": PROFILE})])
    assert b["base_version"] == 0 and b["base_version_source"] == "derived"
    assert "本地派生" in err_b


def test_get_exists_false_exposes_admin_default_version(monkeypatch, capsys):
    """exists:false 时把 admin_default_version 一并透出；server 没给则键仍在、值为 None。"""
    body = {"exists": False, "base_version": 0, "admin_default_version": 4,
            "updated_at": "2026-07-26T09:00:00", "profile": PROFILE}
    out, err, _ = _main_ok(monkeypatch, capsys, ["--get"], [_Resp(200, body)])
    assert out["admin_default_version"] == 4 and out["base_version"] == 0
    assert out["base_version_source"] == "server"
    assert "v4" in err
    # 老 server 没给 → 键恒定存在（上层可无条件读），值为 None
    old, _, _ = _main_ok(monkeypatch, capsys, ["--get"],
                         [_Resp(200, {"exists": False, "profile": PROFILE})])
    assert "admin_default_version" in old and old["admin_default_version"] is None


# ---- server v0.11.0：dropped_keys —— 这次覆盖把哪些键冲掉了 ----

def test_put_warns_when_dropped_keys_non_empty(monkeypatch, capsys, tmp_path):
    """非空 = 这次整份覆盖把别的字段冲掉了 → stdout 原样带出 + stderr 人话警告（当场回读给运营）。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    resp = _Resp(200, {"exists": True, "version": 5,
                       "dropped_keys": ["tone", "visual.character_card"]})
    out, err, _ = _main_ok(monkeypatch, capsys,
                           ["--put", str(f), "--base-version", "4"], [_cur(), resp])
    assert out["dropped_keys"] == ["tone", "visual.character_card"]
    assert "本次覆盖丢掉了" in err and "tone" in err and "visual.character_card" in err
    assert "--get" in err  # 指路：先 --get 拿全量再重发


def test_put_empty_dropped_keys_is_silent(monkeypatch, capsys, tmp_path):
    """[] = 没丢，属正常：键照样透出，但绝不能报警（狼来了会让运营以后都不看）。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    out, err, _ = _main_ok(monkeypatch, capsys, ["--put", str(f), "--base-version", "4"],
                           [_cur(), _Resp(200, {"exists": True, "version": 5,
                                                "dropped_keys": []})])
    assert out["dropped_keys"] == [] and "丢掉了" not in err


def test_rollback_warns_when_dropped_keys_non_empty(monkeypatch, capsys):
    """rollback 同样会丢字段（回到老版本 = 后来新增的段没了），一样要警告。"""
    resp = _Resp(200, {"exists": True, "version": 9, "source": "rollback",
                       "dropped_keys": ["visual.text_color"]})
    out, err, _ = _main_ok(monkeypatch, capsys,
                           ["--rollback", "3", "--base-version", "8"], [resp])
    assert out["dropped_keys"] == ["visual.text_color"]
    assert "本次覆盖丢掉了" in err and "visual.text_color" in err


# ---- server v0.11.0：--versions 分页 ----

def test_versions_pagination_params_and_passthrough(monkeypatch, capsys):
    """--limit/--offset 进 query；total/has_more 原样透出，并给出下一页的 offset。"""
    body = {"versions": [{"version": 3, "source": "rollback", "note": "回退到 v1",
                          "created_at": "2026-07-26T11:15:55.101723", "created_by": 1},
                         {"version": 2, "source": "manual", "note": None,
                          "created_at": "2026-07-25T09:00:00", "created_by": 1}],
            "total": 7, "limit": 2, "offset": 4, "has_more": True}
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--versions", "--limit", "2", "--offset", "4"],
                               [_Resp(200, body)])
    url = calls[0]["url"]
    assert "limit=2" in url and "offset=4" in url
    assert out == body and out["total"] == 7 and out["has_more"] is True
    assert "共 7 个" in err and "--offset 6" in err  # 4 + 本页 2 条


def test_versions_without_pagination_sends_no_query(monkeypatch, capsys):
    """不传分页参数就别自作主张塞默认值——服务端默认 50，塞了反而写死了口径。"""
    out, err, calls = _main_ok(monkeypatch, capsys, ["--versions"],
                               [_Resp(200, {"versions": [], "total": 0, "has_more": False})])
    assert calls[0]["url"].endswith("/api/style-profile/versions") and "?" not in calls[0]["url"]
    assert "--offset" not in err  # has_more=False 时不提示翻页


# ---- server v0.11.0：--admin-default（改默认配置，仅运营老大） ----

def test_admin_default_puts_profile_without_base_version(monkeypatch, capsys, tmp_path):
    """body = {profile, note}；**没有 base_version**（这个端点无乐观锁），也不该要求它。"""
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    out, err, calls = _main_ok(monkeypatch, capsys,
                               ["--admin-default", str(f), "--note", "统一莫兰迪三色"],
                               # 守卫先 GET 一次当前默认配置（单套 → 放行），再 PUT
                               [_Resp(200, {"profile": PROFILE}),
                                _Resp(200, {"version": 6, "updated_at": "2026-07-26T14:00:00"})])
    assert [c["method"] for c in calls] == ["GET", "PUT"]
    assert calls[1]["url"].endswith("/api/style-profile/admin-default")
    assert calls[1]["payload"] == {"profile": PROFILE, "note": "统一莫兰迪三色"}
    assert "base_version" not in calls[1]["payload"]
    assert out["version"] == 6
    # 三条语义必须当场说清（运营老大按下去之前得知道波及面）
    assert "任何运营老大都能改" in err                       # ① 谁能改
    assert "没有自己风格档案的人实时跟随" in err              # ② 影响谁
    assert "不只是之后新建的" in err and "立刻跟着变" in err  # ②' 不只影响新建的人
    assert "不受影响" in err                                 # ②'' 有个人档案的不受波及
    assert "rollback 对它无效" in err and "留底" in err       # ③ 不进历史、不可回退


def test_admin_default_403_says_admin_only_and_exits_1(monkeypatch, capsys, tmp_path):
    """403 = 你不是运营老大（是一般用户），**不是**服务挂了：exit 1 且绝不能说「没连上风格档案服务」。

    若混进通用的 401/403 → Unreachable 分支，上层会误判服务不可用而走第 ③ 层内置降级。"""
    import style_profile
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    out, code, err, _ = _run(
        monkeypatch, capsys, ["--admin-default", str(f)],
        # GET /admin-default 一般用户可读（--get-default 就是它），只有 PUT 才 403
        sender=lambda method, *a, **k: (_Resp(200, {"profile": PROFILE}) if method == "GET"
                                        else _Resp(403, {"detail": "需要管理员权限"})))
    assert code == style_profile.EXIT_ERROR == 1
    assert code != style_profile.EXIT_UNREACHABLE
    assert "只有运营老大能改默认配置" in err and "没连上风格档案服务" not in err
    assert out["outcome"] == "forbidden" and out["ok"] is False
    assert "只有运营老大能改默认配置" in out["hint"] and "403" in out["error"]


def test_other_endpoints_403_still_exits_2(monkeypatch, capsys):
    """回归：除 --admin-default 外，403 仍按「这把 key 读不到档案服务」走 exit 2 + 第 ③ 层。"""
    out, code, err, _ = _run(monkeypatch, capsys, ["--get"],
                             sender=lambda *a, **k: _Resp(403, {"detail": "无权限"}))
    assert code == 2 and out["reason"] == "unauthorized"
    assert "没连上风格档案服务" in err and out["layer"] == "builtin_fallback"


def test_stdout_is_pure_json_on_every_path(monkeypatch, capsys, tmp_path):
    """输出契约：stdout **只有一行** JSON，人话一律走 stderr（上层直接 json.loads 全量）。"""
    import style_profile
    f = tmp_path / "p.json"
    f.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    cases = [
        (["--get"], [_Resp(200, {"exists": True, "version": 1, "profile": PROFILE})], None),
        (["--get"], [_Resp(200, {"exists": False, "source": "admin_default", "profile": PROFILE})], None),
        (["--versions"], [_Resp(200, {"versions": []})], None),
        (["--version", "1"], [_Resp(200, {"version": 1, "profile": PROFILE})], None),
        (["--put", str(f), "--base-version", "1"],
         [_cur(), _Resp(200, {"exists": True, "version": 2, "dropped_keys": ["tone"]})], None),
        (["--rollback", "1", "--base-version", "2"],
         [_Resp(200, {"exists": True, "version": 3, "dropped_keys": []})], None),
        (["--versions", "--limit", "1", "--offset", "2"],
         [_Resp(200, {"versions": [], "total": 3, "limit": 1, "offset": 2, "has_more": True})], None),
        (["--admin-default", str(f)],
         [_Resp(200, {"profile": PROFILE}), _Resp(200, {"version": 6})], None),
        (["--put", str(f), "--base-version", "1"], None, 3),   # 409
        (["--get"], None, 2),                                  # 网络挂
        (["--admin-default", str(f)], None, 1),                # 403：不是运营老大
    ]
    for argv, resps, fail_code in cases:
        monkeypatch.setattr(sys, "argv",
                            ["style_profile.py", "--api-base", "https://stub.test"] + argv)
        monkeypatch.setattr(style_profile.nbdpsy_common, "get_secret", lambda k: "k")
        if fail_code == 3:
            # 守卫那次 GET 正常返回（单套 → 放行），409 发生在真正的 PUT 上
            monkeypatch.setattr(style_profile, "send_request",
                                lambda m, *a, **k: _cur() if m == "GET" else _conflict_resp())
        elif fail_code == 2:
            def boom(*a, **k):
                raise ConnectionError("Max retries exceeded")
            monkeypatch.setattr(style_profile, "send_request", boom)
        elif fail_code == 1:
            # GET /admin-default 一般用户可读（--get-default 就是它），只有 PUT 才 403
            monkeypatch.setattr(style_profile, "send_request",
                                lambda m, *a, **k: (_Resp(200, {"profile": PROFILE}) if m == "GET"
                                                    else _Resp(403, {"detail": "需要管理员权限"})))
        else:
            seq = iter(resps)
            monkeypatch.setattr(style_profile, "send_request", lambda *a, **k: next(seq))
        if fail_code:
            with pytest.raises(SystemExit) as ei:
                style_profile.main()
            assert ei.value.code == fail_code
        else:
            style_profile.main()
        out = capsys.readouterr().out
        assert out.count("\n") == 1, f"{argv} 的 stdout 不是单行：{out!r}"
        json.loads(out)  # 整份可解析，没混进人话

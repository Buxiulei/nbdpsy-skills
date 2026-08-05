#!/usr/bin/env python3
"""服务号 REST 公共层：调服务端、把结果按红线⑤的两桶口径转成四态信封。

menu_ops.py / article_ops.py（后续 schedule_ops.py / stats_ops.py 同）共用这一份。
**两桶判据只此一处**——散在各脚本里迟早分叉，而分叉的代价是把「可能已经群发出去了」
说成「失败」，诱导运营再发一次（白烧一次月配额），或把 401 这种明摆着的配置错误
含糊成「可能成功了」。

两桶（口径与 SKILL.md 红线⑤、references/wechat-oa-spec.md 逐字一致）：

  · **结果已确定失败** → `OpFailed` → `{"outcome":"failed"}` **exit 1**
    线索：请求**根本没发出**（缺凭据 / 参数校验不过 / 连接没建起来 / 401 / 403 / 4xx），
    **或**微信明确回了拒绝码（`success:false` + `wechat_errcode`，如 40164/45009/48001/53501）。
    结果是确定的，**不用查台账**，按提示改配置或参数再来。

  · **结果未确认** → `OpUnknown` → `{"outcome":"unknown"}` **exit 0**
    线索：请求**已经发出去了**、但拿不准生效没有——读响应超时 / 连接被断 /
    服务端 5xx（**含 502**，且**没**明说 `sent:false`）/ 响应不是 JSON；
    外加唯一特例 `45028`（群发保护待手机确认）。**先查台账/线上现状核实，绝不自动重试。**

为什么 502 默认落 unknown：服务端的 502 通常意味着「已经替你转给微信了，但没读到回复」，
而发布 / 群发 / 删除三件事都不可逆——报 failed 会诱导 agent 再发一次。

**唯一能把 5xx 判回 failed 的依据是服务端给的 `sent` 判别位**（T4 审查定案）：响应体带
`"sent": false` 时服务端确知请求根本没转到微信，这次一定没生效——此时报 unknown 只会让运营
白查一次必然为空的台账。`sent:true` 或**字段缺失**（旧版服务端）一律仍按 unknown 处置。

调用方只要在**不可逆动作**上传 `irreversible=True`，两桶就自动分流；查询与幂等动作
（草稿增改、素材上传）用默认 False——重跑最多多一份草稿，报 failed 让运营直接重试更省事。
"""
import json
import sys
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common

DEFAULT_TIMEOUT = 60

# 群发保护：微信已经收到群发请求，只是等管理员在手机上按确认——这是**真·结果未确认**，
# 全 skill 家族唯一一个归 unknown 的 errcode。hint 文案由 SKILL.md 钉死，勿改。
MASS_PROTECT_ERRCODE = 45028
MASS_PROTECT_HINT = ("群发保护已触发：请管理员在 30 分钟内于手机微信确认本次群发；"
                     "超时未确认则本次失败。之后以台账/后台核实为准。"
                     "注意：本次已计入本月群发配额（4 次），若管理员超时未确认（实际未发出），"
                     "可请管理员删除对应群发流水校正配额")

# 群发受众与配额话术：**即时群发（article_ops）与定时群发（schedule_ops）共用这一份**。
# 两处各抄一份的下场是「其中一处漏了受众闸门 = 悄悄全员群发」，或配额话术只在一边说全。
QUOTA_CAVEAT = ("台账的月计数**只统计经本系统发的**：运营若在公众平台后台手动群发过，"
                "实际剩余次数可能更少——复述配额时必须把这句一并说出来，"
                "别让运营以为 4 次是精确保证。")


# 结果未确认时的通用处置（红线⑤的三步）。
UNKNOWN_HINT = ("结果未确认：请求已经发出去了，拿不准到底生效没有。① **先查台账/线上现状**"
                "（`article_ops.py --ledger`、`menu_ops.py --get`）；② 确认**确实没生效**"
                "再问过运营手动重来；⛔ 绝不在没核实台账的情况下重跑同一条命令。")

# 「连接压根没建起来」的特征串：命中即请求未发出 → 确定失败（重试安全，且多半是配置/网络要修）。
# 不在这张表里的网络异常（读超时、连接被断、SSL 中途断）一律当**已发出、结果不明**——
# 宁可让运营多查一次台账，也不能把「可能已群发」说成失败。
NOT_SENT_MARKERS = (
    "Host not allowed", "NewConnectionError", "ConnectTimeoutError", "ProxyError",
    "Connection refused", "Name or service not known", "NameResolutionError",
    "Temporary failure in name resolution", "nodename nor servname",
    "No route to host", "Network is unreachable",
    # URL 本身就不合法（--api-base 打错、少了 https://）：requests 在**建连之前**就抛，
    # 这次一定没发出去。归 unknown 只会让运营白查一次必然为空的台账。
    "Invalid URL", "No scheme supplied", "InvalidSchema", "MissingSchema",
)


class OpFailed(Exception):
    """结果已确定失败 → failed 信封 + exit 1。extra 里的字段（wechat_errcode 等）原样透出。"""

    def __init__(self, error: str, **extra):
        super().__init__(error)
        self.error = error
        self.extra = extra

    def envelope(self) -> dict:
        return {"outcome": "failed", "error": self.error, **self.extra}


class OpUnknown(Exception):
    """结果未确认 → unknown 信封 + **exit 0**（真实未知，绝不冒充失败诱导重试）。"""

    def __init__(self, error: str, hint: str = UNKNOWN_HINT, **extra):
        super().__init__(error)
        self.error = error
        self.hint = hint
        self.extra = extra

    def envelope(self) -> dict:
        return {"outcome": "unknown", "error": self.error, "hint": self.hint, **self.extra}


def emit(payload: dict, code: int) -> int:
    """stdout 恒为且只为一份 JSON——消费方可以无脑 json.loads。人话提示走 stderr。"""
    print(json.dumps(payload, ensure_ascii=False))
    return code


def run(action) -> int:
    """脚本主出口：跑 action()（回 `(payload, exit_code)`），异常按两桶转信封。

    兜底那条 except 不是摆设：漏网异常若甩 traceback，stdout 就是零字节，
    消费方 json.loads 当场崩，还看不出发生了什么。
    """
    try:
        payload, code = action()
    except OpFailed as e:
        return emit(e.envelope(), 1)
    except OpUnknown as e:
        return emit(e.envelope(), 0)
    except Exception as e:                     # noqa: BLE001
        return emit({"outcome": "failed",
                     "error": f"未预期的错误（{type(e).__name__}: {e}）——这多半是脚本 bug "
                              "或环境问题，请把这条连同命令一起报给开发。"}, 1)
    return emit(payload, code)


def warn(msg: str):
    """人话提示/警示走 stderr，不污染 stdout 的纯 JSON。"""
    print(msg, file=sys.stderr)


def mass_filter(to_all: bool, tag_id):
    """群发受众 → 微信 `filter`。**不设默认值是有意的。**

    `filter` 在服务端是必填（漏填直接拒），而这条约束的意义就是不让「漏填」等于
    「推给全部粉丝」——群发不可逆，一次手滑就把不该收到的人全推了。
    所以本地要求运营在「全部粉丝」和「某个标签分组」之间明确选一个，且只能选一个。
    """
    if to_all and tag_id is not None:
        raise OpFailed("`--to-all` 和 `--tag-id` 只能给一个：推给**全部粉丝**与只推给**某个标签分组**"
                       "是互斥的受众，同时给了脚本不替你猜。")
    if to_all:
        return {"is_to_all": True}
    if tag_id is not None:
        return {"is_to_all": False, "tag_id": tag_id}
    raise OpFailed("群发必须明确受众，二选一：`--to-all`（推给**全部粉丝**）或 "
                   "`--tag-id <标签id>`（只推给该标签分组）。"
                   "⛔ 不设默认值是有意的——默认成全员群发，一次漏填就把不该收到的人全推了，"
                   "且**不可逆**。先问清运营这条要发给谁。")


def credentials(api_base=None):
    """取 (api_base, key)。缺凭据是「请求根本发不出去」→ 确定失败。"""
    key = nbdpsy_common.get_secret(nbdpsy_common.WECHAT_API_KEY)
    if not key:
        raise OpFailed(
            "缺凭据 NBDPSY_WECHAT_API_KEY：找管理员要「凭据配置包」（生成时勾**微信服务号权限**），"
            "拿到后 `python3 nbdpsy_common.py secret import <配置包文件>` 一键导入。"
            "⛔ 别用 `secret get` 探测凭据（会把密钥打进对话），探测在不在用 `secret ensure`。")
    return (api_base or nbdpsy_common.wechat_api_base()).rstrip("/"), key


def _requests():
    """延迟导入 requests，缺依赖时给人话而不是 ImportError traceback。"""
    try:
        import requests
    except ImportError:
        raise OpFailed("缺少依赖 requests：在仓库根跑一次 `python3 setup.py`，"
                       "或 `pip install requests` 后重试。")
    return requests


def api_error(resp) -> str:
    """服务端错误体转人话。

    注意**不能假定响应是 JSON**：axum 的 413（体积超限）/ 422（字段反序列化失败）回的是
    裸 text/plain，直接 .json() 会抛，把「参数写错了」变成看不懂的解析错误。
    """
    text = (getattr(resp, "text", "") or "")
    try:
        data = resp.json()
        msg = (data.get("error") or data.get("message") or data.get("detail")
               or text[:200]) if isinstance(data, dict) else text[:200]
    except ValueError:
        msg = text[:200] or "（响应体为空）"
    status = getattr(resp, "status_code", 0)
    tail = ""
    if status == 401:
        tail = "（key 失效或已轮换，请管理员重发凭据配置包）"
    elif status == 403:
        tail = "（key 有效但可能没勾 wechat:operate 权限，请管理员补勾，别换 key）"
    elif status == 422:
        tail = "（请求体字段不对：多半是必填字段没给或类型不符）"
    elif status == 413:
        tail = "（请求体超过服务端上限：正文/图片太大，先拆篇或压缩）"
    return f"HTTP {status}: {msg}{tail}"


def sandbox_hint(exc) -> str:
    """网络被拦时给可执行的下一步（Claude 沙盒拦网是已知场景）。"""
    s = str(exc)
    if any(k in s for k in ("Host not allowed", "ProxyError", "Connection refused",
                            "ConnectionError", "timed out", "Max retries")):
        return ("网络请求失败。若在 Claude Code 沙盒内被拦（典型报错 Host not allowed），"
                "先跑 `python3 scripts/nbdpsy_common.py sandbox allow` 写入放行名单并重启 "
                f"Claude Code。原始错误：{s[:200]}")
    return s[:300]


def _net_error(exc, irreversible: bool):
    """网络异常分桶：连接没建起来 = 确定失败；已经发出去了 = 结果未确认。"""
    if irreversible and not any(m in str(exc) for m in NOT_SENT_MARKERS):
        return OpUnknown(f"请求已发出但没读到结果（{type(exc).__name__}: {str(exc)[:200]}）")
    return OpFailed(sandbox_hint(exc))


def _rejected(data: dict):
    """服务端回 200 + success:false。微信明确拒绝 = 确定失败；唯一例外 45028。"""
    errcode = data.get("wechat_errcode")
    errmsg = data.get("wechat_errmsg") or ""
    extra = {k: data[k] for k in ("wechat_errcode", "wechat_errmsg", "hint") if k in data}
    if errcode == MASS_PROTECT_ERRCODE:
        extra.pop("hint", None)     # hint 由本层钉死，不用服务端那份
        return OpUnknown(f"微信 45028：{errmsg or '群发保护，待管理员确认'}",
                         hint=MASS_PROTECT_HINT, **extra)
    if errcode is None:
        # 没有 errcode 说明是服务端自己拒的（如高危动作没带 confirm），不是微信拒的
        return OpFailed(f"服务端拒绝：{data.get('error') or data.get('message') or data}",
                        **extra)
    return OpFailed(f"微信拒绝（errcode {errcode}）：{errmsg or '（无 errmsg）'}", **extra)


def _not_sent(resp) -> bool:
    """5xx 响应体里的 `sent` 判别位：**只有明确 false** 才算「请求没发到微信」。

    字段缺失、值为 null、响应体读不懂，一律**不**算——那是旧版服务端或网关错误页，
    此时必须退回「结果不明」。判据写成 `is False` 而不是 `not data.get("sent")`：
    后者会把缺失也当成没发出去，等于把「可能已经群发了」说成确定没发，正好搞反最贵的那一侧。
    """
    try:
        data = resp.json()
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("sent") is False


def read_response(resp, irreversible: bool = False) -> dict:
    """HTTP 响应 → 服务端 JSON；按两桶把各类败相转成 OpFailed / OpUnknown。"""
    status = getattr(resp, "status_code", 0)
    if status >= 500:
        msg = api_error(resp)
        # 查询与幂等动作：5xx 没有「可能已生效」的风险，如实报失败让运营直接重试
        if not irreversible:
            raise OpFailed(msg)
        # 不可逆动作：服务端在 5xx 体里带 `sent` 判别位（T4 审查定案）——
        # sent=false 说明请求根本没转到微信，这次确定没生效，含糊成 unknown 只会让运营
        # 白查一次必然为空的台账；sent=true 或字段缺失（旧版服务端）则一律按「已发出、
        # 结果不明」处置：宁可多查一次台账，也不能报 failed 诱导二次发布。
        if _not_sent(resp):
            raise OpFailed(f"{msg}——服务端判定请求**没有发到微信**（sent=false），"
                           "本次确定没生效、也没有半成品，**不用查台账**，按上面的错误改完再来。")
        raise OpUnknown(f"服务端 {status}，这次到底生效没有拿不准：{msg}")
    if status >= 400:
        # 4xx：鉴权/参数没过，服务端**没有**执行任何动作 → 确定失败
        raise OpFailed(api_error(resp))
    try:
        data = resp.json()
    except ValueError:
        text = (getattr(resp, "text", "") or "")[:200]
        msg = f"响应不是 JSON（HTTP {status}）：{text}"
        if irreversible:
            raise OpUnknown(f"{msg}——读不懂回复，这次到底生效没有拿不准")
        raise OpFailed(msg)
    if isinstance(data, dict) and data.get("success") is False:
        raise _rejected(data)
    if not isinstance(data, dict):
        raise OpFailed(f"响应不是 JSON 对象（HTTP {status}）：{str(data)[:200]}")
    return data


def request_json(method: str, url: str, key: str, payload=None,
                 timeout=DEFAULT_TIMEOUT, irreversible: bool = False) -> dict:
    """带 Bearer 鉴权调服务端 REST。唯一打网络的地方——单测 monkeypatch 这里。"""
    requests = _requests()
    try:
        resp = requests.request(method, url, json=payload,
                                headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
    except Exception as e:                     # noqa: BLE001 —— requests 异常族很杂，统一分桶
        raise _net_error(e, irreversible)
    return read_response(resp, irreversible)


def proxy_call(api_base: str, key: str, path: str, body=None,
               timeout=DEFAULT_TIMEOUT, irreversible: bool = False) -> dict:
    """受控透传：菜单/草稿/素材/统计都走它，服务端注入 token。返回**微信原始 JSON**。

    path 必须在服务端白名单内，否则 403（发布/群发/删除走各自的专门端点，透传不给过）。
    """
    data = request_json("POST", f"{api_base}/api/external/wechat/proxy", key,
                        {"path": path, "body": body if body is not None else {}},
                        timeout, irreversible)
    inner = data.get("data")
    return inner if isinstance(inner, dict) else data


# ── 永久图片素材上传（贴图/图片消息用）────────────────────────────────────
# 封面 thumb 的上传住在 md2wechat.py（编译链路的一环）；这里是给**贴图（newspic）**用的
# image 类型——贴图的图不进正文 HTML，直接以 media_id 列表进 image_info，与编译链路无关。
IMAGE_MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
MAX_MATERIAL_BYTES = 10 * 1024 * 1024   # material/add_material?type=image 微信侧上限 10MB


def upload_material_image(api_base: str, key: str, path,
                          timeout=DEFAULT_TIMEOUT) -> str:
    """传一张永久图片素材，返回 media_id。上传是幂等的（重传只是多占一张素材），
    失败一律按确定失败处理（OpFailed），直接重试安全。"""
    p = Path(path)
    if not p.is_file():
        raise OpFailed(f"图片文件不存在：{p}")
    mime = IMAGE_MIMES.get(p.suffix.lower())
    if not mime:
        raise OpFailed(f"图片 {p.name} 不是 jpg/png——微信素材只收这两种，先转格式再来。")
    data = p.read_bytes()
    if not data:
        raise OpFailed(f"图片文件是空的：{p}")
    if len(data) > MAX_MATERIAL_BYTES:
        raise OpFailed(f"图片 {p.name} 有 {len(data) / 1024 / 1024:.1f}MB，"
                       "超过微信永久素材 10MB 上限——先压缩再来，别硬传。")
    requests = _requests()
    try:
        resp = requests.post(f"{api_base}/api/external/wechat/upload-material?type=image",
                             headers={"Authorization": f"Bearer {key}"},
                             files={"file": (p.name, data, mime)}, timeout=timeout)
    except Exception as e:                     # noqa: BLE001 —— 同 request_json，统一分桶
        raise _net_error(e, False)
    payload = read_response(resp)
    media_id = payload.get("media_id")
    if not isinstance(media_id, str) or not media_id:
        raise OpFailed(f"服务端响应缺 media_id：{json.dumps(payload, ensure_ascii=False)[:200]}")
    return media_id

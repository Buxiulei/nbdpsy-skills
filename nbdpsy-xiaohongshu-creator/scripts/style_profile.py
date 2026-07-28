#!/usr/bin/env python3
"""读写「当前运营的风格档案」（经 nbdpsy-api，纯 REST，共 6 个端点）。

风格档案 = 每个运营**自己**的一份视觉 / 语气 / 结构 / 密度设定：创作端按它写绘图提示词，
审查端按它判。现在写死在 skill 里的莫兰迪三色 + 固定人物卡那一套，只是**默认配置**，
不是全局常量——别的运营可以与它完全不同（多号矩阵各有调性）。

用法：
    python3 style_profile.py --get                          # 读当前档案（**先看 exists**）
    python3 style_profile.py --versions [--limit 50] [--offset 0]   # 列历史版本（不含 profile 全文）
    python3 style_profile.py --version 3                    # 取某一版完整内容（回退前预览；多套时是整份容器）
    python3 style_profile.py --put profile.json --base-version 3
        [--source manual|reference_sample|inherited_admin] [--note "按参考样本 8 张实测更新"]
    python3 style_profile.py --rollback 3 --base-version 7  # 回到 v3 的内容（会落成新版本 v8）
    python3 style_profile.py --get-default                  # 只读默认配置（改它之前先用这个留底）
    python3 style_profile.py --admin-default profile.json [--note "..."]
        # **仅运营老大**（role=admin）：整份覆盖「默认配置」（没有个人档案的运营实时跟随它）

一个运营可以有**多套**风格（图文一套、文字版一套、水墨风一套……），下面这些是多套的入口：

    python3 style_profile.py --list-profiles                # 有几套：名字 / 形态 / 哪套是默认
    python3 style_profile.py --get --profile 文字版          # 只取「文字版」那一套
    python3 style_profile.py --get --kind typeset           # 取「文字版形态」下在用的那套
    python3 style_profile.py --version 3 --profile 文字版    # 取**某一版里的**那一套（审查端按留痕行回溯用）
    python3 style_profile.py --version 3 --kind typeset      # 同上，按形态取
    python3 style_profile.py --new-profile 水墨风 --kind carousel --base-version 3
        [--from 图文 | --file 拆解产物.json]                 # 新建一套（默认拿骨架，也可复制/喂 JSON）
    python3 style_profile.py --set-active 文字版 --base-version 4      # 切默认用哪套
    python3 style_profile.py --rename-profile 水墨风 国风 --base-version 5
    python3 style_profile.py --delete-profile 水墨风 --base-version 6  # 删到只剩一套时**拒绝**

凭据：NBDPSY_XHS_API_KEY（与发布线同一把）、NBDPSY_XHS_API_BASE（可选，默认 https://mcp.nbdpsy.com），
由 nbdpsy_common 三层解析（环境变量 > workspace/.env > 用户级 secrets.env）。
**这把 key 是可选凭据**——没配的运营照样要能做内容，见下面 exit 2。

三条硬约束（说错 / 做错就会把运营的档案搞坏，逐条对照）：

1. **`--get` 先看 `exists` 再说话**：`true` = 这是他自己的档案（回读请他确认）；
   `false` = 他还没有，`profile` 是**默认配置**（要问「先用默认配置，可以吗？」）。
   两句话已按契约逐字写进输出的 `say` 字段与 stderr，**直接照念，别自行改写**——
   说错会让运营以为默认配置已经是他自己的档案了。
2. **`--put` 是整份覆盖不是打补丁**：先 `--get` 拿全量 → 改完整体回传；只发被改的字段会把
   其余字段清空。所以 `--put` / `--rollback` **强制要求 `--base-version`**，不传直接报错，
   绝不替你猜版本号（`exists:false` 时传 0）。
   ⚠️ **有多套的运营不能走「`--get` → 改 → `--put`」**：`--get` 只给 active 那**一套的内容**，
   拿它整份覆盖会把其余几套永久抹掉。`--put` 现在**发之前先 GET 一次**，撞上这种 body 直接
   拒绝（exit 1，连 PUT 都不发）——见 `guard_flat_put_over_multi`。多套请用
   `--version <当前版本>` 取整份、改完再 `--put`。
3. **收到 409 别重试同一份 body**：说明档案在别处被改过了。本脚本收到 409 只报不重发，
   并把服务端 `detail.current_version` 原样透出，请按它提示运营重新 `--get` 后再改。

另有两条（server v0.11.0 起）：

- **`base_version` 以 server 下发的为准**：`GET` 无论有没有档案都带 `base_version`（无档案给 0），
  这是「下一次 PUT 该传什么」的唯一真源，本脚本**直接透传**；只有 server 没给（老版本）才回落到
  本地派生，并在 stderr 注明来源（输出里的 `base_version_source` 是 `server` 还是 `derived`）。
- **`--put` / `--rollback` 之后必须看 `dropped_keys`**：server 会算出这次整份覆盖比上一版少掉的键
  （只比顶层 + 二级，`[]` = 没丢）。非空多半是「只带了 visual 就发上去」，把别的段冲掉了——
  stderr 会人话警告，请**当场回读给运营确认**再往下走。服务端不拦截，东西已经存了。

多套档案的三条铁律（2026-07-28，服务端零改动——多套是在 `profile` JSON **内部**实现的）：

1. **没有 `schema: "profiles-v1"` 键 = 老的平铺单套格式**：一律读成一套「图文」（kind=carousel），
   ⛔ **绝不自动写回**（写回会平白造一个新版本、还甩一堆 dropped_keys 警告吓到运营）。
   只有运营明确要新建 / 改名 / 删 / 切默认时才做一次真正的迁移写入，**写之前先把要发生的事说清楚**。
2. **`--get` 不带 `--profile` / `--kind` 时行为与多套化之前完全一致**：老格式原样返回，
   新格式返回 `active` 那一套的内容。创作端、审查端、guide、pipeline 四处都按这个读，改了全断。
3. **`kind` 只有两个合法值**：`carousel`（图文轮播，AI 生图，有 visual/density）、
   `typeset`（文字版，脚本渲染，有 typeset 段）。`tone` / `structure` 两种形态都有。
   跟运营说话时说「**图文那套**」「**文字版那套**」，别说 carousel/typeset（他们不懂）。

⚠️ `profile` 服务端**原样存取、不校验语义**；其中 density 的五个 key 是**中文**
（信息密度档位 / 每页文字量 / 每页信息点 / 版式档 / 运营原话），v1.37.0 起创作端与审查端
都按这五个中文 key 读写，**改写成英文即断链**。`--put` 前会做一次提醒式检查（只警告不拦截）。

输出契约：stdout 纯 JSON、stderr 人话。exit 码：
    0 = 成功
    1 = 服务端明确报错（400 profile 超 64KB / 404 该版本不存在 / `--admin-default` 非运营老大 403 /
        其它 4xx·5xx）或本地入参不合法
    2 = **读不到风格档案服务**（没配 key / 网络不可达 / 超时 / 401·403 鉴权失败；
        `--admin-default` 的 403 例外——那是「你不是运营老大」不是服务挂了，走 exit 1）——
        stderr 明说「没连上风格档案服务」，上层据此走三层降级的第 ③ 层：
        用 skill 内置默认风格（默认配置）继续，并**显式告知运营**，不许静默降级
    3 = 409 版本冲突（不重试；stdout 带 current_version）
    4 = 用法错误（如 --put 缺 --base-version）。刻意不用 argparse 默认的 2——
        2 已被征用作「没连上」信号，用法错误若也回 2，上层会误判服务挂了而降级

`--get` 会在服务端字段之外补几个字段：`base_version`（直接拿去 --put/--rollback 的版本号，
**优先透传 server 下发的值**，老 server 没给才本地派生）、`base_version_source`（`server` / `derived`，
标明上一项从哪来）、`layer`（落在降级链哪一层）、`say`（照念的那句话）、`trace_line`（写进
00-overview.md 的留痕行——审查端按这一行指定的版本判，不按当前最新版；档案会变还能回退，
拿新版判老批次必错）。`exists:false` 时还会透出 `admin_default_version`（正在用默认配置的哪一版；
老 server 没给则为 null）。

⚠️ 术语（2026-07-26 起）：`role=admin` 的运营叫**运营老大**、`role=operator` 叫**一般用户**、
没有个人档案时跟随的那一份叫**默认配置**（它是一份独立配置，不等于任何一个运营老大的个人档案）。
「管理员」一词留给登录 NBDpsy 管理后台的**系统管理员**，别用来指代运营老大。
`--admin-default` / `admin_default_version` / `layer: "admin_default"` 是**接口标识不是称呼**，
保持原样（改了即断链）。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common

EXIT_ERROR = 1
EXIT_UNREACHABLE = 2  # 读不到档案服务 → 上层走第 ③ 层降级
EXIT_CONFLICT = 3     # 409：别重试同一份 body
EXIT_USAGE = 4        # 用法错误（不占用 2）

# 这四句是契约逐字定死的说辞，改字即违约（会让运营误判档案归属 / 静默降级）
SAY_EXISTS = "这是你的风格档案（v{version}），我回读一遍，你确认下"
SAY_MISSING = "你还没有自己的风格档案，先用默认配置，可以吗？"
SAY_OFFLINE = ("没连上风格档案服务，本次用 skill 内置的默认风格（默认配置）继续；"
               "等下次连上再核对")
SAY_CONFLICT = "你的风格档案在别处被改过（v{base} → v{current}），我重新读一遍再改"

# v1.37.0 起创作端与审查端都按这五个**中文** key 读写 profile.density，改写成英文即断链
DENSITY_KEYS = ["信息密度档位", "每页文字量", "每页信息点", "版式档", "运营原话"]

# 与服务端 MAX_PROFILE_BYTES 一致：超限服务端报 400 而非静默截断（截断出来的是坏档案）
MAX_PROFILE_BYTES = 64 * 1024


class _Parser(argparse.ArgumentParser):
    """用法错误退 EXIT_USAGE(4) 而非 argparse 默认的 2——2 是「没连上风格档案服务」的专用信号，
    用法错误若也回 2，上层会误以为服务挂了而走内置兜底。"""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: 用法错误: {message}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


class Unreachable(Exception):
    """读不到档案服务（缺 key / 网络 / 鉴权）→ exit 2，上层走第 ③ 层内置兜底。"""

    def __init__(self, reason: str, error: str, hint: str):
        super().__init__(error)
        self.reason = reason
        self.error = error
        self.hint = hint


class Forbidden(Exception):
    """403 且调用方声明「这个端点本就分权限」（目前只有 --admin-default）→ exit 1 的专门提示。
    **不能混进 Unreachable**：那会说成「没连上风格档案服务」并触发第 ③ 层降级，
    而真相是服务好好的、只是这个人不是运营老大（是一般用户）。"""

    def __init__(self, error: str):
        super().__init__(error)
        self.error = error


class Conflict(Exception):
    """409：base_version 与服务端当前 version 不符 → exit 3。**绝不重试同一份 body**。"""

    def __init__(self, current_version, updated_at, error: str):
        super().__init__(error)
        self.current_version = current_version
        self.updated_at = updated_at
        self.error = error


def send_request(method: str, url: str, key: str, payload=None, timeout=30):
    """带 Bearer 鉴权调 nbdpsy-api（与 publish_note.send_request 同款）。
    网络异常向上抛，由 call() 统一转成「没连上风格档案服务」。"""
    import requests
    return requests.request(method, url, json=payload,
                            headers={"Authorization": f"Bearer {key}"}, timeout=timeout)


def api_error(resp) -> str:
    """nbdpsy-api 错误体：401/422/409 键是 detail（409 的 detail 是 dict），其余是 error。"""
    try:
        data = resp.json()
        msg = data.get("error") or data.get("detail") or resp.text[:200]
    except Exception:
        msg = resp.text[:200]
    if isinstance(msg, dict):
        msg = msg.get("error") or json.dumps(msg, ensure_ascii=False)
    return f"HTTP {resp.status_code}: {msg}"


def conflict_detail(resp) -> dict:
    """409 体是 {"detail": {error, current_version, updated_at}}；detail 缺失时退回顶层。"""
    try:
        data = resp.json()
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    detail = data.get("detail")
    return detail if isinstance(detail, dict) else data


def sandbox_hint(exc) -> str:
    """网络被拦时给 agent 可执行的下一步（Claude 沙盒拦网是已知场景）。"""
    s = str(exc)
    if any(k in s for k in ("Host not allowed", "ProxyError", "Connection refused",
                            "ConnectionError", "timed out", "Max retries")):
        return ("网络请求失败。若在 Claude Code 沙盒内被拦（典型报错 Host not allowed），"
                "先跑 `python3 scripts/nbdpsy_common.py sandbox allow` 写入放行名单并重启 "
                "Claude Code。"
                f"原始错误：{s[:200]}")
    return s[:300]


def call(method: str, path: str, key: str, api_base: str, payload=None, timeout=30,
         forbidden_is_permission=False) -> dict:
    """调一次端点（**不含任何重试**）。网络/鉴权失败 → Unreachable；409 → Conflict；
    其它 4xx·5xx → ValueError。成功返回解析后的 dict。

    `forbidden_is_permission=True` 只给本就分权限的端点用（--admin-default）：那里的 403
    是「你不是运营老大」，要 Forbidden → exit 1；其余端点的 403 仍按「这把 key 读不到档案服务」
    走 Unreachable → exit 2 + 第 ③ 层降级，口径不动。"""
    url = f"{api_base}{path}"
    try:
        resp = send_request(method, url, key, payload, timeout)
    except ModuleNotFoundError as e:
        raise Unreachable("no_requests", str(e),
                          "缺 Python 依赖 requests：pip install requests 后重试") from e
    except Exception as e:
        raise Unreachable("network", sandbox_hint(e),
                          "网络或沙盒拦截：跑 nbdpsy_common.py sandbox allow 后重启 Claude 再试") from e
    if resp.status_code == 403 and forbidden_is_permission:
        raise Forbidden(api_error(resp))
    if resp.status_code in (401, 403):
        raise Unreachable("unauthorized", api_error(resp),
                          "apikey 无效/已轮换或无此权限：找系统管理员重发「运营接入配置包」，"
                          "secret import 导入后重试")
    if resp.status_code == 409:
        d = conflict_detail(resp)
        raise Conflict(d.get("current_version"), d.get("updated_at"),
                       d.get("error") or api_error(resp))
    if resp.status_code >= 400:
        raise ValueError(api_error(resp))
    return resp.json() if resp.text.strip() else {}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def decorate_get(view: dict) -> dict:
    """给 GET 结果补 base_version / base_version_source / layer / say / trace_line，
    见模块 docstring 末段。

    base_version 自 server v0.11.0 起**由 server 无条件下发**（无档案给 0），那是唯一真源，
    这里直接透传；只有老 server 没给时才回落到本地派生（exists→version、不 exists→0）。"""
    out = dict(view)
    server_base = view.get("base_version")
    if view.get("exists"):
        v = view.get("version")
        derived_base = v
        out["layer"] = "user_profile"          # 三层降级链第 ① 层：他自己的档案
        out["say"] = SAY_EXISTS.format(version=v)
        out["trace_line"] = f"风格档案：v{v}（本人档案，读取于 {_today()}）"
    else:
        # 没有个人档案时服务端把「当前版本」记作 0，首次 PUT 就传 base_version=0
        derived_base = 0
        # 第 ② 层：默认配置，**别说成是他的**（"admin_default" 是接口值不是称呼，别改）
        out["layer"] = "admin_default"
        out["say"] = SAY_MISSING
        # 留痕行是创作端 → 审查端的接口，逐字定死（2026-07-26 前的旧批次写的是「管理员默认」，
        # 审查端仍按默认配置识别）
        out["trace_line"] = f"风格档案：v0（默认配置，读取于 {_today()}）"
        # 用的是默认配置的哪一版；老 server 没给就是 null（键恒定存在，上层可无条件读）
        out["admin_default_version"] = view.get("admin_default_version")
    if isinstance(server_base, int) and not isinstance(server_base, bool):
        out["base_version"] = server_base
        out["base_version_source"] = "server"
    else:
        out["base_version"] = derived_base
        out["base_version_source"] = "derived"
    return out


def offline_view(exc: Unreachable, want=None) -> dict:
    """第 ③ 层：读不到服务时的输出。带 say/trace_line，好让上层照说、照留痕，不静默降级。

    `want` = 这次点名要的那一套（只有 `--get --profile/--kind` 会有）。**必须带进留痕行**——
    审查端把「没有套名的留痕行」当存量批次按「图文」判，文字版的批次留一行没名的就会被判错套。"""
    tail = f"{want} " if want else ""
    return {"ok": False, "exists": None, "layer": "builtin_fallback", "reason": exc.reason,
            "error": exc.error, "hint": exc.hint, "say": SAY_OFFLINE,
            "trace_line": f"风格档案：{tail}v—（内置兜底，读取于 {_today()}）"}


#: 三条读命令各有各的信封，里面那层 `profile` 才是档案本体。
#: 运营（和 agent）拿 stdout 存成文件再喂回来是最自然的操作，**三种都要认**——
#: 只认 --get 的话，--get-default 的留底与 --version 取的整份连壳发上去，
#: version/source 这些字段会被当成档案存进去，而且看不出来。
_ENVELOPE_MARKS = (
    ("exists",),                    # --get
    ("admin_default_version",),     # --get-default
    ("version", "source"),          # --version N
)


def unwrap_envelope(data: dict):
    """认出三条读命令的信封并剥出里面的 profile。返回 (profile, 来源说明或 None)。"""
    if not isinstance(data.get("profile"), dict):
        return data, None
    for marks in _ENVELOPE_MARKS:
        if all(m in data for m in marks):
            return data["profile"], "/".join(marks)
    return data, None


def load_profile(path) -> dict:
    """读 --put / --admin-default 的 JSON。两道防呆（都是会把真档案冲掉且运营看不出来的场景）：
    喂了任意一条读命令的整份输出时自动剥出 profile；空对象直接拒绝。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是 JSON 对象，不能当 profile 存")
    data, envelope = unwrap_envelope(data)
    if envelope:
        print(f"ℹ 传进来的是读命令的整份输出（信封字段 {envelope}），"
              f"已自动取其中的 profile 再上传", file=sys.stderr)
    if not data:
        raise ValueError(f"{path} 里的 profile 是空对象——整份覆盖会把档案清空，已拒绝")
    return data


def profile_warnings(profile: dict):
    """上传前的提醒（只警告不拦截，服务端本就原样存取不校验语义）。

    多套容器交给 `container_warnings`（它只查「图文」那类套）：容器顶层本来就没有 density 段，
    拿它去查必然报「profile 里没有 density 段」——**每次正确操作都甩一条假警报**，
    运营看几次就再也不看这条警告了（真出事那次也不会看）。"""
    if is_multi(profile):
        return container_warnings(profile)
    w = []
    size = len(json.dumps(profile, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PROFILE_BYTES:
        w.append(f"profile {size} 字节超 {MAX_PROFILE_BYTES} 上限，服务端会报 400（不截断）")
    return w + density_warnings(profile)


def density_warnings(profile: dict):
    """density 五个中文 key 的跨端接口检查（创作端与审查端都按它们读写，改写成英文即断链）。"""
    w = []
    density = profile.get("density")
    if density is None:
        w.append("profile 里没有 density 段：若你把段名改了，创作端与审查端就读不到密度五字段"
                 "（段名与五个中文 key 都是跨端接口）")
    elif not isinstance(density, dict):
        w.append("density 不是对象，创作端与审查端读不到密度五字段")
    else:
        missing = [k for k in DENSITY_KEYS if k not in density]
        if missing:
            w.append("density 缺中文 key：" + "、".join(missing)
                     + "——这五个中文 key 是创作端/审查端的跨端接口，别改写成英文")
    return w


# ---------------------------------------------------------------------------
# 多套风格档案（profiles-v1）。结构见契约；服务端零改动，多套是在 profile JSON 内部实现的。
# 下面这一段**全是纯函数**（进 dict 出 dict，不碰网络），CLI 分支只负责取数与说人话。
# ---------------------------------------------------------------------------

PROFILES_SCHEMA = "profiles-v1"
KIND_CAROUSEL = "carousel"      # 路线①：信息图轮播（AI 生图），有 visual / density
KIND_TYPESET = "typeset"        # 路线②：文字版（脚本渲染），有 typeset 段
KINDS = (KIND_CAROUSEL, KIND_TYPESET)
# 面向运营的说法：**绝不跟运营说 carousel/typeset**（他们不懂），一律说「图文」「文字版」
KIND_CN = {KIND_CAROUSEL: "图文", KIND_TYPESET: "文字版"}
NAME_CAROUSEL = "图文"          # 初始默认两套的名字（老格式迁过来的那套也叫这个）
NAME_TYPESET = "文字版"
# typeset 段的 8 个字段：theme 必填，其余 null = 用主题默认值、不覆盖（见 typeset_longimage.py）
TYPESET_NULLABLE = ["bg", "accent", "accent_soft", "font", "title_font", "indent", "texture"]


def is_multi(profile) -> bool:
    """有 `schema: profiles-v1` 键 = 新的多套格式。

    ⛔ 没有 = 老的平铺单套：只**读**成一套「图文」，**绝不自动写回**——自动写回会平白造一个新版本，
    还会甩一堆 dropped_keys 警告吓到运营。"""
    return isinstance(profile, dict) and profile.get("schema") == PROFILES_SCHEMA


def set_kind(content) -> str:
    """一套的形态。老格式与漏写 kind 的都按「图文」算（路线① 是默认，且存量档案全是它）。"""
    if isinstance(content, dict) and content.get("kind") in KINDS:
        return content["kind"]
    return KIND_CAROUSEL


def profiles_view(profile) -> dict:
    """把任意 profile 读成 `{legacy, active, sets:{名: 内容}}`（**只读**，不改不写回）。

    老格式读成一套「图文」，内容**原样**（刻意不注入 kind：注入了 `--get` 返回的就不是原档案了，
    创作端拿到的 profile 会与今天不一致）。"""
    if is_multi(profile):
        sets = profile.get("profiles")
        sets = dict(sets) if isinstance(sets, dict) else {}
        active = profile.get("active")
        if active not in sets:
            # active 指了个不存在的名字（人工改坏 / 删剩的残留）：退到第一套，别整份读空
            active = next(iter(sets), None)
        return {"legacy": False, "active": active, "sets": sets}
    return {"legacy": True, "active": NAME_CAROUSEL,
            "sets": {NAME_CAROUSEL: profile} if isinstance(profile, dict) else {}}


def select_set(profile, name=None, kind=None) -> dict:
    """挑出一套。`name` 优先；两个都不给 = active 那套（**这就是 `--get` 不带新参数时的老行为**）。

    `kind` 的规则（契约）：先看 active 那套的 kind 对不对得上，对不上就取该 kind 的**第一套**；
    一套都没有 → `content=None`，由上层提示「要不要现在建一套」。
    返回 `{outcome, name, kind, content, active, names, legacy}`。"""
    v = profiles_view(profile)
    sets, active = v["sets"], v["active"]
    base = {"active": active, "names": list(sets.keys()), "legacy": v["legacy"]}
    if name is not None:
        if name in sets:
            return {"outcome": "ok", "name": name, "kind": set_kind(sets[name]),
                    "content": sets[name], **base}
        return {"outcome": "not_found", "name": None, "kind": None, "content": None, **base}
    if kind is not None:
        if active in sets and set_kind(sets[active]) == kind:
            pick = active
        else:
            pick = next((n for n in sets if set_kind(sets[n]) == kind), None)
        if pick is None:
            return {"outcome": "no_kind_match", "name": None, "kind": None, "content": None, **base}
        return {"outcome": "ok", "name": pick, "kind": kind, "content": sets[pick], **base}
    if active is None:
        return {"outcome": "empty", "name": None, "kind": None, "content": None, **base}
    return {"outcome": "ok", "name": active, "kind": set_kind(sets[active]),
            "content": sets[active], **base}


def list_sets(profile) -> dict:
    """`--list-profiles` 的数据面：每套的名字 / 形态 / 是不是默认那套。"""
    v = profiles_view(profile)
    return {"legacy": v["legacy"], "active": v["active"],
            "profiles": [{"name": n, "kind": set_kind(c), "active": n == v["active"]}
                         for n, c in v["sets"].items()]}


def to_multi(profile):
    """**写入前**把 profile 归一成多套容器，返回 `(容器, 是否发生迁移)`。

    ⛔ 只在真要写的时候调——读取一律走 `profiles_view`。迁移 = 把老的平铺内容原样收进「图文」那套，
    内容一个字不改，只是挪了层级（所以这次 PUT 的 dropped_keys 必然非空，属预期，上层要说清）。"""
    if is_multi(profile):
        c = dict(profile)
        sets = c.get("profiles")
        c["profiles"] = dict(sets) if isinstance(sets, dict) else {}
        if c.get("active") not in c["profiles"]:
            c["active"] = next(iter(c["profiles"]), None)
        return c, False
    flat = dict(profile) if isinstance(profile, dict) else {}
    flat["kind"] = KIND_CAROUSEL
    return {"schema": PROFILES_SCHEMA, "active": NAME_CAROUSEL,
            "profiles": {NAME_CAROUSEL: flat}}, True


def typeset_skeleton(tone=None, structure=None) -> dict:
    """「文字版」那套的初始骨架：theme=clean、其余 null（null = 听主题的，不覆盖）；
    tone / structure 沿用图文那套（语气与标题写法跟形态无关，契约定的）。"""
    ts = {"theme": "clean"}
    ts.update({k: None for k in TYPESET_NULLABLE})
    return {"kind": KIND_TYPESET, "typeset": ts,
            "tone": dict(tone) if isinstance(tone, dict) else {},
            "structure": dict(structure) if isinstance(structure, dict) else {}}


def carousel_skeleton(default_profile) -> dict:
    """「图文」那套的初始骨架 = **默认配置那一份**（`--get-default` 返回的），⛔ 别自己编一份。
    默认配置万一自己也是多套格式（运营老大存了个容器进去），取它 active 那套。"""
    picked = select_set(default_profile)["content"]
    out = dict(picked) if isinstance(picked, dict) else {}
    out["kind"] = KIND_CAROUSEL
    return out


def add_set(container: dict, name: str, kind: str, content: dict) -> dict:
    """往容器里加一套（原地改，调用方已持有副本）。重名直接拒——覆盖别人的一套是不可逆的。"""
    sets = container["profiles"]
    if name in sets:
        raise ValueError(f"你已经有一套叫「{name}」的风格了——换个名字，"
                         f"或者直接改那一套（--get --profile {name} 拿全量再 --put）")
    body = dict(content)
    body["kind"] = kind                     # 形态以命令行 --kind 为准（文件里写错了也不听它）
    sets[name] = body
    return container


def set_active_set(container: dict, name: str) -> dict:
    """切默认用哪套。"""
    if name not in container["profiles"]:
        raise ValueError(f"没有叫「{name}」的风格：现有的是 {_names_cn(container)}")
    container["active"] = name
    return container


def rename_set(container: dict, old: str, new: str) -> dict:
    """改名。保持原有顺序（重建一份而不是删了再加，否则改个名就被挪到最后）。"""
    sets = container["profiles"]
    if old not in sets:
        raise ValueError(f"没有叫「{old}」的风格：现有的是 {_names_cn(container)}")
    if new in sets:
        raise ValueError(f"已经有一套叫「{new}」了，换个名字")
    container["profiles"] = {(new if n == old else n): c for n, c in sets.items()}
    if container.get("active") == old:
        container["active"] = new
    return container


def delete_set(container: dict, name: str) -> dict:
    """删一套。⛔ **删到只剩一套时拒绝**——一套不剩的档案等于把运营清空了，而且这一步不可撤销。"""
    sets = container["profiles"]
    if name not in sets:
        raise ValueError(f"没有叫「{name}」的风格：现有的是 {_names_cn(container)}")
    if len(sets) <= 1:
        raise ValueError(f"「{name}」是你最后一套风格了，删掉就一套都不剩——已拒绝。"
                         f"要换风格请直接改这一套（--get 拿全量再 --put），"
                         f"或者先新建一套再删这套")
    del sets[name]
    if container.get("active") not in sets:
        # 删掉的正好是默认那套：默认顺延到剩下的第一套，别留个指向空气的 active
        container["active"] = next(iter(sets))
    return container


def _names_cn(container: dict) -> str:
    return "、".join(container.get("profiles") or {}) or "（一套都没有）"


def shown_sets(profiles) -> str:
    """念给运营听的那串：`图文·默认、水墨风（图文）、文字版`。
    套名本来就叫「图文」时不再缀一遍形态（「图文（图文·默认）」这种话没法听）。"""
    parts = []
    for p in profiles:
        cn = KIND_CN.get(p["kind"], p["kind"])
        label = p["name"] if p["name"] == cn else f"{p['name']}（{cn}）"
        parts.append(label + "·默认" if p["active"] else label)
    return "、".join(parts) or "（一套都没有）"


def container_warnings(container: dict):
    """多套容器上传前的提醒（只警告不拦截）。大小按整份算；density 五个中文 key **只查图文那类套**
    ——文字版没有插画、没有「信息点」，拿 density 去要求它是误报（狼来了会让运营以后都不看）。"""
    w = []
    size = len(json.dumps(container, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PROFILE_BYTES:
        w.append(f"profile {size} 字节超 {MAX_PROFILE_BYTES} 上限，服务端会报 400（不截断）")
    for name, content in (container.get("profiles") or {}).items():
        if set_kind(content) != KIND_CAROUSEL or not isinstance(content, dict):
            continue
        w += [f"「{name}」这套：{m}" for m in density_warnings(content)]
    return w


def guard_flat_put_over_multi(current: dict, new_profile: dict, what=None, recover=None):
    """`--put` 的前置守卫：⛔ 多套档案**绝不允许**被一份只有一套的 body 整份覆盖。

    翻车实录（这条守卫存在的唯一理由）：运营存了 3 套 → 裸 `--get`（它只给 active 那**一套的内容**）
    → 改一个字段 → `--put --base-version 7` → 存档顶层只剩 density/kind/structure/tone/visual，
    `profiles` 键没了、另外两套**永久消失**，命令还 exit 0 报「✓ 已整份覆盖」。
    唯一的信号是事后的 `dropped_keys`，而它给的补救话术「先 --get 拿全量再重发」**恰恰就是
    产生这份坏 body 的那条命令**（死循环）。所以这里在**发 PUT 之前**拦死：raise → exit 1，
    一个 PUT 都不发（服务端不校验语义，发出去就存进去了，没有后悔药）。

    `current` = 一次 `--get` 的结果（decorate_get 后的），`new_profile` = 这次要发的 body。
    只拦「存的是多套、发的是单套」这一种；发整份容器（含 schema/profiles）照旧放行，
    老的平铺单套档案也照旧放行（它本来就只有一套，覆盖不掉别的）。"""
    stored = current.get("profile")
    if not is_multi(stored) or is_multi(new_profile):
        return
    names = list((stored.get("profiles") or {}).keys())
    n = len(names)
    if what:
        # 默认配置那条路径（--admin-default）：它不进版本历史，rollback 救不回来
        who = f"{what}现在有 {n} 套（{'、'.join(names) or '—'}）"
        how = recover
    elif current.get("exists"):
        who = f"你有 {n} 套（{'、'.join(names) or '—'}）"
        how = (f"用 `--version {current.get('base_version')}` 取整份"
               f"（拿输出里的 `profile` 那一层：schema / active / profiles 三个键）")
    else:
        # 还没有个人档案、正跟随默认配置：他看到的那几套来自默认配置，发一份单套照样只剩一套
        who = f"你现在跟随的默认配置有 {n} 套（{'、'.join(names) or '—'}）"
        how = "用 `--get-default` 取整份（拿输出里的 `profile` 那一层）"
    loss = (f"其余 {n - 1} 套会被抹掉" if n > 1
            else "多套结构（schema / active / profiles）会被打平回老的单套格式")
    raise ValueError(
        f"{who}，这份 body 只有一套——直接发会整份覆盖掉那个多套容器，{loss}，**已拒绝**"
        f"（一个 PUT 都没发）。要改其中一套：{how}，改完再 `--put`。"
        f"⛔ 别再拿 `--get` 的输出去 `--put`：它给的只是默认那一套的内容，"
        f"发上去就是刚才被拦下的这个后果。")


def load_set_file(path) -> dict:
    """读 `--new-profile --file` 给的**单套** JSON（参考图拆解产物走这条）。三道防呆：
    喂 `--get` 整份输出时自动剥 profile；喂整份多套容器直接拒（会套娃）；空对象直接拒。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是 JSON 对象，不能当一套风格存")
    if "exists" in data and isinstance(data.get("profile"), dict):
        print("ℹ 传进来的是 --get 的整份输出，已自动取其中的 profile 字段当这一套的内容",
              file=sys.stderr)
        data = data["profile"]
    if is_multi(data):
        raise ValueError(f"{path} 是**整份多套档案**（带 schema / profiles），不是单独一套——"
                         f"--file 只收一套的内容（图文那套是 visual/density/tone/structure，"
                         f"文字版那套是 typeset/tone/structure）")
    if not data:
        raise ValueError(f"{path} 是空对象，不能当一套风格存")
    return data


def _trace_line_named(view: dict, name: str) -> str:
    """带套名的留痕行（审查端按这一行指定的版本判）。格式与老的只差一个套名，别再自行发挥。

    `--version N` 那个端点**不返 `exists`**（它返的本来就是他自己的某一版），此时按版本号写
    「本人档案 vN」——审查端要按留痕行取回的就是这一版，写成 v0（默认配置）会判错。"""
    if view.get("exists") or ("exists" not in view and view.get("version") is not None):
        return f"风格档案：{name} v{view.get('version')}（本人档案，读取于 {_today()}）"
    return f"风格档案：{name} v0（默认配置，读取于 {_today()}）"


def decorate_selection(view: dict, name=None, kind=None) -> dict:
    """`--get --profile` / `--get --kind` 的输出：把 `profile` 换成挑中的那一套，并补
    `profile_name` / `profile_kind` / `active_profile` / `profile_names` / `outcome`。

    没挑中时 `profile: null` + `say` 提示可以新建，并把 layer / trace_line 落到「内置兜底」——
    因为**实际会用内置默认风格**，留痕行必须说实话，否则审查端会拿一套没用过的档案来判。"""
    sel = select_set(view.get("profile"), name=name, kind=kind)
    out = dict(view)
    out["profile"] = sel["content"]
    out["profile_name"] = sel["name"]
    out["profile_kind"] = sel["kind"]
    out["active_profile"] = sel["active"]
    out["profile_names"] = sel["names"]
    out["profiles_legacy"] = sel["legacy"]
    out["outcome"] = sel["outcome"]
    if sel["outcome"] == "ok":
        # say 保持 decorate_get 那两句逐字不动（exists 真假的说辞是契约定死的，别掺套名进去）
        out["trace_line"] = _trace_line_named(view, sel["name"])
        return out
    have = "、".join(sel["names"]) or "（一套都没有）"
    if name is not None:
        out["say"] = f"你的档案里没有「{name}」这一套风格（现有：{have}），要不要现在建一套？"
    else:
        out["say"] = (f"你还没有「{KIND_CN.get(kind, kind)}」那套风格（现有：{have}），"
                      f"这次先用内置默认；要不要现在建一套？")
    out["layer"] = "builtin_fallback"
    out["reason"] = sel["outcome"]
    # 留痕行带上「他要的那一套」的名字：审查端把没套名的行当存量批次按「图文」判，
    # 文字版的批次留一行没名的，就会被拿图文的标准去判
    want = name if name is not None else KIND_CN.get(kind, kind)
    out["trace_line"] = f"风格档案：{want} v—（内置兜底，读取于 {_today()}）"
    return out


def select_and_say(view: dict, name=None, kind=None) -> dict:
    """`--get --profile/--kind` 与 `--version N --profile/--kind` **共用**的这一步：挑套 + 说人话。

    两处必须是同一份实现——各写一遍就会出现两种留痕行 / 两种 outcome，审查端按留痕行取版本再读
    `profile.visual.*`，口径一散就判错套。"""
    view = decorate_selection(view, name=name, kind=kind)
    if view["outcome"] == "ok":
        cn = KIND_CN.get(view["profile_kind"], view["profile_kind"])
        tag = "" if view["profile_name"] == cn else f"（{cn}）"
        print(f"  挑中「{view['profile_name']}」这一套{tag}；"
              f"他共有 {len(view['profile_names'])} 套，默认是"
              f"「{view['active_profile']}」", file=sys.stderr)
    else:
        print(f"· 没挑中任何一套：{view['say']}", file=sys.stderr)
        print("  → 这次会用 skill 内置默认风格；留痕行已按「内置兜底」写，"
              "别写成他的档案（审查端会拿错版本判）", file=sys.stderr)
    if view.get("profiles_legacy"):
        print("  · 他的档案还是老的单套格式，这里**只读不改**（没有写回，版本号没动）",
              file=sys.stderr)
    return view


def warn_dropped_keys(view: dict):
    """PUT / rollback 之后必须看的那一项：server 算出的「这次整份覆盖比上一版少掉的键」
    （只比顶层 + 二级，`[]` = 没丢，键恒定存在）。值原样在 stdout 里透出，这里只补人话警告——
    东西已经存进去了，服务端不拦截，所以非空时要**当场回读给运营确认**。"""
    dropped = view.get("dropped_keys")
    if not isinstance(dropped, list) or not dropped:
        return
    # 补救话术必须跟守卫口径一致：多套的人再去 `--get` 拿"全量"，拿到的还是 active 那一套，
    # 重发一次仍是坏 body（守卫会拦，但运营会以为脚本前后矛盾）。
    if is_multi(view.get("profile")) or any(str(k) in ("schema", "active", "profiles")
                                            for k in dropped):
        how = (f"先 `--version {view.get('version')}` 取整份（拿输出里的 `profile` 那一层）"
               f"把丢掉的补回来，再整份 `--put`")
    else:
        how = "先 `--get` 拿全量再重发"
    print("⚠ 本次覆盖丢掉了：" + "、".join(str(k) for k in dropped)
          + f"——如果不是有意的，{how}", file=sys.stderr)


def _exit_unreachable(exc: Unreachable, want=None):
    """exit 2 的唯一出口：stderr 必须明说「没连上风格档案服务」，供上层走第 ③ 层。"""
    print(f"✗ 没连上风格档案服务（{exc.reason}）：{exc.error}", file=sys.stderr)
    print(f"  → {exc.hint}", file=sys.stderr)
    print(f"  → 请这样告诉运营：{SAY_OFFLINE}", file=sys.stderr)
    print(json.dumps(offline_view(exc, want), ensure_ascii=False))
    sys.exit(EXIT_UNREACHABLE)


def requested_set_name(args):
    """这次点名要的是哪一套（只有 `--get` / `--version N` 配 `--profile/--kind` 才有）。
    降级 / 没挑中时的留痕行要带上它。"""
    if getattr(args, "profile", None):
        return args.profile
    picking = getattr(args, "get", False) or getattr(args, "version", None) is not None
    if getattr(args, "kind", None) and picking:
        return KIND_CN.get(args.kind, args.kind)
    return None


def main():
    ap = _Parser(description="读写当前运营的风格档案（经 nbdpsy-api，6 端点）")
    ap.add_argument("--get", action="store_true",
                    help="读当前档案（先看 exists：true=他自己的；false=默认配置那套）")
    ap.add_argument("--versions", action="store_true", help="列历史版本（倒序，不含 profile 全文）")
    ap.add_argument("--version", type=int, metavar="N", help="取第 N 版完整内容（回退前预览）")
    ap.add_argument("--put", type=Path, metavar="PROFILE.JSON",
                    help="整份覆盖存新版本（**不是打补丁**；须配 --base-version）")
    ap.add_argument("--rollback", type=int, metavar="N",
                    help="回退到第 N 版（造新版本而非拨指针；须配 --base-version）")
    ap.add_argument("--get-default", action="store_true",
                    help="只读当前默认配置（谁都能读，不需要运营老大；改默认配置前先用它留底）")
    ap.add_argument("--admin-default", type=Path, metavar="PROFILE.JSON",
                    help="**仅运营老大**：整份覆盖默认配置（任何运营老大都能改；没有个人档案的运营"
                         "实时跟随它，不只是之后新建的；不进版本历史、不可回退，改前自行留底）")
    # ---- 多套风格档案（profiles-v1）；不带这些参数时，上面几个子命令的行为一字不变 ----
    ap.add_argument("--list-profiles", action="store_true",
                    help="列出你有几套风格（名字/形态/哪套是默认）。老的单套格式读出来就一套「图文」")
    ap.add_argument("--profile", metavar="套名",
                    help="仅 --get / --version N：只取这一套（外层照旧带 exists / base_version / "
                         "trace_line；配 --version 时取的是那一版里的这一套）")
    ap.add_argument("--kind", choices=list(KINDS), metavar="carousel|typeset",
                    help="仅 --get / --version N / --new-profile：形态。carousel=图文轮播、"
                         "typeset=文字版。--get / --version 时取该形态下在用的那套；"
                         "--new-profile 时是必填")
    ap.add_argument("--new-profile", metavar="套名",
                    help="新建一套（须配 --kind 与 --base-version）。默认拿骨架建；"
                         "也可 --from 复制已有的一套，或 --file 用给定 JSON（参考图拆解产物走这条）")
    ap.add_argument("--from", dest="from_profile", metavar="已有套名",
                    help="仅 --new-profile：复制这一套改个名（形态必须与 --kind 一致）")
    ap.add_argument("--file", type=Path, metavar="SET.JSON",
                    help="仅 --new-profile：用这份 JSON 当新套的内容（只收**一套**，不收整份档案）")
    ap.add_argument("--set-active", metavar="套名",
                    help="切默认用哪套（运营没点明形态时兜底用它；须配 --base-version）")
    ap.add_argument("--rename-profile", nargs=2, metavar=("旧名", "新名"),
                    help="给某一套改名（须配 --base-version）")
    ap.add_argument("--delete-profile", metavar="套名",
                    help="删掉某一套（须配 --base-version；**删到只剩一套时拒绝**）")
    ap.add_argument("--limit", type=int, default=None,
                    help="仅 --versions：每页条数（服务端默认 50、上限 200，超出钳到 200）")
    ap.add_argument("--offset", type=int, default=None,
                    help="仅 --versions：从第几条起（配合响应里的 has_more 翻页取更早的）")
    ap.add_argument("--base-version", type=int, default=None,
                    help="你 --get 读到的当前 version（exists:false 时传 0）；--put/--rollback 必填")
    ap.add_argument("--source", default="manual",
                    choices=["manual", "reference_sample", "inherited_admin"],
                    help="本次改动来源（默认 manual；rollback 由服务端自己写，PUT 不接受）")
    ap.add_argument("--note", help="本次改动说明（≤500 字），如「按参考样本 8 张实测更新」")
    ap.add_argument("--api-base", help="API base（默认凭据 NBDPSY_XHS_API_BASE 或 https://mcp.nbdpsy.com）")
    ap.add_argument("--timeout", type=float, default=30, help="单次请求超时秒数（默认 30）")
    args = ap.parse_args()

    # 改多套的四个动作也是「读全量 → 整份覆盖」，与 --put 同一条硬约束
    multi_writes = [args.new_profile is not None, args.set_active is not None,
                    args.rename_profile is not None, args.delete_profile is not None]
    actions = [bool(args.get), bool(args.get_default), bool(args.versions),
               args.version is not None, args.put is not None, args.rollback is not None,
               args.admin_default is not None, bool(args.list_profiles)] + multi_writes
    if sum(actions) != 1:
        ap.error("恰好指定一个动作：--get / --get-default / --versions / --version N / "
                 "--put FILE / --rollback N / --admin-default FILE / --list-profiles / "
                 "--new-profile 名 / --set-active 名 / --rename-profile 旧 新 / --delete-profile 名")
    # 硬约束 2：整份覆盖不猜版本号——不传 --base-version 直接报错，绝不用「最新版」代替
    if (args.put is not None or args.rollback is not None or any(multi_writes)) \
            and args.base_version is None:
        ap.error("--put / --rollback / --new-profile / --set-active / --rename-profile / "
                 "--delete-profile 必须带 --base-version：先跑 --get 拿到 version"
                 "（exists:false 时传 0）。整份覆盖不替你猜版本号。")
    picking = bool(args.get) or args.version is not None      # 「取某一套」的两条读路径
    if args.profile is not None and not picking:
        ap.error("--profile 只能配 --get / --version N 用（只取某一套）；要建/改名/删/切默认请用 "
                 "--new-profile / --rename-profile / --delete-profile / --set-active")
    if args.kind is not None and not (picking or args.new_profile is not None):
        ap.error("--kind 只能配 --get / --version N（取该形态在用的那套）"
                 "或 --new-profile（新建这套的形态）用")
    if args.profile is not None and args.kind is not None:
        ap.error("--profile 与 --kind 二选一：要么按套名取，要么按形态取")
    if args.new_profile is not None and args.kind is None:
        ap.error("--new-profile 必须带 --kind carousel|typeset（图文 / 文字版）——"
                 "两种形态的字段完全不同，脚本不替你猜")
    if (args.from_profile is not None or args.file is not None) and args.new_profile is None:
        ap.error("--from / --file 只能配 --new-profile 用")
    if args.from_profile is not None and args.file is not None:
        ap.error("--from 与 --file 二选一：复制已有的一套，或用给定 JSON 新建")

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        # 可选凭据：没配的运营照样要能做内容 → 走第 ③ 层，不是致命错
        _exit_unreachable(Unreachable(
            "no_key", f"MISSING:{nbdpsy_common.XHS_API_KEY}",
            "找系统管理员要「运营接入配置包」，secret import 导入后重试；"
            "这把 key 是可选凭据，没有也能用 skill 内置默认风格继续做内容"),
            requested_set_name(args))
    api_base = (args.api_base or nbdpsy_common.xhs_api_base()).rstrip("/")

    try:
        if args.get:
            view = decorate_get(call("GET", "/api/style-profile", key, api_base,
                                     timeout=args.timeout))
            if view.get("exists"):
                print(f"✓ 第 ① 层·他自己的档案：{view['say']}", file=sys.stderr)
            else:
                print(f"· 第 ② 层·默认配置（**别说成是他的**）：{view['say']}", file=sys.stderr)
                if view.get("admin_default_version") is not None:
                    print(f"  正在用默认配置 v{view['admin_default_version']}"
                          f"（运营老大一改，你这边下次 --get 立刻跟着变）", file=sys.stderr)
            if args.profile is not None or args.kind is not None:
                # 只有带了新参数才走挑套；不带时输出与多套化之前**逐字节一致**（四处下游按它读）
                view = select_and_say(view, name=args.profile, kind=args.kind)
            elif is_multi(view.get("profile")):
                # 裸 --get 遇到新格式：给 active 那套的**内容**（不是整个容器）——下游只认单套结构。
                # ⛔ 键集合与多套化之前逐字一致，一个新字段都不许加（创作端/审查端按老键读）。
                sel = select_set(view["profile"])
                view = dict(view, profile=sel["content"])
                print(f"  （他有 {len(sel['names'])} 套风格，这里给的是默认那套"
                      f"「{sel['name']}」的内容；要别的套用 --get --profile 套名 或 --get --kind 形态）",
                      file=sys.stderr)
            src = ("server 下发（唯一真源）" if view.get("base_version_source") == "server"
                   else "本地派生（这台 server 没下发，属老版本）")
            print(f"  --put / --rollback 请用 base_version={view['base_version']}（{src}）",
                  file=sys.stderr)
            print(f"  留痕行（写进 00-overview.md 开头）：{view['trace_line']}", file=sys.stderr)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.list_profiles:
            view = decorate_get(call("GET", "/api/style-profile", key, api_base,
                                     timeout=args.timeout))
            listing = list_sets(view.get("profile"))
            out = dict(view)
            out.pop("profile", None)          # 列表不带全文（与 --versions 同口径）
            out["profiles"] = listing["profiles"]
            out["active_profile"] = listing["active"]
            out["profiles_legacy"] = listing["legacy"]
            out["count"] = len(listing["profiles"])
            shown = shown_sets(listing["profiles"])
            if view.get("exists"):
                # 新命令，可以自己组织话术；exists:false 时 say 保持 SAY_MISSING 逐字不动
                out["say"] = f"你有 {out['count']} 套风格：{shown}；现在默认用「{listing['active']}」"
            print(f"✓ {out['say']}", file=sys.stderr)
            if not view.get("exists"):
                print(f"  （默认配置里是 {out['count']} 套：{shown}）", file=sys.stderr)
            if listing["legacy"]:
                print("· 他的档案还是老的单套格式，这里读成一套「图文」——**没有动它**；"
                      "等他要新建/改名/删/切默认时才会真正迁到多套（迁移前会先跟他说）",
                      file=sys.stderr)
            print(f"  改多套（--new-profile / --set-active / ...）请用 "
                  f"base_version={out['base_version']}", file=sys.stderr)
            print(json.dumps(out, ensure_ascii=False))
            return

        if any(multi_writes):
            # 四个写动作同一条骨架：读全量 → 归一成多套容器 → 改一处 → 整份 PUT（带乐观锁）
            cur = decorate_get(call("GET", "/api/style-profile", key, api_base,
                                    timeout=args.timeout))
            server_base = cur.get("base_version")
            if server_base != args.base_version:
                # 与 --put 同一口径：版本号对不上就别写。这里提前拦，连一次 PUT 都不发
                raise Conflict(server_base, cur.get("updated_at"),
                               f"你给的 --base-version={args.base_version} 与服务端当前 "
                               f"{server_base} 不符")
            container, migrated = to_multi(cur.get("profile"))
            if not cur.get("exists"):
                print("· 他现在还没有自己的风格档案（跟随默认配置）：这一步会**给他建一份自己的**，"
                      "此后运营老大再改默认配置也不会影响他——先跟他说清楚再动手", file=sys.stderr)
            if migrated:
                print("· 他的档案是老的单套格式：这一步会把原内容**原样**收进「图文」那一套"
                      "（一个字不改，只是挪了层级），从此支持多套。这是迁移，属预期", file=sys.stderr)
                print("  → 待会儿 dropped_keys 会列出 visual / density / tone 这些顶层键，"
                      "那是因为它们被挪进「图文」里了，**不是丢了**", file=sys.stderr)

            expected_drop = None       # 这次操作**本来就该**丢的键（改名/删除），用来解释 dropped_keys
            if args.new_profile is not None:
                name = args.new_profile.strip()
                if not name:
                    raise ValueError("新套的名字不能是空的")
                kind = args.kind
                if args.file is not None:
                    content = load_set_file(args.file)
                    if content.get("kind") in KINDS and content["kind"] != kind:
                        print(f"⚠ 文件里写的形态是 {content['kind']}，命令行 --kind 是 {kind}——"
                              f"按命令行算（文件里的被覆盖）", file=sys.stderr)
                    src_desc = f"来自 {args.file}"
                elif args.from_profile is not None:
                    if args.from_profile not in container["profiles"]:
                        raise ValueError(f"没有叫「{args.from_profile}」的风格可复制："
                                         f"现有的是 {_names_cn(container)}")
                    content = dict(container["profiles"][args.from_profile])
                    if set_kind(content) != kind:
                        raise ValueError(
                            f"「{args.from_profile}」是「{KIND_CN[set_kind(content)]}」那一类，"
                            f"不能复制成「{KIND_CN[kind]}」的——两种形态的字段根本不同"
                            f"（图文有插画与信息点，文字版只有排版）。"
                            f"要建「{KIND_CN[kind]}」那套，去掉 --from 直接用骨架")
                    src_desc = f"复制自「{args.from_profile}」"
                elif kind == KIND_CAROUSEL:
                    default_view = call("GET", "/api/style-profile/admin-default", key, api_base,
                                        None, timeout=args.timeout)
                    content = carousel_skeleton(default_view.get("profile"))
                    src_desc = f"默认配置 v{default_view.get('admin_default_version')} 的骨架"
                else:
                    car = select_set(container, kind=KIND_CAROUSEL)["content"]
                    if car is None:
                        default_view = call("GET", "/api/style-profile/admin-default", key,
                                            api_base, None, timeout=args.timeout)
                        car = select_set(default_view.get("profile"))["content"] or {}
                        src_desc = "clean 主题骨架 + 默认配置的语气"
                    else:
                        src_desc = "clean 主题骨架 + 沿用他「图文」那套的语气"
                    content = typeset_skeleton(car.get("tone"), car.get("structure"))
                add_set(container, name, kind, content)
                # 套名本来就叫「文字版」时不再缀一遍形态（「文字版（文字版，…）」这种话没法听）
                tag = src_desc if name == KIND_CN[kind] else f"{KIND_CN[kind]}，{src_desc}"
                done = f"已新建「{name}」（{tag}）"
                auto_note = f"新建风格「{name}」（{tag}）"
            elif args.set_active is not None:
                set_active_set(container, args.set_active)
                done = f"默认已切到「{args.set_active}」"
                auto_note = f"默认风格切到「{args.set_active}」"
            elif args.rename_profile is not None:
                old, new = args.rename_profile
                rename_set(container, old, new)
                done = f"「{old}」已改名为「{new}」"
                auto_note = f"风格改名：{old} → {new}"
                expected_drop = f"profiles.{old}"
            else:
                gone_active = container.get("active") == args.delete_profile
                delete_set(container, args.delete_profile)
                done = f"已删掉「{args.delete_profile}」"
                if gone_active:
                    done += f"（它原本是默认，默认已顺延到「{container['active']}」）"
                auto_note = f"删掉风格「{args.delete_profile}」"
                expected_drop = f"profiles.{args.delete_profile}"

            warnings = container_warnings(container)
            for w in warnings:
                print(f"⚠ {w}", file=sys.stderr)
            payload = {"base_version": args.base_version, "profile": container,
                       "source": args.source, "note": args.note or auto_note}
            view = call("PUT", "/api/style-profile", key, api_base, payload, timeout=args.timeout)
            listing = list_sets(container)
            view["warnings"] = warnings
            view["profiles"] = listing["profiles"]
            view["active_profile"] = listing["active"]
            view["migrated"] = migrated
            print(f"✓ {done}，存为 v{view.get('version')}", file=sys.stderr)
            print(f"  现在他有 {len(listing['profiles'])} 套："
                  f"{shown_sets(listing['profiles'])}", file=sys.stderr)
            warn_dropped_keys(view)
            # dropped_keys 那条警告默认是「你是不是把别的段冲掉了」，但迁移与改名/删除本来就会丢键，
            # 不解释一句会把运营吓住（然后他就再也不看这条警告了）
            if migrated:
                print("  · 上面那条 dropped_keys 是迁移造成的（顶层键挪进「图文」里了），属预期",
                      file=sys.stderr)
            elif expected_drop and view.get("dropped_keys"):
                print(f"  · 上面那条 dropped_keys 里的 {expected_drop} 就是这次要动的那一套，属预期",
                      file=sys.stderr)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.versions:
            query = [f"{k}={v}" for k, v in (("limit", args.limit), ("offset", args.offset))
                     if v is not None]
            path = "/api/style-profile/versions" + ("?" + "&".join(query) if query else "")
            view = call("GET", path, key, api_base, timeout=args.timeout)
            n = len(view.get("versions") or [])
            total = view.get("total")
            tail = f"、共 {total} 个" if isinstance(total, int) else ""
            print(f"✓ 历史版本 {n} 个（本页，倒序{tail}）；先 --version N 预览内容，确认了再 --rollback N",
                  file=sys.stderr)
            if view.get("has_more"):
                print(f"  → 还有更早的版本：加 --offset {(args.offset or 0) + n} 继续翻",
                      file=sys.stderr)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.version is not None:
            view = call("GET", f"/api/style-profile/versions/{args.version}", key, api_base,
                        timeout=args.timeout)
            print(f"✓ v{args.version} 的内容如下（只是预览，没动当前档案）", file=sys.stderr)
            if args.profile is not None or args.kind is not None:
                # 审查端要按留痕行取回某一版再读 profile.visual.*：多套化之后这个端点返的是整份
                # 容器，`profile.visual` 恒 undefined。带 --profile/--kind 时就挑出那一套，
                # 走与 `--get --profile/--kind` **同一个** select + decorate（select_and_say）。
                view = select_and_say(view, name=args.profile, kind=args.kind)
                print(f"  留痕行（写进 00-overview.md 开头）：{view['trace_line']}", file=sys.stderr)
            # 不带 --profile/--kind 时原样透传整份（改多套前「取整份」靠的就是这条路，别动）
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.put is not None:
            profile = load_profile(args.put)
            # 发之前先读一次当前档案：多套档案被一份单套 body 整份覆盖 = 其余几套永久消失，
            # 而这正是「裸 --get → 改 → --put」的必然产物（见 guard_flat_put_over_multi）。
            # 与四个多套写动作同一段 GET，多花一个来回，换的是不可逆的数据丢失被拦在发出去之前。
            cur = decorate_get(call("GET", "/api/style-profile", key, api_base,
                                    timeout=args.timeout))
            guard_flat_put_over_multi(cur, profile)
            warnings = profile_warnings(profile)
            for w in warnings:
                print(f"⚠ {w}", file=sys.stderr)
            payload = {"base_version": args.base_version, "profile": profile,
                       "source": args.source}
            if args.note:
                payload["note"] = args.note
            view = call("PUT", "/api/style-profile", key, api_base, payload, timeout=args.timeout)
            view["warnings"] = warnings
            print(f"✓ 已整份覆盖，存为 v{view.get('version')}（此后你的笔记都按这一版走）",
                  file=sys.stderr)
            warn_dropped_keys(view)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.rollback is not None:
            payload = {"to_version": args.rollback, "base_version": args.base_version}
            view = call("POST", "/api/style-profile/rollback", key, api_base, payload,
                        timeout=args.timeout)
            new_v = view.get("version")
            view["hint"] = (f"回退是造新版本、不是拨指针：内容回到了 v{args.rollback}，"
                            f"版本号却是新的 v{new_v}；中间那几版仍在历史里，"
                            f"所以「回退后又后悔」还能再退回去")
            print(f"✓ 已把 v{args.rollback} 的内容落成新版本 v{new_v}（还能再退回来）",
                  file=sys.stderr)
            warn_dropped_keys(view)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.get_default:
            # 只读默认配置（服务端 2026-07-27 上线，不设 require_admin：一般用户也能读，
            # 因为没建个人档案的人本来就能从 --get 读到同样内容）。
            # 这是「改默认配置前留底」的**唯一正确姿势**——绝不能拿 --get 代替：
            # --get 读的是调用者自己的档案，建过个人档案的人拿到的根本不是默认配置，且照样 exit 0。
            view = call("GET", "/api/style-profile/admin-default", key, api_base, None,
                        timeout=args.timeout)
            print(f"✓ 当前默认配置 v{view.get('admin_default_version')}"
                  f"（没有个人风格档案的人实时跟随这一份）", file=sys.stderr)
            print("  → 要改它之前：把这份输出整个存成文件收好。默认配置**不进版本历史、"
                  "rollback 对它无效**，这份留底是唯一的后悔药。", file=sys.stderr)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.admin_default is not None:
            # 默认配置没有乐观锁（服务端整份覆盖、version 自增），所以不要 --base-version
            profile = load_profile(args.admin_default)
            # 与 --put 同款守卫，而且这里更要紧：默认配置**不进版本历史、rollback 救不回来**，
            # 一旦被单套 body 打平，所有跟随它的运营当场少掉几套风格。
            current_default = call("GET", "/api/style-profile/admin-default", key, api_base)
            guard_flat_put_over_multi(current_default, profile, what="默认配置",
                                      recover="用 `--get-default` 取整份"
                                              "（拿输出里的 `profile` 那一层），改完再发")
            warnings = profile_warnings(profile)
            for w in warnings:
                print(f"⚠ {w}", file=sys.stderr)
            payload = {"profile": profile}
            if args.note:
                payload["note"] = args.note
            view = call("PUT", "/api/style-profile/admin-default", key, api_base, payload,
                        timeout=args.timeout, forbidden_is_permission=True)
            view["warnings"] = warnings
            print(f"✓ 已整份覆盖默认配置，存为 v{view.get('version')}"
                  f"（默认配置是独立的一份，任何运营老大都能改，不属于谁的个人档案）",
                  file=sys.stderr)
            print("  → 波及面：**所有没有自己风格档案的人实时跟随这一版**——不只是之后新建的，"
                  "现有的那些人下次 --get、下次出图就用新的，他们立刻跟着变；"
                  "已建个人档案的各自独立、不受影响", file=sys.stderr)
            print("  → 这份**不进版本历史、rollback 对它无效**（改坏了没法回退）：改前请自行留底",
                  file=sys.stderr)
            print(json.dumps(view, ensure_ascii=False))
            return

    except Unreachable as e:
        _exit_unreachable(e, requested_set_name(args))
    except Forbidden as e:
        # 服务好好的，只是这个人不是运营老大 → 绝不能说成「没连上」，也别让上层降级
        print(f"✗ 只有运营老大能改默认配置：你这把 key 是一般用户（{e.error}）",
              file=sys.stderr)
        print("  → 改你自己的风格档案请用 --put（先 --get 拿 base_version）；"
              "确需改默认配置找运营老大", file=sys.stderr)
        print(json.dumps({
            "ok": False, "outcome": "forbidden", "error": e.error,
            "hint": "只有运营老大能改默认配置：改自己的档案用 --put，要改默认配置找运营老大",
        }, ensure_ascii=False))
        sys.exit(EXIT_ERROR)
    except Conflict as e:
        # 硬约束 3：**不重试同一份 body**——这里只报不重发，让上层重新 GET 后再来
        base = args.base_version
        print(f"✗ 版本冲突：档案在别处被改过（v{base} → v{e.current_version}），"
              f"请重新 --get 后再改；**绝不要重发同一份 body**", file=sys.stderr)
        print(json.dumps({
            "ok": False, "outcome": "conflict", "base_version": base,
            "current_version": e.current_version, "updated_at": e.updated_at,
            "error": e.error,
            "say": SAY_CONFLICT.format(base=base, current=e.current_version),
            "hint": "别重试同一份 body：先 --get 重新拿全量（含新 version），"
                    "把你的改动重新落上去，再整份 PUT",
        }, ensure_ascii=False))
        sys.exit(EXIT_CONFLICT)
    except Exception as e:
        print(f"✗ 失败: {e}", file=sys.stderr)
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(EXIT_ERROR)


if __name__ == "__main__":
    main()

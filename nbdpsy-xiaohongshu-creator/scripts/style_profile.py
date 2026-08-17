#!/usr/bin/env python3
"""读写「当前运营的风格档案」（经 nbdpsy-api，纯 REST）。

风格档案 = 每个运营**自己**的一份视觉 / 语气 / 结构 / 密度设定：创作端按它写绘图提示词，
审查端按它判。现在写死在 skill 里的莫兰迪三色 + 固定人物卡那一套，只是**默认配置**，
不是全局常量——别的运营可以与它完全不同（多号矩阵各有调性）。

用法：
    python3 style_profile.py --get                          # 读当前档案（**先看 exists**）
    python3 style_profile.py --versions [--limit 50] [--offset 0]   # 列历史版本（不含 profile 全文）
    python3 style_profile.py --version 3                    # 取某一版完整内容（回退前预览）
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
    python3 style_profile.py --version 3 --profile 文字版    # 取**那一套的**第 3 版（审查端按留痕行回溯用）
    python3 style_profile.py --version 3 --kind typeset      # 同上，按形态取
    python3 style_profile.py --new-profile 水墨风 --kind carousel
        [--from 图文 | --file 拆解产物.json]                 # 新建一套（默认拿骨架，也可复制/喂 JSON）
    python3 style_profile.py --get --form podcast           # 取「播客」那条视频产线的那套
    python3 style_profile.py --new-profile 微电影 --kind video --form microfilm
    python3 style_profile.py --get --last                   # **按上次**：这台机器上次用的那套
    python3 style_profile.py --set-active 文字版             # 切默认用哪套
    python3 style_profile.py --rename-profile 水墨风 国风
    python3 style_profile.py --delete-profile 水墨风          # 删到只剩一套时**服务端拒绝**（409）
    python3 style_profile.py --init-sets                    # 新运营建档：按默认配置的套数建齐

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
   绝不替你猜版本号（`exists:false` 时传 0）。多套单套**一个写法**：`--get` 给你哪一套、
   `--put` 就发回哪一套，一读一写对得上，动不到别的套。
3. **收到 409 别重试同一份 body**：说明档案在别处被改过了。本脚本收到 409 只报不重发，
   并把服务端 `detail.current_version` 原样透出，请按它提示运营重新 `--get` 后再改。

另有两条（server v0.11.0 起）：

- **`base_version` 以 server 下发的为准**：`GET` 无论有没有档案都带 `base_version`（无档案给 0），
  这是「下一次 PUT 该传什么」的唯一真源，本脚本**直接透传**；只有 server 没给（老版本）才回落到
  本地派生，并在 stderr 注明来源（输出里的 `base_version_source` 是 `server` 还是 `derived`）。
- **`--put` / `--rollback` 之后必须看 `dropped_keys`**：server 会算出这次整份覆盖比上一版少掉的键
  （只比顶层 + 二级，`[]` = 没丢）。非空多半是「只带了 visual 就发上去」，把别的段冲掉了——
  stderr 会人话警告，请**当场回读给运营确认**再往下走。服务端不拦截，东西已经存了。

多套档案的三条铁律（2026-07-29 起，**多套由服务端原生支持**，见 nbdpsy-server v0.17.0）：

1. **多套是服务端的数据模型，不是 `profile` JSON 里的容器**：套管理走 `/api/style-profile/sets`
   四个端点，取某一套走各读端点的 `?set=套名`。`profile` 里再也不会出现 `schema`/`active`/
   `profiles` 这些容器键——旧工具包把容器 PUT 上来会被服务端哨兵拒（400「工具包版本过旧」）。
2. **`--get` 不带 `--profile` / `--kind` 时行为与多套化之前完全一致**：服务端返回 `is_active`
   那一套的内容（外加 `set` / `kind` 两个**增**字段）。创作端、审查端、guide、pipeline 四处
   都按这个读，改了全断。
3. **`kind` 三个合法值**：`carousel`（图文轮播，AI 生图，有 visual/density）、
   `typeset`（文字版，脚本渲染，有 typeset 段）、`video`（视频，有 video 段）。
   `tone` / `structure` 三种形态都有。
   跟运营说话时说「**图文那套**」「**文字版那套**」「**放映／字卡／微电影／播客那套**」，
   别说 carousel/typeset/video（他们不懂）。

视频那一类多一层「子形态」（2026-08-17）：

    kind=video 的套必须在内容里写明 `video.form` ∈ slideshow（放映）/ card（字卡）/
    microfilm（微电影）/ podcast（播客）。**一个子形态一套**——四条产线的旋钮完全不同
    （放映有页间停顿、播客有男女双声、微电影有子风格三档），混一套里必有一半字段没人读。

    ⚠️ 子形态**不在 `GET /sets` 的列表里**（列表只给 name/kind/is_active/version）：
    它在档案内容的 `video.form` 里，所以 `--form` 取套是「1 次列套 + 至多 N 次取内容」。
    ⛔ 别为了省这几次请求把子形态塞进 `kind`（`kind` 一变成 `video/podcast` 这种复合值，
    四处按 `kind == "video"` 判的地方全断）。

    `video` 段里放什么由「**这条产线哪个脚本哪一行读它**」决定，字段→消费者的对照表在
    `nbdpsy-text-to-video/SKILL.md`「风格档案（视频那一类）」节，那里是唯一真源。
    ⛔ 指不到消费者的字段一律不加——加一个没人读的字段就是新造一条死链。

「按上次」本机记忆（2026-08-17 老板拍板：**存本地文件**）：

    `--get --last` 用这台机器上次实际用的那一套（记在 `~/.config/nbdpsy/last-choice.json`）。
    换台电脑就没有了——**这是老板知情并接受的代价**（原话「选本地文件（免改造但换机器不跟人走）」）。
    它与服务端 `is_active` 不是一回事，优先级见 `read_last_choice` 上方那段注释。

⚠️ **建套 / 改名 / 切默认 / 删套这四个动作没有乐观锁**（服务端实测：套是独立资源，
`POST /sets` 与 `PATCH /sets/{name}` 都不收 `base_version`）。所以这四条命令**不要 `--base-version`**，
传了也只会被忽略并给一句提醒——别跟运营说这几步有版本冲突保护，那是假承诺。
`--put` / `--rollback` 的乐观锁照旧，`base_version` 是**该套自己的**版本号。

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
from urllib.parse import quote, urlencode

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


def profile_warnings(profile: dict, kind=None):
    """上传前的提醒（只警告不拦截，服务端本就原样存取不校验语义）。

    多套原生化之后 `profile` 恒是**单套内容**，不再有「容器顶层没有 density 段」那种假警报。
    剩下的都要分形态：**文字版 / 视频那类套没有插画、没有「信息点」**，拿 density 五字段去
    要求它是误报——狼来了会让运营以后连真警告也不看。形态优先信调用方给的 `kind`，其次信
    内容里自带的 `kind` 字段；都没有就按图文查（存量档案全是图文，保持今天的行为）。"""
    kind = kind or profile.get("kind")
    w = []
    size = len(json.dumps(profile, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PROFILE_BYTES:
        w.append(f"profile {size} 字节超 {MAX_PROFILE_BYTES} 上限，服务端会报 400（不截断）")
    if kind == KIND_VIDEO:
        return w + video_warnings(profile)
    return w if kind == KIND_TYPESET else w + density_warnings(profile)


def video_warnings(profile: dict):
    """视频那一类套的提醒。**只报「这个字段没人读」这一类真死链**，⛔ 不报「你没填 X」——
    骨架里每个字段都有脚本默认值，缺了照样能出片，报它就是恒响的狼来了。

    三条（都不会对一份规规矩矩的档案响）：
    1. 没有 `video` 段 / 段里没有 `form`：整套没人认得出是哪条产线，四条产线一个都读不了它。
    2. `form` 不在四个合法值里：拼错一个字母，取套时永远挑不中它。
    3. 段里带着别的子形态的字段：多半是从别的套复制来的，那些字段这条产线一行都不会读。
    """
    video = profile.get("video")
    if video is None:
        return ["profile 里没有 video 段：视频那一类的旋钮全在这一段里，缺了等于一套空档案"]
    if not isinstance(video, dict):
        return ["video 不是对象，四条视频产线都读不出旋钮"]
    form = video.get("form")
    if form is None:
        return ["video 段里没有 form：认不出是放映 / 字卡 / 微电影 / 播客哪一条产线，"
                "取套时永远挑不中它"]
    if form not in VIDEO_FORMS:
        return [f"video.form={form!r} 不是四个子形态之一（{'/'.join(VIDEO_FORMS)}）——"
                f"拼错一个字母，取套时就永远挑不中它"]
    w = []
    known = set(VIDEO_SKELETONS[form]) | {"form"}
    if form == FORM_CARD:
        known.add("oneline")            # 仅 tpl-oneline 版式读，见下
    stray = [k for k in video if k not in known]
    if stray:
        w.append(f"video 段里这些键「{FORM_CN[form]}」这条产线一行都不读：" + "、".join(stray)
                 + "——多半是从别的子形态复制来的，删掉免得以为它在起作用")
    if form == FORM_CARD:
        tpl, oneline = video.get("template"), video.get("oneline")
        if oneline is not None and tpl != ONELINE_TEMPLATE:
            w.append(f"这套用的是 {tpl!r} 版式，但带着 oneline 段——"
                     f"`oneline` 只有 {ONELINE_TEMPLATE} 版式（build_oneline.py）读得到，"
                     f"别的版式带着它等于摆设")
        elif oneline is None and tpl == ONELINE_TEMPLATE:
            w.append(f"这套用 {ONELINE_TEMPLATE} 版式却没有 oneline 段："
                     f"build_oneline.py 拿不到 bg / canvas 会直接拒跑，"
                     f"要么在档案里补这一段，要么每次命令行现给")
    return w


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
# 多套风格档案。**多套由服务端原生承载**（nbdpsy-server v0.17.0）：套管理走
# /api/style-profile/sets 四个端点，取某一套走各读端点的 ?set=。这一段只负责
# 「拼 URL / 挑套 / 说人话」，档案内容一律由服务端给，客户端不再拼装任何容器。
# ---------------------------------------------------------------------------

KIND_CAROUSEL = "carousel"      # 路线①：信息图轮播（AI 生图），有 visual / density
KIND_TYPESET = "typeset"        # 路线②：文字版（脚本渲染），有 typeset 段
KIND_VIDEO = "video"            # 路线③：视频（nbdpsy-text-to-video），有 video 段
KINDS = (KIND_CAROUSEL, KIND_TYPESET, KIND_VIDEO)
# 面向运营的说法：**绝不跟运营说 carousel/typeset/video**（他们不懂），一律说「图文」「文字版」「视频」
KIND_CN = {KIND_CAROUSEL: "图文", KIND_TYPESET: "文字版", KIND_VIDEO: "视频"}
# typeset 段的 8 个字段：theme 必填，其余 null = 用主题默认值、不覆盖（见 typeset_longimage.py）
TYPESET_NULLABLE = ["bg", "accent", "accent_soft", "font", "title_font", "indent", "texture"]

# ── 视频那一类的四个子形态 ────────────────────────────────────────────────────
# 四条产线的旋钮完全不同（放映有页间停顿、播客有男女双声、微电影有子风格三档），
# 所以**一个子形态一套**，套里只放这条产线真读得到的字段。
FORM_SLIDESHOW = "slideshow"    # 放映：轮播图当 PPT 放，slideshow_video.py 一条命令收口
FORM_CARD = "card"              # 字卡：GSAP 动效字卡，render_card.py / build_oneline.py
FORM_MICROFILM = "microfilm"    # 微电影：即梦生成画面 + 合成，十步产线
FORM_PODCAST = "podcast"        # 播客：双声对谈 + 播放器录屏
VIDEO_FORMS = (FORM_SLIDESHOW, FORM_CARD, FORM_MICROFILM, FORM_PODCAST)
FORM_CN = {FORM_SLIDESHOW: "放映", FORM_CARD: "字卡",
           FORM_MICROFILM: "微电影", FORM_PODCAST: "播客"}

#: 每个子形态的骨架 = **那条产线真读得到的旋钮**，取值一律等于脚本/工序的现行默认，
#: 所以「建一套档案」本身不改变任何产线行为，改了值才改行为。
#: ⛔ 往这里加字段前先回答「哪个脚本哪一行读它」——读不到的字段就是死链，不许加。
#: 各字段的消费者对照表见 `nbdpsy-text-to-video/SKILL.md`「风格档案（视频那一类）」节。
VIDEO_SKELETONS = {
    # slideshow_video.py 的 --canvas/--engine/--voice/--speed/--model/--sentence-gap/
    # --bgm/--bgm-duck/--head/--page-gap/--tail/--kenburns/--xfade（该脚本 --style 直读）
    FORM_SLIDESHOW: {
        "canvas": "1080x1440",
        "narration": {"engine": "minimax", "voice": "Chinese (Mandarin)_Warm_Bestie",
                      "speed": 0.95, "model": "speech-2.8-hd", "sentence_gap": 0.45},
        # bgm.source="auto" 对齐的是**产线那条命令**（spec 里一直带 `--bgm auto`），
        # 不是 argparse 的 None——脚本默认不放音乐，但放映从来没这么出过片
        "bgm": {"source": "auto", "duck_db": 14.0},
        "pace": {"head": 0.3, "page_gap": 0.35, "tail": 1.2},
        "motion": {"kenburns": 0.03, "xfade": 0.0},
    },
    # template → 选版式那道工序；narration → tts_gen 那道工序；
    # 只有 tpl-oneline 版式才有 `oneline` 段（build_oneline.py --style 直读），**别给别的版式加**
    FORM_CARD: {
        "template": "tpl-basic",
        "narration": {"voice": "Chinese (Mandarin)_Warm_Bestie", "speed": 0.95},
    },
    # look → direction.md 第一行（审查端按它核色板与转场）；ratio/ai_label → shots.json 的
    # video 段（build_manifest.py 读）；narration → 第 3 步 tts_gen；bgm.mood → 第 7 步 gen_bgm
    FORM_MICROFILM: {
        "look": "暖雾",
        "ratio": "9:16",
        "ai_label": "AI 生成",
        "narration": {"engine": "minimax", "voice": "Chinese (Mandarin)_Warm_Bestie",
                      "speed": 0.95},
        "bgm": {"mood": "calm"},
    },
    # narration → podcast_gen.py --voice-f/--voice-m/--model；player → record_podcast.py
    # --theme/--fade-out（两个脚本都 --style 直读）
    FORM_PODCAST: {
        "narration": {"voice_f": "Chinese (Mandarin)_Warm_Bestie",
                      "voice_m": "Chinese (Mandarin)_Gentleman",
                      "model": "speech-2.8-hd"},
        "player": {"theme": "shenye", "fade_out": 0.0},
    },
}
#: 只有 tpl-oneline 版式读得到 `oneline` 段（build_oneline.py），别的版式带着它就是死字段
ONELINE_TEMPLATE = "tpl-oneline"

SETS_PATH = "/api/style-profile/sets"
PROFILE_PATH = "/api/style-profile"
ADMIN_DEFAULT_PATH = "/api/style-profile/admin-default"
SCOPE_ADMIN_DEFAULT = "admin-default"


def with_query(path: str, **params) -> str:
    """拼 query（值为 None 的键不发）。套名是中文、可能带空格，**必须转义**才不会拼坏 URL。"""
    q = {k: v for k, v in params.items() if v is not None}
    return path + ("?" + urlencode(q) if q else "")


def set_path(name: str, scope=None) -> str:
    """/sets/{套名}：套名进的是 path 段，用 quote(safe="") 整段转义（服务端只禁 / 和 ?）。"""
    return with_query(f"{SETS_PATH}/{quote(str(name), safe='')}", scope=scope)


def fetch_sets(key, api_base, timeout, scope=None) -> list:
    """列套：`GET /sets[?scope=admin-default]` → `[{name,kind,is_active,version,updated_at}]`。
    读侧不设 admin 门，所以一般用户也能看默认配置有哪几套（`--init-sets` 靠这个）。"""
    view = call("GET", with_query(SETS_PATH, scope=scope), key, api_base, timeout=timeout)
    sets = view.get("sets")
    return sets if isinstance(sets, list) else []


def pick_by_kind(sets, kind):
    """按形态挑一套：**is_active 那套优先**，否则取列表里第一套同形态的；一套都没有 → None。"""
    same = [s for s in sets if s.get("kind") == kind]
    for s in same:
        if s.get("is_active"):
            return s
    return same[0] if same else None


def profile_form(profile):
    """一套视频档案的子形态（放映 / 字卡 / 微电影 / 播客）；不是视频那类就返回 None。"""
    if not isinstance(profile, dict):
        return None
    video = profile.get("video")
    return video.get("form") if isinstance(video, dict) else None


def pick_by_form(sets, form, key, api_base, timeout, path=None):
    """在 kind=video 的套里挑 `video.form == form` 的那一套（**is_active 优先**）。
    返回 `(套行, 服务端原始 view)`；一套都不匹配 → `(None, None)`。

    ⚠️ 这里**要逐套把内容取回来看**：`GET /sets` 只给 name/kind/is_active，
    子形态藏在档案内容的 `video.form` 里，列表看不见。所以这条路的请求数是
    「1 次列套 + 至多 N 次取内容」（N = 他有几套视频档案，通常 1–4）——
    知道就好，⛔ 别为了省这几次请求把子形态挪进 kind 字段（那会把 kind 变成
    `video/podcast` 这种复合值，四处按 `kind == "video"` 判的地方全断）。
    """
    ordered = sorted((s for s in sets if s.get("kind") == KIND_VIDEO),
                     key=lambda s: not s.get("is_active"))
    for s in ordered:
        view = call("GET", with_query(path or PROFILE_PATH, set=s["name"]), key, api_base,
                    timeout=timeout)
        if profile_form(view.get("profile")) == form:
            return s, view
    return None, None


def set_names(sets) -> list:
    return [s.get("name") for s in sets]


def resolve_target_set(args, key, api_base):
    """本次「按套操作」点名的是哪一套 → 拼进 `?set=` 的值；没点名返回 None（落到 is_active）。

    ⛔ 读能点名而写不能点名，就会出静默错套：运营以为在改文字版，实际改的是图文那套。
    所以 `--put` / `--rollback` / `--versions` / `--admin-default` 与两条读命令**共用这一份挑套逻辑**。
    """
    if getattr(args, "profile", None):
        return args.profile
    form = getattr(args, "form", None)
    kind = getattr(args, "kind", None)
    if not form and not kind:
        return None
    admin = getattr(args, "admin_default", None) is not None
    scope = SCOPE_ADMIN_DEFAULT if admin else None
    timeout = getattr(args, "timeout", 30)
    sets = fetch_sets(key, api_base, scope=scope, timeout=timeout)
    if form:
        hit, _ = pick_by_form(sets, form, key, api_base, timeout,
                              path=ADMIN_DEFAULT_PATH if admin else PROFILE_PATH)
        if hit is None:
            raise ValueError(f"你还没有「{FORM_CN.get(form, form)}」那一套视频风格——"
                             f"先 `--new-profile <名字> --kind {KIND_VIDEO} --form {form}` "
                             f"建一套，再来改它")
        return hit.get("name")
    hit = pick_by_kind(sets, kind)
    if hit is None:
        raise ValueError(f"你还没有「{KIND_CN.get(kind, kind)}」那一类的风格套——"
                         f"先 `--new-profile <名字> --kind {kind}` 建一套，再来改它")
    return hit.get("name")


def confirm_wrote_set(view: dict, target):
    """写完核一次「服务端确实写在我点名的那一套上」。

    这一步不是多余：`?set=` 拼错 / 服务端忽略了它，都会**静默写到 is_active 那套**——
    响应照样 200、照样报「✓ 已整份覆盖」，运营要等下一批图出来才发现改错了套。
    """
    wrote = view.get("set")
    if target and wrote and wrote != target:
        raise ValueError(
            f"点名要改的是「{target}」，服务端却写在了「{wrote}」上——已停下，别再往下走。"
            f"先 `--list-profiles` 确认这个名字还在（可能被改名或删了），再重来一次")


def typeset_skeleton(tone=None, structure=None) -> dict:
    """「文字版」那套的初始骨架：theme=clean、其余 null（null = 听主题的，不覆盖）；
    tone / structure 沿用图文那套（语气与标题写法跟形态无关，契约定的）。"""
    ts = {"theme": "clean"}
    ts.update({k: None for k in TYPESET_NULLABLE})
    return {"kind": KIND_TYPESET, "typeset": ts,
            "tone": dict(tone) if isinstance(tone, dict) else {},
            "structure": dict(structure) if isinstance(structure, dict) else {}}


def video_skeleton(form, tone=None, structure=None) -> dict:
    """「视频」那一类某个子形态的初始骨架：**只放这条产线真读得到的旋钮**，
    取值一律等于脚本/工序的现行默认（所以建套本身不改变任何产线行为）；
    tone / structure 沿用他在用那套（语气与标题写法跟形态无关，契约定的）。"""
    return {"kind": KIND_VIDEO,
            "video": dict({"form": form}, **json.loads(json.dumps(VIDEO_SKELETONS[form]))),
            "tone": dict(tone) if isinstance(tone, dict) else {},
            "structure": dict(structure) if isinstance(structure, dict) else {}}


def default_set_content(kind, key, api_base, timeout, form=None):
    """新套的初始内容 = **默认配置里同形态的那一套**（⛔ 别自己编一份）。返回 `(内容, 来源说明)`。

    默认配置里没有同形态的套时（生产的默认配置目前只有「图文」一套）：
    文字版退到 clean 骨架 + 沿用他在用那套的语气；视频退到该子形态的旋钮骨架 + 同样沿用语气；
    图文退到默认配置在用的那套。"""
    admin_sets = fetch_sets(key, api_base, timeout, scope=SCOPE_ADMIN_DEFAULT)
    if kind == KIND_VIDEO:
        # 视频那类**按子形态对齐**：默认配置里的视频套若是别的子形态，拿来当骨架等于给他
        # 一套「播客的旋钮 + 放映的名字」，四条产线一个都读不对
        pick, view = pick_by_form(admin_sets, form, key, api_base, timeout,
                                  path=ADMIN_DEFAULT_PATH)
        if pick is not None and isinstance(view.get("profile"), dict) and view["profile"]:
            return dict(view["profile"]), (f"默认配置「{pick['name']}」"
                                           f"v{view.get('admin_default_version')} 的内容")
        mine = call("GET", PROFILE_PATH, key, api_base, timeout=timeout)
        base = mine.get("profile") if isinstance(mine.get("profile"), dict) else {}
        return (video_skeleton(form, base.get("tone"), base.get("structure")),
                f"「{FORM_CN[form]}」那条产线的旋钮骨架 + 沿用他在用那套的语气")
    pick = pick_by_kind(admin_sets, kind)
    if pick is not None:
        view = call("GET", with_query(ADMIN_DEFAULT_PATH, set=pick["name"]), key, api_base,
                    timeout=timeout)
        content = view.get("profile")
        if isinstance(content, dict) and content:
            return dict(content), (f"默认配置「{pick['name']}」"
                                   f"v{view.get('admin_default_version')} 的内容")
    if kind == KIND_TYPESET:
        mine = call("GET", PROFILE_PATH, key, api_base, timeout=timeout)
        base = mine.get("profile") if isinstance(mine.get("profile"), dict) else {}
        return (typeset_skeleton(base.get("tone"), base.get("structure")),
                "clean 主题骨架 + 沿用他在用那套的语气")
    view = call("GET", ADMIN_DEFAULT_PATH, key, api_base, timeout=timeout)
    content = view.get("profile")
    return (dict(content) if isinstance(content, dict) else {},
            f"默认配置 v{view.get('admin_default_version')} 的骨架")


def shown_sets(sets) -> str:
    """念给运营听的那串：`图文·默认、水墨风（图文）、文字版`。
    套名本来就叫「图文」时不再缀一遍形态（「图文（图文·默认）」这种话没法听）。"""
    parts = []
    for s in sets:
        cn = KIND_CN.get(s.get("kind"), s.get("kind"))
        name = s.get("name")
        label = name if name == cn else f"{name}（{cn}）"
        parts.append(label + "·默认" if s.get("is_active") else label)
    return "、".join(parts) or "（一套都没有）"


def load_set_file(path) -> dict:
    """读 `--new-profile --file` 给的**单套** JSON（参考图拆解产物走这条）。两道防呆：
    喂 `--get` 整份输出时自动剥 profile；空对象直接拒（建出空套等于建了个坏档案）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是 JSON 对象，不能当一套风格存")
    if "exists" in data and isinstance(data.get("profile"), dict):
        print("ℹ 传进来的是 --get 的整份输出，已自动取其中的 profile 字段当这一套的内容",
              file=sys.stderr)
        data = data["profile"]
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


def picked_view(view: dict, name, kind, names=None, active=None) -> dict:
    """挑中一套时的输出：`profile` 就是服务端给的那一套（不再本地挑），补
    `profile_name` / `profile_kind` / `outcome` / `trace_line`。

    `say` 保持 decorate_get 那两句逐字不动（exists 真假的说辞是契约定死的，别掺套名进去）。
    `profile_names` / `active_profile` 只有已经列过套的路径才有值，其余给 None——
    **绝不为了凑这两个字段多打一次 /sets**（写命令不再需要多余的来回）。"""
    out = dict(view)
    out["profile_name"] = name
    out["profile_kind"] = kind
    out["profile_names"] = names
    out["active_profile"] = active
    out["outcome"] = "ok"
    out["trace_line"] = _trace_line_named(view, name)
    return out


def unpicked_view(outcome: str, want: str, sets, name=None, kind=None, form=None) -> dict:
    """没挑中那一套时的输出：`profile: null` + `say` 提示可以新建，layer / trace_line 落到
    「内置兜底」——因为**实际会用内置默认风格**，留痕行必须说实话，否则审查端会拿一套
    没用过的档案来判。

    `base_version` 恒为 None：这时候根本没有"哪一套"可写，给个数字会让上层拿它去 `--put`，
    写到别的套上去（宁可让它显式为空而当场失败，也不能悄悄写错套）。"""
    have = "、".join(n for n in set_names(sets)) or "（一套都没有）"
    if name is not None:
        say = f"你的档案里没有「{name}」这一套风格（现有：{have}），要不要现在建一套？"
    elif form is not None:
        say = (f"你还没有「{FORM_CN.get(form, form)}」那套视频风格（现有：{have}），"
               f"这次先用内置默认；要不要现在建一套？")
    else:
        say = (f"你还没有「{KIND_CN.get(kind, kind)}」那套风格（现有：{have}），"
               f"这次先用内置默认；要不要现在建一套？")
    return {
        "ok": True, "exists": bool(sets), "profile": None,
        "profile_name": None, "profile_kind": None,
        "profile_names": set_names(sets), "active_profile": active_name(sets),
        "base_version": None, "outcome": outcome, "reason": outcome,
        "layer": "builtin_fallback", "say": say,
        # 留痕行带上「他要的那一套」的名字：审查端把没套名的行当存量批次按「图文」判，
        # 文字版的批次留一行没名的，就会被拿图文的标准去判
        "trace_line": f"风格档案：{want} v—（内置兜底，读取于 {_today()}）",
    }


def active_name(sets):
    return next((s.get("name") for s in sets if s.get("is_active")), None)


# ---------------------------------------------------------------------------
# 「按上次」本机记忆（2026-08-17 老板拍板：存本地文件）
#
# ⚠️ 它与服务端的 `is_active` **不是一回事**，别混：
#   · `is_active` = 服务端记的**默认套**，跟人走、跨机器、别处改了这里立刻跟着变；
#   · last-choice = **这台机器上次实际用的那一套**，跟机器走、换台电脑就没有了
#     （老板知道这个代价，原话「选本地文件（免改造但换机器不跟人走）」）。
#
# **两者冲突时谁优先**：谁被点名谁优先，没人点名一律听服务端的。
#   ① `--profile` / `--kind` / `--form` 点名 → 点名的赢（并把这次的选择记下来）
#   ② `--last` 点名 → 本机记忆赢
#   ③ 都没点名（裸 `--get`）→ **服务端 is_active**，与今天一字不差
# ⛔ 绝不让本机记忆去改裸 `--get` 的结果：创作端 / 审查端 / guide / pipeline 四处都按裸
# `--get` 读，让一个别人看不见的本地文件去改它，等于同一条命令在两台机器上出两种档案。
# ---------------------------------------------------------------------------

LAST_CHOICE_PATH = Path.home() / ".config" / "nbdpsy" / "last-choice.json"


def read_last_choice(path=None):
    """读本机「上次用的那一套」。**任何毛病都返回 None**（没这个文件 / JSON 坏了 / 没有
    name / 读不动）——记忆是锦上添花，⛔ 绝不能因为它把创作流程打断。"""
    try:
        data = json.loads(Path(path or LAST_CHOICE_PATH).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"]:
        return None
    return data


def write_last_choice(name, kind, form=None, path=None):
    """记下这次实际用的那一套。写不进去只在 stderr 说一句，⛔ 绝不抛（磁盘满 / 只读 home /
    没有 ~/.config 权限都不该让一条已经成功的 --get 变成失败）。返回是否写成功。"""
    if not name:
        return False
    p = Path(path or LAST_CHOICE_PATH)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"name": name, "kind": kind, "form": form,
                                 "at": datetime.now().isoformat(timespec="seconds")},
                                ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        print(f"ℹ 没能记住这次用的那一套（{e}）——不影响本次结果，只是下次 `--last` 取不到",
              file=sys.stderr)
        return False


def remember_from_view(view: dict):
    """`--get` 成功后把「这次实际用的那一套」记到本机。⛔ 只在真的落到某一套上时记：
    没挑中（profile 为 null，实际用的是内置默认）时记下来，下次 `--last` 会取到一套
    他这次根本没用上的风格。"""
    if not isinstance(view, dict) or view.get("profile") is None:
        return False
    name = view.get("set") or view.get("profile_name")
    if not name:
        return False
    return write_last_choice(name, view.get("kind") or view.get("profile_kind"),
                             profile_form(view.get("profile")))


def say_selection(view: dict):
    """挑中 / 没挑中的人话（`--get` 与 `--version N` 共用，两处必须同一份实现——各写一遍
    就会出现两种留痕行 / 两种 outcome，审查端口径一散就判错套）。"""
    if view.get("outcome") == "ok":
        cn = KIND_CN.get(view.get("profile_kind"), view.get("profile_kind"))
        tag = "" if view.get("profile_name") == cn else f"（{cn}）"
        line = f"  挑中「{view.get('profile_name')}」这一套{tag}"
        if view.get("profile_names"):
            line += (f"；他共有 {len(view['profile_names'])} 套，"
                     f"默认是「{view.get('active_profile')}」")
        print(line, file=sys.stderr)
    else:
        print(f"· 没挑中任何一套：{view['say']}", file=sys.stderr)
        print("  → 这次会用 skill 内置默认风格；留痕行已按「内置兜底」写，"
              "别写成他的档案（审查端会拿错版本判）", file=sys.stderr)
    return view


def warn_dropped_keys(view: dict):
    """PUT / rollback 之后必须看的那一项：server 算出的「这次整份覆盖比上一版少掉的键」
    （只比顶层 + 二级，`[]` = 没丢，键恒定存在）。值原样在 stdout 里透出，这里只补人话警告——
    东西已经存进去了，服务端不拦截，所以非空时要**当场回读给运营确认**。

    多套原生化之后 dropped_keys 回到**套内部字段级**（`visual` 整段没了就是 `["visual"]`），
    补救话术也就回到最朴素的那一句：`--get` 给的是哪一套、重发的就是哪一套，一读一写对得上。"""
    dropped = view.get("dropped_keys")
    if not isinstance(dropped, list) or not dropped:
        return
    print("⚠ 本次覆盖丢掉了：" + "、".join(str(k) for k in dropped)
          + "——如果不是有意的，先 `--get` 拿全量再重发", file=sys.stderr)


def _exit_unreachable(exc: Unreachable, want=None):
    """exit 2 的唯一出口：stderr 必须明说「没连上风格档案服务」，供上层走第 ③ 层。"""
    print(f"✗ 没连上风格档案服务（{exc.reason}）：{exc.error}", file=sys.stderr)
    print(f"  → {exc.hint}", file=sys.stderr)
    print(f"  → 请这样告诉运营：{SAY_OFFLINE}", file=sys.stderr)
    print(json.dumps(offline_view(exc, want), ensure_ascii=False))
    sys.exit(EXIT_UNREACHABLE)


def get_one_set(args, key, api_base):
    """`--get` 的取数：不带 `--profile/--kind` 就是老行为（服务端给 is_active 那套）。

    带 `--profile 名`：直接 `GET ?set=名`。两种"没这套"要分清——
    404 = 他有档案但没这套；200 + `exists:false` = 他**一套都没有**，服务端忽略 set 回落到
    默认配置的 is_active 套（实测行为）：这时只有回落到的正好是他要的那个名字才算挑中，
    否则等于没挑中（否则会把「图文」的内容当成他要的「文字版」发给创作端）。

    带 `--kind k`：先列套，`is_active` 优先挑同形态的；他一套都没有时退到裸 `GET`
    看回落到的默认配置那套形态对不对得上（与多套化之前的行为一致）。

    带 `--form f`（仅视频那一类）：先列套，在 kind=video 的套里逐套取内容找 `video.form`
    对得上的那套（is_active 优先，见 `pick_by_form`）。

    带 `--last`：用本机记的「上次用的那一套」（见 `read_last_choice`）。没记录 / 记的那套
    已经不在了，都**退回裸 `--get` 的行为**（服务端 is_active），⛔ 不报错、不打断。

    没挑中 → `profile: null` + say，**exit 仍是 0**（上层照常用内置默认继续做内容）。"""
    if args.last:
        return get_last_set(args, key, api_base)
    if args.profile is None and args.kind is None and args.form is None:
        return decorate_get(call("GET", PROFILE_PATH, key, api_base, timeout=args.timeout))

    if args.form is not None:
        sets = fetch_sets(key, api_base, args.timeout)
        if sets:
            pick, raw = pick_by_form(sets, args.form, key, api_base, args.timeout)
            if pick is not None:
                view = decorate_get(raw)
                return picked_view(view, view.get("set") or pick["name"],
                                   view.get("kind") or KIND_VIDEO,
                                   names=set_names(sets), active=active_name(sets))
        else:
            # 一套都没有 = 还没建档：裸 GET 拿他跟随的默认配置那套，子形态对得上才算挑中
            view = decorate_get(call("GET", PROFILE_PATH, key, api_base, timeout=args.timeout))
            if profile_form(view.get("profile")) == args.form:
                return picked_view(view, view.get("set"), view.get("kind"))
        out = unpicked_view("no_form_match", FORM_CN.get(args.form, args.form), sets,
                            form=args.form)
        say_selection(out)
        print(json.dumps(out, ensure_ascii=False))
        return None

    if args.profile is not None:
        try:
            view = decorate_get(call("GET", with_query(PROFILE_PATH, set=args.profile),
                                     key, api_base, timeout=args.timeout))
            if view.get("exists") or view.get("set") == args.profile:
                return picked_view(view, view.get("set") or args.profile, view.get("kind"))
        except ValueError as e:
            # 只吞 404（「没这套」）；别的 4xx/5xx 照旧往上抛成 exit 1，别当成"没挑中"糊过去
            if not str(e).startswith("HTTP 404"):
                raise
        # 没这套：这时才列一次套，好把「现有哪几套」念给运营听
        sets = fetch_sets(key, api_base, args.timeout)
        out = unpicked_view("not_found", args.profile, sets, name=args.profile)
        say_selection(out)
        print(json.dumps(out, ensure_ascii=False))
        return None

    sets = fetch_sets(key, api_base, args.timeout)
    if sets:
        pick = pick_by_kind(sets, args.kind)
        if pick is not None:
            view = decorate_get(call("GET", with_query(PROFILE_PATH, set=pick["name"]),
                                     key, api_base, timeout=args.timeout))
            return picked_view(view, view.get("set") or pick["name"],
                               view.get("kind") or args.kind,
                               names=set_names(sets), active=active_name(sets))
    else:
        # 一套都没有 = 还没建档：裸 GET 拿他跟随的默认配置那套，形态对得上就算挑中
        view = decorate_get(call("GET", PROFILE_PATH, key, api_base, timeout=args.timeout))
        if view.get("kind") == args.kind:
            return picked_view(view, view.get("set"), view.get("kind"))
    out = unpicked_view("no_kind_match", KIND_CN.get(args.kind, args.kind), sets, kind=args.kind)
    say_selection(out)
    print(json.dumps(out, ensure_ascii=False))
    return None


def get_last_set(args, key, api_base):
    """`--get --last`：用本机记的那一套。**三种情况都优雅退回裸 `--get`**（服务端 is_active）：

      ① 没有 `~/.config/nbdpsy/last-choice.json`（新机器 / 头一次用）
      ② 文件坏了（JSON 残缺、被别的东西覆盖、没有 name 字段）
      ③ 记的那套已经不在了（改名 / 删了 / 换了个账号的 key）

    三种都只在 stderr 说一句就往下走，⛔ 绝不抛、绝不非零退出——「按上次」是省事用的，
    它自己出毛病不该让运营今天做不成内容。"""
    last = read_last_choice()
    if last is None:
        print("· 本机没有「上次用的那一套」的记录（或记录已损坏），这次按你的默认那套来",
              file=sys.stderr)
        return decorate_get(call("GET", PROFILE_PATH, key, api_base, timeout=args.timeout))
    name = last["name"]
    try:
        view = decorate_get(call("GET", with_query(PROFILE_PATH, set=name), key, api_base,
                                 timeout=args.timeout))
    except ValueError as e:
        # 只吞 404（那套没了）；别的 4xx/5xx 照旧往上抛成 exit 1，别当成"没记录"糊过去
        if not str(e).startswith("HTTP 404"):
            raise
        view = None
    # 零套运营带 set 会被服务端忽略而回落到默认配置那套：名字对不上就不算命中
    if view is None or not (view.get("exists") or view.get("set") == name):
        print(f"· 上次用的「{name}」已经不在你的档案里了（改名或删了），这次按你的默认那套来",
              file=sys.stderr)
        return decorate_get(call("GET", PROFILE_PATH, key, api_base, timeout=args.timeout))
    print(f"· 按上次：用「{name}」这一套（上次用于 {last.get('at') or '未知时间'}）",
          file=sys.stderr)
    return picked_view(view, view.get("set") or name, view.get("kind"))


def manage_set(args, key, api_base):
    """建套 / 切默认 / 改名 / 删套：一条命令打一个 /sets 端点，**没有守卫 GET、没有乐观锁**。

    这四个端点的 409 都**不是版本冲突**（重名 / 只剩一套），所以不能走 exit 3 那条
    「先重新 --get 再来」的剧本——重新读一遍再删还是同样结果，只会让上层绕圈。
    统一翻成人话 + exit 1（服务端明确拒绝）。"""
    timeout = args.timeout
    if args.new_profile is not None:
        name = args.new_profile.strip()
        if not name:
            raise ValueError("新套的名字不能是空的")
        kind, payload = args.kind, {"name": name, "kind": args.kind}
        if args.file is not None:
            content = load_set_file(args.file)
            if content.get("kind") in KINDS and content["kind"] != kind:
                print(f"⚠ 文件里写的形态是 {content['kind']}，命令行 --kind 是 {kind}——"
                      f"按命令行算（文件里的被覆盖）", file=sys.stderr)
            if kind == KIND_VIDEO and profile_form(content) not in (None, args.form):
                print(f"⚠ 文件里写的子形态是 {profile_form(content)}，命令行 --form 是 "
                      f"{args.form}——按命令行算（文件里的被覆盖）", file=sys.stderr)
            payload["profile"] = dict(content, kind=kind)
            if kind == KIND_VIDEO:
                # 子形态是取套的唯一钥匙（`--form` 靠它挑套），必须与命令行一致，
                # 否则建出来的套永远挑不中：运营会以为「建了但没生效」
                video = payload["profile"].get("video")
                payload["profile"]["video"] = dict(video if isinstance(video, dict) else {},
                                                   form=args.form)
            src_desc = f"来自 {args.file}"
        elif args.from_profile is not None:
            # 复制交给服务端做（`from` 只认**他自己名下**的套），这里只先核一次形态：
            # 图文与文字版的字段根本不是一回事，复制串了会得到一套确定坏掉的档案
            sets = fetch_sets(key, api_base, timeout)
            src = next((s for s in sets if s.get("name") == args.from_profile), None)
            if src is None:
                raise ValueError(f"没有叫「{args.from_profile}」的风格可复制："
                                 f"现有的是 {'、'.join(set_names(sets)) or '（一套都没有）'}")
            if src.get("kind") != kind:
                raise ValueError(
                    f"「{args.from_profile}」是「{KIND_CN.get(src.get('kind'), src.get('kind'))}」"
                    f"那一类，不能复制成「{KIND_CN[kind]}」的——三种形态的字段根本不同"
                    f"（图文有插画与信息点，文字版只有排版，视频是四条产线的旋钮）。"
                    f"要建「{KIND_CN[kind]}」那套，去掉 --from 直接用骨架")
            if kind == KIND_VIDEO:
                # 服务端的 `from` 是**原样复制内容**，`video.form` 会跟着被复制过来：
                # 拿播客那套复制成「微电影」，建出来的套 form 仍是 podcast，`--form microfilm`
                # 永远挑不中它（运营会以为「建了但没生效」），且旋钮字段整套是别条产线的
                src_view = call("GET", with_query(PROFILE_PATH, set=args.from_profile),
                                key, api_base, timeout=timeout)
                src_form = profile_form(src_view.get("profile"))
                if src_form != args.form:
                    raise ValueError(
                        f"「{args.from_profile}」是「{FORM_CN.get(src_form, src_form)}」那条产线的，"
                        f"不能复制成「{FORM_CN[args.form]}」的——四条产线的旋钮完全不同"
                        f"（放映有页间停顿、播客有男女双声、微电影有子风格三档）。"
                        f"要建「{FORM_CN[args.form]}」那套，去掉 --from 直接用骨架")
            payload["from"] = args.from_profile
            src_desc = f"复制自「{args.from_profile}」"
        else:
            content, src_desc = default_set_content(kind, key, api_base, timeout, form=args.form)
            payload["profile"] = dict(content, kind=kind)
        for w in (profile_warnings(payload["profile"], kind) if "profile" in payload else []):
            print(f"⚠ {w}", file=sys.stderr)
        view = conflict_as_error(
            lambda: call("POST", SETS_PATH, key, api_base, payload, timeout=timeout),
            f"你已经有一套叫「{name}」的风格了——换个名字，或者直接改那一套"
            f"（--get --profile {name} 拿全量再 --put）")
        # 套名本来就叫「文字版」时不再缀一遍形态（「文字版（文字版，…）」这种话没法听）；
        # 视频那类报**子形态**（说「视频」等于没说，四条产线的调性天差地别）
        cn = FORM_CN[args.form] if kind == KIND_VIDEO else KIND_CN[kind]
        tag = src_desc if name == cn else f"{cn}，{src_desc}"
        done = f"已新建「{view.get('name', name)}」（{tag}）"
        if view.get("is_active"):
            done += "；这是他的第一套，已自动成为默认"
    elif args.set_active is not None:
        view = call("PATCH", set_path(args.set_active), key, api_base, {"is_active": True},
                    timeout=timeout)
        done = f"默认已切到「{args.set_active}」"
    elif args.rename_profile is not None:
        old, new = args.rename_profile
        view = conflict_as_error(
            lambda: call("PATCH", set_path(old), key, api_base, {"new_name": new},
                         timeout=timeout),
            f"已经有一套叫「{new}」了，换个名字")
        done = f"「{old}」已改名为「{new}」"
    else:
        view = conflict_as_error(
            lambda: call("DELETE", set_path(args.delete_profile), key, api_base, timeout=timeout),
            f"「{args.delete_profile}」是你最后一套风格，删不得——一套都不剩的档案等于把你清空了。"
            f"要换风格请直接改这一套（--get 拿全量再 --put），或者先新建一套再删这套")
        done = f"已删掉「{args.delete_profile}」"
    sets = fetch_sets(key, api_base, timeout)
    # 拷一份再挂 profiles：view 本身就是 sets 里那一行的同构体，原地挂会拼出自引用
    view = dict(view, profiles=sets, active_profile=active_name(sets))
    print(f"✓ {done}", file=sys.stderr)
    print(f"  现在他有 {len(sets)} 套：{shown_sets(sets)}", file=sys.stderr)
    return view


def conflict_as_error(do, human: str):
    """套管理端点的 409 是业务拒绝（重名 / 只剩一套），不是乐观锁冲突：翻成人话往 exit 1 走，
    别让它冒充「档案在别处被改过」而把上层引去重新 --get（那条路解决不了这两种 409）。"""
    try:
        return do()
    except Conflict as e:
        raise ValueError(f"{human}（服务端：{e.error}）") from None


def init_sets(key, api_base, timeout) -> dict:
    """`--init-sets`：服务端**不给新运营预建套**，按「默认配置有几套」在他名下建齐。

    `from` 复制不了默认配置的套（实测：`from` 只在**同一个人名下**找套，跨 scope 找不到 → 404），
    所以走「读默认配置那套的内容 → 带着内容 POST」这条路。取不到内容就报错退出，
    ⛔ 绝不建出空套（空套 = 一套确定坏掉的档案，而且看不出来）。"""
    defaults = fetch_sets(key, api_base, timeout, scope=SCOPE_ADMIN_DEFAULT)
    if not defaults:
        raise ValueError("默认配置里一套风格都没有，没法照着给他建——请找运营老大先把默认配置"
                         "建起来（--admin-default），或者用 --new-profile 手动给他建一套")
    mine = fetch_sets(key, api_base, timeout)
    have = set(set_names(mine))
    created, skipped = [], []
    # is_active 那套先建：服务端「首套自动成默认」，顺序错了默认套就落到别的套上
    for s in sorted(defaults, key=lambda x: not x.get("is_active")):
        name, kind = s.get("name"), s.get("kind")
        if name in have:
            skipped.append(name)
            continue
        view = call("GET", with_query(ADMIN_DEFAULT_PATH, set=name), key, api_base,
                    timeout=timeout)
        content = view.get("profile")
        if not isinstance(content, dict) or not content:
            raise ValueError(f"默认配置里「{name}」那套是空的，不能拿它建套（会建出一套空档案）"
                             f"——请找运营老大先把这套内容填上，或用 --new-profile 手动建")
        call("POST", SETS_PATH, key, api_base,
             {"name": name, "kind": kind, "profile": content}, timeout=timeout)
        created.append(name)
    sets = fetch_sets(key, api_base, timeout)
    out = {"ok": True, "created": created, "skipped": skipped, "profiles": sets,
           "active_profile": active_name(sets), "count": len(sets)}
    if created:
        out["say"] = (f"给你建好了 {len(created)} 套自己的风格：{shown_sets(sets)}；"
                      f"往后运营老大再改默认配置也不会动到你这几套了")
    else:
        out["say"] = f"你已经有 {len(sets)} 套风格了（{shown_sets(sets)}），这次一套都没动"
    print(f"✓ {out['say']}", file=sys.stderr)
    if skipped:
        print(f"  · 这几套他早就有了，原样没碰：{'、'.join(skipped)}", file=sys.stderr)
    return out


def requested_set_name(args):
    """这次点名要的是哪一套（只有 `--get` / `--version N` 配 `--profile/--kind` 才有）。
    降级 / 没挑中时的留痕行要带上它。"""
    if getattr(args, "profile", None):
        return args.profile
    picking = getattr(args, "get", False) or getattr(args, "version", None) is not None
    if getattr(args, "form", None) and picking:
        return FORM_CN.get(args.form, args.form)
    if getattr(args, "kind", None) and picking:
        return KIND_CN.get(args.kind, args.kind)
    if getattr(args, "last", False):
        # 连不上时读不到服务端也照样能说清「他要的是哪一套」——本机记忆本来就在本地
        last = read_last_choice()
        if last:
            return last["name"]
    return None


def main():
    ap = _Parser(description="读写当前运营的风格档案（经 nbdpsy-api，纯 REST；多套由服务端原生承载）")
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
    # ---- 多套风格档案（服务端原生）；不带这些参数时，上面几个子命令的行为一字不变 ----
    ap.add_argument("--list-profiles", action="store_true",
                    help="列出你有几套风格（名字/形态/哪套是默认）。还没建档的人列出的是他跟随的默认配置")
    ap.add_argument("--profile", metavar="套名",
                    help="仅 --get / --version N：只取这一套（外层照旧带 exists / base_version / "
                         "trace_line；配 --version 时取的是这一套的那一版）")
    ap.add_argument("--kind", choices=list(KINDS), metavar="carousel|typeset|video",
                    help="仅 --get / --version N / --new-profile：形态。carousel=图文轮播、"
                         "typeset=文字版、video=视频。--get / --version 时取该形态下在用的那套；"
                         "--new-profile 时是必填")
    ap.add_argument("--form", choices=list(VIDEO_FORMS),
                    metavar="slideshow|card|microfilm|podcast",
                    help="仅视频那一类：子形态。slideshow=放映、card=字卡、microfilm=微电影、"
                         "podcast=播客（四条产线的旋钮完全不同，一个子形态一套）。"
                         "--get / --version / --put 等取该子形态那套；--new-profile --kind video "
                         "时是必填。不必再传 --kind video（带了 --form 就是视频那一类）")
    ap.add_argument("--last", action="store_true",
                    help="仅 --get：**按上次**——用这台机器上次实际用的那一套"
                         "（记在 ~/.config/nbdpsy/last-choice.json）。没记录 / 记的那套已被删，"
                         "都退回服务端默认那套，不报错")
    ap.add_argument("--new-profile", metavar="套名",
                    help="新建一套（须配 --kind）。默认拿默认配置里同形态那套当骨架；"
                         "也可 --from 复制已有的一套，或 --file 用给定 JSON（参考图拆解产物走这条）")
    ap.add_argument("--from", dest="from_profile", metavar="已有套名",
                    help="仅 --new-profile：复制这一套改个名（形态必须与 --kind 一致）")
    ap.add_argument("--file", type=Path, metavar="SET.JSON",
                    help="仅 --new-profile：用这份 JSON 当新套的内容（只收**一套**，不收整份档案）")
    ap.add_argument("--set-active", metavar="套名", help="切默认用哪套（运营没点明形态时兜底用它）")
    ap.add_argument("--rename-profile", nargs=2, metavar=("旧名", "新名"), help="给某一套改名")
    ap.add_argument("--delete-profile", metavar="套名",
                    help="删掉某一套（**删到只剩一套时服务端拒绝**）")
    ap.add_argument("--init-sets", action="store_true",
                    help="新运营建档：照**默认配置有几套**在他名下建齐同名同形态的套"
                         "（服务端不自动预建；已有的同名套跳过不覆盖）")
    ap.add_argument("--limit", type=int, default=None,
                    help="仅 --versions：每页条数（服务端默认 50、上限 200，超出钳到 200）")
    ap.add_argument("--offset", type=int, default=None,
                    help="仅 --versions：从第几条起（配合响应里的 has_more 翻页取更早的）")
    ap.add_argument("--base-version", type=int, default=None,
                    help="你 --get 读到的**那一套**当前 version（exists:false 时传 0）；"
                         "--put/--rollback 必填。建套/改名/删/切默认不需要它（那些动作没有乐观锁）")
    ap.add_argument("--source", default="manual",
                    choices=["manual", "reference_sample", "inherited_admin"],
                    help="本次改动来源（默认 manual；rollback 由服务端自己写，PUT 不接受）")
    ap.add_argument("--note", help="本次改动说明（≤500 字），如「按参考样本 8 张实测更新」")
    ap.add_argument("--api-base", help="API base（默认凭据 NBDPSY_XHS_API_BASE 或 https://mcp.nbdpsy.com）")
    ap.add_argument("--timeout", type=float, default=30, help="单次请求超时秒数（默认 30）")
    args = ap.parse_args()

    # 套管理四个动作打的是 /sets 那几个端点（独立资源，服务端不收 base_version）
    multi_writes = [args.new_profile is not None, args.set_active is not None,
                    args.rename_profile is not None, args.delete_profile is not None]
    actions = [bool(args.get), bool(args.get_default), bool(args.versions),
               args.version is not None, args.put is not None, args.rollback is not None,
               args.admin_default is not None, bool(args.list_profiles),
               bool(args.init_sets)] + multi_writes
    if sum(actions) != 1:
        ap.error("恰好指定一个动作：--get / --get-default / --versions / --version N / "
                 "--put FILE / --rollback N / --admin-default FILE / --list-profiles / "
                 "--init-sets / --new-profile 名 / --set-active 名 / --rename-profile 旧 新 / "
                 "--delete-profile 名")
    # 硬约束 2：整份覆盖不猜版本号——不传 --base-version 直接报错，绝不用「最新版」代替
    if (args.put is not None or args.rollback is not None) and args.base_version is None:
        ap.error("--put / --rollback 必须带 --base-version：先跑 --get 拿到那一套的 version"
                 "（exists:false 时传 0）。整份覆盖不替你猜版本号。")
    if any(multi_writes) and args.base_version is not None:
        # 老文档 / 老肌肉记忆还会传它。硬报错会让运营卡住，静默吃掉又会让人以为这几步有并发保护
        # （服务端实测：建套/改名/删/切默认都不收 base_version，压根没有乐观锁）——所以说一句再忽略
        print("ℹ 建套 / 改名 / 删套 / 切默认**不需要 --base-version**（这几个动作没有版本冲突），"
              "已忽略你传的这个值", file=sys.stderr)
    # 「按套操作」的动作：server 这几个端点都收 ?set=，不点名就落到 is_active 那套。
    # ⛔ 读能点名而写不能点名 = 运营以为在改文字版、实际改的是图文那套（静默错套）。
    picking = (bool(args.get) or args.version is not None or args.versions
               or args.put is not None or args.rollback is not None
               or args.admin_default is not None)
    if args.profile is not None and not picking:
        ap.error("--profile 只能配 --get / --version N / --versions / --put / --rollback / "
                 "--admin-default 用（点名某一套）；要建/改名/删/切默认请用 "
                 "--new-profile / --rename-profile / --delete-profile / --set-active")
    if args.kind is not None and not (picking or args.new_profile is not None):
        ap.error("--kind 只能配 --get / --version N / --versions / --put / --rollback / "
                 "--admin-default（取该形态在用的那套）"
                 "或 --new-profile（新建这套的形态）用")
    if args.profile is not None and args.kind is not None:
        ap.error("--profile 与 --kind 二选一：要么按套名取，要么按形态取")
    if args.new_profile is not None and args.kind is None:
        ap.error("--new-profile 必须带 --kind carousel|typeset|video（图文 / 文字版 / 视频）——"
                 "三种形态的字段完全不同，脚本不替你猜")
    # --form：视频那一类的子形态。带了 --form 就是视频那类，不必再写 --kind video
    if args.form is not None and not (picking or args.new_profile is not None):
        ap.error("--form 只能配 --get / --version N / --versions / --put / --rollback / "
                 "--admin-default（取该子形态那套）或 --new-profile --kind video（新建这套的"
                 "子形态）用")
    if args.form is not None and args.kind not in (None, KIND_VIDEO):
        ap.error(f"--form 是视频那一类专用的：--kind {args.kind} 没有子形态。"
                 f"要取视频那类请写 --form <子形态>（不必再带 --kind video）")
    if args.form is not None and args.profile is not None:
        ap.error("--profile 与 --form 二选一：要么按套名取，要么按子形态取")
    if args.new_profile is not None and args.kind == KIND_VIDEO and args.form is None:
        ap.error("--new-profile --kind video 必须带 --form "
                 "slideshow|card|microfilm|podcast（放映 / 字卡 / 微电影 / 播客）——"
                 "四条产线的旋钮完全不同，一个子形态一套，脚本不替你猜")
    if args.form is not None and args.new_profile is None and args.kind == KIND_VIDEO:
        # 取套只按 form 走（kind 只在列表里，挑不出子形态），说一句免得以为 --kind 也在起作用
        print("ℹ 取视频那类只按 --form 挑套（--kind video 是多余的，已忽略）", file=sys.stderr)
        args.kind = None
    # --last：本机记忆是「没人点名时才用」的省事入口，跟点名同时出现必是搞混了
    if args.last and not args.get:
        ap.error("--last 只能配 --get 用（按上次实际用的那一套取档案）")
    if args.last and (args.profile is not None or args.kind is not None or args.form is not None):
        ap.error("--last 与 --profile / --kind / --form 二选一："
                 "要么按上次，要么这次点名要哪一套")
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
            view = get_one_set(args, key, api_base)
            if view is None:            # 点名的那一套不存在：话已在 get_one_set 里说完
                return
            if view.get("exists"):
                print(f"✓ 第 ① 层·他自己的档案：{view['say']}", file=sys.stderr)
            else:
                print(f"· 第 ② 层·默认配置（**别说成是他的**）：{view['say']}", file=sys.stderr)
                if view.get("admin_default_version") is not None:
                    print(f"  正在用默认配置 v{view['admin_default_version']}"
                          f"（运营老大一改，你这边下次 --get 立刻跟着变）", file=sys.stderr)
            if view.get("outcome") == "ok":
                say_selection(view)
            src = ("server 下发（唯一真源）" if view.get("base_version_source") == "server"
                   else "本地派生（这台 server 没下发，属老版本）")
            print(f"  --put / --rollback 请用 base_version={view['base_version']}（{src}）"
                  f"——它是**这一套自己的**版本号", file=sys.stderr)
            print(f"  留痕行（写进 00-overview.md 开头）：{view['trace_line']}", file=sys.stderr)
            # 本机记一笔「这次实际用的是哪一套」，供下次 `--get --last`。
            # ⛔ 写失败不影响这次结果（write_last_choice 自己吞异常）
            remember_from_view(view)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.list_profiles:
            sets = fetch_sets(key, api_base, args.timeout)
            exists = bool(sets)
            if not exists:
                # 还没建档的人：列出来的是**他跟随的那份默认配置**有几套（读侧不设门）
                sets = fetch_sets(key, api_base, args.timeout, scope=SCOPE_ADMIN_DEFAULT)
            shown = shown_sets(sets)
            out = {"ok": True, "exists": exists, "profiles": sets,
                   "active_profile": active_name(sets), "count": len(sets)}
            out["say"] = (f"你有 {out['count']} 套风格：{shown}；"
                          f"现在默认用「{out['active_profile']}」") if exists else SAY_MISSING
            print(f"✓ {out['say']}", file=sys.stderr)
            if not exists:
                print(f"  （默认配置里是 {out['count']} 套：{shown}；他要有自己的，"
                      f"跑一次 --init-sets 按这个套数建齐）", file=sys.stderr)
            print("  改某一套的内容：--get --profile 套名 拿全量 → 改 → --put（带那一套的 "
                  "base_version）；建套/改名/删/切默认不需要版本号", file=sys.stderr)
            print(json.dumps(out, ensure_ascii=False))
            return

        if args.init_sets:
            print(json.dumps(init_sets(key, api_base, args.timeout), ensure_ascii=False))
            return

        if any(multi_writes):
            print(json.dumps(manage_set(args, key, api_base), ensure_ascii=False))
            return

        if args.versions:
            target = resolve_target_set(args, key, api_base)
            path = with_query("/api/style-profile/versions", limit=args.limit,
                              offset=args.offset, set=target)
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
            # 服务端按 ?set= 直接给**那一套**的那一版（profile.visual.* 可直读），不再本地挑
            name, kind, names = args.profile, args.kind, None
            if args.form is not None:
                sets = fetch_sets(key, api_base, args.timeout)
                pick, _ = pick_by_form(sets, args.form, key, api_base, args.timeout)
                if pick is None:
                    view = unpicked_view("no_form_match", FORM_CN.get(args.form, args.form),
                                         sets, form=args.form)
                    say_selection(view)
                    print(json.dumps(view, ensure_ascii=False))
                    return
                name, kind, names = pick["name"], KIND_VIDEO, set_names(sets)
            elif kind is not None:
                sets = fetch_sets(key, api_base, args.timeout)
                pick = pick_by_kind(sets, kind)
                if pick is None:
                    view = unpicked_view("no_kind_match", KIND_CN.get(kind, kind), sets, kind=kind)
                    say_selection(view)
                    print(json.dumps(view, ensure_ascii=False))
                    return
                name, names = pick["name"], set_names(sets)
            view = call("GET", with_query(f"/api/style-profile/versions/{args.version}", set=name),
                        key, api_base, timeout=args.timeout)
            print(f"✓ v{args.version} 的内容如下（只是预览，没动当前档案）", file=sys.stderr)
            if name is not None:
                # 审查端按留痕行取回这一版再读 profile.visual.*：留痕行与 `--get --profile/--kind`
                # 共用 picked_view/_trace_line_named，两处口径散了就会判错套
                view = say_selection(picked_view(view, view.get("set") or name,
                                                 view.get("kind") or kind, names=names))
                print(f"  留痕行（写进 00-overview.md 开头）：{view['trace_line']}", file=sys.stderr)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.put is not None:
            profile = load_profile(args.put)
            warnings = profile_warnings(profile)
            for w in warnings:
                print(f"⚠ {w}", file=sys.stderr)
            payload = {"base_version": args.base_version, "profile": profile,
                       "source": args.source}
            if args.note:
                payload["note"] = args.note
            target = resolve_target_set(args, key, api_base)
            view = call("PUT", with_query(PROFILE_PATH, set=target), key, api_base, payload,
                        timeout=args.timeout)
            view["warnings"] = warnings
            confirm_wrote_set(view, target)
            print(f"✓ 已整份覆盖「{view.get('set') or '默认那套'}」，存为 "
                  f"v{view.get('version')}（此后这一套的笔记都按这一版走）", file=sys.stderr)
            warn_dropped_keys(view)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.rollback is not None:
            payload = {"to_version": args.rollback, "base_version": args.base_version}
            target = resolve_target_set(args, key, api_base)
            view = call("POST", with_query("/api/style-profile/rollback", set=target),
                        key, api_base, payload, timeout=args.timeout)
            confirm_wrote_set(view, target)
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
            warnings = profile_warnings(profile)
            for w in warnings:
                print(f"⚠ {w}", file=sys.stderr)
            payload = {"profile": profile}
            if args.note:
                payload["note"] = args.note
            target = resolve_target_set(args, key, api_base)
            view = call("PUT", with_query(ADMIN_DEFAULT_PATH, set=target), key, api_base, payload,
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

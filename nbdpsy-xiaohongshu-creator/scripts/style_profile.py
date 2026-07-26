#!/usr/bin/env python3
"""读写「当前运营的风格档案」（经 nbdpsy-api，纯 REST，共 5 个端点）。

风格档案 = 每个运营**自己**的一份视觉 / 语气 / 结构 / 密度设定：创作端按它写绘图提示词，
审查端按它判。现在写死在 skill 里的莫兰迪三色 + 固定人物卡那一套，只是**管理员的档案**，
不是全局常量——别的运营可以与它完全不同（多号矩阵各有调性）。

用法：
    python3 style_profile.py --get                          # 读当前档案（**先看 exists**）
    python3 style_profile.py --versions                     # 列历史版本（不含 profile 全文）
    python3 style_profile.py --version 3                    # 取某一版完整内容（回退前预览）
    python3 style_profile.py --put profile.json --base-version 3
        [--source manual|reference_sample|inherited_admin] [--note "按参考样本 8 张实测更新"]
    python3 style_profile.py --rollback 3 --base-version 7  # 回到 v3 的内容（会落成新版本 v8）

凭据：NBDPSY_XHS_API_KEY（与发布线同一把）、NBDPSY_XHS_API_BASE（可选，默认 https://mcp.nbdpsy.com），
由 nbdpsy_common 三层解析（环境变量 > workspace/.env > 用户级 secrets.env）。
**这把 key 是可选凭据**——没配的运营照样要能做内容，见下面 exit 2。

三条硬约束（说错 / 做错就会把运营的档案搞坏，逐条对照）：

1. **`--get` 先看 `exists` 再说话**：`true` = 这是他自己的档案（回读请他确认）；
   `false` = 他还没有，`profile` 是**管理员默认那套**（要问「先沿用管理员的风格，可以吗？」）。
   两句话已按契约逐字写进输出的 `say` 字段与 stderr，**直接照念，别自行改写**——
   说错会让运营以为管理员那套已经是他的了。
2. **`--put` 是整份覆盖不是打补丁**：先 `--get` 拿全量 → 改完整体回传；只发被改的字段会把
   其余字段清空。所以 `--put` / `--rollback` **强制要求 `--base-version`**，不传直接报错，
   绝不替你猜版本号（`exists:false` 时传 0）。
3. **收到 409 别重试同一份 body**：说明档案在别处被改过了。本脚本收到 409 只报不重发，
   并把服务端 `detail.current_version` 原样透出，请按它提示运营重新 `--get` 后再改。

⚠️ `profile` 服务端**原样存取、不校验语义**；其中 density 的五个 key 是**中文**
（信息密度档位 / 每页文字量 / 每页信息点 / 版式档 / 运营原话），v1.37.0 起创作端与审查端
都按这五个中文 key 读写，**改写成英文即断链**。`--put` 前会做一次提醒式检查（只警告不拦截）。

输出契约：stdout 纯 JSON、stderr 人话。exit 码：
    0 = 成功
    1 = 服务端明确报错（400 profile 超 64KB / 404 该版本不存在 / 其它 4xx·5xx）或本地入参不合法
    2 = **读不到风格档案服务**（没配 key / 网络不可达 / 超时 / 401·403 鉴权失败）——
        stderr 明说「没连上风格档案服务」，上层据此走三层降级的第 ③ 层：
        用 skill 内置默认风格（管理员那套）继续，并**显式告知运营**，不许静默降级
    3 = 409 版本冲突（不重试；stdout 带 current_version）
    4 = 用法错误（如 --put 缺 --base-version）。刻意不用 argparse 默认的 2——
        2 已被征用作「没连上」信号，用法错误若也回 2，上层会误判服务挂了而降级

`--get` 会在服务端字段之外补四个派生字段（server 不返回，纯本地推导）：
`base_version`（直接拿去 --put/--rollback 的版本号）、`layer`（落在降级链哪一层）、
`say`（照念的那句话）、`trace_line`（写进 00-overview.md 的留痕行——审查端按这一行
指定的版本判，不按当前最新版；档案会变还能回退，拿新版判老批次必错）。
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
SAY_MISSING = "你还没有自己的风格档案，先沿用管理员的那套，可以吗？"
SAY_OFFLINE = ("没连上风格档案服务，本次用 skill 内置的默认风格（管理员那套）继续；"
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


def call(method: str, path: str, key: str, api_base: str, payload=None, timeout=30) -> dict:
    """调一次端点（**不含任何重试**）。网络/鉴权失败 → Unreachable；409 → Conflict；
    其它 4xx·5xx → ValueError。成功返回解析后的 dict。"""
    url = f"{api_base}{path}"
    try:
        resp = send_request(method, url, key, payload, timeout)
    except ModuleNotFoundError as e:
        raise Unreachable("no_requests", str(e),
                          "缺 Python 依赖 requests：pip install requests 后重试") from e
    except Exception as e:
        raise Unreachable("network", sandbox_hint(e),
                          "网络或沙盒拦截：跑 nbdpsy_common.py sandbox allow 后重启 Claude 再试") from e
    if resp.status_code in (401, 403):
        raise Unreachable("unauthorized", api_error(resp),
                          "apikey 无效/已轮换或无此权限：找管理员重发「运营接入配置包」，"
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
    """给 GET 结果补四个派生字段（server 不返回，纯本地推导）：
    base_version / layer / say / trace_line，见模块 docstring 末段。"""
    out = dict(view)
    if view.get("exists"):
        v = view.get("version")
        out["base_version"] = v
        out["layer"] = "user_profile"          # 三层降级链第 ① 层：他自己的档案
        out["say"] = SAY_EXISTS.format(version=v)
        out["trace_line"] = f"风格档案：v{v}（本人档案，读取于 {_today()}）"
    else:
        # 没有个人档案时服务端把「当前版本」记作 0，首次 PUT 就传 base_version=0
        out["base_version"] = 0
        out["layer"] = "admin_default"         # 第 ② 层：管理员默认档案，**别说成是他的**
        out["say"] = SAY_MISSING
        out["trace_line"] = f"风格档案：v0（管理员默认，读取于 {_today()}）"
    return out


def offline_view(exc: Unreachable) -> dict:
    """第 ③ 层：读不到服务时的输出。带 say/trace_line，好让上层照说、照留痕，不静默降级。"""
    return {"ok": False, "exists": None, "layer": "builtin_fallback", "reason": exc.reason,
            "error": exc.error, "hint": exc.hint, "say": SAY_OFFLINE,
            "trace_line": f"风格档案：v—（内置兜底，读取于 {_today()}）"}


def load_profile(path) -> dict:
    """读 --put 的 JSON。两道防呆（都是会把真档案冲掉且运营看不出来的场景）：
    直接喂 --get 整份输出时自动剥出 profile；空对象直接拒绝。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是 JSON 对象，不能当 profile 存")
    if "exists" in data and isinstance(data.get("profile"), dict):
        print("ℹ 传进来的是 --get 的整份输出，已自动取其中的 profile 字段再上传", file=sys.stderr)
        data = data["profile"]
    if not data:
        raise ValueError(f"{path} 里的 profile 是空对象——整份覆盖会把档案清空，已拒绝")
    return data


def profile_warnings(profile: dict):
    """上传前的提醒（只警告不拦截，服务端本就原样存取不校验语义）。"""
    w = []
    size = len(json.dumps(profile, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PROFILE_BYTES:
        w.append(f"profile {size} 字节超 {MAX_PROFILE_BYTES} 上限，服务端会报 400（不截断）")
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


def _exit_unreachable(exc: Unreachable):
    """exit 2 的唯一出口：stderr 必须明说「没连上风格档案服务」，供上层走第 ③ 层。"""
    print(f"✗ 没连上风格档案服务（{exc.reason}）：{exc.error}", file=sys.stderr)
    print(f"  → {exc.hint}", file=sys.stderr)
    print(f"  → 请这样告诉运营：{SAY_OFFLINE}", file=sys.stderr)
    print(json.dumps(offline_view(exc), ensure_ascii=False))
    sys.exit(EXIT_UNREACHABLE)


def main():
    ap = _Parser(description="读写当前运营的风格档案（经 nbdpsy-api，5 端点）")
    ap.add_argument("--get", action="store_true",
                    help="读当前档案（先看 exists：true=他自己的；false=管理员默认那套）")
    ap.add_argument("--versions", action="store_true", help="列历史版本（倒序，不含 profile 全文）")
    ap.add_argument("--version", type=int, metavar="N", help="取第 N 版完整内容（回退前预览）")
    ap.add_argument("--put", type=Path, metavar="PROFILE.JSON",
                    help="整份覆盖存新版本（**不是打补丁**；须配 --base-version）")
    ap.add_argument("--rollback", type=int, metavar="N",
                    help="回退到第 N 版（造新版本而非拨指针；须配 --base-version）")
    ap.add_argument("--base-version", type=int, default=None,
                    help="你 --get 读到的当前 version（exists:false 时传 0）；--put/--rollback 必填")
    ap.add_argument("--source", default="manual",
                    choices=["manual", "reference_sample", "inherited_admin"],
                    help="本次改动来源（默认 manual；rollback 由服务端自己写，PUT 不接受）")
    ap.add_argument("--note", help="本次改动说明（≤500 字），如「按参考样本 8 张实测更新」")
    ap.add_argument("--api-base", help="API base（默认凭据 NBDPSY_XHS_API_BASE 或 https://mcp.nbdpsy.com）")
    ap.add_argument("--timeout", type=float, default=30, help="单次请求超时秒数（默认 30）")
    args = ap.parse_args()

    actions = [bool(args.get), bool(args.versions), args.version is not None,
               args.put is not None, args.rollback is not None]
    if sum(actions) != 1:
        ap.error("恰好指定一个动作：--get / --versions / --version N / --put FILE / --rollback N")
    # 硬约束 2：整份覆盖不猜版本号——不传 --base-version 直接报错，绝不用「最新版」代替
    if (args.put is not None or args.rollback is not None) and args.base_version is None:
        ap.error("--put / --rollback 必须带 --base-version：先跑 --get 拿到 version"
                 "（exists:false 时传 0）。整份覆盖不替你猜版本号。")

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        # 可选凭据：没配的运营照样要能做内容 → 走第 ③ 层，不是致命错
        _exit_unreachable(Unreachable(
            "no_key", f"MISSING:{nbdpsy_common.XHS_API_KEY}",
            "找管理员要「运营接入配置包」，secret import 导入后重试；"
            "这把 key 是可选凭据，没有也能用 skill 内置默认风格继续做内容"))
    api_base = (args.api_base or nbdpsy_common.xhs_api_base()).rstrip("/")

    try:
        if args.get:
            view = decorate_get(call("GET", "/api/style-profile", key, api_base,
                                     timeout=args.timeout))
            if view.get("exists"):
                print(f"✓ 第 ① 层·他自己的档案：{view['say']}", file=sys.stderr)
            else:
                print(f"· 第 ② 层·管理员默认档案（**别说成是他的**）：{view['say']}", file=sys.stderr)
            print(f"  留痕行（写进 00-overview.md 开头）：{view['trace_line']}", file=sys.stderr)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.versions:
            view = call("GET", "/api/style-profile/versions", key, api_base, timeout=args.timeout)
            n = len(view.get("versions") or [])
            print(f"✓ 历史版本 {n} 个（倒序）；先 --version N 预览内容，确认了再 --rollback N",
                  file=sys.stderr)
            print(json.dumps(view, ensure_ascii=False))
            return

        if args.version is not None:
            view = call("GET", f"/api/style-profile/versions/{args.version}", key, api_base,
                        timeout=args.timeout)
            print(f"✓ v{args.version} 的内容如下（只是预览，没动当前档案）", file=sys.stderr)
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
            view = call("PUT", "/api/style-profile", key, api_base, payload, timeout=args.timeout)
            view["warnings"] = warnings
            print(f"✓ 已整份覆盖，存为 v{view.get('version')}（此后你的笔记都按这一版走）",
                  file=sys.stderr)
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
            print(json.dumps(view, ensure_ascii=False))
            return

    except Unreachable as e:
        _exit_unreachable(e)
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

#!/usr/bin/env python3
"""服务号自定义菜单：查线上现状 / 应用本地 JSON / 删除整个菜单。

**本地 JSON 文件是编辑真源**：先 `--get` 把线上现状拉成基线文件，改文件，再 `--apply`。
别在公众平台后台和这里两头改——apply 是**整体覆盖**，后台那边加的入口会被这份文件顶掉。

用法:
    python3 menu_ops.py --get > {workspace}/wechat/menu.json     # 拉线上现状当基线
    python3 menu_ops.py --apply {workspace}/wechat/menu.json     # 只打 diff，不改线上（安全闸门）
    python3 menu_ops.py --apply {workspace}/wechat/menu.json --confirm   # 念完 diff、运营确认后才真改
    python3 menu_ops.py --delete            # 只打警示，不删（安全闸门）
    python3 menu_ops.py --delete --confirm  # 真删整个自定义菜单

输出（stdout 纯 JSON；人话提示与 diff 走 stderr，不污染管道）:
    --get           线上菜单结构本身 `{"button": [...]}`——**可以直接改完拿去 --apply**。
                    exit 0。线上还没有自定义菜单时给一份空骨架 `{"button": []}` 并在 stderr 说明。
    --apply/--delete `{"outcome":"done|failed|unknown", ...}`：done exit 0；failed exit 1；
                    unknown exit 0（结果未确认，先 --get 核实，别直接重跑）。
                    **不带 --confirm 时一律 failed exit 1**——那不是故障，是「本次没执行」的闸门。

三条要跟运营讲清楚的事（不是脚本能兜住的，得靠话术）:
  · **apply 是整体覆盖**：线上菜单被这份文件完全替换，文件里没写的入口就没了。
  · **菜单有约 24 小时客户端缓存**：apply 成功后粉丝不一定马上看到，让运营**取消关注再关注**
    可立即验证——提前说明，免得运营以为没生效反复 apply。
  · **挂进菜单的链接必须是已发布文章的正式 url**（从 `article_ops.py --ledger` 取），
    ⛔ 别挂草稿预览链接，那种链接会过期。

微信侧硬约束（超了本脚本直接拒发，不浪费一次调用）:
  一级菜单最多 3 个；每个一级下二级最多 5 个；没有三级。
  一级名 ≤4 个汉字、二级 ≤7 个汉字属**显示**约束（超了微信截断成 `...`），只警告不拦。

凭据: NBDPSY_WECHAT_API_KEY；基址默认 database.nbdpsy.com，可用 --api-base 覆盖。
"""
import argparse
import json
import sys
from pathlib import Path

# 同目录 vendored 副本
import nbdpsy_common  # noqa: F401  —— wechat_api 经它解析凭据与基址
import wechat_api
from wechat_api import OpFailed

MAX_TOP = 3          # 一级菜单上限
MAX_SUB = 5          # 每个一级下的二级上限
TOP_NAME_WIDTH = 4   # 一级名显示上限（汉字计）
SUB_NAME_WIDTH = 7   # 二级名显示上限
NO_MENU_ERRCODE = 46003   # 「不存在的菜单数据」——没建过菜单，不是故障

CACHE_NOTE = ("菜单有约 24 小时客户端缓存：粉丝不一定马上看到新菜单。"
              "让运营**取消关注再重新关注**即可立即验证，别反复 apply。")


def _width(name: str) -> float:
    """显示宽度：汉字算 1，ASCII 算 0.5（微信按「4 个汉字或 8 个字母」计）。"""
    return sum(1 if ord(c) > 127 else 0.5 for c in name or "")


def action_of(button: dict) -> str:
    """一个按钮到底干什么——diff 里给运营看的人话摘要。"""
    subs = button.get("sub_button") or []
    if subs:
        return f"{len(subs)} 个二级"
    target = (button.get("url") or button.get("key") or button.get("appid")
              or button.get("media_id") or button.get("article_id") or "")
    return f"{button.get('type') or '?'} {target}".strip()


def validate(buttons):
    """按微信硬约束校验，返回警告列表；硬约束不过直接 OpFailed（请求都不发出去）。"""
    if not isinstance(buttons, list) or not buttons:
        raise OpFailed("菜单里没有按钮：`button` 必须是非空数组。"
                       "（要删掉整个菜单请用 `--delete --confirm`，别用空菜单 apply）")
    if len(buttons) > MAX_TOP:
        raise OpFailed(f"一级菜单 {len(buttons)} 个，超过微信上限 {MAX_TOP} 个——"
                       "请合并入口后再 apply。")
    warnings = []
    names = [b.get("name") if isinstance(b, dict) else None for b in buttons]
    if len(set(names)) != len(names):
        warnings.append("有重名的一级菜单：diff 只能按名字比对，这种情况下 diff 可能不准，"
                        "apply 前请人工核对整份文件。")
    for b in buttons:
        if not isinstance(b, dict) or not (b.get("name") or "").strip():
            raise OpFailed(f"有一级菜单缺 name：{json.dumps(b, ensure_ascii=False)[:120]}")
        name = b["name"]
        if _width(name) > TOP_NAME_WIDTH:
            warnings.append(f"一级菜单「{name}」超过 {TOP_NAME_WIDTH} 个汉字，手机上会截断成 `...`")
        subs = b.get("sub_button") or []
        if subs:
            if len(subs) > MAX_SUB:
                raise OpFailed(f"一级菜单「{name}」下有 {len(subs)} 个二级，超过微信上限 {MAX_SUB} 个。")
            for s in subs:
                if not isinstance(s, dict) or not (s.get("name") or "").strip():
                    raise OpFailed(f"「{name}」下有二级菜单缺 name：{json.dumps(s, ensure_ascii=False)[:120]}")
                if s.get("sub_button"):
                    raise OpFailed(f"「{name}」下的二级「{s['name']}」还挂了 sub_button——"
                                   "微信没有三级菜单，这层会被整个丢掉。")
                if _width(s["name"]) > SUB_NAME_WIDTH:
                    warnings.append(f"二级菜单「{s['name']}」超过 {SUB_NAME_WIDTH} 个汉字，"
                                    "手机上会截断成 `...`")
                _check_action(s, f"「{name}」下的二级「{s['name']}」")
        else:
            _check_action(b, f"一级菜单「{name}」")
    return warnings


def _check_action(button: dict, label: str):
    """叶子按钮必须说清点了干什么，否则粉丝点上去毫无反应。"""
    kind = button.get("type")
    if not kind:
        raise OpFailed(f"{label}既没有 sub_button 也没有 type——粉丝点了不会有任何反应。"
                       "跳链接用 `\"type\":\"view\"` + `url`，回复消息用 `\"type\":\"click\"` + `key`。")
    if kind == "view" and not (button.get("url") or "").strip():
        raise OpFailed(f"{label}是 view 型却没有 url。挂文章请用已发布文章的正式 url"
                       "（`article_ops.py --ledger` 里取），别挂会过期的草稿预览链接。")
    if kind == "click" and not (button.get("key") or "").strip():
        raise OpFailed(f"{label}是 click 型却没有 key。")


def menu_diff(old, new):
    """线上菜单 vs 本地文件的人话 diff。按 name 比对——名字就是运营眼里的按钮身份。"""
    old, new = old or [], new or []
    o = {b.get("name", ""): b for b in old if isinstance(b, dict)}
    n = {b.get("name", ""): b for b in new if isinstance(b, dict)}
    lines = []
    for name, nb in n.items():
        ob = o.get(name)
        if ob is None:
            lines.append(f"新增一级菜单「{name}」（{action_of(nb)}）")
            continue
        osub = {s.get("name", ""): s for s in (ob.get("sub_button") or []) if isinstance(s, dict)}
        nsub = {s.get("name", ""): s for s in (nb.get("sub_button") or []) if isinstance(s, dict)}
        if bool(osub) != bool(nsub):
            lines.append(f"一级菜单「{name}」形态变化：{action_of(ob)} → {action_of(nb)}")
        elif not osub and action_of(ob) != action_of(nb):
            lines.append(f"一级菜单「{name}」动作变更：{action_of(ob)} → {action_of(nb)}")
        for sname, ns in nsub.items():
            if sname not in osub:
                lines.append(f"「{name}」下新增二级「{sname}」（{action_of(ns)}）")
            elif action_of(osub[sname]) != action_of(ns):
                lines.append(f"「{name}」下二级「{sname}」动作变更："
                             f"{action_of(osub[sname])} → {action_of(ns)}")
        for sname in osub:
            if sname not in nsub:
                lines.append(f"「{name}」下删除二级「{sname}」（原 {action_of(osub[sname])}）")
    for name, ob in o.items():
        if name not in n:
            lines.append(f"删除一级菜单「{name}」（原 {action_of(ob)}）")
    if list(o) != list(n) and set(o) == set(n) and not lines:
        lines.append(f"只调了一级菜单顺序：{' | '.join(o)} → {' | '.join(n)}")
    return {"lines": lines, "changed": bool(lines),
            "top_level": {"before": list(o), "after": list(n)}}


def fetch_menu(api_base, key, timeout):
    """取线上菜单，返回 (buttons | None, note)。

    46003（没建过自定义菜单）**不是故障**——第一次装修菜单本来就没有基线，返回 None。
    其余错误照常抛（拿不到基线时 apply 仍可继续，但 diff 会缺席，见 do_apply）。
    """
    data = wechat_api.proxy_call(api_base, key, "/cgi-bin/menu/get", {}, timeout)
    menu = data.get("menu") if isinstance(data.get("menu"), dict) else {}
    note = None
    if data.get("conditionalmenu"):
        note = ("这个服务号还配了**个性化菜单**（conditionalmenu）：本 skill 第一版不管它，"
                "apply 只覆盖默认菜单，个性化菜单原样留着。")
    return menu.get("button") or [], note


def _fetch_menu_tolerant(api_base, key, timeout):
    """apply/delete 前拿基线：拿不到也不该挡住动作，降级成「没有 diff」并说清原因。"""
    try:
        buttons, note = fetch_menu(api_base, key, timeout)
        return buttons, note
    except OpFailed as e:
        if e.extra.get("wechat_errcode") == NO_MENU_ERRCODE:
            return None, "线上目前没有通过 API 建的自定义菜单（46003），本次是从零建一份。"
        return None, f"没能拉到线上现状（{e.error}），**本次给不出 diff**——请人工核对文件内容再决定。"


def do_get(args, api_base, key):
    try:
        buttons, note = fetch_menu(api_base, key, args.timeout)
    except OpFailed as e:
        if e.extra.get("wechat_errcode") != NO_MENU_ERRCODE:
            raise
        buttons, note = [], None
        wechat_api.warn("⚠ 线上还没有通过 API 建的自定义菜单（46003）。已给你一份空骨架，"
                        "填好 button 再 --apply 即可建立。")
        wechat_api.warn("⚠ 若运营在公众平台后台手动配过菜单：那套和 API 这套口径不同，"
                        "menu/get 查不到它，而 apply 会**整体覆盖**掉它——动手前先跟运营确认。")
    if note:
        wechat_api.warn(f"⚠ {note}")
    wechat_api.warn(f"提示：这份 JSON 改完可以直接 `--apply` 回去。{CACHE_NOTE}")
    # stdout 只放菜单结构本身：`--get > menu.json` 出来的文件要能直接编辑再 apply
    return {"button": buttons}, 0


def load_menu_file(path):
    """读本地菜单 JSON，返回 button 数组。文件读不出来 = 参数校验不过 = 确定失败。"""
    p = Path(path)
    if not p.is_file():
        raise OpFailed(f"菜单文件不存在：{p}——先 `--get > {p}` 拉一份线上现状当基线再改。")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise OpFailed(f"菜单文件不是合法 JSON（{p}，第 {e.lineno} 行第 {e.colno} 列：{e.msg}）"
                       "——多半是漏了逗号或多了尾逗号。")
    except OSError as e:
        raise OpFailed(f"菜单文件读不出来（{p}）：{type(e).__name__}: {e}")
    if isinstance(data, dict) and "outcome" in data and "button" not in data:
        raise OpFailed(f"{p} 里装的是一份**脚本回执**（outcome={data.get('outcome')}），不是菜单——"
                       "多半是上次 `--get` 失败了、把错误信封重定向进了这个文件。重新 `--get` 一次。")
    if isinstance(data, dict) and isinstance(data.get("menu"), dict):
        data = data["menu"]              # 兼容直接存了微信 menu/get 原始响应的情况
    buttons = data.get("button") if isinstance(data, dict) else data
    if buttons is None:
        raise OpFailed(f"{p} 里没有 `button` 字段——菜单文件的形状是 "
                       '`{"button": [ {...}, {...} ]}`。')
    return buttons


def do_apply(args, api_base, key):
    buttons = load_menu_file(args.apply)
    warnings = validate(buttons)                       # 硬约束不过：一个请求都不发
    old, note = _fetch_menu_tolerant(api_base, key, args.timeout)
    diff = menu_diff(old, buttons) if old is not None else None

    if not args.confirm:
        wechat_api.warn("⚠ 这次**没有改线上菜单**（缺 --confirm）。要改什么，念给运营听：")
        if note:
            wechat_api.warn(f"  · {note}")
        if diff is None:
            wechat_api.warn("  · （拿不到线上现状，这次给不出 diff）")
        elif not diff["lines"]:
            wechat_api.warn("  · （与线上现状没有差异）")
        else:
            for line in diff["lines"]:
                wechat_api.warn(f"  · {line}")
        wechat_api.warn("  · apply 是**整体覆盖**：文件里没写的入口会从线上消失。")
        for w in warnings:
            wechat_api.warn(f"  ⚠ {w}")
        return {"outcome": "failed",
                "error": "未带 --confirm：本次只算了 diff，**没有改线上菜单**"
                         "（这是安全闸门，不是故障）。",
                "diff": diff, "warnings": warnings, "baseline_note": note,
                "hint": f"把上面的 diff 逐条念给运营，确认后加 --confirm 重跑同一条命令。{CACHE_NOTE}"}, 1

    if diff is not None and not diff["changed"]:
        wechat_api.warn("⚠ 这份文件与线上现状没有差异，仍会照常提交一次（menu/create 是整体覆盖，幂等）。")
    wechat_api.proxy_call(api_base, key, "/cgi-bin/menu/create", {"button": buttons},
                          args.timeout, irreversible=True)
    return {"outcome": "done", "applied_top_level": [b.get("name") for b in buttons],
            "diff": diff, "warnings": warnings, "baseline_note": note,
            "hint": CACHE_NOTE}, 0


def do_delete(args, api_base, key):
    old, note = _fetch_menu_tolerant(api_base, key, args.timeout)
    current = [b.get("name") for b in old] if old else []

    if not args.confirm:
        wechat_api.warn("⚠ 这次**没有删除任何东西**（缺 --confirm）。删除的代价：")
        wechat_api.warn(f"  · 粉丝**立刻**看不到底部入口（现有一级菜单："
                        f"{' | '.join(current) or '拉不到/无'}）。")
        wechat_api.warn("  · 想恢复只能重新 apply 一份 menu.json——**先把现状 `--get` 存下来再删**。")
        if note:
            wechat_api.warn(f"  · {note}")
        return {"outcome": "failed",
                "error": "未带 --confirm：本次**没有删除**自定义菜单（这是安全闸门，不是故障）。",
                "current_top_level": current, "baseline_note": note,
                "hint": "先 `--get > menu.json` 把现状存下来当回滚基线，把上面的代价讲给运营，"
                        "确认后加 --confirm 重跑。"}, 1

    wechat_api.proxy_call(api_base, key, "/cgi-bin/menu/delete", {},
                          args.timeout, irreversible=True)
    return {"outcome": "done", "deleted_top_level": current,
            "hint": f"自定义菜单已删除，粉丝端受 24 小时缓存影响可能还看得到残影。{CACHE_NOTE}"
                    "要恢复请把之前 `--get` 存的 menu.json 重新 --apply。"}, 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="服务号自定义菜单：查 / 应用 / 删除")
    ap.add_argument("--get", action="store_true", help="拉线上菜单（stdout 即可直接编辑的 menu.json）")
    ap.add_argument("--apply", metavar="menu.json", help="把本地菜单 JSON 应用到线上（整体覆盖）")
    ap.add_argument("--delete", action="store_true", help="删除整个自定义菜单（粉丝立刻看不到入口）")
    ap.add_argument("--confirm", action="store_true",
                    help="真正执行 --apply / --delete；不带它只打 diff/警示，不碰线上")
    ap.add_argument("--api-base", dest="api_base", help="覆盖服务基址（默认走凭据/内置默认）")
    ap.add_argument("--timeout", type=float, default=wechat_api.DEFAULT_TIMEOUT, help="单次请求超时秒数")
    args = ap.parse_args(argv)

    chosen = [f for f in (args.get, bool(args.apply), args.delete) if f]
    if len(chosen) != 1:
        ap.error("三选一：--get / --apply <menu.json> / --delete")

    def action():
        api_base, key = wechat_api.credentials(args.api_base)
        if args.get:
            return do_get(args, api_base, key)
        if args.apply:
            return do_apply(args, api_base, key)
        return do_delete(args, api_base, key)

    return wechat_api.run(action)


if __name__ == "__main__":
    sys.exit(main())

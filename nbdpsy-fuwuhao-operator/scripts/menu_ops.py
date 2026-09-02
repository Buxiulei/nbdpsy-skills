#!/usr/bin/env python3
"""服务号自定义菜单：查线上现状 / 应用本地 JSON / 删除整个菜单。

🔴 **归属（2026-09-02 裁定，⛔ 别按旧说法「本地 JSON 是编辑真源」办事）**：
**线上菜单本体归服务号线，在公众号后台手改**；本 skill 只持一份**只读快照**当恢复基线。
⇒ `--apply` / `--delete` **只在老板或服务号线明令时才用**，⛔ 越界改线上菜单。
日常「菜单该长什么样」不在这里决定——这里只负责「删坏了能照着快照恢复」。

基线快照（受版本控制，私有仓 Buxiulei/NBDpsy）:
    seo-geo/content/wechat/menu-baseline.json      ← **稳定文件名**，更新即覆盖
⚠️ **稳定名⛔不带日期**：带日期的名字会让闸门每次先猜「最新的是哪个日期」；
   捕获时间写在**提交说明**里，⛔ 不往文件里加元数据键（加键会破坏 `--apply` 的输入契约）。
⚠️ 快照里的 `conditionalmenu`（个性化菜单）**本 skill 恢复不了**，只能照着去后台手工重挂。

🔴 **「约定路径」在两个上下文下指向两个地方——`{workspace}` 不是一个固定值**：
`nbdpsy_common.resolve_workspace()` 先看 `$NBDPSY_WORKSPACE`，再看 `$PWD/seo-geo/content`
是否存在，都没有才回落 `~/nbdpsy-content`。
⇒ **在 NBDpsy 仓根运行时 workspace 落 `seo-geo/content/`，那才是基线真源**；
   在别处运行会解到 `~/nbdpsy-content`，那里**没有**基线。
🩸 2026-09-02 实证：正因为这两个上下文，「基线文件不存在」与「基线文件在那儿」**同时为真**——
   `~/nbdpsy-content/wechat/` 下确实没有，而仓内 `seo-geo/content/wechat/menu.json`
   躺着一份 **2026-08-04 的残缺快照**（只含默认菜单、无 `conditionalmenu`、不含日报入口）。
   那份**比没有更危险**（照它恢复只回来一半，人却以为已按基线恢复过），已于 2026-09-02 删除。
   ⇒ 查「基线在不在」必须**说清在哪个 workspace 下查的**，⛔ 只报「没找到」。

📌 **快照入库前要扫的字段名**（这是本快照的敏感串清单，⛔ 不是凭据泄漏判据）:
    access_token / appsecret / secret / password / bearer / private_key —— 出现即⛔不入库；
    **appid** —— **不是密钥**（它要配上 AppSecret 才可用，本仓另有 9 个文件含它），
    列在这里是为了让清单**完整**，⛔ 别据此写成「appid 是密钥」去做判断。
⚠️ 扫完要跑一次**正对照**（拿必然含敏感串的样本打同一条正则），否则「零命中」可能只是正则瞎了。

用法:
    python3 menu_ops.py --get > <基线路径>            # 拉线上全量现状存快照（只读，随时可跑）
    python3 menu_ops.py --apply <基线路径>            # 只打 diff，不改线上（安全闸门）
    python3 menu_ops.py --apply <改过的文件> --confirm --approval <件号>-<选项键>   # 真改，需批复坐标
    python3 menu_ops.py --apply <基线路径> --restore --confirm --approval <件号>-<选项键>  # 恢复
    python3 menu_ops.py --delete            # 只打警示，不删（安全闸门）
    python3 menu_ops.py --delete --confirm --approval <件号>-<选项键>  # 真删，需批复坐标

🔴 **写命令的三道前置闸**（2026-09-02 裁定），顺序固定 **①→②→③，⛔ 不能反**：
    ① **基线文件存在**否 —— 否则拒，并打印**我找的是哪个绝对路径** + 怎么修；
    ② **基线已提交**否（`git status` 看 dirty）—— dirty 则拒，措辞**明确区别于「内容不一致」**
       （混了会让人去翻菜单内容，而病在没提交）；
    ③ **线上全量 vs 基线**逐字段比 —— 不一致即拒、点名字段、给两个方向的处置。
⚠️ ②依赖「在 git 仓库内」，而那由①保证 ⇒ **①必须在②之前**，
   ⛔ 反过来会在非仓目录里跑 `git status` 拿到一个误导性的错误。
⇒ ③ 的实际效果是「**没有当前基线就删不了**」——而 delete 恰恰最需要基线。
⚠️ **只读预检（不带 `--confirm`）不受①②③管制**——拦了会逼人为了「看一眼菜单长什么样」
   也去满足这些条件；但预检会把「真执行时会被拦」**预告**出来，免得补了 `--confirm` 白跑两轮。
🔴 **`--apply --confirm` 成功后自动刷新基线**：把新的线上全量写回稳定路径、打印 diff 摘要，
   并给出可直接执行的 `git add && git commit`——⛔ **不替人提交**。
   不刷新的话，每次合法改菜单之后基线立刻陈旧，而人最省事的绕法是「重拉基线」，
   那会把线上的误改**固化进基线**。
🔑 **恢复走 `--restore`，⛔ 不靠「文件是不是基线」猜意图**：推断出来的意图**会被意外满足**
   （有人拿基线当新菜单 apply 一次就静默进了恢复模式、绕过闸门而没人知道）。
   ⇒ 拿基线文件直接 `--apply` 而不带 `--restore` ⇒ **拒**，提示你把意图说出来。
⚠️ **核不了一致性时一律拒**（拿不到线上现状）——「查不到」不等于「一致」，
   这道闸的失效方向不能是绿；确实要在核不了时强行恢复，那正是 `--restore` 的用途。

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
import subprocess
import sys
from pathlib import Path

# 同目录 vendored 副本（凭据与基址由 wechat_api 经 nbdpsy_common 解析）。
# ⚠️ nbdpsy_common 这里**只读用一个** `resolve_workspace()` 来算基线快照路径，
#    ⛔ 不改它的解析逻辑——那个函数是所有 skill 共用的，改它的返回值会让别的 skill 产物落到别处。
import nbdpsy_common
import wechat_api
from wechat_api import OpFailed

MAX_TOP = 3          # 一级菜单上限
MAX_SUB = 5          # 每个一级下的二级上限
TOP_NAME_WIDTH = 4   # 一级名显示上限（汉字计）
SUB_NAME_WIDTH = 7   # 二级名显示上限
NO_MENU_ERRCODE = 46003   # 「不存在的菜单数据」——没建过菜单，不是故障

CACHE_NOTE = ("菜单有约 24 小时客户端缓存：粉丝不一定马上看到新菜单。"
              "让运营**取消关注再重新关注**即可立即验证，别反复 apply。")

# 基线快照在 workspace 下的相对位置。⚠️ 只有这一处写死它，改落点只改这里。
BASELINE_RELPATH = Path("wechat") / "menu-baseline.json"


def baseline_path() -> Path:
    """基线快照的**绝对路径**。⛔ 这里只算路径，不判断存不存在。

    ⚠️ 它经 `nbdpsy_common.resolve_workspace()` 得出，因此**随 cwd 变**：
    在 NBDpsy 仓根跑 ⇒ `<仓根>/seo-geo/content/wechat/menu-baseline.json`（真源）；
    在别处跑 ⇒ `~/nbdpsy-content/wechat/menu-baseline.json`（那里通常没有）。
    ⇒ 拿不到时必须**报出这个绝对路径**（见 load_baseline），
      ⛔ 别静默回落到别处找——**静默回落正是造成整件事的机制**：
      同一个「约定路径」在两个上下文下指向两处、一处空一处躺着错的，
      而没有任何东西跳出来说「你查的不是那个」。
    """
    return nbdpsy_common.resolve_workspace() / BASELINE_RELPATH


def load_baseline() -> dict:
    """读基线快照。找不到 ⇒ **报错退出并说清找的是哪个绝对路径**。

    🔴 ⛔ 返回空 dict、⛔ 回落 cwd、⛔ 回落别的 workspace ——
    那些都会让闸门在错的上下文下变成**静默 no-op**（失效方向是绿）。
    """
    p = baseline_path()
    if not p.is_file():
        raise OpFailed(
            f"基线快照不在：{p}\n"
            "⚠️ 这个路径随**当前工作目录**变（`resolve_workspace()`：先看 $NBDPSY_WORKSPACE，"
            "再看 $PWD/seo-geo/content，都没有才回落 ~/nbdpsy-content）。"
            "⇒ 先确认两件事：① 你是不是**在 NBDpsy 仓根**跑的（那才是基线真源）；"
            f"② 文件是不是真的没有——是的话先 `--get > {p}` 拉一份并提交。"
            "⛔ 本次一个写请求都没发出。")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise OpFailed(f"基线快照不是合法 JSON（{p}，第 {e.lineno} 行第 {e.colno} 列：{e.msg}）。")
    if not isinstance(data, dict) or "button" not in data:
        raise OpFailed(f"基线快照里没有 `button` 字段（{p}）——它不是一份菜单快照。")
    return data


def _walk_fields(node, 前缀=""):
    """把嵌套菜单摊平成 {JSON 路径: 值}，用来**点名到底哪个字段变了**。"""
    出: dict[str, object] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            出.update(_walk_fields(v, f"{前缀}.{k}" if 前缀 else k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            出.update(_walk_fields(v, f"{前缀}[{i}]"))
    else:
        出[前缀] = node
    return 出


def baseline_drift(线上: dict, 基线: dict) -> list[str]:
    """线上全量 vs 基线快照的**字段级**差异。空列表 = 一致。

    ⚠️ 逐字段比而不是只比一级菜单名：闸门要能说出**是哪个字段**变了，
    否则「不一致」这三个字帮不了正在排查的人。
    """
    a, b = _walk_fields(基线), _walk_fields(线上)
    行 = []
    for k in sorted(set(a) | set(b)):
        if k not in b:
            行.append(f"基线有、线上没有：`{k}` = {a[k]!r}")
        elif k not in a:
            行.append(f"线上有、基线没有：`{k}` = {b[k]!r}")
        elif a[k] != b[k]:
            行.append(f"`{k}`：基线 {a[k]!r} → 线上 {b[k]!r}")
    return 行


def _基线未提交(p: Path):
    """基线在 git 里是不是 dirty。返回 (True/False/None, 详情)；None = **拿不准**。

    🔴 **必须在「基线存在」那道闸之后调用**：不在 git 仓库里时 git 会报错，
       那种情况该由前一道闸先拒 —— ⛔ 别在非仓目录里跑 `git status` 拿一个误导性的错误。
    """
    r = subprocess.run(["git", "-C", str(p.parent), "status", "--porcelain", "--", str(p)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stderr.strip().splitlines() or ["git 调用失败"])[-1]
    return bool(r.stdout.strip()), (r.stdout.strip() or None)


def 写前闸门(动作: str):
    """写命令的前两道闸。返回 (基线内容, 拒绝回执|None)。

    🔴 顺序固定 ①基线存在 → ②基线已提交，⛔ 不能反（②依赖「在 git 仓库内」，而那由①保证）。
    🔑 ②堵的是「刷新了但没提交」——不堵它，自动刷新只会把陈旧基线从**仓里**搬到**工作区里**，
       病还在（而且别人 clone 下来拿到的仍是旧的那份）。
    """
    基线 = load_baseline()                      # ① 不存在就在这里抛（消息里带绝对路径 + 怎么修）
    p = baseline_path()
    dirty, 详情 = _基线未提交(p)
    if dirty is None:
        return 基线, ({"outcome": "failed",
                      "error": f"**核不了基线有没有提交**（{p} 多半不在 git 仓库里；git 说：{详情}），"
                               f"本次{动作}**没有执行**。"
                               "⛔ 「核不了」不等于「已提交」——这道闸的失效方向不能是绿。",
                      "baseline": str(p),
                      "hint": "基线必须放在受版本控制的位置（NBDpsy 仓 `seo-geo/content/wechat/`）。"
                              "⚠️ 这**不是**「线上与基线内容不一致」，⛔ 别去查菜单内容。"}, 1)
    if dirty:
        return 基线, ({"outcome": "failed",
                      "error": f"基线文件**尚未提交**（git 里是 dirty），本次{动作}**没有执行**。"
                               "⚠️ 这**不是**「线上与基线内容不一致」——是那份基线自己还没进版本库。"
                               "⛔ 别去查菜单内容，先把它提交了。",
                      "baseline": str(p), "git_status": 详情,
                      "hint": f"先提交基线：`git add {p} && "
                              "git commit -m \"chore(服务号): 更新菜单基线\"`，再重跑本命令。"
                              "（刷新了却不提交，等于把陈旧基线从仓里搬到工作区里，病还在。）"}, 1)
    return 基线, None


def 闸门预告() -> list[str]:
    """只读预检专用：把写路径上会撞到的闸门**预告**出来。⛔ 只 warn 不拒。

    ⚠️ 裁定：只读预检**不受**①②③管制（拦了会逼人为了「看一眼菜单」也去满足这些条件）。
       但**不拦 ≠ 不说** —— 不预告的话，人补了 `--confirm` 重跑才被拦，白跑两轮。
    """
    p = baseline_path()
    if not p.is_file():
        return [f"🔴 基线快照不在 `{p}` —— **真要执行时会被拦**。"
                "先确认你是不是在 NBDpsy 仓根跑（或设 $NBDPSY_WORKSPACE），"
                f"确实没有就 `--get > {p}` 拉一份并提交。"]
    dirty, _ = _基线未提交(p)
    if dirty is None:
        return [f"🔴 核不了基线有没有提交（`{p}` 多半不在 git 仓库里）—— **真要执行时会被拦**。"]
    if dirty:
        return [f"🔴 基线文件**尚未提交**（dirty）—— **真要执行时会被拦**。"
                f"先 `git add {p} && git commit`。"]
    return []


def 刷新基线(api_base, key, timeout, 旧基线: dict) -> None:
    """apply 成功后把**新的线上全量**写回基线稳定路径，并打印 diff 摘要与提交命令。

    ⛔ **不替人 commit**：提交是人的动作（何况这份文件在别人的工作区里）。
    🔑 不刷新的话，每次合法改菜单之后基线立刻陈旧，下一条写命令会被③拦住——
       而人最省事的绕法是「重拉基线」，那会把线上的误改**固化进基线**。
    """
    p = baseline_path()
    try:
        buttons, cond, _ = fetch_menu(api_base, key, timeout)
    except OpFailed as e:
        wechat_api.warn(f"⚠ 改是改成功了，但**没能刷新基线**（{e.error}）。"
                        f"⇒ 请手动补一次：`--get > {p}` 再提交，⛔ 别把陈旧基线留在仓里。")
        return
    新 = {"button": buttons}
    if cond:
        新["conditionalmenu"] = cond
    变化 = baseline_drift(新, 旧基线)
    p.write_text(json.dumps(新, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    wechat_api.warn(f"✅ 已把新的线上全量写回基线：{p}")
    if 变化:
        wechat_api.warn(f"   基线 diff 摘要（共 {len(变化)} 处）：")
        for line in 变化[:10]:
            wechat_api.warn(f"     · {line}")
        if len(变化) > 10:
            wechat_api.warn(f"     · …… 另有 {len(变化) - 10} 处")
    wechat_api.warn("🔴 **它还没提交**——下一条写命令会因此被拦。现在就执行：")
    wechat_api.warn(f"   git add {p} && git commit -m \"chore(服务号): 更新菜单基线\"")


def 漂移拒绝(差异: list[str], 动作: str) -> dict:
    """一致性闸门的拒绝回执。**两个方向都要给话**，⛔ 只说一个。"""
    for line in 差异:
        wechat_api.warn(f"  · {line}")
    return {"outcome": "failed",
            "error": f"线上菜单与基线快照**不一致**，本次{动作}**没有执行**（这是安全闸门，不是故障）。",
            "drift": 差异, "baseline": str(baseline_path()),
            "hint": "两个方向，先判断是哪一种：\n"
                    "① **线上比基线新**（有人在公众号后台改过菜单）⇒ 先 "
                    f"`--get > {baseline_path()}` 更新基线**并提交**，再来；\n"
                    "② **基线比线上新**（基线里有还没上线的改动）⇒ 确认你是要把它 apply 上去"
                    "（那就加 `--restore`），还是先把基线里那些改动丢弃。\n"
                    "⛔ 别不看方向就重拉基线——那会把线上的误改**固化进基线**。"}


def _width(name: str) -> float:
    """显示宽度：汉字算 1，ASCII 算 0.5（微信按「4 个汉字或 8 个字母」计）。"""
    return sum(1 if ord(c) > 127 else 0.5 for c in name or "")


def action_of(button: dict) -> str:
    """一个按钮到底干什么——diff 里给运营看的人话摘要。"""
    subs = button.get("sub_button") or []
    if subs:
        return f"{len(subs)} 个二级"
    btype = button.get("type") or "?"
    if btype == "miniprogram":
        # 小程序按钮的身份是 appid+pagepath。只看 url（那是非微信环境的网页回落）
        # 会让「换了跳转的小程序页面」这种改动在 diff 里完全隐身。
        target = f"{button.get('appid') or ''} {button.get('pagepath') or ''}".strip()
    else:
        target = (button.get("url") or button.get("key")
                  or button.get("media_id") or button.get("article_id") or "")
    return f"{btype} {target}".strip()


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
        # 顺序就是运营眼里「谁排最上面」，本身是一次改动，必须单独报出来
        if set(osub) == set(nsub) and list(osub) != list(nsub):
            lines.append(f"「{name}」下二级顺序调整（自上而下）："
                         f"{' | '.join(osub)} → {' | '.join(nsub)}")
    for name, ob in o.items():
        if name not in n:
            lines.append(f"删除一级菜单「{name}」（原 {action_of(ob)}）")
    if set(o) == set(n) and list(o) != list(n):
        lines.append(f"一级菜单顺序调整：{' | '.join(o)} → {' | '.join(n)}")
    return {"lines": lines, "changed": bool(lines),
            "top_level": {"before": list(o), "after": list(n)}}


def fetch_menu(api_base, key, timeout):
    """取线上菜单，返回 (buttons | None, conditional, note)。

    46003（没建过自定义菜单）**不是故障**——第一次装修菜单本来就没有基线，返回 None。
    其余错误照常抛（拿不到基线时 apply 仍可继续，但 diff 会缺席，见 do_apply）。

    🔴 **conditionalmenu 必须一并返回**（2026-09-02 裁定）。原先这里只取 `menu.button`、
    把个性化菜单打一句提示就丢掉——**量具结构性地看不到它要量的那个东西**：
    `--delete` 恰恰会把个性化菜单一起删掉，而本 skill 没有重建能力，
    于是「唯一的基线」偏偏漏掉「唯一恢复不了的部分」。⛔ 别再把它丢了。
    """
    data = wechat_api.proxy_call(api_base, key, "/cgi-bin/menu/get", {}, timeout)
    menu = data.get("menu") if isinstance(data.get("menu"), dict) else {}
    cond = data.get("conditionalmenu")
    cond = cond if isinstance(cond, list) else []
    note = None
    if cond:
        note = (f"这个服务号还配了 **{len(cond)} 条个性化菜单**（conditionalmenu）：它们已经一并存进"
                "本次 `--get` 的输出里（`conditionalmenu` 字段），⛔ 但 `--apply` **不会**把它们建回去"
                "（本 skill 没有 menu/addconditional 能力）——那份文件对它们只是**存档**，不是回滚手段。"
                "⚠ `--delete` 会把它们连同默认菜单一起删掉，删掉后只能去公众平台后台重挂。")
    return menu.get("button") or [], cond, note


def _fetch_menu_tolerant(api_base, key, timeout):
    """apply/delete 前拿基线：拿不到也不该挡住动作，降级成「没有 diff」并说清原因。"""
    try:
        buttons, cond, note = fetch_menu(api_base, key, timeout)
        return buttons, cond, note
    except OpFailed as e:
        if e.extra.get("wechat_errcode") == NO_MENU_ERRCODE:
            return None, [], "线上目前没有通过 API 建的自定义菜单（46003），本次是从零建一份。"
        return None, [], f"没能拉到线上现状（{e.error}），**本次给不出 diff**——请人工核对文件内容再决定。"


def do_get(args, api_base, key):
    try:
        buttons, cond, note = fetch_menu(api_base, key, args.timeout)
    except OpFailed as e:
        if e.extra.get("wechat_errcode") != NO_MENU_ERRCODE:
            raise
        buttons, cond, note = [], [], None
        wechat_api.warn("⚠ 线上还没有通过 API 建的自定义菜单（46003）。已给你一份空骨架，"
                        "填好 button 再 --apply 即可建立。")
        wechat_api.warn("⚠ 若运营在公众平台后台手动配过菜单：那套和 API 这套口径不同，"
                        "menu/get 查不到它，而 apply 会**整体覆盖**掉它——动手前先跟运营确认。")
    if note:
        wechat_api.warn(f"⚠ {note}")
    wechat_api.warn(f"提示：这份 JSON 改完可以直接 `--apply` 回去（`--apply` 只读 `button`，"
                    f"`conditionalmenu` 是存档字段、会被原样忽略）。{CACHE_NOTE}")
    # stdout 只放菜单结构本身：`--get > menu.json` 出来的文件要能直接编辑再 apply。
    # 🔴 `conditionalmenu` 是**新增的兄弟字段**（2026-09-02），⛔ 不是改形状：
    #    `load_menu_file` 取的一直是 `button`，所以旧文件喂新代码、新文件喂旧消费者都照常。
    #    没有个性化菜单时不写这个键，免得给人「这里本来该有东西」的错觉。
    out = {"button": buttons}
    if cond:
        out["conditionalmenu"] = cond
    return out, 0


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
    # 🔴 文件里带着 conditionalmenu 存档时必须说破：apply 只建默认菜单，
    #    ⛔ 别让人以为「把基线 apply 回去 = 全都恢复了」——个性化菜单本 skill 建不回来。
    cond = data.get("conditionalmenu") if isinstance(data, dict) else None
    if cond:
        n = len(cond) if isinstance(cond, list) else "?"
        wechat_api.warn(f"⚠ {p.name} 里存了 **{n} 条个性化菜单**（conditionalmenu），"
                        "本次 `--apply` **不会**建它们——本 skill 没有 menu/addconditional 能力。"
                        "那几条要靠人去公众平台后台重挂，⛔ 别把 apply 完当成「全都恢复了」。")
    return buttons


def _是基线文件(路径) -> bool:
    """要 apply 的文件是不是基线本身。用 `samefile` 而非字符串比——软链/相对路径也认得出。"""
    p, b = Path(路径), baseline_path()
    if not (p.is_file() and b.is_file()):
        return False
    try:
        return p.samefile(b)
    except OSError:
        return False


def do_apply(args, api_base, key):
    buttons = load_menu_file(args.apply)
    warnings = validate(buttons)                       # 硬约束不过：一个请求都不发

    old, cond, note = _fetch_menu_tolerant(api_base, key, args.timeout)
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
        # 只读预检**不受**①②③管制，但把会撞到的闸门预告出来，免得补了 --confirm 再被拦
        for line in 闸门预告():
            wechat_api.warn(f"  {line}")
        return {"outcome": "failed",
                "error": "未带 --confirm：本次只算了 diff，**没有改线上菜单**"
                         "（这是安全闸门，不是故障）。",
                "diff": diff, "warnings": warnings, "baseline_note": note,
                "hint": "把上面的 diff 逐条念给运营，确认后加 `--confirm` "
                        "**和 `--approval <件号>-<选项键>`** 重跑同一条命令"
                        f"（🔴 装修菜单自 2026-09-02 起为坐标制，理由见下方 require_approval 处注释）。"
                        f"{CACHE_NOTE}"}, 1

    # ══ 写路径的前置闸门，顺序固定 ①基线存在 → ②基线已提交 → ③一致性 ══
    # ⚠️ 只读预检**不受**这三道管制（上面那条路已经 return 了），拦了会逼人为了
    #    「看一眼菜单现在长什么样」也去满足这些条件；但那条路会把它们**预告**出来。
    基线, 拒 = 写前闸门("装修菜单")                       # ① + ②
    if 拒:
        return 拒

    if args.restore:
        # ③ 跳过：**不一致正是要恢复的原因**，在这里拒等于在最需要它的时刻挡住唯一正确的操作。
        wechat_api.warn(f"🔴 本次是**恢复操作**：将把线上**默认菜单**覆盖为 "
                        f"`{Path(args.apply).name}` 的内容。")
        n = len(基线.get("conditionalmenu") or [])       # N 从基线数，⛔ 写死
        if n:
            wechat_api.warn(f"⚠ 其中 **{n} 条个性化菜单不会被重建**——本 skill 没有 "
                            "menu/addconditional 能力，那几条只能照着快照去公众平台后台**手工重挂**。"
                            "⛔ 别把这次 apply 当成「全都恢复了」。")
        if diff and diff["lines"]:
            wechat_api.warn("完整 diff（线上 → 将变成）：")
            for line in diff["lines"]:
                wechat_api.warn(f"  · {line}")
    else:
        # ③′ 基线文件直接 apply 而没说自己在恢复 ⇒ 拒。⛔ 不替他把意图猜成「恢复」。
        if _是基线文件(args.apply):
            raise OpFailed(
                f"这是**基线文件**（{baseline_path()}），而你没带 `--restore`。\n"
                "⇒ 要**恢复**（把线上覆盖回基线）请显式加 `--restore`；"
                "要**改菜单**请另存一份改过的文件再 apply。"
                "⛔ 本次一个写请求都没发出。")
        # ③ 一致性
        if old is None:
            raise OpFailed(
                "拿不到线上现状，**无法核对它与基线是否一致**，本次不执行。"
                "⛔ 「查不到」不等于「一致」——这道闸的失效方向不能是绿。"
                "⇒ 网络/服务恢复后重跑；确实要在核不了的情况下强行恢复，用 `--restore`。")
        差异 = baseline_drift({"button": old, "conditionalmenu": cond}, 基线)
        if 差异:
            wechat_api.warn("⚠ 线上菜单与基线快照**不一致**，本次不执行。差异逐条：")
            return 漂移拒绝(差异, "装修菜单"), 1

    if diff is not None and not diff["changed"]:
        wechat_api.warn("⚠ 这份文件与线上现状没有差异，仍会照常提交一次（menu/create 是整体覆盖，幂等）。")

    # 🔴 装修菜单升级为坐标制（2026-09-02 裁定）。理由是**原来的「不纳入」依赖一个空的前提**：
    # 当时判它「可逆」——菜单改错重新 apply 一份 menu.json 就行。实查那份基线文件
    # 当时在 `~/nbdpsy-content` 那个 workspace 下**不存在**，而仓内约定路径上躺着的是一份
    # **2026-08-04 的残缺快照**（只含默认菜单、无 conditionalmenu）——照它恢复只回来一半，
    # 比没有更糟；两者都不受版本控制、且全靠人记得先 `--get`，所谓可逆在现实中是空的。
    # （该残缺快照已于 2026-09-02 删除，基线改为受版本控制的 menu-baseline.json。）
    # ⚠️ 口径是**条件可逆**⛔不是不可逆：apply 覆盖掉的默认菜单，**只要事先存了基线**就建得回来
    #    （与 --delete 对个性化菜单的硬不可逆不是一回事）——但那个条件恰恰是当时没人满足的那个，
    #    所以按「条件成立才可逆」管，⛔ 不按「可逆」免管。
    # ⚠️ 触发点刻意放在 --confirm **之后**（与 article_ops.do_mass_send 逐字对齐）：
    #    不带 --confirm 那条路只算 diff、是只读预检，⛔ 不该被坐标拦住
    #    ——拦了会逼人为了「看一眼菜单现在长什么样」也去要批复，闸门强度与危害脱钩。
    # 🔑 守备范围与发布/群发同：坐标只是**原样记下**，脚本⛔ 不核实那个件真批没批。
    approval = wechat_api.require_approval(
        args.approval, "装修菜单（apply 整体覆盖默认菜单，条件可逆：仅当事先存了基线）")
    wechat_api.proxy_call(api_base, key, "/cgi-bin/menu/create", {"button": buttons},
                          args.timeout, irreversible=True)
    # 改成功 ⇒ 线上已经 ≠ 基线，基线当场陈旧 ⇒ 立刻刷新并催提交（⛔ 不替人 commit）
    刷新基线(api_base, key, args.timeout, 基线)
    return {"outcome": "done", "applied_top_level": [b.get("name") for b in buttons],
            "diff": diff, "warnings": warnings, "baseline_note": note,
            "approval": approval, "baseline_refreshed": str(baseline_path()),
            "hint": f"{CACHE_NOTE}🔴 基线已刷新但**尚未提交**——下一条写命令会因此被拦，"
                    f"现在就 `git add {baseline_path()} && git commit`。"}, 0


def do_delete(args, api_base, key):
    old, cond, note = _fetch_menu_tolerant(api_base, key, args.timeout)
    current = [b.get("name") for b in old] if old else []

    if not args.confirm:
        wechat_api.warn("⚠ 这次**没有删除任何东西**（缺 --confirm）。删除的代价：")
        wechat_api.warn(f"  · 粉丝**立刻**看不到底部入口（现有一级菜单："
                        f"{' | '.join(current) or '拉不到/无'}）。")
        wechat_api.warn("  · menu/delete 会把**默认菜单和全部个性化菜单**一起删掉（微信 API 语义如此）"
                        f"——本号现有 **{len(cond)} 条个性化菜单**会一起没。")
        wechat_api.warn("  · 🔴 **恢复得了的只有默认菜单那一半**：`--get` 存的基线虽然**存下了**"
                        "个性化菜单（conditionalmenu 字段），但 `--apply` **建不回它们**"
                        "（本 skill 没有 menu/addconditional 能力）——那份存档只够人照着"
                        "去公众平台后台**手工重挂**，⛔ 不是一条命令能还原的回滚。")
        if note:
            wechat_api.warn(f"  · {note}")
        # 只读预检**不受**①②③管制，但把会撞到的闸门预告出来
        for line in 闸门预告():
            wechat_api.warn(f"  {line}")
        return {"outcome": "failed",
                "error": "未带 --confirm：本次**没有删除**自定义菜单（这是安全闸门，不是故障）。",
                "current_top_level": current, "conditionalmenu_count": len(cond),
                "baseline_note": note,
                "hint": f"先 `--get > {baseline_path()}` 把现状存成回滚基线**并提交**"
                        "（⚠ 它**只兜得住默认菜单**：个性化菜单虽在文件里，却只能靠人去后台照着重挂），"
                        "把上面的代价讲给运营，确认后加 `--confirm` "
                        "**和 `--approval <件号>-<选项键>`** 重跑"
                        "（🔴 删除菜单自 2026-09-02 起为坐标制）。"}, 1

    # ══ 写路径的前置闸门：①基线存在 → ②基线已提交 → ③线上与基线一致 ══
    # 🔑 ③ 对 delete 的实际效果是「**没有当前基线就删不了**」——而 delete 恰恰最需要基线：
    #    删掉的个性化菜单只能照着快照去后台手工重挂，快照陈旧＝那部分永久回不来。
    基线, 拒 = 写前闸门("删除菜单")                        # ① + ②
    if 拒:
        return 拒
    if old is None:
        raise OpFailed(
            "拿不到线上现状，**无法核对它与基线是否一致**，本次不删。"
            "⛔ 「查不到」不等于「一致」——这道闸的失效方向不能是绿。")
    差异 = baseline_drift({"button": old, "conditionalmenu": cond}, 基线)      # ③
    if 差异:
        wechat_api.warn("⚠ 线上菜单与基线快照**不一致**，本次不删。差异逐条：")
        return 漂移拒绝(差异, "删除菜单"), 1

    wechat_api.warn("⚠ menu/delete 会把**默认菜单和全部个性化菜单**一起删掉（微信 API 语义如此）——本号挂着按标签定向的内部菜单（如老板的「今日日报」钮），删完要去后台/API 重挂。三思。")
    # 🔴 删除菜单升级为坐标制（2026-09-02 裁定），与群发同类：**对个性化菜单是硬不可逆**——
    # 微信语义是默认菜单与全部个性化菜单一起删，而本 skill 没有 menu/addconditional 能力，
    # 删掉的个性化菜单**没有任何一条命令能还原**（其中就有老板续通知窗口的入口）。
    # ⚠️ 与 --apply 的「条件可逆」分档：那边只要事先存了基线就建得回默认菜单；这边不行。
    # ⚠️ 触发点同样放在 --confirm **之后**：不带 --confirm 那条路只读现状打警示，⛔ 不该被坐标拦。
    # 🔑 守备范围与发布/群发同：坐标只是**原样记下**，脚本⛔ 不核实那个件真批没批。
    approval = wechat_api.require_approval(
        args.approval, "删除菜单（连带删除全部个性化菜单，对它们硬不可逆）")
    wechat_api.proxy_call(api_base, key, "/cgi-bin/menu/delete", {},
                          args.timeout, irreversible=True)
    return {"outcome": "done", "deleted_top_level": current,
            "deleted_conditionalmenu_count": len(cond), "approval": approval,
            "hint": f"自定义菜单已删除，粉丝端受 24 小时缓存影响可能还看得到残影。{CACHE_NOTE}"
                    "恢复：把之前 `--get` 存的基线重新 --apply，**只恢复得了默认菜单**；"
                    "个性化菜单即使存在那份文件里，本 skill 也没有重建能力，"
                    "只能照着存档去公众平台后台手工重挂（或另行调 `/cgi-bin/menu/addconditional`）。"}, 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="服务号自定义菜单：查 / 应用 / 删除")
    ap.add_argument("--get", action="store_true", help="拉线上菜单（stdout 即可直接编辑的 menu.json）")
    ap.add_argument("--apply", metavar="menu.json", help="把本地菜单 JSON 应用到线上（整体覆盖）")
    ap.add_argument("--delete", action="store_true", help="删除整个自定义菜单（粉丝立刻看不到入口）")
    ap.add_argument("--confirm", action="store_true",
                    help="真正执行 --apply / --delete；不带它只打 diff/警示，不碰线上")
    ap.add_argument("--restore", action="store_true",
                    help="声明本次 --apply 是**恢复**（把线上覆盖回基线）：跳过一致性检查"
                         "（不一致正是恢复的原因），坐标照常要。⛔ 恢复必须显式说出来，"
                         "脚本不靠「文件是不是基线」猜意图")
    ap.add_argument("--approval", metavar="件号-选项",
                    help="装修/删除菜单的批复坐标（老板台件号 + option_key，如 <件号>-A）。"
                         "--delete 对个性化菜单硬不可逆、--apply 仅在事先存了基线时可逆，"
                         "缺此参数一律 failed exit 1 且一个写请求都不发")
    ap.add_argument("--api-base", dest="api_base", help="覆盖服务基址（默认走凭据/内置默认）")
    ap.add_argument("--timeout", type=float, default=wechat_api.DEFAULT_TIMEOUT, help="单次请求超时秒数")
    args = ap.parse_args(argv)

    # `actions` 分发表：与 article_ops / schedule_ops 逐字同形。
    # 🔑 换成这个写法**不是为了迁就判据**，而是本仓「命令 → 处理函数」的既有唯一映射形状：
    #    `tests/test_guide_approval_sync.py` 靠它把带坐标闸门的处理函数翻回运营敲的命令。
    #    原先这里是 if/return 链，判据看不见 ⇒ menu_ops 只能挂在豁免名单里；
    #    现在它有闸门了，必须能被判据看见（行为与原来的三选一完全一致）。
    actions = [
        (args.get, do_get), (args.apply, do_apply), (args.delete, do_delete),
    ]
    chosen = [fn for flag, fn in actions if flag]
    if len(chosen) != 1:
        ap.error("三选一：--get / --apply <menu.json> / --delete")
    if args.restore and not args.apply:
        ap.error("--restore 只跟 --apply 一起用（它声明的是「这次 apply 是恢复」）")

    def action():
        api_base, key = wechat_api.credentials(args.api_base)
        return chosen[0](args, api_base, key)

    return wechat_api.run(action)


if __name__ == "__main__":
    sys.exit(main())

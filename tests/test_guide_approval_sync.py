"""guide 的「受管制命令清单」必须与代码里 `require_approval` 的实际调用点对得上。

2026-09-02 立。本仓 CHANGELOG 顶部铁律③ 写着「新红线要同步 `nbdpsy-guide`」——靠人记，
**已经漏了三次**。第三次就是 `1998975`：群发/删除升级成坐标制，guide 一个字没改，
运营照着向导读会以为「坐标是发布那边的事」，到群发时才被闸门拦一次才知道。
这里把那条铁律从「记得做」变成机器判据。

🔑 **方向：代码是真源，guide 是被校验的那一侧。** 代码侧⛔ 不靠 `do_<dest>` 命名约定猜，
   而是读 `main()` 里那张 `actions = [(args.<dest>, do_<x>), ...]` 分发表——它本来就是
   「命令 → 处理函数」的唯一映射，直接用它就不必再写第二份清单
   （**第二份正确的实现比错的更难发现**：两份都对的时候没人会去比，其中一份先烂掉）。

⛔ **本判据不管「哪些动作*应该*被管制」**——那是服务号线与老板台的裁定，机器判不了。
   它只管一件事：**代码管了什么，guide 有没有照实写。**

✅ **上面那条已知不对称已裁定并补齐（2026-09-02，v2.43.2）**：`schedule_ops.py --submit-mass`
   （定时群发）与即时群发危害相同（不可逆 + 占当月配额 + 直达全体粉丝），且到点自动执行、
   人还不在场，此前**却没有坐标闸门**。裁定口径是**已裁类别的漏网补齐**，⛔ 不是新管制类别
   ——2026-08-31「群发是受管制动作」那条当时只改了 `article_ops.py`。本判据当场如期变红并
   点名了它，加进 guide 清单块后转绿：**这就是它该有的样子**，⛔ 不要为了让测试变绿而把闸门去掉。
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "nbdpsy-guide" / "SKILL.md"
SCRIPT_DIR = ROOT / "nbdpsy-fuwuhao-operator" / "scripts"

# 🔴 **扫描范围是发现式的，⛔ 不是硬编码的文件名单**（2026-09-02 改）。
# 原先这里写死 `("article_ops.py", "schedule_ops.py")`，那是个**结构性盲区**：
# 将来任何新脚本都自动免检，而且**失效方向是绿**——新脚本里加了坐标闸，本判据看不见，
# 于是 guide 不写也不会红。改成扫 `*_ops.py`，「哪些脚本在范围内」由目录说了算。
#
# 🔑 豁免必须**显式写下来 + 一行理由**，⛔ 不靠「名单里没有」默默略过：
# 「新脚本没进名单」现在会红（见 `test_扫描范围是发现式的`），⛔ 不是静默绿。
# 🔴 `menu_ops.py` 已于 2026-09-02 **退出豁免**：裁定推翻了原先的「不纳入」，
# 理由是它依赖的「可逆」在现实中为空——`--delete` 连带删除全部个性化菜单，本 skill
# 没有 menu/addconditional 能力，那部分**没有任何一条命令能还原**；而当时用来论证可逆的
# 那份基线文件，在 `~/nbdpsy-content` 下不存在、在仓内约定路径上则是一份 2026-08-04 的
# **残缺快照**（只含默认菜单，照它恢复只回来一半），两者都不受版本控制。
# ⇒ `--apply` / `--delete` 均已加坐标闸门。
# ⚠️ 它原先的豁免理由是**机械的**（没有 `actions` 分发表 ⇒ 本判据的映射看不见它）。
#    退出豁免时是**给它补了一张与 article_ops / schedule_ops 同形的 `actions` 表**，
#    ⛔ 不是放宽本判据来迁就它——判据一个字没动。
EXEMPT_SCRIPTS: dict[str, str] = {}

MARK_START = "受管制命令清单:start"
MARK_END = "受管制命令清单:end"


def _all_scripts() -> dict[str, Path]:
    """目录里所有 `*_ops.py`（含豁免的）。豁免名单失效也在这里报。"""
    found = {p.name: p for p in sorted(SCRIPT_DIR.glob("*_ops.py"))}
    assert found, (
        f"`{SCRIPT_DIR}` 下一个 `*_ops.py` 都没扫到 —— 判据失去代码侧真源，"
        "⛔ 别把「扫不到」当成「没有受管制命令」（那是恒绿）。目录搬家了就改 `SCRIPT_DIR`。")
    过期 = sorted(set(EXEMPT_SCRIPTS) - set(found))
    assert not 过期, (
        f"豁免名单里这些脚本已经不存在了：{过期}。"
        "⛔ 别留着——过期的豁免会在同名文件将来出现时**静默生效**。")
    return found


def _scanned_scripts() -> dict[str, Path]:
    """真正参与校验的脚本 = 发现到的 - 显式豁免的。"""
    return {n: p for n, p in _all_scripts().items() if n not in EXEMPT_SCRIPTS}


# guide 清单块里的命令写法：`article_ops.py --publish`（脚本名 + 空格 + 长选项，整体一个反引号块）。
# 🔑 脚本名也是发现式的（**含豁免脚本**）：guide 若给一个豁免脚本列了命令，
#    代码侧没有对应闸门 ⇒ 报「guide 写了、代码没管制」而红 —— 那正是「承诺一道不存在的闸门」。
def _cmd_re() -> re.Pattern:
    名 = "|".join(re.escape(n) for n in sorted(_all_scripts()))
    return re.compile(rf"`({名}) (--[a-z][a-z0-9-]*)`")

FIX_HINT = ("两侧都要动：代码侧是 `require_approval` 的调用点，guide 侧是 "
            f"`nbdpsy-guide/SKILL.md` 里 `{MARK_START}` / `{MARK_END}` 之间那个块。"
            "⛔ 不要只改一边——这条判据存在的理由就是那两边曾经各说各的。")


def _is_require_approval(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return ((isinstance(f, ast.Attribute) and f.attr == "require_approval")
            or (isinstance(f, ast.Name) and f.id == "require_approval"))


def _count_calls(node) -> int:
    return sum(1 for n in ast.walk(node) if _is_require_approval(n))


def _dispatch_table(tree) -> dict[str, str]:
    """`main()` 里的 `actions` 表 → {处理函数名: --flag}。

    表里的条件项不都是裸 `args.x`（还有 `args.status is not None and not args.ledger`
    这种），所以取的是条件表达式里**第一个** `args.<dest>` 属性访问。
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "actions" for t in node.targets)
                and isinstance(node.value, (ast.List, ast.Tuple))):
            continue
        for item in node.value.elts:
            if not (isinstance(item, ast.Tuple) and len(item.elts) == 2):
                continue
            cond, handler = item.elts
            if not isinstance(handler, ast.Name):
                continue
            dest = next((a.attr for a in ast.walk(cond)
                         if isinstance(a, ast.Attribute)
                         and isinstance(a.value, ast.Name) and a.value.id == "args"), None)
            if dest:
                out[handler.id] = "--" + dest.replace("_", "-")
    return out


def gated_commands() -> set[str]:
    """代码侧真源：调用了 `require_approval` 的处理函数，翻回运营敲的命令。"""
    found: set[str] = set()
    for name, path in _scanned_scripts().items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        top_funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]

        # 🔴 防「判据看不见」：模块级或嵌套在别处的调用点会被下面的映射整个漏掉，
        # 而漏掉的表现是**变绿**（少一条就少比一条）。所以先对数，对不上直接红。
        raw, covered = _count_calls(tree), sum(_count_calls(fn) for fn in top_funcs)
        assert raw == covered, (
            f"{name}：{raw} 处 `require_approval` 调用里有 {raw - covered} 处不在顶层函数中"
            "（模块级或嵌套定义），本判据的映射看不见它们 ⇒ **先改判据，⛔ 别改 guide**。")

        table = _dispatch_table(tree)
        assert table, (
            f"{name} 里没找到 `main()` 的 `actions` 分发表——判据失去代码侧真源。"
            "分发表若改了写法，要同步改本文件的 `_dispatch_table`，"
            "⛔ 别把「扫不到」当成「没有受管制命令」。")

        gated = {fn.name for fn in top_funcs if _count_calls(fn)}
        unmapped = gated - table.keys()
        assert not unmapped, (
            f"{name}：这些函数带坐标闸门却不在 `actions` 分发表里 —— {sorted(unmapped)}。"
            "判据只能校验分发表覆盖到的命令，出现这种情况说明它已经看不全，先改判据。")

        found |= {f"{name} {table[fn]}" for fn in gated}
    return found


def guide_commands() -> set[str]:
    """guide 侧：清单块里列出的命令。"""
    text = GUIDE.read_text(encoding="utf-8")
    for mark in (MARK_START, MARK_END):
        assert text.count(mark) == 1, (
            f"`{GUIDE.name}` 里的标记 `{mark}` 出现了 {text.count(mark)} 次，应为 1。"
            "清单块被删掉或被复制了 ⇒ 判据失去 guide 侧锚点，"
            "⛔ 这不是可以放过去的绿。" + FIX_HINT)
    block = text[text.index(MARK_START):text.index(MARK_END)]
    return {f"{script} {flag}" for script, flag in _cmd_re().findall(block)}


def test_guide受管制命令清单与代码的坐标闸门一致():
    code, guide = gated_commands(), guide_commands()

    # 两侧都不许为空：空集合彼此相等，那是**恒绿**不是通过。
    assert code, "代码侧一条带坐标闸门的命令都没扫到 —— 判据恒绿，先修判据。"
    assert guide, "guide 清单块里一条命令都没列 —— 判据恒绿，先修 guide 或判据。"

    missing = sorted(code - guide)
    extra = sorted(guide - code)
    detail = []
    if missing:
        detail.append(f"**代码已管制、guide 没写**：{missing}"
                      "（运营照 guide 做会在真跑那一刻才被拦）")
    if extra:
        detail.append(f"**guide 写了、代码没管制**：{extra}"
                      "（guide 在承诺一道并不存在的闸门——比没写更糟）")
    assert not detail, "；".join(detail) + "。" + FIX_HINT


def test_扫描范围是发现式的且豁免必须仍然成立():
    """🔴 守的是**扫描范围本身**，⛔ 不是范围内的内容。

    原先 `SCRIPTS` 硬编码两个文件名 ⇒ 新脚本自动免检，**且失效方向是绿**
    （新脚本里加了坐标闸，判据看不见，guide 不写也不会红）。改成发现式之后，
    这条判据补上另一半：**豁免不许烂在那里**。

    两个失效方向都要红：
    ① 豁免的脚本**长出了坐标闸** ⇒ 它已经进入管制范围，豁免过期，必须退出豁免并写进 guide；
    ② 豁免**没写理由** ⇒ 名单会退化成「随手加一行就免检」。
    """
    全部 = _all_scripts()
    assert set(_scanned_scripts()) , "全部脚本都被豁免了 —— 判据恒绿，先看豁免名单是不是加过头了。"

    for name, reason in EXEMPT_SCRIPTS.items():
        assert reason and reason.strip(), (
            f"豁免 `{name}` 没写理由。⛔ 不写理由的豁免等于「随手加一行就免检」，"
            "下一个人无从判断它还成不成立。")
        n = _count_calls(ast.parse(全部[name].read_text(encoding="utf-8")))
        assert n == 0, (
            f"`{name}` 在豁免名单里，却有 {n} 处 `require_approval` 调用 ⇒ **豁免已经过期**。"
            "它已经进入坐标制范围，必须：① 从 `EXEMPT_SCRIPTS` 移除；"
            "② 确认它的 `main()` 有 `actions` 分发表（本判据靠它把处理函数翻回命令）；"
            "③ 把它的受管制命令写进 guide 清单块。"
            "⛔ 别反过来把闸门去掉来让这条变绿。")


def test_guide写明坐标不核实那个件真批没批():
    """守的是那句限定语还在不在，⛔ 不守它写得对不对（后者机器判不了）。

    这句是本闸门唯一的守备范围声明：脚本只查坐标**成不成形**，⛔ 不联网核实那个件。
    有人重写第 4 条时最容易把它当废话删掉，而删掉之后 guide 就在暗示「命令跑通＝已获批准」。
    """
    text = GUIDE.read_text(encoding="utf-8")
    for phrase in ("命令跑通", "已获批准"):
        assert phrase in text, (
            f"`{GUIDE.name}` 里找不到「{phrase}」——坐标闸门的守备范围声明"
            "（**命令跑通 ⛔ 不等于已获批准**，真伪要人对台账）被删了。"
            "闸门只保证「有人留了一笔账」，不写清这点，绿会被读成「批过了」。")

#!/usr/bin/env python3
"""合规判据唯一真源：绝对化词（fatal）／医疗口径词（warning）／危机声明与停用热线（R8）。

## 判据句

**判断扫描面够不够，问的是「读者能看到哪些字」，不是「我手上有哪些文件」。**

## 为什么存在（2026-08-17 服务号线实查出的缺口）

公众号摘要 `digest` 从来没进过任何合规扫描，而且按老架构永远不会进——所有扫描器都读
**文件**，而摘要不在文件里（建草稿时单独传的参数，只活在 batch.json 和命令行里）。
摘要是读者在信息流里第一眼看到的那行字，**比正文更早被看到**。同族的还有 title、
author、content_source_url。

根因不是「合规检查没抽出来」，是**扫描域被工具的输入形态决定，而不是被『什么东西会上线』
决定**——没有人做过「摘要不用扫」这个决定，它是工具形态的副产品。而最阴的一点：md 扫干净
了，所有人都会以为扫完了，**缺口被一份真实的绿色报告盖住**。

## 因此：本模块只收文本单元，⛔ 永远不收文件路径

`check()` 的入参是 `[(定位标签, 文本), ...]`。**只要它收文件路径，扫描域就被文件边界
锁死了**——这是本模块存在的全部意义。⛔ 不提供「顺便也能收路径」的重载把这个约束又打开。
调用方要扫文件，自己读成文本再喂；要扫 API 参数，就把参数喂进来。

## 装什么、不装什么

只装**三类合规判据**：R7-abs 绝对化词、R7-med 医疗口径词、R8 危机声明与热线红线。
⛔ 不装 pillar 长文口径（字数区间／参考文献条数／统计块／FAQ 数组）——那些是官网长文的
质量规格不是合规，混进来会让别的调用方一挂就整篇红，红的大部分与合规无关，淹掉真正该看的。
⛔ 也不装小红书平台特有词表（站外导流／硬广特征／极限词正则）——那些只有一个调用方，
留在 check_compliance.py 本地。

## 词表唯一真源

本文件是 R7-abs / R7-med 词表与停用热线三正则的**唯一真源**。词表复制出去就会漂——
今天一致，下次改了对面不知道。`tests/test_compliance_core.py::test_no_wordlist_copies_outside_core`
钉死这条：全仓（除本文件与其 vendored 副本外）不得再出现这些字面量；副本与真源的逐字节
一致由 `tests/test_shared_sync.py` 保证——两条测试联防，副本允许存在但不许漂。
"""
import re

# ── R7-abs 绝对化/夸大词（fatal，调用方应拒绝提交）────────────────────────
# 广告法禁绝对化承诺 + 非医疗机构禁夸大疗效。子串命中即算，不做词形变化。
ABSOLUTE_WORDS = ["根治", "治愈率", "100%", "彻底摆脱", "保证有效", "最有效", "药到病除"]

# ── R7-med 医疗口径词（warning，放行）────────────────────────────────────
# 心理咨询机构非医疗机构，自我描述不得用医疗动词；但学术转述（PTSD 的治疗研究、
# DSM 诊断标准）是正当用法，故只 warn 交人工裁决，⛔ 不 fail。
MEDICAL_WORDS = ["治疗", "治愈", "诊断", "医生", "医院"]

# 文献转述豁免：同一文本单元内含 [[n]](url) 标注时，这些词视为引述而非自我承诺。
# 只给「最有效」——「一项综述称这是最有效的干预之一 [[1]](https://…)」是转述事实，
# 不是承诺；「根治」「保证有效」这类无论谁说都不能出现在自家文案里，⛔ 不给豁免。
CITE_EXEMPT_WORDS = ("最有效",)
# 与 preflight.RE_CITE 形态相同但用途不同：那条用于校验引用编号/URL 一致性，
# 这条只回答「这行是不是文献转述」。⛔ 别合并——判据变了会互相牵连。
_RE_CITE_MARKER = re.compile(r"\[\[\d+\]\]\(https?://[^)]+\)")

# ── R8 危机声明三要素 ────────────────────────────────────────────────────
CRISIS_HOTLINE = "12356"            # 全国统一心理援助热线（fatal 要素）
CRISIS_DISCLAIMER = "不构成医疗建议"  # 免责句（fatal 要素）
CRISIS_BJ_HOTLINE = "010-82951332"  # 北京心理危机研究与干预中心（缺失只 warning）

# ── 停用热线红线（2026-08-14 定案）────────────────────────────────────────
# 希望24（4001619995）已证据停用：官网信息冻结于 2021、2023 年自述近半来电无法接通。
# 容错到带空格的「希望 24」与带连字符的号码——排版换行最容易把机构名拆开。
#
# 🔴 变体清单的对侧真源 = 审稿判据库 `docs/secretary/审稿判据-v1.md` 判据 1.1（NBDpsy 仓）。
#    两份清单必须逐项对齐；任一侧新增变体，**必须同步另一侧**。⛔ 不许只改一边。
# 🩸 2026-08-29 补「希望热线」的由来：判据 1.1 列了它、本正则没有，**两边各缺一项且都是绿的**
#    （1.1 那侧缺的是带空格的「希望 24」，本正则早有）。审稿抽验时才撞出来。
#    ⇒ 这类「第二份正确的实现」比写错更难发现——错的会有人报，不一致的两边各自都跑得通。
# 🔑 **两侧缺项的危害不对称，补的时候朝哪边偏要想清楚**：
#      · **本正则缺一项 = 漏放行**（真写了那个变体会**静默过闸**）—— 有洞，机器不会说话
#      · **判据 1.1 缺一项 = 人工审稿不认为它是变体** —— 人漏看，但机器还拦得住
#    ⇒ 拿不准某个写法算不算变体时，**先加进本正则**（宁可多拦一次，误拦会有人来吵；
#      漏放行没有任何人会发现）。
DEAD_HOTLINE = re.compile(r"4001619995|400-?161-?9995|希望\s*24|希望\s*热线")
# ⚠️ 更正稿豁免（2026-08-17）：老板批 S1 时定的是「已发布的不删不重发，在下一条推送里
# 更正」，而更正段**必须写出那个号码**——不写读者不知道更正的是哪条热线，更正就等于没更正。
# 原判据只认字符串、不认这个字符串在句子里是什么角色，会把更正稿一起拦掉。
# 真正的危险不是被拦，是**接下来那一步**：有人照着闸门去「修」，会把更正段里的号码删掉，
# 于是更正废了、闸门反而变绿——闸门亲手制造了它本该防的那个后果。
DEAD_HOTLINE_RETIRED_DECL = re.compile(
    r"已(?:停止服务|停用|停运|下线|不再服务)|停止服务|此前(?:写过|提到|使用)|更正|勘误|不再(?:可用|使用|提供)")
DEAD_HOTLINE_RECOMMEND = re.compile(r"请?(?:拨打|拨号|致电|打)|联系|求助(?:热线)?(?:：|:)")

DEAD_HOTLINE_DETAIL = (
    "停用热线回流：希望24已于2026-08-14证据停用，用 010-82951332 替换。"
    "⚠️ 若本行是**更正声明**（告诉读者这条热线已停），两个条件都要满足才放行："
    "① 同一行写上「已停止服务／此前写过／更正」这类声明词；"
    "② **替代号码写在「请拨打」之后，且那之后不再出现死号**"
    "（可写「希望热线 4001619995 已停止服务，请拨打 12356」；"
    "⛔ 不能写「请拨打 12356 或 4001619995」——那是真的还在推荐它）。"
    "⛔ 别为了过闸门把号码删掉，那样读者就不知道更正的是哪条热线，更正等于没做")

_CRISIS_SCOPES = ("joined", "skip")

# 空串子串命中恒 True（`"" in "任意字符串"`），会把每个单元都判成违规、或反过来被
# 当成噪声整条规则关掉——两种都是静默的假结论。加载即断言，⛔ 别让空项混进词表。
assert all(ABSOLUTE_WORDS) and all(MEDICAL_WORDS), "词表不得含空串"


def is_retirement_citation(line: str) -> bool:
    """这一行提到停用号码，是**引用以更正**还是**推荐给读者拨**？

    放行给两侧都成立的：有停用声明词 **且推荐动词之后不再出现任何死号变体**。
    「这条热线已停止服务，请拨打 4001619995」这种自相矛盾的写法**不放行**——
    它有声明词，但它仍然在叫人去拨那个号。

    ⛔ 声明词必须与号码**同行**，不能是全文任意位置——否则文末一句「已停用」会把
    全篇的号码都豁免掉。故调用方必须逐行喂，不能整篇喂。

    ## 🩸 2026-08-29 订正：旧判据「同一行**无**推荐动词」是个会伤人的粗糙近似

    旧写法默认「推荐动词一定指向死号」。但**更正段里它指向的恰恰是替代号码**：
        「希望热线 4001619995 已停止服务，请**拨打** 12356」
    ——最自然的更正写法，旧逻辑**一律拦掉**；而写成「请**改拨** 12356」却放行，
    只因「改拨」不在动词表里。**同一件事因措辞不同结果相反，且被拦的是最自然的那个。**

    🔴 这正是本文件 `DEAD_HOTLINE_DETAIL` 注释预言的后果：写稿人照着闸门去「修」，
    会把更正段里的号码删掉 ⇒ **更正废了、闸门反而变绿**。判「**红了之后人该做的事，
    是不是一件真的该做的事**」＝否 ⇒ 那道闸红得不对，**改闸⛔不改稿**。
    （判据侧同步订正：审稿判据库 1.5，NBDpsy 仓。）

    ## 实现取舍：用**第一个**推荐动词，⛔ 不用最后一个

    两种都有反例，选了偏向「拦」的那个：
      · 用第一个 → 「联系我们，希望热线已停用，请拨打 12356」**假红**（"联系"之后有机构名）
      · 用最后一个 → 「请拨打 4001619995，另外可以联系我们」**假放行**——真的在推荐死号
    **假红有人来吵，假放行没有任何人会发现** ⇒ 取第一个。

    ## ⚠️ 明确不守（审稿 1.5 写明，⛔ 别顺手"修好"）

    **劝阻式写法**「⛔ 不要再拨 4001619995」会**假红**（"拨"在动词表、其后有死号）。
    ⛔ **不为它加否定前缀识别**——更正段场景稀少，穷举写法只会让规则越来越脆。
    遇到即按假红**回审稿线复判**，⛔ 实施方不自行绕过。
    """
    if not DEAD_HOTLINE_RETIRED_DECL.search(line):
        return False
    rec = DEAD_HOTLINE_RECOMMEND.search(line)
    if rec is None:
        return True                                       # 纯声明、没叫人拨任何号
    return DEAD_HOTLINE.search(line, rec.end()) is None   # 推荐动词之后不得再出现死号


def has_dead_hotline(line: str) -> bool:
    """这一行是否构成停用热线回流（命中停用号码/机构名，且不是更正引用）。

    ⚠️ 逐行判据——调用方传整篇会让「同行」语义失效（见 is_retirement_citation）。
    """
    return bool(DEAD_HOTLINE.search(line)) and not is_retirement_citation(line)


HOTLINE_24H = re.compile(
    r"12356(?:(?!010-?82951332)[^。！？\n]){0,20}24\s*小时"
    r"|24\s*小时(?:(?!010-?82951332)[^。！？\n]){0,20}12356")
"""**12356 标「24 小时」** —— 官方口径是每日 ≥18 小时。
⚠️ 危害不是"数字不准"：**深夜照着打不通，而读者手里又没有备选号码**。
全仓**唯一可标 24 小时**的是 `010-82951332`。

🩸 **首版是恒红闸门**：标准危机声明块写的是
「心理援助热线 **12356**，北京心理危机研究与干预中心 **010-82951332（24小时）**」——
两个号码同一行，而那个「24小时」修饰的是**北京号**。首版正则一跨就中
⇒ **每一条合规的稿子都会被拦**。⇒ 加 `(?!010-?82951332)`。
⚠️ **写完判据必须拿一条"本来就该放行的"去试** —— 只测反例测不出恒红。"""


def gate_hotlines(text: str) -> list[str]:
    """**发布入口的停用热线硬闸**：返回拒发理由列表（空 ＝ 放行）。

    🔴 **放在发布路径最前面，⛔ 不能只放稿件闸门**——2026-08-20 全仓扫出
    **42 个在途稿件**仍带停用热线，而它们是从**排期稿**里抓到的：
    **在途稿可以绕过稿件闸门直接发。**

    🩸 **前车之鉴**：稿件机检**本来就有这道闸**，B2r 还是漏了——`check()` 第一步
    找不到「## 口播全文」段就 `return`，**图文稿在此直接退出，热线检查一次都没跑到**。
    ⚠️ 而它**报了红**（"找不到口播全文段"）⇒ **照那个红去查的人会去补口播段，
    不会发现那个空号**。
    > **闸门失效：不响、恒响、响错理由。第三种最贵——因为它看起来在工作。**
    ⇒ 本函数**不做任何前置解析**：拿到什么文本就扫什么，⛔ 没有"找不到 X 就 return"的分支。

    ⚠️ **更正稿豁免**沿用 `is_retirement_citation`（同行有停用声明词且无推荐动词 ⇒ 放行）
    ——⛔ 别另写一份：更正段**必须写出那个号码**，拦掉它等于让更正废掉。

    ⚠️ **本文件是 `shared/` 真源**：改完要跑 `tools/sync_shared.py` 同步到各 skill。
    🩸 我 2026-08-20 改了 skill 下的**副本**，sync 一跑就被覆盖、改动全丢。
    """
    reasons = []
    for i, line in enumerate(text.splitlines(), 1):
        if has_dead_hotline(line) and not is_retirement_citation(line):
            reasons.append(f"第 {i} 行出现**已停用的希望24热线**（4001619995）：{line.strip()[:40]}\n"
                           f"    ⇒ 用 010-82951332 替换。"
                           f"⚠️ 若这行是**更正声明**（告诉读者它已停），"
                           f"把「已停止服务／此前写过／更正」写进同一行即可放行")
        if HOTLINE_24H.search(line):
            reasons.append(f"第 {i} 行把 **12356 标成了「24 小时」**：{line.strip()[:40]}\n"
                           f"    ⇒ 12356 官方口径是每日 ≥18 小时；"
                           f"**唯一可标 24 小时的是 010-82951332**。"
                           f"⚠️ 危害不是数字不准，是**深夜照着打不通、手里又没有备选号码**")
    return reasons


def check(units, *, crisis_scope="joined"):
    """扫一组文本单元，返回三类合规判据的结论。

    参数
    ----
    units : 可迭代的 (定位标签, 文本) 二元组
        定位标签是给人看的坐标，随调用方场景取名——公众号线用字段名
        （"title"/"digest"/"body"/"author"），长文线用行号（"行12"）或
        frontmatter 路径（"faq[0].a"）。⛔ 不收文件路径，见模块 docstring。
        文本可以是一行也可以是整段：R7 两类按**单元**判（子串命中即算），
        R8 停用热线按单元内的**行**判（「同行」语义所必需）。
    crisis_scope : "joined" | "skip"
        "joined"：把所有单元拼起来做**文档级**三要素在位判定（整篇场景）。
        "skip"：跳过三要素在位判定（调用方场景不需要，如只扫标题+摘要）。
        ⛔ 没有「对每个单元各判一次」这个取值——标题里当然没有危机声明，那会恒红。
        ⚠️ **"skip" 只豁免「声明在位」，绝不豁免停用热线**：可以不带危机声明，
        不能带错的号码（照着拨打不通的号码，伤害与场景无关）。
        ⛔ 非法取值抛 ValueError 而非静默回落——静默回落会让调用方以为关掉了检查
        其实没关（或反之），是最难发现的一类假绿。

    返回
    ----
    dict:
      ok       : bool，无 fatal 即 True
      fatal    : [{rule, loc, word, text, detail}]，调用方应拒绝提交
                 rule ∈ "R7-abs" | "R8-dead-hotline" | "R8-crisis-missing"
      warnings : 同构，放行但提示人工裁决
                 rule ∈ "R7-med" | "R8-crisis-partial"
      crisis   : crisis_scope="skip" 时为 None；否则
                 {has_12356, has_disclaimer, has_bj_hotline, missing:[要素名]}
    """
    if crisis_scope not in _CRISIS_SCOPES:
        raise ValueError(
            f"crisis_scope 非法：{crisis_scope!r}，只接受 {_CRISIS_SCOPES}"
            "（⛔ 不静默回落——回落会让调用方以为检查已关闭/已开启，其实相反）")

    pairs = [(loc, text if isinstance(text, str) else "") for loc, text in units]
    fatal, warnings = [], []

    for loc, text in pairs:
        for w in ABSOLUTE_WORDS:
            if w in text:
                if w in CITE_EXEMPT_WORDS and _RE_CITE_MARKER.search(text):
                    continue
                fatal.append({
                    "rule": "R7-abs", "loc": loc, "word": w, "text": text,
                    "detail": f"绝对化/夸大红线词「{w}」",
                })
        for w in MEDICAL_WORDS:
            if w in text:
                warnings.append({
                    "rule": "R7-med", "loc": loc, "word": w, "text": text,
                    "detail": f"医疗口径词「{w}」（学术转述可人工豁免）",
                })
        # 停用热线逐行判：声明词必须与号码同行，整段判会让文末一句「已停用」豁免全篇。
        for line in text.split("\n"):
            if has_dead_hotline(line):
                fatal.append({
                    "rule": "R8-dead-hotline", "loc": loc, "word": None,
                    "text": line.strip(), "detail": DEAD_HOTLINE_DETAIL,
                })

    crisis = None
    if crisis_scope == "joined":
        joined = "\n".join(t for _, t in pairs)
        crisis = {
            "has_12356": CRISIS_HOTLINE in joined,
            "has_disclaimer": CRISIS_DISCLAIMER in joined,
            "has_bj_hotline": CRISIS_BJ_HOTLINE in joined,
            "missing": [],
        }
        if not crisis["has_disclaimer"]:
            crisis["missing"].append("『不构成医疗建议』免责句")
        if not crisis["has_12356"]:
            crisis["missing"].append("全国统一心理援助热线 12356")
        if crisis["missing"]:
            fatal.append({
                "rule": "R8-crisis-missing", "loc": "文档", "word": None, "text": "",
                "detail": "危机声明缺要素：" + "、".join(crisis["missing"]),
            })
        elif not crisis["has_bj_hotline"]:
            warnings.append({
                "rule": "R8-crisis-partial", "loc": "文档", "word": None, "text": "",
                "detail": "危机声明缺北京心理危机研究与干预中心热线 010-82951332（24小时）"
                          "——12356 官方口径为每日≥18小时，不可标注 24 小时",
            })

    return {"ok": not fatal, "fatal": fatal, "warnings": warnings, "crisis": crisis}


def receipt_actor() -> str:
    """凭证里的 `actor`：**谁出的这张图**。

    🔴 **机器档也要署名**（2026-08-21 捞法演练）：`manual_confirmed` 人工档有
    `confirmed_by`+`confirmed_at`，而机器档因为"是工具出的"就不记
    ⇒ 今天 13 份「图文 v3」错标追责任线时，**靠的是当事人自己承认，⛔ 不是凭证追出来的**。
    **机器出的一样会错，一样需要署名。**

    ⚠️ 解析顺序：`NBDPSY_ACTOR` 环境变量（调用方/会话标识，最准）→ 退回**脚本名**。
    ⛔ 退回值不假装是会话名：脚本名答的是"哪个工具"，答不了"哪个会话"——
    **答得少但答得真，比编一个像样的值强**。
    """
    import os, sys
    a = os.environ.get("NBDPSY_ACTOR", "").strip()
    if a:
        return a
    return f"script:{os.path.basename(sys.argv[0]) or 'unknown'}"


def receipt_stamp() -> dict:
    """凭证的通用署名段：`created_at` + `actor`。⛔ 三个写入点共用这一份，别各写各的。"""
    import datetime
    return {"created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "actor": receipt_actor()}

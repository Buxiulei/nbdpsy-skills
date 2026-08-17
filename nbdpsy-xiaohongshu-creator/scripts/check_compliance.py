#!/usr/bin/env python3
"""小红书短文合规扫描：高置信违禁词 + 危机声明在位检查。"""

import json
import re
import sys
from pathlib import Path

# 同目录 vendored 依赖（shared/ 是真源，tools/sync_shared.py 同步）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import compliance_core  # noqa: E402  停用热线判据 + 危机声明要素的唯一真源

# 词表（移植自 check_compliance.sh）
# 极限词（广告法 §9）＝ **compliance_core 的核心词 + 小红书平台专属扩充**。
# 🔴 核心那几个从 compliance_core 现取，⛔ 别在这里再抄一遍——抄了就会漂：
# 今天两边一致，下次谁往 core 加一个词，小红书这条链上就静默漏掉它。
# 平台扩充部分（全网第一/国家级/包治…）是小红书语境独有的硬广特征，留在本地是对的。
_JIXIAN_XHS_EXTRA = (r"最好的方法|最强|全网第一|第一品牌|唯一一家|独家秘[籍方]|国家级|世界级|"
                     r"顶[级尖]|永久根除|百分之百|彻底治愈|彻底解决|绝对有效|包治|包好")
JIXIAN = "|".join([re.escape(w) for w in compliance_core.ABSOLUTE_WORDS] + [_JIXIAN_XHS_EXTRA])

# 医疗违禁（非医疗机构禁涉）— 逐字移植自 check_compliance.sh
# 注：治愈 仅当紧跟 [了焦抑情你] 时才判违规（如"治愈了创伤/治愈你的焦虑"），
#     避免误伤"治愈系插画风格"之类的正常修饰用法；其余为高风险短语，无需窄化。
YILIAO = r"治愈[了焦抑情你]|药到病除|特效药?|疗效显著|抗抑郁药|根治焦虑|根治抑郁"

# 站外导流（小红书限流封号红线）
# 注：末尾 "|微信" 裸词是对原 .sh 词表的有意扩充——对抗自检发现"加我的微信好友"
#     "我的微信是："等变体不含"加微信"/"微信号"等固定搭配、原词表零命中。控制器裁决：
#     小红书语境下正文提及"微信"本身即高危导流信号，宁可误报也不可漏报，故加裸词兜底。
DAOLIU = r"加微信|微信号|微信:|加我[vV][xX]|加[vV][xX]|扫码|二维码|加群|进群|私聊加|留[个下]?联系方式|留电话|手机号|网盘|公众号搜|微信"

# 硬广特征（投流拒审 + 自然流限流的高频触发词）
# 依据：正文三段式「结尾轻引导 = 陈述事实、给出选项，不催不促不承诺」
#      （references/xiaohongshu-spec.md §1）。促销/催促/诱导三类词一旦出现，
#      笔记从"科普"滑向"硬广"——投流大概率拒审、自然流被限。
# 窄化说明（避免误伤心理科普的正当表达）：
#   · "免费"不裸词入表——"免费的自助练习"合法；只收"免费领取/免费名额"这类诱导组合。
#   · "立即"不裸词入表——危机语境下"立即求助/立即就医"是正当建议；只收"立即预约/立即咨询/立即购买"。
#   · "优惠/折扣/立减/限时/秒杀"等纯促销词无正当科普用法，裸词收入。
YINGGUANG = (
    r"限时|优惠|特价|立减|折扣|降价|免单|秒杀|团购价|"
    r"仅剩\d|名额有限|抓紧报名|报名从速|"
    r"立即(预约|咨询|购买|下单|抢购)|马上(预约|咨询|下单)|"
    r"(免费|限时)(领取|名额)|免费测评名额|私信我领|扫码领|评论区扣\d"
)

# ── warn 级检测（不拉低 ok，输出到 warnings[] 供人工裁决）────────────────────
# 裸「最」：JIXIAN 只收固定搭配，裸「最」曾致假绿（2026-08-10 内容线实战：
# 「咨询和给建议最不一样的地方」机检全绿、烧进图片后不可逆）。裸「最」不能一刀
# fail（方位/时间/引语大量合法），故 warn + 三级人工裁决口径（见 BARE_ZUI_GUIDANCE）。
# 白名单：方位/时间/固定词/数量限定——这些组合直接豁免不出 warn，减噪。
BARE_ZUI_WHITELIST = r"最近|最终|最后|最初|最先|最早|最新|最左|最右|最上|最下|最底|最顶|最前|最外|最内|最中间|最坏情况|最多|最少|最低限度"
BARE_ZUI_GUIDANCE = (
    "裸「最」需人工三级裁决：🔴对自家服务/内容的最高级断言→必改(广告法风险)；"
    "🟡对心理现象的最高级(最隐蔽/最伤人)→建议软化；"
    "⚪引语原文逐字引用→豁免(改了变错引)。方位/时间/固定词已白名单滤除。"
)

# 提示词元指令残留：`逐字写出这行字：` 之后同一行再出现破折号/分号引导的补充说明，
# 出图会把说明一并画进主标题（2026-08-10 内容线实战翻车）。规范＝元指令放冒号前
# 括号内，冒号后只留要画的文字（illustration-spec.md）。
PROMPT_META_TRAIL = re.compile(r"逐字写出这行字[:：].*[—;；]")


def scan_warnings(numbered_lines: list, raw_text: str) -> list:
    """warn 级扫描：裸「最」（围栏外区块行）+ 提示词元指令残留（全文含围栏内）。

    返回 [{"rule", "line", "text", "guidance"}, ...]；不影响 ok。
    """
    warnings = []
    zui_pat = re.compile(r"最")
    white_pat = re.compile(BARE_ZUI_WHITELIST)
    jixian_pat = re.compile(JIXIAN)
    for line_no, line in numbered_lines:
        if not zui_pat.search(line):
            continue
        if jixian_pat.search(line):
            continue  # 已被极限词 fail 命中，不重复 warn
        # 抠掉白名单组合后仍残留「最」才 warn
        residue = white_pat.sub("", line)
        if "最" in residue:
            warnings.append({
                "rule": "裸最(需人工裁决)",
                "line": line_no,
                "text": line.strip(),
                "guidance": BARE_ZUI_GUIDANCE,
            })
    # 提示词元指令残留：提示词在代码围栏内，须扫原始全文
    for i, line in enumerate(raw_text.splitlines(), start=1):
        if PROMPT_META_TRAIL.search(line):
            warnings.append({
                "rule": "提示词元指令残留",
                "line": i,
                "text": line.strip()[:120],
                "guidance": "元指令一律放冒号前的括号内，冒号之后只留要画的文字；"
                            "破折号/分号后的说明会被画进图。",
            })
    # 标题以「的你」结尾：公众号腔标记，实测浏览 5.3% vs 大盘 10.7%（2026-08-10 数据判据）
    for i, line in enumerate(raw_text.splitlines(), start=1):
        m = re.match(r"^(?:#+\s*)?(?:标题|发布标题)[:：]\s*(.+)$", line.strip())
        title = m.group(1).strip() if m else None
        if title and title.rstrip("！？。!?").endswith("的你"):
            warnings.append({
                "rule": "标题的你结尾",
                "line": i,
                "text": line.strip()[:120],
                "guidance": "名词化第二人称结尾是公众号腔标记（实测跑输大盘一半）——"
                            "改成有具体主语和具体事的句子（见 xiaohongshu-spec 冒号右侧三问）。",
            })
    return warnings


def remove_fenced_blocks(text: str) -> str:
    """移除所有 ``` 围栏块（用于危机声明检查，不关心行号）。"""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def strip_fenced_lines(text: str) -> list:
    """按原始文件绝对行号跳过 ``` 围栏标记行及围栏内容。

    与原 check_compliance.sh 的 awk 语义一致：
    `/^```/ { infence = !infence; next } !infence { print NR, $0 }`——
    围栏标记行本身、围栏内的行都不输出，但保留每个存活行的原始 1-based 行号，
    使违规命中能直接定位回原文件的真实行号（供运营核实/修改）。
    返回 [(原始行号, 行内容), ...]。
    """
    result = []
    in_fence = False
    for line_no, line in enumerate(text.split("\n"), start=1):
        if re.match(r"^```", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        result.append((line_no, line))
    return result


def extract_publish_section(numbered_lines: list) -> tuple:
    """从 (原始行号, 行内容) 列表中提取 "## 发布文案"/"## 正文" 区块。

    与 count_xhs.py 的 count_body_chars 使用相同的标题兼容口径，
    避免只认 "## 发布文案" 而漏扫用旧别名 "## 正文" 写的稿子（合规绕过风险）。
    返回 (区块内的 (原始行号, 行内容) 列表, 是否找到该区块)。
    """
    body = []
    in_section = False
    found = False

    for line_no, line in numbered_lines:
        if re.match(r"^## *(发布文案|正文)", line):
            in_section = True
            found = True
            continue
        if in_section and re.match(r"^## ", line):
            break
        if in_section:
            body.append((line_no, line))

    return body, found


def extract_carousel_section(numbered_lines: list) -> tuple:
    """从 (原始行号, 行内容) 列表中提取 "## 配图轮播" 区块（不含子标题 "### PN"，
    因为提取只以 "^## " 二级标题为边界，"### PN" 是三级标题不会触发结束）。

    对抗自检发现的盲区：配图轮播区块里 "### PN 页面文字" 会被逐字渲染进对外公开
    的配图（P4 页面文字写明文微信号也会被看到），但原扫描范围只认 "## 发布文案"，
    导致这类内容零命中。围栏内的绘图提示词（负向指令，如"不要出现二维码"）已由
    调用方经 strip_fenced_lines 剔除，此处不重复处理，语义与 extract_publish_section
    一致：只按标题边界切区块。

    返回 (区块内的 (原始行号, 行内容) 列表, 是否找到该区块)。
    """
    body = []
    in_section = False
    found = False

    for line_no, line in numbered_lines:
        if re.match(r"^## *配图轮播", line):
            in_section = True
            found = True
            continue
        if in_section and re.match(r"^## ", line):
            break
        if in_section:
            body.append((line_no, line))

    return body, found


def scan_violations(numbered_lines: list) -> list:
    """扫描 (原始行号, 行内容) 列表中的违禁词。

    返回 [{"rule": 词表名, "line": 原始文件绝对行号, "text": 行内容}, ...]。
    """
    violations = []
    rules = [
        ("极限词", JIXIAN),
        ("医疗违禁", YILIAO),
        ("站外导流", DAOLIU),
        ("硬广特征", YINGGUANG),
    ]

    for line_no, line in numbered_lines:
        for rule_name, pattern in rules:
            if re.search(pattern, line):
                violations.append({
                    "rule": rule_name,
                    "line": line_no,
                    "text": line.strip(),
                })

    return violations


def has_crisis_declaration(text: str) -> bool:
    """检查是否包含危机声明 12356。"""
    return compliance_core.CRISIS_HOTLINE in text


# 危机热线号码红线（2026-08-14 定案）。小红书一行声明维持 12356 单号（300 字笔记的一行
# 页脚塞不下第二个机构全名，是版式现实不是安全让步），故这里不要求 010-82951332 在位，
# 只拦两种会把读者引向拨不通号码的写法：
#   ① 希望24（4001619995）已证据停用——官网信息冻结于 2021、2023 年自述近半来电无法接通；
#   ② 12356 官方口径为每日≥18 小时，标「24 小时」会让深夜求助者照着打不通、手里又没有
#      备选号码；全仓唯一可标 24 小时的号码是 010-82951332。
# ① 停用热线的三条正则与「更正稿豁免」判据在 shared/compliance_core.py（唯一真源，
#    与 preflight.py 共用）——⛔ 别在这里再抄一份，两边各存一份必漂。
# ② 「12356 标 24 小时」是小红书侧独有的检查（长文侧 R8 要求 010-82951332 在位，
#    此处只有 12356 单号），故留本地。
H24_MARK = re.compile(r"24\s*(?:小时|[hH](?![A-Za-z]))")
# 分段边界：强句读 + 010-82951332 本身。用于判断「24 小时」到底挂在谁身上——
# 标准声明「…12356，或…010-82951332（24 小时）」里两者同行但 24 小时归 010，不能误伤。
# ⛔ 不能拿逗号当边界：违规写法「12356（全国心理援助热线，24 小时）」正是靠逗号连接的。
H24_SCOPE_SPLIT = re.compile(r"[。；;！!？?\n]|010-?82951332")


def scan_crisis_hotline_violations(numbered_lines):
    """扫危机热线号码红线，返回与 scan_violations 同构的违规项（多带一个 detail 字段）。

    扫描域与「危机声明在位」检查一致（整文去围栏，不收窄到发布文案/配图轮播区块）：
    末页图上的错号码与正文里的一样会被读者照着拨。命中即 fail，且不受 --no-crisis 豁免——
    推介笔记可以不带危机声明，但不能带错的。
    """
    out = []
    for line_no, line in numbered_lines:
        if compliance_core.has_dead_hotline(line):
            out.append({
                "rule": "停用热线",
                "detail": compliance_core.DEAD_HOTLINE_DETAIL,
                "line": line_no,
                "text": line.strip(),
            })
        if any("12356" in seg and H24_MARK.search(seg)
               for seg in H24_SCOPE_SPLIT.split(line)):
            out.append({
                "rule": "热线时段误标",
                "detail": "12356 官方口径为每日≥18小时，不得标注 24 小时；"
                          "24 小时只能挂 010-82951332（北京心理危机研究与干预中心）",
                "line": line_no,
                "text": line.strip(),
            })
    return out


def main():
    # 场景开关：--no-crisis 跳过「危机声明在位」检查（咨询师推介笔记场景专用——
    # 推介是人物介绍非心理科普内容，强行要 12356 声明反而像在科普栏目里）；
    # 极限词/医疗违禁/站外导流/硬广特征照常全扫，绝不放松。
    args = sys.argv[1:]
    no_crisis = False
    files = []
    for a in args:
        if a == "--no-crisis":
            no_crisis = True
        else:
            files.append(a)

    if not files:
        print(json.dumps({"error": "usage: check_compliance.py <file> [--no-crisis]"}, ensure_ascii=False))
        sys.stderr.write("Error: missing required argument <file>\n")
        sys.exit(2)

    filepath = Path(files[0])

    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(json.dumps({"error": f"文件不存在: {filepath}"}, ensure_ascii=False))
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(2)

    # 危机声明检查：整文件去围栏后检查，不限"发布文案"区块内外。
    # 口径依据：① 原 check_compliance.sh 对全文 grep '12356'（不区分围栏内外，
    #   此处额外去围栏是刻意收紧——提示词误含"12356"不该被当作合规声明）；
    #   ② SKILL.md 明确危机声明"放正文末或末页"，末页文字属于 "## 配图轮播"
    #   区块（P6 页面文字），并不在 "## 发布文案" 区块内——若把检查收窄到只看
    #   发布文案区块，会把写在末页的合法危机声明误判为缺失。故保留整文口径。
    text_no_fences = remove_fenced_blocks(text)
    crisis_ok = has_crisis_declaration(text_no_fences)
    crisis_required = not no_crisis

    # 违禁词扫描：按原始文件绝对行号跳过围栏，再提取"发布文案"+"配图轮播"两个区块。
    # 扫描范围扩展依据：配图轮播里 "### PN 页面文字"（围栏外）会被逐字渲染进对外
    # 公开的配图，与发布文案同样必须扫描，否则明文违禁词写在页面文字里会零命中
    # （对抗自检发现的盲区）；围栏内的绘图提示词仍按原语义跳过（负向指令不误伤）。
    numbered_lines = strip_fenced_lines(text)
    publish_section, publish_found = extract_publish_section(numbered_lines)
    carousel_section, carousel_found = extract_carousel_section(numbered_lines)

    if publish_found or carousel_found:
        scan_target = publish_section + carousel_section
    else:
        # 合规兜底闸：两个已知区块都找不到时绝不能静默判全绿——
        # 退化为全文（已去围栏）扫描，宁可误报也不可漏报。
        print(
            "警告：未找到「## 发布文案」「## 正文」或「## 配图轮播」区块，"
            "违禁词扫描已降级为全文扫描",
            file=sys.stderr,
        )
        scan_target = numbered_lines

    violations = scan_violations(scan_target)
    # 热线号码红线不走区块提取，扫全部去围栏行——与「危机声明在位」同域（末页文字也算）。
    violations += scan_crisis_hotline_violations(numbered_lines)
    warnings = scan_warnings(scan_target, text)

    # crisis_required=False（--no-crisis）时，危机声明缺失不再拉低 ok；违禁词照旧一票否决。
    # warnings 不拉低 ok——warn 是人工裁决信号，不是机器判死。
    ok = len(violations) == 0 and (crisis_ok or not crisis_required)

    result = {
        "violations": violations,
        "warnings": warnings,
        "crisis_ok": crisis_ok,
        "crisis_required": crisis_required,
        "ok": ok,
    }

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

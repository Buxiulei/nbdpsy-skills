#!/usr/bin/env python3
"""小红书短文合规扫描：高置信违禁词 + 危机声明在位检查。"""

import json
import re
import sys
from pathlib import Path

# 词表（移植自 check_compliance.sh）
# 极限词（广告法 §9）
JIXIAN = r"最有效|最好的方法|最强|全网第一|第一品牌|唯一一家|独家秘[籍方]|国家级|世界级|顶[级尖]|根治|永久根除|100%|百分之百|彻底治愈|彻底摆脱|彻底解决|绝对有效|包治|包好"

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
    return "12356" in text


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

    # crisis_required=False（--no-crisis）时，危机声明缺失不再拉低 ok；违禁词照旧一票否决。
    ok = len(violations) == 0 and (crisis_ok or not crisis_required)

    result = {
        "violations": violations,
        "crisis_ok": crisis_ok,
        "crisis_required": crisis_required,
        "ok": ok,
    }

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

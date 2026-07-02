#!/usr/bin/env python3
"""小红书短文合规扫描：高置信违禁词 + 危机声明在位检查。"""

import json
import re
import sys
from pathlib import Path

# 词表（移植自 check_compliance.sh）
# 极限词（广告法 §9）
JIXIAN = r"最有效|最好的方法|最强|全网第一|第一品牌|唯一一家|独家秘[籍方]|国家级|世界级|顶[级尖]|根治|永久根除|100%|百分之百|彻底治愈|彻底摆脱|彻底解决|绝对有效|包治|包好"

# 医疗违禁（非医疗机构禁涉）— 移植自 check_compliance.sh
# 注：治愈 可单独出现或后跟特定字符；其他是高风险短语
YILIAO = r"治愈|药到病除|特效药?|疗效显著|抗抑郁药|根治焦虑|根治抑郁"

# 站外导流（小红书限流封号红线）
DAOLIU = r"加微信|微信号|微信:|加我[vV][xX]|加[vV][xX]|扫码|二维码|加群|进群|私聊加|留[个下]?联系方式|留电话|手机号|网盘|公众号搜"


def remove_fenced_blocks(text: str) -> str:
    """移除所有 ``` 围栏块。"""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def extract_publish_section(text: str) -> str:
    """提取 "## 发布文案" 区块。"""
    lines = text.split('\n')
    body_lines = []
    in_section = False

    for line in lines:
        if re.match(r"^## *发布文案", line):
            in_section = True
            continue
        if in_section and re.match(r"^## ", line):
            break
        if in_section:
            body_lines.append(line)

    return '\n'.join(body_lines)


def scan_violations(text: str) -> list:
    """扫描文本中的违禁词，返回 [{"rule": 词表名, "line": 行号, "text": 行内容}, ...]。"""
    violations = []
    rules = [
        ("极限词", JIXIAN),
        ("医疗违禁", YILIAO),
        ("站外导流", DAOLIU),
    ]

    lines = text.split("\n")
    for line_no, line in enumerate(lines, start=1):
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
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: check_compliance.py <file>"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    filepath = Path(sys.argv[1])

    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    # 移除围栏块
    text_no_fences = remove_fenced_blocks(text)

    # 只扫发布文案块
    publish_section = extract_publish_section(text_no_fences)

    # 扫描违禁词
    violations = scan_violations(publish_section)

    # 检查危机声明
    crisis_ok = has_crisis_declaration(text_no_fences)

    ok = len(violations) == 0 and crisis_ok

    result = {
        "violations": violations,
        "crisis_ok": crisis_ok,
        "ok": ok,
    }

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""统计小红书短文「发布文案」正文的纯汉字数并判定是否接近目标字数。"""

import json
import re
import sys
from pathlib import Path

# 阈值（移植自 count_xhs.sh）
DEFAULT_TARGET = 300
PAGE_MIN = 6
PAGE_MAX = 9


def count_body_chars(text: str) -> int:
    r"""
    提取 "## 发布文案"/"## 正文" 与下一个 "## " 标题之间的内容。
    数非标签行中的汉字（一-龥）。
    """
    # 分行处理，手工提取发布文案块
    lines = text.split('\n')
    body_lines = []
    in_section = False

    for line in lines:
        # 检测发布文案/正文标题
        if re.match(r"^## *(发布文案|正文)", line):
            in_section = True
            continue
        # 检测下一个 ## 标题，结束提取
        if in_section and re.match(r"^## ", line):
            break
        # 收集正文行
        if in_section:
            body_lines.append(line)

    body = '\n'.join(body_lines)

    # 去掉可见标签行（以 # 紧跟非空格）
    body = re.sub(r"^\s*#\S.*$\n?", "", body, flags=re.MULTILINE)

    # 计数汉字（Unicode 范围 一-龥）
    chinese_chars = re.findall(r"[一-龥]", body)
    return len(chinese_chars)


def count_pages(text: str) -> int:
    r"""计数匹配 ^### P(\d+) 的页数。"""
    pages = re.findall(r"^### P(\d+)", text, re.MULTILINE)
    return len(pages)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: count_xhs.py <file>"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)

    filepath = Path(sys.argv[1])

    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)

    body_chars = count_body_chars(text)
    pages = count_pages(text)

    # 阈值检查
    lo = DEFAULT_TARGET * 70 // 100
    hi = DEFAULT_TARGET * 150 // 100

    ok_body = lo <= body_chars <= hi
    ok_pages = PAGE_MIN <= pages <= PAGE_MAX
    ok = ok_body and ok_pages

    result = {
        "body_chars": body_chars,
        "pages": pages,
        "ok_body": ok_body,
        "ok_pages": ok_pages,
        "ok": ok,
    }

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()

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
TITLE_MAX = 20  # 小红书标题硬限 20 字（xiaohongshu-spec §1）——此前 spec 写了红线但脚本零守卫
TITLE_KEYWORD_HEAD = 10  # 目标长尾词必须完整落在标题前 10 字内（xiaohongshu-spec §1「标题」2026-07-26 改版）

# emoji / 变体选择符 / 零宽连接符 —— 计数与定位前统一剔除，两处口径必须一致
_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\uFE0F\u200D\u2190-\u21FF\u2B00-\u2BFF]")


def strip_emoji(text: str) -> str:
    """剔除 emoji 与变体选择符，返回用于计数/定位的标题正文。"""
    return _EMOJI_RE.sub("", text).strip()


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


def count_title_chars(text: str) -> tuple:
    r"""提取 frontmatter 的 title 并计数「小红书显示长度」。

    计数口径（与平台一致，非纯汉字数）：汉字/全角标点各 1，
    ASCII 字符（英文字母/数字/半角标点）各 1——即 len() 后的字符数，
    但**剔除 emoji 与变体选择符**（平台标题里 emoji 不占用可见字数配额的主体，
    且我们的红线本意是限制"信息量"，emoji 属装饰）。
    返回 (title, chars, found)；无 frontmatter 或无 title 时 found=False。
    """
    m = re.search(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return ("", 0, False)
    mt = re.search(r"^title:\s*(.+)$", m.group(1), re.MULTILINE)
    if not mt:
        return ("", 0, False)
    title = mt.group(1).strip().strip('"').strip("'")
    # 剔除 emoji（含变体选择符/零宽连接符）后计数
    return (title, len(strip_emoji(title)), True)


def check_title_keyword(title: str, keyword: str) -> tuple:
    r"""校验目标长尾词是否**完整**落在标题前 TITLE_KEYWORD_HEAD 字内。

    口径与 title_chars 一致（先剔 emoji 再定位），大小写不敏感（CPTSD / cptsd 同词）。
    "完整落在前 10 字内" = 词的结束位置 <= 10——排在 10 字之后的关键词等于没写
    （手机一屏标题约露 12 字，搜索匹配与算法权重都偏重前段）。
    返回 (ok, pos, reason)；pos 为 0 基下标，未命中为 -1；ok 时 reason 为空串。
    """
    cleaned = strip_emoji(title)
    pos = cleaned.lower().find(keyword.lower())
    if pos < 0:
        return (False, -1, f"目标长尾词「{keyword}」未出现在标题里")
    if pos + len(keyword) > TITLE_KEYWORD_HEAD:
        return (False, pos,
                f"目标长尾词「{keyword}」未完整落在标题前 {TITLE_KEYWORD_HEAD} 字内"
                f"（起始于第 {pos + 1} 字）——字数不够时砍钩子、不砍关键词")
    return (True, pos, "")


def count_pages(text: str) -> int:
    r"""计数匹配 ^### P(\d+) 的页数。"""
    pages = re.findall(r"^### P(\d+)", text, re.MULTILINE)
    return len(pages)


def main():
    # 页数区间可覆盖：长文拆分默认 6–9；咨询师推介笔记场景传 --page-min 4 --page-max 6。
    # 正文字数区间可覆盖：默认沿用 DEFAULT_TARGET 派生的 210–450（兼容科普笔记）；
    # 咨询师推介笔记正文更长，传 --body-min 400 --body-max 800。
    # 标题长尾词校验为**可选**：不传 --title-keyword 时行为与历史版本完全一致（只校 20 字硬限）。
    args, files = sys.argv[1:], []
    page_min, page_max = PAGE_MIN, PAGE_MAX
    body_min, body_max = None, None
    title_keyword = ""
    i = 0
    while i < len(args):
        if args[i] == "--page-min" and i + 1 < len(args):
            page_min = int(args[i + 1]); i += 2
        elif args[i] == "--page-max" and i + 1 < len(args):
            page_max = int(args[i + 1]); i += 2
        elif args[i] == "--body-min" and i + 1 < len(args):
            body_min = int(args[i + 1]); i += 2
        elif args[i] == "--body-max" and i + 1 < len(args):
            body_max = int(args[i + 1]); i += 2
        elif args[i] == "--title-keyword" and i + 1 < len(args):
            title_keyword = args[i + 1].strip(); i += 2
        else:
            files.append(args[i]); i += 1
    if not files:
        print(json.dumps({"error": "usage: count_xhs.py <file> [--page-min N] [--page-max N] "
                                    "[--body-min N] [--body-max N] [--title-keyword 词]"},
                         ensure_ascii=False))
        sys.stderr.write("Error: missing required argument <file>\n")
        sys.exit(2)

    filepath = Path(files[0])

    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(json.dumps({"error": f"文件不存在: {filepath}"}, ensure_ascii=False))
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(2)

    body_chars = count_body_chars(text)
    pages = count_pages(text)
    title, title_chars, title_found = count_title_chars(text)

    # 阈值检查：正文字数区间默认由 DEFAULT_TARGET 派生（210–450），可被 --body-min/max 覆盖
    lo = body_min if body_min is not None else DEFAULT_TARGET * 70 // 100
    hi = body_max if body_max is not None else DEFAULT_TARGET * 150 // 100

    ok_body = lo <= body_chars <= hi
    ok_pages = page_min <= pages <= page_max
    # 标题缺失不判 FAIL（范例/片段文件可能无 frontmatter）；有则必须 <=20 字
    ok_title = (not title_found) or (title_chars <= TITLE_MAX)
    reasons = []
    if title_found and title_chars > TITLE_MAX:
        reasons.append(f"标题 {title_chars} 字，超硬限 {TITLE_MAX} 字")

    # 目标长尾词校验（仅在传了 --title-keyword 时生效）
    title_keyword_pos = None
    if title_keyword:
        if not title_found:
            # 显式要求校验关键词，却没有 title 可校 —— 不能静默放行
            ok_title = False
            reasons.append(f"未找到 frontmatter title，无法校验目标长尾词「{title_keyword}」")
        else:
            kw_ok, title_keyword_pos, kw_reason = check_title_keyword(title, title_keyword)
            if not kw_ok:
                ok_title = False
                reasons.append(kw_reason)

    ok = ok_body and ok_pages and ok_title

    result = {
        "body_chars": body_chars,
        "pages": pages,
        "title": title,
        "title_chars": title_chars,
        "title_found": title_found,
        "title_keyword": title_keyword,
        "title_keyword_pos": title_keyword_pos,
        "title_reason": "；".join(reasons),
        "ok_body": ok_body,
        "ok_pages": ok_pages,
        "ok_title": ok_title,
        "ok": ok,
    }

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()

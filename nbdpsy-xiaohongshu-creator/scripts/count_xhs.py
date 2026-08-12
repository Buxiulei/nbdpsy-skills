#!/usr/bin/env python3
"""统计小红书短文「发布文案」正文的纯汉字数并判定是否接近目标字数。"""

import json
import re
import sys
from pathlib import Path

# 阈值（移植自 count_xhs.sh）
DEFAULT_TARGET = 300
PLATFORM_BODY_SAFE = 900   # 平台物理约束：正文+标签共 1000，给标签留 ~100 的安全值（唯一硬上限）
PAGE_MIN = 6
PAGE_MAX = 9
TITLE_MAX = 20  # 小红书标题硬限 20 字（xiaohongshu-spec §1）——此前 spec 写了红线但脚本零守卫
TITLE_KEYWORD_HEAD = 10  # 目标长尾词必须完整落在标题前 10 字内（xiaohongshu-spec §1「标题」2026-07-26 改版）

USAGE = ("usage: count_xhs.py <file> [--page-min N] [--page-max N] "
         "[--body-min N] [--body-max N] [--title-keyword 词] "
         "[--density-max N] [--density-points M]")

# 页面文字块里的「结构标签」——它们是版面角色标注、不是要渲染进图的字，计数时剔标签词本身、保留冒号后的值；
# 且这些行不算「信息点」（大标题/副标题是版面元素，不是一条独立信息）。2026-07-26 老板定案的密度档位化配套。
DENSITY_LABELS = ("大标题", "主标题", "副标题", "标题", "页脚", "底部结语", "结语", "底部")
DENSITY_RULE = (
    "字数＝该页「**页面文字**」块的汉字数（口径同 body_chars）；"
    "信息点＝该块剔除结构标签行后剩余的非空行数。\n"
    "⚠️ **只数汉字**（一-龥）：emoji／英文缩写／数字／标点一律不计——`CPTSD`、`7.2%` 都记 0 字；"
    "「大标题/副标题/页脚/结语」等结构标签词与 `（＝…）` 式注解也不计，冒号后的值照计。\n"
    "⚠️ **信息点是保守下界**：按行数算，一行里塞多条也只记 1 条（实际常为该数的约 2 倍），宁可少算不多算；"
    "故 **exit 0 不等于达标**，贴近上限时以人工目视逐页数为准。\n"
    "⚠️ **只约束内容页 P2…P(N-1)**：封面 P1 与末页 PN **不计入上限**"
    "（末页必须承载「行动建议＋品牌一句＋12356 危机声明」，字数天然高于内容页）；"
    "这两页照常输出实测值（`density_pages` 里 `counted: false`）供人工参考，**不参与 `ok_density` 判定**。"
    "（2026-07-26 决策 2：密度档位只约束内容页）\n"
    "⚠️ **本项只在传参时启用**——传了 --density-max／--density-points 即代表运营指定了密度档，"
    "超限即判（`ok_density=false` → `ok=false`，exit 2）；默认档不传参、本项不参与裁决。"
    "注意 exit 2 由正文字数／页数／标题／密度任一不达标触发，"
    "**是否密度问题只看 `ok_density` 与 `density_reason`，不看 exit code**。\n"
    "（2026-07-26 老板定案：运营指定的密度档是硬上限，默认档 200–400 的上限不判 FAIL；"
    "裁决语义与「保守下界／只数汉字」口径 2026-07-26 依 v1.37.0 修补契约 V2#3／V2#4 写明）"
)

# emoji / 变体选择符 / 零宽连接符 —— 计数与定位前统一剔除，两处口径必须一致
_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\uFE0F\u200D\u2190-\u21FF\u2B00-\u2BFF]")


def strip_emoji(text: str) -> str:
    """剔除 emoji 与变体选择符，返回用于计数/定位的标题正文。"""
    return _EMOJI_RE.sub("", text).strip()


def count_hanzi(text: str) -> int:
    """数汉字（Unicode 范围 一-龥）——正文与页面文字共用同一口径，别另起一套。"""
    return len(re.findall(r"[一-龥]", text))


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
    return count_hanzi(body)


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


def extract_page_texts(text: str) -> list:
    r"""逐页抽出「**页面文字**」块的原始行（**图内要显示的字**，不是发布正文、不是绘图提示词）。

    页边界与 count_pages 同一契约：`^### P(\d+)`。块内两种历史写法都认——
    独占一行的 `**页面文字**` 后跟条目行，以及行内式 `**页面文字**：一行内容`。
    块在遇到围栏代码块（```／~~~，即绘图提示词）、下一个 `**加粗标记**` 行、任一标题行或下一页时结束。
    返回 [(页码标签, [行, ...]), ...]，只收有该块的页。
    """
    pages = []
    label, buf, collecting = None, None, False
    for line in text.split("\n"):
        mp = re.match(r"^### P(\d+)", line)
        if mp:
            if label is not None and buf:
                pages.append((label, buf))
            label, buf, collecting = "P" + mp.group(1), [], False
            continue
        if label is None:
            continue
        mt = re.match(r"^\*\*页面文字\*\*\s*[:：]?\s*(.*)$", line)
        if mt:
            collecting = True
            if mt.group(1).strip():
                buf.append(mt.group(1))
            continue
        if collecting:
            if re.match(r"^\s*(```|~~~)", line) or line.startswith("**") or line.startswith("#"):
                collecting = False
                continue
            buf.append(line)
    if label is not None and buf:
        pages.append((label, buf))
    return pages


def split_structural_label(line: str) -> tuple:
    """剥掉行首列表符、`（＝…）` 式注解与结构标签（见 DENSITY_LABELS）。返回 (内容, 是否结构标签行)。"""
    s = re.sub(r"^\s*[-*•·]\s*", "", line.strip())
    # `（＝核心议题词）`「＝」开头的括注是写给人看的注解、不是图上的字（范例文件封面即此写法），剔掉不计
    s = re.sub(r"[（(]\s*[＝=][^）)]*[）)]", "", s)
    m = re.match(r"^(.{1,6}?)\s*[:：]\s*(.*)$", s)
    if m and m.group(1) in DENSITY_LABELS:
        return (m.group(2), True)
    return (s, False)


def count_page_density(lines: list) -> tuple:
    """数一页「页面文字」的字数与信息点数，口径见 DENSITY_RULE。返回 (汉字数, 信息点数)。"""
    chars, points = 0, 0
    for raw in lines:
        content, is_label = split_structural_label(strip_emoji(raw))
        if not content.strip():
            continue
        chars += count_hanzi(content)
        if not is_label:
            points += 1
    return (chars, points)


def main():
    # 页数区间可覆盖：长文拆分默认 6–9；咨询师推介笔记场景传 --page-min 4 --page-max 6。
    # 正文字数区间可覆盖：默认沿用 DEFAULT_TARGET 派生的 210–450（兼容科普笔记）；
    # 咨询师推介笔记正文更长，传 --body-min 400 --body-max 800。
    # 标题长尾词校验为**可选**：不传 --title-keyword 时行为与历史版本完全一致（只校 20 字硬限）。
    # 密度档位校验同样为**可选**：`--density-max N`（每页图内文字量上限，汉字数）/
    # `--density-points M`（每页信息点数上限）——两个都不传时输出字段与历史版本逐字节一致。
    # 只在运营指明密度档位时传（2026-07-26 老板定案：运营给的数是硬上限；默认档 200–400 的 400 是建议值不判 FAIL）。
    args, files = sys.argv[1:], []
    page_min, page_max = PAGE_MIN, PAGE_MAX
    body_min, body_max = None, None
    title_keyword = ""
    density_max, density_points = None, None
    i = 0
    while i < len(args):
        if args[i] in ("--help", "-h"):
            print(USAGE + "\n\n密度档位口径（--density-max / --density-points）：\n" + DENSITY_RULE)
            sys.exit(0)
        elif args[i] == "--page-min" and i + 1 < len(args):
            page_min = int(args[i + 1]); i += 2
        elif args[i] == "--page-max" and i + 1 < len(args):
            page_max = int(args[i + 1]); i += 2
        elif args[i] == "--body-min" and i + 1 < len(args):
            body_min = int(args[i + 1]); i += 2
        elif args[i] == "--body-max" and i + 1 < len(args):
            body_max = int(args[i + 1]); i += 2
        elif args[i] == "--title-keyword" and i + 1 < len(args):
            title_keyword = args[i + 1].strip(); i += 2
        elif args[i] == "--density-max" and i + 1 < len(args):
            density_max = int(args[i + 1]); i += 2
        elif args[i] == "--density-points" and i + 1 < len(args):
            density_points = int(args[i + 1]); i += 2
        else:
            files.append(args[i]); i += 1
    if not files:
        print(json.dumps({"error": USAGE}, ensure_ascii=False))
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

    # 阈值检查：正文字数区间默认由 DEFAULT_TARGET 派生（210–450），可被 --body-min/max 覆盖。
    # ⚠️ 2026-08-12 老板定性降级：这个区间是**产品偏好的参考值，不再判 FAIL**——对照实验证明
    # 硬上限会逼写手在边缘反复剪句子，剪出「在认错」式指代悬空病句（坏的不是写手是规格）。
    # 唯一硬的是平台物理约束：正文+标签共 1000，安全值 900——超它才 FAIL。
    lo = body_min if body_min is not None else DEFAULT_TARGET * 70 // 100
    hi = body_max if body_max is not None else DEFAULT_TARGET * 150 // 100

    ok_body = lo <= body_chars <= hi          # 现语义=「落在参考区间内」，不再参与 ok 判定
    if ok_body:
        body_warn = ""
    elif body_chars > hi:
        body_warn = (f"正文 {body_chars} 字超参考区间 {lo}–{hi}（参考值不判 FAIL；"
                     "超长优先删段落、⛔ 不压句子——压句必出指代悬空）")
    else:
        body_warn = (f"正文 {body_chars} 字低于参考区间 {lo}–{hi}（参考值不判 FAIL；"
                     "「正文=钩子、完整表达在图/视频」架构下短正文合法，确认完整版已进轮播图即可）")
    ok_platform = body_chars <= PLATFORM_BODY_SAFE
    platform_reason = "" if ok_platform else (
        f"正文 {body_chars} 字超平台安全值 {PLATFORM_BODY_SAFE}"
        "（正文+标签共 1000 硬上限）：删段落回 900 内，或改走文字版形态（正文进图）")
    ok_pages = page_min <= pages <= page_max
    # 标题缺失不判 FAIL（范例/片段文件可能无 frontmatter）；有则必须 <=20 字
    ok_title = (not title_found) or (title_chars <= TITLE_MAX)
    reasons = []
    if platform_reason:
        reasons.append(platform_reason)
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

    # 密度档位校验（仅在传了 --density-max / --density-points 时生效；不传则下面的字段一个都不输出）
    density_on = density_max is not None or density_points is not None
    density_pages, density_reasons, ok_density = [], [], True
    if density_on:
        # 2026-07-26 决策 2：密度档位只约束内容页 —— 封面 P1 与末页 PN 豁免。
        # 首尾页按文档里 `### P(\d+)` 的首末标签认定（不按 density_pages 下标，
        # 免得某页缺「页面文字」块时把 P2 当成首页误豁免）。
        all_labels = ["P" + n for n in re.findall(r"^### P(\d+)", text, re.MULTILINE)]
        exempt = {all_labels[0], all_labels[-1]} if all_labels else set()
        for label, lines in extract_page_texts(text):
            chars, points = count_page_density(lines)
            density_pages.append({"page": label, "chars": chars, "points": points,
                                  "counted": label not in exempt})
        if not density_pages:
            # 显式要求校验密度，却一个「页面文字」块都没有 —— 不能静默放行
            ok_density = False
            density_reasons.append("未找到任何「**页面文字**」块，无法校验每页密度")
        # 只拿内容页参与裁决；P1/PN 仍留在 density_pages 里供人工参考
        judged = [p for p in density_pages if p["counted"]]
        if density_max is not None:
            over = [p for p in judged if p["chars"] > density_max]
            if over:
                ok_density = False
                density_reasons.append(
                    "内容页超每页文字量上限 %d 字：%s（运营指定的密度是硬上限，超了＝没执行指令）"
                    % (density_max, "、".join(f"{p['page']} {p['chars']} 字" for p in over)))
        if density_points is not None:
            over = [p for p in judged if p["points"] > density_points]
            if over:
                ok_density = False
                density_reasons.append(
                    "内容页超每页信息点上限 %d 个：%s（信息点为保守估算，判超限时请人工复核该页）"
                    % (density_points, "、".join(f"{p['page']} {p['points']} 个" for p in over)))

    ok = ok_platform and ok_pages and ok_title and ok_density

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
        "body_warn": body_warn,
        "ok_platform": ok_platform,
        "ok_pages": ok_pages,
        "ok_title": ok_title,
    }
    if density_on:
        result.update({
            "density_max": density_max,
            "density_points": density_points,
            "density_pages": density_pages,
            "density_reason": "；".join(density_reasons),
            "density_rule": DENSITY_RULE,
            "ok_density": ok_density,
        })
    result["ok"] = ok

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()

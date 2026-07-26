#!/usr/bin/env python3
"""写作态引用简称标记 `【引: 作者/机构 年份, 文献简称】` 扫描器（2026-07-26 引用职责分离）。

背景：写作 agent 只写人类可读的简称标记，编号 / URL / 参考文献区 / frontmatter citations
统一由「引用落地」步的专职引用 agent 生成。本脚本给那一步用：
1. **起步**：把全文标记结构化列出来（按正文首次出现顺序），供逐条对回第 2 步查证轮的素材清单
   `$WS/drafts/{slug}.sources.md`；`n_suggested` 只是**候选编号**，最终归并以清单同一条记录
   （同一 URL）为唯一依据，脚本 key 不同但落在同一条上的必须人工合并后重新连号；
2. **收尾**：`--expect-empty` 校验残留为 0——标记是中间态，绝不进成品。

扫描前会剥掉开头的 YAML frontmatter，只作用于正文（与审查端同款处理）：frontmatter 注释里
写的标记字面量是说明用的样例，不算残留。

用法:
  cite_scan.py <file.md> [--expect-empty]
契约: stdout=纯 JSON {"ok","total","unique","markers":[...],"malformed":[...]}
      malformed 非空、或 --expect-empty 时仍有残留 → exit 1；文件缺失 exit 2；stderr=人类可读。
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 标记形态：【引: 作者/机构 年份, 文献简称[, 页码/章节]】
# 用 `【引: ` 前缀而非普通全角括号——正文里本来就有大量正常全角括号（「（约 6.8%）」），
# 拿普通括号当标记必然误伤；`【引:`（含冒号）这个组合在中文正文里不会自然出现。
RE_MARK = re.compile(r"【引[:：]\s*([^】]*?)\s*】")
# 起始锚点必须**含冒号**（半/全角都认，与审查端 grep `【引[:：]` 同源）：只锚 `【引` 会把
# `【引言】`、`【引用文献如下】` 这类正常中文词判成写坏的标记，白白把 exit 顶成 1。
# 写坏的标记只剩「开了没闭合」一种（缺 `】` 或跨行），单独用下面这条认——它要求从锚点到行尾
# 都不出现 `】`，因此天然不会把 `【引言】` 卷进来。
RE_UNCLOSED = re.compile(r"【引[:：][^】\n]*$")
RE_YEAR = re.compile(r"(?:^|\s)(n\.d\.|\d{4})$")
RE_FENCE = re.compile(r"^```")
RE_FM_DELIM = re.compile(r"^---\s*$")


def _norm(s: str) -> str:
    """归一化：去空白与常见标点，转小写——让同一文献的不同写法能合并成同一个 n。"""
    return re.sub(r"[\s，,。.、:：;；'\"“”‘’《》〈〉_\-]", "", s).lower()


def strip_frontmatter(text: str) -> str:
    """剥掉开头的 YAML frontmatter（首行 `---` 起、下一个 `---` 止），只留正文。

    frontmatter 里的标记字面量是范文/模板的说明样例，不是残留。用等量空行占位而非删行，
    保证 stderr 报的行号仍与原文件行号一致。没有闭合分隔符时按「不是 frontmatter」原样返回。
    """
    lines = text.splitlines()
    if not lines or not RE_FM_DELIM.match(lines[0]):
        return text
    for i, line in enumerate(lines[1:], 1):
        if RE_FM_DELIM.match(line):
            return "\n".join([""] * (i + 1) + lines[i + 1:])
    return text


def parse_inner(inner: str):
    """把标记内文解析成 (作者/机构, 年份, 文献简称, 页码章节)；解析不出返回 None。"""
    parts = [p.strip() for p in re.split(r"[,，]", inner) if p.strip()]
    if len(parts) < 2:
        return None
    head = parts[0]
    m = RE_YEAR.search(head)
    if not m:
        return None
    author = head[:m.start()].strip()
    if not author:
        return None
    return author, m.group(1), parts[1], ("，".join(parts[2:]) or None)


def scan(text: str):
    markers, malformed = [], []
    index = {}                       # 归一化 key → markers 里的下标
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if RE_FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:                 # 代码块里的示例不算正文标记
            continue
        for m in RE_MARK.finditer(line):
            parsed = parse_inner(m.group(1))
            if not parsed:
                malformed.append({
                    "line": i, "text": m.group(0),
                    "why": "解析不出「作者/机构 年份, 文献简称」——年份须四位数字或 n.d.，简称用逗号分隔",
                })
                continue
            author, year, short, locator = parsed
            key = f"{_norm(author)}|{year}|{_norm(short)}"
            if key in index:
                hit = markers[index[key]]
                hit["count"] += 1
                hit["lines"].append(i)
                if locator and locator not in hit["locators"]:
                    hit["locators"].append(locator)
            else:
                index[key] = len(markers)
                markers.append({
                    "author": author, "year": year, "short": short,
                    "locators": [locator] if locator else [],
                    "count": 1, "first_line": i, "lines": [i], "key": key,
                })
        # `【引:` 开了却到行尾都没 `】` = 写坏了（缺 `】` 或跨行）；`【引言】` 这类不含冒号的
        # 正常中文词不在此列
        for m in RE_UNCLOSED.finditer(line):
            malformed.append({
                "line": i, "text": line[m.start():m.start() + 40],
                "why": "标记未闭合——正确形态 `【引: 作者/机构 年份, 文献简称】`（不得跨行）",
            })
    for n, mk in enumerate(markers, 1):  # n 按正文首次出现顺序从 1 递增
        mk["n_suggested"] = n
    return markers, malformed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--expect-empty", action="store_true",
                    help="收尾自检：要求全文 `【引:` 残留数为 0（引用落地跑完后应为空），非 0 则 exit 1")
    a = ap.parse_args()
    path = Path(a.file)
    if not path.is_file():
        print(json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False))
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(2)
    markers, malformed = scan(strip_frontmatter(path.read_text(encoding="utf-8")))
    total = sum(m["count"] for m in markers) + len(malformed)
    ok = not malformed and (not a.expect_empty or total == 0)
    for m in malformed:
        print(f"  ✗ [malformed] 行{m['line']}: {m['text']} —— {m['why']}", file=sys.stderr)
    if a.expect_empty:
        print(f"{'✓ 无残留（引用落地已跑完）' if total == 0 else f'✗ 仍残留 {total} 处 `【引:` 标记——引用落地没跑完'}",
              file=sys.stderr)
    else:
        for m in markers:
            loc = ("，" + "／".join(m["locators"])) if m["locators"] else ""
            print(f"  [{m['n_suggested']}] {m['author']} {m['year']}, {m['short']}{loc} "
                  f"（{m['count']} 处，首现行 {m['first_line']}）", file=sys.stderr)
        print(f"共 {total} 处标记 / {len(markers)} 条文献"
              f"{f'；{len(malformed)} 处写坏' if malformed else ''}", file=sys.stderr)
        print("提示：`n_suggested` 是按首现顺序的**候选**编号，不可直接当最终编号用——"
              "须逐条对回素材清单 `$WS/drafts/{slug}.sources.md`，落在同一条记录（同一 URL）"
              "的条目必须人工合并后重新连号，以清单为准。", file=sys.stderr)
    print(json.dumps({"ok": ok, "total": total, "unique": len(markers),
                      "markers": markers, "malformed": malformed}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

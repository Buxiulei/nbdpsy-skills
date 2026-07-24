#!/usr/bin/env python3
"""长文 markdown 兼容性与文内引用标注 lint。

背景（生产事故 2026-07：blog_posts id=39 十处加粗渲染失败、正文零引用标注）：
1. bold-flanking —— CommonMark 强调规则与中文排版的冲突：
   闭合 `**` 前是全角标点、后紧跟文字（如 `……。**很多人`）→ 右侧翼不成立，
   react-markdown 按规范原样输出裸 `**`。对称地，开头 `字**「话」` 左侧翼同病。
   修法：把标点移出加粗（`**……**。` / 引号放 `**` 外）。
2. citation-marker —— 文内引用统一为数字标注 `[[n]](url)`（渲染为可点击的 [n]），
   n 对应文末「## 参考文献」有序列表序号；每条参考文献须被正文至少标注一次。

用法:
  lint_markdown.py <file.md> [--citations N]
契约: stdout=纯 JSON {"ok","violations":[{"rule","line","text","fix"}],"cited":[...]}
      违规 exit 1；文件缺失 exit 2；stderr=人类可读。
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 全角/中文常用标点（闭合类：句读+右引号右括号）与（开启类：左引号左括号）
CLOSE_PUNCT = "。！？；：、，”』」）》…"
OPEN_PUNCT = "“『「（《"
# CommonMark 语义里的"文字"（导致翼判定失败的后继/前驱）：字母数字与 CJK
WORDISH = r"\w一-鿿"

# 右翼违规：闭合 ** 前是闭合类全角标点，后紧跟文字（行内继续）
RE_RIGHT = re.compile(rf"[{CLOSE_PUNCT}]\*\*(?=[{WORDISH}])")
# 左翼违规：开启 ** 前紧贴文字，后面是开启类标点（如 字**「话）
RE_LEFT = re.compile(rf"(?<=[{WORDISH}])\*\*(?=[{OPEN_PUNCT}])")
# 文内数字标注 [[n]](url)
RE_MARKER = re.compile(r"\[\[(\d+)\]\]\(https?://[^)]+\)")
# 统计数据样式（pillar-spec R3「带出处统计块」的可执行判据）：
#   百分比/千分比、倍数、相关/效应量（r/d/β/η²）、比值（OR/HR/RR/d/g）、置信区间（95% CI）。
#   样本量单独不算（N=224 不匹配任何分支）——它是规模不是统计结论。
#   2026-07 扩展：恋爱脑一文正文含 r=.42 / r=−.29 等学术统计却零 %/倍，扩前会漏计致 R3 误判不合格。
#   词界（2026-07 加固）：效应量/比值分支前加 (?<![A-Za-z]) 负向后顾——否则英文词内的 d/g/r 会被误当效应量，
#   如 'sd=1.2'（standard deviation）、'id=7'（编号）都不是统计结论，不得计入；'r=.42' 前是空格/CJK 仍计入。
RE_STAT = re.compile(
    r"\d+(?:\.\d+)?\s*[%％‰]"                       # 百分比/千分比
    r"|\d+(?:\.\d+)?\s*倍"                          # 倍数
    r"|(?<![A-Za-z])[rdβη]²?\s*[=＝]\s*[-−]?\.?\d"  # 相关系数/效应量 r/d/β/η(²)
    r"|(?<![A-Za-z])(?:OR|HR|RR|d|g)\s*[=＝]\s*\d"  # 比值/效应量 OR/HR/RR/d/g
    r"|95%\s*CI"                                    # 置信区间
)
RE_REF_HEADING = re.compile(r"^##\s*参考文献\s*$")
RE_FENCE = re.compile(r"^```")


def lint(text: str, citations: int | None, stats_min: int = 0):
    violations = []
    cited = set()
    in_fence = False
    before_refs = True
    stats_cited = stats_total = 0  # 带引用标注同句的统计数 / 全文统计样式总数
    for i, line in enumerate(text.splitlines(), 1):
        if RE_FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if RE_REF_HEADING.match(line.strip()):
            before_refs = False
        for m in list(RE_RIGHT.finditer(line)) + list(RE_LEFT.finditer(line)):
            violations.append({
                "rule": "bold-flanking", "line": i,
                "text": line[max(0, m.start() - 12):m.end() + 12],
                "fix": "把全角标点/引号移到 ** 之外（如 `**……**。`），否则渲染器会原样输出 **",
            })
        if before_refs:
            line_stats = len(RE_STAT.findall(line))
            stats_total += line_stats
            if RE_MARKER.search(line):
                stats_cited += line_stats  # R3：统计数据须与出处标注同句（行级近似）
            for m in RE_MARKER.finditer(line):
                cited.add(int(m.group(1)))
    if stats_min and stats_cited < stats_min:
        violations.append({
            "rule": "stat-block", "line": 0,
            "text": f"正文带出处的统计数据仅 {stats_cited} 处（要求 ≥{stats_min}；全篇统计样式共 {stats_total} 处）",
            "fix": "补足真实统计数据（数字+%/‰/倍）并在同一行紧跟 [[n]](来源链接)；数字必须联网核实存在，"
                   "严禁编造（pillar-spec 硬性要求 R3）",
        })
    if citations:
        missing = [n for n in range(1, citations + 1) if n not in cited]
        if missing:
            violations.append({
                "rule": "citation-marker", "line": 0,
                "text": f"文末有 {citations} 条参考文献，但正文缺少数字标注：{missing}",
                "fix": "在被支撑的句子后加 [[n]](来源链接)，n=文末参考文献序号，每条至少标注一次",
            })
    return violations, sorted(cited)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--citations", type=int, default=None,
                    help="文末参考文献条数；给出则校验文内 [[n]](url) 覆盖 1..N")
    ap.add_argument("--stats-min", type=int, default=0,
                    help="要求正文至少 N 处「统计数据+同行引用标注」（pillar 长文按 R3 传 3；默认 0 不校验）")
    a = ap.parse_args()
    path = Path(a.file)
    if not path.is_file():
        print(json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False))
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(2)
    violations, cited = lint(path.read_text(encoding="utf-8"), a.citations, a.stats_min)
    ok = not violations
    for v in violations:
        print(f"  ✗ [{v['rule']}] 行{v['line']}: {v['text']}", file=sys.stderr)
    print(f"{'✓ 通过' if ok else f'✗ {len(violations)} 处违规'}", file=sys.stderr)
    print(json.dumps({"ok": ok, "violations": violations, "cited": cited}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

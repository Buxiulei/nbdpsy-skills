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
RE_REF_HEADING = re.compile(r"^##\s*参考文献\s*$")
RE_FENCE = re.compile(r"^```")


def lint(text: str, citations: int | None):
    violations = []
    cited = set()
    in_fence = False
    before_refs = True
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
            for m in RE_MARKER.finditer(line):
                cited.add(int(m.group(1)))
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
    a = ap.parse_args()
    path = Path(a.file)
    if not path.is_file():
        print(json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False))
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(2)
    violations, cited = lint(path.read_text(encoding="utf-8"), a.citations)
    ok = not violations
    for v in violations:
        print(f"  ✗ [{v['rule']}] 行{v['line']}: {v['text']}", file=sys.stderr)
    print(f"{'✓ 通过' if ok else f'✗ {len(violations)} 处违规'}", file=sys.stderr)
    print(json.dumps({"ok": ok, "violations": violations, "cited": cited}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

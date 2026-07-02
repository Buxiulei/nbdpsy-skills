#!/usr/bin/env python3
"""长文纯汉字计数（剥 YAML frontmatter），区间外 exit 2。语义对齐原 count_hanzi.sh。"""
import argparse, json, re, sys
from pathlib import Path

def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        m = re.match(r"^---\n.*?\n---\n?", text, re.S)
        if m:
            return text[m.end():]
    return text

def count_hanzi(text: str) -> int:
    return len(re.findall(r"[一-龥]", strip_frontmatter(text)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file"); ap.add_argument("--min", type=int, default=3000); ap.add_argument("--max", type=int, default=5000)
    a = ap.parse_args()
    n = count_hanzi(Path(a.file).read_text(encoding="utf-8"))
    ok = a.min <= n <= a.max
    print(json.dumps({"hanzi": n, "min": a.min, "max": a.max, "ok": ok}, ensure_ascii=False))
    sys.exit(0 if ok else 2)

if __name__ == "__main__":
    main()

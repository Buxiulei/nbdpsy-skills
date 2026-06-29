#!/usr/bin/env bash
# 纯汉字字数统计 + 区间判定（pillar 正文口径：3000–5000）。
# 用法：bash count_hanzi.sh <md文件> [下限 上限]
# 口径：只数 CJK 汉字，英文/数字/标点/URL 不计。FAQ 与参考文献也会被算进去，
#       严格起见 pillar 正文应在剔除 FAQ/参考文献后仍 ≥3000；本脚本给全文粗值，便于快速判断。
set -euo pipefail

file="${1:?用法: count_hanzi.sh <md文件> [下限 上限]}"
lo="${2:-3000}"
hi="${3:-5000}"

[ -f "$file" ] || { echo "✗ 文件不存在: $file" >&2; exit 1; }

# 去掉 YAML frontmatter（首个 --- 到第二个 --- 之间）再计数，避免元数据汉字混入正文字数
body=$(awk 'BEGIN{f=0} /^---[[:space:]]*$/{f++; next} f>=2{print}' "$file")
n=$(printf '%s' "$body" | grep -oP '[\x{4e00}-\x{9fa5}]' | wc -l)

printf '纯汉字字数（正文，不含 frontmatter）: %s\n' "$n"
if [ "$n" -lt "$lo" ]; then
  printf '✗ 不达标：低于下限 %s，需返工补 %s 字真实内容\n' "$lo" "$((lo - n))"
  exit 2
elif [ "$n" -gt "$hi" ]; then
  printf '⚠ 偏长：超过 %s，可考虑精简（非硬性失败）\n' "$hi"
  exit 0
else
  printf '✓ 达标：在 [%s, %s] 区间内\n' "$lo" "$hi"
fi

#!/usr/bin/env bash
# 统计小红书短文「发布文案」正文的纯汉字数并判定是否接近目标字数。
# 口径：数 ## 发布文案（或旧名 ## 正文）到下一个 ## 标题之间的汉字；
#       英文/数字/标点/emoji 不计，且不把"可见标签行"（#xxx）里的汉字算进字数。
# 用法: count_xhs.sh <post.md> [目标字数=300]
# 退出码: 0 达标; 1 偏短或偏长（作为发布前的字数闸门）
set -euo pipefail

f="${1:?用法: count_xhs.sh <post.md> [目标字数=300]}"
target="${2:-300}"

# 提取 "## 发布文案"/"## 正文" 与下一个 "## " 标题之间的内容（标题行本身不计）
body=$(awk '/^## *(发布文案|正文)/{flag=1;next} /^## /{flag=0} flag' "$f")
# 去掉可见标签行（以 # 紧跟非空格，区别于 markdown 标题的 "# "），标签汉字不计入正文字数
body=$(printf '%s\n' "$body" | grep -vP '^\s*#\S' || true)
n=$(printf '%s' "$body" | grep -oP '[\x{4e00}-\x{9fa5}]' | wc -l | tr -d ' ')

lo=$(( target * 70 / 100 ))    # 目标 70%
hi=$(( target * 150 / 100 ))   # 目标 150%

printf '正文汉字数: %s（目标 %s，建议区间 %s–%s）\n' "$n" "$target" "$lo" "$hi"

if [ "$n" -lt "$lo" ]; then
  echo "⚠ 偏短：补真内容到至少 $lo 字（多一条要点/一个共情场景），不要注水"
  exit 1
elif [ "$n" -gt "$hi" ]; then
  echo "⚠ 偏长：小红书正文过长易被划走，压到 $hi 字内"
  exit 1
else
  echo "✓ 字数达标"
fi

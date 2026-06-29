#!/usr/bin/env bash
# 参考文献/内链 URL 可达性初筛（HTTP 层）。
# 这只揪「死链」，不保证「引用口径正确」——语义正确性仍须撰写时 WebFetch 逐条核实。
# 用法：bash check_links.sh <md文件>
# 退出码：有任一外链不可达 → 1；全可达（或仅站内相对链接）→ 0。
set -uo pipefail

file="${1:?用法: check_links.sh <md文件>}"
[ -f "$file" ] || { echo "✗ 文件不存在: $file" >&2; exit 1; }

# 抽出所有 http(s) 绝对 URL（markdown 链接、frontmatter、正文裸链都覆盖），去重
mapfile -t urls < <(grep -oP 'https?://[^\s)<>"]+' "$file" | sed 's/[.,；。)]*$//' | sort -u)

if [ "${#urls[@]}" -eq 0 ]; then
  echo "（无外部 URL；站内相对链接 /xxx 不在本脚本检查范围）"
  exit 0
fi

fail=0
warn=0
for u in "${urls[@]}"; do
  # 跟随跳转，HEAD 优先；部分站禁 HEAD 时回退 GET 取状态码
  code=$(curl -sS -o /dev/null -L -A 'Mozilla/5.0 (link-check)' --max-time 20 -w '%{http_code}' -I "$u" 2>/dev/null || echo 000)
  if [ "$code" = "000" ] || [ "$code" -ge 400 ] 2>/dev/null; then
    code=$(curl -sS -o /dev/null -L -A 'Mozilla/5.0 (link-check)' --max-time 20 -w '%{http_code}' "$u" 2>/dev/null || echo 000)
  fi
  if [ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 400 ] 2>/dev/null; then
    printf '  ✓ %s  %s\n' "$code" "$u"
  elif [ "$code" = "401" ] || [ "$code" = "403" ] || [ "$code" = "429" ]; then
    # 出版商常对脚本 UA 反爬（牛津/Wiley/Springer 等）；URL 多半有效，留待 WebFetch 人工核实，不算死链
    printf '  ⚠ %s  %s  （疑似反爬，须撰写时 WebFetch 已核实其内容）\n' "$code" "$u"
    warn=1
  else
    printf '  ✗ %s  %s\n' "$code" "$u"
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "✗ 存在不可达外链（404/000/5xx），修复或更换来源后再入库"
  exit 1
fi
if [ "$warn" -ne 0 ]; then
  echo "⚠ 含反爬链接（401/403/429）：非死链，但务必确认撰写时已 WebFetch 核实其内容口径"
fi
echo "✓ 无死链（口径正确性仍以撰写时 WebFetch 核实为准）"

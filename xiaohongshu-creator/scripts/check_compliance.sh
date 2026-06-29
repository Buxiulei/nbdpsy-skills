#!/usr/bin/env bash
# 小红书短文合规扫描：高置信违禁词 + 危机声明在位检查。
# 只扫"会被发布"的文案（正文 / 标签 / 页面文字），跳过 ``` 围栏内的绘图提示词——
#   提示词是给画图模型的生成指令（常含 HEX 色值、"不要出现二维码"之类负向指令），永不发布，扫它只会误伤。
# 故意只扫"高置信、低误伤"的词；治疗/诊断等需结合语境的词靠 references/xiaohongshu-spec.md 的语义自检。
# 用法: check_compliance.sh <文件或目录>
# 退出码: 0 全绿; 1 命中红线（需人工处理）
set -uo pipefail

target="${1:?用法: check_compliance.sh <文件或目录>}"

# 极限词（广告法 §9）——写具体短语，避免误伤"最近/最后/第一步"等正常词
JIXIAN='最有效|最好的方法|最强|全网第一|第一品牌|唯一一家|独家秘[籍方]|国家级|世界级|顶[级尖]|根治|永久根除|100%|百分之百|彻底治愈|彻底摆脱|彻底解决|绝对有效|包治|包好'
# 医疗违禁（非医疗机构禁涉）
YILIAO='治愈[了焦抑情你]|药到病除|特效药?|疗效显著|抗抑郁药|根治焦虑|根治抑郁'
# 站外导流（小红书限流封号红线）
DAOLIU='加微信|微信号|微信:|加我[vV][xX]|加[vV][xX]|扫码|二维码|加群|进群|私聊加|留[个下]?联系方式|留电话|手机号|网盘|公众号搜'

# 收集所有目标 .md 文件
list_files () {
  if [ -d "$target" ]; then find "$target" -type f -name '*.md' | sort
  else printf '%s\n' "$target"; fi
}

# 输出"会被发布"的行（跳过 ``` 围栏代码块），格式 file:lineno:正文
published () {
  local f
  while IFS= read -r f; do
    awk -v F="$f" '
      /^```/ { infence = !infence; next }
      !infence { printf "%s:%d:%s\n", F, NR, $0 }
    ' "$f"
  done < <(list_files)
}

PUB="$(published)"
hit=0
scan () {
  local name="$1" pat="$2" out
  out=$(printf '%s\n' "$PUB" | grep -P -- "$pat") || true
  if [ -n "$out" ]; then
    echo "✗ 命中【$name】（出现在会发布的文案里）："
    printf '%s\n' "$out" | sed 's/^/    /'
    hit=1
  fi
}

scan "极限词" "$JIXIAN"
scan "医疗违禁" "$YILIAO"
scan "站外导流" "$DAOLIU"

# 危机声明在位：每个 post-*.md 应含援助热线 12356（整文件检查，不限围栏内外）
miss=$(grep -rL '12356' "$target" --include='post-*.md' 2>/dev/null) || true
if [ -n "$miss" ]; then
  echo "✗ 缺危机声明(12356)的文件："
  echo "$miss" | sed 's/^/    /'
  hit=1
fi

if [ "$hit" -eq 0 ]; then
  echo "✓ 合规扫描通过（高置信违禁词无命中、危机声明在位）"
  echo "  提醒：治疗/诊断等语境词靠语义自检（见 references/xiaohongshu-spec.md 替换表）"
fi
exit "$hit"

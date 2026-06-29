#!/usr/bin/env bash
# NBDpsy skills 一键安装：把两个 skill 拷进 Claude Code / Codex 的技能目录。
# 用法：
#   ./install.sh            # 默认装到两个工具（存在哪个装哪个）
#   ./install.sh claude     # 只装 Claude Code  → ~/.claude/skills/
#   ./install.sh codex      # 只装 Codex        → ${CODEX_HOME:-~/.codex}/skills/
#   ./install.sh both       # 两个都装
# 也支持远程一行安装：
#   curl -fsSL https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.sh | bash -s -- both
set -euo pipefail

REPO_URL="https://github.com/Buxiulei/nbdpsy-skills.git"
SKILLS=(seo-artical-creator xiaohongshu-creator)
TARGET="${1:-both}"

# 定位 skill 源目录：脚本同级有 skill 目录则用本地；否则临时 clone（支持 curl | bash）
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -z "${SRC:-}" ] || [ ! -d "$SRC/${SKILLS[0]}" ]; then
  TMP="$(mktemp -d)"
  echo "→ 本地未找到 skill 目录，临时克隆 $REPO_URL ..."
  git clone --depth 1 "$REPO_URL" "$TMP/repo" >/dev/null 2>&1
  SRC="$TMP/repo"
fi

install_to () {
  local dest="$1" label="$2"
  mkdir -p "$dest"
  echo "→ 安装到 $label（$dest）"
  for s in "${SKILLS[@]}"; do
    rm -rf "$dest/$s"
    cp -R "$SRC/$s" "$dest/$s"
    echo "  ✓ $s"
  done
}

case "$TARGET" in
  claude) install_to "$HOME/.claude/skills" "Claude Code" ;;
  codex)  install_to "${CODEX_HOME:-$HOME/.codex}/skills" "Codex" ;;
  both)
    install_to "$HOME/.claude/skills" "Claude Code"
    install_to "${CODEX_HOME:-$HOME/.codex}/skills" "Codex"
    ;;
  *) echo "用法: install.sh [claude|codex|both]"; exit 1 ;;
esac

cat <<'EOF'

完成 ✓ 重启 / 重新加载工具后即可使用：
  · seo-artical-creator —— 写 SEO/GEO 心理科普 pillar 长文
  · xiaohongshu-creator —— 把长文拆成小红书图文笔记 + 配图提示词

提示：这两个 skill 为 NBDpsy 定制（绑定其品牌话术、合规红线与数据库结构），
他用请先按自己项目改造 SKILL.md 中的品牌/数据库/发布部分。
EOF

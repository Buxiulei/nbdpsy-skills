#!/usr/bin/env bash
# NBDpsy skills 一键安装（Linux/macOS）。用法: ./install.sh [claude|codex|agents|all]（默认 all）
# 远程: curl -fsSL https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.sh | bash
set -euo pipefail
REPO_URL="https://github.com/Buxiulei/nbdpsy-skills.git"
SKILLS=(seo-artical-creator xiaohongshu-creator text-to-video content-reviewer content-pipeline)
TARGET="${1:-all}"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -z "${SRC:-}" ] || [ ! -d "$SRC/${SKILLS[0]}" ]; then
  TMP="$(mktemp -d)"; echo "→ 临时克隆 $REPO_URL ..."
  git clone --depth 1 "$REPO_URL" "$TMP/repo" >/dev/null 2>&1; SRC="$TMP/repo"
fi

copy_to () {  # copy_to <dest> <label>
  mkdir -p "$1"; echo "→ 安装到 $2（$1）"
  for s in "${SKILLS[@]}"; do rm -rf "${1:?}/$s"; cp -R "$SRC/$s" "$1/$s"; echo "  ✓ $s"; done
}
link_codex () {  # ~/.codex/skills/<s> -> ~/.agents/skills/<s>
  local dest="${CODEX_HOME:-$HOME/.codex}/skills"; mkdir -p "$dest"
  echo "→ 链接 Codex 旧路径（$dest → ~/.agents/skills）"
  for s in "${SKILLS[@]}"; do rm -rf "${dest:?}/$s"; ln -s "$HOME/.agents/skills/$s" "$dest/$s"; done
}

case "$TARGET" in
  claude) copy_to "$HOME/.claude/skills" "Claude Code" ;;
  agents) copy_to "$HOME/.agents/skills" "Agent 标准目录" ;;
  codex)  copy_to "$HOME/.agents/skills" "Agent 标准目录"; link_codex ;;
  all)    copy_to "$HOME/.claude/skills" "Claude Code"
          copy_to "$HOME/.agents/skills" "Agent 标准目录"; link_codex ;;
  *) echo "用法: install.sh [claude|codex|agents|all]"; exit 1 ;;
esac

echo
echo "完成 ✓ 下一步（首次必跑）："
echo "  python3 \"$SRC/setup.py\"   # 检测系统装依赖 + 凭据向导"

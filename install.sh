#!/usr/bin/env bash
# NBDpsy skills 一键安装（Linux/macOS）。用法: ./install.sh [claude|codex|agents|all] [--skills-only]（默认 all；--skills-only 跳过自动装依赖）
# 远程: curl -fsSL https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.sh | bash
set -euo pipefail
REPO_URL="https://github.com/Buxiulei/nbdpsy-skills.git"
SKILLS=(nbdpsy-seo-artical-creator nbdpsy-xiaohongshu-creator nbdpsy-text-to-video nbdpsy-youtube-transport nbdpsy-content-reviewer nbdpsy-content-pipeline nbdpsy-guide)

SKILLS_ONLY=0
TARGET=""
for arg in "$@"; do
  case "$arg" in
    --skills-only) SKILLS_ONLY=1 ;;
    *) [ -z "$TARGET" ] && TARGET="$arg" ;;
  esac
done
TARGET="${TARGET:-all}"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -z "${SRC:-}" ] || [ ! -d "$SRC/${SKILLS[0]}" ]; then
  TMP="$(mktemp -d)"; echo "→ 临时克隆 $REPO_URL ..."
  git clone --depth 1 "$REPO_URL" "$TMP/repo" >/dev/null 2>&1; SRC="$TMP/repo"
fi

# 旧版（无 nbdpsy- 前缀）skill 名，安装时顺带清理，防新旧并存重复触发
LEGACY_SKILLS=(seo-artical-creator xiaohongshu-creator text-to-video content-reviewer content-pipeline)

copy_to () {  # copy_to <dest> <label>
  mkdir -p "$1"; echo "→ 安装到 $2（$1）"
  for s in "${LEGACY_SKILLS[@]}"; do
    [ -e "${1:?}/$s" ] && { rm -rf "${1:?}/$s"; echo "  ✗ 清理旧名 $s"; }
  done
  for s in "${SKILLS[@]}"; do rm -rf "${1:?}/$s"; cp -R "$SRC/$s" "$1/$s"; echo "  ✓ $s"; done
}
link_codex () {  # ~/.codex/skills/<s> -> ~/.agents/skills/<s>
  local dest="${CODEX_HOME:-$HOME/.codex}/skills"; mkdir -p "$dest"
  echo "→ 链接 Codex 旧路径（$dest → ~/.agents/skills）"
  for s in "${LEGACY_SKILLS[@]}"; do rm -rf "${dest:?}/$s"; done
  for s in "${SKILLS[@]}"; do rm -rf "${dest:?}/$s"; ln -s "$HOME/.agents/skills/$s" "$dest/$s"; done
}

case "$TARGET" in
  claude) copy_to "$HOME/.claude/skills" "Claude Code" ;;
  agents) copy_to "$HOME/.agents/skills" "Agent 标准目录" ;;
  codex)  copy_to "$HOME/.agents/skills" "Agent 标准目录"; link_codex ;;
  all)    copy_to "$HOME/.claude/skills" "Claude Code"
          copy_to "$HOME/.agents/skills" "Agent 标准目录"; link_codex ;;
  *) echo "用法: install.sh [claude|codex|agents|all] [--skills-only]"; exit 1 ;;
esac

echo
echo "完成 ✓ 正在自动安装依赖 + 检测凭据..."
if [ "$SKILLS_ONLY" = "1" ] || [ "${NBDPSY_SKIP_SETUP:-}" = "1" ]; then
  echo "已跳过（--skills-only）。如需稍后配置：python3 \"$SRC/setup.py\""
elif command -v python3 >/dev/null 2>&1; then
  if [ -t 0 ]; then
    python3 "$SRC/setup.py" || true
  else
    python3 "$SRC/setup.py" --yes || true
  fi
  echo "如报缺凭据：找管理员要「凭据配置包」，然后 python3 nbdpsy_common.py secret import <文件> 一键导入"
else
  echo "未检测到 python3，请先安装 Python 3.9+，再手动运行：python3 \"$SRC/setup.py\""
fi

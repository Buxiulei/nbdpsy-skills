#!/usr/bin/env bash
# NBDpsy skills 一键安装（Linux/macOS）。用法: ./install.sh [claude|codex|agents|all] [--skills-only|--check|--force]
#   默认 all；--skills-only 跳过自动装依赖；--check 只比对真源与安装副本不写盘；--force 无视安装漂移强行覆盖
# 远程: curl -fsSL https://raw.githubusercontent.com/Buxiulei/nbdpsy-skills/master/install.sh | bash
set -euo pipefail
REPO_URL="https://github.com/Buxiulei/nbdpsy-skills.git"
SKILLS=(nbdpsy-seo-artical-creator nbdpsy-xiaohongshu-creator nbdpsy-text-to-video nbdpsy-youtube-transport nbdpsy-fuwuhao-operator nbdpsy-content-reviewer nbdpsy-content-teardown nbdpsy-content-pipeline nbdpsy-guide nbdpsy-strategy-report)

SKILLS_ONLY=0
CHECK_ONLY=0
FORCE=0
TARGET=""
for arg in "$@"; do
  case "$arg" in
    --skills-only) SKILLS_ONLY=1 ;;
    --check) CHECK_ONLY=1 ;;
    --force) FORCE=1 ;;
    *) [ -z "$TARGET" ] && TARGET="$arg" ;;
  esac
done
TARGET="${TARGET:-all}"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
SRC_KIND="local-repo"
if [ -z "${SRC:-}" ] || [ ! -d "$SRC/${SKILLS[0]}" ]; then
  TMP="$(mktemp -d)"; echo "→ 临时克隆 $REPO_URL ..."
  git clone --depth 1 "$REPO_URL" "$TMP/repo" >/dev/null 2>&1; SRC="$TMP/repo"; SRC_KIND="github-clone"
fi

# 旧版（无 nbdpsy- 前缀）skill 名，安装时顺带清理，防新旧并存重复触发
LEGACY_SKILLS=(seo-artical-creator xiaohongshu-creator text-to-video content-reviewer content-pipeline)

# ── 安装漂移检查 ─────────────────────────────────────────────────────────
# copy_to 是 rm -rf + cp -R：谁直接改了安装副本，下次安装会无声销毁。
# 装之前先比一遍，只有「副本被本地改过」才拦（真源更新是安装的正常理由，拦它就成了恒红闸门）。
DRIFT_TARGETS=()  # 本次要检查/安装的安装点，形如 路径=标签
case "$TARGET" in
  claude) DRIFT_TARGETS=("$HOME/.claude/skills=Claude Code") ;;
  agents|codex) DRIFT_TARGETS=("$HOME/.agents/skills=Agent 标准目录") ;;
  all) DRIFT_TARGETS=("$HOME/.claude/skills=Claude Code" "$HOME/.agents/skills=Agent 标准目录") ;;
  *) echo "用法: install.sh [claude|codex|agents|all] [--skills-only|--check|--force]"; exit 1 ;;
esac

CHECKER="$SRC/tools/check_install_drift.py"
run_drift_check () {  # run_drift_check [--gate]；回显退出码，0 一致 / 1 有差异 / 2 有本地改动 / 3 查不了
  local args=() t
  for t in "${DRIFT_TARGETS[@]}"; do args+=(--dest "$t"); done
  # 概览固定报全部三处安装点（含本次不比对的），方便一眼看出哪处是旧安装
  args+=(--overview "$HOME/.claude/skills=Claude Code" --overview "$HOME/.agents/skills=Agent 标准目录")
  python3 "$CHECKER" --src "$SRC" \
    --skills "$(IFS=,; echo "${SKILLS[*]}")" "${args[@]}" "$@"
}
drift_check_available () {
  command -v python3 >/dev/null 2>&1 && [ -f "$CHECKER" ]
}

if [ "$CHECK_ONLY" = "1" ]; then
  if ! drift_check_available; then
    command -v python3 >/dev/null 2>&1 || echo "！跑不了漂移检查：缺 python3"
    [ -f "$CHECKER" ] || echo "！跑不了漂移检查：缺 $CHECKER"
    exit 3
  fi
  rc=0; run_drift_check || rc=$?
  exit "$rc"
fi

if [ "$FORCE" = "1" ]; then
  echo "→ --force：跳过安装漂移检查，安装副本里的本地改动会被直接覆盖"
elif ! drift_check_available; then
  echo "！跳过安装漂移检查（缺 python3 或 $CHECKER）——无法判断安装副本是否被本地改过"
else
  rc=0; run_drift_check --gate || rc=$?
  if [ "$rc" = "2" ]; then
    echo
    echo "已中止安装：先把上面的改动搬回真源（$SRC），或确认可丢弃后重跑 ./install.sh $TARGET --force"
    exit 2
  fi
fi
# ─────────────────────────────────────────────────────────────────────────

# 版本标记：每个安装目的地落一份 .nbdpsy-skills-install.json，供 doctor 上报本机装的是哪版
# 取值失败一律写 unknown、写盘失败只提示不中断——标记是锦上添花，装不上也得把 skill 装完
write_marker () {  # write_marker <dest>
  local dest="$1" ver commit now
  ver="$(grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$SRC/.claude-plugin/plugin.json" 2>/dev/null \
        | head -1 | sed 's/.*"\([^"]*\)"$/\1/')" || true
  [ -n "${ver:-}" ] || ver="unknown"
  commit="$(git -C "$SRC" rev-parse --short HEAD 2>/dev/null)" || true
  [ -n "${commit:-}" ] || commit="unknown"
  now="$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z 2>/dev/null)" || true
  [ -n "${now:-}" ] || now="unknown"
  if ( printf '{\n  "version": "%s",\n  "commit": "%s",\n  "installed_at": "%s",\n  "source": "%s"\n}\n' \
        "$ver" "$commit" "$now" "$SRC_KIND" > "$dest/.nbdpsy-skills-install.json" ) 2>/dev/null; then
    echo "  ✓ 版本标记 v$ver（$commit）"
  else
    echo "  ! 版本标记写入失败（不影响 skill 安装）"
  fi
}

copy_to () {  # copy_to <dest> <label>
  mkdir -p "$1"; echo "→ 安装到 $2（$1）"
  for s in "${LEGACY_SKILLS[@]}"; do
    [ -e "${1:?}/$s" ] && { rm -rf "${1:?}/$s"; echo "  ✗ 清理旧名 $s"; }
  done
  for s in "${SKILLS[@]}"; do rm -rf "${1:?}/$s"; cp -R "$SRC/$s" "$1/$s"; echo "  ✓ $s"; done
  write_marker "$1" || true
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
  *) echo "用法: install.sh [claude|codex|agents|all] [--skills-only|--check|--force]"; exit 1 ;;
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

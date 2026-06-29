#!/usr/bin/env bash
# 凭据解析 / 记录：按 ① 环境变量 → ② 项目 .env → ③ 用户级 secrets 文件 顺序解析。
# 用户级存储：~/.config/nbdpsy/secrets.env（chmod 600，在任何仓库之外，永不入库）。
# 设计意图：skill 运行到需要密钥时，先 ensure 探测缺失项 → 由 AI 向用户询问 → set 记录 → 之后 get 复用。
# 用法：
#   secrets.sh get   <KEY>            解析并打印值；找不到则 exit 1 并向 stderr 打 MISSING:<KEY>
#   secrets.sh set   <KEY> <VALUE>    记录到用户级 secrets 文件（覆盖同名旧值）
#   secrets.sh ensure <KEY> [KEY...]  打印仍缺失的 KEY（每行一个）；全部可解析则无输出、exit 0
# 可用环境变量覆盖路径：NBDPSY_SECRETS（存储文件）、NBDPSY_ENV（项目 .env）
set -uo pipefail

STORE="${NBDPSY_SECRETS:-$HOME/.config/nbdpsy/secrets.env}"
PROJ_ENV="${NBDPSY_ENV:-后端服务/管理后端/.env}"

read_from () {  # read_from <file> <KEY> → echo value / return 1
  [ -f "$1" ] || return 1
  local v
  v=$(grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d "\"'") || true
  [ -n "$v" ] && { printf '%s' "$v"; return 0; }
  return 1
}

resolve () {  # resolve <KEY> → echo value / return 1
  local k="$1"
  [ -n "${!k:-}" ] && { printf '%s' "${!k}"; return 0; }   # ① 环境变量
  read_from "$PROJ_ENV" "$k" && return 0                    # ② 项目 .env
  read_from "$STORE"    "$k" && return 0                    # ③ 用户级 secrets
  return 1
}

case "${1:-}" in
  get)
    [ $# -ge 2 ] || { echo "用法: secrets.sh get <KEY>" >&2; exit 2; }
    resolve "$2" || { echo "MISSING:$2" >&2; exit 1; } ;;
  set)
    [ $# -ge 3 ] || { echo "用法: secrets.sh set <KEY> <VALUE>" >&2; exit 2; }
    mkdir -p "$(dirname "$STORE")"; touch "$STORE"; chmod 600 "$STORE"
    grep -vE "^$2=" "$STORE" > "$STORE.tmp" 2>/dev/null || true
    mv "$STORE.tmp" "$STORE"
    printf '%s=%s\n' "$2" "$3" >> "$STORE"
    chmod 600 "$STORE"
    echo "✓ 已记录 $2 → $STORE（chmod 600，不会入库）" ;;
  ensure)
    shift
    for k in "$@"; do resolve "$k" >/dev/null 2>&1 || echo "$k"; done ;;
  *)
    echo "用法: secrets.sh {get <KEY> | set <KEY> <VALUE> | ensure <KEY...>}" >&2; exit 2 ;;
esac

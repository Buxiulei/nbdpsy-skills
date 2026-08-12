#!/usr/bin/env bash
# 分片并行渲染收口：render_sharded.sh <tpl.html> <out.mp4> <N>
#
# 预清帧目录 → 起 N 个 shard 并行渲 → 等全部退出 → 帧连续性校验 → 调 render_card.py 的 mux 路径。
# 路径基准与 render_card.py 一致：本脚本所在目录（不是 cwd）。每条视频独立工作目录、各带一份副本。
#
# N 的选法：一路 Chromium 逐帧渲染峰值可吃到数 GB 内存（EMDR 线 R15 有 7.1GB 被 OOM 杀的实例），
# 按内存而不是核数定 N，2-4 是安全区。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -lt 3 ]; then
  echo "用法：render_sharded.sh <tpl.html> <out.mp4> <N> [透传给 render_card.py 的参数…]" >&2
  echo "  例：render_sharded.sh tpl-basic.html out.mp4 4 --deterministic" >&2
  exit 2
fi
TPL="$1"; OUT="$2"; N="$3"; shift 3
PASS=("$@")   # 透传 --angle / --deterministic 等

if ! [[ "$N" =~ ^[0-9]+$ ]] || [ "$N" -lt 1 ]; then
  echo "❌ N 必须是 ≥1 的整数，收到「$N」" >&2
  exit 2
fi
[ -f "$HERE/$TPL" ] || { echo "❌ 模板不存在：$HERE/$TPL" >&2; exit 2; }

STEM="$(basename "$TPL")"; STEM="${STEM%.*}"
FRAMEDIR="$HERE/frames_$STEM"
LOGDIR="$FRAMEDIR/.shard-logs"

# 杀进程树：只杀 python 杀不掉它拉起的 node driver 与 Chromium
kill_tree() {
  local p="$1" sig="$2" c
  for c in $(pgrep -P "$p" 2>/dev/null || true); do kill_tree "$c" "$sig"; done
  kill "-$sig" "$p" 2>/dev/null || true
}

declare -a PIDS=()
on_interrupt() {
  trap - INT TERM
  echo >&2
  echo "⚠️ 收到中断，正在杀掉分片进程树…" >&2
  for p in "${PIDS[@]}"; do kill_tree "$p" TERM; done
  sleep 1
  for p in "${PIDS[@]}"; do kill_tree "$p" KILL; done
  exit 130
}

# ── 预清前先认锁：绝不清别人正在写的帧（R15） ──
mkdir -p "$FRAMEDIR"
shopt -s nullglob
for lk in "$FRAMEDIR"/.render.pid*; do
  pid="$(head -1 "$lk" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    echo "❌ 帧目录 frames_$STEM 已被 pid=$pid 的渲染持有（仍存活），拒绝预清。" >&2
    echo "   确认那个渲染确实废了，再 kill $pid 或删 $lk。" >&2
    exit 1
  fi
done
shopt -u nullglob

rm -f "$FRAMEDIR"/f*.png "$FRAMEDIR"/f*.jpg "$FRAMEDIR"/f*.jpeg "$FRAMEDIR"/.render.pid*
mkdir -p "$LOGDIR"
rm -f "$LOGDIR"/shard-*.log

# ── 起 N 片 ──
trap on_interrupt INT TERM
T0=$SECONDS
echo "▶ frames_$STEM：起 $N 片并行渲染"
for ((i = 1; i <= N; i++)); do
  python3 "$HERE/render_card.py" "$TPL" "$OUT" --shard "$i" "$N" ${PASS[@]+"${PASS[@]}"} \
    >"$LOGDIR/shard-$i.log" 2>&1 &
  PIDS+=("$!")
done

# ── 等全部退出，任一非零则整体失败 ──
FAILED=""
for ((i = 1; i <= N; i++)); do
  if ! wait "${PIDS[$((i - 1))]}"; then
    FAILED="$FAILED $i"
  fi
done
trap - INT TERM

for ((i = 1; i <= N; i++)); do
  el="$(sed -n 's/.*elapsed=\([0-9.]*\).*/\1/p' "$LOGDIR/shard-$i.log" | tail -1)"
  rg="$(sed -n 's/.*range=\([0-9]*:[0-9]*\).*/\1/p' "$LOGDIR/shard-$i.log" | tail -1)"
  printf '  第 %d/%d 片  帧[%s)  %ss\n' "$i" "$N" "${rg:-?}" "${el:-?}"
done

if [ -n "$FAILED" ]; then
  echo "❌ 分片渲染失败：第${FAILED// /、} 片（日志 $LOGDIR/shard-*.log）" >&2
  for i in $FAILED; do echo "--- shard-$i.log 末 15 行 ---" >&2; tail -15 "$LOGDIR/shard-$i.log" >&2; done
  exit 1
fi

# ── 各片报的总帧数必须一致：不一致＝模板 TOTAL 不确定，帧域对不齐，成片必错 ──
TOTALS="$(sed -n 's/.*total_frames=\([0-9]*\).*/\1/p' "$LOGDIR"/shard-*.log | sort -u)"
if [ "$(printf '%s\n' "$TOTALS" | grep -c .)" -ne 1 ]; then
  echo "❌ 各分片报的总帧数不一致（$(printf '%s' "$TOTALS" | tr '\n' ' ')）——模板 TOTAL 不确定，禁止出片。" >&2
  exit 1
fi

# ── 帧连续性校验 → 收口混音 ──
python3 "$HERE/render_card.py" "$TPL" --verify-frames --expect "$TOTALS"
python3 "$HERE/render_card.py" "$TPL" "$OUT" --mux-only

echo "⏱ 总耗时 $((SECONDS - T0))s（$N 片并行，共 $TOTALS 帧）"

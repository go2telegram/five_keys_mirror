#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

# 1) Бот (Python)
if pgrep -f "python.*run.py" >/dev/null; then
  echo "[BOT] уже запущен"
else
  echo "[BOT] стартуем..."
  nohup python3 "$BASE_DIR/run.py" > "$LOG_DIR/bot.log" 2>&1 &
  echo "[BOT] PID $!"
fi

# 2) LocalTunnel (если нужен на VPS; можно отключить)
if pgrep -f "node.*tunnel.js" >/dev/null; then
  echo "[LT ] уже запущен"
else
  echo "[LT ] стартуем..."
  (cd "$BASE_DIR/tunnel" && nohup node tunnel.js > "$LOG_DIR/lt.log" 2>&1 &)
  echo "[LT ] PID $!"
fi

echo "[INFO] Логи: tail -f $LOG_DIR/bot.log $LOG_DIR/lt.log"

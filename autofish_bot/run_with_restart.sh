#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

source autofish_bot/venv/bin/activate

LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p $LOG_DIR

PID_FILE="$LOG_DIR/autofish.pid"
LOG_FILE="$LOG_DIR/binance_live.log"
ERROR_LOG_FILE="$LOG_DIR/binance_live_error.log"

RESTART_DELAY=10
MAX_RESTARTS=5
restart_count=0

cleanup() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') 收到退出信号，清理中..."
    rm -f "$PID_FILE"
    exit 0
}

trap cleanup SIGINT SIGTERM

if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE")
    if ps -p $old_pid > /dev/null 2>&1; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 程序已在运行 (PID: $old_pid)"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

echo $$ > "$PID_FILE"

echo "============================================================"
echo "Autofish Binance Live Trading"
echo "============================================================"
echo "启动时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "日志文件: $LOG_FILE"
echo "错误日志: $ERROR_LOG_FILE"
echo "PID 文件: $PID_FILE"
echo "============================================================"

while true; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') 启动程序..."
    
    python3 -m autofish_bot.binance_live --symbol BTCUSDT --testnet >> "$LOG_FILE" 2>> "$ERROR_LOG_FILE"
    
    EXIT_CODE=$?
    echo "$(date '+%Y-%m-%d %H:%M:%S') 程序退出，退出码: $EXIT_CODE"
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 正常退出，停止重启循环"
        break
    fi
    
    restart_count=$((restart_count + 1))
    
    if [ $restart_count -ge $MAX_RESTARTS ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 重启次数超过上限 ($MAX_RESTARTS)，停止重启"
        break
    fi
    
    echo "$(date '+%Y-%m-%d %H:%M:%S') $RESTART_DELAY 秒后重启... (重启次数: $restart_count/$MAX_RESTARTS)"
    sleep $RESTART_DELAY
done

rm -f "$PID_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S') 程序结束"

#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$LOG_DIR/autofish.pid"

mkdir -p "$LOG_DIR"

if [ -f "$PID_FILE" ]; then
    old_pid=$(cat "$PID_FILE")
    if ps -p $old_pid > /dev/null 2>&1; then
        echo "程序已在运行 (PID: $old_pid)"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

echo "启动 Autofish Binance Live Trading..."

nohup "$SCRIPT_DIR/run_with_restart.sh" > /dev/null 2>&1 &

sleep 2

if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE")
    echo "启动成功 (PID: $pid)"
    echo "日志文件: $LOG_DIR/binance_live.log"
else
    echo "启动失败，请检查日志"
    exit 1
fi

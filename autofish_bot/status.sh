#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$LOG_DIR/autofish.pid"

echo "============================================================"
echo "Autofish Binance Live Trading - 状态"
echo "============================================================"

if [ ! -f "$PID_FILE" ]; then
    echo "状态: 未运行"
    exit 0
fi

pid=$(cat "$PID_FILE")

if ! ps -p $pid > /dev/null 2>&1; then
    echo "状态: 未运行 (PID 文件存在但进程不存在)"
    rm -f "$PID_FILE"
    exit 0
fi

echo "状态: 运行中"
echo "PID: $pid"

start_time=$(ps -p $pid -o lstart= | xargs)
echo "启动时间: $start_time"

cpu_usage=$(ps -p $pid -o %cpu= | xargs)
echo "CPU 使用率: ${cpu_usage}%"

mem_usage=$(ps -p $pid -o %mem= | xargs)
echo "内存使用率: ${mem_usage}%"

if [ -f "$LOG_DIR/binance_live.log" ]; then
    log_size=$(ls -lh "$LOG_DIR/binance_live.log" | awk '{print $5}')
    echo "日志大小: $log_size"
    
    echo ""
    echo "最近日志:"
    echo "------------------------------------------------------------"
    tail -10 "$LOG_DIR/binance_live.log"
fi

echo "============================================================"

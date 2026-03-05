#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$LOG_DIR/autofish.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "程序未运行"
    exit 0
fi

pid=$(cat "$PID_FILE")

if ! ps -p $pid > /dev/null 2>&1; then
    echo "程序未运行 (PID 文件存在但进程不存在)"
    rm -f "$PID_FILE"
    exit 0
fi

echo "停止程序 (PID: $pid)..."

kill $pid

for i in {1..10}; do
    if ! ps -p $pid > /dev/null 2>&1; then
        echo "程序已停止"
        rm -f "$PID_FILE"
        exit 0
    fi
    sleep 1
done

echo "程序未响应，强制终止..."
kill -9 $pid 2>/dev/null
rm -f "$PID_FILE"
echo "程序已强制终止"

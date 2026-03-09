#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$LOG_DIR/binance_live_run.pid"
PARAMS_FILE="$LOG_DIR/binance_live_run.params"
LOG_FILE="$LOG_DIR/binance_live.log"
ERROR_LOG_FILE="$LOG_DIR/binance_live_error.log"

RESTART_DELAY=10
MAX_RESTARTS=5

# 默认参数
SYMBOL="BTCUSDT"
TESTNET="--testnet"
DECAY_FACTOR=""

# 解析命令行参数
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --symbol)
                SYMBOL="$2"
                shift 2
                ;;
            --testnet)
                TESTNET="--testnet"
                shift
                ;;
            --no-testnet)
                TESTNET="--no-testnet"
                shift
                ;;
            --decay-factor)
                DECAY_FACTOR="--decay-factor $2"
                shift 2
                ;;
            start|stop|restart|status|_run)
                COMMAND="$1"
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
}

mkdir -p "$LOG_DIR"

run_with_restart() {
    echo $$ > "$PID_FILE"
    
    # 保存启动参数到文件
    echo "SYMBOL=$SYMBOL" > "$PARAMS_FILE"
    echo "TESTNET=$TESTNET" >> "$PARAMS_FILE"
    echo "DECAY_FACTOR=$DECAY_FACTOR" >> "$PARAMS_FILE"
    
    echo "============================================================"
    echo "Autofish V2 Binance Live Trading"
    echo "============================================================"
    echo "启动时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "交易对: $SYMBOL"
    echo "网络: $([ "$TESTNET" = "--testnet" ] && echo "测试网" || echo "主网")"
    echo "日志文件: $LOG_FILE"
    echo "错误日志: $ERROR_LOG_FILE"
    echo "PID 文件: $PID_FILE"
    echo "参数文件: $PARAMS_FILE"
    echo "============================================================"
    
    restart_count=0
    python_pid=""
    stopping=false
    
    cleanup() {
        echo "$(date '+%Y-%m-%d %H:%M:%S') 收到退出信号，清理中..."
        stopping=true
        
        # 先停止 Python 子进程
        if [ -n "$python_pid" ] && ps -p $python_pid > /dev/null 2>&1; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') 停止 Python 进程 (PID: $python_pid)..."
            kill -TERM $python_pid 2>/dev/null
            
            # 等待 Python 进程退出
            for i in {1..10}; do
                if ! ps -p $python_pid > /dev/null 2>&1; then
                    echo "$(date '+%Y-%m-%d %H:%M:%S') Python 进程已停止"
                    break
                fi
                sleep 1
            done
            
            # 如果还在运行，强制终止
            if ps -p $python_pid > /dev/null 2>&1; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') Python 进程未响应，强制终止..."
                kill -KILL $python_pid 2>/dev/null
            fi
        fi
        
        rm -f "$PID_FILE"
        rm -f "$PARAMS_FILE"
        echo "$(date '+%Y-%m-%d %H:%M:%S') 清理完成"
        exit 0
    }
    
    trap cleanup SIGINT SIGTERM
    
    source venv/bin/activate
    
    while true; do
        echo "$(date '+%Y-%m-%d %H:%M:%S') 启动程序..."
        
        python3 binance_live.py --symbol "$SYMBOL" $TESTNET $DECAY_FACTOR 2>> "$ERROR_LOG_FILE" &
        python_pid=$!
        wait $python_pid
        
        EXIT_CODE=$?
        python_pid=""
        
        # 如果正在停止，直接退出
        if [ "$stopping" = true ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') 正在停止，退出重启循环"
            break
        fi
        
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
    rm -f "$PARAMS_FILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') 程序结束"
}

start_program() {
    if [ -f "$PID_FILE" ]; then
        old_pid=$(cat "$PID_FILE")
        if ps -p $old_pid > /dev/null 2>&1; then
            echo "程序已在运行 (PID: $old_pid)"
            exit 1
        else
            rm -f "$PID_FILE"
        fi
    fi
    
    echo "启动 Autofish V2 Binance Live Trading..."
    echo "  交易对: $SYMBOL"
    echo "  网络: $([ "$TESTNET" = "--testnet" ] && echo "测试网" || echo "主网")"
    
    # 传递参数给后台进程
    nohup "$SCRIPT_DIR/binance_live_run.sh" _run --symbol "$SYMBOL" $TESTNET $DECAY_FACTOR > /dev/null 2>&1 &
    
    sleep 2
    
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
        echo "启动成功 (PID: $pid)"
        echo "日志文件: $LOG_FILE"
    else
        echo "启动失败，请检查日志"
        exit 1
    fi
}

stop_program() {
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
    
    # 发送 SIGTERM 信号，进程组
    kill -TERM $pid 2>/dev/null
    
    
    # 磭待进程退出
    for i in {1..15}; do
        if ! ps -p $pid > /dev/null 2>&1; then
            echo "程序已停止"
            rm -f "$PID_FILE"
            exit 0
        fi
        sleep 1
    done
    
    # 如果进程还在运行，强制终止
    echo "程序未响应，强制终止..."
    kill -KILL $pid 2>/dev/null
    pkill -f "binance_live.py" 2>/dev/null
    pkill -f "binance_live_run.sh" 2>/dev/null
    
    
    rm -f "$PID_FILE"
    echo "程序已强制终止"
}

restart_program() {
    echo "重启程序..."
    
    # 从参数文件读取保存的参数
    if [ -f "$PARAMS_FILE" ]; then
        echo "从参数文件读取启动参数..."
        source "$PARAMS_FILE"
    fi
    
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
        if ps -p $pid > /dev/null 2>&1; then
            echo "停止程序 (PID: $pid)..."
            kill -TERM $pid 2>/dev/null
            
            for i in {1..10}; do
                if ! ps -p $pid > /dev/null 2>&1; then
                    echo "程序已停止"
                    rm -f "$PID_FILE"
                    break
                fi
                sleep 1
            done
            
            if ps -p $pid > /dev/null 2>&1; then
                echo "程序未响应，强制终止..."
                kill -KILL $pid 2>/dev/null
                pkill -f "binance_live.py" 2>/dev/null
                pkill -f "binance_live_run.sh" 2>/dev/null
                rm -f "$PID_FILE"
            fi
            
            sleep 2
        else
            echo "程序未运行，直接启动..."
            rm -f "$PID_FILE"
        fi
    else
        echo "程序未运行，直接启动..."
    fi
    
    start_program
}

status_program() {
    echo "============================================================"
    echo "Autofish V2 Binance Live Trading - 状态"
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
    
    # 显示保存的参数
    if [ -f "$PARAMS_FILE" ]; then
        echo ""
        echo "启动参数:"
        source "$PARAMS_FILE"
        echo "  交易对: $SYMBOL"
        echo "  网络: $([ "$TESTNET" = "--testnet" ] && echo "测试网" || echo "主网")"
        echo "  衰减因子: ${DECAY_FACTOR:-默认}"
    fi
    
    start_time=$(ps -p $pid -o lstart= | xargs)
    echo ""
    echo "启动时间: $start_time"
    
    cpu_usage=$(ps -p $pid -o %cpu= | xargs)
    echo "CPU 使用率: ${cpu_usage}%"
    
    mem_usage=$(ps -p $pid -o %mem= | xargs)
    echo "内存使用率: ${mem_usage}%"
    
    if [ -f "$LOG_FILE" ]; then
        log_size=$(ls -lh "$LOG_FILE" | awk '{print $5}')
        echo "日志大小: $log_size"
        
        echo ""
        echo "最近日志:"
        echo "------------------------------------------------------------"
        tail -10 "$LOG_FILE"
    fi
    
    echo "============================================================"
}

usage() {
    echo "用法: $0 [选项] {start|stop|restart|status}"
    echo ""
    echo "命令:"
    echo "  start    启动程序"
    echo "  stop     停止程序"
    echo "  restart  重启程序"
    echo "  status   查看状态 (默认)"
    echo ""
    echo "选项:"
    echo "  --symbol SYMBOL      交易对 (默认: BTCUSDT)"
    echo "  --testnet            使用测试网 (默认)"
    echo "  --no-testnet         使用主网"
    echo "  --decay-factor N     衰减因子 (默认: 0.5)"
    echo ""
    echo "示例:"
    echo "  $0 start                              # 启动 BTCUSDT 测试网"
    echo "  $0 --symbol ETHUSDT start             # 启动 ETHUSDT 测试网"
    echo "  $0 --symbol BTCUSDT --no-testnet start # 启动 BTCUSDT 主网"
    echo "  $0 --symbol ETHUSDT --decay-factor 1.0 start  # 启动 ETHUSDT 保守策略"
    echo "  $0 stop                               # 停止程序"
    echo "  $0 restart                            # 重启程序"
    echo "  $0 status                             # 查看状态"
    echo "  $0                                    # 查看状态 (默认)"
}

# 解析参数
parse_args "$@"

case "${COMMAND:-status}" in
    start)
        start_program
        ;;
    stop)
        stop_program
        ;;
    restart)
        restart_program
        ;;
    status)
        status_program
        ;;
    _run)
        shift
        parse_args "$@"
        run_with_restart
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        echo "未知命令: $1"
        usage
        exit 1
        ;;
esac

#!/bin/bash
# Autofish Web 服务管理脚本
#
# 用法:
#   ./web_manager.sh start <service>     - 启动单个服务
#   ./web_manager.sh stop <service>      - 停止单个服务
#   ./web_manager.sh restart <service>   - 重启单个服务
#   ./web_manager.sh status <service>    - 查看单个服务状态
#   ./web_manager.sh start-all           - 启动所有 Web 服务
#   ./web_manager.sh stop-all            - 停止所有 Web 服务
#   ./web_manager.sh restart-all         - 重启所有 Web 服务
#   ./web_manager.sh status-all          - 查看所有 Web 服务状态
#   ./web_manager.sh start-db            - 启动所有数据库查看服务
#   ./web_manager.sh stop-db             - 停止所有数据库查看服务
#   ./web_manager.sh status-db           - 查看所有数据库查看服务状态
#   ./web_manager.sh logs <service>      - 查看服务日志
#
# Web 服务列表:
#   visualizer - 行情可视化 (端口 5001)
#   backtest   - 回测系统 (端口 5002)
#   live       - 实盘交易 (端口 5003)
#
# 数据库查看服务列表:
#   db-live    - 实盘数据库 live_trading.db (端口 5010)
#   db-backtest- 回测数据库 test_results.db (端口 5011)
#   db-klines  - K线数据库 klines.db (端口 5012)

set -e

# 项目目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$SCRIPT_DIR/logs"
DB_DIR="$SCRIPT_DIR/database"

# venv 环境（可选）
VENV_DIR="$SCRIPT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python3"

# 默认使用系统 python3（venv 损坏时跳过）
PYTHON="python3"

# 创建 logs 目录
mkdir -p "$LOGS_DIR"

# ==================== Web 服务管理 ====================

# 获取服务脚本文件
get_service_script() {
    local service="$1"
    case "$service" in
        visualizer) echo "market_status_visualizer.py" ;;
        backtest)   echo "binance_backtest_web.py" ;;
        live)       echo "binance_live_web.py" ;;
        *)          echo "" ;;
    esac
}

# 获取服务命令参数
get_service_cmd() {
    local service="$1"
    case "$service" in
        visualizer) echo "--server" ;;
        backtest)   echo "serve" ;;
        live)       echo "serve" ;;
        *)          echo "" ;;
    esac
}

get_service_port() {
    local service="$1"
    case "$service" in
        visualizer) echo "5001" ;;
        backtest)   echo "5002" ;;
        live)       echo "5003" ;;
        *)          echo "" ;;
    esac
}

# 检查 Web 服务名是否有效
validate_service() {
    local service="$1"
    local script=$(get_service_script "$service")
    if [ -z "$script" ]; then
        echo "错误: 无效的服务名 '$service'"
        echo "可用服务: visualizer, backtest, live"
        exit 1
    fi
}

# ==================== 数据库服务管理 ====================

# 获取数据库文件路径
get_db_path() {
    local service="$1"
    case "$service" in
        db-live)    echo "$DB_DIR/live_trading.db" ;;
        db-backtest)echo "$DB_DIR/test_results.db" ;;
        db-klines)  echo "$DB_DIR/klines.db" ;;
        *)          echo "" ;;
    esac
}

# 获取数据库服务端口
get_db_port() {
    local service="$1"
    case "$service" in
        db-live)    echo "5010" ;;
        db-backtest)echo "5011" ;;
        db-klines)  echo "5012" ;;
        *)          echo "" ;;
    esac
}

# 获取数据库服务描述
get_db_desc() {
    local service="$1"
    case "$service" in
        db-live)    echo "实盘数据库" ;;
        db-backtest)echo "回测数据库" ;;
        db-klines)  echo "K线数据库" ;;
        *)          echo "" ;;
    esac
}

# 检查数据库服务名是否有效
validate_db_service() {
    local service="$1"
    local db_path=$(get_db_path "$service")
    if [ -z "$db_path" ]; then
        echo "错误: 无效的数据库服务名 '$service'"
        echo "可用服务: db-live, db-backtest, db-klines"
        exit 1
    fi
}

# ==================== 通用函数 ====================

# 获取 PID 文件路径
get_pid_file() {
    local service="$1"
    echo "$LOGS_DIR/$service.pid"
}

# 获取日志文件路径
get_log_file() {
    local service="$1"
    echo "$LOGS_DIR/$service.log"
}

# 检查服务是否运行
is_running() {
    local service="$1"
    local pid_file=$(get_pid_file "$service")

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# ==================== Web 服务操作 ====================

# 启动 Web 服务
start_service() {
    local service="$1"
    validate_service "$service"

    local pid_file=$(get_pid_file "$service")
    local log_file=$(get_log_file "$service")
    local script=$(get_service_script "$service")
    local cmd=$(get_service_cmd "$service")
    local port=$(get_service_port "$service")

    if is_running "$service"; then
        echo "服务 $service 已在运行 (端口 $port)"
        return 0
    fi

    echo "启动 $service (端口 $port)..."

    cd "$SCRIPT_DIR"
    nohup "$PYTHON" "$script" "$cmd" --port "$port" >> "$log_file" 2>&1 &
    local pid=$!
    echo "$pid" > "$pid_file"

    sleep 1
    if is_running "$service"; then
        echo "服务 $service 启动成功 (PID: $pid)"
        echo "访问地址: http://localhost:$port"
    else
        echo "服务 $service 启动失败，请查看日志:"
        echo "  tail -50 $log_file"
        exit 1
    fi
}

# 停止 Web 服务
stop_service() {
    local service="$1"
    validate_service "$service"

    local pid_file=$(get_pid_file "$service")
    local port=$(get_service_port "$service")

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "停止 $service (PID: $pid)..."
            kill "$pid"
            sleep 1

            # 强制终止如果还在运行
            if ps -p "$pid" > /dev/null 2>&1; then
                echo "强制终止 $service..."
                kill -9 "$pid"
            fi
        fi
        rm -f "$pid_file"
        echo "服务 $service 已停止"
    else
        echo "服务 $service 未运行"
    fi
}

# 查看 Web 服务状态
status_service() {
    local service="$1"
    validate_service "$service"

    local pid_file=$(get_pid_file "$service")
    local port=$(get_service_port "$service")

    if is_running "$service"; then
        local pid=$(cat "$pid_file")
        echo "$service: 运行中 (PID: $pid, 端口: $port)"
        echo "  访问: http://localhost:$port"
        echo "  日志: $(get_log_file $service)"
    else
        if [ -f "$pid_file" ]; then
            echo "$service: 已停止 (PID 文件存在但进程已终止)"
        else
            echo "$service: 未运行"
        fi
    fi
}

# ==================== 数据库服务操作 ====================

# 启动数据库服务
start_db_service() {
    local service="$1"
    validate_db_service "$service"

    local pid_file=$(get_pid_file "$service")
    local log_file=$(get_log_file "$service")
    local db_path=$(get_db_path "$service")
    local port=$(get_db_port "$service")
    local desc=$(get_db_desc "$service")

    if is_running "$service"; then
        echo "服务 $service 已在运行 (端口 $port)"
        return 0
    fi

    if [ ! -f "$db_path" ]; then
        echo "错误: 数据库文件不存在: $db_path"
        exit 1
    fi

    echo "启动 $service - $desc (端口 $port)..."

    # 检查 sqlite_web 是否安装
    if ! command -v sqlite_web &> /dev/null && ! python3 -m sqlite_web --help &> /dev/null; then
        echo "错误: sqlite_web 未安装，请运行: pip install sqlite-web"
        exit 1
    fi

    cd "$SCRIPT_DIR"
    nohup python3 -m sqlite_web "$db_path" --port "$port" >> "$log_file" 2>&1 &
    local pid=$!
    echo "$pid" > "$pid_file"

    sleep 1
    if is_running "$service"; then
        echo "服务 $service 启动成功 (PID: $pid)"
        echo "访问地址: http://localhost:$port"
    else
        echo "服务 $service 启动失败，请查看日志:"
        echo "  tail -50 $log_file"
        exit 1
    fi
}

# 停止数据库服务
stop_db_service() {
    local service="$1"
    validate_db_service "$service"

    local pid_file=$(get_pid_file "$service")
    local port=$(get_db_port "$service")

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "停止 $service (PID: $pid)..."
            kill "$pid"
            sleep 1

            # 强制终止如果还在运行
            if ps -p "$pid" > /dev/null 2>&1; then
                echo "强制终止 $service..."
                kill -9 "$pid"
            fi
        fi
        rm -f "$pid_file"
        echo "服务 $service 已停止"
    else
        echo "服务 $service 未运行"
    fi
}

# 查看数据库服务状态
status_db_service() {
    local service="$1"
    validate_db_service "$service"

    local pid_file=$(get_pid_file "$service")
    local port=$(get_db_port "$service")
    local desc=$(get_db_desc "$service")
    local db_path=$(get_db_path "$service")

    if is_running "$service"; then
        local pid=$(cat "$pid_file")
        echo "$service: 运行中 ($desc, PID: $pid, 端口: $port)"
        echo "  访问: http://localhost:$port"
        echo "  数据库: $db_path"
    else
        if [ -f "$pid_file" ]; then
            echo "$service: 已停止 (PID 文件存在但进程已终止)"
        else
            echo "$service: 未运行 ($desc)"
        fi
    fi
}

# ==================== 批量操作 ====================

# 查看所有 Web 服务状态
status_all() {
    echo "=== Web 服务状态 ==="
    echo ""
    for service in visualizer backtest live; do
        status_service "$service"
        echo ""
    done
}

# 启动所有 Web 服务
start_all() {
    echo "启动所有 Web 服务..."
    for service in visualizer backtest live; do
        start_service "$service"
        echo ""
    done
    echo "所有 Web 服务已启动"
}

# 停止所有 Web 服务
stop_all() {
    echo "停止所有 Web 服务..."
    for service in visualizer backtest live; do
        stop_service "$service"
    done
    echo "所有 Web 服务已停止"
}

# 重启所有 Web 服务
restart_all() {
    echo "重启所有 Web 服务..."
    stop_all
    sleep 2
    start_all
}

# 查看所有数据库服务状态
status_db_all() {
    echo "=== 数据库查看服务状态 ==="
    echo ""
    for service in db-live db-backtest db-klines; do
        status_db_service "$service"
        echo ""
    done
}

# 启动所有数据库服务
start_db_all() {
    echo "启动所有数据库查看服务..."
    for service in db-live db-backtest db-klines; do
        start_db_service "$service"
        echo ""
    done
    echo "所有数据库查看服务已启动"
}

# 停止所有数据库服务
stop_db_all() {
    echo "停止所有数据库查看服务..."
    for service in db-live db-backtest db-klines; do
        stop_db_service "$service"
    done
    echo "所有数据库查看服务已停止"
}

# 重启所有数据库服务
restart_db_all() {
    echo "重启所有数据库查看服务..."
    stop_db_all
    sleep 1
    start_db_all
}

# 查看日志
logs_service() {
    local service="$1"
    local lines="${2:-50}"

    local log_file=$(get_log_file "$service")
    if [ -z "$log_file" ]; then
        echo "错误: 无效的服务名 '$service'"
        exit 1
    fi

    if [ -f "$log_file" ]; then
        echo "=== $service 日志 (最近 $lines 行) ==="
        tail -"$lines" "$log_file"
    else
        echo "日志文件不存在: $log_file"
    fi
}

# ==================== 主逻辑 ====================

case "$1" in
    start)
        start_service "$2"
        ;;
    stop)
        stop_service "$2"
        ;;
    restart)
        stop_service "$2"
        sleep 1
        start_service "$2"
        ;;
    status)
        status_service "$2"
        ;;
    start-all)
        start_all
        ;;
    stop-all)
        stop_all
        ;;
    restart-all)
        restart_all
        ;;
    status-all)
        status_all
        ;;
    start-db)
        start_db_all
        ;;
    stop-db)
        stop_db_all
        ;;
    restart-db)
        restart_db_all
        ;;
    status-db)
        status_db_all
        ;;
    logs)
        logs_service "$2" "$3"
        ;;
    *)
        echo "用法: $0 <command> [service]"
        echo ""
        echo "命令:"
        echo "  start <service>     - 启动单个 Web 服务"
        echo "  stop <service>      - 停止单个 Web 服务"
        echo "  restart <service>   - 重启单个 Web 服务"
        echo "  status <service>    - 查看单个 Web 服务状态"
        echo "  start-all           - 启动所有 Web 服务"
        echo "  stop-all            - 停止所有 Web 服务"
        echo "  restart-all         - 重启所有 Web 服务"
        echo "  status-all          - 查看所有 Web 服务状态"
        echo "  start-db            - 启动所有数据库查看服务"
        echo "  stop-db             - 停止所有数据库查看服务"
        echo "  restart-db          - 重启所有数据库查看服务"
        echo "  status-db           - 查看所有数据库查看服务状态"
        echo "  logs <service> [n]  - 查看服务日志 (默认 50 行)"
        echo ""
        echo "Web 服务:"
        echo "  visualizer - 行情可视化 (端口 5001)"
        echo "  backtest   - 回测系统 (端口 5002)"
        echo "  live       - 实盘交易 (端口 5003)"
        echo ""
        echo "数据库查看服务:"
        echo "  db-live    - 实盘数据库 live_trading.db (端口 5010)"
        echo "  db-backtest- 回测数据库 test_results.db (端口 5011)"
        echo "  db-klines  - K线数据库 klines.db (端口 5012)"
        exit 1
        ;;
esac
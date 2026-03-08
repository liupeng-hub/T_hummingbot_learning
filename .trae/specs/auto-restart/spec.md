# 程序后台运行与自动重启规范

## 概述

实现程序后台运行，并在意外退出后自动重启，确保交易程序持续运行。

## 方案对比

### 方案 1: systemd (推荐 - Linux)

**优点**:
- 系统级服务管理
- 自动重启
- 日志管理
- 开机自启

**缺点**:
- 仅适用于 Linux
- 需要 root 权限

### 方案 2: launchd (推荐 - macOS)

**优点**:
- 系统级服务管理
- 自动重启
- 日志管理
- 开机自启

**缺点**:
- 仅适用于 macOS

### 方案 3: supervisord

**优点**:
- 跨平台
- 进程管理
- 自动重启
- Web 管理界面

**缺点**:
- 需要额外安装

### 方案 4: PM2

**优点**:
- 跨平台
- Node.js 生态
- 自动重启
- 日志管理
- 监控面板

**缺点**:
- 需要 Node.js 环境

### 方案 5: Shell 脚本 + cron

**优点**:
- 简单
- 无需额外安装

**缺点**:
- 功能有限
- 无日志管理

## 推荐方案

### macOS: launchd

创建 `~/Library/LaunchAgents/com.autofish.binance.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.autofish.binance</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot/venv/bin/python3</string>
        <string>-m</string>
        <string>autofish_bot.binance_live</string>
        <string>--symbol</string>
        <string>BTCUSDT</string>
        <string>--testnet</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/liupeng/Documents/trae_projects/hummingbot_learning</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/liupeng/Documents/trae_projects/hummingbot_learning/logs/binance_live.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/liupeng/Documents/trae_projects/hummingbot_learning/logs/binance_live_error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot/venv/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

### Linux: systemd

创建 `/etc/systemd/system/autofish-binance.service`:

```ini
[Unit]
Description=Autofish Binance Live Trading
After=network.target

[Service]
Type=simple
User=liupeng
WorkingDirectory=/Users/liupeng/Documents/trae_projects/hummingbot_learning
ExecStart=/Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot/venv/bin/python3 -m autofish_bot.binance_live --symbol BTCUSDT --testnet
Restart=always
RestartSec=10
StandardOutput=append:/Users/liupeng/Documents/trae_projects/hummingbot_learning/logs/binance_live.log
StandardError=append:/Users/liupeng/Documents/trae_projects/hummingbot_learning/logs/binance_live_error.log

[Install]
WantedBy=multi-user.target
```

### supervisord

创建 `/etc/supervisor/conf.d/autofish-binance.conf`:

```ini
[program:autofish-binance]
command=/Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot/venv/bin/python3 -m autofish_bot.binance_live --symbol BTCUSDT --testnet
directory=/Users/liupeng/Documents/trae_projects/hummingbot_learning
user=liupeng
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=60
redirect_stderr=true
stdout_logfile=/Users/liupeng/Documents/trae_projects/hummingbot_learning/logs/binance_live.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=5
```

### Shell 脚本

创建 `run_with_restart.sh`:

```bash
#!/bin/bash

cd /Users/liupeng/Documents/trae_projects/hummingbot_learning
source autofish_bot/venv/bin/activate

LOG_DIR="logs"
mkdir -p $LOG_DIR

while true; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') Starting autofish..."
    python3 -m autofish_bot.binance_live --symbol BTCUSDT --testnet >> $LOG_DIR/binance_live.log 2>&1
    
    EXIT_CODE=$?
    echo "$(date '+%Y-%m-%d %H:%M:%S') Program exited with code $EXIT_CODE"
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') Normal exit, stopping restart loop"
        break
    fi
    
    echo "$(date '+%Y-%m-%d %H:%M:%S') Restarting in 10 seconds..."
    sleep 10
done
```

## 功能对比

| 功能 | launchd | systemd | supervisord | Shell 脚本 |
|------|---------|---------|-------------|-----------|
| 自动重启 | ✅ | ✅ | ✅ | ✅ |
| 开机自启 | ✅ | ✅ | ✅ | ❌ |
| 日志管理 | ✅ | ✅ | ✅ | ✅ |
| 进程监控 | ✅ | ✅ | ✅ | ❌ |
| Web 界面 | ❌ | ❌ | ✅ | ❌ |
| 跨平台 | ❌ | ❌ | ✅ | ✅ |

## 推荐选择

| 操作系统 | 推荐方案 |
|---------|----------|
| macOS | launchd |
| Linux | systemd |
| 跨平台 | supervisord |
| 简单场景 | Shell 脚本 |

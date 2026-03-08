# Checklist

## 日志目录

- [ ] 创建 `logs/` 目录
- [ ] 添加 `.gitignore` 规则

## launchd 配置 (macOS)

- [ ] 创建 `com.autofish.binance.plist` 文件
- [ ] 配置自动重启
- [ ] 配置日志输出
- [ ] 编写加载脚本
- [ ] 编写卸载脚本

## systemd 配置 (Linux)

- [ ] 创建 `autofish-binance.service` 文件
- [ ] 配置自动重启
- [ ] 配置日志输出
- [ ] 编写安装脚本

## Shell 脚本

- [ ] 创建 `run_with_restart.sh` 脚本
- [ ] 添加执行权限
- [ ] 测试重启逻辑

## 管理脚本

- [ ] 创建 `start.sh` 启动脚本
- [ ] 创建 `stop.sh` 停止脚本
- [ ] 创建 `status.sh` 状态检查脚本

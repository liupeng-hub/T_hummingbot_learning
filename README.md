# Hummingbot Learning

学习 Hummingbot 量化交易框架。

## 目录结构

```
hummingbot_learning/
├── docker-compose.yml    # Docker 配置
├── conf/                 # 配置文件目录
├── scripts/              # 策略脚本目录
├── logs/                 # 日志目录
└── data/                 # 数据目录
```

## 启动方式

```bash
# 启动 Hummingbot
cd /Users/liupeng/Documents/trae_projects/hummingbot_learning
docker-compose up -d

# 进入 Hummingbot 命令行
docker attach hummingbot_learning

# 退出（不停止容器）
# 按 Ctrl+P 然后 Ctrl+Q

# 停止容器
docker-compose down
```

## 学习目标

1. 熟悉 Hummingbot 基本操作
2. 研究 Pure Market Making 策略
3. 研究 Grid Strike 策略
4. 实现 autofish 策略

## 相关文档

- [Hummingbot 官方文档](https://hummingbot.org/)
- [GitHub 仓库](https://github.com/hummingbot/hummingbot)

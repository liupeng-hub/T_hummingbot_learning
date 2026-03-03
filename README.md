# Hummingbot Learning

学习 Hummingbot 量化交易框架。

## 目录结构

```
hummingbot_learning/
├── docker-compose.yml    # Docker 配置
├── conf/                 # 配置文件目录
├── scripts/              # 策略脚本目录
├── logs/                 # 日志目录
├── data/                 # 数据目录
├── .env                  # 环境变量配置
└── tests/
    └── realtime_simulator_api.py  # Autofish V1 实时模拟器
```

## 启动方式

```bash
# 启动 Hummingbot
docker-compose up -d

# 进入 Hummingbot 命令行
docker attach hummingbot_learning

# 退出（不停止容器）
# 按 Ctrl+P 然后 Ctrl+Q

# 停止容器
docker-compose down
```

## Autofish V1 实时模拟器

### 功能特性

- 使用 Binance API 进行实时模拟交易
- 支持测试网和主网
- WebSocket 实时监听订单状态
- 链式挂单策略
- 自动止盈止损
- 微信通知
- 订单状态持久化
- 程序重启自动恢复订单

### 环境变量配置

在项目根目录创建 `.env` 文件：

```bash
# Binance API 配置
BINANCE_TESTNET_API_KEY=your_testnet_api_key
BINANCE_TESTNET_SECRET_KEY=your_testnet_secret_key

# 主网 API（可选）
BINANCE_API_KEY=your_mainnet_api_key
BINANCE_SECRET_KEY=your_mainnet_secret_key

# 微信通知 Webhook
WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key

# 代理配置（可选）
HTTP_PROXY=http://127.0.0.1:1087
HTTPS_PROXY=http://127.0.0.1:1087
```

### 运行方式

```bash
# 进入项目目录
cd hummingbot_learning

# 运行模拟器
python3 tests/realtime_simulator_api.py
```

### 配置参数

在代码中可以修改以下配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| symbol | BTCUSDT | 交易对 |
| leverage | 10 | 杠杆倍数 |
| grid_spacing | 0.01 (1%) | 网格间距 |
| exit_profit | 0.01 (1%) | 止盈比例 |
| stop_loss | 0.08 (8%) | 止损比例 |
| total_amount_quote | 1200 | 总投入金额 (USDT) |
| max_entries | 4 | 最大层级 |
| decay_factor | 0.5 | 权重衰减因子 |

### 通知消息

程序会在以下事件发送微信通知：

- 🚀 程序启动
- 🟢 入场单下单
- ✅ 入场成交
- 🎯 止盈触发
- 🛑 止损触发
- 📝 订单修改
- 🔄 订单恢复
- ❌ 错误通知
- ⏹️ 程序停止

### 文件说明

| 文件 | 说明 |
|------|------|
| realtime_simulator_api.py | 主程序 |
| realtime_simulator_api.log | 运行日志 |
| autofish_state.json | 订单状态持久化文件 |

### 跳过订单恢复

如需跳过订单恢复，直接创建新订单，可在 `run()` 方法中注释掉恢复调用：

```python
# need_new_order = await self._restore_orders(current_price)
need_new_order = True
self.chain_state = ChainState(base_price=current_price)
```

## 学习目标

1. 熟悉 Hummingbot 基本操作
2. 研究 Pure Market Making 策略
3. 研究 Grid Strike 策略
4. 实现 autofish 策略

## 相关文档

- [Hummingbot 官方文档](https://hummingbot.org/)
- [GitHub 仓库](https://github.com/hummingbot/hummingbot)
- [Binance Futures API](https://binance-docs.github.io/apidocs/futures/en/)

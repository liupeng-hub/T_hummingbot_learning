# Autofish V1 - 链式挂单策略

基于价格波动幅度概率分布的链式挂单交易策略。

## 目录结构

```
autofish_bot/
├── __init__.py                     # 模块入口
├── autofish_core.py                # 核心算法（订单、权重计算、价格计算）
├── amplitude_analyzer.py           # 振幅分析模块
├── amplitude_config_{symbol}.json  # 振幅分析配置（按交易对生成）
├── amplitude_report_{symbol}.md    # 振幅分析报告（按交易对生成）
├── binance_backtest.py             # Binance 回测模块（使用历史 K 线数据）
├── binance_live.py                 # Binance 实盘模块（使用 Binance API）
└── README.md                       # 说明文档
```

## 快速开始

### 1. 振幅分析（推荐首先执行）

```bash
cd hummingbot_learning

# 分析 BTCUSDT 日线振幅
python3 -m autofish_bot.amplitude_analyzer --symbol BTCUSDT

# 分析 ETHUSDT
python3 -m autofish_bot.amplitude_analyzer --symbol ETHUSDT

# 自定义参数
python3 -m autofish_bot.amplitude_analyzer --symbol ETHUSDT --interval 1d --limit 500 --leverage 10
```

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --interval | 1d | K线周期 |
| --limit | 1000 | K线数量 |
| --leverage | 10 | 杠杆倍数 |

**输出文件**：

| 文件 | 说明 |
|------|------|
| `amplitude_config_{symbol}.json` | 配置文件（供回测/实盘读取） |
| `amplitude_report_{symbol}.md` | 分析报告（包含完整数据和说明） |

### 2. 回测

```bash
# 回测 BTCUSDT（自动加载 amplitude_config_BTCUSDT.json）
python3 -m autofish_bot.binance_backtest --symbol BTCUSDT --limit 500

# 回测 ETHUSDT（自动加载 amplitude_config_ETHUSDT.json）
python3 -m autofish_bot.binance_backtest --symbol ETHUSDT --limit 500

# 查看帮助
python3 -m autofish_bot.binance_backtest --help
```

### 3. 实盘交易

```bash
# 实盘 BTCUSDT（测试网）
python3 -m autofish_bot.binance_live --symbol BTCUSDT

# 实盘 ETHUSDT（测试网）
python3 -m autofish_bot.binance_live --symbol ETHUSDT

# 实盘 BTCUSDT（主网）
python3 -m autofish_bot.binance_live --symbol BTCUSDT --no-testnet
```

**参数说明**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --testnet | True | 使用测试网 |
| --no-testnet | - | 使用主网（真实交易） |

## 核心算法

### 权重计算公式

```
权重 = 振幅 × 概率^(1/d)
```

| 衰减因子d | 幂次β | 策略风格 |
|-----------|-------|----------|
| 0.5 | 2 | 激进（权重集中） |
| 1.0 | 1 | 保守（权重平均） |

### 订单价格计算

```
入场价 = 基准价格 × (1 - 网格间距)
止盈价 = 入场价 × (1 + 止盈比例)
止损价 = 入场价 × (1 - 止损比例)
```

### 链式挂单逻辑

1. 创建 A1 入场单
2. A1 成交后，下止盈止损条件单，同时创建 A2 入场单
3. 重复直到达到最大层级
4. 止盈/止损触发后，取消另一个条件单，重新创建该层级入场单

## 环境配置

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

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| symbol | BTCUSDT | 交易对 |
| total_amount_quote | 1200 | 总投入金额 (USDT) |
| leverage | 10 | 杠杆倍数 |
| decay_factor | 0.5 | 权重衰减因子 |
| max_entries | 4 | 最大层级（读取前N个权重） |
| valid_amplitudes | [1,2,3,4,5,6,7,8,9] | 有效振幅区间 |
| weights | [...] | 各层级权重 |
| grid_spacing | 0.01 (1%) | 网格间距 |
| exit_profit | 0.01 (1%) | 止盈比例 |
| stop_loss | 0.08 (8%) | 止损比例 |

## 配置文件示例

`amplitude_config_BTCUSDT.json`：

```json
{
  "symbol":"BTCUSDT",
  "total_amount_quote":1200,
  "leverage":10,
  "decay_factor":0.5,
  "max_entries":4,
  "valid_amplitudes":[1, 2, 3, 4, 5, 6, 7, 8, 9],
  "weights":[0.084, 0.3018, 0.3165, 0.1364, 0.0982, 0.0281, 0.027, 0.0066, 0.0015],
  "grid_spacing":0.01,
  "exit_profit":0.01,
  "stop_loss":0.08,
  "total_expected_return":0.2933
}
```

**字段说明**：

| 字段 | 说明 |
|------|------|
| valid_amplitudes | 有效振幅区间（正收益区间，≥10%已剔除） |
| weights | 各振幅权重（按振幅1-9排序） |
| max_entries | 回测/实盘读取前N个权重 |
| total_expected_return | 总预期收益（所有正收益区间之和） |

## 日志文件

| 文件 | 说明 |
|------|------|
| amplitude_analyzer.log | 振幅分析日志 |
| amplitude_config_{symbol}.json | 振幅配置 |
| amplitude_report_{symbol}.md | 振幅分析报告 |
| backtest.log | 回测日志 |
| live.log | 实盘日志 |
| live_state.json | 实盘状态持久化 |

## 风险提示

- 本策略仅供学习和研究使用
- 加密货币交易存在高风险，请谨慎投资
- 使用实盘模块前，请确保已在测试网充分测试
- 建议先使用小额资金进行实盘验证

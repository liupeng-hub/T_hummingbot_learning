# Autofish V1 - 链式挂单策略

基于价格波动幅度概率分布的链式挂单交易策略。

## 目录结构

```
autofish_bot/
├── __init__.py                     # 模块入口
├── autofish_core.py                # 核心算法（订单、权重计算、价格计算）
├── amplitude_analyzer.py           # 振幅分析模块（支持 Binance/LongPort）
├── amplitude_config_{symbol}.json  # 振幅分析配置（按交易对生成）
├── amplitude_report_{symbol}.md    # 振幅分析报告（按交易对生成）
├── binance_backtest.py             # Binance 回测模块（使用历史 K 线数据）
├── binance_live.py                 # Binance 实盘模块（使用 Binance API）
├── longport_backtest.py            # LongPort 回测模块（港股/美股/A股）
├── longport_live.py                # LongPort 实盘模块（港股/美股/A股）
├── requirements.txt                # Python 依赖
├── venv/                           # Python 虚拟环境
└── README.md                       # 说明文档
```

## 快速开始

### 0. 环境准备

```bash
cd hummingbot_learning/autofish_bot

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 1. 振幅分析（推荐首先执行）

```bash
# 激活虚拟环境
cd hummingbot_learning
source autofish_bot/venv/bin/activate

# 分析 BTCUSDT 日线振幅（Binance）
python3 -m autofish_bot.amplitude_analyzer --symbol BTCUSDT

# 分析 ETHUSDT
python3 -m autofish_bot.amplitude_analyzer --symbol ETHUSDT

# 分析腾讯控股 700.HK（LongPort）
python3 -m autofish_bot.amplitude_analyzer --symbol 700.HK --source longport

# 分析苹果 AAPL.US
python3 -m autofish_bot.amplitude_analyzer --symbol AAPL.US --source longport

# 自定义参数
python3 -m autofish_bot.amplitude_analyzer --symbol ETHUSDT --interval 1d --limit 500 --leverage 10
```

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --interval | 1d | K线周期 |
| --limit | 1000 | K线数量 |
| --leverage | 10 | 杠杆倍数（LongPort 股票默认为 1） |
| --source | binance | 数据源: binance 或 longport |

**输出文件**：

| 文件 | 说明 |
|------|------|
| `amplitude_config_{symbol}.json` | 配置文件（供回测/实盘读取） |
| `amplitude_report_{symbol}.md` | 分析报告（包含完整数据和说明） |

### 2. Binance 回测

```bash
# 激活虚拟环境
cd hummingbot_learning
source autofish_bot/venv/bin/activate

# 回测 BTCUSDT（自动加载 amplitude_config_BTCUSDT.json）
python3 -m autofish_bot.binance_backtest --symbol BTCUSDT --limit 500

# 回测 ETHUSDT（自动加载 amplitude_config_ETHUSDT.json）
python3 -m autofish_bot.binance_backtest --symbol ETHUSDT --limit 500

# 查看帮助
python3 -m autofish_bot.binance_backtest --help
```

**说明**：回测会自动加载对应的 `amplitude_config_{symbol}.json` 配置文件，包含权重、网格间距、止盈止损等参数。

### 3. Binance 实盘交易

```bash
# 激活虚拟环境
cd hummingbot_learning
source autofish_bot/venv/bin/activate

# 实盘 BTCUSDT（测试网，自动加载 amplitude_config_BTCUSDT.json）
python3 -m autofish_bot.binance_live --symbol BTCUSDT

# 实盘 ETHUSDT（测试网，自动加载 amplitude_config_ETHUSDT.json）
python3 -m autofish_bot.binance_live --symbol ETHUSDT

# 实盘 BTCUSDT（主网）
python3 -m autofish_bot.binance_live --symbol BTCUSDT --no-testnet
```

**说明**：实盘交易会自动加载对应的 `amplitude_config_{symbol}.json` 配置文件。

**参数说明**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --testnet | True | 使用测试网 |
| --no-testnet | - | 使用主网（真实交易） |

### 4. LongPort 回测（港股/美股/A股）

```bash
# 激活虚拟环境
cd hummingbot_learning
source autofish_bot/venv/bin/activate

# 回测腾讯控股 (700.HK，自动加载 amplitude_config_700.HK.json)
python3 -m autofish_bot.longport_backtest --symbol 700.HK

# 回测苹果 (AAPL.US，自动加载 amplitude_config_AAPL.US.json)
python3 -m autofish_bot.longport_backtest --symbol AAPL.US --interval 1d --count 200

# 回测贵州茅台 (600519.SH)
python3 -m autofish_bot.longport_backtest --symbol 600519.SH

# 查看帮助
python3 -m autofish_bot.longport_backtest --help
```

**说明**：回测会自动加载对应的 `amplitude_config_{symbol}.json` 配置文件。

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | 700.HK | 交易对（港股.HK/美股.US/A股.SH/.SZ） |
| --interval | 1d | K线周期 |
| --count | 200 | K线数量 |
| --stop-loss | 0.08 | 止损比例 |
| --total-amount | 1200 | 总投入金额 |

### 5. LongPort 实盘交易

```bash
# 激活虚拟环境
cd hummingbot_learning
source autofish_bot/venv/bin/activate

# 实盘交易腾讯控股（自动加载 amplitude_config_700.HK.json）
python3 -m autofish_bot.longport_live --symbol 700.HK

# 实盘交易苹果（自动加载 amplitude_config_AAPL.US.json）
python3 -m autofish_bot.longport_live --symbol AAPL.US

# 查看帮助
python3 -m autofish_bot.longport_live --help
```

**说明**：实盘交易会自动加载对应的 `amplitude_config_{symbol}.json` 配置文件。

**参数说明**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | 700.HK | 交易对 |
| --stop-loss | 0.08 | 止损比例 |
| --total-amount | 1200 | 总投入金额 |

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

在 `autofish_bot` 目录下创建 `.env` 文件：

```bash
cd hummingbot_learning/autofish_bot
touch .env
```

`.env` 文件内容：

```bash
# Binance API 配置
BINANCE_TESTNET_API_KEY=your_testnet_api_key
BINANCE_TESTNET_SECRET_KEY=your_testnet_secret_key

# 主网 API（可选）
BINANCE_API_KEY=your_mainnet_api_key
BINANCE_SECRET_KEY=your_mainnet_secret_key

# LongPort API 配置（港股/美股/A股）
LONGPORT_APP_KEY=your_app_key
LONGPORT_APP_SECRET=your_app_secret
LONGPORT_ACCESS_TOKEN=your_access_token

# LongPort 代理配置（可选，如果网络连接失败时使用）
LONGPORT_HTTP_PROXY=http://127.0.0.1:7890
LONGPORT_HTTPS_PROXY=http://127.0.0.1:7890

# 微信通知 Webhook
WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key

# 代理配置（可选，用于 Binance）
HTTP_PROXY=http://127.0.0.1:1087
HTTPS_PROXY=http://127.0.0.1:1087
```

**获取 LongPort API 凭证**：
1. 访问 https://open.longportapp.com/
2. 登录后进入「用户中心」
3. 创建应用获取 App Key、App Secret、Access Token

**网络问题排查**：
- 如果 LongPort 连接失败（Connection reset by peer），请配置 LONGPORT_HTTP_PROXY 环境变量
- 代理地址格式：`http://127.0.0.1:7890` 或 `http://username:password@proxy:port`

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
| binance_backtest.log | Binance 回测日志 |
| binance_live.log | Binance 实盘日志 |
| binance_live_state.json | Binance 实盘状态持久化 |
| longport_backtest.log | LongPort 回测日志 |
| longport_live.log | LongPort 实盘日志 |
| longport_live_state.json | LongPort 实盘状态持久化 |

## 风险提示

- 本策略仅供学习和研究使用
- 加密货币交易存在高风险，请谨慎投资
- 使用实盘模块前，请确保已在测试网充分测试
- 建议先使用小额资金进行实盘验证

# Autofish V2 - 链式挂单策略

基于价格波动幅度概率分布的链式挂单交易策略。

## 目录结构

```
autofish_bot_v2/
├── __init__.py                     # 模块入口
├── autofish_core.py                # 核心算法模块（订单、权重计算、振幅分析）
├── binance_backtest.py             # Binance 回测模块（使用历史 K 线数据）
├── binance_live.py                 # Binance 实盘模块（使用 Binance API）
├── binance_live_run.sh             # Binance 实盘启动/停止/状态脚本
├── longport_backtest.py            # LongPort 回测模块（港股/美股/A股）
├── longport_live.py                # LongPort 实盘模块（港股/美股/A股）
├── requirements.txt                # Python 依赖
├── venv/                           # Python 虚拟环境
├── logs/                           # 日志目录
│   ├── autofish.pid                # PID 文件
│   ├── binance_live.log            # Binance 实盘日志
│   ├── binance_live_error.log      # Binance 实盘错误日志
│   └── amplitude_analyzer.log      # 振幅分析日志
├── autofish_output/                # 输出目录
│   ├── {source}_{symbol}_amplitude_config.json  # 振幅配置
│   ├── {source}_{symbol}_amplitude_report.md    # 振幅分析报告
│   └── {source}_{symbol}_backtest_report.md     # 回测报告
└── README.md                       # 说明文档
```

## 快速开始

### 0. 环境准备

```bash
cd hummingbot_learning/autofish_bot_v2

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
source venv/bin/activate

# 分析 BTCUSDT 日线振幅（Binance，默认 ATR 入场策略）
python autofish_core.py --symbol BTCUSDT

# 分析 ETHUSDT（使用布林带入场策略）
python autofish_core.py --symbol ETHUSDT --entry-strategy bollinger

# 分析 SOLUSDT（使用综合入场策略）
python autofish_core.py --symbol SOLUSDT --entry-strategy composite

# 分析腾讯控股 700.HK（LongPort）
python autofish_core.py --symbol 700.HK --source longport

# 分析苹果 AAPL.US
python autofish_core.py --symbol AAPL.US --source longport

# 自定义参数
python autofish_core.py --symbol ETHUSDT --interval 1d --limit 500 --leverage 10

# 查看帮助
python autofish_core.py --help
```

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --interval | 1d | K线周期 |
| --limit | 1000 | K线数量 |
| --leverage | 10 | 杠杆倍数（LongPort 股票默认为 1） |
| --source | binance | 数据源: binance 或 longport |
| --output | None | 输出文件路径 |
| --entry-strategy | atr | 入场价格策略: fixed, atr, bollinger, support, composite |

**输出文件**：

| 文件 | 说明 |
|------|------|
| `autofish_output/{source}_{symbol}_amplitude_config.json` | 配置文件（包含 d=0.5 和 d=1.0 两种策略） |
| `autofish_output/{source}_{symbol}_amplitude_report.md` | 分析报告（包含完整数据和说明） |
| `logs/amplitude_analyzer.log` | 振幅分析日志 |

### 2. Binance 回测

```bash
# 激活虚拟环境
source venv/bin/activate

# 回测 BTCUSDT（自动加载振幅配置，使用 d=0.5 策略）
python binance_backtest.py --symbol BTCUSDT --interval 1h --limit 500 --decay-factor 0.5

# 回测 ETHUSDT（使用 d=1.0 保守策略）
python binance_backtest.py --symbol ETHUSDT --interval 1h --limit 500 --decay-factor 1.0

# 查看帮助
python binance_backtest.py --help
```

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --interval | 1h | K线周期 |
| --limit | 500 | K线数量 |
| --decay-factor | 0.5 | 衰减因子（0.5 激进 / 1.0 保守） |

**说明**：
- 回测会自动加载对应的振幅配置文件 `{source}_{symbol}_amplitude_config.json`
- 根据指定的 `--decay-factor` 读取对应的策略配置（d_0.5 或 d_1.0）
- 如果没有振幅配置文件，则使用内置默认配置
- `stop_loss`、`total_amount_quote`、`entry_price_strategy` 从配置文件读取

### 3. Binance 实盘交易

```bash
# 激活虚拟环境
source venv/bin/activate

# 启动实盘（测试网，使用 d=0.5 策略）
python binance_live.py --symbol BTCUSDT --testnet --decay-factor 0.5

# 启动实盘（主网，使用 d=1.0 保守策略）
python binance_live.py --symbol BTCUSDT --no-testnet --decay-factor 1.0

# 或使用脚本启动
./binance_live_run.sh start

# 查看状态
./binance_live_run.sh status

# 停止实盘
./binance_live_run.sh stop
```

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --testnet | - | 使用测试网 |
| --no-testnet | - | 使用主网 |
| --decay-factor | 0.5 | 衰减因子（0.5 激进 / 1.0 保守） |

**说明**：
- 实盘会自动加载对应的振幅配置文件 `{source}_{symbol}_amplitude_config.json`
- 根据指定的 `--decay-factor` 读取对应的策略配置（d_0.5 或 d_1.0）
- 如果没有振幅配置文件，则使用内置默认配置
- `stop_loss`、`total_amount_quote`、`entry_price_strategy` 从配置文件读取

**特性**：
- 自动加载振幅配置文件
- 自动重启：程序异常退出后自动重启，最多 5 次
- 日志记录：输出到 `logs/binance_live.log`
- PID 管理：防止重复运行
- 优雅退出：支持 SIGTERM 信号优雅退出

### 4. LongPort 回测（港股/美股/A股）

```bash
# 激活虚拟环境
source venv/bin/activate

# 回测腾讯控股 (700.HK，使用 d=0.5 策略)
python longport_backtest.py --symbol 700.HK --interval 1d --count 200 --decay-factor 0.5

# 回测苹果 (AAPL.US，使用 d=1.0 保守策略)
python longport_backtest.py --symbol AAPL.US --interval 1d --count 200 --decay-factor 1.0

# 回测贵州茅台 (600519.SH)
python longport_backtest.py --symbol 600519.SH --interval 1d --count 200

# 查看帮助
python longport_backtest.py --help
```

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | 700.HK | 交易对（港股.HK/美股.US/A股.SH/.SZ） |
| --interval | 1d | K线周期 |
| --count | 200 | K线数量 |
| --decay-factor | 0.5 | 衰减因子（0.5 激进 / 1.0 保守） |

**说明**：
- 回测会自动加载对应的振幅配置文件 `{source}_{symbol}_amplitude_config.json`
- 根据指定的 `--decay-factor` 读取对应的策略配置（d_0.5 或 d_1.0）
- 如果没有振幅配置文件，则使用内置默认配置
- `stop_loss`、`total_amount_quote`、`entry_price_strategy` 从配置文件读取

### 5. LongPort 实盘交易

```bash
# 激活虚拟环境
source venv/bin/activate

# 实盘交易腾讯控股（使用 d=0.5 策略）
python longport_live.py --symbol 700.HK --decay-factor 0.5

# 实盘交易苹果（使用 d=1.0 保守策略）
python longport_live.py --symbol AAPL.US --decay-factor 1.0

# 查看帮助
python longport_live.py --help
```

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | 700.HK | 交易对 |
| --decay-factor | 0.5 | 衰减因子（0.5 激进 / 1.0 保守） |

**说明**：
- 实盘会自动加载对应的振幅配置文件 `{source}_{symbol}_amplitude_config.json`
- 根据指定的 `--decay-factor` 读取对应的策略配置（d_0.5 或 d_1.0）
- 如果没有振幅配置文件，则使用内置默认配置
- `stop_loss`、`total_amount_quote`、`entry_price_strategy` 从配置文件读取

## 核心算法

### 权重计算公式

```
权重 = 振幅 × 概率^(1/d)
```

| 衰减因子d | 幂次β | 策略风格 |
|-----------|-------|----------|
| 0.5 | 2 | 激进（权重集中在前几层） |
| 1.0 | 1 | 保守（权重分布更均匀） |

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

## 核心类

| 类 | 说明 |
|---|------|
| `Autofish_Order` | 订单数据类 |
| `Autofish_ChainState` | 链式挂单状态管理 |
| `Autofish_WeightCalculator` | 权重计算器 |
| `Autofish_OrderCalculator` | 订单计算器（提供默认配置） |
| `Autofish_AmplitudeAnalyzer` | 振幅分析器（生成权重和报告） |
| `Autofish_AmplitudeConfig` | 振幅配置加载器（读取配置文件） |

## 环境配置

在 `autofish_bot_v2` 目录下创建 `.env` 文件：

```bash
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

## 配置文件格式

`autofish_output/binance_BTCUSDT_amplitude_config.json`：

```json
{
  "d_0.5": {
    "symbol": "BTCUSDT",
    "total_amount_quote": 1200,
    "leverage": 10,
    "decay_factor": 0.5,
    "max_entries": 4,
    "valid_amplitudes": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "weights": [0.0852, 0.2956, 0.3177, 0.137, 0.1008, 0.0282, 0.0271, 0.0066, 0.0019],
    "grid_spacing": 0.01,
    "exit_profit": 0.01,
    "stop_loss": 0.08,
    "total_expected_return": 0.2942,
    "entry_price_strategy": {
      "name": "atr",
      "params": {
        "atr_period": 14,
        "atr_multiplier": 0.5,
        "min_spacing": 0.005,
        "max_spacing": 0.03
      }
    }
  },
  "d_1.0": {
    "symbol": "BTCUSDT",
    "total_amount_quote": 1200,
    "leverage": 10,
    "decay_factor": 1.0,
    "max_entries": 4,
    "valid_amplitudes": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "weights": [0.0622, 0.1638, 0.208, 0.1577, 0.1513, 0.0877, 0.0928, 0.0489, 0.0275],
    "grid_spacing": 0.01,
    "exit_profit": 0.01,
    "stop_loss": 0.08,
    "total_expected_return": 0.2942,
    "entry_price_strategy": {
      "name": "atr",
      "params": {
        "atr_period": 14,
        "atr_multiplier": 0.5,
        "min_spacing": 0.005,
        "max_spacing": 0.03
      }
    }
  }
}
```

**字段说明**：

| 字段 | 说明 |
|------|------|
| d_0.5 | 衰减因子 0.5 的配置（激进策略） |
| d_1.0 | 衰减因子 1.0 的配置（保守策略） |
| valid_amplitudes | 有效振幅区间（正收益区间，≥10%已剔除） |
| weights | 各振幅权重列表（按振幅1-9排序） |
| max_entries | 回测/实盘读取前N个权重 |
| total_expected_return | 总预期收益（所有正收益区间之和） |

## 配置参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| symbol | BTCUSDT | 交易对 |
| total_amount_quote | 1200 | 总投入金额 |
| leverage | 10 | 杠杆倍数（LongPort 股票为 1） |
| decay_factor | 0.5 | 权重衰减因子（0.5 激进 / 1.0 保守） |
| max_entries | 4 | 最大层级（读取前N个权重） |
| valid_amplitudes | [1,2,3,4,5,6,7,8,9] | 有效振幅区间 |
| weights | [...] | 各层级权重列表 |
| grid_spacing | 0.01 (1%) | 网格间距 |
| exit_profit | 0.01 (1%) | 止盈比例 |
| stop_loss | 0.08 (8%) | 止损比例 |
| entry_price_strategy | {"name": "atr", ...} | 入场价格策略配置 |

### 入场价格策略

| 策略名称 | 说明 |
|----------|------|
| fixed | 固定网格间距（默认） |
| atr | 基于 ATR 动态计算 |
| bollinger | 布林带下轨入场 |
| support | 支撑位入场 |
| composite | 综合多种指标 |

详细说明请参考 [入场价格策略文档](docs/entry_price_strategy.md)

## 日志文件

| 文件 | 说明 |
|------|------|
| logs/autofish.pid | PID 文件 |
| logs/binance_live.log | Binance 实盘日志 |
| logs/binance_live_error.log | Binance 实盘错误日志 |
| logs/amplitude_analyzer.log | 振幅分析日志 |
| autofish_output/{source}_{symbol}_amplitude_config.json | 振幅配置 |
| autofish_output/{source}_{symbol}_amplitude_report.md | 振幅分析报告 |
| autofish_output/{source}_{symbol}_backtest_report.md | 回测报告 |

## V2 版本更新

### 主要变更

1. **代码整合**：将 `amplitude_analyzer.py` 合并到 `autofish_core.py`，减少文件数量
2. **类名统一**：所有类增加 `Autofish_` 前缀，避免命名冲突
3. **脚本整合**：`start.sh`、`stop.sh`、`status.sh` 合并为 `binance_live_run.sh`
4. **日志统一**：所有日志输出到 `logs/` 目录
5. **代理支持**：振幅分析自动从 `.env` 读取代理配置
6. **双策略支持**：配置文件同时包含 d=0.5（激进）和 d=1.0（保守）两种策略
7. **配置简化**：移除冗余参数，统一使用 `--decay-factor` 选择策略
8. **入场价格策略**：支持 5 种入场价格策略（fixed, atr, bollinger, support, composite）
9. **CLI 简化**：移除 `--stop-loss` 和 `--total-amount` 参数，从配置文件读取

### 类名对照

| V1 类名 | V2 类名 |
|---------|---------|
| `Order` | `Autofish_Order` |
| `ChainState` | `Autofish_ChainState` |
| `WeightCalculator` | `Autofish_WeightCalculator` |
| `AmplitudeAnalyzer` | `Autofish_AmplitudeAnalyzer` |
| `AmplitudeConfig` | `Autofish_AmplitudeConfig` |

## 风险提示

- 本策略仅供学习和研究使用
- 加密货币交易存在高风险，请谨慎投资
- 使用实盘模块前，请确保已在测试网充分测试
- 建议先使用小额资金进行实盘验证

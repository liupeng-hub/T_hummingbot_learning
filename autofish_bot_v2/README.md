# Autofish V2 - 链式挂单策略

基于价格波动幅度概率分布的链式挂单交易策略，集成行情状态检测、可视化分析和行情感知回测功能。

## 核心模块

| 模块 | 文件 | 说明 |
|------|------|------|
| 核心算法 | `autofish_core.py` | 订单、权重计算、振幅分析 |
| 行情检测 | `market_status_detector.py` | 市场状态识别（震荡/趋势） |
| 行情可视化 | `market_status_visualizer.py` | K线图可视化、Web界面 |
| 行情感知回测 | `market_aware_backtest.py` | 结合行情状态的策略回测 |
| Binance回测 | `binance_backtest.py` | Binance历史数据回测 |
| Binance实盘 | `binance_live.py` | Binance实盘交易 |
| LongPort回测 | `longport_backtest.py` | 港股/美股/A股回测 |
| LongPort实盘 | `longport_live.py` | 港股/美股/A股实盘 |

详细模块架构请参考 [市场模块架构说明](docs/market_module_architecture.md)

## 目录结构

```
autofish_bot_v2/
├── __init__.py                     # 模块入口
├── autofish_core.py                # 核心算法模块（订单、权重计算、振幅分析）
├── market_status_detector.py       # 行情状态检测器
├── market_status_visualizer.py     # 行情可视化系统
├── market_aware_backtest.py        # 行情感知回测引擎
├── binance_backtest.py             # Binance 回测模块
├── binance_live.py                 # Binance 实盘模块
├── binance_live_run.sh             # Binance 实盘启动/停止/状态脚本
├── longport_backtest.py            # LongPort 回测模块（港股/美股/A股）
├── longport_live.py                # LongPort 实盘模块（港股/美股/A股）
├── binance_kline_fetcher.py        # Binance K线数据获取
├── requirements.txt                # Python 依赖
├── venv/                           # Python 虚拟环境
├── logs/                           # 日志目录
│   ├── autofish.pid                # PID 文件
│   ├── binance_live.log            # Binance 实盘日志
│   ├── binance_live_error.log      # Binance 实盘错误日志
│   └── amplitude_analyzer.log      # 振幅分析日志
├── out/                           # 输出目录
│   ├── autofish/                  # 基础振幅分析和普通回测输出
│   ├── market_backtest/           # 行情感知回测输出
│   ├── market_visualizer/         # 行情可视化输出
│   └── market_optimization/       # 参数优化输出
├── database/                      # 数据库文件
│   ├── market_visualizer.db        # SQLite 数据库
│   └── *.md, *.png, *.html         # 可视化输出文件
├── templates/                      # Web 界面模板
│   └── index.html                  # 行情可视化 Web 界面
├── docs/                           # 文档目录
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

振幅分析用于生成标的特定的配置参数，包括权重、网格间距、止盈止损比例等。

```bash
# 激活虚拟环境
source venv/bin/activate

# 分析 BTCUSDT 日线振幅（Binance，默认 ATR 入场策略）
# 执行后会生成 binance_BTCUSDT_amplitude_config.json 配置文件
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
| `out/autofish/{source}_{symbol}_amplitude_config.json` | 配置文件（包含 d=0.5 和 d=1.0 两种策略） |
| `out/autofish/{source}_{symbol}_amplitude_report.md` | 分析报告（包含完整数据和说明） |
| `logs/amplitude_analyzer.log` | 振幅分析日志 |

### 2. 行情状态检测

识别市场状态（震荡/趋势），支持多种算法：

```bash
# 分析最近30天行情（使用改进算法）
python market_status_detector.py --symbol BTCUSDT --days 30 --algorithm improved

# 分析指定日期范围
python market_status_detector.py --symbol BTCUSDT --date-range 20200101-20260310 --algorithm improved

# 使用不同算法
python market_status_detector.py --symbol ETHUSDT --days 30 --algorithm adx
```

**算法选项**：

| 算法 | 说明 |
|------|------|
| improved | 改进算法（推荐），结合支撑阻力、箱体震荡、突破识别 |
| dual_thrust | Dual Thrust 算法，基于价格突破区间判断 |
| adx | ADX 趋势强度算法 |
| composite | 综合算法，结合多种指标 |
| realtime | 实时算法，基于价格行为和波动率 |

**输出文件**：

| 文件 | 说明 |
|------|------|
| `out/market_backtest/binance_{symbol}_market_report_{interval}_{days}d.md` | 详细分析报告 |
| `out/market_backtest/binance_{symbol}_market_history.md` | 历史记录汇总 |

### 3. 行情可视化

K线图可视化，以色带形式展示行情状态区间：

```bash
# 命令行模式 - 生成可视化文件
python market_status_visualizer.py \
    --symbol BTCUSDT \
    --date-range 20200101-20260310 \
    --algorithm improved \
    --generate-all

# Web服务器模式 - 交互式界面
python market_status_visualizer.py --server --port 5001
# 访问 http://localhost:5001
```

**输出文件**：

| 文件 | 说明 |
|------|------|
| `out/market_visualizer/market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.md` | MD 分析报告 |
| `out/market_visualizer/market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.png` | PNG 图表 |
| `out/market_visualizer/market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.html` | 交互式 HTML |
| `database/market_visualizer.db` | SQLite 数据库 |

详细说明请参考 [行情可视化设计文档](docs/market_visualizer_design.md)

### 4. 行情感知回测

根据市场状态动态控制交易：

```bash
# 基本使用
python market_aware_backtest.py --symbol BTCUSDT --days 30

# 指定时间范围
python market_aware_backtest.py --symbol BTCUSDT --date-range 20200101-20260310

# 使用不同行情算法
python market_aware_backtest.py --symbol BTCUSDT --days 30 --market-algorithm improved
python market_aware_backtest.py --symbol BTCUSDT --days 30 --market-algorithm adx

# 对比测试：始终震荡模式（不停止交易）
python market_aware_backtest.py --symbol BTCUSDT --days 30 --market-algorithm always_ranging
```

**核心策略**：

| 状态变化 | 处理动作 |
|----------|----------|
| 震荡 → 趋势 | 平仓所有订单，停止交易 |
| 趋势 → 震荡 | 创建首个订单，开始交易 |

详细说明请参考 [行情感知回测文档](docs/market_aware_backtest.md)

### 5. Binance 回测

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

### 6. Binance 实盘交易

```bash
# 激活虚拟环境
source venv/bin/activate

# 启动实盘（测试网，使用 d=0.5 策略）
python binance_live.py --symbol BTCUSDT --testnet --decay-factor 0.5

# 启动实盘（主网，使用 d=1.0 保守策略）
python binance_live.py --symbol BTCUSDT --no-testnet --decay-factor 1.0

# 或使用脚本启动（默认 BTCUSDT 测试网）
./binance_live_run.sh start

# 使用脚本启动指定交易对
./binance_live_run.sh --symbol ETHUSDT start

# 使用脚本启动主网
./binance_live_run.sh --symbol BTCUSDT --no-testnet start

# 使用脚本启动保守策略
./binance_live_run.sh --symbol ETHUSDT --decay-factor 1.0 start

# 查看状态
./binance_live_run.sh status

# 停止实盘
./binance_live_run.sh stop

# 重启实盘
./binance_live_run.sh restart
```

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --testnet | - | 使用测试网（默认） |
| --no-testnet | - | 使用主网 |
| --decay-factor | 0.5 | 衰减因子（0.5 激进 / 1.0 保守） |
| --stop-loss | 0.08 | 止损比例（无振幅配置时使用） |
| --total-amount | 10000 | 总投入金额（无振幅配置时使用） |

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
- 脚本参数：支持 `--symbol`、`--testnet`、`--no-testnet`、`--decay-factor` 参数

### 7. LongPort 回测（港股/美股/A股）

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

### 8. LongPort 实盘交易

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

### A1 超时重挂

当 A1 订单挂单后，如果行情持续上涨，价格一直无法达到 A1 入场位置，可启用超时重挂机制：

1. A1 挂单超过 `a1_timeout_minutes` 分钟未成交
2. 取消原 A1 订单及其关联的止盈止损单
3. 使用当前价格重新计算 A1 入场价
4. 重新挂单 A1

**配置参数**：
- `a1_timeout_minutes`: 超时时间（分钟），默认 60，设为 0 不启用

**适用场景**：
- 行情持续上涨，A1 入场价迟迟无法触及
- 避免长时间空仓错过交易机会

## 核心类

### Autofish 核心类

| 类 | 说明 |
|---|------|
| `Autofish_Order` | 订单数据类 |
| `Autofish_ChainState` | 链式挂单状态管理 |
| `Autofish_WeightCalculator` | 权重计算器 |
| `Autofish_OrderCalculator` | 订单计算器（提供默认配置） |
| `Autofish_AmplitudeAnalyzer` | 振幅分析器（生成权重和报告） |
| `Autofish_AmplitudeConfig` | 振幅配置加载器（读取配置文件） |

### 行情检测类

| 类 | 说明 |
|---|------|
| `MarketStatusDetector` | 行情检测主控制器 |
| `ImprovedStatusAlgorithm` | 改进算法（推荐） |
| `DualThrustAlgorithm` | Dual Thrust 算法 |
| `ADXAlgorithm` | ADX 趋势强度算法 |
| `SupportResistanceDetector` | 支撑阻力位检测器 |
| `BoxRangeDetector` | 箱体震荡检测器 |

### 行情可视化类

| 类 | 说明 |
|---|------|
| `MarketVisualizerDB` | 数据库管理 |
| `ChartVisualizer` | 静态图表生成 |
| `WebChartVisualizer` | 交互式 HTML 图表生成 |
| `MarketStatusVisualizer` | 命令行控制器 |
| `MarketVisualizerServer` | Web 服务器 |

### 行情感知回测类

| 类 | 说明 |
|---|------|
| `MarketAwareBacktestEngine` | 行情感知回测引擎 |
| `MarketStatusEvent` | 行情状态事件 |
| `TradingPeriod` | 交易时段记录 |

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

### 振幅配置文件

`out/autofish/binance_BTCUSDT_amplitude_config.json`（由 `python autofish_core.py --symbol BTCUSDT` 生成）：

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
    "total_expected_return": 0.2942
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
    "total_expected_return": 0.2942
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

### 扩展策略配置文件

`out/autofish/autofish_extern_strategy.json`（所有标的共用的扩展策略配置）：

```json
{
  "entry_price_strategy": {
    "name": "atr",
    "params": {
      "atr_period": 14,
      "atr_multiplier": 0.5,
      "min_spacing": 0.005,
      "max_spacing": 0.03
    }
  },
  "market_aware": {
    "enabled": true,
    "algorithm": "dual_thrust",
    "lookback_period": 20,
    "breakout_threshold": 0.02,
    "consecutive_bars": 3,
    "down_confirm_days": 1,
    "k2_down_factor": 0.6,
    "cooldown_days": 1,
    "check_interval": 60,
    "trading_statuses": ["ranging"]
  }
}
```

**字段说明**：

| 字段 | 说明 |
|------|------|
| entry_price_strategy | 入场价格策略配置 |
| entry_price_strategy.name | 策略名称: fixed, atr, bollinger, support, composite |
| entry_price_strategy.params | 策略参数 |
| market_aware | 行情感知策略配置 |
| market_aware.enabled | 是否启用行情感知 |
| market_aware.algorithm | 行情检测算法: improved, dual_thrust, adx, composite |
| market_aware.lookback_period | 回看天数（日线） |
| market_aware.breakout_threshold | 突破阈值 |
| market_aware.consecutive_bars | 连续确认天数 |
| market_aware.down_confirm_days | 下跌确认天数 |
| market_aware.k2_down_factor | K2下跌因子 |
| market_aware.cooldown_days | 状态切换冷却期 |
| market_aware.check_interval | 检测间隔（秒） |
| market_aware.trading_statuses | 允许交易的状态: ranging, trending_up, trending_down |

**配置文件关系**：

```
┌─────────────────────────────────────────────────────────────────┐
│                    autofish_extern_strategy.json                │
│                    （所有标的共用的扩展策略）                      │
│  ┌─────────────────────┐  ┌─────────────────────────────────┐  │
│  │ entry_price_strategy│  │        market_aware             │  │
│  │   (入场价格策略)      │  │      (行情感知策略)              │  │
│  └─────────────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              binance_BTCUSDT_amplitude_config.json              │
│                   （BTCUSDT 标的特定参数）                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ d_0.5: weights, grid_spacing, stop_loss, ...            │   │
│  │ d_1.0: weights, grid_spacing, stop_loss, ...            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              binance_ETHUSDT_amplitude_config.json              │
│                   （ETHUSDT 标的特定参数）                        │
└─────────────────────────────────────────────────────────────────┘
```

## 配置参数说明

### 振幅配置参数

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

### 扩展策略参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| a1_timeout_minutes | 10 | A1 订单超时时间（分钟），0 表示不启用 |
| entry_price_strategy.name | atr | 入场价格策略: fixed, atr, bollinger, support, composite |
| market_aware.enabled | true | 是否启用行情感知 |
| market_aware.algorithm | dual_thrust | 行情检测算法 |
| market_aware.trading_statuses | ["ranging"] | 允许交易的状态 |

### 入场价格策略

| 策略名称 | 说明 |
|----------|------|
| fixed | 固定网格间距（默认） |
| atr | 基于 ATR 动态计算 |
| bollinger | 布林带下轨入场 |
| support | 支撑位入场 |
| composite | 综合多种指标 |

详细说明请参考 [入场价格策略文档](docs/entry_price_strategy.md)

## 日志与输出文件

### 日志文件

| 文件 | 说明 |
|------|------|
| logs/autofish.pid | PID 文件 |
| logs/binance_live.log | Binance 实盘日志 |
| logs/binance_live_error.log | Binance 实盘错误日志 |
| logs/amplitude_analyzer.log | 振幅分析日志 |
| logs/market_visualizer_server.log | 行情可视化服务器日志 |

### out/autofish - 基础振幅分析和普通回测输出

| 文件 | 说明 |
|------|------|
| out/autofish/{source}_{symbol}_amplitude_config.json | 振幅配置 |
| out/autofish/{source}_{symbol}_amplitude_report.md | 振幅分析报告 |
| out/autofish/{source}_{symbol}_backtest_report.md | 回测报告 |

### out/market_backtest - 行情感知回测输出

| 文件 | 说明 |
|------|------|
| out/market_backtest/{source}_{symbol}_market_aware_backtest_{days}d_{date_range}.md | 行情感知回测报告 |
| out/market_backtest/{source}_{symbol}_market_aware_history.md | 行情感知回测历史记录 |
| out/market_backtest/binance_{symbol}_market_report_{interval}_{days}d.md | 行情检测报告 |
| out/market_backtest/binance_{symbol}_market_history.md | 行情检测历史记录 |

### out/market_visualizer - 行情可视化输出

| 文件 | 说明 |
|------|------|
| out/market_visualizer/market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.md | MD 分析报告 |
| out/market_visualizer/market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.png | PNG 图表 |
| out/market_visualizer/market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.html | 交互式 HTML |

### out/market_optimization - 参数优化输出

| 文件 | 说明 |
|------|------|
| out/market_optimization/optuna_dual_thrust_results.csv | Dual Thrust 优化结果 |
| out/market_optimization/optuna_dual_thrust_report.md | Dual Thrust 优化报告 |
| out/market_optimization/optuna_improved_results.csv | Improved 优化结果 |
| out/market_optimization/optuna_improved_report.md | Improved 优化报告 |

### database - 数据库文件

| 文件 | 说明 |
|------|------|
| database/klines.db | K线缓存数据库 |
| database/market_visualizer.db | 可视化数据库 |

## 相关文档

| 文档 | 说明 |
|------|------|
| [市场模块架构说明](docs/market_module_architecture.md) | 三大核心模块关系与使用场景 |
| [行情检测器文档](docs/market_status_detector.md) | 行情状态检测算法详解 |
| [行情可视化设计](docs/market_visualizer_design.md) | 可视化系统设计文档 |
| [行情感知回测](docs/market_aware_backtest.md) | 行情感知回测引擎文档 |
| [入场价格策略](docs/entry_price_strategy.md) | 入场价格策略详解 |
| [Optuna Dual Thrust 优化器](docs/optuna_dual_thrust_optimizer.md) | Dual Thrust 参数优化 |
| [Optuna Improved 优化器](docs/optuna_improved_strategy_optimizer.md) | Improved 策略参数优化 |

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
10. **行情检测模块**：新增 `market_status_detector.py`，支持多种行情状态检测算法
11. **行情可视化模块**：新增 `market_status_visualizer.py`，支持 K 线图可视化和 Web 界面
12. **行情感知回测**：新增 `market_aware_backtest.py`，根据行情状态动态控制交易

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

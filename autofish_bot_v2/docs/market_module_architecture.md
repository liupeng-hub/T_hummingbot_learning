# 市场模块架构说明

## 概述

Autofish Bot V2 包含三个核心模块，形成完整的行情分析、可视化、回测体系：

| 模块 | 文件 | 职责 |
|------|------|------|
| 行情检测器 | `market_status_detector.py` | 核心算法层，识别市场状态 |
| 行情可视化 | `market_status_visualizer.py` | 可视化层，图表展示分析结果 |
| 行情感知回测 | `market_aware_backtest.py` | 回测层，结合行情状态优化策略 |

## 模块关系图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    market_status_detector.py                                │
│                         (核心算法层)                                         │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐ │
│  │ PriceAction     │  │ Volatility      │  │ SupportResistance           │ │
│  │ Detector        │  │ Detector        │  │ Detector                    │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘ │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐ │
│  │ BoxRange        │  │ DualThrust      │  │ ImprovedStatus              │ │
│  │ Detector        │  │ Algorithm       │  │ Algorithm                   │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                    MarketStatusDetector                               │ │
│  │                    (统一检测入口)                                      │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
┌───────────────────────────────────┐  ┌───────────────────────────────────────┐
│  market_status_visualizer.py      │  │     market_aware_backtest.py          │
│        (可视化层)                  │  │          (回测层)                      │
│                                   │  │                                       │
│  ┌─────────────────────────────┐  │  │  ┌─────────────────────────────────┐  │
│  │ MarketVisualizerDB          │  │  │  │ MarketAwareBacktestEngine       │  │
│  │ (数据库管理)                 │  │  │  │ (行情感知回测引擎)               │  │
│  └─────────────────────────────┘  │  │  └─────────────────────────────────┘  │
│  ┌─────────────────────────────┐  │  │                                       │
│  │ ChartVisualizer             │  │  │  功能：                               │
│  │ (静态图表生成)               │  │  │  - 根据行情状态调整策略参数           │
│  └─────────────────────────────┘  │  │  - 震荡/趋势行情使用不同策略          │
│  ┌─────────────────────────────┐  │  │  - 回测时过滤不利行情                  │
│  │ WebChartVisualizer          │  │  │                                       │
│  │ (交互式HTML图表)             │  │  └───────────────────────────────────────┘
│  └─────────────────────────────┘  │
│  ┌─────────────────────────────┐  │
│  │ MarketStatusVisualizer      │  │
│  │ (命令行控制器)               │  │
│  └─────────────────────────────┘  │
│  ┌─────────────────────────────┐  │
│  │ MarketVisualizerServer      │  │
│  │ (Web服务器)                  │  │
│  └─────────────────────────────┘  │
│                                   │
│  功能：                           │
│  - K线图可视化                    │
│  - 状态色带显示                   │
│  - Web界面管理测试                │
│  - 多算法对比                     │
└───────────────────────────────────┘
```

## 模块详细说明

### 1. market_status_detector.py - 行情检测器

**定位**: 核心算法层，无外部依赖的独立模块

**核心功能**:
- 识别市场状态：震荡(RANGING)、上涨(TRENDING_UP)、下跌(TRENDING_DOWN)
- 提供多种检测算法：Improved、DualThrust、ADX、Composite、RealTime
- 支持命令行独立运行

**核心类**:

| 类名 | 说明 |
|------|------|
| `MarketStatusDetector` | 主控制器，统一检测入口 |
| `ImprovedStatusAlgorithm` | 改进算法（推荐），结合支撑阻力、箱体震荡、突破识别 |
| `DualThrustAlgorithm` | Dual Thrust 算法，基于价格突破区间判断 |
| `ADXAlgorithm` | ADX 趋势强度算法 |
| `CompositeAlgorithm` | 综合算法，结合多种指标 |
| `SupportResistanceDetector` | 支撑阻力位检测器 |
| `BoxRangeDetector` | 箱体震荡检测器 |
| `PriceActionDetector` | 价格行为检测器 |
| `VolatilityDetector` | 波动率检测器 |

**命令行使用**:

```bash
# 分析最近30天行情
python market_status_detector.py --symbol BTCUSDT --days 30 --algorithm improved

# 分析指定日期范围
python market_status_detector.py --symbol BTCUSDT --date-range 20200101-20260310 --algorithm improved

# 使用不同算法
python market_status_detector.py --symbol ETHUSDT --days 30 --algorithm adx
```

**输出文件**:

| 文件 | 说明 |
|------|------|
| `out/market_backtest/binance_{symbol}_market_report_{interval}_{days}d.md` | 详细分析报告 |
| `out/market_backtest/binance_{symbol}_market_history.md` | 历史记录汇总 |

---

### 2. market_status_visualizer.py - 行情可视化

**定位**: 可视化层，依赖 `market_status_detector.py`

**核心功能**:
- K线图可视化，以色带形式展示行情状态区间
- 支持两种渲染模式：顶部色带、K线上方色带
- Web界面管理测试用例
- 多算法对比分析

**核心类**:

| 类名 | 说明 |
|------|------|
| `MarketVisualizerDB` | 数据库管理，SQLite 持久化 |
| `ChartVisualizer` | 静态图表生成（PNG） |
| `WebChartVisualizer` | 交互式 HTML 图表生成 |
| `MarketStatusVisualizer` | 命令行模式控制器 |
| `MarketVisualizerServer` | Web 服务器，提供 API 和前端界面 |

**运行模式**:

```bash
# 命令行模式 - 生成可视化文件
python market_status_visualizer.py \
    --symbol BTCUSDT \
    --date-range 20200101-20260310 \
    --algorithm improved \
    --generate-all

# Web服务器模式 - 交互式界面
python market_status_visualizer.py --server --port 5001
```

**输出文件**:

| 文件 | 说明 |
|------|------|
| `out/market_visualizer/market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.md` | MD 分析报告 |
| `out/market_visualizer/market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.png` | PNG 图表 |
| `out/market_visualizer/market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.html` | 交互式 HTML |
| `database/market_visualizer.db` | SQLite 数据库 |

**Web API 接口**:

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/test-cases` | GET | 获取测试用例列表 |
| `/api/test-cases` | POST | 创建新测试 |
| `/api/test-cases/:id` | GET | 获取测试详情 |
| `/api/test-cases/:id` | DELETE | 删除测试 |
| `/api/compare` | POST | 对比多个测试结果 |
| `/api/algorithms` | GET | 获取算法列表 |

---

### 3. market_aware_backtest.py - 行情感知回测

**定位**: 回测层，依赖 `market_status_detector.py`

**核心功能**:
- 根据市场状态动态控制交易
- 震荡行情：正常进行链式挂单交易
- 趋势行情：平仓所有订单，停止交易
- 记录行情状态变化事件和交易时段

**核心类**:

| 类名 | 说明 |
|------|------|
| `MarketAwareBacktestEngine` | 行情感知回测引擎，继承自 `BacktestEngine` |
| `MarketStatusEvent` | 行情状态事件数据类 |
| `TradingPeriod` | 交易时段数据类 |

**核心策略**:

| 状态变化 | 处理动作 |
|----------|----------|
| 震荡 → 趋势 | 平仓所有订单，停止交易 |
| 趋势 → 震荡 | 创建首个订单，开始交易 |
| 趋势 → 反向趋势 | 保持停止状态 |

**命令行使用**:

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

**输出文件**:

| 文件 | 说明 |
|------|------|
| `out/market_backtest/binance_{symbol}_market_aware_backtest_{days}d_{date_range}.md` | 详细回测报告 |
| `out/market_backtest/binance_{symbol}_market_aware_history.md` | 历史记录汇总 |

---

## 数据流

```
                    ┌─────────────────┐
                    │   Binance API   │
                    └────────┬────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                           K线数据获取                                       │
│                                                                            │
│  binance_kline_fetcher.py  ──────────────────────────────────────────────  │
│  获取历史K线数据，支持多周期 (1m, 1h, 1d 等)                                │
└────────────────────────────────────────────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   Detector      │ │   Visualizer    │ │   Backtest      │
│   行情检测       │ │   可视化        │ │   回测          │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ 输出:           │ │ 输出:           │ │ 输出:           │
│ - MD报告        │ │ - MD报告        │ │ - 回测报告      │
│ - 历史记录      │ │ - PNG图表       │ │ - 历史记录      │
│                 │ │ - HTML交互      │ │                 │
│                 │ │ - SQLite数据库  │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## 使用场景

### 场景1：快速行情分析

只需要了解当前市场状态，使用 `market_status_detector.py`：

```bash
python market_status_detector.py --symbol BTCUSDT --days 30 --algorithm improved
```

### 场景2：可视化分析

需要直观的图表展示，使用 `market_status_visualizer.py`：

```bash
# 命令行生成文件
python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 --algorithm improved --generate-all

# Web界面交互
python market_status_visualizer.py --server --port 5001
# 访问 http://localhost:5001
```

### 场景3：策略回测

需要验证策略在历史数据上的表现，使用 `market_aware_backtest.py`：

```bash
python market_aware_backtest.py --symbol BTCUSDT --date-range 20200101-20260310 --market-algorithm improved
```

### 场景4：多算法对比

使用 Web 界面对比不同算法的检测结果：

```bash
python market_status_visualizer.py --server --port 5001
# 在 Web 界面选择多个测试用例进行对比
```

## 扩展性

### 添加新算法

1. 在 `market_status_detector.py` 中实现算法类，继承 `StatusAlgorithm`
2. 在 `MarketStatusDetector` 中注册算法
3. 在命令行参数中添加选项

### 添加新可视化

1. 在 `market_status_visualizer.py` 中添加新的可视化类
2. 实现生成逻辑
3. 在命令行参数中添加输出选项

### 添加新回测策略

1. 在 `market_aware_backtest.py` 中扩展 `MarketAwareBacktestEngine`
2. 实现新的状态变化处理逻辑
3. 添加相应的命令行参数

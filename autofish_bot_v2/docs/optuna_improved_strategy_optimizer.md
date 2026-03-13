# Optuna Improved Strategy 参数优化器

## 模块概述

**源文件**: `optuna_improved_strategy_optimizer.py`

**功能**: 使用贝叶斯优化（Optuna）对 Improved 行情判断算法和交易策略参数进行联合优化，寻找在特定市场环境下表现最优的参数组合。

## 核心原理

该模块通过定义一个目标函数（Objective Function），将回测系统的各项指标（净利润、胜率、回撤等）综合为一个评分。Optuna 算法会自动探索参数空间，寻找使评分最大化的参数组合。

### 优化目标

优化目标是一个综合得分（Score），计算公式如下：

```python
score = (
    profit_score * 0.5 +    # 净利润得分 (权重 50%)
    winrate_score * 0.3 +   # 胜率得分 (权重 30%)
    trading_score * 0.2     # 交易活跃度得分 (权重 20%)
)
```

- **净利润得分**: 将净利润归一化到 [-1, 2] 区间。
- **胜率得分**: 直接使用胜率 (0-1)。
- **交易活跃度得分**: 交易时间占比 (0-1)，鼓励策略在震荡行情中积极交易。

## 优化参数空间

优化器同时调整两类参数：

### 1. 行情判断参数 (Market Params)
用于 `ImprovedStatusAlgorithm`，决定如何识别震荡和趋势。

| 参数名 | 范围 | 说明 |
|--------|------|------|
| `lookback_period` | 40 - 90 (int) | 回看周期，用于识别支撑阻力位 |
| `min_range_duration` | 5 - 20 (int) | 最小震荡持续天数 |
| `max_range_pct` | 0.10 - 0.25 (float) | 震荡区间的最大宽度比例 |
| `breakout_threshold` | 0.02 - 0.05 (float) | 突破阈值 |
| `swing_window` | 3 - 7 (int) | 识别高低点的窗口大小 |
| `merge_threshold` | 0.02 - 0.05 (float) | 合并相近支撑阻力位的阈值 |
| `min_touches` | 2 - 5 (int) | 支撑阻力位的最小触及次数 |

### 2. 交易策略参数 (Strategy Params)
用于 `Autofish` 策略，决定具体的交易执行。

| 参数名 | 范围 | 说明 |
|--------|------|------|
| `grid_spacing` | 0.005 - 0.02 (float) | 网格间距 (0.5% - 2%) |
| `exit_profit` | 0.005 - 0.02 (float) | 止盈比例 |
| `stop_loss` | 0.05 - 0.12 (float) | 止损比例 |
| `decay_factor` | 0.3 - 0.7 (float) | 资金衰减因子 |
| `max_entries` | 2 - 6 (int) | 最大加仓层数 |

## 使用方法

### 命令行运行

```bash
# 基本用法：运行 50 次试验
python optuna_improved_strategy_optimizer.py --symbol BTCUSDT --date-range 20230101-20231231 --n-trials 50

# 增加试验次数以获得更好结果
python optuna_improved_strategy_optimizer.py --symbol ETHUSDT --date-range 20230101-20231231 --n-trials 100
```

### 输出结果

1.  **控制台输出**: 实时显示每次试验的参数和得分，以及最终的最佳参数。
2.  **结果文件**: `out/market_optimization/optuna_improved_results.csv`，包含所有试验的详细数据。
3.  **优化报告**: `out/market_optimization/optuna_improved_report.md`，包含最佳参数总结、参数重要性分析和使用建议。

## 类结构

### OptunaImprovedStrategyOptimizer

主优化器类。

#### 方法

- `__init__(symbol, date_range)`: 初始化优化器。
- `run(n_trials)`: 启动优化过程。
- `objective(trial)`: Optuna 的目标函数，执行单次优化试验。
- `_run_backtest(market_params, strategy_params)`: 调用 `MarketAwareBacktestEngine` 执行回测。
- `_calculate_score(results)`: 计算回测结果的综合得分。
- `_generate_report(study)`: 生成 Markdown 格式的优化报告。

## 依赖

- `optuna`: 贝叶斯优化框架
- `pandas`: 数据处理
- `market_aware_backtest`: 回测引擎
- `market_status_detector`: 行情判断模块

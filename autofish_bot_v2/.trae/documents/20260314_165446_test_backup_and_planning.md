# 测试文件备份与完整测试规划

## 1. 任务概述

### 1.1 目标

1. **备份原有测试文件**：将现有测试文件备份到 `out/test_old_bak` 目录
2. **建立完整测试规划**：创建覆盖所有测试类型的测试计划

### 1.2 统一测试参数

| 参数 | 值 |
|------|-----|
| 时间范围 | 20200101-20260310 |
| 标的 | BTCUSDT |
| 风险因子 | 0.5 |

## 2. 备份方案

### 2.1 备份目录结构

```
out/test_old_bak/
├── autofish/                    # 振幅分析和普通回测
│   ├── binance_BTCUSDT_*.md
│   ├── binance_ETHUSDT_*.md
│   └── ...
├── market_backtest/             # 行情感知回测
│   ├── binance_BTCUSDT_*.md
│   └── ...
├── market_visualizer/           # 行情可视化
│   ├── market_visualizer_*.md
│   ├── market_visualizer_*.png
│   └── market_visualizer_*.html
├── market_optimization/         # 参数优化
│   ├── *_optimization_*.md
│   └── *_optimization_*.csv
└── database/                    # 数据库备份
    └── market_visualizer.db
```

### 2.2 备份命令

```bash
# 创建备份目录
mkdir -p out/test_old_bak/autofish
mkdir -p out/test_old_bak/market_backtest
mkdir -p out/test_old_bak/market_visualizer
mkdir -p out/test_old_bak/market_optimization
mkdir -p out/test_old_bak/database

# 移动文件
mv out/autofish/*.md out/test_old_bak/autofish/ 2>/dev/null
mv out/market_backtest/*.md out/test_old_bak/market_backtest/ 2>/dev/null
mv out/market_visualizer/* out/test_old_bak/market_visualizer/ 2>/dev/null
mv out/market_optimization/* out/test_old_bak/market_optimization/ 2>/dev/null

# 备份数据库
cp database/market_visualizer.db out/test_old_bak/database/ 2>/dev/null

# 清空数据库（保留表结构）
sqlite3 database/market_visualizer.db "DELETE FROM market_status; DELETE FROM klines; DELETE FROM visualization_cache;" 2>/dev/null
```

## 3. 测试规划

### 3.1 测试计划列表

| 计划ID | 测试名称 | 测试类型 | 执行器 | 场景数 |
|--------|----------|----------|--------|--------|
| TP001 | BTCUSDT基础回测 | backtest | binance_backtest.py | 2 |
| TP002 | BTCUSDT行情感知回测 | market_aware | market_aware_backtest.py | 4 |
| TP003 | BTCUSDT行情可视化 | visualizer | market_status_visualizer.py | 5 |
| TP004 | Dual Thrust参数优化 | optimization | optuna_dual_thrust_optimizer.py | 1 |
| TP005 | Improved参数优化 | optimization | optuna_improved_strategy_optimizer.py | 1 |

**总计**: 5个测试计划，13个测试场景

### 3.2 详细测试计划

#### TP001: BTCUSDT基础回测

```json
{
  "plan_id": "TP001",
  "plan_name": "BTCUSDT基础回测",
  "test_type": "backtest",
  "test_parameters": {
    "symbol": "BTCUSDT",
    "date_range": "20200101-20260310",
    "decay_factor": 0.5
  },
  "test_scenarios": [
    {"scenario_id": "S001", "name": "激进策略(d=0.5)", "params": {"decay_factor": 0.5}},
    {"scenario_id": "S002", "name": "保守策略(d=1.0)", "params": {"decay_factor": 1.0}}
  ]
}
```

#### TP002: BTCUSDT行情感知回测

```json
{
  "plan_id": "TP002",
  "plan_name": "BTCUSDT行情感知回测",
  "test_type": "market_aware",
  "test_parameters": {
    "symbol": "BTCUSDT",
    "date_range": "20200101-20260310",
    "decay_factor": 0.5,
    "market_algorithm": "dual_thrust"
  },
  "test_scenarios": [
    {"scenario_id": "S001", "name": "只做震荡(默认)", "params": {"trading_statuses": ["ranging"], "down_confirm_days": 1, "k2_down_factor": 0.6}},
    {"scenario_id": "S002", "name": "只做震荡(保守)", "params": {"trading_statuses": ["ranging"], "down_confirm_days": 2, "k2_down_factor": 0.8}},
    {"scenario_id": "S003", "name": "只做震荡(激进)", "params": {"trading_statuses": ["ranging"], "down_confirm_days": 1, "k2_down_factor": 0.4}},
    {"scenario_id": "S004", "name": "震荡+上涨", "params": {"trading_statuses": ["ranging", "trending_up"], "down_confirm_days": 1, "k2_down_factor": 0.6}}
  ]
}
```

**Dual Thrust 增强参数说明**：

| 参数 | 说明 | 默认值 | 测试范围 |
|------|------|--------|----------|
| down_confirm_days | 下跌确认天数 | 1 | 1-3 |
| k2_down_factor | 下跌敏感因子 | 0.6 | 0.4-0.8 |
| cooldown_days | 状态切换冷却期 | 1 | 1-2 |

#### TP003: BTCUSDT行情可视化

```json
{
  "plan_id": "TP003",
  "plan_name": "BTCUSDT行情可视化",
  "test_type": "visualizer",
  "test_parameters": {
    "symbol": "BTCUSDT",
    "interval": "1d",
    "date_range": "20200101-20260310"
  },
  "test_scenarios": [
    {"scenario_id": "S001", "name": "Dual Thrust (默认)", "params": {"algorithm": "dual_thrust", "down_confirm_days": 1, "k2_down_factor": 0.6}},
    {"scenario_id": "S002", "name": "Dual Thrust (保守)", "params": {"algorithm": "dual_thrust", "down_confirm_days": 2, "k2_down_factor": 0.8}},
    {"scenario_id": "S003", "name": "Dual Thrust (激进)", "params": {"algorithm": "dual_thrust", "down_confirm_days": 1, "k2_down_factor": 0.4}},
    {"scenario_id": "S004", "name": "Dual Thrust (高确认)", "params": {"algorithm": "dual_thrust", "down_confirm_days": 3, "k2_down_factor": 0.6}},
    {"scenario_id": "S005", "name": "Improved算法", "params": {"algorithm": "improved"}}
  ]
}
```

#### TP004: Dual Thrust参数优化

```json
{
  "plan_id": "TP004",
  "plan_name": "Dual Thrust参数优化",
  "test_type": "optimization",
  "test_parameters": {
    "symbol": "BTCUSDT",
    "date_range": "20200101-20260310",
    "algorithm": "dual_thrust",
    "n_trials": 100
  },
  "search_space": {
    "down_confirm_days": {"type": "int", "min": 1, "max": 5},
    "k2_down_factor": {"type": "float", "min": 0.3, "max": 0.8},
    "cooldown_days": {"type": "int", "min": 1, "max": 3}
  }
}
```

#### TP005: Improved参数优化

```json
{
  "plan_id": "TP005",
  "plan_name": "Improved参数优化",
  "test_type": "optimization",
  "test_parameters": {
    "symbol": "BTCUSDT",
    "date_range": "20200101-20260310",
    "algorithm": "improved",
    "n_trials": 100
  },
  "search_space": {
    "breakout_threshold": {"type": "float", "min": 0.01, "max": 0.05},
    "consecutive_bars": {"type": "int", "min": 2, "max": 5}
  }
}
```

## 4. 执行步骤

### 阶段1: 备份原有文件

1. 创建备份目录 `out/test_old_bak/`
2. 移动 autofish 目录下的测试文件
3. 移动 market_backtest 目录下的测试文件
4. 移动 market_visualizer 目录下的测试文件
5. 移动 market_optimization 目录下的测试文件

### 阶段2: 创建测试计划

1. 创建 TP001 基础回测计划
2. 创建 TP002 行情感知回测计划
3. 创建 TP003 行情可视化计划
4. 创建 TP004 Dual Thrust优化计划
5. 创建 TP005 Improved优化计划

### 阶段3: 更新测试历史索引

1. 更新 test_history_index.md
2. 创建 BTCUSDT_history.md

## 5. 预期结果

### 5.1 备份结果

- 所有原有测试文件移动到 `out/test_old_bak/` 对应子目录
- 可视化数据库备份到 `out/test_old_bak/database/market_visualizer.db`
- 原目录保留配置文件（如 amplitude_config.json）
- 数据库数据已清空，保留表结构

### 5.2 测试计划结果

- 5个测试计划文件创建在 `out/test_plans/active/`
- 测试历史索引更新

## 6. 验收标准

1. ✅ 备份目录包含所有原有测试文件
2. ✅ 5个测试计划文件正确创建
3. ✅ 测试计划参数符合统一要求
4. ✅ 测试历史索引正确更新

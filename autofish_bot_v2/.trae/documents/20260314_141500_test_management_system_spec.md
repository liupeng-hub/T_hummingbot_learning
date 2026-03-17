# 测试规划与结果管理系统设计规格

## 1. 背景与问题

### 1.1 当前问题

1. **文件命名混乱**：测试文件命名不统一，难以识别测试场景
   - `binance_BTCUSDT_market_aware_backtest_2261d_20200101-20260310.md`
   - `binance_BTCUSDT_market_aware_backtest_2261d_20200101-20260310_01.md`
   - 无法直观了解测试目的和参数

2. **测试记录分散**：没有统一的测试历史记录
   - 测试结果分散在多个文件中
   - 难以对比不同测试的结果

3. **缺乏测试规划**：没有测试计划驱动测试执行
   - 测试随意性强
   - 无法追踪测试目的和预期

4. **历史对比困难**：无法快速对比历史测试结果
   - 参数变化难以追踪
   - 结果变化原因不明确

### 1.2 目标

1. 建立统一的测试规划文件格式
2. 建立规范的测试结果记录格式
3. 实现测试规划驱动测试执行
4. 实现测试历史对比分析

## 2. 系统架构

### 2.1 目录结构

```
out/
├── test_plans/                          # 测试规划目录
│   ├── active/                          # 活跃测试计划
│   │   ├── TP001_backtest_btcusdt_baseline.json
│   │   ├── TP002_market_aware_dual_thrust.json
│   │   ├── TP003_visualizer_btcusdt_analysis.json
│   │   └── TP004_optimization_dual_thrust.json
│   ├── completed/                       # 已完成测试计划
│   │   └── TP001_backtest_btcusdt_baseline.json
│   └── archived/                        # 归档测试计划
│
├── test_results/                        # 测试结果目录
│   ├── backtest/                        # 普通回测结果
│   │   ├── TP001/                       # 按测试计划ID组织
│   │   │   ├── TP001_S001_result.md     # 测试结果报告
│   │   │   ├── TP001_S002_result.md
│   │   │   └── TP001_summary.md         # 测试汇总
│   │   └── TP005/
│   │       └── ...
│   ├── market_aware/                    # 行情感知回测结果
│   │   ├── TP002/
│   │   │   ├── TP002_S001_result.md
│   │   │   ├── TP002_S002_result.md
│   │   │   └── TP002_summary.md
│   │   └── TP006/
│   │       └── ...
│   ├── visualizer/                      # 可视化测试结果
│   │   ├── TP003/
│   │   │   ├── TP003_S001_result.md
│   │   │   ├── TP003_S001_chart.png
│   │   │   └── TP003_S001_chart.html
│   │   └── ...
│   ├── optimization/                    # 优化测试结果
│   │   ├── TP004/
│   │   │   ├── TP004_result.csv
│   │   │   ├── TP004_result.md
│   │   │   └── TP004_best_params.json
│   │   └── ...
│   └── amplitude/                       # 振幅分析结果
│       └── TP007/
│           └── ...
│
├── test_history/                        # 测试历史记录
│   ├── test_history_index.md            # 测试历史索引
│   ├── BTCUSDT_history.md               # 按标的分组的历史
│   └── ETHUSDT_history.md
│
└── test_comparison/                     # 测试对比分析
    ├── comparison_001.md                 # 对比报告
    └── comparison_index.md              # 对比索引
```

### 2.2 核心概念

| 概念 | 说明 |
|------|------|
| TestPlan | 测试计划，定义测试目的、参数、预期结果 |
| TestResult | 测试结果，记录单次测试的实际结果 |
| TestHistory | 测试历史，按标的/策略分组的历史记录 |
| TestComparison | 测试对比，多组测试结果的对比分析 |

### 2.3 测试模块类型

| 模块类型 | 执行器 | 输出目录 | 说明 |
|----------|--------|----------|------|
| 普通回测 | `binance_backtest.py` | `test_results/backtest/` | Binance历史数据回测（无行情感知） |
| 行情感知回测 | `market_aware_backtest.py` | `test_results/market_aware/` | 结合行情状态的策略回测 |
| 行情可视化 | `market_status_visualizer.py` | `test_results/visualizer/` | K线图可视化分析 |
| 参数优化 | `optuna_dual_thrust_optimizer.py` | `test_results/optimization/` | Dual Thrust参数优化 |
| 参数优化 | `optuna_improved_strategy_optimizer.py` | `test_results/optimization/` | Improved策略参数优化 |
| 振幅分析 | `autofish_core.py` | `test_results/amplitude/` | 振幅概率分布分析 |

### 2.4 测试类型对比

| 对比项 | 普通回测 | 行情感知回测 |
|--------|----------|--------------|
| 执行器 | `binance_backtest.py` | `market_aware_backtest.py` |
| 行情感知 | ❌ 无 | ✅ 有 |
| 交易控制 | 始终交易 | 根据行情状态动态控制 |
| 输出指标 | 交易统计 | 交易统计 + 行情状态统计 |
| 适用场景 | 基准测试、策略验证 | 行情感知效果验证 |

## 3. 测试规划文件格式

### 3.1 普通回测测试计划示例 (TP001_backtest_btcusdt_baseline.json)

```json
{
  "plan_id": "TP001",
  "plan_name": "BTCUSDT 基准回测",
  "description": "BTCUSDT 普通回测基准测试，无行情感知",
  "created_at": "2026-03-14T10:00:00",
  "status": "active",
  "test_type": "backtest",
  
  "test_objective": {
    "primary": "建立 BTCUSDT 回测基准数据",
    "secondary": [
      "对比不同 decay_factor 效果",
      "验证策略基本表现"
    ]
  },
  
  "test_parameters": {
    "symbol": "BTCUSDT",
    "interval": "1h",
    "limit": 500,
    "strategy_params": {
      "decay_factor": 0.5,
      "stop_loss": 0.08,
      "total_amount": 10000
    }
  },
  
  "test_scenarios": [
    {
      "scenario_id": "S001",
      "name": "激进策略 (d=0.5)",
      "params": {
        "decay_factor": 0.5
      }
    },
    {
      "scenario_id": "S002",
      "name": "保守策略 (d=1.0)",
      "params": {
        "decay_factor": 1.0
      }
    }
  ],
  
  "expected_results": {
    "metrics": ["total_trades", "win_rate", "net_profit", "max_drawdown"],
    "comparison": "S001 预期交易次数更多，S002 预期胜率更高"
  },
  
  "execution": {
    "executor": "binance_backtest.py",
    "command_template": "python binance_backtest.py --symbol {symbol} --interval {interval} --limit {limit} --decay-factor {decay_factor}"
  }
}
```

### 3.2 行情感知回测测试计划示例 (TP002_market_aware_dual_thrust.json)

```json
{
  "plan_id": "TP002",
  "plan_name": "行情感知 Dual Thrust 策略测试",
  "description": "测试 Dual Thrust 算法在行情感知模式下的表现",
  "created_at": "2026-03-14T12:00:00",
  "status": "active",
  "test_type": "market_aware",
  
  "test_objective": {
    "primary": "验证行情感知功能对策略收益的影响",
    "secondary": [
      "对比只做震荡 vs 震荡+上涨策略",
      "验证超时重挂功能效果"
    ]
  },
  
  "test_parameters": {
    "symbol": "BTCUSDT",
    "date_range": "20200101-20260310",
    "market_algorithm": "dual_thrust",
    "market_aware": {
      "enabled": true,
      "trading_statuses": ["ranging"]
    },
    "strategy_params": {
      "decay_factor": 0.5,
      "stop_loss": 0.08,
      "total_amount": 10000
    }
  },
  
  "test_scenarios": [
    {
      "scenario_id": "S001",
      "name": "只做震荡 (超时=0)",
      "params": {
        "market_aware.trading_statuses": ["ranging"],
        "first_entry_timeout": 0
      }
    },
    {
      "scenario_id": "S002",
      "name": "只做震荡 (超时=10)",
      "params": {
        "market_aware.trading_statuses": ["ranging"],
        "first_entry_timeout": 10
      }
    }
  ],
  
  "expected_results": {
    "metrics": ["total_trades", "win_rate", "net_profit", "trading_time_ratio"],
    "comparison": "S001 vs S002 预期收益差异 < 5%"
  },
  
  "execution": {
    "executor": "market_aware_backtest.py",
    "command_template": "python market_aware_backtest.py --symbol {symbol} --date-range {date_range} --market-algorithm {market_algorithm} ..."
  }
}
```

### 3.3 测试计划状态

| 状态 | 说明 |
|------|------|
| draft | 草稿，规划中 |
| active | 活跃，可执行测试 |
| running | 执行中 |
| completed | 已完成，所有场景已测试 |
| archived | 已归档 |

### 3.4 可视化测试计划示例 (TP003_visualizer_btcusdt_analysis.json)

```json
{
  "plan_id": "TP003",
  "plan_name": "BTCUSDT 行情可视化分析",
  "description": "使用不同算法分析 BTCUSDT 行情状态",
  "created_at": "2026-03-14T14:00:00",
  "status": "active",
  "test_type": "visualizer",
  
  "test_objective": {
    "primary": "对比不同行情算法的可视化效果",
    "secondary": [
      "验证 dual_thrust 算法识别效果",
      "验证 improved 算法识别效果"
    ]
  },
  
  "test_parameters": {
    "symbol": "BTCUSDT",
    "interval": "1d",
    "date_range": "20200101-20260310"
  },
  
  "test_scenarios": [
    {
      "scenario_id": "S001",
      "name": "Dual Thrust 算法",
      "params": {
        "algorithm": "dual_thrust"
      },
      "expected_output": ["md", "png", "html"]
    },
    {
      "scenario_id": "S002",
      "name": "Improved 算法",
      "params": {
        "algorithm": "improved"
      },
      "expected_output": ["md", "png", "html"]
    }
  ],
  
  "execution": {
    "executor": "market_status_visualizer.py",
    "command_template": "python market_status_visualizer.py --symbol {symbol} --interval {interval} --date-range {date_range} --algorithm {algorithm} --generate-all"
  }
}
```

### 3.5 参数优化测试计划示例 (TP004_optimization_dual_thrust.json)

```json
{
  "plan_id": "TP004",
  "plan_name": "Dual Thrust 参数优化",
  "description": "使用 Optuna 优化 Dual Thrust 算法参数",
  "created_at": "2026-03-14T15:00:00",
  "status": "active",
  "test_type": "optimization",
  
  "test_objective": {
    "primary": "找到 Dual Thrust 算法的最优参数组合",
    "secondary": [
      "验证 down_confirm_days 参数影响",
      "验证 k2_down_factor 参数影响"
    ]
  },
  
  "test_parameters": {
    "symbol": "BTCUSDT",
    "date_range": "20200101-20260310",
    "algorithm": "dual_thrust",
    "n_trials": 100,
    "optimization_metric": "net_profit"
  },
  
  "search_space": {
    "down_confirm_days": {"type": "int", "min": 1, "max": 5},
    "k2_down_factor": {"type": "float", "min": 0.3, "max": 0.8},
    "cooldown_days": {"type": "int", "min": 1, "max": 3}
  },
  
  "expected_results": {
    "metrics": ["best_net_profit", "best_params", "optimization_history"],
    "output_files": ["result.csv", "result.md", "best_params.json"]
  },
  
  "execution": {
    "executor": "optuna_dual_thrust_optimizer.py",
    "command_template": "python optuna_dual_thrust_optimizer.py --symbol {symbol} --date-range {date_range} --n-trials {n_trials}"
  }
}
```

## 4. 测试结果文件格式

### 4.1 普通回测结果文件 (test_results/backtest/TP001/TP001_S001_result.md)

```markdown
# 测试结果报告

## 测试信息

| 项目 | 值 |
|------|-----|
| 测试计划 | TP001 - BTCUSDT 基准回测 |
| 测试场景 | S001 - 激进策略 (d=0.5) |
| 测试类型 | backtest |
| 执行时间 | 2026-03-14 10:30:00 |
| 执行命令 | `python binance_backtest.py --symbol BTCUSDT --interval 1h --limit 500 --decay-factor 0.5` |

## 测试参数

| 参数 | 值 |
|------|-----|
| 标的 | BTCUSDT |
| K线周期 | 1h |
| K线数量 | 500 |
| 衰减因子 | 0.5 |
| 止损比例 | 8% |

## 测试结果

### 核心指标

| 指标 | 值 |
|------|-----|
| 总交易 | 156 |
| 胜率 | 78.5% |
| 净收益 | 12,345.67 USDT |
| 收益率 | 123.45% |
| 最大回撤 | 15.2% |

---
测试ID: TP001_S001_20260314_103000
```

### 4.2 行情感知回测结果文件 (test_results/market_aware/TP002/TP002_S001_result.md)

```markdown
# 测试结果报告

## 测试信息

| 项目 | 值 |
|------|-----|
| 测试计划 | TP001 - 行情感知 Dual Thrust 策略测试 |
| 测试场景 | S001 - 只做震荡 (超时=0) |
| 执行时间 | 2026-03-14 12:30:00 |
| 执行命令 | `python market_aware_backtest.py --symbol BTCUSDT ...` |

## 测试参数

| 参数 | 值 |
|------|-----|
| 标的 | BTCUSDT |
| 日期范围 | 2020-01-01 ~ 2026-03-10 |
| 行情算法 | dual_thrust |
| 交易状态 | ranging |
| 超时设置 | 0 分钟 |

## 测试结果

### 核心指标

| 指标 | 值 |
|------|-----|
| 总交易 | 1,803 |
| 胜率 | 83.47% |
| 净收益 | 54,187.68 USDT |
| 收益率 | 1083.75% |
| 交易时间占比 | 64.4% |

### 详细数据

[详细测试数据...]

## 测试结论

[测试结论分析...]

---
测试ID: TP001_S001_20260314_123000
```

### 4.3 测试汇总文件 (test_results/market_aware/TP002/TP002_summary.md)

```markdown
# 测试计划汇总报告

## 测试计划信息

| 项目 | 值 |
|------|-----|
| 测试计划 | TP001 - 行情感知 Dual Thrust 策略测试 |
| 创建时间 | 2026-03-14 12:00:00 |
| 完成时间 | 2026-03-14 13:00:00 |
| 测试场景数 | 5 |
| 完成场景数 | 5 |

## 场景对比

| 场景 | 总交易 | 胜率 | 净收益 | 收益率 |
|------|--------|------|--------|--------|
| S001 只做震荡 (超时=0) | 1,803 | 83.47% | 54,187.68 | 1083.75% |
| S002 只做震荡 (超时=10) | 1,803 | 83.47% | 54,187.68 | 1083.75% |
| S003 震荡+上涨 (超时=0) | 1,279 | 84.68% | 50,875.22 | 1017.50% |
| S004 震荡+上涨 (超时=10) | 1,279 | 84.68% | 50,875.22 | 1017.50% |
| S005 震荡+上涨 (超时=5) | 1,279 | 84.68% | 50,875.22 | 1017.50% |

## 结论

1. 超时重挂功能对结果影响极小
2. 只做震荡策略收益更高

## 建议

[改进建议...]
```

## 5. 测试历史记录

### 5.1 测试历史索引 (test_history/test_history_index.md)

```markdown
# 测试历史索引

## 按标的分组

| 标的 | 测试次数 | 最近测试 | 历史文件 |
|------|----------|----------|----------|
| BTCUSDT | 25 | 2026-03-14 | [BTCUSDT_history.md](BTCUSDT_history.md) |
| ETHUSDT | 5 | 2026-03-13 | [ETHUSDT_history.md](ETHUSDT_history.md) |

## 按策略分组

| 策略 | 测试次数 | 最近测试 |
|------|----------|----------|
| 行情感知 | 15 | 2026-03-14 |
| 普通回测 | 10 | 2026-03-13 |

## 最近测试

| 日期 | 测试计划 | 标的 | 策略 | 结果 |
|------|----------|------|------|------|
| 2026-03-14 | TP001 | BTCUSDT | 行情感知 | [查看](../test_results/TP001/TP001_summary.md) |
```

### 5.2 标的历史记录 (test_history/BTCUSDT_history.md)

```markdown
# BTCUSDT 测试历史

## 测试记录

| 测试ID | 日期 | 测试计划 | 策略 | 总交易 | 胜率 | 净收益 | 收益率 |
|--------|------|----------|------|--------|------|--------|--------|
| TP001_S001 | 2026-03-14 | 行情感知 | 只做震荡 | 1,803 | 83.47% | 54,187.68 | 1083.75% |
| TP001_S003 | 2026-03-14 | 行情感知 | 震荡+上涨 | 1,279 | 84.68% | 50,875.22 | 1017.50% |

## 参数变化追踪

| 测试ID | decay_factor | stop_loss | market_aware | 备注 |
|--------|--------------|-----------|--------------|------|
| TP001_S001 | 0.5 | 0.08 | ranging | 基准测试 |
| TP001_S003 | 0.5 | 0.08 | ranging+up | 增加上涨交易 |

## 收益趋势

[收益趋势图表...]
```

## 6. 测试对比分析

### 6.1 对比报告 (test_comparison/comparison_001.md)

```markdown
# 测试对比报告

## 对比信息

| 项目 | 值 |
|------|-----|
| 对比ID | CMP001 |
| 对比名称 | 行情感知策略对比 |
| 创建时间 | 2026-03-14 14:00:00 |
| 对比测试 | TP001_S001, TP001_S003 |

## 对比维度

### 1. 收益对比

| 测试 | 净收益 | 收益率 | 差异 |
|------|--------|--------|------|
| TP001_S001 (只做震荡) | 54,187.68 | 1083.75% | 基准 |
| TP001_S003 (震荡+上涨) | 50,875.22 | 1017.50% | -6.1% |

### 2. 交易频率对比

| 测试 | 总交易 | 胜率 | 差异 |
|------|--------|------|------|
| TP001_S001 | 1,803 | 83.47% | 基准 |
| TP001_S003 | 1,279 | 84.68% | -29% |

## 结论

只做震荡策略收益更高，震荡+上涨策略胜率略高但交易次数减少。

## 建议

推荐使用只做震荡策略。
```

## 7. 测试执行流程

### 7.1 创建测试计划

```bash
# 创建测试计划
python test_manager.py create-plan \
  --name "行情感知 Dual Thrust 策略测试" \
  --description "测试 Dual Thrust 算法在行情感知模式下的表现" \
  --symbol BTCUSDT \
  --date-range 20200101-20260310 \
  --scenarios scenarios.json
```

### 7.2 执行测试计划

```bash
# 执行测试计划
python test_manager.py run-plan --plan-id TP001

# 执行单个场景
python test_manager.py run-scenario --plan-id TP001 --scenario-id S001
```

### 7.3 生成对比报告

```bash
# 生成对比报告
python test_manager.py compare \
  --plan-id TP001 \
  --scenarios S001,S002,S003
```

### 7.4 查看历史

```bash
# 查看标的历史
python test_manager.py history --symbol BTCUSDT

# 查看测试计划历史
python test_manager.py history --plan-id TP001
```

## 8. 文件命名规范

### 8.1 测试计划文件

```
test_plans/active/TP{序号}_{简短描述}.json
```

示例：
- `TP001_market_aware_dual_thrust.json`
- `TP002_entry_strategy_comparison.json`

### 8.2 测试结果文件

```
test_results/TP{计划序号}/TP{计划序号}_S{场景序号}_result.md
test_results/TP{计划序号}/TP{计划序号}_summary.md
```

示例：
- `test_results/TP001/TP001_S001_result.md`
- `test_results/TP001/TP001_summary.md`

### 8.3 测试历史文件

```
test_history/test_history_index.md
test_history/{标的}_history.md
```

示例：
- `test_history/test_history_index.md`
- `test_history/BTCUSDT_history.md`

## 9. 实现计划

### 阶段1：创建测试管理器

1. 创建 `test_manager.py` 测试管理器
2. 实现测试计划创建、读取、更新功能
3. 实现测试执行功能

### 阶段2：改造现有回测模块

1. 修改 `market_aware_backtest.py` 支持测试计划驱动
2. 修改 `binance_backtest.py` 支持测试计划驱动
3. 统一结果输出格式

### 阶段3：创建历史记录系统

1. 实现测试历史记录功能
2. 实现历史对比功能
3. 创建历史索引

### 阶段4：迁移现有数据

1. 分析现有测试文件
2. 创建对应的测试计划
3. 迁移测试结果到新格式

## 10. 验收标准

1. ✅ 测试计划可以创建、执行、归档
2. ✅ 测试结果按计划ID组织
3. ✅ 测试历史可以按标的、策略查询
4. ✅ 测试对比报告可以自动生成
5. ✅ 文件命名规范统一

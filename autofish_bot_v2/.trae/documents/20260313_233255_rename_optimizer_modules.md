# 重命名优化器模块计划

## 背景

当前命名不够清晰，建议改进：
- `module_architecture.md` → `market_module_architecture.md` (更明确是市场模块架构)
- `dual_thrust_optimizer.py` → `optuna_dual_thrust_optimizer.py` (标明使用Optuna优化框架)
- `market_strategy_optimizer.py` → `optuna_improved_strategy_optimizer.py` (标明优化的是Improved算法)

## 修改范围

### 1. 文件重命名

| 原文件名 | 新文件名 |
|----------|----------|
| `docs/module_architecture.md` | `docs/market_module_architecture.md` |
| `dual_thrust_optimizer.py` | `optuna_dual_thrust_optimizer.py` |
| `market_strategy_optimizer.py` | `optuna_improved_strategy_optimizer.py` |
| `docs/market_strategy_optimizer.md` | `docs/optuna_improved_strategy_optimizer.md` |

### 2. optuna_dual_thrust_optimizer.py 内部修改

- 类名: `DualThrustOptimizer` → `OptunaDualThrustOptimizer`
- 日志名: `dual_thrust_optimizer` → `optuna_dual_thrust_optimizer`
- 输出文件名:
  - `dual_thrust_optimization_results.csv` → `optuna_dual_thrust_results.csv`
  - `dual_thrust_optimization_report.md` → `optuna_dual_thrust_report.md`

### 3. optuna_improved_strategy_optimizer.py 内部修改

- 类名: `MarketStrategyOptimizer` → `OptunaImprovedStrategyOptimizer`
- 日志名: `market_strategy_optimizer` → `optuna_improved_strategy_optimizer`
- 输出文件名:
  - `optimization_results.csv` → `optuna_improved_results.csv`
  - `optimization_report.md` → `optuna_improved_report.md`

### 4. 文档更新

#### docs/market_module_architecture.md
- 更新模块表格中的文件名引用
- 更新使用示例中的命令

#### docs/optuna_improved_strategy_optimizer.md (原 market_strategy_optimizer.md)
- 更新源文件名引用
- 更新类名
- 更新命令示例

#### README.md
- 更新核心模块表格
- 更新文档链接 `module_architecture.md` → `market_module_architecture.md`
- 新增优化器模块说明

## 执行步骤

1. 重命名 `docs/module_architecture.md` → `docs/market_module_architecture.md`
2. 重命名 `dual_thrust_optimizer.py` → `optuna_dual_thrust_optimizer.py`
3. 修改 `optuna_dual_thrust_optimizer.py` 内部类名、日志名、输出文件名
4. 重命名 `market_strategy_optimizer.py` → `optuna_improved_strategy_optimizer.py`
5. 修改 `optuna_improved_strategy_optimizer.py` 内部类名、日志名、输出文件名
6. 重命名 `docs/market_strategy_optimizer.md` → `docs/optuna_improved_strategy_optimizer.md`
7. 更新 `docs/optuna_improved_strategy_optimizer.md` 内容
8. 更新 `docs/market_module_architecture.md` 内容
9. 更新 `README.md` 引用和内容

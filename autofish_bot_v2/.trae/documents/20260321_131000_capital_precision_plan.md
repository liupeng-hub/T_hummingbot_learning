# 数据精度调整计划

## 目标
对多个表中的金额和数值字段进行精度调整。

## 需要修改的字段

### 1. capital_statistics 表 - 保留 2 位小数
- final_capital
- trading_capital
- profit_pool
- total_return
- total_profit
- total_loss
- max_capital
- max_drawdown
- avg_profit
- avg_loss
- win_rate

### 2. capital_history 表 - 保留 2 位小数
- old_capital
- new_capital
- profit

### 3. trade_details 表
- entry_price - 保留 2 位小数
- exit_price - 保留 2 位小数
- quantity - 保留 6 位小数

### 4. test_results 表 - 保留 2 位小数
- win_rate
- total_profit
- total_loss
- net_profit
- roi
- price_change
- excess_return
- profit_factor
- sharpe_ratio
- max_profit_trade
- max_loss_trade
- trading_time_ratio
- stopped_time_ratio

## 实施步骤

### 步骤 1: 修改 autofish_core.py
**修改内容**:
- `FixedCapitalTracker.get_statistics` - 数值 round(x, 2)
- `ProgressiveCapitalTracker.get_statistics` - 数值 round(x, 2)
- `ProgressiveCapitalTracker.update_capital` - capital_history 精度处理

### 步骤 2: 修改 binance_backtest.py
**修改内容**:
- 保存 trade_details 时对 entry_price, exit_price 使用 round(x, 2)
- 对 quantity 使用 round(x, 6)
- 保存 test_results 时对相关字段使用 round(x, 2)

### 步骤 3: 数据库迁移（可选）
添加迁移逻辑将现有数据四舍五入到指定精度。

## 代码修改清单

| 文件 | 修改位置 | 修改内容 |
|------|----------|----------|
| `autofish_core.py` | FixedCapitalTracker.get_statistics | 数值 round(x, 2) |
| `autofish_core.py` | ProgressiveCapitalTracker.get_statistics | 数值 round(x, 2) |
| `autofish_core.py` | ProgressiveCapitalTracker.update_capital | capital_history 精度处理 |
| `binance_backtest.py` | 保存 trade_details | entry_price/exit_price round(x, 2), quantity round(x, 6) |
| `binance_backtest.py` | 保存 test_results | 相关字段 round(x, 2) |

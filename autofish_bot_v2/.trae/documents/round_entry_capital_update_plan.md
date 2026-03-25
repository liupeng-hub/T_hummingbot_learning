# 同一轮次交易资金更新问题修复计划

## 问题描述

当前实现中，当一个订单盈利或亏损后，同一轮次中的后续新订单的 `entry_capital`（交易资金/入场资金）没有相应更新。

### 预期行为
- 在复利策略下，A1 盈利后，A2 应该使用更新后的总资金作为交易资金
- 在保守/稳健策略下，A1 盈利后，A2 的交易资金也应该反映资金池的变化

### 当前行为
- `round_entry_capital` 只在 A1 成交时设置一次
- 后续 A2/A3/A4 成交时，仍然使用 A1 成交时的 `round_entry_capital`
- 这导致同一轮次中，所有订单的 `entry_capital` 都相同，没有反映资金变化

## 问题分析

### 代码位置
文件：`binance_backtest.py`

#### 1. 入场时设置交易资金（第 283-307 行）
```python
if pending_order.level == 1:
    self.chain_state.round_entry_capital = total_capital  # 只在 A1 时设置
    self.chain_state.round_entry_total_capital = total_capital

pending_order.entry_capital = self.chain_state.round_entry_capital  # A2/A3/A4 使用相同的值
pending_order.entry_total_capital = self.chain_state.round_entry_total_capital
```

#### 2. 出场时更新资金池（第 457-489 行）
- `_update_capital_after_trade` 方法会更新 `capital_pool` 和 `round_entry_total_capital`
- 但没有更新 `round_entry_capital`

### 根本原因
- `round_entry_capital` 代表"入场资金"，用于计算订单金额
- 在复利策略下，这个值应该随着盈亏而变化
- 但当前只在 A1 成交时设置一次，后续订单都复用这个值

## 修复方案

### 方案：在出场后更新 `round_entry_capital`

在 `_update_capital_after_trade` 方法中，根据策略更新 `round_entry_capital`：

1. **复利策略 (fuli)**：
   - `round_entry_capital` = 新的总资金（交易资金 + 利润池）
   - 这样 A2 会使用 A1 盈利后的总资金来计算订单金额

2. **其他策略 (保守/稳健/激进)**：
   - `round_entry_capital` = 交易资金（不含利润池）
   - 这样 A2 会使用更新后的交易资金

3. **固定策略 (guding)**：
   - 保持不变，始终使用初始资金

### 代码修改

文件：`binance_backtest.py`
方法：`_update_capital_after_trade`

```python
def _update_capital_after_trade(self, profit: Decimal, kline_time: datetime = None) -> None:
    # ... 原有代码 ...
    
    # 更新轮次总资金
    new_total_capital = self.capital_pool.trading_capital + (
        self.capital_pool.profit_pool if hasattr(self.capital_pool, 'profit_pool') else Decimal('0')
    )
    self.chain_state.round_entry_total_capital = new_total_capital
    
    # 新增：根据策略更新 round_entry_capital
    if self.capital_pool.strategy == 'fuli':
        # 复利策略：入场资金 = 总资金
        self.chain_state.round_entry_capital = new_total_capital
    elif self.capital_pool.strategy != 'guding':
        # 其他策略（保守/稳健/激进）：入场资金 = 交易资金
        self.chain_state.round_entry_capital = self.capital_pool.trading_capital
    # 固定策略：不更新，保持初始资金
    
    logger.info(f"[轮次资金更新] 总资金={new_total_capital:.2f}, 入场资金={self.chain_state.round_entry_capital:.2f}")
```

## 验证计划

1. 运行回测测试
2. 检查同一轮次中多个订单的 `entry_capital` 是否正确变化
3. 验证资金计算是否正确

## 影响范围

- 修复后，同一轮次中 A2/A3/A4 的 `entry_capital` 会反映 A1 的盈亏
- 这会影响：
  - 订单金额计算（基于 entry_capital * weight）
  - Web 展示的交易详情
  - 资金统计的准确性

## 相关文件

- `binance_backtest.py` - 主要修改文件
- `autofish_core.py` - `Autofish_ChainState` 类定义

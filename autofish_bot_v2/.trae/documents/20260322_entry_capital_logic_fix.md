# 分析：同一 K 线触发多个订单的处理顺序

## 代码分析

### 入场处理顺序

```python
def _process_entry(self, low_price: Decimal, current_price: Decimal, kline_time: datetime = None):
    pending_order = self.chain_state.get_pending_order()  # 只获取一个订单
    if pending_order:
        if Autofish_OrderCalculator.check_entry_triggered(low_price, pending_order.entry_price):
            # 处理入场
            ...
            # 创建下一个订单
            next_level = pending_order.level + 1
            if next_level <= max_level:
                new_order = self._create_order(next_level, pending_order.entry_price)
                self.chain_state.orders.append(new_order)
```

**关键点**：
1. `_process_entry` 只处理一个 `pending_order`
2. `get_pending_order()` 返回第一个 `state == "pending"` 的订单
3. `self.orders` 的顺序是 A1 -> A2 -> A3 -> A4（按创建顺序）

**结论**：同一 K 线只能触发一个订单入场，处理顺序是 A1 -> A2 -> A3 -> A4。

### 出场处理顺序

```python
def _process_exit(self, open_price: Decimal, high_price: Decimal, low_price: Decimal, current_price: Decimal, kline_time: datetime = None):
    filled_orders = self.chain_state.get_filled_orders()  # 获取所有已成交订单
    
    for order in filled_orders:  # 遍历所有已成交订单
        if order.state != "filled":
            continue
        
        # 检查止盈止损
        tp_triggered = high_price >= order.take_profit_price
        sl_triggered = low_price <= order.stop_loss_price
        
        if tp_triggered or sl_triggered:
            # 平仓
            self._close_order(order, ...)
            # 取消挂单
            self.chain_state.cancel_pending_orders()
            # 创建新订单
            new_order = self._create_order(order.level, current_price)
            self.chain_state.orders.append(new_order)
            break  # 只处理一个订单
```

**关键点**：
1. `_process_exit` 遍历所有 `filled_orders`
2. `get_filled_orders()` 返回 `[o for o in self.orders if o.state == "filled"]`
3. `self.orders` 的顺序是 A1 -> A2 -> A3 -> A4（按创建顺序）
4. 处理一个订单后 `break`，所以同一 K 线只能处理一个出场

**结论**：出场处理顺序是 A1 -> A2 -> A3 -> A4，但同一 K 线只能处理一个出场。

## 问题分析

### 数据时间线

| 序号 | 级别 | 入场时间 | 出场时间 | 入场资金 |
|------|------|----------|----------|----------|
| 181 | A1 | 23:52:00 | 00:03:00 | 33385.81 |
| 182 | A2 | 00:02:00 | 00:04:00 | 33385.81 |
| 183 | A2 | 00:07:00 | 00:13:00 | - |
| 184 | A4 | 05:18:00 | 05:18:00 | - |
| 185 | A3 | 05:08:00 | 05:22:00 | - |

### 问题分析

1. **序号 181 (A1)**: 入场时设置 `round_entry_capital = 33385.81`
2. **序号 182 (A2)**: 入场时使用 `round_entry_capital = 33385.81`（正确）
3. **序号 181 (A1)**: 出场时，我之前清除了 `round_entry_capital`（已移除）
4. **序号 183 (A2)**: 入场时，`round_entry_capital` 是 None

**根本原因**：
- A1 出场后，链中还有其他订单（A2、A3、A4）
- 这些订单出场后，会创建新的同级别订单
- 新的 A2 入场时，`round_entry_capital` 是 None
- 因为我的代码只在 A1 入场时设置 `round_entry_capital`

### 正确的业务逻辑

1. **同一轮链式挂单**：A1 入场时设置 `round_entry_capital`，后续 A2/A3/A4 使用相同资金
2. **A1 出场后**：链中可能还有其他订单，不应该清除 `round_entry_capital`
3. **新一轮开始**：当链中没有已成交的订单时，表示新一轮开始，应该重新设置 `round_entry_capital`

## 解决方案

### 方案：当链中没有已成交订单时，设置入场资金

```python
def _process_entry(self, low_price: Decimal, current_price: Decimal, kline_time: datetime = None):
    pending_order = self.chain_state.get_pending_order()
    if pending_order:
        if Autofish_OrderCalculator.check_entry_triggered(low_price, pending_order.entry_price):
            pending_order.set_state("filled", "K线触发入场")
            
            if self.capital_pool.strategy == 'guding':
                pending_order.entry_capital = self.capital_pool.initial_capital
                pending_order.entry_total_capital = self.capital_pool.initial_capital
            else:
                filled_orders = self.chain_state.get_filled_orders()
                if len(filled_orders) == 0:  # 链中没有已成交订单，表示新一轮开始
                    self.chain_state.round_entry_capital = self.capital_pool.trading_capital
                    self.chain_state.round_entry_total_capital = self.capital_pool.trading_capital + (
                        self.capital_pool.profit_pool if hasattr(self.capital_pool, 'profit_pool') else Decimal('0')
                    )
                    logger.info(f"[新一轮开始] 更新入场资金: {self.chain_state.round_entry_capital}")
                
                pending_order.entry_capital = self.chain_state.round_entry_capital
                pending_order.entry_total_capital = self.chain_state.round_entry_total_capital
```

### 关键点

1. **`len(filled_orders) == 0`**：表示链中没有已成交订单，新一轮开始
2. **A1 入场时**：`filled_orders` 为空，设置 `round_entry_capital`
3. **A2/A3/A4 入场时**：`filled_orders` 不为空，使用现有 `round_entry_capital`
4. **A1 出场后**：`filled_orders` 可能不为空（还有 A2/A3/A4），不清除 `round_entry_capital`
5. **新一轮 A1 入场时**：`filled_orders` 为空，重新设置 `round_entry_capital`

## 处理顺序确认

| 场景 | 处理顺序 | 说明 |
|------|----------|------|
| 入场 | A1 -> A2 -> A3 -> A4 | 同一 K 线只能触发一个入场 |
| 出场 | A1 -> A2 -> A3 -> A4 | 同一 K 线只能处理一个出场 |

**注意**：出场后创建的新订单（同级别）会被添加到 `orders` 列表末尾，但不会影响处理顺序。

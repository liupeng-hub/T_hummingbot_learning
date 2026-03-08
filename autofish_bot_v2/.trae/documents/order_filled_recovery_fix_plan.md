# A3 订单成交后未处理问题分析与修复计划

## 问题描述

订单 12680979065 (A3) 昨晚成交了，但：
1. log 中没有看到通告相关的日志
2. 没有挂单 A4
3. 没有更新 A3 的止盈止损单

## 问题分析

### 当前状态文件 (binance_live_state.json)

```json
{
  "level": 3,
  "entry_price": "67068.00",
  "state": "pending",
  "order_id": 12680979065,
  "tp_order_id": null,
  "sl_order_id": null
}
```

### 代码流程分析

#### 1. WebSocket 实时处理流程 (正常情况)

```
ORDER_TRADE_UPDATE 事件
    ↓
_handle_order_update()
    ↓
_handle_order_filled()
    ├── order.state = "filled"
    ├── _place_exit_orders()     ← 下止盈止损单
    ├── notify_entry_filled()    ← 发送通知
    ├── _place_next_level_order() ← 下 A4 入场单
    └── _save_state()
```

#### 2. 状态恢复流程 (程序重启时)

```
_restore_orders()
    ↓
查询 Binance 订单状态 (第 1746-1757 行)
    ↓
if binance_status == "FILLED":
    order.state = "filled"       ← 只更新了状态
    order.entry_price = filled_price
    # ❌ 没有调用后续处理！
```

#### 3. 补单检查流程

```
_check_and_supplement_orders()
    ↓
for order in filled_orders:
    need_tp = not order.tp_order_id
    need_sl = not order.sl_order_id
    if need_tp: _place_tp_order()
    if need_sl: _place_sl_order()
```

### 根本原因

**状态恢复时，只更新了订单状态，没有执行后续处理：**

1. ❌ 没有下止盈止损单
2. ❌ 没有发送通知
3. ❌ 没有下 A4 入场单

虽然 `_check_and_supplement_orders()` 会补止盈止损单，但：
- 它在 `_restore_orders()` 之后调用
- A3 的 `tp_order_id` 和 `sl_order_id` 都是 `null`，会被检测到需要补单
- 但**没有发送通知**和**下 A4 入场单**的逻辑

### 可能的触发场景

1. **WebSocket 断开**：订单成交时 WebSocket 断开，没收到 `ORDER_TRADE_UPDATE` 事件
2. **程序崩溃/重启**：订单成交后程序异常退出，重启时只恢复了状态

## 修复方案

### 方案一：在状态恢复时调用完整的成交处理流程

修改 `_restore_orders()` 方法，当检测到订单从 pending 变为 filled 时，调用 `_handle_order_filled()` 的核心逻辑：

```python
if binance_status == "FILLED":
    filled_price = Decimal(str(binance_order.get("avgPrice", order.entry_price)))
    
    # 标记为需要后续处理
    order.state = "filled"
    order.entry_price = filled_price
    orders_need_process.append(order)  # 新增：记录需要处理的订单

# 在 _restore_orders 结束后，处理这些订单
for order in orders_need_process:
    await self._place_exit_orders(order)      # 下止盈止损单
    notify_entry_filled(order, ...)            # 发送通知
    await self._place_next_level_order(order)  # 下下一级入场单
```

### 方案二：提取成交处理逻辑为独立方法

将 `_handle_order_filled()` 的核心逻辑提取为 `_process_order_filled()`，供实时处理和状态恢复共同调用：

```python
async def _process_order_filled(self, order: Any, filled_price: Decimal) -> None:
    """处理订单成交后的通用逻辑"""
    order.state = "filled"
    order.entry_price = filled_price
    
    await self._place_exit_orders(order)
    notify_entry_filled(order, filled_price, Decimal("0"), self.config)
    await self._place_next_level_order(order)
    self._save_state()

async def _handle_order_filled(self, order: Any, order_data: Dict[str, Any]) -> None:
    """WebSocket 实时成交处理"""
    filled_price = Decimal(str(order_data.get("avgPrice", order.entry_price)))
    await self._process_order_filled(order, filled_price)
```

## 实施步骤

1. **提取成交处理逻辑**
   - 创建 `_process_order_filled()` 方法
   - 包含：下止盈止损单、发送通知、下下一级入场单

2. **修改 WebSocket 处理**
   - `_handle_order_filled()` 调用 `_process_order_filled()`

3. **修改状态恢复逻辑**
   - 在 `_restore_orders()` 中检测订单从 pending 变为 filled
   - 调用 `_process_order_filled()` 执行后续处理

4. **添加日志**
   - 在状态恢复时记录"检测到订单成交，执行后续处理"

## 测试验证

1. 模拟场景：手动修改状态文件，将 pending 订单的 order_id 改为已成交的订单
2. 重启程序，验证是否正确执行后续处理
3. 检查日志是否包含：
   - 下止盈止损单
   - 发送通知
   - 下 A4 入场单

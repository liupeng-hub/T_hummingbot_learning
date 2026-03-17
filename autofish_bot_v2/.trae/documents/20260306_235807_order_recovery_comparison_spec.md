# 新旧代码订单恢复逻辑对比分析

## 1. 概述

本文档对比 `autofish_bot` (旧代码) 和 `autofish_bot_v2` (新代码) 在启动后订单恢复、删除冗余、补充止盈止损、补充下一级挂单的逻辑差异。

## 2. 订单恢复 (_restore_orders)

### 2.1 方法签名

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 方法名 | `async def _restore_orders(self, current_price: Decimal) -> bool` | `async def _restore_orders(self, current_price: Decimal) -> bool` |
| 返回值 | `bool` (是否需要新订单) | `bool` (是否需要新订单) |

### 2.2 状态加载

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 加载方式 | `self._load_state()` 返回 `ChainState` 对象 | `self._load_state()` 返回 `dict`，再调用 `ChainState.from_dict()` |
| base_price 处理 | `self.chain_state.base_price = current_price` | 无此操作 |

### 2.3 API 调用方式

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 获取 Algo 条件单 | `await self.get_open_algo_orders(symbol)` | `await self.client.get_open_algo_orders(symbol)` |
| 获取持仓 | `await self.get_positions(symbol)` | `await self.client.get_positions(symbol)` |
| 获取历史 Algo 单 | `await self.get_all_algo_orders(symbol, limit=100)` | `await self.client.get_all_algo_orders(symbol, limit=100)` |
| 获取订单状态 | `await self.get_order_status(symbol, order.order_id)` | `await self.client.get_order_status(symbol, order.order_id)` |
| 取消 Algo 单 | `await self.cancel_algo_order(symbol, algo_id)` | `await self.client.cancel_algo_order(symbol, algo_id)` |

### 2.4 订单状态更新

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 设置成交状态 | `order.set_state("filled", "程序重启同步-已成交")` | `order.state = "filled"` |
| 设置平仓状态 | 通过 `orders_to_remove` 删除 | `order.state = "closed"` + `order.close_reason = close_reason` |

### 2.5 平仓检测逻辑

**旧代码**:
```python
if close_reason:
    orders_to_remove.append(order)
    print(f"   ✅ A{order.level} 已平仓，原因: {close_reason}，删除本地订单")
```

**新代码**:
```python
if close_reason:
    order.state = "closed"
    order.close_reason = close_reason
    orders_to_remove.append(order)
    print(f"   ✅ A{order.level} 已平仓，原因: {close_reason}，删除本地订单")
```

**差异**: 新代码在删除前设置了 `order.state = "closed"` 和 `order.close_reason`。

### 2.6 订单删除方式

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 删除方式 | 遍历查找并 `pop(i)` | 直接 `self.chain_state.orders.remove(order)` |

**旧代码**:
```python
for order in orders_to_remove:
    for i, o in enumerate(self.chain_state.orders):
        if o.order_id == order.order_id and o.level == order.level and o.state == order.state:
            self.chain_state.orders.pop(i)
            break
```

**新代码**:
```python
for order in orders_to_remove:
    if order in self.chain_state.orders:
        self.chain_state.orders.remove(order)
```

### 2.7 级别调整逻辑

**旧代码和新代码一致**:
```python
if self.chain_state.orders:
    self.chain_state.orders.sort(key=lambda o: o.level)
    for new_level, order in enumerate(self.chain_state.orders, start=1):
        old_level = order.level
        if old_level != new_level:
            order.level = new_level
```

### 2.8 初始化新状态

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 无保存状态时 | `self.chain_state = ChainState(base_price=current_price)` | `self.chain_state = ChainState(base_price=current_price, orders=[])` |

## 3. 补充止盈止损 (_check_and_supplement_orders)

### 3.1 方法签名

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 方法名 | `async def _check_and_supplement_orders(self)` | `async def _check_and_supplement_orders(self) -> None` |
| 返回值 | 无 | `None` |

### 3.2 API 调用方式

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 获取 Algo 条件单 | `await self.get_open_algo_orders(symbol)` | `await self.client.get_open_algo_orders(symbol)` |
| 获取当前价格 | `await self._get_current_price(symbol)` | `await self._get_current_price()` (无参数) |

### 3.3 补单逻辑

**旧代码和新代码基本一致**:
1. 检查 `order.state == "filled"`
2. 检查 `need_tp = not order.tp_order_id`
3. 检查 `need_sl = not order.sl_order_id`
4. 止损价已跌破时市价平仓
5. 止盈价已超过时调整止盈价

### 3.4 补单方法

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| 下止盈单 | `await self._place_tp_order(order)` | `await self._place_tp_order(order)` |
| 下止损单 | `await self._place_sl_order(order)` | `await self._place_sl_order(order)` |
| 市价平仓 | `await self._market_close_order(order, "stop_loss")` | `await self._market_close_order(order, "stop_loss")` |

## 4. 补充下一级挂单 (run 方法)

### 4.1 旧代码逻辑

```python
if not need_new_order:
    await self._check_and_supplement_orders()
    
    filled_orders = [o for o in self.chain_state.orders if o.state == "filled"]
    pending_orders = [o for o in self.chain_state.orders if o.state == "pending"]
    
    if filled_orders:
        max_filled_level = max(o.level for o in filled_orders)
        max_level = self.config.get("max_entries", 4)
        next_level = max_filled_level + 1
        
        has_next_pending = any(o.level == next_level for o in pending_orders)
        
        if next_level <= max_level and not has_next_pending:
            new_order = self._create_order(next_level, current_price)
            self.chain_state.orders.append(new_order)
            print(f"\n{'='*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📥 入场单补下: A{next_level}")
            print(f"{'='*60}")
            await self._place_entry_order(new_order, is_supplement=True)
```

### 4.2 新代码逻辑

```python
if not need_new_order:
    await self._check_and_supplement_orders()
    
    filled_orders = [o for o in self.chain_state.orders if o.state == "filled"]
    pending_orders = [o for o in self.chain_state.orders if o.state == "pending"]
    
    if filled_orders:
        max_filled_level = max(o.level for o in filled_orders)
        max_level = self.config.get("max_entries", 4)
        next_level = max_filled_level + 1
        
        has_next_pending = any(o.level == next_level for o in pending_orders)
        
        if next_level <= max_level and not has_next_pending:
            new_order = self._create_order(next_level, current_price)
            self.chain_state.orders.append(new_order)
            print(f"\n{'='*60}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 📥 入场单补下: A{next_level}")
            print(f"{'='*60}")
            await self._place_entry_order(new_order, is_supplement=True)
```

### 4.3 对比结果

**逻辑完全一致** ✅

## 5. 差异总结

### 5.1 需要修复的问题

| 问题 | 风险等级 | 说明 |
|------|----------|------|
| base_price 未更新 | 低 | 旧代码在恢复时更新 `base_price`，新代码没有 |
| 订单状态设置方式 | 低 | 旧代码使用 `set_state()` 方法，新代码直接赋值 |

### 5.2 架构差异

| 项目 | 旧代码 | 新代码 |
|------|--------|--------|
| API 调用 | 直接调用 `self.xxx()` | 通过 `self.client.xxx()` |
| 状态管理 | `ChainState` 直接操作 | `ChainState.from_dict()` 反序列化 |

### 5.3 一致的部分

| 功能 | 状态 |
|------|------|
| 订单恢复流程 | ✅ 一致 |
| 删除冗余订单 | ✅ 一致 |
| 补充止盈止损 | ✅ 一致 |
| 补充下一级挂单 | ✅ 一致 |
| 级别调整逻辑 | ✅ 一致 |

## 6. 建议修复

### 6.1 base_price 更新

在 `_restore_orders` 方法中添加：
```python
self.chain_state.base_price = current_price
```

### 6.2 订单状态设置

如果 `Order` 类有 `set_state` 方法，建议使用它来设置状态，以保持一致性。

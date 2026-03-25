# group_id 赋值逻辑优化计划

## 问题分析

### 当前实现
1. A1 成交时：`chain_state.group_id += 1`，然后 `pending_order.group_id = chain_state.group_id`
2. A1 成交后创建 A2 挂单：`_create_order(2, ...)`，A2 的 `group_id=0`
3. A2 成交时：检查 `if pending_order.group_id == 0`，如果是，则 `pending_order.group_id = chain_state.group_id`

### 问题
1. A2/A3/A4 挂单创建时 `group_id=0`，入场时才设置
2. 入场时的检查 `if pending_order.group_id == 0` 可能失败（如果 `group_id` 不是 0）
3. 数据库中存在 `group_id=0` 的交易记录

### 用户建议的方案
- A1 成交时：`chain_state.group_id += 1`，然后 `pending_order.group_id = chain_state.group_id`
- A1 成交后创建 A2 挂单时：**直接设置** `group_id = chain_state.group_id`
- 同样 A3/A4 挂单创建时：**直接设置** `group_id = chain_state.group_id`

### 优点
- 订单创建时就确定了 `group_id`，不需要等到入场时再设置
- 避免入场时 `group_id` 不是 0 的问题
- 逻辑更清晰：同一轮次的订单在创建时就绑定同一个 `group_id`

---

## 关于"一轮订单都结束后，再启动新一轮的 A1"

### 当前实现分析

**出场后重建订单的逻辑**（`_process_exit` 方法）：
```python
if closed_levels:
    self.chain_state.cancel_pending_orders()
    
    for level in closed_levels:
        new_order = self._create_order(level, current_price)
        self.chain_state.orders.append(new_order)
```

**问题**：
- 当前实现是：**每个订单出场后立即重建同级别的挂单**
- 例如：A2 止盈后，立即创建新的 A2 挂单（`group_id=0`）
- 这不是"一轮订单都结束后，再启动新一轮的 A1"

### 一轮订单结束的条件

**定义**：一轮订单结束 = 所有已成交订单都已出场 + 没有挂单

**检查逻辑**：
```python
def is_round_finished(self) -> bool:
    """检查一轮订单是否结束"""
    filled_orders = [o for o in self.orders if o.state == "filled"]
    pending_orders = [o for o in self.orders if o.state == "pending"]
    return len(filled_orders) == 0 and len(pending_orders) == 0
```

---

## 实施计划

### 步骤 1：修改 `_create_order` 方法，支持传入 `group_id` 参数

**修改位置**：`binance_backtest.py` 的 `_create_order` 方法

**修改内容**：
```python
def _create_order(self, level: int, base_price: Decimal, klines: List[Dict] = None, group_id: int = None) -> Autofish_Order:
    """创建订单
    
    参数:
        level: 层级
        base_price: 基准价格
        klines: K 线数据（用于策略计算，仅 A1 使用）
        group_id: 轮次 ID（可选，如果不传则使用 chain_state.group_id）
    """
    # ... 创建订单的逻辑 ...
    
    # 设置 group_id
    if group_id is not None:
        order.group_id = group_id
    else:
        order.group_id = self.chain_state.group_id if self.chain_state else 0
    
    return order
```

### 步骤 2：修改 A1 成交后创建 A2/A3/A4 挂单的逻辑

**修改位置**：`binance_backtest.py` 的 `_process_entry` 方法

**修改内容**：
```python
# A1 成交后创建 A2 挂单
next_level = pending_order.level + 1
if next_level <= max_level:
    new_order = self._create_order(next_level, pending_order.entry_price, group_id=self.chain_state.group_id)
    self.chain_state.orders.append(new_order)
    logger.info(f"[链式下单] 创建 A{next_level}: 入场价={new_order.entry_price:.2f}, group_id={new_order.group_id}")
```

### 步骤 3：修改入场时的 group_id 设置逻辑

**修改位置**：`binance_backtest.py` 的 `_process_entry` 方法

**修改内容**：
```python
if pending_order.level == 1:
    # A1 成交时递增 group_id 并设置
    self.chain_state.group_id += 1
    pending_order.group_id = self.chain_state.group_id
    logger.info(f"[新轮次开始] A1 成交: group_id={pending_order.group_id}")
else:
    # A2/A3/A4 成交时，group_id 应该已经在创建时设置
    if pending_order.group_id == 0:
        logger.warning(f"[入场异常] A{pending_order.level} 成交: group_id=0，应该在创建时设置!")
        pending_order.group_id = self.chain_state.group_id
    else:
        logger.info(f"[入场确认] A{pending_order.level} 成交: group_id={pending_order.group_id}")
```

### 步骤 4：修改出场后重建订单的逻辑

**修改位置**：`binance_backtest.py` 的 `_process_exit` 方法

**修改内容**：
```python
if closed_levels:
    self.chain_state.cancel_pending_orders()
    
    # 检查是否一轮订单都结束了
    filled_orders = self.chain_state.get_filled_orders()
    if len(filled_orders) == 0:
        # 一轮订单都结束了，创建新的 A1
        new_order = self._create_order(1, current_price, klines=self.klines_history)
        self.chain_state.orders.append(new_order)
        logger.info(f"[新一轮开始] 创建 A1: 入场价={new_order.entry_price:.2f}, group_id 将在入场时设置")
    else:
        # 还有其他订单在场内，重建同级别的挂单
        for level in closed_levels:
            new_order = self._create_order(level, current_price, group_id=self.chain_state.group_id)
            self.chain_state.orders.append(new_order)
            logger.info(f"[出场后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}, group_id={new_order.group_id}")
```

### 步骤 5：添加一轮订单结束的检查方法

**修改位置**：`autofish_core.py` 的 `Autofish_ChainState` 类

**修改内容**：
```python
def is_round_finished(self) -> bool:
    """检查一轮订单是否结束
    
    一轮订单结束的条件：
    1. 没有已成交的订单（所有订单都已出场）
    2. 没有挂单（或者可以忽略挂单，因为挂单会在新一轮开始时取消）
    """
    filled_orders = [o for o in self.orders if o.state == "filled"]
    return len(filled_orders) == 0
```

### 步骤 6：添加调试日志

**修改位置**：所有涉及 `group_id` 设置的地方

**修改内容**：
- 订单创建时：记录 `group_id` 的值
- 订单入场时：记录 `group_id` 的值
- 订单出场时：记录 `group_id` 的值
- 一轮订单结束时：记录日志

---

## 验证计划

1. 运行回测，检查日志中 `group_id` 的设置是否正确
2. 检查数据库中是否有 `group_id=0` 的交易记录
3. 检查同一轮次的订单是否使用相同的 `group_id`
4. 检查不同轮次的订单是否使用不同的 `group_id`

---

## 文件修改清单

1. `binance_backtest.py`：
   - `_create_order` 方法：添加 `group_id` 参数
   - `_process_entry` 方法：修改 `group_id` 设置逻辑
   - `_process_exit` 方法：修改出场后重建订单的逻辑

2. `autofish_core.py`：
   - `Autofish_ChainState` 类：添加 `is_round_finished` 方法

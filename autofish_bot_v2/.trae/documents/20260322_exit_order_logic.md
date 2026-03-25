# 分析：同一 K 线触发多个订单的处理逻辑

## 当前代码问题

### 当前处理顺序

```python
def _process_exit(self, ...):
    filled_orders = self.chain_state.get_filled_orders()  # 获取已成交订单
    
    for order in filled_orders:  # 按 orders 列表顺序遍历（A1 -> A2 -> A3 -> A4）
        if tp_triggered or sl_triggered:
            # 处理出场
            self.chain_state.cancel_pending_orders()  # 取消挂单
            new_order = self._create_order(order.level, current_price)  # 创建同级别新订单
            self.chain_state.orders.append(new_order)
            break  # 只处理一个订单
```

**问题**：当前代码按 A1 -> A2 -> A3 -> A4 的顺序遍历，处理一个订单后 break。

## 订单价格关系分析

### 做多场景（买入）

```
价格轴（从高到低）:
                                    A1止盈价
                                    A1入场价
                    A2止盈价        A1止损价
                    A2入场价
    A4止盈价        A2止损价
    A4入场价        A3止盈价
    A4止损价        A3入场价
                    A3止损价
                                    （价格继续下跌）
```

**入场价关系**：A4 < A3 < A2 < A1
**止盈价关系**：A4止盈 < A3止盈 < A2止盈 < A1止盈
**止损价关系**：A4止损 < A3止损 < A2止损 < A1止损

### 触发顺序分析

#### 止盈场景（价格上涨）

价格从低往上涨：
1. 先涨到 A4 止盈价 → A4 止盈触发
2. 继续涨到 A3 止盈价 → A3 止盈触发
3. 继续涨到 A2 止盈价 → A2 止盈触发
4. 继续涨到 A1 止盈价 → A1 止盈触发

**止盈处理顺序**：A4 → A3 → A2 → A1（从低级到高级）

#### 止损场景（价格下跌）

价格从高往下跌：
1. 先跌到 A1 止损价 → A1 止损触发
2. 继续跌到 A2 止损价 → A2 止损触发
3. 继续跌到 A3 止损价 → A3 止损触发
4. 继续跌到 A4 止损价 → A4 止损触发

**止损处理顺序**：A1 → A2 → A3 → A4（从高级到低级）

## 当前代码：止损 A1 后的处理逻辑

### 代码分析

```python
elif sl_triggered:
    self._close_order(order, "stop_loss", order.stop_loss_price, leverage, kline_time)
    self.chain_state.cancel_pending_orders()  # 取消所有挂单
    new_order = self._create_order(order.level, current_price)  # 创建同级别新订单
    self.chain_state.orders.append(new_order)
    break
```

### `cancel_pending_orders` 方法

```python
def cancel_pending_orders(self):
    """取消所有挂单"""
    for order in self.orders:
        if order.state == "pending":
            order.state = "cancelled"
```

### 止损 A1 后的状态

| 订单 | 状态 | 说明 |
|------|------|------|
| A1 | closed | 止损出场 |
| A2 | filled | 如果已成交，保持持仓 |
| A3 | filled | 如果已成交，保持持仓 |
| A4 | filled | 如果已成交，保持持仓 |
| 新 A1 | pending | 新创建的 A1 订单 |

**关键点**：
1. 止损 A1 后，A2、A3、A4 如果已成交，仍然保持持仓
2. 创建新的 A1 订单（pending 状态）
3. 下一根 K 线，新的 A1 可能入场

### 问题场景

**场景**：A1 止损后，A2、A3、A4 还在持仓

1. A1 止损出场
2. 创建新的 A1 订单
3. 价格反弹上涨
4. 新的 A1 入场
5. 价格继续上涨，触发 A4 止盈
6. A4 止盈后，创建新的 A4 订单
7. ...

**问题**：
- 同一轮的 A1 已经止损，但 A2、A3、A4 还在持仓
- 新的 A1 入场后，链中同时存在旧的 A2、A3、A4 和新的 A1
- 这是否符合业务逻辑？

## 业务逻辑分析

### 问题1：A1 止损后，A2、A3、A4 应该如何处理？

**选项 A**：A1 止损后，取消 A2、A3、A4 的持仓
- 理由：A1 是第一笔入场，A1 止损意味着这一轮失败
- 问题：A2、A3、A4 可能已经盈利，强制取消会损失利润

**选项 B**：A1 止损后，A2、A3、A4 继续持仓
- 理由：每个订单独立止盈止损
- 问题：新的 A1 入场后，链中订单关系混乱

**选项 C**：A1 止损后，A2、A3、A4 按顺序止损/止盈
- 理由：价格下跌触发 A1 止损，可能继续触发 A2、A3、A4 止损
- 问题：需要正确处理同一 K 线多个订单出场

### 问题2：新的 A1 何时创建？

**当前逻辑**：A1 止损后立即创建新的 A1 订单

**问题**：如果 A2、A3、A4 还在持仓，新的 A1 入场后：
- 链中同时存在旧的 A2、A3、A4 和新的 A1
- 入场资金如何计算？

## 解决方案

### 方案一：A1 止损后，强制平仓所有订单

**逻辑**：
1. A1 止损后，平仓所有 A2、A3、A4（按止损价计算）
2. 清空链状态
3. 创建新的 A1 订单

**优点**：逻辑清晰，每轮独立
**缺点**：可能损失 A2、A3、A4 的利润

### 方案二：A1 止损后，等待所有订单出场后再创建新的 A1（已选择）

**逻辑**：
1. A1 止损后，不立即创建新的 A1
2. 等待 A2、A3、A4 全部出场后
3. 再创建新的 A1 订单

**优点**：保留 A2、A3、A4 的利润机会
**缺点**：实现复杂，需要跟踪链状态

### 方案三：按触发顺序处理所有订单

**逻辑**：
1. 同一 K 线可能触发多个订单
2. 按正确的触发顺序处理所有订单
3. A1 止损后，继续处理 A2、A3、A4（如果触发）
4. 所有订单处理完后，再创建新的订单

**优点**：正确反映价格变化，交易序号正确
**缺点**：实现复杂

---

## 方案二详细设计（已选择）

### 核心逻辑

1. **A1 止损后，不创建新的 A1 订单**
2. **等待链中所有订单（A2、A3、A4）全部出场**
3. **所有订单出场后，创建新的 A1 订单**

### 状态跟踪

在 `Autofish_ChainState` 中添加状态字段：

```python
class Autofish_ChainState:
    orders: List[Autofish_Order] = field(default_factory=list)
    is_active: bool = True
    group_id: int = 0
    waiting_for_reset: bool = False  # 新增：等待链重置标志
```

### 处理流程

```
A1 止损:
  -> 设置 waiting_for_reset = True
  -> 不创建新的 A1 订单
  -> A2、A3、A4 继续持仓

后续 K 线:
  -> A2、A3、A4 可能止盈/止损
  -> 每次出场后检查：链中是否还有 filled 状态的订单？
  -> 如果没有 filled 订单：
     -> waiting_for_reset = False
     -> 创建新的 A1 订单

A1 止盈:
  -> 正常处理
  -> 创建新的 A1 订单
```

### 代码修改

#### 1. 修改 `_process_exit` 方法

```python
def _process_exit(self, open_price, high_price, low_price, current_price, kline_time):
    leverage = self.config.get("leverage", Decimal("10"))
    
    filled_orders = self.chain_state.get_filled_orders()
    
    # 收集所有触发的订单
    tp_orders = [o for o in filled_orders if high_price >= o.take_profit_price]
    sl_orders = [o for o in filled_orders if low_price <= o.stop_loss_price]
    
    # 按触发顺序排序
    tp_orders.sort(key=lambda o: o.take_profit_price)  # A4 → A3 → A2 → A1
    sl_orders.sort(key=lambda o: o.stop_loss_price, reverse=True)  # A1 → A2 → A3 → A4
    
    closed_levels = []
    a1_stopped = False
    
    # 根据 K 线形态判断处理顺序
    if current_price >= open_price:  # 阳线：先跌后涨
        for order in sl_orders:
            self._close_order(order, "stop_loss", order.stop_loss_price, leverage, kline_time)
            closed_levels.append(order.level)
            if order.level == 1:
                a1_stopped = True
        for order in tp_orders:
            if order.level not in closed_levels:
                self._close_order(order, "take_profit", order.take_profit_price, leverage, kline_time)
                closed_levels.append(order.level)
    else:  # 阴线：先涨后跌
        for order in tp_orders:
            self._close_order(order, "take_profit", order.take_profit_price, leverage, kline_time)
            closed_levels.append(order.level)
        for order in sl_orders:
            if order.level not in closed_levels:
                self._close_order(order, "stop_loss", order.stop_loss_price, leverage, kline_time)
                closed_levels.append(order.level)
                if order.level == 1:
                    a1_stopped = True
    
    if closed_levels:
        self.chain_state.cancel_pending_orders()
        
        # 如果 A1 止损，设置等待重置标志
        if a1_stopped:
            self.chain_state.waiting_for_reset = True
            logger.info(f"[A1 止损] 设置等待重置标志，等待其他订单出场")
        else:
            # 正常创建新订单
            for level in closed_levels:
                new_order = self._create_order(level, current_price)
                self.chain_state.orders.append(new_order)
    
    # 检查是否所有订单都已出场
    if self.chain_state.waiting_for_reset:
        remaining_filled = [o for o in self.chain_state.orders if o.state == "filled"]
        if len(remaining_filled) == 0:
            self.chain_state.waiting_for_reset = False
            new_order = self._create_order(1, current_price)
            self.chain_state.orders.append(new_order)
            logger.info(f"[链重置] 所有订单已出场，创建新的 A1 订单")
```

### 数据流程图

```
初始状态:
  A1 (filled), A2 (filled), A3 (filled), A4 (pending)
  waiting_for_reset = False

A1 止损:
  A1 (closed), A2 (filled), A3 (filled), A4 (pending)
  waiting_for_reset = True
  不创建新的 A1

A4 入场:
  A1 (closed), A2 (filled), A3 (filled), A4 (filled)
  waiting_for_reset = True

A4 止盈:
  A1 (closed), A2 (filled), A3 (filled), A4 (closed)
  waiting_for_reset = True
  创建新的 A4 (pending)

A3 止盈:
  A1 (closed), A2 (filled), A3 (closed), A4 (pending)
  waiting_for_reset = True
  创建新的 A3 (pending)

A2 止盈:
  A1 (closed), A2 (closed), A3 (pending), A4 (pending)
  waiting_for_reset = True
  创建新的 A2 (pending)
  检查：没有 filled 订单了
  waiting_for_reset = False
  创建新的 A1 (pending)

最终状态:
  A1 (pending), A2 (pending), A3 (pending), A4 (pending)
  waiting_for_reset = False
```

### group_id 处理逻辑

```
A1 入场时:
  -> 如果 waiting_for_reset = False（新一轮开始）
     -> group_id += 1
  -> order.group_id = chain_state.group_id

A2/A3/A4 入场时:
  -> order.group_id = chain_state.group_id
```

### 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `autofish_core.py` | `Autofish_ChainState` 类添加 `waiting_for_reset: bool = False` 字段 |
| `binance_backtest.py` | `_process_exit` 方法：A1 止损时设置 `waiting_for_reset = True` |
| `binance_backtest.py` | `_process_exit` 方法：检查所有订单出场后创建新的 A1 |
| `binance_backtest.py` | `_process_entry` 方法：根据 `waiting_for_reset` 状态决定是否递增 `group_id` |

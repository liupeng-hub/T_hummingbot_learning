# 订单同步设计规范

## 概述

程序重启时，需要将本地订单状态与 Binance 实际状态同步。本文档梳理所有可能的场景和处理逻辑。

## 数据来源

### Binance API

#### 普通订单 API

| API | 说明 | 用途 |
|-----|------|------|
| `/fapi/v1/openOrders` | 当前委托（普通订单） | 检查入场单是否挂单中 |
| `/fapi/v1/allOrders` | 历史委托（普通订单） | 查询入场单历史状态 |
| `/fapi/v1/order` | 查询单个订单 | 查询特定订单状态 |

#### Algo 条件单 API

| API | 说明 | 用途 |
|-----|------|------|
| `/fapi/v1/openAlgoOrders` | 当前委托（Algo 条件单） | 检查止盈止损单是否挂单中 |
| `/fapi/v1/allAlgoOrders` | 历史 Algo 条件单 | 查询止盈止损单历史状态 |

#### 仓位和成交 API

| API | 说明 | 用途 |
|-----|------|------|
| `/fapi/v2/position` | 当前仓位 | 判断是否持有仓位 |
| `/fapi/v1/userTrades` | 历史成交 | 查询成交记录，确定平仓原因 |

### 重要说明

**普通订单和 Algo 条件单使用不同的 API**：

1. **普通订单**（LIMIT、MARKET 等）
   - 当前委托：`GET /fapi/v1/openOrders`
   - 历史委托：`GET /fapi/v1/allOrders`

2. **Algo 条件单**（STOP_MARKET、TAKE_PROFIT_MARKET）
   - 当前委托：`GET /fapi/v1/openAlgoOrders`
   - 历史委托：`GET /fapi/v1/algo/order/history`

3. **成交记录**
   - 历史成交：`GET /fapi/v1/userTrades`
   - 注意：成交记录中包含 `orderId`，可以关联到具体的订单

### 本地状态

| 字段 | 说明 |
|------|------|
| `state` | 订单状态：pending/filled/closed |
| `order_id` | 入场单 ID |
| `tp_order_id` | 止盈条件单 ID |
| `sl_order_id` | 止损条件单 ID |
| `entry_price` | 入场价 |
| `quantity` | 数量 |

## 本地状态与 Binance 状态的关系

### 本地 pending 状态

本地 `pending` 表示入场单挂单中，等待成交。

| Binance 状态 | 说明 | 处理 |
|-------------|------|------|
| 订单存在 + NEW | 入场单仍在挂单 | 保持 pending |
| 订单存在 + FILLED | 入场单已成交 | 更新为 filled，下止盈止损单 |
| 订单存在 + CANCELED | 入场单已取消 | 删除本地订单 |
| 订单存在 + EXPIRED | 入场单已过期 | 删除本地订单 |
| 订单不存在 | 订单已从系统清除 | 查历史委托确认状态 |

### 本地 filled 状态

本地 `filled` 表示入场单已成交，持有仓位，有止盈止损单。

| 止盈单状态 | 止损单状态 | 仓位状态 | 说明 | 处理 |
|-----------|-----------|---------|------|------|
| 存在 | 存在 | 有仓位 | 正常状态 | 保持 filled |
| 存在 | 不存在 | 有仓位 | 止损单缺失 | 补止损单 |
| 不存在 | 存在 | 有仓位 | 止盈单缺失 | 补止盈单 |
| 不存在 | 不存在 | 有仓位 | 止盈止损都缺失 | 补止盈止损单 |
| 存在 | 不存在 | 无仓位 | 止损已成交 | 取消止盈，更新为 closed |
| 不存在 | 存在 | 无仓位 | 止盈已成交 | 取消止损，更新为 closed |
| 不存在 | 不存在 | 无仓位 | 已平仓 | 查历史成交，更新为 closed |

### 本地 closed 状态

本地 `closed` 表示订单已平仓。

| 处理 |
|------|
| 保留历史记录，不进行任何操作 |

## 详细场景分析

### 场景 1: pending → filled（程序关闭期间成交）

```
本地状态: pending, order_id=123
Binance 状态: 订单 123 已成交

处理:
1. 查询订单 123 的成交价
2. 更新本地状态为 filled
3. 下止盈止损条件单
```

### 场景 2: pending → 取消（程序关闭期间取消）

```
本地状态: pending, order_id=123
Binance 状态: 订单 123 已取消

处理:
1. 删除本地订单记录
2. 如果有残留的止盈止损单，取消它们
```

### 场景 3: filled + 止盈成交（程序关闭期间止盈）

```
本地状态: filled, tp_id=Ax, sl_id=Ay
Binance 状态: Ax 不存在，Ay 存在，无仓位

处理:
1. 判断止盈已成交
2. 取消残留的止损单 Ay
3. 更新状态为 closed, close_reason="take_profit"
4. 发送平仓通知
```

### 场景 4: filled + 止损成交（程序关闭期间止损）

```
本地状态: filled, tp_id=Ax, sl_id=Ay
Binance 状态: Ax 存在，Ay 不存在，无仓位

处理:
1. 判断止损已成交
2. 取消残留的止盈单 Ax
3. 更新状态为 closed, close_reason="stop_loss"
4. 发送平仓通知
```

### 场景 5: filled + 都成交（程序关闭期间平仓）

```
本地状态: filled, tp_id=Ax, sl_id=Ay
Binance 状态: Ax 不存在，Ay 不存在，无仓位

处理:
1. 查询历史成交记录
2. 确定是止盈还是止损成交
3. 更新状态为 closed, close_reason="take_profit" 或 "stop_loss"
4. 发送平仓通知
```

### 场景 6: filled + 止盈止损缺失（需要补单）

```
本地状态: filled, tp_id=Ax, sl_id=Ay
Binance 状态: Ax 不存在，Ay 不存在，有仓位

处理:
1. 判断止盈止损单缺失
2. 执行补单逻辑
```

### 场景 7: pending + 订单不存在（需要查历史）

```
本地状态: pending, order_id=123
Binance 状态: 订单 123 不存在

处理:
1. 查询历史委托，确认订单最终状态
2. 如果是 FILLED → 更新为 filled
3. 如果是 CANCELED/EXPIRED → 删除本地订单
```

### 场景 8: pending + 部分成交

```
本地状态: pending, order_id=123
Binance 状态: 订单 123 部分成交 (PARTIALLY_FILLED)

处理:
1. 保持 pending 状态
2. 更新已成交数量（如果需要）
3. 等待完全成交后再下止盈止损单
```

### 场景 9: pending 成交后崩溃（止盈止损可能部分下了）

```
时间线:
T1: pending 订单成交
T2: 程序开始下止盈止损单
T3: 程序崩溃（止盈止损单可能部分下了）

重启时:
本地状态: pending（未更新为 filled）
Binance 状态: 入场单已成交，可能有部分止盈止损单

处理:
1. 查询入场单状态 → FILLED
2. 更新本地状态为 filled
3. 检查止盈止损单是否存在
4. 如果部分存在 → 保留，补缺失的
5. 如果都不存在 → 补止盈止损单
```

### 场景 10: filled + 本地数据不完整

```
本地状态: filled, 但 tp_order_id=None, sl_order_id=None
Binance 状态: 有仓位

处理:
1. 检查仓位存在性
2. 如果有仓位 → 执行补单逻辑
3. 如果无仓位 → 查历史成交，更新为 closed
```

### 场景 11: filled + 止盈止损单被手动修改

```
本地状态: filled, tp_id=Ax, sl_id=Ay
Binance 状态: Ax 存在但触发价已改变，Ay 存在但触发价已改变

处理:
1. 检测触发价是否与本地记录一致
2. 如果不一致 → 更新本地记录的止盈止损价
3. 发送通知告知用户止盈止损单被修改
```

## 恢复流程

```
1. 加载本地状态
2. 获取 Binance 当前仓位
3. 获取 Binance 当前委托（普通订单 + Algo 条件单）
4. 遍历本地订单:
   a. pending 订单:
      - 查询订单状态
      - 根据状态更新或删除
   b. filled 订单:
      - 检查止盈止损单存在性
      - 检查仓位存在性
      - 判断是否已平仓
      - 执行相应处理
   c. closed 订单:
      - 保留历史记录
5. 取消残留的条件单
6. 保存状态
7. 发送恢复通知
8. 执行补单检查
```

## 实现要点

### 1. 仓位检查

```python
positions = await self.get_positions(symbol)
has_position = any(p['positionAmt'] > 0 for p in positions)
```

### 2. 历史成交查询

**重要说明**：条件止盈止损单触发后，会生成新的市价单执行成交。

**关键发现**：历史 Algo 条件单 API 返回的数据中包含：
- `algoId`：条件单 ID（可以关联到本地存储的 tp_order_id / sl_order_id）
- `orderId`：触发后生成的新订单 ID
- `status`：条件单状态（FILLED 表示已成交）

```python
# 查询 Algo 条件单历史状态
algo_history = await self.get_algo_order_history(symbol)
algo_status_map = {algo['algoId']: algo for algo in algo_history}

# 判断止盈止损是否成交
if order.tp_order_id and order.tp_order_id in algo_status_map:
    if algo_status_map[order.tp_order_id]['status'] == 'FILLED':
        close_reason = "take_profit"

if order.sl_order_id and order.sl_order_id in algo_status_map:
    if algo_status_map[order.sl_order_id]['status'] == 'FILLED':
        close_reason = "stop_loss"
```

### 3. 条件单触发后的 ID 关系

```
条件止盈单 (algoId=Ax)
    ↓ 价格触发
生成市价单 (orderId=新的ID，如 12345)
    ↓ 执行成交
历史 Algo 记录 (algoId=Ax, orderId=12345, status=FILLED)
```

**结论**：可以通过 `algoId` 直接关联条件单和成交状态，无需通过成交属性匹配。

### 3. 残留条件单取消

```python
# 在删除 pending 订单前，记录关联的条件单 ID
pending_cancel_algo_ids = []
for order in orders_to_remove:
    if order.tp_order_id:
        pending_cancel_algo_ids.append(order.tp_order_id)
    if order.sl_order_id:
        pending_cancel_algo_ids.append(order.sl_order_id)

# 取消残留的条件单
for algo_id in pending_cancel_algo_ids:
    if algo_id in algo_ids:  # 仍然存在
        await self.cancel_algo_order(symbol, algo_id)
```

# 完善订单状态信息填充和日志记录

## 问题描述

当前订单状态信息中，以下字段没有正确填充：

| 字段 | 说明 | 当前状态 |
|------|------|----------|
| `filled_at` | 入场成交时间 | 未填充 |
| `closed_at` | 平仓时间 | 未填充 |
| `close_price` | 平仓价格 | 部分填充 |
| `close_reason` | 平仓原因 | 已填充 |
| `profit` | 盈亏金额 | 已填充 |

另外，订单 close 时，没有将完整的订单数据打印到日志中。

## 需要修改的位置

### 1. 入场成交时填充 `filled_at`

**文件**: `binance_live.py`

**位置**: `_process_order_filled()` 方法

```python
async def _process_order_filled(self, order: Any, filled_price: Decimal, is_recovery: bool = False) -> None:
    order.state = "filled"
    order.entry_price = filled_price
    order.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # 新增
    
    await self._place_exit_orders(order)
    ...
```

### 2. 止盈触发时填充 `closed_at` 和 `close_price`

**文件**: `binance_live.py`

**位置**: `AlgoHandler._handle_take_profit()` 方法

```python
async def _handle_take_profit(self, order: Any, algo_data: Dict[str, Any]) -> None:
    order.state = "closed"
    order.close_reason = CloseReason.TAKE_PROFIT.value
    order.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # 新增
    order.close_price = order.take_profit_price  # 确保填充
    
    ...
    
    # 打印订单完整信息到日志
    self._log_order_closed(order, "止盈")
```

### 3. 止损触发时填充 `closed_at` 和 `close_price`

**文件**: `binance_live.py`

**位置**: `AlgoHandler._handle_stop_loss()` 方法

```python
async def _handle_stop_loss(self, order: Any, algo_data: Dict[str, Any]) -> None:
    order.state = "closed"
    order.close_reason = CloseReason.STOP_LOSS.value
    order.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # 新增
    order.close_price = order.stop_loss_price  # 确保填充
    
    ...
    
    # 打印订单完整信息到日志
    self._log_order_closed(order, "止损")
```

### 4. 添加订单关闭日志打印方法

**文件**: `binance_live.py`

**新增方法**: `_log_order_closed()`

```python
def _log_order_closed(self, order: Any, reason: str) -> None:
    """打印订单关闭信息到日志"""
    logger.info(f"[订单关闭] A{order.level} {reason}")
    logger.info(f"  入场价格: {order.entry_price:.2f}")
    logger.info(f"  入场时间: {order.filled_at}")
    logger.info(f"  平仓价格: {order.close_price:.2f}")
    logger.info(f"  平仓时间: {order.closed_at}")
    logger.info(f"  平仓原因: {order.close_reason}")
    logger.info(f"  数量: {order.quantity:.6f}")
    logger.info(f"  金额: {order.stake_amount:.2f} USDT")
    logger.info(f"  盈亏: {order.profit:.2f} USDT")
    logger.info(f"  持仓时长: {self._calculate_holding_duration(order)}")
```

### 5. 添加持仓时长计算方法

```python
def _calculate_holding_duration(self, order: Any) -> str:
    """计算持仓时长"""
    if not order.filled_at or not order.closed_at:
        return "未知"
    
    filled_time = datetime.strptime(order.filled_at, '%Y-%m-%d %H:%M:%S')
    closed_time = datetime.strptime(order.closed_at, '%Y-%m-%d %H:%M:%S')
    duration = closed_time - filled_time
    
    hours = duration.total_seconds() // 3600
    minutes = (duration.total_seconds() % 3600) // 60
    
    return f"{int(hours)}小时{int(minutes)}分钟"
```

### 6. 状态恢复时填充时间字段

**文件**: `binance_live.py`

**位置**: `_restore_orders()` 方法

在状态恢复时，如果检测到订单已成交但 `filled_at` 为空，需要填充当前时间（或从 Binance 获取实际时间）。

## 实施步骤

1. 修改 `_process_order_filled()` 方法，填充 `filled_at`
2. 修改 `_handle_take_profit()` 方法，填充 `closed_at` 和 `close_price`
3. 修改 `_handle_stop_loss()` 方法，填充 `closed_at` 和 `close_price`
4. 添加 `_log_order_closed()` 方法
5. 添加 `_calculate_holding_duration()` 方法
6. 修改 `_restore_orders()` 方法，处理状态恢复时的时间字段
7. 提交到 Git

## 日志输出示例

```
[订单关闭] A1 止盈
  入场价格: 66555.50
  入场时间: 2026-03-09 02:24:35
  平仓价格: 67221.10
  平仓时间: 2026-03-09 11:00:03
  平仓原因: take_profit
  数量: 0.007000
  金额: 465.89 USDT
  盈亏: 46.39 USDT
  持仓时长: 8小时35分钟
```

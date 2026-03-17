# A1 超时重挂通知优化方案

## 问题分析

### 问题1：通知格式不统一

**现有格式对比**：

| 通知类型 | 格式特点 |
|---------|---------|
| 入场单下单 | 简洁单行，`> **字段**: 值` |
| 入场成交 | 简洁单行，`> **字段**: 值` |
| 止盈触发 | 简洁单行，`> **字段**: 值` |
| A1 超时重挂 | 多行缩进，`>   - 字段: 值` |

### 问题2：新订单号显示为 None

**原因**：`notify_a1_timeout_refresh` 在 `_place_entry_order` 之前调用，此时 `new_a1.order_id` 还未被设置。

**代码流程**：
```python
# 当前流程
new_a1 = await self._create_order(1, current_price, klines)  # order_id = None
notify_a1_timeout_refresh(timeout_a1, new_a1, ...)           # 发送通知，order_id = None
await self._place_entry_order(new_a1, ...)                   # 设置 order_id
```

### 问题3：两条消息重复

**当前流程**：
1. `notify_a1_timeout_refresh` 发送 "⏰ A1 超时重挂"
2. `_place_entry_order` 内部调用 `notify_entry_order` 发送 "🟢 入场单下单 A1"

**问题**：第二条消息没有体现是重挂订单，用户会困惑。

## 解决方案

### 方案：合并为单条通知

**核心思路**：
1. 移除独立的 `notify_a1_timeout_refresh` 调用
2. 在 `_place_entry_order` 中添加 `is_timeout_refresh` 参数
3. 如果是超时重挂，发送包含完整信息的单条通知

**新通知格式**：

```
## ⏰ A1 超时重挂

> **层级**: A1 (第1层/共4层)
> **触发原因**: A1 挂单超过 10 分钟未成交
> **当前价格**: 71234.56 USDT
> 
> **原订单**:
>   入场价: 70831.50 USDT
>   订单ID: 12792308355
>   创建时间: 2026-03-14 01:24:55
> 
> **新订单**:
>   入场价: 71187.50 USDT
>   数量: 0.007 BTC
>   金额: 498.31 USDT
>   止盈价: 71899.00 USDT (+1.0%)
>   止损价: 65492.50 USDT (-8.0%)
>   订单ID: 12792472973
> 
> **价格调整**: 356.00 (0.50%)
> **时间**: 2026-03-14 01:34:55
```

## 代码修改

### 1. 修改 `_place_entry_order` 方法

添加参数：
```python
async def _place_entry_order(self, order: Any, is_supplement: bool = False, 
                              is_timeout_refresh: bool = False, 
                              old_order: Any = None,
                              timeout_minutes: int = 0) -> None:
```

### 2. 新增通知函数 `notify_entry_order_timeout_refresh`

```python
def notify_entry_order_timeout_refresh(order, old_order, current_price: Decimal, 
                                        timeout_minutes: int, config: dict):
    """发送 A1 超时重挂通知（包含新订单完整信息）"""
    max_entries = config.get('max_entries', 4)
    symbol = config.get('symbol', 'BTCUSDT')
    
    price_diff = abs(float(order.entry_price) - float(old_order.entry_price))
    price_diff_pct = price_diff / float(old_order.entry_price) * 100
    
    content = dedent(f"""\
        > **层级**: A{order.level} (第{order.level}层/共{max_entries}层)
        > **触发原因**: A1 挂单超过 {timeout_minutes} 分钟未成交
        > **当前价格**: {float(current_price):.2f} USDT
        > 
        > **原订单**:
        >   入场价: {float(old_order.entry_price):.2f} USDT
        >   订单ID: {old_order.order_id}
        >   创建时间: {old_order.created_at}
        > 
        > **新订单**:
        >   入场价: {order.entry_price:.2f} USDT
        >   数量: {order.quantity:.6f} BTC
        >   金额: {order.stake_amount:.2f} USDT
        >   止盈价: {order.take_profit_price:.2f} USDT (+{float(config.get('exit_profit', Decimal('0.01')))*100:.1f}%)
        >   止损价: {order.stop_loss_price:.2f} USDT (-{float(config.get('stop_loss', Decimal('0.08')))*100:.1f}%)
        >   订单ID: {order.order_id}
        > 
        > **价格调整**: {price_diff:.2f} ({price_diff_pct:.2f}%)
        > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""").strip()
    
    send_wechat_notification(f"⏰ A1 超时重挂", content)
```

### 3. 修改 `_check_and_handle_a1_timeout` 方法

```python
# 移除 notify_a1_timeout_refresh 调用
# 传递参数给 _place_entry_order
await self._place_entry_order(
    new_a1, 
    is_supplement=False, 
    is_timeout_refresh=True,
    old_order=timeout_a1,
    timeout_minutes=self.a1_timeout_minutes
)
```

### 4. 删除 `notify_a1_timeout_refresh` 函数

不再需要独立的通知函数。

## 执行步骤

### 阶段1: 新增通知函数
1. 添加 `notify_entry_order_timeout_refresh` 函数

### 阶段2: 修改 `_place_entry_order` 方法
1. 添加 `is_timeout_refresh`, `old_order`, `timeout_minutes` 参数
2. 在下单成功后，根据参数选择发送哪种通知

### 阶段3: 修改 `_check_and_handle_a1_timeout` 方法
1. 移除 `notify_a1_timeout_refresh` 调用
2. 传递超时重挂参数给 `_place_entry_order`

### 阶段4: 清理
1. 删除 `notify_a1_timeout_refresh` 函数

## 通知格式统一规范

所有通知使用统一格式：
```python
content = dedent(f"""\
    > **字段1**: 值1
    > **字段2**: 值2
    > **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""").strip()
```

特点：
- 使用 `dedent` 和 `strip()` 处理缩进
- 每行以 `> ` 开头
- 字段格式：`> **字段名**: 值`
- 子项使用 `>   - 子项: 值`（两个空格缩进）

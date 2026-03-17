# 订单金额小于最小要求问题修复计划

## 问题描述

```
Binance API Error [-4164]: Order's notional must be no smaller than 100 (unless you choose reduce only).
```

Binance 要求订单的名义价值（notional = price × quantity）必须不小于 100 USDT。

## 问题分析

### 当前代码流程

```python
# _create_order() 创建订单
order = order_calculator.create_order(...)
order.quantity = self._adjust_quantity(order.quantity)  # 只调整精度

# _place_entry_order() 下单
result = await self.client.place_order(quantity=float(quantity), price=float(price))
```

### 问题原因

`_adjust_quantity()` 只调整数量精度，**没有检查订单金额是否满足最小要求**。

当权重很小（如 A4 权重 0.03%）时：
- 总投入 1200 USDT
- A4 金额 = 1200 × 0.03% = 0.36 USDT
- 远小于 Binance 最小要求 100 USDT

## 修复方案

### 方案：在 `_adjust_quantity()` 中增加最小金额检查

```python
MIN_NOTIONAL = Decimal("100")  # Binance 最小名义价值要求

def _adjust_quantity(self, quantity: Decimal, price: Decimal = None) -> Decimal:
    """调整数量精度，并确保满足最小金额要求"""
    step_size = getattr(self, 'step_size', Decimal("0.001"))
    adjusted = (quantity // step_size) * step_size
    
    if adjusted <= 0:
        adjusted = step_size
    
    # 检查最小金额要求
    if price:
        min_notional = Decimal("100")  # Binance 最小要求
        current_notional = adjusted * price
        if current_notional < min_notional:
            # 调整数量以满足最小金额要求
            adjusted = (min_notional / price // step_size + 1) * step_size
            logger.warning(f"[数量调整] 订单金额 {current_notional:.2f} < 100 USDT，调整数量为 {adjusted:.6f}")
    
    return adjusted
```

### 调用修改

```python
# _place_entry_order() 中
quantity = self._adjust_quantity(order.quantity, order.entry_price)
```

## 实施步骤

1. 修改 `_adjust_quantity()` 方法，增加 `price` 参数和最小金额检查
2. 修改 `_place_entry_order()` 调用，传入价格参数
3. 添加日志记录调整信息

## 测试验证

1. 模拟小权重订单（金额 < 100 USDT）
2. 验证数量是否被正确调整
3. 验证下单是否成功

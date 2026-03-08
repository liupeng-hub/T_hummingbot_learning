# 做空适配分析

## 当前算法分析（做多）

### 价格计算

| 价格类型 | 计算公式 | 说明 |
|----------|----------|------|
| 入场价格 | `base_price * (1 - grid_spacing * level)` | 比当前价格低 |
| 止盈价格 | `entry_price * (1 + exit_profit)` | 比入场价格高 |
| 止损价格 | `entry_price * (1 - stop_loss)` | 比入场价格低 |

### 触发条件

| 触发类型 | 判断条件 | 说明 |
|----------|----------|------|
| 入场触发 | `low_price <= entry_price` | 价格下跌到入场价 |
| 止盈触发 | `high_price >= take_profit_price` | 价格上涨到止盈价 |
| 止损触发 | `low_price <= stop_loss_price` | 价格下跌到止损价 |

## 做空逻辑对比

| 价格类型 | 做多 | 做空 |
|----------|------|------|
| 入场价格 | 比当前价格低 | 比当前价格高 |
| 止盈价格 | 比入场价格高 | 比入场价格低 |
| 止损价格 | 比入场价格低 | 比入场价格高 |
| 入场触发 | 价格下跌触发 | 价格上涨触发 |
| 止盈触发 | 价格上涨触发 | 价格下跌触发 |
| 止损触发 | 价格下跌触发 | 价格上涨触发 |

## 用户方案分析

用户提议：设置 `exit_profit = -0.01`，`stop_loss = -0.08`

### 价格计算结果

| 价格类型 | 公式 | 结果 |
|----------|------|------|
| 止盈价格 | `entry_price * (1 + (-0.01))` | 比入场价格低 ✅ |
| 止损价格 | `entry_price * (1 - (-0.08))` | 比入场价格高 ✅ |

### 问题

❌ **入场价格计算**：
- 当前：`base_price * (1 - grid_spacing * level)` → 比当前价格低
- 做空需要：比当前价格高

❌ **入场触发条件**：
- 当前：`low_price <= entry_price` → 价格下跌触发
- 做空需要：价格上涨触发

❌ **止盈触发条件**：
- 当前：`high_price >= take_profit_price` → 价格上涨触发
- 做空需要：价格下跌触发

❌ **止损触发条件**：
- 当前：`low_price <= stop_loss_price` → 价格下跌触发
- 做空需要：价格上涨触发

## 结论

**不能**仅通过修改 `exit_profit` 和 `stop_loss` 为负值来适配做空。

## 解决方案

### 方案一：添加 `direction` 配置项

在配置文件中添加 `direction` 字段：
- `"long"`：做多（默认）
- `"short"`：做空

### 方案二：修改代码逻辑

需要修改以下位置：

#### 1. autofish_core.py

**create_order() 方法**：
```python
# 入场价格
if direction == "short":
    entry_price = base_price * (Decimal("1") + self.grid_spacing * level)  # 做空：比当前价格高
else:
    entry_price = base_price * (Decimal("1") - self.grid_spacing * level)  # 做多：比当前价格低
```

**check_xxx_triggered() 方法**：
```python
@staticmethod
def check_entry_triggered(low_price: Decimal, high_price: Decimal, entry_price: Decimal, direction: str) -> bool:
    if direction == "short":
        return high_price >= entry_price  # 做空：价格上涨触发
    else:
        return low_price <= entry_price  # 做多：价格下跌触发

@staticmethod
def check_take_profit_triggered(low_price: Decimal, high_price: Decimal, take_profit_price: Decimal, direction: str) -> bool:
    if direction == "short":
        return low_price <= take_profit_price  # 做空：价格下跌触发
    else:
        return high_price >= take_profit_price  # 做多：价格上涨触发

@staticmethod
def check_stop_loss_triggered(low_price: Decimal, high_price: Decimal, stop_loss_price: Decimal, direction: str) -> bool:
    if direction == "short":
        return high_price >= stop_loss_price  # 做空：价格上涨触发
    else:
        return low_price <= stop_loss_price  # 做多：价格下跌触发
```

#### 2. binance_backtest.py / longport_backtest.py

修改 `_process_entry()` 和 `_process_exit()` 方法，传递 `direction` 参数。

#### 3. binance_live.py / longport_live.py

修改入场和出场处理逻辑。

### 方案三：简化方案（仅修改配置）

如果用户坚持只修改配置，可以：

1. 保持 `exit_profit` 和 `stop_loss` 为正值
2. 修改代码，根据 `direction` 自动调整计算公式

```python
if direction == "short":
    take_profit_price = entry_price * (Decimal("1") - self.exit_profit)  # 做空：向下
    stop_loss_price = entry_price * (Decimal("1") + self.stop_loss)  # 做空：向上
else:
    take_profit_price = entry_price * (Decimal("1") + self.exit_profit)  # 做多：向上
    stop_loss_price = entry_price * (Decimal("1") - self.stop_loss)  # 做多：向下
```

## 推荐方案

**方案三**：添加 `direction` 配置项，代码自动处理做多/做空逻辑差异。

### 配置示例

```json
{
    "symbol": "BTCUSDT",
    "direction": "short",
    "grid_spacing": 0.01,
    "exit_profit": 0.01,
    "stop_loss": 0.08,
    ...
}
```

### 优点

1. 配置简单，只需添加 `direction` 字段
2. `exit_profit` 和 `stop_loss` 保持正值，语义清晰
3. 代码自动处理做多/做空差异

### 需要修改的文件

1. `autofish_core.py`：修改价格计算和触发条件
2. `binance_backtest.py`：修改触发检查
3. `longport_backtest.py`：修改触发检查
4. `binance_live.py`：修改触发检查
5. `longport_live.py`：修改触发检查

# 修复权重显示和下单金额问题

## 问题描述

当前代码中，下单金额直接使用配置文件中的原始权重，但没有根据 `max_entries` 进行归一化。

### 用户需求

1. **启动通知**：显示配置文件中的全部权重（不做归一化）
2. **配置确认通知**：显示按 `max_entries` 归一化后的权重（实际下单时的权重）

### 配置文件示例

```json
{
  "max_entries": 4,
  "weights": [0.0831, 0.2996, 0.3167, 0.1365, 0.1005, 0.0281, 0.027, 0.0066, 0.0018]
}
```

### 问题分析

- `weights` 数组有 9 个元素（对应 9 个振幅区间）
- `max_entries = 4`，表示只使用前 4 个层级
- 直接使用原始权重会导致金额计算错误（总和不为 1）

### 正确做法

1. **启动通知**：显示配置文件中的全部 9 个权重
2. **配置确认通知和下单**：
   - 取前 `max_entries` 个权重
   - 对这 `max_entries` 个权重进行归一化（使总和为 1）
   - 使用归一化后的权重计算下单金额

### 示例计算

**原始权重（全部9个）**:
```
[0.0831, 0.2996, 0.3167, 0.1365, 0.1005, 0.0281, 0.027, 0.0066, 0.0018]
```

**启动通知显示**:
```
网格权重: A1: 8.3%, A2: 30.0%, A3: 31.7%, A4: 13.7%, A5: 10.1%, A6: 2.8%, A7: 2.7%, A8: 0.7%, A9: 0.2%
```

**归一化权重（前4个）**:
```
原始: [0.0831, 0.2996, 0.3167, 0.1365]
总和: 0.8357
归一化后: [0.0994, 0.3584, 0.3790, 0.1632]
总和: 1.0000
```

**配置确认通知显示**:
```
各层级分配:
A1: 497 USDT (9.9%)
A2: 1792 USDT (35.8%)
A3: 1895 USDT (37.9%)
A4: 816 USDT (16.3%)
```

## 需要修改的文件

### 1. autofish_core.py

- 添加 `normalize_weights(weights: List[Decimal], max_entries: int) -> List[Decimal]` 函数
- 修改 `create_order()` 方法，使用归一化权重

### 2. binance_live.py

- **notify_startup()**: 恢复显示全部权重（不做归一化）
- **_check_min_notional()**: 使用归一化权重
- **_create_order()**: 使用归一化权重
- **日志输出**: 显示归一化后的权重

### 3. binance_backtest.py

- **_get_weights()**: 返回归一化权重
- **_create_order()**: 使用归一化权重
- **日志输出**: 显示归一化后的权重

### 4. longport_live.py

- **_create_order()**: 使用归一化权重

### 5. longport_backtest.py

- **_get_weights()**: 返回归一化权重
- **_create_order()**: 使用归一化权重
- **日志输出**: 显示归一化后的权重

## 实施步骤

### 步骤 1: 修改 autofish_core.py

添加归一化函数：
```python
def normalize_weights(weights: List[Decimal], max_entries: int) -> List[Decimal]:
    """归一化权重
    
    取前 max_entries 个权重，然后归一化使总和为 1
    """
    if not weights:
        return []
    
    # 取前 max_entries 个权重
    selected_weights = weights[:max_entries]
    
    # 计算总和
    total = sum(selected_weights)
    if total == 0:
        return selected_weights
    
    # 归一化
    return [w / total for w in selected_weights]
```

修改 `create_order()` 方法，使用归一化权重。

### 步骤 2: 修改 binance_live.py

1. **notify_startup()**: 恢复显示全部权重
2. **_check_min_notional()**: 使用归一化权重
3. **_create_order()**: 使用归一化权重

### 步骤 3: 修改 binance_backtest.py

1. **_get_weights()**: 返回归一化权重
2. **_create_order()**: 使用归一化权重

### 步骤 4: 修改 longport_live.py

- **_create_order()**: 使用归一化权重

### 步骤 5: 修改 longport_backtest.py

1. **_get_weights()**: 返回归一化权重
2. **_create_order()**: 使用归一化权重

### 步骤 6: 提交到 Git

## 注意事项

1. 保持向后兼容性：如果没有配置 weights，使用默认逻辑
2. 日志输出：确保日志中显示的是归一化后的权重
3. 启动通知：显示原始权重，让用户了解完整的权重分布
4. 配置确认通知：显示归一化权重，让用户了解实际下单分配

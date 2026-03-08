# 入场价格策略说明

## 概述

入场价格策略用于计算 A1 订单的入场价格。通过策略模式，用户可以灵活选择不同的入场价格计算方式，以适应不同的市场环境。

## 策略列表

| 策略名称 | 说明 | 适用场景 |
|----------|------|----------|
| `fixed` | 固定网格间距 | 默认策略，适用于稳定市场 |
| `atr` | ATR 动态计算 | 适用于波动性变化较大的市场 |
| `bollinger` | 布林带下轨入场 | 适用于震荡市场 |
| `support` | 支撑位入场 | 适用于趋势市场 |
| `composite` | 综合多种指标 | 推荐策略，适用于各种市场 |

## 策略详解

### 1. 固定网格策略（FixedGridStrategy）

**原理**：使用固定的网格间距计算入场价格。

**公式**：
```
入场价格 = 当前价格 × (1 - 网格间距 × 层级)
```

**示例**：
- 当前价格：67000 USDT
- 网格间距：1%
- A1 入场价：67000 × (1 - 0.01) = 66330 USDT

**配置**：
```json
{
  "entry_price_strategy": {
    "name": "fixed"
  }
}
```

**适用场景**：
- 市场波动性稳定
- 不需要复杂的技术分析
- 追求简单可靠

---

### 2. ATR 动态策略（ATRDynamicStrategy）

**原理**：基于 ATR（平均真实波幅）动态调整网格间距。

**公式**：
```
ATR = 平均真实波幅（14 周期）
动态网格间距 = ATR × 乘数 / 当前价格
入场价格 = 当前价格 × (1 - 动态网格间距 × 层级)
```

**示例**：
- 当前价格：67000 USDT
- ATR：500 USDT
- ATR 占比：500 / 67000 = 0.75%
- 动态网格间距：0.75% × 0.5 = 0.375% → 限制为最小 0.5%
- A1 入场价：67000 × (1 - 0.005) = 66665 USDT

**配置**：
```json
{
  "entry_price_strategy": {
    "name": "atr",
    "params": {
      "atr_period": 14,
      "atr_multiplier": 0.5,
      "min_spacing": 0.005,
      "max_spacing": 0.03
    }
  }
}
```

**参数说明**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `atr_period` | 14 | ATR 计算周期 |
| `atr_multiplier` | 0.5 | ATR 乘数 |
| `min_spacing` | 0.005 | 最小网格间距（0.5%） |
| `max_spacing` | 0.03 | 最大网格间距（3%） |

**适用场景**：
- 市场波动性变化较大
- 需要适应市场波动
- 追求动态调整

---

### 3. 布林带策略（BollingerBandStrategy）

**原理**：将入场价格设置在布林带下轨附近。

**公式**：
```
中轨 = N 周期移动平均线
标准差 = N 周期标准差
下轨 = 中轨 - 2 × 标准差
入场价格 = max(下轨, 当前价格 × (1 - 最小间距))
```

**示例**：
- 当前价格：67000 USDT
- 中轨：66500 USDT
- 标准差：300 USDT
- 下轨：66500 - 2 × 300 = 65900 USDT
- 最小入场价：67000 × (1 - 0.005) = 66665 USDT
- A1 入场价：max(65900, 66665) = 66665 USDT

**配置**：
```json
{
  "entry_price_strategy": {
    "name": "bollinger",
    "params": {
      "period": 20,
      "std_multiplier": 2,
      "min_spacing": 0.005
    }
  }
}
```

**参数说明**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `period` | 20 | 布林带周期 |
| `std_multiplier` | 2 | 标准差乘数 |
| `min_spacing` | 0.005 | 最小网格间距（0.5%） |

**适用场景**：
- 震荡市场
- 价格在布林带内波动
- 追求超卖区域入场

---

### 4. 支撑位策略（SupportLevelStrategy）

**原理**：将入场价格设置在最近支撑位附近。

**公式**：
```
支撑位 = 最近 N 根 K 线的最低价
入场价格 = max(支撑位, 当前价格 × (1 - 最小间距))
```

**示例**：
- 当前价格：67000 USDT
- 最近 20 根 K 线最低价：66000 USDT
- 最小入场价：67000 × (1 - 0.005) = 66665 USDT
- A1 入场价：max(66000, 66665) = 66665 USDT

**配置**：
```json
{
  "entry_price_strategy": {
    "name": "support",
    "params": {
      "lookback": 20,
      "min_spacing": 0.005
    }
  }
}
```

**参数说明**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `lookback` | 20 | 回溯 K 线数量 |
| `min_spacing` | 0.005 | 最小网格间距（0.5%） |

**适用场景**：
- 趋势市场
- 价格在支撑位附近反弹
- 追求技术支撑入场

---

### 5. 综合策略（CompositeStrategy）

**原理**：综合多种技术指标，找到最优入场价格。

**公式**：
```
ATR 入场价 = ATR 策略计算
布林带入场价 = 布林带策略计算
支撑位入场价 = 支撑位策略计算
入场价格 = max(ATR 入场价, 布林带入场价, 支撑位入场价)
```

**示例**：
- ATR 入场价：66665 USDT
- 布林带入场价：66665 USDT
- 支撑位入场价：66665 USDT
- A1 入场价：max(66665, 66665, 66665) = 66665 USDT

**配置**：
```json
{
  "entry_price_strategy": {
    "name": "composite"
  }
}
```

**适用场景**：
- 各种市场环境
- 追求稳健入场
- 综合多种技术指标

---

## 配置文件使用说明

### 完整配置示例

```json
{
  "symbol": "BTCUSDT",
  "total_amount_quote": 5000,
  "leverage": 10,
  "decay_factor": 0.5,
  "max_entries": 4,
  "valid_amplitudes": [1, 2, 3, 4, 5, 6, 7, 8, 9],
  "weights": [0.0852, 0.2956, 0.3177, 0.137, 0.1008, 0.0282, 0.0271, 0.0066, 0.0019],
  "grid_spacing": 0.01,
  "exit_profit": 0.01,
  "stop_loss": 0.08,
  "total_expected_return": 0.2942,
  "entry_price_strategy": {
    "name": "atr",
    "params": {
      "atr_period": 14,
      "atr_multiplier": 0.5,
      "min_spacing": 0.005,
      "max_spacing": 0.03
    }
  }
}
```

### 配置项说明

| 配置项 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `entry_price_strategy` | Object | 否 | 入场价格策略配置 |
| `entry_price_strategy.name` | String | 是 | 策略名称 |
| `entry_price_strategy.params` | Object | 否 | 策略参数 |

### 默认行为

如果未配置 `entry_price_strategy`，系统将使用 `fixed` 策略（固定网格间距）。

### 策略切换

**切换到 ATR 策略**：
```json
{
  "entry_price_strategy": {
    "name": "atr"
  }
}
```

**切换到布林带策略**：
```json
{
  "entry_price_strategy": {
    "name": "bollinger"
  }
}
```

**切换到支撑位策略**：
```json
{
  "entry_price_strategy": {
    "name": "support"
  }
}
```

**切换到综合策略**：
```json
{
  "entry_price_strategy": {
    "name": "composite"
  }
}
```

**使用固定网格策略**：
```json
{
  "entry_price_strategy": {
    "name": "fixed"
  }
}
```

---

## 自定义策略

### 创建自定义策略

```python
from autofish_core import EntryPriceStrategy
from decimal import Decimal
from typing import Dict, List, Optional

class MyCustomStrategy(EntryPriceStrategy):
    """自定义入场价格策略"""
    
    @property
    def name(self) -> str:
        return "my_custom"
    
    def calculate_entry_price(
        self,
        current_price: Decimal,
        level: int,
        grid_spacing: Decimal,
        klines: Optional[List[Dict]] = None,
        **kwargs
    ) -> Decimal:
        # 实现自定义逻辑
        # 例如：基于 RSI 指标计算入场价格
        
        return entry_price
```

### 注册自定义策略

```python
from autofish_core import EntryPriceStrategyFactory

EntryPriceStrategyFactory.register("my_custom", MyCustomStrategy)
```

### 使用自定义策略

```json
{
  "entry_price_strategy": {
    "name": "my_custom",
    "params": {
      "param1": "value1",
      "param2": "value2"
    }
  }
}
```

---

## 策略选择建议

### 市场环境与策略匹配

| 市场环境 | 推荐策略 | 原因 |
|----------|----------|------|
| 稳定市场 | `fixed` | 波动性稳定，固定间距足够 |
| 高波动市场 | `atr` | 动态适应波动性变化 |
| 震荡市场 | `bollinger` | 在超卖区域入场 |
| 趋势市场 | `support` | 在支撑位附近入场 |
| 不确定市场 | `composite` | 综合多种指标，更稳健 |

### 参数调优建议

**ATR 策略**：
- 高波动市场：增大 `atr_multiplier`（如 0.8）
- 低波动市场：减小 `atr_multiplier`（如 0.3）

**布林带策略**：
- 宽幅震荡：增大 `std_multiplier`（如 2.5）
- 窄幅震荡：减小 `std_multiplier`（如 1.5）

**支撑位策略**：
- 短期支撑：减小 `lookback`（如 10）
- 长期支撑：增大 `lookback`（如 30）

---

## 注意事项

1. **仅 A1 生效**：入场价格策略仅对 A1 订单生效，其他层级仍使用固定网格间距。

2. **K 线数据**：ATR、布林带、支撑位策略需要 K 线数据，系统会自动获取 30 根 1 小时 K 线。

3. **数据不足**：如果 K 线数据不足，系统会自动回退到固定网格策略。

4. **价格限制**：所有策略都会确保入场价格低于当前价格，并满足最小间距要求。

5. **日志记录**：系统会记录策略计算过程，便于调试和分析。

---

## 常见问题

### Q1: 为什么入场价格和预期不一致？

**A**: 可能原因：
- K 线数据不足，回退到固定网格策略
- 动态网格间距超出限制范围
- 入场价格低于最小间距限制

### Q2: 如何查看策略计算过程？

**A**: 查看日志文件 `logs/binance_live.log`，搜索策略名称（如 `[ATR策略]`）。

### Q3: 策略参数如何优化？

**A**: 建议使用回测功能测试不同参数组合，选择最优参数。

### Q4: 可以组合多个策略吗？

**A**: 使用 `composite` 策略可以综合多种技术指标。

---

## 更新日志

- **2026-03-08**: 初始版本，支持 5 种入场价格策略

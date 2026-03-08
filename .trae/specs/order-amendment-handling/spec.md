# 订单修改事件处理规范

## 概述

当用户手动修改 Binance 上的订单时，程序需要正确处理这些修改事件，同步更新本地状态。

## Binance 事件类型

### 1. 普通订单事件 (ORDER_TRADE_UPDATE)

| 执行类型 (x) | 说明 | 当前处理 |
|-------------|------|----------|
| NEW | 新订单 | ❌ 未处理 |
| TRADE | 成交 | ✅ 已处理（FILLED 分支） |
| FILLED | 完全成交 | ✅ 已处理 |
| CANCELED | 已取消 | ✅ 已处理 |
| EXPIRED | 已过期 | ❌ 未处理 |
| AMENDMENT | 订单修改 | ✅ 已处理（价格、数量） |
| TRADE_PREVENT | STP 触发 | ❌ 未处理 |

### 2. Algo 条件单事件 (ALGO_UPDATE)

| 状态 (X) | 说明 | 当前处理 |
|----------|------|----------|
| NEW | 新条件单 | ✅ 已处理（匹配订单、更新价格） |
| FILLED | 条件单触发成交 | ✅ 已处理（止盈/止损） |
| CANCELED | 条件单取消 | ✅ 已处理 |
| EXPIRED | 条件单过期 | ❌ 未处理 |
| REJECTED | 条件单被拒绝 | ❌ 未处理 |
| TRIGGERED | 条件单已触发 | ❌ 未处理 |

## 场景分析

### 场景 1: 入场单修改（AMENDMENT）

```
用户操作: 修改 pending 订单的价格或数量
Binance 事件: ORDER_TRADE_UPDATE, x=AMENDMENT
本地处理:
  - 更新入场价格 → 同时更新止盈止损价格
  - 更新数量
  - 保存状态
```

**当前状态**: ✅ 已实现

### 场景 2: 止盈止损单修改

```
用户操作: 修改 filled 订单的止盈/止损触发价格
Binance 事件: ALGO_UPDATE, X=NEW
本地处理:
  - 更新止盈价格
  - 更新止损价格
  - 保存状态
```

**当前状态**: ✅ 已实现

### 场景 3: 入场单过期（EXPIRED）

```
用户操作: 无（订单超过有效期）
Binance 事件: ORDER_TRADE_UPDATE, x=EXPIRED
本地处理:
  - 删除本地订单
  - 取消关联的止盈止损单（如果有）
```

**当前状态**: ❌ 未实现

### 场景 4: 条件单过期（EXPIRED）

```
用户操作: 无（条件单超过有效期）
Binance 事件: ALGO_UPDATE, X=EXPIRED
本地处理:
  - 标记止盈/止损单为 None
  - 需要补单
```

**当前状态**: ❌ 未实现

### 场景 5: 条件单被拒绝（REJECTED）

```
用户操作: 无（下条件单失败）
Binance 事件: ALGO_UPDATE, X=REJECTED
本地处理:
  - 标记止盈/止损单为 None
  - 需要补单
```

**当前状态**: ❌ 未实现

### 场景 6: 条件单已触发（TRIGGERED）

```
用户操作: 无（条件单价格达到触发价）
Binance 事件: ALGO_UPDATE, X=TRIGGERED
本地处理:
  - 等待成交（FILLED 事件）
```

**当前状态**: ❌ 未实现（可能不需要特殊处理）

### 场景 7: STP 触发（TRADE_PREVENT）

```
用户操作: 无（自成交保护触发）
Binance 事件: ORDER_TRADE_UPDATE, x=TRADE_PREVENT
本地处理:
  - 订单被取消
  - 需要重新下单
```

**当前状态**: ❌ 未实现

## 完整性检查

### 已实现 ✅

| 场景 | 事件 | 处理 |
|------|------|------|
| 入场单成交 | ORDER_TRADE_UPDATE + FILLED | 更新状态，下止盈止损单 |
| 入场单取消 | ORDER_TRADE_UPDATE + CANCELED | 更新状态 |
| 入场单修改 | ORDER_TRADE_UPDATE + AMENDMENT | 更新价格、数量、止盈止损价 |
| 止盈止损单成交 | ALGO_UPDATE + FILLED | 平仓，创建新订单 |
| 止盈止损单取消 | ALGO_UPDATE + CANCELED | 标记为 None |
| 止盈止损单新建 | ALGO_UPDATE + NEW | 匹配订单，更新价格 |

### 未实现 ❌

| 场景 | 事件 | 建议处理 |
|------|------|----------|
| 入场单过期 | ORDER_TRADE_UPDATE + EXPIRED | 删除订单，取消关联条件单 |
| 条件单过期 | ALGO_UPDATE + EXPIRED | 标记为 None，需要补单 |
| 条件单拒绝 | ALGO_UPDATE + REJECTED | 标记为 None，需要补单 |
| 条件单触发 | ALGO_UPDATE + TRIGGERED | 可选：日志记录 |
| STP 触发 | ORDER_TRADE_UPDATE + TRADE_PREVENT | 删除订单，重新下单 |

## 结论

**当前实现覆盖了主要场景，但缺少以下边界情况处理：**

1. **EXPIRED 事件**：订单/条件单过期
2. **REJECTED 事件**：条件单被拒绝
3. **TRADE_PREVENT 事件**：STP 触发

建议优先级：
1. 高：EXPIRED 事件（订单过期较常见）
2. 中：REJECTED 事件（条件单被拒绝）
3. 低：TRADE_PREVENT 事件（STP 触发较少见）

# A1 超时重挂优化分析

## 文档信息

| 项目 | 内容 |
|------|------|
| 创建日期 | 2026-04-04 |
| 版本 | 1.0 |
| 关联文档 | `docs/20260326_trading_algorithm.md`, `binance_live.py` |

---

## 一、当前超时重挂流程分析

### 1.1 现有流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     A1 超时重挂流程                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 检查超时条件                                                 │
│     └── 挂单时间 > a1_timeout_minutes 分钟                       │
│     └── 每 5 分钟检查一次                                        │
│                                                                  │
│  2. 取消旧订单                                                   │
│     ├── DELETE /fapi/v1/order (取消入场单)                       │
│     └── DELETE /fapi/v1/algo/order (取消止盈止损单)              │
│                                                                  │
│  3. 计算新订单                                                   │
│     └── new_entry_price = current_price * (1 - grid_spacing)    │
│     └── 基于当前价格重新计算                                     │
│                                                                  │
│  4. 下新订单                                                     │
│     └── POST /fapi/v1/order                                     │
│     └── POST /fapi/v1/algo/order (止盈止损)                      │
│                                                                  │
│  ⚠️ 问题：没有评估新订单是否比旧订单更有优势                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 入场价格计算逻辑

**位置**: `autofish_core.py` line 887

```python
entry_price = base_price * (Decimal("1") - self.grid_spacing * level)
```

对于 A1 (level=1):
- `entry_price = current_price * (1 - grid_spacing)`
- 如果 `grid_spacing = 0.01`，则入场价 = 当前价 × 0.99

### 1.3 超时重挂代码

**位置**: `binance_live.py` line 3744-3768

```python
# 取消旧订单后...
klines = await self._get_recent_klines()
new_first_entry = await self._create_order(1, current_price, klines)

# 没有比较新旧价格的逻辑
# 直接下新订单

await self._place_entry_order(
    new_first_entry,
    is_supplement=False,
    is_timeout_refresh=True,
    old_order=timeout_first_entry,
    timeout_minutes=self.a1_timeout_minutes,
    current_price=current_price
)
```

---

## 二、问题分析

### 2.1 核心问题：无价格优势评估

**场景描述**：

```
时间 T1:
  - 当前价格: 100 USDT
  - 入场价格: 99 USDT (100 * 0.99)
  - A1 挂单等待成交

时间 T2 (超时后):
  - 当前价格: 100.1 USDT (仅上涨 0.1%)
  - 新入场价格: 99.1 USDT (100.1 * 0.99)

问题：
  - 新入场价 (99.1) 与旧入场价 (99) 仅差 0.1%
  - 重挂后的订单位置几乎没有变化
  - 成交概率提升微乎其微
  - 但产生了额外的 API 调用和潜在风险
```

### 2.2 重挂成本分析

| 成本项目 | 说明 |
|---------|------|
| API 调用 | 取消订单 1 次 + 下新单 1 次 = 2 次 |
| 速率限制 | 消耗 API 速率配额 |
| 滑点风险 | 取消后重新下单可能有价格变化 |
| 网络延迟 | 可能导致订单状态不一致 |
| 数据库操作 | 删除旧记录 + 插入新记录 |

### 2.3 无效重挂的场景

| 场景 | 价格变化 | 入场价变化 | 是否应该重挂 |
|------|---------|-----------|-------------|
| 价格稳定 | < 0.1% | < 0.1% | ❌ 不应重挂 |
| 价格小幅上涨 | 0.1% - 0.5% | 0.1% - 0.5% | ⚠️ 需评估 |
| 价格大幅上涨 | > 0.5% | > 0.5% | ✅ 应该重挂 |
| 价格下跌 | < 0% | 更接近入场价 | ✅ 可能即将成交 |

---

## 三、优化方案

### 方案 A：价格差异阈值（推荐）

**核心思路**：只有当新入场价与旧入场价的差异超过阈值时才重挂。

```python
async def _should_refresh_order(self, old_order, new_entry_price: Decimal) -> tuple[bool, str]:
    """评估是否应该重挂订单

    返回:
        (should_refresh: bool, reason: str)
    """
    if not old_order:
        return True, "无旧订单"

    old_entry_price = old_order.entry_price
    price_diff_pct = abs(new_entry_price - old_entry_price) / old_entry_price

    # 配置参数
    min_price_diff_pct = self.config.get("min_refresh_price_diff", Decimal("0.003"))  # 0.3%

    if price_diff_pct < min_price_diff_pct:
        return False, f"价格差异 {price_diff_pct:.3%} < 阈值 {min_price_diff_pct:.3%}"

    return True, f"价格差异 {price_diff_pct:.3%} >= 阈值 {min_price_diff_pct:.3%}"
```

**配置项**：
```json
{
    "min_refresh_price_diff": 0.003  // 0.3% 最小价格差异
}
```

### 方案 B：多因子评估

**核心思路**：综合考虑多个因素决定是否重挂。

```python
async def _evaluate_refresh_necessity(self, old_order, current_price: Decimal) -> dict:
    """多因子评估重挂必要性

    返回:
        {
            'should_refresh': bool,
            'score': float,  # 0-100 分
            'factors': dict
        }
    """
    factors = {}
    score = 0

    # 因子 1: 价格差异 (权重 40%)
    new_entry_price = current_price * (1 - self.grid_spacing)
    price_diff_pct = (new_entry_price - old_order.entry_price) / old_order.entry_price
    if price_diff_pct > 0.005:  # > 0.5%
        factors['price_diff'] = {'score': 40, 'value': price_diff_pct}
        score += 40
    elif price_diff_pct > 0.003:  # > 0.3%
        factors['price_diff'] = {'score': 30, 'value': price_diff_pct}
        score += 30
    else:
        factors['price_diff'] = {'score': 0, 'value': price_diff_pct}

    # 因子 2: 超时次数 (权重 20%)
    if old_order.timeout_count >= 3:
        factors['timeout_count'] = {'score': 20, 'value': old_order.timeout_count}
        score += 20

    # 因子 3: 市场波动 (权重 40%)
    volatility = await self._calculate_recent_volatility()
    if volatility > 0.02:  # 高波动
        factors['volatility'] = {'score': 40, 'value': volatility}
        score += 40
    elif volatility > 0.01:
        factors['volatility'] = {'score': 20, 'value': volatility}
        score += 20

    return {
        'should_refresh': score >= 50,  # 50 分以上才重挂
        'score': score,
        'factors': factors
    }
```

### 方案 C：动态调整超时时间

**核心思路**：根据价格变化情况动态调整超时时间。

```python
def _calculate_dynamic_timeout(self, order, current_price: Decimal) -> int:
    """根据价格变化计算动态超时时间

    返回:
        剩余等待时间（分钟）
    """
    base_timeout = self.a1_timeout_minutes

    # 计算入场价与当前价的距离
    distance_pct = (order.entry_price - current_price) / current_price

    if distance_pct < 0.002:  # 价格接近入场价
        # 延长等待时间，可能即将成交
        return base_timeout * 2
    elif distance_pct > 0.01:  # 价格远离入场价
        # 可能需要更长时间等待回调
        return base_timeout
    else:
        return base_timeout
```

### 方案 D：智能等待策略

**核心思路**：不立即重挂，而是等待价格有利变化。

```python
async def _smart_refresh_order(self, old_order, current_price: Decimal) -> None:
    """智能重挂策略

    策略：
    1. 如果价格正在向入场价移动，继续等待
    2. 如果价格远离入场价，评估是否重挂
    3. 如果价格稳定，检查是否需要重挂
    """
    new_entry_price = current_price * (1 - self.grid_spacing)
    price_trend = await self._get_price_trend()  # up/down/stable

    if price_trend == 'down':
        # 价格下跌，入场价更接近当前价，可能即将成交
        logger.info(f"[智能重挂] 价格下跌趋势，继续等待")
        return

    if price_trend == 'up':
        price_diff = (new_entry_price - old_order.entry_price) / old_order.entry_price
        if price_diff > self.min_price_diff_pct:
            # 价格上涨且差异足够大，重挂
            await self._do_refresh_order(old_order, current_price)
        else:
            logger.info(f"[智能重挂] 价格上涨但差异不足，继续等待")
        return

    # 价格稳定，评估超时次数
    if old_order.timeout_count >= 5:
        logger.info(f"[智能重挂] 已超时 {old_order.timeout_count} 次，尝试重挂")
        await self._do_refresh_order(old_order, current_price)
```

---

## 四、推荐实现

### 4.1 短期方案（方案 A）

简单有效，最小改动：

**修改位置**: `binance_live.py` line 3743-3768

```python
async def _check_and_handle_first_entry_timeout(self, current_price: Decimal) -> None:
    """检查并处理第一笔入场订单超时"""
    # ... 原有超时检查代码 ...

    # === 新增：价格差异评估 ===
    klines = await self._get_recent_klines()
    new_first_entry = await self._create_order(1, current_price, klines)

    # 评估是否应该重挂
    should_refresh, reason = await self._should_refresh_order(
        timeout_first_entry,
        new_first_entry.entry_price
    )

    if not should_refresh:
        logger.info(f"[A1 超时] 跳过重挂: {reason}")
        print(f"   ⏭️ 跳过重挂: {reason}")

        # 重置计时，继续等待
        timeout_first_entry.created_at = datetime.now()
        return

    # 继续原有的重挂逻辑
    new_first_entry.timeout_count = timeout_first_entry.timeout_count + 1
    # ...
```

### 4.2 配置项

**位置**: `config.json` 或 case 配置

```json
{
    "timeout": {
        "a1_timeout_minutes": 10,
        "min_refresh_price_diff": 0.003,
        "max_timeout_count": 10,
        "enable_smart_refresh": true
    }
}
```

### 4.3 指标统计

建议添加以下统计指标：

| 指标 | 说明 |
|------|------|
| `skipped_refresh_count` | 因价格差异不足跳过的重挂次数 |
| `avg_price_diff_on_refresh` | 重挂时的平均价格差异 |
| `refresh_success_rate` | 重挂后成交率 |

---

## 五、其他潜在问题

### 5.1 问题：超时检查频率固定

**现状**：每 5 分钟检查一次

**问题**：
- 价格快速变化时，5 分钟间隔可能太长
- 价格稳定时，5 分钟检查浪费资源

**建议**：根据价格波动动态调整检查频率

### 5.2 问题：无最大超时次数限制

**现状**：订单可以无限次超时重挂

**问题**：
- 如果行情一直不利，会持续重挂
- 浪费资源且无法成交

**建议**：添加 `max_timeout_count` 配置项

### 5.3 问题：超时重挂后未重新计算入场资金

**现状**：超时重挂时使用原有的入场资金

**问题**：
- 如果资金池状态变化，可能应该重新计算

**建议**：评估是否需要重新计算入场资金

---

## 六、实施计划

### Phase 1: 价格差异阈值（优先级高）

1. 添加 `_should_refresh_order()` 方法
2. 添加 `min_refresh_price_diff` 配置项
3. 在超时处理流程中集成评估逻辑
4. 添加跳过重挂的日志和统计

### Phase 2: 最大超时次数限制

1. 添加 `max_timeout_count` 配置项
2. 超过最大次数后停止重挂
3. 发送通知提醒用户

### Phase 3: 智能重挂策略

1. 实现价格趋势检测
2. 实现动态超时时间
3. 完善统计指标

---

*文档版本: 1.0*
*创建日期: 2026-04-04*
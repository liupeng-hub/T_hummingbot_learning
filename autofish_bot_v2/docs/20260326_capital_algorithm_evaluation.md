# Autofish Bot V2 复利资金算法评估报告

**评估日期**: 2026-03-26  
**评估范围**: 资金池管理、复利计算、入场资金策略、爆仓恢复、提现机制

---

## 目录

1. [资金池计算逻辑验证](#1-资金池计算逻辑验证)
2. [复利增长计算验证](#2-复利增长计算验证)
3. [三种模式对比分析](#3-三种模式对比分析)
4. [潜在问题与改进建议](#4-潜在问题与改进建议)
5. [总结](#5-总结)

---

## 1. 资金池计算逻辑验证

### 1.1 核心数据结构

系统使用 `ProgressiveCapitalTracker` 类管理资金池，核心属性如下：

```python
@dataclass
class ProgressiveCapitalTracker:
    initial_capital: Decimal          # 初始资金
    trading_capital: Decimal          # 当前交易资金（动态变化）
    profit_pool: Decimal              # 利润池（锁定的利润）
    total_profit: Decimal             # 累计利润
    total_loss: Decimal               # 累计亏损
    max_capital: Decimal              # 历史最高资金
    withdrawal_count: int             # 提现次数
    liquidation_count: int            # 爆仓次数
```

### 1.2 资金更新逻辑分析

**代码位置**: [autofish_core.py:2313-2356](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/autofish_core.py#L2313-L2356)

```python
def update_capital(self, profit: Decimal, kline_time: datetime = None) -> Dict:
    old_trading_capital = self.trading_capital
    
    # 直接使用包含杠杆的利润来更新资金池
    actual_profit = profit
    
    if actual_profit > 0:
        self.trading_capital += actual_profit
        self.total_profit += actual_profit
    else:
        self.trading_capital += actual_profit
        self.total_loss += abs(actual_profit)
    
    if self.trading_capital > self.max_capital:
        self.max_capital = self.trading_capital
```

**✅ 验证结论**: 资金更新逻辑正确

- 盈利时：`trading_capital` 增加，`total_profit` 累计
- 亏损时：`trading_capital` 减少，`total_loss` 累计
- `max_capital` 正确跟踪历史最高资金

### 1.3 盈亏计算验证（杠杆效应）

**代码位置**: [autofish_core.py:927-938](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/autofish_core.py#L927-L938)

```python
def calculate_profit(self, order: Autofish_Order, close_price: Decimal) -> Decimal:
    profit = order.stake_amount * (close_price - order.entry_price) / order.entry_price * self.leverage
    return profit
```

**公式分析**:
```
profit = stake_amount × (close_price - entry_price) / entry_price × leverage
       = stake_amount × 价格变化率 × 杠杆倍数
```

**示例验证**:
- 入场价: 50000 USDT
- 平仓价: 50500 USDT (止盈 1%)
- 投入金额: 100 USDT
- 杠杆: 10x

```
profit = 100 × (50500 - 50000) / 50000 × 10
       = 100 × 0.01 × 10
       = 10 USDT
```

**✅ 验证结论**: 盈亏计算正确包含杠杆效应

**⚠️ 注意事项**: 利润计算公式假设使用全仓模式。在逐仓模式下，最大亏损被限制在保证金范围内，但当前实现未区分这两种模式。

---

## 2. 复利增长计算验证

### 2.1 入场资金策略架构

系统使用策略模式管理入场资金计算：

```
EntryCapitalStrategy (抽象基类)
    ├── FixedCapitalStrategy      (固定模式)
    ├── CompoundCapitalStrategy   (复利模式)
    └── DefaultCapitalStrategy    (默认模式)
```

**代码位置**: [autofish_core.py:2123-2231](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/autofish_core.py#L2123-L2231)

### 2.2 Compound 模式入场资金计算

**代码位置**: [autofish_core.py:2188-2208](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/autofish_core.py#L2188-L2208)

```python
class CompoundCapitalStrategy(EntryCapitalStrategy):
    def calculate_entry_capital(self, capital_pool, level: int, chain_state: Any) -> Decimal:
        total_capital = self._get_total_capital(capital_pool)  # trading_capital + profit_pool
        if level == 1:
            chain_state.round_entry_capital = total_capital
            chain_state.round_entry_total_capital = total_capital
        return chain_state.round_entry_capital
    
    def calculate_entry_total_capital(self, capital_pool, level: int, chain_state: Any) -> Decimal:
        total_capital = self._get_total_capital(capital_pool)
        if level == 1:
            chain_state.round_entry_capital = total_capital
            chain_state.round_entry_total_capital = total_capital
        return chain_state.round_entry_total_capital
```

**✅ 验证结论**: Compound 模式正确使用总资金（交易资金 + 利润池）作为入场资金

### 2.3 轮次资金锁定机制

**关键逻辑**: 入场资金在 A1 成交时锁定，同一轮次内保持不变

**代码位置**: [binance_backtest.py:289-296](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/binance_backtest.py#L289-L296)

```python
pending_order.entry_capital = self.capital_strategy.calculate_entry_capital(
    self.capital_pool, pending_order.level, self.chain_state
)
pending_order.entry_total_capital = self.capital_strategy.calculate_entry_total_capital(
    self.capital_pool, pending_order.level, self.chain_state
)
```

**轮次资金更新逻辑**: [binance_backtest.py:472-477](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/binance_backtest.py#L472-L477)

```python
new_total_capital = self.capital_pool.trading_capital + (
    self.capital_pool.profit_pool if hasattr(self.capital_pool, 'profit_pool') else Decimal('0')
)
self.chain_state.round_entry_total_capital = new_total_capital
```

**⚠️ 潜在问题**: 轮次总资金在每次交易后更新，但入场资金保持不变。这导致：
- `entry_capital`: A1 成交时锁定，整轮不变
- `entry_total_capital`: 每次交易后更新为当前总资金

**建议**: 明确区分这两个字段的语义，或考虑是否需要在同一轮次内保持 `entry_total_capital` 不变。

---

## 3. 三种模式对比分析

### 3.1 模式定义对比表

| 模式 | entry_capital | entry_total_capital | 说明 |
|------|--------------|---------------------|------|
| **fixed** | `initial_capital` | `initial_capital` | 始终使用初始资金，无复利效应 |
| **compound** | `trading_capital + profit_pool` | `trading_capital + profit_pool` | 使用总资金，完全复利 |
| **default** | `trading_capital` | `trading_capital + profit_pool` | 入场资金=交易资金，总资金包含利润池 |

### 3.2 实际效果对比

**假设场景**:
- 初始资金: 10000 USDT
- 第一轮盈利: 1000 USDT（已触发提现，利润池 5000 USDT，交易资金 15000 USDT）

| 模式 | 入场资金 | 入场总资金 | 第二轮最大投入 |
|------|---------|-----------|--------------|
| fixed | 10000 | 10000 | 10000 |
| compound | 20000 | 20000 | 20000 |
| default | 15000 | 20000 | 15000 |

### 3.3 模式选择建议

| 模式 | 适用场景 | 风险等级 | 收益预期 |
|------|---------|---------|---------|
| fixed | 保守策略，稳定收益 | 低 | 低 |
| compound | 激进策略，追求高收益 | 高 | 高 |
| default | 平衡策略，适度复利 | 中 | 中 |

---

## 4. 潜在问题与改进建议

### 4.1 资金计算漏洞

#### 问题 1: A1 超时重挂时未更新入场资金

**代码位置**: [binance_backtest.py:525-536](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/binance_backtest.py#L525-L536)

```python
def _check_first_entry_timeout(self, current_price: Decimal, current_time: datetime) -> None:
    # ... 省略 ...
    self.chain_state.orders.remove(timeout_first_entry)
    
    new_first_entry = self._create_order(1, current_price, self.klines_history, kline_time=current_time)
    self.chain_state.orders.append(new_first_entry)
    # ⚠️ 未更新 chain_state.round_entry_capital 和 round_entry_total_capital
```

**影响**: A1 超时重挂后，新订单可能使用旧的入场资金数据。

**建议修复**:
```python
# 在创建新订单后添加
if hasattr(self, 'capital_strategy'):
    new_first_entry.entry_capital = self.capital_strategy.calculate_entry_capital(
        self.capital_pool, 1, self.chain_state
    )
    new_first_entry.entry_total_capital = self.capital_strategy.calculate_entry_total_capital(
        self.capital_pool, 1, self.chain_state
    )
```

#### 问题 2: 强制平仓时入场资金记录不一致

**代码位置**: [binance_backtest.py:949-969](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/binance_backtest.py#L949-L969)

```python
def _close_all_positions(self, price: Decimal, timestamp: int, reason: str, kline_time: datetime = None):
    for order in filled_orders:
        # ...
        entry_total_capital = self.chain_state.round_entry_total_capital
        # ⚠️ 使用当前轮次的 round_entry_total_capital，而非订单入场时的值
```

**影响**: 强制平仓记录的 `entry_total_capital` 可能与订单实际入场时的值不同。

**建议**: 在订单对象中保存入场时的 `entry_total_capital`，而非使用链状态的当前值。

### 4.2 爆仓恢复逻辑分析

**代码位置**: [autofish_core.py:2399-2420](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/autofish_core.py#L2399-L2420)

```python
def check_liquidation(self) -> bool:
    threshold_amount = self.initial_capital * self.liquidation_threshold
    return self.trading_capital < threshold_amount

def recover_from_liquidation(self) -> bool:
    if self.profit_pool >= self.initial_capital:
        self.profit_pool -= self.initial_capital
        self.trading_capital = self.initial_capital
        self.liquidation_count += 1
        return True
    return False
```

**爆仓阈值计算**: [autofish_core.py:2430-2433](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/autofish_core.py#L2430-L2433)

```python
auto_liquidation_threshold = 1 - (stop_loss * leverage)
# 例如: stop_loss=0.08, leverage=10 → threshold=0.2
```

**✅ 验证结论**: 爆仓恢复逻辑合理

- 爆仓阈值自动计算：`1 - (止损比例 × 杠杆)`
- 恢复条件：利润池 ≥ 初始资金
- 恢复后：交易资金重置为初始资金

**⚠️ 潜在问题**: 如果利润池不足以恢复，系统无法继续交易，需要外部资金注入。

**建议**: 添加告警机制，在利润池接近耗尽时提醒用户。

### 4.3 提现机制分析

**代码位置**: [autofish_core.py:2358-2397](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/autofish_core.py#L2358-L2397)

```python
def check_withdrawal(self, kline_time: datetime = None) -> Optional[Dict]:
    threshold_amount = self.initial_capital * self.withdrawal_threshold
    
    if self.trading_capital >= threshold_amount:
        retain_amount = self.initial_capital * self.withdrawal_retain
        withdrawal_amount = self.trading_capital - retain_amount
        
        if withdrawal_amount > 0:
            self.profit_pool += withdrawal_amount
            self.trading_capital = retain_amount
            self.withdrawal_count += 1
            self.total_withdrawal += withdrawal_amount
```

**预设策略参数**: [autofish_core.py:2434-2448](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/autofish_core.py#L2434-L2448)

| 策略 | 提现阈值 | 保留倍数 | 说明 |
|------|---------|---------|------|
| baoshou (保守) | 2.0x | 1.5x | 资金翻倍时提现，保留 1.5 倍 |
| wenjian (稳健) | 3.0x | 2.0x | 资金三倍时提现，保留 2 倍 |
| jijin (激进) | 1.5x | 1.2x | 资金 1.5 倍时提现，保留 1.2 倍 |
| fuli (复利) | 999.0x | 1.0x | 几乎不提现，最大化复利 |

**✅ 验证结论**: 提现机制设计合理

**⚠️ 潜在问题**: 
1. 提现后 `trading_capital` 减少，可能导致下一轮入场资金不足
2. 在 compound 模式下，提现后总资金减少，影响复利效果

**建议**: 添加提现后的最小资金检查，确保交易资金不低于最低入场要求。

### 4.4 其他发现

#### 问题 3: 订单创建时资金来源不一致

**代码位置**: [binance_backtest.py:164-180](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/binance_backtest.py#L164-L180)

```python
def _create_order(self, level: int, base_price: Decimal, ...):
    if hasattr(self, 'capital_pool'):
        if self.capital_pool.strategy == 'guding':
            total_amount = self.capital_pool.initial_capital
        elif self.capital_pool.strategy == 'fuli':
            total_amount = self.capital_pool.trading_capital + self.capital_pool.profit_pool
        else:
            total_amount = self.capital_pool.trading_capital
    else:
        total_amount = self.config.get("total_amount_quote", Decimal("1200"))
```

**⚠️ 问题**: 这里的逻辑与 `EntryCapitalStrategy` 策略模式重复，且使用 `strategy` 字段判断而非 `entry_mode`。

**建议**: 统一使用 `EntryCapitalStrategy` 计算入场资金，移除 `_create_order` 中的重复逻辑。

#### 问题 4: 测试用例过时

**代码位置**: [test_capital_pool.py:16](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/tests/unit/test_capital_pool.py#L16)

```python
Autofish_CapitalPool = autofish_core.Autofish_CapitalPool
```

**问题**: 测试文件引用 `Autofish_CapitalPool` 类，但该类已被重构为 `ProgressiveCapitalTracker` 和 `FixedCapitalTracker`。

**建议**: 更新测试用例以匹配新的类结构。

---

## 5. 总结

### 5.1 验证结果汇总

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 资金池更新逻辑 | ✅ 正确 | 盈亏正确更新 trading_capital |
| 杠杆效应计算 | ✅ 正确 | 利润公式正确包含杠杆倍数 |
| Compound 模式 | ✅ 正确 | 使用总资金作为入场资金 |
| 三种模式差异 | ✅ 正确 | 模式定义清晰，行为一致 |
| 爆仓恢复逻辑 | ✅ 合理 | 阈值自动计算，恢复条件明确 |
| 提现机制 | ✅ 合理 | 多种策略可选，参数合理 |

### 5.2 发现的问题汇总

| 问题 | 严重程度 | 影响 |
|------|---------|------|
| A1 超时重挂未更新入场资金 | 中 | 数据不一致 |
| 强制平仓入场资金记录不一致 | 低 | 数据追踪不准确 |
| 订单创建资金来源逻辑重复 | 低 | 代码维护性差 |
| 测试用例过时 | 低 | 测试覆盖率下降 |

### 5.3 改进建议优先级

1. **高优先级**: 修复 A1 超时重挂时的入场资金更新问题
2. **中优先级**: 统一订单创建时的资金计算逻辑
3. **低优先级**: 更新测试用例，添加更多边界条件测试

### 5.4 架构评价

整体架构设计良好，使用了策略模式管理不同的入场资金计算方式，代码结构清晰。主要改进方向是消除重复逻辑、完善边界条件处理、更新测试覆盖。

---

**评估人**: AI Assistant  
**审核状态**: 待审核

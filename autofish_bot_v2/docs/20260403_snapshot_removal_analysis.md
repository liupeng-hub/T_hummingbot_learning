# 移除快照表可行性分析

## 文档信息

| 项目 | 内容 |
|------|------|
| 创建日期 | 2026-04-03 |
| 版本 | 1.0 |
| 关联文档 | `docs/20260402_session_recovery_refactor.md` |

---

## 一、当前快照存储内容

### 1.1 `live_state_snapshots` 表结构

```sql
CREATE TABLE live_state_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    snapshot_time TEXT NOT NULL,
    base_price REAL DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    group_id INTEGER DEFAULT 0,
    state_data TEXT DEFAULT '{}',  -- JSON 数据
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### 1.2 `state_data` JSON 内容

```json
{
    "base_price": "67500.00",
    "group_id": 5,
    "capital_pool": {
        "trading_capital": 5000.0,
        "profit_pool": 125.5,
        "total_profit": 350.0,
        "total_loss": 224.5,
        "withdrawal_count": 0,
        "liquidation_count": 0
    },
    "results": {
        "total_trades": 15,
        "win_trades": 9,
        "loss_trades": 6,
        "total_profit": 350.0,
        "total_loss": 224.5
    }
}
```

**注意**：`orders` 字段已在上一轮改造中移除，不再保存到快照。

---

## 二、数据库表与快照数据对比

### 2.1 数据来源对照表

| 快照数据 | 数据库表 | 字段 | 是否可替代 | 备注 |
|---------|---------|------|-----------|------|
| `capital_pool.trading_capital` | `live_capital_statistics` | `trading_capital` | ✅ 是 | 完全一致 |
| `capital_pool.profit_pool` | `live_capital_statistics` | `profit_pool` | ✅ 是 | 完全一致 |
| `capital_pool.total_profit` | `live_capital_statistics` | `total_profit` | ✅ 是 | 完全一致 |
| `capital_pool.total_loss` | `live_capital_statistics` | `total_loss` | ✅ 是 | 完全一致 |
| `capital_pool.withdrawal_count` | `live_capital_statistics` | `withdrawal_count` | ✅ 是 | 完全一致 |
| `capital_pool.liquidation_count` | `live_capital_statistics` | `liquidation_count` | ✅ 是 | 完全一致 |
| `results.total_trades` | `live_sessions` | `total_trades` | ✅ 是 | 完全一致 |
| `results.win_trades` | `live_sessions` | `win_trades` | ✅ 是 | 完全一致 |
| `results.loss_trades` | `live_sessions` | `loss_trades` | ✅ 是 | 完全一致 |
| `results.total_profit` | `live_sessions` | `total_profit` | ✅ 是 | 完全一致 |
| `results.total_loss` | `live_sessions` | `total_loss` | ✅ 是 | 完全一致 |
| `group_id` | `live_orders` | `group_id` | ✅ 是 | 需要取 MAX |
| `base_price` | 无 | - | ❌ 否 | **缺失** |

### 2.2 详细字段对比

#### `live_capital_statistics` 表

| 字段 | 快照对应 |
|------|---------|
| `trading_capital` | `capital_pool.trading_capital` |
| `profit_pool` | `capital_pool.profit_pool` |
| `total_profit` | `capital_pool.total_profit` |
| `total_loss` | `capital_pool.total_loss` |
| `withdrawal_count` | `capital_pool.withdrawal_count` |
| `liquidation_count` | `capital_pool.liquidation_count` |
| `initial_capital` | 可从 `live_sessions.initial_capital` 获取 |
| `final_capital` | 可从 `live_sessions.final_capital` 获取 |
| `max_capital` | 快照无此字段，数据库独有 |
| `max_drawdown` | 快照无此字段，数据库独有 |
| `total_trades` | 快照 `results.total_trades` |
| `profit_trades` | 快照 `results.win_trades` |
| `loss_trades` | 快照 `results.loss_trades` |
| `avg_profit` | 快照无，可计算 |
| `avg_loss` | 快照无，可计算 |
| `win_rate` | 快照无，可计算 |

#### `live_sessions` 表

| 字段 | 快照对应 |
|------|---------|
| `total_trades` | `results.total_trades` |
| `win_trades` | `results.win_trades` |
| `loss_trades` | `results.loss_trades` |
| `total_profit` | `results.total_profit` |
| `total_loss` | `results.total_loss` |
| `net_profit` | 快照无，可计算 |
| `initial_capital` | 快照无 |
| `final_capital` | 快照无 |

#### `live_orders` 表

| 字段 | 快照对应 |
|------|---------|
| `group_id` | 快照 `group_id` |
| `level` | 订单层级 |
| `state` | 订单状态 |
| 其他字段 | 订单详情 |

---

## 三、`base_price` 缺失问题

### 3.1 问题分析

`base_price` 是当前基准价格，用于计算入场价：

```python
entry_price = base_price * (1 - grid_spacing * level)
```

**快照中保存**：`base_price` 随状态保存

**数据库中无此字段**：
- `live_sessions` 没有 `base_price` 字段
- `live_orders` 有 `entry_price`，但没有 `base_price`

### 3.2 解决方案

**方案 A**：恢复时使用当前价格

```python
current_price = await self._get_current_price()
base_price = current_price  # 使用当前价格作为基准
```

**优点**：简单，不需要额外存储
**缺点**：可能与原 `base_price` 不同，影响新订单入场价

**方案 B**：从订单推算

```python
# 从最后一个 pending 订单推算
pending_orders = [o for o in orders if o.state == 'pending']
if pending_orders:
    last_order = pending_orders[-1]
    base_price = last_order.entry_price / (1 - grid_spacing * last_order.level)
```

**优点**：保持一致性
**缺点**：如果没有 pending 订单，无法推算

**方案 C**：在 `live_sessions` 表添加 `base_price` 字段

```sql
ALTER TABLE live_sessions ADD COLUMN base_price REAL DEFAULT 0;
```

**优点**：数据完整，可追溯
**缺点**：需要数据库迁移

**推荐方案 C**：添加字段，保证数据完整性。

---

## 四、`group_id` 恢复问题

### 4.1 当前问题

修改后快照不保存 `orders`，`group_id` 从快照加载，可能过期或不存在。

### 4.2 解决方案

从 `live_orders` 表获取最大 `group_id`：

```python
async def _restore_orders(self, current_price: Decimal) -> bool:
    # ... 从数据库加载订单 ...

    # 从订单获取最大 group_id
    if orders:
        max_group_id = max(o.group_id for o in orders if o.group_id)
        self.chain_state.group_id = max_group_id
    else:
        self.chain_state.group_id = 0
```

**优点**：
- 数据来源单一，不会不一致
- 恢复时自动获取正确的 `group_id`

---

## 五、`live_trades` 表用途分析

### 5.1 表结构

```sql
CREATE TABLE live_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    trade_type TEXT,          -- 'take_profit' 或 'stop_loss'
    level INTEGER DEFAULT 1,
    entry_price REAL DEFAULT 0,
    exit_price REAL DEFAULT 0,
    quantity REAL DEFAULT 0,
    profit REAL DEFAULT 0,
    leverage INTEGER DEFAULT 10,
    entry_time TEXT,
    exit_time TEXT,
    holding_duration_seconds INTEGER DEFAULT 0
)
```

### 5.2 写入时机

| 事件 | `trade_type` | 写入位置 |
|------|-------------|---------|
| 止盈触发 | `'take_profit'` | `_handle_take_profit` (line 1288) |
| 止损触发 | `'stop_loss'` | `_handle_stop_loss` (line 1389) |

### 5.3 用途分析

| 用途 | 说明 |
|------|------|
| **交易历史记录** | 记录每笔完整交易（入场→出场） |
| **盈亏分析** | 可按层级、类型分析盈亏 |
| **持仓时长统计** | `holding_duration_seconds` 记录持仓时长 |
| **报表生成** | 用于生成交易报表、统计分析 |

### 5.4 与 `live_orders` 的区别

| 表 | 内容 | 时机 |
|----|------|------|
| `live_orders` | 订单生命周期（pending→filled→closed） | 实时更新 |
| `live_trades` | 完整交易记录（入场价、出场价、盈亏） | 仅平仓时写入 |

**关键区别**：
- `live_orders` 记录订单状态变化
- `live_trades` 记录完整交易的最终结果

### 5.5 是否必要？

**必要**，原因：

1. **数据冗余保护**：`live_orders` 被删除后，`live_trades` 仍保留交易历史
2. **统计分析**：便于按层级、类型统计盈亏
3. **审计追溯**：保留完整的交易记录

---

## 六、移除快照的可行性结论

### 6.1 可移除的数据

| 数据 | 替代来源 | 状态 |
|------|---------|------|
| `capital_pool` | `live_capital_statistics` | ✅ 可移除 |
| `results` | `live_sessions` | ✅ 可移除 |
| `group_id` | `live_orders.MAX(group_id)` | ✅ 可移除 |

### 6.2 需要补充的数据

| 数据 | 解决方案 |
|------|---------|
| `base_price` | 在 `live_sessions` 表添加字段 |

### 6.3 结论

**可以移除快照**，但需要：

1. 在 `live_sessions` 表添加 `base_price` 字段
2. 恢复时从各表加载数据：
   - 订单：`live_orders`
   - 资金池：`live_capital_statistics`
   - 统计：`live_sessions`
   - `group_id`：从 `live_orders` 计算

---

## 七、改造方案

### 7.1 数据库迁移

```sql
-- 添加 base_price 字段
ALTER TABLE live_sessions ADD COLUMN base_price REAL DEFAULT 0;
```

### 7.2 代码修改

```python
async def _restore_orders(self, current_price: Decimal) -> bool:
    """从数据库恢复订单状态"""
    symbol = self.config.get("symbol", "BTCUSDT")
    need_new_order = True

    # === 1. 从 live_orders 加载订单 ===
    db_orders = self.db.get_orders(self.session_id) if self.session_id else []
    orders = []
    max_group_id = 0

    if db_orders:
        from autofish_core import Autofish_Order
        for row in db_orders:
            if row['state'] in ('closed', 'cancelled'):
                continue

            order = Autofish_Order(
                level=row['level'],
                entry_price=Decimal(str(row['entry_price'])),
                quantity=Decimal(str(row['quantity'])),
                stake_amount=Decimal(str(row['stake_amount'])),
                take_profit_price=Decimal(str(row['take_profit_price'])),
                stop_loss_price=Decimal(str(row['stop_loss_price'])),
                state=row['state'],
                order_id=row['order_id'] if row['order_id'] else None,
                tp_order_id=row['tp_order_id'] if row['tp_order_id'] else None,
                sl_order_id=row['sl_order_id'] if row['sl_order_id'] else None,
                group_id=row['group_id'] if row['group_id'] else 0,
                created_at=row['created_at'],
                filled_at=row['filled_at'],
            )
            orders.append(order)
            if row['group_id'] and row['group_id'] > max_group_id:
                max_group_id = row['group_id']

        logger.info(f"[数据库恢复] 从 live_orders 表恢复 {len(orders)} 个订单")

    # === 2. 创建 chain_state ===
    from autofish_core import Autofish_ChainState
    self.chain_state = Autofish_ChainState(base_price=current_price, orders=orders)
    self.chain_state.group_id = max_group_id

    # === 3. 从 live_capital_statistics 恢复资金池 ===
    if self.session_id:
        stats = self.db.get_statistics(self.session_id)
        if stats:
            self.capital_pool.trading_capital = Decimal(str(stats['trading_capital']))
            if hasattr(self.capital_pool, 'profit_pool'):
                self.capital_pool.profit_pool = Decimal(str(stats['profit_pool']))
            if hasattr(self.capital_pool, 'total_profit'):
                self.capital_pool.total_profit = Decimal(str(stats['total_profit']))
            if hasattr(self.capital_pool, 'total_loss'):
                self.capital_pool.total_loss = Decimal(str(stats['total_loss']))
            if hasattr(self.capital_pool, 'withdrawal_count'):
                self.capital_pool.withdrawal_count = stats['withdrawal_count']
            if hasattr(self.capital_pool, 'liquidation_count'):
                self.capital_pool.liquidation_count = stats['liquidation_count']
            logger.info(f"[资金池恢复] trading_capital={self.capital_pool.trading_capital}")

    # === 4. 从 live_sessions 恢复统计 ===
    if self.session_id:
        session = self.db.get_session(self.session_id)
        if session:
            self.results['total_trades'] = session.get('total_trades', 0)
            self.results['win_trades'] = session.get('win_trades', 0)
            self.results['loss_trades'] = session.get('loss_trades', 0)
            self.results['total_profit'] = Decimal(str(session.get('total_profit', 0)))
            self.results['total_loss'] = Decimal(str(session.get('total_loss', 0)))

    # === 5. 同步交易所状态 ===
    # ... 保持原有的同步逻辑 ...

    return len(orders) > 0
```

### 7.3 移除 `_save_state` 调用

移除所有 `_save_state()` 调用，因为数据已在各表中实时更新。

---

## 八、总结

| 问题 | 结论 |
|------|------|
| 快照数据是否冗余？ | 是，大部分数据在其他表中已有 |
| 能否移除快照？ | 能，但需补充 `base_price` 字段 |
| `live_trades` 是否必要？ | 是，用于交易历史记录和统计分析 |
| `group_id` 如何恢复？ | 从 `live_orders` 表取最大值 |

---

*文档版本: 1.0*
*创建日期: 2026-04-03*
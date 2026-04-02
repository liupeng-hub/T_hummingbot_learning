# Session 恢复与状态同步流程完善设计文档

## 文档信息

| 项目 | 内容 |
|------|------|
| 创建日期 | 2026-04-02 |
| 版本 | 1.0 |
| 状态 | 待确认 |
| 关联 Issue | Session 35 层级调整导致状态不一致 |

---

## 一、问题背景

### 1.1 发现过程

用户反馈 Session 35 出现 A1、A3 订单但没有 A2 订单的问题，分析日志后发现更严重的问题：**状态快照与数据库订单不一致**，导致恢复后显示"持仓订单：0"。

### 1.2 数据存储现状

系统使用两种方式存储状态：

| 存储方式 | 内容 | 保存时机 |
|---------|------|---------|
| `live_orders` 表 | 单个订单记录（含原始层级） | 下单时、成交时、止盈止损时 |
| `live_state_snapshots` 表 | 完整状态快照（含调整后层级） | 状态变更时（止盈/止损后） |

---

## 二、问题分析

### 2.1 层级调整导致状态不一致

**代码位置**：
- `_handle_take_profit` (line 1339): 调用 `_adjust_order_levels()`
- `_handle_stop_loss` (line 1440): 调用 `_adjust_order_levels()`
- `_restore_orders` (line 3336-3343): 恢复时又进行层级调整

**`_adjust_order_levels` 逻辑**：

```python
def _adjust_order_levels(self) -> None:
    # 移除已关闭的订单
    valid_orders = [o for o in self.trader.chain_state.orders
                   if o.state != "closed"]

    # 按层级排序后重新编号
    valid_orders.sort(key=lambda o: o.level)

    for i, order in enumerate(valid_orders, start=1):
        if order.level != i:
            order.level = i  # A2→A1, A3→A2...

    self.trader.chain_state.orders = valid_orders
```

**问题流程示例**：

```
原始状态: A1 filled, A2 pending, A3 pending

A1 止盈触发:
  1. A1 -> closed (移除)
  2. _adjust_order_levels: A2 -> A1, A3 -> A2
  3. _save_state: 快照保存 [A1(原A2), A2(原A3)]

结果:
  - 数据库 live_orders: A1 filled(closed), A3 pending (原始层级)
  - 快照 orders: [level=1(原A2), level=2(原A3)] (调整后层级)
```

**恢复时问题**：
- 快照 `level=1` 对应原 A2
- 数据库 `level=1` 对应原 A1
- 两者无法匹配，导致状态混乱

### 2.2 `update_order` 查询条件问题

```python
# database/live_trading_db.py line 1288
WHERE session_id = ? AND level = ? AND group_id = ?
```

如果订单层级被调整：
- 订单原来是 `level=2`，调整后 `level=1`
- `update_order(order)` 用 `level=1` 查询，找不到 `level=2` 的记录
- 更新失败，数据库状态不更新

### 2.3 恢复流程数据来源混乱

- 恢复时从快照加载 orders（含调整后层级）
- 但数据库 `live_orders` 是独立的权威数据源
- 两者不一致，导致恢复后的状态不可靠

---

## 三、策略逻辑分析

### 3.1 订单价格关系

```
价格 ↑
  │
  │  A1 入场 ──────────────────────── TP1 (止盈，最高)
  │     │
  │     └── SL1 (止损，最高)
  │
  │  A2 入场 ──────────────────────── TP2
  │     │
  │     └── SL2
  │
  │  A3 入场 ──────────────────────── TP3
  │     │
  │     └── SL3
  │
  │  A4 入场 ──────────────────────── TP4 (止盈，最低)
  │     │
  │     └── SL4 (止损，最低)
  │
```

**入场价公式**：
```python
entry_price = base_price * (1 - grid_spacing * level)
```

- A1 入场价最高，止损价 SL1 也最高
- A4 入场价最低，止损价 SL4 也最低

### 3.2 止盈触发场景

#### 场景 A：A1 成交，A2 pending，A1 止盈

```
状态: A1 filled, A2 pending
A1 止盈触发:
  → 取消 A2 pending
  → A1 closed
  → 系统无持仓
  → 重新下新 A1（新一轮）
```

#### 场景 B：A1 成交，A2 成交，A3 pending，A2 止盈

```
状态: A1 filled, A2 filled, A3 pending
A2 止盈触发:
  → 取消 A3 pending
  → A2 closed
  → 系统仍有 A1 filled
  → 需要下 A2（同级重建）
```

**当前代码问题**：`_cancel_next_level_and_restart` 只在 `order.level == 1` 时重新下 A1，A2 止盈不会下单。

### 3.3 止损触发场景

#### 场景：A1 成交，A2 成交，A3 成交，A4 pending，A1 止损

```
状态: A1 filled, A2 filled, A3 filled, A4 pending
A1 止损触发:
  → 取消 A4 pending
  → A1 closed
  → 系统仍有 A2 filled, A3 filled
  → 价格继续下跌：A2 止损 → A3 止损
  → 价格回升：A3 先止盈（TP3 < TP2）
```

**止损顺序**：按 A1→A2→A3→A4 顺序触发（SL1 > SL2 > SL3 > SL4）

**止盈顺序**：按 A4→A3→A2→A1 顺序触发（TP4 < TP3 < TP2 < TP1）

### 3.4 层级调整的设计意图分析

**可能的设计意图**：让层级连续，方便下"下一级订单"时计算 `next_level = order.level + 1`

**实际问题**：

1. **入场价不更新**：层级调整后，订单的 `entry_price` 不重新计算，仍保持原值
2. **数据库不一致**：数据库保存原始层级，快照保存调整后层级
3. **恢复失败**：用调整后层级无法匹配数据库记录
4. **无实际意义**：层级只是标识符，调整后价格不变，策略逻辑无变化

### 3.5 链式下单机制

**下单原则**：只有 A2 成交，才会下发 A3 的 pending 挂单。

```
A1 pending → A1 成交 → 下 A2 pending → A2 成交 → 下 A3 pending → ...
```

**因此**：
- 任何时候最多只有一个 pending 订单
- `_cancel_next_level` 只取消一级是正确的
- 不会出现 A2、A3、A4 同时 pending 的情况

**结论**：`_cancel_next_level` 的逻辑是正确的，无需修改。

### 3.6 层级调整方法保留

`_adjust_order_levels()` 方法本身保留，仅移除调用，后续可根据需要重新启用或删除。

---

## 四、改造方案

### 4.1 核心原则

| 原则 | 说明 |
|------|------|
| **单一数据源** | 订单数据以 `live_orders` 表为准 |
| **层级不变** | 订单层级固定，不做调整 |
| **快照简化** | 快照不保存 orders，只保存其他状态 |

### 4.2 改造内容

#### 改造 1：移除层级调整调用（保留方法）

**修改位置**：

| 位置 | 操作 |
|------|------|
| `_handle_take_profit` (line 1339) | 注释或移除 `_adjust_order_levels()` 调用 |
| `_handle_stop_loss` (line 1440) | 注释或移除 `_adjust_order_levels()` 调用 |
| `_restore_orders` (line 3336-3343) | 注释或移除层级调整代码块 |

**注意**：`_adjust_order_levels()` 方法本身保留，以备后续需要。

**影响**：订单层级可能不连续（A1, A3, A4），但保持数据一致性。

#### 改造 2：恢复时从数据库加载订单

**修改 `_restore_orders` 方法**：

```python
async def _restore_orders(self, current_price: Decimal) -> bool:
    symbol = self.config.get("symbol", "BTCUSDT")

    # === Phase 1: 从数据库加载订单 ===
    db_orders = self.db.get_orders(self.session_id)
    orders = []

    if db_orders:
        from autofish_core import Autofish_Order, Autofish_ChainState
        for row in db_orders:
            # 只恢复未关闭的订单
            if row['state'] in ('closed', 'cancelled'):
                continue

            order = Autofish_Order(
                level=row['level'],  # 原始层级
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
                filled_at=row['filled_at'],
                created_at=row['created_at'],
            )
            orders.append(order)

        logger.info(f"[数据库恢复] 从 live_orders 表恢复 {len(orders)} 个订单")

    # 创建 chain_state
    from autofish_core import Autofish_ChainState
    self.chain_state = Autofish_ChainState(
        base_price=current_price,
        orders=orders
    )

    # === Phase 2: 从快照加载其他状态 ===
    state_data = self._load_state()
    if state_data:
        # 恢复 capital_pool
        if 'capital_pool' in state_data:
            cp_data = state_data['capital_pool']
            self.capital_pool.trading_capital = Decimal(str(cp_data.get('trading_capital', self.initial_capital)))
            # ... 其他资金池字段

        # 恢复 results
        if 'results' in state_data:
            r_data = state_data['results']
            self.results['total_trades'] = r_data.get('total_trades', 0)
            # ... 其他统计字段

        # 恢复 group_id
        if 'group_id' in state_data:
            self.chain_state.group_id = state_data['group_id']

    # === Phase 3: 同步交易所状态 ===
    # ... 保持原有的同步逻辑

    return len(orders) > 0
```

#### 改造 3：简化 `_save_state`

快照不再保存 orders，orders 由 `live_orders` 表管理：

```python
def _save_state(self) -> None:
    if self.chain_state:
        try:
            # 不再保存 orders 到快照
            state = {
                'base_price': str(self.chain_state.base_price),
                'group_id': self.chain_state.group_id,
                'capital_pool': {
                    'trading_capital': float(self.capital_pool.trading_capital),
                    'profit_pool': float(getattr(self.capital_pool, 'profit_pool', 0)),
                    'total_profit': float(getattr(self.capital_pool, 'total_profit', 0)),
                    'total_loss': float(getattr(self.capital_pool, 'total_loss', 0)),
                    'withdrawal_count': getattr(self.capital_pool, 'withdrawal_count', 0),
                    'liquidation_count': getattr(self.capital_pool, 'liquidation_count', 0),
                },
                'results': {
                    'total_trades': self.results['total_trades'],
                    'win_trades': self.results['win_trades'],
                    'loss_trades': self.results['loss_trades'],
                    'total_profit': float(self.results['total_profit']),
                    'total_loss': float(self.results['total_loss']),
                },
            }
            self.state_repository.save(state)
        except Exception as e:
            logger.error(f"[状态保存] 保存失败: {e}", exc_info=True)
```

---

## 五、改造后恢复流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     改造后恢复流程                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 从数据库加载订单                                             │
│     db_orders = db.get_orders(session_id)                       │
│     └── 只取 state != 'closed' 且 state != 'cancelled'          │
│     └── 保持原始层级                                             │
│                                                                  │
│  2. 创建 chain_state                                            │
│     chain_state = Autofish_ChainState(orders=db_orders)         │
│                                                                  │
│  3. 从快照加载其他状态                                           │
│     state_data = _load_state()                                  │
│     └── capital_pool, results, group_id                         │
│     └── 不加载 orders                                           │
│                                                                  │
│  4. 同步交易所状态                                               │
│     ├── 查询 Binance 订单状态                                    │
│     ├── 查询 Algo 条件单状态                                     │
│     ├── 检测成交/取消/平仓                                       │
│     └── 补充缺失的止盈止损单                                     │
│                                                                  │
│  5. 不进行层级调整                                               │
│     └── 订单保持原始层级                                         │
│                                                                  │
│  6. 保存快照（不含 orders）                                       │
│     _save_state()                                               │
│     └── 只保存 capital_pool, results, group_id                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 六、涉及文件与修改点

| 文件 | 修改内容 |
|------|---------|
| `binance_live.py` | 1. `_handle_take_profit`: 移除 `_adjust_order_levels`<br>2. `_handle_stop_loss`: 移除 `_adjust_order_levels`<br>3. `_restore_orders`: 从数据库加载订单，移除层级调整<br>4. `_save_state`: 不保存 orders |
| `database/live_trading_db.py` | 无需修改（已有 `get_orders` 方法） |
| `autofish_core.py` | 无需修改 |

---

## 七、实现步骤

### Phase 1: 移除层级调整调用（保留方法）

| Step | 文件 | 位置 | 操作 |
|------|------|------|------|
| 1 | `binance_live.py` | line 1339 | 注释或移除 `self._adjust_order_levels()` 调用 |
| 2 | `binance_live.py` | line 1440 | 注释或移除 `self._adjust_order_levels()` 调用 |
| 3 | `binance_live.py` | line 3336-3343 | 注释或移除层级调整代码块 |

**注意**：`_adjust_order_levels()` 方法定义保留，不移除。

### Phase 2: 修改恢复逻辑

| Step | 文件 | 位置 | 操作 |
|------|------|------|------|
| 4 | `binance_live.py` | `_restore_orders` | 从数据库加载订单 |
| 5 | `binance_live.py` | `_restore_orders` | 从快照加载其他状态 |

### Phase 3: 简化快照

| Step | 文件 | 位置 | 操作 |
|------|------|------|------|
| 6 | `binance_live.py` | `_save_state` | 不保存 orders 字段 |

---

## 八、验证方案

### 8.1 层级一致性验证

```sql
-- 查询数据库订单层级
SELECT level, state, order_id FROM live_orders WHERE session_id = ?;

-- 查询快照内容（改造后应该没有 orders 字段）
SELECT state_data FROM live_state_snapshots WHERE session_id = ? ORDER BY snapshot_time DESC LIMIT 1;
```

**预期结果**：
- `live_orders` 层级保持原始（1, 2, 3, ...）
- `live_state_snapshots` 不包含 orders 字段

### 8.2 恢复后订单数量验证

**测试步骤**：
1. 创建 session，下单 A1, A2, A3
2. A1 止盈触发
3. 停止 session
4. 恢复 session
5. 检查订单数量是否正确（应显示 A2 pending, A3 pending）
6. 检查层级是否保持原始（A2 level=2, A3 level=3）

### 8.3 止损场景验证

**测试步骤**：
1. 创建 session，等待 A1, A2, A3 成交
2. 触发 A1 止损
3. 检查 A2, A3 是否仍持仓
4. 价格回升，检查 A3 是否先止盈

---

## 九、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 层级不连续 | UI 显示可能有空缺 | UI 显示时做映射处理 |
| 旧快照兼容 | 恢复时可能读到旧 orders | 恢复时优先使用数据库，忽略快照 orders |
| 测试覆盖不足 | 边界场景未验证 | 完整测试后再上线 |

---

## 十、待确认事项

1. ~~是否同意移除 `_adjust_order_levels`？~~
   - ✅ **已确认并完成**：移除调用，保留方法

2. ~~是否同意从数据库加载订单而非快照？~~
   - ✅ **已确认并完成**：订单从 `live_orders` 表加载

3. ~~是否同意快照不保存 orders？~~
   - ✅ **已确认并完成**：快照只保存 `capital_pool`、`results`、`base_price`、`group_id`

---

*文档版本: 1.2*
*创建日期: 2026-04-02*
*更新日期: 2026-04-03*
*更新内容: 添加链式下单机制说明，明确保留 `_adjust_order_levels` 方法，完成所有改造*
# Session 恢复与状态同步流程完善计划

## 文档信息

| 项目 | 内容 |
|------|------|
| 创建日期 | 2026-04-03 |
| 版本 | 1.0 |
| 关联文档 | `docs/20260402_session_recovery_refactor.md`, `docs/20260403_snapshot_removal_analysis.md` |

---

## Context

用户反馈 session 35 出现 A1、A3 订单但没有 A2 订单的问题，分析日志发现关键流程缺少追踪信息。后续发现更严重的问题：**状态快照与数据库订单不一致**，导致恢复后显示"持仓订单：0"。

本计划旨在：
1. 分析当前 session 恢复流程的问题
2. 设计完善的状态同步机制
3. 统一 `live_state_snapshots` 和 `live_orders` 的数据来源

---

## 一、当前恢复流程分析

### 1.1 数据存储现状

系统使用两种方式存储状态：

| 存储方式 | 内容 | 保存时机 |
|---------|------|---------|
| `live_orders` 表 | 单个订单记录（含原始层级） | 下单时、成交时、止盈止损时 |
| `live_state_snapshots` 表 | 完整状态快照（含调整后层级） | 状态变更时（止盈/止损后） |

### 1.2 恢复流程（`_restore_orders`）

```
┌─────────────────────────────────────────────────────────────────┐
│                     当前恢复流程                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 从快照加载状态 (state_data = _load_state())                  │
│     └── 包含 orders, capital_pool, results, group_id            │
│                                                                  │
│  2. 转换为 chain_state                                           │
│     └── saved_state = Autofish_ChainState.from_dict(state_data) │
│     └── orders 中的层级可能是调整后的                            │
│                                                                  │
│  3. 同步交易所状态                                                │
│     ├── 查询 Binance 订单状态                                    │
│     ├── 查询 Algo 条件单状态                                     │
│     └── 检测成交/取消/平仓                                       │
│                                                                  │
│  4. 层级调整（再次！）                                            │
│     └── line 3336-3343: 重新编号订单层级                         │
│     └── 加剧状态不一致                                           │
│                                                                  │
│  5. 保存状态 (_save_state())                                     │
│     └── 保存调整后的层级                                         │
│                                                                  │
│  问题：快照的 orders 与数据库 live_orders 层级不一致             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 发现的问题

#### 问题 1：层级调整导致状态不一致

**位置**：
- `_handle_take_profit` (line 1339): 调用 `_adjust_order_levels()`
- `_handle_stop_loss` (line 1440): 调用 `_adjust_order_levels()`
- `_restore_orders` (line 3336-3343): 恢复时又进行层级调整

**流程示例**：
```
原始状态: A1 filled, A2 pending, A3 pending
A1 止盈触发:
  1. A1 -> closed (移除)
  2. _adjust_order_levels: A2 -> A1, A3 -> A2
  3. _save_state: 快照保存 A1(原A2), A2(原A3)

数据库 live_orders: A1 filled, A3 pending (原始层级)
快照 orders: A1(原A2), A2(原A3) (调整后层级)
```

**结果**：恢复时快照 level=1 对应的是原 A2，但数据库 level=1 是原 A1。

#### 问题 2：`update_order` 查询条件问题

```python
# database/live_trading_db.py line 1288
WHERE session_id = ? AND level = ? AND group_id = ?
```

如果订单层级被调整：
- 订单原来是 level=2，调整后 level=1
- `update_order(order)` 用 level=1 查询，找不到 level=2 的记录
- 更新失败，数据库状态不更新

#### 问题 3：恢复流程数据来源混乱

- 恢复时从快照加载 orders（含调整后层级）
- 但数据库 `live_orders` 是独立的权威数据源
- 两者不一致，导致恢复后的状态不可靠

---

## 二、改造方案

### 2.1 核心原则

1. **单一数据源原则**：订单数据以 `live_orders` 表为准
2. **层级不变原则**：订单层级固定，不做调整
3. **快照简化原则**：快照不保存 orders，只保存其他状态

### 2.2 改造内容

#### 改造 1：移除层级调整

**修改位置**：
| 位置 | 操作 |
|------|------|
| `_handle_take_profit` (line 1339) | 移除 `_adjust_order_levels()` 调用 |
| `_handle_stop_loss` (line 1440) | 移除 `_adjust_order_levels()` 调用 |
| `_restore_orders` (line 3336-3343) | 移除层级调整代码块 |

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
                'capital_pool': {...},
                'results': {...},
                # orders 字段删除
            }
            self.state_repository.save(state)
        except Exception as e:
            logger.error(f"[状态保存] 保存失败: {e}", exc_info=True)
```

#### 改造 4：数据库订单状态同步

在关键节点同步数据库订单状态：

| 触发点 | 数据库操作 |
|-------|-----------|
| 下入场单 | `db.save_order()` |
| 入场成交 | `db.update_order()` |
| 下止盈止损单 | `db.update_order()` (更新 tp/sl_order_id) |
| 止盈触发 | `db.update_order()` (更新 state, close_reason, profit) |
| 止损触发 | `db.update_order()` (更新 state, close_reason, profit) |
| 订单取消 | `db.update_order()` (更新 state) |

---

## 三、完整恢复流程（改造后）

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
│  数据一致性：                                                    │
│  - orders 数据源: live_orders 表（原始层级）                     │
│  - 其他状态数据源: live_state_snapshots 表                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 四、涉及文件与修改点

| 文件 | 修改内容 |
|------|---------|
| `binance_live.py` | 1. `_handle_take_profit`: 移除 `_adjust_order_levels`<br>2. `_handle_stop_loss`: 移除 `_adjust_order_levels`<br>3. `_restore_orders`: 从数据库加载订单，移除层级调整<br>4. `_save_state`: 不保存 orders |
| `database/live_trading_db.py` | 无需修改（已有 `get_orders` 方法） |
| `autofish_core.py` | 无需修改 |

---

## 五、实现步骤

### Phase 1: 修复层级调整问题 ✅ 已完成

#### Step 1: 移止盈处理中的 `_adjust_order_levels` ✅
- 文件: `binance_live.py`
- 位置: line 1339
- 操作: 已注释 `# self._adjust_order_levels()  # 注释：移除层级调整，保持原始层级`

#### Step 2: 移止损处理中的 `_adjust_order_levels` ✅
- 文件: `binance_live.py`
- 位置: line 1440
- 操作: 已注释 `# self._adjust_order_levels()  # 注释：移除层级调整，保持原始层级`

#### Step 3: 修改 `_restore_orders` ✅
- 文件: `binance_live.py`
- 位置: line 3103-3194
- 操作: ✅ 已完成
  1. 从数据库加载订单（替代从快照加载 orders）
  2. 移除恢复时的层级调整代码

#### Step 4: 修改 `_save_state` ✅
- 文件: `binance_live.py`
- 位置: line 2283-2313
- 操作: ✅ 已完成 - 不保存 orders 字段到快照

### Phase 2: 验证与测试

#### Step 5: 测试恢复流程
1. 创建 session，下单 A1, A2, A3
2. A1 止盈触发
3. 停止 session
4. 恢复 session
5. 检查订单数量是否正确（应显示 A2 pending, A3 pending）
6. 检查层级是否保持原始（A2 level=2, A3 level=3）

---

## 六、验证方案

### 6.1 层级一致性验证

```sql
-- 查询数据库订单层级
SELECT level, state, order_id FROM live_orders WHERE session_id = ?;

-- 查询快照中的 orders（改造后应该没有 orders 字段）
SELECT state_data FROM live_state_snapshots WHERE session_id = ? ORDER BY snapshot_time DESC LIMIT 1;
```

预期结果：
- `live_orders` 层级保持原始（1, 2, 3, ...）
- `live_state_snapshots` 不包含 orders 字段

### 6.2 恢复后订单数量验证

恢复后，活跃会话应正确显示持仓订单数量：
- 恢复前: A2 pending, A3 pending
- 恢复后: 显示"持仓订单：2"

---

## 七、日志改进（Phase 3）

后续添加详细日志，便于调试：

### 7.1 恢复流程日志

```python
logger.info(f"[恢复开始] session_id={self.session_id}")
logger.info(f"[数据库加载] 从 live_orders 表获取 {len(db_orders)} 条记录")
logger.info(f"[订单恢复] A{row['level']}: state={row['state']}, order_id={row['order_id']}")
logger.info(f"[快照加载] 加载 capital_pool, results, group_id")
logger.info(f"[恢复完成] chain_state.orders 数量: {len(self.chain_state.orders)}")
```

### 7.2 状态同步日志

```python
logger.info(f"[交易所同步] 查询 Binance 订单状态...")
logger.info(f"[交易所同步] orderId={order_id}, Binance状态={binance_status}")
logger.info(f"[平仓检测] A{level}: 止盈/止损触发，标记为 closed")
```

---

## 八、移除快照表方案（Phase 2）

### 8.1 分析结论

详见 `docs/20260403_snapshot_removal_analysis.md`

**快照数据冗余分析**：
| 快照数据 | 数据库表 | 是否可替代 |
|---------|---------|-----------|
| `capital_pool.*` | `live_capital_statistics` | ✅ 完全可替代 |
| `results.*` | `live_sessions` | ✅ 完全可替代 |
| `group_id` | `live_sessions.group_id` | ✅ 直接读取（新增字段） |
| `base_price` | `live_sessions.base_price` | ✅ 直接读取（新增字段） |

### 8.2 方案 C：添加 `base_price` 和 `group_id` 字段到 `live_sessions`

```sql
ALTER TABLE live_sessions ADD COLUMN base_price REAL DEFAULT 0;
ALTER TABLE live_sessions ADD COLUMN group_id INTEGER DEFAULT 0;
```

**为什么 `group_id` 放在 `live_sessions`**：
- `group_id` 是 session 级别的状态，用于标识订单组
- 从 `live_orders.MAX(group_id)` 计算可能不准确（订单可能被删除）
- 保存在 session 表中更可靠，便于恢复

### 8.3 实现步骤

#### Step 1: 数据库迁移
- 文件: `database/live_trading_db.py`
- 操作: 在 `init_db()` 中添加字段（兼容已有数据库）
```python
# 添加 base_price 和 group_id 字段
try:
    cursor.execute("ALTER TABLE live_sessions ADD COLUMN base_price REAL DEFAULT 0")
except sqlite3.OperationalError:
    pass  # 字段已存在
try:
    cursor.execute("ALTER TABLE live_sessions ADD COLUMN group_id INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass  # 字段已存在
```

#### Step 2: 修改保存逻辑
- `_save_state()` 移除（不再需要）
- 在更新 session 统计时同步更新 `base_price` 和 `group_id`：
```python
# 在 update_session_stats() 中添加
self.db.update_session_stats(session_id, {
    ...existing fields...
    'base_price': float(self.chain_state.base_price),
    'group_id': self.chain_state.group_id,
})
```

#### Step 3: 修改恢复逻辑 `_restore_orders`
- 从 `live_sessions` 表读取 `base_price`、`group_id` 和统计数据
- 从 `live_capital_statistics` 表读取资金池数据
- 从 `live_orders` 表加载订单

```python
# 从 live_sessions 恢复 session 状态
session = self.db.get_session(self.session_id)
if session:
    self.chain_state.base_price = Decimal(str(session.get('base_price', current_price)))
    self.chain_state.group_id = session.get('group_id', 0)
    # 恢复统计
    self.results['total_trades'] = session.get('total_trades', 0)
    ...
```

#### Step 4: 移除快照相关代码
- 移除 `_save_state()` 方法调用
- 移除 `_load_state()` 方法调用
- 可保留方法定义以备后续需要

### 8.4 `group_id` 保存/更新/读取适配

| 操作 | 位置 | 代码 |
|------|------|------|
| **保存** | 创建 session 时 | `db.create_session()` 初始化 `group_id=0` |
| **更新** | 止盈/止损/下单时 | `db.update_session_stats()` 更新 `group_id` |
| **读取** | `_restore_orders` | `session.get('group_id', 0)` |

### 8.5 `base_price` 保存/更新/读取适配

| 操作 | 位置 | 代码 |
|------|------|------|
| **保存** | 创建 session 时 | `db.create_session()` 初始化 `base_price` |
| **更新** | 下单时/状态变更时 | `db.update_session_stats()` 更新 `base_price` |
| **读取** | `_restore_orders` | `session.get('base_price', current_price)` |

---

## 九、`live_trades` 表用途分析

### 9.1 表结构

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

### 9.2 写入时机

| 事件 | `trade_type` | 写入位置 |
|------|-------------|---------|
| 止盈触发 | `'take_profit'` | `_handle_take_profit` (line 1288) |
| 止损触发 | `'stop_loss'` | `_handle_stop_loss` (line 1389) |

### 9.3 与 `live_orders` 的区别

| 表 | 内容 | 更新时机 | 用途 |
|----|------|---------|------|
| `live_orders` | 订单生命周期状态（pending→filled→closed） | 实时更新 | 状态恢复、实时监控 |
| `live_trades` | 完整交易记录（入场价、出场价、盈亏、持仓时长） | 仅平仓时写入 | 历史分析、报表统计 |

### 9.4 核心用途

1. **交易历史记录**
   - 保留每笔完整交易的入场→出场记录
   - 即使 `live_orders` 被清理，历史交易仍可追溯

2. **盈亏分析**
   - 按层级分析盈亏分布（哪些层级盈利/亏损最多）
   - 按类型分析（止盈 vs 止损的盈亏对比）

3. **持仓时长统计**
   - `holding_duration_seconds` 记录持仓时长
   - 分析不同层级的平均持仓时间

4. **报表生成**
   - 生成交易报表、统计分析
   - 计算胜率、平均盈亏等指标

5. **数据冗余保护**
   - `live_orders` 可能被清理或损坏
   - `live_trades` 作为交易历史的独立备份

### 9.5 是否必要？

**必要**，原因：
- 与 `live_orders` 功能不同，互补而非冗余
- 提供完整的交易审计和统计分析能力
- 数据独立存储，提高可靠性

---

## 十、Web 显示改进（Phase 3）

### 10.1 当前状态

**文件**: `web/live/index.html`

| 位置 | 当前代码 | 问题 |
|------|---------|------|
| line 1121 | `<strong>Group ID:</strong> ${state.group_id || 0}` | 从实时状态获取，显示正确但需确认数据源 |
| line 2890 | `<thead><tr><th>层级</th><th>状态</th><th>入场价</th><th>盈亏</th></tr></thead>` | 订单列表缺少 Group ID 列 |

### 10.2 改进内容

#### 改进 1: Session 详情页 Group ID 显示

**位置**: line 1121

保持现有逻辑，但确保数据来自正确的数据源：
- 实时状态：从 trader 的 `chain_state.group_id` 获取
- 历史详情：从 `live_sessions.group_id` 字段获取

```javascript
// 确保从正确数据源获取
<p class="mb-0"><strong>Group ID:</strong> ${state.group_id || session.group_id || 0}</p>
```

#### 改进 2: 订单列表增加 Group ID 列

**位置**: line 2890-2899

修改表头和表格行：

```html
<thead><tr><th>Group ID</th><th>层级</th><th>状态</th><th>入场价</th><th>盈亏</th></tr></thead>
<tbody>
    ${orders.map(o => `
        <tr>
            <td>${o.group_id || '-'}</td>
            <td>${getLevelBadge(o.level)}</td>
            <td><span class="state-${o.state}">${o.state}</span></td>
            <td>${formatNumber(o.entry_price)}</td>
            <td class="${getProfitClass(o.profit)}">${formatCurrency(o.profit)}</td>
        </tr>
    `).join('')}
</tbody>
```

### 10.3 数据流确认

| 场景 | Group ID 数据源 |
|------|----------------|
| 实时运行状态 | `trader.chain_state.group_id` → API `/api/live-traders` |
| 历史会话详情 | `live_sessions.group_id` → API `/api/live-sessions/:id` |
| 订单列表 | `live_orders.group_id` → API `/api/live-sessions/:id/orders` |

### 10.4 涉及文件

| 文件 | 修改内容 |
|------|---------|
| `web/live/index.html` | 1. line 1121: Group ID 显示改为 `${state.group_id || session.group_id || 0}`<br>2. line 2890-2899: 订单列表增加 Group ID 列 |
| `binance_live_web.py` | 确认 API 返回正确的 group_id 字段 |

---

## 十一、`group_id` 设计说明

### 11.1 核心原则

**`chain_state.group_id` 表示"最后一个成交轮次"**，只在 A1 成交时更新。

### 11.2 设计规则

| 操作 | group_id 规则 | 说明 |
|------|--------------|------|
| A1 下单 | `order.group_id = chain_state.group_id + 1` | 不更新 chain_state.group_id |
| A1 成交 | `chain_state.group_id = order.group_id` | 确认轮次，更新 chain_state |
| A1 取消 | 无变化 | chain_state.group_id 保持不变 |
| A2/A3/A4 下单 | `order.group_id = chain_state.group_id` | 使用当前轮次的 group_id |

### 11.3 场景验证

#### 场景 1：正常流程
```
A1 下单 (group_id=1) → A1 成交 (chain_state.group_id=1) → A2 下单 (group_id=1)
```

#### 场景 2：A1 超时重挂
```
A1 下单 (order.group_id=1, chain_state.group_id=0)
→ A1 超时取消
→ 新 A1 下单 (order.group_id=1, chain_state.group_id=0)  // 与之前相同
→ 新 A1 成交 (chain_state.group_id=1)
```

#### 场景 3：行情变化取消后重新开始
```
A1 下单 (order.group_id=1, chain_state.group_id=0)
→ 行情变化取消 A1
→ 行情恢复，新 A1 下单 (order.group_id=1, chain_state.group_id=0)  // 与之前相同
→ 新 A1 成交 (chain_state.group_id=1)
```

#### 场景 4：多轮交易
```
A1 成交 (group_id=1) → 止盈
→ 新 A1 下单 (order.group_id=2, chain_state.group_id=1)
→ 新 A1 成交 (chain_state.group_id=2)
```

### 11.4 设计优点

1. **group_id 连续性**：只有成交的订单才确认 group_id，避免跳号
2. **数据一致性**：分析时可以准确追踪每个交易轮次
3. **简化逻辑**：无需特殊处理取消场景

---

## 十二、总结

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 移除层级调整调用，从数据库加载订单 | ✅ 已完成 |
| Phase 2 | 添加 `base_price` 和 `group_id` 到 `live_sessions`，移除快照 | ✅ 已完成 |
| Phase 3 | Web 显示改进，订单列表增加 Group ID 列 | ✅ 已完成 |
| Phase 4 | 行情变化处理改进，取消挂单逻辑完善 | ✅ 已完成 |
| Phase 5 | group_id 设计改进，保证连续性 | ✅ 已完成 |

---

*文档版本: 1.1*
*创建日期: 2026-04-03*
*更新日期: 2026-04-03 - 添加 group_id 设计说明，完善行情变化处理*
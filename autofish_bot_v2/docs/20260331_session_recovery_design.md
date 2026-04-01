# Session 恢复机制设计文档

## 概述

本文档描述 Autofish V2 实盘交易系统的 Session 恢复机制设计，解决 Web 服务重启后如何恢复中断的交易会话。

## 问题背景

### 现存问题

1. **Web 服务重启后内存 trader 消失**：内存中的 traders 全部消失，数据库 session 记录仍为 `running`
2. **无法恢复已存在的 session**：从 Web 启动新 trader 时会创建新 session_id，无法恢复旧 session
3. **状态数据未被利用**：数据库有完整的状态快照（订单、资金池、统计），但没有恢复入口
4. **超时订单孤立问题**：A1 超时重挂时，旧订单从内存删除但未从 `live_orders` 表删除，导致数据不一致

### 设计目标

- 支持从中断点恢复交易会话
- 订单状态与交易所自动同步
- 资金池状态正确恢复
- 止盈止损单自动检查和补充

---

## 架构设计

### 状态存储位置

| 数据 | 存储位置 | 表名 | 说明 |
|------|---------|------|------|
| Session 记录 | 数据库 | `live_sessions` | session_id, case_id, status, start_time |
| 订单状态快照 | 数据库 | `live_state_snapshots` | orders, capital_pool, results, group_id |
| 订单记录 | 数据库 | `live_orders` | 单订单详情（下单时写入） |
| 内存 Trader | 进程内存 | - | WebSocket 连接、实时状态 |

### 两套订单存储的关系

```
┌─────────────────────────────────────────────────────────────────┐
│                        订单存储架构                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   live_state_snapshots（状态快照）                               │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ - 完整状态恢复                                           │   │
│   │ - 包含 orders[], capital_pool, results, group_id         │   │
│   │ - 每次 _save_state() 更新                                │   │
│   │ - 恢复时从此加载                                          │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│   live_orders（订单记录）                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ - 单订单持久化                                           │   │
│   │ - 下单成功时 save_order() 写入                           │   │
│   │ - 用于历史查询和审计                                      │   │
│   │ - 超时删除时需同步删除                                    │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 恢复流程设计

### 整体流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                      服务启动                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  _check_interrupted_sessions()                                  │
│  ─────────────────────────────                                  │
│  1. 查询数据库 status='running' 的 session                       │
│  2. 过滤掉内存中已存在的 trader                                   │
│  3. 将中断的 session 状态更新为 'interrupted'                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      前端显示                                    │
│  ─────────────────                                              │
│  - 活跃会话：显示内存中运行的 trader                              │
│  - 可恢复会话：显示 interrupted 状态的 session                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              用户点击"恢复"按钮                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  POST /api/traders/recover/<session_id>                         │
│  ──────────────────────────────────────                         │
│  1. 验证 session 存在且可恢复                                    │
│  2. 调用 LiveTraderManager.recover_trader()                     │
│  3. 返回恢复结果                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  LiveTraderManager.recover_trader()                             │
│  ─────────────────────────────────                              │
│  1. 获取 session 信息                                            │
│  2. 从 case_id 加载配置                                          │
│  3. 创建 trader，设置 recover_session_id                         │
│  4. 调用 start_trader() 启动                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  BinanceLiveTrader.run() [恢复模式]                              │
│  ────────────────────────────────────                            │
│  1. 复用现有 session_id（不创建新 session）                       │
│  2. 初始化 DbStateRepository                                     │
│  3. 连接 WebSocket                                               │
│  4. 调用 _restore_orders() 恢复订单状态                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  _restore_orders()                                              │
│  ───────────────────                                            │
│  1. 从 live_state_snapshots 加载状态快照                         │
│  2. 遍历快照中的订单，与 Binance 同步状态                         │
│  3. 检查/补充止盈止损单                                          │
│  4. 保存同步后的状态                                             │
│  5. 发送恢复通知                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 订单同步详细流程

`_restore_orders()` 方法（`binance_live.py:2820`）是恢复的核心：

```
┌─────────────────────────────────────────────────────────────────┐
│                    订单同步流程                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  for each order in chain_state.orders:                         │
│      │                                                          │
│      ├─► if state == "closed" → 从内存删除（已平仓）            │
│      │                                                          │
│      ├─► if state == "cancelled" → 从内存删除（已取消）         │
│      │                                                          │
│      ├─► if state == "pending":                                │
│      │       │                                                  │
│      │       ├─► 查询 Binance 订单状态                          │
│      │       │                                                  │
│      │       ├─► if FILLED → 更新为 filled，下止盈止损单        │
│      │       │                                                  │
│      │       ├─► if CANCELED/EXPIRED → 从内存删除               │
│      │       │                                                  │
│      │       └─► if NEW/PARTIALLY_FILLED → 保持挂单状态         │
│      │                                                          │
│      └─► if state == "filled":                                 │
│              │                                                  │
│              ├─► 检查止盈止损单是否存在                          │
│              │                                                  │
│              ├─► if 止盈止损单缺失 → 补充下单                    │
│              │                                                  │
│              └─► if 无仓位且止盈/止损单已触发 → 标记为 closed    │
│                                                                 │
│  _save_state() → 保存同步后的状态                                │
│  notify_orders_recovered() → 发送恢复通知                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 关键代码实现

### 1. 数据库层

#### 新增方法

```python
# database/live_trading_db.py

def delete_order(self, session_id: int, order_id: int) -> bool:
    """删除订单记录"""
    conn = self._get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            DELETE FROM live_orders
            WHERE session_id = ? AND order_id = ?
        """, (session_id, order_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def delete_orders_by_ids(self, session_id: int, order_ids: List[int]) -> int:
    """批量删除订单记录"""
    if not order_ids:
        return 0
    conn = self._get_connection()
    cursor = conn.cursor()
    try:
        placeholders = ','.join('?' * len(order_ids))
        cursor.execute(f"""
            DELETE FROM live_orders
            WHERE session_id = ? AND order_id IN ({placeholders})
        """, [session_id] + order_ids)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

def get_recoverable_sessions(self) -> List[Dict]:
    """获取可恢复的 session 列表"""
    conn = self._get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT s.*, c.symbol, c.name as case_name, c.testnet
            FROM live_sessions s
            JOIN live_cases c ON s.case_id = c.id
            WHERE s.status = 'running'
            ORDER BY s.start_time DESC
        """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
```

### 2. Trader 恢复模式

#### 初始化参数

```python
# binance_live.py

class BinanceLiveTrader:
    def __init__(self, symbol: str, amplitude: Dict, market: Dict, entry: Dict,
                 timeout: Dict, capital: Dict, testnet: bool = True,
                 recover_session_id: int = None):
        # ... 原有初始化代码 ...

        # 恢复模式标识
        self.recover_session_id: Optional[int] = recover_session_id
```

#### run() 方法中的恢复逻辑

```python
async def run(self):
    # ... 前置初始化代码 ...

    # === 创建/恢复数据库会话 ===
    if self.recover_session_id:
        # 恢复模式：使用现有 session_id
        self.session_id = self.recover_session_id
        logger.info(f"[恢复模式] 绑定到现有 session_id={self.session_id}")
        print(f"[恢复] session_id={self.session_id} (恢复模式)")
    else:
        # 正常模式：创建新会话
        self.session_id = self.db.create_session_legacy(
            symbol=self.config.get('symbol', 'BTCUSDT'),
            initial_capital=float(self.initial_capital),
            config=self.config,
            case_id=self.case_id
        )

    # 初始化状态仓库
    self.state_repository = DbStateRepository(self.db, self.session_id)

    # ... WebSocket 连接代码 ...

    # 恢复订单状态
    need_new_order = await self._restore_orders(current_price)
```

### 3. LiveTraderManager 恢复方法

```python
# binance_live.py

class LiveTraderManager:
    async def recover_trader(self, session_id: int) -> Optional[BinanceLiveTrader]:
        """恢复指定 session 的交易实例"""
        from database.live_trading_db import LiveTradingDB

        db = LiveTradingDB()

        # 获取 session 信息
        session = db.get_session(session_id)
        if not session:
            logger.error(f"[恢复] Session 不存在: {session_id}")
            return None

        if session['status'] != 'running':
            logger.error(f"[恢复] Session 状态不是 running: {session['status']}")
            return None

        # 检查是否已在内存中运行
        if self.get_trader(session_id) is not None:
            logger.warning(f"[恢复] Session 已在运行: {session_id}")
            return None

        # 从 case_id 创建 trader
        case_id = session.get('case_id')
        if not case_id:
            logger.error(f"[恢复] Session 无 case_id: {session_id}")
            return None

        trader = await self.create_trader_from_case(case_id)
        if not trader:
            logger.error(f"[恢复] 无法从 case_id={case_id} 创建 trader")
            return None

        # 设置恢复模式
        trader.recover_session_id = session_id
        logger.info(f"[恢复] 已创建恢复实例: session_id={session_id}, case_id={case_id}")

        return trader
```

### 4. Web API

```python
# binance_live_web.py

@app.route('/api/traders/recoverable', methods=['GET'])
def get_recoverable_sessions():
    """获取可恢复的 session 列表"""
    try:
        sessions = db.get_recoverable_sessions()
        running_ids = set(trader_manager.get_running_sessions())
        recoverable = [s for s in sessions if s['id'] not in running_ids]
        return jsonify({'success': True, 'data': recoverable})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/traders/recover/<int:session_id>', methods=['POST'])
def recover_trader(session_id):
    """恢复指定 session"""
    try:
        if trader_manager.get_trader(session_id) is not None:
            return jsonify({'success': False, 'error': 'Session already running'}), 400

        trader = run_async(trader_manager.recover_trader(session_id))
        if not trader:
            return jsonify({'success': False, 'error': 'Failed to create trader'}), 500

        recovered_session_id = run_async(trader_manager.start_trader(trader))

        if recovered_session_id:
            return jsonify({
                'success': True,
                'data': {'session_id': recovered_session_id, 'recovered': True}
            })
        return jsonify({'success': False, 'error': 'Failed to start'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
```

### 5. 服务启动检查

```python
# binance_live_web.py

def _check_interrupted_sessions():
    """检查并标记中断的 session"""
    try:
        sessions = db.get_recoverable_sessions()
        running_ids = set(trader_manager.get_running_sessions())

        interrupted_count = 0
        for session in sessions:
            if session['id'] not in running_ids:
                db.end_session(session['id'], status='interrupted')
                logger.info(f"[启动检查] Session {session['id']} 已标记为 interrupted")
                interrupted_count += 1

        if interrupted_count > 0:
            print(f"   ⚠️  发现 {interrupted_count} 个中断的会话，可通过 /api/traders/recoverable 查看")
    except Exception as e:
        logger.error(f"[启动检查] 检查中断会话失败: {e}")
```

---

## 超时订单处理修复

### 问题分析

A1 超时重挂时：
1. 取消旧订单（Binance）✅
2. `chain_state.orders.remove(old_order)` ✅
3. 创建新订单 ✅
4. `db.save_order(new_order)` ✅
5. `_save_state()` → live_state_snapshots 更新 ✅

**问题**：`live_orders` 表中旧订单记录未删除 ❌

### 修复方案

```python
# binance_live.py - _check_and_handle_first_entry_timeout()

# 现有代码
self.chain_state.orders.remove(timeout_first_entry)

# 新增：删除数据库中的订单记录
if self.session_id:
    order_ids_to_delete = []
    if timeout_first_entry.order_id:
        order_ids_to_delete.append(timeout_first_entry.order_id)
    if order_ids_to_delete:
        self.db.delete_orders_by_ids(self.session_id, order_ids_to_delete)
        logger.info(f"[超时清理] 已删除数据库订单记录: order_ids={order_ids_to_delete}")
```

---

## 前端界面

### 新增可恢复会话区域

```html
<!-- 活跃会话标签页中 -->
<div class="card mt-3" id="recoverableCard" style="display: none;">
    <div class="card-header bg-warning text-dark">
        <span>⚠️ 可恢复会话</span>
        <small class="text-muted ms-2">(服务中断的会话)</small>
    </div>
    <div class="card-body">
        <div id="recoverableSessionsContent">
            <p class="text-muted">加载中...</p>
        </div>
    </div>
</div>
```

### JavaScript 函数

```javascript
// 加载可恢复会话
async function loadRecoverableSessions() {
    const response = await fetch(`${API_BASE}/traders/recoverable`);
    const data = await response.json();

    if (data.success && data.data && data.data.length > 0) {
        document.getElementById('recoverableCard').style.display = 'block';
        // 渲染表格...
    } else {
        document.getElementById('recoverableCard').style.display = 'none';
    }
}

// 恢复中断的会话
async function recoverSession(sessionId) {
    if (!confirm(`确定要恢复会话 ${sessionId} 吗？`)) return;

    const response = await fetch(`${API_BASE}/traders/recover/${sessionId}`, {
        method: 'POST'
    });
    const result = await response.json();

    if (result.success) {
        alert(`会话已恢复! Session ID: ${result.data.session_id}`);
        loadActiveSessions();
    } else {
        showError('恢复失败', result.error);
    }
}
```

---

## API 接口

### GET /api/traders/recoverable

获取可恢复的 session 列表。

**响应示例**：
```json
{
    "success": true,
    "data": [
        {
            "id": 123,
            "case_id": 5,
            "symbol": "BTCUSDT",
            "case_name": "BTC网格实盘",
            "testnet": 1,
            "start_time": "2026-03-31 10:00:00",
            "status": "running"
        }
    ]
}
```

### POST /api/traders/recover/<session_id>

恢复指定的 session。

**响应示例**：
```json
{
    "success": true,
    "data": {
        "session_id": 123,
        "recovered": true
    }
}
```

---

## 验证测试

### 测试步骤

1. **启动实盘交易**：
   - 通过 Web 或 CLI 启动一个实盘交易
   - 等待有订单状态（pending 或 filled）

2. **模拟崩溃**：
   - 强制终止 Web 服务（`Ctrl+C` 或 `kill`）
   - 不要通过正常停止流程

3. **验证状态**：
   - 重启 Web 服务
   - 检查控制台输出，确认有"发现 N 个中断的会话"
   - 打开 Web 页面，查看"可恢复会话"区域

4. **执行恢复**：
   - 点击"恢复"按钮
   - 确认弹窗
   - 等待恢复完成

5. **验证恢复结果**：
   - 检查订单状态是否正确
   - 检查止盈止损单是否存在
   - 检查资金池状态是否正确
   - 检查是否收到恢复通知（微信）

### 预期行为

- 恢复后 session_id 不变
- 订单状态与 Binance 一致
- 止盈止损单自动检查和补充
- 资金池状态正确恢复
- 收到订单同步通知

---

## 注意事项

1. **恢复时机**：只有在 session 状态为 `running` 且内存中没有对应 trader 时才能恢复

2. **并发安全**：恢复操作有锁保护，同一 session 不能同时被多个进程恢复

3. **状态一致性**：恢复以 `live_state_snapshots` 为准，与 Binance 实时同步

4. **通知机制**：恢复后会发送订单同步通知，包含当前所有订单状态

---

*文档版本: 1.0*
*创建日期: 2026-03-31*
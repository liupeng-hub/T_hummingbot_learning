# Session 状态与订单状态管理

本文档描述实盘交易系统中 Session 和 Order 的状态定义、转换流程及相关操作。

## 一、Session 状态

### 1.1 状态定义

| 状态 | 含义 | 数据库字段 |
|------|------|-----------|
| `draft` | 配置已创建，未启动 | `live_cases.status` |
| `running` | 交易运行中 | `live_sessions.status` |
| `stopped` | 已停止（正常或异常） | `live_sessions.status` |

> 注：`paused`（暂停）是内存状态，不写入数据库。

### 1.2 状态转换图

```
┌─────────────────────────────────────────────────────────────┐
│                     Session 状态转换                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   ┌─────────┐     run()      ┌─────────┐     stop()        │
│   │  draft  │ ───────────────>│ running │ ────────────────>│ stopped │
│   │ (配置)  │                 │ (运行)  │                   │ (停止)  │
│   └─────────┘                 └────┬────┘                   └─────────┘
│                                    │                              │
│                                    │ pause()                      │
│                                    ▼                              │
│                               ┌─────────┐                        │
│                               │ paused  │                        │
│                               │ (暂停)  │                        │
│                               └────┬────┘                        │
│                                    │ resume()                    │
│                                    │                             │
│                                    └──────────> running          │
│                                                              │
│   恢复流程 (recover_trader):                                  │
│   stopped ──────> running (绑定原 session_id)                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 触发操作

| 操作 | 触发条件 | 执行内容 | 代码位置 |
|------|---------|---------|---------|
| **启动** | `run()` | 创建 session，设置 `status='running'` | `binance_live.py:3671` |
| **停止** | `stop()` 或异常 | 取消挂单，保存状态，设置 `status='stopped'` | `binance_live.py:2596` |
| **暂停** | `pauseTrader()` | 设置 `self.paused=True`，停止处理订单 | `binance_live.py:2993` |
| **恢复** | `resumeTrader()` | 设置 `self.paused=False`，同步状态 | `binance_live.py:2993` |
| **重启恢复** | `recover_trader()` | 绑定原 session_id，恢复本地状态 | `binance_live.py:4572` |

### 1.4 数据库表结构

#### live_cases（配置表）

```sql
CREATE TABLE live_cases (
    id INTEGER PRIMARY KEY,
    name TEXT,
    symbol TEXT NOT NULL,
    testnet INTEGER DEFAULT 1,
    status TEXT DEFAULT 'draft',  -- draft / active / archived
    amplitude TEXT DEFAULT '{}',
    market TEXT DEFAULT '{}',
    entry TEXT DEFAULT '{}',
    timeout TEXT DEFAULT '{}',
    capital TEXT DEFAULT '{}',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### live_sessions（会话表）

```sql
CREATE TABLE live_sessions (
    id INTEGER PRIMARY KEY,
    case_id INTEGER,
    symbol TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,                  -- 停止时间
    status TEXT DEFAULT 'running',  -- running / stopped
    total_trades INTEGER DEFAULT 0,
    win_trades INTEGER DEFAULT 0,
    loss_trades INTEGER DEFAULT 0,
    net_profit REAL DEFAULT 0,
    initial_capital REAL DEFAULT 0,
    final_capital REAL DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (case_id) REFERENCES live_cases(id)
);
```

---

## 二、Order 状态

### 2.1 状态定义

| 状态 | 含义 | 订单动作 |
|------|------|---------|
| `pending` | 挂单中 | 入场单已下单，等待成交 |
| `filled` | 已成交 | 入场单成交，持有仓位 |
| `closed` | 已平仓 | 止盈/止损触发，仓位平掉 |
| `cancelled` | 已取消 | 订单被取消（超时重挂等） |

### 2.2 状态转换图

```
┌─────────────────────────────────────────────────────────────┐
│                     Order 状态转换                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   ┌─────────┐   成交(FILLED)   ┌─────────┐   止盈/止损      │
│   │ pending │ ─────────────────>│ filled  │ ───────────────>│ closed │
│   │ (挂单)  │                   │ (持仓)  │                  │ (平仓) │
│   └────┬────┘                   └────┬────┘                  └────────┘│
│        │                              │                                  │
│        │ 取消                          │ 止损触发                         │
│        │ (超时/手动)                   │ (盘中止损)                       │
│        ▼                              ▼                                  │
│   ┌──────────┐                  ┌─────────┐                            │
│   │cancelled │                  │ closed  │                            │
│   │ (取消)   │                  │ (平仓)  │                            │
│   └──────────┘                  └─────────┘                            │
│                                                                          │
│   超时重挂流程:                                                           │
│   pending ──(超时)──> cancelled ──(重挂)──> pending (新订单)             │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.3 触发操作

| 操作 | 触发条件 | 执行内容 | 代码位置 |
|------|---------|---------|---------|
| **下单** | 需要入场 | 创建订单，设置 `state='pending'` | `binance_live.py:2680` |
| **成交** | WebSocket `ORDER_TRADE_UPDATE` | 设置 `state='filled'`，下止盈止损单 | `binance_live.py:4273` |
| **止盈** | WebSocket `ALGO_UPDATE` | 设置 `state='closed'`，计算盈亏 | `binance_live.py:1245` |
| **止损** | WebSocket `ALGO_UPDATE` | 设置 `state='closed'`，计算盈亏 | `binance_live.py:1341` |
| **取消** | 超时/手动取消 | 设置 `state='cancelled'` | `binance_live.py:2914` |
| **超时重挂** | A1 挂单超时 | 取消原单，创建新订单 | `binance_live.py:3500` |

### 2.4 数据库表结构

```sql
CREATE TABLE live_orders (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    order_id INTEGER DEFAULT 0,        -- Binance 订单ID
    level INTEGER DEFAULT 1,           -- 层级 A1, A2, ...
    group_id INTEGER DEFAULT 0,        -- 轮次ID
    state TEXT DEFAULT 'pending',      -- pending / filled / closed / cancelled
    entry_price REAL DEFAULT 0,
    quantity REAL DEFAULT 0,
    stake_amount REAL DEFAULT 0,
    take_profit_price REAL DEFAULT 0,
    stop_loss_price REAL DEFAULT 0,
    tp_order_id INTEGER DEFAULT 0,     -- 止盈条件单ID
    sl_order_id INTEGER DEFAULT 0,     -- 止损条件单ID
    created_at TEXT,
    filled_at TEXT,
    closed_at TEXT,
    close_reason TEXT,                 -- take_profit / stop_loss / timeout
    close_price REAL DEFAULT 0,
    profit REAL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES live_sessions(id)
);
```

---

## 三、完整交易流程

### 3.1 正常交易流程

```
┌─────────────────────────────────────────────────────────────┐
│                     正常交易流程                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. 创建配置 (draft)                                         │
│     └── 创建 live_case，status='draft'                      │
│                                                              │
│  2. 启动交易 (running)                                       │
│     ├── 创建 live_session，status='running'                 │
│     ├── 初始化行情轨道（Dual Thrust）                        │
│     ├── 计算 A1 入场价，下 LIMIT BUY 单                      │
│     └── 订单 state='pending'                                │
│                                                              │
│  3. 入场成交 (filled)                                        │
│     ├── WebSocket 收到 ORDER_TRADE_UPDATE                   │
│     ├── 订单 state='filled'                                 │
│     ├── 下 TAKE_PROFIT_MARKET 条件单                        │
│     ├── 下 STOP_MARKET 条件单                               │
│     └── 如有更多层级，下 A2 入场单                           │
│                                                              │
│  4. 止盈/止损触发 (closed)                                   │
│     ├── WebSocket 收到 ALGO_UPDATE                          │
│     ├── 订单 state='closed'                                 │
│     ├── 计算 profit，更新统计                               │
│     ├── 记录 live_trades                                    │
│     └── 如止盈，下新一轮 A1                                  │
│                                                              │
│  5. 停止交易 (stopped)                                       │
│     ├── 取消所有 pending 订单                               │
│     ├── 保存资金统计                                         │
│     └── 更新 live_session，status='stopped'                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 超时重挂流程

```
┌─────────────────────────────────────────────────────────────┐
│                     超时重挂流程                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. A1 挂单超过配置时间未成交                                 │
│     └── 定时检查 (每 5 分钟)                                 │
│                                                              │
│  2. 取消原订单                                               │
│     ├── 取消 LIMIT 入场单                                   │
│     ├── 取消关联的止盈止损条件单                             │
│     └── 原订单 state='cancelled'                            │
│                                                              │
│  3. 创建新订单                                               │
│     ├── 获取最新价格                                         │
│     ├── 重新计算入场价                                       │
│     ├── 下新 LIMIT 入场单                                   │
│     └── 新订单 state='pending', timeout_count+1             │
│                                                              │
│  4. 记录统计                                                 │
│     └── 更新 timeout_refresh_count                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 状态恢复流程

```
┌─────────────────────────────────────────────────────────────┐
│                     状态恢复流程                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. 验证 Session                                             │
│     ├── 检查 session 存在                                    │
│     ├── 检查 status='stopped'                               │
│     └── 获取关联的 case_id                                  │
│                                                              │
│  2. 创建 Trader 实例                                         │
│     └── 设置 recover_session_id                             │
│                                                              │
│  3. 加载本地状态                                             │
│     ├── 从 state_{symbol}.json 加载                         │
│     │   ├── orders 列表                                     │
│     │   ├── group_id                                        │
│     │   ├── capital_pool 状态                               │
│     │   └── results 统计                                    │
│     └── 恢复 chain_state                                    │
│                                                              │
│  4. 同步交易所状态                                           │
│     ├── 查询 Binance 挂单状态                               │
│     ├── 查询 Algo 条件单状态                                │
│     ├── 检测暂停期间的成交/止损                             │
│     │   ├── 如果入场单成交 → 下止盈止损                     │
│     │   └── 如果止盈止损触发 → 计算盈亏                     │
│     └── 补充缺失的止盈止损单                                 │
│                                                              │
│  5. 同步资金状态                                             │
│     └── 对比当前资金与保存的资金                            │
│                                                              │
│  6. 继续 WebSocket 循环                                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、本地状态文件

### 4.1 文件位置

```
state_{symbol}.json
```

例如：`state_BTCUSDT.json`

### 4.2 文件结构

```json
{
  "orders": [
    {
      "level": 1,
      "state": "filled",
      "entry_price": "67500.00",
      "quantity": "0.025",
      "take_profit_price": "68175.00",
      "stop_loss_price": "62100.00",
      "tp_order_id": 123456,
      "sl_order_id": 123457,
      "order_id": 789012,
      "timeout_count": 0
    }
  ],
  "group_id": 5,
  "base_price": 67500.0,
  "capital_pool": {
    "trading_capital": 5000.0,
    "profit_pool": 125.50,
    "total_profit": 350.00,
    "total_loss": 224.50,
    "withdrawal_count": 0,
    "liquidation_count": 0
  },
  "results": {
    "total_trades": 15,
    "win_trades": 9,
    "loss_trades": 6,
    "total_profit": 350.00,
    "total_loss": 224.50
  }
}
```

---

## 五、关键代码位置

### 5.1 Session 管理

| 功能 | 文件 | 方法 |
|------|------|------|
| 创建配置 | `database/live_trading_db.py` | `create_case()` |
| 启动 Session | `binance_live.py:3671` | `run()` |
| 停止 Session | `binance_live.py:2596` | `_handle_exit()` |
| 结束 Session | `database/live_trading_db.py:1083` | `end_session()` |
| 恢复 Session | `binance_live.py:4572` | `recover_trader()` |

### 5.2 Order 管理

| 功能 | 文件 | 方法 |
|------|------|------|
| 下入场单 | `binance_live.py:2680` | `_place_entry_order()` |
| 下止盈止损单 | `binance_live.py:2786` | `_place_tp_sl_orders()` |
| 处理成交 | `binance_live.py:4273` | `_handle_order_filled()` |
| 处理止盈 | `binance_live.py:1245` | `_handle_take_profit()` |
| 处理止损 | `binance_live.py:1341` | `_handle_stop_loss()` |
| 超时重挂 | `binance_live.py:3500` | `_check_first_entry_timeout()` |

### 5.3 状态恢复

| 功能 | 文件 | 方法 |
|------|------|------|
| 恢复订单状态 | `binance_live.py:3054` | `_restore_orders()` |
| 同步订单状态 | `binance_live.py:2858` | `_sync_orders_from_exchange()` |
| 同步资金状态 | `binance_live.py:2957` | `_sync_capital()` |
| 保存状态 | `binance_live.py:2265` | `_save_state()` |

---

## 六、WebSocket 事件处理

### 6.1 订阅的事件

| 事件类型 | 说明 | 处理方法 |
|---------|------|---------|
| `ORDER_TRADE_UPDATE` | 订单状态更新 | `_handle_order_update()` |
| `ALGO_UPDATE` | 条件单状态更新 | `handle_algo_update()` |
| `kline` | K线数据（日线） | `_handle_kline_event()` |
| `listenKeyExpired` | Listen Key 过期 | 重连 WebSocket |

### 6.2 事件处理流程

```
WebSocket 消息
      │
      ├── ORDER_TRADE_UPDATE
      │   ├── status=FILLED → 入场成交处理
      │   └── status=CANCELED → 订单取消处理
      │
      ├── ALGO_UPDATE
      │   ├── TAKE_PROFIT → 止盈处理
      │   └── STOP → 止损处理
      │
      ├── kline
      │   ├── x=true (收盘) → 重新计算轨道
      │   └── x=false (盘中) → 检查价格突破
      │
      └── listenKeyExpired
          └── 重新获取 Listen Key，重连
```

---

## 七、API 接口

### 7.1 Session 相关

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/live-cases` | GET | 获取配置列表 |
| `/api/live-cases` | POST | 创建配置 |
| `/api/live-sessions` | GET | 获取会话列表 |
| `/api/live-sessions/<id>` | GET | 获取会话详情 |
| `/api/live-sessions/<id>` | DELETE | 删除会话 |
| `/api/traders` | GET | 获取运行中的 traders |
| `/api/traders/start/<case_id>` | POST | 启动交易 |
| `/api/traders/stop/<session_id>` | POST | 停止交易 |
| `/api/traders/pause/<session_id>` | POST | 暂停交易 |
| `/api/traders/resume/<session_id>` | POST | 恢复交易 |
| `/api/traders/recover/<session_id>` | POST | 恢复已停止的会话 |

### 7.2 Order 相关

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/live-sessions/<id>/orders` | GET | 获取订单列表 |
| `/api/live-sessions/<id>/trades` | GET | 获取交易记录 |
| `/api/live-sessions/<id>/state` | GET | 获取当前状态 |
| `/api/live-sessions/<id>/metrics` | GET | 获取统计指标 |

---

*文档版本: 1.0*
*创建日期: 2026-04-01*
*更新: Session 状态与订单状态管理文档*
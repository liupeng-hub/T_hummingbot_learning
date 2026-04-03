# Autofish V2 实盘交易系统设计文档

## 文档信息

| 项目 | 内容 |
|------|------|
| 创建日期 | 2026-04-03 |
| 版本 | 1.2 |
| 适用项目 | autofish_bot_v2 |

---

## 一、系统概述

### 1.1 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Autofish V2 系统架构                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ Web API     │    │ 主程序      │    │ 数据库      │         │
│  │ (Flask)     │◄──►│ binance_live│◄──►│ (SQLite)    │         │
│  │ 端口 5003   │    │ .py         │    │             │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│                            │                                     │
│                            ▼                                     │
│                     ┌─────────────┐                             │
│                     │ Binance API │                             │
│                     │ (WebSocket) │                             │
│                     └─────────────┘                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 核心文件

| 文件 | 职责 |
|------|------|
| `binance_live.py` | 主程序，包含交易逻辑、API交互、状态管理 |
| `autofish_core.py` | 核心数据结构（订单、状态、资金池等） |
| `binance_live_web.py` | Web API 服务 |
| `database/live_trading_db.py` | 数据库操作层 |
| `out/autofish/defaults/timeout_strategy.json` | 超时参数定义配置 |

### 1.3 核心类

| 类名 | 职责 |
|------|------|
| `BinanceLiveTrader` | 交易器主类，管理整个交易流程 |
| `BinanceClient` | Binance API 封装，REST 和 WebSocket |
| `AlgoHandler` | 止盈止损条件单事件处理 |
| `LiveTraderManager` | 多实例管理器 |
| `Autofish_Order` | 订单数据结构 |
| `Autofish_ChainState` | 链式订单状态管理 |
| `Autofish_CapitalPool` | 资金池管理 |

---

## 二、核心数据结构

### 2.1 订单状态

```
┌─────────────────────────────────────────────────────────────────┐
│                    订单生命周期                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  pending ──(成交)──► filled ──(止盈/止损)──► closed              │
│      │                  │                                        │
│      │                  └──(市价平仓)──► closed                   │
│      │                                                           │
│      └──(取消)──► cancelled                                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 订单数据结构

```python
@dataclass
class Autofish_Order:
    # 基本信息
    level: int                    # 层级 (1, 2, 3, 4)
    entry_price: Decimal          # 入场价
    quantity: Decimal             # 数量
    stake_amount: Decimal         # 投入金额
    take_profit_price: Decimal    # 止盈价
    stop_loss_price: Decimal      # 止损价

    # 状态
    state: str = "pending"        # pending/filled/closed/cancelled
    group_id: int = 0             # 轮次ID

    # Binance 订单ID
    order_id: Optional[int]       # 入场单ID
    tp_order_id: Optional[int]    # 止盈条件单ID
    sl_order_id: Optional[int]    # 止损条件单ID

    # 平仓信息
    close_price: Optional[Decimal]
    close_reason: Optional[str]   # take_profit/stop_loss
    profit: Optional[Decimal]
```

### 2.3 链式状态

```python
@dataclass
class Autofish_ChainState:
    base_price: Decimal              # 基准价格
    orders: List[Autofish_Order]     # 订单列表
    is_active: bool = True           # 是否活跃
    group_id: int = 0                # 当前轮次
```

### 2.4 Group ID 设计

```
┌─────────────────────────────────────────────────────────────────┐
│                    Group ID 设计原则                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  chain_state.group_id 表示"最后一个成交轮次"                      │
│                                                                  │
│  A1 下单时：order.group_id = chain_state.group_id + 1            │
│           chain_state.group_id 不变（等成交确认）                 │
│                                                                  │
│  A1 成交时：chain_state.group_id = order.group_id（确认轮次）     │
│                                                                  │
│  A2/A3/A4 下单：order.group_id = chain_state.group_id            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、程序运行场景

### 3.1 场景概览

| 场景 | 触发条件 | 主要操作 |
|------|---------|---------|
| 启动新实例 | 命令行启动 | 初始化配置、连接API、下A1单 |
| 恢复实例 | 程序重启 | 从数据库恢复状态、同步交易所 |
| 正常交易 | 订单成交 | 下止盈止损单、下下一级订单 |
| 止盈触发 | Algo事件 | 计算盈亏、更新资金池、清理订单 |
| 止损触发 | Algo事件 | 计算盈亏、更新资金池、清理订单 |
| 行情变化 | 状态检测 | 取消挂单、平仓持仓 |
| 程序退出 | 信号/命令 | 取消订单、保存状态、通知 |

### 3.2 启动流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    启动流程                                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 解析命令行参数                                                │
│     └── --case-id: 配置ID                                        │
│     └── --recover-session-id: 恢复模式                           │
│                                                                  │
│  2. 加载配置                                                      │
│     └── 从 live_cases 表读取配置                                  │
│                                                                  │
│  3. 初始化交易器                                                  │
│     ├── BinanceClient (API连接)                                  │
│     ├── 资金池初始化                                              │
│     ├── 行情检测器初始化                                          │
│     └── 精度信息获取                                              │
│                                                                  │
│  4. 创建/恢复 Session                                             │
│     ├── 新启动：create_session()                                 │
│     └── 恢复：_restore_orders()                                  │
│                                                                  │
│  5. 启动 WebSocket                                                │
│     ├── 订阅用户数据流（订单更新）                                 │
│     └── 订阅 K线数据流（行情检测）                                 │
│                                                                  │
│  6. 启动主循环                                                    │
│     ├── WebSocket 事件处理                                        │
│     ├── 行情状态检测                                              │
│     └── A1 超时检查                                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 恢复流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    恢复流程 (_restore_orders)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 从 live_sessions 加载 session 状态                           │
│     ├── base_price, group_id                                    │
│     └── 统计数据 (total_trades, win_trades, etc.)               │
│                                                                  │
│  2. 从 live_capital_statistics 加载资金池状态                     │
│     └── trading_capital, profit_pool, etc.                      │
│                                                                  │
│  3. 从 live_orders 加载订单                                       │
│     ├── 只恢复 state != 'closed' 且 state != 'cancelled'         │
│     └── 保持原始层级                                              │
│                                                                  │
│  4. 创建 chain_state                                             │
│     └── 使用数据库中的 base_price 和 group_id                     │
│                                                                  │
│  5. 同步交易所状态                                                │
│     ├── 查询 Binance 订单状态                                    │
│     ├── 查询 Algo 条件单状态                                     │
│     ├── 检测成交/取消/平仓                                       │
│     └── 补充缺失的止盈止损单                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 四、订单处理逻辑

### 4.1 订单ID关系

```
┌─────────────────────────────────────────────────────────────────┐
│                    订单ID关系                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  每个订单有3个独立ID：                                            │
│                                                                  │
│  A1 入场单: order_id_1 (LIMIT订单)                               │
│  A1 止盈单: tp_order_id_1 (Algo条件单)                           │
│  A1 止损单: sl_order_id_1 (Algo条件单)                           │
│                                                                  │
│  A2 入场单: order_id_2 (LIMIT订单)                               │
│  A2 止盈单: tp_order_id_2 (Algo条件单)                           │
│  A2 止损单: sl_order_id_2 (Algo条件单)                           │
│                                                                  │
│  ...每个订单都是独立的ID                                          │
│                                                                  │
│  注意：Binance期货持仓是合并的，同一方向的所有订单合并为一个持仓     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 入场价格计算

```
入场价 = base_price × (1 - grid_spacing × level)

示例（base_price=67000, grid_spacing=1%）:
  A1: 67000 × (1 - 0.01 × 1) = 66330
  A2: 67000 × (1 - 0.01 × 2) = 65660
  A3: 67000 × (1 - 0.01 × 3) = 64990
  A4: 67000 × (1 - 0.01 × 4) = 64320
```

### 4.3 止盈止损价格

```
止盈价 = 入场价 × (1 + exit_profit)
止损价 = 入场价 × (1 - stop_loss)

示例（入场价=66000, exit_profit=1%, stop_loss=8%）:
  止盈价: 66000 × 1.01 = 66660
  止损价: 66000 × 0.92 = 60720
```

### 4.4 价格关系图

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

---

## 五、挂单逻辑

### 5.1 链式下单原则

```
┌─────────────────────────────────────────────────────────────────┐
│                    链式下单原则                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  只有 A(n) 成交，才会下 A(n+1) 的 pending 挂单                    │
│                                                                  │
│  A1 pending → A1 成交 → 下 A2 pending                            │
│           → A2 成交 → 下 A3 pending                              │
│           → A3 成交 → 下 A4 pending                              │
│                                                                  │
│  因此：任何时候最多只有一个 pending 订单                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 入场单下单流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    入场单下单 (_place_entry_order)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 计算入场价                                                    │
│     entry_price = base_price × (1 - grid_spacing × level)       │
│                                                                  │
│  2. 调整价格和数量精度                                             │
│     └── 满足 Binance 最小金额要求                                 │
│                                                                  │
│  3. 发送 LIMIT 订单                                               │
│     POST /fapi/v1/order                                          │
│     { symbol, side: BUY, type: LIMIT, quantity, price }         │
│                                                                  │
│  4. 获取 orderId                                                  │
│     order.order_id = result["orderId"]                           │
│                                                                  │
│  5. 保存到数据库                                                  │
│     db.save_order(session_id, order)                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 止盈止损单下单流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    止盈止损单下单 (_place_exit_orders)             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  触发条件：入场单成交后自动调用                                     │
│                                                                  │
│  1. 止盈单 (TAKE_PROFIT_MARKET)                                  │
│     POST /fapi/v1/algo/order                                     │
│     { symbol, side: SELL, type: TAKE_PROFIT_MARKET,             │
│       quantity, triggerPrice }                                   │
│     └── 返回 algoId → order.tp_order_id                         │
│                                                                  │
│  2. 止损单 (STOP_MARKET)                                         │
│     POST /fapi/v1/algo/order                                     │
│     { symbol, side: SELL, type: STOP_MARKET,                    │
│       quantity, triggerPrice }                                   │
│     └── 返回 algoId → order.sl_order_id                         │
│                                                                  │
│  3. 更新数据库                                                    │
│     db.update_order(session_id, order)                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 六、取消逻辑

### 6.1 取消场景

| 场景 | 取消内容 | 触发位置 |
|------|---------|---------|
| A1止盈 | 取消 A2 pending | `_cancel_next_level_and_restart` |
| A1止损 | 取消 A2 pending | `_cancel_next_level` |
| 行情变非交易 | 取消所有 pending | `_handle_market_status_change` |
| 程序退出 | 取消所有订单 | `_handle_exit` |
| A1超时 | 取消旧 A1 pending | `_refresh_first_entry_order` |

### 6.4 A1 超时重挂评估流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    A1 超时重挂评估流程                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  触发条件：A1 挂单超过 a1_timeout_minutes 分钟未成交              │
│                                                                  │
│  1. 计算新入场价                                                  │
│     new_entry_price = current_price × (1 - grid_spacing)        │
│                                                                  │
│  2. 评估是否应该重挂                                              │
│     ├── 检查最大超时次数限制                                      │
│     │   if max_timeout_count > 0 AND timeout_count >= max:      │
│     │       → 停止重挂，保留原订单                               │
│     │                                                            │
│     └── 检查价格差异阈值                                         │
│         price_diff = (new_entry_price - old_entry_price)        │
│                     / old_entry_price                            │
│         if price_diff < min_refresh_price_diff:                 │
│             → 跳过重挂，重置计时器继续等待                        │
│             → 记录 skipped_refresh_count                         │
│                                                                  │
│  3. 执行重挂（条件满足时）                                        │
│     ├── 取消旧入场单和止盈止损单                                  │
│     ├── 下新入场单                                               │
│     ├── 记录 timeout_refresh_count                               │
│     └── 传递超时次数（累加）                                      │
│                                                                  │
│  配置参数：                                                       │
│  - min_refresh_price_diff: 最小重挂价格差异（默认 1.67%）         │
│  - max_timeout_count: 最大超时次数（默认 10，0 表示不限制）        │
│                                                                  │
│  示例（价格 60000，阈值 1.67%）：                                  │
│  - 旧入场价: 59400 (60000 × 0.99)                                │
│  - 新入场价: 59500 (60060 × 0.99)                                │
│  - 价格差异: 0.17% < 1.67% → 跳过重挂                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 取消下一级订单

```
┌─────────────────────────────────────────────────────────────────┐
│                    取消下一级订单                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  _cancel_next_level(order):                                      │
│                                                                  │
│  1. 找到下一级 pending 订单                                       │
│     next_level = order.level + 1                                │
│     next_order = 找到 level==next_level 且 state==pending       │
│                                                                  │
│  2. 取消 Binance 订单                                            │
│     DELETE /fapi/v1/order { symbol, orderId }                   │
│                                                                  │
│  3. 更新本地状态                                                  │
│     next_order.state = "cancelled"                              │
│     chain_state.orders.remove(next_order)                       │
│                                                                  │
│  4. 更新数据库                                                   │
│     db.update_order(session_id, next_order)                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 A1 止盈后的特殊处理

```
┌─────────────────────────────────────────────────────────────────┐
│                    A1 止盈后的处理                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  _cancel_next_level_and_restart(order):                          │
│                                                                  │
│  1. 取消下一级 pending 订单                                       │
│                                                                  │
│  2. 如果 order.level == 1（A1止盈）:                             │
│     └── 重新下 A1 pending（新一轮开始）                           │
│                                                                  │
│  3. 如果 order.level != 1:                                       │
│     └── 不下单，等待其他订单处理                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 七、止盈止损处理

### 7.1 止盈触发流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    止盈触发 (_handle_take_profit)                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  触发条件：收到 Algo 事件，algoId == order.tp_order_id           │
│                                                                  │
│  1. 检查订单状态（避免重复处理）                                   │
│     if order.state == "closed": return                          │
│                                                                  │
│  2. 更新订单状态                                                  │
│     order.state = "closed"                                      │
│     order.close_reason = "take_profit"                          │
│     order.close_price = order.take_profit_price                 │
│                                                                  │
│  3. 计算盈亏                                                      │
│     profit = (take_profit_price - entry_price) × quantity       │
│            × leverage                                            │
│                                                                  │
│  4. 更新资金池                                                    │
│     capital_pool.update_capital(profit)                         │
│                                                                  │
│  5. 更新统计                                                      │
│     results['total_trades'] += 1                                │
│     results['win_trades'] += 1                                  │
│     results['total_profit'] += profit                           │
│                                                                  │
│  6. 保存交易记录到数据库                                          │
│     db.save_trade(session_id, order, 'take_profit')             │
│                                                                  │
│  7. 取消下一级订单                                                │
│     await _cancel_next_level_and_restart(order)                 │
│                                                                  │
│  8. 发送通知                                                      │
│     notify_take_profit(order, profit)                           │
│                                                                  │
│  9. 保存状态                                                      │
│     _save_state()                                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 止损触发流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    止损触发 (_handle_stop_loss)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  触发条件：收到 Algo 事件，algoId == order.sl_order_id           │
│                                                                  │
│  流程与止盈类似，区别：                                            │
│                                                                  │
│  - order.close_reason = "stop_loss"                             │
│  - order.close_price = order.stop_loss_price                   │
│  - results['loss_trades'] += 1                                  │
│  - results['total_loss'] += profit (负数)                       │
│  - 取消下一级但不下新单：_cancel_next_level(order)               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 止盈止损顺序

```
止盈触发顺序（价格上涨）：
  TP4 → TP3 → TP2 → TP1 (TP4 最低，最先触发)

止损触发顺序（价格下跌）：
  SL1 → SL2 → SL3 → SL4 (SL1 最高，最先触发)
```

---

## 八、平仓逻辑

### 8.1 平仓场景

| 场景 | 触发位置 | 说明 |
|------|---------|------|
| 行情变非交易 | `_handle_market_status_change` | 取消pending，平仓filled |
| 程序退出 | `_handle_exit` | 清理所有订单 |
| 持仓检查 | 外部调用 | 手动平仓 |

### 8.2 平仓流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    平仓流程 (_close_all_positions)               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  输入：close_price (平仓价格), reason (平仓原因)                  │
│                                                                  │
│  1. 收集所有 filled 订单                                         │
│     filled_orders = [o for o in orders if o.state == "filled"]  │
│                                                                  │
│  2. 计算总持仓数量                                                │
│     total_quantity = sum(o.quantity for o in filled_orders)     │
│                                                                  │
│  3. 取消所有止盈止损条件单                                        │
│     for order in filled_orders:                                 │
│         cancel_algo_order(order.tp_order_id)                    │
│         cancel_algo_order(order.sl_order_id)                    │
│                                                                  │
│  4. 发送市价卖出订单                                              │
│     POST /fapi/v1/order                                         │
│     { symbol, side: SELL, type: MARKET, quantity }             │
│                                                                  │
│  5. 获取成交价格                                                  │
│     actual_close_price = result["avgPrice"]                     │
│                                                                  │
│  6. 更新每个订单状态                                              │
│     for order in filled_orders:                                 │
│         order.state = "closed"                                  │
│         order.close_price = actual_close_price                  │
│         order.close_reason = reason                             │
│                                                                  │
│         # 独立计算每个订单盈亏                                    │
│         order_profit = (close_price - entry_price) × quantity   │
│         order.profit = order_profit                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.3 盈亏计算

```
每个订单独立计算盈亏：

  订单盈亏 = (平仓价 - 入场价) × 数量

示例（平仓价 = 66000）:
  A1: 入场价=67000, 数量=0.03 → (66000-67000)×0.03 = -300
  A2: 入场价=66500, 数量=0.03 → (66000-66500)×0.03 = -150
  A3: 入场价=66200, 数量=0.03 → (66000-66200)×0.03 = -60
  总盈亏 = -510
```

---

## 九、行情感知

### 9.1 行情状态

| 状态 | 说明 | 交易策略 |
|------|------|---------|
| `RANGING` | 震荡 | 正常交易 |
| `TRENDING_UP` | 上涨趋势 | 根据配置决定 |
| `TRENDING_DOWN` | 下跌趋势 | 根据配置决定 |
| `UNKNOWN` | 未知 | 不交易 |

### 9.2 行情检测机制

```
┌─────────────────────────────────────────────────────────────────┐
│                    行情检测                                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 实时检测（WebSocket K线事件）                                 │
│     订阅: btcusdt@kline_1d (日线K线)                            │
│     触发: 每次 K线 更新时检测价格是否突破 band                    │
│                                                                  │
│  2. 定时检测（check_interval）                                   │
│     配置: market_config.dual_thrust.check_interval (默认60秒)   │
│     触发: 定时补充检测，防止遗漏事件                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 9.3 行情变化处理

```
┌─────────────────────────────────────────────────────────────────┐
│                    行情变化处理                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  非交易状态 → 非交易状态: 不处理                                   │
│                                                                  │
│  非交易状态 → 交易状态:                                           │
│     ├── 取消旧 pending 订单                                      │
│     └── 下新 A1 订单                                             │
│                                                                  │
│  交易状态 → 非交易状态:                                           │
│     ├── 取消所有 pending 订单                                    │
│     ├── 市价平仓所有 filled 订单                                 │
│     └── 标记 chain_state.is_active = False                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 9.4 Dual Thrust 算法详解

#### 9.4.1 算法原理

Dual Thrust 算法基于历史波动幅度构建突破区间：

```
公式：
  Range = max(HH - LC, HC - LL)
  Upper = Open + K1 * Range
  Lower = Open - K2 * Range * K2_Down_Factor (下跌时更敏感)

其中：
  HH = 前 n_days 天的最高价
  LL = 前 n_days 天的最低价
  HC = 前 n_days 天的最高收盘价
  LC = 前 n_days 天的最低收盘价
  Open = 当日开盘价
```

#### 9.4.2 默认参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `n_days` | 4 | 计算 Range 的历史天数 |
| `k1` | 0.4 | 上轨系数 |
| `k2` | 0.4 | 下轨系数 |
| `k2_down_factor` | 0.8 | 下跌敏感因子 |
| `down_confirm_days` | 2 | 下跌确认天数 |
| `cooldown_days` | 1 | 状态切换冷却期 |

#### 9.4.3 状态判断逻辑

```
┌─────────────────────────────────────────────────────────────────┐
│                    Dual Thrust 状态判断                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  价格位置判断：                                                   │
│                                                                  │
│  current_price > Upper:                                          │
│     └── TRENDING_UP (上涨趋势)                                   │
│                                                                  │
│  current_price < Lower (连续 down_confirm_days 天):              │
│     └── TRENDING_DOWN (下跌趋势)                                 │
│                                                                  │
│  其他情况：                                                       │
│     └── RANGING (震荡行情)                                       │
│                                                                  │
│  特殊处理：                                                       │
│  - 上涨突破：立即生效                                             │
│  - 下跌突破：需连续确认（避免假突破）                              │
│  - 冷却期内：使用宽松下轨（避免频繁切换）                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 9.5 K线数据获取与聚合

#### 9.5.1 数据周期说明

| 场景 | 获取方式 | 说明 |
|------|---------|------|
| 初始化 | 直接获取日线 | 启动时从缓存获取历史日线 |
| 运行时 | 获取1h聚合为日线 | 实时性强，无需等日线收盘 |

#### 9.5.2 初始化流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    行情初始化 (_initialize_market_bands)          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 计算时间范围                                                  │
│     end_time = now                                               │
│     start_time = now - (n_days + 2) 天                           │
│                                                                  │
│  2. 获取历史日线                                                  │
│     klines = fetcher.fetch_kline(                                │
│         symbol, interval='1d', start_time, end_time              │
│     )                                                            │
│                                                                  │
│  3. 数据校验                                                      │
│     if len(klines) < n_days + 1:                                 │
│         → 默认 RANGING 状态                                      │
│         → return                                                 │
│                                                                  │
│  4. 计算 Dual Thrust 轨道                                        │
│     result = algorithm.calculate(klines[-(n_days+1):])           │
│                                                                  │
│  5. 缓存轨道数据                                                  │
│     _current_bands = {upper, lower, range, ...}                  │
│                                                                  │
│  6. 设置当前状态                                                  │
│     current_market_status = result.status                        │
│                                                                  │
│  7. 保存到数据库                                                  │
│     ├── save_market_result() → live_market_results               │
│     └── save_dual_thrust_bands() → live_market_dual_thrust       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 9.5.3 运行时检测流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    运行时行情检测                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  方式1: WebSocket K线事件（事件驱动）                             │
│                                                                  │
│  订阅: {symbol}@kline_1d                                         │
│     ├── K线更新 (x=false): _on_kline_update()                    │
│     │   └── 检查是否突破轨道                                     │
│     └── K线收盘 (x=true): _on_daily_kline_closed()               │
│         └── 重新计算轨道                                         │
│                                                                  │
│  方式2: 1h K线聚合（备选）                                        │
│                                                                  │
│  获取: 100 根 1h K线                                             │
│     ↓                                                            │
│  聚合: _aggregate_to_daily(klines)                               │
│     ├── 按日期分组                                               │
│     ├── 合并 OHLCV                                               │
│     └── 生成约 4-5 天的日线数据                                  │
│     ↓                                                            │
│  计算: algorithm.calculate(daily_klines)                         │
│                                                                  │
│  注意: 100h ≈ 4.16 天，刚好满足 n_days=4 的最小需求               │
│       如果跨周末/假期可能数据不足                                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 9.5.4 日线聚合逻辑

```python
def _aggregate_to_daily(klines: List[Dict]) -> List[Dict]:
    """将分钟K线聚合为日线"""
    daily_data = {}
    for k in klines:
        ts = k.get('timestamp', 0)
        dt = datetime.fromtimestamp(ts / 1000)
        date_key = dt.strftime('%Y-%m-%d')

        if date_key not in daily_data:
            daily_data[date_key] = {
                'open': k['open'],
                'high': k['high'],
                'low': k['low'],
                'close': k['close'],
                'volume': k['volume'],
            }
        else:
            daily_data[date_key]['high'] = max(daily_data[date_key]['high'], k['high'])
            daily_data[date_key]['low'] = min(daily_data[date_key]['low'], k['low'])
            daily_data[date_key]['close'] = k['close']
            daily_data[date_key]['volume'] += k['volume']

    return [daily_data[d] for d in sorted(daily_data.keys())]
```

### 9.6 行情数据存储

#### 9.6.1 相关数据表

| 表 | 内容 | 写入时机 |
|---|------|---------|
| `live_market_cases` | 行情配置 | Session 创建时 |
| `live_market_results` | 行情检测结果 | 初始化、K线事件、定时检测 |
| `live_market_dual_thrust` | Dual Thrust 轨道 | 初始化、日线收盘 |

#### 9.6.2 写入时机汇总

| 触发事件 | 写入内容 |
|---------|---------|
| 程序启动 | 初始行情状态、轨道数据 |
| K线更新 | 行情检测结果 |
| 日线收盘 | 新的轨道数据 |
| 状态变化 | 行情检测结果 |

---

## 十、状态保存与恢复

### 10.1 数据库表

| 表 | 内容 | 用途 |
|---|------|------|
| `live_cases` | 实盘配置 | 配置管理 |
| `live_sessions` | 会话记录 | 统计、状态 |
| `live_orders` | 订单记录 | 订单生命周期 |
| `live_trades` | 交易记录 | 完整交易历史 |
| `live_capital_statistics` | 资金统计 | 资金池状态 |
| `live_capital_history` | 资金历史 | 资金变化记录 |

### 10.2 数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                    数据流                                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  写入时机：                                                       │
│                                                                  │
│  下入场单 → save_order()                                         │
│  入场成交 → update_order()                                       │
│  下止盈止损 → update_order() (更新 tp/sl_order_id)               │
│  止盈触发 → update_order(), save_trade(), save_capital_history() │
│  止损触发 → update_order(), save_trade(), save_capital_history() │
│  订单取消 → update_order()                                       │
│  状态变化 → update_session_stats() (base_price, group_id)        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 10.3 恢复数据来源

| 数据 | 来源 |
|------|------|
| 订单 | `live_orders` 表 |
| 资金池 | `live_capital_statistics` 表 |
| 统计 | `live_sessions` 表 |
| base_price | `live_sessions.base_price` |
| group_id | `live_sessions.group_id` |

---

## 十一、数据库设计详解

### 11.1 数据库表概览

系统使用 SQLite 数据库，包含以下表：

| 表 | 内容 | 主要字段 |
|---|------|---------|
| `live_cases` | 实盘配置 | id, name, symbol, amplitude, market, capital |
| `live_sessions` | 会话记录 | id, case_id, symbol, status, base_price, group_id, 统计字段 |
| `live_orders` | 订单记录 | id, session_id, level, group_id, state, 入场价, 止盈止损价 |
| `live_trades` | 交易记录 | id, session_id, order_id, trade_type, profit |
| `live_capital_statistics` | 资金统计 | id, session_id, trading_capital, profit_pool |
| `live_capital_history` | 资金历史 | id, session_id, old_capital, new_capital, event_type |
| `live_market_cases` | 行情配置 | id, session_id, algorithm, check_interval |
| `live_market_results` | 行情结果 | id, case_id, market_status, confidence |
| `live_market_dual_thrust` | Dual Thrust 轨道 | id, session_id, upper_band, lower_band |
| `live_session_metrics` | 会话统计指标 | id, session_id, 执行时间/持仓时间/超时统计 |
| `live_notifications` | 通知记录 | id, session_id, msg_type, content |

### 11.2 表结构详情

#### live_cases - 实盘配置表

```sql
CREATE TABLE live_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    symbol TEXT NOT NULL,
    testnet INTEGER DEFAULT 1,
    amplitude TEXT DEFAULT '{}',   -- JSON: grid_spacing, exit_profit, stop_loss, etc.
    market TEXT DEFAULT '{}',      -- JSON: algorithm, trading_statuses
    entry TEXT DEFAULT '{}',       -- JSON: entry_price_strategy
    timeout TEXT DEFAULT '{}',     -- JSON: a1_timeout_minutes, min_refresh_price_diff, max_timeout_count
    capital TEXT DEFAULT '{}',     -- JSON: total_amount_quote, leverage, strategy
    status TEXT DEFAULT 'draft',   -- draft, active, stopped, archived
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

#### live_sessions - 实盘会话表

```sql
CREATE TABLE live_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER DEFAULT 0,
    name TEXT DEFAULT '',
    symbol TEXT NOT NULL,
    testnet INTEGER DEFAULT 1,
    start_time TEXT NOT NULL,
    end_time TEXT,
    status TEXT DEFAULT 'running',  -- running, stopped, error
    -- 配置快照
    amplitude TEXT DEFAULT '{}',
    market TEXT DEFAULT '{}',
    entry TEXT DEFAULT '{}',
    timeout TEXT DEFAULT '{}',     -- JSON: a1_timeout_minutes, min_refresh_price_diff, max_timeout_count
    capital TEXT DEFAULT '{}',
    -- 统计结果
    total_trades INTEGER DEFAULT 0,
    win_trades INTEGER DEFAULT 0,
    loss_trades INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0,
    total_profit REAL DEFAULT 0,
    total_loss REAL DEFAULT 0,
    net_profit REAL DEFAULT 0,
    initial_capital REAL DEFAULT 0,
    final_capital REAL DEFAULT 0,
    roi REAL DEFAULT 0,
    -- 状态字段（新增）
    base_price REAL DEFAULT 0,
    group_id INTEGER DEFAULT 0,
    -- 其他
    error_message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES live_cases(id)
)
```

#### live_orders - 实盘订单表

```sql
CREATE TABLE live_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    order_id INTEGER DEFAULT 0,       -- Binance orderId
    level INTEGER DEFAULT 1,          -- 订单层级 (1, 2, 3, 4)
    group_id INTEGER DEFAULT 0,       -- 轮次ID
    state TEXT DEFAULT 'pending',     -- pending, filled, closed, cancelled
    -- 价格信息
    entry_price REAL DEFAULT 0,
    quantity REAL DEFAULT 0,
    stake_amount REAL DEFAULT 0,
    take_profit_price REAL DEFAULT 0,
    stop_loss_price REAL DEFAULT 0,
    -- Binance 订单ID
    tp_order_id INTEGER DEFAULT 0,    -- 止盈条件单ID
    sl_order_id INTEGER DEFAULT 0,    -- 止损条件单ID
    -- 时间戳
    created_at TEXT,
    first_created_at TEXT,            -- 首次下单时间（超时重挂时保持）
    filled_at TEXT,
    closed_at TEXT,
    -- 平仓信息
    close_reason TEXT,                -- take_profit, stop_loss, market_status_change
    close_price REAL DEFAULT 0,
    profit REAL DEFAULT 0,
    -- 资金快照
    entry_capital REAL DEFAULT 0,
    entry_total_capital REAL DEFAULT 0,
    -- 补单标记
    tp_supplemented INTEGER DEFAULT 0,
    sl_supplemented INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
)
```

#### live_trades - 交易记录表

```sql
CREATE TABLE live_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    order_id INTEGER NOT NULL,        -- 关联 live_orders.id
    trade_type TEXT,                  -- take_profit, stop_loss
    level INTEGER DEFAULT 1,
    entry_price REAL DEFAULT 0,
    exit_price REAL DEFAULT 0,
    quantity REAL DEFAULT 0,
    profit REAL DEFAULT 0,
    leverage INTEGER DEFAULT 10,
    entry_time TEXT,
    exit_time TEXT,
    holding_duration_seconds INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (order_id) REFERENCES live_orders(id)
)
```

#### live_capital_statistics - 资金统计表

```sql
CREATE TABLE live_capital_statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL UNIQUE,
    strategy TEXT DEFAULT 'guding',
    initial_capital REAL NOT NULL,
    final_capital REAL NOT NULL,
    trading_capital REAL NOT NULL,
    profit_pool REAL NOT NULL,
    total_return REAL NOT NULL,
    total_profit REAL NOT NULL,
    total_loss REAL NOT NULL,
    max_capital REAL NOT NULL,
    max_drawdown REAL NOT NULL,
    withdrawal_threshold REAL DEFAULT 2.0,
    withdrawal_retain REAL DEFAULT 1.5,
    liquidation_threshold REAL DEFAULT 0.2,
    withdrawal_count INTEGER NOT NULL DEFAULT 0,
    total_withdrawal REAL NOT NULL DEFAULT 0,
    liquidation_count INTEGER NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    profit_trades INTEGER NOT NULL DEFAULT 0,
    loss_trades INTEGER NOT NULL DEFAULT 0,
    avg_profit REAL NOT NULL DEFAULT 0,
    avg_loss REAL NOT NULL DEFAULT 0,
    win_rate REAL NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
)
```

#### live_session_metrics - 会话统计指标表

```sql
CREATE TABLE live_session_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL UNIQUE,
    -- 累计执行时间统计（分钟）
    avg_execution_time REAL DEFAULT 0,
    min_execution_time REAL DEFAULT 0,
    max_execution_time REAL DEFAULT 0,
    total_execution_time REAL DEFAULT 0,
    execution_count INTEGER DEFAULT 0,
    -- 持仓时间统计（分钟）
    avg_holding_time REAL DEFAULT 0,
    min_holding_time REAL DEFAULT 0,
    max_holding_time REAL DEFAULT 0,
    total_holding_time REAL DEFAULT 0,
    holding_count INTEGER DEFAULT 0,
    -- 盈亏分布统计
    max_profit_trade REAL DEFAULT 0,
    max_loss_trade REAL DEFAULT 0,
    profit_factor REAL DEFAULT 0,
    -- 订单层级统计
    order_group_count INTEGER DEFAULT 0,
    max_level_reached INTEGER DEFAULT 0,
    tp_trigger_count INTEGER DEFAULT 0,
    sl_trigger_count INTEGER DEFAULT 0,
    -- 超时统计
    timeout_refresh_count INTEGER DEFAULT 0,
    skipped_refresh_count INTEGER DEFAULT 0,  -- 因价格差异不足跳过的重挂次数
    supplement_count INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
)
```

### 11.3 表关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                    数据库表关系                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  live_cases ──(case_id)──► live_sessions                        │
│                              │                                   │
│                              ├──► live_orders (session_id)       │
│                              │       │                           │
│                              │       └──► live_trades (order_id) │
│                              │                                   │
│                              ├──► live_capital_statistics        │
│                              │       │                           │
│                              │       └──► live_capital_history   │
│                              │                                   │
│                              ├──► live_market_cases              │
│                              │       │                           │
│                              │       └──► live_market_results    │
│                              │                                   │
│                              ├──► live_market_dual_thrust        │
│                              │                                   │
│                              ├──► live_notifications             │
│                              │                                   │
│                              └──► live_session_metrics           │
│                                                                  │
│  外键约束:                                                       │
│  - live_sessions.case_id → live_cases.id                        │
│  - live_orders.session_id → live_sessions.id (ON DELETE CASCADE)│
│  - live_trades.session_id → live_sessions.id (ON DELETE CASCADE)│
│  - live_trades.order_id → live_orders.id                        │
│  - 其他表均有 session_id 外键                                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 11.4 关键索引

```sql
-- 高频查询索引
CREATE INDEX idx_live_sessions_status ON live_sessions(status);
CREATE INDEX idx_live_orders_session ON live_orders(session_id);
CREATE INDEX idx_live_trades_session ON live_trades(session_id);
CREATE INDEX idx_live_capital_stats_session ON live_capital_statistics(session_id);
CREATE INDEX idx_live_market_results_time ON live_market_results(check_time);
CREATE INDEX idx_live_dual_thrust_date ON live_market_dual_thrust(kline_date);
```

---

## 十二、时序图

### 12.1 启动新实例时序图

```
用户              binance_live.py           BinanceClient           Binance API             数据库
  │                     │                        │                      │                    │
  │  启动命令           │                        │                      │                    │
  │  --case-id 1        │                        │                      │                    │
  │────────────────────►│                        │                      │                    │
  │                     │                        │                      │                    │
  │                     │  db.get_case(1)        │                      │                    │
  │                     │───────────────────────────────────────────────────────────────────►│
  │                     │◄───────────────────────────────────────────────────────────────────│
  │                     │                        │                      │                    │
  │                     │  初始化 BinanceClient  │                      │                    │
  │                     │───────────────────────►│                      │                    │
  │                     │                        │  GET /fapi/v1/       │                    │
  │                     │                        │  exchangeInfo        │                    │
  │                     │                        │─────────────────────►│                    │
  │                     │                        │◄─────────────────────│                    │
  │                     │◄───────────────────────│                      │                    │
  │                     │                        │                      │                    │
  │                     │  db.create_session()   │                      │                    │
  │                     │───────────────────────────────────────────────────────────────────►│
  │                     │◄───────────────────────────────────────────────────────────────────│
  │                     │                        │                      │                    │
  │                     │  db.save_statistics()  │                      │                    │
  │                     │───────────────────────────────────────────────────────────────────►│
  │                     │                        │                      │                    │
  │                     │  计算 Dual Thrust      │                      │                    │
  │                     │  db.save_dual_thrust_bands()                  │                    │
  │                     │───────────────────────────────────────────────────────────────────►│
  │                     │                        │                      │                    │
  │                     │                        │  POST /fapi/v1/order │                    │
  │                     │                        │  (LIMIT BUY A1)      │                    │
  │                     │                        │─────────────────────►│                    │
  │                     │                        │◄─────────────────────│                    │
  │                     │◄───────────────────────│  orderId             │                    │
  │                     │                        │                      │                    │
  │                     │  db.save_order()       │                      │                    │
  │                     │───────────────────────────────────────────────────────────────────►│
  │                     │                        │                      │                    │
  │                     │  启动 WebSocket        │                      │                    │
  │                     │───────────────────────►│                      │                    │
  │                     │                        │  订阅用户数据流      │                    │
  │                     │                        │─────────────────────►│                    │
  │                     │                        │  订阅K线数据流       │                    │
  │                     │                        │─────────────────────►│                    │
```

### 12.2 恢复实例时序图

```
用户              binance_live.py           数据库                 Binance API
  │                     │                        │                      │
  │  启动命令           │                        │                      │
  │  --recover-session-id 35                    │                      │
  │────────────────────►│                        │                      │
  │                     │                        │                      │
  │                     │  db.get_session(35)    │                      │
  │                     │───────────────────────►│                      │
  │                     │◄───────────────────────│  base_price, group_id│
  │                     │                        │  统计数据            │
  │                     │                        │                      │
  │                     │  db.get_statistics(35) │                      │
  │                     │───────────────────────►│                      │
  │                     │◄───────────────────────│  资金池状态          │
  │                     │                        │                      │
  │                     │  db.get_orders(35)     │                      │
  │                     │───────────────────────►│                      │
  │                     │◄───────────────────────│  订单列表            │
  │                     │  (state != closed/cancelled)                 │
  │                     │                        │                      │
  │                     │  创建 chain_state      │                      │
  │                     │                        │                      │
  │                     │  同步交易所状态        │                      │
  │                     │  ─────────────────────────────────────────────►│
  │                     │  GET /fapi/v1/order    │                      │
  │                     │  (查询入场单状态)      │                      │
  │                     │◄─────────────────────────────────────────────│
  │                     │                        │                      │
  │                     │  GET /fapi/v1/algo/order                     │
  │                     │  (查询条件单状态)      │                      │
  │                     │◄─────────────────────────────────────────────│
  │                     │                        │                      │
  │                     │  检测成交/取消/平仓    │                      │
  │                     │                        │                      │
  │                     │  [如缺失止盈止损单]    │                      │
  │                     │  POST /fapi/v1/algo/order                    │
  │                     │─────────────────────────────────────────────►│
  │                     │◄─────────────────────────────────────────────│
  │                     │                        │                      │
  │                     │  db.update_order()     │                      │
  │                     │  (更新 tp/sl_order_id) │                      │
  │                     │───────────────────────►│                      │
  │                     │                        │                      │
  │                     │  启动 WebSocket        │                      │
```

### 12.3 入场成交时序图

```
Binance WS          binance_live.py           数据库                 Binance API
    │                     │                        │                      │
    │  ORDER_TRADE_UPDATE │                        │                      │
    │  status=FILLED      │                        │                      │
    │────────────────────►│                        │                      │
    │                     │                        │                      │
    │                     │  匹配订单              │                      │
    │                     │  (orderId == order.order_id)                 │
    │                     │                        │                      │
    │                     │  order.state = "filled"                      │
    │                     │                        │                      │
    │                     │  db.update_order()     │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  [如果是 A1 成交]      │                      │
    │                     │  chain_state.group_id  │                      │
    │                     │    = order.group_id    │                      │
    │                     │  db.update_session_stats()                   │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  下止盈止损单          │                      │
    │                     │  ─────────────────────────────────────────────►│
    │                     │  POST /fapi/v1/algo/order                    │
    │                     │  (TAKE_PROFIT_MARKET)  │                      │
    │                     │◄─────────────────────────────────────────────│
    │                     │  algoId → tp_order_id  │                      │
    │                     │                        │                      │
    │                     │  POST /fapi/v1/algo/order                    │
    │                     │  (STOP_MARKET)         │                      │
    │                     │◄─────────────────────────────────────────────│
    │                     │  algoId → sl_order_id  │                      │
    │                     │                        │                      │
    │                     │  db.update_order()     │                      │
    │                     │  (更新 tp/sl_order_id) │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  [如果有 pending 容量] │                      │
    │                     │  下下一级入场单        │                      │
    │                     │  POST /fapi/v1/order   │                      │
    │                     │  (LIMIT BUY An+1)      │                      │
    │                     │─────────────────────────────────────────────►│
    │                     │◄─────────────────────────────────────────────│
    │                     │                        │                      │
    │                     │  db.save_order()       │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  发送通知              │                      │
```

### 12.4 止盈触发时序图

```
Binance WS          binance_live.py           数据库                 Binance API
    │                     │                        │                      │
    │  Algo 事件          │                        │                      │
    │  algoId == tp_order_id                      │                      │
    │────────────────────►│                        │                      │
    │                     │                        │                      │
    │                     │  匹配订单              │                      │
    │                     │  (algoId → order.tp_order_id)                │
    │                     │                        │                      │
    │                     │  order.state = "closed"                      │
    │                     │  order.close_reason    │                      │
    │                     │    = "take_profit"     │                      │
    │                     │  order.close_price     │                      │
    │                     │    = take_profit_price │                      │
    │                     │  order.profit = (...)  │                      │
    │                     │                        │                      │
    │                     │  db.update_order()     │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  db.save_trade()       │                      │
    │                     │  (写入 live_trades)    │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  capital_pool.update_capital(profit)         │
    │                     │                        │                      │
    │                     │  db.save_statistics()  │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  db.save_capital_history()                   │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  db.update_session_stats()                   │
    │                     │  (total_trades++, win_trades++)              │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  取消下一级订单        │                      │
    │                     │  DELETE /fapi/v1/order │                      │
    │                     │─────────────────────────────────────────────►│
    │                     │                        │                      │
    │                     │  db.update_order()     │                      │
    │                     │  (state='cancelled')   │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  [如果是 A1 止盈]      │                      │
    │                     │  下新 A1 pending       │                      │
    │                     │  POST /fapi/v1/order   │                      │
    │                     │─────────────────────────────────────────────►│
    │                     │                        │                      │
    │                     │  db.save_order()       │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  发送止盈通知          │                      │
```

### 12.5 止损触发时序图

```
Binance WS          binance_live.py           数据库                 Binance API
    │                     │                        │                      │
    │  Algo 事件          │                        │                      │
    │  algoId == sl_order_id                      │                      │
    │────────────────────►│                        │                      │
    │                     │                        │                      │
    │                     │  匹配订单              │                      │
    │                     │  (algoId → order.sl_order_id)                │
    │                     │                        │                      │
    │                     │  order.state = "closed"                      │
    │                     │  order.close_reason    │                      │
    │                     │    = "stop_loss"       │                      │
    │                     │  order.close_price     │                      │
    │                     │    = stop_loss_price   │                      │
    │                     │  order.profit = (...)  │  (负数)              │
    │                     │                        │                      │
    │                     │  db.update_order()     │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  db.save_trade()       │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  db.save_statistics()  │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  db.save_capital_history()                   │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  db.update_session_stats()                   │
    │                     │  (total_trades++, loss_trades++)             │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  取消下一级订单        │                      │
    │                     │  (不下新单)            │                      │
    │                     │  DELETE /fapi/v1/order │                      │
    │                     │─────────────────────────────────────────────►│
    │                     │                        │                      │
    │                     │  db.update_order()     │                      │
    │                     │  (state='cancelled')   │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  发送止损通知          │                      │
```

### 12.6 行情变化时序图

```
K线 WS              binance_live.py           数据库                 Binance API
    │                     │                        │                      │
    │  K线更新事件        │                        │                      │
    │  (价格突破 band)    │                        │                      │
    │────────────────────►│                        │                      │
    │                     │                        │                      │
    │                     │  计算行情状态          │                      │
    │                     │  market_status =       │                      │
    │                     │    'trending_down'     │                      │
    │                     │                        │                      │
    │                     │  检查 trading_statuses │                      │
    │                     │  不在交易状态          │                      │
    │                     │                        │                      │
    │                     │  [交易状态 → 非交易状态]                       │
    │                     │                        │                      │
    │                     │  取消所有 pending 订单 │                      │
    │                     │  DELETE /fapi/v1/order │                      │
    │                     │─────────────────────────────────────────────►│
    │                     │                        │                      │
    │                     │  db.update_order()     │                      │
    │                     │  (state='cancelled')   │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  平仓所有 filled 订单  │                      │
    │                     │  [取消止盈止损条件单]  │                      │
    │                     │  DELETE /fapi/v1/algo/order                  │
    │                     │─────────────────────────────────────────────►│
    │                     │                        │                      │
    │                     │  [市价卖出]            │                      │
    │                     │  POST /fapi/v1/order   │                      │
    │                     │  { type: MARKET,       │                      │
    │                     │    side: SELL }        │                      │
    │                     │─────────────────────────────────────────────►│
    │                     │◄─────────────────────────────────────────────│
    │                     │  avgPrice              │                      │
    │                     │                        │                      │
    │                     │  更新每个订单状态      │                      │
    │                     │  order.state = "closed"                      │
    │                     │  order.close_reason =  │                      │
    │                     │    "market_status_change"                    │
    │                     │  db.update_order()     │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  db.save_trade()       │                      │
    │                     │  (每个订单)            │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  db.save_statistics()  │                      │
    │                     │───────────────────────►│                      │
    │                     │                        │                      │
    │                     │  chain_state.is_active = False               │
    │                     │                        │                      │
    │                     │  发送行情变化通知      │                      │
```

### 12.7 平仓流程时序图

```
binance_live.py           数据库                 Binance API
      │                        │                      │
      │  收集 filled 订单      │                      │
      │  (从 chain_state.orders)                     │
      │                        │                      │
      │  计算总数量            │                      │
      │  total_quantity = sum(order.quantity)       │
      │                        │                      │
      │  取消止盈止损条件单    │                      │
      │  DELETE /fapi/v1/algo/order                 │
      │  (每个 tp_order_id)    │                      │
      │─────────────────────────────────────────────►│
      │  DELETE /fapi/v1/algo/order                 │
      │  (每个 sl_order_id)    │                      │
      │─────────────────────────────────────────────►│
      │                        │                      │
      │  发送市价卖出          │                      │
      │  POST /fapi/v1/order   │                      │
      │  { side: SELL,         │                      │
      │    type: MARKET,       │                      │
      │    quantity }          │                      │
      │─────────────────────────────────────────────►│
      │◄─────────────────────────────────────────────│
      │  avgPrice              │                      │
      │                        │                      │
      │  更新每个订单状态      │                      │
      │  for order in filled_orders:                 │
      │    order.state = "closed"                    │
      │    order.close_price = avgPrice              │
      │    order.profit = (avgPrice - entry_price)   │
      │                  × quantity                  │
      │    db.update_order()   │                      │
      │───────────────────────►│                      │
      │                        │                      │
      │  保存交易记录          │                      │
      │  db.save_trade()       │                      │
      │  (每个订单)            │                      │
      │───────────────────────►│                      │
      │                        │                      │
      │  更新资金池            │                      │
      │  db.save_statistics()  │                      │
      │───────────────────────►│                      │
      │                        │                      │
      │  db.save_capital_history()                   │
      │───────────────────────►│                      │
```

---

## 十三、数据库操作映射

### 13.1 写入时机汇总表

| 触发事件 | 数据库操作 | 涉及表 |
|---------|-----------|--------|
| 创建配置 | `db.create_case()` | live_cases |
| 创建会话 | `db.create_session()` | live_sessions |
| 下入场单 | `db.save_order()` | live_orders |
| 入场成交 | `db.update_order()` + `db.update_session_stats()` | live_orders, live_sessions |
| 下止盈止损 | `db.update_order()` | live_orders |
| 止盈触发 | `db.update_order()` + `db.save_trade()` + `db.save_statistics()` + `db.save_capital_history()` + `db.update_session_stats()` | live_orders, live_trades, live_capital_statistics, live_capital_history, live_sessions |
| 止损触发 | 同止盈 | 同止盈 |
| 订单取消 | `db.update_order()` | live_orders |
| 行情检测 | `db.save_dual_thrust_bands()` | live_market_dual_thrust |
| 平仓 | 同止盈（多个订单） | 同止盈 |
| 发送通知 | `db.save_notification()` | live_notifications |

### 13.2 恢复读取时机汇总表

| 数据 | 来源表 | 方法 |
|------|--------|------|
| 配置 | live_cases | `db.get_case()` |
| Session 状态 | live_sessions | `db.get_session()` |
| base_price | live_sessions.base_price | `session.get('base_price')` |
| group_id | live_sessions.group_id | `session.get('group_id')` |
| 订单 | live_orders | `db.get_orders()` |
| 资金池 | live_capital_statistics | `db.get_statistics()` |
| 资金历史 | live_capital_history | `db.get_capital_history()` |
| 行情轨道 | live_market_dual_thrust | `db.get_latest_dual_thrust_bands()` |
| 通知记录 | live_notifications | `db.get_notifications()` |
| 统计指标 | live_session_metrics | `db.get_session_metrics()` |

### 13.3 关键字段更新时机

#### group_id 更新时机

| 操作 | 位置 | 说明 |
|------|------|------|
| 创建 session | `db.create_session()` | 初始化 `group_id=0` |
| A1 下单 | `_create_order()` | `order.group_id = chain_state.group_id + 1` |
| A1 成交 | `_process_order_filled()` | `chain_state.group_id = order.group_id` |
| A2/A3/A4 下单 | `_create_order()` | `order.group_id = chain_state.group_id` |
| 恢复 | `_restore_orders()` | `session.get('group_id', 0)` |

#### base_price 更新时机

| 操作 | 位置 | 说明 |
|------|------|------|
| 创建 session | `db.create_session()` | 初始化为当前价格 |
| 下单时 | `_save_state()` 或 `update_session_stats()` | 更新到最新基准价 |
| 恢复 | `_restore_orders()` | `session.get('base_price', current_price)` |

---

## 十四、WebSocket 事件处理

### 14.1 订阅流

```
用户数据流: <listenKey>
  └── ORDER_TRADE_UPDATE: 订单状态变化
  └── ACCOUNT_UPDATE: 账户更新

K线数据流: btcusdt@kline_1d
  └── K线更新事件: 行情检测
```

### 14.2 事件处理流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    WebSocket 事件处理                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ORDER_TRADE_UPDATE:                                             │
│     ├── NEW → 订单创建（忽略，已本地处理）                         │
│     ├── FILLED → _handle_order_filled()                         │
│     │    └── 入场单成交，下止盈止损单                             │
│     ├── CANCELED → _handle_order_cancelled()                    │
│     │    └── 订单取消（超时/手动）                                │
│     └── EXPIRED → 同 CANCELED                                   │
│                                                                  │
│  Algo 事件 (条件单触发):                                          │
│     ├── algoId == tp_order_id → _handle_take_profit()           │
│     └── algoId == sl_order_id → _handle_stop_loss()             │
│                                                                  │
│  K线更新:                                                         │
│     └── _on_kline_update() → 行情检测 → 价格突破判断              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 十五、资金池管理

### 15.1 资金池结构

```python
class Autofish_CapitalPool:
    trading_capital: Decimal      # 可用交易资金
    profit_pool: Decimal          # 利润池
    total_profit: Decimal         # 累计盈利
    total_loss: Decimal           # 累计亏损
    withdrawal_count: int         # 提现次数
    liquidation_count: int        # 爆仓次数
```

### 15.2 资金池更新

```
┌─────────────────────────────────────────────────────────────────┐
│                    资金池更新                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  update_capital(profit):                                         │
│     trading_capital += profit                                   │
│     if profit > 0:                                              │
│         total_profit += profit                                  │
│         profit_pool += profit                                   │
│     else:                                                        │
│         total_loss += profit  # profit 是负数                   │
│                                                                  │
│  check_liquidation():                                            │
│     return trading_capital < liquidation_threshold              │
│                                                                  │
│  recover_from_liquidation():                                     │
│     if profit_pool >= withdrawal_retain:                        │
│         transfer = profit_pool - withdrawal_retain              │
│         trading_capital += transfer                             │
│         profit_pool = withdrawal_retain                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 十六、通知系统

### 16.1 通知类型

| 类型 | 触发 | 模板 |
|------|------|------|
| `startup` | 程序启动 | 启动通知 |
| `entry` | 入场单下单 | 入场通知 |
| `entry_filled` | 入场成交 | 成交通知 |
| `take_profit` | 止盈触发 | 止盈通知 |
| `stop_loss` | 止损触发 | 止损通知 |
| `market_status` | 行情变化 | 行情通知 |
| `exit` | 程序退出 | 退出通知 |
| `error` | 严重错误 | 错误通知 |

### 16.2 通知渠道

- 企业微信 Webhook（配置 `WECHAT_WEBHOOK`）

---

## 十七、配置说明

### 17.1 主要配置项

```json
{
  "symbol": "BTCUSDT",
  "testnet": true,
  "amplitude": {
    "decay_factor": 0.5,
    "stop_loss": 0.08,
    "leverage": 10,
    "max_entries": 4,
    "grid_spacing": 0.01,
    "exit_profit": 0.01
  },
  "market": {
    "algorithm": "dual_thrust",
    "trading_statuses": ["ranging"],
    "dual_thrust": {
      "n_days": 4,
      "k1": 0.4,
      "k2": 0.4,
      "check_interval": 60
    }
  },
  "capital": {
    "total_amount_quote": 5000,
    "strategy": "jijin",
    "entry_mode": "compound"
  },
  "timeout": {
    "a1_timeout_minutes": 0,
    "min_refresh_price_diff": 0.0167,
    "max_timeout_count": 10
  }
}
```

---

## 十八、总结

### 18.1 核心流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    核心交易流程                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  启动 ──► 下A1 pending ──► A1成交 ──► 下A1止盈止损 ──► 下A2     │
│                              │                                   │
│                              ▼                                   │
│                     ┌─────────────────┐                         │
│                     │ 止盈/止损触发    │                         │
│                     └────────┬────────┘                         │
│                              │                                   │
│              ┌───────────────┼───────────────┐                  │
│              ▼               ▼               ▼                  │
│         A1止盈          An止盈          止损触发                  │
│         (新A1)         (不下单)       (不下新单)                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 18.2 关键设计点

1. **链式下单**：只有前一级成交才下下一级
2. **单一 pending**：任何时候最多一个 pending 订单
3. **Group ID**：A1 成交确认轮次，保证连续性
4. **持仓合并**：Binance 期货持仓合并，平仓需计算总量
5. **数据持久化**：所有状态实时写入数据库
6. **行情感知**：根据行情状态决定是否交易

---

*文档版本: 2.4*
*创建日期: 2026-04-03*
*更新日期: 2026-04-04 - 添加 Dual Thrust 算法详解、K线获取与聚合逻辑*
# Binance Live 实盘交易模块说明文档

## 一、模块概述

### 1.1 简介

`binance_live.py` 是 Autofish Bot V2 的实盘交易模块，实现了基于链式挂单策略的 Binance Futures 自动交易。该模块通过 WebSocket 实时监听订单状态，支持状态恢复、补单机制、行情感知等高级功能。

### 1.2 核心功能

| 功能 | 描述 |
|-----|------|
| 链式挂单 | 支持 A1-A4 多层级网格入场 |
| 入场价格策略 | 支持 fixed/atr/bollinger/support/composite 策略 |
| 行情感知 | 基于 Dual Thrust/ADX 算法判断市场状态 |
| A1 超时重挂 | 入场单超时后自动取消并重新下单 |
| 状态恢复 | 程序重启后自动恢复订单状态 |
| 补单机制 | 检测并补充缺失的止盈止损条件单 |
| 实时通知 | 支持微信机器人推送交易通知 |

---

## 二、模块架构

### 2.1 类结构

```
binance_live.py
├── 常量定义 (STATE_FILE, LOG_FILE, OrderState, CloseReason...)
├── 日志配置 (setup_logger, FlushFileHandler)
├── 异常类 (BinanceAPIError, NetworkError, OrderError, StateError)
├── 重试机制 (RetryConfig, retry_on_exception)
├── 状态仓库 (StateRepository)
├── 通知服务 (NotificationTemplate, send_wechat_notification, notify_*)
├── BinanceClient (API 客户端)
│   ├── REST API 请求
│   ├── WebSocket 连接
│   ├── 订单操作
│   └── 条件单操作
├── AlgoHandler (条件单处理器)
│   ├── handle_algo_update()
│   ├── _handle_take_profit()
│   ├── _handle_stop_loss()
│   └── 补单逻辑
└── BinanceLiveTrader (主交易器)
    ├── run() - 主运行循环
    ├── _create_order() - 创建订单
    ├── _place_entry_order() - 下入场单
    ├── _process_order_filled() - 处理成交
    └── 状态管理方法
```

### 2.2 数据流

```
                           启动
                             │
                             ▼
                   ┌─────────────────┐
                   │  初始化精度      │
                   │  初始化行情检测   │
                   └─────────────────┘
                             │
                             ▼
                   ┌─────────────────┐
                   │  状态恢复        │
                   │  - 从文件加载    │
                   │  - 同步 Binance  │
                   └─────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────┐
          │         WebSocket 主循环          │
          │  ┌─────────────────────────────┐  │
          │  │ 1. 接收订单状态更新           │  │
          │  │ 2. 处理成交 → 下止盈止损      │  │
          │  │ 3. 处理止盈/止损 → 重新下单   │  │
          │  │ 4. 检查 A1 超时              │  │
          │  │ 5. 检查行情状态              │  │
          │  └─────────────────────────────┘  │
          └──────────────────────────────────┘
                             │
                             ▼
                          停止/退出
```

---

## 三、核心组件详解

### 3.1 BinanceClient - API 客户端

**职责：** 封装 Binance Futures API 调用

**主要方法：**

| 方法 | 功能 |
|-----|------|
| `get_exchange_info()` | 获取交易对精度信息 |
| `place_order()` | 下限价单 |
| `cancel_order()` | 取消订单 |
| `place_tp_sl_orders()` | 下止盈止损条件单 |
| `cancel_algo_order()` | 取消条件单 |
| `get_open_orders()` | 获取当前挂单 |
| `get_position()` | 获取持仓信息 |
| `create_listen_key()` | 创建 WebSocket 监听 key |
| `keepalive_listen_key()` | 续期监听 key |

### 3.2 AlgoHandler - 条件单处理器

**职责：** 处理止盈止损条件单的状态变化

**处理逻辑：**

```
ALGO_UPDATE 事件
      │
      ├── status = TRIGGERING → 触发中（等待成交）
      │
      ├── status = TRIGGERED → 已触发
      │
      ├── status = FINISHED → 已完成
      │     │
      │     ├── 是止盈单 → _handle_take_profit()
      │     │     ├── 更新订单状态
      │     │     ├── 计算盈亏
      │     │     ├── 取消止损单
      │     │     └── 创建新 A1
      │     │
      │     └── 是止损单 → _handle_stop_loss()
      │           ├── 更新订单状态
      │           ├── 计算盈亏
      │           ├── 取消止盈单
      │           └── 调整层级
      │
      └── status = CANCELED/EXPIRED/REJECTED → 需要补单
```

### 3.3 BinanceLiveTrader - 主交易器

**职责：** 协调所有组件，执行交易策略

**关键属性：**

```python
class BinanceLiveTrader:
    config: Dict[str, Any]          # 配置参数
    testnet: bool                   # 是否测试网
    chain_state: Autofish_ChainState # 链式订单状态
    client: BinanceClient           # API 客户端
    algo_handler: AlgoHandler       # 条件单处理器
    market_detector: MarketStatusDetector  # 行情检测器
    results: Dict                   # 交易统计结果
```

**主运行流程：**

```python
async def run(self):
    # 1. 初始化
    await self._init_precision()
    await self._init_market_detector()

    # 2. 检查资金
    if not await self._check_fund_sufficiency():
        return

    # 3. 创建 WebSocket 连接
    listen_key = await self.client.create_listen_key()

    async with session.ws_connect(ws_url) as ws:
        # 4. 恢复状态
        await self._restore_orders(current_price)

        # 5. 主循环
        while self.running:
            msg = await ws.receive()
            await self._handle_ws_message(data)

            # 检查 A1 超时
            await self._check_and_handle_first_entry_timeout()

            # 检查行情状态
            market_result = await self._check_market_status()
            if market_result.status != self.current_market_status:
                await self._handle_market_status_change(...)
```

---

## 四、订单生命周期

### 4.1 状态流转

```
                    创建订单
                        │
                        ▼
                ┌───────────────┐
                │   pending     │ ← 挂单等待成交
                └───────────────┘
                        │
                        │ 订单成交
                        ▼
                ┌───────────────┐
                │   filled      │ ← 已成交，持有仓位
                └───────────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
    ┌───────────┐ ┌───────────┐ ┌───────────┐
    │ take_profit│ │ stop_loss │ │ 强制平仓  │
    └───────────┘ └───────────┘ └───────────┘
          │             │             │
          └─────────────┼─────────────┘
                        ▼
                ┌───────────────┐
                │   closed      │ ← 已平仓
                └───────────────┘
```

### 4.2 成交后处理

```python
async def _process_order_filled(self, order, filled_price):
    # 1. 更新订单状态
    order.state = "filled"
    order.filled_at = datetime.now()

    # 2. 下止盈止损条件单
    await self._place_exit_orders(order)

    # 3. 发送通知
    notify_entry_filled(order, filled_price, ...)

    # 4. 下下一级入场单
    await self._place_next_level_order(order)
```

### 4.3 止盈处理

```python
async def _handle_take_profit(self, order, algo_data):
    # 1. 更新状态
    order.state = "closed"
    order.close_reason = "take_profit"
    order.close_price = order.take_profit_price

    # 2. 计算盈亏
    profit = (order.take_profit_price - order.entry_price) * order.quantity
    order.profit = profit

    # 3. 取消止损单
    await self.client.cancel_algo_order(symbol, order.sl_order_id)

    # 4. 发送通知
    notify_take_profit(order, profit, self.config)

    # 5. 取消下一级挂单，重新下 A1
    await self._cancel_next_level_and_restart(order)
```

---

## 五、配置说明

### 5.1 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|-----|------|-------|------|
| `symbol` | string | BTCUSDT | 交易对 |
| `total_amount_quote` | number | 10000 | 总投入金额 (USDT) |
| `leverage` | number | 10 | 杠杆倍数 |
| `max_entries` | number | 4 | 最大层级数 |
| `grid_spacing` | number | 0.01 | 网格间距 (1%) |
| `exit_profit` | number | 0.01 | 止盈比例 (1%) |
| `stop_loss` | number | 0.08 | 止损比例 (8%) |
| `decay_factor` | number | 0.5 | 衰减因子 |
| `weights` | array | [0.4, 0.3, 0.2, 0.1] | 各层级权重 |
| `a1_timeout_minutes` | number | 10 | A1 超时时间 (分钟) |

### 5.2 入场价格策略配置

```json
{
    "entry_price_strategy": {
        "strategy": "atr",
        "atr": {
            "atr_period": 14,
            "atr_multiplier": 0.5,
            "min_spacing": 0.005,
            "max_spacing": 0.03
        }
    }
}
```

### 5.3 行情感知配置

```json
{
    "market_aware": {
        "algorithm": "dual_thrust",
        "trading_statuses": ["ranging", "trending_up"],
        "dual_thrust": {
            "n_days": 4,
            "k1": 0.4,
            "k2": 0.4
        }
    }
}
```

---

## 六、使用方法

### 6.1 命令行启动

```bash
# 测试网
python binance_live.py --symbol BTCUSDT --testnet

# 主网
python binance_live.py --symbol BTCUSDT --no-testnet

# 自定义参数
python binance_live.py --symbol BTCUSDT --total-amount 5000 --decay-factor 0.5
```

### 6.2 环境变量

在 `.env` 文件中配置：

```env
# 测试网
BINANCE_TESTNET_API_KEY=your_testnet_api_key
BINANCE_TESTNET_SECRET_KEY=your_testnet_secret_key

# 主网
BINANCE_API_KEY=your_mainnet_api_key
BINANCE_SECRET_KEY=your_mainnet_secret_key

# 代理（可选）
HTTPS_PROXY=http://127.0.0.1:7890

# 微信机器人（可选）
WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
```

### 6.3 程序退出

- 按 `Ctrl+C` 正常退出
- 程序会自动保存状态到 `binance_live_state.json`
- 下次启动会自动恢复状态

---

## 七、状态恢复机制

### 7.1 状态文件

**文件路径：** `binance_live_state.json`

**内容结构：**

```json
{
    "base_price": "85000.00",
    "orders": [
        {
            "level": 1,
            "entry_price": "84150.00",
            "quantity": "0.001420",
            "stake_amount": "119.49",
            "take_profit_price": "84991.50",
            "stop_loss_price": "77418.00",
            "state": "filled",
            "order_id": 12345678,
            "tp_order_id": 87654321,
            "sl_order_id": 87654322,
            "created_at": "2026-03-27 10:00:00",
            "filled_at": "2026-03-27 10:15:00"
        }
    ],
    "is_active": true
}
```

### 7.2 恢复流程

```
程序启动
    │
    ▼
加载状态文件
    │
    ├── 文件不存在 → 创建新 A1 订单
    │
    └── 文件存在
        │
        ▼
    遍历订单列表
        │
        ├── pending → 检查 Binance 订单状态
        │     ├── 成交 → 处理成交逻辑
        │     └── 未成交 → 保留挂单
        │
        └── filled → 检查止盈止损单
              ├── 存在 → 保留
              └── 缺失 → 补下条件单
```

---

## 八、补单机制

### 8.1 场景说明

以下情况需要补单：

1. **止盈/止损单被拒绝** - 不满足 Binance 最小金额要求
2. **程序崩溃** - 条件单未下单成功
3. **网络中断** - 订单请求失败

### 8.2 补单逻辑

```python
# 状态恢复时检查
for order in chain_state.orders:
    if order.state == "filled":
        # 检查止盈单
        if not order.tp_order_id:
            await self._supplement_tp_order(order)

        # 检查止损单
        if not order.sl_order_id:
            await self._supplement_sl_order(order)
```

---

## 九、通知服务

### 9.1 通知类型

| 事件 | 标题 | 内容 |
|-----|------|------|
| 启动 | 🚀 启动通知 | 配置信息、当前价格 |
| 入场成交 | ✅ 入场成交 | 订单详情、持仓信息 |
| 止盈 | 🎯 止盈触发 | 盈利金额、持仓时长 |
| 止损 | 🛑 止损触发 | 亏损金额 |
| A1 超时重挂 | ⏰ A1 超时 | 原订单、新订单信息 |
| 行情变化 | 🔄 行情变化 | 状态变化、操作 |
| 退出 | ⏹️ 退出通知 | 运行时长、统计信息 |
| 错误 | ❌ 错误通知 | 错误信息 |

### 9.2 微信机器人配置

1. 在企业微信中创建群机器人
2. 获取 Webhook URL
3. 配置到 `.env` 文件

---

## 十、功能移植状态

### 10.1 已完成移植

| 功能 | 优先级 | 状态 | 说明 |
|-----|-------|------|------|
| 资金池管理 | P0 | ✅ 已完成 | 支持 FixedCapitalTracker 和 ProgressiveCapitalTracker |
| 入场资金策略 | P0 | ✅ 已完成 | 支持 fixed、compound、default 模式 |
| 盈亏计算（含杠杆） | P0 | ✅ 已完成 | 止盈止损计算已包含杠杆倍数 |
| 资金池状态持久化 | P0 | ✅ 已完成 | 保存到 binance_live_state.json |
| 状态恢复 | P0 | ✅ 已完成 | 程序重启后自动恢复资金池状态 |
| group_id 管理 | P0 | ✅ 已完成 | A1 成交时更新 group_id |
| 提现检查 | P0 | ✅ 已完成 | 止盈后自动检查提现触发 |
| 爆仓检查与恢复 | P0 | ✅ 已完成 | 止损后检查爆仓并尝试从利润池恢复 |
| 事件处理锁 | P1 | ✅ 已完成 | 使用 asyncio.Lock 确保 WebSocket 事件顺序处理 |
| 数据库存储 | P2 | ✅ 已完成 | SQLite 存储会话、订单、交易记录、资金历史 |
| Web API | P2 | ✅ 已完成 | 提供 /api/status, /api/orders, /api/capital 等接口 |
| 前端页面 | P2 | ✅ 已完成 | 实时状态展示页面（/index.html） |

### 10.2 新增模块

| 模块 | 文件 | 说明 |
|-----|------|------|
| 数据库模块 | database/live_trading_db.py | 实盘交易数据持久化 |
| Web API | binance_live.py (LiveTradingAPI) | 实时状态查询 API 服务 |
| 前端页面 | web/static/style.css, web/static/app.js | 实盘监控前端页面 |

详见移植方案文档：`docs/20260327_binance_live_migration_plan.md`

---

## 十一、配置示例（含资金池）

### 11.1 资金池配置

```json
{
    "symbol": "BTCUSDT",
    "total_amount_quote": 10000,
    "leverage": 10,
    "capital": {
        "strategy": "jijin",
        "entry_mode": "compound",
        "withdraw_threshold": 2.0,
        "withdraw_keep": 1.5,
        "liquidation_threshold": 0.1
    }
}
```

**策略说明：**

| 策略 | 说明 |
|-----|------|
| `guding` | 固定资金模式，交易资金不变 |
| `jijin` | 递进资金模式，支持利润池和提现 |

**入场模式：**

| 模式 | 说明 |
|-----|------|
| `fixed` | 固定金额入场 |
| `compound` | 复利模式，使用交易资金+利润池 |
| `default` | 默认模式，仅使用交易资金 |

### 11.2 状态文件格式

```json
{
    "base_price": "85000.00",
    "orders": [...],
    "capital_pool": {
        "trading_capital": 10000.0,
        "profit_pool": 5000.0,
        "total_profit": 8000.0,
        "total_loss": 3000.0,
        "withdrawal_count": 1,
        "liquidation_count": 0
    },
    "results": {
        "total_trades": 15,
        "win_trades": 10,
        "loss_trades": 5,
        "total_profit": 8000.0,
        "total_loss": 3000.0
    },
    "group_id": 3,
    "is_active": true
}
```

---

## 十二、故障排查

### 12.1 常见问题

| 问题 | 原因 | 解决方案 |
|-----|------|---------|
| WebSocket 连接失败 | 网络问题/代理配置 | 检查网络/配置代理 |
| 订单被拒绝 | 不满足最小金额 | 增加总资金/减少层级 |
| 条件单补单失败 | API 限流 | 等待重试 |
| 状态恢复异常 | 状态文件损坏 | 删除状态文件重新开始 |

### 12.2 日志文件

**路径：** `logs/binance_live.log`

**日志级别：** INFO

---

## 十三、安全注意事项

1. **API Key 安全** - 不要将 API Key 提交到代码仓库
2. **测试网优先** - 先在测试网验证策略，再切换主网
3. **资金管理** - 合理设置止损，控制风险
4. **监控** - 定期检查程序运行状态和交易记录

---

## 十四、Web API 服务

### 14.1 启动 API 服务

API 服务默认随交易程序自动启动，无需额外配置。

```python
# 配置项
config = {
    'api_enabled': True,    # 是否启用 API（默认 True）
    'api_port': 8080,       # API 端口（默认 8080）
}

# 或手动启动
from binance_live import LiveTradingAPI
api = LiveTradingAPI(trader=trader, port=8080)
await api.start()
```

### 14.2 API 接口

| 接口 | 方法 | 说明 |
|-----|------|------|
| `/api/status` | GET | 获取当前交易状态 |
| `/api/orders` | GET | 获取当前订单列表 |
| `/api/capital` | GET | 获取资金池状态 |
| `/api/stats` | GET | 获取统计数据 |
| `/api/session` | GET | 获取当前会话信息 |
| `/api/history` | GET | 获取历史会话列表 |
| `/api/trades` | GET | 获取交易记录 |

### 14.3 前端监控页面

访问 `http://localhost:8080/` 可查看实时监控页面，展示：

- 交易状态（交易对、网络、WebSocket 连接、行情状态）
- 资金池状态（初始资金、交易资金、利润池、提现次数）
- 订单列表（层级、状态、入场价、止盈止损、盈亏）
- 交易统计（总交易数、胜率、净盈亏）

---

## 十五、数据库存储

### 15.1 数据库文件

**路径：** `database/live_trading.db`

### 15.2 数据表

| 表名 | 说明 |
|-----|------|
| `live_sessions` | 交易会话表（每次启动创建一个会话） |
| `live_orders` | 实盘订单表 |
| `live_trades` | 交易记录表（止盈/止损成交） |
| `capital_history` | 资金历史表 |

### 15.3 查询示例

```python
from database.live_trading_db import LiveTradingDB

db = LiveTradingDB()

# 获取最新会话
session = db.get_latest_session('BTCUSDT')

# 获取交易记录
trades = db.get_trades(session['id'])

# 获取资金历史
history = db.get_capital_history(session['id'])
```

---

*文档版本: 3.0*
*创建日期: 2026-03-27*
*更新日期: 2026-03-28*
*更新内容: 完成 P1/P2 功能移植（事件处理锁、数据库存储、Web API、前端页面）*
*更新日期: 2026-03-27*
*更新内容: 完成 P0 核心功能移植（资金池管理、入场资金策略、盈亏计算含杠杆）*
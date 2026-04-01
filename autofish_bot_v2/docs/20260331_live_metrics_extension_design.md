# 实盘统计指标扩展设计

## 背景

回测系统 (`test_results` 表) 包含丰富的统计指标，如实盘系统缺乏类似的统计信息，不便于后续展示和分析。本文档设计扩展实盘的统计指标体系。

## 现有表结构对比

### 回测 test_results 表指标

| 字段 | 说明 | 实盘是否有 |
|------|------|-----------|
| total_trades | 总交易次数 | ✅ live_sessions |
| win_trades | 盈利次数 | ✅ live_sessions |
| loss_trades | 亏损次数 | ✅ live_sessions |
| win_rate | 胜率 | ✅ live_sessions |
| total_profit | 总盈利 | ✅ live_sessions |
| total_loss | 总亏损 | ✅ live_sessions |
| net_profit | 净盈亏 | ✅ live_sessions |
| roi | 投资回报率 | ✅ live_sessions |
| avg_execution_time | 平均挂单成交时间(分钟) | ❌ 缺失 |
| avg_holding_time | 平均持仓时间(分钟) | ❌ 缺失 |
| order_group_count | 订单组数(轮次) | ❌ 缺失 |
| max_profit_trade | 单笔最大盈利 | ❌ 缺失 |
| max_loss_trade | 单笔最大亏损 | ❌ 缺失 |
| profit_factor | 盈亏比 | ❌ 缺失 |
| max_drawdown | 最大回撤 | ✅ live_capital_statistics |
| sharpe_ratio | 夏普比率 | ❌ 缺失 |

### 实盘 live_orders 表字段

| 字段 | 说明 | 可用于计算 |
|------|------|-----------|
| created_at | 订单创建时间 | 执行时间起点 |
| filled_at | 订单成交时间 | 执行时间终点 |
| closed_at | 订单平仓时间 | 持仓时间终点 |
| profit | 盈亏 | 盈亏统计 |

### 实盘 live_trades 表字段

| 字段 | 说明 | 可用于计算 |
|------|------|-----------|
| holding_duration_seconds | 持仓时长(秒) | 持仓时间统计 |
| entry_time | 入场时间 | - |
| exit_time | 出场时间 | - |

---

## 设计方案

### 方案概述

创建专门的 `live_session_metrics` 表存储扩展统计指标，同时：
1. 扩展 `live_orders` 表，添加执行时间字段
2. 在 trader 运行时实时计算并更新指标
3. 会话结束时保存最终统计

### 1. 新增 live_session_metrics 表

```sql
CREATE TABLE IF NOT EXISTS live_session_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL UNIQUE,

    -- === 订单执行时间统计 (分钟) ===
    avg_execution_time REAL DEFAULT 0,       -- 平均挂单成交时间
    min_execution_time REAL DEFAULT 0,       -- 最短成交时间
    max_execution_time REAL DEFAULT 0,       -- 最长成交时间
    total_execution_time REAL DEFAULT 0,     -- 总等待时间

    -- === 持仓时间统计 (分钟) ===
    avg_holding_time REAL DEFAULT 0,         -- 平均持仓时间
    min_holding_time REAL DEFAULT 0,         -- 最短持仓时间
    max_holding_time REAL DEFAULT 0,         -- 最长持仓时间
    total_holding_time REAL DEFAULT 0,       -- 总持仓时间

    -- === 盈亏分布统计 ===
    max_profit_trade REAL DEFAULT 0,         -- 单笔最大盈利
    max_loss_trade REAL DEFAULT 0,           -- 单笔最大亏损
    avg_profit REAL DEFAULT 0,               -- 平均盈利（仅盈利交易）
    avg_loss REAL DEFAULT 0,                 -- 平均亏损（仅亏损交易）
    profit_factor REAL DEFAULT 0,            -- 盈亏比 = 总盈利/总亏损

    -- === 订单层级统计 ===
    order_group_count INTEGER DEFAULT 0,     -- 订单组数(轮次)
    max_level_reached INTEGER DEFAULT 0,     -- 最大层级达到
    tp_trigger_count INTEGER DEFAULT 0,      -- 止盈触发次数
    sl_trigger_count INTEGER DEFAULT 0,      -- 止损触发次数

    -- === 超时统计 ===
    timeout_refresh_count INTEGER DEFAULT 0, -- A1 超时重挂次数
    supplement_count INTEGER DEFAULT 0,      -- 止盈止损单补充次数

    -- === 时间统计 ===
    total_runtime_minutes REAL DEFAULT 0,    -- 总运行时长(分钟)
    trading_time_ratio REAL DEFAULT 0,       -- 交易时间占比
    paused_time_minutes REAL DEFAULT 0,      -- 暂停时长(分钟)

    -- === 元数据 ===
    calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_session_metrics_session ON live_session_metrics(session_id);
```

### 2. 扩展 live_orders 表

```sql
-- 添加执行时间字段（如果不存在）
ALTER TABLE live_orders ADD COLUMN execution_time_minutes REAL DEFAULT 0;
```

### 3. 指标计算逻辑

#### 3.1 执行时间计算（累计设计）

```
执行时间 = filled_at - first_created_at
```

**累计设计说明**：
- `first_created_at`: 订单首次挂单的时间
- `created_at`: 最近一次挂单的时间（超时重挂时会更新）
- 执行时间从首次挂单开始计算，包含所有超时重挂的等待时间

**超时重挂处理**：
```
A1 首次挂单 → pending → 超时取消 → 新 A1 挂单 → pending → 成交

first_created_at = 首次挂单时间（不变）
created_at = 最近挂单时间（更新）
filled_at = 成交时间

执行时间 = filled_at - first_created_at（累计等待时间）
```

在 `_record_execution_time()` 方法中计算：

```python
# binance_live.py

def _record_execution_time(self, order):
    """记录订单执行时间（累计设计）"""
    # 优先使用 first_created_at（累计时间），否则回退到 created_at
    start_time = order.first_created_at or order.created_at
    if start_time and order.filled_at:
        created = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
        filled = datetime.strptime(order.filled_at, '%Y-%m-%d %H:%M:%S')
        execution_time = (filled - created).total_seconds() / 60
        self._metrics['execution_times'].append(execution_time)
```

**超时重挂时保留首次创建时间**：

```python
# _place_entry_order() 中

if is_timeout_refresh and old_order and old_order.first_created_at:
    # 超时重挂：保留首次创建时间
    order.first_created_at = old_order.first_created_at
else:
    # 新订单：首次创建时间 = 当前时间
    order.first_created_at = now_str
```

#### 3.2 持仓时间计算

```
持仓时间 = closed_at - filled_at
```

已有 `holding_duration_seconds` 字段，可直接使用。

#### 3.3 盈亏统计更新

在订单平仓时更新：

```python
# binance_live.py

async def _process_order_closed(self, order, reason):
    # ... 现有代码 ...

    # 更新盈亏统计
    self._update_profit_metrics(order.profit, reason)
```

#### 3.4 指标聚合更新

```python
class BinanceLiveTrader:
    def _update_execution_metrics(self, execution_time: float):
        """更新执行时间统计"""
        metrics = self._get_or_create_metrics()

        # 累加
        metrics['total_execution_time'] += execution_time
        metrics['execution_count'] = metrics.get('execution_count', 0) + 1

        # 计算平均值
        metrics['avg_execution_time'] = (
            metrics['total_execution_time'] / metrics['execution_count']
        )

        # 最大最小值
        if metrics['min_execution_time'] == 0 or execution_time < metrics['min_execution_time']:
            metrics['min_execution_time'] = execution_time
        if execution_time > metrics['max_execution_time']:
            metrics['max_execution_time'] = execution_time

        self._metrics = metrics

    def _update_holding_metrics(self, holding_time: float):
        """更新持仓时间统计"""
        metrics = self._get_or_create_metrics()

        metrics['total_holding_time'] += holding_time
        metrics['holding_count'] = metrics.get('holding_count', 0) + 1

        metrics['avg_holding_time'] = (
            metrics['total_holding_time'] / metrics['holding_count']
        )

        if metrics['min_holding_time'] == 0 or holding_time < metrics['min_holding_time']:
            metrics['min_holding_time'] = holding_time
        if holding_time > metrics['max_holding_time']:
            metrics['max_holding_time'] = holding_time

        self._metrics = metrics

    def _update_profit_metrics(self, profit: float, reason: str):
        """更新盈亏统计"""
        metrics = self._get_or_create_metrics()

        # 更新止盈止损计数
        if reason == 'take_profit':
            metrics['tp_trigger_count'] = metrics.get('tp_trigger_count', 0) + 1
        elif reason == 'stop_loss':
            metrics['sl_trigger_count'] = metrics.get('sl_trigger_count', 0) + 1

        # 最大盈利/亏损
        if profit > 0:
            if profit > metrics.get('max_profit_trade', 0):
                metrics['max_profit_trade'] = profit
        else:
            if profit < metrics.get('max_loss_trade', 0):
                metrics['max_loss_trade'] = profit

        # 盈亏比
        if self.results['total_loss'] != 0:
            metrics['profit_factor'] = abs(
                float(self.results['total_profit']) / float(self.results['total_loss'])
            )

        self._metrics = metrics
```

---

## 实现步骤

### Step 1: 数据库表扩展

在 `database/live_trading_db.py` 中添加：

```python
# 创建 live_session_metrics 表
def _create_tables(self):
    # ... 现有表创建代码 ...

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS live_session_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL UNIQUE,

            -- 执行时间统计
            avg_execution_time REAL DEFAULT 0,
            min_execution_time REAL DEFAULT 0,
            max_execution_time REAL DEFAULT 0,
            total_execution_time REAL DEFAULT 0,
            execution_count INTEGER DEFAULT 0,

            -- 持仓时间统计
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
            supplement_count INTEGER DEFAULT 0,

            -- 时间统计
            total_runtime_minutes REAL DEFAULT 0,
            paused_time_minutes REAL DEFAULT 0,

            calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
        )
    """)
```

### Step 2: 新增 CRUD 方法

```python
# database/live_trading_db.py

def get_session_metrics(self, session_id: int) -> Optional[Dict]:
    """获取会话统计指标"""
    conn = self._get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT * FROM live_session_metrics WHERE session_id = ?
        """, (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def save_session_metrics(self, session_id: int, metrics: Dict) -> bool:
    """保存会话统计指标"""
    conn = self._get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO live_session_metrics (
                session_id, avg_execution_time, min_execution_time, max_execution_time,
                total_execution_time, execution_count, avg_holding_time, min_holding_time,
                max_holding_time, total_holding_time, holding_count, max_profit_trade,
                max_loss_trade, profit_factor, order_group_count, max_level_reached,
                tp_trigger_count, sl_trigger_count, timeout_refresh_count, supplement_count,
                total_runtime_minutes, paused_time_minutes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            metrics.get('avg_execution_time', 0),
            metrics.get('min_execution_time', 0),
            metrics.get('max_execution_time', 0),
            metrics.get('total_execution_time', 0),
            metrics.get('execution_count', 0),
            metrics.get('avg_holding_time', 0),
            metrics.get('min_holding_time', 0),
            metrics.get('max_holding_time', 0),
            metrics.get('total_holding_time', 0),
            metrics.get('holding_count', 0),
            metrics.get('max_profit_trade', 0),
            metrics.get('max_loss_trade', 0),
            metrics.get('profit_factor', 0),
            metrics.get('order_group_count', 0),
            metrics.get('max_level_reached', 0),
            metrics.get('tp_trigger_count', 0),
            metrics.get('sl_trigger_count', 0),
            metrics.get('timeout_refresh_count', 0),
            metrics.get('supplement_count', 0),
            metrics.get('total_runtime_minutes', 0),
            metrics.get('paused_time_minutes', 0),
            datetime.now().isoformat()
        ))
        conn.commit()
        return True
    finally:
        conn.close()
```

### Step 3: Trader 中集成

在 `BinanceLiveTrader` 类中添加：

```python
class BinanceLiveTrader:
    def __init__(self, ...):
        # ... 现有初始化 ...

        # 统计指标
        self._metrics = {
            'execution_times': [],
            'holding_times': [],
            'profits': [],
            'tp_trigger_count': 0,
            'sl_trigger_count': 0,
            'timeout_refresh_count': 0,
            'supplement_count': 0,
            'start_time': None,
            'pause_start_time': None,
            'total_paused_minutes': 0,
        }

    def _record_execution_time(self, order):
        """记录执行时间"""
        if order.created_at and order.filled_at:
            created = datetime.strptime(order.created_at, '%Y-%m-%d %H:%M:%S')
            filled = datetime.strptime(order.filled_at, '%Y-%m-%d %H:%M:%S')
            execution_time = (filled - created).total_seconds() / 60
            self._metrics['execution_times'].append(execution_time)

    def _record_holding_time(self, holding_seconds: int):
        """记录持仓时间"""
        self._metrics['holding_times'].append(holding_seconds / 60)

    def _record_profit(self, profit: float, reason: str):
        """记录盈亏"""
        self._metrics['profits'].append(profit)
        if reason == 'take_profit':
            self._metrics['tp_trigger_count'] += 1
        elif reason == 'stop_loss':
            self._metrics['sl_trigger_count'] += 1

    def _get_metrics_summary(self) -> Dict:
        """获取统计摘要"""
        exec_times = self._metrics['execution_times']
        hold_times = self._metrics['holding_times']
        profits = self._metrics['profits']

        return {
            'avg_execution_time': sum(exec_times) / len(exec_times) if exec_times else 0,
            'min_execution_time': min(exec_times) if exec_times else 0,
            'max_execution_time': max(exec_times) if exec_times else 0,
            'total_execution_time': sum(exec_times),
            'execution_count': len(exec_times),

            'avg_holding_time': sum(hold_times) / len(hold_times) if hold_times else 0,
            'min_holding_time': min(hold_times) if hold_times else 0,
            'max_holding_time': max(hold_times) if hold_times else 0,
            'total_holding_time': sum(hold_times),
            'holding_count': len(hold_times),

            'max_profit_trade': max(profits) if profits else 0,
            'max_loss_trade': min(profits) if profits else 0,
            'profit_factor': (
                abs(sum(p for p in profits if p > 0) / sum(p for p in profits if p < 0))
                if any(p < 0 for p in profits) and any(p > 0 for p in profits) else 0
            ),

            'order_group_count': self.chain_state.group_id if self.chain_state else 0,
            'max_level_reached': max(
                (o.level for o in self.chain_state.orders if o.state in ['filled', 'closed']),
                default=0
            ) if self.chain_state else 0,

            'tp_trigger_count': self._metrics['tp_trigger_count'],
            'sl_trigger_count': self._metrics['sl_trigger_count'],
            'timeout_refresh_count': self._metrics['timeout_refresh_count'],
            'supplement_count': self._metrics['supplement_count'],

            'total_runtime_minutes': (
                (datetime.now() - self._metrics['start_time']).total_seconds() / 60
                if self._metrics['start_time'] else 0
            ),
            'paused_time_minutes': self._metrics['total_paused_minutes'],
        }

    def _save_metrics(self):
        """保存统计指标到数据库"""
        if self.session_id:
            metrics = self._get_metrics_summary()
            self.db.save_session_metrics(self.session_id, metrics)
```

---

## Web API 扩展

### 新增接口

```
GET /api/live-sessions/<session_id>/metrics
```

**响应示例**：

```json
{
    "success": true,
    "data": {
        "session_id": 123,
        "avg_execution_time": 15.5,
        "min_execution_time": 2.0,
        "max_execution_time": 45.0,
        "avg_holding_time": 120.0,
        "min_holding_time": 30.0,
        "max_holding_time": 360.0,
        "max_profit_trade": 150.0,
        "max_loss_trade": -80.0,
        "profit_factor": 2.5,
        "order_group_count": 5,
        "max_level_reached": 3,
        "tp_trigger_count": 8,
        "sl_trigger_count": 2,
        "timeout_refresh_count": 3,
        "total_runtime_minutes": 1440.0,
        "paused_time_minutes": 60.0
    }
}
```

---

## 前端展示建议

### 会话详情页新增指标展示

```
┌─────────────────────────────────────────────────────────────────┐
│                      订单执行统计                                │
├─────────────────────────────────────────────────────────────────┤
│  平均挂单时间: 15.5 分钟                                         │
│  最短成交: 2.0 分钟 | 最长成交: 45.0 分钟                        │
├─────────────────────────────────────────────────────────────────┤
│                      持仓时间统计                                │
├─────────────────────────────────────────────────────────────────┤
│  平均持仓: 2.0 小时                                              │
│  最短持仓: 30 分钟 | 最长持仓: 6.0 小时                          │
├─────────────────────────────────────────────────────────────────┤
│                      盈亏分布统计                                │
├─────────────────────────────────────────────────────────────────┤
│  单笔最大盈利: +150 USDT                                         │
│  单笔最大亏损: -80 USDT                                          │
│  盈亏比: 2.5                                                     │
├─────────────────────────────────────────────────────────────────┤
│                      交易统计                                    │
├─────────────────────────────────────────────────────────────────┤
│  止盈触发: 8 次 | 止损触发: 2 次                                  │
│  超时重挂: 3 次 | 补单次数: 1 次                                  │
│  最大层级: 3 | 完成轮次: 5                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 实现优先级

| 优先级 | 指标 | 实现难度 | 价值 |
|--------|------|---------|------|
| P0 | avg_execution_time | 低 | 高 - 评估挂单策略效果 |
| P0 | avg_holding_time | 低 | 高 - 评估持仓策略效果 |
| P0 | max_profit_trade / max_loss_trade | 低 | 高 - 风险评估 |
| P1 | profit_factor | 低 | 中 - 盈亏比分析 |
| P1 | tp_trigger_count / sl_trigger_count | 低 | 中 - 止盈止损效果 |
| P2 | timeout_refresh_count | 低 | 低 - 超时监控 |
| P2 | supplement_count | 低 | 低 - 补单监控 |

---

*文档版本: 1.0*
*创建日期: 2026-03-31*
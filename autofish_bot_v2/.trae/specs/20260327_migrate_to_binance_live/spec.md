# 链式挂单和回测逻辑移植到 binance_live

## 背景
binance_live.py 是实盘交易模块，目前实现了基本的链式挂单策略，但缺少回测程序（binance_backtest.py）中的高级功能，如资金池管理、入场资金策略、市场状态检测等。同时，实盘交易目前还未做数据库存储，需要补充设计。

## 变更内容
- 移植资金池管理逻辑（CapitalPool）
- 移植入场资金策略（EntryCapitalStrategy）
- 移植市场状态检测增强功能
- 移植 A1 超时重挂机制
- 移植行情状态变化处理逻辑
- 移植盈亏统计和资金历史记录
- **新增实盘交易数据库存储设计（新建专用数据表）**
- **新增实盘信息 Web 展示**
- 输出 binance_live 说明文档

## 影响范围
- 涉及代码: binance_live.py, autofish_core.py, database/test_results_db.py, test_manager.py
- 新增文档: docs/binance_live_guide.md

---

## 一、数据存储表设计

### 1.1 表设计原则

**复用 vs 新建分析：**

| 方面 | 复用现有表 | 新建专用表 |
|------|-----------|-----------|
| 数据隔离 | ❌ 回测与实盘混合 | ✅ 完全隔离 |
| 查询性能 | ❌ 需要额外过滤 | ✅ 独立查询 |
| 字段扩展 | ❌ 需要兼容回测 | ✅ 可自由扩展 |
| 维护成本 | ✅ 表结构统一 | ⚠️ 需要维护多套 |
| 数据迁移 | ✅ 无需迁移 | ⚠️ 需要新建表 |

**结论：采用新建专用数据表方案**

### 1.2 表结构详细设计

#### 1.2.1 live_sessions 表 - 实盘会话

```sql
CREATE TABLE IF NOT EXISTS live_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                          -- 会话名称（如：BTCUSDT_20260327_001）
    symbol TEXT NOT NULL,                        -- 交易对
    config TEXT NOT NULL,                        -- JSON 格式的完整配置
    status TEXT DEFAULT 'running',               -- running, stopped, error
    started_at TEXT NOT NULL,                    -- 启动时间
    stopped_at TEXT,                             -- 停止时间
    error_message TEXT,                          -- 错误信息
    total_trades INTEGER DEFAULT 0,              -- 总交易次数
    win_trades INTEGER DEFAULT 0,                -- 盈利次数
    loss_trades INTEGER DEFAULT 0,               -- 亏损次数
    total_profit REAL DEFAULT 0,                 -- 总盈利
    total_loss REAL DEFAULT 0,                   -- 总亏损
    initial_capital REAL NOT NULL,               -- 初始资金
    final_capital REAL,                          -- 最终资金
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_live_sessions_symbol ON live_sessions(symbol);
CREATE INDEX IF NOT EXISTS idx_live_sessions_status ON live_sessions(status);
CREATE INDEX IF NOT EXISTS idx_live_sessions_started_at ON live_sessions(started_at);
```

**字段说明：**

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| id | INTEGER | 主键，自增 | 1, 2, 3 |
| name | TEXT | 会话名称，格式：{symbol}_{date}_{seq} | BTCUSDT_20260327_001 |
| symbol | TEXT | 交易对 | BTCUSDT |
| config | TEXT | JSON 配置，包含所有策略参数 | {"leverage": 10, "grid_spacing": 0.01, ...} |
| status | TEXT | 会话状态 | running, stopped, error |
| started_at | TEXT | 启动时间 | 2026-03-27 10:00:00 |
| stopped_at | TEXT | 停止时间 | 2026-03-27 18:00:00 |
| initial_capital | REAL | 初始资金 | 10000.0 |
| final_capital | REAL | 最终资金 | 10500.0 |

#### 1.2.2 live_orders 表 - 实盘订单

```sql
CREATE TABLE IF NOT EXISTS live_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,                 -- 关联会话 ID
    level INTEGER NOT NULL,                      -- 订单层级 (1-4)
    binance_order_id INTEGER,                    -- Binance 入场单 ID
    entry_price REAL NOT NULL,                   -- 入场价格
    take_profit_price REAL NOT NULL,             -- 止盈价格
    stop_loss_price REAL NOT NULL,               -- 止损价格
    quantity REAL NOT NULL,                      -- 数量
    stake_amount REAL NOT NULL,                  -- 金额
    state TEXT DEFAULT 'pending',                -- pending, filled, closed, cancelled
    entry_capital REAL,                          -- 入场资金
    entry_total_capital REAL,                    -- 入场总资金
    tp_order_id INTEGER,                         -- 止盈单 ID（Algo）
    sl_order_id INTEGER,                         -- 止损单 ID（Algo）
    group_id INTEGER DEFAULT 0,                  -- 轮次 ID
    created_at TEXT,                             -- 创建时间
    filled_at TEXT,                              -- 成交时间
    closed_at TEXT,                              -- 平仓时间
    close_price REAL,                            -- 平仓价格
    close_reason TEXT,                           -- 平仓原因
    profit REAL,                                 -- 盈亏
    tp_supplemented INTEGER DEFAULT 0,           -- 止盈单是否补单
    sl_supplemented INTEGER DEFAULT 0,           -- 止损单是否补单
    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_live_orders_session ON live_orders(session_id);
CREATE INDEX IF NOT EXISTS idx_live_orders_level ON live_orders(level);
CREATE INDEX IF NOT EXISTS idx_live_orders_state ON live_orders(state);
CREATE INDEX IF NOT EXISTS idx_live_orders_group_id ON live_orders(group_id);
CREATE INDEX IF NOT EXISTS idx_live_orders_created_at ON live_orders(created_at);
```

**字段说明：**

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| session_id | INTEGER | 关联的会话 ID | 1 |
| level | INTEGER | 订单层级 | 1, 2, 3, 4 |
| binance_order_id | INTEGER | Binance 入场单 ID | 12345678 |
| entry_price | REAL | 入场价格 | 85000.00 |
| take_profit_price | REAL | 止盈价格 | 85850.00 |
| stop_loss_price | REAL | 止损价格 | 78200.00 |
| quantity | REAL | 数量 | 0.014118 |
| stake_amount | REAL | 金额 | 120.0 |
| state | TEXT | 订单状态 | pending, filled, closed |
| entry_capital | REAL | 入场资金（策略计算） | 120.0 |
| entry_total_capital | REAL | 入场总资金 | 10000.0 |
| tp_order_id | INTEGER | 止盈条件单 ID | 87654321 |
| sl_order_id | INTEGER | 止损条件单 ID | 87654322 |
| group_id | INTEGER | 轮次 ID | 1, 2, 3 |
| close_reason | TEXT | 平仓原因 | take_profit, stop_loss |

#### 1.2.3 live_capital_history 表 - 实盘资金历史

```sql
CREATE TABLE IF NOT EXISTS live_capital_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,                     -- 时间戳
    old_capital REAL NOT NULL,                   -- 变化前资金
    new_capital REAL NOT NULL,                   -- 变化后资金
    total_capital REAL NOT NULL,                 -- 总资金
    trading_capital REAL NOT NULL,               -- 交易资金
    profit_pool REAL DEFAULT 0,                  -- 利润池
    profit REAL DEFAULT 0,                       -- 本次盈亏
    event_type TEXT NOT NULL,                    -- 事件类型
    order_id INTEGER,                            -- 关联订单 ID
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_live_capital_history_session ON live_capital_history(session_id);
CREATE INDEX IF NOT EXISTS idx_live_capital_history_timestamp ON live_capital_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_live_capital_history_event_type ON live_capital_history(event_type);
```

**事件类型（event_type）：**

| 类型 | 说明 |
|------|------|
| trade | 交易盈亏 |
| withdrawal | 提现 |
| liquidation | 爆仓恢复 |
| init | 初始化 |
| reset | 重置 |

#### 1.2.4 live_capital_statistics 表 - 实盘资金统计

```sql
CREATE TABLE IF NOT EXISTS live_capital_statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL UNIQUE,
    strategy TEXT DEFAULT 'guding',              -- 资金策略
    entry_mode TEXT DEFAULT 'compound',          -- 入场资金模式
    initial_capital REAL NOT NULL,               -- 初始资金
    trading_capital REAL NOT NULL,               -- 交易资金
    profit_pool REAL DEFAULT 0,                  -- 利润池
    final_capital REAL NOT NULL,                 -- 最终资金
    total_return REAL DEFAULT 0,                 -- 总收益率
    total_profit REAL DEFAULT 0,                 -- 总盈利
    total_loss REAL DEFAULT 0,                   -- 总亏损
    max_capital REAL NOT NULL,                   -- 最大资金
    max_drawdown REAL DEFAULT 0,                 -- 最大回撤
    withdrawal_threshold REAL DEFAULT 2.0,       -- 提现阈值
    withdrawal_retain REAL DEFAULT 1.5,          -- 提现保留
    liquidation_threshold REAL DEFAULT 0.2,      -- 爆仓阈值
    withdrawal_count INTEGER DEFAULT 0,          -- 提现次数
    total_withdrawal REAL DEFAULT 0,             -- 总提现金额
    liquidation_count INTEGER DEFAULT 0,         -- 爆仓恢复次数
    total_trades INTEGER DEFAULT 0,              -- 总交易次数
    profit_trades INTEGER DEFAULT 0,             -- 盈利次数
    loss_trades INTEGER DEFAULT 0,               -- 亏损次数
    avg_profit REAL DEFAULT 0,                   -- 平均盈利
    avg_loss REAL DEFAULT 0,                     -- 平均亏损
    win_rate REAL DEFAULT 0,                     -- 胜率
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_live_capital_statistics_session ON live_capital_statistics(session_id);
```

### 1.3 数据库操作类设计

在 `database/test_results_db.py` 中添加 `LiveTradingDB` 类：

```python
class LiveTradingDB:
    """实盘交易数据库管理类"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            base_dir = Path(__file__).parent
            db_path = base_dir / "live_trading.db"
        self.db_path = str(db_path)
        self._ensure_tables()
    
    # ==================== 会话管理 ====================
    
    def create_session(self, session: LiveSession) -> int:
        """创建实盘会话"""
        pass
    
    def get_session(self, session_id: int) -> Optional[Dict]:
        """获取会话详情"""
        pass
    
    def list_sessions(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取会话列表"""
        pass
    
    def update_session(self, session_id: int, updates: Dict) -> bool:
        """更新会话"""
        pass
    
    def stop_session(self, session_id: int, error_message: str = None) -> bool:
        """停止会话"""
        pass
    
    # ==================== 订单管理 ====================
    
    def create_order(self, order: LiveOrder) -> int:
        """创建订单记录"""
        pass
    
    def get_order(self, order_id: int) -> Optional[Dict]:
        """获取订单详情"""
        pass
    
    def get_orders_by_session(self, session_id: int, state: str = None) -> List[Dict]:
        """获取会话的所有订单"""
        pass
    
    def update_order(self, order_id: int, updates: Dict) -> bool:
        """更新订单"""
        pass
    
    def update_order_state(self, order_id: int, state: str, **kwargs) -> bool:
        """更新订单状态"""
        pass
    
    # ==================== 资金历史 ====================
    
    def save_capital_history(self, session_id: int, history: Dict) -> int:
        """保存资金历史"""
        pass
    
    def get_capital_history(self, session_id: int, limit: int = 1000, offset: int = 0) -> List[Dict]:
        """获取资金历史"""
        pass
    
    # ==================== 资金统计 ====================
    
    def save_capital_statistics(self, session_id: int, stats: Dict) -> bool:
        """保存资金统计"""
        pass
    
    def get_capital_statistics(self, session_id: int) -> Optional[Dict]:
        """获取资金统计"""
        pass
```

---

## 二、实盘信息 Web 展示设计

### 2.1 API 接口设计

在 `test_manager.py` 中添加实盘 API 路由：

#### 2.1.1 会话管理接口

| 接口 | 方法 | 功能 | 参数 |
|------|------|------|------|
| `/api/live/sessions` | GET | 获取会话列表 | status, symbol, limit, offset |
| `/api/live/sessions` | POST | 创建会话 | name, symbol, config |
| `/api/live/sessions/<id>` | GET | 获取会话详情 | - |
| `/api/live/sessions/<id>` | DELETE | 删除会话 | - |
| `/api/live/sessions/<id>/stop` | POST | 停止会话 | - |

#### 2.1.2 订单查询接口

| 接口 | 方法 | 功能 | 参数 |
|------|------|------|------|
| `/api/live/sessions/<id>/orders` | GET | 获取订单列表 | state, level, group_id |
| `/api/live/sessions/<id>/orders/<order_id>` | GET | 获取订单详情 | - |

#### 2.1.3 资金查询接口

| 接口 | 方法 | 功能 | 参数 |
|------|------|------|------|
| `/api/live/sessions/<id>/capital` | GET | 获取资金历史 | limit, offset |
| `/api/live/sessions/<id>/statistics` | GET | 获取资金统计 | - |

#### 2.1.4 实时状态接口

| 接口 | 方法 | 功能 | 参数 |
|------|------|------|------|
| `/api/live/current` | GET | 获取当前运行状态 | - |
| `/api/live/current/orders` | GET | 获取当前订单状态 | - |
| `/api/live/current/pnl` | GET | 获取当前盈亏 | - |

### 2.2 API 实现代码

```python
# test_manager.py 中添加

from database.test_results_db import LiveTradingDB

live_db = LiveTradingDB()

# ==================== 实盘会话 API ====================

@app.route('/api/live/sessions', methods=['GET'])
def get_live_sessions():
    """获取实盘会话列表"""
    status = request.args.get('status')
    symbol = request.args.get('symbol')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    filters = {}
    if status:
        filters['status'] = status
    if symbol:
        filters['symbol'] = symbol
    
    sessions = live_db.list_sessions(filters, limit, offset)
    return jsonify({
        'success': True,
        'data': sessions,
        'count': len(sessions)
    })

@app.route('/api/live/sessions', methods=['POST'])
def create_live_session():
    """创建实盘会话"""
    data = request.get_json()
    
    session = LiveSession(
        name=data.get('name'),
        symbol=data.get('symbol'),
        config=json.dumps(data.get('config', {})),
        started_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        initial_capital=data.get('config', {}).get('initial_capital', 0),
        created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        updated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )
    
    session_id = live_db.create_session(session)
    return jsonify({
        'success': True,
        'data': {'session_id': session_id}
    })

@app.route('/api/live/sessions/<int:session_id>', methods=['GET'])
def get_live_session(session_id):
    """获取实盘会话详情"""
    session = live_db.get_session(session_id)
    if not session:
        return jsonify({'success': False, 'error': 'Session not found'}), 404
    
    # 获取关联的订单和统计
    orders = live_db.get_orders_by_session(session_id)
    statistics = live_db.get_capital_statistics(session_id)
    
    return jsonify({
        'success': True,
        'data': {
            'session': session,
            'orders': orders,
            'statistics': statistics
        }
    })

@app.route('/api/live/sessions/<int:session_id>/orders', methods=['GET'])
def get_live_orders(session_id):
    """获取实盘订单列表"""
    state = request.args.get('state')
    level = request.args.get('level', type=int)
    group_id = request.args.get('group_id', type=int)
    
    orders = live_db.get_orders_by_session(session_id, state=state)
    
    # 过滤
    if level:
        orders = [o for o in orders if o['level'] == level]
    if group_id:
        orders = [o for o in orders if o['group_id'] == group_id]
    
    return jsonify({
        'success': True,
        'data': orders,
        'count': len(orders)
    })

@app.route('/api/live/sessions/<int:session_id>/capital', methods=['GET'])
def get_live_capital_history(session_id):
    """获取实盘资金历史"""
    limit = request.args.get('limit', 200, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    history = live_db.get_capital_history(session_id, limit, offset)
    return jsonify({
        'success': True,
        'data': history,
        'count': len(history)
    })

@app.route('/api/live/sessions/<int:session_id>/statistics', methods=['GET'])
def get_live_statistics(session_id):
    """获取实盘资金统计"""
    statistics = live_db.get_capital_statistics(session_id)
    if not statistics:
        return jsonify({'success': False, 'error': 'Statistics not found'}), 404
    
    return jsonify({
        'success': True,
        'data': statistics
    })
```

### 2.3 前端页面设计

#### 2.3.1 实盘会话列表页面

路径：`web/live/index.html`

功能：
- 显示所有实盘会话列表
- 支持按状态、交易对筛选
- 显示每个会话的基本统计信息
- 点击进入会话详情

#### 2.3.2 实盘会话详情页面

路径：`web/live/session.html`

功能：
- 显示会话配置信息
- 显示订单列表（按轮次分组）
- 显示资金历史图表
- 显示盈亏统计

---

## 三、binance_live 代码修改点

### 3.1 导入模块修改

**文件：** `binance_live.py`

**位置：** 文件顶部导入区域（约第 40 行）

**修改内容：**
```python
# 现有导入
from market_status_detector import MarketStatusDetector, MarketStatus, StatusResult

# 新增导入
from autofish_core import (
    Autofish_ChainState,
    Autofish_Order,
    CapitalPoolFactory,
    EntryCapitalStrategyFactory,
    EntryPriceStrategyFactory,
    normalize_weights,
)
from database.test_results_db import LiveTradingDB, LiveSession, LiveOrder
```

### 3.2 BinanceLiveTrader 类初始化修改

**文件：** `binance_live.py`

**位置：** `BinanceLiveTrader.__init__` 方法（约第 1614 行）

**修改内容：**
```python
def __init__(self, config: Dict[str, Any], testnet: bool = True):
    self.config = config
    self.testnet = testnet
    
    # ===== 新增：初始化数据库 =====
    self.live_db = LiveTradingDB()
    self.session_id: Optional[int] = None
    
    # ===== 新增：初始化资金池 =====
    capital_config = config.get('capital', {'strategy': 'guding'})
    self.initial_capital = Decimal(str(config.get('total_amount_quote', 10000)))
    self.stop_loss = Decimal(str(config.get('stop_loss', '0.08')))
    self.leverage = int(config.get('leverage', 10))
    
    self.capital_pool = CapitalPoolFactory.create(
        initial_capital=self.initial_capital,
        capital_config=capital_config,
        stop_loss=float(self.stop_loss),
        leverage=self.leverage
    )
    
    # ===== 新增：初始化入场资金策略 =====
    entry_mode = capital_config.get('entry_mode', 'compound')
    self.capital_strategy = EntryCapitalStrategyFactory.create_strategy(entry_mode)
    
    # ===== 新增：初始化入场价格策略 =====
    entry_price_config = config.get('entry_price_strategy', {'strategy': 'fixed'})
    entry_price_strategy_name = entry_price_config.get('strategy', 'fixed')
    entry_price_params = entry_price_config.get(entry_price_strategy_name, {})
    self.entry_price_strategy = EntryPriceStrategyFactory.create(
        entry_price_strategy_name, **entry_price_params
    )
    
    # ... 现有代码 ...
```

### 3.3 _create_order 方法修改

**文件：** `binance_live.py`

**位置：** `_create_order` 方法（需要新增）

**修改内容：**
```python
async def _create_order(self, level: int, base_price: Decimal, klines: List[Dict] = None, 
                        group_id: int = None) -> Any:
    """创建订单
    
    参数:
        level: 层级
        base_price: 基准价格
        klines: K 线数据（用于入场价格策略）
        group_id: 轮次 ID
    """
    from autofish_core import Autofish_Order, Autofish_OrderCalculator
    
    grid_spacing = self.config.get('grid_spacing', Decimal('0.01'))
    exit_profit = self.config.get('exit_profit', Decimal('0.01'))
    stop_loss = self.config.get('stop_loss', Decimal('0.08'))
    
    # ===== 使用入场资金策略计算资金 =====
    total_amount = self.capital_strategy.calculate_entry_capital(
        self.capital_pool, level, self.chain_state
    )
    
    # ===== 使用入场价格策略计算入场价 =====
    if level == 1:
        entry_price = self.entry_price_strategy.calculate_entry_price(
            current_price=base_price,
            level=level,
            grid_spacing=grid_spacing,
            klines=klines
        )
    else:
        entry_price = base_price * (Decimal('1') - grid_spacing * level)
    
    # 计算止盈止损价格
    take_profit_price = entry_price * (Decimal('1') + exit_profit)
    stop_loss_price = entry_price * (Decimal('1') - stop_loss)
    
    # 计算权重和数量
    weights = self._get_weights()
    weight = weights.get(level, Decimal('0.25'))
    stake_amount = total_amount * weight
    quantity = stake_amount / entry_price
    
    # 确定 group_id
    if group_id is None:
        if level == 1:
            actual_group_id = self.chain_state.group_id + 1
        else:
            actual_group_id = self.chain_state.group_id
    else:
        actual_group_id = group_id
    
    # 创建订单对象
    order = Autofish_Order(
        level=level,
        entry_price=entry_price,
        quantity=quantity,
        stake_amount=stake_amount,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
        state='pending',
        created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        group_id=actual_group_id,
    )
    
    # ===== 记录入场资金 =====
    order.entry_capital = self.capital_strategy.calculate_entry_capital(
        self.capital_pool, level, self.chain_state
    )
    order.entry_total_capital = self.capital_strategy.calculate_entry_total_capital(
        self.capital_pool, level, self.chain_state
    )
    
    logger.info(f"[创建订单] A{level}: entry={entry_price:.2f}, "
               f"tp={take_profit_price:.2f}, sl={stop_loss_price:.2f}, "
               f"stake={stake_amount:.2f} USDT, group_id={actual_group_id}")
    
    return order

def _get_weights(self) -> Dict[int, Decimal]:
    """获取归一化后的权重"""
    weights_list = [Decimal(str(w)) for w in self.config.get('weights', [])]
    if not weights_list:
        return {1: Decimal('0.25'), 2: Decimal('0.25'), 3: Decimal('0.25'), 4: Decimal('0.25')}
    
    max_entries = self.config.get('max_entries', 4)
    normalized_weights = normalize_weights(weights_list, max_entries)
    
    weights = {}
    for i, w in enumerate(normalized_weights):
        weights[i + 1] = w
    return weights
```

### 3.4 订单成交处理修改

**文件：** `binance_live.py`

**位置：** `_handle_order_filled` 方法（需要新增或修改现有逻辑）

**修改内容：**
```python
async def _handle_order_filled(self, order: Any, filled_price: Decimal, commission: Decimal = Decimal('0')) -> None:
    """处理订单成交
    
    参数:
        order: 订单对象
        filled_price: 成交价格
        commission: 手续费
    """
    order.state = 'filled'
    order.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # ===== 更新 chain_state.group_id =====
    if order.level == 1:
        old_group_id = self.chain_state.group_id
        self.chain_state.group_id = order.group_id
        logger.info(f"[新轮次开始] A1 成交: group_id 从 {old_group_id} 变更为 {order.group_id}")
    
    # ===== 记录入场资金 =====
    order.entry_capital = self.capital_strategy.calculate_entry_capital(
        self.capital_pool, order.level, self.chain_state
    )
    order.entry_total_capital = self.capital_strategy.calculate_entry_total_capital(
        self.capital_pool, order.level, self.chain_state
    )
    
    # ===== 保存到数据库 =====
    if self.session_id:
        self.live_db.update_order(order.id, {
            'state': 'filled',
            'filled_at': order.filled_at,
            'entry_capital': float(order.entry_capital),
            'entry_total_capital': float(order.entry_total_capital),
            'group_id': order.group_id,
        })
    
    # 发送通知
    notify_entry_filled(order, filled_price, commission, self.config)
    
    # 下止盈止损条件单
    await self._place_tp_sl_orders(order)
    
    # 下下一级入场单
    next_level = order.level + 1
    max_level = self.config.get('max_entries', 4)
    if next_level <= max_level:
        klines = await self._get_recent_klines()
        new_order = await self._create_order(next_level, order.entry_price, klines, 
                                             group_id=self.chain_state.group_id)
        self.chain_state.orders.append(new_order)
        await self._place_entry_order(new_order)
    
    self._save_state()
```

### 3.5 订单平仓处理修改

**文件：** `binance_live.py`

**位置：** `_handle_take_profit` 和 `_handle_stop_loss` 方法

**修改内容：**
```python
async def _handle_take_profit(self, order: Any, algo_data: Dict[str, Any]) -> None:
    """处理止盈"""
    logger.info(f"[止盈触发] A{order.level}")
    
    order.state = 'closed'
    order.close_reason = 'take_profit'
    order.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order.close_price = order.take_profit_price
    
    # ===== 计算盈亏 =====
    leverage = self.config.get('leverage', 10)
    profit = (order.take_profit_price - order.entry_price) * order.quantity * leverage
    order.profit = profit
    
    # ===== 更新资金池 =====
    self._update_capital_after_trade(profit)
    
    # ===== 更新统计 =====
    self.results['total_trades'] += 1
    self.results['win_trades'] += 1
    self.results['total_profit'] += profit
    
    # ===== 保存到数据库 =====
    if self.session_id:
        self.live_db.update_order(order.id, {
            'state': 'closed',
            'closed_at': order.closed_at,
            'close_price': float(order.close_price),
            'close_reason': 'take_profit',
            'profit': float(profit),
        })
        self._save_capital_history(order, profit, 'take_profit')
    
    # 取消止损单
    if order.sl_order_id:
        try:
            await self.client.cancel_algo_order(self.config.get('symbol'), order.sl_order_id)
        except Exception as e:
            logger.warning(f"[取消止损单] 失败: {e}")
    
    # 发送通知
    notify_take_profit(order, profit, self.config)
    
    # 重新下 A1
    await self._restart_after_close(order)
    
    self._save_state()

def _update_capital_after_trade(self, profit: Decimal) -> None:
    """交易后更新资金池
    
    参数:
        profit: 本次交易盈亏
    """
    result = self.capital_pool.process_trade_profit(profit, datetime.now())
    
    if result.get('withdrawal'):
        logger.info(f"[资金池] 触发提现: 提现金额={result.get('withdrawal_amount', 0):.2f}, "
                   f"保留资金={result.get('trading_capital', 0):.2f}")
        # 发送提现通知
        notify_warning(f"触发提现: {result.get('withdrawal_amount', 0):.2f} USDT", self.config)
    
    if result.get('liquidation'):
        logger.warning(f"[资金池] 触发爆仓恢复: 恢复资金={result.get('recovered_capital', 0):.2f}")
    
    # 记录资金池状态
    if hasattr(self.capital_pool, 'trading_capital'):
        total_capital = self.capital_pool.trading_capital + (
            self.capital_pool.profit_pool if hasattr(self.capital_pool, 'profit_pool') else Decimal('0')
        )
        logger.info(f"[资金池状态] 交易资金={self.capital_pool.trading_capital:.2f}, "
                   f"利润池={getattr(self.capital_pool, 'profit_pool', Decimal('0')):.2f}, "
                   f"总资金={total_capital:.2f}")
    
    # 更新轮次总资金
    new_total_capital = self.capital_pool.trading_capital + (
        self.capital_pool.profit_pool if hasattr(self.capital_pool, 'profit_pool') else Decimal('0')
    )
    self.chain_state.round_entry_total_capital = new_total_capital

def _save_capital_history(self, order: Any, profit: Decimal, event_type: str) -> None:
    """保存资金历史到数据库"""
    if not self.session_id:
        return
    
    total_capital = self.capital_pool.trading_capital + (
        self.capital_pool.profit_pool if hasattr(self.capital_pool, 'profit_pool') else Decimal('0')
    )
    
    history = {
        'session_id': self.session_id,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'old_capital': float(total_capital - profit),
        'new_capital': float(total_capital),
        'total_capital': float(total_capital),
        'trading_capital': float(self.capital_pool.trading_capital),
        'profit_pool': float(getattr(self.capital_pool, 'profit_pool', 0)),
        'profit': float(profit),
        'event_type': event_type,
        'order_id': order.id if hasattr(order, 'id') else None,
    }
    
    self.live_db.save_capital_history(self.session_id, history)
```

### 3.6 A1 超时重挂机制

**文件：** `binance_live.py`

**位置：** 主循环中（`run` 方法）

**修改内容：**
```python
async def _check_first_entry_timeout(self, current_price: Decimal) -> None:
    """检查第一笔入场订单是否超时
    
    参数:
        current_price: 当前价格
    """
    if self.a1_timeout_minutes <= 0:
        return
    
    if not self.chain_state:
        return
    
    now = datetime.now()
    
    # 获取 A1 挂单
    first_entry = None
    for order in self.chain_state.orders:
        if order.level == 1 and order.state == 'pending':
            first_entry = order
            break
    
    if not first_entry:
        return
    
    # 检查是否超时
    created_at = datetime.strptime(first_entry.created_at, '%Y-%m-%d %H:%M:%S')
    elapsed = (now - created_at).total_seconds() / 60
    
    if elapsed < self.a1_timeout_minutes:
        return
    
    logger.info(f"[A1 超时] A1 挂单已超过 {self.a1_timeout_minutes} 分钟未成交")
    print(f"\n[{now.strftime('%H:%M:%S')}] ⏰ A1 超时重挂")
    
    # 取消旧订单
    if first_entry.order_id:
        try:
            await self.client.cancel_order(self.config.get('symbol'), first_entry.order_id)
            logger.info(f"[取消订单] orderId={first_entry.order_id}")
        except Exception as e:
            logger.warning(f"[取消订单] 失败: {e}")
    
    # 从列表中移除
    self.chain_state.orders.remove(first_entry)
    
    # 创建新订单
    klines = await self._get_recent_klines()
    new_first_entry = await self._create_order(1, current_price, klines)
    self.chain_state.orders.append(new_first_entry)
    self.chain_state.base_price = current_price
    
    # 下单
    await self._place_entry_order(new_first_entry)
    
    # 发送通知
    notify_first_entry_timeout_refresh(first_entry, new_first_entry, current_price, 
                                       self.a1_timeout_minutes, self.config)
    
    self._save_state()
```

---

## 四、参数化封装方案

### 4.1 配置结构设计

实盘交易配置采用与回测相同的参数结构，便于统一管理和复用：

```json
{
    "symbol": "BTCUSDT",
    "total_amount_quote": 10000,
    "leverage": 10,
    "max_entries": 4,
    "grid_spacing": 0.01,
    "exit_profit": 0.01,
    "stop_loss": 0.08,
    "decay_factor": 0.5,
    "weights": [0.4, 0.3, 0.2, 0.1],
    "a1_timeout_minutes": 10,
    
    "capital": {
        "strategy": "jijin",
        "entry_mode": "compound",
        "withdrawal_threshold": 1.5,
        "withdrawal_retain": 1.2,
        "liquidation_threshold": 0.2
    },
    
    "entry_price_strategy": {
        "strategy": "atr",
        "atr": {
            "period": 14,
            "multiplier": 1.5,
            "min_spacing": 0.005,
            "max_spacing": 0.03
        }
    },
    
    "market_aware": {
        "algorithm": "dual_thrust",
        "trading_statuses": ["ranging"],
        "dual_thrust": {
            "n_days": 4,
            "k1": 0.4,
            "k2": 0.4,
            "k2_down_factor": 0.8,
            "check_interval": 60
        }
    }
}
```

### 4.2 配置参数说明

#### 4.2.1 基础参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| symbol | string | BTCUSDT | 交易对 |
| total_amount_quote | number | 10000 | 总资金（USDT） |
| leverage | number | 10 | 杠杆倍数 |
| max_entries | number | 4 | 最大层级 |
| grid_spacing | number | 0.01 | 网格间距（1%） |
| exit_profit | number | 0.01 | 止盈比例（1%） |
| stop_loss | number | 0.08 | 止损比例（8%） |
| decay_factor | number | 0.5 | 衰减因子 |
| weights | array | [0.4, 0.3, 0.2, 0.1] | 各层级权重 |
| a1_timeout_minutes | number | 10 | A1 超时时间（分钟） |

#### 4.2.2 资金池参数（capital）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| strategy | string | guding | 资金策略：guding（固定）、jijin（基金）、fuli（复利） |
| entry_mode | string | compound | 入场资金模式：fixed、compound、default |
| withdrawal_threshold | number | 2.0 | 提现阈值（利润池达到交易资金的倍数） |
| withdrawal_retain | number | 1.5 | 提现保留（提现后保留的交易资金倍数） |
| liquidation_threshold | number | 0.2 | 爆仓阈值（交易资金低于初始资金的比例） |

#### 4.2.3 入场价格策略参数（entry_price_strategy）

| 策略 | 参数 | 默认值 | 说明 |
|------|------|--------|------|
| fixed | - | - | 固定间距入场 |
| atr | period | 14 | ATR 周期 |
| atr | multiplier | 1.5 | ATR 倍数 |
| atr | min_spacing | 0.005 | 最小间距 |
| atr | max_spacing | 0.03 | 最大间距 |

#### 4.2.4 行情感知参数（market_aware）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| algorithm | string | dual_thrust | 行情判断算法 |
| trading_statuses | array | ["ranging"] | 允许交易的市场状态 |
| check_interval | number | 60 | 检测间隔（秒） |

**支持的算法：**
- `always_ranging`: 始终判断为震荡
- `dual_thrust`: Dual Thrust 算法
- `adx`: ADX 趋势强度算法
- `composite`: 复合算法

### 4.3 配置加载与验证

```python
class LiveConfig:
    """实盘配置管理类"""
    
    REQUIRED_FIELDS = ['symbol', 'total_amount_quote']
    
    DEFAULT_CONFIG = {
        'leverage': 10,
        'max_entries': 4,
        'grid_spacing': 0.01,
        'exit_profit': 0.01,
        'stop_loss': 0.08,
        'decay_factor': 0.5,
        'weights': [0.4, 0.3, 0.2, 0.1],
        'a1_timeout_minutes': 10,
        'capital': {'strategy': 'guding', 'entry_mode': 'compound'},
        'entry_price_strategy': {'strategy': 'fixed'},
        'market_aware': {'algorithm': 'dual_thrust', 'trading_statuses': ['ranging']},
    }
    
    def __init__(self, config_path: str = None, config_dict: Dict = None):
        if config_path:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        elif config_dict:
            self.config = config_dict
        else:
            raise ValueError("必须提供 config_path 或 config_dict")
        
        self._merge_defaults()
        self._validate()
    
    def _merge_defaults(self):
        """合并默认配置"""
        for key, value in self.DEFAULT_CONFIG.items():
            if key not in self.config:
                self.config[key] = value
            elif isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key not in self.config[key]:
                        self.config[key][sub_key] = sub_value
    
    def _validate(self):
        """验证配置"""
        for field in self.REQUIRED_FIELDS:
            if field not in self.config:
                raise ValueError(f"缺少必填字段: {field}")
        
        # 验证数值范围
        if self.config['leverage'] <= 0 or self.config['leverage'] > 125:
            raise ValueError("杠杆倍数必须在 1-125 之间")
        
        if self.config['grid_spacing'] <= 0 or self.config['grid_spacing'] > 0.1:
            raise ValueError("网格间距必须在 0-10% 之间")
        
        # 验证权重
        weights = self.config.get('weights', [])
        if weights:
            if len(weights) != self.config['max_entries']:
                raise ValueError(f"权重数量({len(weights)})必须等于最大层级({self.config['max_entries']})")
            if abs(sum(weights) - 1.0) > 0.01:
                raise ValueError("权重之和必须等于 1")
    
    def get(self, key: str, default=None):
        return self.config.get(key, default)
    
    def to_dict(self) -> Dict:
        return self.config.copy()
```

### 4.4 启动入口

```python
async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Binance 实盘交易")
    parser.add_argument("--config", type=str, required=True, help="配置文件路径")
    parser.add_argument("--testnet", action="store_true", help="使用测试网")
    
    args = parser.parse_args()
    
    # 加载配置
    config = LiveConfig(config_path=args.config)
    
    # 创建交易器
    trader = BinanceLiveTrader(config.to_dict(), testnet=args.testnet)
    
    # 运行
    await trader.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 五、修改需求
无

## 六、移除需求
无

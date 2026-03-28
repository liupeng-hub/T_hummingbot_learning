#!/usr/bin/env python3
"""
实盘交易数据库模块

提供实盘交易数据的数据库存储、查询功能。

数据库表结构（与回测对齐）：
1. live_cases - 实盘配置表（对应 test_cases）
2. live_sessions - 实盘会话表（对应 test_results）
3. live_orders - 实盘订单表（实盘特有，追踪订单生命周期）
4. live_trades - 交易记录表（对应 trade_details）
5. live_capital_statistics - 资金统计表（对应 capital_statistics）
6. live_capital_history - 资金历史表（对应 capital_history）
7. live_market_cases - 行情配置表（对应 market_visualizer_cases）
8. live_market_results - 行情结果表（对应 market_visualizer_details）
9. live_state_snapshots - 状态快照表（替代文件存储）
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from pathlib import Path
from decimal import Decimal


DB_FILE = Path(__file__).parent / "live_trading.db"


# ==================== 数据类定义 ====================

@dataclass
class LiveCase:
    """实盘配置数据类（对应 test_cases）"""
    name: str
    symbol: str
    testnet: int = 1
    id: Optional[int] = None
    description: str = ""
    amplitude: str = "{}"    # grid_spacing, exit_profit, stop_loss, decay_factor, weights, max_entries
    market: str = "{}"       # market_aware, algorithm, trading_statuses
    entry: str = "{}"        # entry_price_strategy
    timeout: str = "{}"      # a1_timeout_minutes
    capital: str = "{}"      # total_amount_quote, leverage, strategy, entry_mode, withdraw_threshold
    status: str = "draft"    # draft, active, stopped, archived
    created_at: str = ""
    updated_at: str = ""


@dataclass
class LiveSession:
    """实盘会话数据类（对应 test_results）"""
    case_id: int = 0         # 关联 live_cases（可为空，兼容旧数据）
    symbol: str = ""
    testnet: int = 1
    start_time: str = ""
    end_time: str = ""
    id: Optional[int] = None
    name: str = ""
    status: str = "running"  # running, stopped, error
    # 配置快照（运行时实际使用的配置）
    amplitude: str = "{}"
    market: str = "{}"
    entry: str = "{}"
    timeout: str = "{}"
    capital: str = "{}"
    # 统计结果
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0
    net_profit: float = 0.0
    initial_capital: float = 0.0
    final_capital: float = 0.0
    roi: float = 0.0
    # 其他
    error_message: str = ""
    created_at: str = ""


@dataclass
class LiveOrder:
    """实盘订单数据类（实盘特有）"""
    session_id: int
    order_id: int = 0  # Binance orderId
    level: int = 1
    group_id: int = 0
    state: str = "pending"  # pending, filled, closed
    entry_price: float = 0.0
    quantity: float = 0.0
    stake_amount: float = 0.0
    take_profit_price: float = 0.0
    stop_loss_price: float = 0.0
    tp_order_id: int = 0  # Binance algoId
    sl_order_id: int = 0  # Binance algoId
    created_at: str = ""
    filled_at: str = ""
    closed_at: str = ""
    close_reason: str = ""
    close_price: float = 0.0
    profit: float = 0.0
    entry_capital: float = 0.0
    entry_total_capital: float = 0.0
    tp_supplemented: int = 0  # 是否补单
    sl_supplemented: int = 0  # 是否补单
    id: Optional[int] = None


@dataclass
class LiveTrade:
    """实盘交易记录数据类（对应 trade_details）"""
    session_id: int
    order_id: int  # 关联 live_order.id
    trade_type: str = ""  # take_profit, stop_loss
    level: int = 1
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    profit: float = 0.0
    leverage: int = 10
    entry_time: str = ""
    exit_time: str = ""
    holding_duration_seconds: int = 0
    id: Optional[int] = None


@dataclass
class LiveCapitalStatistics:
    """资金统计数据类（对应 capital_statistics）"""
    session_id: int
    strategy: str = "guding"
    initial_capital: float = 0.0
    final_capital: float = 0.0
    trading_capital: float = 0.0
    profit_pool: float = 0.0
    total_return: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0
    max_capital: float = 0.0
    max_drawdown: float = 0.0
    withdrawal_threshold: float = 2.0
    withdrawal_retain: float = 1.5
    liquidation_threshold: float = 0.2
    withdrawal_count: int = 0
    total_withdrawal: float = 0.0
    liquidation_count: int = 0
    total_trades: int = 0
    profit_trades: int = 0
    loss_trades: int = 0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    id: Optional[int] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class LiveCapitalHistory:
    """资金历史数据类（对应 capital_history）"""
    session_id: int
    statistics_id: int = 0
    timestamp: str = ""
    old_capital: float = 0.0
    new_capital: float = 0.0
    total_capital: float = 0.0
    profit: float = 0.0
    event_type: str = ""  # trade_profit, withdrawal, liquidation_recovery
    related_order_id: int = 0
    id: Optional[int] = None
    created_at: str = ""


@dataclass
class LiveMarketCase:
    """行情配置数据类（对应 market_visualizer_cases）"""
    session_id: int
    symbol: str = ""
    algorithm: str = ""
    id: Optional[int] = None
    algorithm_config: str = "{}"
    check_interval: int = 60
    status: str = "active"
    created_at: str = ""


@dataclass
class LiveMarketResult:
    """行情结果数据类（对应 market_visualizer_details）"""
    case_id: int
    check_time: str = ""
    market_status: str = ""  # ranging, trending_up, trending_down, unknown
    confidence: float = 0.0
    reason: str = ""
    open_price: float = 0.0
    close_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    volume: float = 0.0
    id: Optional[int] = None
    created_at: str = ""


@dataclass
class LiveStateSnapshot:
    """状态快照数据类（替代文件存储）"""
    session_id: int
    snapshot_time: str = ""
    base_price: float = 0.0
    is_active: int = 1
    group_id: int = 0
    state_data: str = "{}"  # JSON: 完整状态数据（包含 orders、capital_pool、results 等）
    id: Optional[int] = None
    created_at: str = ""


# ==================== DbStateRepository ====================

class DbStateRepository:
    """数据库状态仓库（替代文件存储）"""

    def __init__(self, db: 'LiveTradingDB', session_id: int):
        self.db = db
        self.session_id = session_id

    def save(self, data: Dict) -> bool:
        """保存状态到数据库"""
        return self.db.save_state_snapshot(
            session_id=self.session_id,
            base_price=data.get('base_price', 0),
            is_active=data.get('is_active', 1),
            group_id=data.get('group_id', 0),
            state_data=data
        )

    def load(self) -> Optional[Dict]:
        """从数据库加载最新状态"""
        snapshot = self.db.get_latest_snapshot(self.session_id)
        if snapshot:
            state_data = snapshot.get('state_data', '{}')
            if isinstance(state_data, str):
                return json.loads(state_data)
            return state_data
        return None

    def exists(self) -> bool:
        """检查状态是否存在"""
        snapshot = self.db.get_latest_snapshot(self.session_id)
        return snapshot is not None

    def delete(self) -> bool:
        """删除状态"""
        return self.db.delete_snapshots(self.session_id)


# ==================== LiveTradingDB ====================

class LiveTradingDB:
    """实盘交易数据库类"""

    def __init__(self, db_path: str = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = DB_FILE

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # ==================== 表创建 ====================

        # 1. live_cases（实盘配置表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                symbol TEXT NOT NULL,
                testnet INTEGER DEFAULT 1,
                amplitude TEXT DEFAULT '{}',
                market TEXT DEFAULT '{}',
                entry TEXT DEFAULT '{}',
                timeout TEXT DEFAULT '{}',
                capital TEXT DEFAULT '{}',
                status TEXT DEFAULT 'draft',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. live_sessions（实盘会话表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER DEFAULT 0,
                name TEXT DEFAULT '',
                symbol TEXT NOT NULL,
                testnet INTEGER DEFAULT 1,
                start_time TEXT NOT NULL,
                end_time TEXT,
                status TEXT DEFAULT 'running',
                amplitude TEXT DEFAULT '{}',
                market TEXT DEFAULT '{}',
                entry TEXT DEFAULT '{}',
                timeout TEXT DEFAULT '{}',
                capital TEXT DEFAULT '{}',
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
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (case_id) REFERENCES live_cases(id)
            )
        """)

        # 3. live_orders（实盘订单表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                order_id INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                group_id INTEGER DEFAULT 0,
                state TEXT DEFAULT 'pending',
                entry_price REAL DEFAULT 0,
                quantity REAL DEFAULT 0,
                stake_amount REAL DEFAULT 0,
                take_profit_price REAL DEFAULT 0,
                stop_loss_price REAL DEFAULT 0,
                tp_order_id INTEGER DEFAULT 0,
                sl_order_id INTEGER DEFAULT 0,
                created_at TEXT,
                filled_at TEXT,
                closed_at TEXT,
                close_reason TEXT,
                close_price REAL DEFAULT 0,
                profit REAL DEFAULT 0,
                entry_capital REAL DEFAULT 0,
                entry_total_capital REAL DEFAULT 0,
                tp_supplemented INTEGER DEFAULT 0,
                sl_supplemented INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
            )
        """)

        # 4. live_trades（交易记录表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL,
                trade_type TEXT,
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
        """)

        # 5. live_capital_statistics（资金统计表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_capital_statistics (
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
        """)

        # 6. live_capital_history（资金历史表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_capital_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                statistics_id INTEGER,
                timestamp TEXT NOT NULL,
                old_capital REAL NOT NULL,
                new_capital REAL NOT NULL,
                total_capital REAL,
                profit REAL NOT NULL,
                event_type TEXT,
                related_order_id INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (statistics_id) REFERENCES live_capital_statistics(id) ON DELETE CASCADE
            )
        """)

        # 7. live_market_cases（行情配置表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_market_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                algorithm_config TEXT DEFAULT '{}',
                check_interval INTEGER DEFAULT 60,
                status TEXT DEFAULT 'active',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
            )
        """)

        # 8. live_market_results（行情结果表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_market_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                check_time TEXT NOT NULL,
                market_status TEXT NOT NULL,
                confidence REAL DEFAULT 0,
                reason TEXT DEFAULT '',
                open_price REAL DEFAULT 0,
                close_price REAL DEFAULT 0,
                high_price REAL DEFAULT 0,
                low_price REAL DEFAULT 0,
                volume REAL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (case_id) REFERENCES live_market_cases(id) ON DELETE CASCADE
            )
        """)

        # 9. live_state_snapshots（状态快照表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_state_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                snapshot_time TEXT NOT NULL,
                base_price REAL DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                group_id INTEGER DEFAULT 0,
                state_data TEXT DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
            )
        """)

        # ==================== 索引创建 ====================

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_cases_symbol ON live_cases(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_cases_status ON live_cases(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_sessions_case ON live_sessions(case_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_sessions_symbol ON live_sessions(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_sessions_status ON live_sessions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_orders_session ON live_orders(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_trades_session ON live_trades(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_capital_stats_session ON live_capital_statistics(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_capital_history_session ON live_capital_history(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_market_cases_session ON live_market_cases(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_market_results_case ON live_market_results(case_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_market_results_time ON live_market_results(check_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_snapshots_session ON live_state_snapshots(session_id)")

        conn.commit()
        conn.close()

        self._run_migrations()

    def _run_migrations(self):
        """运行数据库迁移"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # 检查 live_orders 是否有新字段
            cursor.execute("PRAGMA table_info(live_orders)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'tp_supplemented' not in columns:
                cursor.execute("ALTER TABLE live_orders ADD COLUMN tp_supplemented INTEGER DEFAULT 0")
                print("迁移: live_orders 添加 tp_supplemented 字段")

            if 'sl_supplemented' not in columns:
                cursor.execute("ALTER TABLE live_orders ADD COLUMN sl_supplemented INTEGER DEFAULT 0")
                print("迁移: live_orders 添加 sl_supplemented 字段")

            conn.commit()

            # 检查 capital_history 表名
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='capital_history'")
            if cursor.fetchone():
                # 检查是否有 statistics_id 字段
                cursor.execute("PRAGMA table_info(capital_history)")
                columns = [row[1] for row in cursor.fetchall()]

                if 'statistics_id' not in columns:
                    # 重命名表
                    cursor.execute("ALTER TABLE capital_history RENAME TO live_capital_history")
                    cursor.execute("ALTER TABLE live_capital_history ADD COLUMN statistics_id INTEGER DEFAULT 0")
                    cursor.execute("ALTER TABLE live_capital_history ADD COLUMN total_capital REAL DEFAULT 0")
                    cursor.execute("ALTER TABLE live_capital_history ADD COLUMN profit REAL DEFAULT 0")
                    print("迁移: capital_history 重命名为 live_capital_history 并添加新字段")
                    conn.commit()

        except Exception as e:
            print(f"数据库迁移失败: {e}")
        finally:
            conn.close()

    # ==================== 实盘配置 CRUD ====================

    def create_case(self, case: LiveCase) -> int:
        """创建实盘配置"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO live_cases
                (name, description, symbol, testnet, amplitude, market, entry, timeout, capital, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (case.name, case.description, case.symbol, case.testnet,
                  case.amplitude, case.market, case.entry, case.timeout, case.capital,
                  case.status, now, now))

            case_id = cursor.lastrowid
            conn.commit()
            return case_id
        except Exception as e:
            print(f"创建实盘配置失败: {e}")
            return 0
        finally:
            conn.close()

    def get_case(self, case_id: int) -> Optional[Dict]:
        """获取实盘配置"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM live_cases WHERE id = ?", (case_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_cases(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取实盘配置列表"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            sql = "SELECT * FROM live_cases WHERE 1=1"
            params = []

            if filters:
                if filters.get('symbol'):
                    sql += " AND symbol = ?"
                    params.append(filters['symbol'])
                if filters.get('status'):
                    sql += " AND status = ?"
                    params.append(filters['status'])
                if filters.get('testnet'):
                    sql += " AND testnet = ?"
                    params.append(filters['testnet'])

            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def update_case(self, case_id: int, updates: Dict) -> bool:
        """更新实盘配置"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            allowed_fields = ['name', 'description', 'symbol', 'testnet', 'amplitude',
                            'market', 'entry', 'timeout', 'capital', 'status']
            set_clauses = []
            params = []

            for field in allowed_fields:
                if field in updates:
                    set_clauses.append(f"{field} = ?")
                    params.append(updates[field])

            if not set_clauses:
                return True

            set_clauses.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(case_id)

            sql = f"UPDATE live_cases SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(sql, params)

            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"更新实盘配置失败: {e}")
            return False
        finally:
            conn.close()

    def update_case_status(self, case_id: int, status: str) -> bool:
        """更新实盘配置状态"""
        return self.update_case(case_id, {'status': status})

    def delete_case(self, case_id: int) -> bool:
        """删除实盘配置及其关联数据"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # 获取关联的 sessions
            cursor.execute("SELECT id FROM live_sessions WHERE case_id = ?", (case_id,))
            session_ids = [row['id'] for row in cursor.fetchall()]

            # 删除关联数据
            for session_id in session_ids:
                self._delete_session_data(conn, session_id)

            cursor.execute("DELETE FROM live_sessions WHERE case_id = ?", (case_id,))
            cursor.execute("DELETE FROM live_cases WHERE id = ?", (case_id,))

            conn.commit()
            return True
        except Exception as e:
            print(f"删除实盘配置失败: {e}")
            return False
        finally:
            conn.close()

    def copy_case(self, case_id: int) -> int:
        """复制实盘配置"""
        case = self.get_case(case_id)
        if not case:
            return 0

        new_case = LiveCase(
            name=f"{case['name']} (副本)",
            description=case['description'],
            symbol=case['symbol'],
            testnet=case['testnet'],
            amplitude=case['amplitude'],
            market=case['market'],
            entry=case['entry'],
            timeout=case['timeout'],
            capital=case['capital'],
            status='draft'
        )

        return self.create_case(new_case)

    # ==================== 实盘会话 CRUD ====================

    def create_session(self, session: LiveSession) -> int:
        """创建实盘会话

        注意：session.case_id 必须是有效的（存在于 live_cases 表）
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            now = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO live_sessions
                (case_id, name, symbol, testnet, start_time, status, amplitude, market, entry, timeout, capital,
                 initial_capital, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (session.case_id, session.name, session.symbol, session.testnet,
                  session.start_time, session.status, session.amplitude, session.market,
                  session.entry, session.timeout, session.capital, session.initial_capital, now))

            session_id = cursor.lastrowid

            # 更新 case 状态为 active
            if session.case_id and session.case_id > 0:
                cursor.execute("UPDATE live_cases SET status = 'active', updated_at = ? WHERE id = ?", (now, session.case_id))

            conn.commit()
            return session_id
        except Exception as e:
            print(f"创建实盘会话失败: {e}")
            return 0
        finally:
            conn.close()

    def get_session(self, session_id: int) -> Optional[Dict]:
        """获取会话信息"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT s.*, c.name as case_name,
                       cs.strategy as capital_strategy, cs.initial_capital as cs_initial_capital,
                       cs.final_capital as cs_final_capital, cs.trading_capital, cs.profit_pool,
                       cs.total_return, cs.total_profit as cs_total_profit, cs.total_loss as cs_total_loss,
                       cs.max_capital, cs.max_drawdown, cs.withdrawal_count, cs.liquidation_count
                FROM live_sessions s
                LEFT JOIN live_cases c ON s.case_id = c.id
                LEFT JOIN live_capital_statistics cs ON s.id = cs.session_id
                WHERE s.id = ?
            """, (session_id,))
            row = cursor.fetchone()
            if not row:
                return None

            result = dict(row)

            # 处理 capital_statistics
            if result.get('capital_strategy'):
                result['capital_statistics'] = {
                    'strategy': result.pop('capital_strategy'),
                    'initial_capital': result.pop('cs_initial_capital'),
                    'final_capital': result.pop('cs_final_capital'),
                    'trading_capital': result.pop('trading_capital'),
                    'profit_pool': result.pop('profit_pool'),
                    'total_return': result.pop('total_return'),
                    'total_profit': result.pop('cs_total_profit'),
                    'total_loss': result.pop('cs_total_loss'),
                    'max_capital': result.pop('max_capital'),
                    'max_drawdown': result.pop('max_drawdown'),
                    'withdrawal_count': result.pop('withdrawal_count'),
                    'liquidation_count': result.pop('liquidation_count'),
                }
            else:
                result['capital_statistics'] = None
                for key in ['capital_strategy', 'cs_initial_capital', 'cs_final_capital', 'trading_capital',
                           'profit_pool', 'total_return', 'cs_total_profit', 'cs_total_loss',
                           'max_capital', 'max_drawdown', 'withdrawal_count', 'liquidation_count']:
                    result.pop(key, None)

            return result
        finally:
            conn.close()

    def get_latest_session(self, symbol: str = None, status: str = None) -> Optional[Dict]:
        """获取最新会话"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            sql = "SELECT * FROM live_sessions WHERE 1=1"
            params = []

            if symbol:
                sql += " AND symbol = ?"
                params.append(symbol)
            if status:
                sql += " AND status = ?"
                params.append(status)

            sql += " ORDER BY start_time DESC LIMIT 1"

            cursor.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_sessions(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取会话列表"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            sql = """
                SELECT s.*, c.name as case_name
                FROM live_sessions s
                LEFT JOIN live_cases c ON s.case_id = c.id
                WHERE 1=1
            """
            params = []

            if filters:
                if filters.get('case_id'):
                    sql += " AND s.case_id = ?"
                    params.append(filters['case_id'])
                if filters.get('symbol'):
                    sql += " AND s.symbol = ?"
                    params.append(filters['symbol'])
                if filters.get('status'):
                    sql += " AND s.status = ?"
                    params.append(filters['status'])
                if filters.get('testnet'):
                    sql += " AND s.testnet = ?"
                    params.append(filters['testnet'])

            sql += " ORDER BY s.start_time DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def update_session(self, session_id: int, updates: Dict) -> bool:
        """更新会话"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            allowed_fields = ['end_time', 'status', 'total_trades', 'win_trades', 'loss_trades',
                            'win_rate', 'total_profit', 'total_loss', 'net_profit',
                            'final_capital', 'roi', 'error_message']
            set_clauses = []
            params = []

            for field in allowed_fields:
                if field in updates:
                    set_clauses.append(f"{field} = ?")
                    params.append(updates[field])

            if not set_clauses:
                return True

            params.append(session_id)
            sql = f"UPDATE live_sessions SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(sql, params)

            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"更新会话失败: {e}")
            return False
        finally:
            conn.close()

    def end_session(self, session_id: int, status: str = "stopped",
                   final_capital: float = None, error_message: str = "") -> bool:
        """结束会话"""
        updates = {
            'end_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': status,
        }
        if final_capital is not None:
            updates['final_capital'] = final_capital
        if error_message:
            updates['error_message'] = error_message

        return self.update_session(session_id, updates)

    def _delete_session_data(self, conn, session_id: int):
        """删除会话关联数据"""
        cursor = conn.cursor()

        # 获取 statistics_id
        cursor.execute("SELECT id FROM live_capital_statistics WHERE session_id = ?", (session_id,))
        stats_ids = [row['id'] for row in cursor.fetchall()]

        # 获取 market_case_id
        cursor.execute("SELECT id FROM live_market_cases WHERE session_id = ?", (session_id,))
        market_case_ids = [row['id'] for row in cursor.fetchall()]

        # 删除关联数据
        for stats_id in stats_ids:
            cursor.execute("DELETE FROM live_capital_history WHERE statistics_id = ?", (stats_id,))

        for market_case_id in market_case_ids:
            cursor.execute("DELETE FROM live_market_results WHERE case_id = ?", (market_case_id,))

        cursor.execute("DELETE FROM live_capital_history WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM live_capital_statistics WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM live_market_results WHERE case_id IN (SELECT id FROM live_market_cases WHERE session_id = ?)", (session_id,))
        cursor.execute("DELETE FROM live_market_cases WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM live_state_snapshots WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM live_trades WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM live_orders WHERE session_id = ?", (session_id,))

    def delete_session(self, session_id: int) -> bool:
        """删除会话及其关联数据"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            self._delete_session_data(conn, session_id)
            cursor.execute("DELETE FROM live_sessions WHERE id = ?", (session_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"删除会话失败: {e}")
            return False
        finally:
            conn.close()

    def delete_sessions_by_case(self, case_id: int) -> int:
        """删除配置关联的所有会话及其数据"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # 获取所有关联会话
            cursor.execute("SELECT id FROM live_sessions WHERE case_id = ?", (case_id,))
            session_ids = [row['id'] for row in cursor.fetchall()]

            # 删除每个会话的数据
            for session_id in session_ids:
                self._delete_session_data(conn, session_id)

            # 删除会话记录
            cursor.execute("DELETE FROM live_sessions WHERE case_id = ?", (case_id,))
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
        except Exception as e:
            print(f"删除配置关联会话失败: {e}")
            return 0
        finally:
            conn.close()

    def delete_session_data(self, session_id: int) -> bool:
        """删除会话关联数据（保留会话记录）"""
        conn = self._get_connection()

        try:
            self._delete_session_data(conn, session_id)
            conn.commit()
            return True
        except Exception as e:
            print(f"删除会话数据失败: {e}")
            return False
        finally:
            conn.close()

    # ==================== 订单 CRUD ====================

    def save_order(self, session_id: int, order: Any) -> int:
        """保存订单"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO live_orders (
                    session_id, order_id, level, group_id, state,
                    entry_price, quantity, stake_amount,
                    take_profit_price, stop_loss_price,
                    tp_order_id, sl_order_id,
                    created_at, filled_at, closed_at,
                    close_reason, close_price, profit,
                    entry_capital, entry_total_capital,
                    tp_supplemented, sl_supplemented
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                order.order_id or 0,
                order.level,
                order.group_id or 0,
                order.state,
                float(order.entry_price),
                float(order.quantity),
                float(order.stake_amount),
                float(order.take_profit_price),
                float(order.stop_loss_price),
                order.tp_order_id or 0,
                order.sl_order_id or 0,
                order.created_at or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                order.filled_at or "",
                order.closed_at or "",
                order.close_reason or "",
                float(order.close_price or 0),
                float(order.profit or 0),
                float(order.entry_capital or 0),
                float(order.entry_total_capital or 0),
                order.tp_supplemented or 0,
                order.sl_supplemented or 0
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def update_order(self, session_id: int, order: Any) -> bool:
        """更新订单状态"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE live_orders SET
                    order_id = ?,
                    state = ?,
                    tp_order_id = ?,
                    sl_order_id = ?,
                    filled_at = ?,
                    closed_at = ?,
                    close_reason = ?,
                    close_price = ?,
                    profit = ?,
                    entry_capital = ?,
                    entry_total_capital = ?,
                    tp_supplemented = ?,
                    sl_supplemented = ?
                WHERE session_id = ? AND level = ? AND group_id = ?
            """, (
                order.order_id or 0,
                order.state,
                order.tp_order_id or 0,
                order.sl_order_id or 0,
                order.filled_at or "",
                order.closed_at or "",
                order.close_reason or "",
                float(order.close_price or 0),
                float(order.profit or 0),
                float(order.entry_capital or 0),
                float(order.entry_total_capital or 0),
                order.tp_supplemented or 0,
                order.sl_supplemented or 0,
                session_id, order.level, order.group_id
            ))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_orders(self, session_id: int) -> List[Dict]:
        """获取会话的所有订单"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM live_orders WHERE session_id = ?
                ORDER BY created_at
            """, (session_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_order_by_level(self, session_id: int, level: int, group_id: int = 0) -> Optional[Dict]:
        """获取指定层级的订单"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM live_orders
                WHERE session_id = ? AND level = ? AND group_id = ?
                ORDER BY created_at DESC LIMIT 1
            """, (session_id, level, group_id))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ==================== 交易记录 CRUD ====================

    def save_trade(self, session_id: int, order: Any, trade_type: str,
                   leverage: int = 10, holding_duration: int = 0) -> int:
        """保存交易记录"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO live_trades (
                    session_id, order_id, trade_type, level,
                    entry_price, exit_price, quantity, profit,
                    leverage, entry_time, exit_time, holding_duration_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                order.order_id or 0,
                trade_type,
                order.level,
                float(order.entry_price),
                float(order.close_price),
                float(order.quantity),
                float(order.profit or 0),
                leverage,
                order.filled_at or "",
                order.closed_at or "",
                holding_duration
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_trades(self, session_id: int) -> List[Dict]:
        """获取会话的所有交易记录"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM live_trades WHERE session_id = ?
                ORDER BY exit_time
            """, (session_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ==================== 资金统计 CRUD ====================

    def save_statistics(self, session_id: int, stats: Dict) -> int:
        """保存资金统计"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO live_capital_statistics
                (session_id, strategy, initial_capital, final_capital, trading_capital, profit_pool,
                 total_return, total_profit, total_loss, max_capital, max_drawdown,
                 withdrawal_threshold, withdrawal_retain, liquidation_threshold,
                 withdrawal_count, total_withdrawal, liquidation_count,
                 total_trades, profit_trades, loss_trades, avg_profit, avg_loss, win_rate,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                stats.get('strategy', 'guding'),
                stats.get('initial_capital', 0),
                stats.get('final_capital', 0),
                stats.get('trading_capital', 0),
                stats.get('profit_pool', 0),
                stats.get('total_return', 0),
                stats.get('total_profit', 0),
                stats.get('total_loss', 0),
                stats.get('max_capital', 0),
                stats.get('max_drawdown', 0),
                stats.get('withdrawal_threshold', 2.0),
                stats.get('withdrawal_retain', 1.5),
                stats.get('liquidation_threshold', 0.2),
                stats.get('withdrawal_count', 0),
                stats.get('total_withdrawal', 0),
                stats.get('liquidation_count', 0),
                stats.get('total_trades', 0),
                stats.get('profit_trades', 0),
                stats.get('loss_trades', 0),
                stats.get('avg_profit', 0),
                stats.get('avg_loss', 0),
                stats.get('win_rate', 0),
                now, now
            ))

            stats_id = cursor.lastrowid
            conn.commit()
            return stats_id
        except Exception as e:
            print(f"保存资金统计失败: {e}")
            return 0
        finally:
            conn.close()

    def get_statistics(self, session_id: int) -> Optional[Dict]:
        """获取资金统计"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM live_capital_statistics WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ==================== 资金历史 CRUD ====================

    def save_capital_history(self, session_id: int, statistics_id: int = 0, history: Dict = None,
                             event_type: str = '', old_capital: float = 0, new_capital: float = 0,
                             profit_pool: float = 0, amount: float = 0, related_order_id: int = 0) -> int:
        """保存资金历史

        支持两种调用方式：
        1. 新方式: save_capital_history(session_id, statistics_id, history_dict)
        2. 兼容方式: save_capital_history(session_id, event_type, old_capital, new_capital, ...)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            now = datetime.now().isoformat()

            # 如果提供了 history 字典，使用新方式
            if history is not None:
                timestamp = history.get('timestamp', now)
                old_cap = history.get('old_capital', 0)
                new_cap = history.get('new_capital', 0)
                total_cap = history.get('total_capital', 0)
                profit = history.get('profit', 0)
                evt_type = history.get('event_type', '')
                related_id = history.get('related_order_id', 0)
            else:
                # 使用兼容方式的参数
                timestamp = now
                old_cap = old_capital
                new_cap = new_capital
                total_cap = profit_pool
                profit = amount
                evt_type = event_type
                related_id = related_order_id

            cursor.execute("""
                INSERT INTO live_capital_history
                (session_id, statistics_id, timestamp, old_capital, new_capital, total_capital,
                 profit, event_type, related_order_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                statistics_id,
                timestamp,
                old_cap,
                new_cap,
                total_cap,
                profit,
                evt_type,
                related_id,
                now
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_capital_history(self, session_id: int, limit: int = 1000) -> List[Dict]:
        """获取资金历史"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM live_capital_history WHERE session_id = ?
                ORDER BY timestamp ASC LIMIT ?
            """, (session_id, limit))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ==================== 行情记录 CRUD ====================

    def create_market_case(self, session_id: int, symbol: str, algorithm: str,
                          algorithm_config: Dict = None, check_interval: int = 60) -> int:
        """创建行情配置"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Decimal 类型转换
        def json_default(obj):
            if isinstance(obj, Decimal):
                return float(obj)
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        try:
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO live_market_cases
                (session_id, symbol, algorithm, algorithm_config, check_interval, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                symbol,
                algorithm,
                json.dumps(algorithm_config or {}, default=json_default),
                check_interval,
                'active',
                now
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def save_market_result(self, case_id: int, result: Dict) -> int:
        """保存行情结果"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO live_market_results
                (case_id, check_time, market_status, confidence, reason,
                 open_price, close_price, high_price, low_price, volume, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                case_id,
                result.get('check_time', now),
                result.get('market_status', 'unknown'),
                result.get('confidence', 0),
                result.get('reason', ''),
                result.get('open_price', 0),
                result.get('close_price', 0),
                result.get('high_price', 0),
                result.get('low_price', 0),
                result.get('volume', 0),
                now
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_market_results(self, case_id: int, limit: int = 1000) -> List[Dict]:
        """获取行情结果"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM live_market_results WHERE case_id = ?
                ORDER BY check_time DESC LIMIT ?
            """, (case_id, limit))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_market_statistics(self, case_id: int) -> Dict:
        """获取行情统计（动态计算）"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT market_status, COUNT(*) as count, AVG(confidence) as avg_confidence
                FROM live_market_results
                WHERE case_id = ?
                GROUP BY market_status
            """, (case_id,))
            rows = cursor.fetchall()

            stats = {
                'status_counts': {},
                'avg_confidence': {},
                'total_checks': 0
            }

            for row in rows:
                status = row['market_status']
                count = row['count']
                stats['status_counts'][status] = count
                stats['avg_confidence'][status] = row['avg_confidence']
                stats['total_checks'] += count

            return stats
        finally:
            conn.close()

    # ==================== 状态快照 CRUD ====================

    def save_state_snapshot(self, session_id: int, base_price: float, is_active: int,
                            group_id: int, state_data: Dict) -> bool:
        """保存状态快照"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            now = datetime.now().isoformat()

            # 序列化状态数据，处理 Decimal 类型
            def json_default(obj):
                if isinstance(obj, Decimal):
                    return float(obj)
                raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

            cursor.execute("""
                INSERT INTO live_state_snapshots
                (session_id, snapshot_time, base_price, is_active, group_id, state_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                now,
                float(base_price) if isinstance(base_price, Decimal) else base_price,
                is_active,
                group_id,
                json.dumps(state_data, default=json_default),
                now
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"保存状态快照失败: {e}")
            return False
        finally:
            conn.close()

    def get_latest_snapshot(self, session_id: int) -> Optional[Dict]:
        """获取最新状态快照"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM live_state_snapshots
                WHERE session_id = ?
                ORDER BY snapshot_time DESC LIMIT 1
            """, (session_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                if result.get('state_data'):
                    result['state_data'] = json.loads(result['state_data'])
                return result
            return None
        finally:
            conn.close()

    def delete_snapshots(self, session_id: int) -> bool:
        """删除所有快照"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM live_state_snapshots WHERE session_id = ?", (session_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    # ==================== 兼容旧接口 ====================

    def create_session_legacy(self, symbol: str, initial_capital: float, config: Dict, case_id: Optional[int] = None) -> int:
        """兼容旧接口创建会话

        参数:
            symbol: 交易对
            initial_capital: 初始资金
            config: 配置字典
            case_id: 关联的配置 ID（必须存在于 live_cases 表）
        """
        # 序列化配置，处理 Decimal 类型
        def json_default(obj):
            if isinstance(obj, Decimal):
                return float(obj)
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        session = LiveSession(
            case_id=case_id if case_id else 0,  # case_id=0 表示无关联配置（需要确保外键约束已处理）
            symbol=symbol,
            start_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            status="running",
            initial_capital=initial_capital,
            capital=json.dumps(config, default=json_default)
        )
        return self.create_session(session)

    def update_session_stats(self, session_id: int, stats: Dict):
        """兼容旧接口更新统计"""
        updates = {
            'total_trades': stats.get('total_trades', 0),
            'win_trades': stats.get('win_trades', 0),
            'loss_trades': stats.get('loss_trades', 0),
            'win_rate': stats.get('win_rate', 0),
            'total_profit': stats.get('total_profit', 0),
            'total_loss': stats.get('total_loss', 0),
            'net_profit': stats.get('net_profit', stats.get('total_profit', 0) + stats.get('total_loss', 0)),
            'final_capital': stats.get('final_capital', 0),
            'roi': stats.get('roi', 0),
        }
        self.update_session(session_id, updates)

    def get_session_stats(self, session_id: int) -> Dict:
        """获取会话统计信息"""
        trades = self.get_trades(session_id)

        total_trades = len(trades)
        win_trades = len([t for t in trades if t['profit'] > 0])
        loss_trades = len([t for t in trades if t['profit'] < 0])
        total_profit = sum(t['profit'] for t in trades if t['profit'] > 0)
        total_loss = sum(t['profit'] for t in trades if t['profit'] < 0)

        return {
            'total_trades': total_trades,
            'win_trades': win_trades,
            'loss_trades': loss_trades,
            'win_rate': win_trades / total_trades if total_trades > 0 else 0,
            'total_profit': total_profit,
            'total_loss': total_loss,
            'net_profit': total_profit + total_loss,
        }

    def get_all_sessions(self, symbol: str = None, limit: int = 100) -> List[Dict]:
        """兼容旧接口获取所有会话"""
        filters = {'symbol': symbol} if symbol else None
        return self.list_sessions(filters=filters, limit=limit)

    # ==================== 统计汇总 ====================

    def get_session_count_by_status(self, status: str = None) -> int:
        """按状态统计会话数量"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            if status:
                cursor.execute("SELECT COUNT(*) FROM live_sessions WHERE status = ?", (status,))
            else:
                cursor.execute("SELECT COUNT(*) FROM live_sessions")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_active_sessions(self) -> List[Dict]:
        """获取所有活跃会话"""
        return self.list_sessions(filters={'status': 'running'})

    def get_statistics_summary(self, symbol: str = None) -> Dict:
        """获取资金统计汇总"""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            sql = """
                SELECT
                    COUNT(*) as total_sessions,
                    SUM(cs.total_trades) as total_trades,
                    SUM(cs.profit_trades) as profit_trades,
                    SUM(cs.loss_trades) as loss_trades,
                    AVG(cs.win_rate) as avg_win_rate,
                    SUM(cs.total_profit) as total_profit,
                    SUM(cs.total_loss) as total_loss,
                    AVG(cs.max_drawdown) as avg_max_drawdown,
                    SUM(cs.withdrawal_count) as withdrawal_count,
                    SUM(cs.liquidation_count) as liquidation_count
                FROM live_capital_statistics cs
                JOIN live_sessions s ON cs.session_id = s.id
                WHERE s.status = 'stopped'
            """
            params = []

            if symbol:
                sql += " AND s.symbol = ?"
                params.append(symbol)

            cursor.execute(sql, params)
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {}
        finally:
            conn.close()


# 类型提示
from typing import Any
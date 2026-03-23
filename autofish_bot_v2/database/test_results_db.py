#!/usr/bin/env python3
"""
测试结果数据库模块

提供测试结果的数据库存储、查询、对比和报告生成功能。
"""

import sqlite3
import json
import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from pathlib import Path

from market_status_detector import MarketStatus


@dataclass
class TestCase:
    """测试用例数据类"""
    case_id: str
    name: str
    symbol: str
    interval: str = "1m"
    date_start: str = ""
    date_end: str = ""
    test_type: str = "market_aware"
    description: str = ""
    amplitude: str = "{}"
    market: str = "{}"
    entry: str = "{}"
    timeout: str = "{}"
    capital: str = "{}"
    status: str = "draft"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class TestResult:
    """测试结果数据类"""
    result_id: str
    case_id: str
    symbol: str
    interval: str
    start_time: str
    end_time: str
    klines_count: int = 0
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0
    net_profit: float = 0.0
    roi: float = 0.0
    price_change: float = 0.0
    excess_return: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_profit_trade: float = 0.0
    max_loss_trade: float = 0.0
    trading_time_ratio: float = 0.0
    stopped_time_ratio: float = 0.0
    market_status_changes: int = 0
    market_algorithm: str = ""
    trading_statuses: str = "[]"
    extra_metrics: str = "{}"
    capital: str = "{}"
    executed_at: str = ""
    duration_ms: int = 0
    status: str = "running"
    order_group_count: int = 0


@dataclass
class TradeDetail:
    """交易详情数据类"""
    result_id: str
    order_group_id: int = 0
    trade_seq: int = 0
    level: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    trade_type: str = ""
    profit: float = 0.0
    entry_time: str = ""
    exit_time: str = ""
    quantity: float = 0.0
    stake: float = 0.0
    entry_capital: float = 0.0
    entry_total_capital: float = 0.0


@dataclass
class MarketVisualizerCase:
    """行情可视化用例数据类"""
    case_id: str
    name: str
    symbol: str
    interval: str
    start_date: str
    end_date: str
    algorithm: str
    algorithm_config: str = "{}"
    description: str = ""
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MarketVisualizerResult:
    """行情可视化结果数据类"""
    result_id: str
    case_id: str
    total_intervals: int = 0
    ranging_intervals: int = 0
    trending_up_intervals: int = 0
    trending_down_intervals: int = 0
    ranging_count: int = 0
    trending_up_count: int = 0
    trending_down_count: int = 0
    status_ranges: str = "[]"
    duration_ms: int = 0
    executed_at: str = ""


@dataclass
class MarketVisualizerDetail:
    """行情可视化详情数据类"""
    result_id: str
    date: str
    status: str
    confidence: float = 0.0
    reason: str = ""
    open_price: float = 0.0
    close_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    volume: float = 0.0


class TestResultsDB:
    """测试结果数据库管理类"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            base_dir = Path(__file__).parent
            db_path = base_dir / "test_results.db"
        
        self.db_path = str(db_path)
        self._ensure_tables()
    
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    def _ensure_tables(self):
        """创建数据库表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 测试用例表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                symbol TEXT NOT NULL,
                interval TEXT DEFAULT '1m',
                date_start TEXT NOT NULL,
                date_end TEXT NOT NULL,
                test_type TEXT NOT NULL DEFAULT 'market_aware',
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
        
        # 测试结果表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id TEXT UNIQUE NOT NULL,
                case_id TEXT NOT NULL,
                symbol TEXT,
                interval TEXT,
                start_time DATETIME,
                end_time DATETIME,
                klines_count INTEGER DEFAULT 0,
                total_trades INTEGER DEFAULT 0,
                win_trades INTEGER DEFAULT 0,
                loss_trades INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0,
                total_profit REAL DEFAULT 0,
                total_loss REAL DEFAULT 0,
                net_profit REAL DEFAULT 0,
                roi REAL DEFAULT 0,
                price_change REAL DEFAULT 0,
                excess_return REAL DEFAULT 0,
                profit_factor REAL DEFAULT 0,
                sharpe_ratio REAL DEFAULT 0,
                max_profit_trade REAL DEFAULT 0,
                max_loss_trade REAL DEFAULT 0,
                trading_time_ratio REAL DEFAULT 0,
                stopped_time_ratio REAL DEFAULT 0,
                market_status_changes INTEGER DEFAULT 0,
                market_algorithm TEXT,
                trading_statuses TEXT DEFAULT '[]',
                extra_metrics TEXT DEFAULT '{}',
                capital TEXT DEFAULT '{}',
                executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                duration_ms INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running',
                order_group_count INTEGER DEFAULT 0,
                FOREIGN KEY (case_id) REFERENCES test_cases(case_id)
            )
        """)
        
        # 交易详情表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id TEXT NOT NULL,
                order_group_id INTEGER DEFAULT 0,
                trade_seq INTEGER NOT NULL,
                level TEXT,
                entry_price REAL,
                exit_price REAL,
                entry_time DATETIME,
                exit_time DATETIME,
                trade_type TEXT,
                profit REAL,
                quantity REAL DEFAULT 0,
                stake REAL DEFAULT 0,
                entry_capital REAL DEFAULT 0,
                entry_total_capital REAL DEFAULT 0,
                FOREIGN KEY (result_id) REFERENCES test_results(result_id)
            )
        """)
        
        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_symbol ON test_cases(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_status ON test_cases(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_type ON test_cases(test_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_case ON test_results(case_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_symbol ON test_results(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_status ON test_results(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_result ON trade_details(result_id)")
        
        # 资金统计表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS capital_statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id TEXT NOT NULL UNIQUE,
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
                FOREIGN KEY (result_id) REFERENCES test_results(result_id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capital_statistics_result ON capital_statistics(result_id)")
        
        # 资金历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS capital_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id TEXT NOT NULL,
                statistics_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                old_capital REAL NOT NULL,
                new_capital REAL NOT NULL,
                total_capital REAL,
                profit REAL NOT NULL,
                event_type TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (result_id) REFERENCES test_results(result_id) ON DELETE CASCADE,
                FOREIGN KEY (statistics_id) REFERENCES capital_statistics(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capital_history_result ON capital_history(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capital_history_statistics ON capital_history(statistics_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capital_history_timestamp ON capital_history(timestamp)")
        
        # 行情可视化用例表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_visualizer_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL DEFAULT '1d',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                algorithm_config TEXT DEFAULT '{}',
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 行情可视化结果表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_visualizer_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id TEXT UNIQUE NOT NULL,
                case_id TEXT NOT NULL,
                total_intervals INTEGER DEFAULT 0,
                ranging_intervals INTEGER DEFAULT 0,
                trending_up_intervals INTEGER DEFAULT 0,
                trending_down_intervals INTEGER DEFAULT 0,
                ranging_count INTEGER DEFAULT 0,
                trending_up_count INTEGER DEFAULT 0,
                trending_down_count INTEGER DEFAULT 0,
                status_ranges TEXT DEFAULT '[]',
                duration_ms INTEGER DEFAULT 0,
                executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (case_id) REFERENCES market_visualizer_cases(case_id)
            )
        """)
        
        # 行情可视化详情表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_visualizer_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id TEXT NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL DEFAULT 0,
                reason TEXT DEFAULT '',
                open_price REAL DEFAULT 0,
                close_price REAL DEFAULT 0,
                high_price REAL DEFAULT 0,
                low_price REAL DEFAULT 0,
                volume REAL DEFAULT 0,
                FOREIGN KEY (result_id) REFERENCES market_visualizer_results(result_id)
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_cases_symbol ON market_visualizer_cases(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_cases_algorithm ON market_visualizer_cases(algorithm)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_cases_status ON market_visualizer_cases(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_results_case ON market_visualizer_results(case_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_details_result ON market_visualizer_details(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_details_date ON market_visualizer_details(date)")
        
        # 优化器结果表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS optimizer_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                optimizer_id TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                stage TEXT NOT NULL,
                date_range TEXT NOT NULL,
                days INTEGER,
                n_trials INTEGER,
                best_value REAL,
                best_params TEXT,
                param_ranges TEXT,
                avg_value REAL,
                std_value REAL,
                duration_ms INTEGER,
                status TEXT DEFAULT 'running',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            )
        """)
        
        # 优化器历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS optimizer_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                optimizer_id TEXT NOT NULL,
                trial_number INTEGER NOT NULL,
                value REAL NOT NULL,
                params TEXT,
                metrics TEXT,
                duration_ms INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (optimizer_id) REFERENCES optimizer_results(optimizer_id)
            )
        """)
        
        # 优化器相关索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_optimizer_results_symbol ON optimizer_results(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_optimizer_results_algorithm ON optimizer_results(algorithm)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_optimizer_results_stage ON optimizer_results(stage)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_optimizer_results_status ON optimizer_results(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_optimizer_history_optimizer ON optimizer_history(optimizer_id)")
        
        conn.commit()
        conn.close()
        
        self._run_migrations()
    
    def _run_migrations(self):
        """运行数据库迁移"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("PRAGMA table_info(test_cases)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'capital' not in columns:
                if 'capital_params' in columns:
                    cursor.execute("ALTER TABLE test_cases RENAME COLUMN capital_params TO capital")
                    print("迁移: test_cases capital_params 重命名为 capital")
                else:
                    cursor.execute("ALTER TABLE test_cases ADD COLUMN capital TEXT DEFAULT '{}'")
                    print("迁移: test_cases 添加 capital 字段")
            
            cursor.execute("PRAGMA table_info(test_results)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'capital' not in columns:
                if 'capital_params' in columns:
                    cursor.execute("ALTER TABLE test_results RENAME COLUMN capital_params TO capital")
                    print("迁移: test_results capital_params 重命名为 capital")
                else:
                    cursor.execute("ALTER TABLE test_results ADD COLUMN capital TEXT DEFAULT '{}'")
                    print("迁移: test_results 添加 capital 字段")
            
            conn.commit()
            
            # capital_statistics 表迁移
            cursor.execute("PRAGMA table_info(capital_statistics)")
            cs_columns = [row[1] for row in cursor.fetchall()]
            
            if 'strategy' not in cs_columns:
                cursor.execute("ALTER TABLE capital_statistics ADD COLUMN strategy TEXT DEFAULT 'guding'")
                print("迁移: capital_statistics 添加 strategy 字段")
            
            if 'withdrawal_threshold' not in cs_columns:
                cursor.execute("ALTER TABLE capital_statistics ADD COLUMN withdrawal_threshold REAL DEFAULT 2.0")
                print("迁移: capital_statistics 添加 withdrawal_threshold 字段")
            
            if 'withdrawal_retain' not in cs_columns:
                cursor.execute("ALTER TABLE capital_statistics ADD COLUMN withdrawal_retain REAL DEFAULT 1.5")
                print("迁移: capital_statistics 添加 withdrawal_retain 字段")
            
            if 'liquidation_threshold' not in cs_columns:
                cursor.execute("ALTER TABLE capital_statistics ADD COLUMN liquidation_threshold REAL DEFAULT 0.2")
                print("迁移: capital_statistics 添加 liquidation_threshold 字段")
            
            # trade_details 表添加资金字段
            cursor.execute("PRAGMA table_info(trade_details)")
            td_columns = [row[1] for row in cursor.fetchall()]
            
            if 'entry_capital' not in td_columns:
                cursor.execute("ALTER TABLE trade_details ADD COLUMN entry_capital REAL DEFAULT 0")
                print("迁移: trade_details 添加 entry_capital 字段")
            
            if 'entry_total_capital' not in td_columns:
                cursor.execute("ALTER TABLE trade_details ADD COLUMN entry_total_capital REAL DEFAULT 0")
                print("迁移: trade_details 添加 entry_total_capital 字段")
            
            if 'order_group_id' not in td_columns:
                cursor.execute("ALTER TABLE trade_details ADD COLUMN order_group_id INTEGER DEFAULT 0")
                print("迁移: trade_details 添加 order_group_id 字段")
            
            conn.commit()
            
            # test_results 表添加 order_group_count 字段
            cursor.execute("PRAGMA table_info(test_results)")
            tr_columns = [row[1] for row in cursor.fetchall()]
            
            if 'order_group_count' not in tr_columns:
                cursor.execute("ALTER TABLE test_results ADD COLUMN order_group_count INTEGER DEFAULT 0")
                print("迁移: test_results 添加 order_group_count 字段")
            
            conn.commit()
            
            # 删除 test_results 表中的冗余 capital_statistics 列
            cursor.execute("PRAGMA table_info(test_results)")
            tr_columns = [row[1] for row in cursor.fetchall()]
            
            if 'capital_statistics' in tr_columns:
                print("迁移: 删除 test_results 表中的冗余 capital_statistics 列")
                cursor.execute("ALTER TABLE test_results RENAME TO test_results_old")
                cursor.execute("""
                    CREATE TABLE test_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        result_id TEXT UNIQUE NOT NULL,
                        case_id TEXT NOT NULL,
                        symbol TEXT,
                        interval TEXT,
                        start_time DATETIME,
                        end_time DATETIME,
                        klines_count INTEGER DEFAULT 0,
                        total_trades INTEGER DEFAULT 0,
                        win_trades INTEGER DEFAULT 0,
                        loss_trades INTEGER DEFAULT 0,
                        win_rate REAL DEFAULT 0,
                        total_profit REAL DEFAULT 0,
                        total_loss REAL DEFAULT 0,
                        net_profit REAL DEFAULT 0,
                        roi REAL DEFAULT 0,
                        price_change REAL DEFAULT 0,
                        excess_return REAL DEFAULT 0,
                        profit_factor REAL DEFAULT 0,
                        sharpe_ratio REAL DEFAULT 0,
                        max_profit_trade REAL DEFAULT 0,
                        max_loss_trade REAL DEFAULT 0,
                        trading_time_ratio REAL DEFAULT 0,
                        stopped_time_ratio REAL DEFAULT 0,
                        market_status_changes INTEGER DEFAULT 0,
                        market_algorithm TEXT,
                        trading_statuses TEXT DEFAULT '[]',
                        extra_metrics TEXT DEFAULT '{}',
                        capital TEXT DEFAULT '{}',
                        executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        duration_ms INTEGER DEFAULT 0,
                        status TEXT DEFAULT 'running',
                        FOREIGN KEY (case_id) REFERENCES test_cases(case_id)
                    )
                """)
                cursor.execute("""
                    INSERT INTO test_results 
                    SELECT id, result_id, case_id, symbol, interval, start_time, end_time,
                           klines_count, total_trades, win_trades, loss_trades, win_rate,
                           total_profit, total_loss, net_profit, roi, price_change, excess_return,
                           profit_factor, sharpe_ratio, max_profit_trade, max_loss_trade,
                           trading_time_ratio, stopped_time_ratio, market_status_changes,
                           market_algorithm, trading_statuses, extra_metrics, capital,
                           executed_at, duration_ms, status
                    FROM test_results_old
                """)
                cursor.execute("DROP TABLE test_results_old")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_symbol ON test_results(symbol)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_status ON test_results(status)")
                conn.commit()
            
            cursor.execute("PRAGMA table_info(test_cases)")
            columns = [row[1] for row in cursor.fetchall()]
            
            symbol_idx = columns.index('symbol') if 'symbol' in columns else -1
            interval_idx = columns.index('interval') if 'interval' in columns else -1
            timeout_idx = columns.index('timeout') if 'timeout' in columns else -1
            capital_idx = columns.index('capital') if 'capital' in columns else -1
            
            need_rebuild = False
            if symbol_idx > 0 and interval_idx > 0 and interval_idx != symbol_idx + 1:
                need_rebuild = True
                print(f"迁移: interval 需要调整到 symbol 之后 (symbol={symbol_idx}, interval={interval_idx})")
            if timeout_idx > 0 and capital_idx > 0 and capital_idx != timeout_idx + 1:
                need_rebuild = True
                print(f"迁移: capital 需要调整到 timeout 之后 (timeout={timeout_idx}, capital={capital_idx})")
            
            if need_rebuild:
                print("迁移: test_cases 重建表结构")
                cursor.execute("ALTER TABLE test_cases RENAME TO test_cases_old")
                cursor.execute("""
                    CREATE TABLE test_cases (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        case_id TEXT UNIQUE NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT,
                        symbol TEXT NOT NULL,
                        interval TEXT DEFAULT '1m',
                        date_start TEXT NOT NULL,
                        date_end TEXT NOT NULL,
                        test_type TEXT NOT NULL DEFAULT 'market_aware',
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
                cursor.execute("""
                    INSERT INTO test_cases 
                    (id, case_id, name, description, symbol, interval, date_start, date_end, test_type,
                     amplitude, market, entry, timeout, capital, status, created_at, updated_at)
                    SELECT id, case_id, name, description, symbol, interval, date_start, date_end, test_type,
                           amplitude, market, entry, timeout, capital, status, created_at, updated_at
                    FROM test_cases_old
                """)
                cursor.execute("DROP TABLE test_cases_old")
                print("迁移: test_cases 表重建完成")
                conn.commit()
        except Exception as e:
            print(f"数据库迁移失败: {e}")
        finally:
            conn.close()
    
    # ==================== 测试用例 CRUD ====================
    
    def create_case(self, case: TestCase) -> str:
        """创建测试用例"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if not case.case_id:
                case.case_id = str(uuid.uuid4())
            
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO test_cases 
                (case_id, name, description, symbol, interval, date_start, date_end, test_type,
                 amplitude, market, entry, timeout, capital, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (case.case_id, case.name, case.description, case.symbol, case.interval,
                  case.date_start, case.date_end, case.test_type,
                  case.amplitude, case.market, case.entry, case.timeout, case.capital,
                  case.status, now, now))
            
            conn.commit()
            return case.case_id
        except Exception as e:
            print(f"创建测试用例失败: {e}")
            return ""
        finally:
            conn.close()
    
    def get_case(self, case_id: str) -> Optional[Dict]:
        """获取测试用例"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM test_cases WHERE case_id = ?", (case_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def list_cases(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取测试用例列表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            sql = "SELECT * FROM test_cases WHERE 1=1"
            params = []
            
            if filters:
                if filters.get('symbol'):
                    sql += " AND symbol = ?"
                    params.append(filters['symbol'])
                if filters.get('status'):
                    sql += " AND status = ?"
                    params.append(filters['status'])
                if filters.get('test_type'):
                    sql += " AND test_type = ?"
                    params.append(filters['test_type'])
            
            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def update_case(self, case_id: str, updates: Dict) -> bool:
        """更新测试用例（仅 draft/active 状态）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # 检查状态
            cursor.execute("SELECT status FROM test_cases WHERE case_id = ?", (case_id,))
            row = cursor.fetchone()
            if not row:
                return False
            
            status = row['status']
            if status not in ('draft', 'active'):
                print(f"测试用例状态为 {status}，不允许修改")
                return False
            
            # 构建更新语句
            allowed_fields = ['name', 'description', 'symbol', 'date_start', 'date_end',
                            'test_type', 'amplitude', 'market', 'entry', 'timeout', 'status', 'interval', 'capital']
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
            
            sql = f"UPDATE test_cases SET {', '.join(set_clauses)} WHERE case_id = ?"
            cursor.execute(sql, params)
            
            conn.commit()
            return True
        except Exception as e:
            print(f"更新测试用例失败: {e}")
            return False
        finally:
            conn.close()
    
    def update_case_status(self, case_id: str, status: str) -> bool:
        """更新测试用例状态"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "UPDATE test_cases SET status = ?, updated_at = ? WHERE case_id = ?",
                (status, datetime.now().isoformat(), case_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"更新测试用例状态失败: {e}")
            return False
        finally:
            conn.close()
    
    def delete_case(self, case_id: str) -> bool:
        """删除测试用例"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT result_id FROM test_results WHERE case_id = ?", (case_id,))
            result_ids = [row['result_id'] for row in cursor.fetchall()]
            
            for result_id in result_ids:
                cursor.execute("DELETE FROM capital_history WHERE result_id = ?", (result_id,))
                cursor.execute("DELETE FROM capital_statistics WHERE result_id = ?", (result_id,))
                cursor.execute("DELETE FROM trade_details WHERE result_id = ?", (result_id,))
            
            cursor.execute("DELETE FROM test_results WHERE case_id = ?", (case_id,))
            cursor.execute("DELETE FROM test_cases WHERE case_id = ?", (case_id,))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"删除测试用例失败: {e}")
            return False
        finally:
            conn.close()
    
    def reset_case(self, case_id: str) -> bool:
        """重置测试用例（清除测试数据，恢复为 active 状态）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # 检查状态
            cursor.execute("SELECT status FROM test_cases WHERE case_id = ?", (case_id,))
            row = cursor.fetchone()
            if not row:
                return False
            
            # 删除关联的测试结果
            cursor.execute("SELECT result_id FROM test_results WHERE case_id = ?", (case_id,))
            result_ids = [row['result_id'] for row in cursor.fetchall()]
            
            for result_id in result_ids:
                cursor.execute("DELETE FROM trade_details WHERE result_id = ?", (result_id,))
                cursor.execute("DELETE FROM capital_history WHERE result_id = ?", (result_id,))
                cursor.execute("DELETE FROM capital_statistics WHERE result_id = ?", (result_id,))
            
            cursor.execute("DELETE FROM test_results WHERE case_id = ?", (case_id,))
            
            # 恢复状态为 active
            cursor.execute("""
                UPDATE test_cases SET status = 'active', updated_at = ? WHERE case_id = ?
            """, (datetime.now().isoformat(), case_id))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"重置测试用例失败: {e}")
            return False
        finally:
            conn.close()
    
    # ==================== 测试结果 CRUD ====================
    
    def create_result(self, result: TestResult) -> str:
        """创建测试结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if not result.result_id:
                result.result_id = str(uuid.uuid4())
            
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO test_results 
                (result_id, case_id, symbol, interval, start_time, end_time, klines_count,
                 total_trades, win_trades, loss_trades, win_rate, total_profit, total_loss,
                 net_profit, roi, price_change, excess_return, profit_factor, sharpe_ratio,
                 max_profit_trade, max_loss_trade, trading_time_ratio, stopped_time_ratio,
                 market_status_changes, market_algorithm, trading_statuses, extra_metrics,
                 capital, executed_at, duration_ms, status, order_group_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (result.result_id, result.case_id, result.symbol, result.interval,
                  result.start_time, result.end_time, result.klines_count,
                  result.total_trades, result.win_trades, result.loss_trades,
                  result.win_rate, result.total_profit, result.total_loss,
                  result.net_profit, result.roi, result.price_change, result.excess_return,
                  result.profit_factor, result.sharpe_ratio, result.max_profit_trade,
                  result.max_loss_trade, result.trading_time_ratio, result.stopped_time_ratio,
                  result.market_status_changes, result.market_algorithm, result.trading_statuses,
                  result.extra_metrics, result.capital, now, result.duration_ms, result.status,
                  result.order_group_count))
            
            # 更新用例状态为 running
            cursor.execute("""
                UPDATE test_cases SET status = 'running', updated_at = ? WHERE case_id = ?
            """, (now, result.case_id))
            
            conn.commit()
            return result.result_id
        except Exception as e:
            print(f"创建测试结果失败: {e}")
            return ""
        finally:
            conn.close()
    
    def update_result(self, result_id: str, updates: Dict) -> bool:
        """更新测试结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            allowed_fields = ['klines_count', 'total_trades', 'win_trades', 'loss_trades',
                            'win_rate', 'total_profit', 'total_loss', 'net_profit', 'roi',
                            'price_change', 'excess_return', 'profit_factor', 'sharpe_ratio',
                            'max_profit_trade', 'max_loss_trade', 'trading_time_ratio',
                            'stopped_time_ratio', 'market_status_changes', 'market_algorithm',
                            'trading_statuses', 'extra_metrics', 'duration_ms', 'status', 'order_group_count']
            
            set_clauses = []
            params = []
            
            for field in allowed_fields:
                if field in updates:
                    set_clauses.append(f"{field} = ?")
                    params.append(updates[field])
            
            if not set_clauses:
                return True
            
            params.append(result_id)
            sql = f"UPDATE test_results SET {', '.join(set_clauses)} WHERE result_id = ?"
            cursor.execute(sql, params)
            
            # 如果状态变为 success，更新用例状态为 completed
            if updates.get('status') == 'success':
                cursor.execute("SELECT case_id FROM test_results WHERE result_id = ?", (result_id,))
                row = cursor.fetchone()
                if row:
                    cursor.execute("""
                        UPDATE test_cases SET status = 'completed', updated_at = ? WHERE case_id = ?
                    """, (datetime.now().isoformat(), row['case_id']))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"更新测试结果失败: {e}")
            return False
        finally:
            conn.close()
    
    def get_result(self, result_id: str) -> Optional[Dict]:
        """获取测试结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT r.*, c.test_type, c.name as case_name,
                       cs.strategy as capital_strategy, cs.initial_capital, cs.final_capital,
                       cs.trading_capital, cs.profit_pool, cs.total_return, cs.total_profit,
                       cs.total_loss, cs.max_capital, cs.max_drawdown, cs.withdrawal_threshold,
                       cs.withdrawal_retain, cs.liquidation_threshold, cs.withdrawal_count,
                       cs.total_withdrawal, cs.liquidation_count, cs.total_trades as cs_total_trades,
                       cs.profit_trades, cs.loss_trades, cs.avg_profit, cs.avg_loss, cs.win_rate as cs_win_rate
                FROM test_results r
                LEFT JOIN test_cases c ON r.case_id = c.case_id
                LEFT JOIN capital_statistics cs ON r.result_id = cs.result_id
                WHERE r.result_id = ?
            """, (result_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            result = dict(row)
            if result.get('capital_strategy'):
                result['capital_statistics'] = {
                    'strategy': result.pop('capital_strategy'),
                    'initial_capital': result.pop('initial_capital'),
                    'final_capital': result.pop('final_capital'),
                    'trading_capital': result.pop('trading_capital'),
                    'profit_pool': result.pop('profit_pool'),
                    'total_return': result.pop('total_return'),
                    'total_profit': result.pop('total_profit'),
                    'total_loss': result.pop('total_loss'),
                    'max_capital': result.pop('max_capital'),
                    'max_drawdown': result.pop('max_drawdown'),
                    'withdrawal_threshold': result.pop('withdrawal_threshold'),
                    'withdrawal_retain': result.pop('withdrawal_retain'),
                    'liquidation_threshold': result.pop('liquidation_threshold'),
                    'withdrawal_count': result.pop('withdrawal_count'),
                    'total_withdrawal': result.pop('total_withdrawal'),
                    'liquidation_count': result.pop('liquidation_count'),
                    'total_trades': result.pop('cs_total_trades'),
                    'profit_trades': result.pop('profit_trades'),
                    'loss_trades': result.pop('loss_trades'),
                    'avg_profit': result.pop('avg_profit'),
                    'avg_loss': result.pop('avg_loss'),
                    'win_rate': result.pop('cs_win_rate'),
                }
            else:
                result['capital_statistics'] = None
                for key in ['capital_strategy', 'initial_capital', 'final_capital', 'trading_capital',
                           'profit_pool', 'total_return', 'total_profit', 'total_loss', 'max_capital',
                           'max_drawdown', 'withdrawal_threshold', 'withdrawal_retain', 'liquidation_threshold',
                           'withdrawal_count', 'total_withdrawal', 'liquidation_count', 'cs_total_trades',
                           'profit_trades', 'loss_trades', 'avg_profit', 'avg_loss', 'cs_win_rate']:
                    result.pop(key, None)
            
            return result
        finally:
            conn.close()
    
    def list_results(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取测试结果列表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            sql = """
                SELECT r.*, c.test_type, c.name as case_name,
                       cs.strategy as capital_strategy, cs.initial_capital, cs.final_capital,
                       cs.trading_capital, cs.profit_pool, cs.total_return, cs.total_profit,
                       cs.total_loss, cs.max_capital, cs.max_drawdown, cs.withdrawal_threshold,
                       cs.withdrawal_retain, cs.liquidation_threshold, cs.withdrawal_count,
                       cs.total_withdrawal, cs.liquidation_count, cs.total_trades as cs_total_trades,
                       cs.profit_trades, cs.loss_trades, cs.avg_profit, cs.avg_loss, cs.win_rate as cs_win_rate
                FROM test_results r
                LEFT JOIN test_cases c ON r.case_id = c.case_id
                LEFT JOIN capital_statistics cs ON r.result_id = cs.result_id
                WHERE 1=1
            """
            params = []
            
            if filters:
                if filters.get('case_id'):
                    sql += " AND r.case_id = ?"
                    params.append(filters['case_id'])
                if filters.get('symbol'):
                    sql += " AND r.symbol = ?"
                    params.append(filters['symbol'])
                if filters.get('status'):
                    sql += " AND r.status = ?"
                    params.append(filters['status'])
                if filters.get('market_algorithm'):
                    sql += " AND r.market_algorithm = ?"
                    params.append(filters['market_algorithm'])
            
            sql += " ORDER BY r.executed_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                result = dict(row)
                if result.get('capital_strategy'):
                    result['capital_statistics'] = {
                        'strategy': result.pop('capital_strategy'),
                        'initial_capital': result.pop('initial_capital'),
                        'final_capital': result.pop('final_capital'),
                        'trading_capital': result.pop('trading_capital'),
                        'profit_pool': result.pop('profit_pool'),
                        'total_return': result.pop('total_return'),
                        'total_profit': result.pop('total_profit'),
                        'total_loss': result.pop('total_loss'),
                        'max_capital': result.pop('max_capital'),
                        'max_drawdown': result.pop('max_drawdown'),
                        'withdrawal_threshold': result.pop('withdrawal_threshold'),
                        'withdrawal_retain': result.pop('withdrawal_retain'),
                        'liquidation_threshold': result.pop('liquidation_threshold'),
                        'withdrawal_count': result.pop('withdrawal_count'),
                        'total_withdrawal': result.pop('total_withdrawal'),
                        'liquidation_count': result.pop('liquidation_count'),
                        'total_trades': result.pop('cs_total_trades'),
                        'profit_trades': result.pop('profit_trades'),
                        'loss_trades': result.pop('loss_trades'),
                        'avg_profit': result.pop('avg_profit'),
                        'avg_loss': result.pop('avg_loss'),
                        'win_rate': result.pop('cs_win_rate'),
                    }
                else:
                    result['capital_statistics'] = None
                    for key in ['capital_strategy', 'initial_capital', 'final_capital', 'trading_capital',
                               'profit_pool', 'total_return', 'total_profit', 'total_loss', 'max_capital',
                               'max_drawdown', 'withdrawal_threshold', 'withdrawal_retain', 'liquidation_threshold',
                               'withdrawal_count', 'total_withdrawal', 'liquidation_count', 'cs_total_trades',
                               'profit_trades', 'loss_trades', 'avg_profit', 'avg_loss', 'cs_win_rate']:
                        result.pop(key, None)
                results.append(result)
            
            return results
        finally:
            conn.close()
    
    # ==================== 交易详情 CRUD ====================
    
    def save_trade_details(self, result_id: str, trades: List[TradeDetail]) -> bool:
        """保存交易详情"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            for trade in trades:
                cursor.execute("""
                    INSERT INTO trade_details 
                    (result_id, order_group_id, trade_seq, level, entry_price, exit_price, entry_time,
                     exit_time, trade_type, profit, quantity, stake, entry_capital, entry_total_capital)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (result_id, trade.order_group_id, trade.trade_seq, trade.level, trade.entry_price,
                      trade.exit_price, trade.entry_time, trade.exit_time,
                      trade.trade_type, trade.profit, trade.quantity, trade.stake,
                      trade.entry_capital, trade.entry_total_capital))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"保存交易详情失败: {e}")
            return False
        finally:
            conn.close()
    
    def get_trade_details(self, result_id: str) -> List[Dict]:
        """获取交易详情"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM trade_details WHERE result_id = ? ORDER BY trade_seq", (result_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    # ==================== 历史汇总 ====================
    
    def get_history_summary(self, filters: Dict = None) -> Dict:
        """获取测试历史汇总"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            sql = "SELECT * FROM test_results WHERE status = 'success'"
            params = []
            
            if filters:
                if filters.get('symbol'):
                    sql += " AND symbol = ?"
                    params.append(filters['symbol'])
                if filters.get('market_algorithm'):
                    sql += " AND market_algorithm = ?"
                    params.append(filters['market_algorithm'])
            
            cursor.execute(sql, params)
            results = [dict(row) for row in cursor.fetchall()]
            
            if not results:
                return {
                    'total_tests': 0,
                    'success_count': 0,
                    'failed_count': 0,
                    'success_rate': 0,
                    'avg_win_rate': 0,
                    'avg_roi': 0,
                    'avg_excess_return': 0,
                    'avg_profit_factor': 0,
                    'max_roi': 0,
                    'min_roi': 0,
                }
            
            total = len(results)
            win_rates = [r['win_rate'] for r in results if r['win_rate']]
            rois = [r['roi'] for r in results if r['roi']]
            excess_returns = [r['excess_return'] for r in results if r['excess_return']]
            profit_factors = [r['profit_factor'] for r in results if r['profit_factor']]
            
            return {
                'total_tests': total,
                'success_count': total,
                'failed_count': 0,
                'success_rate': 100.0,
                'avg_win_rate': sum(win_rates) / len(win_rates) if win_rates else 0,
                'avg_roi': sum(rois) / len(rois) if rois else 0,
                'avg_excess_return': sum(excess_returns) / len(excess_returns) if excess_returns else 0,
                'avg_profit_factor': sum(profit_factors) / len(profit_factors) if profit_factors else 0,
                'max_roi': max(rois) if rois else 0,
                'min_roi': min(rois) if rois else 0,
            }
        finally:
            conn.close()
    
    def get_history_by_symbol(self) -> List[Dict]:
        """按标的统计"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT symbol, COUNT(*) as count,
                       AVG(win_rate) as avg_win_rate,
                       AVG(roi) as avg_roi,
                       AVG(excess_return) as avg_excess_return
                FROM test_results 
                WHERE status = 'success'
                GROUP BY symbol
                ORDER BY count DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_history_by_algorithm(self) -> List[Dict]:
        """按算法统计"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT market_algorithm, COUNT(*) as count,
                       AVG(win_rate) as avg_win_rate,
                       AVG(roi) as avg_roi,
                       AVG(excess_return) as avg_excess_return
                FROM test_results 
                WHERE status = 'success' AND market_algorithm IS NOT NULL
                GROUP BY market_algorithm
                ORDER BY count DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    # ==================== 兼容旧接口 ====================
    
    def save_execution(self, execution) -> str:
        """兼容旧接口"""
        return execution.execution_id
    
    def save_params(self, execution_id: str, params: Dict[str, Any]) -> bool:
        """兼容旧接口"""
        return True
    
    def save_result(self, result: TestResult) -> bool:
        """兼容旧接口"""
        result_id = self.create_result(result)
        return bool(result_id)
    
    # ==================== 行情可视化 CRUD ====================
    
    def create_visualizer_case(self, case: MarketVisualizerCase) -> str:
        """创建行情可视化用例"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if not case.case_id:
                case.case_id = str(uuid.uuid4())
            
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO market_visualizer_cases 
                (case_id, name, symbol, interval, start_date, end_date, algorithm,
                 algorithm_config, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (case.case_id, case.name, case.symbol, case.interval,
                  case.start_date, case.end_date, case.algorithm,
                  case.algorithm_config, case.description, case.status, now, now))
            
            conn.commit()
            return case.case_id
        except Exception as e:
            print(f"创建行情可视化用例失败: {e}")
            return ""
        finally:
            conn.close()
    
    def get_visualizer_case(self, case_id: str) -> Optional[Dict]:
        """获取行情可视化用例"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM market_visualizer_cases WHERE case_id = ?", (case_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                if result.get('algorithm_config'):
                    result['algorithm_config'] = json.loads(result['algorithm_config'])
                return result
            return None
        finally:
            conn.close()
    
    def list_visualizer_cases(self, filters: Dict = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取行情可视化用例列表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            sql = "SELECT * FROM market_visualizer_cases WHERE 1=1"
            params = []
            
            if filters:
                if filters.get('symbol'):
                    sql += " AND symbol = ?"
                    params.append(filters['symbol'])
                if filters.get('algorithm'):
                    sql += " AND algorithm = ?"
                    params.append(filters['algorithm'])
                if filters.get('status'):
                    sql += " AND status = ?"
                    params.append(filters['status'])
            
            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(sql, params)
            results = []
            for row in cursor.fetchall():
                item = dict(row)
                if item.get('algorithm_config'):
                    item['algorithm_config'] = json.loads(item['algorithm_config'])
                results.append(item)
            return results
        finally:
            conn.close()
    
    # ==================== 资金统计 CRUD ====================
    
    def save_capital_statistics(self, result_id: str, stats: Dict) -> bool:
        """保存资金统计数据"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO capital_statistics
                (result_id, strategy, initial_capital, final_capital, trading_capital, profit_pool,
                 total_return, total_profit, total_loss, max_capital, max_drawdown,
                 withdrawal_threshold, withdrawal_retain, liquidation_threshold,
                 withdrawal_count, total_withdrawal, liquidation_count,
                 total_trades, profit_trades, loss_trades, avg_profit, avg_loss, win_rate,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result_id,
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
                stats.get('round_count', stats.get('total_trades', 0)),
                stats.get('win_rounds', stats.get('profit_trades', 0)),
                stats.get('loss_rounds', stats.get('loss_trades', 0)),
                stats.get('avg_round_profit', stats.get('avg_profit', 0)),
                stats.get('avg_round_profit', 0) if stats.get('loss_rounds', 0) > 0 else 0,
                stats.get('win_rate', 0),
                now, now
            ))
            
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            print(f"保存资金统计数据失败: {e}")
            return 0
        finally:
            conn.close()
    
    def get_capital_statistics(self, result_id: str) -> Optional[Dict]:
        """获取资金统计数据"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM capital_statistics WHERE result_id = ?", (result_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def delete_capital_statistics(self, result_id: str) -> bool:
        """删除资金统计数据"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM capital_statistics WHERE result_id = ?", (result_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"删除资金统计数据失败: {e}")
            return False
        finally:
            conn.close()
    
    # ==================== 资金历史 CRUD ====================
    
    def save_capital_history(self, result_id: str, statistics_id: int, history: List[Dict]) -> bool:
        """保存资金历史记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            for item in history:
                cursor.execute("""
                    INSERT INTO capital_history
                    (result_id, statistics_id, timestamp, old_capital, new_capital, total_capital, profit, event_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    result_id,
                    statistics_id,
                    item.get('timestamp', ''),
                    item.get('old_capital', 0),
                    item.get('new_capital', 0),
                    item.get('total_capital'),
                    item.get('profit', 0),
                    item.get('event_type', ''),
                    datetime.now().isoformat()
                ))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"保存资金历史记录失败: {e}")
            return False
        finally:
            conn.close()
    
    def get_capital_history(self, result_id: str, limit: int = 1000, offset: int = 0) -> List[Dict]:
        """获取资金历史记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM capital_history 
                WHERE result_id = ? 
                ORDER BY timestamp ASC 
                LIMIT ? OFFSET ?
            """, (result_id, limit, offset))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def delete_capital_history(self, result_id: str) -> bool:
        """删除资金历史记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM capital_history WHERE result_id = ?", (result_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"删除资金历史记录失败: {e}")
            return False
        finally:
            conn.close()
    
    def update_visualizer_case_status(self, case_id: str, status: str) -> bool:
        """更新行情可视化用例状态"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE market_visualizer_cases 
                SET status = ?, updated_at = ? 
                WHERE case_id = ?
            """, (status, datetime.now().isoformat(), case_id))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"更新行情可视化用例状态失败: {e}")
            return False
        finally:
            conn.close()
    
    def delete_visualizer_case(self, case_id: str) -> bool:
        """删除行情可视化用例及其关联数据"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT result_id FROM market_visualizer_results WHERE case_id = ?", (case_id,))
            result_ids = [row['result_id'] for row in cursor.fetchall()]
            
            for result_id in result_ids:
                cursor.execute("DELETE FROM market_visualizer_details WHERE result_id = ?", (result_id,))
            
            cursor.execute("DELETE FROM market_visualizer_results WHERE case_id = ?", (case_id,))
            cursor.execute("DELETE FROM market_visualizer_cases WHERE case_id = ?", (case_id,))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"删除行情可视化用例失败: {e}")
            return False
        finally:
            conn.close()
    
    def count_visualizer_cases(self, filters: Dict = None) -> int:
        """统计行情可视化用例数量"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            sql = "SELECT COUNT(*) FROM market_visualizer_cases WHERE 1=1"
            params = []
            
            if filters:
                if filters.get('symbol'):
                    sql += " AND symbol = ?"
                    params.append(filters['symbol'])
                if filters.get('algorithm'):
                    sql += " AND algorithm = ?"
                    params.append(filters['algorithm'])
                if filters.get('status'):
                    sql += " AND status = ?"
                    params.append(filters['status'])
            
            cursor.execute(sql, params)
            return cursor.fetchone()[0]
        finally:
            conn.close()
    
    def create_visualizer_result(self, result: MarketVisualizerResult) -> str:
        """创建行情可视化结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if not result.result_id:
                result.result_id = str(uuid.uuid4())
            
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO market_visualizer_results 
                (result_id, case_id, total_intervals, ranging_intervals, trending_up_intervals,
                 trending_down_intervals, ranging_count, trending_up_count, trending_down_count,
                 status_ranges, duration_ms, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (result.result_id, result.case_id, result.total_intervals,
                  result.ranging_intervals, result.trending_up_intervals, result.trending_down_intervals,
                  result.ranging_count, result.trending_up_count, result.trending_down_count,
                  result.status_ranges, result.duration_ms, now))
            
            cursor.execute("""
                UPDATE market_visualizer_cases SET status = 'completed', updated_at = ? WHERE case_id = ?
            """, (now, result.case_id))
            
            conn.commit()
            return result.result_id
        except Exception as e:
            print(f"创建行情可视化结果失败: {e}")
            return ""
        finally:
            conn.close()
    
    def get_visualizer_result(self, result_id: str) -> Optional[Dict]:
        """获取行情可视化结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM market_visualizer_results WHERE result_id = ?", (result_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                if result.get('status_ranges'):
                    result['status_ranges'] = json.loads(result['status_ranges'])
                return result
            return None
        finally:
            conn.close()
    
    def get_visualizer_result_by_case(self, case_id: str) -> Optional[Dict]:
        """根据用例ID获取最新的行情可视化结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM market_visualizer_results 
                WHERE case_id = ? 
                ORDER BY executed_at DESC 
                LIMIT 1
            """, (case_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                if result.get('status_ranges'):
                    result['status_ranges'] = json.loads(result['status_ranges'])
                return result
            return None
        finally:
            conn.close()
    
    def create_visualizer_details(self, result_id: str, details: List[Dict]) -> bool:
        """批量创建行情可视化详情"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            for detail in details:
                cursor.execute("""
                    INSERT INTO market_visualizer_details 
                    (result_id, date, status, confidence, reason,
                     open_price, close_price, high_price, low_price, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (result_id, detail['date'], detail['status'],
                      detail.get('confidence', 1.0), detail.get('reason', ''),
                      detail['open_price'], detail['close_price'],
                      detail['high_price'], detail['low_price'], detail['volume']))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"创建行情可视化详情失败: {e}")
            return False
        finally:
            conn.close()
    
    def get_visualizer_details(self, result_id: str) -> List[Dict]:
        """获取行情可视化详情列表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM market_visualizer_details 
                WHERE result_id = ? 
                ORDER BY date ASC
            """, (result_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_visualizer_statistics(self, result_id: str) -> Dict:
        """获取行情可视化统计信息"""
        result = self.get_visualizer_result(result_id)
        if result is None:
            return {}
        
        total = result['total_intervals']
        return {
            'total_intervals': total,
            'status_intervals': {
                'ranging': result['ranging_intervals'],
                'trending_up': result['trending_up_intervals'],
                'trending_down': result['trending_down_intervals'],
            },
            'status_percent': {
                'ranging': round(result['ranging_intervals'] / total * 100, 1) if total > 0 else 0,
                'trending_up': round(result['trending_up_intervals'] / total * 100, 1) if total > 0 else 0,
                'trending_down': round(result['trending_down_intervals'] / total * 100, 1) if total > 0 else 0,
            },
            'ranging_count': result['ranging_count'],
            'trending_up_count': result['trending_up_count'],
            'trending_down_count': result['trending_down_count'],
            'duration_ms': result['duration_ms'],
            'executed_at': result['executed_at'],
        }
    
    # ==================== 优化器 CRUD ====================
    
    def save_optimizer_result(
        self,
        optimizer_id: str,
        symbol: str,
        algorithm: str,
        stage: str,
        date_range: str,
        days: int,
        n_trials: int,
        best_value: float,
        best_params: Dict,
        param_ranges: Dict,
        avg_value: float,
        std_value: float,
        duration_ms: int = 0,
        status: str = 'completed'
    ) -> bool:
        """保存优化器结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO optimizer_results
                (optimizer_id, symbol, algorithm, stage, date_range, days, n_trials,
                 best_value, best_params, param_ranges, avg_value, std_value,
                 duration_ms, status, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                optimizer_id, symbol, algorithm, stage, date_range, days, n_trials,
                best_value, json.dumps(best_params), json.dumps(param_ranges),
                avg_value, std_value, duration_ms, status, now, now if status == 'completed' else None
            ))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"保存优化器结果失败: {e}")
            return False
        finally:
            conn.close()
    
    def save_optimizer_history(
        self,
        optimizer_id: str,
        trial: int,
        value: float,
        params: Dict,
        metrics: Dict,
        duration_ms: int = 0
    ) -> bool:
        """保存优化器历史"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO optimizer_history
                (optimizer_id, trial_number, value, params, metrics, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                optimizer_id, trial, value,
                json.dumps(params), json.dumps(metrics), duration_ms,
                datetime.now().isoformat()
            ))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"保存优化器历史失败: {e}")
            return False
        finally:
            conn.close()
    
    def get_optimizer_result(self, optimizer_id: str) -> Optional[Dict]:
        """获取优化器结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM optimizer_results WHERE optimizer_id = ?", (optimizer_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                result['best_params'] = json.loads(result['best_params']) if result['best_params'] else {}
                result['param_ranges'] = json.loads(result['param_ranges']) if result['param_ranges'] else {}
                return result
            return None
        finally:
            conn.close()
    
    def get_optimizer_history(self, optimizer_id: str) -> List[Dict]:
        """获取优化器历史"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM optimizer_history 
                WHERE optimizer_id = ? 
                ORDER BY trial_number ASC
            """, (optimizer_id,))
            
            results = []
            for row in cursor.fetchall():
                result = dict(row)
                result['params'] = json.loads(result['params']) if result['params'] else {}
                result['metrics'] = json.loads(result['metrics']) if result['metrics'] else {}
                results.append(result)
            return results
        finally:
            conn.close()
    
    def get_best_params(self, symbol: str, algorithm: str = 'dual_thrust', stage: str = None) -> Optional[Dict]:
        """获取最佳参数"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            sql = """
                SELECT * FROM optimizer_results 
                WHERE symbol = ? AND algorithm = ? AND status = 'completed'
            """
            params = [symbol, algorithm]
            
            if stage:
                sql += " AND stage = ?"
                params.append(stage)
            
            sql += " ORDER BY best_value DESC LIMIT 1"
            
            cursor.execute(sql, params)
            row = cursor.fetchone()
            
            if row:
                result = dict(row)
                result['best_params'] = json.loads(result['best_params']) if result['best_params'] else {}
                result['param_ranges'] = json.loads(result['param_ranges']) if result['param_ranges'] else {}
                return result
            return None
        finally:
            conn.close()
    
    def list_optimizer_results(
        self,
        symbol: str = None,
        algorithm: str = None,
        stage: str = None,
        status: str = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict]:
        """获取优化器结果列表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            sql = "SELECT * FROM optimizer_results WHERE 1=1"
            params = []
            
            if symbol:
                sql += " AND symbol = ?"
                params.append(symbol)
            if algorithm:
                sql += " AND algorithm = ?"
                params.append(algorithm)
            if stage:
                sql += " AND stage = ?"
                params.append(stage)
            if status:
                sql += " AND status = ?"
                params.append(status)
            
            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(sql, params)
            
            results = []
            for row in cursor.fetchall():
                result = dict(row)
                result['best_params'] = json.loads(result['best_params']) if result['best_params'] else {}
                result['param_ranges'] = json.loads(result['param_ranges']) if result['param_ranges'] else {}
                results.append(result)
            return results
        finally:
            conn.close()

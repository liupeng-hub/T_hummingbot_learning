#!/usr/bin/env python3
"""
数据库迁移脚本：将 case_id 和 result_id 从 UUID 字符串改为自增整数 ID

迁移步骤：
1. 备份现有数据
2. 创建新表结构
3. 迁移数据
4. 删除旧表
"""

import sqlite3
import json
import shutil
from datetime import datetime
from pathlib import Path


def migrate_database(db_path: str = None):
    """执行数据库迁移"""
    if db_path is None:
        base_dir = Path(__file__).parent
        db_path = base_dir / "test_results.db"
    
    db_path = Path(db_path)
    
    if not db_path.exists():
        print(f"数据库文件不存在: {db_path}")
        return False
    
    # 备份数据库
    backup_path = db_path.with_suffix(f'.db.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    shutil.copy2(db_path, backup_path)
    print(f"数据库已备份到: {backup_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # 开始事务
        cursor.execute("BEGIN TRANSACTION")
        
        # 检查是否需要迁移
        cursor.execute("PRAGMA table_info(test_cases)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'case_id' not in columns:
            print("数据库已经是新结构，无需迁移")
            conn.commit()
            return True
        
        print("开始迁移数据库...")
        
        # ========== 1. 迁移 test_cases 表 ==========
        print("迁移 test_cases 表...")
        cursor.execute("ALTER TABLE test_cases RENAME TO test_cases_old")
        cursor.execute("""
            CREATE TABLE test_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
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
        
        cursor.execute("SELECT * FROM test_cases_old")
        old_cases = cursor.fetchall()
        
        case_id_map = {}  # 旧 case_id -> 新 id
        for case in old_cases:
            cursor.execute("""
                INSERT INTO test_cases 
                (name, description, symbol, interval, date_start, date_end, test_type,
                 amplitude, market, entry, timeout, capital, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (case['name'], case['description'], case['symbol'], case['interval'],
                  case['date_start'], case['date_end'], case['test_type'],
                  case['amplitude'], case['market'], case['entry'], case['timeout'], case['capital'],
                  case['status'], case['created_at'], case['updated_at']))
            
            new_id = cursor.lastrowid
            case_id_map[case['case_id']] = new_id
            print(f"  用例 '{case['name']}' : {case['case_id']} -> {new_id}")
        
        # ========== 2. 迁移 test_results 表 ==========
        print("迁移 test_results 表...")
        cursor.execute("ALTER TABLE test_results RENAME TO test_results_old")
        cursor.execute("""
            CREATE TABLE test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
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
                avg_execution_time REAL DEFAULT 0,
                avg_holding_time REAL DEFAULT 0,
                FOREIGN KEY (case_id) REFERENCES test_cases(id)
            )
        """)
        
        cursor.execute("SELECT * FROM test_results_old")
        old_results = cursor.fetchall()
        
        result_id_map = {}  # 旧 result_id -> 新 id
        for result in old_results:
            old_case_id = result['case_id']
            new_case_id = case_id_map.get(old_case_id)
            
            if new_case_id is None:
                print(f"  警告: 找不到 case_id {old_case_id} 的映射，跳过结果 {result['result_id']}")
                continue
            
            cursor.execute("""
                INSERT INTO test_results 
                (case_id, symbol, interval, start_time, end_time, klines_count, total_trades,
                 win_trades, loss_trades, win_rate, total_profit, total_loss, net_profit, roi,
                 price_change, excess_return, profit_factor, sharpe_ratio, max_profit_trade,
                 max_loss_trade, trading_time_ratio, stopped_time_ratio, market_status_changes,
                 market_algorithm, trading_statuses, extra_metrics, capital, executed_at,
                 duration_ms, status, order_group_count, avg_execution_time, avg_holding_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (new_case_id, result['symbol'], result['interval'], result['start_time'], result['end_time'],
                  result['klines_count'], result['total_trades'], result['win_trades'], result['loss_trades'],
                  result['win_rate'], result['total_profit'], result['total_loss'], result['net_profit'],
                  result['roi'], result['price_change'], result['excess_return'], result['profit_factor'],
                  result['sharpe_ratio'], result['max_profit_trade'], result['max_loss_trade'],
                  result['trading_time_ratio'], result['stopped_time_ratio'], result['market_status_changes'],
                  result['market_algorithm'], result['trading_statuses'], result['extra_metrics'],
                  result['capital'], result['executed_at'], result['duration_ms'], result['status'],
                  result['order_group_count'], result['avg_execution_time'], result['avg_holding_time']))
            
            new_id = cursor.lastrowid
            result_id_map[result['result_id']] = new_id
            print(f"  结果 {result['result_id']} -> {new_id}")
        
        # ========== 3. 迁移 trade_details 表 ==========
        print("迁移 trade_details 表...")
        cursor.execute("ALTER TABLE trade_details RENAME TO trade_details_old")
        cursor.execute("""
            CREATE TABLE trade_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER NOT NULL,
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
                FOREIGN KEY (result_id) REFERENCES test_results(id)
            )
        """)
        
        cursor.execute("SELECT * FROM trade_details_old")
        old_trades = cursor.fetchall()
        
        for trade in old_trades:
            old_result_id = trade['result_id']
            new_result_id = result_id_map.get(old_result_id)
            
            if new_result_id is None:
                continue
            
            cursor.execute("""
                INSERT INTO trade_details 
                (result_id, order_group_id, trade_seq, level, entry_price, exit_price, entry_time,
                 exit_time, trade_type, profit, quantity, stake, entry_capital, entry_total_capital)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (new_result_id, trade['order_group_id'], trade['trade_seq'], trade['level'],
                  trade['entry_price'], trade['exit_price'], trade['entry_time'], trade['exit_time'],
                  trade['trade_type'], trade['profit'], trade['quantity'], trade['stake'],
                  trade['entry_capital'], trade['entry_total_capital']))
        
        print(f"  迁移了 {len(old_trades)} 条交易详情")
        
        # ========== 4. 迁移 capital_statistics 表 ==========
        print("迁移 capital_statistics 表...")
        cursor.execute("ALTER TABLE capital_statistics RENAME TO capital_statistics_old")
        cursor.execute("""
            CREATE TABLE capital_statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER NOT NULL UNIQUE,
                strategy TEXT DEFAULT 'guding',
                entry_mode TEXT DEFAULT 'compound',
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
                FOREIGN KEY (result_id) REFERENCES test_results(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("SELECT * FROM capital_statistics_old")
        old_stats = cursor.fetchall()
        
        for stat in old_stats:
            old_result_id = stat['result_id']
            new_result_id = result_id_map.get(old_result_id)
            
            if new_result_id is None:
                continue
            
            cursor.execute("""
                INSERT INTO capital_statistics 
                (result_id, strategy, entry_mode, initial_capital, final_capital, trading_capital,
                 profit_pool, total_return, total_profit, total_loss, max_capital, max_drawdown,
                 withdrawal_threshold, withdrawal_retain, liquidation_threshold, withdrawal_count,
                 total_withdrawal, liquidation_count, total_trades, profit_trades, loss_trades,
                 avg_profit, avg_loss, win_rate, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (new_result_id, stat['strategy'], stat['entry_mode'], stat['initial_capital'],
                  stat['final_capital'], stat['trading_capital'], stat['profit_pool'],
                  stat['total_return'], stat['total_profit'], stat['total_loss'],
                  stat['max_capital'], stat['max_drawdown'], stat['withdrawal_threshold'],
                  stat['withdrawal_retain'], stat['liquidation_threshold'], stat['withdrawal_count'],
                  stat['total_withdrawal'], stat['liquidation_count'], stat['total_trades'],
                  stat['profit_trades'], stat['loss_trades'], stat['avg_profit'], stat['avg_loss'],
                  stat['win_rate'], stat['created_at'], stat['updated_at']))
        
        print(f"  迁移了 {len(old_stats)} 条资金统计")
        
        # ========== 5. 迁移 capital_history 表 ==========
        print("迁移 capital_history 表...")
        cursor.execute("ALTER TABLE capital_history RENAME TO capital_history_old")
        cursor.execute("""
            CREATE TABLE capital_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER NOT NULL,
                statistics_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                old_capital REAL NOT NULL,
                new_capital REAL NOT NULL,
                total_capital REAL,
                profit REAL NOT NULL,
                event_type TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (result_id) REFERENCES test_results(id) ON DELETE CASCADE,
                FOREIGN KEY (statistics_id) REFERENCES capital_statistics(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("SELECT * FROM capital_history_old")
        old_history = cursor.fetchall()
        
        for history in old_history:
            old_result_id = history['result_id']
            new_result_id = result_id_map.get(old_result_id)
            
            if new_result_id is None:
                continue
            
            # 查找新的 statistics_id
            cursor.execute("SELECT id FROM capital_statistics WHERE result_id = ?", (new_result_id,))
            stat_row = cursor.fetchone()
            new_statistics_id = stat_row[0] if stat_row else 0
            
            cursor.execute("""
                INSERT INTO capital_history 
                (result_id, statistics_id, timestamp, old_capital, new_capital, total_capital, profit, event_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (new_result_id, new_statistics_id, history['timestamp'], history['old_capital'],
                  history['new_capital'], history['total_capital'], history['profit'],
                  history['event_type'], history['created_at']))
        
        print(f"  迁移了 {len(old_history)} 条资金历史")
        
        # ========== 6. 迁移 market_visualizer_cases 表 ==========
        print("迁移 market_visualizer_cases 表...")
        cursor.execute("ALTER TABLE market_visualizer_cases RENAME TO market_visualizer_cases_old")
        cursor.execute("""
            CREATE TABLE market_visualizer_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
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
        
        cursor.execute("SELECT * FROM market_visualizer_cases_old")
        old_mv_cases = cursor.fetchall()
        
        mv_case_id_map = {}
        for case in old_mv_cases:
            cursor.execute("""
                INSERT INTO market_visualizer_cases 
                (name, symbol, interval, start_date, end_date, algorithm, algorithm_config, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (case['name'], case['symbol'], case['interval'], case['start_date'], case['end_date'],
                  case['algorithm'], case['algorithm_config'], case['description'], case['status'],
                  case['created_at'], case['updated_at']))
            
            new_id = cursor.lastrowid
            mv_case_id_map[case['case_id']] = new_id
            print(f"  行情可视化用例 '{case['name']}' : {case['case_id']} -> {new_id}")
        
        # ========== 7. 迁移 market_visualizer_results 表 ==========
        print("迁移 market_visualizer_results 表...")
        cursor.execute("ALTER TABLE market_visualizer_results RENAME TO market_visualizer_results_old")
        cursor.execute("""
            CREATE TABLE market_visualizer_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
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
                FOREIGN KEY (case_id) REFERENCES market_visualizer_cases(id)
            )
        """)
        
        cursor.execute("SELECT * FROM market_visualizer_results_old")
        old_mv_results = cursor.fetchall()
        
        mv_result_id_map = {}
        for result in old_mv_results:
            old_case_id = result['case_id']
            new_case_id = mv_case_id_map.get(old_case_id)
            
            if new_case_id is None:
                continue
            
            cursor.execute("""
                INSERT INTO market_visualizer_results 
                (case_id, total_intervals, ranging_intervals, trending_up_intervals, trending_down_intervals,
                 ranging_count, trending_up_count, trending_down_count, status_ranges, duration_ms, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (new_case_id, result['total_intervals'], result['ranging_intervals'],
                  result['trending_up_intervals'], result['trending_down_intervals'],
                  result['ranging_count'], result['trending_up_count'], result['trending_down_count'],
                  result['status_ranges'], result['duration_ms'], result['executed_at']))
            
            new_id = cursor.lastrowid
            mv_result_id_map[result['result_id']] = new_id
        
        print(f"  迁移了 {len(old_mv_results)} 条行情可视化结果")
        
        # ========== 8. 迁移 market_visualizer_details 表 ==========
        print("迁移 market_visualizer_details 表...")
        cursor.execute("ALTER TABLE market_visualizer_details RENAME TO market_visualizer_details_old")
        cursor.execute("""
            CREATE TABLE market_visualizer_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL DEFAULT 0,
                reason TEXT DEFAULT '',
                open_price REAL DEFAULT 0,
                close_price REAL DEFAULT 0,
                high_price REAL DEFAULT 0,
                low_price REAL DEFAULT 0,
                volume REAL DEFAULT 0,
                FOREIGN KEY (result_id) REFERENCES market_visualizer_results(id)
            )
        """)
        
        cursor.execute("SELECT * FROM market_visualizer_details_old")
        old_mv_details = cursor.fetchall()
        
        for detail in old_mv_details:
            old_result_id = detail['result_id']
            new_result_id = mv_result_id_map.get(old_result_id)
            
            if new_result_id is None:
                continue
            
            cursor.execute("""
                INSERT INTO market_visualizer_details 
                (result_id, date, status, confidence, reason, open_price, close_price, high_price, low_price, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (new_result_id, detail['date'], detail['status'], detail['confidence'],
                  detail['reason'], detail['open_price'], detail['close_price'],
                  detail['high_price'], detail['low_price'], detail['volume']))
        
        print(f"  迁移了 {len(old_mv_details)} 条行情可视化详情")
        
        # ========== 9. 删除旧表 ==========
        print("删除旧表...")
        cursor.execute("DROP TABLE IF EXISTS test_cases_old")
        cursor.execute("DROP TABLE IF EXISTS test_results_old")
        cursor.execute("DROP TABLE IF EXISTS trade_details_old")
        cursor.execute("DROP TABLE IF EXISTS capital_statistics_old")
        cursor.execute("DROP TABLE IF EXISTS capital_history_old")
        cursor.execute("DROP TABLE IF EXISTS market_visualizer_cases_old")
        cursor.execute("DROP TABLE IF EXISTS market_visualizer_results_old")
        cursor.execute("DROP TABLE IF EXISTS market_visualizer_details_old")
        
        # ========== 10. 重建索引 ==========
        print("重建索引...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_symbol ON test_cases(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_status ON test_cases(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_type ON test_cases(test_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_case ON test_results(case_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_symbol ON test_results(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_status ON test_results(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_result ON trade_details(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capital_statistics_result ON capital_statistics(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capital_history_result ON capital_history(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capital_history_statistics ON capital_history(statistics_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capital_history_timestamp ON capital_history(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_cases_symbol ON market_visualizer_cases(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_cases_algorithm ON market_visualizer_cases(algorithm)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_cases_status ON market_visualizer_cases(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_results_case ON market_visualizer_results(case_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_details_result ON market_visualizer_details(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mv_details_date ON market_visualizer_details(date)")
        
        # 提交事务
        conn.commit()
        print("\n数据库迁移完成！")
        print(f"- 测试用例: {len(old_cases)} 条")
        print(f"- 测试结果: {len(old_results)} 条")
        print(f"- 交易详情: {len(old_trades)} 条")
        print(f"- 资金统计: {len(old_stats)} 条")
        print(f"- 资金历史: {len(old_history)} 条")
        print(f"- 行情可视化用例: {len(old_mv_cases)} 条")
        print(f"- 行情可视化结果: {len(old_mv_results)} 条")
        print(f"- 行情可视化详情: {len(old_mv_details)} 条")
        
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"迁移失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = migrate_database(db_path)
    sys.exit(0 if success else 1)

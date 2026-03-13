#!/usr/bin/env python3
"""
行情可视化系统数据库模块
负责测试用例、测试结果、每日状态的持久化存储
"""

import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
import sqlite3


@dataclass
class TestCase:
    """测试用例数据类"""
    id: str
    name: str
    symbol: str
    interval: str
    start_date: str
    end_date: str
    algorithm: str
    algorithm_config: Dict
    description: str
    created_at: str
    updated_at: str
    status: str = 'pending'


@dataclass
class TestResult:
    """测试结果数据类"""
    id: str
    test_case_id: str
    total_days: int
    ranging_days: int
    trending_up_days: int
    trending_down_days: int
    ranging_count: int
    trending_up_count: int
    trending_down_count: int
    status_ranges: List[Dict]
    executed_at: str
    duration_ms: int


@dataclass
class DailyStatus:
    """每日状态数据类"""
    id: str
    test_result_id: str
    date: str
    status: str
    confidence: float
    reason: str
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float


class MarketVisualizerDB:
    """行情可视化数据库管理类"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(base_dir, 'market_visualizer_out')
            os.makedirs(output_dir, exist_ok=True)
            db_path = os.path.join(output_dir, 'market_visualizer.db')
        
        self.db_path = db_path
        self._init_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """初始化数据库表结构"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_cases (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL DEFAULT '1d',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                algorithm_config TEXT,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                id TEXT PRIMARY KEY,
                test_case_id TEXT NOT NULL,
                total_days INTEGER,
                ranging_days INTEGER,
                trending_up_days INTEGER,
                trending_down_days INTEGER,
                ranging_count INTEGER,
                trending_up_count INTEGER,
                trending_down_count INTEGER,
                status_ranges TEXT,
                executed_at TEXT NOT NULL,
                duration_ms INTEGER,
                FOREIGN KEY (test_case_id) REFERENCES test_cases(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_statuses (
                id TEXT PRIMARY KEY,
                test_result_id TEXT NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL,
                reason TEXT,
                open_price REAL,
                close_price REAL,
                high_price REAL,
                low_price REAL,
                volume REAL,
                FOREIGN KEY (test_result_id) REFERENCES test_results(id)
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_daily_statuses_result 
            ON daily_statuses(test_result_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_daily_statuses_date 
            ON daily_statuses(date)
        ''')
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def _generate_uuid() -> str:
        """生成UUID"""
        return str(uuid.uuid4())
    
    @staticmethod
    def _get_now() -> str:
        """获取当前时间字符串"""
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    def create_test_case(
        self,
        name: str,
        symbol: str,
        interval: str,
        start_date: str,
        end_date: str,
        algorithm: str,
        algorithm_config: Dict = None,
        description: str = '',
    ) -> TestCase:
        """创建测试用例"""
        now = self._get_now()
        test_case = TestCase(
            id=self._generate_uuid(),
            name=name,
            symbol=symbol,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            algorithm=algorithm,
            algorithm_config=algorithm_config or {},
            description=description,
            created_at=now,
            updated_at=now,
            status='pending',
        )
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO test_cases 
            (id, name, symbol, interval, start_date, end_date, algorithm, 
             algorithm_config, description, created_at, updated_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            test_case.id,
            test_case.name,
            test_case.symbol,
            test_case.interval,
            test_case.start_date,
            test_case.end_date,
            test_case.algorithm,
            json.dumps(test_case.algorithm_config),
            test_case.description,
            test_case.created_at,
            test_case.updated_at,
            test_case.status,
        ))
        
        conn.commit()
        conn.close()
        
        return test_case
    
    def get_test_case(self, test_case_id: str) -> Optional[TestCase]:
        """获取单个测试用例"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM test_cases WHERE id = ?', (test_case_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return None
        
        return self._row_to_test_case(row)
    
    def get_test_cases(
        self,
        symbol: str = None,
        algorithm: str = None,
        status: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TestCase]:
        """获取测试用例列表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        sql = 'SELECT * FROM test_cases WHERE 1=1'
        params = []
        
        if symbol:
            sql += ' AND symbol = ?'
            params.append(symbol)
        
        if algorithm:
            sql += ' AND algorithm = ?'
            params.append(algorithm)
        
        if status:
            sql += ' AND status = ?'
            params.append(status)
        
        sql += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_test_case(row) for row in rows]
    
    def update_test_case_status(self, test_case_id: str, status: str):
        """更新测试用例状态"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE test_cases 
            SET status = ?, updated_at = ? 
            WHERE id = ?
        ''', (status, self._get_now(), test_case_id))
        
        conn.commit()
        conn.close()
    
    def delete_test_case(self, test_case_id: str):
        """删除测试用例及其关联数据"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM daily_statuses 
            WHERE test_result_id IN 
            (SELECT id FROM test_results WHERE test_case_id = ?)
        ''', (test_case_id,))
        
        cursor.execute('DELETE FROM test_results WHERE test_case_id = ?', (test_case_id,))
        cursor.execute('DELETE FROM test_cases WHERE id = ?', (test_case_id,))
        
        conn.commit()
        conn.close()
    
    def _row_to_test_case(self, row: sqlite3.Row) -> TestCase:
        """将数据库行转换为TestCase对象"""
        return TestCase(
            id=row['id'],
            name=row['name'],
            symbol=row['symbol'],
            interval=row['interval'],
            start_date=row['start_date'],
            end_date=row['end_date'],
            algorithm=row['algorithm'],
            algorithm_config=json.loads(row['algorithm_config']) if row['algorithm_config'] else {},
            description=row['description'] or '',
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            status=row['status'],
        )
    
    def create_test_result(
        self,
        test_case_id: str,
        total_days: int,
        ranging_days: int,
        trending_up_days: int,
        trending_down_days: int,
        ranging_count: int,
        trending_up_count: int,
        trending_down_count: int,
        status_ranges: List[Dict],
        duration_ms: int,
    ) -> TestResult:
        """创建测试结果"""
        test_result = TestResult(
            id=self._generate_uuid(),
            test_case_id=test_case_id,
            total_days=total_days,
            ranging_days=ranging_days,
            trending_up_days=trending_up_days,
            trending_down_days=trending_down_days,
            ranging_count=ranging_count,
            trending_up_count=trending_up_count,
            trending_down_count=trending_down_count,
            status_ranges=status_ranges,
            executed_at=self._get_now(),
            duration_ms=duration_ms,
        )
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO test_results 
            (id, test_case_id, total_days, ranging_days, trending_up_days, 
             trending_down_days, ranging_count, trending_up_count, trending_down_count,
             status_ranges, executed_at, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            test_result.id,
            test_result.test_case_id,
            test_result.total_days,
            test_result.ranging_days,
            test_result.trending_up_days,
            test_result.trending_down_days,
            test_result.ranging_count,
            test_result.trending_up_count,
            test_result.trending_down_count,
            json.dumps(test_result.status_ranges),
            test_result.executed_at,
            test_result.duration_ms,
        ))
        
        conn.commit()
        conn.close()
        
        return test_result
    
    def get_test_result(self, test_result_id: str) -> Optional[TestResult]:
        """获取单个测试结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM test_results WHERE id = ?', (test_result_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return None
        
        return self._row_to_test_result(row)
    
    def get_test_result_by_case(self, test_case_id: str) -> Optional[TestResult]:
        """根据测试用例ID获取最新的测试结果"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM test_results 
            WHERE test_case_id = ? 
            ORDER BY executed_at DESC 
            LIMIT 1
        ''', (test_case_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return None
        
        return self._row_to_test_result(row)
    
    def _row_to_test_result(self, row: sqlite3.Row) -> TestResult:
        """将数据库行转换为TestResult对象"""
        return TestResult(
            id=row['id'],
            test_case_id=row['test_case_id'],
            total_days=row['total_days'],
            ranging_days=row['ranging_days'],
            trending_up_days=row['trending_up_days'],
            trending_down_days=row['trending_down_days'],
            ranging_count=row['ranging_count'],
            trending_up_count=row['trending_up_count'],
            trending_down_count=row['trending_down_count'],
            status_ranges=json.loads(row['status_ranges']) if row['status_ranges'] else [],
            executed_at=row['executed_at'],
            duration_ms=row['duration_ms'],
        )
    
    def create_daily_statuses(self, test_result_id: str, daily_statuses: List[Dict]):
        """批量创建每日状态"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        for ds in daily_statuses:
            cursor.execute('''
                INSERT INTO daily_statuses 
                (id, test_result_id, date, status, confidence, reason,
                 open_price, close_price, high_price, low_price, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                self._generate_uuid(),
                test_result_id,
                ds['date'],
                ds['status'],
                ds.get('confidence', 1.0),
                ds.get('reason', ''),
                ds['open_price'],
                ds['close_price'],
                ds['high_price'],
                ds['low_price'],
                ds['volume'],
            ))
        
        conn.commit()
        conn.close()
    
    def get_daily_statuses(self, test_result_id: str) -> List[DailyStatus]:
        """获取测试结果的所有每日状态"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM daily_statuses 
            WHERE test_result_id = ? 
            ORDER BY date ASC
        ''', (test_result_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_daily_status(row) for row in rows]
    
    def _row_to_daily_status(self, row: sqlite3.Row) -> DailyStatus:
        """将数据库行转换为DailyStatus对象"""
        return DailyStatus(
            id=row['id'],
            test_result_id=row['test_result_id'],
            date=row['date'],
            status=row['status'],
            confidence=row['confidence'],
            reason=row['reason'],
            open_price=row['open_price'],
            close_price=row['close_price'],
            high_price=row['high_price'],
            low_price=row['low_price'],
            volume=row['volume'],
        )
    
    def get_statistics(self, test_result_id: str) -> Dict:
        """获取测试结果的统计信息"""
        result = self.get_test_result(test_result_id)
        if result is None:
            return {}
        
        total = result.total_days
        return {
            'total_days': total,
            'ranging_days': result.ranging_days,
            'ranging_percent': round(result.ranging_days / total * 100, 1) if total > 0 else 0,
            'trending_up_days': result.trending_up_days,
            'trending_up_percent': round(result.trending_up_days / total * 100, 1) if total > 0 else 0,
            'trending_down_days': result.trending_down_days,
            'trending_down_percent': round(result.trending_down_days / total * 100, 1) if total > 0 else 0,
            'ranging_count': result.ranging_count,
            'trending_up_count': result.trending_up_count,
            'trending_down_count': result.trending_down_count,
            'duration_ms': result.duration_ms,
            'executed_at': result.executed_at,
        }
    
    def count_test_cases(self, symbol: str = None, algorithm: str = None, status: str = None) -> int:
        """统计测试用例数量"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        sql = 'SELECT COUNT(*) FROM test_cases WHERE 1=1'
        params = []
        
        if symbol:
            sql += ' AND symbol = ?'
            params.append(symbol)
        
        if algorithm:
            sql += ' AND algorithm = ?'
            params.append(algorithm)
        
        if status:
            sql += ' AND status = ?'
            params.append(status)
        
        cursor.execute(sql, params)
        count = cursor.fetchone()[0]
        conn.close()
        
        return count


if __name__ == '__main__':
    db = MarketVisualizerDB()
    print(f"数据库已创建: {db.db_path}")
    
    test_case = db.create_test_case(
        name='测试用例1',
        symbol='BTCUSDT',
        interval='1d',
        start_date='2023-01-01',
        end_date='2023-03-31',
        algorithm='dual_thrust',
        algorithm_config={'k2_down_factor': 0.6, 'down_confirm_days': 1},
        description='这是一个测试用例',
    )
    print(f"创建测试用例: {test_case.id}")
    
    cases = db.get_test_cases()
    print(f"测试用例列表: {len(cases)} 条")

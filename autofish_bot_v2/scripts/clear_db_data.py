#!/usr/bin/env python3
"""数据清理脚本"""

import sqlite3
from pathlib import Path

conn = sqlite3.connect('database/test_results.db')
cursor = conn.cursor()

print('=== 清空前数据统计 ===')
tables = ['test_plans', 'test_scenarios', 'test_executions', 'test_params', 'test_results', 'trade_details', 'visualizer_cases', 'visualizer_results', 'visualizer_daily_statuses', 'optimizer_results', 'optimizer_history']
for table in tables:
    cursor.execute(f'SELECT COUNT(*) FROM {table}')
    count = cursor.fetchone()[0]
    print(f'{table}: {count} 条记录')

print('\n=== 清空数据 ===')
for table in tables:
    cursor.execute(f'DELETE FROM {table}')
conn.commit()

print('\n=== 清空后数据统计 ===')
for table in tables:
    cursor.execute(f'SELECT COUNT(*) FROM {table}')
    count = cursor.fetchone()[0]
    print(f'{table}: {count} 条记录')

print('\n=== 验证表结构 ===')
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
db_tables = [row[0] for row in cursor.fetchall()]
print(f'数据库表: {db_tables}')

conn.close()
print('\n✅ 数据清理完成')

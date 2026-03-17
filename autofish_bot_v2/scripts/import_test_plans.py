#!/usr/bin/env python3
"""导入测试计划 JSON 文件到数据库"""

import json
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

def import_test_plans():
    plans_dir = Path('out/test_plans/active')
    backup_dir = Path('out/test_old_bak')
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect('database/test_results.db')
    cursor = conn.cursor()
    
    plan_files = list(plans_dir.glob('*.json'))
    print(f'找到 {len(plan_files)} 个测试计划文件')
    
    imported = 0
    for plan_file in plan_files:
        try:
            with open(plan_file, 'r', encoding='utf-8') as f:
                plan_data = json.load(f)
            
            plan_id = plan_data.get('plan_id')
            plan_name = plan_data.get('plan_name', plan_id)
            test_type = plan_data.get('test_type', 'backtest')
            description = plan_data.get('description', '')
            status = plan_data.get('status', 'active')
            created_at = plan_data.get('created_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            
            cursor.execute("""
                INSERT OR REPLACE INTO test_plans 
                (plan_id, plan_name, test_type, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (plan_id, plan_name, test_type, description, status, created_at, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            
            scenarios = plan_data.get('test_scenarios', [])
            for scenario in scenarios:
                scenario_id = scenario.get('scenario_id')
                scenario_name = scenario.get('name', scenario_id)
                params_json = json.dumps(scenario.get('params', {}), ensure_ascii=False)
                
                cursor.execute("""
                    INSERT OR REPLACE INTO test_scenarios
                    (plan_id, scenario_id, scenario_name, params_json)
                    VALUES (?, ?, ?, ?)
                """, (plan_id, scenario_id, scenario_name, params_json))
            
            print(f'导入: {plan_id} - {plan_name} ({len(scenarios)} 个场景)')
            imported += 1
            
        except Exception as e:
            print(f'导入失败: {plan_file.name} - {e}')
    
    conn.commit()
    conn.close()
    
    print(f'\n成功导入 {imported}/{len(plan_files)} 个测试计划')
    
    print('\n=== 备份 JSON 文件 ===')
    for plan_file in plan_files:
        backup_path = backup_dir / plan_file.name
        shutil.copy2(plan_file, backup_path)
        print(f'备份: {plan_file.name} -> {backup_path}')
    
    print(f'\n✅ 完成！备份目录: {backup_dir}')

if __name__ == '__main__':
    import_test_plans()

#!/usr/bin/env python3
"""
数据迁移脚本：从备份的 JSON 文件导入测试计划到数据库

用法:
    python scripts/migrate_test_plans.py
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

# 配置
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "database/test_results.db"
BACKUP_DIR = BASE_DIR / "out/test_old_bak"

# 默认执行配置
DEFAULT_EXECUTIONS = {
    "backtest": {
        "executor": "binance_backtest.py",
        "command_template": "python3 binance_backtest.py --symbol {symbol} --date-range {date_range} --decay-factor {decay_factor} --stop-loss {stop_loss} --total-amount {total_amount} --output-dir {output_dir}"
    },
    "market_aware": {
        "executor": "market_aware_backtest.py",
        "command_template": "python3 market_aware_backtest.py --symbol {symbol} --date-range {date_range} --market-algorithm {market_algorithm} --decay-factor {decay_factor} --stop-loss {stop_loss} --total-amount {total_amount} --output-dir {output_dir}"
    },
    "visualizer": {
        "executor": "market_status_visualizer.py",
        "command_template": "python3 market_status_visualizer.py --symbol {symbol} --interval {interval} --date-range {date_range} --algorithm {algorithm} --down-confirm-days {down_confirm_days} --k2-down-factor {k2_down_factor} --generate-all"
    },
    "optimization": {
        "executor": "optuna_dual_thrust_optimizer.py",
        "command_template": "python3 optuna_dual_thrust_optimizer.py --symbol {symbol} --date-range {date_range} --output-dir {output_dir}"
    }
}


def clear_database(conn):
    """清空数据库表"""
    cursor = conn.cursor()
    
    print("清空 test_scenarios 表...")
    cursor.execute("DELETE FROM test_scenarios")
    
    print("清空 test_plans 表...")
    cursor.execute("DELETE FROM test_plans")
    
    conn.commit()
    print("数据库表已清空")


def import_plan(conn, plan_data):
    """导入单个测试计划"""
    cursor = conn.cursor()
    
    plan_id = plan_data["plan_id"]
    plan_name = plan_data["plan_name"]
    description = plan_data.get("description", "")
    test_type = plan_data["test_type"]
    status = plan_data.get("status", "active")
    created_at = plan_data.get("created_at", datetime.now().isoformat())
    updated_at = created_at
    
    # 处理 JSON 字段
    test_objective = json.dumps(plan_data.get("test_objective", {}))
    test_parameters = json.dumps(plan_data.get("test_parameters", {}))
    
    # 获取执行配置
    execution_config = plan_data.get("execution", DEFAULT_EXECUTIONS.get(test_type, {}))
    execution = json.dumps(execution_config)
    
    # 插入 test_plans 表
    cursor.execute("""
        INSERT INTO test_plans (plan_id, plan_name, test_type, description, status, created_at, updated_at, test_objective, test_parameters, execution)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (plan_id, plan_name, test_type, description, status, created_at, updated_at, test_objective, test_parameters, execution))
    
    # 导入测试场景
    scenarios = plan_data.get("test_scenarios", [])
    for scenario in scenarios:
        scenario_id = scenario["scenario_id"]
        scenario_name = scenario.get("name", "")
        params_json = json.dumps(scenario.get("params", {}))
        
        cursor.execute("""
            INSERT INTO test_scenarios (plan_id, scenario_id, scenario_name, params_json)
            VALUES (?, ?, ?, ?)
        """, (plan_id, scenario_id, scenario_name, params_json))
    
    conn.commit()
    print(f"已导入测试计划: {plan_id} - {plan_name} ({len(scenarios)} 个场景)")


def verify_import(conn):
    """验证导入结果"""
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM test_plans")
    plan_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM test_scenarios")
    scenario_count = cursor.fetchone()[0]
    
    print(f"\n验证结果:")
    print(f"  测试计划数量: {plan_count}")
    print(f"  测试场景数量: {scenario_count}")
    
    # 显示每个测试计划的详情
    cursor.execute("SELECT plan_id, plan_name, test_type, status FROM test_plans ORDER BY plan_id")
    plans = cursor.fetchall()
    print(f"\n测试计划列表:")
    for plan in plans:
        print(f"  {plan[0]} | {plan[1]} | {plan[2]} | {plan[3]}")


def main():
    print("=" * 60)
    print("测试计划数据迁移脚本")
    print("=" * 60)
    
    # 连接数据库
    if not os.path.exists(DB_PATH):
        print(f"错误: 数据库文件不存在: {DB_PATH}")
        sys.exit(1)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        # 清空数据库
        clear_database(conn)
        
        # 查找备份的 JSON 文件
        json_files = list(BACKUP_DIR.glob("TP*.json"))
        print(f"\n找到 {len(json_files)} 个备份文件:")
        
        for json_file in json_files:
            print(f"\n处理文件: {json_file.name}")
            with open(json_file, 'r', encoding='utf-8') as f:
                plan_data = json.load(f)
            
            import_plan(conn, plan_data)
        
        # 验证导入结果
        verify_import(conn)
        
        print("\n" + "=" * 60)
        print("数据迁移完成!")
        print("=" * 60)
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == "__main__":
    main()

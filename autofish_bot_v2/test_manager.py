#!/usr/bin/env python3
"""
测试管理系统 - CLI， WebServer

功能:
1. 测试计划管理: 创建、读取、更新、归档
2. 测试执行: 按计划执行测试场景
3. 结果记录: 统一格式记录测试结果
4. 历史管理: 测试历史索引和查询
5. 对比分析: 多组测试结果对比

使用示例:
    # 创建测试计划
    python test_manager.py create-plan --name "行情感知测试" --type market_aware --symbol BTCUSDT
    
    # 执行测试计划
    python test_manager.py run-plan --plan-id TP001
    
    # 查看历史
    python test_manager.py history --symbol BTCUSDT
"""

import os
import sys
import json
import argparse
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from datetime import datetime
import json

from database.test_results_db import TestResultsDB, TestCase, TestResult, TradeDetail

# 配置日志
def setup_logging():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / 'test_manager.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


class TestType(str, Enum):
    BACKTEST = "backtest"
    MARKET_AWARE = "market_aware"
    VISUALIZER = "visualizer"
    OPTIMIZATION = "optimization"
    AMPLITUDE = "amplitude"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RUNNING = "running"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass
class TestScenario:
    scenario_id: str
    name: str
    params: Dict[str, Any]
    expected_output: List[str] = field(default_factory=list)


@dataclass
class TestPlan:
    plan_id: str
    plan_name: str
    description: str
    test_type: str
    status: str
    created_at: str
    test_objective: Dict[str, Any]
    test_parameters: Dict[str, Any]
    test_scenarios: List[Dict[str, Any]] = field(default_factory=list)
    expected_results: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""
    search_space: Dict[str, Any] = field(default_factory=dict)
    optimization_target: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TestPlan':
        known_fields = {
            'plan_id', 'plan_name', 'description', 'test_type', 'status',
            'created_at', 'test_objective', 'test_parameters', 'test_scenarios',
            'expected_results', 'execution', 'updated_at', 'search_space',
            'optimization_target'
        }
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        
        # 设置默认值
        if 'test_objective' not in filtered_data:
            filtered_data['test_objective'] = {}
        if 'test_parameters' not in filtered_data:
            filtered_data['test_parameters'] = {}
        
        return cls(**filtered_data)


class TestManager:
    """测试管理器"""
    
    OUTPUT_DIR = "out"
    TEST_PLANS_DIR = "test_plans"
    TEST_HISTORY_DIR = "test_history"
    TEST_COMPARISON_DIR = "test_comparison"
    
    TEST_TYPE_DIRS = {
        TestType.BACKTEST: "backtest",
        TestType.MARKET_AWARE: "market_aware",
        TestType.VISUALIZER: "visualizer",
        TestType.OPTIMIZATION: "optimization",
        TestType.AMPLITUDE: "amplitude",
    }
    
    EXECUTORS = {
        TestType.BACKTEST: "binance_backtest.py",
        TestType.MARKET_AWARE: "binance_backtest.py",
        TestType.VISUALIZER: "market_status_visualizer.py",
        TestType.OPTIMIZATION: "optuna_dual_thrust_optimizer.py",
        TestType.AMPLITUDE: "autofish_core.py",
    }
    
    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir or os.path.dirname(os.path.abspath(__file__)))
        self.output_dir = self.base_dir / self.OUTPUT_DIR
        self.db = TestResultsDB(str(self.base_dir / "database/test_results.db"))
        self._ensure_directories()
        logger.info(f"TestManager 初始化完成, base_dir={self.base_dir}")
    
    def _ensure_directories(self):
        for dir_name in ["test_report", self.TEST_HISTORY_DIR, self.TEST_COMPARISON_DIR]:
            dir_path = self.output_dir / dir_name
            dir_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"目录结构已确保存在")
    
    def _get_next_plan_id(self) -> str:
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT MAX(CAST(SUBSTR(plan_id, 3) AS INTEGER)) as max_id FROM test_plans")
        row = cursor.fetchone()
        conn.close()
        
        max_id = row['max_id'] if row and row['max_id'] else 0
        return f"TP{max_id + 1:03d}"
    
    def create_plan(self, name: str, test_type: str, description: str = "",
                    parameters: Dict[str, Any] = None, scenarios: List[Dict[str, Any]] = None,
                    objective: Dict[str, Any] = None) -> TestPlan:
        logger.info(f"创建测试计划: name={name}, test_type={test_type}")
        plan_id = self._get_next_plan_id()
        logger.debug(f"生成计划ID: {plan_id}")
        now = datetime.now().isoformat()
        
        test_parameters = parameters or {}
        test_scenarios = scenarios or []
        test_objective = objective or {"primary": description}
        
        executor = self.EXECUTORS.get(TestType(test_type), "unknown.py")
        
        plan = TestPlan(
            plan_id=plan_id,
            plan_name=name,
            description=description,
            test_type=test_type,
            status=PlanStatus.ACTIVE.value,
            created_at=now,
            test_objective=test_objective,
            test_parameters=test_parameters,
            test_scenarios=test_scenarios,
            expected_results={"metrics": []},
            execution={"executor": executor, "command_template": ""},
            updated_at=now
        )
        
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO test_plans (plan_id, plan_name, test_type, description, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (plan_id, name, test_type, description, 'active', now, now))
        
        for scenario in test_scenarios:
            cursor.execute("""
                INSERT INTO test_scenarios (plan_id, scenario_id, scenario_name, params_json)
                VALUES (?, ?, ?, ?)
            """, (plan_id, scenario['scenario_id'], scenario.get('name', ''), json.dumps(scenario.get('params', {}))))
        
        conn.commit()
        conn.close()
        
        logger.info(f"测试计划创建成功: plan_id={plan_id}, name={name}")
        return plan
    
    def load_plan(self, plan_id: str) -> Optional[TestPlan]:
        logger.debug(f"加载测试计划: plan_id={plan_id}")
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM test_plans WHERE plan_id = ?", (plan_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return None
        
        plan_data = dict(row)
        
        # 解析 JSON 字段
        if plan_data.get('test_objective'):
            plan_data['test_objective'] = json.loads(plan_data['test_objective'])
        else:
            plan_data['test_objective'] = {}
        
        if plan_data.get('test_parameters'):
            plan_data['test_parameters'] = json.loads(plan_data['test_parameters'])
        else:
            plan_data['test_parameters'] = {}
        
        # 解析 execution 字段
        if plan_data.get('execution'):
            plan_data['execution'] = json.loads(plan_data['execution'])
        else:
            plan_data['execution'] = {}
        
        cursor.execute("SELECT * FROM test_scenarios WHERE plan_id = ?", (plan_id,))
        scenarios = []
        for s in cursor.fetchall():
            scenarios.append({
                'scenario_id': s['scenario_id'],
                'name': s['scenario_name'],
                'params': json.loads(s['params_json']) if s['params_json'] else {}
            })
        
        conn.close()
        
        plan_data['test_scenarios'] = scenarios
        
        logger.debug(f"测试计划加载成功: plan_id={plan_id}, scenarios_count={len(scenarios)}")
        return TestPlan.from_dict(plan_data)
    
    def list_plans(self, status: str = None) -> List[TestPlan]:
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        if status:
            cursor.execute("SELECT * FROM test_plans WHERE status = ? ORDER BY created_at DESC", (status,))
        else:
            cursor.execute("SELECT * FROM test_plans ORDER BY created_at DESC")
        
        plans = []
        for row in cursor.fetchall():
            plan_data = dict(row)
            
            # 解析 JSON 字段
            if plan_data.get('test_objective'):
                plan_data['test_objective'] = json.loads(plan_data['test_objective'])
            else:
                plan_data['test_objective'] = {}
            
            if plan_data.get('test_parameters'):
                plan_data['test_parameters'] = json.loads(plan_data['test_parameters'])
            else:
                plan_data['test_parameters'] = {}
            
            # 解析 execution 字段
            if plan_data.get('execution'):
                plan_data['execution'] = json.loads(plan_data['execution'])
            else:
                plan_data['execution'] = {}
            
            cursor.execute("SELECT * FROM test_scenarios WHERE plan_id = ?", (plan_data['plan_id'],))
            scenarios = []
            for s in cursor.fetchall():
                scenarios.append({
                    'scenario_id': s['scenario_id'],
                    'name': s['scenario_name'],
                    'params': json.loads(s['params_json']) if s['params_json'] else {}
                })
            plan_data['test_scenarios'] = scenarios
            plans.append(TestPlan.from_dict(plan_data))
        
        conn.close()
        return plans
    
    def update_plan_status(self, plan_id: str, new_status: str) -> Optional[TestPlan]:
        plan = self.load_plan(plan_id)
        if not plan:
            return None
        
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE test_plans SET status = ?, updated_at = ? WHERE plan_id = ?",
            (new_status, datetime.now().isoformat(), plan_id)
        )
        conn.commit()
        conn.close()
        
        return self.load_plan(plan_id)
    
    def get_report_dir(self, test_type: str) -> Path:
        type_dir = self.TEST_TYPE_DIRS.get(TestType(test_type), "other")
        return self.output_dir / "test_report" / type_dir
    
    def save_result(self, plan: TestPlan, scenario: Dict[str, Any], 
                    result_data: Dict[str, Any], output_files: List[str] = None) -> str:
        results_dir = self.get_report_dir(plan.test_type) / plan.plan_id
        results_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_id = f"{plan.plan_id}_{scenario['scenario_id']}_{timestamp}"
        
        result_content = self._generate_result_markdown(plan, scenario, result_data, output_files)
        result_file = results_dir / f"{plan.plan_id}_{scenario['scenario_id']}_result.md"
        
        with open(result_file, 'w', encoding='utf-8') as f:
            f.write(result_content)
        
        self._update_history(plan, scenario, result_data)
        
        return str(result_file)
    
    def _generate_result_markdown(self, plan: TestPlan, scenario: Dict[str, Any],
                                   result_data: Dict[str, Any], output_files: List[str] = None) -> str:
        lines = [
            f"# 测试结果报告",
            "",
            "## 测试信息",
            "",
            "| 项目 | 值 |",
            "|------|-----|",
            f"| 测试计划 | {plan.plan_id} - {plan.plan_name} |",
            f"| 测试场景 | {scenario['scenario_id']} - {scenario['name']} |",
            f"| 测试类型 | {plan.test_type} |",
            f"| 执行时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |",
            "",
            "## 测试参数",
            "",
            "| 参数 | 值 |",
            "|------|-----|",
        ]
        
        for key, value in plan.test_parameters.items():
            lines.append(f"| {key} | {value} |")
        
        for key, value in scenario.get('params', {}).items():
            lines.append(f"| {key} | {value} |")
        
        lines.extend([
            "",
            "## 测试结果",
            "",
            "### 核心指标",
            "",
            "| 指标 | 值 |",
            "|------|-----|",
        ])
        
        for key, value in result_data.items():
            lines.append(f"| {key} | {value} |")
        
        if output_files:
            lines.extend([
                "",
                "## 输出文件",
                "",
            ])
            for f in output_files:
                lines.append(f"- {f}")
        
        lines.extend([
            "",
            "---",
            f"测试ID: {plan.plan_id}_{scenario['scenario_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        ])
        
        return "\n".join(lines)
    
    def _update_history(self, plan: TestPlan, scenario: Dict[str, Any], 
                        result_data: Dict[str, Any]):
        history_dir = self.output_dir / self.TEST_HISTORY_DIR
        history_dir.mkdir(parents=True, exist_ok=True)
        
        symbol = plan.test_parameters.get('symbol', 'UNKNOWN')
        history_file = history_dir / f"{symbol}_history.md"
        
        if not history_file.exists():
            header = [
                f"# {symbol} 测试历史",
                "",
                "## 测试记录",
                "",
                "| 测试ID | 日期 | 测试计划 | 类型 | 核心指标 |",
                "|--------|------|----------|------|----------|",
            ]
            with open(history_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(header) + "\n")
        
        metrics_str = ", ".join([f"{k}: {v}" for k, v in list(result_data.items())[:3]])
        
        with open(history_file, 'a', encoding='utf-8') as f:
            f.write(f"| {plan.plan_id}_{scenario['scenario_id']} | {datetime.now().strftime('%Y-%m-%d')} | {plan.plan_name} | {plan.test_type} | {metrics_str} |\n")
    
    def generate_summary(self, plan_id: str) -> Optional[str]:
        plan = self.load_plan(plan_id)
        if not plan:
            return None
        
        results_dir = self.get_report_dir(plan.test_type) / plan.plan_id
        summary_file = results_dir / f"{plan.plan_id}_summary.md"
        
        lines = [
            f"# 测试计划汇总报告",
            "",
            "## 测试计划信息",
            "",
            "| 项目 | 值 |",
            "|------|-----|",
            f"| 测试计划 | {plan.plan_id} - {plan.plan_name} |",
            f"| 测试类型 | {plan.test_type} |",
            f"| 创建时间 | {plan.created_at} |",
            f"| 状态 | {plan.status} |",
            "",
            "## 测试场景结果",
            "",
            "| 场景 | 状态 | 核心指标 |",
            "|------|------|----------|",
        ]
        
        for scenario in plan.test_scenarios:
            result_file = results_dir / f"{plan.plan_id}_{scenario['scenario_id']}_result.md"
            status = "✅ 已完成" if result_file.exists() else "⏳ 待执行"
            lines.append(f"| {scenario['scenario_id']} - {scenario['name']} | {status} | - |")
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        
        return str(summary_file)
    
    def compare_results(self, plan_id: str, scenario_ids: List[str] = None) -> str:
        plan = self.load_plan(plan_id)
        if not plan:
            raise ValueError(f"测试计划不存在: {plan_id}")
        
        results_dir = self.get_report_dir(plan.test_type) / plan.plan_id
        
        comparison_id = f"CMP_{plan_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        comparison_file = self.output_dir / self.TEST_COMPARISON_DIR / f"{comparison_id}.md"
        
        lines = [
            f"# 测试对比报告",
            "",
            "## 对比信息",
            "",
            "| 项目 | 值 |",
            "|------|-----|",
            f"| 对比ID | {comparison_id} |",
            f"| 测试计划 | {plan.plan_id} - {plan.plan_name} |",
            f"| 创建时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |",
            "",
            "## 场景对比",
            "",
            "| 场景 | 核心指标 |",
            "|------|----------|",
        ]
        
        scenarios = plan.test_scenarios
        if scenario_ids:
            scenarios = [s for s in scenarios if s['scenario_id'] in scenario_ids]
        
        for scenario in scenarios:
            result_file = results_dir / f"{plan.plan_id}_{scenario['scenario_id']}_result.md"
            if result_file.exists():
                lines.append(f"| {scenario['scenario_id']} - {scenario['name']} | [查看]({result_file.name}) |")
            else:
                lines.append(f"| {scenario['scenario_id']} - {scenario['name']} | 未执行 |")
        
        with open(comparison_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        
        return str(comparison_file)
    
    def run_plan(self, plan_id: str, scenario_id: str = None, dry_run: bool = False) -> List[str]:
        """执行测试计划
        
        参数:
            plan_id: 测试计划ID
            scenario_id: 指定场景ID，不指定则执行所有场景
            dry_run: 只显示命令，不执行
            
        返回:
            执行的命令列表
        """
        logger.info(f"执行测试计划: plan_id={plan_id}, scenario_id={scenario_id}, dry_run={dry_run}")
        plan = self.load_plan(plan_id)
        if not plan:
            logger.error(f"测试计划不存在: {plan_id}")
            raise ValueError(f"测试计划不存在: {plan_id}")
        
        executor = plan.execution.get("executor", "")
        command_template = plan.execution.get("command_template", "")
        
        if not executor or not command_template:
            logger.error(f"测试计划缺少执行配置: executor={executor}, command_template={command_template}")
            raise ValueError(f"测试计划缺少执行配置")
        
        results_dir = self.get_report_dir(plan.test_type) / plan.plan_id
        
        scenarios = plan.test_scenarios
        if scenario_id:
            scenarios = [s for s in scenarios if s.get("scenario_id") == scenario_id]
        
        logger.info(f"准备执行 {len(scenarios)} 个场景")
        executed_commands = []
        
        for scenario in scenarios:
            logger.info(f"执行场景: {scenario.get('scenario_id')} - {scenario.get('name')}")
            scenario_output_dir = results_dir / f"{plan.plan_id}_{scenario['scenario_id']}_raw"
            scenario_output_dir.mkdir(parents=True, exist_ok=True)
            
            params = {**plan.test_parameters, **scenario.get("params", {})}
            
            command = command_template
            for key, value in params.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    value = ",".join(str(v) for v in value)
                command = command.replace(f"{{{key}}}", str(value))
            
            command = command.replace("{symbol}", params.get("symbol", ""))
            command = command.replace("{date_range}", params.get("date_range", ""))
            command = command.replace("{output_dir}", str(scenario_output_dir))
            
            import re
            command = re.sub(r'\{[a-zA-Z_][a-zA-Z0-9_]*\}', '', command)
            
            print(f"\n{'='*60}")
            print(f"[{plan.plan_id}] 执行场景: {scenario.get('scenario_id')} - {scenario.get('name')}")
            print(f"输出目录: {scenario_output_dir}")
            print(f"{'='*60}")
            print(f"命令: {command}")
            
            if dry_run:
                print("(dry-run) 跳过执行")
                executed_commands.append(command)
                continue
            
            try:
                result = subprocess.run(command, shell=True, cwd=str(self.base_dir))
                if result.returncode == 0:
                    logger.info(f"场景 {scenario.get('scenario_id')} 执行成功")
                    print(f"✅ 场景 {scenario.get('scenario_id')} 执行成功")
                    print(f"📁 结果已保存到: {scenario_output_dir}")
                else:
                    logger.error(f"场景 {scenario.get('scenario_id')} 执行失败，返回码: {result.returncode}")
                    print(f"❌ 场景 {scenario.get('scenario_id')} 执行失败，返回码: {result.returncode}")
            except Exception as e:
                logger.exception(f"执行异常: {e}")
                print(f"❌ 执行异常: {e}")
            
            executed_commands.append(command)
        
        return executed_commands


def _export_report(args):
    """导出报告"""
    db = TestResultsDB()
    report_id = args.id
    report_type = args.type
    output_path = args.output
    
    if not report_type:
        if report_id.startswith("VR_"):
            report_type = "visualizer"
        elif report_id.startswith("OPT_"):
            report_type = "optimizer"
        elif report_id.startswith("LP_"):
            report_type = "longport"
        else:
            result = db.get_result(report_id)
            if result:
                test_type = result.get('test_type', 'backtest')
                if test_type == 'market_aware':
                    report_type = "market_aware"
                else:
                    report_type = "backtest"
            else:
                print(f"❌ 未找到ID: {report_id}")
                return
    
    base_dir = Path("out/test_report")
    type_dir = base_dir / report_type
    type_dir.mkdir(parents=True, exist_ok=True)
    
    if report_type in ["backtest", "market_aware", "longport"]:
        result = db.get_result(report_id)
        if not result:
            print(f"❌ 未找到执行记录: {report_id}")
            return
        
        symbol = result.get('symbol', 'UNKNOWN')
        start_time = result.get('start_time', '')
        end_time = result.get('end_time', '')
        
        if start_time and end_time:
            date_range = f"{start_time[:10].replace('-', '')}-{end_time[:10].replace('-', '')}"
        else:
            date_range = "unknown"
        
        base_name = f"{symbol}_{date_range}_{report_id}"
        
        if args.format in ["md", "all"]:
            if not output_path:
                output_path = str(type_dir / f"{base_name}.md")
            
            report = db.generate_report(report_id)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"✅ MD报告已导出到: {output_path}")
        
        if args.format in ["csv", "all"]:
            trades = db.get_trade_details(report_id)
            if trades:
                csv_path = str(type_dir / f"{base_name}_trades.csv")
                import csv
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['trade_seq', 'level', 'entry_price', 'exit_price', 'trade_type', 'profit', 'entry_time', 'exit_time'])
                    for t in trades:
                        writer.writerow([
                            t.get('trade_seq', 0),
                            t.get('level', ''),
                            t.get('entry_price', 0),
                            t.get('exit_price', 0),
                            t.get('trade_type', ''),
                            t.get('profit', 0),
                            t.get('entry_time', ''),
                            t.get('exit_time', '')
                        ])
                print(f"✅ CSV交易明细已导出到: {csv_path}")
    
    elif report_type == "visualizer":
        result = db.get_visualizer_result(report_id)
        if not result:
            print(f"❌ 未找到可视化结果: {report_id}")
            return
        
        symbol = result.get('symbol', 'UNKNOWN')
        algorithm = result.get('algorithm', 'unknown')
        algorithm_display = algorithm.replace('_', '').title()
        
        case_id = result.get('case_id', '')
        case = db.get_visualizer_case(case_id) if case_id else None
        if case:
            start_date = case.get('start_date', '')
            end_date = case.get('end_date', '')
            date_range = f"{start_date.replace('-', '')}-{end_date.replace('-', '')}"
        else:
            date_range = "unknown"
        
        base_name = f"{symbol}_{date_range}_{algorithm_display}_{report_id}"
        
        if args.format in ["md", "all"]:
            if not output_path:
                output_path = str(type_dir / f"{base_name}.md")
            
            lines = []
            lines.append(f"# {symbol} 行情分析报告\n")
            lines.append(f"**结果ID**: {report_id}")
            lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            lines.append("---\n")
            lines.append("## 基本信息\n")
            lines.append("| 项目 | 值 |")
            lines.append("|------|-----|")
            lines.append(f"| 交易对 | {symbol} |")
            lines.append(f"| 分析算法 | {algorithm_display} |")
            lines.append(f"| 总天数 | {result.get('total_days', 0)} |")
            lines.append(f"| 震荡天数 | {result.get('ranging_days', 0)} ({result.get('ranging_days', 0) / max(result.get('total_days', 1), 1) * 100:.1f}%) |")
            lines.append(f"| 上涨天数 | {result.get('trending_up_days', 0)} |")
            lines.append(f"| 下跌天数 | {result.get('trending_down_days', 0)} |\n")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"✅ MD报告已导出到: {output_path}")
        
        if args.format in ["csv", "all"]:
            daily_statuses = db.get_visualizer_daily_statuses(report_id)
            if daily_statuses:
                csv_path = str(type_dir / f"{base_name}_daily.csv")
                import csv
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['date', 'status', 'confidence', 'reason', 'open_price', 'close_price', 'high_price', 'low_price', 'volume'])
                    for ds in daily_statuses:
                        writer.writerow([
                            ds.get('date', ''),
                            ds.get('status', ''),
                            ds.get('confidence', 0),
                            ds.get('reason', ''),
                            ds.get('open_price', 0),
                            ds.get('close_price', 0),
                            ds.get('high_price', 0),
                            ds.get('low_price', 0),
                            ds.get('volume', 0)
                        ])
                print(f"✅ CSV每日状态已导出到: {csv_path}")
    
    elif report_type == "optimizer":
        result = db.get_optimizer_result(report_id)
        if not result:
            print(f"❌ 未找到优化结果: {report_id}")
            return
        
        symbol = result.get('symbol', 'UNKNOWN')
        algorithm = result.get('algorithm', 'unknown')
        algorithm_display = algorithm.replace('_', '').title()
        days = result.get('days', 0)
        date_range = f"{days}d"
        
        base_name = f"{symbol}_{date_range}_{algorithm_display}_{report_id}"
        
        if args.format in ["md", "all"]:
            if not output_path:
                output_path = str(type_dir / f"{base_name}.md")
            
            best_params = result.get('best_params', {})
            
            lines = []
            lines.append(f"# {symbol} 参数优化报告\n")
            lines.append(f"**优化ID**: {report_id}")
            lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            lines.append("---\n")
            lines.append("## 基本信息\n")
            lines.append("| 项目 | 值 |")
            lines.append("|------|-----|")
            lines.append(f"| 交易对 | {symbol} |")
            lines.append(f"| 优化算法 | {algorithm_display} |")
            lines.append(f"| 回测天数 | {days} |")
            lines.append(f"| 优化次数 | {result.get('n_trials', 0)} |")
            lines.append(f"| 最佳收益 | {result.get('best_value', 0) * 100:.2f}% |\n")
            
            lines.append("## 最佳参数配置\n")
            lines.append("```json")
            lines.append(json.dumps(best_params, indent=2, ensure_ascii=False))
            lines.append("```\n")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(f"✅ MD报告已导出到: {output_path}")
        
        if args.format in ["csv", "all"]:
            history = db.get_optimizer_history(report_id)
            if history:
                csv_path = str(type_dir / f"{base_name}_results.csv")
                import csv
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['trial', 'value', 'grid_spacing', 'exit_profit', 'stop_loss', 'decay_factor', 'max_entries'])
                    for h in history:
                        writer.writerow([
                            h.get('trial', 0),
                            h.get('value', 0),
                            h.get('grid_spacing', 0),
                            h.get('exit_profit', 0),
                            h.get('stop_loss', 0),
                            h.get('decay_factor', 0),
                            h.get('max_entries', 0)
                        ])
                print(f"✅ CSV优化结果已导出到: {csv_path}")
    
    _update_readme_index()


def _update_readme_index():
    """更新汇总索引文件"""
    base_dir = Path("out/test_report")
    readme_path = base_dir / "README.md"
    
    db = TestResultsDB()
    
    lines = []
    lines.append("# 测试报告汇总\n")
    lines.append(f"**最后更新**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("---\n")
    
    lines.append("## 统计概览\n")
    lines.append("| 类型 | 报告数量 | 最新报告时间 |")
    lines.append("|------|----------|-------------|")
    
    type_dirs = ['backtest', 'market_aware', 'visualizer', 'optimizer_DualThrust', 'optimizer_Improved', 'longport']
    
    for type_name in type_dirs:
        type_dir = base_dir / type_name
        if type_dir.exists():
            md_files = list(type_dir.glob("*.md"))
            count = len(md_files)
            if count > 0:
                latest = max(f.stat().st_mtime for f in md_files)
                latest_time = datetime.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M:%S')
            else:
                latest_time = "-"
        else:
            count = 0
            latest_time = "-"
        
        lines.append(f"| {type_name} | {count} | {latest_time} |")
    
    lines.append("")
    lines.append("## 最近报告\n")
    
    for type_name in type_dirs:
        type_dir = base_dir / type_name
        if not type_dir.exists():
            continue
        
        md_files = list(type_dir.glob("*.md"))
        if not md_files:
            continue
        
        lines.append(f"### {type_name}\n")
        lines.append("| 报告 | 链接 |")
        lines.append("|------|------|")
        
        for md_file in sorted(md_files, key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
            lines.append(f"| {md_file.stem} | [查看](./{type_name}/{md_file.name}) |")
        
        lines.append("")
    
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"✅ 汇总索引已更新: {readme_path}")


def main():
    parser = argparse.ArgumentParser(description="测试管理系统")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    create_parser = subparsers.add_parser("create-plan", help="创建测试计划")
    create_parser.add_argument("--name", required=True, help="测试计划名称")
    create_parser.add_argument("--type", required=True, choices=[t.value for t in TestType], help="测试类型")
    create_parser.add_argument("--description", default="", help="测试计划描述")
    create_parser.add_argument("--symbol", help="交易标的")
    create_parser.add_argument("--date-range", help="日期范围")
    create_parser.add_argument("--scenarios", help="测试场景JSON文件")
    
    list_parser = subparsers.add_parser("list-plans", help="列出测试计划")
    list_parser.add_argument("--status", choices=[s.value for s in PlanStatus], help="按状态筛选")
    
    show_parser = subparsers.add_parser("show-plan", help="查看测试计划")
    show_parser.add_argument("--plan-id", required=True, help="测试计划ID")
    
    run_parser = subparsers.add_parser("run-plan", help="执行测试计划")
    run_parser.add_argument("--plan-id", required=True, help="测试计划ID")
    run_parser.add_argument("--scenario", help="指定场景ID，不指定则执行所有场景")
    run_parser.add_argument("--dry-run", action="store_true", help="只显示命令，不执行")
    
    summary_parser = subparsers.add_parser("summary", help="生成测试汇总")
    summary_parser.add_argument("--plan-id", required=True, help="测试计划ID")
    
    compare_parser = subparsers.add_parser("compare", help="生成对比报告")
    compare_parser.add_argument("--plan-id", required=True, help="测试计划ID")
    compare_parser.add_argument("--scenarios", help="要对比的场景ID，逗号分隔")
    
    history_parser = subparsers.add_parser("history", help="查看测试历史")
    history_parser.add_argument("--symbol", help="按标的筛选")
    history_parser.add_argument("--type", help="按测试类型筛选")
    
    query_parser = subparsers.add_parser("query-results", help="查询测试结果")
    query_parser.add_argument("--symbol", help="按标的筛选")
    query_parser.add_argument("--type", help="按测试类型筛选")
    query_parser.add_argument("--plan-id", help="按计划ID筛选")
    query_parser.add_argument("--limit", type=int, default=20, help="返回结果数量")
    
    export_parser = subparsers.add_parser("export", help="导出测试报告")
    export_parser.add_argument("id", help="执行ID/结果ID/优化ID")
    export_parser.add_argument("--format", choices=["md", "csv", "png", "html", "all"], default="md", help="导出格式")
    export_parser.add_argument("--type", choices=["backtest", "market_aware", "visualizer", "optimizer", "longport"], 
                               help="报告类型（自动检测时可不指定）")
    export_parser.add_argument("--output", help="输出文件路径（不指定则使用默认路径）")
    
    stats_parser = subparsers.add_parser("stats", help="查看统计数据")
    
    serve_parser = subparsers.add_parser("serve", help="启动Web API服务")
    serve_parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    serve_parser.add_argument("--port", type=int, default=5002, help="监听端口")
    serve_parser.add_argument("--debug", action="store_true", help="调试模式")
    
    args = parser.parse_args()
    
    manager = TestManager()
    
    if args.command == "create-plan":
        parameters = {}
        if args.symbol:
            parameters["symbol"] = args.symbol
        if args.date_range:
            parameters["date_range"] = args.date_range
        
        scenarios = []
        if args.scenarios and os.path.exists(args.scenarios):
            with open(args.scenarios, 'r') as f:
                scenarios = json.load(f)
        
        plan = manager.create_plan(
            name=args.name,
            test_type=args.type,
            description=args.description,
            parameters=parameters,
            scenarios=scenarios
        )
        print(f"✅ 测试计划已创建: {plan.plan_id} - {plan.plan_name}")
        print(f"   状态: {plan.status}")
        print(f"   类型: {plan.test_type}")
    
    elif args.command == "list-plans":
        plans = manager.list_plans(args.status)
        if not plans:
            print("暂无测试计划")
        else:
            print(f"共 {len(plans)} 个测试计划:\n")
            for plan in plans:
                print(f"  {plan.plan_id} | {plan.plan_name} | {plan.test_type} | {plan.status}")
    
    elif args.command == "show-plan":
        plan = manager.load_plan(args.plan_id)
        if plan:
            print(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"❌ 测试计划不存在: {args.plan_id}")
    
    elif args.command == "run-plan":
        try:
            commands = manager.run_plan(args.plan_id, args.scenario, args.dry_run)
            print(f"\n✅ 执行完成，共 {len(commands)} 个场景")
        except ValueError as e:
            logger.error(f"执行测试计划失败: {e}")
            print(f"❌ {e}")
            sys.exit(1)
    
    elif args.command == "summary":
        summary_file = manager.generate_summary(args.plan_id)
        if summary_file:
            print(f"✅ 汇总报告已生成: {summary_file}")
        else:
            print(f"❌ 测试计划不存在: {args.plan_id}")
    
    elif args.command == "compare":
        scenario_ids = args.scenarios.split(",") if args.scenarios else None
        comparison_file = manager.compare_results(args.plan_id, scenario_ids)
        print(f"✅ 对比报告已生成: {comparison_file}")
    
    elif args.command == "history":
        history_dir = manager.output_dir / manager.TEST_HISTORY_DIR
        if args.symbol:
            history_file = history_dir / f"{args.symbol}_history.md"
            if history_file.exists():
                with open(history_file, 'r') as f:
                    print(f.read())
            else:
                print(f"暂无 {args.symbol} 测试历史")
        else:
            for f in history_dir.glob("*_history.md"):
                print(f"\n=== {f.stem} ===")
                with open(f, 'r') as fp:
                    print(fp.read())
    
    elif args.command == "query-results":
        filters = {}
        if args.symbol:
            filters['symbol'] = args.symbol
        if args.type:
            filters['test_type'] = args.type
        if args.plan_id:
            filters['plan_id'] = args.plan_id
        
        db = TestResultsDB()
        results = db.query_results(filters, args.limit)
        
        if not results:
            print("暂无测试结果")
        else:
            print(f"\n共 {len(results)} 条结果:\n")
            for r in results:
                print(f"  {r.get('execution_id')} | {r.get('symbol')} | {r.get('test_type')} | "
                      f"胜率:{r.get('win_rate', 0):.1f}% | 净收益:{r.get('net_profit', 0):.2f} | "
                      f"执行时间:{r.get('executed_at', '')}")
    
    elif args.command == "export":
        _export_report(args)
    
    elif args.command == "stats":
        db = TestResultsDB()
        stats = db.get_statistics()
        
        print("\n📊 测试统计:")
        print(f"  总执行次数: {stats.get('total_executions', 0)}")
        print(f"  成功次数: {stats.get('successful_executions', 0)}")
        print(f"  按类型统计:")
        for t, cnt in stats.get('by_type', {}).items():
            print(f"    - {t}: {cnt}")
        print(f"  按标的统计:")
        for s, cnt in stats.get('by_symbol', {}).items():
            print(f"    - {s}: {cnt}")
        print(f"  平均胜率: {stats.get('avg_win_rate', 0):.1f}%")
        print(f"  平均收益率: {stats.get('avg_roi', 0):.1f}%")
    
    elif args.command == "serve":
        run_server(host=args.host, port=args.port, debug=args.debug)
    
    else:
        parser.print_help()


def create_flask_app():
    """创建 Flask Web API 应用"""
    from flask import Flask, request, jsonify, render_template, send_from_directory
    from flask_cors import CORS
    
    base_dir = Path(__file__).parent
    app = Flask(__name__, 
                template_folder=str(base_dir / 'web/test_results'))
    CORS(app)
    
    db = TestResultsDB()
    
    @app.route('/')
    def index():
        return render_template('index.html')
    
    @app.route('/api/test-results', methods=['GET'])
    def get_test_results():
        try:
            filters = {}
            if request.args.get('symbol'):
                filters['symbol'] = request.args.get('symbol')
            if request.args.get('test_type'):
                filters['test_type'] = request.args.get('test_type')
            if request.args.get('plan_id'):
                filters['plan_id'] = request.args.get('plan_id')
            limit = int(request.args.get('limit', 50))
            results = db.query_results(filters, limit)
            return jsonify({'success': True, 'data': results})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/test-results/<execution_id>', methods=['GET'])
    def get_test_result(execution_id):
        try:
            result = db.get_result(execution_id)
            if not result:
                return jsonify({'success': False, 'error': 'Result not found'})
            return jsonify({'success': True, 'data': result})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/test-results/compare', methods=['GET'])
    def compare_test_results():
        try:
            execution_ids = request.args.get('ids', '').split(',')
            execution_ids = [eid.strip() for eid in execution_ids if eid.strip()]
            if len(execution_ids) < 2:
                return jsonify({'success': False, 'error': 'Need at least 2 execution IDs'})
            comparison = db.compare_results(execution_ids)
            return jsonify({'success': True, 'data': comparison})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/trade-details/<execution_id>', methods=['GET'])
    def get_trade_details(execution_id):
        try:
            trades = db.get_trade_details(execution_id)
            return jsonify({'success': True, 'data': trades})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/reports/<execution_id>', methods=['GET'])
    def get_report(execution_id):
        try:
            format_type = request.args.get('format', 'json')
            if format_type == 'md':
                report = db.generate_report(execution_id)
                return report, 200, {'Content-Type': 'text/markdown'}
            else:
                result = db.get_result(execution_id)
                if not result:
                    return jsonify({'success': False, 'error': 'Result not found'})
                return jsonify({'success': True, 'data': result})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/export/<execution_id>', methods=['POST'])
    def export_result(execution_id):
        try:
            format_type = request.args.get('format', 'md')
            result = db.get_result(execution_id)
            if not result:
                return jsonify({'success': False, 'error': 'Result not found'})
            
            from pathlib import Path
            import csv
            
            base_dir = Path("out/test_report/backtest")
            base_dir.mkdir(parents=True, exist_ok=True)
            
            symbol = result.get('symbol', 'UNKNOWN')
            start_time = result.get('start_time', '')
            end_time = result.get('end_time', '')
            
            if start_time and end_time:
                date_range = f"{start_time[:10].replace('-', '')}-{end_time[:10].replace('-', '')}"
            else:
                date_range = "unknown"
            
            base_name = f"{symbol}_{date_range}_{execution_id}"
            
            if format_type == 'md':
                output_path = base_dir / f"{base_name}.md"
                report = db.generate_report(execution_id)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(report)
                return jsonify({'success': True, 'message': f'报告已导出到 {output_path}', 'path': str(output_path)})
            
            elif format_type == 'csv':
                output_path = base_dir / f"{base_name}_trades.csv"
                trades = db.get_trade_details(execution_id)
                with open(output_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['seq', 'level', 'entry_price', 'exit_price', 'type', 'profit', 'entry_time', 'exit_time'])
                    for t in trades:
                        writer.writerow([t.get('trade_seq'), t.get('level'), t.get('entry_price'), t.get('exit_price'), t.get('trade_type'), t.get('profit'), t.get('entry_time'), t.get('exit_time')])
                return jsonify({'success': True, 'message': f'CSV已导出到 {output_path}', 'path': str(output_path)})
            
            elif format_type == 'all':
                md_path = base_dir / f"{base_name}.md"
                csv_path = base_dir / f"{base_name}_trades.csv"
                
                report = db.generate_report(execution_id)
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(report)
                
                trades = db.get_trade_details(execution_id)
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['trade_seq', 'level', 'entry_price', 'exit_price', 'trade_type', 'profit', 'entry_time', 'exit_time'])
                    for t in trades:
                        writer.writerow([t.get('trade_seq'), t.get('level'), t.get('entry_price'), t.get('exit_price'), t.get('trade_type'), t.get('profit'), t.get('entry_time'), t.get('exit_time')])
                
                return jsonify({'success': True, 'message': f'报告已导出', 'paths': [str(md_path), str(csv_path)]})
            
            else:
                return jsonify({'success': True, 'data': result})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/visualizer-results', methods=['GET'])
    def get_visualizer_results():
        try:
            filters = {}
            if request.args.get('symbol'):
                filters['symbol'] = request.args.get('symbol')
            if request.args.get('algorithm'):
                filters['algorithm'] = request.args.get('algorithm')
            limit = int(request.args.get('limit', 50))
            results = db.query_visualizer_results(filters, limit)
            return jsonify({'success': True, 'data': results})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/visualizer-daily-statuses/<result_id>', methods=['GET'])
    def get_visualizer_daily_statuses(result_id):
        try:
            statuses = db.get_visualizer_daily_statuses(result_id)
            return jsonify({'success': True, 'data': statuses})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/history', methods=['GET'])
    def get_test_history():
        try:
            from pathlib import Path
            from datetime import datetime
            
            symbol = request.args.get('symbol')
            test_type = request.args.get('test_type')
            
            conn = db._get_connection()
            cursor = conn.cursor()
            
            sql = """
                SELECT r.*, e.test_type, e.executed_at
                FROM test_results r
                JOIN test_executions e ON r.execution_id = e.execution_id
                WHERE 1=1
            """
            params = []
            
            if symbol:
                sql += " AND r.symbol = ?"
                params.append(symbol)
            if test_type:
                sql += " AND e.test_type = ?"
                params.append(test_type)
            
            sql += " ORDER BY e.executed_at DESC"
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            
            results = []
            total_tests = len(rows)
            success_count = 0
            total_win_rate = 0
            total_roi = 0
            
            for row in rows:
                r = dict(row)
                results.append(r)
                if r.get('net_profit', 0) > 0:
                    success_count += 1
                total_win_rate += r.get('win_rate', 0)
                total_roi += r.get('roi', 0)
            
            cursor.execute("""
                SELECT symbol, COUNT(*) as count, 
                       AVG(win_rate) as avg_win_rate, 
                       AVG(roi) as avg_roi,
                       AVG(net_profit) as avg_net_profit
                FROM test_results r
                JOIN test_executions e ON r.execution_id = e.execution_id
                GROUP BY symbol
                ORDER BY count DESC
            """)
            by_symbol = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("""
                SELECT e.test_type, COUNT(*) as count,
                       AVG(r.win_rate) as avg_win_rate,
                       AVG(r.roi) as avg_roi,
                       AVG(r.net_profit) as avg_net_profit
                FROM test_results r
                JOIN test_executions e ON r.execution_id = e.execution_id
                GROUP BY e.test_type
                ORDER BY count DESC
            """)
            by_type = [dict(row) for row in cursor.fetchall()]
            
            conn.close()
            
            summary = {
                'total_tests': total_tests,
                'success_count': success_count,
                'failed_count': total_tests - success_count,
                'success_rate': round(success_count / total_tests * 100, 1) if total_tests > 0 else 0,
                'avg_win_rate': round(total_win_rate / total_tests, 1) if total_tests > 0 else 0,
                'avg_roi': round(total_roi / total_tests, 2) if total_tests > 0 else 0
            }
            
            return jsonify({
                'success': True,
                'data': {
                    'summary': summary,
                    'by_symbol': by_symbol,
                    'by_type': by_type,
                    'recent_tests': results[:20]
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/history/export', methods=['GET'])
    def export_test_history():
        try:
            from pathlib import Path
            from datetime import datetime
            
            format_type = request.args.get('format', 'md')
            
            conn = db._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT r.*, e.test_type, e.executed_at
                FROM test_results r
                JOIN test_executions e ON r.execution_id = e.execution_id
                ORDER BY e.executed_at DESC
            """)
            rows = cursor.fetchall()
            
            cursor.execute("""
                SELECT symbol, COUNT(*) as count, 
                       AVG(win_rate) as avg_win_rate, 
                       AVG(roi) as avg_roi
                FROM test_results r
                JOIN test_executions e ON r.execution_id = e.execution_id
                GROUP BY symbol
                ORDER BY count DESC
            """)
            by_symbol = cursor.fetchall()
            
            cursor.execute("""
                SELECT e.test_type, COUNT(*) as count,
                       AVG(r.win_rate) as avg_win_rate,
                       AVG(r.roi) as avg_roi
                FROM test_results r
                JOIN test_executions e ON r.execution_id = e.execution_id
                GROUP BY e.test_type
                ORDER BY count DESC
            """)
            by_type = cursor.fetchall()
            
            conn.close()
            
            export_dir = Path('out/test_history')
            export_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if format_type == 'md' or format_type == 'all':
                md_path = export_dir / f"test_history_{timestamp}.md"
                total_tests = len(rows)
                success_count = sum(1 for r in rows if r['net_profit'] > 0)
                
                md_content = f"""# 测试历史汇总报告

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 概览统计

| 指标 | 值 |
|------|-----|
| 总测试次数 | {total_tests} |
| 成功次数 | {success_count} |
| 失败次数 | {total_tests - success_count} |
| 成功率 | {round(success_count/total_tests*100, 1) if total_tests > 0 else 0}% |
| 平均胜率 | {round(sum(r['win_rate'] for r in rows)/total_tests, 1) if total_tests > 0 else 0}% |
| 平均收益率 | {round(sum(r['roi'] for r in rows)/total_tests, 2) if total_tests > 0 else 0}% |

## 按标的统计

| 标的 | 测试次数 | 平均胜率 | 平均收益率 |
|------|----------|----------|------------|
"""
                for row in by_symbol:
                    md_content += f"| {row['symbol']} | {row['count']} | {row['avg_win_rate']:.1f}% | {row['avg_roi']:.2f}% |\n"
                
                md_content += """
## 按类型统计

| 类型 | 测试次数 | 平均胜率 | 平均收益率 |
|------|----------|----------|------------|
"""
                for row in by_type:
                    md_content += f"| {row['test_type']} | {row['count']} | {row['avg_win_rate']:.1f}% | {row['avg_roi']:.2f}% |\n"
                
                md_content += f"""
## 最近测试记录

| 执行ID | 标的 | 类型 | 胜率 | 收益率 | 执行时间 |
|--------|------|------|------|--------|----------|
"""
                for r in rows[:20]:
                    md_content += f"| {r['execution_id'][:30]}... | {r['symbol']} | {r['test_type']} | {r['win_rate']:.1f}% | {r['roi']:.2f}% | {r['executed_at']} |\n"
                
                md_content += f"""
---
*报告由测试管理系统自动生成*
"""
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                print(f"MD 导出: {md_path}")
            
            if format_type == 'csv' or format_type == 'all':
                csv_path = export_dir / f"test_history_{timestamp}.csv"
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    f.write('执行ID,标的,类型,胜率(%),收益率(%),净收益(USDT),总交易,执行时间\n')
                    for r in rows:
                        f.write(f"{r['execution_id']},{r['symbol']},{r['test_type']},{r['win_rate']:.1f},{r['roi']:.2f},{r['net_profit']:.2f},{r['total_trades']},{r['executed_at']}\n")
                print(f"CSV 导出: {csv_path}")
            
            return jsonify({
                'success': True,
                'message': '测试历史已导出',
                'path': str(export_dir)
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    # ==================== 新增测试用例 API ====================
    
    @app.route('/api/cases', methods=['GET'])
    def list_cases():
        try:
            filters = {}
            if request.args.get('symbol'):
                filters['symbol'] = request.args.get('symbol')
            if request.args.get('status'):
                filters['status'] = request.args.get('status')
            if request.args.get('test_type'):
                filters['test_type'] = request.args.get('test_type')
            
            limit = int(request.args.get('limit', 100))
            offset = int(request.args.get('offset', 0))
            
            cases = db.list_cases(filters, limit, offset)
            
            for case in cases:
                for field in ['amplitude', 'market', 'entry', 'timeout']:
                    if case.get(field):
                        case[field] = json.loads(case[field])
            
            return jsonify({'success': True, 'data': cases})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/cases', methods=['POST'])
    def create_case():
        try:
            data = request.get_json()
            
            case = TestCase(
                case_id='',
                name=data.get('name', ''),
                symbol=data.get('symbol', ''),
                date_start=data.get('date_start', ''),
                date_end=data.get('date_end', ''),
                test_type=data.get('test_type', 'market_aware'),
                description=data.get('description', ''),
                amplitude=json.dumps(data.get('amplitude', {})),
                market=json.dumps(data.get('market', {})),
                entry=json.dumps(data.get('entry', {})),
                timeout=json.dumps(data.get('timeout', {})),
                status='draft'
            )
            
            case_id = db.create_case(case)
            
            if case_id:
                return jsonify({'success': True, 'case_id': case_id})
            else:
                return jsonify({'success': False, 'error': '创建测试用例失败'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/cases/<case_id>', methods=['GET'])
    def get_case(case_id):
        try:
            case = db.get_case(case_id)
            
            if not case:
                return jsonify({'success': False, 'error': '测试用例不存在'})
            
            for field in ['amplitude', 'market', 'entry', 'timeout']:
                if case.get(field):
                    case[field] = json.loads(case[field])
            
            return jsonify({'success': True, 'data': case})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/cases/<case_id>', methods=['PUT'])
    def update_case(case_id):
        try:
            data = request.get_json()
            
            updates = {}
            for field in ['name', 'description', 'symbol', 'date_start', 'date_end',
                         'test_type', 'status']:
                if field in data:
                    updates[field] = data[field]
            
            for field in ['amplitude', 'market', 'entry', 'timeout']:
                if field in data:
                    updates[field] = json.dumps(data[field])
            
            success = db.update_case(case_id, updates)
            
            if success:
                return jsonify({'success': True, 'message': '测试用例已更新'})
            else:
                return jsonify({'success': False, 'error': '更新失败，可能状态不允许修改'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/cases/<case_id>', methods=['DELETE'])
    def delete_case(case_id):
        try:
            success = db.delete_case(case_id)
            
            if success:
                return jsonify({'success': True, 'message': '测试用例已删除'})
            else:
                return jsonify({'success': False, 'error': '删除失败'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/cases/<case_id>/reset', methods=['POST'])
    def reset_case(case_id):
        try:
            success = db.reset_case(case_id)
            
            if success:
                return jsonify({'success': True, 'message': '测试用例已重置'})
            else:
                return jsonify({'success': False, 'error': '重置失败'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/cases/<case_id>/run', methods=['POST'])
    def run_case(case_id):
        try:
            case = db.get_case(case_id)
            if not case:
                return jsonify({'success': False, 'error': '测试用例不存在'})
            
            if case['status'] not in ('draft', 'active'):
                return jsonify({'success': False, 'error': f'状态 {case["status"]} 不允许执行'})
            
            amplitude = json.loads(case['amplitude'] or '{}')
            market = json.loads(case['market'] or '{}')
            entry = json.loads(case['entry'] or '{}')
            timeout = json.loads(case['timeout'] or '{}')
            
            cmd = [
                'python3', 'binance_backtest.py',
                '--symbol', case['symbol'],
                '--date-range', f"{case['date_start']}-{case['date_end']}",
                '--case-id', case_id,
                '--amplitude-params', json.dumps(amplitude),
                '--market-params', json.dumps(market),
                '--entry-params', json.dumps(entry),
                '--timeout-params', json.dumps(timeout)
            ]
            
            import subprocess
            import threading
            
            def run_backtest():
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            thread = threading.Thread(target=run_backtest)
            thread.start()
            
            return jsonify({
                'success': True,
                'message': f'测试用例 {case_id} 已开始执行',
                'command': ' '.join(cmd)
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    # ==================== 测试结果 API ====================
    
    @app.route('/api/results', methods=['GET'])
    def list_results():
        try:
            filters = {}
            if request.args.get('case_id'):
                filters['case_id'] = request.args.get('case_id')
            if request.args.get('symbol'):
                filters['symbol'] = request.args.get('symbol')
            if request.args.get('status'):
                filters['status'] = request.args.get('status')
            if request.args.get('market_algorithm'):
                filters['market_algorithm'] = request.args.get('market_algorithm')
            
            limit = int(request.args.get('limit', 100))
            offset = int(request.args.get('offset', 0))
            
            results = db.list_results(filters, limit, offset)
            
            for result in results:
                if result.get('trading_statuses'):
                    result['trading_statuses'] = json.loads(result['trading_statuses'])
                if result.get('extra_metrics'):
                    result['extra_metrics'] = json.loads(result['extra_metrics'])
            
            return jsonify({'success': True, 'data': results})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/results/<result_id>', methods=['GET'])
    def get_result(result_id):
        try:
            result = db.get_result(result_id)
            
            if not result:
                return jsonify({'success': False, 'error': '测试结果不存在'})
            
            if result.get('trading_statuses'):
                result['trading_statuses'] = json.loads(result['trading_statuses'])
            if result.get('extra_metrics'):
                result['extra_metrics'] = json.loads(result['extra_metrics'])
            
            return jsonify({'success': True, 'data': result})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/results/<result_id>/trades', methods=['GET'])
    def get_trades(result_id):
        try:
            trades = db.get_trade_details(result_id)
            return jsonify({'success': True, 'data': trades})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/results/<result_id>/chart', methods=['GET'])
    def get_chart_data(result_id):
        try:
            result = db.get_result(result_id)
            if not result:
                return jsonify({'success': False, 'error': '测试结果不存在'})
            
            trades = db.get_trade_details(result_id)
            
            chart_data = {
                'result': result,
                'klines': [],
                'trades': trades
            }
            
            return jsonify({'success': True, 'data': chart_data})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    # ==================== 历史汇总 API ====================
    
    @app.route('/api/history', methods=['GET'])
    def get_history():
        try:
            filters = {}
            if request.args.get('symbol'):
                filters['symbol'] = request.args.get('symbol')
            if request.args.get('market_algorithm'):
                filters['market_algorithm'] = request.args.get('market_algorithm')
            
            summary = db.get_history_summary(filters)
            by_symbol = db.get_history_by_symbol()
            by_algorithm = db.get_history_by_algorithm()
            
            return jsonify({
                'success': True,
                'data': {
                    'summary': summary,
                    'by_symbol': by_symbol,
                    'by_algorithm': by_algorithm
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/history/export', methods=['GET'])
    def export_history():
        try:
            from pathlib import Path
            from datetime import datetime
            
            format_type = request.args.get('format', 'md')
            
            filters = {}
            if request.args.get('symbol'):
                filters['symbol'] = request.args.get('symbol')
            
            summary = db.get_history_summary(filters)
            by_symbol = db.get_history_by_symbol()
            by_algorithm = db.get_history_by_algorithm()
            
            export_dir = Path('out/test_history')
            export_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if format_type == 'md' or format_type == 'all':
                md_path = export_dir / f"test_history_{timestamp}.md"
                
                md_content = f"""# 测试历史汇总报告

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 概览统计

| 指标 | 值 |
|------|-----|
| 总测试次数 | {summary['total_tests']} |
| 成功率 | {summary['success_rate']:.1f}% |
| 平均胜率 | {summary['avg_win_rate']:.1f}% |
| 平均收益率 | {summary['avg_roi']:.2f}% |
| 平均超额收益 | {summary['avg_excess_return']:.2f}% |

## 按标的统计

| 标的 | 测试次数 | 平均胜率 | 平均收益率 |
|------|----------|----------|------------|
"""
                for row in by_symbol:
                    md_content += f"| {row['symbol']} | {row['count']} | {row['avg_win_rate']:.1f}% | {row['avg_roi']:.2f}% |\n"
                
                md_content += """
## 按算法统计

| 算法 | 测试次数 | 平均胜率 | 平均收益率 |
|------|----------|----------|------------|
"""
                for row in by_algorithm:
                    md_content += f"| {row['market_algorithm']} | {row['count']} | {row['avg_win_rate']:.1f}% | {row['avg_roi']:.2f}% |\n"
                
                md_content += f"""
---
*报告由测试管理系统自动生成*
"""
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                
                return jsonify({
                    'success': True,
                    'message': '测试历史已导出',
                    'path': str(md_path)
                })
            
            return jsonify({'success': False, 'error': '不支持的导出格式'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    # ==================== 测试对比 API ====================
    
    @app.route('/api/compare', methods=['POST'])
    def compare_results():
        try:
            data = request.get_json()
            result_ids = data.get('result_ids', [])
            
            if not result_ids or len(result_ids) < 2:
                return jsonify({'success': False, 'error': '至少需要选择2个测试结果进行对比'})
            
            if len(result_ids) > 5:
                return jsonify({'success': False, 'error': '最多支持对比5个测试结果'})
            
            results = []
            for result_id in result_ids:
                result = db.get_result(result_id)
                if result:
                    if result.get('trading_statuses'):
                        result['trading_statuses'] = json.loads(result['trading_statuses'])
                    results.append(result)
            
            if len(results) < 2:
                return jsonify({'success': False, 'error': '找到的测试结果不足2个'})
            
            metrics = ['win_rate', 'roi', 'excess_return', 'total_trades', 'net_profit', 'profit_factor']
            comparison = {}
            
            for metric in metrics:
                values = [(r['result_id'], r.get(metric, 0)) for r in results]
                if metric in ['win_rate', 'roi', 'excess_return', 'profit_factor']:
                    best = max(values, key=lambda x: x[1])
                else:
                    best = max(values, key=lambda x: x[1])
                
                comparison[metric] = {
                    'values': {v[0]: round(v[1], 2) for v in values},
                    'best': best[0]
                }
            
            return jsonify({
                'success': True,
                'data': {
                    'results': results,
                    'comparison': comparison
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    return app


def run_server(host='0.0.0.0', port=5002, debug=False):
    """启动 Web API 服务器"""
    app = create_flask_app()
    print(f"🚀 测试结果 Web API 服务启动")
    print(f"📍 地址: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()

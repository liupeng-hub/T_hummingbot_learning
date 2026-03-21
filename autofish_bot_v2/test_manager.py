#!/usr/bin/env python3
"""
测试管理系统 - CLI 与 WebServer

功能:
1. 测试用例管理: 创建、查看、删除、执行
2. 测试结果管理: 查看、删除、导出
3. Web API 服务: 提供 RESTful 接口

使用示例:
    # 创建测试用例
    python test_manager.py create-case --symbol BTCUSDT --date-range 20250101-20250131
    
    # 列出测试用例
    python test_manager.py list-cases
    
    # 执行测试用例
    python test_manager.py run-case <case_id>
    
    # 查看测试结果
    python test_manager.py list-results
    python test_manager.py show-result <result_id>
    
    # 启动 Web 服务
    python test_manager.py serve --port 5002
"""

import os
import sys
import json
import argparse
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import asyncio

from database.test_results_db import TestResultsDB, TestCase, TestResult, TradeDetail
from binance_kline_fetcher import KlineFetcher

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
    
    create_case_parser = subparsers.add_parser("create-case", help="创建测试用例")
    create_case_parser.add_argument("--symbol", required=True, help="交易对（必选）")
    create_case_parser.add_argument("--date-range", required=True, help="时间范围 (yyyymmdd-yyyymmdd)（必选）")
    create_case_parser.add_argument("--name", default="", help="用例名称")
    create_case_parser.add_argument("--description", default="", help="用例描述")
    create_case_parser.add_argument("--amplitude-params", help="振幅参数（JSON字符串）")
    create_case_parser.add_argument("--market-params", help="行情算法参数（JSON字符串）")
    create_case_parser.add_argument("--entry-params", help="入场价格策略参数（JSON字符串）")
    create_case_parser.add_argument("--timeout-params", help="超时参数（JSON字符串）")
    create_case_parser.add_argument("--capital-params", help="资金池参数（JSON字符串")
    
    list_cases_parser = subparsers.add_parser("list-cases", help="列出测试用例")
    list_cases_parser.add_argument("--symbol", help="按交易对筛选")
    list_cases_parser.add_argument("--status", help="按状态筛选")
    list_cases_parser.add_argument("--limit", type=int, default=100, help="返回数量限制")
    
    show_case_parser = subparsers.add_parser("show-case", help="查看测试用例详情")
    show_case_parser.add_argument("case_id", help="测试用例ID")
    
    delete_case_parser = subparsers.add_parser("delete-case", help="删除测试用例")
    delete_case_parser.add_argument("case_id", help="测试用例ID")
    
    reset_case_parser = subparsers.add_parser("reset-case", help="重置测试用例（清除测试结果，恢复为可执行状态）")
    reset_case_parser.add_argument("case_id", help="测试用例ID")
    
    run_case_parser = subparsers.add_parser("run-case", help="执行测试用例")
    run_case_parser.add_argument("case_id", help="测试用例ID")
    run_case_parser.add_argument("--dry-run", action="store_true", help="只显示命令，不执行")
    
    list_results_parser = subparsers.add_parser("list-results", help="列出测试结果")
    list_results_parser.add_argument("--case-id", help="按用例ID筛选")
    list_results_parser.add_argument("--symbol", help="按交易对筛选")
    list_results_parser.add_argument("--status", help="按状态筛选")
    list_results_parser.add_argument("--limit", type=int, default=100, help="返回数量限制")
    
    show_result_parser = subparsers.add_parser("show-result", help="查看测试结果详情")
    show_result_parser.add_argument("result_id", help="测试结果ID")
    
    delete_result_parser = subparsers.add_parser("delete-result", help="删除测试结果")
    delete_result_parser.add_argument("result_id", help="测试结果ID")
    
    export_parser = subparsers.add_parser("export", help="导出测试报告")
    export_parser.add_argument("id", help="执行ID/结果ID")
    export_parser.add_argument("--format", choices=["md", "csv", "png", "html", "all"], default="md", help="导出格式")
    export_parser.add_argument("--type", choices=["backtest", "market_aware", "visualizer", "optimizer", "longport"], 
                               help="报告类型（自动检测时可不指定）")
    export_parser.add_argument("--output", help="输出文件路径")
    
    stats_parser = subparsers.add_parser("stats", help="查看统计数据")
    
    serve_parser = subparsers.add_parser("serve", help="启动Web API服务")
    serve_parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    serve_parser.add_argument("--port", type=int, default=5002, help="监听端口")
    serve_parser.add_argument("--debug", action="store_true", help="调试模式")
    
    args = parser.parse_args()
    
    db = TestResultsDB()
    
    if args.command == "create-case":
        date_parts = args.date_range.split("-")
        if len(date_parts) != 2:
            print(f"❌ 日期格式错误，应为 yyyymmdd-yyyymmdd")
            sys.exit(1)
        
        date_start = f"{date_parts[0][:4]}-{date_parts[0][4:6]}-{date_parts[0][6:8]}"
        date_end = f"{date_parts[1][:4]}-{date_parts[1][4:6]}-{date_parts[1][6:8]}"
        
        case = TestCase(
            case_id='',
            name=args.name or f"{args.symbol}_{args.date_range}",
            symbol=args.symbol,
            date_start=date_start,
            date_end=date_end,
            test_type='market_aware',
            description=args.description,
            amplitude=args.amplitude_params or '{}',
            market=args.market_params or '{"algorithm": "always_ranging"}',
            entry=args.entry_params or '{}',
            timeout=args.timeout_params or '{"a1_timeout_minutes": 0}',
            capital=args.capital_params or '{"strategy": "guding"}',
            status='draft'
        )
        
        case_id = db.create_case(case)
        if case_id:
            print(f"✅ 测试用例已创建: {case_id}")
            print(f"   名称: {case.name}")
            print(f"   交易对: {case.symbol}")
            print(f"   日期范围: {date_start} ~ {date_end}")
        else:
            print(f"❌ 创建测试用例失败")
            sys.exit(1)
    
    elif args.command == "list-cases":
        filters = {}
        if args.symbol:
            filters['symbol'] = args.symbol
        if args.status:
            filters['status'] = args.status
        
        cases = db.list_cases(filters, args.limit, 0)
        
        if not cases:
            print("暂无测试用例")
        else:
            print(f"\n共 {len(cases)} 个测试用例:\n")
            print(f"{'用例ID':<40} | {'名称':<30} | {'交易对':<10} | {'状态':<10} | {'日期范围'}")
            print("-" * 120)
            for c in cases:
                date_range = f"{c.get('date_start', '')} ~ {c.get('date_end', '')}"
                print(f"{c['case_id']:<40} | {c.get('name', '')[:30]:<30} | {c.get('symbol', ''):<10} | {c.get('status', ''):<10} | {date_range}")
    
    elif args.command == "show-case":
        case = db.get_case(args.case_id)
        if not case:
            print(f"❌ 测试用例不存在: {args.case_id}")
            sys.exit(1)
        
        for field in ['amplitude', 'market', 'entry', 'timeout']:
            if case.get(field):
                case[field] = json.loads(case[field])
        
        print(json.dumps(case, indent=2, ensure_ascii=False, default=str))
    
    elif args.command == "delete-case":
        success = db.delete_case(args.case_id)
        if success:
            print(f"✅ 测试用例已删除: {args.case_id}")
        else:
            print(f"❌ 删除失败: {args.case_id}")
            sys.exit(1)
    
    elif args.command == "reset-case":
        success = db.reset_case(args.case_id)
        if success:
            print(f"✅ 测试用例已重置: {args.case_id}")
            print(f"   状态已恢复为 active，可以重新执行")
        else:
            print(f"❌ 重置失败: {args.case_id}")
            sys.exit(1)
    
    elif args.command == "run-case":
        case = db.get_case(args.case_id)
        if not case:
            print(f"❌ 测试用例不存在: {args.case_id}")
            sys.exit(1)
        
        if case['status'] not in ('draft', 'active'):
            print(f"❌ 状态 {case['status']} 不允许执行")
            sys.exit(1)
        
        amplitude = case.get('amplitude') or '{}'
        market = case.get('market') or '{"algorithm": "always_ranging"}'
        entry = case.get('entry') or '{}'
        timeout = case.get('timeout') or '{"a1_timeout_minutes": 0}'
        capital = case.get('capital') or '{"strategy": "guding"}'
        
        date_start = case['date_start'].replace('-', '')
        date_end = case['date_end'].replace('-', '')
        date_range = f"{date_start}-{date_end}"
        
        cmd = [
            'python3', 'binance_backtest.py',
            '--symbol', case['symbol'],
            '--date-range', date_range,
            '--case-id', args.case_id,
            '--interval', case.get('interval', '1m'),
            '--amplitude-params', amplitude,
            '--market-params', market,
            '--entry-params', entry,
            '--timeout-params', timeout,
            '--capital-params', capital
        ]
        
        print(f"\n{'='*60}")
        print(f"执行测试用例: {args.case_id}")
        print(f"交易对: {case['symbol']}")
        print(f"日期范围: {case['date_start']} ~ {case['date_end']}")
        print(f"{'='*60}")
        print(f"命令: {' '.join(cmd)}")
        
        if args.dry_run:
            print("(dry-run) 跳过执行")
        else:
            db.update_case_status(args.case_id, 'running')
            try:
                result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
                if result.returncode == 0:
                    db.update_case_status(args.case_id, 'completed')
                    print(f"✅ 测试用例执行成功")
                else:
                    db.update_case_status(args.case_id, 'error')
                    print(f"❌ 测试用例执行失败，返回码: {result.returncode}")
            except Exception as e:
                db.update_case_status(args.case_id, 'error')
                print(f"❌ 执行异常: {e}")
                sys.exit(1)
    
    elif args.command == "list-results":
        filters = {}
        if args.case_id:
            filters['case_id'] = args.case_id
        if args.symbol:
            filters['symbol'] = args.symbol
        if args.status:
            filters['status'] = args.status
        
        results = db.list_results(filters, args.limit, 0)
        
        if not results:
            print("暂无测试结果")
        else:
            print(f"\n共 {len(results)} 条测试结果:\n")
            print(f"{'结果ID':<40} | {'用例ID':<36} | {'交易对':<10} | {'胜率':<8} | {'收益率':<10} | {'净收益':<12}")
            print("-" * 130)
            for r in results:
                print(f"{r['result_id']:<40} | {(r.get('case_id') or '')[:36]:<36} | {r.get('symbol', ''):<10} | {r.get('win_rate', 0):.1f}% | {r.get('roi', 0):.2f}% | {r.get('net_profit', 0):.2f}")
    
    elif args.command == "show-result":
        result = db.get_result(args.result_id)
        if not result:
            print(f"❌ 测试结果不存在: {args.result_id}")
            sys.exit(1)
        
        if result.get('trading_statuses'):
            result['trading_statuses'] = json.loads(result['trading_statuses'])
        if result.get('extra_metrics'):
            result['extra_metrics'] = json.loads(result['extra_metrics'])
        
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    
    elif args.command == "delete-result":
        success = db.delete_result(args.result_id)
        if success:
            print(f"✅ 测试结果已删除: {args.result_id}")
        else:
            print(f"❌ 删除失败: {args.result_id}")
            sys.exit(1)
    
    elif args.command == "export":
        _export_report(args)
    
    elif args.command == "stats":
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
            results = db.list_results(filters, limit)
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
                capital=json.dumps(data.get('capital', {})),
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
            
            for field in ['amplitude', 'market', 'entry', 'timeout', 'capital']:
                if case.get(field):
                    case[field] = json.loads(case[field])
            
            test_case_info = {
                'case_id': case.get('case_id'),
                'name': case.get('name'),
                'status': case.get('status'),
                'symbol': case.get('symbol'),
                'test_type': case.get('test_type'),
                'date_start': case.get('date_start'),
                'date_end': case.get('date_end'),
                'description': case.get('description'),
                'interval': case.get('interval', '1m'),
                'created_at': case.get('created_at'),
                'updated_at': case.get('updated_at'),
                'success': True
            }
            
            return jsonify({
                'data': {
                    'test_case': test_case_info,
                    'amplitude': case.get('amplitude', {}),
                    'market': case.get('market', {}),
                    'entry': case.get('entry', {}),
                    'timeout': case.get('timeout', {}),
                    'capital': case.get('capital', {})
                }
            })
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
            
            for field in ['amplitude', 'market', 'entry', 'timeout', 'capital']:
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
            capital = json.loads(case['capital'] or '{}')
            
            cmd = [
                'python3', 'binance_backtest.py',
                '--symbol', case['symbol'],
                '--date-range', f"{case['date_start']}-{case['date_end']}",
                '--case-id', case_id,
                '--interval', case.get('interval', '1m'),
                '--amplitude-params', json.dumps(amplitude),
                '--market-params', json.dumps(market),
                '--entry-params', json.dumps(entry),
                '--timeout-params', json.dumps(timeout),
                '--capital-params', json.dumps(capital)
            ]
            
            import subprocess
            import threading
            
            db.update_case_status(case_id, 'running')
            
            def run_backtest():
                try:
                    print(f"[{case_id}] 开始执行命令: {' '.join(cmd)}")
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
                    print(f"[{case_id}] 命令返回码: {result.returncode}")
                    if result.stdout:
                        print(f"[{case_id}] 输出: {result.stdout[-2000:]}")
                    if result.stderr:
                        print(f"[{case_id}] 错误: {result.stderr[-1000:]}")
                    if result.returncode == 0:
                        db.update_case_status(case_id, 'completed')
                        print(f"[{case_id}] 测试完成")
                    else:
                        db.update_case_status(case_id, 'error')
                        print(f"[{case_id}] 测试失败: {result.stderr}")
                except Exception as e:
                    db.update_case_status(case_id, 'error')
                    print(f"[{case_id}] 测试异常: {e}")
            
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
            if result.get('capital'):
                result['capital'] = json.loads(result['capital'])
            
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
    
    @app.route('/api/results/<result_id>/capital', methods=['GET'])
    def get_capital_detail(result_id):
        try:
            result = db.get_result(result_id)
            if not result:
                return jsonify({'success': False, 'error': '测试结果不存在'})
            
            capital_stats = db.get_capital_statistics(result_id)
            capital_history = db.get_capital_history(result_id)
            
            return jsonify({
                'success': True,
                'data': {
                    'statistics': capital_stats,
                    'history': capital_history
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/results/<result_id>/chart', methods=['GET'])
    def get_chart_data(result_id):
        try:
            result = db.get_result(result_id)
            if not result:
                return jsonify({'success': False, 'error': '测试结果不存在'})
            
            trades = db.get_trade_details(result_id)
            
            for t in trades:
                if t.get('entry_time'):
                    t['entry_date'] = t['entry_time'].split()[0] if ' ' in t['entry_time'] else t['entry_time']
                if t.get('exit_time'):
                    t['exit_date'] = t['exit_time'].split()[0] if ' ' in t['exit_time'] else t['exit_time']
            
            klines = []
            symbol = result.get('symbol')
            start_time = result.get('start_time')
            end_time = result.get('end_time')
            
            case = None
            if result.get('case_id'):
                case = db.get_case(result.get('case_id'))
            
            interval = request.args.get('interval')
            if not interval:
                if case and case.get('interval'):
                    interval = case.get('interval')
                else:
                    interval = '1m'
            
            if not start_time or not end_time:
                if trades:
                    if not start_time:
                        start_time = min(t.get('entry_time') for t in trades if t.get('entry_time'))
                    if not end_time:
                        end_time = max(t.get('exit_time') for t in trades if t.get('exit_time'))
                
                if (not start_time or not end_time) and result.get('case_id'):
                    case = db.get_case(result.get('case_id'))
                    if case:
                        if not start_time and case.get('date_start'):
                            start_time = case.get('date_start')
                        if not end_time and case.get('date_end'):
                            end_time = case.get('date_end')
            
            if symbol and start_time and end_time:
                try:
                    fetcher = KlineFetcher()
                    start_str = start_time.split()[0] if ' ' in start_time else start_time
                    end_str = end_time.split()[0] if ' ' in end_time else end_time
                    start_dt = datetime.strptime(start_str, '%Y-%m-%d')
                    end_dt = datetime.strptime(end_str, '%Y-%m-%d')
                    start_ts = int(start_dt.timestamp() * 1000)
                    end_ts = int(end_dt.timestamp() * 1000)
                    
                    async def fetch_klines_async():
                        return await fetcher.fetch_kline(symbol, interval, start_ts, end_ts)
                    
                    raw_klines = asyncio.run(fetch_klines_async())
                    
                    # 限制K线数量，采样显示
                    max_klines = 5000
                    if len(raw_klines) > max_klines:
                        step = len(raw_klines) // max_klines
                        raw_klines = raw_klines[::step]
                        logger.info(f"K线数据采样: 原始{len(raw_klines) * step}条, 采样后{len(raw_klines)}条")
                    
                    for k in raw_klines:
                        dt = datetime.fromtimestamp(k['timestamp'] / 1000)
                        klines.append({
                            'date': dt.strftime('%Y-%m-%d'),
                            'timestamp': k['timestamp'],
                            'open': float(k['open']),
                            'high': float(k['high']),
                            'low': float(k['low']),
                            'close': float(k['close']),
                            'volume': float(k['volume'])
                        })
                except Exception as e:
                    logger.error(f"获取K线数据失败: {e}")
            
            capital_history = db.get_capital_history(result_id)
            
            chart_data = {
                'result': result,
                'klines': klines,
                'trades': trades,
                'capital_history': capital_history
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

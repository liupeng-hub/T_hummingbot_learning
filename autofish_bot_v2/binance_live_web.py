#!/usr/bin/env python3
"""
实盘交易管理系统 - CLI 与 WebServer

功能:
1. 实盘配置管理: 创建、查看、删除、启动
2. 实盘会话管理: 查看、停止、统计
3. Web API 服务: 提供 RESTful 接口

使用示例:
    # 创建实盘配置
    python binance_live_web.py create-case --symbol BTCUSDT --name "BTC网格"

    # 列出实盘配置
    python binance_live_web.py list-cases

    # 启动实盘
    python binance_live_web.py run-case <case_id>

    # 查看实盘状态
    python binance_live_web.py list-sessions
    python binance_live_web.py show-session <session_id>

    # 启动 Web 服务
    python binance_live_web.py serve --port 5003
"""

import os
import sys
import json
import argparse
import subprocess
import logging
import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from database.live_trading_db import (
    LiveTradingDB, LiveCase, LiveSession,
    DbStateRepository
)
from binance_live import LiveTraderManager
from autofish_core import ConfigLoader

# 配置日志
def setup_logging():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / 'live_web.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


# ============================================================================
# CLI 命令处理函数
# ============================================================================

def _create_case(args):
    """创建实盘配置"""
    db = LiveTradingDB()

    # 构建 amplitude 参数
    amplitude = {
        'grid_spacing': args.grid_spacing,
        'exit_profit': args.exit_profit,
        'stop_loss': args.stop_loss,
        'decay_factor': args.decay_factor,
        'weights': args.weights or [0.4, 0.3, 0.2, 0.1],
        'max_entries': args.max_entries,
    }

    # 构建 market 参数
    market = {
        'market_aware': args.market_aware,
        'algorithm': args.market_algorithm,
        'trading_statuses': args.trading_statuses or ['ranging'],
    }
    if args.market_params:
        market.update(json.loads(args.market_params))

    # 构建 entry 参数
    entry = json.loads(args.entry_params) if args.entry_params else {}

    # 构建 timeout 参数
    timeout = {
        'a1_timeout_minutes': args.a1_timeout,
    }

    # 构建 capital 参数
    capital = {
        'total_amount_quote': args.total_amount,
        'leverage': args.leverage,
        'strategy': args.capital_strategy,
        'entry_mode': args.entry_mode,
    }
    if args.capital_params:
        capital.update(json.loads(args.capital_params))

    case = LiveCase(
        name=args.name or f"{args.symbol}_live",
        symbol=args.symbol,
        testnet=1 if args.testnet else 0,
        description=args.description or '',
        amplitude=json.dumps(amplitude),
        market=json.dumps(market),
        entry=json.dumps(entry),
        timeout=json.dumps(timeout),
        capital=json.dumps(capital),
        status='draft'
    )

    case_id = db.create_case(case)
    if case_id:
        print(f"✅ 实盘配置已创建: {case_id}")
        print(f"   名称: {case.name}")
        print(f"   交易对: {case.symbol}")
        print(f"   测试网: {'是' if args.testnet else '否'}")
        print(f"   总资金: {args.total_amount} USDT")
        print(f"   杠杆: {args.leverage}x")
    else:
        print(f"❌ 创建实盘配置失败")
        sys.exit(1)


def _list_cases(args):
    """列出实盘配置"""
    db = LiveTradingDB()

    filters = {}
    if args.symbol:
        filters['symbol'] = args.symbol
    if args.status:
        filters['status'] = args.status

    cases = db.list_cases(filters, args.limit, 0)

    if not cases:
        print("暂无实盘配置")
    else:
        print(f"\n共 {len(cases)} 个实盘配置:\n")
        print(f"{'配置ID':<8} | {'名称':<25} | {'交易对':<10} | {'网络':<8} | {'状态':<10}")
        print("-" * 70)
        for c in cases:
            network = '测试网' if c.get('testnet') else '主网'
            print(f"{c['id']:<8} | {c.get('name', '')[:25]:<25} | {c.get('symbol', ''):<10} | {network:<8} | {c.get('status', ''):<10}")


def _show_case(args):
    """查看实盘配置详情"""
    db = LiveTradingDB()

    case = db.get_case(args.id)
    if not case:
        print(f"❌ 实盘配置不存在: {args.id}")
        sys.exit(1)

    # 解析 JSON 字段
    for field in ['amplitude', 'market', 'entry', 'timeout', 'capital']:
        if case.get(field):
            try:
                case[field] = json.loads(case[field])
            except:
                pass

    print(json.dumps(case, indent=2, ensure_ascii=False, default=str))


def _delete_case(args):
    """删除实盘配置"""
    db = LiveTradingDB()

    # 检查是否有运行中的会话
    sessions = db.list_sessions(filters={'case_id': args.id, 'status': 'running'})
    if sessions:
        print(f"❌ 存在运行中的会话，请先停止:")
        for s in sessions:
            print(f"   - Session {s['id']}: {s['symbol']}")
        sys.exit(1)

    success = db.delete_case(args.id)
    if success:
        print(f"✅ 实盘配置已删除: {args.id}")
    else:
        print(f"❌ 删除失败: {args.id}")
        sys.exit(1)


def _run_case(args):
    """启动实盘交易"""
    db = LiveTradingDB()

    case = db.get_case(args.id)
    if not case:
        print(f"❌ 实盘配置不存在: {args.id}")
        sys.exit(1)

    if case['status'] not in ('draft', 'active', 'stopped'):
        print(f"❌ 状态 {case['status']} 不允许启动")
        sys.exit(1)

    # 使用 --case-id 参数，让 binance_live.py 从数据库加载配置
    cmd = [
        'python3', 'binance_live.py',
        '--case-id', str(args.id),
    ]

    print(f"\n{'='*60}")
    print(f"启动实盘交易: {args.id}")
    print(f"交易对: {case['symbol']}")
    print(f"网络: {'测试网' if case.get('testnet') else '主网'}")
    print(f"{'='*60}")
    print(f"命令: {' '.join(cmd)}")

    if args.dry_run:
        print("(dry-run) 跳过执行")
        return

    # 更新状态为 active
    db.update_case_status(args.id, 'active')

    try:
        result = subprocess.run(cmd, cwd=str(Path(__file__).parent))
        if result.returncode == 0:
            print(f"✅ 实盘交易正常退出")
        else:
            print(f"❌ 实盘交易异常退出，返回码: {result.returncode}")
    except KeyboardInterrupt:
        print(f"\n⏹️ 实盘交易已手动停止")
    except Exception as e:
        print(f"❌ 执行异常: {e}")
        sys.exit(1)


def _list_sessions(args):
    """列出实盘会话"""
    db = LiveTradingDB()

    filters = {}
    if args.case_id:
        filters['case_id'] = args.case_id
    if args.symbol:
        filters['symbol'] = args.symbol
    if args.status:
        filters['status'] = args.status

    sessions = db.list_sessions(filters, args.limit, 0)

    if not sessions:
        print("暂无实盘会话")
    else:
        print(f"\n共 {len(sessions)} 个实盘会话:\n")
        print(f"{'会话ID':<8} | {'配置ID':<8} | {'交易对':<10} | {'状态':<10} | {'开始时间':<20}")
        print("-" * 70)
        for s in sessions:
            print(f"{s['id']:<8} | {s.get('case_id', ''):<8} | {s.get('symbol', ''):<10} | {s.get('status', ''):<10} | {s.get('start_time', '')[:19]:<20}")


def _show_session(args):
    """查看会话详情"""
    db = LiveTradingDB()

    session = db.get_session(args.id)
    if not session:
        print(f"❌ 会话不存在: {args.id}")
        sys.exit(1)

    # 解析 JSON 字段
    for field in ['amplitude', 'market', 'entry', 'timeout', 'capital']:
        if session.get(field):
            try:
                session[field] = json.loads(session[field])
            except:
                pass

    print(json.dumps(session, indent=2, ensure_ascii=False, default=str))


def _stop_session(args):
    """停止会话"""
    db = LiveTradingDB()

    session = db.get_session(args.id)
    if not session:
        print(f"❌ 会话不存在: {args.id}")
        sys.exit(1)

    if session['status'] != 'running':
        print(f"❌ 会话状态不是 running: {session['status']}")
        sys.exit(1)

    # 这里只是更新数据库状态，实际停止需要发送信号到运行中的进程
    # TODO: 实现通过 PID 或其他方式停止进程
    db.end_session(args.id, status='stopped')
    print(f"✅ 会话已标记为停止: {args.id}")
    print(f"   注意: 如果实盘程序仍在运行，需要手动停止 (Ctrl+C)")


def _show_stats(args):
    """显示统计信息"""
    db = LiveTradingDB()

    print("\n📊 实盘交易统计:")

    # 按状态统计会话
    running_count = db.get_session_count_by_status('running')
    stopped_count = db.get_session_count_by_status('stopped')
    error_count = db.get_session_count_by_status('error')

    print(f"  会话统计:")
    print(f"    - 运行中: {running_count}")
    print(f"    - 已停止: {stopped_count}")
    print(f"    - 错误: {error_count}")

    # 资金统计汇总
    if args.symbol:
        stats = db.get_statistics_summary(args.symbol)
        print(f"\n  {args.symbol} 资金统计:")
    else:
        stats = db.get_statistics_summary()
        print(f"\n  整体资金统计:")

    if stats:
        print(f"    - 总交易次数: {stats.get('total_trades', 0)}")
        print(f"    - 盈利次数: {stats.get('profit_trades', 0)}")
        print(f"    - 亏损次数: {stats.get('loss_trades', 0)}")
        print(f"    - 平均胜率: {stats.get('avg_win_rate', 0):.1f}%")
        print(f"    - 总盈利: {stats.get('total_profit', 0):.2f} USDT")
        print(f"    - 总亏损: {stats.get('total_loss', 0):.2f} USDT")
        print(f"    - 提现次数: {stats.get('withdrawal_count', 0)}")
        print(f"    - 爆仓次数: {stats.get('liquidation_count', 0)}")


# ============================================================================
# Web API
# ============================================================================

def create_flask_app():
    """创建 Flask Web API 应用"""
    from flask import Flask, request, jsonify, render_template, send_from_directory
    from flask_cors import CORS

    base_dir = Path(__file__).parent
    app = Flask(__name__,
                template_folder=str(base_dir / 'web/live'))
    CORS(app)

    db = LiveTradingDB()
    trader_manager = LiveTraderManager()

    # 用于在 Flask 同步环境中运行异步任务
    def run_async(coro):
        """在后台线程中运行异步协程"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    @app.route('/')
    def index():
        return render_template('index.html')

    # ==================== 实盘配置 API ====================

    @app.route('/api/live-cases', methods=['GET'])
    def get_live_cases():
        """获取实盘配置列表"""
        try:
            filters = {}
            if request.args.get('symbol'):
                filters['symbol'] = request.args.get('symbol')
            if request.args.get('status'):
                filters['status'] = request.args.get('status')
            limit = int(request.args.get('limit', 50))
            cases = db.list_cases(filters, limit)
            return jsonify({'success': True, 'data': cases})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-cases', methods=['POST'])
    def create_live_case():
        """创建实盘配置"""
        try:
            data = request.get_json()
            case = LiveCase(
                name=data.get('name', f"{data.get('symbol')}_live"),
                symbol=data['symbol'],
                testnet=data.get('testnet', 1),
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
                return jsonify({'success': True, 'data': {'id': case_id}})
            return jsonify({'success': False, 'error': 'Create failed'}), 500
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-cases/<int:case_id>', methods=['GET'])
    def get_live_case(case_id):
        """获取实盘配置详情"""
        try:
            case = db.get_case(case_id)
            if not case:
                return jsonify({'success': False, 'error': 'Case not found'}), 404

            # 解析 JSON 字段
            for field in ['amplitude', 'market', 'entry', 'timeout', 'capital']:
                if case.get(field):
                    try:
                        case[field] = json.loads(case[field])
                    except:
                        pass

            return jsonify({'success': True, 'data': case})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-cases/<int:case_id>', methods=['DELETE'])
    def delete_live_case(case_id):
        """删除实盘配置"""
        try:
            # 检查是否有运行中的会话
            sessions = db.list_sessions(filters={'case_id': case_id, 'status': 'running'})
            if sessions:
                return jsonify({'success': False, 'error': 'Has running sessions'}), 400

            success = db.delete_case(case_id)
            if success:
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': 'Delete failed'}), 500
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-cases/<int:case_id>', methods=['PUT'])
    def update_live_case(case_id):
        """更新实盘配置"""
        try:
            case = db.get_case(case_id)
            if not case:
                return jsonify({'success': False, 'error': 'Case not found'}), 404

            # 检查是否有运行中的会话
            sessions = db.list_sessions(filters={'case_id': case_id, 'status': 'running'})
            if sessions:
                return jsonify({'success': False, 'error': 'Cannot update while running'}), 400

            data = request.get_json()

            # 更新字段
            update_data = {}
            if 'name' in data:
                update_data['name'] = data['name']
            if 'description' in data:
                update_data['description'] = data['description']
            if 'symbol' in data:
                update_data['symbol'] = data['symbol']
            if 'testnet' in data:
                update_data['testnet'] = data['testnet']
            if 'status' in data:
                update_data['status'] = data['status']
            if 'amplitude' in data:
                update_data['amplitude'] = json.dumps(data['amplitude']) if isinstance(data['amplitude'], dict) else data['amplitude']
            if 'market' in data:
                update_data['market'] = json.dumps(data['market']) if isinstance(data['market'], dict) else data['market']
            if 'entry' in data:
                update_data['entry'] = json.dumps(data['entry']) if isinstance(data['entry'], dict) else data['entry']
            if 'timeout' in data:
                update_data['timeout'] = json.dumps(data['timeout']) if isinstance(data['timeout'], dict) else data['timeout']
            if 'capital' in data:
                update_data['capital'] = json.dumps(data['capital']) if isinstance(data['capital'], dict) else data['capital']

            success = db.update_case(case_id, update_data)
            if success:
                return jsonify({'success': True, 'message': 'Updated'})
            return jsonify({'success': False, 'error': 'Update failed'}), 500
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-cases/<int:case_id>/reset', methods=['POST'])
    def reset_live_case(case_id):
        """重置实盘配置（清除所有会话数据）"""
        try:
            case = db.get_case(case_id)
            if not case:
                return jsonify({'success': False, 'error': 'Case not found'}), 404

            # 检查是否有运行中的会话
            sessions = db.list_sessions(filters={'case_id': case_id, 'status': 'running'})
            if sessions:
                return jsonify({'success': False, 'error': 'Cannot reset while running'}), 400

            # 删除所有关联的会话数据
            deleted_count = db.delete_sessions_by_case(case_id)
            db.update_case_status(case_id, 'draft')

            return jsonify({
                'success': True,
                'message': f'Reset complete, {deleted_count} sessions deleted'
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-cases/<int:case_id>/copy', methods=['POST'])
    def copy_live_case(case_id):
        """复制实盘配置"""
        try:
            case = db.get_case(case_id)
            if not case:
                return jsonify({'success': False, 'error': 'Case not found'}), 404

            # 创建新配置
            new_case = LiveCase(
                name=f"{case.get('name', '')} (副本)",
                symbol=case.get('symbol', 'BTCUSDT'),
                testnet=case.get('testnet', 1),
                description=case.get('description', ''),
                amplitude=case.get('amplitude', '{}'),
                market=case.get('market', '{}'),
                entry=case.get('entry', '{}'),
                timeout=case.get('timeout', '{}'),
                capital=case.get('capital', '{}'),
                status='draft'
            )

            new_id = db.create_case(new_case)
            if new_id:
                return jsonify({'success': True, 'data': {'id': new_id}})
            return jsonify({'success': False, 'error': 'Copy failed'}), 500
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # ==================== 实盘会话 API ====================

    @app.route('/api/live-sessions', methods=['GET'])
    def get_live_sessions():
        """获取实盘会话列表"""
        try:
            filters = {}
            if request.args.get('case_id'):
                filters['case_id'] = int(request.args.get('case_id'))
            if request.args.get('symbol'):
                filters['symbol'] = request.args.get('symbol')
            if request.args.get('status'):
                filters['status'] = request.args.get('status')
            limit = int(request.args.get('limit', 50))
            sessions = db.list_sessions(filters, limit)
            return jsonify({'success': True, 'data': sessions})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-sessions/<int:session_id>', methods=['GET'])
    def get_live_session(session_id):
        """获取会话详情"""
        try:
            session = db.get_session(session_id)
            if not session:
                return jsonify({'success': False, 'error': 'Session not found'}), 404

            # 解析 JSON 字段
            for field in ['amplitude', 'market', 'entry', 'timeout', 'capital']:
                if session.get(field):
                    try:
                        session[field] = json.loads(session[field])
                    except:
                        pass

            return jsonify({'success': True, 'data': session})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-sessions/<int:session_id>/orders', methods=['GET'])
    def get_session_orders(session_id):
        """获取会话订单"""
        try:
            orders = db.get_orders(session_id)
            return jsonify({'success': True, 'data': orders})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-sessions/<int:session_id>/trades', methods=['GET'])
    def get_session_trades(session_id):
        """获取会话交易记录"""
        try:
            trades = db.get_trades(session_id)
            return jsonify({'success': True, 'data': trades})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-sessions/<int:session_id>/capital', methods=['GET'])
    def get_session_capital(session_id):
        """获取会话资金历史"""
        try:
            history = db.get_capital_history(session_id)
            stats = db.get_statistics(session_id)
            return jsonify({
                'success': True,
                'data': {
                    'history': history,
                    'statistics': stats
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-sessions/<int:session_id>/state', methods=['GET'])
    def get_session_state(session_id):
        """获取会话当前状态"""
        try:
            repo = DbStateRepository(db, session_id)
            state = repo.load()
            if state:
                return jsonify({'success': True, 'data': state})
            return jsonify({'success': True, 'data': None})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # ==================== 统计 API ====================

    @app.route('/api/stats', methods=['GET'])
    def get_stats():
        """获取统计数据"""
        try:
            symbol = request.args.get('symbol')
            stats = db.get_statistics_summary(symbol)
            return jsonify({'success': True, 'data': stats})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/active-sessions', methods=['GET'])
    def get_active_sessions():
        """获取活跃会话"""
        try:
            sessions = db.get_active_sessions()
            return jsonify({'success': True, 'data': sessions})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # ==================== 策略默认参数 API ====================

    @app.route('/api/defaults', methods=['GET'])
    def get_all_defaults():
        """获取所有策略默认参数（只有默认值）"""
        try:
            defaults = ConfigLoader.load_strategy_defaults()
            return jsonify({'success': True, 'data': defaults})
        except Exception as e:
            logger.error(f"获取策略默认参数失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/defaults/entry', methods=['GET'])
    def get_entry_defaults():
        """获取入场策略默认参数

        Query params:
            strategy: 策略名称（atr/bollinger/support/composite/fixed），不指定则返回所有
        """
        try:
            strategy_name = request.args.get('strategy')
            defaults = ConfigLoader.get_entry_strategy_defaults(strategy_name)
            return jsonify({'success': True, 'data': defaults})
        except Exception as e:
            logger.error(f"获取入场策略默认参数失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/defaults/market', methods=['GET'])
    def get_market_defaults():
        """获取行情策略默认参数

        Query params:
            algorithm: 算法名称（dual_thrust/improved/composite/adx/always_ranging），不指定则返回所有
        """
        try:
            algorithm_name = request.args.get('algorithm')
            defaults = ConfigLoader.get_market_strategy_defaults(algorithm_name)
            return jsonify({'success': True, 'data': defaults})
        except Exception as e:
            logger.error(f"获取行情策略默认参数失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/defaults/capital', methods=['GET'])
    def get_capital_defaults():
        """获取资金策略默认参数

        Query params:
            strategy: 策略名称（guding/wenjian/jijin/fuli/baoshou），不指定则返回所有
        """
        try:
            strategy_name = request.args.get('strategy')
            defaults = ConfigLoader.get_capital_strategy_defaults(strategy_name)
            return jsonify({'success': True, 'data': defaults})
        except Exception as e:
            logger.error(f"获取资金策略默认参数失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/defaults/timeout', methods=['GET'])
    def get_timeout_defaults():
        """获取超时参数默认值"""
        try:
            defaults = ConfigLoader.get_timeout_defaults()
            return jsonify({'success': True, 'data': defaults})
        except Exception as e:
            logger.error(f"获取超时参数默认值失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ==================== 参数定义 API（含元信息，用于 Web 表单） ====================

    @app.route('/api/definitions/entry', methods=['GET'])
    def get_entry_definition():
        """获取入场策略参数定义（含元信息：default, type, min, max）

        用于 Web 表单渲染和验证
        """
        try:
            strategy_name = request.args.get('strategy')
            definition = ConfigLoader.get_entry_strategy_definition(strategy_name)
            return jsonify({'success': True, 'data': definition})
        except Exception as e:
            logger.error(f"获取入场策略定义失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/definitions/market', methods=['GET'])
    def get_market_definition():
        """获取行情策略参数定义（含元信息）"""
        try:
            algorithm_name = request.args.get('algorithm')
            definition = ConfigLoader.get_market_strategy_definition(algorithm_name)
            return jsonify({'success': True, 'data': definition})
        except Exception as e:
            logger.error(f"获取行情策略定义失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/definitions/capital', methods=['GET'])
    def get_capital_definition():
        """获取资金策略参数定义（含元信息）"""
        try:
            strategy_name = request.args.get('strategy')
            definition = ConfigLoader.get_capital_strategy_definition(strategy_name)
            return jsonify({'success': True, 'data': definition})
        except Exception as e:
            logger.error(f"获取资金策略定义失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/definitions/timeout', methods=['GET'])
    def get_timeout_definition():
        """获取超时参数定义（含元信息）"""
        try:
            definition = ConfigLoader.get_timeout_definition()
            return jsonify({'success': True, 'data': definition})
        except Exception as e:
            logger.error(f"获取超时参数定义失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/definitions/amplitude', methods=['GET'])
    def get_amplitude_definition():
        """获取振幅参数定义（含元信息）"""
        try:
            definition = ConfigLoader.get_amplitude_definition()
            return jsonify({'success': True, 'data': definition})
        except Exception as e:
            logger.error(f"获取振幅参数定义失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ==================== 振幅配置 API ====================

    @app.route('/api/amplitudes', methods=['GET'])
    def list_amplitudes():
        """列出所有可用的振幅配置文件"""
        try:
            amplitudes = ConfigLoader.list_available_amplitudes()
            return jsonify({'success': True, 'data': amplitudes})
        except Exception as e:
            logger.error(f"获取振幅配置列表失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/amplitudes/<exchange>/<symbol>', methods=['GET'])
    def get_amplitude_config(exchange, symbol):
        """获取指定标的的振幅配置

        Query params:
            decay_factor: 衰减因子，不指定则返回所有预设
        """
        try:
            decay_factor = request.args.get('decay_factor')
            if decay_factor:
                decay_factor = float(decay_factor)
            config = ConfigLoader.load_amplitude_config(symbol, exchange, decay_factor)
            return jsonify({'success': True, 'data': config})
        except Exception as e:
            logger.error(f"获取振幅配置失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ==================== 实盘交易管理 API（使用 LiveTraderManager） ====================

    @app.route('/api/traders', methods=['GET'])
    def get_traders():
        """获取当前运行的交易器列表"""
        try:
            traders_info = run_async(trader_manager.list_traders())
            return jsonify({'success': True, 'data': traders_info})
        except Exception as e:
            logger.error(f"获取交易器列表失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/traders/<int:session_id>', methods=['GET'])
    def get_trader(session_id):
        """获取指定交易器状态"""
        try:
            trader_info = run_async(trader_manager.get_trader_info(session_id))
            if trader_info:
                return jsonify({'success': True, 'data': trader_info})
            return jsonify({'success': False, 'error': 'Trader not found'}), 404
        except Exception as e:
            logger.error(f"获取交易器状态失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/traders/start/<int:case_id>', methods=['POST'])
    def start_trader(case_id):
        """启动实盘交易器"""
        try:
            # 先创建 trader
            trader = run_async(trader_manager.create_trader_from_case(case_id))
            if not trader:
                return jsonify({'success': False, 'error': 'Failed to create trader'}), 500

            # 启动 trader
            session_id = run_async(trader_manager.start_trader(trader))
            if session_id:
                return jsonify({
                    'success': True,
                    'data': {
                        'session_id': session_id,
                        'case_id': case_id,
                        'symbol': trader.symbol
                    }
                })
            return jsonify({'success': False, 'error': 'Failed to start trader'}), 500
        except Exception as e:
            logger.error(f"启动交易器失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/traders/stop/<int:session_id>', methods=['POST'])
    def stop_trader(session_id):
        """停止实盘交易器"""
        try:
            success = run_async(trader_manager.stop_trader(session_id))
            if success:
                return jsonify({'success': True, 'data': {'session_id': session_id}})
            return jsonify({'success': False, 'error': 'Failed to stop trader'}), 500
        except Exception as e:
            logger.error(f"停止交易器失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/traders/pause/<int:session_id>', methods=['POST'])
    def pause_trader(session_id):
        """暂停实盘交易器

        暂停后：
        - WebSocket 保持连接
        - 继续处理订单事件（止盈/止损）
        - 不下新订单
        """
        try:
            success = run_async(trader_manager.pause_trader(session_id))
            if success:
                return jsonify({'success': True, 'data': {'session_id': session_id, 'status': 'paused'}})
            return jsonify({'success': False, 'error': 'Failed to pause trader'}), 500
        except Exception as e:
            logger.error(f"暂停交易器失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/traders/resume/<int:session_id>', methods=['POST'])
    def resume_trader(session_id):
        """恢复实盘交易器

        恢复前会同步交易所状态：
        - 同步订单状态
        - 同步资金池状态
        """
        try:
            result = run_async(trader_manager.resume_trader(session_id))
            if result.get('success'):
                return jsonify({
                    'success': True,
                    'data': {
                        'session_id': session_id,
                        'status': 'running',
                        'order_sync': result.get('order_sync'),
                        'capital_sync': result.get('capital_sync')
                    }
                })
            return jsonify({'success': False, 'error': result.get('error', 'Failed to resume')}), 500
        except Exception as e:
            logger.error(f"恢复交易器失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/live-sessions/<int:session_id>/reset', methods=['POST'])
    def reset_live_session(session_id):
        """重置实盘会话（清除状态数据）"""
        try:
            session = db.get_session(session_id)
            if not session:
                return jsonify({'success': False, 'error': 'Session not found'}), 404

            if session.get('status') == 'running':
                return jsonify({'success': False, 'error': 'Cannot reset running session'}), 400

            # 删除会话相关数据
            db.delete_session_data(session_id)

            return jsonify({'success': True, 'message': f'Session {session_id} reset'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # ==================== 静态文件 ====================

    @app.route('/static/<path:filename>')
    def serve_static(filename):
        static_dir = base_dir / 'web/static'
        return send_from_directory(str(static_dir), filename)

    return app


def run_server(host='0.0.0.0', port=5003, debug=False):
    """启动 Web API 服务"""
    app = create_flask_app()
    print(f"\n🌐 实盘交易 Web API 服务启动")
    print(f"   地址: http://{host}:{port}")
    print(f"   API 文档:")
    print(f"     --- 实盘配置 ---")
    print(f"     - GET    /api/live-cases           - 实盘配置列表")
    print(f"     - POST   /api/live-cases           - 创建实盘配置")
    print(f"     - GET    /api/live-cases/:id       - 实盘配置详情")
    print(f"     - PUT    /api/live-cases/:id       - 更新实盘配置")
    print(f"     - DELETE /api/live-cases/:id       - 删除实盘配置")
    print(f"     - POST   /api/live-cases/:id/reset - 重置配置")
    print(f"     - POST   /api/live-cases/:id/copy  - 复制配置")
    print(f"     --- 实盘会话 ---")
    print(f"     - GET    /api/live-sessions        - 实盘会话列表")
    print(f"     - GET    /api/live-sessions/:id    - 会话详情")
    print(f"     - GET    /api/live-sessions/:id/orders  - 会话订单")
    print(f"     - GET    /api/live-sessions/:id/trades  - 交易记录")
    print(f"     - GET    /api/live-sessions/:id/capital - 资金历史")
    print(f"     - POST   /api/live-sessions/:id/reset - 重置会话")
    print(f"     --- 策略默认参数（只有默认值）---")
    print(f"     - GET    /api/defaults             - 所有策略默认参数")
    print(f"     - GET    /api/defaults/entry       - 入场策略默认参数")
    print(f"     - GET    /api/defaults/market      - 行情策略默认参数")
    print(f"     - GET    /api/defaults/capital     - 资金策略默认参数")
    print(f"     - GET    /api/defaults/timeout     - 超时参数默认值")
    print(f"     --- 参数定义（含元信息，用于表单）---")
    print(f"     - GET    /api/definitions/entry    - 入场策略参数定义")
    print(f"     - GET    /api/definitions/market   - 行情策略参数定义")
    print(f"     - GET    /api/definitions/capital  - 资金策略参数定义")
    print(f"     - GET    /api/definitions/timeout  - 超时参数定义")
    print(f"     - GET    /api/definitions/amplitude - 振幅参数定义")
    print(f"     --- 振幅配置 ---")
    print(f"     - GET    /api/amplitudes           - 可用振幅配置列表")
    print(f"     - GET    /api/amplitudes/:exchange/:symbol - 标的振幅配置")
    print(f"     --- 统计 ---")
    print(f"     - GET    /api/stats                - 统计数据")
    print(f"     - GET    /api/active-sessions      - 活跃会话")
    print(f"     --- 实盘交易器管理 ---")
    print(f"     - GET    /api/traders              - 获取运行中的交易器列表")
    print(f"     - GET    /api/traders/:session_id  - 获取交易器详细状态")
    print(f"     - POST   /api/traders/start/:case_id   - 启动交易器")
    print(f"     - POST   /api/traders/pause/:session_id - 暂停交易器")
    print(f"     - POST   /api/traders/resume/:session_id - 恢复交易器")
    print(f"     - POST   /api/traders/stop/:session_id  - 停止交易器")
    print()

    app.run(host=host, port=port, debug=debug)


# ============================================================================
# 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="实盘交易管理系统")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # create-case 命令
    create_case_parser = subparsers.add_parser("create-case", help="创建实盘配置")
    create_case_parser.add_argument("--symbol", required=True, help="交易对")
    create_case_parser.add_argument("--name", help="配置名称")
    create_case_parser.add_argument("--description", help="描述")
    create_case_parser.add_argument("--testnet", action="store_true", default=True, help="使用测试网 (默认)")
    create_case_parser.add_argument("--no-testnet", dest="testnet", action="store_false", help="使用主网")
    create_case_parser.add_argument("--total-amount", type=float, default=10000, help="总资金 (USDT)")
    create_case_parser.add_argument("--leverage", type=int, default=10, help="杠杆倍数")
    create_case_parser.add_argument("--max-entries", type=int, default=4, help="最大层级")
    create_case_parser.add_argument("--grid-spacing", type=float, default=0.01, help="网格间距")
    create_case_parser.add_argument("--exit-profit", type=float, default=0.01, help="止盈比例")
    create_case_parser.add_argument("--stop-loss", type=float, default=0.08, help="止损比例")
    create_case_parser.add_argument("--decay-factor", type=float, default=0.5, help="衰减因子")
    create_case_parser.add_argument("--weights", type=json.loads, help="权重配置 (JSON)")
    create_case_parser.add_argument("--market-aware", action="store_true", help="启用行情感知")
    create_case_parser.add_argument("--market-algorithm", default="dual_thrust", help="行情算法")
    create_case_parser.add_argument("--trading-statuses", type=json.loads, help="交易状态列表 (JSON)")
    create_case_parser.add_argument("--market-params", help="行情参数 (JSON)")
    create_case_parser.add_argument("--entry-params", help="入场参数 (JSON)")
    create_case_parser.add_argument("--a1-timeout", type=int, default=0, help="A1 超时 (分钟)")
    create_case_parser.add_argument("--capital-strategy", default="guding", help="资金策略")
    create_case_parser.add_argument("--entry-mode", default="compound", help="入场模式")
    create_case_parser.add_argument("--capital-params", help="资金参数 (JSON)")

    # list-cases 命令
    list_cases_parser = subparsers.add_parser("list-cases", help="列出实盘配置")
    list_cases_parser.add_argument("--symbol", help="按交易对筛选")
    list_cases_parser.add_argument("--status", help="按状态筛选")
    list_cases_parser.add_argument("--limit", type=int, default=50, help="限制数量")

    # show-case 命令
    show_case_parser = subparsers.add_parser("show-case", help="查看实盘配置详情")
    show_case_parser.add_argument("id", type=int, help="配置ID")

    # delete-case 命令
    delete_case_parser = subparsers.add_parser("delete-case", help="删除实盘配置")
    delete_case_parser.add_argument("id", type=int, help="配置ID")

    # run-case 命令
    run_case_parser = subparsers.add_parser("run-case", help="启动实盘交易")
    run_case_parser.add_argument("id", type=int, help="配置ID")
    run_case_parser.add_argument("--dry-run", action="store_true", help="只打印命令，不执行")

    # list-sessions 命令
    list_sessions_parser = subparsers.add_parser("list-sessions", help="列出实盘会话")
    list_sessions_parser.add_argument("--case-id", type=int, help="按配置ID筛选")
    list_sessions_parser.add_argument("--symbol", help="按交易对筛选")
    list_sessions_parser.add_argument("--status", help="按状态筛选")
    list_sessions_parser.add_argument("--limit", type=int, default=50, help="限制数量")

    # show-session 命令
    show_session_parser = subparsers.add_parser("show-session", help="查看会话详情")
    show_session_parser.add_argument("id", type=int, help="会话ID")

    # stop-session 命令
    stop_session_parser = subparsers.add_parser("stop-session", help="停止会话")
    stop_session_parser.add_argument("id", type=int, help="会话ID")

    # stats 命令
    stats_parser = subparsers.add_parser("stats", help="查看统计数据")
    stats_parser.add_argument("--symbol", help="按交易对筛选")

    # serve 命令
    serve_parser = subparsers.add_parser("serve", help="启动Web API服务")
    serve_parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    serve_parser.add_argument("--port", type=int, default=5003, help="监听端口")
    serve_parser.add_argument("--debug", action="store_true", help="调试模式")

    args = parser.parse_args()

    if args.command == "create-case":
        _create_case(args)
    elif args.command == "list-cases":
        _list_cases(args)
    elif args.command == "show-case":
        _show_case(args)
    elif args.command == "delete-case":
        _delete_case(args)
    elif args.command == "run-case":
        _run_case(args)
    elif args.command == "list-sessions":
        _list_sessions(args)
    elif args.command == "show-session":
        _show_session(args)
    elif args.command == "stop-session":
        _stop_session(args)
    elif args.command == "stats":
        _show_stats(args)
    elif args.command == "serve":
        run_server(host=args.host, port=args.port, debug=args.debug)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
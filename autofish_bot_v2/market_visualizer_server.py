#!/usr/bin/env python3
"""
行情可视化系统 Web 服务器
提供 RESTful API 和 Web 界面
"""

import os
import sys
import json
import time
import asyncio
import threading
import logging
from datetime import datetime
from typing import Dict, List, Optional
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

from market_visualizer_db import MarketVisualizerDB, TestCase, TestResult, DailyStatus

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOGS_DIR, 'market_visualizer_server.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('MarketVisualizerServer')

app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')
CORS(app)

db = MarketVisualizerDB()

logger.info("服务器初始化完成")


ALGORITHMS = {
    'dual_thrust': {
        'name': 'Dual Thrust',
        'description': '基于突破的行情判断算法',
        'params': {
            'k1': {'type': 'float', 'default': 0.5, 'description': '上轨系数'},
            'k2': {'type': 'float', 'default': 0.5, 'description': '下轨系数'},
            'k2_down_factor': {'type': 'float', 'default': 0.5, 'description': '下跌识别因子'},
            'down_confirm_days': {'type': 'int', 'default': 1, 'description': '下跌确认天数'},
        }
    },
    'improved': {
        'name': 'Improved Status',
        'description': '改进的行情状态判断算法',
        'params': {
            'volatility_threshold': {'type': 'float', 'default': 0.02, 'description': '波动率阈值'},
            'trend_confirm_days': {'type': 'int', 'default': 3, 'description': '趋势确认天数'},
        }
    },
    'always_ranging': {
        'name': 'Always Ranging',
        'description': '始终判定为震荡状态',
        'params': {}
    }
}

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT']


@app.route('/')
def index():
    """主页"""
    logger.info("访问主页")
    return send_from_directory('templates', 'index.html')


@app.route('/api/test-cases', methods=['GET'])
def get_test_cases():
    """获取测试用例列表"""
    symbol = request.args.get('symbol')
    algorithm = request.args.get('algorithm')
    status = request.args.get('status')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    logger.info(f"获取测试用例列表: symbol={symbol}, algorithm={algorithm}, status={status}, limit={limit}, offset={offset}")
    
    cases = db.get_test_cases(
        symbol=symbol,
        algorithm=algorithm,
        status=status,
        limit=limit,
        offset=offset
    )
    
    total = db.count_test_cases(symbol=symbol, algorithm=algorithm, status=status)
    
    logger.info(f"返回测试用例: {len(cases)}条, 总计{total}条")
    
    return jsonify({
        'success': True,
        'data': {
            'items': [case_to_dict(c) for c in cases],
            'total': total,
            'limit': limit,
            'offset': offset
        }
    })


@app.route('/api/test-cases/<test_case_id>', methods=['GET'])
def get_test_case(test_case_id: str):
    """获取单个测试用例详情"""
    logger.info(f"获取测试用例详情: {test_case_id}")
    
    case = db.get_test_case(test_case_id)
    if case is None:
        logger.warning(f"测试用例不存在: {test_case_id}")
        return jsonify({'success': False, 'error': '测试用例不存在'}), 404
    
    result = db.get_test_result_by_case(test_case_id)
    
    data = case_to_dict(case)
    data['result'] = result_to_dict(result) if result else None
    
    logger.info(f"返回测试用例: {case.name}, 状态: {case.status}")
    
    return jsonify({'success': True, 'data': data})


@app.route('/api/test-cases', methods=['POST'])
def create_test_case():
    """创建并执行新测试"""
    data = request.get_json()
    
    logger.info(f"创建新测试: {data}")
    
    required_fields = ['name', 'symbol', 'start_date', 'end_date', 'algorithm']
    for field in required_fields:
        if field not in data:
            logger.error(f"缺少必填字段: {field}")
            return jsonify({'success': False, 'error': f'缺少必填字段: {field}'}), 400
    
    algorithm = data['algorithm']
    if algorithm not in ALGORITHMS:
        logger.error(f"不支持的算法: {algorithm}")
        return jsonify({'success': False, 'error': f'不支持的算法: {algorithm}'}), 400
    
    test_case = db.create_test_case(
        name=data['name'],
        symbol=data['symbol'],
        interval=data.get('interval', '1d'),
        start_date=data['start_date'],
        end_date=data['end_date'],
        algorithm=algorithm,
        algorithm_config=data.get('algorithm_config', {}),
        description=data.get('description', ''),
    )
    
    logger.info(f"测试用例已创建: {test_case.id} - {test_case.name}")
    
    generate_files = {
        'md': data.get('generate_md', False),
        'png': data.get('generate_png', False),
        'html': data.get('generate_html', False),
    }
    
    thread = threading.Thread(
        target=execute_test_async,
        args=(test_case.id, generate_files)
    )
    thread.start()
    
    logger.info(f"测试执行线程已启动: {test_case.id}")
    
    return jsonify({
        'success': True,
        'data': case_to_dict(test_case),
        'message': '测试已开始执行'
    })


@app.route('/api/test-cases/<test_case_id>/re-run', methods=['POST'])
def re_run_test(test_case_id: str):
    """重新执行测试"""
    logger.info(f"重新执行测试: {test_case_id}")
    
    case = db.get_test_case(test_case_id)
    if case is None:
        logger.warning(f"测试用例不存在: {test_case_id}")
        return jsonify({'success': False, 'error': '测试用例不存在'}), 404
    
    db.update_test_case_status(test_case_id, 'pending')
    
    thread = threading.Thread(
        target=execute_test_async,
        args=(test_case_id,)
    )
    thread.start()
    
    logger.info(f"重新执行线程已启动: {test_case_id}")
    
    return jsonify({
        'success': True,
        'message': '测试已开始重新执行'
    })


@app.route('/api/test-cases/<test_case_id>', methods=['DELETE'])
def delete_test_case(test_case_id: str):
    """删除测试用例"""
    logger.info(f"删除测试用例: {test_case_id}")
    
    case = db.get_test_case(test_case_id)
    if case is None:
        logger.warning(f"测试用例不存在: {test_case_id}")
        return jsonify({'success': False, 'error': '测试用例不存在'}), 404
    
    db.delete_test_case(test_case_id)
    
    logger.info(f"测试用例已删除: {test_case_id}")
    
    return jsonify({'success': True, 'message': '删除成功'})


@app.route('/api/test-results/<test_result_id>', methods=['GET'])
def get_test_result(test_result_id: str):
    """获取测试结果"""
    logger.info(f"获取测试结果: {test_result_id}")
    
    result = db.get_test_result(test_result_id)
    if result is None:
        logger.warning(f"测试结果不存在: {test_result_id}")
        return jsonify({'success': False, 'error': '测试结果不存在'}), 404
    
    return jsonify({'success': True, 'data': result_to_dict(result)})


@app.route('/api/daily-statuses/<test_result_id>', methods=['GET'])
def get_daily_statuses(test_result_id: str):
    """获取每日状态数据"""
    logger.info(f"获取每日状态数据: {test_result_id}")
    
    statuses = db.get_daily_statuses(test_result_id)
    
    logger.info(f"返回每日状态: {len(statuses)}条")
    
    return jsonify({
        'success': True,
        'data': [daily_status_to_dict(s) for s in statuses]
    })


@app.route('/api/statistics/<test_result_id>', methods=['GET'])
def get_statistics(test_result_id: str):
    """获取统计信息"""
    logger.info(f"获取统计信息: {test_result_id}")
    
    stats = db.get_statistics(test_result_id)
    
    return jsonify({'success': True, 'data': stats})


@app.route('/api/klines', methods=['GET'])
def get_klines():
    """获取K线数据"""
    symbol = request.args.get('symbol')
    interval = request.args.get('interval', '1d')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    logger.info(f"获取K线数据: symbol={symbol}, interval={interval}, start={start_date}, end={end_date}")
    
    if not symbol or not start_date or not end_date:
        logger.error("缺少必要参数")
        return jsonify({'success': False, 'error': '缺少必要参数'}), 400
    
    try:
        from binance_kline_fetcher import KlineFetcher
        
        fetcher = KlineFetcher()
        klines = asyncio.run(fetcher.get_klines(
            symbol=symbol,
            interval=interval,
            start_time=start_date,
            end_time=end_date
        ))
        
        logger.info(f"返回K线数据: {len(klines)}条")
        
        return jsonify({
            'success': True,
            'data': klines
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/symbols', methods=['GET'])
def get_symbols():
    """获取可用交易对列表"""
    return jsonify({'success': True, 'data': SYMBOLS})


@app.route('/api/algorithms', methods=['GET'])
def get_algorithms():
    """获取可用算法列表"""
    return jsonify({'success': True, 'data': ALGORITHMS})


@app.route('/api/algorithm-params/<algorithm_name>', methods=['GET'])
def get_algorithm_params(algorithm_name: str):
    """获取算法参数定义"""
    if algorithm_name not in ALGORITHMS:
        return jsonify({'success': False, 'error': '算法不存在'}), 404
    
    return jsonify({
        'success': True,
        'data': ALGORITHMS[algorithm_name]['params']
    })


@app.route('/api/compare', methods=['POST'])
def compare_tests():
    """对比多个测试结果"""
    try:
        data = request.get_json()
        test_case_ids = data.get('test_case_ids', [])
        
        if len(test_case_ids) < 2:
            return jsonify({'success': False, 'error': '至少需要选择2个测试'}), 400
        
        if len(test_case_ids) > 4:
            return jsonify({'success': False, 'error': '最多只能对比4个测试'}), 400
        
        results = []
        for tc_id in test_case_ids:
            case = db.get_test_case(tc_id)
            if case is None:
                continue
            
            result = db.get_test_result_by_case(tc_id)
            stats = db.get_statistics(result.id) if result else None
            daily_statuses = db.get_daily_statuses(result.id) if result else []
            
            results.append({
                'test_case': case_to_dict(case),
                'result': result_to_dict(result) if result else None,
                'statistics': stats,
                'daily_statuses': daily_statuses,
            })
        
        return jsonify({'success': True, 'data': results})
    except Exception as e:
        logger.error(f"对比测试异常: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def execute_test_async(test_case_id: str, generate_files: Dict = None):
    """异步执行测试"""
    if generate_files is None:
        generate_files = {'md': False, 'png': False, 'html': False}
    
    try:
        logger.info(f"[{test_case_id}] 开始执行测试, 文件生成: {generate_files}")
        db.update_test_case_status(test_case_id, 'running')
        
        case = db.get_test_case(test_case_id)
        if case is None:
            logger.error(f"[{test_case_id}] 测试用例不存在")
            return
        
        logger.info(f"[{test_case_id}] 测试参数: symbol={case.symbol}, interval={case.interval}, date={case.start_date}~{case.end_date}, algorithm={case.algorithm}")
        
        start_time = time.time()
        
        logger.info(f"[{test_case_id}] 开始获取K线数据...")
        from binance_kline_fetcher import KlineFetcher
        
        fetcher = KlineFetcher()
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            start_ts = int(datetime.strptime(case.start_date, '%Y-%m-%d').timestamp() * 1000)
            end_ts = int(datetime.strptime(case.end_date, '%Y-%m-%d').timestamp() * 1000) + 86400000 - 1
            
            klines = loop.run_until_complete(fetcher.fetch_and_cache(
                symbol=case.symbol,
                interval=case.interval,
                start_time=start_ts,
                end_time=end_ts
            ))
            loop.close()
        except Exception as e:
            logger.error(f"[{test_case_id}] 获取K线数据异常: {e}")
            db.update_test_case_status(test_case_id, 'failed')
            return
        
        if not klines:
            logger.error(f"[{test_case_id}] 获取K线数据失败或数据为空")
            db.update_test_case_status(test_case_id, 'failed')
            return
        
        logger.info(f"[{test_case_id}] 获取到 {len(klines)} 条K线数据")
        
        logger.info(f"[{test_case_id}] 开始运行算法: {case.algorithm}")
        from market_status_visualizer import AlgorithmRunner
        
        config = case.algorithm_config or {}
        logger.info(f"[{test_case_id}] 算法配置: {config}")
        runner = AlgorithmRunner(case.algorithm, config)
        
        daily_results = runner.run(klines)
        logger.info(f"[{test_case_id}] 算法运行完成, 得到 {len(daily_results)} 条每日状态")
        
        status_ranges = integrate_status_ranges(daily_results)
        logger.info(f"[{test_case_id}] 整合得到 {len(status_ranges)} 个状态区间")
        
        daily_statuses = []
        ranging_days = trending_up_days = trending_down_days = 0
        ranging_count = trending_up_count = trending_down_count = 0
        
        for dr in daily_results:
            daily_statuses.append({
                'date': dr.date,
                'status': dr.status.value,
                'confidence': dr.confidence,
                'reason': dr.reason,
                'open_price': dr.open_price,
                'close_price': dr.close_price,
                'high_price': dr.high_price,
                'low_price': dr.low_price,
                'volume': 0,
            })
            
            if dr.status.value == 'ranging':
                ranging_days += 1
            elif dr.status.value == 'trending_up':
                trending_up_days += 1
            else:
                trending_down_days += 1
        
        for sr in status_ranges:
            if sr['status'] == 'ranging':
                ranging_count += 1
            elif sr['status'] == 'trending_up':
                trending_up_count += 1
            else:
                trending_down_count += 1
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        test_result = db.create_test_result(
            test_case_id=test_case_id,
            total_days=len(daily_results),
            ranging_days=ranging_days,
            trending_up_days=trending_up_days,
            trending_down_days=trending_down_days,
            ranging_count=ranging_count,
            trending_up_count=trending_up_count,
            trending_down_count=trending_down_count,
            status_ranges=status_ranges,
            duration_ms=duration_ms,
        )
        
        db.create_daily_statuses(test_result.id, daily_statuses)
        
        logger.info(f"[{test_case_id}] 生成输出文件...")
        try:
            from market_status_visualizer import (
                ReportGenerator, ChartVisualizer, WebChartVisualizer,
                DailyStatus as VizDailyStatus, MarketStatus, StatusRange
            )
            import pandas as pd
            
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'market_visualizer_out')
            
            viz_daily_statuses = []
            for ds in daily_statuses:
                viz_ds = VizDailyStatus(
                    date=ds['date'],
                    timestamp=0,
                    status=MarketStatus(ds['status']),
                    confidence=ds['confidence'],
                    reason=ds['reason'],
                    open_price=ds['open_price'],
                    close_price=ds['close_price'],
                    high_price=ds['high_price'],
                    low_price=ds['low_price'],
                )
                viz_daily_statuses.append(viz_ds)
            
            viz_ranges = []
            for sr in status_ranges:
                viz_r = StatusRange(
                    start_date=sr['start_date'],
                    end_date=sr['end_date'],
                    status=MarketStatus(sr['status']),
                    duration=sr['duration'],
                    start_price=sr['start_price'],
                    end_price=sr['end_price'],
                    price_change=sr['price_change'],
                )
                viz_ranges.append(viz_r)
            
            statistics = {
                'total_days': len(daily_results),
                'status_days': {
                    MarketStatus.RANGING: ranging_days,
                    MarketStatus.TRENDING_UP: trending_up_days,
                    MarketStatus.TRENDING_DOWN: trending_down_days,
                },
                'status_percent': {
                    MarketStatus.RANGING: round(ranging_days / len(daily_results) * 100, 1) if daily_results else 0,
                    MarketStatus.TRENDING_UP: round(trending_up_days / len(daily_results) * 100, 1) if daily_results else 0,
                    MarketStatus.TRENDING_DOWN: round(trending_down_days / len(daily_results) * 100, 1) if daily_results else 0,
                },
                'range_counts': {
                    MarketStatus.RANGING: ranging_count,
                    MarketStatus.TRENDING_UP: trending_up_count,
                    MarketStatus.TRENDING_DOWN: trending_down_count,
                },
            }
            
            date_range_str = f"{case.start_date.replace('-', '')}-{case.end_date.replace('-', '')}"
            
            existing_files = [f for f in os.listdir(output_dir) if f.startswith(f"market_visualizer_{case.symbol}_{case.interval}_{date_range_str}_{case.algorithm}")]
            seq = len([f for f in existing_files if f.endswith('.md')]) + 1
            
            if generate_files.get('md', False):
                report_gen = ReportGenerator(output_dir)
                report_path = report_gen.generate(
                    symbol=case.symbol,
                    interval=case.interval,
                    date_range=date_range_str,
                    algorithm=case.algorithm,
                    algorithm_config=config,
                    daily_statuses=viz_daily_statuses,
                    ranges=viz_ranges,
                    events=[],
                    statistics=statistics,
                    seq=seq,
                )
                logger.info(f"[{test_case_id}] MD报告已生成: {report_path}")
            
            if generate_files.get('png', False) or generate_files.get('html', False):
                chart_viz = ChartVisualizer(output_dir)
                df_data = []
                for ds in daily_statuses:
                    df_data.append({
                        'datetime': ds['date'],
                        'Open': ds['open_price'],
                        'High': ds['high_price'],
                        'Low': ds['low_price'],
                        'Close': ds['close_price'],
                        'Volume': ds['volume'],
                    })
                df = pd.DataFrame(df_data)
                df['datetime'] = pd.to_datetime(df['datetime'])
                df.set_index('datetime', inplace=True)
                
                if generate_files.get('png', False):
                    chart_path = chart_viz.plot(
                        df=df,
                        daily_statuses=viz_daily_statuses,
                        ranges=viz_ranges,
                        symbol=case.symbol,
                        interval=case.interval,
                        date_range=date_range_str,
                        algorithm=case.algorithm,
                        seq=seq,
                    )
                    logger.info(f"[{test_case_id}] PNG图表已生成: {chart_path}")
                
                if generate_files.get('html', False):
                    web_viz = WebChartVisualizer(output_dir)
                    html_path = web_viz.generate_html(
                        df=df,
                        daily_statuses=viz_daily_statuses,
                        ranges=viz_ranges,
                        symbol=case.symbol,
                        interval=case.interval,
                        date_range=date_range_str,
                        algorithm=case.algorithm,
                        algorithm_config=config,
                        statistics=statistics,
                        seq=seq,
                    )
                    logger.info(f"[{test_case_id}] HTML已生成: {html_path}")
            
        except Exception as e:
            logger.error(f"[{test_case_id}] 生成文件失败: {e}")
            import traceback
            traceback.print_exc()
        
        db.update_test_case_status(test_case_id, 'completed')
        logger.info(f"[{test_case_id}] 测试完成")
        
    except Exception as e:
        print(f"执行测试失败: {e}")
        import traceback
        traceback.print_exc()
        db.update_test_case_status(test_case_id, 'failed')


def integrate_status_ranges(daily_results: List[Dict]) -> List[Dict]:
    """将每日状态整合为区间"""
    if not daily_results:
        return []
    
    ranges = []
    current_range = None
    
    for dr in daily_results:
        if current_range is None:
            current_range = {
                'status': dr['status'],
                'start_date': dr['date'],
                'end_date': dr['date'],
                'start_price': dr['open'],
                'end_price': dr['close'],
                'duration': 1,
            }
        elif dr['status'] == current_range['status']:
            current_range['end_date'] = dr['date']
            current_range['end_price'] = dr['close']
            current_range['duration'] += 1
        else:
            start_price = current_range['start_price']
            end_price = current_range['end_price']
            current_range['price_change'] = round((end_price - start_price) / start_price * 100, 2)
            ranges.append(current_range)
            
            current_range = {
                'status': dr['status'],
                'start_date': dr['date'],
                'end_date': dr['date'],
                'start_price': dr['open'],
                'end_price': dr['close'],
                'duration': 1,
            }
    
    if current_range:
        start_price = current_range['start_price']
        end_price = current_range['end_price']
        current_range['price_change'] = round((end_price - start_price) / start_price * 100, 2)
        ranges.append(current_range)
    
    return ranges


def case_to_dict(case: TestCase) -> Dict:
    """将TestCase转换为字典"""
    return {
        'id': case.id,
        'name': case.name,
        'symbol': case.symbol,
        'interval': case.interval,
        'start_date': case.start_date,
        'end_date': case.end_date,
        'algorithm': case.algorithm,
        'algorithm_config': case.algorithm_config,
        'description': case.description,
        'created_at': case.created_at,
        'updated_at': case.updated_at,
        'status': case.status,
    }


def result_to_dict(result: TestResult) -> Dict:
    """将TestResult转换为字典"""
    return {
        'id': result.id,
        'test_case_id': result.test_case_id,
        'total_days': result.total_days,
        'ranging_days': result.ranging_days,
        'trending_up_days': result.trending_up_days,
        'trending_down_days': result.trending_down_days,
        'ranging_count': result.ranging_count,
        'trending_up_count': result.trending_up_count,
        'trending_down_count': result.trending_down_count,
        'status_ranges': result.status_ranges,
        'executed_at': result.executed_at,
        'duration_ms': result.duration_ms,
    }


def daily_status_to_dict(status: DailyStatus) -> Dict:
    """将DailyStatus转换为字典"""
    amplitude = 0
    if status.open_price and status.open_price > 0:
        amplitude = (status.high_price - status.low_price) / status.open_price * 100
    
    return {
        'id': status.id,
        'test_result_id': status.test_result_id,
        'date': status.date,
        'status': status.status,
        'confidence': status.confidence,
        'reason': status.reason,
        'open_price': status.open_price,
        'close_price': status.close_price,
        'high_price': status.high_price,
        'low_price': status.low_price,
        'volume': status.volume,
        'amplitude': round(amplitude, 2),
    }


if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    print("启动行情可视化服务器...")
    print("访问地址: http://localhost:5001")
    app.run(host='0.0.0.0', port=5001, debug=True)

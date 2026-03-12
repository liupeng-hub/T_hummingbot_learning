#!/usr/bin/env python3
"""
市场策略参数优化器

使用贝叶斯优化（Optuna）对行情判断算法和交易策略参数进行联合优化。

使用方法:
    # 运行50次优化试验
    python market_strategy_optimizer.py --symbol BTCUSDT --date-range 20200101-20260310 --n-trials 50

    # 使用更多试验次数
    python market_strategy_optimizer.py --symbol BTCUSDT --date-range 20200101-20260310 --n-trials 100
"""

import optuna
import pandas as pd
from datetime import datetime
import asyncio
import json
import os
import sys
import argparse
import logging
from decimal import Decimal
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_aware_backtest import MarketAwareBacktestEngine
from market_status_detector import (
    ImprovedStatusAlgorithm, 
    SupportResistanceDetector, 
    BoxRangeDetector,
    MarketStatus
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("market_strategy_optimizer")

optuna.logging.set_verbosity(optuna.logging.WARNING)


class MarketStrategyOptimizer:
    """市场策略参数优化器"""
    
    def __init__(self, symbol: str, date_range: str):
        self.symbol = symbol
        self.date_range = date_range
        self.results_file = 'autofish_output/optimization_results.csv'
        self.report_file = 'autofish_output/optimization_report.md'
        self.results: List[Dict] = []
        self.best_params: Optional[Dict] = None
        self.best_value: float = 0.0
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        
        os.makedirs('autofish_output', exist_ok=True)
        
        self._parse_date_range()
    
    def _parse_date_range(self):
        """解析日期范围"""
        try:
            parts = self.date_range.split('-')
            start_str = parts[0]
            end_str = parts[1]
            
            self._start_date = datetime.strptime(start_str, '%Y%m%d')
            self._end_date = datetime.strptime(end_str, '%Y%m%d')
            
            self._start_time = int(self._start_date.timestamp() * 1000)
            self._end_time = int(self._end_date.timestamp() * 1000) + 86400000 - 1
            
            self._total_days = (self._end_date - self._start_date).days + 1
            
            logger.info(f"日期范围: {self._start_date.strftime('%Y-%m-%d')} ~ {self._end_date.strftime('%Y-%m-%d')} ({self._total_days} 天)")
        except Exception as e:
            raise ValueError(f"日期范围解析失败: {e}")
    
    def objective(self, trial: optuna.Trial) -> float:
        """优化目标函数"""
        market_params = {
            'lookback_period': trial.suggest_int('lookback_period', 40, 90),
            'min_range_duration': trial.suggest_int('min_range_duration', 5, 20),
            'max_range_pct': trial.suggest_float('max_range_pct', 0.10, 0.25),
            'breakout_threshold': trial.suggest_float('breakout_threshold', 0.02, 0.05),
            'swing_window': trial.suggest_int('swing_window', 3, 7),
            'merge_threshold': trial.suggest_float('merge_threshold', 0.02, 0.05),
            'min_touches': trial.suggest_int('min_touches', 2, 5),
        }
        
        strategy_params = {
            'grid_spacing': trial.suggest_float('grid_spacing', 0.005, 0.02),
            'exit_profit': trial.suggest_float('exit_profit', 0.005, 0.02),
            'stop_loss': trial.suggest_float('stop_loss', 0.05, 0.12),
            'decay_factor': trial.suggest_float('decay_factor', 0.3, 0.7),
            'max_entries': trial.suggest_int('max_entries', 2, 6),
        }
        
        try:
            result = asyncio.run(self._run_backtest(market_params, strategy_params))
            
            self._record_result(trial, market_params, strategy_params, result)
            
            return result['score']
        except Exception as e:
            logger.error(f"Trial {trial.number} 失败: {e}")
            return 0.0
    
    async def _run_backtest(self, market_params: Dict, strategy_params: Dict) -> Dict:
        """运行回测并返回结果"""
        sr_detector = SupportResistanceDetector({
            'lookback_period': market_params['lookback_period'],
            'swing_window': market_params['swing_window'],
            'merge_threshold': market_params['merge_threshold'],
            'min_touches': market_params['min_touches'],
        })
        
        box_detector = BoxRangeDetector({
            'min_duration': market_params['min_range_duration'],
            'max_range_pct': market_params['max_range_pct'],
            'lookback_period': market_params['lookback_period'],
        })
        
        algorithm = ImprovedStatusAlgorithm({
            'lookback_period': market_params['lookback_period'],
            'min_range_duration': market_params['min_range_duration'],
            'max_range_pct': market_params['max_range_pct'],
            'breakout_threshold': market_params['breakout_threshold'],
        })
        algorithm.sr_detector = sr_detector
        algorithm.box_detector = box_detector
        
        config = {
            'symbol': self.symbol,
            'leverage': Decimal('10'),
            'grid_spacing': Decimal(str(strategy_params['grid_spacing'])),
            'exit_profit': Decimal(str(strategy_params['exit_profit'])),
            'stop_loss': Decimal(str(strategy_params['stop_loss'])),
            'total_amount_quote': Decimal('5000'),
            'max_entries': strategy_params['max_entries'],
            'decay_factor': Decimal(str(strategy_params['decay_factor'])),
        }
        
        market_config = {
            'algorithm': 'improved',
            'lookback_period': market_params['lookback_period'],
            'min_range_duration': market_params['min_range_duration'],
            'max_range_pct': market_params['max_range_pct'],
            'breakout_threshold': market_params['breakout_threshold'],
            'min_market_klines': market_params['lookback_period'],
        }
        
        engine = MarketAwareBacktestEngine(config, market_config)
        engine.market_detector.algorithm = algorithm
        
        await engine.run(
            symbol=self.symbol,
            interval='1m',
            start_time=self._start_time,
            end_time=self._end_time,
        )
        
        score = self._calculate_score(engine.results)
        
        net_profit = float(engine.results['net_profit']) if 'net_profit' in engine.results else 0.0
        if 'total_profit' in engine.results and 'total_loss' in engine.results:
            net_profit = float(engine.results['total_profit'] - engine.results['total_loss'])
        
        total_trades = engine.results.get('total_trades', 0)
        win_trades = engine.results.get('win_trades', 0)
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        
        return {
            'score': score,
            'total_trades': total_trades,
            'win_trades': win_trades,
            'win_rate': win_rate,
            'net_profit': net_profit,
            'max_drawdown': engine.results.get('max_drawdown', 0.0),
            'profit_factor': engine.results.get('profit_factor', 1.0),
            'market_changes': len(engine.results.get('market_status_events', [])),
            'trading_pct': engine.results.get('market_statistics', {}).get('trading_pct', 0.0),
        }
    
    def _calculate_score(self, results: Dict) -> float:
        """计算综合得分"""
        net_profit = float(results.get('total_profit', 0) - results.get('total_loss', 0))
        total_trades = results.get('total_trades', 0)
        win_trades = results.get('win_trades', 0)
        
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        
        profit_score = min(max(net_profit / 5000, -1.0), 2.0)
        
        winrate_score = win_rate / 100
        
        trading_pct = results.get('market_statistics', {}).get('trading_pct', 50)
        trading_score = min(trading_pct / 100, 1.0)
        
        score = (
            profit_score * 0.5 +
            winrate_score * 0.3 +
            trading_score * 0.2
        )
        
        return max(score, 0.0)
    
    def _record_result(self, trial: optuna.Trial, market_params: Dict, 
                       strategy_params: Dict, result: Dict):
        """记录结果"""
        record = {
            'trial': trial.number,
            'timestamp': datetime.now().isoformat(),
            **market_params,
            **strategy_params,
            **result
        }
        self.results.append(record)
        
        self._save_results()
    
    def run(self, n_trials: int = 50) -> optuna.Study:
        """运行优化"""
        print(f"\n{'='*60}")
        print(f"开始参数优化: {self.symbol}")
        print(f"时间范围: {self.date_range} ({self._total_days} 天)")
        print(f"试验次数: {n_trials}")
        print(f"{'='*60}\n")
        
        study = optuna.create_study(
            direction='maximize',
            study_name='market_strategy_optimization',
            sampler=optuna.samplers.TPESampler(seed=42),
        )
        
        study.optimize(self.objective, n_trials=n_trials, show_progress_bar=True)
        
        self.best_params = study.best_params
        self.best_value = study.best_value
        
        print(f"\n{'='*60}")
        print(f"优化完成!")
        print(f"最佳得分: {self.best_value:.4f}")
        print(f"{'='*60}\n")
        
        self._save_results()
        self._generate_report(study)
        
        return study
    
    def _save_results(self):
        """保存结果到CSV"""
        if not self.results:
            return
        
        df = pd.DataFrame(self.results)
        df.to_csv(self.results_file, index=False)
        logger.info(f"结果已保存: {self.results_file}")
    
    def _generate_report(self, study: optuna.Study):
        """生成优化报告"""
        best = study.best_params
        
        report = f"""# 参数优化报告

## 优化概览
- 优化时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
- 交易对: {self.symbol}
- 时间范围: {self.date_range} ({self._total_days} 天)
- 试验次数: {len(self.results)}
- 最佳得分: {study.best_value:.4f}

## 最佳参数组合

### 行情判断参数
| 参数 | 最优值 |
|------|--------|
| lookback_period | {best['lookback_period']} |
| min_range_duration | {best['min_range_duration']} |
| max_range_pct | {best['max_range_pct']:.3f} |
| breakout_threshold | {best['breakout_threshold']:.3f} |
| swing_window | {best['swing_window']} |
| merge_threshold | {best['merge_threshold']:.3f} |
| min_touches | {best['min_touches']} |

### 交易策略参数
| 参数 | 最优值 |
|------|--------|
| grid_spacing | {best['grid_spacing']:.4f} |
| exit_profit | {best['exit_profit']:.4f} |
| stop_loss | {best['stop_loss']:.2%} |
| decay_factor | {best['decay_factor']:.2f} |
| max_entries | {best['max_entries']} |

## Top 10 结果
| 排名 | 得分 | 净收益 | 胜率 | 交易次数 | 交易时间占比 |
|------|------|--------|------|----------|--------------|
"""
        
        sorted_results = sorted(self.results, key=lambda x: x['score'], reverse=True)[:10]
        for i, r in enumerate(sorted_results, 1):
            report += f"| {i} | {r['score']:.4f} | {r['net_profit']:.2f} | {r.get('win_rate', 0):.1f}% | {r['total_trades']} | {r.get('trading_pct', 0):.1f}% |\n"
        
        report += "\n## 参数重要性\n\n"
        try:
            importance = optuna.importance.get_param_importances(study)
            report += "| 参数 | 重要性 |\n"
            report += "|------|--------|\n"
            for param, imp in importance.items():
                report += f"| {param} | {imp:.4f} |\n"
        except Exception:
            report += "（参数重要性分析需要更多试验）\n"
        
        report += f"""
## 最佳参数使用方法

```bash
# 使用最佳参数运行回测
python market_aware_backtest.py \\
    --symbol {self.symbol} \\
    --date-range {self.date_range} \\
    --market-algorithm improved \\
    --decay-factor {best['decay_factor']:.2f} \\
    --stop-loss {best['stop_loss']:.2f} \\
    --total-amount 5000
```

## 参数说明

### 行情判断参数
- **lookback_period**: 回看周期（天），用于判断行情的历史数据长度
- **min_range_duration**: 最小震荡持续天数，识别震荡行情的最短持续时间
- **max_range_pct**: 最大区间宽度，震荡区间的最大价格波动范围
- **breakout_threshold**: 突破阈值，判断是否突破支撑/阻力位的阈值
- **swing_window**: 局部高低点窗口，识别支撑/阻力位的窗口大小
- **merge_threshold**: 价格合并阈值，将相近价格合并为同一支撑/阻力位
- **min_touches**: 最少触及次数，支撑/阻力位的最少触及次数

### 交易策略参数
- **grid_spacing**: 网格间距，相邻订单的价格间隔
- **exit_profit**: 止盈比例，订单止盈的价格比例
- **stop_loss**: 止损比例，整体仓位的止损比例
- **decay_factor**: 衰减因子，订单金额的衰减系数
- **max_entries**: 最大层数，最大订单数量
"""
        
        with open(self.report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"📄 报告已保存: {self.report_file}")


def main():
    parser = argparse.ArgumentParser(description="市场策略参数优化器")
    parser.add_argument('--symbol', default='BTCUSDT', help='交易对')
    parser.add_argument('--date-range', required=True, help='时间范围 (格式: yyyymmdd-yyyymmdd)')
    parser.add_argument('--n-trials', type=int, default=50, help='优化试验次数')
    args = parser.parse_args()
    
    optimizer = MarketStrategyOptimizer(args.symbol, args.date_range)
    study = optimizer.run(n_trials=args.n_trials)
    
    print(f"\n最佳参数:")
    for key, value in study.best_params.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")
    print(f"\n最佳得分: {study.best_value:.4f}")


if __name__ == '__main__':
    main()

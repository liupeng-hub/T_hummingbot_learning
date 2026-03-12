#!/usr/bin/env python3
"""
Dual Thrust 参数优化器

使用贝叶斯优化（Optuna）对 Dual Thrust 算法参数进行优化。

使用方法:
    python dual_thrust_optimizer.py --symbol BTCUSDT --date-range 20200101-20260310 --n-trials 50
"""

import optuna
import pandas as pd
from datetime import datetime
import asyncio
import os
import sys
import argparse
import logging
from decimal import Decimal
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_aware_backtest import MarketAwareBacktestEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("dual_thrust_optimizer")

optuna.logging.set_verbosity(optuna.logging.WARNING)


class DualThrustOptimizer:
    """Dual Thrust 参数优化器"""
    
    def __init__(self, symbol: str, date_range: str):
        self.symbol = symbol
        self.date_range = date_range
        self.results_file = 'autofish_output/dual_thrust_optimization_results.csv'
        self.report_file = 'autofish_output/dual_thrust_optimization_report.md'
        self.results: List[Dict] = []
        self.best_params: Optional[Dict] = None
        self.best_value: float = 0.0
        self._start_time: Optional[int] = None
        self._end_time: Optional[int] = None
        
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
        dual_thrust_params = {
            'n_days': trial.suggest_int('n_days', 2, 7),
            'k1': trial.suggest_float('k1', 0.3, 0.7),
            'k2': trial.suggest_float('k2', 0.3, 0.7),
            'k2_down_factor': trial.suggest_float('k2_down_factor', 0.5, 1.0),
            'down_confirm_days': trial.suggest_int('down_confirm_days', 1, 3),
            'cooldown_days': trial.suggest_int('cooldown_days', 1, 3),
        }
        
        strategy_params = {
            'grid_spacing': trial.suggest_float('grid_spacing', 0.008, 0.015),
            'exit_profit': trial.suggest_float('exit_profit', 0.008, 0.015),
            'stop_loss': trial.suggest_float('stop_loss', 0.08, 0.12),
            'decay_factor': trial.suggest_float('decay_factor', 0.4, 0.6),
            'max_entries': trial.suggest_int('max_entries', 2, 4),
        }
        
        try:
            result = asyncio.run(self._run_backtest(dual_thrust_params, strategy_params))
            
            self._record_result(trial, dual_thrust_params, strategy_params, result)
            
            return result['score']
        except Exception as e:
            logger.error(f"Trial {trial.number} 失败: {e}")
            return 0.0
    
    async def _run_backtest(self, dual_thrust_params: Dict, strategy_params: Dict) -> Dict:
        """运行回测并返回结果"""
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
            'algorithm': 'dual_thrust',
            'n_days': dual_thrust_params['n_days'],
            'k1': dual_thrust_params['k1'],
            'k2': dual_thrust_params['k2'],
            'k2_down_factor': dual_thrust_params['k2_down_factor'],
            'down_confirm_days': dual_thrust_params['down_confirm_days'],
            'cooldown_days': dual_thrust_params['cooldown_days'],
            'min_market_klines': dual_thrust_params['n_days'] + 1,
        }
        
        engine = MarketAwareBacktestEngine(config, market_config)
        
        await engine.run(
            symbol=self.symbol,
            interval='1m',
            start_time=self._start_time,
            end_time=self._end_time,
        )
        
        score = self._calculate_score(engine.results)
        
        net_profit = float(engine.results['total_profit'] - engine.results['total_loss']) if 'total_profit' in engine.results else 0.0
        
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
        
        profit_score = min(max(net_profit / 5000, -1.0), 3.0)
        
        winrate_score = win_rate / 100
        
        trading_pct = results.get('market_statistics', {}).get('trading_pct', 50)
        trading_score = min(trading_pct / 100, 1.0)
        
        score = (
            profit_score * 0.5 +
            winrate_score * 0.3 +
            trading_score * 0.2
        )
        
        return max(score, 0.0)
    
    def _record_result(self, trial: optuna.Trial, dual_thrust_params: Dict, 
                       strategy_params: Dict, result: Dict):
        """记录结果"""
        record = {
            'trial': trial.number,
            'timestamp': datetime.now().isoformat(),
            **dual_thrust_params,
            **strategy_params,
            **result
        }
        self.results.append(record)
        
        self._save_results()
    
    def run(self, n_trials: int = 50) -> optuna.Study:
        """运行优化"""
        print(f"\n{'='*60}")
        print(f"开始 Dual Thrust 参数优化: {self.symbol}")
        print(f"时间范围: {self.date_range} ({self._total_days} 天)")
        print(f"试验次数: {n_trials}")
        print(f"{'='*60}\n")
        
        study = optuna.create_study(
            direction='maximize',
            study_name='dual_thrust_optimization',
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
        
        report = f"""# Dual Thrust 参数优化报告

## 优化概览
- 优化时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
- 交易对: {self.symbol}
- 时间范围: {self.date_range} ({self._total_days} 天)
- 试验次数: {len(self.results)}
- 最佳得分: {study.best_value:.4f}

## 最佳参数组合

### Dual Thrust 参数
| 参数 | 最优值 |
|------|--------|
| n_days | {best['n_days']} |
| k1 | {best['k1']:.4f} |
| k2 | {best['k2']:.4f} |
| k2_down_factor | {best['k2_down_factor']:.4f} |
| down_confirm_days | {best['down_confirm_days']} |
| cooldown_days | {best['cooldown_days']} |

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
python market_aware_backtest.py \\
    --symbol {self.symbol} \\
    --date-range {self.date_range} \\
    --market-algorithm dual_thrust \\
    --n-days {best['n_days']} \\
    --k1 {best['k1']:.4f} \\
    --k2 {best['k2']:.4f} \\
    --k2-down-factor {best['k2_down_factor']:.4f} \\
    --down-confirm-days {best['down_confirm_days']} \\
    --cooldown-days {best['cooldown_days']} \\
    --decay-factor {best['decay_factor']:.2f} \\
    --stop-loss {best['stop_loss']:.2f} \\
    --total-amount 5000
```

## 参数说明

### Dual Thrust 参数
- **n_days**: 回看天数，用于计算 Range
- **k1**: 上轨系数，控制上涨趋势识别敏感度
- **k2**: 下轨系数，控制下跌趋势识别敏感度
- **k2_down_factor**: 下跌敏感系数，< 1 时下跌识别更敏感
- **down_confirm_days**: 下跌确认天数，需要连续跌破才确认
- **cooldown_days**: 状态切换冷却期，避免频繁切换

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
    parser = argparse.ArgumentParser(description="Dual Thrust 参数优化器")
    parser.add_argument('--symbol', default='BTCUSDT', help='交易对')
    parser.add_argument('--date-range', required=True, help='时间范围 (格式: yyyymmdd-yyyymmdd)')
    parser.add_argument('--n-trials', type=int, default=50, help='优化试验次数')
    args = parser.parse_args()
    
    optimizer = DualThrustOptimizer(args.symbol, args.date_range)
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

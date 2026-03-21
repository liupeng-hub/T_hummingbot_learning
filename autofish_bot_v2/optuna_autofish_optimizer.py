#!/usr/bin/env python3
"""
Autofish 参数优化器

使用 Optuna 对 Autofish 策略参数进行分阶段优化。

使用方法:
    # 完整三阶段优化
    python optuna_autofish_optimizer.py --symbol BTCUSDT --date-range 20200101-20260310 --stages all --n-trials 50

    # 单阶段优化
    python optuna_autofish_optimizer.py --symbol BTCUSDT --date-range 20200101-20260310 --stages amplitude --n-trials 50
"""

import optuna
import pandas as pd
from datetime import datetime
from pathlib import Path
import asyncio
import json
import os
import sys
import argparse
import logging
import uuid
import time
from decimal import Decimal
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from binance_backtest import MarketAwareBacktestEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("optuna_autofish_optimizer")

optuna.logging.set_verbosity(optuna.logging.WARNING)


class OptunaAutofishOptimizer:
    """Autofish 参数优化器"""
    
    def __init__(self, symbol: str, date_range: str):
        self.symbol = symbol
        self.date_range = date_range
        self.optimizer_id = str(uuid.uuid4())
        
        self.output_dir = Path('out/test_report/optimizer_Autofish')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.results_file = self.output_dir / f"{self.optimizer_id}_results.csv"
        self.report_file = self.output_dir / f"{self.optimizer_id}.md"
        
        self.results: List[Dict] = []
        self.best_params: Optional[Dict] = None
        self.best_value: float = 0.0
        
        self._start_time: Optional[int] = None
        self._end_time: Optional[int] = None
        self._total_days: int = 0
        self._start_date: Optional[datetime] = None
        self._end_date: Optional[datetime] = None
        
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
    
    def _calculate_score(self, results: Dict) -> float:
        """计算综合得分
        
        score = profit_score * 0.7 + winrate_score * 0.15 + trading_score * 0.15
        """
        net_profit = float(results.get('total_profit', 0) - results.get('total_loss', 0))
        total_trades = results.get('total_trades', 0)
        win_trades = results.get('win_trades', 0)
        
        total_amount = 10000
        profit_score = min(max(net_profit / total_amount, -1.0), 3.0)
        
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        winrate_score = win_rate / 100
        
        trading_pct = results.get('market_statistics', {}).get('trading_pct', 50)
        trading_score = min(trading_pct / 100, 1.0)
        
        score = (
            profit_score * 0.7 +
            winrate_score * 0.15 +
            trading_score * 0.15
        )
        
        return max(score, 0.0)
    
    def _record_result(self, trial: optuna.Trial, params: Dict, result: Dict):
        """记录结果"""
        record = {
            'trial': trial.number,
            'timestamp': datetime.now().isoformat(),
            **params,
            **result
        }
        self.results.append(record)
    
    async def _run_backtest(
        self,
        amplitude: Dict,
        market: Dict,
        entry: Dict = None,
        timeout: Dict = None
    ) -> Dict:
        """运行回测"""
        if entry is None:
            entry = {}
        if timeout is None:
            timeout = {'a1_timeout_minutes': 0}
        
        amplitude['total_amount_quote'] = Decimal('10000')
        
        if 'grid_spacing' in amplitude:
            amplitude['grid_spacing'] = Decimal(str(amplitude['grid_spacing']))
        if 'exit_profit' in amplitude:
            amplitude['exit_profit'] = Decimal(str(amplitude['exit_profit']))
        if 'stop_loss' in amplitude:
            amplitude['stop_loss'] = Decimal(str(amplitude['stop_loss']))
        if 'decay_factor' in amplitude:
            amplitude['decay_factor'] = Decimal(str(amplitude['decay_factor']))
        
        engine = MarketAwareBacktestEngine(amplitude, market, entry, timeout)
        
        await engine.run(
            symbol=self.symbol,
            interval='1m',
            start_time=self._start_time,
            end_time=self._end_time,
        )
        
        score = self._calculate_score(engine.results)
        
        net_profit = float(engine.results.get('total_profit', 0) - engine.results.get('total_loss', 0))
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
            'trading_pct': engine.results.get('market_statistics', {}).get('trading_pct', 0.0),
        }
    
    def _optimize_amplitude(self, n_trials: int = 50, initial_market: Dict = None) -> optuna.Study:
        """优化 amplitude 参数"""
        print(f"\n{'='*60}")
        print(f"阶段 1: Amplitude 参数优化")
        print(f"{'='*60}\n")
        
        if initial_market is None:
            initial_market = {
                'algorithm': 'dual_thrust',
                'dual_thrust': {
                    'n_days': 4,
                    'k1': 0.4,
                    'k2': 0.4,
                    'k2_down_factor': 0.8,
                    'down_confirm_days': 2,
                    'cooldown_days': 1,
                },
                'trading_statuses': ['ranging'],
                'interval': '1d',
                'min_market_klines': 5,
            }
        
        def objective(trial: optuna.Trial) -> float:
            amplitude_params = {
                'grid_spacing': trial.suggest_float('grid_spacing', 0.005, 0.02),
                'exit_profit': trial.suggest_float('exit_profit', 0.005, 0.02),
                'stop_loss': trial.suggest_float('stop_loss', 0.05, 0.12),
                'decay_factor': trial.suggest_float('decay_factor', 0.3, 0.7),
                'max_entries': trial.suggest_int('max_entries', 2, 6),
                'leverage': 10,
            }
            
            try:
                result = asyncio.run(self._run_backtest(amplitude_params, initial_market))
                self._record_result(trial, amplitude_params, result)
                return result['score']
            except Exception as e:
                logger.error(f"Trial {trial.number} 失败: {e}")
                return 0.0
        
        study = optuna.create_study(
            direction='maximize',
            study_name='amplitude_optimization',
            sampler=optuna.samplers.TPESampler(seed=42),
        )
        
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
        
        self.best_params = study.best_params
        self.best_value = study.best_value
        
        print(f"\n阶段 1 完成! 最佳得分: {self.best_value:.4f}")
        
        return study
    
    def _optimize_market(
        self,
        n_trials: int = 50,
        initial_amplitude: Dict = None
    ) -> optuna.Study:
        """优化 market 参数 (Dual Thrust)"""
        print(f"\n{'='*60}")
        print(f"阶段 2: Dual Thrust 行情算法参数优化")
        print(f"{'='*60}\n")
        
        if initial_amplitude is None:
            initial_amplitude = self.best_params or {}
        
        initial_amplitude.setdefault('leverage', 10)
        
        def objective(trial: optuna.Trial) -> float:
            market_params = {
                'algorithm': 'dual_thrust',
                'dual_thrust': {
                    'n_days': trial.suggest_int('n_days', 2, 7),
                    'k1': trial.suggest_float('k1', 0.3, 0.7),
                    'k2': trial.suggest_float('k2', 0.3, 0.7),
                    'k2_down_factor': trial.suggest_float('k2_down_factor', 0.5, 1.0),
                    'down_confirm_days': trial.suggest_int('down_confirm_days', 1, 3),
                    'cooldown_days': trial.suggest_int('cooldown_days', 1, 3),
                },
                'trading_statuses': ['ranging'],
                'interval': '1d',
                'min_market_klines': trial.suggest_int('n_days', 2, 7) + 1,
            }
            
            try:
                result = asyncio.run(self._run_backtest(initial_amplitude, market_params))
                self._record_result(trial, market_params, result)
                return result['score']
            except Exception as e:
                logger.error(f"Trial {trial.number} 失败: {e}")
                return 0.0
        
        study = optuna.create_study(
            direction='maximize',
            study_name='market_optimization',
            sampler=optuna.samplers.TPESampler(seed=42),
        )
        
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
        
        self.best_params = {**initial_amplitude, **study.best_params}
        self.best_value = study.best_value
        
        print(f"\n阶段 2 完成! 最佳得分: {self.best_value:.4f}")
        
        return study
    
    def _optimize_entry(
        self,
        n_trials: int = 50,
        initial_amplitude: Dict = None,
        initial_market: Dict = None
    ) -> optuna.Study:
        """优化 entry 参数"""
        print(f"\n{'='*60}")
        print(f"阶段 3: 入场价格策略参数优化")
        print(f"{'='*60}\n")
        
        if initial_amplitude is None:
            initial_amplitude = self.best_params or {}
        
        if initial_market is None:
            initial_market = {
                'algorithm': 'dual_thrust',
                'dual_thrust': {
                    'n_days': 4,
                    'k1': 0.4,
                    'k2': 0.4,
                    'k2_down_factor': 0.8,
                    'down_confirm_days': 2,
                    'cooldown_days': 1,
                },
                'trading_statuses': ['ranging'],
                'interval': '1d',
                'min_market_klines': 5,
            }
        
        def objective(trial: optuna.Trial) -> float:
            strategy = trial.suggest_categorical('strategy', ['fixed', 'atr', 'ema'])
            
            entry_params = {'strategy': strategy}
            
            if strategy == 'atr':
                entry_params['atr'] = {
                    'atr_period': trial.suggest_int('atr_period', 10, 20),
                    'atr_multiplier': trial.suggest_float('atr_multiplier', 0.3, 1.0),
                    'min_spacing': trial.suggest_float('min_spacing', 0.005, 0.015),
                    'max_spacing': trial.suggest_float('max_spacing', 0.015, 0.03),
                }
            elif strategy == 'ema':
                entry_params['ema'] = {
                    'ema_period': trial.suggest_int('ema_period', 5, 20),
                    'deviation_threshold': trial.suggest_float('deviation_threshold', 0.005, 0.02),
                }
            
            try:
                result = asyncio.run(self._run_backtest(initial_amplitude, initial_market, entry_params))
                self._record_result(trial, entry_params, result)
                return result['score']
            except Exception as e:
                logger.error(f"Trial {trial.number} 失败: {e}")
                return 0.0
        
        study = optuna.create_study(
            direction='maximize',
            study_name='entry_optimization',
            sampler=optuna.samplers.TPESampler(seed=42),
        )
        
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
        
        self.best_params = {**initial_amplitude, **initial_market.get('dual_thrust', {}), **study.best_params}
        self.best_value = study.best_value
        
        print(f"\n阶段 3 完成! 最佳得分: {self.best_value:.4f}")
        
        return study
    
    def run(
        self,
        stages: str = 'all',
        n_trials: int = 50,
        amplitude_params: Dict = None,
        market_params: Dict = None,
        entry_params: Dict = None
    ) -> Dict:
        """运行优化"""
        start_time = time.time()
        
        print(f"\n{'='*60}")
        print(f"Autofish 参数优化")
        print(f"{'='*60}")
        print(f"优化 ID: {self.optimizer_id}")
        print(f"交易对: {self.symbol}")
        print(f"时间范围: {self.date_range} ({self._total_days} 天)")
        print(f"优化阶段: {stages}")
        print(f"试验次数: {n_trials}")
        print(f"{'='*60}\n")
        
        studies = {}
        
        if stages in ['all', 'amplitude']:
            studies['amplitude'] = self._optimize_amplitude(n_trials, market_params)
            amplitude_params = self.best_params
        
        if stages in ['all', 'market']:
            studies['market'] = self._optimize_market(n_trials, amplitude_params)
            market_dual_thrust = {
                'algorithm': 'dual_thrust',
                'dual_thrust': {
                    'n_days': studies['market'].best_params.get('n_days', 4),
                    'k1': studies['market'].best_params.get('k1', 0.4),
                    'k2': studies['market'].best_params.get('k2', 0.4),
                    'k2_down_factor': studies['market'].best_params.get('k2_down_factor', 0.8),
                    'down_confirm_days': studies['market'].best_params.get('down_confirm_days', 2),
                    'cooldown_days': studies['market'].best_params.get('cooldown_days', 1),
                },
                'trading_statuses': ['ranging'],
                'interval': '1d',
                'min_market_klines': studies['market'].best_params.get('n_days', 4) + 1,
            }
        
        if stages in ['all', 'entry']:
            studies['entry'] = self._optimize_entry(n_trials, amplitude_params, market_params or market_dual_thrust)
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        self._save_results()
        self._save_to_database(stages, n_trials, duration_ms)
        self._generate_report(studies, stages)
        
        print(f"\n{'='*60}")
        print(f"优化完成!")
        print(f"最佳得分: {self.best_value:.4f}")
        print(f"耗时: {duration_ms / 1000:.1f} 秒")
        print(f"{'='*60}\n")
        
        return {
            'optimizer_id': self.optimizer_id,
            'best_value': self.best_value,
            'best_params': self.best_params,
            'studies': studies,
        }
    
    def _save_results(self):
        """保存结果到 CSV"""
        if not self.results:
            return
        
        df = pd.DataFrame(self.results)
        df.to_csv(self.results_file, index=False)
        logger.info(f"结果已保存: {self.results_file}")
    
    def _save_to_database(self, stage: str, n_trials: int, duration_ms: int):
        """保存到数据库"""
        try:
            from database.test_results_db import TestResultsDB
            db = TestResultsDB()
            
            if self.results:
                values = [r['score'] for r in self.results if 'score' in r]
                avg_value = sum(values) / len(values) if values else 0
                std_value = (sum((v - avg_value) ** 2 for v in values) / len(values)) ** 0.5 if values else 0
            else:
                avg_value = 0
                std_value = 0
            
            db.save_optimizer_result(
                optimizer_id=self.optimizer_id,
                symbol=self.symbol,
                algorithm='dual_thrust',
                stage=stage,
                date_range=self.date_range,
                days=self._total_days,
                n_trials=n_trials,
                best_value=self.best_value,
                best_params=self.best_params or {},
                param_ranges={},
                avg_value=avg_value,
                std_value=std_value,
                duration_ms=duration_ms,
                status='completed'
            )
            
            for r in self.results:
                params_to_save = {}
                for k, v in r.items():
                    if k not in ['trial', 'timestamp', 'score', 'total_trades', 'win_rate', 'net_profit']:
                        if isinstance(v, Decimal):
                            params_to_save[k] = float(v)
                        else:
                            params_to_save[k] = v
                
                db.save_optimizer_history(
                    optimizer_id=self.optimizer_id,
                    trial=r.get('trial', 0),
                    value=r.get('score', 0),
                    params=params_to_save,
                    metrics={
                        'score': r.get('score', 0),
                        'total_trades': r.get('total_trades', 0),
                        'win_rate': r.get('win_rate', 0),
                        'net_profit': r.get('net_profit', 0),
                    }
                )
            
            print(f"✅ 优化结果已保存到数据库: {self.optimizer_id}")
        except Exception as e:
            logger.error(f"保存优化结果到数据库失败: {e}")
    
    def _generate_report(self, studies: Dict, stage: str):
        """生成优化报告"""
        report = f"""# Autofish 参数优化报告

## 优化概览
- 优化时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
- 优化 ID: {self.optimizer_id}
- 交易对: {self.symbol}
- 时间范围: {self.date_range} ({self._total_days} 天)
- 优化阶段: {stage}
- 试验次数: {len(self.results)}
- 最佳得分: {self.best_value:.4f}

## 最佳参数组合

"""
        
        if self.best_params:
            report += "| 参数 | 最优值 |\n|------|--------|\n"
            for key, value in self.best_params.items():
                if isinstance(value, float):
                    report += f"| {key} | {value:.4f} |\n"
                else:
                    report += f"| {key} | {value} |\n"
        
        report += "\n## Top 10 结果\n"
        report += "| 排名 | 得分 | 净收益 | 胜率 | 交易次数 |\n"
        report += "|------|------|--------|------|----------|\n"
        
        sorted_results = sorted(self.results, key=lambda x: x.get('score', 0), reverse=True)[:10]
        for i, r in enumerate(sorted_results, 1):
            report += f"| {i} | {r.get('score', 0):.4f} | {r.get('net_profit', 0):.2f} | {r.get('win_rate', 0):.1f}% | {r.get('total_trades', 0)} |\n"
        
        report += "\n## 参数重要性\n\n"
        
        for stage_name, study in studies.items():
            report += f"### {stage_name.upper()} 阶段\n\n"
            try:
                importance = optuna.importance.get_param_importances(study)
                report += "| 参数 | 重要性 |\n|------|--------|\n"
                for param, imp in importance.items():
                    report += f"| {param} | {imp:.4f} |\n"
                report += "\n"
            except Exception:
                report += "（参数重要性分析需要更多试验）\n\n"
        
        report += f"""
## 使用建议

```bash
python binance_backtest.py \\
    --symbol {self.symbol} \\
    --date-range {self.date_range} \\
    --amplitude-params '{json.dumps({k: v for k, v in self.best_params.items() if k in ['grid_spacing', 'exit_profit', 'stop_loss', 'decay_factor', 'max_entries']}, indent=2)}' \\
    --market-params '{{"algorithm": "dual_thrust", "dual_thrust": {json.dumps({k: v for k, v in self.best_params.items() if k in ['n_days', 'k1', 'k2', 'k2_down_factor', 'down_confirm_days', 'cooldown_days']})}}}'
```
"""
        
        with open(self.report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"📄 报告已保存: {self.report_file}")


def main():
    parser = argparse.ArgumentParser(description="Autofish 参数优化器")
    parser.add_argument('--symbol', required=True, help='交易对')
    parser.add_argument('--date-range', required=True, help='时间范围 (格式: yyyymmdd-yyyymmdd)')
    parser.add_argument('--stages', default='all', choices=['all', 'amplitude', 'market', 'entry'], help='优化阶段')
    parser.add_argument('--n-trials', type=int, default=50, help='每阶段试验次数')
    parser.add_argument('--amplitude-params', type=str, help='初始 amplitude 参数 (JSON)')
    parser.add_argument('--market-params', type=str, help='初始 market 参数 (JSON)')
    parser.add_argument('--entry-params', type=str, help='初始 entry 参数 (JSON)')
    
    args = parser.parse_args()
    
    amplitude_params = json.loads(args.amplitude_params) if args.amplitude_params else None
    market_params = json.loads(args.market_params) if args.market_params else None
    entry_params = json.loads(args.entry_params) if args.entry_params else None
    
    optimizer = OptunaAutofishOptimizer(args.symbol, args.date_range)
    result = optimizer.run(
        stages=args.stages,
        n_trials=args.n_trials,
        amplitude_params=amplitude_params,
        market_params=market_params,
        entry_params=entry_params
    )
    
    print(f"\n最佳参数:")
    for key, value in result['best_params'].items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")
    print(f"\n最佳得分: {result['best_value']:.4f}")


if __name__ == '__main__':
    main()

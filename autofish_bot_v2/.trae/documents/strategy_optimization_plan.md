# 参数优化计划（含贝叶斯优化）

## 目标

对行情判断算法和交易策略的参数进行联合优化，使用贝叶斯优化高效找到最优参数组合。

---

## 为什么使用贝叶斯优化？

| 方法 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| 网格搜索 | 全面覆盖 | 计算量大，组合爆炸 | 参数少 |
| 随机搜索 | 简单快速 | 效率低 | 快速探索 |
| **贝叶斯优化** | **高效**智能采样 | 需要额外依赖 | **参数多、计算成本高** |

**贝叶斯优化优势**：
- 根据历史结果智能选择下一组参数
- 用最少的试验次数找到最优解
- 适合回测这种计算成本高的场景

---

## Python 贝叶斯优化库对比

| 库 | 特点 | 推荐度 |
|-----|------|--------|
| **Optuna** | 现代、易用、可视化好 | ⭐⭐⭐⭐⭐ |
| Scikit-Optimize (skopt) | 简单、与 sklearn 兼容 | ⭐⭐⭐⭐ |
| Hyperopt | 成熟、功能全 | ⭐⭐⭐⭐ |
| BayesianOptimization | 轻量、纯贝叶斯 | ⭐⭐⭐ |

**推荐使用 Optuna**:
- 安装简单：`pip install optuna`
- API 友好
- 内置可视化
- 支持分布式优化

---

## 参数定义

### 1. 行情判断参数（影响交易时机）

| 参数 | 说明 | 范围 | 默认值 |
|------|------|------|----------|
| lookback_period | 回看周期（天） | 40-90 | 60 |
| min_range_duration | 最小震荡持续天数 | 5-20 | 10 |
| max_range_pct | 最大区间宽度 | 0.10-0.25 | 0.15 |
| breakout_threshold | 突破阈值 | 0.02-0.05 | 0.03 |
| swing_window | 局部高低点窗口 | 3-7 | 5 |
| merge_threshold | 价格合并阈值 | 0.02-0.05 | 0.03 |
| min_touches | 最少触及次数 | 2-5 | 3 |

### 2. Autofish 交易策略参数（影响交易收益）

| 参数 | 说明 | 范围 | 默认值 |
|------|------|------|----------|
| grid_spacing | 网格间距 | 0.005-0.02 | 0.01 |
| exit_profit | 止盈比例 | 0.005-0.02 | 0.01 |
| stop_loss | 止损比例 | 0.05-0.12 | 0.08 |
| decay_factor | 衰减因子 | 0.3-0.7 | 0.5 |
| max_entries | 最大层数 | 2-6 | 4 |

---

## 实施步骤

### 步骤 1: 安装依赖

```bash
pip install optuna optuna-dashboard
```

### 步骤 2: 创建优化脚本
**文件**: `market_strategy_optimizer.py`
```python
import optuna
import pandas as pd
from datetime import datetime
import asyncio
import json
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_aware_backtest import MarketAwareBacktestEngine
from market_status_detector import (
    ImprovedStatusAlgorithm, 
    SupportResistanceDetector, 
    BoxRangeDetector,
    MarketStatus
)

from autofish_core import Autofish_ChainState

class MarketStrategyOptimizer:
    """市场策略参数优化器"""
    
    def __init__(self, symbol: str, date_range: str):
        self.symbol = symbol
        self.date_range = date_range
        self.results_file = 'autofish_output/optimization_results.csv'
        self.report_file = 'autofish_output/optimization_report.md'
        self.results = []
        self.best_params = None
        self.best_value = 0
        
        # 确保输出目录存在
        os.makedirs('autofish_output', exist_ok=True)
        
    def objective(self, trial):
        """优化目标函数"""
        # 1. 采样行情判断参数
        market_params = {
            'lookback_period': trial.suggest_int('lookback_period', 40, 90),
            'min_range_duration': trial.suggest_int('min_range_duration', 5, 20),
            'max_range_pct': trial.suggest_float('max_range_pct', 0.10, 0.25),
            'breakout_threshold': trial.suggest_float('breakout_threshold', 0.02, 0.05),
            'swing_window': trial.suggest_int('swing_window', 3, 7),
            'merge_threshold': trial.suggest_float('merge_threshold', 0.02, 0.05),
            'min_touches': trial.suggest_int('min_touches', 2, 5),
        }
        
        # 2. 采样交易策略参数
        strategy_params = {
            'grid_spacing': trial.suggest_float('grid_spacing', 0.005, 0.02),
            'exit_profit': trial.suggest_float('exit_profit', 0.005, 0.02),
            'stop_loss': trial.suggest_float('stop_loss', 0.05, 0.12),
            'decay_factor': trial.suggest_float('decay_factor', 0.3, 0.7),
            'max_entries': trial.suggest_int('max_entries', 2, 6),
        }
        
        # 3. 运行回测
        result = asyncio.run(self._run_backtest(market_params, strategy_params))
        
        # 4. 记录结果
        self._record_result(trial, market_params, strategy_params, result)
        
        # 5. 返回优化目标
        return result['score']
    
    async def _run_backtest(self, market_params, strategy_params):
        """运行回测并返回结果"""
        # 创建算法实例
        sr_detector = SupportResistanceDetector({
            'lookback_period': market_params['lookback_period'],
            'swing_window': market_params['swing_window'],
            'merge_threshold': market_params['merge_threshold'],
            'min_touches': market_params['min_touches'],
        })
        
        box_detector = BoxRangeDetector({
            'min_duration': market_params['min_range_duration'],
            'max_range_pct': market_params['max_range_pct'],
        })
        
        algorithm = ImprovedStatusAlgorithm({
            'lookback_period': market_params['lookback_period'],
            'min_range_duration': market_params['min_range_duration'],
            'max_range_pct': market_params['max_range_pct'],
            'breakout_threshold': market_params['breakout_threshold'],
        })
        algorithm.sr_detector = sr_detector
        algorithm.box_detector = box_detector
        
        # 配置回测参数
        config = {
            'symbol': self.symbol,
            'leverage': 10,
            'grid_spacing': strategy_params['grid_spacing'],
            'exit_profit': strategy_params['exit_profit'],
            'stop_loss': strategy_params['stop_loss'],
            'total_amount_quote': 5000,
            'max_entries': strategy_params['max_entries'],
            'decay_factor': strategy_params['decay_factor'],
        }
        
        market_config = {
            'algorithm': 'improved',
            'lookback_period': market_params['lookback_period'],
            'min_range_duration': market_params['min_range_duration'],
            'max_range_pct': market_params['max_range_pct'],
            'breakout_threshold': market_params['breakout_threshold'],
        }
        
        # 运行回测
        engine = MarketAwareBacktestEngine(config, market_config)
        engine.market_detector.algorithm = algorithm
        
        # 解析日期范围
        start_str, end_str = self.date_range.split('-')
        start_date = datetime.strptime(start_str, '%Y%m%d')
        end_date = datetime.strptime(end_str, '%Y%m%d')
        
        await engine.run(
            symbol=self.symbol,
            interval='1m',
            start_time=int(start_date.timestamp() * 1000),
            end_time=int(end_date.timestamp() * 1000),
        )
        
        # 计算综合得分
        score = self._calculate_score(engine.results)
        
        return {
            'score': score,
            'total_trades': engine.results['total_trades'],
            'win_rate': engine.results['win_rate'],
            'net_profit': float(engine.results['net_profit']),
            'max_drawdown': engine.results.get('max_drawdown', 0),
            'profit_factor': engine.results.get('profit_factor', 1.0),
            'market_changes': engine.results.get('market_status_changes', 0),
        }
    
    def _calculate_score(self, results):
        """计算综合得分"""
        # 归一化各指标
        profit_score = min(results['net_profit'] / 10000, 1.0)  # 最大10000
        winrate_score = results['win_rate'] / 100
        drawdown_score = 1 - results.get('max_drawdown', 0) / 0.3  # 最大30%
        
        # 加权得分
        score = (
            profit_score * 0.4 +
            winrate_score * 0.3 +
            drawdown_score * 0.3
        )
        return score
    
    def _record_result(self, trial, market_params, strategy_params, result):
        """记录结果"""
        record = {
            'trial': trial.number,
            'timestamp': datetime.now().isoformat(),
            **market_params,
            **strategy_params,
            **result
        }
        self.results.append(record)
        
        # 实时保存
        self._save_results()
    
    def run(self, n_trials=50):
        """运行优化"""
        print(f"\n{'='*60}")
        print(f"开始参数优化: {self.symbol} {self.date_range}")
        print(f"试验次数: {n_trials}")
        print(f"{'='*60}\n")
        
        study = optuna.create_study(
            direction='maximize',
            study_name='market_strategy_optimization'
        )
        
        study.optimize(self.objective, n_trials=n_trials)
        
        self.best_params = study.best_params
        self.best_value = study.best_value
        
        print(f"\n{'='*60}")
        print(f"优化完成!")
        print(f"最佳得分: {self.best_value:.4f}")
        print(f"{'='*60}\n")
        
        # 保存结果
        self._save_results()
        self._generate_report(study)
        
        return study
    
    def _save_results(self):
        """保存结果到CSV"""
        df = pd.DataFrame(self.results)
        df.to_csv(self.results_file, index=False)
        print(f"结果已保存: {self.results_file}")
    
    def _generate_report(self, study):
        """生成优化报告"""
        report = f"""# 参数优化报告

## 优化概览
- 优化时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
- 交易对: {self.symbol}
- 时间范围: {self.date_range}
- 试验次数: {len(self.results)}
- 最佳得分: {study.best_value:.4f}

## 最佳参数组合

### 行情判断参数
| 参数 | 最优值 |
|------|--------|
| lookback_period | {study.best_params['lookback_period']} |
| min_range_duration | {study.best_params['min_range_duration']} |
| max_range_pct | {study.best_params['max_range_pct']:.3f} |
| breakout_threshold | {study.best_params['breakout_threshold']:.3f} |
| swing_window | {study.best_params['swing_window']} |
| merge_threshold | {study.best_params['merge_threshold']:.3f} |
| min_touches | {study.best_params['min_touches']} |

### 交易策略参数
| 参数 | 最优值 |
|------|--------|
| grid_spacing | {study.best_params['grid_spacing']:.4f} |
| exit_profit | {study.best_params['exit_profit']:.4f} |
| stop_loss | {study.best_params['stop_loss']:.2%} |
| decay_factor | {study.best_params['decay_factor']:.2f} |
| max_entries | {study.best_params['max_entries']} |

## Top 10 结果
| 排名 | 得分 | 净收益 | 胜率 | 最大回撤 |
|------|------|--------|------|----------|
"""
        
        # 添加 Top 10 结果
        sorted_results = sorted(self.results, key=lambda x: x['score'], reverse=True)[:10]
        for i, r in enumerate(sorted_results, 1):
            report += f"| {i+1} | {r['score']:.4f} | {r['net_profit']:.2f} | {r['win_rate']:.1f}% | {r.get('max_drawdown', 0):.1f}% |\n"
        
        report += "\n## 参数重要性\n\n"
        try:
            importance = optuna.importance.get_param_importances(study)
            report += "| 参数 | 重要性 |\n"
            report += "|------|--------|\n"
            for param, imp in importance.items():
                report += f"| {param} | {imp:.4f} |\n"
        except:
            report += "（参数重要性分析需要更多试验）\n"
        
        # 保存报告
        with open(self.report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"报告已保存: {self.report_file}"


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', default='BTCUSDT')
    parser.add_argument('--date-range', required=True)
    parser.add_argument('--n-trials', type=int, default=50)
    args = parser.parse_args()
    
    optimizer = MarketStrategyOptimizer(args.symbol, args.date_range)
    study = optimizer.run(n_trials=args.n_trials)
    
    print(f"\n最佳参数: {study.best_params}")
    print(f"最佳得分: {study.best_value:.4f}")


if __name__ == '__main__':
    main()
```
### 步骤 3: 更新检测器支持参数传入
修改 `SupportResistanceDetector` 和 `BoxRangeDetector`，接受配置参数

### 步骤 4: 更新回测引擎支持参数传入
修改 `MarketAwareBacktestEngine`，接受外部创建的算法实例

---

## 结果记录机制
### CSV 记录格式
**文件**: `autofish_output/optimization_results.csv`

| 字段 | 类型 | 说明 |
|------|------|------|
| trial | int | 试验编号 |
| timestamp | str | 时间戳 |
| lookback_period | int | 回看周期 |
| min_range_duration | int | 最小震荡持续 |
| max_range_pct | float | 最大区间宽度 |
| breakout_threshold | float | 突破阈值 |
| swing_window | int | 局部高低点窗口 |
| merge_threshold | float | 价格合并阈值 |
| min_touches | int | 最少触及次数 |
| grid_spacing | float | 网格间距 |
| exit_profit | float | 止盈比例 |
| stop_loss | float | 止损比例 |
| decay_factor | float | 衰减因子 |
| max_entries | int | 最大层数 |
| score | float | 综合得分 |
| total_trades | int | 总交易次数 |
| win_rate | float | 胜率 |
| net_profit | float | 净收益 |
| max_drawdown | float | 最大回撤 |
| profit_factor | float | 盈利因子 |
| market_changes | int | 行情状态变化次数 |

---

## 评估指标
### 综合得分公式
```python
score = (
    profit_score * 0.4 +      # 净收益归一化
    winrate_score * 0.3 +     # 胜率
    drawdown_score * 0.3      # 风险控制
)
```
### 参数重要性分析
Optuna 自动计算参数重要性，帮助识别哪些参数对结果影响最大

---

## 文件修改清单
| 文件 | 操作 | 说明 |
|------|------|------|
| `market_strategy_optimizer.py` | 新增 | 贝叶斯优化脚本 |
| `market_status_detector.py` | 修改 | 支持参数传入 |
| `market_aware_backtest.py` | 修改 | 支持外部算法实例 |
| `autofish_output/optimization_results.csv` | 新增 | 结果记录 |
| `autofish_output/optimization_report.md` | 新增 | 优化报告 |

---

## 使用示例
```bash
# 安装依赖
pip install optuna

# 运行优化(50次试验)
python market_strategy_optimizer.py --symbol BTCUSDT --date-range 20220616-20230107 --n-trials 50

# 查看报告
cat autofish_output/optimization_report.md

# 查看结果CSV
head -20 autofish_output/optimization_results.csv
```
---

## 预期效果
1. **高效找到最优参数** - 50次试验即可找到较好的参数组合
2. **参数重要性分析** - 了解哪些参数对结果影响最大
3. **可复现的结果记录** - CSV 格式便于后续分析
4. **自动化报告生成** - Markdown 格式的优化报告

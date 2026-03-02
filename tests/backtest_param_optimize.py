"""
Autofish V1 策略参数优化回测

测试不同参数组合的效果

运行方式：
    cd /Users/liupeng/Documents/trae_projects/hummingbot_learning
    python3 tests/backtest_param_optimize.py
"""

import unittest
from decimal import Decimal
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import random
import pandas as pd
import os


@dataclass
class ChainLevel:
    """链式入场层级"""
    level: int
    target_price: Decimal
    stake_amount: Decimal
    state: str = "pending"
    filled_price: Optional[Decimal] = None


@dataclass
class ChainState:
    """链式挂单状态"""
    base_price: Decimal
    levels: List[ChainLevel]
    current_level: int = 0
    exit_price: Optional[Decimal] = None
    is_active: bool = True

    def get_next_pending_level(self) -> Optional[ChainLevel]:
        for level in self.levels:
            if level.state == "pending":
                return level
        return None

    def get_filled_levels(self) -> List[ChainLevel]:
        return [l for l in self.levels if l.state == "filled"]

    def get_total_stake(self) -> Decimal:
        return sum(l.stake_amount for l in self.get_filled_levels())

    def get_average_entry_price(self) -> Optional[Decimal]:
        filled = self.get_filled_levels()
        if not filled:
            return None
        total_value = sum(l.stake_amount * l.filled_price for l in filled if l.filled_price)
        total_stake = sum(l.stake_amount for l in filled if l.filled_price)
        return total_value / total_stake if total_stake > 0 else None


class WeightCalculator:
    """权重计算器"""

    def __init__(self, decay_factor: Decimal = Decimal("0.5")):
        self.decay_factor = decay_factor
        self.amplitude_probabilities = {
            1: Decimal("0.36"),
            2: Decimal("0.24"),
            3: Decimal("0.16"),
            4: Decimal("0.09"),
        }

    def calculate_weights(self) -> List[Decimal]:
        beta = Decimal("1") / self.decay_factor
        raw_weights = []
        for amp, prob in self.amplitude_probabilities.items():
            raw_weight = Decimal(str(amp)) * (prob ** beta)
            raw_weights.append(raw_weight)
        total = sum(raw_weights)
        return [w / total for w in raw_weights]

    def calculate_stake_amounts(self, total_amount: Decimal) -> List[Decimal]:
        weights = self.calculate_weights()
        return [total_amount * w for w in weights]


class BacktestEngine:
    """回测引擎"""

    def __init__(self, config: dict):
        self.config = config
        self.calculator = WeightCalculator(config.get("decay_factor", Decimal("0.5")))
        self.trades = []
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
        }

    def run_backtest(self, price_data: List[dict]) -> dict:
        """运行回测"""
        chain_state = None
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.09"))
        total_amount = self.config.get("total_amount_quote", Decimal("10000"))
        leverage = self.config.get("leverage", Decimal("10"))

        for i, candle in enumerate(price_data):
            current_price = Decimal(str(candle["close"]))
            low_price = Decimal(str(candle["low"]))
            high_price = Decimal(str(candle["high"]))

            if chain_state is None or not chain_state.is_active:
                chain_state = self._initialize_chain_state(current_price, total_amount, grid_spacing)

            if chain_state and chain_state.is_active:
                self._process_entry_orders(chain_state, low_price)
                self._process_exit(chain_state, high_price, low_price, exit_profit, stop_loss, leverage)

        return self.results

    def _initialize_chain_state(self, base_price: Decimal, total_amount: Decimal, grid_spacing: Decimal) -> ChainState:
        """
        初始化链式状态
        
        入场价格计算（链式）:
        - A1 = P0 × (1 - spacing) = P0 × 99%
        - A2 = A1 × (1 - spacing) = P0 × 98.01%
        - A3 = A2 × (1 - spacing) = P0 × 97.03%
        - A4 = A3 × (1 - spacing) = P0 × 96.06%
        """
        stake_amounts = self.calculator.calculate_stake_amounts(total_amount)
        levels = []
        
        current_price = base_price
        for i in range(4):
            target_price = current_price * (Decimal("1") - grid_spacing)
            levels.append(ChainLevel(
                level=i + 1,
                target_price=target_price,
                stake_amount=stake_amounts[i],
            ))
            current_price = target_price  # 链式计算：下一个基于当前

        return ChainState(base_price=base_price, levels=levels)

    def _process_entry_orders(self, chain_state: ChainState, low_price: Decimal):
        """处理入场订单"""
        next_level = chain_state.get_next_pending_level()
        if next_level and low_price <= next_level.target_price:
            next_level.state = "filled"
            next_level.filled_price = next_level.target_price

    def _process_exit(self, chain_state: ChainState, high_price: Decimal, low_price: Decimal,
                      exit_profit: Decimal, stop_loss: Decimal, leverage: Decimal):
        """处理出场"""
        filled = chain_state.get_filled_levels()
        if not filled:
            return

        avg_price = chain_state.get_average_entry_price()
        if not avg_price:
            return

        exit_price = avg_price * (Decimal("1") + exit_profit)
        stop_price = avg_price * (Decimal("1") - stop_loss)

        if high_price >= exit_price:
            profit = self._calculate_profit(chain_state, exit_price, leverage)
            self.results["total_trades"] += 1
            self.results["win_trades"] += 1
            self.results["total_profit"] += profit
            chain_state.is_active = False

        elif low_price <= stop_price:
            loss = self._calculate_loss(chain_state, stop_price, leverage)
            self.results["total_trades"] += 1
            self.results["loss_trades"] += 1
            self.results["total_loss"] += loss
            chain_state.is_active = False

    def _calculate_profit(self, chain_state: ChainState, exit_price: Decimal, leverage: Decimal) -> Decimal:
        """计算盈利"""
        total_stake = chain_state.get_total_stake()
        avg_price = chain_state.get_average_entry_price()
        if avg_price and total_stake:
            return total_stake * (exit_price - avg_price) / avg_price * leverage
        return Decimal("0")

    def _calculate_loss(self, chain_state: ChainState, stop_price: Decimal, leverage: Decimal) -> Decimal:
        """计算亏损"""
        total_stake = chain_state.get_total_stake()
        avg_price = chain_state.get_average_entry_price()
        if avg_price and total_stake:
            return total_stake * (avg_price - stop_price) / avg_price * leverage
        return Decimal("0")


def load_price_data() -> List[dict]:
    """加载价格数据"""
    data_path = "/Users/liupeng/Documents/trae_projects/freqtrade_learning/user_data/data/binance/futures/BTC_USDT_USDT-1h-futures.feather"
    
    if not os.path.exists(data_path):
        return []
    
    df = pd.read_feather(data_path)
    df = df.tail(720)
    
    price_data = []
    for _, row in df.iterrows():
        price_data.append({
            "time": row['date'],
            "open": float(row['open']),
            "high": float(row['high']),
            "low": float(row['low']),
            "close": float(row['close']),
        })
    
    return price_data


class TestParamOptimize(unittest.TestCase):
    """参数优化测试"""

    def test_param_optimization(self):
        """测试不同参数组合"""
        print("\n" + "=" * 80)
        print("Autofish V1 参数优化回测")
        print("=" * 80)

        price_data = load_price_data()
        if not price_data:
            self.skipTest("数据文件不存在")

        print(f"\n数据信息:")
        print(f"  数据量: {len(price_data)} 条")

        param_combinations = [
            {"name": "方案1: 10x杠杆, 3%止损", "leverage": Decimal("10"), "stop_loss": Decimal("0.03"), "exit_profit": Decimal("0.01")},
            {"name": "方案2: 10x杠杆, 4%止损", "leverage": Decimal("10"), "stop_loss": Decimal("0.04"), "exit_profit": Decimal("0.01")},
            {"name": "方案3: 5x杠杆, 5%止损", "leverage": Decimal("5"), "stop_loss": Decimal("0.05"), "exit_profit": Decimal("0.01")},
            {"name": "方案4: 5x杠杆, 6%止损", "leverage": Decimal("5"), "stop_loss": Decimal("0.06"), "exit_profit": Decimal("0.01")},
            {"name": "方案5: 3x杠杆, 8%止损", "leverage": Decimal("3"), "stop_loss": Decimal("0.08"), "exit_profit": Decimal("0.01")},
            {"name": "方案6: 2x杠杆, 10%止损", "leverage": Decimal("2"), "stop_loss": Decimal("0.10"), "exit_profit": Decimal("0.01")},
        ]

        print("\n" + "-" * 80)
        print(f"{'方案':<25} {'杠杆':<8} {'止损':<8} {'交易次数':<10} {'胜率':<10} {'净收益':<15} {'收益率':<10}")
        print("-" * 80)

        best_roi = Decimal("-999")
        best_config = None

        for params in param_combinations:
            config = {
                "grid_spacing": Decimal("0.01"),
                "exit_profit": params["exit_profit"],
                "stop_loss": params["stop_loss"],
                "decay_factor": Decimal("0.5"),
                "total_amount_quote": Decimal("10000"),
                "leverage": params["leverage"],
            }

            engine = BacktestEngine(config)
            results = engine.run_backtest(price_data)

            if results['total_trades'] > 0:
                win_rate = results['win_trades'] / results['total_trades'] * 100
                net_profit = float(results['total_profit'] - results['total_loss'])
                roi = net_profit / 10000 * 100
            else:
                win_rate = 0
                net_profit = 0
                roi = 0

            print(f"{params['name']:<25} {params['leverage']}x{'':<5} {float(params['stop_loss'])*100:.0f}%{'':<5} {results['total_trades']:<10} {win_rate:.1f}%{'':<5} {net_profit:<15.2f} {roi:.2f}%")

            if Decimal(str(roi)) > best_roi:
                best_roi = Decimal(str(roi))
                best_config = params

        print("-" * 80)
        print(f"\n最佳方案: {best_config['name']}")
        print(f"  杠杆: {best_config['leverage']}x")
        print(f"  止损: {float(best_config['stop_loss'])*100:.0f}%")
        print(f"  收益率: {best_roi:.2f}%")

        print("\n分析:")
        print("  - 震荡区间1-4%，止损应 > 4% 避免正常波动触发")
        print("  - 高杠杆需要小止损，低杠杆可以用大止损")
        print("  - 需要平衡杠杆和止损的关系")

        self.assertGreaterEqual(len(param_combinations), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)

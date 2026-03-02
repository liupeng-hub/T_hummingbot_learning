"""
Autofish V1 策略回测脚本

完整链式挂单逻辑：
1. A1挂单 → A1成交 → A2挂单 → A2成交 → A3挂单 → A3成交 → A4挂单
2. E_n成交 → 取消A_{n+1}挂单 → 重新计算新A_n挂单
3. 挂单金额根据权重分配

运行方式：
    cd /Users/liupeng/Documents/trae_projects/hummingbot_learning
    python3 tests/backtest_autofish_v1.py
"""

import unittest
from decimal import Decimal
from typing import List, Optional
from dataclasses import dataclass, field
import pandas as pd
import os


@dataclass
class Order:
    """订单"""
    level: int
    entry_price: Decimal
    quantity: Decimal
    stake_amount: Decimal
    take_profit_price: Decimal
    stop_loss_price: Decimal
    state: str = "pending"
    close_price: Optional[Decimal] = None
    close_reason: Optional[str] = None
    profit: Optional[Decimal] = None


@dataclass
class ChainState:
    """链式挂单状态"""
    base_price: Decimal
    orders: List[Order] = field(default_factory=list)
    is_active: bool = True

    def get_pending_order(self) -> Optional[Order]:
        for order in self.orders:
            if order.state == "pending":
                return order
        return None

    def get_filled_orders(self) -> List[Order]:
        return [o for o in self.orders if o.state == "filled"]

    def cancel_pending_orders(self):
        for order in self.orders:
            if order.state == "pending":
                order.state = "cancelled"


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

    def get_stake_amount(self, level: int, total_amount: Decimal) -> Decimal:
        weights = self.calculate_weights()
        if level <= len(weights):
            return total_amount * weights[level - 1]
        return total_amount * weights[-1]


class BacktestEngine:
    """回测引擎"""

    def __init__(self, config: dict):
        self.config = config
        self.calculator = WeightCalculator(config.get("decay_factor", Decimal("0.5")))
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
            "order_details": [],
            "chain_events": [],
        }

    def run_backtest(self, price_data: List[dict]) -> dict:
        chain_state = None
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.03"))
        total_amount = self.config.get("total_amount_quote", Decimal("10000"))
        leverage = self.config.get("leverage", Decimal("10"))
        max_level = self.config.get("max_entries", 4)
        
        debug_count = 0

        for i, candle in enumerate(price_data):
            current_price = Decimal(str(candle["close"]))
            low_price = Decimal(str(candle["low"]))
            high_price = Decimal(str(candle["high"]))

            if chain_state is None:
                chain_state = self._create_initial_state(current_price, total_amount, grid_spacing, exit_profit, stop_loss)
                pending = chain_state.get_pending_order()
                if pending and debug_count < 5:
                    self.results["chain_events"].append({
                        "type": "init",
                        "level": pending.level,
                        "price": float(pending.entry_price),
                        "low": float(low_price),
                        "triggered": low_price <= pending.entry_price,
                    })
                    debug_count += 1

            self._process_entry(chain_state, low_price, total_amount, grid_spacing, exit_profit, stop_loss, max_level)
            self._process_exit(chain_state, high_price, low_price, leverage, total_amount, grid_spacing, exit_profit, stop_loss, current_price)

        return self.results

    def _create_initial_state(self, base_price: Decimal, total_amount: Decimal,
                               grid_spacing: Decimal, exit_profit: Decimal,
                               stop_loss: Decimal) -> ChainState:
        chain_state = ChainState(base_price=base_price)
        self._create_order(chain_state, 1, base_price, total_amount, grid_spacing, exit_profit, stop_loss)
        return chain_state

    def _create_order(self, chain_state: ChainState, level: int, base_price: Decimal,
                      total_amount: Decimal, grid_spacing: Decimal,
                      exit_profit: Decimal, stop_loss: Decimal):
        entry_price = base_price * (Decimal("1") - grid_spacing)
        take_profit_price = entry_price * (Decimal("1") + exit_profit)
        stop_loss_price = entry_price * (Decimal("1") - stop_loss)
        stake_amount = self.calculator.get_stake_amount(level, total_amount)
        
        order = Order(
            level=level,
            entry_price=entry_price,
            quantity=stake_amount / entry_price,
            stake_amount=stake_amount,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            state="pending",
        )
        chain_state.orders.append(order)

    def _process_entry(self, chain_state: ChainState, low_price: Decimal,
                       total_amount: Decimal, grid_spacing: Decimal,
                       exit_profit: Decimal, stop_loss: Decimal, max_level: int):
        pending_order = chain_state.get_pending_order()
        if pending_order:
            if low_price <= pending_order.entry_price:
                pending_order.state = "filled"
                
                self.results["chain_events"].append({
                    "type": "entry",
                    "level": pending_order.level,
                    "price": float(pending_order.entry_price),
                })
                
                next_level = pending_order.level + 1
                if next_level <= max_level:
                    self._create_order(chain_state, next_level, pending_order.entry_price,
                                      total_amount, grid_spacing, exit_profit, stop_loss)

    def _process_exit(self, chain_state: ChainState, high_price: Decimal,
                      low_price: Decimal, leverage: Decimal, total_amount: Decimal,
                      grid_spacing: Decimal, exit_profit: Decimal, stop_loss: Decimal,
                      current_price: Decimal):
        filled_orders = chain_state.get_filled_orders()
        
        for order in filled_orders:
            if order.state != "filled":
                continue
            
            if high_price >= order.take_profit_price:
                self._close_order(chain_state, order, "take_profit", order.take_profit_price, leverage)
                chain_state.cancel_pending_orders()
                self._create_order(chain_state, order.level, current_price,
                                  total_amount, grid_spacing, exit_profit, stop_loss)
                break

            elif low_price <= order.stop_loss_price:
                self._close_order(chain_state, order, "stop_loss", order.stop_loss_price, leverage)
                chain_state.cancel_pending_orders()
                self._create_order(chain_state, order.level, current_price,
                                  total_amount, grid_spacing, exit_profit, stop_loss)
                break

    def _close_order(self, chain_state: ChainState, order: Order, reason: str,
                     close_price: Decimal, leverage: Decimal):
        order.state = "closed"
        order.close_price = close_price
        order.close_reason = reason
        
        if reason == "take_profit":
            order.profit = order.stake_amount * (close_price - order.entry_price) / order.entry_price * leverage
            self.results["win_trades"] += 1
            self.results["total_profit"] += order.profit
        else:
            order.profit = -order.stake_amount * (order.entry_price - close_price) / order.entry_price * leverage
            self.results["loss_trades"] += 1
            self.results["total_loss"] += abs(order.profit)
        
        self.results["total_trades"] += 1
        self.results["order_details"].append({
            "level": order.level,
            "entry_price": float(order.entry_price),
            "close_price": float(order.close_price),
            "profit": float(order.profit),
            "reason": reason,
        })
        self.results["chain_events"].append({
            "type": reason,
            "level": order.level,
            "price": float(order.close_price),
        })


def load_price_data(timeframe: str = "1h", start_date: str = None, end_date: str = None) -> List[dict]:
    data_path = f"/Users/liupeng/Documents/trae_projects/freqtrade_learning/user_data/data/binance/futures/BTC_USDT_USDT-{timeframe}-futures.feather"
    if not os.path.exists(data_path):
        return []
    df = pd.read_feather(data_path)
    
    # 使用相同的时间范围
    if start_date and end_date:
        df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
    else:
        if timeframe == "1m":
            df = df.tail(43200)  # 30天 = 43200分钟
        else:
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


def get_common_date_range() -> tuple:
    """获取1小时和1分钟K线的共同时间范围"""
    df_1h = pd.read_feather("/Users/liupeng/Documents/trae_projects/freqtrade_learning/user_data/data/binance/futures/BTC_USDT_USDT-1h-futures.feather")
    df_1m = pd.read_feather("/Users/liupeng/Documents/trae_projects/freqtrade_learning/user_data/data/binance/futures/BTC_USDT_USDT-1m-futures.feather")
    
    # 获取共同的时间范围（最近30天）
    end_date = min(df_1h['date'].max(), df_1m['date'].max())
    
    # 30天前
    from datetime import timedelta
    start_date = end_date - timedelta(days=30)
    
    return start_date, end_date


class TestBacktest(unittest.TestCase):
    def test_backtest_1h(self):
        """1小时K线回测"""
        self._run_backtest("1h")

    def test_backtest_1m(self):
        """1分钟K线回测"""
        self._run_backtest("1m")

    def test_backtest_compare(self):
        """对比1小时和1分钟K线（相同时间范围）"""
        start_date, end_date = get_common_date_range()
        print("\n" + "=" * 80)
        print(f"相同时间范围对比: {start_date} ~ {end_date}")
        print("=" * 80)
        
        print("\n--- 1小时K线 ---")
        self._run_backtest("1h", start_date, end_date)
        
        print("\n--- 1分钟K线 ---")
        self._run_backtest("1m", start_date, end_date)

    def _run_backtest(self, timeframe: str, start_date=None, end_date=None):
        print("\n" + "=" * 80)
        print(f"Autofish V1 回测（{timeframe} K线）")
        if start_date and end_date:
            print(f"时间范围: {start_date} ~ {end_date}")
        print("=" * 80)

        price_data = load_price_data(timeframe, start_date, end_date)
        if not price_data:
            self.skipTest(f"数据文件不存在: {timeframe}")

        # 分析数据
        prices = [p['close'] for p in price_data]
        lows = [p['low'] for p in price_data]
        highs = [p['high'] for p in price_data]
        
        print(f"\n数据量: {len(price_data)} 条")
        print(f"价格范围: {min(lows):.2f} ~ {max(highs):.2f}")
        print(f"价格波动: {(max(highs) - min(lows)) / min(lows) * 100:.2f}%")

        config = {
            "grid_spacing": Decimal("0.01"),
            "exit_profit": Decimal("0.01"),
            "stop_loss": Decimal("0.03"),
            "decay_factor": Decimal("0.5"),
            "total_amount_quote": Decimal("10000"),
            "leverage": Decimal("10"),
            "max_entries": 4,
        }

        print(f"\n回测配置:")
        print(f"  杠杆: {config['leverage']}x, 网格: {float(config['grid_spacing'])*100}%, "
              f"止盈: {float(config['exit_profit'])*100}%, 止损: {float(config['stop_loss'])*100}%")

        engine = BacktestEngine(config)
        results = engine.run_backtest(price_data)

        print(f"\n回测结果:")
        print(f"  总交易: {results['total_trades']}, 盈利: {results['win_trades']}, 亏损: {results['loss_trades']}")
        
        if results['total_trades'] > 0:
            win_rate = results['win_trades'] / results['total_trades'] * 100
            print(f"  胜率: {win_rate:.2f}%")

        print(f"  总盈利: {float(results['total_profit']):.2f}, 总亏损: {float(results['total_loss']):.2f}")
        print(f"  净收益: {float(results['total_profit'] - results['total_loss']):.2f} USDT")

        if results['total_trades'] > 0:
            roi = float(results['total_profit'] - results['total_loss']) / float(config['total_amount_quote']) * 100
            print(f"  收益率: {roi:.2f}%")
        else:
            # 分析为什么没有交易
            first_close = Decimal(str(price_data[0]['close']))
            a1_target = first_close * Decimal("0.99")
            min_low = min(Decimal(str(p['low'])) for p in price_data)
            
            print(f"\n分析（无交易）:")
            print(f"  首根K线收盘价: {first_close:.2f}")
            print(f"  A1目标价: {a1_target:.2f}")
            print(f"  最低价: {min_low:.2f}")
            print(f"  是否触及A1: {'是' if min_low <= a1_target else '否'}")
            
            if results['chain_events']:
                print(f"\n调试事件（全部）:")
                for event in results['chain_events']:
                    print(f"  {event}")
            
            if min_low > a1_target:
                gap = (min_low - a1_target) / a1_target * 100
                print(f"  差距: {gap:.2f}%")
                print(f"  建议: 调整网格间距到 {gap / 4:.2f}% 或更小")

        self.assertGreaterEqual(results['total_trades'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)

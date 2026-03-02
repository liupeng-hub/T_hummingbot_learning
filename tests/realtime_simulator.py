"""
Autofish V1 实时模拟测试

使用 Binance WebSocket 获取实时1分钟K线数据

运行方式：
    cd /Users/liupeng/Documents/trae_projects/hummingbot_learning
    python3 tests/realtime_simulator.py
"""

import asyncio
import json
from decimal import Decimal
from typing import List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import aiohttp


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


class RealtimeSimulator:
    """实时模拟器"""

    def __init__(self, config: dict):
        self.config = config
        self.calculator = WeightCalculator(config.get("decay_factor", Decimal("0.5")))
        self.chain_state = None
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
        }
        self.current_candle = None
        self.last_trade_time = None

    def _create_initial_state(self, base_price: Decimal):
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.03"))
        total_amount = self.config.get("total_amount_quote", Decimal("10000"))
        
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
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 创建 A{level} 挂单: 入场价={entry_price:.2f}, 止盈={take_profit_price:.2f}, 止损={stop_loss_price:.2f}")

    def _process_entry(self, low_price: Decimal):
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.03"))
        total_amount = self.config.get("total_amount_quote", Decimal("10000"))
        max_level = self.config.get("max_entries", 4)
        
        pending_order = self.chain_state.get_pending_order()
        if pending_order:
            if low_price <= pending_order.entry_price:
                pending_order.state = "filled"
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ A{pending_order.level} 成交: 入场价={pending_order.entry_price:.2f}")
                
                next_level = pending_order.level + 1
                if next_level <= max_level:
                    self._create_order(self.chain_state, next_level, pending_order.entry_price,
                                      total_amount, grid_spacing, exit_profit, stop_loss)

    def _process_exit(self, high_price: Decimal, low_price: Decimal, current_price: Decimal):
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.03"))
        total_amount = self.config.get("total_amount_quote", Decimal("10000"))
        leverage = self.config.get("leverage", Decimal("10"))
        
        filled_orders = self.chain_state.get_filled_orders()
        
        for order in filled_orders:
            if order.state != "filled":
                continue
            
            if high_price >= order.take_profit_price:
                self._close_order(order, "take_profit", order.take_profit_price, leverage)
                self.chain_state.cancel_pending_orders()
                self._create_order(self.chain_state, order.level, current_price,
                                  total_amount, grid_spacing, exit_profit, stop_loss)
                break

            elif low_price <= order.stop_loss_price:
                self._close_order(order, "stop_loss", order.stop_loss_price, leverage)
                self.chain_state.cancel_pending_orders()
                self._create_order(self.chain_state, order.level, current_price,
                                  total_amount, grid_spacing, exit_profit, stop_loss)
                break

    def _close_order(self, order: Order, reason: str, close_price: Decimal, leverage: Decimal):
        order.state = "closed"
        order.close_price = close_price
        order.close_reason = reason
        
        if reason == "take_profit":
            order.profit = order.stake_amount * (close_price - order.entry_price) / order.entry_price * leverage
            self.results["win_trades"] += 1
            self.results["total_profit"] += order.profit
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 A{order.level} 止盈: 出场价={close_price:.2f}, 盈利={order.profit:.2f} USDT")
        else:
            order.profit = -order.stake_amount * (order.entry_price - close_price) / order.entry_price * leverage
            self.results["loss_trades"] += 1
            self.results["total_loss"] += abs(order.profit)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ A{order.level} 止损: 出场价={close_price:.2f}, 亏损={order.profit:.2f} USDT")
        
        self.results["total_trades"] += 1
        self._print_summary()

    def _print_summary(self):
        print(f"\n📊 当前统计:")
        print(f"   总交易: {self.results['total_trades']}, 盈利: {self.results['win_trades']}, 亏损: {self.results['loss_trades']}")
        print(f"   总盈利: {float(self.results['total_profit']):.2f}, 总亏损: {float(self.results['total_loss']):.2f}")
        print(f"   净收益: {float(self.results['total_profit'] - self.results['total_loss']):.2f} USDT\n")

    def on_kline(self, kline_data: dict):
        """处理K线数据"""
        k = kline_data['k']
        
        is_closed = k['x']
        open_price = Decimal(k['o'])
        high_price = Decimal(k['h'])
        low_price = Decimal(k['l'])
        close_price = Decimal(k['c'])
        
        self.current_candle = {
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'is_closed': is_closed,
        }
        
        if self.chain_state is None:
            self.chain_state = self._create_initial_state(close_price)
            return
        
        self._process_entry(low_price)
        self._process_exit(high_price, low_price, close_price)
        
        if is_closed:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] K线收盘: O={open_price:.2f}, H={high_price:.2f}, L={low_price:.2f}, C={close_price:.2f}")

    async def run(self):
        """运行实时模拟"""
        symbol = self.config.get("symbol", "btcusdt").lower()
        uri = f"wss://stream.binance.com:9443/ws/{symbol}@kline_1m"
        
        print("=" * 60)
        print("Autofish V1 实时模拟测试")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol.upper()}")
        print(f"  杠杆: {self.config.get('leverage', 10)}x")
        print(f"  网格间距: {float(self.config.get('grid_spacing', Decimal('0.01')))*100}%")
        print(f"  止盈: {float(self.config.get('exit_profit', Decimal('0.01')))*100}%")
        print(f"  止损: {float(self.config.get('stop_loss', Decimal('0.03')))*100}%")
        print(f"\n连接 Binance WebSocket（使用代理 socks5://127.0.0.1:1087）...")
        print(f"URI: {uri}\n")
        
        try:
            proxy = "http://127.0.0.1:1087"
            
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(uri, proxy=proxy) as websocket:
                    print("✅ 连接成功！开始接收实时数据...\n")
                    
                    async for message in websocket:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(message.data)
                            if 'k' in data:
                                self.on_kline(data)
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            print(f"WebSocket 错误: {websocket.exception()}")
                            break
                            
        except KeyboardInterrupt:
            print("\n\n⏹️ 停止模拟")
            self._print_summary()
        except Exception as e:
            print(f"\n❌ 错误: {e}")
            import traceback
            traceback.print_exc()
            self._print_summary()


def main():
    config = {
        "symbol": "btcusdt",
        "grid_spacing": Decimal("0.01"),
        "exit_profit": Decimal("0.01"),
        "stop_loss": Decimal("0.03"),
        "decay_factor": Decimal("0.5"),
        "total_amount_quote": Decimal("10000"),
        "leverage": Decimal("10"),
        "max_entries": 4,
    }
    
    simulator = RealtimeSimulator(config)
    asyncio.run(simulator.run())


if __name__ == '__main__':
    main()

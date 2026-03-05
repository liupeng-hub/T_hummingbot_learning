"""
Autofish V1 Binance 回测模块

使用历史 K 线数据进行策略回测

运行方式：
    cd hummingbot_learning
    source autofish_bot/venv/bin/activate
    python3 -m autofish_bot.binance_backtest --symbol BTCUSDT
"""

import asyncio
import json
import logging
import os
import argparse
from decimal import Decimal
from typing import List, Optional, Dict, Any
from datetime import datetime
import aiohttp
from dotenv import load_dotenv

from .autofish_core import (
    Order,
    ChainState,
    WeightCalculator,
    create_order,
    calculate_profit,
    calculate_order_prices,
    check_take_profit_triggered,
    check_stop_loss_triggered,
    check_entry_triggered,
    get_default_config,
)
from .amplitude_analyzer import AmplitudeConfig


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(LOG_DIR, ".env")
load_dotenv(ENV_FILE)
LOG_FILE = os.path.join(LOG_DIR, "binance_backtest.log")

HTTP_PROXY = os.getenv("HTTP_PROXY", "")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

class FlushFileHandler(logging.FileHandler):
    """每次写入后自动刷新的 FileHandler"""
    def emit(self, record):
        super().emit(record)
        self.flush()

file_handler = FlushFileHandler(LOG_FILE, mode='a', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, config: dict, use_amplitude_config: bool = True):
        self.config = config
        self.use_amplitude_config = use_amplitude_config
        self.amplitude_config: Optional[AmplitudeConfig] = None
        self.custom_weights: Optional[Dict[int, Decimal]] = None
        
        if use_amplitude_config:
            symbol = config.get("symbol", "BTCUSDT")
            self.amplitude_config = AmplitudeConfig.load_latest(symbol)
            if self.amplitude_config:
                decay_factor = Decimal(str(config.get("decay_factor", 0.5)))
                self.custom_weights = self.amplitude_config.get_weights(decay_factor)
                
                self.config["leverage"] = self.amplitude_config.get_leverage()
                self.config["grid_spacing"] = self.amplitude_config.get_grid_spacing()
                self.config["exit_profit"] = self.amplitude_config.get_exit_profit()
                self.config["stop_loss"] = self.amplitude_config.get_stop_loss()
                self.config["total_amount_quote"] = self.amplitude_config.get_total_amount_quote()
                self.config["max_entries"] = self.amplitude_config.get_max_entries()
                
                logger.info(f"[配置加载] 使用振幅分析配置: {symbol}")
                logger.info(f"  配置文件: {self.amplitude_config.config_path}")
                logger.info(f"  交易对: {self.config.get('symbol')}")
                logger.info(f"  杠杆: {self.config['leverage']}x")
                logger.info(f"  总投入: {self.config['total_amount_quote']} USDT")
                logger.info(f"  网格间距: {float(self.config['grid_spacing'])*100:.1f}%")
                logger.info(f"  止盈比例: {float(self.config['exit_profit'])*100:.1f}%")
                logger.info(f"  止损比例: {float(self.config['stop_loss'])*100:.1f}%")
                logger.info(f"  衰减因子: {self.config.get('decay_factor', 0.5)}")
                logger.info(f"  最大层级: {self.config['max_entries']}")
                logger.info(f"  权重: {self.custom_weights}")
            else:
                logger.warning("[配置加载] 未找到振幅分析配置，使用默认权重")
        
        self.calculator = WeightCalculator(Decimal(str(self.config.get("decay_factor", 0.5))))
        self.chain_state: Optional[ChainState] = None
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
            "trades": [],
        }
        self.kline_count = 0
        self.start_time = None
        self.end_time = None
    
    def _create_order(self, level: int, base_price: Decimal) -> Order:
        """创建订单"""
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.08"))
        total_amount = self.config.get("total_amount_quote", Decimal("1200"))
        
        if self.custom_weights and level in self.custom_weights:
            weight = self.custom_weights[level]
            stake_amount = total_amount * weight
            prices = calculate_order_prices(base_price, grid_spacing, exit_profit, stop_loss)
            quantity = stake_amount / prices["entry_price"]
            
            order = Order(
                level=level,
                entry_price=prices["entry_price"],
                quantity=quantity,
                stake_amount=stake_amount,
                take_profit_price=prices["take_profit_price"],
                stop_loss_price=prices["stop_loss_price"],
                state="pending",
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            )
            
            logger.info(f"[创建订单] A{level}: entry={prices['entry_price']:.2f}, "
                       f"tp={prices['take_profit_price']:.2f}, sl={prices['stop_loss_price']:.2f}, "
                       f"stake={stake_amount:.2f} USDT, qty={quantity:.6f} BTC, weight={weight:.4f}")
            
            return order
        
        return create_order(
            level=level,
            base_price=base_price,
            grid_spacing=grid_spacing,
            exit_profit=exit_profit,
            stop_loss=stop_loss,
            total_amount=total_amount,
            calculator=self.calculator
        )
    
    def _process_entry(self, low_price: Decimal, current_price: Decimal):
        """处理入场"""
        max_level = self.config.get("max_entries", 4)
        
        pending_order = self.chain_state.get_pending_order()
        if pending_order:
            if check_entry_triggered(low_price, pending_order.entry_price):
                pending_order.set_state("filled", "K线触发入场")
                
                weight_pct = self.calculator.get_weight_percentage(pending_order.level)
                logger.info(f"[入场成交] A{pending_order.level} (权重 {weight_pct:.2f}%): "
                           f"入场价={pending_order.entry_price:.2f}, "
                           f"数量={pending_order.quantity:.6f} BTC, "
                           f"金额={pending_order.stake_amount:.2f} USDT")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ A{pending_order.level} 成交: 入场价={pending_order.entry_price:.2f}")
                
                next_level = pending_order.level + 1
                if next_level <= max_level:
                    new_order = self._create_order(next_level, pending_order.entry_price)
                    self.chain_state.orders.append(new_order)
                    logger.info(f"[链式下单] 创建 A{next_level}: 入场价={new_order.entry_price:.2f}")
    
    def _process_exit(self, high_price: Decimal, low_price: Decimal, current_price: Decimal):
        """处理出场"""
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.08"))
        total_amount = self.config.get("total_amount_quote", Decimal("1200"))
        leverage = self.config.get("leverage", Decimal("10"))
        
        filled_orders = self.chain_state.get_filled_orders()
        
        for order in filled_orders:
            if order.state != "filled":
                continue
            
            if check_take_profit_triggered(high_price, order.take_profit_price):
                self._close_order(order, "take_profit", order.take_profit_price, leverage)
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[止盈后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break

            elif check_stop_loss_triggered(low_price, order.stop_loss_price):
                self._close_order(order, "stop_loss", order.stop_loss_price, leverage)
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[止损后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break
    
    def _close_order(self, order: Order, reason: str, close_price: Decimal, leverage: Decimal):
        """平仓"""
        order.set_state("closed", reason)
        order.close_price = close_price
        order.profit = calculate_profit(order, close_price, leverage)
        
        if reason == "take_profit":
            self.results["win_trades"] += 1
            self.results["total_profit"] += order.profit
            logger.info(f"[止盈] A{order.level}: 出场价={close_price:.2f}, "
                       f"盈利={order.profit:.2f} USDT")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 A{order.level} 止盈: 出场价={close_price:.2f}, 盈利={order.profit:.2f} USDT")
        else:
            self.results["loss_trades"] += 1
            self.results["total_loss"] += abs(order.profit)
            logger.info(f"[止损] A{order.level}: 出场价={close_price:.2f}, "
                       f"亏损={order.profit:.2f} USDT")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损: 出场价={close_price:.2f}, 亏损={order.profit:.2f} USDT")
        
        self.results["total_trades"] += 1
        self.results["trades"].append({
            "level": order.level,
            "entry_price": float(order.entry_price),
            "close_price": float(close_price),
            "profit": float(order.profit),
            "reason": reason,
        })
    
    def _on_kline(self, kline: dict):
        """处理 K 线数据"""
        self.kline_count += 1
        
        open_price = Decimal(str(kline.get("open", kline.get("o", 0))))
        high_price = Decimal(str(kline.get("high", kline.get("h", 0))))
        low_price = Decimal(str(kline.get("low", kline.get("l", 0))))
        close_price = Decimal(str(kline.get("close", kline.get("c", 0))))
        volume = Decimal(str(kline.get("volume", kline.get("v", 0))))
        timestamp = kline.get("timestamp", kline.get("t", 0))
        
        if self.kline_count % 100 == 0:
            dt = datetime.fromtimestamp(timestamp / 1000) if timestamp else datetime.now()
            logger.debug(f"[K线 #{self.kline_count}] {dt.strftime('%Y-%m-%d %H:%M')} "
                        f"O={open_price:.2f} H={high_price:.2f} L={low_price:.2f} C={close_price:.2f}")
        
        self._process_entry(low_price, close_price)
        self._process_exit(high_price, low_price, close_price)
    
    async def fetch_klines(self, symbol: str, interval: str = "1m", limit: int = 1000) -> List[dict]:
        """获取历史 K 线数据"""
        url = f"https://fapi.binance.com/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        
        proxy = HTTPS_PROXY or HTTP_PROXY or None
        
        logger.info(f"[获取K线] symbol={symbol}, interval={interval}, limit={limit}, proxy={proxy}")
        
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            kwargs = {"params": params}
            if proxy:
                kwargs["proxy"] = proxy
            
            async with session.get(url, **kwargs) as response:
                if response.status == 200:
                    data = await response.json()
                    klines = []
                    for item in data:
                        klines.append({
                            "timestamp": item[0],
                            "open": item[1],
                            "high": item[2],
                            "low": item[3],
                            "close": item[4],
                            "volume": item[5],
                        })
                    logger.info(f"[获取K线] 成功获取 {len(klines)} 条数据")
                    return klines
                else:
                    text = await response.text()
                    logger.error(f"[获取K线] 失败: {response.status} - {text}")
                    return []
    
    async def run(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 1000):
        """运行回测"""
        logger.info("=" * 60)
        logger.info("Autofish V1 回测开始")
        logger.info("=" * 60)
        logger.info(f"配置: {self.config}")
        
        print("=" * 60)
        print("Autofish V1 回测")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol}")
        print(f"  K线周期: {interval}")
        print(f"  数据量: {limit}")
        print(f"  网格间距: {float(self.config.get('grid_spacing', Decimal('0.01')))*100}%")
        print(f"  止盈: {float(self.config.get('exit_profit', Decimal('0.01')))*100}%")
        print(f"  止损: {float(self.config.get('stop_loss', Decimal('0.08')))*100}%")
        print(f"  杠杆: {self.config.get('leverage', 10)}x")
        print(f"  总资金: {self.config.get('total_amount_quote', 1200)} USDT")
        print(f"  最大层级: {self.config.get('max_entries', 4)}")
        
        klines = await self.fetch_klines(symbol, interval, limit)
        
        if not klines:
            logger.error("获取 K 线数据失败")
            return
        
        self.start_time = datetime.fromtimestamp(klines[0]["timestamp"] / 1000)
        self.end_time = datetime.fromtimestamp(klines[-1]["timestamp"] / 1000)
        
        print(f"\n📊 回测时间范围:")
        print(f"  开始: {self.start_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  结束: {self.end_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  K线数: {len(klines)}")
        
        first_price = Decimal(klines[0]["open"])
        self.chain_state = ChainState(base_price=first_price)
        
        first_order = self._create_order(1, first_price)
        self.chain_state.orders.append(first_order)
        
        logger.info(f"[初始化] 创建 A1: 入场价={first_order.entry_price:.2f}")
        print(f"\n📋 创建首个订单: A1 入场价={first_order.entry_price:.2f}")
        
        print(f"\n⏳ 开始回测...")
        
        for kline in klines:
            self._on_kline(kline)
        
        self._print_summary()
    
    def _print_summary(self):
        """打印回测结果"""
        net_profit = self.results["total_profit"] - self.results["total_loss"]
        win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
                   if self.results["total_trades"] > 0 else 0)
        
        print("\n" + "=" * 60)
        print("📊 回测结果")
        print("=" * 60)
        print(f"  回测时间: {self.start_time.strftime('%Y-%m-%d %H:%M')} - {self.end_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  K线数量: {self.kline_count}")
        print(f"  总交易: {self.results['total_trades']}")
        print(f"  盈利次数: {self.results['win_trades']}")
        print(f"  亏损次数: {self.results['loss_trades']}")
        print(f"  胜率: {win_rate:.2f}%")
        print(f"  总盈利: {float(self.results['total_profit']):.2f} USDT")
        print(f"  总亏损: {float(self.results['total_loss']):.2f} USDT")
        print(f"  净收益: {float(net_profit):.2f} USDT")
        print("=" * 60)
        
        logger.info("=" * 60)
        logger.info("回测结果")
        logger.info("=" * 60)
        logger.info(f"  总交易: {self.results['total_trades']}")
        logger.info(f"  盈利次数: {self.results['win_trades']}")
        logger.info(f"  亏损次数: {self.results['loss_trades']}")
        logger.info(f"  胜率: {win_rate:.2f}%")
        logger.info(f"  总盈利: {self.results['total_profit']:.2f} USDT")
        logger.info(f"  总亏损: {self.results['total_loss']:.2f} USDT")
        logger.info(f"  净收益: {net_profit:.2f} USDT")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Autofish V1 回测")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期 (默认: 1m)")
    parser.add_argument("--limit", type=int, default=1500, help="K线数量 (默认: 1500)")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="止损比例 (默认: 0.08)")
    parser.add_argument("--total-amount", type=float, default=1200, help="总投入金额 (默认: 1200)")
    
    args = parser.parse_args()
    
    config = get_default_config()
    config["symbol"] = args.symbol
    config.update({
        "stop_loss": Decimal(str(args.stop_loss)),
        "total_amount_quote": Decimal(str(args.total_amount)),
    })
    
    engine = BacktestEngine(config)
    await engine.run(symbol=args.symbol, interval=args.interval, limit=args.limit)


if __name__ == "__main__":
    asyncio.run(main())

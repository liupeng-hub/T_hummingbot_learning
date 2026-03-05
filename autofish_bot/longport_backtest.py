"""
Autofish V1 LongPort 回测模块

使用 LongPort API 获取历史 K 线数据进行策略回测
支持港股、美股、A股

运行方式：
    cd hummingbot_learning
    source autofish_bot/venv/bin/activate
    python3 -m autofish_bot.longport_backtest --symbol 700.HK

环境变量配置 (.env):
    LONGPORT_APP_KEY=your_app_key
    LONGPORT_APP_SECRET=your_app_secret
    LONGPORT_ACCESS_TOKEN=your_access_token
"""

import asyncio
import json
import logging
import os
import argparse
from decimal import Decimal
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dotenv import load_dotenv

from longport.openapi import Config, QuoteContext, Period, AdjustType

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

LOG_FILE = os.path.join(LOG_DIR, "longport_backtest.log")

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


def get_period_from_interval(interval: str) -> Period:
    """将间隔字符串转换为 Period 枚举"""
    period_map = {
        "1m": Period.Min_1,
        "2m": Period.Min_2,
        "3m": Period.Min_3,
        "5m": Period.Min_5,
        "10m": Period.Min_10,
        "15m": Period.Min_15,
        "20m": Period.Min_20,
        "30m": Period.Min_30,
        "45m": Period.Min_45,
        "60m": Period.Min_60,
        "1h": Period.Min_60,
        "2h": Period.Min_120,
        "3h": Period.Min_180,
        "4h": Period.Min_240,
        "1d": Period.Day,
        "1D": Period.Day,
        "1w": Period.Week,
        "1W": Period.Week,
        "1M": Period.Month,
    }
    return period_map.get(interval, Period.Min_1)


class LongPortBacktestEngine:
    """LongPort 回测引擎"""
    
    def __init__(self, config: dict, use_amplitude_config: bool = True):
        self.config = config
        self.use_amplitude_config = use_amplitude_config
        self.amplitude_config: Optional[AmplitudeConfig] = None
        self.custom_weights: Optional[Dict[int, Decimal]] = None
        
        if use_amplitude_config:
            symbol = config.get("symbol", "700.HK")
            self.amplitude_config = AmplitudeConfig.load_latest(symbol)
            if self.amplitude_config:
                decay_factor = Decimal(str(config.get("decay_factor", 0.5)))
                self.custom_weights = self.amplitude_config.get_weights(decay_factor)
                
                self.config["grid_spacing"] = self.amplitude_config.get_grid_spacing()
                self.config["exit_profit"] = self.amplitude_config.get_exit_profit()
                self.config["stop_loss"] = self.amplitude_config.get_stop_loss()
                self.config["total_amount_quote"] = self.amplitude_config.get_total_amount_quote()
                self.config["max_entries"] = self.amplitude_config.get_max_entries()
                
                logger.info(f"[配置加载] 使用振幅分析配置: {symbol}")
                logger.info(f"  配置文件: {self.amplitude_config.config_path}")
                logger.info(f"  交易对: {self.config.get('symbol')}")
                logger.info(f"  总投入: {self.config['total_amount_quote']} {self._get_currency()}")
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
        
        self.quote_ctx: Optional[QuoteContext] = None
    
    def _get_currency(self) -> str:
        """根据交易对获取货币类型"""
        symbol = self.config.get("symbol", "700.HK")
        if ".HK" in symbol.upper():
            return "HKD"
        elif ".US" in symbol.upper():
            return "USD"
        elif ".SH" in symbol.upper() or ".SZ" in symbol.upper():
            return "CNY"
        return "USD"
    
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
                       f"stake={stake_amount:.2f}, qty={quantity:.6f}, weight={weight:.4f}")
            
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
                           f"数量={pending_order.quantity:.6f}, "
                           f"金额={pending_order.stake_amount:.2f}")
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
        
        filled_orders = self.chain_state.get_filled_orders()
        
        for order in filled_orders:
            if order.state != "filled":
                continue
            
            if check_take_profit_triggered(high_price, order.take_profit_price):
                self._close_order(order, "take_profit", order.take_profit_price)
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[止盈后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break

            elif check_stop_loss_triggered(low_price, order.stop_loss_price):
                self._close_order(order, "stop_loss", order.stop_loss_price)
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[止损后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break
    
    def _close_order(self, order: Order, reason: str, close_price: Decimal):
        """平仓"""
        order.set_state("closed", reason)
        order.close_price = close_price
        order.profit = calculate_profit(order, close_price, Decimal("1"))
        
        if reason == "take_profit":
            self.results["win_trades"] += 1
            self.results["total_profit"] += order.profit
            logger.info(f"[止盈] A{order.level}: 出场价={close_price:.2f}, "
                       f"盈利={order.profit:.2f}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 A{order.level} 止盈: 出场价={close_price:.2f}, 盈利={order.profit:.2f}")
        else:
            self.results["loss_trades"] += 1
            self.results["total_loss"] += abs(order.profit)
            logger.info(f"[止损] A{order.level}: 出场价={close_price:.2f}, "
                       f"亏损={order.profit:.2f}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 A{order.level} 止损: 出场价={close_price:.2f}, 亏损={order.profit:.2f}")
        
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
            dt = datetime.fromtimestamp(timestamp) if timestamp else datetime.now()
            logger.debug(f"[K线 #{self.kline_count}] {dt.strftime('%Y-%m-%d %H:%M')} "
                        f"O={open_price:.2f} H={high_price:.2f} L={low_price:.2f} C={close_price:.2f}")
        
        self._process_entry(low_price, close_price)
        self._process_exit(high_price, low_price, close_price)
    
    async def fetch_klines(self, symbol: str, period: Period, count: int = 200) -> List[dict]:
        """获取历史 K 线数据"""
        logger.info(f"[获取K线] symbol={symbol}, period={period}, count={count}")
        
        try:
            config = Config.from_env()
            self.quote_ctx = QuoteContext(config)
            
            candlesticks = self.quote_ctx.history_candlesticks_by_offset(
                symbol=symbol,
                period=period,
                adjust_type=AdjustType.NoAdjust,
                forward=False,
                time=datetime.now(),
                count=count
            )
            
            klines = []
            for candle in candlesticks:
                klines.append({
                    "timestamp": int(candle.timestamp.timestamp() * 1000),
                    "open": str(candle.open),
                    "high": str(candle.high),
                    "low": str(candle.low),
                    "close": str(candle.close),
                    "volume": str(candle.volume),
                })
            
            logger.info(f"[获取K线] 成功获取 {len(klines)} 条数据")
            return klines
            
        except Exception as e:
            logger.error(f"[获取K线] 失败: {e}")
            return []
    
    async def run(self, symbol: str = "700.HK", interval: str = "1m", count: int = 200):
        """运行回测"""
        logger.info("=" * 60)
        logger.info("Autofish V1 LongPort 回测开始")
        logger.info("=" * 60)
        logger.info(f"配置: {self.config}")
        
        currency = self._get_currency()
        period = get_period_from_interval(interval)
        
        print("=" * 60)
        print("Autofish V1 LongPort 回测")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol}")
        print(f"  K线周期: {interval}")
        print(f"  数据量: {count}")
        print(f"  网格间距: {float(self.config.get('grid_spacing', Decimal('0.01')))*100}%")
        print(f"  止盈: {float(self.config.get('exit_profit', Decimal('0.01')))*100}%")
        print(f"  止损: {float(self.config.get('stop_loss', Decimal('0.08')))*100}%")
        print(f"  总资金: {self.config.get('total_amount_quote', 1200)} {currency}")
        print(f"  最大层级: {self.config.get('max_entries', 4)}")
        
        klines = await self.fetch_klines(symbol, period, count)
        
        if not klines:
            logger.error("获取 K 线数据失败")
            return
        
        self.start_time = datetime.fromtimestamp(klines[0]["timestamp"])
        self.end_time = datetime.fromtimestamp(klines[-1]["timestamp"])
        
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
        currency = self._get_currency()
        
        print("\n" + "=" * 60)
        print("📊 回测结果")
        print("=" * 60)
        print(f"  回测时间: {self.start_time.strftime('%Y-%m-%d %H:%M')} - {self.end_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  K线数量: {self.kline_count}")
        print(f"  总交易: {self.results['total_trades']}")
        print(f"  盈利次数: {self.results['win_trades']}")
        print(f"  亏损次数: {self.results['loss_trades']}")
        print(f"  胜率: {win_rate:.2f}%")
        print(f"  总盈利: {float(self.results['total_profit']):.2f} {currency}")
        print(f"  总亏损: {float(self.results['total_loss']):.2f} {currency}")
        print(f"  净收益: {float(net_profit):.2f} {currency}")
        print("=" * 60)
        
        logger.info("=" * 60)
        logger.info("回测结果")
        logger.info("=" * 60)
        logger.info(f"  总交易: {self.results['total_trades']}")
        logger.info(f"  盈利次数: {self.results['win_trades']}")
        logger.info(f"  亏损次数: {self.results['loss_trades']}")
        logger.info(f"  胜率: {win_rate:.2f}%")
        logger.info(f"  总盈利: {self.results['total_profit']:.2f} {currency}")
        logger.info(f"  总亏损: {self.results['total_loss']:.2f} {currency}")
        logger.info(f"  净收益: {net_profit:.2f} {currency}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Autofish V1 LongPort 回测")
    parser.add_argument("--symbol", type=str, default="700.HK", help="交易对 (默认: 700.HK)")
    parser.add_argument("--interval", type=str, default="1d", help="K线周期 (默认: 1d)")
    parser.add_argument("--count", type=int, default=200, help="K线数量 (默认: 200)")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="止损比例 (默认: 0.08)")
    parser.add_argument("--total-amount", type=float, default=1200, help="总投入金额 (默认: 1200)")
    
    args = parser.parse_args()
    
    config = get_default_config()
    config["symbol"] = args.symbol
    config.update({
        "stop_loss": Decimal(str(args.stop_loss)),
        "total_amount_quote": Decimal(str(args.total_amount)),
    })
    
    engine = LongPortBacktestEngine(config)
    await engine.run(symbol=args.symbol, interval=args.interval, count=args.count)


if __name__ == "__main__":
    asyncio.run(main())

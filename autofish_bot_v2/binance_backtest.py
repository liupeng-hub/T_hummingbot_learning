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

from autofish_core import (
    Autofish_Order,
    Autofish_ChainState,
    Autofish_WeightCalculator,
    Autofish_OrderCalculator,
    Autofish_AmplitudeConfig,
)


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
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
    """Binance 回测引擎
    
    使用历史 K 线数据模拟链式挂单策略的执行过程。
    
    主要功能：
    1. 获取历史 K 线数据
    2. 模拟订单执行（入场、止盈、止损）
    3. 计算盈亏统计
    4. 生成回测报告
    
    回测流程：
        获取K线 -> 遍历每根K线 -> 检查入场/出场条件 -> 
        更新状态 -> 计算盈亏 -> 生成报告
    
    Attributes:
        config: 配置字典（symbol, total_amount, leverage 等）
        interval: K线周期
        calculator: 权重计算器
        chain_state: 链式挂单状态
        results: 回测结果统计
        kline_count: 已处理的 K 线数量
        start_time: 回测开始时间
        end_time: 回测结束时间
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.interval = None
        self.days = None  # 回测天数
        
        self.calculator = Autofish_WeightCalculator(Decimal(str(self.config.get("decay_factor", 0.5))))
        self.chain_state: Optional[Autofish_ChainState] = None
        self.results = {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "total_profit": Decimal("0"),
            "total_loss": Decimal("0"),
            "trades": [],
            "simultaneous_triggers": 0,
            "first_price": None,      # 第一根 K 线价格
            "last_price": None,       # 最后一根 K 线价格
            "trade_returns": [],      # 每笔交易的收益率列表
            "max_profit": Decimal("0"),   # 最大单笔盈利
            "max_loss": Decimal("0"),     # 最大单笔亏损
        }
        self.kline_count = 0
        self.start_time = None
        self.end_time = None
        self.klines_history: List[Dict] = []
    
    def _get_weights(self) -> Dict[int, Decimal]:
        """获取归一化后的权重"""
        from autofish_core import normalize_weights
        
        weights_list = [Decimal(str(w)) for w in self.config.get("weights", [])]
        if not weights_list:
            return {}
        
        max_entries = self.config.get('max_entries', 4)
        normalized_weights = normalize_weights(weights_list, max_entries)
        
        weights = {}
        for i, w in enumerate(normalized_weights):
            weights[i + 1] = w
        return weights
    
    def _create_order(self, level: int, base_price: Decimal, klines: List[Dict] = None) -> Autofish_Order:
        """创建订单
        
        参数:
            level: 层级
            base_price: 基准价格
            klines: K 线数据（用于策略计算，仅 A1 使用）
        """
        from autofish_core import EntryPriceStrategyFactory
        
        grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
        exit_profit = self.config.get("exit_profit", Decimal("0.01"))
        stop_loss = self.config.get("stop_loss", Decimal("0.08"))
        total_amount = self.config.get("total_amount_quote", Decimal("1200"))
        
        # 从配置创建入场价格策略
        strategy_config = self.config.get("entry_price_strategy", {"name": "fixed"})
        strategy = EntryPriceStrategyFactory.create(
            strategy_config.get("name", "fixed"),
            **strategy_config.get("params", {})
        )
        
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=grid_spacing,
            exit_profit=exit_profit,
            stop_loss=stop_loss,
            entry_strategy=strategy
        )
        
        weights = self._get_weights()
        if weights and level in weights:
            weight = weights[level]
            stake_amount = total_amount * weight
            
            # 使用策略计算入场价格（仅 A1 使用策略）
            if level == 1:
                entry_price = strategy.calculate_entry_price(
                    current_price=base_price,
                    level=level,
                    grid_spacing=grid_spacing,
                    klines=klines
                )
            else:
                entry_price = base_price * (Decimal("1") - grid_spacing * level)
            
            take_profit_price = entry_price * (Decimal("1") + exit_profit)
            stop_loss_price = entry_price * (Decimal("1") - stop_loss)
            quantity = stake_amount / entry_price
            
            order = Autofish_Order(
                level=level,
                entry_price=entry_price,
                quantity=quantity,
                stake_amount=stake_amount,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
                state="pending",
                created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            )
            
            logger.info(f"[创建订单] A{level}: entry={entry_price:.2f}, "
                       f"tp={take_profit_price:.2f}, sl={stop_loss_price:.2f}, "
                       f"stake={stake_amount:.2f} USDT, qty={quantity:.6f} BTC, "
                       f"weight={weight:.4f}, strategy={strategy.name}")
            
            return order
        
        # fallback: 使用默认权重
        weights_list = [Decimal(str(w)) for w in self.config.get("weights", [])]
        max_entries = self.config.get('max_entries', 4)
        return order_calculator.create_order(
            level=level,
            base_price=base_price,
            total_amount=total_amount,
            weights=weights_list,
            max_entries=max_entries,
            klines=klines
        )
    
    def _process_entry(self, low_price: Decimal, current_price: Decimal):
        """处理入场"""
        max_level = self.config.get("max_entries", 4)
        
        pending_order = self.chain_state.get_pending_order()
        if pending_order:
            if Autofish_OrderCalculator.check_entry_triggered(low_price, pending_order.entry_price):
                pending_order.set_state("filled", "K线触发入场")
                
                weights = self._get_weights()
                weight_pct = float(weights.get(pending_order.level, Decimal("0"))) * 100
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
    
    def _process_exit(self, open_price: Decimal, high_price: Decimal, low_price: Decimal, current_price: Decimal):
        """处理出场
        
        改进：当 K 线同时触及止盈止损时，根据 K 线形态判断触发顺序
        
        参数:
            open_price: K 线开盘价
            high_price: K 线最高价
            low_price: K 线最低价
            current_price: 当前价格（收盘价）
        """
        leverage = self.config.get("leverage", Decimal("10"))
        
        filled_orders = self.chain_state.get_filled_orders()
        
        for order in filled_orders:
            if order.state != "filled":
                continue
            
            tp_triggered = high_price >= order.take_profit_price
            sl_triggered = low_price <= order.stop_loss_price
            
            if tp_triggered and sl_triggered:
                self.results["simultaneous_triggers"] += 1
                
                exit_type = self._determine_exit_order(order, open_price, high_price, low_price, current_price)
                
                logger.warning(
                    f"[同时触发] K线同时触及止盈止损: "
                    f"A{order.level}, TP={order.take_profit_price:.2f}, SL={order.stop_loss_price:.2f}, "
                    f"K线 O={open_price:.2f} H={high_price:.2f} L={low_price:.2f} C={current_price:.2f}, "
                    f"判断结果: {exit_type}"
                )
                
                if exit_type == "take_profit":
                    self._close_order(order, "take_profit", order.take_profit_price, leverage)
                else:
                    self._close_order(order, "stop_loss", order.stop_loss_price, leverage)
                
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[{'止盈' if exit_type == 'take_profit' else '止损'}后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break
                
            elif tp_triggered:
                self._close_order(order, "take_profit", order.take_profit_price, leverage)
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[止盈后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break
                
            elif sl_triggered:
                self._close_order(order, "stop_loss", order.stop_loss_price, leverage)
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[止损后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break
    
    def _determine_exit_order(self, order: Autofish_Order, open_price: Decimal, high_price: Decimal, low_price: Decimal, close_price: Decimal) -> str:
        """判断止盈止损触发顺序
        
        当 K 线同时触及止盈止损时，根据 K 线形态判断触发顺序：
        - 阳线（close > open）：假设先跌后涨，止损先触发
        - 阴线（close < open）：假设先涨后跌，止盈先触发
        - 十字星（close ≈ open）：假设止损先触发（保守估计）
        
        参数:
            order: 订单对象
            open_price: K 线开盘价
            high_price: K 线最高价
            low_price: K 线最低价
            close_price: K 线收盘价
            
        返回:
            "take_profit" 或 "stop_loss"
        """
        if close_price > open_price:
            return "stop_loss"
        elif close_price < open_price:
            return "take_profit"
        else:
            return "stop_loss"
    
    def _close_order(self, order: Autofish_Order, reason: str, close_price: Decimal, leverage: Decimal):
        """平仓"""
        order.set_state("closed", reason)
        order.close_price = close_price
        order.profit = Autofish_OrderCalculator(leverage=leverage).calculate_profit(order, close_price)
        
        # 计算并记录交易收益率
        if order.stake_amount and order.stake_amount > 0:
            trade_return = order.profit / order.stake_amount
            self.results["trade_returns"].append(trade_return)
        
        # 更新最大盈亏
        if order.profit > self.results["max_profit"]:
            self.results["max_profit"] = order.profit
        if order.profit < self.results["max_loss"]:
            self.results["max_loss"] = order.profit
        
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
        self._process_exit(open_price, high_price, low_price, close_price)
    
    async def fetch_klines(self, symbol: str, interval: str = "1m", limit: int = 1000, days: int = None, start_time: int = None, end_time: int = None, auto_fetch: bool = True) -> List[dict]:
        """获取历史 K 线数据
        
        优先从本地缓存获取，如果缓存数据不完整则自动补充缺失数据
        
        参数:
            symbol: 交易对
            interval: K 线周期
            limit: 单次获取数量（最大 1500）
            days: 回测天数
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
            auto_fetch: 是否自动获取缺失数据
        """
        from binance_kline_fetcher import KlineFetcher
        
        fetcher = KlineFetcher()
        
        # 计算时间范围（如果未指定）
        if not start_time or not end_time:
            end_time = int(datetime.now().timestamp() * 1000)
            if days:
                start_time = end_time - days * 24 * 60 * 60 * 1000
            else:
                interval_minutes = {
                    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
                    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
                    "1d": 1440, "3d": 4320, "1w": 10080
                }
                minutes = interval_minutes.get(interval, 1)
                start_time = end_time - limit * minutes * 60 * 1000
        
        # 检查缓存覆盖情况
        missing_ranges = fetcher._find_missing_ranges(symbol, interval, start_time, end_time)
        
        # 如果有缺失且启用自动获取
        if missing_ranges and auto_fetch:
            print(f"\n⚠️  缓存数据不完整，缺失 {len(missing_ranges)} 个时间段:")
            for range_start, range_end in missing_ranges:
                start_dt = datetime.fromtimestamp(range_start / 1000)
                end_dt = datetime.fromtimestamp(range_end / 1000)
                print(f"  - {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")
            
            print(f"\n[自动补充] 正在获取缺失数据...")
            
            # 自动获取缺失数据
            for range_start, range_end in missing_ranges:
                try:
                    klines = await fetcher._fetch_from_api(symbol, interval, range_start, range_end)
                    if klines:
                        fetcher._save_to_cache(symbol, interval, klines)
                except Exception as e:
                    logger.error(f"[自动补充] 获取失败: {e}")
                    print(f"\n❌ 自动获取失败，请手动运行:")
                    print(f"   python binance_kline_fetcher.py --symbol {symbol} --interval {interval}")
                    return []
            
            print(f"\n✅ 缓存已更新")
        
        # 从缓存读取数据
        klines = fetcher.query_cache(symbol, interval, start_time, end_time)
        
        if klines:
            logger.info(f"[获取K线] 从本地缓存获取 {len(klines)} 条数据")
            print(f"[获取K线] 从本地缓存获取 {len(klines)} 条数据")
            return klines
        
        # 缓存无数据
        if not auto_fetch:
            logger.error(f"[获取K线] 本地缓存无数据，自动获取已禁用")
            print(f"\n❌ 本地缓存无数据，自动获取已禁用，请手动运行:")
            print(f"   python binance_kline_fetcher.py --symbol {symbol} --interval {interval}")
        else:
            logger.error(f"[获取K线] 本地缓存无数据")
            print(f"\n❌ 本地缓存无数据，请先运行:")
            print(f"   python binance_kline_fetcher.py --symbol {symbol} --interval {interval}")
        
        return []
    
    async def run(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 1000, days: int = None, start_time: int = None, end_time: int = None, auto_fetch: bool = True):
        """运行回测
        
        主要流程：
        1. 获取历史 K 线数据
        2. 遍历每根 K 线，模拟订单执行
        3. 统计盈亏结果
        4. 生成回测报告
        
        参数:
            symbol: 交易对
            interval: K线周期
            limit: K线数量
            days: 回测天数（如果指定，则分批获取足够的数据）
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
            auto_fetch: 是否自动获取缺失数据
        """
        self.interval = interval
        self.days = days  # 保存回测天数
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
        if start_time and end_time:
            start_dt = datetime.fromtimestamp(start_time / 1000)
            end_dt = datetime.fromtimestamp(end_time / 1000)
            print(f"  时间范围: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")
        elif days:
            print(f"  回测天数: {days} 天")
        else:
            print(f"  数据量: {limit}")
        print(f"  网格间距: {float(self.config.get('grid_spacing', Decimal('0.01')))*100}%")
        print(f"  止盈: {float(self.config.get('exit_profit', Decimal('0.01')))*100}%")
        print(f"  止损: {float(self.config.get('stop_loss', Decimal('0.08')))*100}%")
        print(f"  杠杆: {self.config.get('leverage', 10)}x")
        print(f"  总资金: {self.config.get('total_amount_quote', 1200)} USDT")
        print(f"  最大层级: {self.config.get('max_entries', 4)}")
        
        klines = await self.fetch_klines(symbol, interval, limit, days, start_time, end_time, auto_fetch)
        
        if not klines:
            logger.error("获取 K 线数据失败")
            return
        
        self.start_time = datetime.fromtimestamp(klines[0]["timestamp"] / 1000)
        self.end_time = datetime.fromtimestamp(klines[-1]["timestamp"] / 1000)
        
        # 记录首尾价格（用于计算标的涨跌幅）
        self.results["first_price"] = Decimal(klines[0]["open"])
        self.results["last_price"] = Decimal(klines[-1]["close"])
        
        print(f"\n📊 回测时间范围:")
        print(f"  开始: {self.start_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  结束: {self.end_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  K线数: {len(klines)}")
        
        first_price = Decimal(klines[0]["open"])
        self.chain_state = Autofish_ChainState(base_price=first_price)
        
        self.klines_history = klines[:30] if len(klines) >= 30 else klines
        first_order = self._create_order(1, first_price, self.klines_history)
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
    
    def calculate_metrics(self) -> Dict[str, Any]:
        """计算回测指标
        
        返回:
            包含各项指标的字典
        """
        # 标的涨跌幅
        if self.results["first_price"] and self.results["last_price"]:
            price_change = (self.results["last_price"] - self.results["first_price"]) / self.results["first_price"] * 100
        else:
            price_change = Decimal("0")
        
        # 盈亏比
        if self.results["loss_trades"] > 0 and self.results["win_trades"] > 0:
            avg_profit = self.results["total_profit"] / self.results["win_trades"]
            avg_loss = self.results["total_loss"] / self.results["loss_trades"]
            profit_loss_ratio = avg_profit / avg_loss
        else:
            profit_loss_ratio = None  # 无亏损或无盈利
        
        # 夏普比率
        if len(self.results["trade_returns"]) >= 2:
            returns = [float(r) for r in self.results["trade_returns"]]
            avg_return = sum(returns) / len(returns)
            variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
            std_dev = variance ** 0.5
            # 当标准差接近 0 时（所有收益相同），夏普比率无意义
            if std_dev < 1e-10:
                sharpe_ratio = Decimal("0")
            else:
                sharpe_ratio = Decimal(str(avg_return / std_dev))
        else:
            sharpe_ratio = Decimal("0")
        
        return {
            "price_change": price_change,
            "profit_loss_ratio": profit_loss_ratio,
            "sharpe_ratio": sharpe_ratio,
        }
    
    def save_report(self, symbol: str, days: int = None, date_range: str = None):
        """保存回测报告到 Markdown 文件
        
        生成包含以下内容的报告：
        1. 回测区间信息
        2. 振幅配置参数
        3. 回测结果统计
        4. 交易明细
        
        参数:
            symbol: 交易对
            days: 回测天数（可选，用于文件名）
            date_range: 时间范围字符串（可选，用于文件名，格式: yyyymmdd-yyyymmdd）
        """
        import os
        
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autofish_output")
        os.makedirs(output_dir, exist_ok=True)
        
        if date_range:
            filepath = os.path.join(output_dir, f"binance_{symbol}_backtest_report_{date_range}.md")
        elif days:
            filepath = os.path.join(output_dir, f"binance_{symbol}_backtest_report_{days}d.md")
        else:
            filepath = os.path.join(output_dir, f"binance_{symbol}_backtest_report.md")
        
        net_profit = self.results["total_profit"] - self.results["total_loss"]
        win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
                   if self.results["total_trades"] > 0 else 0)
        
        lines = []
        lines.append(f"# Autofish V2 回测报告 (Binance: {symbol})")
        lines.append(f"")
        lines.append(f"**回测时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"")
        
        lines.append(f"## 回测区间")
        lines.append(f"")
        lines.append(f"| 项目 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 交易对 | {symbol} |")
        lines.append(f"| K线周期 | {self.interval} |")
        lines.append(f"| 开始时间 | {self.start_time.strftime('%Y-%m-%d %H:%M') if self.start_time else '-'} |")
        lines.append(f"| 结束时间 | {self.end_time.strftime('%Y-%m-%d %H:%M') if self.end_time else '-'} |")
        lines.append(f"| K线数量 | {self.kline_count} |")
        lines.append(f"")
        
        lines.append(f"## 振幅配置参数")
        lines.append(f"")
        weights_list = self.config.get("weights", [])
        if weights_list:
            weights_dict = {i+1: w for i, w in enumerate(weights_list)}
            valid_amplitudes = self.config.get("valid_amplitudes", [])
            total_expected_return = self.config.get("total_expected_return", 0)
            
            lines.append(f"| 参数 | 值 | 说明 |")
            lines.append(f"|------|-----|------|")
            lines.append(f"| 杠杆 | {self.config.get('leverage', 10)}x | - |")
            lines.append(f"| 总投入 | {self.config.get('total_amount_quote', 1200)} USDT | - |")
            lines.append(f"| 网格间距 | {float(self.config.get('grid_spacing', 0.01))*100:.1f}% | 入场价 = 基准价 × (1 - 网格间距) |")
            lines.append(f"| 止盈比例 | {float(self.config.get('exit_profit', 0.01))*100:.1f}% | 止盈价 = 入场价 × (1 + 止盈比例) |")
            lines.append(f"| 止损比例 | {float(self.config.get('stop_loss', 0.08))*100:.1f}% | 止损价 = 入场价 × (1 - 止损比例) |")
            lines.append(f"| 衰减因子 | {self.config.get('decay_factor', 0.5)} | 权重计算参数 |")
            lines.append(f"| 最大层级 | {self.config.get('max_entries', 4)} | 最多挂单层数 |")
            lines.append(f"| 有效振幅 | {valid_amplitudes} | 正收益区间 |")
            weight_items = [f"A{k}: {v*100:.2f}%" for k, v in sorted(weights_dict.items())]
            weight_lines = []
            for i in range(0, len(weight_items), 3):
                weight_lines.append(", ".join(weight_items[i:i+3]))
            lines.append(f"| 权重 | {'<br>'.join(weight_lines)} | 各层级资金分配比例 |")
            lines.append(f"| 总预期收益 | {float(total_expected_return)*100:.2f}% | 振幅分析预期 |")
        else:
            lines.append(f"未使用振幅配置，使用默认参数")
        lines.append(f"")
        
        lines.append(f"## 回测结果")
        lines.append(f"")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 总交易次数 | {self.results['total_trades']} |")
        lines.append(f"| 盈利次数 | {self.results['win_trades']} |")
        lines.append(f"| 亏损次数 | {self.results['loss_trades']} |")
        lines.append(f"| 胜率 | {win_rate:.2f}% |")
        lines.append(f"| 总盈利 | {float(self.results['total_profit']):.2f} USDT |")
        lines.append(f"| 总亏损 | {float(self.results['total_loss']):.2f} USDT |")
        lines.append(f"| 净收益 | {float(net_profit):.2f} USDT |")
        if self.config.get('total_amount_quote'):
            roi = float(net_profit) / float(self.config.get('total_amount_quote', 1200)) * 100
            lines.append(f"| 收益率 | {roi:.2f}% | 净收益 / 总投入 |")
        
        if self.results.get('simultaneous_triggers', 0) > 0:
            lines.append(f"| 同时触及止盈止损 | {self.results['simultaneous_triggers']} 次 | K线同时触及止盈止损，根据K线形态判断 |")
        lines.append(f"")
        
        # 计算指标
        metrics = self.calculate_metrics()
        
        # 对比分析
        lines.append(f"## 对比分析")
        lines.append(f"")
        lines.append(f"| 指标 | 值 | 说明 |")
        lines.append(f"|------|-----|------|")
        
        price_change = float(metrics["price_change"])
        roi = float(net_profit) / float(self.config.get('total_amount_quote', 1200)) * 100
        excess_return = roi - price_change
        
        lines.append(f"| 标的涨跌幅 | {price_change:.2f}% | 同期 {symbol} 涨跌 |")
        lines.append(f"| 策略收益率 | {roi:.2f}% | 策略净收益率 |")
        lines.append(f"| 超额收益 | {excess_return:.2f}% | 策略收益 - 标的涨跌 |")
        lines.append(f"")
        
        # 风险指标
        lines.append(f"## 风险指标")
        lines.append(f"")
        lines.append(f"| 指标 | 值 | 说明 |")
        lines.append(f"|------|-----|------|")
        
        plr = f"{float(metrics['profit_loss_ratio']):.2f}" if metrics['profit_loss_ratio'] else "N/A"
        sharpe = float(metrics["sharpe_ratio"])
        
        lines.append(f"| 盈亏比 | {plr} | 平均盈利 / 平均亏损 |")
        lines.append(f"| 夏普比率 | {sharpe:.2f} | 风险调整后收益 |")
        lines.append(f"| 最大单笔盈利 | {float(self.results['max_profit']):.2f} USDT | - |")
        lines.append(f"| 最大单笔亏损 | {float(self.results['max_loss']):.2f} USDT | - |")
        lines.append(f"")
        
        if self.results['trades']:
            lines.append(f"## 交易明细")
            lines.append(f"")
            lines.append(f"| 层级 | 入场价 | 出场价 | 类型 | 盈亏 |")
            lines.append(f"|------|--------|--------|------|------|")
            for trade in self.results['trades'][-50:]:
                lines.append(f"| A{trade['level']} | {trade['entry_price']:.2f} | {trade['close_price']:.2f} | {trade['reason']} | {float(trade['profit']):.2f} USDT |")
            if len(self.results['trades']) > 50:
                lines.append(f"| ... | ... | ... | ... | ... |")
                lines.append(f"*共 {len(self.results['trades'])} 笔交易，仅显示最近 50 笔*")
            lines.append(f"")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        logger.info(f"[保存报告] 成功保存到: {filepath}")
        print(f"\n📄 回测报告已保存: {filepath}")
    
    def save_history(self, symbol: str, days: int = None, date_range: str = None):
        """保存回测历史记录
        
        追加记录每次回测的关键指标，方便对比不同回测结果
        
        参数:
            symbol: 交易对
            days: 回测天数（可选）
            date_range: 时间范围字符串（可选，格式: yyyymmdd-yyyymmdd）
        """
        import os
        
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autofish_output")
        os.makedirs(output_dir, exist_ok=True)
        
        filepath = os.path.join(output_dir, f"binance_{symbol}_backtest_history.md")
        
        # 计算指标
        metrics = self.calculate_metrics()
        net_profit = self.results["total_profit"] - self.results["total_loss"]
        roi = float(net_profit) / float(self.config.get('total_amount_quote', 1200)) * 100
        win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
                   if self.results["total_trades"] > 0 else 0)
        
        # 超额收益
        price_change = float(metrics["price_change"])
        excess_return = roi - price_change
        
        # 盈亏比显示
        plr = f"{float(metrics['profit_loss_ratio']):.2f}" if metrics['profit_loss_ratio'] else "N/A"
        sharpe = float(metrics["sharpe_ratio"])
        
        # 检查文件是否存在
        if not os.path.exists(filepath):
            # 创建新文件，写入表头
            header = [
                f"# {symbol} 回测历史记录",
                "",
                "| 回测时间 | 日期范围 | 天数 | 交易次数 | 胜率 | 收益率 | 标的涨跌 | 超额收益 | 盈亏比 | 夏普比率 |",
                "|----------|----------|------|----------|------|--------|----------|----------|--------|----------|",
            ]
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(header) + '\n')
        
        # 追加数据行
        date_range_str = f"{self.start_time.strftime('%Y-%m-%d')} ~ {self.end_time.strftime('%Y-%m-%d')}" if self.start_time and self.end_time else "-"
        
        # 计算天数（根据实际回测时间范围）
        if self.start_time and self.end_time:
            calculated_days = (self.end_time - self.start_time).days + 1
        else:
            calculated_days = days if days else None
        
        days_str = str(calculated_days)
        
        row = (
            f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | {date_range_str} | {days_str} | "
            f"{self.results['total_trades']} | {win_rate:.1f}% | {roi:.2f}% | "
            f"{price_change:.2f}% | {excess_return:.2f}% | {plr} | "
            f"{sharpe:.2f} |"
        )
        
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(row + '\n')
        
        print(f"📊 历史记录已追加: {filepath}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Autofish V2 回测")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期 (默认: 1m)")
    parser.add_argument("--limit", type=int, default=1500, help="K线数量 (默认: 1500)")
    parser.add_argument("--days", type=int, default=None, help="回测天数 (默认: None，使用 limit 参数)")
    parser.add_argument("--date-range", type=str, default=None, help="回测时间范围 (格式: yyyymmdd-yyyymmdd，例如: 20260301-20260310)")
    parser.add_argument("--decay-factor", type=float, default=0.5, help="衰减因子 (默认: 0.5，可选: 0.5/1.0)")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="止损比例 (默认: 0.08)")
    parser.add_argument("--total-amount", type=float, default=10000, help="总投入金额 (默认: 10000)")
    parser.add_argument("--no-auto-fetch", action="store_true", help="禁用自动获取缺失数据（仅使用缓存）")
    
    args = parser.parse_args()
    
    # 解析时间范围（支持多段，用逗号分隔）
    date_ranges = []
    
    if args.date_range:
        # 支持多段时间范围，用逗号分隔
        range_parts = args.date_range.split(",")
        
        for range_str in range_parts:
            range_str = range_str.strip()
            if not range_str:
                continue
            
            try:
                # 支持两种格式: yyyymmdd-yyyymmdd 或 yyyy-mm-dd-yyyy-mm-dd
                if range_str.count("-") == 1:
                    # 格式: yyyymmdd-yyyymmdd
                    parts = range_str.split("-")
                    start_date = datetime.strptime(parts[0], "%Y%m%d")
                    end_date = datetime.strptime(parts[1], "%Y%m%d")
                elif range_str.count("-") == 4:
                    # 格式: yyyy-mm-dd-yyyy-mm-dd
                    parts = range_str.split("-")
                    start_date = datetime.strptime(f"{parts[0]}-{parts[1]}-{parts[2]}", "%Y-%m-%d")
                    end_date = datetime.strptime(f"{parts[3]}-{parts[4]}-{parts[5]}", "%Y-%m-%d")
                else:
                    logger.error(f"[时间范围] 格式错误: {range_str}")
                    continue
                
                start_time = int(start_date.timestamp() * 1000)
                end_time = int(end_date.timestamp() * 1000) + 86400000 - 1  # 结束日期的 23:59:59
                days = (end_date - start_date).days + 1
                date_range_str = f"{days}d_{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"
                
                date_ranges.append({
                    "start_time": start_time,
                    "end_time": end_time,
                    "days": days,
                    "date_range_str": date_range_str,
                    "start_date": start_date,
                    "end_date": end_date,
                })
                
                logger.info(f"[时间范围] {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')} ({days} 天)")
            except ValueError as e:
                logger.error(f"[时间范围] 解析失败: {range_str}, 错误: {e}")
    
    decay_factor = Decimal(str(args.decay_factor))
    
    amplitude_config = Autofish_AmplitudeConfig.load_latest(args.symbol, decay_factor=decay_factor)
    
    if amplitude_config:
        config = {
            "symbol": amplitude_config.get_symbol(),
            "leverage": amplitude_config.get_leverage(),
            "grid_spacing": amplitude_config.get_grid_spacing(),
            "exit_profit": amplitude_config.get_exit_profit(),
            "stop_loss": amplitude_config.get_stop_loss(),
            "total_amount_quote": amplitude_config.get_total_amount_quote(),
            "max_entries": amplitude_config.get_max_entries(),
            "decay_factor": amplitude_config.get_decay_factor(),
            "weights": amplitude_config.get_weights(),
            "valid_amplitudes": amplitude_config.get_valid_amplitudes(),
            "total_expected_return": amplitude_config.get_total_expected_return(),
            "entry_price_strategy": amplitude_config.get_entry_price_strategy(),
        }
        config_file = amplitude_config.config_path
    else:
        config = Autofish_OrderCalculator.get_default_config("binance")
        config["symbol"] = args.symbol
        config["decay_factor"] = decay_factor
        config.update({
            "stop_loss": Decimal(str(args.stop_loss)),
            "total_amount_quote": Decimal(str(args.total_amount)),
        })
        config_file = "无（使用内置默认配置）"
    
    logger.info(f"[配置加载] {'使用振幅分析配置' if amplitude_config else '使用默认配置'}: {args.symbol}")
    logger.info(f"  配置文件: {config_file}")
    logger.info(f"  交易标的: {config.get('symbol')}")
    logger.info(f"  交易杠杆: {config['leverage']}x")
    logger.info(f"  资金投入: {config['total_amount_quote']} USDT")
    logger.info(f"  网格间距: {float(config['grid_spacing'])*100:.1f}%")
    logger.info(f"  止盈比例: {float(config['exit_profit'])*100:.1f}%")
    logger.info(f"  止损比例: {float(config['stop_loss'])*100:.1f}%")
    logger.info(f"  衰减因子: {float(decay_factor)}")
    logger.info(f"  最大层级: {config['max_entries']}")
    logger.info(f"  网格权重: {config.get('weights', [])}")
    
    # 处理回测
    if date_ranges:
        # 多段时间范围
        print(f"\n📊 共 {len(date_ranges)} 个时间段需要回测")
        
        for i, dr in enumerate(date_ranges, 1):
            print(f"\n{'='*60}")
            print(f"📅 第 {i}/{len(date_ranges)} 个时间段: {dr['start_date'].strftime('%Y-%m-%d')} ~ {dr['end_date'].strftime('%Y-%m-%d')} ({dr['days']} 天)")
            print(f"{'='*60}")
            
            # 如果不是第一个时间段，等待一段时间避免 API 限制
            if i > 1:
                print(f"⏳ 等待 30 秒避免 API 限制...")
                await asyncio.sleep(30)
            
            engine = BacktestEngine(config)
            await engine.run(
                symbol=args.symbol, 
                interval=args.interval, 
                limit=args.limit, 
                days=dr['days'], 
                start_time=dr['start_time'], 
                end_time=dr['end_time'],
                auto_fetch=not args.no_auto_fetch
            )
            engine.save_report(args.symbol, dr['days'], dr['date_range_str'])
            engine.save_history(args.symbol, dr['days'], dr['date_range_str'])
    else:
        # 单次回测（使用 --days 或 --limit）
        engine = BacktestEngine(config)
        await engine.run(symbol=args.symbol, interval=args.interval, limit=args.limit, days=args.days, auto_fetch=not args.no_auto_fetch)
        engine.save_report(args.symbol, args.days)
        engine.save_history(args.symbol, args.days)


if __name__ == "__main__":
    asyncio.run(main())

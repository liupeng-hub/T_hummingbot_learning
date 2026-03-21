#!/usr/bin/env python3
"""
行情感知回测模块

将行情分析与回测结合，根据市场状态动态控制交易：
- 震荡行情：正常进行链式挂单交易
- 趋势行情：平仓所有订单，停止交易

运行方式：
    python binance_backtest.py --symbol BTCUSDT --date-range 20200101-20260310
"""

import asyncio
import json
import logging
import os
import argparse
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Dict, Any
import aiohttp
from dotenv import load_dotenv

from autofish_core import (
    Autofish_Order,
    Autofish_ChainState,
    Autofish_WeightCalculator,
    Autofish_OrderCalculator,
    Autofish_AmplitudeConfig,
)
from market_status_detector import (
    MarketStatus,
    MarketStatusDetector,
    RealTimeStatusAlgorithm,
    AlwaysRangingAlgorithm,
    ImprovedStatusAlgorithm,
    DualThrustAlgorithm,
    ADXAlgorithm,
    CompositeAlgorithm,
    StatusAlgorithm,
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
        
        self.a1_timeout_minutes = config.get('a1_timeout_minutes', 10)
        
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
            "first_price": None,
            "last_price": None,
            "trade_returns": [],
            "max_profit": Decimal("0"),
            "max_loss": Decimal("0"),
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
        
        strategy_config = self.config.get("entry_price_strategy", {"name": "fixed"})
        if "strategy" in strategy_config:
            strategy_name = strategy_config.get("strategy", "fixed")
            strategy_params = strategy_config.get(strategy_name, {})
        else:
            strategy_name = strategy_config.get("name", "fixed")
            strategy_params = strategy_config.get("params", {})
        strategy = EntryPriceStrategyFactory.create(strategy_name, **strategy_params)
        
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
    
    def _process_entry(self, low_price: Decimal, current_price: Decimal, kline_time: datetime = None):
        """处理入场"""
        max_level = self.config.get("max_entries", 4)
        
        pending_order = self.chain_state.get_pending_order()
        if pending_order:
            if Autofish_OrderCalculator.check_entry_triggered(low_price, pending_order.entry_price):
                pending_order.set_state("filled", "K线触发入场")
                pending_order.filled_at = kline_time.strftime('%Y-%m-%d %H:%M:%S') if kline_time else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
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
    
    def _process_exit(self, open_price: Decimal, high_price: Decimal, low_price: Decimal, current_price: Decimal, kline_time: datetime = None):
        """处理出场
        
        改进：当 K 线同时触及止盈止损时，根据 K 线形态判断触发顺序
        
        参数:
            open_price: K 线开盘价
            high_price: K 线最高价
            low_price: K 线最低价
            current_price: 当前价格（收盘价）
            kline_time: K 线时间
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
                    self._close_order(order, "take_profit", order.take_profit_price, leverage, kline_time)
                else:
                    self._close_order(order, "stop_loss", order.stop_loss_price, leverage, kline_time)
                
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[{'止盈' if exit_type == 'take_profit' else '止损'}后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break
                
            elif tp_triggered:
                self._close_order(order, "take_profit", order.take_profit_price, leverage, kline_time)
                self.chain_state.cancel_pending_orders()
                new_order = self._create_order(order.level, current_price)
                self.chain_state.orders.append(new_order)
                logger.info(f"[止盈后重建] 创建 A{new_order.level}: 入场价={new_order.entry_price:.2f}")
                break
                
            elif sl_triggered:
                self._close_order(order, "stop_loss", order.stop_loss_price, leverage, kline_time)
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
    
    def _close_order(self, order: Autofish_Order, reason: str, close_price: Decimal, leverage: Decimal, kline_time: datetime = None):
        """平仓"""
        order.set_state("closed", reason)
        order.close_price = close_price
        order.profit = Autofish_OrderCalculator(leverage=leverage).calculate_profit(order, close_price)
        order.closed_at = kline_time.strftime('%Y-%m-%d %H:%M:%S') if kline_time else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if order.stake_amount and order.stake_amount > 0:
            trade_return = order.profit / order.stake_amount
            self.results["trade_returns"].append(trade_return)
        
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
            "exit_price": float(close_price),
            "entry_time": order.filled_at,
            "exit_time": order.closed_at,
            "profit": float(order.profit),
            "reason": reason,
            "trade_type": "take_profit" if reason == "take_profit" else "stop_loss",
            "quantity": float(order.quantity) if order.quantity else 0,
            "stake": float(order.stake_amount) if order.stake_amount else 0,
        })
        
        self._update_capital_after_trade(order.profit, kline_time)
    
    def _update_capital_after_trade(self, profit: Decimal, kline_time: datetime = None) -> None:
        """交易后更新资金池
        
        Args:
            profit: 本次交易盈亏
            kline_time: K线时间
        """
        if self.capital_pool.strategy == 'guding':
            return
        
        result = self.capital_pool.process_trade_profit(profit, kline_time)
        
        if result.get('withdrawal'):
            logger.info(f"[资金池] 触发提现: 提现金额={result.get('withdrawal_amount', 0):.2f}, "
                       f"保留资金={result.get('retained_capital', 0):.2f}")
        
        if result.get('liquidation'):
            logger.warning(f"[资金池] 触发爆仓恢复: 恢复资金={result.get('recovered_capital', 0):.2f}")
    
    def _on_kline(self, kline: dict):
        """处理 K 线数据"""
        self.kline_count += 1
        
        open_price = Decimal(str(kline.get("open", kline.get("o", 0))))
        high_price = Decimal(str(kline.get("high", kline.get("h", 0))))
        low_price = Decimal(str(kline.get("low", kline.get("l", 0))))
        close_price = Decimal(str(kline.get("close", kline.get("c", 0))))
        volume = Decimal(str(kline.get("volume", kline.get("v", 0))))
        timestamp = kline.get("timestamp", kline.get("t", 0))
        
        kline_time = datetime.fromtimestamp(timestamp / 1000) if timestamp else datetime.now()
        
        if self.kline_count % 100 == 0:
            logger.debug(f"[K线 #{self.kline_count}] {kline_time.strftime('%Y-%m-%d %H:%M')} "
                        f"O={open_price:.2f} H={high_price:.2f} L={low_price:.2f} C={close_price:.2f}")
        
        self._check_first_entry_timeout(close_price, kline_time)
        
        self._process_entry(low_price, close_price, kline_time)
        self._process_exit(open_price, high_price, low_price, close_price, kline_time)
    
    def _check_first_entry_timeout(self, current_price: Decimal, current_time: datetime) -> None:
        """检查第一笔入场订单是否超时（回测版本）
        
        参数:
            current_price: 当前价格
            current_time: 当前 K 线时间
        """
        if self.a1_timeout_minutes <= 0:
            return
        
        if not self.chain_state:
            return
        
        timeout_first_entry = self.chain_state.check_first_entry_timeout(current_time, self.a1_timeout_minutes)
        if not timeout_first_entry:
            return
        
        logger.info(f"[A1 超时] A1 挂单已超过 {self.a1_timeout_minutes} 分钟未成交")
        print(f"\n[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ⏰ A1 超时重挂")
        print(f"   触发原因: A1 挂单超过 {self.a1_timeout_minutes} 分钟未成交")
        print(f"   当前价格: {float(current_price):.2f}")
        print(f"   原订单入场价: {float(timeout_first_entry.entry_price):.2f}")
        print(f"   原订单创建时间: {timeout_first_entry.created_at}")
        
        self.chain_state.orders.remove(timeout_first_entry)
        
        new_first_entry = self._create_order(1, current_price, self.klines_history)
        self.chain_state.orders.append(new_first_entry)
        self.chain_state.base_price = current_price
        
        price_diff = abs(float(new_first_entry.entry_price) - float(timeout_first_entry.entry_price))
        price_diff_pct = price_diff / float(timeout_first_entry.entry_price) * 100 if float(timeout_first_entry.entry_price) > 0 else 0
        
        logger.info(f"[新 A1] 入场价={new_first_entry.entry_price:.2f}")
        print(f"   新 A1 入场价: {float(new_first_entry.entry_price):.2f}")
        print(f"   价格调整: {price_diff:.2f} ({price_diff_pct:.2f}%)")
    
    async def run(self, symbol: str = "BTCUSDT", interval: str = "1m", start_time: int = None, end_time: int = None):
        """运行回测
        
        主要流程：
        1. 获取历史 K 线数据
        2. 遍历每根 K 线，模拟订单执行
        3. 统计盈亏结果
        4. 生成回测报告
        
        参数:
            symbol: 交易对
            interval: K线周期
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
        """
        self.interval = interval
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
        print(f"  网格间距: {float(self.config.get('grid_spacing', Decimal('0.01')))*100}%")
        print(f"  止盈: {float(self.config.get('exit_profit', Decimal('0.01')))*100}%")
        print(f"  止损: {float(self.config.get('stop_loss', Decimal('0.08')))*100}%")
        print(f"  杠杆: {self.config.get('leverage', 10)}x")
        print(f"  总资金: {self.config.get('total_amount_quote', 1200)} USDT")
        print(f"  最大层级: {self.config.get('max_entries', 4)}")
        
        from binance_kline_fetcher import KlineFetcher
        fetcher = KlineFetcher()
        klines = await fetcher.fetch_kline(symbol, interval, start_time, end_time)
        
        if not klines:
            logger.error("获取 K 线数据失败")
            return
        
        self.start_time = datetime.fromtimestamp(klines[0]["timestamp"] / 1000)
        self.end_time = datetime.fromtimestamp(klines[-1]["timestamp"] / 1000)
        
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
        if self.results["first_price"] and self.results["last_price"]:
            price_change = (self.results["last_price"] - self.results["first_price"]) / self.results["first_price"] * 100
        else:
            price_change = Decimal("0")
        
        if self.results["loss_trades"] > 0 and self.results["win_trades"] > 0:
            avg_profit = self.results["total_profit"] / self.results["win_trades"]
            avg_loss = self.results["total_loss"] / self.results["loss_trades"]
            profit_loss_ratio = avg_profit / avg_loss
        else:
            profit_loss_ratio = None
        
        if len(self.results["trade_returns"]) >= 2:
            returns = [float(r) for r in self.results["trade_returns"]]
            avg_return = sum(returns) / len(returns)
            variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
            std_dev = variance ** 0.5
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
    
    def get_closed_orders(self) -> List[Dict]:
        """获取已平仓订单"""
        return self.closed_orders


@dataclass
class MarketStatusEvent:
    """行情状态事件"""
    timestamp: int
    time: datetime
    status: MarketStatus
    confidence: float
    reason: str
    action: str
    price: Decimal
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp,
            'time': self.time.strftime('%Y-%m-%d %H:%M'),
            'status': self.status.value,
            'confidence': self.confidence,
            'reason': self.reason,
            'action': self.action,
            'price': float(self.price),
        }


@dataclass
class TradingPeriod:
    """交易时段"""
    start_time: datetime
    end_time: datetime
    status: MarketStatus
    trades: int = 0
    profit: Decimal = Decimal("0")
    
    def to_dict(self) -> Dict:
        return {
            'start_time': self.start_time.strftime('%Y-%m-%d %H:%M'),
            'end_time': self.end_time.strftime('%Y-%m-%d %H:%M'),
            'status': self.status.value,
            'trades': self.trades,
            'profit': float(self.profit),
        }


class MarketAwareBacktestEngine(BacktestEngine):
    """行情感知回测引擎
    
    继承自 BacktestEngine，添加行情感知能力：
    - 震荡行情：正常交易
    - 趋势行情：平仓停止
    
    Attributes:
        market: 行情算法配置
        market_detector: 行情判断器
        trading_enabled: 是否允许交易
        current_market_status: 当前行情状态
        market_status_events: 行情状态变化事件列表
        daily_klines_cache: 1d K线缓存
    """
    
    ALGORITHMS = {
        'realtime': RealTimeStatusAlgorithm,
        'always_ranging': AlwaysRangingAlgorithm,
        'improved': ImprovedStatusAlgorithm,
        'dual_thrust': DualThrustAlgorithm,
        'adx': ADXAlgorithm,
        'composite': CompositeAlgorithm,
    }
    
    def __init__(
        self,
        amplitude: Dict,
        market: Dict,
        entry: Dict,
        timeout: Dict,
        capital: Dict = None,
    ):
        config = amplitude.copy()
        config['a1_timeout_minutes'] = timeout.get('a1_timeout_minutes', 0)
        
        if entry:
            config['entry_price_strategy'] = entry
        
        super().__init__(config)
        
        self.market = market or {}
        self.trading_statuses = market.get('trading_statuses', ['ranging']) if market else ['ranging']
        
        algorithm = self._create_algorithm()
        self.market_detector = MarketStatusDetector(algorithm=algorithm)
        
        self.trading_enabled = True
        self.current_market_status = MarketStatus.UNKNOWN
        self.market_status_events: List[MarketStatusEvent] = []
        self.trading_periods: List[TradingPeriod] = []
        self._current_trading_period: Optional[TradingPeriod] = None
        
        self.daily_klines_cache: List[Dict] = []
        self._last_check_date: Optional[date] = None
        
        self.results['market_status_events'] = []
        self.results['trading_periods'] = []
        self.results['total_trading_minutes'] = 0
        self.results['total_stopped_minutes'] = 0
        self.results['market_statistics'] = {}
        
        self.total_amount_quote = Decimal(str(amplitude.get('total_amount_quote', 10000)))
        self.initial_capital = self.total_amount_quote
        self.stop_loss = float(amplitude.get('stop_loss', 0.08))
        self.leverage = int(amplitude.get('leverage', 10))
        
        from autofish_core import CapitalPoolFactory
        self.capital_pool = CapitalPoolFactory.create(
            self.initial_capital,
            capital or {'strategy': 'guding'},
            self.stop_loss,
            self.leverage
        )
        self.capital_strategy = self.capital_pool.strategy
        
    def _create_algorithm(self) -> StatusAlgorithm:
        """创建行情判断算法"""
        algo_name = self.market.get('algorithm', 'always_ranging')
        algo_params = self.market.get(algo_name, {})
        
        algo_class = self.ALGORITHMS.get(algo_name)
        if algo_class:
            return algo_class(algo_params if algo_params else None)
        
        logger.warning(f"未找到算法 {algo_name}，使用默认 AlwaysRangingAlgorithm")
        return AlwaysRangingAlgorithm()
    
    async def _fetch_multi_interval_klines(
        self, 
        symbol: str, 
        interval: str, 
        start_time: int = None, 
        end_time: int = None
    ) -> tuple:
        """获取多周期 K线数据
        
        返回:
            (1m_klines, 1d_klines)
        """
        from binance_kline_fetcher import KlineFetcher
        
        fetcher = KlineFetcher()
        
        klines_1m = await fetcher.fetch_kline(symbol, interval, start_time, end_time)
        
        if not klines_1m:
            logger.error("获取 1m K线数据失败")
            return [], []
        
        market_interval = self.market.get('interval', '1d')
        market_start = start_time - (self.market.get('min_market_klines', 20) * 86400000)
        
        klines_1d = await fetcher.fetch_kline(symbol, market_interval, market_start, end_time)
        
        if not klines_1d:
            logger.warning("获取 1d K线数据失败，将使用 1m K线聚合")
        
        logger.info(f"[多周期数据] 1m K线: {len(klines_1m)} 条, 1d K线: {len(klines_1d) if klines_1d else 0} 条")
        
        return klines_1m, klines_1d
    
    def _check_market_status(self, kline_1m: dict) -> MarketStatus:
        """检查行情状态
        
        每天第一根 1m K线时更新行情判断
        """
        current_ts = kline_1m['timestamp']
        current_date = datetime.fromtimestamp(current_ts / 1000).date()
        
        if self._last_check_date == current_date:
            return self.current_market_status
        
        self._last_check_date = current_date
        
        market_klines = self._get_market_klines_before(current_ts)
        
        min_klines = self.market.get('min_market_klines', 20)
        if len(market_klines) < min_klines:
            logger.warning(f"[行情判断] K线数据不足: {len(market_klines)} < {min_klines}")
            return self.current_market_status
        
        result = self.market_detector.algorithm.calculate(market_klines, self.market)
        
        logger.info(f"[行情判断] {current_date}: {result.status.value}, 置信度={result.confidence:.2f}, 原因={result.reason}")
        
        return result.status
    
    def _get_market_klines_before(self, timestamp: int) -> List[Dict]:
        """获取指定时间之前的 1d K线"""
        return [k for k in self.daily_klines_cache if k['timestamp'] < timestamp]
    
    def _on_market_status_change(
        self, 
        old_status: MarketStatus, 
        new_status: MarketStatus, 
        kline: dict,
        confidence: float = 0.0,
        reason: str = ''
    ):
        """处理行情状态变化"""
        price = Decimal(str(kline['close']))
        timestamp = kline['timestamp']
        time = datetime.fromtimestamp(timestamp / 1000)
        
        is_trending = new_status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]
        was_trending = old_status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]
        
        is_trading_status = new_status in [MarketStatus.RANGING, MarketStatus.TRENDING_UP]
        was_trading_status = old_status in [MarketStatus.RANGING, MarketStatus.TRENDING_UP]
        
        action = 'continue'
        
        if new_status == MarketStatus.TRENDING_DOWN and not old_status == MarketStatus.TRENDING_DOWN:
            if self.trading_enabled:
                self._close_all_positions(price, timestamp, 'market_status_change', time)
                self.trading_enabled = False
                action = 'stop_trading'
                self._end_trading_period(time)
                logger.info(f"[行情变化] {old_status.value} -> {new_status.value}, 停止交易")
        
        elif is_trading_status and not was_trading_status:
            if not self.trading_enabled:
                self.trading_enabled = True
                self._create_first_order(price, kline)
                action = 'start_trading'
                self._start_trading_period(time, new_status)
                logger.info(f"[行情变化] {old_status.value} -> {new_status.value}, 开始交易")
        
        event = MarketStatusEvent(
            timestamp=timestamp,
            time=time,
            status=new_status,
            confidence=confidence,
            reason=reason,
            action=action,
            price=price
        )
        self.market_status_events.append(event)
        self.results['market_status_events'].append(event.to_dict())
        
        self.current_market_status = new_status
    
    def _close_all_positions(self, price: Decimal, timestamp: int, reason: str, kline_time: datetime = None):
        """平仓所有已成交订单"""
        if not self.chain_state:
            return
        
        filled_orders = self.chain_state.get_filled_orders()
        leverage = self.config.get("leverage", Decimal("10"))
        
        for order in filled_orders:
            if order.state != "filled":
                continue
            
            order.set_state("closed", f"market_status_{reason}")
            order.close_price = price
            order.profit = self._calculate_profit(order, price, leverage)
            order.closed_at = kline_time.strftime('%Y-%m-%d %H:%M:%S') if kline_time else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            if order.stake_amount and order.stake_amount > 0:
                trade_return = order.profit / order.stake_amount
                self.results["trade_returns"].append(trade_return)
            
            if order.profit > self.results.get("max_profit", Decimal("0")):
                self.results["max_profit"] = order.profit
            if order.profit < self.results.get("max_loss", Decimal("0")):
                self.results["max_loss"] = order.profit
            
            if order.profit > 0:
                self.results["win_trades"] += 1
                self.results["total_profit"] += order.profit
                logger.info(f"[强制平仓-止盈] A{order.level}: 出场价={price:.2f}, 盈利={order.profit:.2f} USDT")
            else:
                self.results["loss_trades"] += 1
                self.results["total_loss"] += abs(order.profit)
                logger.info(f"[强制平仓-止损] A{order.level}: 出场价={price:.2f}, 亏损={order.profit:.2f} USDT")
            
            self.results["total_trades"] += 1
            self.results["trades"].append({
                "level": order.level,
                "entry_price": float(order.entry_price),
                "exit_price": float(price),
                "entry_time": order.filled_at,
                "exit_time": order.closed_at,
                "profit": float(order.profit),
                "reason": f"market_{reason}",
                "trade_type": "take_profit" if order.profit >= 0 else "stop_loss",
                "quantity": float(order.quantity) if order.quantity else 0,
                "stake": float(order.stake_amount) if order.stake_amount else 0,
            })
        
        self.chain_state.cancel_pending_orders()
        self.chain_state.orders = []
    
    def _calculate_profit(self, order: Autofish_Order, close_price: Decimal, leverage: Decimal) -> Decimal:
        """计算盈亏"""
        price_diff = close_price - order.entry_price
        profit = price_diff * order.quantity * leverage
        return profit
    
    def _create_first_order(self, price: Decimal, kline: dict = None):
        """创建首个订单"""
        from autofish_core import Autofish_ChainState
        
        if not self.chain_state:
            self.chain_state = Autofish_ChainState(base_price=price)
        
        klines = self.klines_history if hasattr(self, 'klines_history') and self.klines_history else None
        first_order = self._create_order(1, price, klines)
        self.chain_state.orders.append(first_order)
        logger.info(f"[开始交易] 创建 A1: 入场价={first_order.entry_price:.2f}")
    
    def _start_trading_period(self, time: datetime, status: MarketStatus):
        """开始交易时段"""
        self._current_trading_period = TradingPeriod(
            start_time=time,
            end_time=time,
            status=status
        )
    
    def _end_trading_period(self, time: datetime):
        """结束交易时段"""
        if self._current_trading_period:
            self._current_trading_period.end_time = time
            self.trading_periods.append(self._current_trading_period)
            self._current_trading_period = None
    
    def _on_kline(self, kline: dict):
        """处理 K线数据（重写）"""
        self.kline_count += 1
        
        open_price = Decimal(str(kline.get("open", kline.get("o", 0))))
        high_price = Decimal(str(kline.get("high", kline.get("h", 0))))
        low_price = Decimal(str(kline.get("low", kline.get("l", 0))))
        close_price = Decimal(str(kline.get("close", kline.get("c", 0))))
        timestamp = kline.get("timestamp", kline.get("t", 0))
        
        kline_time = datetime.fromtimestamp(timestamp / 1000) if timestamp else datetime.now()
        
        if self.kline_count % 100 == 0:
            logger.debug(f"[K线 #{self.kline_count}] {kline_time.strftime('%Y-%m-%d %H:%M')} "
                        f"O={open_price:.2f} H={high_price:.2f} L={low_price:.2f} C={close_price:.2f}")
        
        new_status = self._check_market_status(kline)
        
        if new_status != self.current_market_status:
            self._on_market_status_change(
                self.current_market_status, 
                new_status, 
                kline,
                confidence=0.0,
                reason=''
            )
        
        if self._current_trading_period:
            self._current_trading_period.end_time = kline_time
        
        if not self.trading_enabled:
            return
        
        self._check_first_entry_timeout(close_price, kline_time)
        
        self._process_entry(low_price, close_price)
        self._process_exit(open_price, high_price, low_price, close_price, kline_time)
    
    async def run(
        self, 
        symbol: str = "BTCUSDT", 
        interval: str = "1m", 
        start_time: int = None, 
        end_time: int = None
    ):
        """运行行情感知回测"""
        self.interval = interval
        
        logger.info("=" * 60)
        logger.info("行情感知回测开始")
        logger.info("=" * 60)
        logger.info(f"配置: {self.config}")
        logger.info(f"行情配置: {self.market}")
        
        print("=" * 60)
        print("行情感知回测")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol}")
        print(f"  K线周期: {interval}")
        print(f"  行情判断周期: {self.market.get('interval', '1d')}")
        print(f"  行情判断算法: {self.market.get('algorithm', 'realtime')}")
        if start_time and end_time:
            start_dt = datetime.fromtimestamp(start_time / 1000)
            end_dt = datetime.fromtimestamp(end_time / 1000)
            print(f"  时间范围: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")
        
        klines_1m, klines_1d = await self._fetch_multi_interval_klines(
            symbol, interval, start_time, end_time
        )
        
        if not klines_1m:
            logger.error("获取 K线数据失败")
            return
        
        self.daily_klines_cache = klines_1d
        
        self.start_time = datetime.fromtimestamp(klines_1m[0]["timestamp"] / 1000)
        self.end_time = datetime.fromtimestamp(klines_1m[-1]["timestamp"] / 1000)
        
        self.results["first_price"] = Decimal(klines_1m[0]["open"])
        self.results["last_price"] = Decimal(klines_1m[-1]["close"])
        
        print(f"\n📊 回测时间范围:")
        print(f"  开始: {self.start_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  结束: {self.end_time.strftime('%Y-%m-%d %H:%M')}")
        print(f"  1m K线数: {len(klines_1m)}")
        print(f"  1d K线数: {len(klines_1d)}")
        
        first_price = Decimal(klines_1m[0]["open"])
        from autofish_core import Autofish_ChainState
        self.chain_state = Autofish_ChainState(base_price=first_price)
        
        self.klines_history = klines_1m[:30] if len(klines_1m) >= 30 else klines_1m
        
        required_periods = self.market_detector.algorithm.get_required_periods()
        min_klines = max(required_periods, self.market.get('min_market_klines', 20))
        
        if len(klines_1d) >= min_klines:
            initial_result = self.market_detector.algorithm.calculate(
                klines_1d[:min_klines],
                self.market
            )
            self.current_market_status = initial_result.status
            logger.info(f"[初始行情] {initial_result.status.value}, 原因={initial_result.reason}")
            
            if self.current_market_status == MarketStatus.TRENDING_DOWN:
                self.trading_enabled = False
                print(f"\n⚠️ 初始行情为下跌趋势，暂停交易")
            else:
                first_order = self._create_order(1, first_price, self.klines_history)
                self.chain_state.orders.append(first_order)
                print(f"\n📋 创建首个订单: A1 入场价={first_order.entry_price:.2f}")
                self._start_trading_period(self.start_time, self.current_market_status)
        else:
            first_order = self._create_order(1, first_price, self.klines_history)
            self.chain_state.orders.append(first_order)
            print(f"\n📋 创建首个订单: A1 入场价={first_order.entry_price:.2f}")
            self._start_trading_period(self.start_time, MarketStatus.RANGING)
        
        print(f"\n⏳ 开始回测...")
        
        for kline in klines_1m:
            self._on_kline(kline)
        
        if self._current_trading_period:
            self._current_trading_period.end_time = self.end_time
            self.trading_periods.append(self._current_trading_period)
        
        self._calculate_market_statistics()
        self._print_summary()
    
    def _calculate_market_statistics(self):
        """计算行情统计"""
        total_minutes = (self.end_time - self.start_time).total_seconds() / 60
        
        trading_minutes = 0
        stopped_minutes = 0
        
        for period in self.trading_periods:
            duration = (period.end_time - period.start_time).total_seconds() / 60
            if period.status == MarketStatus.RANGING:
                trading_minutes += duration
            else:
                stopped_minutes += duration
        
        self.results['total_trading_minutes'] = int(trading_minutes)
        self.results['total_stopped_minutes'] = int(stopped_minutes)
        
        self.results['trading_periods'] = [p.to_dict() for p in self.trading_periods]
        
        ranging_count = sum(1 for e in self.market_status_events if e.status == MarketStatus.RANGING)
        trending_count = sum(1 for e in self.market_status_events if e.status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN])
        
        self.results['market_statistics'] = {
            'total_events': len(self.market_status_events),
            'ranging_events': ranging_count,
            'trending_events': trending_count,
            'trading_minutes': int(trading_minutes),
            'stopped_minutes': int(stopped_minutes),
            'trading_pct': trading_minutes / total_minutes * 100 if total_minutes > 0 else 0,
            'stopped_pct': stopped_minutes / total_minutes * 100 if total_minutes > 0 else 0,
        }
    
    def _print_summary(self):
        """打印回测结果"""
        net_profit = self.results["total_profit"] - self.results["total_loss"]
        win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
                   if self.results["total_trades"] > 0 else 0)
        
        market_stats = self.results.get('market_statistics', {})
        
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
        
        print("\n📈 行情统计:")
        print(f"  行情状态变化: {market_stats.get('total_events', 0)} 次")
        print(f"  交易时间占比: {market_stats.get('trading_pct', 0):.1f}%")
        print(f"  停止时间占比: {market_stats.get('stopped_pct', 0):.1f}%")
        
        print("=" * 60)
        
        logger.info("=" * 60)
        logger.info("回测结果")
        logger.info("=" * 60)
        logger.info(f"  总交易: {self.results['total_trades']}")
        logger.info(f"  胜率: {win_rate:.2f}%")
        logger.info(f"  净收益: {net_profit:.2f} USDT")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="行情感知回测")
    parser.add_argument("--symbol", type=str, required=True, help="交易对（必选）")
    parser.add_argument("--date-range", type=str, required=True, help="时间范围 (yyyymmdd-yyyymmdd)（必选）")
    parser.add_argument("--case-id", type=str, default=None, help="测试用例ID")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期（默认: 1m）")
    parser.add_argument("--amplitude-params", type=str, default=None, help="振幅参数（JSON字符串）")
    parser.add_argument("--market-params", type=str, default=None, help="行情算法参数（JSON字符串，格式: {\"algorithm\": \"dual_thrust\", \"dual_thrust\": {...}, \"trading_statuses\": [\"ranging\"]}）")
    parser.add_argument("--entry-params", type=str, default=None, help="入场价格策略参数（JSON字符串，格式: {\"strategy\": \"atr\", \"atr\": {...}}）")
    parser.add_argument("--timeout-params", type=str, default=None, help="超时参数（JSON字符串）")
    parser.add_argument("--capital-params", type=str, default=None, help="资金池参数（JSON字符串，格式: {\"mode\": \"progressive\", \"initial_capital\": 10000, \"strategy\": \"conservative\"}）")
    
    args = parser.parse_args()
    
    amplitude = json.loads(args.amplitude_params) if args.amplitude_params else {}
    market = json.loads(args.market_params) if args.market_params else {"algorithm": "always_ranging"}
    entry = json.loads(args.entry_params) if args.entry_params else {}
    timeout = json.loads(args.timeout_params) if args.timeout_params else {"a1_timeout_minutes": 0}
    capital = json.loads(args.capital_params) if args.capital_params else {"strategy": "guding"}
    
    logger.info(f"[参数] symbol={args.symbol}")
    logger.info(f"[参数] date_range={args.date_range}")
    logger.info(f"[参数] amplitude={amplitude}")
    logger.info(f"[参数] market={market}")
    logger.info(f"[参数] entry={entry}")
    logger.info(f"[参数] timeout={timeout}")
    logger.info(f"[参数] capital={capital}")
    
    date_ranges = []
    
    if args.date_range:
        range_parts = args.date_range.split(",")
        
        for range_str in range_parts:
            range_str = range_str.strip()
            if not range_str:
                continue
            
            try:
                if range_str.count("-") == 1:
                    parts = range_str.split("-")
                    start_date = datetime.strptime(parts[0], "%Y%m%d")
                    end_date = datetime.strptime(parts[1], "%Y%m%d")
                else:
                    logger.error(f"[时间范围] 格式错误: {range_str}")
                    continue
                
                start_time = int(start_date.timestamp() * 1000)
                end_time = int(end_date.timestamp() * 1000) + 86400000 - 1
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
            except ValueError as e:
                logger.error(f"[时间范围] 解析失败: {range_str}, 错误: {e}")
    
    decay_factor = Decimal(str(amplitude.get("decay_factor", 0.5))) if amplitude else Decimal("0.5")
    
    def ensure_decimal(value, default="0"):
        """确保值为 Decimal 类型"""
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    
    if not amplitude:
        from autofish_core import Autofish_AmplitudeConfig
        amplitude_config = Autofish_AmplitudeConfig.load_latest(args.symbol, decay_factor=decay_factor)
        if amplitude_config:
            amplitude = {
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
            }
    else:
        amplitude["grid_spacing"] = ensure_decimal(amplitude.get("grid_spacing"), "0.01")
        amplitude["exit_profit"] = ensure_decimal(amplitude.get("exit_profit"), "0.01")
        amplitude["stop_loss"] = ensure_decimal(amplitude.get("stop_loss"), "0.08")
        amplitude["total_amount_quote"] = ensure_decimal(amplitude.get("total_amount_quote"), "10000")
        amplitude["decay_factor"] = ensure_decimal(amplitude.get("decay_factor"), "0.5")
    
    print(f"\n📊 共 {len(date_ranges)} 个时间段需要回测")
    
    for i, dr in enumerate(date_ranges, 1):
        print(f"\n{'='*60}")
        print(f"📅 第 {i}/{len(date_ranges)} 个时间段: {dr['start_date'].strftime('%Y-%m-%d')} ~ {dr['end_date'].strftime('%Y-%m-%d')} ({dr['days']} 天)")
        print(f"{'='*60}")
        
        engine = MarketAwareBacktestEngine(amplitude, market, entry, timeout, capital)
        await engine.run(
            symbol=args.symbol, 
            interval=args.interval, 
            start_time=dr['start_time'], 
            end_time=dr['end_time']
        )
        
        _save_to_database(args, engine, dr['date_range_str'], amplitude, market, entry, timeout, capital)


def _save_to_database(args, engine, date_range_str, amplitude, market, entry, timeout, capital):
    """保存行情感知回测结果到数据库"""
    try:
        from database.test_results_db import TestResultsDB, TestResult
        from datetime import datetime
        import uuid
        
        db = TestResultsDB()
        
        result_id = f"cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        case_id = args.case_id if args.case_id else result_id
        
        params = {
            "symbol": args.symbol,
            "date_range": args.date_range,
            "amplitude": amplitude,
            "market": market,
            "entry": entry,
            "timeout": timeout,
            "capital": capital,
        }
        
        results = engine.results
        market_stats = results.get('market_statistics', {})
        
        total_trades = results.get('total_trades', 0)
        win_trades = results.get('win_trades', 0)
        loss_trades = results.get('loss_trades', 0)
        total_profit = float(results.get('total_profit', 0))
        total_loss = float(results.get('total_loss', 0))
        net_profit = total_profit - total_loss
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
        
        total_amount = float(engine.config.get('total_amount_quote', 1200))
        roi = (net_profit / total_amount * 100) if total_amount > 0 else 0
        
        first_price = float(results.get('first_price', 0))
        last_price = float(results.get('last_price', 0))
        price_change = ((last_price - first_price) / first_price * 100) if first_price > 0 else 0
        excess_return = roi - price_change
        
        capital_stats = engine.capital_pool.get_statistics() if engine.capital_pool and hasattr(engine.capital_pool, 'get_statistics') else {}
        
        result = TestResult(
            result_id=result_id,
            case_id=case_id,
            symbol=args.symbol,
            interval="1m",
            start_time=engine.start_time.strftime('%Y-%m-%d %H:%M') if engine.start_time else '',
            end_time=engine.end_time.strftime('%Y-%m-%d %H:%M') if engine.end_time else '',
            klines_count=engine.kline_count,
            total_trades=total_trades,
            win_trades=win_trades,
            loss_trades=loss_trades,
            win_rate=win_rate,
            total_profit=total_profit,
            total_loss=total_loss,
            net_profit=net_profit,
            roi=roi,
            price_change=price_change,
            excess_return=excess_return,
            profit_factor=0,
            sharpe_ratio=0,
            max_profit_trade=float(results.get('max_profit', 0)),
            max_loss_trade=float(results.get('max_loss', 0)),
            trading_time_ratio=market_stats.get('trading_pct', 0),
            stopped_time_ratio=market_stats.get('stopped_pct', 0),
            market_status_changes=market_stats.get('total_events', 0),
            market_algorithm=market.get('algorithm', 'always_ranging'),
            capital=json.dumps(capital),
        )
        db.save_result(result)
        
        if capital_stats:
            statistics_id = db.save_capital_statistics(result_id, capital_stats)
            if statistics_id and capital_stats.get('capital_history'):
                db.save_capital_history(result_id, statistics_id, capital_stats['capital_history'])
                print(f"   资金统计已保存: {len(capital_stats.get('capital_history', []))} 条历史记录")
        
        trades = results.get('trades', [])
        if trades:
            trade_details = []
            for i, t in enumerate(trades):
                from database.test_results_db import TradeDetail
                trade_details.append(TradeDetail(
                    result_id=result_id,
                    trade_seq=i + 1,
                    level=str(t.get('level', '')),
                    entry_price=float(t.get('entry_price', 0)),
                    exit_price=float(t.get('exit_price', 0)),
                    entry_time=t.get('entry_time', ''),
                    exit_time=t.get('exit_time', ''),
                    trade_type=t.get('trade_type', ''),
                    profit=float(t.get('profit', 0)),
                    quantity=float(t.get('quantity', 0)),
                    stake=float(t.get('stake', 0)),
                ))
            db.save_trade_details(result_id, trade_details)
            print(f"   交易详情已保存: {len(trade_details)} 条")
        
        print(f"\n✅ 结果已保存到数据库: result_id={result_id}, case_id={case_id}")
    except Exception as e:
        print(f"\n⚠️ 保存到数据库失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())

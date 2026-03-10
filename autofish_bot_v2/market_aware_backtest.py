#!/usr/bin/env python3
"""
行情感知回测模块

将行情分析与回测结合，根据市场状态动态控制交易：
- 震荡行情：正常进行链式挂单交易
- 趋势行情：平仓所有订单，停止交易

运行方式：
    python market_aware_backtest.py --symbol BTCUSDT --days 30 --market-aware
"""

import asyncio
import logging
import os
import argparse
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Dict, Any

from binance_backtest import BacktestEngine
from market_status_detector import (
    MarketStatus,
    MarketStatusDetector,
    RealTimeStatusAlgorithm,
    StatusAlgorithm,
)
from autofish_core import Autofish_Order

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "market_aware_backtest.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


MARKET_STATUS_CONFIG = {
    'market_interval': '1d',
    'algorithm': 'realtime',
    'min_market_klines': 20,
    'confirm_periods': 2,
    'close_on_trending': True,
    'trending_close_method': 'market',
}


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
        market_config: 行情配置
        market_detector: 行情判断器
        trading_enabled: 是否允许交易
        current_market_status: 当前行情状态
        market_status_events: 行情状态变化事件列表
        daily_klines_cache: 1d K线缓存
    """
    
    def __init__(self, config: dict, market_config: dict = None):
        super().__init__(config)
        
        self.market_config = market_config or MARKET_STATUS_CONFIG.copy()
        
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
        
    def _create_algorithm(self) -> StatusAlgorithm:
        """创建行情判断算法"""
        algo_name = self.market_config.get('algorithm', 'realtime')
        
        if algo_name == 'realtime':
            return RealTimeStatusAlgorithm({
                'lookback_period': 20,
                'breakout_threshold': 0.02,
                'consecutive_bars': 3,
                'atr_period': 14,
                'expansion_threshold': 1.5,
                'contraction_threshold': 0.7,
                'confirm_periods': self.market_config.get('confirm_periods', 2),
            })
        else:
            from market_status_detector import ADXAlgorithm, CompositeAlgorithm
            if algo_name == 'adx':
                return ADXAlgorithm()
            else:
                return CompositeAlgorithm()
    
    async def _fetch_multi_interval_klines(
        self, 
        symbol: str, 
        interval: str, 
        limit: int = 1000,
        days: int = None,
        start_time: int = None, 
        end_time: int = None,
        auto_fetch: bool = True
    ) -> tuple:
        """获取多周期 K线数据
        
        返回:
            (1m_klines, 1d_klines)
        """
        from binance_kline_fetcher import KlineFetcher
        
        fetcher = KlineFetcher()
        
        success = await fetcher.ensure_klines(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            days=days,
            auto_fetch=auto_fetch
        )
        
        if not success:
            logger.error("获取 1m K线数据失败")
            return [], []
        
        actual_start, actual_end = fetcher.get_time_range()
        klines_1m = fetcher.query_cache(symbol, interval, actual_start, actual_end)
        
        market_interval = self.market_config.get('market_interval', '1d')
        
        market_start = actual_start - (self.market_config.get('min_market_klines', 20) * 86400000)
        
        success = await fetcher.ensure_klines(
            symbol=symbol,
            interval=market_interval,
            start_time=market_start,
            end_time=actual_end,
            auto_fetch=auto_fetch
        )
        
        if success:
            klines_1d = fetcher.query_cache(symbol, market_interval, market_start, actual_end)
        else:
            logger.warning("获取 1d K线数据失败，将使用 1m K线聚合")
            klines_1d = []
        
        logger.info(f"[多周期数据] 1m K线: {len(klines_1m)} 条, 1d K线: {len(klines_1d)} 条")
        
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
        
        min_klines = self.market_config.get('min_market_klines', 20)
        if len(market_klines) < min_klines:
            logger.warning(f"[行情判断] K线数据不足: {len(market_klines)} < {min_klines}")
            return self.current_market_status
        
        result = self.market_detector.algorithm.calculate(market_klines, self.market_config)
        
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
        
        action = 'continue'
        
        if is_trending and not was_trending:
            if self.trading_enabled:
                self._close_all_positions(price, timestamp, 'market_status_change')
                self.trading_enabled = False
                action = 'stop_trading'
                self._end_trading_period(time)
                logger.info(f"[行情变化] {old_status.value} -> {new_status.value}, 停止交易")
        
        elif new_status == MarketStatus.RANGING and was_trending:
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
    
    def _close_all_positions(self, price: Decimal, timestamp: int, reason: str):
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
                "close_price": float(price),
                "profit": float(order.profit),
                "reason": f"market_{reason}",
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
        
        if self.kline_count % 100 == 0:
            dt = datetime.fromtimestamp(timestamp / 1000) if timestamp else datetime.now()
            logger.debug(f"[K线 #{self.kline_count}] {dt.strftime('%Y-%m-%d %H:%M')} "
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
            self._current_trading_period.end_time = datetime.fromtimestamp(timestamp / 1000)
        
        if not self.trading_enabled:
            return
        
        self._process_entry(low_price, close_price)
        self._process_exit(open_price, high_price, low_price, close_price)
    
    async def run(
        self, 
        symbol: str = "BTCUSDT", 
        interval: str = "1m", 
        limit: int = 1000, 
        days: int = None, 
        start_time: int = None, 
        end_time: int = None, 
        auto_fetch: bool = True
    ):
        """运行行情感知回测"""
        self.interval = interval
        self.days = days
        
        logger.info("=" * 60)
        logger.info("行情感知回测开始")
        logger.info("=" * 60)
        logger.info(f"配置: {self.config}")
        logger.info(f"行情配置: {self.market_config}")
        
        print("=" * 60)
        print("行情感知回测")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {symbol}")
        print(f"  K线周期: {interval}")
        print(f"  行情判断周期: {self.market_config.get('market_interval', '1d')}")
        print(f"  行情判断算法: {self.market_config.get('algorithm', 'realtime')}")
        if start_time and end_time:
            start_dt = datetime.fromtimestamp(start_time / 1000)
            end_dt = datetime.fromtimestamp(end_time / 1000)
            print(f"  时间范围: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")
        elif days:
            print(f"  回测天数: {days} 天")
        else:
            print(f"  数据量: {limit}")
        
        klines_1m, klines_1d = await self._fetch_multi_interval_klines(
            symbol, interval, limit, days, start_time, end_time, auto_fetch
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
        
        if len(klines_1d) >= self.market_config.get('min_market_klines', 20):
            initial_result = self.market_detector.algorithm.calculate(
                klines_1d[:self.market_config.get('min_market_klines', 20)],
                self.market_config
            )
            self.current_market_status = initial_result.status
            logger.info(f"[初始行情] {initial_result.status.value}, 原因={initial_result.reason}")
            
            if self.current_market_status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]:
                self.trading_enabled = False
                print(f"\n⚠️ 初始行情为趋势，暂停交易")
            else:
                first_order = self._create_order(1, first_price, self.klines_history)
                self.chain_state.orders.append(first_order)
                print(f"\n📋 创建首个订单: A1 入场价={first_order.entry_price:.2f}")
                self._start_trading_period(self.start_time, self.current_market_status)
        else:
            first_order = self._create_order(1, first_price, self.klines_history)
            self.chain_state.orders.append(first_order)
            print(f"\n📋 创建首个订单: A1 入场价={first_order.entry_price:.2f}")
            self._start_trading_period(self.start_time, MarketStatus.UNKNOWN)
        
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
    
    def save_report(self, symbol: str, days: int = None, date_range: str = None):
        """保存回测报告（扩展）"""
        import os
        
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autofish_output")
        os.makedirs(output_dir, exist_ok=True)
        
        if date_range:
            filepath = os.path.join(output_dir, f"binance_{symbol}_market_aware_backtest_{date_range}.md")
        elif days:
            filepath = os.path.join(output_dir, f"binance_{symbol}_market_aware_backtest_{days}d.md")
        else:
            filepath = os.path.join(output_dir, f"binance_{symbol}_market_aware_backtest.md")
        
        net_profit = self.results["total_profit"] - self.results["total_loss"]
        win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
                   if self.results["total_trades"] > 0 else 0)
        
        lines = []
        lines.append(f"# 行情感知回测报告 (Binance: {symbol})")
        lines.append(f"")
        lines.append(f"**回测时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"")
        
        lines.append(f"## 回测区间")
        lines.append(f"")
        lines.append(f"| 项目 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 交易对 | {symbol} |")
        lines.append(f"| K线周期 | {self.interval} |")
        lines.append(f"| 行情判断周期 | {self.market_config.get('market_interval', '1d')} |")
        lines.append(f"| 行情判断算法 | {self.market_config.get('algorithm', 'realtime')} |")
        lines.append(f"| 开始时间 | {self.start_time.strftime('%Y-%m-%d %H:%M') if self.start_time else '-'} |")
        lines.append(f"| 结束时间 | {self.end_time.strftime('%Y-%m-%d %H:%M') if self.end_time else '-'} |")
        lines.append(f"| K线数量 | {self.kline_count} |")
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
        lines.append(f"")
        
        market_stats = self.results.get('market_statistics', {})
        lines.append(f"## 行情分析")
        lines.append(f"")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 行情判断周期 | {self.market_config.get('market_interval', '1d')} |")
        lines.append(f"| 行情判断算法 | {self.market_config.get('algorithm', 'realtime')} |")
        lines.append(f"| 行情状态变化 | {market_stats.get('total_events', 0)} 次 |")
        lines.append(f"| 交易时间占比 | {market_stats.get('trading_pct', 0):.1f}% |")
        lines.append(f"| 停止时间占比 | {market_stats.get('stopped_pct', 0):.1f}% |")
        lines.append(f"")
        
        events = self.results.get('market_status_events', [])
        if events:
            lines.append(f"### 行情状态变化")
            lines.append(f"")
            lines.append(f"| 时间 | 状态变化 | 价格 | 执行动作 |")
            lines.append(f"|------|----------|------|----------|")
            
            prev_status = None
            for event in events:
                if event['status'] != prev_status:
                    lines.append(f"| {event['time']} | {prev_status or '初始'} -> {event['status']} | {event['price']:.2f} | {event['action']} |")
                    prev_status = event['status']
            lines.append(f"")
        
        periods = self.results.get('trading_periods', [])
        if periods:
            lines.append(f"### 交易时段")
            lines.append(f"")
            lines.append(f"| 开始时间 | 结束时间 | 状态 | 交易次数 | 收益 |")
            lines.append(f"|----------|----------|------|----------|------|")
            for period in periods:
                lines.append(f"| {period['start_time']} | {period['end_time']} | {period['status']} | {period['trades']} | {period['profit']:.2f} USDT |")
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
        """保存回测历史记录"""
        import os
        
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autofish_output")
        os.makedirs(output_dir, exist_ok=True)
        
        filepath = os.path.join(output_dir, f"binance_{symbol}_market_aware_history.md")
        
        metrics = self.calculate_metrics()
        net_profit = self.results["total_profit"] - self.results["total_loss"]
        roi = float(net_profit) / float(self.config.get('total_amount_quote', 1200)) * 100
        win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
                   if self.results["total_trades"] > 0 else 0)
        
        price_change = float(metrics["price_change"])
        excess_return = roi - price_change
        
        market_stats = self.results.get('market_statistics', {})
        
        if not os.path.exists(filepath):
            header = [
                f"# {symbol} 行情感知回测历史记录",
                "",
                "| 回测时间 | 日期范围 | 天数 | 交易次数 | 胜率 | 收益率 | 标的涨跌 | 超额收益 | 交易时间占比 |",
                "|----------|----------|------|----------|------|--------|----------|----------|--------------|",
            ]
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(header) + '\n')
        
        date_range_str = f"{self.start_time.strftime('%Y-%m-%d')} ~ {self.end_time.strftime('%Y-%m-%d')}" if self.start_time and self.end_time else "-"
        
        if self.start_time and self.end_time:
            calculated_days = (self.end_time - self.start_time).days + 1
        else:
            calculated_days = days if days else None
        
        days_str = str(calculated_days) if calculated_days else "-"
        
        row = (
            f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | {date_range_str} | {days_str} | "
            f"{self.results['total_trades']} | {win_rate:.1f}% | {roi:.2f}% | "
            f"{price_change:.2f}% | {excess_return:.2f}% | {market_stats.get('trading_pct', 0):.1f}% |"
        )
        
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(row + '\n')
        
        print(f"📊 历史记录已追加: {filepath}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="行情感知回测")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期")
    parser.add_argument("--limit", type=int, default=1500, help="K线数量")
    parser.add_argument("--days", type=int, default=None, help="回测天数")
    parser.add_argument("--date-range", type=str, default=None, help="时间范围 (yyyymmdd-yyyymmdd)")
    parser.add_argument("--decay-factor", type=float, default=0.5, help="衰减因子")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="止损比例")
    parser.add_argument("--total-amount", type=float, default=10000, help="总投入金额")
    parser.add_argument("--market-aware", action="store_true", help="启用行情感知")
    parser.add_argument("--market-interval", type=str, default="1d", help="行情判断周期")
    parser.add_argument("--market-algorithm", type=str, default="realtime", help="行情判断算法")
    parser.add_argument("--no-auto-fetch", action="store_true", help="禁用自动获取")
    
    args = parser.parse_args()
    
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
    
    decay_factor = Decimal(str(args.decay_factor))
    
    from autofish_core import Autofish_AmplitudeConfig
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
    else:
        from autofish_core import Autofish_OrderCalculator
        config = Autofish_OrderCalculator.get_default_config("binance")
        config["symbol"] = args.symbol
        config["decay_factor"] = decay_factor
        config.update({
            "stop_loss": Decimal(str(args.stop_loss)),
            "total_amount_quote": Decimal(str(args.total_amount)),
        })
    
    market_config = {
        'market_interval': args.market_interval,
        'algorithm': args.market_algorithm,
        'min_market_klines': 20,
        'confirm_periods': 2,
        'close_on_trending': True,
    }
    
    if date_ranges:
        print(f"\n📊 共 {len(date_ranges)} 个时间段需要回测")
        
        for i, dr in enumerate(date_ranges, 1):
            print(f"\n{'='*60}")
            print(f"📅 第 {i}/{len(date_ranges)} 个时间段: {dr['start_date'].strftime('%Y-%m-%d')} ~ {dr['end_date'].strftime('%Y-%m-%d')} ({dr['days']} 天)")
            print(f"{'='*60}")
            
            engine = MarketAwareBacktestEngine(config, market_config)
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
        engine = MarketAwareBacktestEngine(config, market_config)
        await engine.run(
            symbol=args.symbol, 
            interval=args.interval, 
            limit=args.limit, 
            days=args.days, 
            auto_fetch=not args.no_auto_fetch
        )
        engine.save_report(args.symbol, args.days)
        engine.save_history(args.symbol, args.days)


if __name__ == "__main__":
    asyncio.run(main())

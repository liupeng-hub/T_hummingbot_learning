#!/usr/bin/env python3
"""
市场行情判断器

功能:
- 判断当前市场处于震荡行情还是趋势行情
- 支持不同算法替换
- 可嵌入到回测和实盘代码中
- 生成行情分析报告

使用方法:
    # 分析最近 20 天的行情
    python market_status_detector.py --symbol BTCUSDT --days 20

    # 分析指定时间范围
    python market_status_detector.py --symbol BTCUSDT --date-range "20240101-20240601"

    # 使用不同算法
    python market_status_detector.py --symbol BTCUSDT --days 20 --algorithm adx
"""

import os
import sys
import asyncio
import argparse
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("market_status_detector")


class MarketStatus(Enum):
    """市场状态"""
    RANGING = "ranging"              # 震荡行情
    TRENDING_UP = "trending_up"      # 上涨趋势
    TRENDING_DOWN = "trending_down"  # 下跌趋势
    TRANSITIONING = "transitioning"  # 过渡状态
    UNKNOWN = "unknown"              # 未知状态


@dataclass
class StatusResult:
    """行情判断结果"""
    status: MarketStatus           # 市场状态
    confidence: float              # 置信度 (0-1)
    indicators: Dict               # 指标值
    reason: str                    # 判断原因


@dataclass
class MarketInterval:
    """市场区间"""
    start_time: int
    end_time: int
    status: MarketStatus
    duration: int
    price_range: Tuple[float, float]
    indicators: Dict
    
    def to_dict(self) -> Dict:
        return {
            'start_time': datetime.fromtimestamp(self.start_time / 1000).strftime('%Y-%m-%d %H:%M'),
            'end_time': datetime.fromtimestamp(self.end_time / 1000).strftime('%Y-%m-%d %H:%M'),
            'status': self.status.value,
            'duration': self.duration,
            'price_range': self.price_range,
        }


class PriceActionDetector:
    """价格行为检测器（实时性最高，滞后0-1天）"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'lookback_period': 20,
            'breakout_threshold': 0.02,
            'consecutive_bars': 3,
        }
    
    def detect(self, klines: List[Dict]) -> Dict:
        if len(klines) < self.config['lookback_period']:
            return {'breakout': False, 'direction': None}
        
        recent = klines[-self.config['lookback_period']:]
        range_high = max(float(k['high']) for k in recent)
        range_low = min(float(k['low']) for k in recent)
        current_price = float(klines[-1]['close'])
        
        breakout_up = current_price > range_high * (1 - self.config['breakout_threshold'])
        breakout_down = current_price < range_low * (1 + self.config['breakout_threshold'])
        
        consecutive_up = self._count_consecutive(klines, 'up')
        consecutive_down = self._count_consecutive(klines, 'down')
        
        if breakout_up or consecutive_up >= self.config['consecutive_bars']:
            return {
                'breakout': True,
                'direction': 'up',
                'consecutive': consecutive_up,
                'range_high': range_high,
                'range_low': range_low,
                'current_price': current_price,
            }
        elif breakout_down or consecutive_down >= self.config['consecutive_bars']:
            return {
                'breakout': True,
                'direction': 'down',
                'consecutive': consecutive_down,
                'range_high': range_high,
                'range_low': range_low,
                'current_price': current_price,
            }
        else:
            return {
                'breakout': False,
                'direction': None,
                'consecutive': max(consecutive_up, consecutive_down),
                'range_high': range_high,
                'range_low': range_low,
                'current_price': current_price,
            }
    
    def _count_consecutive(self, klines: List[Dict], direction: str) -> int:
        count = 0
        for k in reversed(klines):
            if direction == 'up' and float(k['close']) > float(k['open']):
                count += 1
            elif direction == 'down' and float(k['close']) < float(k['open']):
                count += 1
            else:
                break
        return count


class VolatilityDetector:
    """波动率检测器（实时性高，滞后1-2天）"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'atr_period': 14,
            'expansion_threshold': 1.5,
            'contraction_threshold': 0.7,
        }
    
    def detect(self, klines: List[Dict]) -> Dict:
        if len(klines) < self.config['atr_period'] * 2:
            return {'volatility_status': 'unknown'}
        
        atr = self._calculate_atr(klines, self.config['atr_period'])
        atr_ma = self._calculate_atr_ma(klines, self.config['atr_period'] * 2)
        atr_ratio = atr / atr_ma if atr_ma > 0 else 1.0
        
        if atr_ratio >= self.config['expansion_threshold']:
            status = 'expanding'
        elif atr_ratio <= self.config['contraction_threshold']:
            status = 'contracting'
        else:
            status = 'normal'
        
        return {
            'atr': atr,
            'atr_ma': atr_ma,
            'atr_ratio': atr_ratio,
            'volatility_status': status,
        }
    
    def _calculate_atr(self, klines: List[Dict], period: int) -> float:
        tr_list = []
        for i in range(1, len(klines)):
            high = float(klines[i]['high'])
            low = float(klines[i]['low'])
            close_prev = float(klines[i-1]['close'])
            
            tr = max(
                high - low,
                abs(high - close_prev),
                abs(low - close_prev)
            )
            tr_list.append(tr)
        
        if len(tr_list) < period:
            return sum(tr_list) / len(tr_list) if tr_list else 0
        
        return sum(tr_list[-period:]) / period
    
    def _calculate_atr_ma(self, klines: List[Dict], period: int) -> float:
        atr_list = []
        for i in range(period, len(klines)):
            atr = self._calculate_atr(klines[:i+1], self.config['atr_period'])
            atr_list.append(atr)
        
        return sum(atr_list[-period:]) / len(atr_list) if atr_list else 0


class StatusAlgorithm(ABC):
    """行情判断算法基类"""
    
    name: str = "base"
    description: str = "基础算法"
    
    @abstractmethod
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        """计算市场状态"""
        pass
    
    @abstractmethod
    def get_required_periods(self) -> int:
        """获取算法所需的最小 K 线数量"""
        pass
    
    def get_indicators(self) -> Dict:
        """获取算法计算的指标值"""
        return {}


class ADXAlgorithm(StatusAlgorithm):
    """ADX 趋势强度算法"""
    
    name = "adx"
    description = "基于 ADX 的趋势强度判断"
    
    def __init__(self, period: int = 14, threshold: int = 25):
        self.period = period
        self.threshold = threshold
        self._indicators = {}
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        """计算 ADX 并判断行情"""
        if len(klines) < self.get_required_periods():
            return StatusResult(
                status=MarketStatus.UNKNOWN,
                confidence=0.0,
                indicators={},
                reason="K线数据不足"
            )
        
        # 计算 ADX
        adx = self._calculate_adx(klines)
        self._indicators['adx'] = adx
        
        # 判断行情
        if adx >= self.threshold:
            # 趋势行情，判断方向
            price = float(klines[-1]['close'])
            ma = self._calculate_ma(klines, 50)
            
            if price > ma:
                status = MarketStatus.TRENDING_UP
                reason = f"ADX={adx:.2f}>={self.threshold}, 价格>MA50, 上涨趋势"
            else:
                status = MarketStatus.TRENDING_DOWN
                reason = f"ADX={adx:.2f}>={self.threshold}, 价格<MA50, 下跌趋势"
            
            confidence = min(1.0, (adx - self.threshold) / 25)
        else:
            status = MarketStatus.RANGING
            reason = f"ADX={adx:.2f}<{self.threshold}, 震荡行情"
            confidence = 1.0 - (adx / self.threshold)
        
        return StatusResult(
            status=status,
            confidence=confidence,
            indicators=self._indicators,
            reason=reason
        )
    
    def get_required_periods(self) -> int:
        return self.period * 2 + 50  # ADX + MA
    
    def get_indicators(self) -> Dict:
        return self._indicators
    
    def _calculate_adx(self, klines: List[Dict]) -> float:
        """计算 ADX"""
        high = [float(k['high']) for k in klines]
        low = [float(k['low']) for k in klines]
        close = [float(k['close']) for k in klines]
        
        # +DM 和 -DM
        plus_dm = []
        minus_dm = []
        tr = []
        
        for i in range(1, len(high)):
            up_move = high[i] - high[i-1]
            down_move = low[i-1] - low[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
                minus_dm.append(0)
            elif down_move > up_move and down_move > 0:
                plus_dm.append(0)
                minus_dm.append(down_move)
            else:
                plus_dm.append(0)
                minus_dm.append(0)
            
            # TR
            tr.append(max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            ))
        
        if not tr:
            return 0.0
        
        # 平滑
        atr = self._sma(tr, self.period)
        plus_dm_smooth = self._sma(plus_dm, self.period)
        minus_dm_smooth = self._sma(minus_dm, self.period)
        
        if atr == 0:
            return 0.0
        
        # +DI 和 -DI
        plus_di = 100 * plus_dm_smooth / atr
        minus_di = 100 * minus_dm_smooth / atr
        
        # DX
        di_sum = plus_di + minus_di
        if di_sum == 0:
            return 0.0
        
        dx = 100 * abs(plus_di - minus_di) / di_sum
        
        # ADX (平滑 DX)
        adx = self._sma([dx], self.period)
        
        return adx
    
    def _calculate_ma(self, klines: List[Dict], period: int) -> float:
        """计算均线"""
        if len(klines) < period:
            return float(klines[-1]['close'])
        
        closes = [float(k['close']) for k in klines[-period:]]
        return sum(closes) / len(closes)
    
    def _sma(self, data: List[float], period: int) -> float:
        """简单移动平均"""
        if not data:
            return 0.0
        
        if len(data) < period:
            return sum(data) / len(data)
        
        return sum(data[-period:]) / period


class CompositeAlgorithm(StatusAlgorithm):
    """组合算法 - 多指标综合判断"""
    
    name = "composite"
    description = "ADX + ATR + 布林带宽度组合判断"
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'adx_period': 14,
            'adx_threshold': 25,
            'atr_period': 14,
            'atr_multiplier': 1.5,
            'bb_period': 20,
            'bb_std': 2,
            'bb_width_threshold': 0.04,
            'ma_period': 50,
        }
        
        # 子算法
        self.adx_algo = ADXAlgorithm(
            period=self.config['adx_period'],
            threshold=self.config['adx_threshold']
        )
        
        self._indicators = {}
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        """综合多指标判断"""
        if len(klines) < self.get_required_periods():
            return StatusResult(
                status=MarketStatus.UNKNOWN,
                confidence=0.0,
                indicators={},
                reason="K线数据不足"
            )
        
        # 1. ADX 判断
        adx_result = self.adx_algo.calculate(klines, config)
        adx = adx_result.indicators.get('adx', 0)
        
        # 2. ATR 判断
        atr = self._calculate_atr(klines)
        atr_ma = self._calculate_atr_ma(klines, 50)
        atr_ratio = atr / atr_ma if atr_ma > 0 else 1.0
        
        # 3. 布林带宽度
        bb_width = self._calculate_bb_width(klines)
        
        # 4. 价格与均线关系
        price = float(klines[-1]['close'])
        ma = self._calculate_ma(klines, self.config['ma_period'])
        
        # 保存指标
        self._indicators = {
            'adx': adx,
            'atr': atr,
            'atr_ratio': atr_ratio,
            'bb_width': bb_width,
            'price': price,
            'ma': ma,
        }
        
        # 5. 综合判断
        trend_score = 0
        reasons = []
        
        # ADX 贡献
        if adx >= self.config['adx_threshold']:
            trend_score += 40
            reasons.append(f"ADX={adx:.2f}>={self.config['adx_threshold']}")
        
        # ATR 贡献
        if atr_ratio >= self.config['atr_multiplier']:
            trend_score += 30
            reasons.append(f"ATR比率={atr_ratio:.2f}>={self.config['atr_multiplier']}")
        
        # 布林带贡献
        if bb_width >= self.config['bb_width_threshold']:
            trend_score += 30
            reasons.append(f"BB宽度={bb_width:.4f}>={self.config['bb_width_threshold']}")
        
        # 判断结果
        if trend_score >= 70:
            # 强趋势
            if price > ma:
                status = MarketStatus.TRENDING_UP
            else:
                status = MarketStatus.TRENDING_DOWN
            confidence = trend_score / 100
            reason = f"趋势得分={trend_score}, " + ", ".join(reasons)
        elif trend_score >= 40:
            # 过渡状态
            status = MarketStatus.TRANSITIONING
            confidence = 0.5
            reason = f"过渡状态, 趋势得分={trend_score}"
        else:
            # 震荡
            status = MarketStatus.RANGING
            confidence = 1.0 - trend_score / 100
            reason = f"震荡行情, 趋势得分={trend_score}"
        
        return StatusResult(
            status=status,
            confidence=confidence,
            indicators=self._indicators,
            reason=reason
        )
    
    def get_required_periods(self) -> int:
        return max(
            self.config['adx_period'] * 2 + 50,
            self.config['atr_period'] * 2 + 50,
            self.config['bb_period'],
            self.config['ma_period']
        )
    
    def get_indicators(self) -> Dict:
        return self._indicators
    
    def _calculate_atr(self, klines: List[Dict]) -> float:
        """计算 ATR"""
        high = [float(k['high']) for k in klines]
        low = [float(k['low']) for k in klines]
        close = [float(k['close']) for k in klines]
        
        tr = []
        for i in range(1, len(high)):
            tr.append(max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            ))
        
        if not tr:
            return 0.0
        
        return sum(tr[-self.config['atr_period']:]) / min(len(tr), self.config['atr_period'])
    
    def _calculate_atr_ma(self, klines: List[Dict], period: int) -> float:
        """计算 ATR 均值"""
        high = [float(k['high']) for k in klines]
        low = [float(k['low']) for k in klines]
        close = [float(k['close']) for k in klines]
        
        tr = []
        for i in range(1, len(high)):
            tr.append(max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            ))
        
        if len(tr) < period:
            return sum(tr) / len(tr) if tr else 0.0
        
        return sum(tr[-period:]) / period
    
    def _calculate_bb_width(self, klines: List[Dict]) -> float:
        """计算布林带宽度"""
        closes = [float(k['close']) for k in klines[-self.config['bb_period']:]]
        
        if len(closes) < self.config['bb_period']:
            return 0.0
        
        ma = sum(closes) / len(closes)
        
        # 标准差
        variance = sum((c - ma) ** 2 for c in closes) / len(closes)
        std = variance ** 0.5
        
        upper = ma + self.config['bb_std'] * std
        lower = ma - self.config['bb_std'] * std
        
        if ma == 0:
            return 0.0
        
        return (upper - lower) / ma
    
    def _calculate_ma(self, klines: List[Dict], period: int) -> float:
        """计算均线"""
        if len(klines) < period:
            return float(klines[-1]['close'])
        
        closes = [float(k['close']) for k in klines[-period:]]
        return sum(closes) / len(closes)


class RealTimeStatusAlgorithm(StatusAlgorithm):
    """实时市场状态判断算法
    
    改进版本：
    - 增加状态持续性判断（惯性）
    - 需要更强的信号才能切换状态
    - 震荡状态更稳定
    """
    
    name = "realtime"
    description = "实时市场状态判断算法（价格行为+波动率）"
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'lookback_period': 20,
            'breakout_threshold': 0.02,
            'consecutive_bars': 3,
            'atr_period': 14,
            'expansion_threshold': 1.5,
            'contraction_threshold': 0.7,
            'confirm_periods': 2,
            'min_trend_signals': 4,
            'status_inertia': True,
            'min_trend_confidence': 0.8,
            'min_range_duration': 5,
        }
        
        self.price_detector = PriceActionDetector(self.config)
        self.volatility_detector = VolatilityDetector(self.config)
        
        self._indicators = {}
        self._status_history = []
        self._current_status = MarketStatus.UNKNOWN
        self._status_duration = 0
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        if len(klines) < self.config['lookback_period']:
            return StatusResult(
                status=MarketStatus.UNKNOWN,
                confidence=0.0,
                indicators={},
                reason="K线数据不足"
            )
        
        price_result = self.price_detector.detect(klines)
        volatility_result = self.volatility_detector.detect(klines)
        
        status, confidence, reason = self._determine_status(
            price_result, volatility_result
        )
        
        status = self._apply_inertia(status, confidence)
        
        self._status_history.append(status)
        confirmed_status = self._confirm_status()
        
        self._indicators = {
            'price_action': price_result,
            'volatility': volatility_result,
        }
        
        return StatusResult(
            status=confirmed_status,
            confidence=confidence,
            indicators=self._indicators,
            reason=reason
        )
    
    def _apply_inertia(self, new_status: MarketStatus, confidence: float) -> MarketStatus:
        """应用状态惯性
        
        状态切换需要更强的信号：
        - 震荡 -> 趋势：需要更高的置信度和持续时间
        - 趋势 -> 震荡：相对容易（保护资金）
        - 趋势 -> 反向趋势：需要更强的信号
        """
        if not self.config.get('status_inertia', True):
            return new_status
        
        if self._current_status == MarketStatus.UNKNOWN:
            self._current_status = new_status
            self._status_duration = 1
            return new_status
        
        if new_status == self._current_status:
            self._status_duration += 1
            return new_status
        
        is_current_trending = self._current_status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]
        is_new_trending = new_status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]
        
        if not is_current_trending and is_new_trending:
            min_confidence = self.config.get('min_trend_confidence', 0.8)
            min_duration = self.config.get('min_range_duration', 5)
            
            if confidence < min_confidence or self._status_duration < min_duration:
                return self._current_status
        
        if is_current_trending and is_new_trending:
            if self._current_status != new_status:
                if confidence < 0.9:
                    return self._current_status
        
        self._current_status = new_status
        self._status_duration = 1
        return new_status
    
    def _determine_status(self, price_result: Dict, 
                          volatility_result: Dict) -> Tuple[MarketStatus, float, str]:
        reasons = []
        trend_signals = 0
        range_signals = 0
        
        if price_result['breakout']:
            if price_result['direction'] == 'up':
                trend_signals += 3
                reasons.append(f"向上突破区间 {price_result['range_high']:.2f}")
            else:
                trend_signals += 3
                reasons.append(f"向下突破区间 {price_result['range_low']:.2f}")
        else:
            range_signals += 2
            reasons.append("价格在区间内")
        
        if price_result['consecutive'] >= self.config['consecutive_bars']:
            trend_signals += 1
            reasons.append(f"连续{price_result['consecutive']}根同向K线")
        
        if volatility_result['volatility_status'] == 'expanding':
            trend_signals += 1
            reasons.append(f"波动率扩张 ATR比率={volatility_result['atr_ratio']:.2f}")
        elif volatility_result['volatility_status'] == 'contracting':
            range_signals += 1
            reasons.append(f"波动率收缩 ATR比率={volatility_result['atr_ratio']:.2f}")
        
        min_trend_signals = self.config.get('min_trend_signals', 4)
        
        if trend_signals >= min_trend_signals:
            if price_result['direction'] == 'up':
                status = MarketStatus.TRENDING_UP
            else:
                status = MarketStatus.TRENDING_DOWN
            confidence = min(1.0, trend_signals / 5)
        elif range_signals >= 2:
            status = MarketStatus.RANGING
            confidence = min(1.0, range_signals / 3)
        else:
            status = MarketStatus.TRANSITIONING
            confidence = 0.5
        
        return status, confidence, ", ".join(reasons)
    
    def _confirm_status(self) -> MarketStatus:
        if len(self._status_history) < self.config['confirm_periods']:
            return self._status_history[-1] if self._status_history else MarketStatus.UNKNOWN
        
        recent = self._status_history[-self.config['confirm_periods']:]
        
        if len(set(recent)) == 1:
            return recent[0]
        
        if self._current_status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]:
            trending_count = sum(1 for s in recent if s in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN])
            if trending_count >= len(recent) * 0.5:
                return self._current_status
        
        return self._status_history[-1]
    
    def get_required_periods(self) -> int:
        return max(
            self.config['lookback_period'],
            self.config['atr_period'] * 2
        )
    
    def get_indicators(self) -> Dict:
        return self._indicators


class IntervalAnalyzer:
    """区间分析器"""
    
    def __init__(self):
        self.intervals: List[MarketInterval] = []
        self._current_interval = None
    
    def update(self, timestamp: int, price: float, status: MarketStatus, indicators: Dict):
        if self._current_interval is None:
            self._current_interval = MarketInterval(
                start_time=timestamp,
                end_time=timestamp,
                status=status,
                duration=1,
                price_range=(price, price),
                indicators=indicators,
            )
        elif status == self._current_interval.status:
            self._current_interval.end_time = timestamp
            self._current_interval.duration += 1
            low, high = self._current_interval.price_range
            self._current_interval.price_range = (min(low, price), max(high, price))
        else:
            self.intervals.append(self._current_interval)
            self._current_interval = MarketInterval(
                start_time=timestamp,
                end_time=timestamp,
                status=status,
                duration=1,
                price_range=(price, price),
                indicators=indicators,
            )
    
    def get_intervals(self) -> List[Dict]:
        result = [i.to_dict() for i in self.intervals]
        if self._current_interval:
            result.append(self._current_interval.to_dict())
        return result
    
    def get_current_interval(self) -> Optional[MarketInterval]:
        return self._current_interval


class StrategySwitcher:
    """策略切换决策器"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'min_interval_duration': 3,
            'switch_threshold': 0.6,
        }
        
        self._current_strategy = 'ranging'
        self._switch_history = []
    
    def should_switch(self, status: MarketStatus, confidence: float, 
                      duration: int) -> Tuple[bool, str]:
        if duration < self.config['min_interval_duration']:
            return False, self._current_strategy
        
        if confidence < self.config['switch_threshold']:
            return False, self._current_strategy
        
        if status == MarketStatus.RANGING:
            target_strategy = 'ranging'
        elif status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]:
            target_strategy = 'trending'
        else:
            return False, self._current_strategy
        
        if target_strategy != self._current_strategy:
            self._switch_history.append({
                'from': self._current_strategy,
                'to': target_strategy,
                'status': status.value,
                'confidence': confidence,
            })
            self._current_strategy = target_strategy
            return True, target_strategy
        
        return False, self._current_strategy
    
    def get_current_strategy(self) -> str:
        return self._current_strategy
    
    def get_switch_history(self) -> List[Dict]:
        return self._switch_history


class MarketStatusDetector:
    """市场行情判断器"""
    
    ALGORITHMS = {
        'realtime': RealTimeStatusAlgorithm,
        'adx': ADXAlgorithm,
        'composite': CompositeAlgorithm,
    }
    
    def __init__(self, algorithm: StatusAlgorithm = None, config: Dict = None):
        self.algorithm = algorithm or RealTimeStatusAlgorithm(config)
        self.config = config or {}
        
        self._current_status = MarketStatus.UNKNOWN
        self._history: List[Dict] = []
        self._klines: List[Dict] = []
        
        self.interval_analyzer = IntervalAnalyzer()
        self.strategy_switcher = StrategySwitcher(config)
    
    def set_algorithm(self, algorithm: StatusAlgorithm):
        """设置算法（支持运行时替换）"""
        self.algorithm = algorithm
        self._history = []
        self.interval_analyzer = IntervalAnalyzer()
        self.strategy_switcher = StrategySwitcher(self.config)
    
    async def analyze(self, symbol: str, interval: str = "1m",
                      start_time: int = None, end_time: int = None,
                      days: int = None, limit: int = None) -> Dict:
        from binance_kline_fetcher import KlineFetcher
        
        self._interval = interval
        
        fetcher = KlineFetcher()
        success = await fetcher.ensure_klines(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            days=days,
            limit=limit,
            auto_fetch=True
        )
        
        if not success:
            raise Exception("获取 K 线数据失败")
        
        actual_start, actual_end = fetcher.get_time_range()
        klines = fetcher.query_cache(symbol, interval, actual_start, actual_end)
        
        if not klines:
            raise Exception("K 线数据为空")
        
        results = []
        required_periods = self.algorithm.get_required_periods()
        
        self.interval_analyzer = IntervalAnalyzer()
        
        print(f"[分析] K线数量: {len(klines)}, 最小需求: {required_periods}")
        
        for i in range(required_periods, len(klines)):
            window = klines[:i+1]
            result = self.algorithm.calculate(window, self.config)
            
            self.interval_analyzer.update(
                klines[i]['timestamp'],
                float(klines[i]['close']),
                result.status,
                result.indicators
            )
            
            results.append({
                'timestamp': klines[i]['timestamp'],
                'time': datetime.fromtimestamp(klines[i]['timestamp'] / 1000),
                'price': float(klines[i]['close']),
                'status': result.status,
                'confidence': result.confidence,
                'indicators': result.indicators,
                'reason': result.reason,
            })
        
        stats = self._calculate_statistics(results)
        
        self._history = results
        self._klines = klines
        self._start_time = actual_start
        self._end_time = actual_end
        
        return {
            'symbol': symbol,
            'interval': interval,
            'start_time': actual_start,
            'end_time': actual_end,
            'total_klines': len(klines),
            'total_results': len(results),
            'statistics': stats,
            'intervals': self.interval_analyzer.get_intervals(),
            'results': results,
        }
    
    def update(self, kline: Dict) -> Dict:
        self._klines.append(kline)
        
        required = self.algorithm.get_required_periods()
        if len(self._klines) > required * 2:
            self._klines = self._klines[-required * 2:]
        
        if len(self._klines) < required:
            return {'status': MarketStatus.UNKNOWN, 'should_switch': False}
        
        result = self.algorithm.calculate(self._klines, self.config)
        self._current_status = result.status
        
        self.interval_analyzer.update(
            kline['timestamp'],
            float(kline['close']),
            result.status,
            result.indicators
        )
        
        current_interval = self.interval_analyzer.get_current_interval()
        should_switch, target_strategy = self.strategy_switcher.should_switch(
            result.status,
            result.confidence,
            current_interval.duration if current_interval else 0
        )
        
        return {
            'status': result.status,
            'confidence': result.confidence,
            'reason': result.reason,
            'should_switch': should_switch,
            'target_strategy': target_strategy,
            'current_strategy': self.strategy_switcher.get_current_strategy(),
        }
    
    def get_status(self) -> MarketStatus:
        return self._current_status
    
    def should_trade(self) -> bool:
        return self._current_status == MarketStatus.RANGING
    
    def get_indicators(self) -> Dict:
        return self.algorithm.get_indicators()
    
    def get_current_strategy(self) -> str:
        return self.strategy_switcher.get_current_strategy()
    
    def get_intervals(self) -> List[Dict]:
        return self.interval_analyzer.get_intervals()
    
    def get_switch_history(self) -> List[Dict]:
        return self.strategy_switcher.get_switch_history()
    
    def _calculate_statistics(self, results: List[Dict]) -> Dict:
        """计算统计数据"""
        if not results:
            return {}
        
        statuses = [r['status'] for r in results]
        
        return {
            'total': len(results),
            'ranging_count': statuses.count(MarketStatus.RANGING),
            'ranging_pct': statuses.count(MarketStatus.RANGING) / len(statuses) * 100,
            'trending_up_count': statuses.count(MarketStatus.TRENDING_UP),
            'trending_up_pct': statuses.count(MarketStatus.TRENDING_UP) / len(statuses) * 100,
            'trending_down_count': statuses.count(MarketStatus.TRENDING_DOWN),
            'trending_down_pct': statuses.count(MarketStatus.TRENDING_DOWN) / len(statuses) * 100,
            'transitioning_count': statuses.count(MarketStatus.TRANSITIONING),
            'transitioning_pct': statuses.count(MarketStatus.TRANSITIONING) / len(statuses) * 100,
        }
    
    def save_report(self, symbol: str, interval: str = None, days: int = None, date_range_str: str = None):
        interval = interval or getattr(self, '_interval', '1m')
        
        if date_range_str:
            filename = f"binance_{symbol}_market_report_{interval}_{date_range_str}.md"
        elif days:
            filename = f"binance_{symbol}_market_report_{interval}_{days}d.md"
        else:
            filename = f"binance_{symbol}_market_report_{interval}.md"
        
        output_dir = "autofish_output"
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
        
        stats = self._calculate_statistics(self._history)
        
        start_time_str = datetime.fromtimestamp(self._start_time / 1000).strftime('%Y-%m-%d')
        end_time_str = datetime.fromtimestamp(self._end_time / 1000).strftime('%Y-%m-%d')
        
        intervals = self.get_intervals()
        intervals_content = ""
        if intervals:
            intervals_content = "\n## 区间划分\n\n| 开始时间 | 结束时间 | 状态 | 持续K线数 |\n|----------|----------|------|----------|\n"
            for interval_item in intervals:
                intervals_content += f"| {interval_item['start_time']} | {interval_item['end_time']} | {interval_item['status']} | {interval_item['duration']} |\n"
        
        content = f"""# {symbol} 市场行情分析报告

## 基本信息

| 项目 | 值 |
|------|-----|
| 交易对 | {symbol} |
| K线周期 | {interval} |
| 分析天数 | {days or '-'} |
| 时间范围 | {start_time_str} ~ {end_time_str} |
| K线数量 | {len(self._klines)} |
| 分析算法 | {self.algorithm.name} |

## 行情统计

| 行情状态 | 数量 | 占比 |
|----------|------|------|
| 震荡行情 | {stats.get('ranging_count', 0)} | {stats.get('ranging_pct', 0):.2f}% |
| 上涨趋势 | {stats.get('trending_up_count', 0)} | {stats.get('trending_up_pct', 0):.2f}% |
| 下跌趋势 | {stats.get('trending_down_count', 0)} | {stats.get('trending_down_pct', 0):.2f}% |
| 过渡状态 | {stats.get('transitioning_count', 0)} | {stats.get('transitioning_pct', 0):.2f}% |
{intervals_content}
## 行情时间线

"""
        prev_status = None
        for r in self._history:
            if r['status'] != prev_status:
                content += f"- {r['time'].strftime('%Y-%m-%d %H:%M')}: {r['status'].value} ({r['reason']})\n"
                prev_status = r['status']
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"📄 行情报告已保存: {filepath}")
    
    def save_history(self, symbol: str, interval: str = None, days: int = None, date_range_str: str = None):
        interval = interval or getattr(self, '_interval', '1m')
        
        filename = f"binance_{symbol}_market_history.md"
        output_dir = "autofish_output"
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
        
        stats = self._calculate_statistics(self._history)
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        time_range = date_range_str or f"{days}d"
        
        if not os.path.exists(filepath):
            header = f"""# {symbol} 市场行情分析历史记录

| 分析时间 | K线周期 | 时间范围 | 天数 | 震荡占比 | 上涨占比 | 下跌占比 | 算法 |
|----------|---------|----------|------|----------|----------|----------|------|
"""
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(header)
        
        content = f"| {now} | {interval} | {time_range} | {days or '-'} | {stats.get('ranging_pct', 0):.1f}% | {stats.get('trending_up_pct', 0):.1f}% | {stats.get('trending_down_pct', 0):.1f}% | {self.algorithm.name} |\n"
        
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(content)
        
        print(f"📊 历史记录已追加: {filepath}")


async def main():
    parser = argparse.ArgumentParser(description="市场行情判断器")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期 (默认: 1m)")
    parser.add_argument("--days", type=int, default=None, help="分析天数")
    parser.add_argument("--date-range", type=str, default=None, help="时间范围 (格式: yyyymmdd-yyyymmdd)")
    parser.add_argument("--algorithm", type=str, default="realtime", 
                        choices=['realtime', 'adx', 'composite'], help="算法 (默认: realtime)")
    parser.add_argument("--adx-threshold", type=int, default=25, help="ADX 阈值 (默认: 25)")
    
    args = parser.parse_args()
    
    if args.algorithm == 'realtime':
        algorithm = RealTimeStatusAlgorithm()
    elif args.algorithm == 'adx':
        algorithm = ADXAlgorithm(threshold=args.adx_threshold)
    else:
        algorithm = CompositeAlgorithm()
    
    detector = MarketStatusDetector(algorithm=algorithm)
    
    start_time = None
    end_time = None
    date_range_str = None
    
    if args.date_range:
        try:
            if args.date_range.count("-") == 1:
                parts = args.date_range.split("-")
                start_date = datetime.strptime(parts[0], "%Y%m%d")
                end_date = datetime.strptime(parts[1], "%Y%m%d")
            else:
                raise ValueError(f"不支持的日期格式: {args.date_range}")
            
            start_time = int(start_date.timestamp() * 1000)
            end_time = int(end_date.timestamp() * 1000) + 86400000 - 1
            days = (end_date - start_date).days + 1
            date_range_str = f"{days}d_{args.date_range}"
        except ValueError as e:
            logger.error(f"[时间范围] 解析失败: {e}")
            return
    else:
        days = args.days
    
    print(f"\n{'='*60}")
    print(f"📊 市场行情分析")
    print(f"  交易对: {args.symbol}")
    print(f"  周期: {args.interval}")
    print(f"  算法: {args.algorithm}")
    print(f"{'='*60}")
    
    try:
        result = await detector.analyze(
            symbol=args.symbol,
            interval=args.interval,
            start_time=start_time,
            end_time=end_time,
            days=args.days
        )
        
        stats = result['statistics']
        print(f"\n📈 行情统计:")
        print(f"  震荡行情: {stats['ranging_pct']:.1f}% ({stats['ranging_count']} 次)")
        print(f"  上涨趋势: {stats['trending_up_pct']:.1f}% ({stats['trending_up_count']} 次)")
        print(f"  下跌趋势: {stats['trending_down_pct']:.1f}% ({stats['trending_down_count']} 次)")
        print(f"  过渡状态: {stats['transitioning_pct']:.1f}% ({stats['transitioning_count']} 次)")
        
        intervals = result.get('intervals', [])
        if intervals:
            print(f"\n📊 区间划分 ({len(intervals)} 个区间):")
            for i, interval in enumerate(intervals[:10]):
                print(f"  {i+1}. {interval['start_time']} ~ {interval['end_time']}: {interval['status']} ({interval['duration']} 根K线)")
            if len(intervals) > 10:
                print(f"  ... 还有 {len(intervals) - 10} 个区间")
        
        detector.save_report(args.symbol, days, date_range_str)
        detector.save_history(args.symbol, days, date_range_str)
        
    except Exception as e:
        logger.error(f"[分析] 失败: {e}")
        raise


REALTIME_PRIORITY_CONFIG = {
    'lookback_period': 15,
    'breakout_threshold': 0.015,
    'consecutive_bars': 2,
    'atr_period': 10,
    'expansion_threshold': 1.3,
    'contraction_threshold': 0.8,
    'confirm_periods': 1,
    'min_interval_duration': 2,
    'switch_threshold': 0.5,
}

RELIABILITY_PRIORITY_CONFIG = {
    'lookback_period': 20,
    'breakout_threshold': 0.02,
    'consecutive_bars': 3,
    'atr_period': 14,
    'expansion_threshold': 1.5,
    'contraction_threshold': 0.7,
    'confirm_periods': 2,
    'min_interval_duration': 3,
    'switch_threshold': 0.6,
}


if __name__ == "__main__":
    asyncio.run(main())

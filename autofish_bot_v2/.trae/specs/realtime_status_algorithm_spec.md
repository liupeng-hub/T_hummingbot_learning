# 实时市场状态切换算法设计规格

## 1. 需求分析

### 1.1 核心需求

| 需求 | 说明 |
|------|------|
| **实时性** | 状态切换不能太延后 |
| **区间划分** | 明确划分震荡区间和趋势区间 |
| **策略切换** | 根据状态切换震荡算法和趋势算法 |

### 1.2 关键问题

**EMA均线的滞后性问题**：
- EMA200 滞后约100天
- EMA99 滞后约50天
- 即使EMA7也滞后约3-4天

**对于策略切换来说，这个延迟太大了！**

## 2. 解决方案

### 2.1 方案对比

| 方案 | 实时性 | 可靠性 | 适用性 |
|------|--------|--------|--------|
| **EMA均线** | ⭐⭐ | ⭐⭐⭐⭐ | 不适合（滞后太大） |
| **价格突破** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 适合（实时性好） |
| **波动率变化** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 适合（实时性好） |
| **组合方案** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **推荐** |

### 2.2 推荐方案：价格行为 + 波动率组合

```
┌─────────────────────────────────────────────────────────────────┐
│                    实时市场状态判断器                             │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 第一层：价格行为判断（实时性最高）                          │    │
│  │  - 价格突破近期高低点                                      │    │
│  │  - 连续阳线/阴线                                          │    │
│  │  - 价格形态                                               │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 第二层：波动率判断（实时性高）                              │    │
│  │  - ATR 变化率                                             │    │
│  │  - 价格波动幅度                                            │    │
│  │  - 波动率扩张/收缩                                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 第三层：趋势确认（可靠性高）                                │    │
│  │  - 短期EMA（EMA7、EMA25）                                  │    │
│  │  - ADX                                                    │    │
│  │  - 成交量变化                                              │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## 3. 核心算法设计

### 3.1 价格行为判断（实时性最高）

```python
class PriceActionDetector:
    """价格行为检测器（实时性最高）"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'lookback_period': 20,      # 回看周期
            'breakout_threshold': 0.02,  # 突破阈值 2%
            'consecutive_bars': 3,       # 连续K线数量
        }
    
    def detect(self, klines: List[Dict]) -> Dict:
        """
        检测价格行为
        
        返回:
        {
            'breakout': True/False,      # 是否突破
            'direction': 'up'/'down',    # 突破方向
            'consecutive': 3,            # 连续同向K线数量
            'range_high': 100,           # 区间高点
            'range_low': 90,             # 区间低点
            'current_price': 105,        # 当前价格
        }
        """
        if len(klines) < self.config['lookback_period']:
            return {'breakout': False, 'direction': None}
        
        # 1. 计算近期区间
        recent = klines[-self.config['lookback_period']:]
        range_high = max(float(k['high']) for k in recent)
        range_low = min(float(k['low']) for k in recent)
        range_size = range_high - range_low
        
        # 2. 当前价格
        current_price = float(klines[-1]['close'])
        
        # 3. 判断是否突破
        breakout_up = current_price > range_high * (1 - self.config['breakout_threshold'])
        breakout_down = current_price < range_low * (1 + self.config['breakout_threshold'])
        
        # 4. 连续K线判断
        consecutive_up = self._count_consecutive(klines, 'up')
        consecutive_down = self._count_consecutive(klines, 'down')
        
        # 5. 综合判断
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
        """统计连续同向K线数量"""
        count = 0
        for k in reversed(klines):
            if direction == 'up' and float(k['close']) > float(k['open']):
                count += 1
            elif direction == 'down' and float(k['close']) < float(k['open']):
                count += 1
            else:
                break
        return count
```

### 3.2 波动率判断（实时性高）

```python
class VolatilityDetector:
    """波动率检测器"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'atr_period': 14,
            'expansion_threshold': 1.5,  # ATR扩张阈值
            'contraction_threshold': 0.7, # ATR收缩阈值
        }
        
        self._atr_history = []
    
    def detect(self, klines: List[Dict]) -> Dict:
        """
        检测波动率变化
        
        返回:
        {
            'atr': 100,                  # 当前ATR
            'atr_ma': 80,                # ATR均值
            'atr_ratio': 1.25,           # ATR比率
            'volatility_status': 'expanding',  # 波动率状态
        }
        """
        if len(klines) < self.config['atr_period'] * 2:
            return {'volatility_status': 'unknown'}
        
        # 1. 计算ATR
        atr = self._calculate_atr(klines, self.config['atr_period'])
        
        # 2. 计算ATR均值
        atr_ma = self._calculate_atr_ma(klines, self.config['atr_period'] * 2)
        
        # 3. 计算ATR比率
        atr_ratio = atr / atr_ma if atr_ma > 0 else 1.0
        
        # 4. 判断波动率状态
        if atr_ratio >= self.config['expansion_threshold']:
            status = 'expanding'  # 波动率扩张（可能是趋势开始）
        elif atr_ratio <= self.config['contraction_threshold']:
            status = 'contracting'  # 波动率收缩（可能是震荡）
        else:
            status = 'normal'  # 正常波动
        
        return {
            'atr': atr,
            'atr_ma': atr_ma,
            'atr_ratio': atr_ratio,
            'volatility_status': status,
        }
    
    def _calculate_atr(self, klines: List[Dict], period: int) -> float:
        """计算ATR"""
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
        """计算ATR均值"""
        atr_list = []
        for i in range(period, len(klines)):
            atr = self._calculate_atr(klines[:i+1], self.config['atr_period'])
            atr_list.append(atr)
        
        return sum(atr_list[-period:]) / len(atr_list) if atr_list else 0
```

### 3.3 组合判断算法

```python
class RealTimeStatusAlgorithm(StatusAlgorithm):
    """实时市场状态判断算法"""
    
    name = "realtime"
    description = "实时市场状态判断算法（价格行为+波动率）"
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            # 价格行为参数
            'lookback_period': 20,
            'breakout_threshold': 0.02,
            'consecutive_bars': 3,
            
            # 波动率参数
            'atr_period': 14,
            'expansion_threshold': 1.5,
            'contraction_threshold': 0.7,
            
            # 确认参数
            'confirm_periods': 2,  # 确认周期数
        }
        
        self.price_detector = PriceActionDetector(self.config)
        self.volatility_detector = VolatilityDetector(self.config)
        
        self._indicators = {}
        self._status_history = []  # 状态历史
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        """计算市场状态"""
        if len(klines) < self.config['lookback_period']:
            return StatusResult(
                status=MarketStatus.UNKNOWN,
                confidence=0.0,
                indicators={},
                reason="K线数据不足"
            )
        
        # 1. 价格行为判断
        price_result = self.price_detector.detect(klines)
        
        # 2. 波动率判断
        volatility_result = self.volatility_detector.detect(klines)
        
        # 3. 综合判断
        status, confidence, reason = self._determine_status(
            price_result, volatility_result
        )
        
        # 4. 状态确认（需要连续N周期一致）
        self._status_history.append(status)
        confirmed_status = self._confirm_status()
        
        # 保存指标
        self._indicators = {
            'price_action': price_result,
            'volatility': volatility_result,
            'status_history': [s.value for s in self._status_history[-5:]],
        }
        
        return StatusResult(
            status=confirmed_status,
            confidence=confidence,
            indicators=self._indicators,
            reason=reason
        )
    
    def _determine_status(self, price_result: Dict, 
                          volatility_result: Dict) -> Tuple[MarketStatus, float, str]:
        """综合判断市场状态"""
        reasons = []
        trend_signals = 0
        range_signals = 0
        
        # 1. 价格突破信号
        if price_result['breakout']:
            if price_result['direction'] == 'up':
                trend_signals += 2
                reasons.append(f"向上突破区间 {price_result['range_high']:.2f}")
            else:
                trend_signals += 2
                reasons.append(f"向下突破区间 {price_result['range_low']:.2f}")
        else:
            range_signals += 1
            reasons.append("价格在区间内")
        
        # 2. 连续K线信号
        if price_result['consecutive'] >= self.config['consecutive_bars']:
            trend_signals += 1
            reasons.append(f"连续{price_result['consecutive']}根同向K线")
        
        # 3. 波动率信号
        if volatility_result['volatility_status'] == 'expanding':
            trend_signals += 1
            reasons.append(f"波动率扩张 ATR比率={volatility_result['atr_ratio']:.2f}")
        elif volatility_result['volatility_status'] == 'contracting':
            range_signals += 1
            reasons.append(f"波动率收缩 ATR比率={volatility_result['atr_ratio']:.2f}")
        
        # 4. 判断结果
        if trend_signals >= 3:
            if price_result['direction'] == 'up':
                status = MarketStatus.TRENDING_UP
            else:
                status = MarketStatus.TRENDING_DOWN
            confidence = min(1.0, trend_signals / 4)
        elif range_signals >= 2:
            status = MarketStatus.RANGING
            confidence = min(1.0, range_signals / 3)
        else:
            status = MarketStatus.TRANSITIONING
            confidence = 0.5
        
        return status, confidence, ", ".join(reasons)
    
    def _confirm_status(self) -> MarketStatus:
        """确认状态（需要连续N周期一致）"""
        if len(self._status_history) < self.config['confirm_periods']:
            return self._status_history[-1] if self._status_history else MarketStatus.UNKNOWN
        
        recent = self._status_history[-self.config['confirm_periods']:]
        
        # 如果最近N周期状态一致，则确认
        if len(set(recent)) == 1:
            return recent[0]
        
        # 否则返回最近状态
        return self._status_history[-1]
    
    def get_required_periods(self) -> int:
        return max(
            self.config['lookback_period'],
            self.config['atr_period'] * 2
        )
    
    def get_indicators(self) -> Dict:
        return self._indicators
```

## 4. 区间划分输出

### 4.1 区间数据结构

```python
@dataclass
class MarketInterval:
    """市场区间"""
    start_time: int              # 开始时间
    end_time: int                # 结束时间
    status: MarketStatus         # 市场状态
    duration: int                # 持续时间（K线数量）
    price_range: Tuple[float, float]  # 价格区间 (low, high)
    indicators: Dict             # 关键指标
    
    def to_dict(self) -> Dict:
        return {
            'start_time': datetime.fromtimestamp(self.start_time / 1000).strftime('%Y-%m-%d %H:%M'),
            'end_time': datetime.fromtimestamp(self.end_time / 1000).strftime('%Y-%m-%d %H:%M'),
            'status': self.status.value,
            'duration': self.duration,
            'price_range': self.price_range,
            'indicators': self.indicators,
        }
```

### 4.2 区间分析器

```python
class IntervalAnalyzer:
    """区间分析器"""
    
    def __init__(self):
        self.intervals: List[MarketInterval] = []
        self._current_interval = None
    
    def update(self, timestamp: int, price: float, status: MarketStatus, indicators: Dict):
        """更新区间"""
        if self._current_interval is None:
            # 开始新区间
            self._current_interval = MarketInterval(
                start_time=timestamp,
                end_time=timestamp,
                status=status,
                duration=1,
                price_range=(price, price),
                indicators=indicators,
            )
        elif status == self._current_interval.status:
            # 继续当前区间
            self._current_interval.end_time = timestamp
            self._current_interval.duration += 1
            low, high = self._current_interval.price_range
            self._current_interval.price_range = (min(low, price), max(high, price))
        else:
            # 状态变化，保存当前区间，开始新区间
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
        """获取所有区间"""
        result = [i.to_dict() for i in self.intervals]
        if self._current_interval:
            result.append(self._current_interval.to_dict())
        return result
    
    def get_statistics(self) -> Dict:
        """获取区间统计"""
        all_intervals = self.intervals + ([self._current_interval] if self._current_interval else [])
        
        if not all_intervals:
            return {}
        
        ranging = [i for i in all_intervals if i.status == MarketStatus.RANGING]
        trending_up = [i for i in all_intervals if i.status == MarketStatus.TRENDING_UP]
        trending_down = [i for i in all_intervals if i.status == MarketStatus.TRENDING_DOWN]
        
        return {
            'total_intervals': len(all_intervals),
            'ranging': {
                'count': len(ranging),
                'avg_duration': sum(i.duration for i in ranging) / len(ranging) if ranging else 0,
                'total_duration': sum(i.duration for i in ranging),
            },
            'trending_up': {
                'count': len(trending_up),
                'avg_duration': sum(i.duration for i in trending_up) / len(trending_up) if trending_up else 0,
                'total_duration': sum(i.duration for i in trending_up),
            },
            'trending_down': {
                'count': len(trending_down),
                'avg_duration': sum(i.duration for i in trending_down) / len(trending_down) if trending_down else 0,
                'total_duration': sum(i.duration for i in trending_down),
            },
        }
```

## 5. 策略切换接口

### 5.1 切换决策器

```python
class StrategySwitcher:
    """策略切换决策器"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'min_interval_duration': 5,  # 最小区间持续时间
            'switch_threshold': 0.7,     # 切换置信度阈值
        }
        
        self._current_strategy = 'ranging'  # 当前策略
        self._switch_history = []
    
    def should_switch(self, status: MarketStatus, confidence: float, 
                      duration: int) -> Tuple[bool, str]:
        """
        判断是否应该切换策略
        
        返回: (是否切换, 目标策略)
        """
        # 1. 持续时间检查
        if duration < self.config['min_interval_duration']:
            return False, self._current_strategy
        
        # 2. 置信度检查
        if confidence < self.config['switch_threshold']:
            return False, self._current_strategy
        
        # 3. 确定目标策略
        if status == MarketStatus.RANGING:
            target_strategy = 'ranging'
        elif status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]:
            target_strategy = 'trending'
        else:
            return False, self._current_strategy
        
        # 4. 判断是否需要切换
        if target_strategy != self._current_strategy:
            # 记录切换
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
        """获取当前策略"""
        return self._current_strategy
    
    def get_switch_history(self) -> List[Dict]:
        """获取切换历史"""
        return self._switch_history
```

## 6. 完整集成示例

```python
class RealTimeMarketAnalyzer:
    """实时市场分析器"""
    
    def __init__(self, config: Dict = None):
        self.algorithm = RealTimeStatusAlgorithm(config)
        self.interval_analyzer = IntervalAnalyzer()
        self.strategy_switcher = StrategySwitcher(config)
        
        self._klines = []
    
    def update(self, kline: Dict) -> Dict:
        """
        更新市场分析
        
        返回:
        {
            'status': MarketStatus,
            'confidence': float,
            'should_switch': bool,
            'target_strategy': str,
            'interval': MarketInterval,
        }
        """
        self._klines.append(kline)
        
        # 保持足够的K线数量
        required = self.algorithm.get_required_periods()
        if len(self._klines) > required * 2:
            self._klines = self._klines[-required * 2:]
        
        # 1. 计算市场状态
        result = self.algorithm.calculate(self._klines, {})
        
        # 2. 更新区间分析
        self.interval_analyzer.update(
            kline['timestamp'],
            float(kline['close']),
            result.status,
            result.indicators
        )
        
        # 3. 判断策略切换
        current_interval = self.interval_analyzer._current_interval
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
            'interval': current_interval.to_dict() if current_interval else None,
        }
```

## 7. 实时性对比

| 指标 | EMA均线方案 | 实时方案 |
|------|-------------|----------|
| **价格突破检测** | 滞后3-100天 | 实时（当天） |
| **波动率变化** | 滞后14-28天 | 滞后1-2天 |
| **状态切换延迟** | 5-10天 | 1-3天 |
| **可靠性** | 高 | 中高 |

## 8. 实施步骤

### 步骤 1：实现核心算法

创建 `realtime_status_detector.py`：
- `PriceActionDetector` 类
- `VolatilityDetector` 类
- `RealTimeStatusAlgorithm` 类

### 步骤 2：实现区间分析

创建 `interval_analyzer.py`：
- `MarketInterval` 数据类
- `IntervalAnalyzer` 类

### 步骤 3：实现策略切换

创建 `strategy_switcher.py`：
- `StrategySwitcher` 类
- `RealTimeMarketAnalyzer` 类

### 步骤 4：集成测试

1. 回测验证
2. 实盘模拟
3. 参数优化

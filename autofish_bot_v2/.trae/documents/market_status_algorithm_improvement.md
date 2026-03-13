# 行情判断算法改进方案

## 当前问题分析

### 1. 震荡区间识别太短
- 当前 `lookback_period` 只有 20 天
- 状态切换频繁，震荡区间只有 1-几天
- 与人工看K线判断差距大

### 2. 当前算法局限性

| 问题 | 当前实现 | 人工判断 |
|------|----------|----------|
| 回看周期 | 20 天 | 数周到数月 |
| 支撑阻力 | 无 | 关键参考 |
| 箱体识别 | 无 | 核心概念 |
| 时间框架 | 单一 | 多框架确认 |
| 震荡持续 | 不考虑 | 核心特征 |

### 3. 人工判断震荡的核心要素

1. **价格区间明确**: 有清晰的支撑位和阻力位
2. **持续时间长**: 通常数周到数月
3. **多次测试**: 价格多次触及支撑/阻力后反弹
4. **成交量特征**: 震荡期间成交量萎缩
5. **突破确认**: 需要有效突破（放量、收盘确认）

---

## 改进方案

### 方案一：增加支撑阻力位识别

**核心思想**: 震荡行情的本质是价格在支撑位和阻力位之间波动

```python
class SupportResistanceDetector:
    """支撑阻力位检测器"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'lookback_period': 60,      # 回看60天
            'touch_threshold': 0.02,    # 触及阈值 2%
            'min_touches': 3,           # 最少触及次数
            'merge_threshold': 0.03,    # 合并阈值 3%
        }
    
    def detect(self, klines: List[Dict]) -> Dict:
        """检测支撑阻力位"""
        # 1. 找出所有局部高点和低点
        swing_highs = self._find_swing_highs(klines)
        swing_lows = self._find_swing_lows(klines)
        
        # 2. 聚类找出关键阻力位
        resistance_levels = self._cluster_levels(swing_highs)
        
        # 3. 聚类找出关键支撑位
        support_levels = self._cluster_levels(swing_lows)
        
        # 4. 计算区间宽度
        if resistance_levels and support_levels:
            range_width = (resistance_levels[0] - support_levels[0]) / support_levels[0]
        else:
            range_width = None
        
        return {
            'resistance': resistance_levels,
            'support': support_levels,
            'range_width': range_width,
            'is_ranging': range_width is not None and range_width < 0.15,  # 区间宽度 < 15%
        }
    
    def _find_swing_highs(self, klines: List[Dict], window: int = 5) -> List[float]:
        """找出局部高点"""
        highs = []
        for i in range(window, len(klines) - window):
            is_high = True
            for j in range(i - window, i + window + 1):
                if float(klines[j]['high']) > float(klines[i]['high']):
                    is_high = False
                    break
            if is_high:
                highs.append(float(klines[i]['high']))
        return highs
    
    def _find_swing_lows(self, klines: List[Dict], window: int = 5) -> List[float]:
        """找出局部低点"""
        lows = []
        for i in range(window, len(klines) - window):
            is_low = True
            for j in range(i - window, i + window + 1):
                if float(klines[j]['low']) < float(klines[i]['low']):
                    is_low = False
                    break
            if is_low:
                lows.append(float(klines[i]['low']))
        return lows
    
    def _cluster_levels(self, prices: List[float]) -> List[float]:
        """聚类合并相近的价格水平"""
        if not prices:
            return []
        
        prices = sorted(prices)
        clusters = [[prices[0]]]
        
        for price in prices[1:]:
            if abs(price - clusters[-1][-1]) / clusters[-1][-1] < self.config['merge_threshold']:
                clusters[-1].append(price)
            else:
                clusters.append([price])
        
        # 只保留触及次数足够的水平
        levels = []
        for cluster in clusters:
            if len(cluster) >= self.config['min_touches']:
                levels.append(sum(cluster) / len(cluster))
        
        return levels
```

### 方案二：箱体震荡识别算法

**核心思想**: 识别价格在固定区间内反复波动的形态

```python
class BoxRangeDetector:
    """箱体震荡检测器"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'min_duration': 10,          # 最少持续天数
            'max_range_pct': 0.15,       # 最大区间宽度 15%
            'min_touches': 4,            # 最少触及次数（上下各2次）
            'breakout_threshold': 0.03,  # 突破阈值
            'lookback_period': 90,       # 回看周期
        }
    
    def detect(self, klines: List[Dict]) -> Dict:
        """检测箱体震荡"""
        if len(klines) < self.config['min_duration']:
            return {'is_box': False, 'reason': '数据不足'}
        
        # 使用最近的数据
        recent = klines[-self.config['lookback_period']:]
        
        # 计算价格区间
        highs = [float(k['high']) for k in recent]
        lows = [float(k['low']) for k in recent]
        
        box_high = max(highs)
        box_low = min(lows)
        box_mid = (box_high + box_low) / 2
        range_pct = (box_high - box_low) / box_mid
        
        # 检查区间宽度
        if range_pct > self.config['max_range_pct']:
            return {
                'is_box': False,
                'reason': f'区间宽度 {range_pct:.1%} 超过阈值 {self.config["max_range_pct"]:.1%}'
            }
        
        # 计算触及次数
        upper_touches = sum(1 for h in highs if h >= box_high * (1 - 0.01))
        lower_touches = sum(1 for l in lows if l <= box_low * (1 + 0.01))
        
        if upper_touches < 2 or lower_touches < 2:
            return {
                'is_box': False,
                'reason': f'触及次数不足: 上{upper_touches}次, 下{lower_touches}次'
            }
        
        # 检查持续时间
        duration = len(recent)
        
        return {
            'is_box': True,
            'box_high': box_high,
            'box_low': box_low,
            'box_mid': box_mid,
            'range_pct': range_pct,
            'upper_touches': upper_touches,
            'lower_touches': lower_touches,
            'duration': duration,
            'reason': f'箱体震荡: {box_low:.2f} - {box_high:.2f}, 持续{duration}天'
        }
```

### 方案三：多时间框架确认

**核心思想**: 使用多个时间框架确认行情状态

```python
class MultiTimeframeDetector:
    """多时间框架检测器"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'timeframes': ['1d', '1w'],  # 日线和周线
            'weight': {'1d': 0.4, '1w': 0.6},  # 周线权重更高
        }
        self.detectors = {
            '1d': BoxRangeDetector({'lookback_period': 60}),
            '1w': BoxRangeDetector({'lookback_period': 26}),  # 半年
        }
    
    def detect(self, klines_1d: List[Dict], klines_1w: List[Dict]) -> Dict:
        """多时间框架检测"""
        results = {}
        
        # 日线检测
        results['1d'] = self.detectors['1d'].detect(klines_1d)
        
        # 周线检测
        results['1w'] = self.detectors['1w'].detect(klines_1w)
        
        # 综合判断
        is_ranging = (
            results['1d'].get('is_box', False) and 
            results['1w'].get('is_box', False)
        )
        
        # 如果周线是趋势，日线是震荡，以周线为准
        if not results['1w'].get('is_box', True):
            is_ranging = False
        
        return {
            'is_ranging': is_ranging,
            'daily': results['1d'],
            'weekly': results['1w'],
            'reason': self._get_reason(results)
        }
```

### 方案四：改进的行情判断算法

```python
class ImprovedStatusAlgorithm(StatusAlgorithm):
    """改进的行情判断算法
    
    核心改进：
    1. 更长的回看周期（60-90天）
    2. 支撑阻力位识别
    3. 箱体震荡识别
    4. 多时间框架确认
    5. 更严格的趋势确认
    """
    
    name = "improved"
    description = "改进的行情判断算法（支撑阻力+箱体震荡+多时间框架）"
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'lookback_period': 60,
            'min_range_duration': 10,
            'max_range_pct': 0.15,
            'breakout_confirm_days': 3,
            'volume_confirm': True,
        }
        
        self.sr_detector = SupportResistanceDetector()
        self.box_detector = BoxRangeDetector()
        
        self._current_status = MarketStatus.UNKNOWN
        self._status_start_time = None
        self._range_high = None
        self._range_low = None
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        if len(klines) < self.config['lookback_period']:
            return StatusResult(
                status=MarketStatus.UNKNOWN,
                confidence=0.0,
                indicators={},
                reason="K线数据不足"
            )
        
        # 1. 检测支撑阻力位
        sr_result = self.sr_detector.detect(klines)
        
        # 2. 检测箱体震荡
        box_result = self.box_detector.detect(klines)
        
        # 3. 检测趋势突破
        breakout_result = self._detect_breakout(klines, sr_result)
        
        # 4. 综合判断
        status, confidence, reason = self._determine_status(
            sr_result, box_result, breakout_result, klines
        )
        
        indicators = {
            'support': sr_result.get('support', []),
            'resistance': sr_result.get('resistance', []),
            'box': box_result if box_result.get('is_box') else None,
            'breakout': breakout_result,
        }
        
        return StatusResult(
            status=status,
            confidence=confidence,
            indicators=indicators,
            reason=reason
        )
    
    def _detect_breakout(self, klines: List[Dict], sr_result: Dict) -> Dict:
        """检测趋势突破"""
        if not sr_result.get('support') or not sr_result.get('resistance'):
            return {'breakout': False}
        
        current_price = float(klines[-1]['close'])
        resistance = sr_result['resistance'][0]
        support = sr_result['support'][0]
        
        # 向上突破
        if current_price > resistance * 1.02:  # 突破阻力位 2%
            return {
                'breakout': True,
                'direction': 'up',
                'level': resistance,
                'price': current_price,
            }
        
        # 向下突破
        if current_price < support * 0.98:  # 跌破支撑位 2%
            return {
                'breakout': True,
                'direction': 'down',
                'level': support,
                'price': current_price,
            }
        
        return {'breakout': False}
    
    def _determine_status(self, sr_result, box_result, breakout_result, klines):
        """综合判断行情状态"""
        
        # 如果有突破，判断为趋势
        if breakout_result.get('breakout'):
            direction = breakout_result['direction']
            if direction == 'up':
                return MarketStatus.TRENDING_UP, 0.8, f"向上突破 {breakout_result['level']:.2f}"
            else:
                return MarketStatus.TRENDING_DOWN, 0.8, f"向下突破 {breakout_result['level']:.2f}"
        
        # 如果是箱体震荡
        if box_result.get('is_box'):
            return (
                MarketStatus.RANGING,
                0.9,
                f"箱体震荡 {box_result['box_low']:.2f} - {box_result['box_high']:.2f}, "
                f"持续 {box_result['duration']} 天"
            )
        
        # 如果有明确的支撑阻力
        if sr_result.get('is_ranging'):
            support = sr_result['support'][0] if sr_result['support'] else 0
            resistance = sr_result['resistance'][0] if sr_result['resistance'] else 0
            return (
                MarketStatus.RANGING,
                0.7,
                f"震荡区间 {support:.2f} - {resistance:.2f}"
            )
        
        # 默认判断
        return MarketStatus.TRANSITIONING, 0.5, "行情状态不明确"
    
    def get_required_periods(self) -> int:
        return self.config['lookback_period']
```

---

## 实施步骤

### 步骤 1: 添加支撑阻力检测器
在 `market_status_detector.py` 中添加 `SupportResistanceDetector` 类

### 步骤 2: 添加箱体震荡检测器
添加 `BoxRangeDetector` 类

### 步骤 3: 创建改进算法
添加 `ImprovedStatusAlgorithm` 类

### 步骤 4: 注册新算法
在 `MarketStatusDetector.ALGORITHMS` 中注册

### 步骤 5: 回测验证
使用历史数据验证新算法的效果

---

## 参数调优建议

| 参数 | 当前值 | 建议值 | 说明 |
|------|--------|--------|------|
| lookback_period | 20 | 60-90 | 更长的回看周期 |
| min_range_duration | 5 | 10-15 | 更长的震荡持续时间 |
| max_range_pct | - | 0.15 | 最大区间宽度 15% |
| breakout_threshold | 0.02 | 0.03 | 更严格的突破确认 |
| min_touches | - | 3-4 | 最少触及次数 |

---

## 预期效果

1. **震荡区间更长**: 从 1-几天 提升到 数周-数月
2. **更接近人工判断**: 基于支撑阻力和箱体形态
3. **减少误判**: 多条件确认，避免频繁切换
4. **更好的交易时机**: 明确震荡边界，知道何时交易何时避开

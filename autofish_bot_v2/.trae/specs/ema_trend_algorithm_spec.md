# 多EMA均线趋势判断算法设计规格

## 1. 需求分析

### 1.1 用户理解

- **趋势行情**：会持续一段时间（上涨或下跌）
- **震荡行情**：也会持续一段时间
- **需要判断**：当前处于哪种行情，以及行情的持续性

### 1.2 目标

设计一个基于多EMA均线的趋势判断算法：
1. 使用多EMA均线判断趋势方向和强度
2. 支持辅助指标（ADX、ATR等）
3. 支持多周期判断
4. 识别趋势/震荡的持续性

## 2. 算法设计

### 2.1 多EMA均线系统

#### 均线配置

| 均线 | 周期 | 作用 |
|------|------|------|
| EMA7 | 7 | 短期趋势，快速反应 |
| EMA25 | 25 | 中期趋势 |
| EMA99 | 99 | 长期趋势，主要支撑/阻力 |
| EMA200 | 200 | 超长期趋势，牛熊分界 |

#### 均线排列判断

```
多头排列（上涨趋势）：
EMA7 > EMA25 > EMA99 > EMA200

空头排列（下跌趋势）：
EMA7 < EMA25 < EMA99 < EMA200

震荡排列（无明确趋势）：
均线交织，无明显排列顺序
```

### 2.2 趋势强度指标

#### 均线发散度

```python
def calculate_ema_divergence(ema7, ema25, ema99, ema200):
    """
    计算均线发散度
    
    发散度越大，趋势越强
    发散度越小，越接近震荡
    """
    # 短期发散度
    short_divergence = abs(ema7 - ema25) / ema25 * 100
    
    # 中期发散度
    mid_divergence = abs(ema25 - ema99) / ema99 * 100
    
    # 长期发散度
    long_divergence = abs(ema99 - ema200) / ema200 * 100
    
    # 综合发散度（加权平均）
    total_divergence = (
        short_divergence * 0.5 + 
        mid_divergence * 0.3 + 
        long_divergence * 0.2
    )
    
    return total_divergence
```

#### 均线斜率

```python
def calculate_ema_slope(ema_values, period=5):
    """
    计算均线斜率
    
    斜率 > 0: 上升趋势
    斜率 < 0: 下降趋势
    斜率接近 0: 横盘震荡
    """
    if len(ema_values) < period:
        return 0
    
    recent = ema_values[-period:]
    slope = (recent[-1] - recent[0]) / recent[0] * 100
    
    return slope
```

### 2.3 辅助指标

#### ADX（趋势强度）

- ADX < 20：无明显趋势
- ADX 20-25：趋势形成中
- ADX 25-50：强趋势
- ADX > 50：极强趋势

#### ATR（波动率）

- ATR 扩大：波动率增加，可能是趋势开始
- ATR 收缩：波动率减少，可能是震荡

#### 布林带宽度

- 宽度扩张：趋势行情
- 宽度收缩：震荡行情

### 2.4 多周期判断

#### 周期配置

| 周期 | 作用 |
|------|------|
| 1d | 主要趋势判断 |
| 4h | 中期趋势确认 |
| 1h | 短期趋势确认 |

#### 多周期共振

```
趋势确认条件：
1. 大周期（1d）趋势方向明确
2. 中周期（4h）趋势方向一致
3. 小周期（1h）趋势方向一致

震荡确认条件：
1. 大周期（1d）均线交织
2. 中周期（4h）均线交织
3. 小周期（1h）均线交织
```

### 2.5 行情持续性判断

#### 趋势持续时间

```python
class TrendDuration:
    """趋势持续时间跟踪"""
    
    def __init__(self):
        self.current_trend = None
        self.trend_start_time = None
        self.trend_duration = 0
        self.trend_history = []
    
    def update(self, new_trend, timestamp):
        """更新趋势状态"""
        if new_trend != self.current_trend:
            # 趋势变化，记录历史
            if self.current_trend is not None:
                self.trend_history.append({
                    'trend': self.current_trend,
                    'start_time': self.trend_start_time,
                    'end_time': timestamp,
                    'duration': self.trend_duration,
                })
            
            # 开始新趋势
            self.current_trend = new_trend
            self.trend_start_time = timestamp
            self.trend_duration = 1
        else:
            # 趋势持续
            self.trend_duration += 1
    
    def get_average_duration(self, trend_type, lookback=10):
        """获取某类趋势的平均持续时间"""
        durations = [
            h['duration'] for h in self.trend_history[-lookback:]
            if h['trend'] == trend_type
        ]
        return sum(durations) / len(durations) if durations else 0
```

## 3. 算法实现

### 3.1 EMA趋势算法类

```python
class EMATrendAlgorithm(StatusAlgorithm):
    """多EMA均线趋势判断算法"""
    
    name = "ema_trend"
    description = "多EMA均线趋势判断算法"
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'ema_periods': [7, 25, 99, 200],
            'divergence_threshold': 2.0,  # 发散度阈值
            'slope_threshold': 0.5,       # 斜率阈值
            'adx_threshold': 25,
            'use_multi_timeframe': False,
            'min_trend_duration': 3,      # 最小趋势持续时间
        }
        
        self._indicators = {}
        self._trend_tracker = TrendDuration()
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        """计算市场状态"""
        if len(klines) < max(self.config['ema_periods']):
            return StatusResult(
                status=MarketStatus.UNKNOWN,
                confidence=0.0,
                indicators={},
                reason="K线数据不足"
            )
        
        closes = [float(k['close']) for k in klines]
        
        # 1. 计算EMA均线
        ema_values = {}
        for period in self.config['ema_periods']:
            ema_values[period] = self._calculate_ema(closes, period)
        
        # 2. 判断均线排列
        arrangement = self._check_arrangement(ema_values)
        
        # 3. 计算发散度
        divergence = self._calculate_divergence(ema_values)
        
        # 4. 计算斜率
        slopes = {}
        for period in self.config['ema_periods']:
            slopes[period] = self._calculate_slope(ema_values[period])
        
        # 5. 计算ADX
        adx = self._calculate_adx(klines)
        
        # 6. 综合判断
        status, confidence, reason = self._determine_status(
            arrangement, divergence, slopes, adx
        )
        
        # 7. 更新趋势跟踪
        self._trend_tracker.update(status, klines[-1]['timestamp'])
        
        # 保存指标
        self._indicators = {
            'ema': {f'ema{p}': v[-1] for p, v in ema_values.items()},
            'arrangement': arrangement,
            'divergence': divergence,
            'slopes': {f'slope_ema{p}': s for p, s in slopes.items()},
            'adx': adx,
            'trend_duration': self._trend_tracker.trend_duration,
        }
        
        return StatusResult(
            status=status,
            confidence=confidence,
            indicators=self._indicators,
            reason=reason
        )
    
    def _calculate_ema(self, closes: List[float], period: int) -> List[float]:
        """计算EMA"""
        multiplier = 2 / (period + 1)
        ema = [closes[0]]
        
        for i in range(1, len(closes)):
            ema.append((closes[i] - ema[-1]) * multiplier + ema[-1])
        
        return ema
    
    def _check_arrangement(self, ema_values: Dict) -> str:
        """检查均线排列"""
        ema7 = ema_values[7][-1]
        ema25 = ema_values[25][-1]
        ema99 = ema_values[99][-1]
        ema200 = ema_values[200][-1]
        
        if ema7 > ema25 > ema99 > ema200:
            return 'bullish'  # 多头排列
        elif ema7 < ema25 < ema99 < ema200:
            return 'bearish'  # 空头排列
        else:
            return 'mixed'    # 混合排列
    
    def _calculate_divergence(self, ema_values: Dict) -> float:
        """计算均线发散度"""
        ema7 = ema_values[7][-1]
        ema25 = ema_values[25][-1]
        ema99 = ema_values[99][-1]
        ema200 = ema_values[200][-1]
        
        short = abs(ema7 - ema25) / ema25 * 100
        mid = abs(ema25 - ema99) / ema99 * 100
        long = abs(ema99 - ema200) / ema200 * 100
        
        return short * 0.5 + mid * 0.3 + long * 0.2
    
    def _calculate_slope(self, ema_values: List[float], period: int = 5) -> float:
        """计算斜率"""
        if len(ema_values) < period:
            return 0
        
        recent = ema_values[-period:]
        return (recent[-1] - recent[0]) / recent[0] * 100
    
    def _determine_status(self, arrangement: str, divergence: float, 
                          slopes: Dict, adx: float) -> Tuple[MarketStatus, float, str]:
        """综合判断市场状态"""
        reasons = []
        trend_score = 0
        
        # 1. 均线排列贡献
        if arrangement == 'bullish':
            trend_score += 30
            reasons.append("多头排列")
        elif arrangement == 'bearish':
            trend_score += 30
            reasons.append("空头排列")
        
        # 2. 发散度贡献
        if divergence >= self.config['divergence_threshold']:
            trend_score += 25
            reasons.append(f"发散度={divergence:.2f}%")
        
        # 3. 斜率贡献
        slope_ema25 = slopes.get(25, 0)
        if abs(slope_ema25) >= self.config['slope_threshold']:
            trend_score += 25
            reasons.append(f"EMA25斜率={slope_ema25:.2f}%")
        
        # 4. ADX贡献
        if adx >= self.config['adx_threshold']:
            trend_score += 20
            reasons.append(f"ADX={adx:.2f}")
        
        # 判断结果
        if trend_score >= 70:
            # 强趋势
            if arrangement == 'bullish' or slope_ema25 > 0:
                status = MarketStatus.TRENDING_UP
            else:
                status = MarketStatus.TRENDING_DOWN
            confidence = min(1.0, trend_score / 100)
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
        
        return status, confidence, reason
    
    def get_required_periods(self) -> int:
        return max(self.config['ema_periods']) + 50
    
    def get_indicators(self) -> Dict:
        return self._indicators
```

### 3.2 多周期算法类

```python
class MultiTimeframeAlgorithm(StatusAlgorithm):
    """多周期趋势判断算法"""
    
    name = "multi_timeframe"
    description = "多周期趋势判断算法"
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'timeframes': ['1d', '4h', '1h'],
            'ema_periods': [7, 25, 99, 200],
            'weights': {
                '1d': 0.5,   # 日线权重
                '4h': 0.3,   # 4小时权重
                '1h': 0.2,   # 1小时权重
            },
        }
        
        # 每个周期的算法
        self._tf_algorithms = {
            tf: EMATrendAlgorithm({'ema_periods': self.config['ema_periods']})
            for tf in self.config['timeframes']
        }
        
        self._indicators = {}
    
    async def calculate_multi(self, klines_by_tf: Dict[str, List[Dict]], 
                               config: Dict) -> StatusResult:
        """
        多周期计算
        
        参数:
            klines_by_tf: 按周期分组的K线数据
                {'1d': [...], '4h': [...], '1h': [...]}
        """
        results = {}
        
        # 1. 计算每个周期的状态
        for tf, klines in klines_by_tf.items():
            if tf in self._tf_algorithms:
                results[tf] = self._tf_algorithms[tf].calculate(klines, config)
        
        # 2. 加权综合
        weighted_score = {
            MarketStatus.TRENDING_UP: 0,
            MarketStatus.TRENDING_DOWN: 0,
            MarketStatus.RANGING: 0,
            MarketStatus.TRANSITIONING: 0,
        }
        
        for tf, result in results.items():
            weight = self.config['weights'].get(tf, 0)
            weighted_score[result.status] += weight * result.confidence
        
        # 3. 确定最终状态
        final_status = max(weighted_score, key=weighted_score.get)
        final_confidence = weighted_score[final_status]
        
        # 4. 生成原因
        reasons = []
        for tf, result in results.items():
            reasons.append(f"{tf}: {result.status.value}({result.confidence:.0%})")
        
        # 保存指标
        self._indicators = {
            'tf_results': {tf: {
                'status': r.status.value,
                'confidence': r.confidence,
                'indicators': r.indicators,
            } for tf, r in results.items()},
            'weighted_score': {k.value: v for k, v in weighted_score.items()},
        }
        
        return StatusResult(
            status=final_status,
            confidence=final_confidence,
            indicators=self._indicators,
            reason=" | ".join(reasons)
        )
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        """单周期计算（降级使用）"""
        algo = EMATrendAlgorithm({'ema_periods': self.config['ema_periods']})
        return algo.calculate(klines, config)
    
    def get_required_periods(self) -> int:
        return max(self.config['ema_periods']) + 50
    
    def get_indicators(self) -> Dict:
        return self._indicators
```

## 4. 算法对比

### 4.1 算法特点

| 算法 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **ADX** | 明确趋势强度 | 滞后性 | 趋势强度判断 |
| **EMA趋势** | 直观、反应快 | 震荡时假信号多 | 趋势方向判断 |
| **组合算法** | 综合多指标 | 参数复杂 | 通用场景 |
| **多周期** | 更可靠 | 需要多周期数据 | 精确判断 |

### 4.2 推荐配置

```python
# 震荡策略推荐配置
RANGING_STRATEGY_CONFIG = {
    'algorithm': 'ema_trend',
    'ema_periods': [7, 25, 99, 200],
    'divergence_threshold': 2.0,
    'slope_threshold': 0.5,
    'min_trend_duration': 3,
    'use_multi_timeframe': True,
    'timeframes': ['1d', '4h'],
}

# 趋势策略推荐配置
TRENDING_STRATEGY_CONFIG = {
    'algorithm': 'multi_timeframe',
    'ema_periods': [7, 25, 99, 200],
    'timeframes': ['1d', '4h', '1h'],
    'weights': {'1d': 0.5, '4h': 0.3, '1h': 0.2},
}
```

## 5. 实施步骤

### 步骤 1：实现 EMA 趋势算法

在 `market_status_detector.py` 中添加：
- `EMATrendAlgorithm` 类
- `TrendDuration` 类

### 步骤 2：实现多周期算法

在 `market_status_detector.py` 中添加：
- `MultiTimeframeAlgorithm` 类

### 步骤 3：更新命令行接口

添加参数：
- `--algorithm ema_trend`
- `--algorithm multi_timeframe`
- `--timeframes 1d,4h,1h`

### 步骤 4：测试验证

1. 测试 EMA 趋势算法
2. 测试多周期算法
3. 对比不同算法的结果

## 6. 测试用例

### 6.1 EMA 趋势算法测试

| 测试 | 均线排列 | 发散度 | 斜率 | ADX | 预期结果 |
|------|----------|--------|------|-----|----------|
| 多头趋势 | EMA7>25>99>200 | 3% | 1% | 30 | TRENDING_UP |
| 空头趋势 | EMA7<25<99<200 | 3% | -1% | 30 | TRENDING_DOWN |
| 震荡 | 混合 | 1% | 0.2% | 15 | RANGING |

### 6.2 多周期算法测试

| 测试 | 1d | 4h | 1h | 预期结果 |
|------|-----|-----|-----|----------|
| 共振上涨 | TRENDING_UP | TRENDING_UP | TRENDING_UP | TRENDING_UP |
| 共振下跌 | TRENDING_DOWN | TRENDING_DOWN | TRENDING_DOWN | TRENDING_DOWN |
| 分歧 | TRENDING_UP | RANGING | TRENDING_DOWN | TRANSITIONING |
| 震荡 | RANGING | RANGING | RANGING | RANGING |

## 7. 预期效果

### 7.1 趋势识别

- **更早识别趋势**：EMA 均线反应更快
- **更准确判断**：多周期共振确认
- **持续性跟踪**：记录趋势持续时间

### 7.2 震荡识别

- **均线交织**：明确震荡特征
- **发散度低**：量化震荡程度
- **斜率接近0**：横盘确认

### 7.3 实盘应用

```python
# 实盘使用示例
detector = MarketStatusDetector(algorithm=EMATrendAlgorithm())

# 更新行情
status = detector.update(kline)

# 判断是否交易
if status == MarketStatus.RANGING:
    # 震荡行情，执行网格策略
    execute_grid_strategy()
else:
    # 趋势行情，停止交易
    logger.info(f"趋势行情: {status.value}, 停止交易")
```

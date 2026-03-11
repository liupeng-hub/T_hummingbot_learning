# 市场行情判断器 (Market Status Detector)

## 模块概述

**源文件**: `market_status_detector.py`

**功能**: 判断当前市场处于震荡行情还是趋势行情

**核心特性**:
- 支持多种算法替换
- 可嵌入到回测和实盘代码中
- 生成行情分析报告

## 核心数据结构

### MarketStatus 枚举

市场状态定义：

| 状态 | 值 | 说明 |
|------|-----|------|
| RANGING | ranging | 震荡行情 |
| TRENDING_UP | trending_up | 上涨趋势 |
| TRENDING_DOWN | trending_down | 下跌趋势 |
| TRANSITIONING | transitioning | 过渡状态 |
| UNKNOWN | unknown | 未知状态 |

```python
class MarketStatus(Enum):
    RANGING = "ranging"
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    TRANSITIONING = "transitioning"
    UNKNOWN = "unknown"
```

### StatusResult 数据类

行情判断结果封装：

| 字段 | 类型 | 说明 |
|------|------|------|
| status | MarketStatus | 市场状态 |
| confidence | float | 置信度 (0-1) |
| indicators | Dict | 指标值 |
| reason | str | 判断原因 |

```python
@dataclass
class StatusResult:
    status: MarketStatus
    confidence: float
    indicators: Dict
    reason: str
```

### MarketInterval 数据类

市场区间记录：

| 字段 | 类型 | 说明 |
|------|------|------|
| start_time | int | 开始时间戳 |
| end_time | int | 结束时间戳 |
| status | MarketStatus | 市场状态 |
| duration | int | 持续K线数 |
| price_range | Tuple[float, float] | 价格区间 |
| indicators | Dict | 指标值 |

## 检测器组件

### PriceActionDetector

价格行为检测器，实时性最高，滞后0-1天。

**配置参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| lookback_period | 20 | 回看K线数 |
| breakout_threshold | 0.02 | 突破阈值 (2%) |
| consecutive_bars | 3 | 连续同向K线数 |

**检测逻辑**:
1. 计算回看周期内的最高价和最低价
2. 判断当前价格是否突破区间
3. 统计连续同向K线数量

**返回结果**:
```python
{
    'breakout': True/False,
    'direction': 'up'/'down'/None,
    'consecutive': int,
    'range_high': float,
    'range_low': float,
    'current_price': float,
}
```

### VolatilityDetector

波动率检测器，实时性高，滞后1-2天。

**配置参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| atr_period | 14 | ATR周期 |
| expansion_threshold | 1.5 | 扩张阈值 |
| contraction_threshold | 0.7 | 收缩阈值 |

**检测逻辑**:
1. 计算 ATR (Average True Range)
2. 计算 ATR 均值
3. 判断波动率状态

**返回结果**:
```python
{
    'atr': float,
    'atr_ma': float,
    'atr_ratio': float,
    'volatility_status': 'expanding'/'contracting'/'normal',
}
```

## 算法体系

### 类继承关系

```
StatusAlgorithm (抽象基类)
├── RealTimeStatusAlgorithm (实时判断算法)
├── ADXAlgorithm (ADX趋势强度算法)
├── CompositeAlgorithm (组合算法)
└── AlwaysRangingAlgorithm (始终震荡算法)
```

### StatusAlgorithm 抽象基类

```python
class StatusAlgorithm(ABC):
    name: str = "base"
    description: str = "基础算法"
    
    @abstractmethod
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        """计算市场状态"""
        pass
    
    @abstractmethod
    def get_required_periods(self) -> int:
        """获取算法所需的最小K线数量"""
        pass
    
    def get_indicators(self) -> Dict:
        """获取算法计算的指标值"""
        return {}
```

### RealTimeStatusAlgorithm

实时市场状态判断算法，结合价格行为和波动率判断。

**特点**:
- 状态惯性机制：需要更强的信号才能切换状态
- 震荡状态更稳定
- 防止频繁切换

**配置参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| lookback_period | 20 | 回看K线数 |
| breakout_threshold | 0.02 | 突破阈值 |
| consecutive_bars | 3 | 连续同向K线数 |
| atr_period | 14 | ATR周期 |
| expansion_threshold | 1.5 | 波动率扩张阈值 |
| contraction_threshold | 0.7 | 波动率收缩阈值 |
| confirm_periods | 2 | 确认周期数 |
| min_trend_signals | 4 | 最小趋势信号数 |
| status_inertia | True | 启用状态惯性 |
| min_trend_confidence | 0.8 | 最小趋势置信度 |
| min_range_duration | 5 | 最小震荡持续时间 |

**判断逻辑**:
1. 价格行为检测：突破区间、连续K线
2. 波动率检测：ATR扩张/收缩
3. 信号加权计算
4. 状态惯性过滤
5. 多周期确认

### ADXAlgorithm

基于 ADX (Average Directional Index) 的趋势强度判断算法。

**配置参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| period | 14 | ADX周期 |
| threshold | 25 | ADX阈值 |

**判断逻辑**:
1. 计算 +DM 和 -DM
2. 计算 ATR
3. 计算 +DI 和 -DI
4. 计算 ADX
5. ADX >= threshold 为趋势行情，否则为震荡

### CompositeAlgorithm

组合算法，综合多指标判断。

**配置参数**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| adx_period | 14 | ADX周期 |
| adx_threshold | 25 | ADX阈值 |
| atr_period | 14 | ATR周期 |
| atr_multiplier | 1.5 | ATR倍数 |
| bb_period | 20 | 布林带周期 |
| bb_std | 2 | 布林带标准差 |
| bb_width_threshold | 0.04 | 布林带宽度阈值 |
| ma_period | 50 | 均线周期 |

**评分规则**:

| 指标 | 趋势得分贡献 |
|------|-------------|
| ADX >= threshold | +40 |
| ATR比率 >= multiplier | +30 |
| 布林带宽度 >= threshold | +30 |

**判断标准**:
- 得分 >= 70: 趋势行情
- 得分 >= 40: 过渡状态
- 得分 < 40: 震荡行情

### AlwaysRangingAlgorithm

始终返回震荡行情的算法，用于对比测试。

```python
class AlwaysRangingAlgorithm(StatusAlgorithm):
    name = "always_ranging"
    description = "始终返回震荡行情（用于对比测试）"
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        return StatusResult(
            status=MarketStatus.RANGING,
            confidence=1.0,
            indicators={},
            reason="始终震荡模式（对比测试）"
        )
    
    def get_required_periods(self) -> int:
        return 1
```

## 主类：MarketStatusDetector

市场行情判断器主类。

### 初始化

```python
detector = MarketStatusDetector(
    algorithm=RealTimeStatusAlgorithm(config),
    config={}
)
```

### 核心方法

#### analyze() - 批量分析

分析历史K线数据，返回行情统计。

```python
result = await detector.analyze(
    symbol="BTCUSDT",
    interval="1m",
    days=30
)

# 返回结果
{
    'symbol': 'BTCUSDT',
    'interval': '1m',
    'start_time': int,
    'end_time': int,
    'total_klines': int,
    'total_results': int,
    'statistics': {
        'total': int,
        'ranging_count': int,
        'ranging_pct': float,
        'trending_up_count': int,
        'trending_up_pct': float,
        'trending_down_count': int,
        'trending_down_pct': float,
        'transitioning_count': int,
        'transitioning_pct': float,
    },
    'intervals': List[Dict],
    'results': List[Dict],
}
```

#### update() - 实时更新

实时更新市场状态，用于实盘交易。

```python
result = detector.update(kline)

# 返回结果
{
    'status': MarketStatus,
    'confidence': float,
    'reason': str,
    'should_switch': bool,
    'target_strategy': str,
    'current_strategy': str,
}
```

#### 报告生成

```python
detector.save_report(symbol, days, date_range_str)
detector.save_history(symbol, days, date_range_str)
```

## 辅助组件

### IntervalAnalyzer

区间分析器，记录不同状态的时间区间。

```python
analyzer = IntervalAnalyzer()
analyzer.update(timestamp, price, status, indicators)
intervals = analyzer.get_intervals()
```

### StrategySwitcher

策略切换决策器，决定何时切换交易策略。

```python
switcher = StrategySwitcher(config)
should_switch, target = switcher.should_switch(status, confidence, duration)
```

## 命令行使用

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --interval | 1m | K线周期 |
| --days | None | 分析天数 |
| --date-range | None | 时间范围 (yyyymmdd-yyyymmdd) |
| --algorithm | realtime | 算法 (realtime/adx/composite/always_ranging) |
| --adx-threshold | 25 | ADX阈值 |

### 使用示例

```bash
# 分析最近 20 天的行情
python market_status_detector.py --symbol BTCUSDT --days 20

# 分析指定时间范围
python market_status_detector.py --symbol BTCUSDT --date-range "20240101-20240601"

# 使用 ADX 算法
python market_status_detector.py --symbol BTCUSDT --days 20 --algorithm adx

# 使用组合算法
python market_status_detector.py --symbol BTCUSDT --days 20 --algorithm composite
```

## 配置预设

### REALTIME_PRIORITY_CONFIG

实时性优先配置，响应更快：

```python
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
```

### RELIABILITY_PRIORITY_CONFIG

可靠性优先配置，更稳定：

```python
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
```

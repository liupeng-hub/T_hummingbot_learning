# 市场行情判断器设计规格

## 1. 需求背景

### 1.1 问题分析

从回测结果来看：
- **震荡行情**：策略表现优秀，胜率高，盈利稳定
- **趋势行情**（上涨/下跌）：策略表现不佳，容易止损

### 1.2 目标

设计一个市场行情判断器：
1. 实时判断当前市场处于震荡行情还是趋势行情
2. 趋势行情时停止交易，震荡行情时继续执行
3. **支持不同算法替换，便于后续扩展**
4. **可接收回测 K 线参数进行分析**
5. **生成行情分析报告和历史记录**
6. **可嵌入到回测和实盘代码中**

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      MarketStatusDetector                        │
│                      (市场行情判断器)                             │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 算法插件系统 (支持替换)                                    │    │
│  │  - ADXAlgorithm: ADX 趋势强度算法                         │    │
│  │  - ATRAlgorithm: ATR 波动率算法                           │    │
│  │  - BBWidthAlgorithm: 布林带宽度算法                        │    │
│  │  - CompositeAlgorithm: 组合算法 (默认)                    │    │
│  │  - 自定义算法: 用户可扩展                                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 数据输入接口                                              │    │
│  │  - 从 DB 获取 K 线数据                                    │    │
│  │  - 参数: symbol, interval, date-range/days/limit         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 行情分析引擎                                              │    │
│  │  - 遍历 K 线数据                                          │    │
│  │  - 调用算法判断行情                                        │    │
│  │  - 记录行情变化                                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 报告生成模块                                              │    │
│  │  - 生成行情分析报告                                        │    │
│  │  - 追加历史记录                                            │    │
│  │  - 输出文件:                                              │    │
│  │    binance_BTCUSDT_market_report_5d.md                   │    │
│  │    binance_BTCUSDT_market_report_5d_20220616-20230107.md │    │
│  │    binance_BTCUSDT_market_history.md                     │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 模块关系

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ binance_kline_   │     │ market_status_   │     │ binance_backtest │
│ fetcher.py       │────→│ detector.py      │←────│ .py              │
│ (数据获取)       │     │ (行情判断)       │     │ (回测引擎)       │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                │
                                ↓
                         ┌──────────────────┐
                         │ autofish_bot.py  │
                         │ (实盘交易)       │
                         └──────────────────┘
```

## 3. 核心类设计

### 3.1 市场状态枚举

```python
class MarketStatus(Enum):
    """市场状态"""
    RANGING = "ranging"              # 震荡行情
    TRENDING_UP = "trending_up"      # 上涨趋势
    TRENDING_DOWN = "trending_down"  # 下跌趋势
    TRANSITIONING = "transitioning"  # 过渡状态
    UNKNOWN = "unknown"              # 未知状态
```

### 3.2 算法基类（支持替换）

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class StatusResult:
    """行情判断结果"""
    status: MarketStatus           # 市场状态
    confidence: float              # 置信度 (0-1)
    indicators: Dict               # 指标值
    reason: str                    # 判断原因

class StatusAlgorithm(ABC):
    """行情判断算法基类"""
    
    name: str = "base"
    description: str = "基础算法"
    
    @abstractmethod
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        """
        计算市场状态
        
        参数:
            klines: K 线数据列表
            config: 配置参数
        
        返回:
            StatusResult: 行情判断结果
        """
        pass
    
    @abstractmethod
    def get_required_periods(self) -> int:
        """
        获取算法所需的最小 K 线数量
        
        返回:
            int: 最小 K 线数量
        """
        pass
    
    def get_indicators(self) -> Dict:
        """
        获取算法计算的指标值
        
        返回:
            Dict: 指标值字典
        """
        return {}
```

### 3.3 内置算法实现

#### ADX 算法

```python
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
                reason = f"ADX={adx:.2f} >= {self.threshold}, 价格 > MA50, 上涨趋势"
            else:
                status = MarketStatus.TRENDING_DOWN
                reason = f"ADX={adx:.2f} >= {self.threshold}, 价格 < MA50, 下跌趋势"
            
            confidence = min(1.0, (adx - self.threshold) / 25)
        else:
            status = MarketStatus.RANGING
            reason = f"ADX={adx:.2f} < {self.threshold}, 震荡行情"
            confidence = 1.0 - (adx / self.threshold)
        
        return StatusResult(
            status=status,
            confidence=confidence,
            indicators=self._indicators,
            reason=reason
        )
    
    def get_required_periods(self) -> int:
        return self.period * 2
    
    def get_indicators(self) -> Dict:
        return self._indicators
```

#### 组合算法（默认）

```python
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
            self.config['adx_period'] * 2,
            self.config['atr_period'] * 2,
            self.config['bb_period'],
            self.config['ma_period']
        )
    
    def get_indicators(self) -> Dict:
        return self._indicators
```

### 3.4 行情判断器主类

```python
class MarketStatusDetector:
    """市场行情判断器"""
    
    def __init__(self, algorithm: StatusAlgorithm = None, config: Dict = None):
        """
        初始化
        
        参数:
            algorithm: 行情判断算法（默认使用组合算法）
            config: 配置参数
        """
        self.algorithm = algorithm or CompositeAlgorithm(config)
        self.config = config or {}
        
        # 状态
        self._current_status = MarketStatus.UNKNOWN
        self._history: List[Dict] = []
        self._klines: List[Dict] = []
        
        # 数据获取器
        self._fetcher = None
    
    def set_algorithm(self, algorithm: StatusAlgorithm):
        """
        设置算法（支持运行时替换）
        
        参数:
            algorithm: 行情判断算法
        """
        self.algorithm = algorithm
        self._history = []
    
    async def analyze(self, symbol: str, interval: str = "1m",
                      start_time: int = None, end_time: int = None,
                      days: int = None, limit: int = None) -> Dict:
        """
        分析指定范围的行情
        
        参数:
            symbol: 交易对
            interval: K 线周期
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
            days: 分析天数
            limit: K 线数量
        
        返回:
            Dict: 分析结果
        """
        # 1. 获取 K 线数据
        from binance_kline_fetcher import KlineFetcher
        
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
        
        # 2. 分析行情
        results = []
        required_periods = self.algorithm.get_required_periods()
        
        for i in range(required_periods, len(klines)):
            window = klines[:i+1]
            result = self.algorithm.calculate(window, self.config)
            
            results.append({
                'timestamp': klines[i]['timestamp'],
                'time': datetime.fromtimestamp(klines[i]['timestamp'] / 1000),
                'price': float(klines[i]['close']),
                'status': result.status,
                'confidence': result.confidence,
                'indicators': result.indicators,
                'reason': result.reason,
            })
        
        # 3. 统计分析
        stats = self._calculate_statistics(results)
        
        # 4. 保存结果
        self._history = results
        self._klines = klines
        
        return {
            'symbol': symbol,
            'interval': interval,
            'start_time': actual_start,
            'end_time': actual_end,
            'total_klines': len(klines),
            'total_results': len(results),
            'statistics': stats,
            'results': results,
        }
    
    def update(self, kline: Dict) -> MarketStatus:
        """
        实时更新行情判断（用于实盘）
        
        参数:
            kline: K 线数据
        
        返回:
            MarketStatus: 当前市场状态
        """
        self._klines.append(kline)
        
        # 保持足够的 K 线数量
        required = self.algorithm.get_required_periods()
        if len(self._klines) > required * 2:
            self._klines = self._klines[-required * 2:]
        
        if len(self._klines) < required:
            return MarketStatus.UNKNOWN
        
        result = self.algorithm.calculate(self._klines, self.config)
        self._current_status = result.status
        
        return self._current_status
    
    def get_status(self) -> MarketStatus:
        """获取当前市场状态"""
        return self._current_status
    
    def should_trade(self) -> bool:
        """
        是否应该交易
        
        返回:
            bool: True=允许交易（震荡）, False=停止交易（趋势）
        """
        return self._current_status == MarketStatus.RANGING
    
    def get_indicators(self) -> Dict:
        """获取当前指标值"""
        return self.algorithm.get_indicators()
    
    def save_report(self, symbol: str, days: int = None, date_range_str: str = None):
        """保存行情分析报告"""
        # ... (同上)
    
    def save_history(self, symbol: str, days: int = None, date_range_str: str = None):
        """追加历史记录"""
        # ... (同上)
```

## 4. 命名对比

| 原命名 | 新命名 | 说明 |
|--------|--------|------|
| `MarketRegime` | `MarketStatus` | 市场状态 |
| `RegimeDetector` | `StatusDetector` | 状态检测器 |
| `RegimeAlgorithm` | `StatusAlgorithm` | 状态判断算法 |
| `RegimeResult` | `StatusResult` | 状态判断结果 |
| `_current_regime` | `_current_status` | 当前状态 |

## 5. 实施步骤

### 步骤 1：创建核心模块

创建 `market_status_detector.py`：
- 实现 `MarketStatus` 枚举
- 实现 `StatusResult` 数据类
- 实现 `StatusAlgorithm` 基类
- 实现内置算法（ADX、组合算法）
- 实现 `MarketStatusDetector` 主类

### 步骤 2：添加命令行接口

在 `market_status_detector.py` 中添加：
- 参数解析
- 主函数
- 报告生成

### 步骤 3：集成到回测系统

修改 `binance_backtest.py`：
- 在回测前分析行情
- 根据行情决定是否执行
- 保存行情报告

### 步骤 4：集成到实盘系统

修改 `autofish_bot.py`：
- 在主循环中更新行情判断
- 根据行情决定是否交易

### 步骤 5：测试验证

1. 测试独立使用
2. 测试回测集成
3. 测试实盘集成

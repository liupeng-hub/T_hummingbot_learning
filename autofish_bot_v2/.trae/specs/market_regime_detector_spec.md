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
│                      MarketRegimeDetector                        │
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
│ binance_kline_   │     │ market_regime_   │     │ binance_backtest │
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

### 3.1 行情状态枚举

```python
class MarketRegime(Enum):
    """市场行情状态"""
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
class RegimeResult:
    """行情判断结果"""
    regime: MarketRegime           # 行情状态
    confidence: float              # 置信度 (0-1)
    indicators: Dict               # 指标值
    reason: str                    # 判断原因

class RegimeAlgorithm(ABC):
    """行情判断算法基类"""
    
    name: str = "base"
    description: str = "基础算法"
    
    @abstractmethod
    def calculate(self, klines: List[Dict], config: Dict) -> RegimeResult:
        """
        计算行情状态
        
        参数:
            klines: K 线数据列表
            config: 配置参数
        
        返回:
            RegimeResult: 行情判断结果
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
class ADXAlgorithm(RegimeAlgorithm):
    """ADX 趋势强度算法"""
    
    name = "adx"
    description = "基于 ADX 的趋势强度判断"
    
    def __init__(self, period: int = 14, threshold: int = 25):
        self.period = period
        self.threshold = threshold
        self._indicators = {}
    
    def calculate(self, klines: List[Dict], config: Dict) -> RegimeResult:
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
                regime = MarketRegime.TRENDING_UP
                reason = f"ADX={adx:.2f} >= {self.threshold}, 价格 > MA50, 上涨趋势"
            else:
                regime = MarketRegime.TRENDING_DOWN
                reason = f"ADX={adx:.2f} >= {self.threshold}, 价格 < MA50, 下跌趋势"
            
            confidence = min(1.0, (adx - self.threshold) / 25)
        else:
            regime = MarketRegime.RANGING
            reason = f"ADX={adx:.2f} < {self.threshold}, 震荡行情"
            confidence = 1.0 - (adx / self.threshold)
        
        return RegimeResult(
            regime=regime,
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
class CompositeAlgorithm(RegimeAlgorithm):
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
    
    def calculate(self, klines: List[Dict], config: Dict) -> RegimeResult:
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
                regime = MarketRegime.TRENDING_UP
            else:
                regime = MarketRegime.TRENDING_DOWN
            confidence = trend_score / 100
            reason = f"趋势得分={trend_score}, " + ", ".join(reasons)
        elif trend_score >= 40:
            # 过渡状态
            regime = MarketRegime.TRANSITIONING
            confidence = 0.5
            reason = f"过渡状态, 趋势得分={trend_score}"
        else:
            # 震荡
            regime = MarketRegime.RANGING
            confidence = 1.0 - trend_score / 100
            reason = f"震荡行情, 趋势得分={trend_score}"
        
        return RegimeResult(
            regime=regime,
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
class MarketRegimeDetector:
    """市场行情判断器"""
    
    def __init__(self, algorithm: RegimeAlgorithm = None, config: Dict = None):
        """
        初始化
        
        参数:
            algorithm: 行情判断算法（默认使用组合算法）
            config: 配置参数
        """
        self.algorithm = algorithm or CompositeAlgorithm(config)
        self.config = config or {}
        
        # 状态
        self._current_regime = MarketRegime.UNKNOWN
        self._history: List[Dict] = []
        self._klines: List[Dict] = []
        
        # 数据获取器
        self._fetcher = None
    
    def set_algorithm(self, algorithm: RegimeAlgorithm):
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
                'regime': result.regime,
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
    
    def update(self, kline: Dict) -> MarketRegime:
        """
        实时更新行情判断（用于实盘）
        
        参数:
            kline: K 线数据
        
        返回:
            MarketRegime: 当前行情状态
        """
        self._klines.append(kline)
        
        # 保持足够的 K 线数量
        required = self.algorithm.get_required_periods()
        if len(self._klines) > required * 2:
            self._klines = self._klines[-required * 2:]
        
        if len(self._klines) < required:
            return MarketRegime.UNKNOWN
        
        result = self.algorithm.calculate(self._klines, self.config)
        self._current_regime = result.regime
        
        return self._current_regime
    
    def get_regime(self) -> MarketRegime:
        """获取当前行情状态"""
        return self._current_regime
    
    def should_trade(self) -> bool:
        """
        是否应该交易
        
        返回:
            bool: True=允许交易（震荡）, False=停止交易（趋势）
        """
        return self._current_regime == MarketRegime.RANGING
    
    def get_indicators(self) -> Dict:
        """获取当前指标值"""
        return self.algorithm.get_indicators()
    
    def save_report(self, symbol: str, days: int = None, date_range_str: str = None):
        """
        保存行情分析报告
        
        参数:
            symbol: 交易对
            days: 分析天数
            date_range_str: 日期范围字符串
        """
        # 生成文件名
        if date_range_str:
            filename = f"binance_{symbol}_market_report_{date_range_str}.md"
        elif days:
            filename = f"binance_{symbol}_market_report_{days}d.md"
        else:
            filename = f"binance_{symbol}_market_report.md"
        
        filepath = os.path.join("autofish_output", filename)
        
        # 生成报告内容
        content = self._generate_report_content(symbol, days, date_range_str)
        
        # 保存文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"📄 行情报告已保存: {filepath}")
    
    def save_history(self, symbol: str, days: int = None, date_range_str: str = None):
        """
        追加历史记录
        
        参数:
            symbol: 交易对
            days: 分析天数
            date_range_str: 日期范围字符串
        """
        filename = f"binance_{symbol}_market_history.md"
        filepath = os.path.join("autofish_output", filename)
        
        # 生成历史记录内容
        content = self._generate_history_content(symbol, days, date_range_str)
        
        # 检查文件是否存在
        if os.path.exists(filepath):
            # 追加到现有文件
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(content)
        else:
            # 创建新文件
            with open(filepath, 'w', encoding='utf-8') as f:
                header = self._generate_history_header(symbol)
                f.write(header + content)
        
        print(f"📊 历史记录已追加: {filepath}")
    
    def _calculate_statistics(self, results: List[Dict]) -> Dict:
        """计算统计数据"""
        if not results:
            return {}
        
        regimes = [r['regime'] for r in results]
        
        return {
            'total': len(results),
            'ranging_count': regimes.count(MarketRegime.RANGING),
            'ranging_pct': regimes.count(MarketRegime.RANGING) / len(regimes) * 100,
            'trending_up_count': regimes.count(MarketRegime.TRENDING_UP),
            'trending_up_pct': regimes.count(MarketRegime.TRENDING_UP) / len(regimes) * 100,
            'trending_down_count': regimes.count(MarketRegime.TRENDING_DOWN),
            'trending_down_pct': regimes.count(MarketRegime.TRENDING_DOWN) / len(regimes) * 100,
            'transitioning_count': regimes.count(MarketRegime.TRANSITIONING),
            'transitioning_pct': regimes.count(MarketRegime.TRANSITIONING) / len(regimes) * 100,
        }
    
    def _generate_report_content(self, symbol: str, days: int, date_range_str: str) -> str:
        """生成报告内容"""
        stats = self._calculate_statistics(self._history)
        
        content = f"""# {symbol} 市场行情分析报告

## 基本信息

| 项目 | 值 |
|------|-----|
| 交易对 | {symbol} |
| 分析周期 | {days}天 / {date_range_str or '-'} |
| K线数量 | {len(self._klines)} |
| 分析算法 | {self.algorithm.name} |

## 行情统计

| 行情状态 | 数量 | 占比 |
|----------|------|------|
| 震荡行情 | {stats.get('ranging_count', 0)} | {stats.get('ranging_pct', 0):.2f}% |
| 上涨趋势 | {stats.get('trending_up_count', 0)} | {stats.get('trending_up_pct', 0):.2f}% |
| 下跌趋势 | {stats.get('trending_down_count', 0)} | {stats.get('trending_down_pct', 0):.2f}% |
| 过渡状态 | {stats.get('transitioning_count', 0)} | {stats.get('transitioning_pct', 0):.2f}% |

## 行情时间线

"""
        # 添加行情变化时间线
        prev_regime = None
        for r in self._history:
            if r['regime'] != prev_regime:
                content += f"- {r['time'].strftime('%Y-%m-%d %H:%M')}: {r['regime'].value} ({r['reason']})\n"
                prev_regime = r['regime']
        
        return content
    
    def _generate_history_header(self, symbol: str) -> str:
        """生成历史记录表头"""
        return f"""# {symbol} 市场行情分析历史记录

| 分析时间 | 时间范围 | 天数 | 震荡占比 | 上涨占比 | 下跌占比 | 算法 |
|----------|----------|------|----------|----------|----------|------|
"""
    
    def _generate_history_content(self, symbol: str, days: int, date_range_str: str) -> str:
        """生成历史记录内容"""
        stats = self._calculate_statistics(self._history)
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M')
        time_range = date_range_str or f"{days}d"
        
        return f"""| {now} | {time_range} | {days or '-'} | {stats.get('ranging_pct', 0):.1f}% | {stats.get('trending_up_pct', 0):.1f}% | {stats.get('trending_down_pct', 0):.1f}% | {self.algorithm.name} |
"""
```

## 4. 命令行接口

### 4.1 独立使用

```bash
# 分析最近 20 天的行情
python market_regime_detector.py --symbol BTCUSDT --days 20

# 分析指定时间范围
python market_regime_detector.py --symbol BTCUSDT --date-range "20240101-20240601"

# 分析多段时间范围
python market_regime_detector.py --symbol BTCUSDT --date-range "20240101-20240601,20240701-20241201"

# 使用不同算法
python market_regime_detector.py --symbol BTCUSDT --days 20 --algorithm adx

# 查看帮助
python market_regime_detector.py --help
```

### 4.2 嵌入回测

```python
# binance_backtest.py

# 创建行情判断器
detector = MarketRegimeDetector()

# 分析行情
analysis = await detector.analyze(
    symbol=symbol,
    interval=interval,
    start_time=start_time,
    end_time=end_time
)

# 根据行情决定是否交易
if analysis['statistics']['ranging_pct'] >= 70:
    # 震荡行情占主导，执行回测
    engine = BacktestEngine(config)
    await engine.run(...)
else:
    print("趋势行情占主导，跳过回测")

# 保存报告
detector.save_report(symbol, days, date_range_str)
detector.save_history(symbol, days, date_range_str)
```

### 4.3 嵌入实盘

```python
# autofish_bot.py

# 创建行情判断器
detector = MarketRegimeDetector()

# 在主循环中
async def main_loop():
    while True:
        # 获取最新 K 线
        kline = await get_latest_kline(symbol)
        
        # 更新行情判断
        regime = detector.update(kline)
        
        # 根据行情决定是否交易
        if detector.should_trade():
            # 震荡行情，执行交易逻辑
            await execute_strategy()
        else:
            # 趋势行情，停止交易
            logger.info(f"趋势行情: {regime.value}, 停止交易")
        
        await asyncio.sleep(60)
```

## 5. 输出文件

### 5.1 行情报告

**文件名**: `binance_BTCUSDT_market_report_5d.md` 或 `binance_BTCUSDT_market_report_5d_20220616-20230107.md`

**内容**:
```markdown
# BTCUSDT 市场行情分析报告

## 基本信息

| 项目 | 值 |
|------|-----|
| 交易对 | BTCUSDT |
| 分析周期 | 5天 / 5d_20220616-20230107 |
| K线数量 | 7200 |
| 分析算法 | composite |

## 行情统计

| 行情状态 | 数量 | 占比 |
|----------|------|------|
| 震荡行情 | 5760 | 80.00% |
| 上涨趋势 | 720 | 10.00% |
| 下跌趋势 | 360 | 5.00% |
| 过渡状态 | 360 | 5.00% |

## 行情时间线

- 2022-06-16 00:00: ranging (ADX=18.50 < 25, 震荡行情)
- 2022-06-18 12:00: trending_up (ADX=28.30 >= 25, 价格 > MA50)
- 2022-06-19 08:00: ranging (ADX=22.10 < 25, 震荡行情)
...
```

### 5.2 历史记录

**文件名**: `binance_BTCUSDT_market_history.md`

**内容**:
```markdown
# BTCUSDT 市场行情分析历史记录

| 分析时间 | 时间范围 | 天数 | 震荡占比 | 上涨占比 | 下跌占比 | 算法 |
|----------|----------|------|----------|----------|----------|------|
| 2026-03-10 10:00 | 5d | 5 | 80.0% | 10.0% | 5.0% | composite |
| 2026-03-10 10:05 | 20d | 20 | 65.0% | 20.0% | 10.0% | composite |
| 2026-03-10 10:10 | 5d_20220616-20230107 | 206 | 70.0% | 15.0% | 10.0% | composite |
```

## 6. 实施步骤

### 步骤 1：创建核心模块

创建 `market_regime_detector.py`：
- 实现 `MarketRegime` 枚举
- 实现 `RegimeResult` 数据类
- 实现 `RegimeAlgorithm` 基类
- 实现内置算法（ADX、组合算法）
- 实现 `MarketRegimeDetector` 主类

### 步骤 2：添加命令行接口

在 `market_regime_detector.py` 中添加：
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

## 7. 测试用例

### 7.1 算法测试

| 测试 | 输入 | 预期结果 |
|------|------|----------|
| ADX 震荡 | ADX=18 | RANGING |
| ADX 趋势 | ADX=30, 价格>MA | TRENDING_UP |
| ADX 趋势 | ADX=30, 价格<MA | TRENDING_DOWN |
| 组合震荡 | 趋势得分=20 | RANGING |
| 组合趋势 | 趋势得分=80 | TRENDING_UP/DOWN |

### 7.2 集成测试

| 测试 | 命令 | 预期结果 |
|------|------|----------|
| 独立分析 | `--days 20` | 生成报告文件 |
| 回测集成 | 回测前分析 | 根据行情决定是否执行 |
| 实盘集成 | 实时更新 | 根据行情决定是否交易 |

## 8. 扩展方向

### 8.1 新增算法

```python
class MachineLearningAlgorithm(RegimeAlgorithm):
    """机器学习算法"""
    
    name = "ml"
    description = "基于机器学习的行情判断"
    
    def __init__(self, model_path: str):
        self.model = self._load_model(model_path)
    
    def calculate(self, klines: List[Dict], config: Dict) -> RegimeResult:
        # 特征工程
        features = self._extract_features(klines)
        
        # 预测
        prediction = self.model.predict(features)
        
        # 返回结果
        ...
```

### 8.2 参数优化

```python
# 自动优化参数
optimizer = RegimeOptimizer(detector)
best_params = optimizer.optimize(
    symbol="BTCUSDT",
    date_range="20240101-20241201",
    target="accuracy"
)
```

### 8.3 多时间框架

```python
# 多时间框架分析
detector = MarketRegimeDetector()
detector.add_timeframe("1h")  # 1小时
detector.add_timeframe("4h")  # 4小时
detector.add_timeframe("1d")  # 日线

result = detector.analyze_multi_timeframe(symbol, ...)
```

# 行情判断器 (Market Status Detector)

## 模块概述

**源文件**: `market_status_detector.py`

**功能**: 实时判断当前市场状态（震荡/趋势），支持多种算法，可独立运行或集成到回测系统。

**核心状态 (MarketStatus)**:
- `RANGING`: 震荡行情 (适合 Autofish 策略)
- `TRENDING_UP`: 上涨趋势 (风险较高)
- `TRENDING_DOWN`: 下跌趋势 (风险极高)
- `TRANSITIONING`: 过渡状态
- `UNKNOWN`: 未知/数据不足

## 核心算法

### 1. ImprovedStatusAlgorithm (改进算法 - 推荐)
结合支撑阻力位、箱体震荡和突破识别的综合算法。

**逻辑**:
1.  **支撑阻力检测**: 识别最近 60 天的关键支撑/阻力位。
2.  **箱体检测**: 判断价格是否在固定区间内波动 (10-20 天)。
3.  **突破检测**: 判断当前价格是否突破关键位。
4.  **状态判定**:
    - 突破 -> `TRENDING_UP` / `TRENDING_DOWN`
    - 箱体震荡 -> `RANGING`
    - 区间内波动 -> `RANGING`
    - 无明确信号 -> `RANGING` (默认)

### 2. RealTimeStatusAlgorithm (实时算法)
基于价格行为 (Price Action) 和波动率 (ATR) 的快速响应算法。

**逻辑**:
1.  **价格行为**: 连续 K 线方向、突破近期高低点。
2.  **波动率**: ATR 扩张/收缩。
3.  **综合评分**:
    - 趋势信号 >= 4 -> `TRENDING`
    - 震荡信号 >= 2 -> `RANGING`

### 3. ADXAlgorithm (ADX 趋势强度)
传统 ADX 指标判断。

**逻辑**:
- ADX >= 25 -> 趋势 (结合 MA 判断方向)
- ADX < 25 -> 震荡

## 类结构

### MarketStatusDetector
主控制器类。

#### 方法
- `analyze(symbol, interval, days)`: 分析指定时间段的历史行情。
- `update(kline)`: 实时更新单根 K 线，返回最新状态。
- `save_report(symbol)`: 生成 Markdown 分析报告。
- `save_history(symbol)`: 追加保存历史记录。

### StatusAlgorithm (抽象基类)
定义算法接口。

#### 子类
- `ImprovedStatusAlgorithm`
- `RealTimeStatusAlgorithm`
- `ADXAlgorithm`
- `CompositeAlgorithm`
- `AlwaysRangingAlgorithm` (测试用)

### 辅助检测器
- `SupportResistanceDetector`: 识别支撑阻力位。
- `BoxRangeDetector`: 识别箱体震荡。
- `PriceActionDetector`: 识别价格突破。
- `VolatilityDetector`: 识别波动率变化。

## 使用方法

### 命令行运行

```bash
# 分析最近 30 天行情 (使用改进算法)
python market_status_detector.py --symbol BTCUSDT --days 30 --algorithm improved

# 分析指定日期范围
python market_status_detector.py --symbol ETHUSDT --date-range 20230101-20230601

# 比较不同算法
python market_status_detector.py --symbol BTCUSDT --days 30 --algorithm adx
```

### 代码集成

```python
from market_status_detector import MarketStatusDetector, ImprovedStatusAlgorithm

# 初始化
detector = MarketStatusDetector(algorithm=ImprovedStatusAlgorithm())

# 实时更新
status_result = detector.update(current_kline)

if status_result['status'] == MarketStatus.RANGING:
    # 执行震荡策略
    pass
else:
    # 停止交易或平仓
    pass
```

## 输出报告

运行分析后，会在 `autofish_output` 目录下生成报告：
1.  `binance_BTCUSDT_market_report_1m_30d.md`: 详细分析报告，包含区间划分和状态变化。
2.  `binance_BTCUSDT_market_history.md`: 历史记录汇总表。

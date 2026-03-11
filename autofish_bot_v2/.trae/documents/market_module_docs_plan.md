# 市场模块文档整理计划

## 目标
将 `market_status_detector.py` 和 `market_aware_backtest.py` 两个文件的设计分别整理成独立的文档，输出到 `docs` 目录。

---

## 文档 1: `docs/market_status_detector.md`

**源文件**: `market_status_detector.py`

### 内容大纲

1. **模块概述**
   - 功能：判断市场处于震荡行情还是趋势行情
   - 特性：支持多算法替换、可嵌入回测和实盘、生成行情分析报告

2. **核心数据结构**
   - `MarketStatus` 枚举：市场状态定义
   - `StatusResult` 数据类：判断结果封装
   - `MarketInterval` 数据类：市场区间记录

3. **检测器组件**
   - `PriceActionDetector`：价格行为检测（突破、连续K线）
   - `VolatilityDetector`：波动率检测（ATR、波动状态）

4. **算法体系**
   - `StatusAlgorithm` 抽象基类
   - `RealTimeStatusAlgorithm`：实时判断算法（价格行为+波动率+状态惯性）
   - `ADXAlgorithm`：ADX趋势强度算法
   - `CompositeAlgorithm`：组合算法（ADX+ATR+布林带）
   - `AlwaysRangingAlgorithm`：始终震荡算法（对比测试用）

5. **主类：MarketStatusDetector**
   - 初始化与算法设置
   - `analyze()` 批量分析方法
   - `update()` 实时更新方法
   - 报告生成功能

6. **辅助组件**
   - `IntervalAnalyzer`：区间分析器
   - `StrategySwitcher`：策略切换决策器

7. **命令行使用**
   - 参数说明
   - 使用示例

---

## 文档 2: `docs/market_aware_backtest.md`

**源文件**: `market_aware_backtest.py`

### 内容大纲

1. **模块概述**
   - 功能：将行情分析与回测结合，根据市场状态动态控制交易
   - 策略：震荡行情正常交易，趋势行情平仓停止

2. **核心数据结构**
   - `MarketStatusEvent`：行情状态事件
   - `TradingPeriod`：交易时段记录
   - `MARKET_STATUS_CONFIG`：默认配置

3. **主类：MarketAwareBacktestEngine**
   - 继承关系：继承自 `BacktestEngine`
   - 核心属性：market_config, market_detector, trading_enabled 等

4. **核心方法**
   - `_create_algorithm()`：创建行情判断算法
   - `_fetch_multi_interval_klines()`：获取多周期K线数据
   - `_check_market_status()`：每日检查行情状态
   - `_on_market_status_change()`：处理行情状态变化
   - `_close_all_positions()`：强制平仓所有订单

5. **交易控制流程**
   - 初始化流程
   - K线处理流程
   - 状态切换处理

6. **报告生成**
   - `save_report()`：保存回测报告
   - `save_history()`：保存历史记录

7. **命令行使用**
   - 参数说明
   - 使用示例

---

## 实现步骤

### 步骤 1: 创建 docs 目录
```bash
mkdir -p docs
```

### 步骤 2: 创建 market_status_detector.md
按上述大纲编写，包含类图、代码示例

### 步骤 3: 创建 market_aware_backtest.md
按上述大纲编写，包含流程图、使用示例

## 文件清单

| 文件路径 | 说明 |
|----------|------|
| `docs/market_status_detector.md` | 市场行情判断器设计文档 |
| `docs/market_aware_backtest.md` | 行情感知回测设计文档 |

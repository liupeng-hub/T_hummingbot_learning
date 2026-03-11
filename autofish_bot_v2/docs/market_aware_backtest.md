# 行情感知回测 (Market Aware Backtest)

## 模块概述

**源文件**: `market_aware_backtest.py`

**功能**: 将行情分析与回测结合，根据市场状态动态控制交易

**核心策略**:
- 震荡行情：正常进行链式挂单交易
- 趋势行情：平仓所有订单，停止交易

## 核心数据结构

### MarketStatusEvent

行情状态事件，记录状态变化时刻。

| 字段 | 类型 | 说明 |
|------|------|------|
| timestamp | int | 时间戳 |
| time | datetime | 时间 |
| status | MarketStatus | 市场状态 |
| confidence | float | 置信度 |
| reason | str | 判断原因 |
| action | str | 执行动作 |
| price | Decimal | 当前价格 |

```python
@dataclass
class MarketStatusEvent:
    timestamp: int
    time: datetime
    status: MarketStatus
    confidence: float
    reason: str
    action: str
    price: Decimal
```

### TradingPeriod

交易时段记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| start_time | datetime | 开始时间 |
| end_time | datetime | 结束时间 |
| status | MarketStatus | 市场状态 |
| trades | int | 交易次数 |
| profit | Decimal | 收益 |

```python
@dataclass
class TradingPeriod:
    start_time: datetime
    end_time: datetime
    status: MarketStatus
    trades: int = 0
    profit: Decimal = Decimal("0")
```

### MARKET_STATUS_CONFIG

默认行情配置：

```python
MARKET_STATUS_CONFIG = {
    'market_interval': '1d',          # 行情判断K线周期
    'algorithm': 'realtime',          # 行情判断算法
    'min_market_klines': 20,          # 最小K线数量
    'confirm_periods': 2,             # 确认周期数
    'close_on_trending': True,        # 趋势行情时平仓
    'trending_close_method': 'market', # 平仓方式
}
```

## 主类：MarketAwareBacktestEngine

行情感知回测引擎，继承自 `BacktestEngine`。

### 继承关系

```
BacktestEngine (基类)
└── MarketAwareBacktestEngine (行情感知回测引擎)
```

### 核心属性

| 属性 | 类型 | 说明 |
|------|------|------|
| market_config | dict | 行情配置 |
| market_detector | MarketStatusDetector | 行情判断器 |
| trading_enabled | bool | 是否允许交易 |
| current_market_status | MarketStatus | 当前行情状态 |
| market_status_events | List[MarketStatusEvent] | 状态变化事件列表 |
| trading_periods | List[TradingPeriod] | 交易时段列表 |
| daily_klines_cache | List[Dict] | 1d K线缓存 |

### 初始化

```python
engine = MarketAwareBacktestEngine(
    config={
        'symbol': 'BTCUSDT',
        'leverage': Decimal('10'),
        'grid_spacing': Decimal('0.01'),
        'exit_profit': Decimal('0.01'),
        'stop_loss': Decimal('0.08'),
        'total_amount_quote': Decimal('5000'),
        'max_entries': 4,
    },
    market_config={
        'market_interval': '1d',
        'algorithm': 'realtime',
        'min_market_klines': 20,
    }
)
```

## 核心方法

### _create_algorithm()

创建行情判断算法实例。

```python
def _create_algorithm(self) -> StatusAlgorithm:
    algo_name = self.market_config.get('algorithm', 'realtime')
    
    if algo_name == 'realtime':
        return RealTimeStatusAlgorithm({...})
    elif algo_name == 'always_ranging':
        return AlwaysRangingAlgorithm()
    elif algo_name == 'adx':
        return ADXAlgorithm()
    else:
        return CompositeAlgorithm()
```

### _fetch_multi_interval_klines()

获取多周期K线数据。

**参数**:
- symbol: 交易对
- interval: 交易K线周期 (默认 1m)
- limit: K线数量限制
- days: 回测天数
- start_time/end_time: 时间范围

**返回**: `(klines_1m, klines_1d)`

**逻辑**:
1. 获取交易周期K线 (1m)
2. 获取行情判断周期K线 (1d)
3. 行情K线需要额外获取前置数据 (min_market_klines 天)

### _check_market_status()

检查行情状态，每日第一根1m K线时更新判断。

```python
def _check_market_status(self, kline_1m: dict) -> MarketStatus:
    current_ts = kline_1m['timestamp']
    current_date = datetime.fromtimestamp(current_ts / 1000).date()
    
    # 同一天不重复判断
    if self._last_check_date == current_date:
        return self.current_market_status
    
    # 获取当日之前的1d K线
    market_klines = self._get_market_klines_before(current_ts)
    
    # 调用算法计算
    result = self.market_detector.algorithm.calculate(market_klines, self.market_config)
    
    return result.status
```

### _on_market_status_change()

处理行情状态变化。

**状态变化处理逻辑**:

| 变化 | 处理 |
|------|------|
| 震荡 -> 趋势 | 平仓所有订单，停止交易 |
| 趋势 -> 震荡 | 创建首个订单，开始交易 |
| 趋势 -> 反向趋势 | 保持停止状态 |

```python
def _on_market_status_change(self, old_status, new_status, kline, confidence, reason):
    is_trending = new_status in [TRENDING_UP, TRENDING_DOWN]
    was_trending = old_status in [TRENDING_UP, TRENDING_DOWN]
    
    if is_trending and not was_trending:
        # 进入趋势行情：平仓停止
        self._close_all_positions(price, timestamp, 'market_status_change')
        self.trading_enabled = False
        
    elif new_status == RANGING and was_trending:
        # 回到震荡行情：开始交易
        self.trading_enabled = True
        self._create_first_order(price, kline)
```

### _close_all_positions()

强制平仓所有已成交订单。

```python
def _close_all_positions(self, price: Decimal, timestamp: int, reason: str):
    filled_orders = self.chain_state.get_filled_orders()
    
    for order in filled_orders:
        if order.state != "filled":
            continue
        
        order.set_state("closed", f"market_status_{reason}")
        order.close_price = price
        order.profit = self._calculate_profit(order, price, leverage)
        
        # 更新统计
        if order.profit > 0:
            self.results["win_trades"] += 1
            self.results["total_profit"] += order.profit
        else:
            self.results["loss_trades"] += 1
            self.results["total_loss"] += abs(order.profit)
    
    # 清空订单列表
    self.chain_state.cancel_pending_orders()
    self.chain_state.orders = []
```

## 交易控制流程

### 初始化流程

```
1. 加载配置
   ↓
2. 创建行情判断器
   ↓
3. 获取多周期K线数据
   ├── 1m K线 (交易用)
   └── 1d K线 (行情判断用)
   ↓
4. 初始行情判断
   ├── 震荡 → 创建首个订单
   └── 趋势 → 暂停交易
```

### K线处理流程

```
每根1m K线:
   ↓
检查是否新的一天
   ├── 是 → 更新行情判断
   └── 否 → 使用缓存状态
   ↓
行情状态是否变化？
   ├── 是 → 处理状态变化
   │      ├── 震荡→趋势: 平仓停止
   │      └── 趋势→震荡: 开始交易
   └── 否 → 继续
   ↓
是否允许交易？
   ├── 是 → 处理入场/出场
   └── 否 → 跳过
```

### 状态切换处理

```
震荡 → 趋势:
   ↓
1. 记录状态变化事件
   ↓
2. 强制平仓所有持仓
   ├── 计算盈亏
   ├── 更新统计
   └── 清空订单
   ↓
3. 设置 trading_enabled = False
   ↓
4. 结束当前交易时段

趋势 → 震荡:
   ↓
1. 记录状态变化事件
   ↓
2. 设置 trading_enabled = True
   ↓
3. 创建首个订单
   ↓
4. 开始新的交易时段
```

## 报告生成

### save_report()

保存详细的回测报告。

**报告内容**:
- 回测区间信息
- 回测结果统计
- 行情分析统计
- 行情状态变化记录
- 交易时段记录
- 交易明细

```python
engine.save_report(symbol, days, date_range)
```

### save_history()

保存回测历史记录（追加模式）。

**记录内容**:
- 回测时间
- 日期范围
- 天数
- 交易次数
- 胜率
- 收益率
- 标的涨跌
- 超额收益
- 交易时间占比
- 行情策略

```python
engine.save_history(symbol, days, date_range)
```

## 命令行使用

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --symbol | BTCUSDT | 交易对 |
| --interval | 1m | K线周期 |
| --limit | 1500 | K线数量 |
| --days | None | 回测天数 |
| --date-range | None | 时间范围 (yyyymmdd-yyyymmdd) |
| --decay-factor | 0.5 | 衰减因子 |
| --stop-loss | 0.08 | 止损比例 |
| --total-amount | 10000 | 总投入金额 |
| --market-aware | False | 启用行情感知 |
| --market-interval | 1d | 行情判断周期 |
| --market-algorithm | realtime | 行情判断算法 |
| --no-auto-fetch | False | 禁用自动获取 |

### 使用示例

```bash
# 基本使用
python market_aware_backtest.py --symbol BTCUSDT --days 30

# 指定时间范围
python market_aware_backtest.py --symbol BTCUSDT --date-range 20240101-20240601

# 使用不同行情算法
python market_aware_backtest.py --symbol BTCUSDT --days 30 --market-algorithm adx
python market_aware_backtest.py --symbol BTCUSDT --days 30 --market-algorithm composite

# 对比测试：始终震荡模式
python market_aware_backtest.py --symbol BTCUSDT --days 30 --market-algorithm always_ranging

# 多时间段回测
python market_aware_backtest.py --symbol BTCUSDT --date-range "20230101-20230331,20230401-20230630"
```

## 输出示例

### 控制台输出

```
============================================================
行情感知回测
============================================================

配置:
  交易对: BTCUSDT
  K线周期: 1m
  行情判断周期: 1d
  行情判断算法: realtime
  时间范围: 2022-06-16 ~ 2023-01-07

📊 回测时间范围:
  开始: 2022-06-16 00:00
  结束: 2023-01-07 23:59
  1m K线数: 296640
  1d K线数: 226

⏳ 开始回测...

============================================================
📊 回测结果
============================================================
  回测时间: 2022-06-16 00:00 - 2023-01-07 23:59
  K线数量: 296640
  总交易: 130
  盈利次数: 117
  亏损次数: 13
  胜率: 90.00%
  总盈利: 11564.50 USDT
  总亏损: 5405.01 USDT
  净收益: 6159.49 USDT

📈 行情统计:
  行情状态变化: 37 次
  交易时间占比: 84.0%
  停止时间占比: 0.0%
============================================================

📄 回测报告已保存: autofish_output/binance_BTCUSDT_market_aware_backtest_206d_20220616-20230107.md
📊 历史记录已追加: autofish_output/binance_BTCUSDT_market_aware_history.md
```

### 历史记录格式

```markdown
| 回测时间 | 日期范围 | 天数 | 交易次数 | 胜率 | 收益率 | 标的涨跌 | 超额收益 | 交易时间占比 | 行情策略 |
|----------|----------|------|----------|------|--------|----------|----------|--------------|----------|
| 2026-03-11 21:16 | 2022-06-16 ~ 2023-01-07 | 206 | 115 | 95.7% | 119.62% | -20.90% | 140.52% | 100.0% | always_ranging |
| 2026-03-11 21:11 | 2022-06-16 ~ 2023-01-07 | 206 | 130 | 90.0% | 123.19% | -20.90% | 144.09% | 84.0% | realtime |
```

# 行情分析与回测结合规格文档

## 1. 背景与目标

### 1.1 背景
- 回测使用 1m K线数据进行订单处理（挂单、止盈、止损）
- 行情判断使用 1d K线数据判断市场状态（震荡/趋势）
- 需要将两者结合，实现根据行情状态控制交易行为

### 1.2 目标
- 在回测过程中，根据行情状态动态控制交易
- 震荡行情：正常进行链式挂单交易
- 趋势行情：平仓所有订单，停止交易，等待行情回归震荡
- 记录行情变化信息到回测报告

## 2. 方案设计

### 2.1 核心思路

```
┌─────────────────────────────────────────────────────────────┐
│                    回测主循环 (1m K线)                        │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  获取 1m K线  │───>│ 行情状态检查  │───>│ 交易决策执行  │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                              │                              │
│                              ▼                              │
│                    ┌──────────────────┐                    │
│                    │ 使用 1d K线判断   │                    │
│                    │ 当前行情状态      │                    │
│                    └──────────────────┘                    │
│                              │                              │
│              ┌───────────────┼───────────────┐             │
│              ▼               ▼               ▼             │
│         ┌────────┐     ┌──────────┐    ┌──────────┐       │
│         │ 震荡   │     │ 上涨趋势  │    │ 下跌趋势  │       │
│         │ 正常交易│     │ 平仓停止  │    │ 平仓停止  │       │
│         └────────┘     └──────────┘    └──────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 行情判断时机

**方案选择：滚动窗口实时判断**

每根 1m K线处理时，使用"截至当前时间的 1d K线数据"进行行情判断：
- 优点：实时捕捉行情变化，不滞后
- 实现：维护一个 1d K线缓存，每次处理 1m K线时更新判断

### 2.3 数据对齐策略

```
时间线：
  1d K线:  |----Day1----|----Day2----|----Day3----|
  1m K线:  |D1|D1|D1|...|D2|D2|D2|...|D3|D3|D3|...|

行情判断：
  - 处理 Day1 的 1m K线时，使用 Day1 及之前的 1d K线判断
  - 处理 Day2 的 1m K线时，使用 Day2 及之前的 1d K线判断
  - 当天第一根 1m K线时，重新计算行情状态
```

### 2.4 状态切换逻辑

#### 2.4.1 震荡 -> 趋势
```
触发条件：行情状态从 RANGING 变为 TRENDING_UP 或 TRENDING_DOWN

执行动作：
1. 平仓所有已成交订单（按当前价格）
2. 取消所有挂单订单
3. 设置 trading_enabled = False
4. 记录状态切换事件
```

#### 2.4.2 趋势 -> 震荡
```
触发条件：行情状态从 TRENDING_* 变为 RANGING

执行动作：
1. 设置 trading_enabled = True
2. 创建新的 A1 挂单
3. 记录状态切换事件
```

### 2.5 行情判断配置

```python
MARKET_STATUS_CONFIG = {
    # 行情判断使用的 K 线周期
    'market_interval': '1d',
    
    # 行情判断算法
    'algorithm': 'realtime',  # realtime / adx / composite
    
    # 行情判断所需的最小 K 线数量
    'min_market_klines': 20,
    
    # 状态切换确认周期（连续 N 次相同状态才切换）
    'confirm_periods': 2,
    
    # 是否在趋势行情中强制平仓
    'close_on_trending': True,
    
    # 趋势行情平仓方式
    'trending_close_method': 'market',  # market / take_profit_only
}
```

## 3. 数据结构

### 3.1 行情状态记录

```python
@dataclass
class MarketStatusEvent:
    """行情状态事件"""
    timestamp: int              # 时间戳
    time: datetime              # 时间
    status: MarketStatus        # 行情状态
    confidence: float           # 置信度
    reason: str                 # 判断原因
    action: str                 # 执行动作 (start_trading / stop_trading / continue)
    price: Decimal              # 当时价格
```

### 3.2 回测结果扩展

```python
# 在 BacktestEngine.results 中添加
results = {
    # ... 现有字段 ...
    
    # 行情相关
    'market_status_events': [],      # 行情状态变化事件列表
    'trading_periods': [],           # 交易时段列表
    'stopped_periods': [],           # 停止交易时段列表
    'total_trading_minutes': 0,      # 总交易时间（分钟）
    'total_stopped_minutes': 0,      # 总停止时间（分钟）
}
```

## 4. 回测报告扩展

### 4.1 新增章节：行情分析

```markdown
## 行情分析

### 行情统计
| 指标 | 值 |
|------|-----|
| 行情判断周期 | 1d |
| 行情判断算法 | realtime |
| 震荡时间占比 | XX% |
| 趋势时间占比 | XX% |

### 行情状态变化
| 时间 | 状态变化 | 价格 | 执行动作 |
|------|----------|------|----------|
| 2026-03-10 00:00 | 震荡 -> 上涨趋势 | 85000 | 停止交易 |
| 2026-03-12 00:00 | 上涨趋势 -> 震荡 | 83000 | 开始交易 |

### 交易时段
| 时段 | 开始时间 | 结束时间 | 状态 | 交易次数 | 收益 |
|------|----------|----------|------|----------|------|
| 1 | 2026-03-01 | 2026-03-10 | 震荡 | 50 | +200 USDT |
| 2 | 2026-03-12 | 2026-03-15 | 震荡 | 20 | +50 USDT |
```

## 5. 实现方案

### 5.1 新增类：MarketAwareBacktestEngine

继承自 BacktestEngine，添加行情感知能力：

```python
class MarketAwareBacktestEngine(BacktestEngine):
    """行情感知回测引擎"""
    
    def __init__(self, config: dict, market_config: dict = None):
        super().__init__(config)
        self.market_config = market_config or MARKET_STATUS_CONFIG
        self.market_detector = MarketStatusDetector(
            algorithm=RealTimeStatusAlgorithm(market_config)
        )
        
        self.trading_enabled = True
        self.current_market_status = MarketStatus.UNKNOWN
        self.market_status_events = []
        self.daily_klines_cache = []
        
    async def run(self, symbol, interval, ...):
        # 1. 获取 1d K线数据
        # 2. 获取 1m K线数据
        # 3. 遍历 1m K线，每根 K线检查行情状态
        pass
    
    def _check_market_status(self, kline_1m):
        # 检查是否需要更新行情判断（每天一次）
        # 返回当前行情状态
        pass
    
    def _on_market_status_change(self, old_status, new_status, price):
        # 处理行情状态变化
        pass
    
    def _on_kline(self, kline):
        # 重写 K线处理逻辑
        # 1. 检查行情状态
        # 2. 根据状态决定是否交易
        pass
```

### 5.2 关键方法实现

#### 5.2.1 行情状态检查

```python
def _check_market_status(self, kline_1m: dict) -> MarketStatus:
    """检查行情状态
    
    每天第一根 1m K线时更新行情判断
    """
    current_date = datetime.fromtimestamp(kline_1m['timestamp'] / 1000).date()
    
    if self._last_check_date == current_date:
        return self.current_market_status
    
    # 需要更新判断
    self._last_check_date = current_date
    
    # 获取截至当前时间的 1d K线
    current_ts = kline_1m['timestamp']
    market_klines = self._get_market_klines_before(current_ts)
    
    if len(market_klines) < self.market_config['min_market_klines']:
        return self.current_market_status
    
    # 计算行情状态
    result = self.market_detector.algorithm.calculate(
        market_klines, 
        self.market_config
    )
    
    return result.status
```

#### 5.2.2 状态变化处理

```python
def _on_market_status_change(self, old_status: MarketStatus, 
                              new_status: MarketStatus, 
                              kline: dict):
    """处理行情状态变化"""
    price = Decimal(str(kline['close']))
    timestamp = kline['timestamp']
    
    # 记录事件
    event = MarketStatusEvent(
        timestamp=timestamp,
        time=datetime.fromtimestamp(timestamp / 1000),
        status=new_status,
        confidence=0.0,  # TODO
        reason='',
        action='',
        price=price
    )
    
    if new_status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]:
        # 趋势行情：停止交易
        if self.trading_enabled:
            self._close_all_positions(price, 'market')
            self.trading_enabled = False
            event.action = 'stop_trading'
            logger.info(f"[行情变化] {old_status.value} -> {new_status.value}, 停止交易")
    
    elif new_status == MarketStatus.RANGING:
        # 震荡行情：开始交易
        if not self.trading_enabled:
            self.trading_enabled = True
            self._create_first_order(price)
            event.action = 'start_trading'
            logger.info(f"[行情变化] {old_status.value} -> {new_status.value}, 开始交易")
    
    self.market_status_events.append(event)
    self.current_market_status = new_status
```

## 6. 测试计划

### 6.1 单元测试
- 行情状态检查逻辑
- 状态切换逻辑
- 平仓/开仓逻辑

### 6.2 集成测试
- 完整回测流程
- 报告生成

### 6.3 回测对比
- 有行情控制 vs 无行情控制的回测结果对比

## 7. 后续扩展

### 7.1 实盘集成
- 实时获取 1d K线数据
- 定时更新行情状态
- 动态启停交易

### 7.2 多周期判断
- 支持 4h、1h 等周期
- 多周期共振确认

### 7.3 策略优化
- 根据趋势方向调整策略（做多/做空）
- 根据行情强度调整仓位

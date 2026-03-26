# Autofish Bot V2 回测程序执行流程文档

本文档详细描述 Autofish Bot V2 回测程序的完整执行流程，包括主入口、数据获取、K线处理、交易执行和结果统计等核心环节。

---

## 1. 概述

### 1.1 回测程序整体架构

Autofish Bot V2 回测系统采用分层架构设计，主要包含以下层次：

```
┌─────────────────────────────────────────────────────────────┐
│                      用户界面层                              │
│  binance_backtest.py / longport_backtest.py                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      回测引擎层                              │
│  BacktestEngine / MarketAwareBacktestEngine                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      核心模块层                              │
│  autofish_core.py / market_status_detector.py               │
│  binance_kline_fetcher.py                                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      数据存储层                              │
│  test_results_db.py / SQLite 数据库                         │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 核心组件说明

| 组件 | 文件 | 功能 |
|------|------|------|
| 回测引擎 | `binance_backtest.py` | 执行回测逻辑，管理订单状态 |
| 核心策略 | `autofish_core.py` | 订单计算、权重分配、资金管理 |
| 行情检测 | `market_status_detector.py` | 判断市场状态（震荡/趋势） |
| 数据获取 | `binance_kline_fetcher.py` | 获取和缓存 K 线数据 |
| 结果存储 | `database/test_results_db.py` | 保存回测结果到数据库 |

### 1.3 回测程序主流程图

详细的回测主流程图请参考 [flowcharts.md](./flowcharts.md#1-回测程序主流程图)。

---

## 2. 主入口和执行顺序

### 2.1 main() 函数流程

回测程序的主入口位于 [binance_backtest.py](../binance_backtest.py) 的 `main()` 函数。

**执行步骤：**

```python
async def main():
    # 1. 解析命令行参数
    parser = argparse.ArgumentParser(description="行情感知回测")
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument("--date-range", type=str, required=True)
    parser.add_argument("--amplitude-params", type=str, default=None)
    parser.add_argument("--market-params", type=str, default=None)
    parser.add_argument("--entry-params", type=str, default=None)
    parser.add_argument("--timeout-params", type=str, default=None)
    parser.add_argument("--capital-params", type=str, default=None)
    
    args = parser.parse_args()
    
    # 2. 解析配置参数
    amplitude = json.loads(args.amplitude_params) if args.amplitude_params else {}
    market = json.loads(args.market_params) if args.market_params else {}
    entry = json.loads(args.entry_params) if args.entry_params else {}
    timeout = json.loads(args.timeout_params) if args.timeout_params else {}
    capital = json.loads(args.capital_params) if args.capital_params else {}
    
    # 3. 解析时间范围
    date_ranges = parse_date_range(args.date_range)
    
    # 4. 加载振幅配置（如果未提供参数）
    if not amplitude:
        amplitude_config = Autofish_AmplitudeConfig.load_latest(args.symbol)
        amplitude = amplitude_config.to_dict()
    
    # 5. 遍历每个时间段执行回测
    for dr in date_ranges:
        # 5.1 创建回测引擎
        engine = MarketAwareBacktestEngine(amplitude, market, entry, timeout, capital)
        
        # 5.2 运行回测
        await engine.run(
            symbol=args.symbol,
            interval=args.interval,
            start_time=dr['start_time'],
            end_time=dr['end_time']
        )
        
        # 5.3 保存结果到数据库
        _save_to_database(args, engine, dr['date_range_str'], amplitude, market, entry, timeout, capital)
```

**命令行参数说明：**

| 参数 | 必选 | 说明 | 示例 |
|------|------|------|------|
| `--symbol` | 是 | 交易对 | BTCUSDT |
| `--date-range` | 是 | 时间范围 | 20200101-20260310 |
| `--interval` | 否 | K线周期（默认 1m） | 1m |
| `--amplitude-params` | 否 | 振幅参数（JSON） | '{"grid_spacing": 0.01}' |
| `--market-params` | 否 | 行情参数（JSON） | '{"algorithm": "dual_thrust"}' |
| `--entry-params` | 否 | 入场参数（JSON） | '{"strategy": "atr"}' |
| `--timeout-params` | 否 | 超时参数（JSON） | '{"a1_timeout_minutes": 10}' |
| `--capital-params` | 否 | 资金参数（JSON） | '{"strategy": "baoshou"}' |

### 2.2 核心引擎类继承关系

```
┌─────────────────────────────────────────────────────────────┐
│                    BacktestEngine                           │
│  基础回测引擎                                                │
│  - 获取历史 K 线数据                                         │
│  - 模拟订单执行                                              │
│  - 计算盈亏统计                                              │
│  - 生成回测报告                                              │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ 继承
                              │
┌─────────────────────────────────────────────────────────────┐
│                MarketAwareBacktestEngine                    │
│  行情感知回测引擎                                            │
│  - 继承 BacktestEngine 所有功能                              │
│  - 添加行情状态判断                                          │
│  - 震荡行情：正常交易                                        │
│  - 趋势行情：平仓停止                                        │
│  - 多周期 K 线获取（1m + 1d）                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                LongPortBacktestEngine                       │
│  LongPort 回测引擎（独立实现）                               │
│  - 支持港股、美股、A股                                       │
│  - 使用 LongPort API 获取数据                                │
│  - 无杠杆交易                                                │
└─────────────────────────────────────────────────────────────┘
```

**类定义位置：**

- [BacktestEngine](../binance_backtest.py#L79-L681) - 基础回测引擎
- [MarketAwareBacktestEngine](../binance_backtest.py#L726-L1199) - 行情感知回测引擎
- [LongPortBacktestEngine](../longport_backtest.py#L95-L530) - LongPort 回测引擎

---

## 3. 数据获取流程

### 3.1 多周期 K 线获取

回测引擎通过 `_fetch_multi_interval_klines()` 方法获取多周期 K 线数据：

**代码位置：** [binance_backtest.py#L811-L837](../binance_backtest.py#L811-L837)

```python
async def _fetch_multi_interval_klines(self, symbol: str, interval: str, 
                                        start_time: int = None, end_time: int = None) -> tuple:
    """获取多周期 K线数据
    
    返回:
        (1m_klines, 1d_klines)
    """
    from binance_kline_fetcher import KlineFetcher
    
    fetcher = KlineFetcher()
    
    # 1. 获取 1m K线（用于交易模拟）
    klines_1m = await fetcher.fetch_kline(symbol, interval, start_time, end_time)
    
    if not klines_1m:
        logger.error("获取 1m K线数据失败")
        return [], []
    
    # 2. 获取 1d K线（用于行情判断）
    market_interval = self.market.get('interval', '1d')
    market_start = start_time - (self.market.get('min_market_klines', 20) * 86400000)
    
    klines_1d = await fetcher.fetch_kline(symbol, market_interval, market_start, end_time)
    
    if not klines_1d:
        logger.warning("获取 1d K线数据失败，将使用 1m K线聚合")
    
    logger.info(f"[多周期数据] 1m K线: {len(klines_1m)} 条, 1d K线: {len(klines_1d) if klines_1d else 0} 条")
    
    return klines_1m, klines_1d
```

**数据流程图：**

```
┌─────────────────────────────────────────────────────────────┐
│                    数据获取流程                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [命令行参数]                                                │
│       │                                                     │
│       ▼                                                     │
│  [解析时间范围] ──────► start_time, end_time                │
│       │                                                     │
│       ▼                                                     │
│  [KlineFetcher.fetch_kline()]                               │
│       │                                                     │
│       ├───► 检查本地缓存 (klines.db)                        │
│       │         │                                           │
│       │         ├───► 缓存命中 ──► 返回缓存数据              │
│       │         │                                           │
│       │         └───► 缓存未命中 ──► 调用 Binance API        │
│       │                              │                      │
│       │                              └───► 保存到缓存        │
│       │                                                     │
│       ▼                                                     │
│  [返回 K线数据列表]                                          │
│       │                                                     │
│       ├───► 1m K线：用于交易模拟                             │
│       │                                                     │
│       └───► 1d K线：用于行情判断                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 数据缓存机制

K 线数据缓存由 [binance_kline_fetcher.py](../binance_kline_fetcher.py) 的 `KlineFetcher` 类实现：

**缓存策略：**

1. **本地 SQLite 数据库**：每个交易对和周期单独存储
2. **表命名规则**：`klines_{symbol}_{interval}`（如 `klines_BTCUSDT_1m`）
3. **增量更新**：只获取缺失的时间段数据
4. **自动去重**：使用 `INSERT OR REPLACE` 避免重复数据

**缓存查询流程：**

```python
def query_cache(self, symbol: str, interval: str, 
                start_time: int = None, end_time: int = None) -> List[Dict]:
    """从缓存查询 K 线数据"""
    table = self._get_table_name(symbol, interval)
    
    # 检查表是否存在
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
    if not cursor.fetchone():
        return []
    
    # 查询数据
    if start_time and end_time:
        cursor.execute(f"""
            SELECT timestamp, open, high, low, close, volume 
            FROM {table} 
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (start_time, end_time))
    
    return klines
```

**缺失检测：**

```python
def _find_missing_ranges(self, symbol: str, interval: str,
                          start_time: int, end_time: int) -> List[Tuple[int, int]]:
    """找出缺失的时间范围"""
    # 获取已有数据的时间范围
    cursor.execute(f"""
        SELECT MIN(timestamp), MAX(timestamp), COUNT(*) 
        FROM {table}
    """)
    
    # 计算预期的 K 线数量
    expected_count = int((end_time - start_time) / (1000 * 60 * minutes))
    
    # 如果缓存数量小于预期数量，说明有缺失
    if count < expected_count * 0.9:
        # 找出缺失的时间范围
        ...
    
    return missing_ranges
```

---

## 4. K 线处理流程

### 4.1 _on_kline() 主处理方法

每根 K 线都会调用 `_on_kline()` 方法进行处理，这是回测的核心循环。

**代码位置：** [binance_backtest.py#L1006-L1042](../binance_backtest.py#L1006-L1042)

```python
def _on_kline(self, kline: dict):
    """处理 K 线数据（重写）"""
    self.kline_count += 1
    
    # 1. 解析 K 线数据
    open_price = Decimal(str(kline.get("open", kline.get("o", 0))))
    high_price = Decimal(str(kline.get("high", kline.get("h", 0))))
    low_price = Decimal(str(kline.get("low", kline.get("l", 0))))
    close_price = Decimal(str(kline.get("close", kline.get("c", 0))))
    timestamp = kline.get("timestamp", kline.get("t", 0))
    
    kline_time = datetime.fromtimestamp(timestamp / 1000) if timestamp else datetime.now()
    
    # 2. 检查行情状态（每天第一根 1m K线时更新）
    new_status = self._check_market_status(kline)
    
    # 3. 处理行情状态变化
    if new_status != self.current_market_status:
        self._on_market_status_change(
            self.current_market_status, 
            new_status, 
            kline,
            confidence=0.0,
            reason=''
        )
    
    # 4. 更新交易时段
    if self._current_trading_period:
        self._current_trading_period.end_time = kline_time
    
    # 5. 如果不允许交易，跳过
    if not self.trading_enabled:
        return
    
    # 6. 检查 A1 超时
    self._check_first_entry_timeout(close_price, kline_time)
    
    # 7. 处理入场
    self._process_entry(low_price, close_price, kline_time)
    
    # 8. 处理出场
    self._process_exit(open_price, high_price, low_price, close_price, kline_time)
```

**处理流程图：**

```
┌─────────────────────────────────────────────────────────────┐
│                    K线处理流程                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [接收 K线数据]                                              │
│       │                                                     │
│       ▼                                                     │
│  [解析价格数据] ──► open, high, low, close, timestamp       │
│       │                                                     │
│       ▼                                                     │
│  [检查行情状态] ◄──── 每天第一根 1m K线时更新                │
│       │                                                     │
│       ├───► 状态变化 ──► _on_market_status_change()         │
│       │              │                                      │
│       │              ├───► 趋势下跌 ──► 平仓停止交易         │
│       │              │                                      │
│       │              └───► 震荡 ──► 恢复交易                 │
│       │                                                     │
│       ▼                                                     │
│  [检查交易许可]                                              │
│       │                                                     │
│       ├───► 不允许交易 ──► 返回                             │
│       │                                                     │
│       ▼                                                     │
│  [检查 A1 超时] ──► 超时则重新挂单                           │
│       │                                                     │
│       ▼                                                     │
│  [处理入场] ──► _process_entry()                            │
│       │                                                     │
│       ▼                                                     │
│  [处理出场] ──► _process_exit()                             │
│       │                                                     │
│       ▼                                                     │
│  [返回，等待下一根 K线]                                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 行情状态判断逻辑

行情状态判断由 [market_status_detector.py](../market_status_detector.py) 模块实现。

**代码位置：** [binance_backtest.py#L839-L863](../binance_backtest.py#L839-L863)

```python
def _check_market_status(self, kline_1m: dict) -> MarketStatus:
    """检查行情状态
    
    每天第一根 1m K线时更新行情判断
    """
    current_ts = kline_1m['timestamp']
    current_date = datetime.fromtimestamp(current_ts / 1000).date()
    
    # 如果今天已经判断过，直接返回
    if self._last_check_date == current_date:
        return self.current_market_status
    
    self._last_check_date = current_date
    
    # 获取当前时间之前的 1d K线
    market_klines = self._get_market_klines_before(current_ts)
    
    # 检查数据是否足够
    min_klines = self.market.get('min_market_klines', 20)
    if len(market_klines) < min_klines:
        logger.warning(f"[行情判断] K线数据不足: {len(market_klines)} < {min_klines}")
        return self.current_market_status
    
    # 调用行情算法计算
    result = self.market_detector.algorithm.calculate(market_klines, self.market)
    
    logger.info(f"[行情判断] {current_date}: {result.status.value}, 置信度={result.confidence:.2f}, 原因={result.reason}")
    
    return result.status
```

**支持的行情算法：**

| 算法名称 | 类名 | 说明 |
|---------|------|------|
| `always_ranging` | AlwaysRangingAlgorithm | 始终返回震荡（用于对比测试） |
| `realtime` | RealTimeStatusAlgorithm | 实时价格行为 + 波动率判断 |
| `improved` | ImprovedStatusAlgorithm | 支撑阻力位 + 箱体震荡识别 |
| `dual_thrust` | DualThrustAlgorithm | Dual Thrust 突破区间判断 |
| `adx` | ADXAlgorithm | ADX 趋势强度判断 |
| `composite` | CompositeAlgorithm | 多指标综合判断 |

**行情状态变化处理：**

```python
def _on_market_status_change(self, old_status: MarketStatus, new_status: MarketStatus, 
                              kline: dict, confidence: float = 0.0, reason: str = ''):
    """处理行情状态变化"""
    price = Decimal(str(kline['close']))
    timestamp = kline['timestamp']
    time = datetime.fromtimestamp(timestamp / 1000)
    
    # 判断是否为趋势状态
    is_trending = new_status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]
    was_trending = old_status in [MarketStatus.TRENDING_UP, MarketStatus.TRENDING_DOWN]
    
    # 判断是否为可交易状态
    is_trading_status = new_status in [MarketStatus.RANGING, MarketStatus.TRENDING_UP]
    was_trading_status = old_status in [MarketStatus.RANGING, MarketStatus.TRENDING_UP]
    
    action = 'continue'
    
    # 下跌趋势：平仓停止交易
    if new_status == MarketStatus.TRENDING_DOWN and not old_status == MarketStatus.TRENDING_DOWN:
        if self.trading_enabled:
            self._close_all_positions(price, timestamp, 'market_status_change', time)
            self.trading_enabled = False
            action = 'stop_trading'
            self._end_trading_period(time)
    
    # 恢复交易
    elif is_trading_status and not was_trading_status:
        if not self.trading_enabled:
            self.trading_enabled = True
            self._create_first_order(price, kline)
            action = 'start_trading'
            self._start_trading_period(time, new_status)
    
    # 记录事件
    event = MarketStatusEvent(
        timestamp=timestamp,
        time=time,
        status=new_status,
        confidence=confidence,
        reason=reason,
        action=action,
        price=price
    )
    self.market_status_events.append(event)
    self.current_market_status = new_status
```

---

## 5. 交易执行流程

详细的交易执行流程图请参考 [flowcharts.md](./flowcharts.md#2-交易执行流程图)。

### 5.1 订单创建

订单创建由 `_create_order()` 方法实现。

**代码位置：** [binance_backtest.py#L148-L262](../binance_backtest.py#L148-L262)

```python
def _create_order(self, level: int, base_price: Decimal, klines: List[Dict] = None, 
                   group_id: int = None, kline_time: datetime = None) -> Autofish_Order:
    """创建订单
    
    参数:
        level: 层级 (1, 2, 3, 4)
        base_price: 基准价格
        klines: K 线数据（用于策略计算，仅 A1 使用）
        group_id: 轮次 ID
        kline_time: K 线时间（用于设置创建时间）
    """
    # 1. 获取配置参数
    grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
    exit_profit = self.config.get("exit_profit", Decimal("0.01"))
    stop_loss = self.config.get("stop_loss", Decimal("0.08"))
    
    # 2. 根据资金池策略动态获取 total_amount
    if hasattr(self, 'capital_pool'):
        if self.capital_pool.strategy == 'guding':
            total_amount = self.capital_pool.initial_capital
        elif self.capital_pool.strategy == 'fuli':
            total_amount = self.capital_pool.trading_capital + self.capital_pool.profit_pool
        else:
            total_amount = self.capital_pool.trading_capital
    else:
        total_amount = self.config.get("total_amount_quote", Decimal("1200"))
    
    # 3. 创建入场价格策略
    strategy_config = self.config.get("entry_price_strategy", {"name": "fixed"})
    strategy_name = strategy_config.get("strategy", strategy_config.get("name", "fixed"))
    strategy_params = strategy_config.get(strategy_name, strategy_config.get("params", {}))
    strategy = EntryPriceStrategyFactory.create(strategy_name, **strategy_params)
    
    # 4. 创建订单计算器
    order_calculator = Autofish_OrderCalculator(
        grid_spacing=grid_spacing,
        exit_profit=exit_profit,
        stop_loss=stop_loss,
        entry_strategy=strategy
    )
    
    # 5. 确定 group_id
    if group_id is None:
        if level == 1:
            actual_group_id = self.chain_state.group_id + 1
        else:
            actual_group_id = self.chain_state.group_id
    else:
        actual_group_id = group_id
    
    # 6. 计算权重和资金分配
    weights = self._get_weights()
    if weights and level in weights:
        weight = weights[level]
        stake_amount = total_amount * weight
        
        # A1 使用入场策略计算入场价
        if level == 1:
            entry_price = strategy.calculate_entry_price(
                current_price=base_price,
                level=level,
                grid_spacing=grid_spacing,
                klines=klines
            )
        else:
            # A2+ 使用固定网格间距
            entry_price = base_price * (Decimal("1") - grid_spacing * level)
        
        # 计算止盈止损价格
        take_profit_price = entry_price * (Decimal("1") + exit_profit)
        stop_loss_price = entry_price * (Decimal("1") - stop_loss)
        
        # 计算数量
        quantity = stake_amount / entry_price
        
        # 7. 创建订单对象
        order = Autofish_Order(
            level=level,
            entry_price=entry_price,
            quantity=quantity,
            stake_amount=stake_amount,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            state="pending",
            created_at=kline_time.strftime('%Y-%m-%d %H:%M:%S') if kline_time else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            group_id=actual_group_id,
        )
        
        return order
```

**入场价格策略：**

| 策略名称 | 类名 | 计算公式 |
|---------|------|---------|
| `fixed` | FixedGridStrategy | 入场价 = 当前价 × (1 - 网格间距 × 层级) |
| `atr` | ATRDynamicStrategy | 网格间距 = ATR × 乘数 / 当前价 |
| `bollinger` | BollingerBandStrategy | 入场价 = max(下轨, 当前价 × (1 - 最小间距)) |
| `support` | SupportLevelStrategy | 入场价 = max(支撑位, 当前价 × (1 - 最小间距)) |
| `composite` | CompositeStrategy | 综合多种技术指标 |

### 5.2 入场处理

入场处理由 `_process_entry()` 方法实现。

**代码位置：** [binance_backtest.py#L264-L311](../binance_backtest.py#L264-L311)

```python
def _process_entry(self, low_price: Decimal, current_price: Decimal, kline_time: datetime = None):
    """处理入场"""
    max_level = self.config.get("max_entries", 4)
    
    # 1. 获取挂单中的订单
    pending_order = self.chain_state.get_pending_order()
    
    if pending_order:
        # 2. 检查是否触发入场（K线最低价 <= 入场价）
        if Autofish_OrderCalculator.check_entry_triggered(low_price, pending_order.entry_price):
            # 3. 更新订单状态
            pending_order.set_state("filled", "K线触发入场")
            pending_order.filled_at = kline_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # 4. 更新 group_id
            if pending_order.level == 1:
                old_group_id = self.chain_state.group_id
                self.chain_state.group_id = pending_order.group_id
                logger.info(f"[新轮次开始] A1 成交: group_id 从 {old_group_id} 变更为 {pending_order.group_id}")
            
            # 5. 记录入场资金
            pending_order.entry_capital = self.capital_strategy.calculate_entry_capital(
                self.capital_pool, pending_order.level, self.chain_state
            )
            pending_order.entry_total_capital = self.capital_strategy.calculate_entry_total_capital(
                self.capital_pool, pending_order.level, self.chain_state
            )
            
            # 6. 创建下一层级订单（链式下单）
            next_level = pending_order.level + 1
            if next_level <= max_level:
                new_order = self._create_order(next_level, pending_order.entry_price, 
                                               group_id=self.chain_state.group_id, kline_time=kline_time)
                self.chain_state.orders.append(new_order)
```

**入场触发条件：**

```
入场触发条件：K线最低价 <= 入场价格

示例：
  入场价格：50000
  K线数据：open=50100, high=50200, low=49950, close=50050
  
  判断：49950 <= 50000 → 触发入场
```

### 5.3 出场处理

出场处理由 `_process_exit()` 方法实现。

**代码位置：** [binance_backtest.py#L313-L386](../binance_backtest.py#L313-L386)

```python
def _process_exit(self, open_price: Decimal, high_price: Decimal, low_price: Decimal, 
                   current_price: Decimal, kline_time: datetime = None):
    """处理出场"""
    leverage = self.config.get("leverage", Decimal("10"))
    
    # 1. 获取已成交的订单
    filled_orders = self.chain_state.get_filled_orders()
    
    # 2. 找出触发止盈和止损的订单
    tp_orders = [o for o in filled_orders if o.state == "filled" and high_price >= o.take_profit_price]
    sl_orders = [o for o in filled_orders if o.state == "filled" and low_price <= o.stop_loss_price]
    
    # 3. 排序：止盈按价格升序，止损按价格降序
    tp_orders.sort(key=lambda o: o.take_profit_price)
    sl_orders.sort(key=lambda o: o.stop_loss_price, reverse=True)
    
    closed_levels = []
    
    # 4. 根据 K 线阴阳线判断触发顺序
    if current_price >= open_price:
        # 阳线 - 假设先跌后涨，止损先触发
        for order in sl_orders:
            self._close_order(order, "stop_loss", order.stop_loss_price, leverage, kline_time)
            closed_levels.append(order.level)
        
        for order in tp_orders:
            if order.level not in closed_levels:
                self._close_order(order, "take_profit", order.take_profit_price, leverage, kline_time)
                closed_levels.append(order.level)
    else:
        # 阴线 - 假设先涨后跌，止盈先触发
        for order in tp_orders:
            self._close_order(order, "take_profit", order.take_profit_price, leverage, kline_time)
            closed_levels.append(order.level)
        
        for order in sl_orders:
            if order.level not in closed_levels:
                self._close_order(order, "stop_loss", order.stop_loss_price, leverage, kline_time)
                closed_levels.append(order.level)
    
    # 5. 出场后重建订单
    if closed_levels:
        self.chain_state.cancel_pending_orders()
        
        # 检查行情状态
        if not self.trading_enabled:
            return
        
        # 检查是否一轮订单链结束
        if self.chain_state.is_order_chain_finished():
            # 一轮结束，创建新的 A1
            new_order = self._create_order(1, current_price, klines=self.klines_history, kline_time=kline_time)
            self.chain_state.orders.append(new_order)
        else:
            # 还有其他订单在场内，重建同级别的挂单
            for level in closed_levels:
                new_order = self._create_order(level, current_price, group_id=self.chain_state.group_id, kline_time=kline_time)
                self.chain_state.orders.append(new_order)
```

**出场触发条件：**

```
止盈触发条件：K线最高价 >= 止盈价格
止损触发条件：K线最低价 <= 止损价格

示例：
  止盈价格：50500
  止损价格：46000
  K线数据：open=50000, high=50600, low=49900, close=50550
  
  判断：
    50600 >= 50500 → 触发止盈
    49900 > 46000 → 未触发止损
```

**同时触发处理：**

当一根 K 线同时触发止盈和止损时，根据 K 线阴阳线判断触发顺序：

- **阳线**（收盘价 >= 开盘价）：假设先跌后涨，止损先触发
- **阴线**（收盘价 < 开盘价）：假设先涨后跌，止盈先触发

### 5.4 平仓处理

平仓处理由 `_close_order()` 方法实现。

**代码位置：** [binance_backtest.py#L388-L443](../binance_backtest.py#L388-L443)

```python
def _close_order(self, order: Autofish_Order, reason: str, close_price: Decimal, 
                  leverage: Decimal, kline_time: datetime = None):
    """平仓"""
    # 1. 更新订单状态
    order.set_state("closed", reason)
    order.close_price = close_price
    
    # 2. 计算盈亏
    order.profit = Autofish_OrderCalculator(leverage=leverage).calculate_profit(order, close_price)
    order.closed_at = kline_time.strftime('%Y-%m-%d %H:%M:%S')
    
    # 3. 计算收益率
    if order.stake_amount and order.stake_amount > 0:
        trade_return = order.profit / order.stake_amount
        self.results["trade_returns"].append(trade_return)
    
    # 4. 更新最大盈亏
    if order.profit > self.results["max_profit"]:
        self.results["max_profit"] = order.profit
    if order.profit < self.results["max_loss"]:
        self.results["max_loss"] = order.profit
    
    # 5. 更新统计
    if reason == "take_profit":
        self.results["win_trades"] += 1
        self.results["total_profit"] += order.profit
    else:
        self.results["loss_trades"] += 1
        self.results["total_loss"] += abs(order.profit)
    
    # 6. 更新资金池
    self._update_capital_after_trade(order.profit, kline_time)
    
    # 7. 记录交易详情
    self.results["total_trades"] += 1
    self.results["trades"].append({
        "level": order.level,
        "group_id": order.group_id,
        "entry_price": float(order.entry_price),
        "exit_price": float(close_price),
        "creation_time": order.created_at,
        "entry_time": order.filled_at,
        "exit_time": order.closed_at,
        "profit": float(order.profit),
        "reason": reason,
        "trade_type": "take_profit" if reason == "take_profit" else "stop_loss",
        "quantity": float(order.quantity) if order.quantity else 0,
        "stake": float(order.stake_amount) if order.stake_amount else 0,
        "entry_capital": float(order.entry_capital) if order.entry_capital else 0,
        "entry_total_capital": float(entry_total_capital) if entry_total_capital else 0,
    })
```

**盈亏计算公式：**

```python
def calculate_profit(self, order: Autofish_Order, close_price: Decimal) -> Decimal:
    """计算盈亏"""
    profit = order.stake_amount * (close_price - order.entry_price) / order.entry_price * self.leverage
    return profit
```

**示例：**

```
入场价格：50000
出场价格：50500（止盈）
投入金额：100 USDT
杠杆倍数：10x

盈亏计算：
  profit = 100 * (50500 - 50000) / 50000 * 10
         = 100 * 0.01 * 10
         = 10 USDT
```

---

## 6. 结果统计流程

### 6.1 统计数据结构

回测结果存储在 `results` 字典中：

```python
self.results = {
    # 基础统计
    "total_trades": 0,           # 总交易次数
    "win_trades": 0,             # 盈利次数
    "loss_trades": 0,            # 亏损次数
    "total_profit": Decimal("0"), # 总盈利
    "total_loss": Decimal("0"),   # 总亏损
    
    # 价格统计
    "first_price": None,          # 第一根 K 线开盘价
    "last_price": None,           # 最后一根 K 线收盘价
    
    # 收益统计
    "trade_returns": [],          # 每笔交易收益率
    "max_profit": Decimal("0"),   # 单笔最大盈利
    "max_loss": Decimal("0"),     # 单笔最大亏损
    
    # 交易详情
    "trades": [],                 # 交易记录列表
    
    # 行情统计（仅 MarketAwareBacktestEngine）
    "market_status_events": [],   # 行情状态变化事件
    "trading_periods": [],        # 交易时段列表
    "total_trading_minutes": 0,   # 总交易时间（分钟）
    "total_stopped_minutes": 0,   # 总停止时间（分钟）
    "market_statistics": {},      # 行情统计
}
```

### 6.2 结果打印

回测结束后调用 `_print_summary()` 方法打印结果。

**代码位置：** [binance_backtest.py#L1165-L1198](../binance_backtest.py#L1165-L1198)

```python
def _print_summary(self):
    """打印回测结果"""
    # 1. 计算核心指标
    net_profit = self.results["total_profit"] - self.results["total_loss"]
    win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
               if self.results["total_trades"] > 0 else 0)
    
    market_stats = self.results.get('market_statistics', {})
    
    # 2. 打印结果
    print("\n" + "=" * 60)
    print("📊 回测结果")
    print("=" * 60)
    print(f"  回测时间: {self.start_time.strftime('%Y-%m-%d %H:%M')} - {self.end_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"  K线数量: {self.kline_count}")
    print(f"  总交易: {self.results['total_trades']}")
    print(f"  盈利次数: {self.results['win_trades']}")
    print(f"  亏损次数: {self.results['loss_trades']}")
    print(f"  胜率: {win_rate:.2f}%")
    print(f"  总盈利: {float(self.results['total_profit']):.2f} USDT")
    print(f"  总亏损: {float(self.results['total_loss']):.2f} USDT")
    print(f"  净收益: {float(net_profit):.2f} USDT")
    
    # 3. 打印行情统计（如果有）
    print("\n📈 行情统计:")
    print(f"  行情状态变化: {market_stats.get('total_events', 0)} 次")
    print(f"  交易时间占比: {market_stats.get('trading_pct', 0):.1f}%")
    print(f"  停止时间占比: {market_stats.get('stopped_pct', 0):.1f}%")
    
    print("=" * 60)
```

### 6.3 数据库保存

回测结果通过 `_save_to_database()` 函数保存到 SQLite 数据库。

**代码位置：** [binance_backtest.py#L1316-L1458](../binance_backtest.py#L1316-L1458)

```python
def _save_to_database(args, engine, date_range_str, amplitude, market, entry, timeout, capital):
    """保存行情感知回测结果到数据库"""
    from database.test_results_db import TestResultsDB, TestResult, TradeDetail
    
    db = TestResultsDB()
    
    # 1. 准备参数
    id = args.id if args.id else 0
    params = {
        "symbol": args.symbol,
        "date_range": args.date_range,
        "amplitude": amplitude,
        "market": market,
        "entry": entry,
        "timeout": timeout,
        "capital": capital,
    }
    
    results = engine.results
    market_stats = results.get('market_statistics', {})
    
    # 2. 计算指标
    total_trades = results.get('total_trades', 0)
    win_trades = results.get('win_trades', 0)
    loss_trades = results.get('loss_trades', 0)
    total_profit = float(results.get('total_profit', 0))
    total_loss = float(results.get('total_loss', 0))
    net_profit = total_profit - total_loss
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
    
    total_amount = float(engine.config.get('total_amount_quote', 1200))
    roi = (net_profit / total_amount * 100) if total_amount > 0 else 0
    
    first_price = float(results.get('first_price', 0))
    last_price = float(results.get('last_price', 0))
    price_change = ((last_price - first_price) / first_price * 100) if first_price > 0 else 0
    excess_return = roi - price_change
    
    # 3. 计算平均订单成交时间和平均持仓时间
    trades = results.get('trades', [])
    total_execution_time = 0
    total_holding_time = 0
    valid_execution_trades = 0
    valid_holding_trades = 0
    
    for trade in trades:
        # 成交时间：entry_time - creation_time
        if trade.get('creation_time') and trade.get('entry_time'):
            creation_time = datetime.strptime(trade['creation_time'], '%Y-%m-%d %H:%M:%S')
            entry_time = datetime.strptime(trade['entry_time'], '%Y-%m-%d %H:%M:%S')
            execution_time = (entry_time - creation_time).total_seconds() / 60
            if execution_time >= 0:
                total_execution_time += execution_time
                valid_execution_trades += 1
        
        # 持仓时间：exit_time - entry_time
        if trade.get('entry_time') and trade.get('exit_time'):
            entry_time = datetime.strptime(trade['entry_time'], '%Y-%m-%d %H:%M:%S')
            exit_time = datetime.strptime(trade['exit_time'], '%Y-%m-%d %H:%M:%S')
            holding_time = (exit_time - entry_time).total_seconds() / 60
            if holding_time >= 0:
                total_holding_time += holding_time
                valid_holding_trades += 1
    
    avg_execution_time = total_execution_time / valid_execution_trades if valid_execution_trades > 0 else 0
    avg_holding_time = total_holding_time / valid_holding_trades if valid_holding_trades > 0 else 0
    
    # 4. 创建测试结果记录
    result = TestResult(
        case_id=id,
        symbol=args.symbol,
        interval="1m",
        start_time=engine.start_time.strftime('%Y-%m-%d %H:%M'),
        end_time=engine.end_time.strftime('%Y-%m-%d %H:%M'),
        klines_count=engine.kline_count,
        total_trades=total_trades,
        win_trades=win_trades,
        loss_trades=loss_trades,
        win_rate=win_rate,
        total_profit=total_profit,
        total_loss=total_loss,
        net_profit=net_profit,
        roi=roi,
        price_change=price_change,
        excess_return=excess_return,
        profit_factor=0,
        sharpe_ratio=0,
        max_profit_trade=float(results.get('max_profit', 0)),
        max_loss_trade=float(results.get('max_loss', 0)),
        trading_time_ratio=market_stats.get('trading_pct', 0),
        stopped_time_ratio=market_stats.get('stopped_pct', 0),
        market_status_changes=market_stats.get('total_events', 0),
        market_algorithm=market.get('algorithm', 'always_ranging'),
        capital=json.dumps(capital),
        order_group_count=engine.chain_state.group_id,
        avg_execution_time=avg_execution_time,
        avg_holding_time=avg_holding_time,
    )
    result_id = db.create_result(result)
    
    # 5. 保存资金统计
    capital_stats = engine.capital_pool.get_statistics() if engine.capital_pool and hasattr(engine.capital_pool, 'get_statistics') else {}
    if capital_stats and result_id:
        statistics_id = db.save_capital_statistics(result_id, capital_stats)
        if statistics_id and capital_stats.get('capital_history'):
            db.save_capital_history(result_id, statistics_id, capital_stats['capital_history'])
    
    # 6. 保存交易详情
    if trades and result_id:
        sorted_trades = sorted(trades, key=lambda x: (x.get('exit_time', ''), x.get('entry_time', '')))
        trade_details = []
        for i, t in enumerate(sorted_trades):
            trade_details.append(TradeDetail(
                result_id=result_id,
                order_group_id=t.get('group_id', 0),
                trade_seq=i + 1,
                level=str(t.get('level', '')),
                entry_price=float(t.get('entry_price', 0)),
                exit_price=float(t.get('exit_price', 0)),
                creation_time=t.get('creation_time', ''),
                entry_time=t.get('entry_time', ''),
                exit_time=t.get('exit_time', ''),
                trade_type=t.get('trade_type', ''),
                profit=float(t.get('profit', 0)),
                quantity=float(t.get('quantity', 0)),
                stake=float(t.get('stake', 0)),
                entry_capital=float(t.get('entry_capital', 0)),
                entry_total_capital=float(t.get('entry_total_capital', 0)),
            ))
        db.save_trade_details(result_id, trade_details)
    
    print(f"\n✅ 结果已保存到数据库: result_id={result_id}")
```

**数据库表结构：**

| 表名 | 说明 |
|------|------|
| `test_cases` | 测试用例表 |
| `test_results` | 测试结果表 |
| `trade_details` | 交易详情表 |
| `capital_statistics` | 资金统计表 |
| `capital_history` | 资金历史表 |

---

## 7. 与核心模块的交互关系

### 7.1 模块依赖关系图

```
┌─────────────────────────────────────────────────────────────┐
│                    binance_backtest.py                      │
│  MarketAwareBacktestEngine                                  │
└─────────────────────────────────────────────────────────────┘
         │              │              │              │
         │              │              │              │
         ▼              ▼              ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│autofish_    │ │market_      │ │binance_     │ │test_        │
│core.py      │ │status_      │ │kline_       │ │results_     │
│             │ │detector.py  │ │fetcher.py   │ │db.py        │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
     │                │                │                │
     │                │                │                │
     ▼                ▼                ▼                ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│Autofish_    │ │MarketStatus │ │KlineFetcher │ │TestResultsDB│
│Order        │ │Detector     │ │             │ │             │
│Autofish_    │ │StatusAlgo   │ │fetch_kline()│ │create_result│
│ChainState   │ │             │ │             │ │save_trades  │
│WeightCalc   │ │calculate()  │ │             │ │             │
│OrderCalc    │ │             │ │             │ │             │
│CapitalPool  │ │             │ │             │ │             │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
```

### 7.2 核心模块功能说明

#### 7.2.1 autofish_core.py

**主要类：**

| 类名 | 功能 | 使用位置 |
|------|------|---------|
| `Autofish_Order` | 订单数据类 | 创建和管理订单 |
| `Autofish_ChainState` | 链式状态管理 | 管理所有订单状态 |
| `Autofish_WeightCalculator` | 权重计算器 | 计算各层级资金分配 |
| `Autofish_OrderCalculator` | 订单计算器 | 计算入场价、止盈止损价 |
| `Autofish_AmplitudeConfig` | 振幅配置加载器 | 加载振幅分析配置 |
| `CapitalPoolFactory` | 资金池工厂 | 创建资金池实例 |
| `EntryCapitalStrategyFactory` | 入场资金策略工厂 | 创建入场资金策略 |

**使用示例：**

```python
# 创建链式状态
chain_state = Autofish_ChainState(base_price=Decimal("50000"))

# 创建订单
order = Autofish_Order(
    level=1,
    entry_price=Decimal("49500"),
    quantity=Decimal("0.002"),
    stake_amount=Decimal("100"),
    take_profit_price=Decimal("50000"),
    stop_loss_price=Decimal("45500"),
    state="pending",
    group_id=1,
)

# 添加订单到状态
chain_state.orders.append(order)

# 获取挂单中的订单
pending_order = chain_state.get_pending_order()

# 获取已成交的订单
filled_orders = chain_state.get_filled_orders()
```

#### 7.2.2 market_status_detector.py

**主要类：**

| 类名 | 功能 | 使用位置 |
|------|------|---------|
| `MarketStatus` | 市场状态枚举 | 表示市场状态 |
| `MarketStatusDetector` | 市场行情判断器 | 判断市场状态 |
| `StatusAlgorithm` | 算法基类 | 定义算法接口 |
| `DualThrustAlgorithm` | Dual Thrust 算法 | 基于 Dual Thrust 判断 |
| `ADXAlgorithm` | ADX 算法 | 基于 ADX 判断 |
| `CompositeAlgorithm` | 组合算法 | 多指标综合判断 |

**使用示例：**

```python
# 创建行情检测器
algorithm = DualThrustAlgorithm({'n_days': 4, 'k1': 0.4, 'k2': 0.4})
detector = MarketStatusDetector(algorithm=algorithm)

# 判断市场状态
result = detector.algorithm.calculate(klines, config)

print(f"市场状态: {result.status.value}")
print(f"置信度: {result.confidence}")
print(f"原因: {result.reason}")
```

#### 7.2.3 binance_kline_fetcher.py

**主要类：**

| 类名 | 功能 | 使用位置 |
|------|------|---------|
| `KlineFetcher` | K 线获取器 | 获取和缓存 K 线数据 |

**主要方法：**

| 方法 | 功能 |
|------|------|
| `fetch_kline()` | 获取 K 线数据（自动缓存） |
| `query_cache()` | 查询缓存数据 |
| `get_cache_status()` | 获取缓存状态 |
| `clear_cache()` | 清空缓存 |

**使用示例：**

```python
# 创建 K 线获取器
fetcher = KlineFetcher()

# 获取 K 线数据
klines = await fetcher.fetch_kline(
    symbol="BTCUSDT",
    interval="1m",
    start_time=int(start_date.timestamp() * 1000),
    end_time=int(end_date.timestamp() * 1000)
)

# 查看缓存状态
status = fetcher.get_cache_status("BTCUSDT", "1m")
```

#### 7.2.4 test_results_db.py

**主要类：**

| 类名 | 功能 | 使用位置 |
|------|------|---------|
| `TestResultsDB` | 测试结果数据库 | 保存和查询测试结果 |
| `TestCase` | 测试用例数据类 | 表示测试用例 |
| `TestResult` | 测试结果数据类 | 表示测试结果 |
| `TradeDetail` | 交易详情数据类 | 表示交易详情 |

**主要方法：**

| 方法 | 功能 |
|------|------|
| `create_result()` | 创建测试结果 |
| `save_trade_details()` | 保存交易详情 |
| `save_capital_statistics()` | 保存资金统计 |
| `save_capital_history()` | 保存资金历史 |
| `get_result()` | 获取测试结果 |
| `list_results()` | 获取结果列表 |

**使用示例：**

```python
# 创建数据库实例
db = TestResultsDB()

# 创建测试结果
result = TestResult(
    case_id=1,
    symbol="BTCUSDT",
    interval="1m",
    start_time="2024-01-01 00:00",
    end_time="2024-06-01 00:00",
    total_trades=100,
    win_trades=60,
    loss_trades=40,
    win_rate=60.0,
    net_profit=500.0,
)
result_id = db.create_result(result)

# 保存交易详情
trade_details = [
    TradeDetail(
        result_id=result_id,
        trade_seq=1,
        level="1",
        entry_price=50000.0,
        exit_price=50500.0,
        profit=10.0,
        trade_type="take_profit",
    )
]
db.save_trade_details(result_id, trade_details)
```

### 7.3 数据流向

```
┌─────────────────────────────────────────────────────────────┐
│                        数据流向总览                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [外部数据源] Binance API / LongPort API                     │
│       │                                                     │
│       ▼                                                     │
│  [K线数据] ──────► KlineFetcher ──────► 缓存到 SQLite       │
│       │                                                     │
│       ▼                                                     │
│  [MarketStatusDetector] ──────► 市场状态（震荡/趋势）        │
│       │                                                     │
│       ▼                                                     │
│  [MarketAwareBacktestEngine]                                │
│       │                                                     │
│       ├───► 创建订单 (Autofish_Order)                       │
│       │                                                     │
│       ├───► 管理状态 (Autofish_ChainState)                  │
│       │                                                     │
│       ├───► 计算盈亏 (Autofish_OrderCalculator)             │
│       │                                                     │
│       └───► 更新资金 (CapitalPool)                          │
│                                                             │
│       ▼                                                     │
│  [结果统计] results 字典                                     │
│       │                                                     │
│       ▼                                                     │
│  [TestResultsDB] ──────► SQLite 数据库                      │
│       │                                                     │
│       ├───► test_results 表                                 │
│       │                                                     │
│       ├───► trade_details 表                                │
│       │                                                     │
│       ├───► capital_statistics 表                           │
│       │                                                     │
│       └───► capital_history 表                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. 总结

本文档详细描述了 Autofish Bot V2 回测程序的完整执行流程：

1. **主入口**：`main()` 函数解析参数、创建引擎、执行回测、保存结果
2. **数据获取**：`KlineFetcher` 获取多周期 K 线数据并缓存到本地
3. **K 线处理**：`_on_kline()` 方法检查行情状态、处理入场出场
4. **交易执行**：创建订单、触发入场、触发出场、计算盈亏
5. **结果统计**：统计数据、打印报告、保存到数据库

更多流程图和决策点说明请参考 [flowcharts.md](./flowcharts.md)。

---

*文档生成时间: 2026-03-26*  
*版本: V2.0*

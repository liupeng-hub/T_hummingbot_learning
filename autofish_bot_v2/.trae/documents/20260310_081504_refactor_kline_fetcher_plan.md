# 重构：K 线数据管理职责分离

## 1. 需求背景

当前设计：
- `binance_backtest.py` 中的 `fetch_klines` 方法包含数据完整性检查逻辑
- 回测模块和数据管理模块职责不清晰

问题：
- 职责混乱：回测代码包含数据管理逻辑
- 代码重复：其他模块需要 K 线数据时也要重复实现

## 2. 目标

将 K 线数据完整性检查逻辑移至 `binance_kline_fetcher.py`：

| 模块 | 职责 |
|------|------|
| `binance_kline_fetcher.py` | 数据管理（获取、缓存、完整性检查、补齐） |
| `binance_backtest.py` | 回测逻辑（仅从 DB 获取数据） |

## 3. 设计方案

### 3.1 流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                      用户执行回测命令                            │
│   python binance_backtest.py --symbol BTCUSDT --days 20         │
│   或                                                            │
│   python binance_backtest.py --date-range "20240101-20240601,..." │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│              1. 回测请求 binance_kline_fetcher 准备数据          │
│   fetcher.ensure_klines(symbol, interval, ...)                  │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│              2. binance_kline_fetcher 检查并补齐数据             │
│   - 计算时间范围（根据参数类型）                                  │
│   - 检查缓存完整性                                                │
│   - 自动获取缺失数据                                              │
│   - 存储到 DB                                                    │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│              3. 回测从 DB 获取数据                                │
│   klines = fetcher.query_cache(symbol, interval, start, end)    │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│              4. 回测引擎处理数据                                  │
│   - 遍历 K 线                                                    │
│   - 模拟订单执行                                                  │
│   - 统计盈亏                                                      │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 新增接口

在 `KlineFetcher` 类中新增 `ensure_klines()` 方法：

```python
async def ensure_klines(self, symbol: str, interval: str,
                        start_time: int = None, end_time: int = None,
                        days: int = None, limit: int = None,
                        auto_fetch: bool = True) -> bool:
    """
    确保 K 线数据完整（检查并补齐）
    
    参数:
        symbol: 交易对
        interval: K 线周期
        start_time: 开始时间戳（毫秒）
        end_time: 结束时间戳（毫秒）
        days: 获取最近 N 天数据
        limit: 获取最近 N 条数据
        auto_fetch: 是否自动获取缺失数据
    
    返回:
        True: 数据已准备好
        False: 数据获取失败
    """
```

### 3.3 时间范围计算逻辑

```python
def _calculate_time_range(self, interval: str, start_time: int = None, end_time: int = None,
                          days: int = None, limit: int = None) -> Tuple[int, int]:
    """计算时间范围
    
    优先级：
    1. start_time/end_time: 直接使用
    2. days: 从当前时间往前推 N 天
    3. limit: 从当前时间往前推 N 条数据
    """
    if start_time and end_time:
        return start_time, end_time
    
    end_time = int(datetime.now().timestamp() * 1000)
    
    if days:
        start_time = end_time - days * 24 * 60 * 60 * 1000
    elif limit:
        interval_minutes = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
            "1d": 1440, "3d": 4320, "1w": 10080
        }
        minutes = interval_minutes.get(interval, 1)
        start_time = end_time - limit * minutes * 60 * 1000
    else:
        # 默认获取最近 1500 条
        start_time = end_time - 1500 * 60 * 1000
    
    return start_time, end_time
```

### 3.4 多段 date-range 处理

```python
# binance_backtest.py main() 函数中

if args.date_range:
    # 支持多段时间范围，用逗号分隔
    range_parts = args.date_range.split(",")
    
    for range_str in range_parts:
        # 解析每段时间范围
        start_date, end_date = parse_date_range(range_str)
        
        # 请求 binance_kline_fetcher 准备数据
        fetcher = KlineFetcher()
        success = await fetcher.ensure_klines(
            symbol=args.symbol,
            interval=args.interval,
            start_time=int(start_date.timestamp() * 1000),
            end_time=int(end_date.timestamp() * 1000) + 86400000 - 1,
            auto_fetch=not args.no_auto_fetch
        )
        
        if success:
            # 从 DB 获取数据
            klines = fetcher.query_cache(...)
            # 执行回测
            ...
```

## 4. 实施步骤

### 步骤 1：修改 binance_kline_fetcher.py

1. 将 `_find_missing_ranges()` 改为 public 方法 `find_missing_ranges()`
2. 新增 `_calculate_time_range()` 方法
3. 新增 `ensure_klines()` 方法
4. 新增 `get_time_range()` 方法

### 步骤 2：修改 binance_backtest.py

1. 简化 `fetch_klines()` 方法
2. 先调用 `KlineFetcher.ensure_klines()` 准备数据
3. 再调用 `KlineFetcher.query_cache()` 获取数据
4. 移除时间范围计算逻辑
5. 移除缓存检查逻辑
6. 移除自动获取逻辑

### 步骤 3：测试验证


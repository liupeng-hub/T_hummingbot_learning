# ensure_klines 方法重构计划

## 任务概述
重构 `ensure_klines` 方法，简化参数：
- 移除 `days` 和 `limit` 参数
- `start_time: int`, `end_time: int` 改为必选参数

## 需要修改的文件和位置

### 1. binance_kline_fetcher.py
**位置**: L445-541

**当前签名:**
```python
async def ensure_klines(self, symbol: str, interval: str,
                        start_time: int = None, end_time: int = None,
                        days: int = None, limit: int = None,
                        auto_fetch: bool = True) -> bool:
```

**修改后签名:**
```python
async def ensure_klines(self, symbol: str, interval: str,
                        start_time: int, end_time: int,
                        auto_fetch: bool = True) -> bool:
```

**修改内容:**
- 移除 `days` 和 `limit` 参数
- 移除 `_calculate_time_range` 调用，直接使用传入的 `start_time/end_time`
- 简化方法逻辑

### 2. binance_backtest.py
**位置**: L452-460, L767-774, L787-793

**L452-460 当前代码:**
```python
success = await fetcher.ensure_klines(
    symbol=symbol,
    interval=interval,
    start_time=start_time,
    end_time=end_time,
    days=days,
    limit=limit,
    auto_fetch=auto_fetch
)
```

**修改后:**
```python
success = await fetcher.ensure_klines(
    symbol=symbol,
    interval=interval,
    start_time=start_time,
    end_time=end_time,
    auto_fetch=auto_fetch
)
```

**L767-774 和 L787-793 同样修改**

### 3. market_status_visualizer.py
**位置**: L116-121 (DataProvider类)

**当前代码:**
```python
await self.fetcher.ensure_klines(
    symbol=symbol,
    interval=interval,
    days=(end_date - start_date).days + 1,
    auto_fetch=True
)
```

**修改后:**
```python
start_time = int(start_date.timestamp() * 1000)
end_time = int(end_date.timestamp() * 1000)
await self.fetcher.ensure_klines(
    symbol=symbol,
    interval=interval,
    start_time=start_time,
    end_time=end_time,
    auto_fetch=True
)
```

### 4. market_status_detector.py
**位置**: L1548-1556

**当前代码:**
```python
success = await fetcher.ensure_klines(
    symbol=symbol,
    interval=interval,
    start_time=start_time,
    end_time=end_time,
    days=days,
    limit=limit,
    auto_fetch=True
)
```

**修改后:**
```python
success = await fetcher.ensure_klines(
    symbol=symbol,
    interval=interval,
    start_time=start_time,
    end_time=end_time,
    auto_fetch=True
)
```

### 5. test_manager.py
**位置**: get_chart_data 函数

**修改内容:**
参考 DataProvider 类实现，使用异步方式获取K线：
1. 调用 `ensure_klines` 确保数据完整
2. 调用 `query_cache` 获取缓存数据

**修改后代码:**
```python
import asyncio

async def fetch_klines_async(symbol, interval, start_time, end_time):
    fetcher = KlineFetcher()
    await fetcher.ensure_klines(symbol, interval, start_time, end_time, auto_fetch=True)
    return fetcher.query_cache(symbol, interval, start_time, end_time)

@app.route('/api/results/<result_id>/chart', methods=['GET'])
def get_chart_data(result_id):
    # ...
    if symbol and start_time and end_time:
        try:
            raw_klines = asyncio.run(fetch_klines_async(symbol, interval, start_ts, end_ts))
            # ...
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
```

## 实施步骤

1. **修改 binance_kline_fetcher.py**
   - 修改 `ensure_klines` 方法签名和实现
   - 可选：保留 `_calculate_time_range` 供其他地方使用

2. **修改 binance_backtest.py**
   - 修改 L452-460 处调用
   - 修改 L767-774 处调用
   - 修改 L787-793 处调用

3. **修改 market_status_visualizer.py**
   - 修改 L116-121 处调用

4. **修改 market_status_detector.py**
   - 修改 L1548-1556 处调用

5. **修改 test_manager.py**
   - 添加异步获取K线的辅助函数
   - 修改 get_chart_data 函数使用异步方式

6. **验证**
   - 重启所有相关服务
   - 测试K线获取功能

# K线获取方法统一重构计划

## 任务概述
将所有 K 线获取逻辑统一使用 `fetch_and_cache` 方法，简化代码并移除冗余。

## fetch_and_cache 方法签名
```python
async def fetch_and_cache(self, symbol: str, interval: str,
                           start_time: int = None, end_time: int = None,
                           days: int = None) -> List[Dict]:
    """获取 K 线并缓存
    
    返回: K 线数据列表
    """
```

**注意：** 根据用户反馈，`days` 参数也将被移除，只保留 `start_time` 和 `end_time` 作为必选参数。

## 修改后的 fetch_and_cache 签名
```python
async def fetch_and_cache(self, symbol: str, interval: str,
                           start_time: int, end_time: int) -> List[Dict]:
    """获取 K 线并缓存
    
    参数:
        symbol: 交易对
        interval: K 线周期
        start_time: 开始时间戳（毫秒，必选）
        end_time: 结束时间戳（毫秒，必选）
    
    返回: K 线数据列表
    """
```

## 需要修改的文件

### 1. binance_kline_fetcher.py

#### fetch_and_cache 方法 (L407-443)
**修改签名：** 移除 `days` 参数，`start_time` 和 `end_time` 改为必选

```python
async def fetch_and_cache(self, symbol: str, interval: str,
                           start_time: int, end_time: int) -> List[Dict]:
    """获取 K 线并缓存"""
    print(f"\n{'='*60}")
    print(f"📊 {symbol} {interval}")
    print(f"  时间范围: {datetime.fromtimestamp(start_time/1000).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(end_time/1000).strftime('%Y-%m-%d')}")
    print(f"{'='*60}")
    
    missing_ranges = self._find_missing_ranges(symbol, interval, start_time, end_time)
    
    if not missing_ranges:
        print(f"✅ 缓存已完整，无需更新")
        return self.query_cache(symbol, interval, start_time, end_time)
    
    print(f"📋 缺失 {len(missing_ranges)} 个时间段:")
    for range_start, range_end in missing_ranges:
        print(f"  - {datetime.fromtimestamp(range_start/1000).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(range_end/1000).strftime('%Y-%m-%d')}")
    
    for range_start, range_end in missing_ranges:
        klines = await self._fetch_from_api(symbol, interval, range_start, range_end)
        if klines:
            self._save_to_cache(symbol, interval, klines)
    
    return self.query_cache(symbol, interval, start_time, end_time)
```

#### 删除冗余方法
- 删除 `ensure_klines` 方法 (L475-541)
- 删除 `_calculate_time_range` 方法 (L445-473)

### 2. binance_backtest.py

#### fetch_klines 方法 (L432-477) - 删除
此方法可以完全删除，调用处直接使用 `fetch_and_cache`

#### run 方法 (L525)
**当前调用：**
```python
klines = await self.fetch_klines(symbol, interval, limit, days, start_time, end_time, auto_fetch)
```

**修改后：**
```python
from binance_kline_fetcher import KlineFetcher

fetcher = KlineFetcher()
klines = await fetcher.fetch_and_cache(symbol, interval, start_time, end_time)
```

#### fetch_multi_interval_klines 方法 (L755-800)
**当前代码：**
```python
success = await fetcher.ensure_klines(...)
actual_start, actual_end = fetcher.get_time_range()
klines_1m = fetcher.query_cache(...)
# ...
success = await fetcher.ensure_klines(...)
klines_1d = fetcher.query_cache(...)
```

**修改后：**
```python
klines_1m = await fetcher.fetch_and_cache(symbol, interval, start_time, end_time)

market_interval = self.market.get('interval', '1d')
market_start = start_time - (self.market.get('min_market_klines', 20) * 86400000)

klines_1d = await fetcher.fetch_and_cache(symbol, market_interval, market_start, end_time)
```

### 3. market_status_visualizer.py

#### DataProvider.get_klines (L105-130)
**当前代码：**
```python
async def get_klines(self, symbol: str, interval: str, start_date: datetime, end_date: datetime) -> List[Dict]:
    start_time = int(start_date.timestamp() * 1000)
    end_time = int(end_date.timestamp() * 1000)
    
    await self.fetcher.ensure_klines(...)
    klines = self.fetcher.query_cache(...)
    return klines
```

**修改后：**
```python
async def get_klines(self, symbol: str, interval: str, start_date: datetime, end_date: datetime) -> List[Dict]:
    start_time = int(start_date.timestamp() * 1000)
    end_time = int(end_date.timestamp() * 1000)
    
    return await self.fetcher.fetch_and_cache(symbol, interval, start_time, end_time)
```

### 4. market_status_detector.py

#### analyze 方法 (L1543-1563)
**当前代码：**
```python
success = await fetcher.ensure_klines(...)
actual_start, actual_end = fetcher.get_time_range()
klines = fetcher.query_cache(...)
```

**修改后：**
```python
klines = await fetcher.fetch_and_cache(symbol, interval, start_time, end_time)

if not klines:
    raise Exception("K 线数据为空")
```

### 5. test_manager.py

#### get_chart_data 函数 (L1650-1662)
**当前代码：**
```python
async def fetch_klines_async():
    await fetcher.ensure_klines(symbol, interval, start_ts, end_ts, auto_fetch=True)
    return fetcher.query_cache(symbol, interval, start_ts, end_ts)

raw_klines = asyncio.run(fetch_klines_async())
```

**修改后：**
```python
async def fetch_klines_async():
    return await fetcher.fetch_and_cache(symbol, interval, start_ts, end_ts)

raw_klines = asyncio.run(fetch_klines_async())
```

## 实施步骤

1. **修改 binance_kline_fetcher.py**
   - 修改 `fetch_and_cache` 方法签名（移除 days 参数，start_time/end_time 改为必选）
   - 删除 `ensure_klines` 方法
   - 删除 `_calculate_time_range` 方法

2. **修改 binance_backtest.py**
   - 删除 `fetch_klines` 方法
   - 修改 `run` 方法直接调用 `fetch_and_cache`
   - 修改 `fetch_multi_interval_klines` 方法

3. **修改 market_status_visualizer.py**
   - 简化 `get_klines` 方法

4. **修改 market_status_detector.py**
   - 简化 `analyze` 方法中的 K 线获取逻辑

5. **修改 test_manager.py**
   - 简化 `get_chart_data` 中的异步获取逻辑

6. **验证**
   - 重启所有服务
   - 测试 K 线获取功能

## 参数适配说明

| 原方法参数 | fetch_and_cache 参数 | 说明 |
|-----------|---------------------|------|
| symbol | symbol | 直接传递 |
| interval | interval | 直接传递 |
| start_time | start_time | 必选，直接传递 |
| end_time | end_time | 必选，直接传递 |
| days | - | 已移除，调用前需计算时间戳 |
| limit | - | 已移除 |
| auto_fetch | - | 已移除，默认自动获取 |

**注意：** 调用方需要确保 `start_time` 和 `end_time` 已正确计算。

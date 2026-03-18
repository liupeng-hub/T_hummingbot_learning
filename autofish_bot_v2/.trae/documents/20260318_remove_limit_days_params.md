# 移除 binance_backtest.py 中 limit 和 days 参数计划

## 问题分析

当前 `run()` 方法和 `_fetch_multi_interval_klines()` 方法中有 `limit` 和 `days` 参数，但测试中现在使用 `start_time` 和 `end_time` 来指定时间范围，不再需要这两个参数。

## 需要修改的位置

### 1. `run()` 方法签名 (L941-949)
```python
# 当前
async def run(
    self, 
    symbol: str = "BTCUSDT", 
    interval: str = "1m", 
    limit: int = 1000,  # 移除
    days: int = None,   # 移除
    start_time: int = None, 
    end_time: int = None, 
    auto_fetch: bool = True
):

# 修改后
async def run(
    self, 
    symbol: str = "BTCUSDT", 
    interval: str = "1m", 
    start_time: int = None, 
    end_time: int = None
):
```

### 2. `run()` 方法内部使用 (L953, L973-976, L978-979)
- 移除 `self.days = days`
- 移除 `elif days:` 分支
- 修改 `_fetch_multi_interval_klines()` 调用

### 3. `_fetch_multi_interval_klines()` 方法签名 (L701-708)
```python
# 当前
async def _fetch_multi_interval_klines(
    self, 
    symbol: str, 
    interval: str, 
    limit: int = 1000,  # 移除
    days: int = None,   # 移除
    start_time: int = None, 
    end_time: int = None
) -> tuple:

# 修改后
async def _fetch_multi_interval_klines(
    self, 
    symbol: str, 
    interval: str, 
    start_time: int = None, 
    end_time: int = None
) -> tuple:
```

### 4. `_fetch_multi_interval_klines()` 方法内部逻辑
- 移除 `limit` 和 `days` 相关的计算逻辑
- 只保留 `start_time` 和 `end_time` 的逻辑

### 5. main() 函数调用 (L1212-1220)
```python
# 当前
await engine.run(
    symbol=args.symbol, 
    interval="1m", 
    limit=1500,      # 移除
    days=dr['days'], # 移除
    start_time=dr['start_time'], 
    end_time=dr['end_time'],
    auto_fetch=True  # 移除
)

# 修改后
await engine.run(
    symbol=args.symbol, 
    interval="1m", 
    start_time=dr['start_time'], 
    end_time=dr['end_time']
)
```

## 实施步骤

1. 修改 `_fetch_multi_interval_klines()` 方法签名和内部逻辑
2. 修改 `run()` 方法签名和内部逻辑
3. 修改 main() 函数中的调用

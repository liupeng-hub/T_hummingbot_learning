# K 线数据本地缓存方案

## 需求

1. **单独程序**：创建独立的 K 线获取程序
2. **分表存储**：每个标的的每个周期 K 线分别存储到各自的数据表
3. **先获取后回测**：执行回测前，先执行获取 K 线的程序

## 方案设计

### 1. 程序结构

```
autofish_bot_v2/
├── kline_cache/
│   └── klines.db           # SQLite 数据库
├── kline_fetcher.py        # K 线获取程序（新建）
├── binance_backtest.py     # 回测程序（修改）
└── ...
```

### 2. 数据库设计

#### 表命名规则

```
klines_{symbol}_{interval}  # 例如: klines_BTCUSDT_1m, klines_BTCUSDT_1h
```

#### 表结构

```sql
CREATE TABLE IF NOT EXISTS klines_BTCUSDT_1m (
    timestamp INTEGER PRIMARY KEY,  -- 毫秒时间戳
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_time ON klines_BTCUSDT_1m(timestamp);
```

### 3. K 线获取程序 (kline_fetcher.py)

#### 命令行参数

```bash
# 获取单个标的单个周期
python kline_fetcher.py --symbol BTCUSDT --interval 1m

# 获取单个标的多个周期
python kline_fetcher.py --symbol BTCUSDT --interval 1m,5m,1h

# 获取多个标的多个周期
python kline_fetcher.py --symbol BTCUSDT,ETHUSDT --interval 1m,5m,1h

# 按时间范围获取
python kline_fetcher.py --symbol BTCUSDT --interval 1m --date-range "20220616-20230107"

# 按天数获取
python kline_fetcher.py --symbol BTCUSDT --interval 1m --days 365

# 查看缓存状态
python kline_fetcher.py --symbol BTCUSDT --interval 1m --status

# 清空缓存
python kline_fetcher.py --symbol BTCUSDT --interval 1m --clear
```

#### 核心类设计

```python
class KlineFetcher:
    """K 线获取和缓存管理"""
    
    def __init__(self, cache_dir: str = "kline_cache"):
        self.cache_dir = cache_dir
        self.db_path = os.path.join(cache_dir, "klines.db")
        self._init_db()
    
    def _get_table_name(self, symbol: str, interval: str) -> str:
        """获取表名"""
        return f"klines_{symbol}_{interval}"
    
    async def fetch_and_cache(self, symbol: str, interval: str, 
                               start_time: int = None, end_time: int = None,
                               days: int = None):
        """获取 K 线并缓存"""
        # 1. 检查本地缓存
        cached = self._query_cache(symbol, interval, start_time, end_time)
        
        # 2. 找出缺失的时间范围
        missing_ranges = self._find_missing_ranges(symbol, interval, start_time, end_time)
        
        # 3. 从 API 获取缺失数据
        for range_start, range_end in missing_ranges:
            klines = await self._fetch_from_api(symbol, interval, range_start, range_end)
            self._save_to_cache(symbol, interval, klines)
            print(f"[获取] {symbol} {interval}: {len(klines)} 条")
        
        # 4. 返回完整数据
        return self._query_cache(symbol, interval, start_time, end_time)
    
    def get_cache_status(self, symbol: str, interval: str) -> Dict:
        """获取缓存状态"""
        table = self._get_table_name(symbol, interval)
        # SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table}
    
    def clear_cache(self, symbol: str = None, interval: str = None):
        """清空缓存"""
        if symbol and interval:
            table = self._get_table_name(symbol, interval)
            # DROP TABLE {table}
        elif symbol:
            # DROP TABLE klines_{symbol}_*
        else:
            # 清空所有表
```

### 4. 回测程序修改 (binance_backtest.py)

#### 修改 fetch_klines 方法

```python
async def fetch_klines(self, symbol: str, interval: str = "1m", 
                       start_time: int = None, end_time: int = None) -> List[dict]:
    """从本地缓存获取 K 线数据"""
    from kline_fetcher import KlineFetcher
    
    fetcher = KlineFetcher()
    klines = fetcher.query_cache(symbol, interval, start_time, end_time)
    
    if not klines:
        logger.error(f"[获取K线] 本地缓存无数据，请先运行: python kline_fetcher.py --symbol {symbol} --interval {interval}")
        return []
    
    logger.info(f"[获取K线] 从本地缓存获取 {len(klines)} 条数据")
    return klines
```

### 5. 使用流程

#### 步骤 1：获取 K 线数据

```bash
# 获取 BTCUSDT 的 1m K 线（最近 365 天）
python kline_fetcher.py --symbol BTCUSDT --interval 1m --days 365

# 获取多个时间范围
python kline_fetcher.py --symbol BTCUSDT --interval 1m --date-range "20220616-20230107,20230108-20230310"
```

#### 步骤 2：执行回测

```bash
# 回测会直接使用本地缓存
python binance_backtest.py --symbol BTCUSDT --date-range "20220616-20230107"
```

### 6. 数据量估算

| 标的 | 周期 | 1 年数据量 | 3 年数据量 |
|------|------|------------|------------|
| BTCUSDT | 1m | ~52 MB | ~157 MB |
| BTCUSDT | 5m | ~10 MB | ~31 MB |
| BTCUSDT | 1h | ~0.9 MB | ~2.6 MB |
| BTCUSDT | 1d | ~36 KB | ~108 KB |

### 7. 实施步骤

1. **创建 kline_fetcher.py**
   - 实现 `KlineFetcher` 类
   - 实现 SQLite 数据库操作
   - 实现命令行参数解析
   - 实现增量更新逻辑

2. **修改 binance_backtest.py**
   - 修改 `fetch_klines` 方法
   - 从本地缓存读取数据
   - 添加缓存状态检查

3. **测试验证**
   - 测试 K 线获取
   - 测试增量更新
   - 测试回测功能

### 8. 预期效果

| 指标 | 当前 | 优化后 |
|------|------|--------|
| 回测启动时间 | 5-10 分钟 | < 1 秒 |
| API 请求次数 | 每次回测数百次 | 仅获取时调用 |
| 离线可用 | 否 | 是 |
| 多次回测 | 每次都获取 | 复用缓存 |
| API 限制问题 | 经常遇到 | 分离解决 |

### 9. 优势

| 优势 | 说明 |
|------|------|
| **职责分离** | 获取和回测分离，互不影响 |
| **灵活存储** | 每个周期单独存储，按需获取 |
| **避免限制** | 获取程序可以控制请求频率 |
| **增量更新** | 只获取缺失的数据 |
| **离线回测** | 无网络也可回测 |

### 10. 结论

**方案可行**，建议实施。

主要改进：
- 单独程序获取 K 线，避免 API 限制影响回测
- 每个周期单独存储，灵活高效
- 增量更新，减少重复获取

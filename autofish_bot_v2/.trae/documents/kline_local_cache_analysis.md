# K 线数据本地缓存方案分析

## 需求

将标的的 1m K 线数据本地缓存，内部保持时间顺序，查询时利用本地数据，避免频繁调用 Binance API。

## 可行性分析

### 1. 数据量估算

| 时间范围 | K 线数量 | 存储大小（估算） |
|----------|----------|------------------|
| 1 天 | 1,440 条 | ~144 KB |
| 1 月 | 43,200 条 | ~4.3 MB |
| 1 年 | 525,600 条 | ~52 MB |
| 3 年 | 1,576,800 条 | ~157 MB |

**结论**：数据量可控，单标的 3 年数据约 157 MB。

### 2. 存储方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **SQLite** | 查询快、支持索引、单文件 | 需要数据库操作 | ⭐⭐⭐⭐⭐ |
| **CSV** | 简单、可读 | 查询慢、无索引 | ⭐⭐ |
| **Parquet** | 压缩率高、列式存储 | 需要 pandas 依赖 | ⭐⭐⭐⭐ |
| **JSON** | 简单、可读 | 文件大、查询慢 | ⭐⭐ |

**推荐方案**：SQLite + 可选 Parquet 备份

### 3. 数据结构设计

```sql
CREATE TABLE klines_1m (
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,  -- 毫秒时间戳
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, timestamp)
);

CREATE INDEX idx_klines_time ON klines_1m(symbol, timestamp);
```

### 4. 查询效率

| 查询类型 | 时间复杂度 | 预期耗时 |
|----------|------------|----------|
| 按时间范围查询 | O(log n) | < 10ms |
| 按日期查询 | O(log n) | < 5ms |
| 全量扫描 | O(n) | ~100ms/年 |

### 5. 数据更新策略

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| **增量更新** | 只获取缺失的时间段 | 日常更新 |
| **全量更新** | 重新获取所有数据 | 首次运行、数据修复 |
| **定时更新** | 每天自动更新最新数据 | 实盘运行 |

### 6. 实现方案

#### 6.1 数据管理类

```python
class KlineCache:
    def __init__(self, cache_dir: str = "kline_cache"):
        self.cache_dir = cache_dir
        self.db_path = os.path.join(cache_dir, "klines.db")
        
    async def get_klines(self, symbol: str, start_time: int, end_time: int) -> List[Dict]:
        """获取 K 线数据（优先从缓存获取）"""
        # 1. 查询本地缓存
        cached = self._query_cache(symbol, start_time, end_time)
        
        # 2. 检查是否有缺失
        missing_ranges = self._find_missing_ranges(cached, start_time, end_time)
        
        # 3. 如果有缺失，从 API 获取并缓存
        if missing_ranges:
            for range_start, range_end in missing_ranges:
                klines = await self._fetch_from_api(symbol, range_start, range_end)
                self._save_to_cache(symbol, klines)
            cached = self._query_cache(symbol, start_time, end_time)
        
        return cached
```

#### 6.2 文件结构

```
autofish_bot_v2/
├── kline_cache/
│   ├── klines.db           # SQLite 数据库
│   ├── BTCUSDT.parquet     # 可选：Parquet 备份
│   └── ETHUSDT.parquet
└── binance_backtest.py
```

### 7. 优缺点分析

#### 优点

| 优点 | 说明 |
|------|------|
| **避免 API 限制** | 不受 2400 次/分钟限制 |
| **提高回测速度** | 本地查询 < 10ms |
| **离线可用** | 无网络也可回测 |
| **数据复用** | 多次回测无需重复获取 |
| **支持增量更新** | 只获取新数据 |

#### 缺点

| 缺点 | 说明 |
|------|------|
| **存储空间** | 单标的 3 年约 157 MB |
| **初次获取** | 首次需要获取历史数据 |
| **数据维护** | 需要定期更新 |
| **数据一致性** | 需要处理数据修复 |

### 8. 实施步骤

1. **创建缓存模块**
   - 实现 `KlineCache` 类
   - 创建 SQLite 数据库
   - 实现查询和存储方法

2. **修改回测代码**
   - 修改 `fetch_klines` 方法
   - 优先从缓存获取
   - 缺失时从 API 获取

3. **添加缓存管理命令**
   - `--cache-update`: 更新缓存
   - `--cache-clear`: 清空缓存
   - `--cache-status`: 查看缓存状态

4. **测试验证**
   - 测试缓存查询
   - 测试增量更新
   - 测试回测功能

### 9. 预期效果

| 指标 | 当前 | 优化后 |
|------|------|--------|
| 回测启动时间 | 5-10 分钟 | < 1 秒 |
| API 请求次数 | 每次回测数百次 | 仅增量更新 |
| 离线可用 | 否 | 是 |
| 多次回测 | 每次都获取 | 复用缓存 |

### 10. 结论

**方案可行**，建议实施。

主要收益：
- 解决 API 频率限制问题
- 大幅提高回测效率
- 支持离线回测
- 支持增量更新

建议优先级：**高**

# 回测自动补充缺失 K 线数据设计规格

## 1. 需求背景

当前回测流程：
1. 用户运行 `binance_kline_fetcher.py` 获取 K 线数据
2. 用户运行 `binance_backtest.py` 进行回测
3. 如果缓存数据不完整，回测失败

**问题**：
- 缓存数据可能缺少最近几天的最新数据
- 用户需要手动运行获取程序
- 数据不完整时回测无法进行

## 2. 目标

回测时自动检测并补充缺失数据，支持所有参数场景：
1. `--limit` 参数：获取最近 N 条数据
2. `--days` 参数：获取最近 N 天数据
3. `--date-range` 参数：获取指定时间范围数据
4. 自动调用 `binance_kline_fetcher` 补充缺失数据
5. 从缓存读取完整数据
6. 开始回测

## 3. 设计方案

### 3.1 参数场景分析

| 参数 | 时间范围计算 | 缺失检测 |
|------|-------------|----------|
| `--limit 1500` | 最新 1500 条数据（从当前时间往前） | 检查缓存是否覆盖最近 1500 条 |
| `--days 20` | 最近 20 天（从当前时间往前） | 检查缓存是否覆盖最近 20 天 |
| `--date-range "20240101-20240601"` | 2024-01-01 到 2024-06-01 | 检查缓存是否覆盖该范围 |

### 3.2 时间范围计算

```python
def calculate_time_range(args: argparse.Namespace) -> Tuple[int, int]:
    """根据参数计算时间范围
    
    返回: (start_time, end_time) 毫秒时间戳
    """
    end_time = int(datetime.now().timestamp() * 1000)
    
    if args.date_range:
        # 场景 1: 指定时间范围
        start_date, end_date = parse_date_range(args.date_range)
        start_time = int(start_date.timestamp() * 1000)
        end_time = int(end_date.timestamp() * 1000) + 86400000 - 1
        
    elif args.days:
        # 场景 2: 最近 N 天
        start_time = end_time - args.days * 24 * 60 * 60 * 1000
        
    else:
        # 场景 3: 最近 N 条数据（默认 1500）
        # 根据周期计算时间范围
        interval_minutes = get_interval_minutes(args.interval)
        start_time = end_time - args.limit * interval_minutes * 60 * 1000
    
    return start_time, end_time
```


# 回测 K 线周期问题分析与改进方案

## 问题描述

### 当前回测逻辑

在 `binance_backtest.py` 的 `_process_exit()` 方法中：

```python
def _process_exit(self, high_price: Decimal, low_price: Decimal, current_price: Decimal):
    for order in filled_orders:
        # 先判断止盈
        if check_take_profit_triggered(high_price, order.take_profit_price):
            self._close_order(order, "take_profit", ...)
            break
        
        # 再判断止损
        elif check_stop_loss_triggered(low_price, order.stop_loss_price):
            self._close_order(order, "stop_loss", ...)
            break
```

### 问题分析

**场景示例**：

假设一个 1 小时 K 线：
- Open: 67000
- High: 67500（触及止盈 67200）
- Low: 66000（触及止损 66100）
- Close: 66500

**当前逻辑**：先判断止盈，触发止盈，盈利。

**实际情况**：
1. 价格可能先跌到 66000（触发止损），再涨到 67500
2. 价格可能先涨到 67500（触发止盈），再跌到 66000
3. 价格可能在中间多次波动

**结果偏差**：
- 回测结果与实际交易结果可能完全不同
- 盈亏统计不准确
- 链式订单触发顺序错误

## 问题根源

### 1. K 线数据局限性

K 线只提供 OHLC 四个价格点，无法知道：
- 价格在 K 线内的具体走势
- High 和 Low 谁先到达
- 价格在 K 线内的波动次数

### 2. 算法特性

Autofish 是**振幅触发**算法，不是**周期触发**算法：
- 订单触发取决于价格是否触及目标价位
- 与时间周期无关
- 需要精确的价格序列

### 3. 链式订单复杂性

一个 K 线内可能发生：
- A1 止盈 → 下新 A1
- 新 A1 入场 → 下 A2
- A2 入场 → 下 A3
- A3 止损 → 清空所有订单

当前回测逻辑无法模拟这种复杂场景。

## 解决方案

### 方案一：使用更小周期 K 线

**原理**：减小 K 线周期，降低单根 K 线内同时触及止盈止损的概率。

**优点**：
- 实现简单
- 数据获取方便

**缺点**：
- 仍然存在偏差（只是减小）
- 数据量增大，回测速度变慢
- Binance API 限制单次最多 1500 条数据

**建议**：
- 使用 1m 或 3m 周期
- 避免使用 1h 或更大的周期

### 方案二：K 线内价格模拟

**原理**：根据 K 线特征，模拟价格在 K 线内的走势。

**实现方式**：

1. **基于波动率的模拟**：
   - 根据 Open、High、Low、Close 的关系
   - 判断价格先涨还是先跌
   - 模拟价格序列

2. **保守估计**：
   - 如果同时触及止盈止损，假设止损先触发（保守）
   - 或者假设止盈先触发（乐观）
   - 提供上下界估计

3. **随机模拟**：
   - 使用蒙特卡洛方法
   - 多次模拟取平均

**优点**：
- 更接近实际情况
- 可以处理复杂场景

**缺点**：
- 实现复杂
- 仍然存在假设偏差

### 方案三：使用 Tick 数据（Binance 支持）

**原理**：使用逐笔成交数据，而不是 K 线数据。

**Binance API 支持**：
- `/api/v3/trades`：最近成交记录
- `/api/v3/historicalTrades`：历史成交记录（需要 API Key）
- `/api/v3/aggTrades`：归集成交记录

**API 限制**：
- 每次请求最多 1000 条交易
- 使用时间参数时，间隔最多 1 小时

**优点**：
- 最精确的回测
- 完全模拟实际交易
- 可以准确判断止盈止损触发顺序

**缺点**：
- 数据量大（一天可能有数百万条）
- 回测速度慢
- 需要分批获取，处理复杂

**实现建议**：
```python
async def fetch_tick_data(self, symbol: str, start_time: int, end_time: int) -> List[dict]:
    """获取逐笔成交数据"""
    url = "https://fapi.binance.com/fapi/v1/aggTrades"
    all_trades = []
    from_id = None
    
    while True:
        params = {"symbol": symbol, "limit": 1000}
        if from_id:
            params["fromId"] = from_id
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                trades = await resp.json()
        
        if not trades:
            break
        
        # 过滤时间范围
        filtered = [t for t in trades if start_time <= t["T"] <= end_time]
        all_trades.extend(filtered)
        
        if len(trades) < 1000:
            break
        
        from_id = trades[-1]["a"] + 1
    
    return all_trades
```

### 方案四：混合方案（推荐）

**原理**：结合多种方法，提供置信区间。

**实现步骤**：

1. **使用 1m K 线作为基础数据**

2. **K 线内判断逻辑**：
   ```python
   def _process_exit_in_kline(self, order, open_price, high_price, low_price, close_price):
       tp_triggered = high_price >= order.take_profit_price
       sl_triggered = low_price <= order.stop_loss_price
       
       if tp_triggered and sl_triggered:
           # 同时触及止盈止损，需要判断谁先到达
           # 方法1: 根据 K 线形态判断
           if close_price > open_price:
               # 阳线，假设先跌后涨，止损先触发
               return "stop_loss"
           else:
               # 阴线，假设先涨后跌，止盈先触发
               return "take_profit"
           
           # 方法2: 保守估计（止损先触发）
           # return "stop_loss"
           
           # 方法3: 提供上下界
           # return "both"  # 需要特殊处理
       elif tp_triggered:
           return "take_profit"
       elif sl_triggered:
           return "stop_loss"
       else:
           return None
   ```

3. **提供置信区间**：
   - 乐观估计：假设止盈先触发
   - 保守估计：假设止损先触发
   - 中性估计：根据 K 线形态判断

4. **统计报告**：
   - 显示乐观/保守/中性三种结果
   - 提供盈亏区间

## 实施计划

### 阶段一：短期改进

1. **修改回测参数默认值**：
   - 将默认 K 线周期改为 1m
   - 增加周期选择提示

2. **添加 K 线内判断逻辑**：
   - 实现同时触及止盈止损的处理
   - 根据 K 线形态判断触发顺序

3. **添加警告日志**：
   - 当检测到同时触及止盈止损时，记录警告

### 阶段二：中期改进

1. **实现置信区间**：
   - 乐观/保守/中性三种估计
   - 报告中显示盈亏区间

2. **优化回测报告**：
   - 显示同时触及次数
   - 显示不同估计的差异

### 阶段三：长期改进

1. **研究 Tick 数据获取方案**：
   - 实时收集 Tick 数据
   - 建立本地 Tick 数据库

2. **实现 Tick 级别回测**：
   - 支持多种数据源
   - 高性能回测引擎

## 代码修改建议

### 修改 `_process_exit` 方法

```python
def _process_exit(self, open_price: Decimal, high_price: Decimal, low_price: Decimal, close_price: Decimal):
    """处理出场，考虑 K 线内价格走势"""
    filled_orders = self.chain_state.get_filled_orders()
    
    for order in filled_orders:
        if order.state != "filled":
            continue
        
        tp_triggered = high_price >= order.take_profit_price
        sl_triggered = low_price <= order.stop_loss_price
        
        if tp_triggered and sl_triggered:
            # 同时触及止盈止损，需要判断谁先到达
            result = self._determine_exit_order(order, open_price, high_price, low_price, close_price)
            if result == "take_profit":
                self._close_order(order, "take_profit", order.take_profit_price, self.leverage)
            else:
                self._close_order(order, "stop_loss", order.stop_loss_price, self.leverage)
            
            self._handle_post_exit(order, close_price)
            self.stats["simultaneous_triggers"] += 1
            break
            
        elif tp_triggered:
            self._close_order(order, "take_profit", order.take_profit_price, self.leverage)
            self._handle_post_exit(order, close_price)
            break
            
        elif sl_triggered:
            self._close_order(order, "stop_loss", order.stop_loss_price, self.leverage)
            self._handle_post_exit(order, close_price)
            break

def _determine_exit_order(self, order, open_price, high_price, low_price, close_price):
    """判断止盈止损触发顺序
    
    根据 K 线形态判断：
    - 阳线（close > open）：假设先跌后涨，止损先触发
    - 阴线（close < open）：假设先涨后跌，止盈先触发
    - 十字星（close ≈ open）：假设止损先触发（保守）
    """
    if close_price > open_price:
        # 阳线，假设先跌后涨
        return "stop_loss"
    elif close_price < open_price:
        # 阴线，假设先涨后跌
        return "take_profit"
    else:
        # 十字星，保守估计
        return "stop_loss"
```

## 结论

您的分析是正确的：

1. **Autofish 是振幅触发算法**，不是周期触发算法
2. **大周期 K 线确实存在回测偏差**
3. **使用最小周期是有效的改进方法**

**重要发现**：Binance **支持** Tick 级别历史数据！

建议：
- **短期**：使用 1m K 线 + K 线内判断逻辑
- **中期**：提供置信区间估计
- **长期**：使用 Binance aggTrades API 获取 Tick 数据，实现精确回测

### Binance Tick 数据接口

| 接口 | 说明 | 限制 |
|------|------|------|
| `/api/v3/trades` | 最近成交 | 最多 1000 条 |
| `/api/v3/historicalTrades` | 历史成交 | 需要 API Key |
| `/api/v3/aggTrades` | 归集成交 | 时间间隔最多 1 小时 |

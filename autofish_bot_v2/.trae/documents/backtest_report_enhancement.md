# 回测报告增强计划

## 需求

1. **同期标的涨跌百分比** - 作为收益率的对比基准
2. **盈亏比** - 平均盈利 / 平均亏损
3. **夏普比率** - 风险调整后收益
4. **历史记录文件** - 追加记录每次回测数据，方便对比

## 实现方案

### 1. 同期标的涨跌百分比

**计算方法**：
```
标的涨跌幅 = (结束价格 - 开始价格) / 开始价格 × 100%
```

### 2. 盈亏比

**计算方法**：
```
平均盈利 = 总盈利 / 盈利次数
平均亏损 = 总亏损 / 亏损次数
盈亏比 = 平均盈利 / 平均亏损
```

### 3. 夏普比率

**计算方法**：
```
夏普比率 = 平均收益率 / 收益率标准差
```

### 4. 历史记录文件

**文件名格式**：
- `binance_{symbol}_backtest_history.md`

**文件内容**：
- 每次回测追加一行记录
- 包含关键指标：日期范围、交易次数、胜率、收益率、标的涨跌、盈亏比、夏普比率

**示例**：
```markdown
# BTCUSDT 回测历史记录

| 回测时间 | 日期范围 | 天数 | 交易次数 | 胜率 | 收益率 | 标的涨跌 | 超额收益 | 盈亏比 | 夏普比率 |
|----------|----------|------|----------|------|--------|----------|----------|--------|----------|
| 2026-03-09 23:30 | 2026-02-27 ~ 2026-03-09 | 10 | 8 | 100% | 13.13% | -2.50% | 15.63% | N/A | 2.35 |
| 2026-03-09 23:35 | 2026-02-20 ~ 2026-03-09 | 17 | 15 | 80% | 18.50% | 5.20% | 13.30% | 3.20 | 1.85 |
```

## 修改文件

### binance_backtest.py

#### 1. 添加新字段到 results

```python
self.results = {
    ...
    "first_price": None,      # 第一根 K 线价格
    "last_price": None,       # 最后一根 K 线价格
    "trade_returns": [],      # 每笔交易的收益率列表
    "max_profit": Decimal("0"),   # 最大单笔盈利
    "max_loss": Decimal("0"),     # 最大单笔亏损
}
```

#### 2. 修改 run() 方法

```python
# 记录首尾价格
self.results["first_price"] = Decimal(klines[0]["open"])
self.results["last_price"] = Decimal(klines[-1]["close"])
```

#### 3. 修改 _close_order() 方法

```python
# 计算并记录收益率
trade_return = profit / order.stake_amount
self.results["trade_returns"].append(trade_return)

# 更新最大盈亏
if profit > self.results["max_profit"]:
    self.results["max_profit"] = profit
if profit < self.results["max_loss"]:
    self.results["max_loss"] = profit
```

#### 4. 修改 save_report() 方法

新增计算函数：
```python
def calculate_metrics(self):
    """计算回测指标"""
    # 标的涨跌幅
    if self.results["first_price"] and self.results["last_price"]:
        price_change = (self.results["last_price"] - self.results["first_price"]) / self.results["first_price"] * 100
    else:
        price_change = Decimal("0")
    
    # 盈亏比
    if self.results["loss_trades"] > 0:
        avg_profit = self.results["total_profit"] / self.results["win_trades"]
        avg_loss = self.results["total_loss"] / self.results["loss_trades"]
        profit_loss_ratio = avg_profit / avg_loss
    else:
        profit_loss_ratio = None  # 无亏损
    
    # 夏普比率
    if len(self.results["trade_returns"]) >= 2:
        returns = self.results["trade_returns"]
        avg_return = sum(returns) / len(returns)
        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
        std_dev = variance ** 0.5
        sharpe_ratio = avg_return / std_dev if std_dev > 0 else 0
    else:
        sharpe_ratio = 0
    
    return {
        "price_change": price_change,
        "profit_loss_ratio": profit_loss_ratio,
        "sharpe_ratio": sharpe_ratio,
    }
```

#### 5. 新增 save_history() 方法

```python
def save_history(self, symbol: str, days: int = None):
    """保存回测历史记录"""
    import os
    
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autofish_output")
    os.makedirs(output_dir, exist_ok=True)
    
    filepath = os.path.join(output_dir, f"binance_{symbol}_backtest_history.md")
    
    # 计算指标
    metrics = self.calculate_metrics()
    net_profit = self.results["total_profit"] - self.results["total_loss"]
    roi = float(net_profit) / float(self.config.get('total_amount_quote', 1200)) * 100
    win_rate = (self.results["win_trades"] / self.results["total_trades"] * 100 
               if self.results["total_trades"] > 0 else 0)
    
    # 超额收益
    excess_return = roi - float(metrics["price_change"])
    
    # 盈亏比显示
    plr = f"{metrics['profit_loss_ratio']:.2f}" if metrics['profit_loss_ratio'] else "N/A"
    
    # 检查文件是否存在
    if not os.path.exists(filepath):
        # 创建新文件，写入表头
        header = [
            "# BTCUSDT 回测历史记录",
            "",
            "| 回测时间 | 日期范围 | 天数 | 交易次数 | 胜率 | 收益率 | 标的涨跌 | 超额收益 | 盈亏比 | 夏普比率 |",
            "|----------|----------|------|----------|------|--------|----------|----------|--------|----------|",
        ]
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(header) + '\n')
    
    # 追加数据行
    date_range = f"{self.start_time.strftime('%Y-%m-%d')} ~ {self.end_time.strftime('%Y-%m-%d')}" if self.start_time and self.end_time else "-"
    days_str = str(days) if days else "-"
    
    row = (
        f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | {date_range} | {days_str} | "
        f"{self.results['total_trades']} | {win_rate:.1f}% | {roi:.2f}% | "
        f"{float(metrics['price_change']):.2f}% | {excess_return:.2f}% | {plr} | "
        f"{metrics['sharpe_ratio']:.2f} |"
    )
    
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(row + '\n')
    
    print(f"📊 历史记录已追加: {filepath}")
```

## 实施步骤

1. 修改 `__init__()` 方法，添加新字段
2. 修改 `run()` 方法，记录首尾价格
3. 修改 `_close_order()` 方法，记录交易收益率和最大盈亏
4. 添加 `calculate_metrics()` 方法
5. 修改 `save_report()` 方法，增加新指标显示
6. 添加 `save_history()` 方法
7. 修改 `main()` 方法，调用 `save_history()`
8. 运行测试验证

## 预期输出

### 单次报告 (binance_BTCUSDT_backtest_report_10d.md)

```markdown
## 对比分析

| 指标 | 值 | 说明 |
|------|-----|------|
| 标的涨跌幅 | -2.50% | 同期 BTCUSDT 涨跌 |
| 策略收益率 | 13.13% | 策略净收益率 |
| 超额收益 | 15.63% | 策略收益 - 标的涨跌 |

## 风险指标

| 指标 | 值 | 说明 |
|------|-----|------|
| 盈亏比 | N/A | 无亏损交易 |
| 夏普比率 | 2.35 | 风险调整后收益 |
| 最大单笔盈利 | 189.44 USDT | - |
| 最大单笔亏损 | 0.00 USDT | - |
```

### 历史记录 (binance_BTCUSDT_backtest_history.md)

```markdown
# BTCUSDT 回测历史记录

| 回测时间 | 日期范围 | 天数 | 交易次数 | 胜率 | 收益率 | 标的涨跌 | 超额收益 | 盈亏比 | 夏普比率 |
|----------|----------|------|----------|------|--------|----------|----------|--------|----------|
| 2026-03-09 23:30 | 2026-02-27 ~ 2026-03-09 | 10 | 8 | 100.0% | 13.13% | -2.50% | 15.63% | N/A | 2.35 |
```

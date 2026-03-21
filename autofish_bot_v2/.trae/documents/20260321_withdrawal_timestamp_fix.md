# 提现记录分析报告

## 问题分析

### 1. 提现记录时间戳问题
- **交易记录时间**：K 线时间（如 `2021-01-26T09:37:00`）
- **提现记录时间**：系统运行时间（如 `2026-03-21T23:27:56`）

**原因**：`check_withdrawal` 方法中使用 `datetime.now()` 而不是 K 线时间。

### 2. 提现次数多的原因
从数据可以看到：
- `withdrawal_threshold = 1.5` → 触发阈值：10000 × 1.5 = 15000
- `withdrawal_retain = 1.2` → 保留金额：10000 × 1.2 = 12000

**逻辑**：每次交易盈利后，如果 `trading_capital >= 15000`，就触发提现，保留 12000。

**示例**：
```
2021-01-26T09:37:00 | 14936.71 → 15036.13 | +99.41 | 交易
2026-03-21T23:27:56 | 15036.13 → 12000.00 | -3036.13 | 提现  ← 时间戳错误
```

这是**正常行为**，符合资金管理策略。每次盈利后资金超过阈值就提现。

### 3. 核心问题
提现记录的时间戳使用系统运行时间，导致：
1. 图表上提现记录与交易记录时间不连续
2. 无法在正确的 K 线时间点显示提现事件

## 修复方案

### 修改文件：`autofish_core.py`

1. **修改 `process_trade_profit` 方法**
   - 传递 K 线时间给 `check_withdrawal`
   - 提现记录使用 K 线时间

2. **修改 `check_withdrawal` 方法**
   - 接收 K 线时间参数
   - 使用 K 线时间记录提现历史

### 具体修改

```python
# autofish_core.py

def process_trade_profit(self, profit: Decimal, kline_time: datetime = None) -> Dict:
    result = self.update_capital(profit, kline_time)
    
    self.round_profits.append(profit)
    self.total_round_profit += profit
    
    # 传递 kline_time 给 check_withdrawal
    withdrawal = self.check_withdrawal(kline_time)
    if withdrawal:
        result['withdrawal'] = withdrawal
    
    if self.check_liquidation():
        result['liquidation_triggered'] = True
        self.recover_from_liquidation()
    
    return result

def check_withdrawal(self, kline_time: datetime = None) -> Optional[Dict]:
    threshold_amount = self.initial_capital * self.withdrawal_threshold
    
    if self.trading_capital >= threshold_amount:
        retain_amount = self.initial_capital * self.withdrawal_retain
        withdrawal_amount = self.trading_capital - retain_amount
        
        if withdrawal_amount > 0:
            self.profit_pool += withdrawal_amount
            self.trading_capital = retain_amount
            self.withdrawal_count += 1
            
            # 使用 K 线时间记录提现历史
            self.capital_history.append({
                'timestamp': (kline_time or datetime.now()).isoformat(),
                'old_capital': float(retain_amount + withdrawal_amount),
                'new_capital': float(self.trading_capital),
                'profit': -float(withdrawal_amount),
                'total_capital': float(self.trading_capital + self.profit_pool),
                'event_type': 'withdrawal',
            })
            
            return {
                'withdrawal_amount': withdrawal_amount,
                'profit_pool': self.profit_pool,
                'trading_capital': self.trading_capital,
                'withdrawal_count': self.withdrawal_count,
            }
    
    return None
```

## 结论

1. **提现次数多是正常的**：这是资金管理策略的设计，每次盈利后资金超过阈值就提现
2. **需要修复的是时间戳**：提现记录应使用 K 线时间，而不是系统运行时间

# Binance 最小金额要求预检查计划

## 问题分析

### 当前问题

Binance 要求订单金额 >= min_notional（通常为 100 USDT），但 Autofish 策略会将总资金按权重分配到不同层级，可能导致某些层级金额不足。

### 示例

假设：
- 总资金 = 1200 USDT
- 最大层级 = 4
- 权重分配：36%、32%、21%、9%（d=0.5）

各层级金额：
- A1: 1200 × 36% = 432 USDT ✅
- A2: 1200 × 32% = 384 USDT ✅
- A3: 1200 × 21% = 252 USDT ✅
- A4: 1200 × 9% = 108 USDT ✅

但如果总资金 = 500 USDT：
- A1: 500 × 36% = 180 USDT ✅
- A2: 500 × 32% = 160 USDT ✅
- A3: 500 × 21% = 105 USDT ✅
- A4: 500 × 9% = 45 USDT ❌ < 100 USDT

## 解决方案

### 方案：启动前预检查

在程序启动时，检查配置是否满足最小金额要求，并给出建议。

### 检查逻辑

```
1. 获取 min_notional（从 Binance API）
2. 计算各层级权重
3. 计算各层级金额 = 总资金 × 权重
4. 检查每个层级金额是否 >= min_notional
5. 如果不满足，给出建议：
   - 建议最小总资金
   - 或建议减少最大层级
```

### 最小总资金计算

```
最小总资金 = min_notional / 最小权重

其中最小权重 = min(各层级权重)

例如：
- min_notional = 100 USDT
- 最小权重 = 9%（A4）
- 最小总资金 = 100 / 0.09 = 1111 USDT
```

## 实施步骤

### 步骤 1: 添加预检查方法

在 `BinanceLiveTrader` 类中添加 `_check_min_notional()` 方法：

```python
def _check_min_notional(self) -> Tuple[bool, Dict]:
    """检查配置是否满足最小金额要求
    
    返回:
        (是否满足, 检查结果详情)
    """
    min_notional = getattr(self, 'min_notional', Decimal("100"))
    total_amount = Decimal(str(self.config.get('total_amount', 1200)))
    max_entries = self.config.get('max_entries', 4)
    
    # 获取权重
    weights = self.calculator.calculate_weights(...)
    
    # 检查每个层级
    results = []
    all_satisfied = True
    
    for level in range(1, max_entries + 1):
        weight = weights.get(level, Decimal("0"))
        stake = total_amount * weight
        
        satisfied = stake >= min_notional
        if not satisfied:
            all_satisfied = False
        
        results.append({
            'level': level,
            'weight': float(weight),
            'stake': float(stake),
            'satisfied': satisfied
        })
    
    # 计算建议最小总资金
    min_weight = min(r['weight'] for r in results)
    suggested_min_amount = min_notional / Decimal(str(min_weight))
    
    return all_satisfied, {
        'results': results,
        'min_notional': float(min_notional),
        'total_amount': float(total_amount),
        'suggested_min_amount': float(suggested_min_amount)
    }
```

### 步骤 2: 在 run() 方法中调用预检查

```python
async def run(self) -> None:
    # 初始化精度（获取 min_notional）
    await self._init_precision()
    
    # 预检查
    satisfied, check_result = self._check_min_notional()
    
    if not satisfied:
        logger.warning(f"[预检查] 配置不满足最小金额要求")
        print(f"\n{'='*60}")
        print(f"⚠️ 配置预检查警告")
        print(f"{'='*60}")
        print(f"  最小金额要求: {check_result['min_notional']} USDT")
        print(f"  当前总资金: {check_result['total_amount']} USDT")
        print(f"  建议最小总资金: {check_result['suggested_min_amount']:.2f} USDT")
        print(f"\n  各层级检查:")
        for r in check_result['results']:
            status = "✅" if r['satisfied'] else "❌"
            print(f"    A{r['level']}: {r['stake']:.2f} USDT ({r['weight']*100:.1f}%) {status}")
        print(f"{'='*60}\n")
        
        # 可以选择退出或继续
        # return  # 退出
        # 或者继续运行，但调整数量
    
    # 继续正常流程
    ...
```

### 步骤 3: 更新振幅分析器

在 `Autofish_AmplitudeAnalyzer` 中添加最小资金计算：

```python
def calculate_min_required_amount(self, min_notional: Decimal = Decimal("100")) -> Decimal:
    """计算满足最小金额要求的最小总资金
    
    参数:
        min_notional: 最小订单金额要求
    
    返回:
        最小总资金
    """
    # 获取最小权重
    min_weight = min(self.weights.values())
    
    # 计算最小总资金
    min_amount = min_notional / min_weight
    
    return min_amount
```

## 输出示例

```
============================================================
⚠️ 配置预检查警告
============================================================
  最小金额要求: 100 USDT
  当前总资金: 500 USDT
  建议最小总资金: 1111.11 USDT

  各层级检查:
    A1: 180.00 USDT (36.0%) ✅
    A2: 160.00 USDT (32.0%) ✅
    A3: 105.00 USDT (21.0%) ✅
    A4: 45.00 USDT (9.0%) ❌
============================================================
```

## 预期成果

1. 程序启动时自动检查配置是否满足要求
2. 不满足时给出明确警告和建议
3. 避免运行时因金额不足导致下单失败
4. 提高用户体验和系统可靠性

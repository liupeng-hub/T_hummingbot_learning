# Web 触发用例执行 - Decimal 类型转换分析

## 数据流程分析

### 1. Web 触发 (`test_manager.py:run_case`)
```python
# 第 1545-1548 行
amplitude = json.loads(case['amplitude'] or '{}')
market = json.loads(case['market'] or '{}')
entry = json.loads(case['entry'] or '{}')
timeout = json.loads(case['timeout'] or '{}')

# 通过命令行参数传递
cmd = [
    'python3', 'market_aware_backtest.py',
    '--amplitude-params', json.dumps(amplitude),
    ...
]
```

### 2. 回测执行 (`market_aware_backtest.py`)
```python
# 第 609-612 行
amplitude = json.loads(args.amplitude_params) if args.amplitude_params else {}

# 第 658-665 行 - ensure_decimal 函数定义
def ensure_decimal(value, default="0"):
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

# 第 680-685 行 - else 分支中的转换
amplitude["grid_spacing"] = ensure_decimal(amplitude.get("grid_spacing"), "0.01")
amplitude["exit_profit"] = ensure_decimal(amplitude.get("exit_profit"), "0.01")
amplitude["stop_loss"] = ensure_decimal(amplitude.get("stop_loss"), "0.08")
amplitude["total_amount_quote"] = ensure_decimal(amplitude.get("total_amount_quote"), "10000")
amplitude["decay_factor"] = ensure_decimal(amplitude.get("decay_factor"), "0.5")
```

### 3. MarketAwareBacktestEngine.__init__
```python
# 第 128 行
config = amplitude.copy()  # 直接复制，不转换
```

### 4. BacktestEngine.__init__
```python
# 第 96 行
self.calculator = Autofish_WeightCalculator(Decimal(str(self.config.get("decay_factor", 0.5))))
```

### 5. BacktestEngine._create_order
```python
# 第 143-145 行
grid_spacing = self.config.get("grid_spacing", Decimal("0.01"))
exit_profit = self.config.get("exit_profit", Decimal("0.01"))
stop_loss = self.config.get("stop_loss", Decimal("0.08"))
```

### 6. BacktestEngine._get_weights
```python
# 第 121 行 - weights 数组已在此处转换
weights_list = [Decimal(str(w)) for w in self.config.get("weights", [])]
```

## 问题分析

### 当前代码已正确处理
✅ `market_aware_backtest.py` 的 `else` 分支中已调用 `ensure_decimal()` 转换
✅ `binance_backtest.py` 的 `_get_weights()` 方法已处理 `weights` 数组转换
✅ `valid_amplitudes` 数组元素为 int，用于数组索引，不需要转换

### 需要修复的问题
1. **`decay_factor` 变量重复定义**：第 656 行定义了 `decay_factor` 变量，但第 685 行又在 `amplitude` 字典中设置，逻辑不一致

### 结论
**当前代码已经正确处理了 Decimal 转换**，只需要清理重复的变量定义。

## 实施计划

### 步骤 1：移除重复的 decay_factor 变量定义
删除 `market_aware_backtest.py` 第 656 行的 `decay_factor` 变量定义，统一在 else 分支中处理。

### 步骤 2：验证测试
通过 Web 触发测试用例执行，确认参数类型正确，计算无误。

## 修改内容

### 文件：`market_aware_backtest.py`

**删除第 656 行**：
```python
# 删除这行（重复定义）
decay_factor = Decimal(str(amplitude.get("decay_factor", 0.5))) if amplitude else Decimal("0.5")
```

**保留第 680-685 行**（else 分支中的转换）：
```python
amplitude["grid_spacing"] = ensure_decimal(amplitude.get("grid_spacing"), "0.01")
amplitude["exit_profit"] = ensure_decimal(amplitude.get("exit_profit"), "0.01")
amplitude["stop_loss"] = ensure_decimal(amplitude.get("stop_loss"), "0.08")
amplitude["total_amount_quote"] = ensure_decimal(amplitude.get("total_amount_quote"), "10000")
amplitude["decay_factor"] = ensure_decimal(amplitude.get("decay_factor"), "0.5")
```

### 无需修改
- `test_manager.py`：只负责传递 JSON 字符串
- `binance_backtest.py`：已在配置初始化时处理 Decimal 转换
- `weights` 数组：已在 `_get_weights()` 方法中处理

# Web 页面测试计划表单优化计划

## 问题分析

当前 Web 页面创建测试计划表单存在以下问题：

1. **测试场景已废弃**：HTML 中仍有测试场景相关的代码，2. **振幅参数不完整**：缺少 `weights` 字段
3. **行情算法参数动态显示**：选择不同算法后，页面没有展示对应的参数配置框
4. **入场价格策略缺失**：没有入场价格策略的选择和对应参数设置

## 配置文件参考

### 振幅参数 (amplitude_config.json)
```json
{
  "symbol": "BTCUSDT",
  "total_amount_quote": 5000,
  "leverage": 10,
  "decay_factor": 0.5,
  "max_entries": 4,
  "valid_amplitudes": [1, 2, 3, 4, 5, 6, 7, 8, 9],
  "weights": [0.0831, 0.2996, 0.3167, 0.1365, 0.1005, 0.0281, 0.027, 0.0066, 0.0018],
  "grid_spacing": 0.01,
  "exit_profit": 0.01,
  "stop_loss": 0.08,
  "total_expected_return": 0.2944
}
```

### 行情算法参数 (market_status_detector.py)

| 算法 | 参数 |
|------|------|
| **always_ranging** | 无额外参数 |
| **dual_thrust** | n_days, k1, k2, k2_down_factor, down_confirm_days, cooldown_days |
| **improved** | lookback_period, min_range_duration, max_range_pct, breakout_threshold, breakout_confirm_days, swing_window, merge_threshold, min_touches |
| **composite** | adx_period, adx_threshold, atr_period, atr_multiplier, bb_period, bb_std, bb_width_threshold, ma_period |
| **adx** | period, threshold |
| **realtime** | (实时算法，参数复杂) |

### 入场价格策略参数 (entry_price_strategy)

| 策略 | 参数 |
|------|------|
| **fixed** | 无额外参数（固定网格间距） |
| **atr** | atr_period, atr_multiplier, min_spacing, max_spacing |
| **bollinger** | period, num_std, min_spacing, max_spacing |
| **support** | period, min_touches, price_tolerance |
| **composite** | atr_period, atr_multiplier, bb_period, bb_std |

## 实施步骤

### Step 1: 删除测试场景相关代码

**文件**: `web/test_results/index.html`

1. 删除 HTML 中的测试场景部分（已删除，需确认）
2. 删除 JavaScript 中的 `addScenario` 函数
3. 删除 `savePlan` 函数中的场景处理逻辑
4. 删除 `showCreatePlanForm` 和 `showEditPlanForm` 中的场景相关代码

### Step 2: 完善振幅参数表单

**文件**: `web/test_results/index.html`

添加缺失字段：
- `weights`: 权重数组（与 valid_amplitudes 对应，逗号分隔输入）

### Step 3: 实现行情算法参数动态显示

**文件**: `web/test_results/index.html`

根据选择的算法动态显示参数：

```javascript
// 緻加算法选择框的 onchange 事件
function onMarketAlgorithmChange() {
    const algorithm = document.getElementById('formMarketAlgorithm').value;
    
    // 隐藏所有算法参数容器
    document.getElementById('dualThrustParams').style.display = 'none';
    document.getElementById('improvedParams').style.display = 'none';
    document.getElementById('compositeParams').style.display = 'none';
    
    // 根据选择显示对应参数
    if (algorithm === 'dual_thrust') {
        document.getElementById('dualThrustParams').style.display = 'block';
    } else if (algorithm === 'improved') {
        document.getElementById('improvedParams').style.display = 'block';
    } else if (algorithm === 'composite') {
        document.getElementById('compositeParams').style.display = 'block';
    }
    // always_ranging 无额外参数
}
```

### Step 4: 添加入场价格策略配置

**文件**: `web/test_results/index.html`

入场价格策略选项：
- fixed: 固定网格间距（无额外参数）
- atr: ATR 动态策略（atr_period, atr_multiplier, min_spacing, max_spacing）
- bollinger: 布林带策略（period, num_std, min_spacing, max_spacing）
- support: 支撑位策略（period, min_touches, price_tolerance）
- composite: 综合策略（atr_period, atr_multiplier, bb_period, bb_std）

实现动态显示：
```javascript
function onEntryStrategyChange() {
    const strategy = document.getElementById('formEntryStrategy').value;
    
    // 隐藏所有策略参数容器
    document.getElementById('atrParams').style.display = 'none';
    document.getElementById('bollingerParams').style.display = 'none';
    document.getElementById('supportParams').style.display = 'none';
    document.getElementById('compositeParams').style.display = 'none';
    
    // 根据选择显示对应参数
    if (strategy === 'atr') {
        document.getElementById('atrParams').style.display = 'block';
    } else if (strategy === 'bollinger') {
        document.getElementById('bollingerParams').style.display = 'block';
    } else if (strategy === 'support') {
        document.getElementById('supportParams').style.display = 'block';
    } else if (strategy === 'composite') {
        document.getElementById('compositeParams').style.display = 'block';
    }
    // fixed 无额外参数
}
```

### Step 5: 更新 savePlan 函数

更新 `savePlan` 函数以正确收集所有参数：
- amplitude_params: 包含 weights
- market_algorithm_params: 根据算法类型收集对应参数
- entry_algorithm_params: 入场价格策略参数

### Step 6: 更新 showEditPlanForm 函数

更新编辑表单填充逻辑，正确显示所有参数值。

## 验证清单

- [x] 测试场景相关代码已完全删除
- [x] 振幅参数表单包含所有字段（含 weights）
- [x] 行情算法参数根据选择动态显示
- [x] 入场价格策略配置正确显示
- [x] 保存功能正确收集所有参数
- [x] 编辑功能正确填充所有参数值

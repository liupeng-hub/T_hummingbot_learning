# 行情可视化系统算法参数完善计划

## 问题分析

### 当前状态
1. **ALGORITHMS 字典不完整**：只有 3 个算法（dual_thrust, improved, always_ranging），缺少 composite, adx, realtime
2. **参数定义不完整**：各算法参数与 `market_status_detector.py` 中 `get_default_config()` 不一致
3. **前端缺少算法描述**：选择算法时没有显示算法介绍信息

### 目标算法列表
| 算法名 | 类名 | 描述 |
|--------|------|------|
| dual_thrust | DualThrustAlgorithm | Dual Thrust 状态过滤器（增强版） |
| improved | ImprovedStatusAlgorithm | 改进的行情判断算法（支撑阻力+箱体震荡） |
| always_ranging | AlwaysRangingAlgorithm | 始终返回震荡行情（用于对比测试） |
| composite | CompositeAlgorithm | ADX + ATR + 布林带宽度组合判断 |
| adx | ADXAlgorithm | 基于 ADX 的趋势强度判断 |
| realtime | RealTimeStatusAlgorithm | 实时市场状态判断算法（价格行为+波动率） |

## 实施计划

### 任务 1: 更新 ALGORITHMS 字典
**文件**: `market_status_visualizer.py`

更新 ALGORITHMS 字典，包含所有 6 个算法及其完整参数定义：

```python
ALGORITHMS = {
    'dual_thrust': {
        'name': 'Dual Thrust',
        'description': 'Dual Thrust 状态过滤器（增强版）- 基于历史波动幅度构建突破区间',
        'params': {
            'n_days': {'type': 'int', 'default': 4, 'description': '回看天数'},
            'k1': {'type': 'float', 'default': 0.4, 'description': '上轨系数 K1'},
            'k2': {'type': 'float', 'default': 0.4, 'description': '下轨系数 K2'},
            'k2_down_factor': {'type': 'float', 'default': 0.8, 'description': '下跌敏感系数'},
            'down_confirm_days': {'type': 'int', 'default': 2, 'description': '下跌确认天数'},
            'cooldown_days': {'type': 'int', 'default': 1, 'description': '冷却期(天)'},
        }
    },
    'improved': {
        'name': 'Improved Status',
        'description': '改进的行情判断算法 - 支撑阻力+箱体震荡识别',
        'params': {
            'lookback_period': {'type': 'int', 'default': 60, 'description': '回看周期'},
            'min_range_duration': {'type': 'int', 'default': 10, 'description': '最小震荡持续天数'},
            'max_range_pct': {'type': 'float', 'default': 0.15, 'description': '最大震荡区间比例'},
            'breakout_threshold': {'type': 'float', 'default': 0.03, 'description': '突破阈值'},
            'breakout_confirm_days': {'type': 'int', 'default': 3, 'description': '突破确认天数'},
            'swing_window': {'type': 'int', 'default': 5, 'description': '摆动窗口'},
            'merge_threshold': {'type': 'float', 'default': 0.03, 'description': '合并阈值'},
            'min_touches': {'type': 'int', 'default': 3, 'description': '最小触及次数'},
        }
    },
    'always_ranging': {
        'name': 'Always Ranging',
        'description': '始终返回震荡行情 - 用于与原 binance_backtest 的测试结果对比',
        'params': {}
    },
    'composite': {
        'name': 'Composite',
        'description': '组合算法 - ADX + ATR + 布林带宽度综合判断',
        'params': {
            'adx_period': {'type': 'int', 'default': 14, 'description': 'ADX 周期'},
            'adx_threshold': {'type': 'int', 'default': 25, 'description': 'ADX 阈值'},
            'atr_period': {'type': 'int', 'default': 14, 'description': 'ATR 周期'},
            'atr_multiplier': {'type': 'float', 'default': 1.5, 'description': 'ATR 乘数'},
            'bb_period': {'type': 'int', 'default': 20, 'description': '布林带周期'},
            'bb_std': {'type': 'float', 'default': 2.0, 'description': '布林带标准差'},
            'bb_width_threshold': {'type': 'float', 'default': 0.04, 'description': '布林带宽度阈值'},
            'ma_period': {'type': 'int', 'default': 50, 'description': 'MA 周期'},
        }
    },
    'adx': {
        'name': 'ADX',
        'description': '基于 ADX 的趋势强度判断',
        'params': {
            'period': {'type': 'int', 'default': 14, 'description': 'ADX 周期'},
            'threshold': {'type': 'int', 'default': 25, 'description': '趋势阈值'},
        }
    },
    'realtime': {
        'name': 'RealTime',
        'description': '实时市场状态判断算法 - 价格行为+波动率，增加状态惯性',
        'params': {
            'lookback_period': {'type': 'int', 'default': 20, 'description': '回看周期'},
            'breakout_threshold': {'type': 'float', 'default': 0.02, 'description': '突破阈值'},
            'consecutive_bars': {'type': 'int', 'default': 3, 'description': '连续K线数'},
            'atr_period': {'type': 'int', 'default': 14, 'description': 'ATR 周期'},
            'expansion_threshold': {'type': 'float', 'default': 1.5, 'description': '扩张阈值'},
            'contraction_threshold': {'type': 'float', 'default': 0.7, 'description': '收缩阈值'},
            'confirm_periods': {'type': 'int', 'default': 2, 'description': '确认周期数'},
            'min_trend_signals': {'type': 'int', 'default': 4, 'description': '最小趋势信号数'},
            'status_inertia': {'type': 'bool', 'default': True, 'description': '启用状态惯性'},
            'min_trend_confidence': {'type': 'float', 'default': 0.8, 'description': '最小趋势置信度'},
            'min_range_duration': {'type': 'int', 'default': 5, 'description': '最小震荡持续天数'},
        }
    }
}
```

### 任务 2: 更新前端 HTML
**文件**: `web/visualizer/index.html`

1. **添加算法描述显示区域**：在算法选择下拉框下方添加描述信息显示
2. **修改算法选择事件**：切换算法时更新描述信息

修改内容：
- 在算法选择 select 后添加 `<div>` 显示算法描述
- 在 `onAlgorithmChange` 方法中更新描述显示

### 任务 3: 验证参数传递
确保前端参数正确传递到后端，后端正确使用参数初始化算法。

## 预期结果
1. 新建行情测试时，可以选择全部 6 种算法
2. 选择算法后，显示算法描述信息
3. 每个算法显示对应的参数配置项
4. 参数默认值与 `market_status_detector.py` 中定义一致

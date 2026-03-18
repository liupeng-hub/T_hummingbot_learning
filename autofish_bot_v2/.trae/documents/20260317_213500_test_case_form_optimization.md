# 测试用例表单优化计划

## 任务概述
优化测试用例创建表单，改进参数配置的用户体验。

## 修改内容

### 1. 有效振幅 (valid_amplitudes) - 固定值显示
- 移除输入框，改为固定显示 `[1, 2, 3, 4, 5, 6, 7, 8, 9]`
- 用户不可修改此值

### 2. 允许交易状态 - 多选下拉
- 提供所有可能的状态供用户选择（多选）
- 可选状态：`ranging`, `trending_up`, `trending_down`, `transitioning`
- 当选择 `always_ranging` 算法时，自动锁定为只有 `ranging`

### 3. 行情算法 - 完整展示6个算法

| 算法 | 描述 | 参数 |
|------|------|------|
| **always_ranging** | 始终返回震荡行情（用于对比测试） | 无参数 |
| **dual_thrust** | Dual Thrust 状态过滤器（增强版）。基于历史波动幅度构建突破区间，价格在轨道内为震荡，突破上轨为上涨趋势，跌破下轨为下跌趋势 | n_days(4), k1(0.4), k2(0.4), k2_down_factor(0.8), down_confirm_days(2), cooldown_days(1) |
| **improved** | 改进的行情判断算法（支撑阻力+箱体震荡）。更长回看周期，支撑阻力位识别，箱体震荡识别，更严格的趋势确认 | lookback_period(60), min_range_duration(10), max_range_pct(0.15), breakout_threshold(0.03) |
| **composite** | ADX + ATR + 布林带宽度组合判断。综合多指标判断趋势强度 | adx_period(14), adx_threshold(25), atr_period(14), atr_multiplier(1.5), bb_period(20), bb_std(2) |
| **adx** | 基于 ADX 的趋势强度判断。ADX>=threshold 为趋势行情，否则为震荡 | period(14), threshold(25) |
| **realtime** | 实时市场状态判断算法（价格行为+波动率）。增加状态持续性判断（惯性），需要更强的信号才能切换状态 | lookback_period(20), breakout_threshold(0.02), consecutive_bars(3), atr_period(14) |

### 4. 入场策略 - 完整展示5个策略

| 策略 | 描述 | 参数 |
|------|------|------|
| **fixed** | 固定网格策略 | 无参数 |
| **atr** | ATR动态策略。基于ATR计算入场间距 | atr_period(14), atr_multiplier(0.5), min_spacing(0.005), max_spacing(0.03) |
| **bollinger** | 布林带策略。基于布林带计算入场位置 | period(20), num_std(2), min_spacing(0.005), max_spacing(0.03) |
| **support** | 支撑位策略。识别支撑位作为入场点 | period(20), min_touches(2), price_tolerance(0.01) |
| **composite** | 综合策略。结合ATR和布林带 | atr_period(14), atr_multiplier(0.5), bb_period(20), bb_std(2) |

## 实施步骤

### 步骤1: 修改振幅参数Tab
- 将 `valid_amplitudes` 输入框改为固定文本显示
- 移除 `weights` 输入框（使用默认权重）

### 步骤2: 修改行情算法Tab
- 更新算法选择下拉框，添加6个算法选项
- 为每个算法添加描述信息
- 为每个算法创建对应的参数表单区域
- 添加 `realtime` 算法的参数表单

### 步骤3: 修改允许交易状态
- 改为多选复选框形式
- 选项：ranging, trending_up, trending_down, transitioning
- 添加JavaScript逻辑：选择 always_ranging 时自动锁定为 ranging

### 步骤4: 修改入场策略Tab
- 更新策略选择下拉框，添加5个策略选项
- 为每个策略添加描述信息
- 为每个策略创建对应的参数表单区域
- 添加 `support` 和 `composite` 策略的参数表单

### 步骤5: 更新JavaScript逻辑
- 更新 `onMarketAlgorithmChange()` 函数
- 更新 `onEntryStrategyChange()` 函数
- 添加 `always_ranging` 算法的特殊处理逻辑

### 步骤6: 更新DEFAULT_PARAMS
- 在JavaScript中添加完整的默认参数配置
- 确保与后端配置一致

## 文件修改
- `/Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/web/test_results/index.html`

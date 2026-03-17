# autofish_extern_strategy.json 配置格式改造计划

## 背景

当前 `autofish_extern_strategy.json` 配置格式不够清晰，需要改造为 key=value 的方式，使配置更加结构化和易于管理。

## 当前格式

```json
{
  "entry_price_strategy": {
    "name": "atr",
    "params": {
      "atr_period": 14,
      "atr_multiplier": 0.5,
      "min_spacing": 0.005,
      "max_spacing": 0.03
    }
  },
  "market_aware": {
    "enabled": true,
    "algorithm": "dual_thrust",
    "lookback_period": 20,
    "breakout_threshold": 0.02,
    "consecutive_bars": 3,
    "down_confirm_days": 1,
    "k2_down_factor": 0.6,
    "cooldown_days": 1,
    "check_interval": 60,
    "trading_statuses": ["ranging"]
  }
}
```

## 新格式

```json
{
  "entry_price_strategy": {
    "strategy": "atr",
    "atr": {
      "atr_period": 14,
      "atr_multiplier": 0.5,
      "min_spacing": 0.005,
      "max_spacing": 0.03
    },
    "bollinger": {
      "period": 20,
      "num_std": 2,
      "min_spacing": 0.005,
      "max_spacing": 0.03
    }
  },
  "market_aware": {
    "algorithm": "dual_thrust",
    "dual_thrust": {
      "lookback_period": 20,
      "breakout_threshold": 0.02,
      "consecutive_bars": 3,
      "down_confirm_days": 1,
      "k2_down_factor": 0.6,
      "cooldown_days": 1,
      "check_interval": 60
    },
    "improved": {
      "lookback_period": 60,
      "min_range_duration": 10,
      "max_range_pct": 0.15
    },
    "trading_statuses": ["ranging"]
  }
}
```

## 主要变更

### 1. entry_price_strategy
- `name` 改为 `strategy`
- `params` 改为直接以策略名为 key，参数为 value
- 支持多个策略配置，通过 `strategy` 指定当前使用的策略

### 2. market_aware
- 删除 `enabled` 字段
- 算法参数从顶层移到以算法名为 key 的子字典中
- 支持多个算法配置，通过 `algorithm` 指定当前使用的算法
- `trading_statuses` 保留在顶层

## 实施步骤

### Step 1: 更新 Autofish_ExternStrategy 类

**文件**: `autofish_core.py`

修改 `Autofish_ExternStrategy` 类：
- 更新 `DEFAULT_CONFIG` 为新格式
- 修改 `get_entry_price_strategy()` 方法返回新格式
- 修改 `get_market_aware()` 方法返回新格式
- 添加 `get_active_entry_strategy()` 方法获取当前激活的策略参数
- 添加 `get_active_market_algorithm()` 方法获取当前激活的算法参数

### Step 2: 更新 binance_backtest.py

修改使用配置的代码：
- `entry_price_strategy` 从 `{"name": xxx, "params": {}}` 改为 `{"strategy": xxx, xxx: {}}`
- 使用 `get_active_entry_strategy()` 获取当前策略参数

### Step 3: 更新 binance_live.py

修改使用配置的代码：
- `market_aware` 配置读取适配新格式
- `entry_price_strategy` 配置读取适配新格式

### Step 4: 更新 market_aware_backtest.py

修改使用配置的代码：
- `market_algorithm_params` 配置读取适配新格式

### Step 5: 更新 Web 页面

**文件**: `web/test_results/index.html`

修改 JavaScript 代码：
- `savePlan()` 函数生成新格式的配置
- `showEditPlanForm()` 函数解析新格式的配置

### Step 6: 更新 test_manager.py API

修改 API 端点：
- 保存和读取配置时使用新格式

### Step 7: 更新配置文件

更新 `autofish_extern_strategy.json` 为新格式

## 验证清单

- [x] Autofish_ExternStrategy 类已更新
- [x] binance_backtest.py 已适配
- [x] binance_live.py 已适配
- [x] market_aware_backtest.py 已适配
- [x] Web 页面已适配
- [x] test_manager.py API 已适配
- [x] 配置文件已更新
- [x] 功能测试通过

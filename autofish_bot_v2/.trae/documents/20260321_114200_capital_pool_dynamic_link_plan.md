# 资金池与订单金额动态关联实现计划

## 需求分析

### 核心概念
- **交易资金变量**：资金池中定义，初始值来自 `total_amount_quote`
- **一轮交易**：从 A1 入场开始，到所有订单（A1-A4）平仓结束的完整交易周期
- **capital 是必选参数**：必须提供 capital 参数
- **资金池作为数据中心**：记录所有资金数据，回测与资金池对接

### 一轮交易的定义

**一轮交易流程：**
```
入场阶段:
  A1 入场 → A2 入场 → A3 入场 → A4 入场
  
平仓阶段（止盈/止损）:
  A4 平仓 → A3 平仓 → A2 平仓 → A1 平仓
  
轮次结束:
  所有订单平仓 → 更新资金池 → 下一轮开始
```

**关键点：**
- 同一轮内，A1-A4 订单金额在入场时确定，保持一致
- 资金池更新发生在**一轮交易结束后**，不是每笔交易后
- 下一轮订单金额 = 上一轮结束后的资金池金额

### 两种模式

#### Fix 模式（固定模式）
- 每一轮交易固定使用**初始资金**进行下单
- 盈亏单独统计为该轮交易的总盈亏
- 整个测试总体盈亏 = 每一轮交易的盈亏总和
- 优点：方便跟踪分析交易的单笔和总盈亏值

#### Progressive 模式（递进模式）
- 按资金池策略进行资金操作
- 一轮交易结束后更新资金池
- 下一轮订单金额 = 资金池当前 `trading_capital`
- 支持提现和爆仓恢复机制

### 资金更新时机对比

| 方案 | 更新时机 | 同一轮内订单金额 | Progressive 模式影响 |
|------|---------|-----------------|---------------------|
| 方案 A（当前） | 每笔交易后 | 可能不一致 | A1 平仓后 A2/A3/A4 金额会变化 |
| 方案 B（期望） | 每轮交易后 | 保持一致 | 下一轮才变化 |

**当前代码实际行为：**
- 订单金额在订单创建时确定（`total_amount = config.get("total_amount_quote")`）
- 同一轮内订单金额确实保持一致
- 但 `total_amount` 是固定配置值，不会随资金池变化

**需要修改为方案 B：**
```
第 1 轮: total_amount_quote → A1/A2/A3/A4 订单金额
    ↓
第 1 轮结束: 所有订单平仓 → 更新资金池
    ↓
第 2 轮: 资金池.trading_capital → A1/A2/A3/A4 订单金额
```

### 爆仓阈值（liquidation_threshold）计算

**基于交易参数自动计算：**
```python
liquidation_threshold = 1 - (stop_loss × leverage)
```

**示例：**
```
stop_loss = 0.08 (8% 价格下跌止损)
leverage = 10 (10 倍杠杆)

单笔订单最大亏损 = stop_loss × leverage = 0.08 × 10 = 0.8 (80%)
liquidation_threshold = 1 - 0.8 = 0.2

触发条件: trading_capital < initial_capital × 0.2
含义: 亏损 80% 时触发爆仓恢复
```

**参数关系表：**

| 参数 | 值 | 说明 |
|------|-----|------|
| `stop_loss` | 0.08 | 8% 价格下跌触发止损 |
| `leverage` | 10 | 10 倍杠杆 |
| 单笔最大亏损 | 80% | stop_loss × leverage |
| `liquidation_threshold` | 0.2 | 1 - 单笔最大亏损 |

**爆仓恢复机制：**
```
trading_capital < initial_capital × liquidation_threshold
    ↓
触发爆仓恢复
    ↓
从 profit_pool 恢复资金到 initial_capital
    ↓
开始新一轮交易
```

## 当前问题

1. `total_amount_quote` 和资金池 `initial_capital` 是独立配置的
2. 订单金额使用固定的 `total_amount_quote`，不会随资金池变化
3. 资金池初始化代码零散，不好理解
4. 缺少"一轮交易"的概念和盈亏统计
5. 回测与资金池对接不清晰
6. 命名不统一：`Autofish_CapitalPool` 需要改为 `ProgressiveCapitalTracker`
7. 配置文件冗余：`initial_capital` 和 `liquidation_threshold` 不需要单独配置

## 配置文件简化

### autofish_extern_strategy.json 简化

**简化前：**
```json
{
  "capital_pool_strategy": {
    "mode": "fixed",
    "initial_capital": 10000,           // 冗余：来自 total_amount_quote
    "strategy": "conservative",
    "conservative": {
      "withdrawal_threshold": 2.0,
      "withdrawal_retain": 1.5,
      "liquidation_threshold": 0.1      // 冗余：基于 stop_loss × leverage 自动计算
    },
    "aggressive": {...},
    "very_conservative": {...},
    "custom": {}
  }
}
```

**简化后：**
```json
{
  "capital_pool_strategy": {
    "strategy": "guding",
    "baoshou": {
      "withdrawal_threshold": 2.0,
      "withdrawal_retain": 1.5
    },
    "wenjian": {
      "withdrawal_threshold": 3.0,
      "withdrawal_retain": 2.0
    },
    "jijin": {
      "withdrawal_threshold": 1.5,
      "withdrawal_retain": 1.2
    }
  }
}
```

**参数来源说明：**

| 参数 | 来源 | 说明 |
|------|------|------|
| `initial_capital` | `amplitude.total_amount_quote` | 订单总金额作为初始资金 |
| `liquidation_threshold` | `1 - (stop_loss × leverage)` | 基于 amplitude 配置自动计算 |
| `withdrawal_threshold` | 预设策略或自定义 | 从 capital_pool_strategy 获取 |
| `withdrawal_retain` | 预设策略或自定义 | 从 capital_pool_strategy 获取 |

## CLI 参数结构

### --capital-params 参数格式

```bash
# 固定模式
--capital-params '{"strategy": "guding"}'

# 保守策略（使用预设参数）
--capital-params '{"strategy": "baoshou"}'

# 保守策略（覆盖预设参数）
--capital-params '{"strategy": "baoshou", "withdrawal_threshold": 2.5, "withdrawal_retain": 1.8}'

# 自定义策略（必须指定参数）
--capital-params '{"strategy": "zidingyi", "withdrawal_threshold": 2.5, "withdrawal_retain": 1.8}'
```

### 参数覆盖规则

| 策略 | withdrawal_threshold | withdrawal_retain | 说明 |
|------|---------------------|-------------------|------|
| `guding` | 忽略 | 忽略 | 固定模式不使用这些参数 |
| `baoshou` | 可覆盖（默认2.0） | 可覆盖（默认1.5） | 用户可覆盖预设值 |
| `wenjian` | 可覆盖（默认3.0） | 可覆盖（默认2.0） | 用户可覆盖预设值 |
| `jijin` | 可覆盖（默认1.5） | 可覆盖（默认1.2） | 用户可覆盖预设值 |
| `zidingyi` | 必填 | 必填 | 必须指定参数 |

### 参数字段说明

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `strategy` | 是 | string | 策略名称：`guding`、`baoshou`、`wenjian`、`jijin`、`zidingyi` |
| `withdrawal_threshold` | zidingyi 时必填 | float | 提现阈值 |
| `withdrawal_retain` | zidingyi 时必填 | float | 保留比例 |

### 策略参数对照表

| 策略 | withdrawal_threshold | withdrawal_retain | 说明 |
|------|---------------------|-------------------|------|
| `guding` | - | - | 固定模式，无提现参数 |
| `baoshou` | 2.0 | 1.5 | 保守：资金翻倍时提现 |
| `wenjian` | 3.0 | 2.0 | 稳健：资金3倍时提现 |
| `jijin` | 1.5 | 1.2 | 激进：资金1.5倍时提现 |
| `zidingyi` | 自定义 | 自定义 | 需要指定参数 |

### 模式与策略关系

```
strategy: guding
├── 模式：固定
├── 参数：无
└── 行为：每轮使用初始资金，记录盈亏

strategy: baoshou / wenjian / jijin
├── 模式：递进
├── 参数：预设值
└── 行为：资金动态变化，触发提现/爆仓恢复

strategy: zidingyi
├── 模式：递进
├── 参数：用户指定 withdrawal_threshold 和 withdrawal_retain
└── 行为：资金动态变化，触发提现/爆仓恢复
```

**注意：** `initial_capital` 和 `liquidation_threshold` 不需要在 CLI 中指定，会自动从 `amplitude` 配置获取。

## API 请求结构

### 创建测试用例 API

**POST /api/cases**

```json
{
  "name": "BTCUSDT测试",
  "symbol": "BTCUSDT",
  "date_start": "20240101",
  "date_end": "20240131",
  "amplitude": {
    "total_amount_quote": 10000,
    "stop_loss": 0.08,
    "leverage": 10,
    ...
  },
  "capital": {
    "mode": "progressive",
    "strategy": "conservative"
  }
}
```

### 数据库存储结构

**test_cases 表 capital 字段：**
```json
{
  "mode": "progressive",
  "strategy": "conservative"
}
```

**test_results 表 capital 字段：**
```json
{
  "mode": "progressive",
  "strategy": "conservative",
  "initial_capital": 10000,
  "liquidation_threshold": 0.2
}
```

## 完整示例

### CLI 创建测试用例

```bash
python test_manager.py create-case \
  --symbol BTCUSDT \
  --date-range 20240101-20240131 \
  --name "BTCUSDT资金池测试" \
  --amplitude-params '{"total_amount_quote": 10000, "stop_loss": 0.08, "leverage": 10, "decay_factor": 0.5, "max_entries": 4, "grid_spacing": 0.01, "exit_profit": 0.01}' \
  --market-params '{"algorithm": "dual_thrust", "trading_statuses": ["ranging"], "dual_thrust": {"n_days": 4, "k1": 0.4, "k2": 0.4}}' \
  --capital-params '{"strategy": "baoshou"}'
```

### Web API 创建测试用例

```javascript
fetch('/api/cases', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    name: "BTCUSDT资金池测试",
    symbol: "BTCUSDT",
    date_start: "20240101",
    date_end: "20240131",
    amplitude: {
      total_amount_quote: 10000,
      stop_loss: 0.08,
      leverage: 10,
      decay_factor: 0.5,
      max_entries: 4,
      grid_spacing: 0.01,
      exit_profit: 0.01
    },
    market: {
      algorithm: "dual_thrust",
      trading_statuses: ["ranging"],
      dual_thrust: {n_days: 4, k1: 0.4, k2: 0.4}
    },
    capital: {
      strategy: "baoshou"
    }
  })
})
```

## Web 前端资金池配置表单设计

### 表单布局

```
┌─────────────────────────────────────────────────────────────┐
│  资金池策略                                                   │
├─────────────────────────────────────────────────────────────┤
│  策略选择: [下拉框]                                           │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ ○ 固定模式 (guding)                                      ││
│  │ ○ 保守策略 (baoshou) - 资金翻倍时提现                      ││
│  │ ○ 稳健策略 (wenjian) - 资金3倍时提现                       ││
│  │ ○ 激进策略 (jijin) - 资金1.5倍时提现                       ││
│  │ ○ 自定义策略 (zidingyi)                                   ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  策略参数: (非固定模式显示)                                    │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 提现阈值: [  2.0  ] 倍  (资金达到初始资金×阈值时提现)        ││
│  │ 保留比例: [  1.5  ] 倍  (提现后保留初始资金×比例)            ││
│  │ 爆仓阈值: [  0.2  ]     (自动计算: 1 - stop_loss × leverage)││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  自动计算参数: (只读显示)                                      │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 初始资金: 10000 USDT (来自 total_amount_quote)            ││
│  │ 爆仓阈值: 0.2 (1 - 0.08 × 10)                             ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 策略选择下拉框

```html
<select id="capitalStrategy">
  <option value="guding">固定模式 (guding)</option>
  <option value="baoshou">保守策略 (baoshou) - 提现阈值2.0, 保留1.5</option>
  <option value="wenjian">稳健策略 (wenjian) - 提现阈值3.0, 保留2.0</option>
  <option value="jijin">激进策略 (jijin) - 提现阈值1.5, 保留1.2</option>
  <option value="zidingyi">自定义策略 (zidingyi)</option>
</select>
```

### 参数默认值展示

| 策略 | withdrawal_threshold | withdrawal_retain | liquidation_threshold | 是否可编辑 |
|------|---------------------|-------------------|----------------------|-----------|
| guding | - | - | - | 隐藏参数区域 |
| baoshou | 2.0 | 1.5 | 自动计算 | 可覆盖 |
| wenjian | 3.0 | 2.0 | 自动计算 | 可覆盖 |
| jijin | 1.5 | 1.2 | 自动计算 | 可覆盖 |
| zidingyi | 必填 | 必填 | 自动计算 | 必填 |

### 前端交互逻辑

```javascript
// 策略选择变化时
function onStrategyChange(strategy) {
  const paramsSection = document.getElementById('capitalParamsSection');
  const thresholdInput = document.getElementById('withdrawalThreshold');
  const retainInput = document.getElementById('withdrawalRetain');
  
  if (strategy === 'guding') {
    // 固定模式：隐藏参数区域
    paramsSection.style.display = 'none';
  } else if (strategy === 'zidingyi') {
    // 自定义：清空输入框，设为必填
    paramsSection.style.display = 'block';
    thresholdInput.value = '';
    retainInput.value = '';
    thresholdInput.required = true;
    retainInput.required = true;
  } else {
    // 预设策略：填充默认值，可覆盖
    paramsSection.style.display = 'block';
    const defaults = {
      'baoshou': { withdrawal_threshold: 2.0, withdrawal_retain: 1.5 },
      'wenjian': { withdrawal_threshold: 3.0, withdrawal_retain: 2.0 },
      'jijin': { withdrawal_threshold: 1.5, withdrawal_retain: 1.2 }
    };
    thresholdInput.value = defaults[strategy].withdrawal_threshold;
    retainInput.value = defaults[strategy].withdrawal_retain;
    thresholdInput.required = false;
    retainInput.required = false;
  }
}
```

## 数据库表结构核对

### test_cases 表

| 字段 | 类型 | 说明 |
|------|------|------|
| capital | TEXT | JSON 格式，如 `{"strategy": "baoshou", "withdrawal_threshold": 2.0, "withdrawal_retain": 1.5}` |

### test_results 表

| 字段 | 类型 | 说明 |
|------|------|------|
| capital | TEXT | JSON 格式，包含完整参数 |

**capital 字段结构：**
```json
{
  "strategy": "baoshou",
  "withdrawal_threshold": 2.0,
  "withdrawal_retain": 1.5,
  "initial_capital": 10000,
  "liquidation_threshold": 0.2
}
```

### capital_statistics 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| result_id | TEXT | 外键，关联 test_results.result_id |
| strategy | TEXT | 策略名称 |
| initial_capital | REAL | 初始资金 |
| final_capital | REAL | 最终资金 |
| trading_capital | REAL | 交易资金 |
| profit_pool | REAL | 利润池 |
| total_return | REAL | 总收益率 (%) |
| total_profit | REAL | 累计盈利 |
| total_loss | REAL | 累计亏损 |
| max_capital | REAL | 最大资金 |
| max_drawdown | REAL | 最大回撤 (%) |
| withdrawal_threshold | REAL | 提现阈值 |
| withdrawal_retain | REAL | 保留比例 |
| liquidation_threshold | REAL | 爆仓阈值 |
| withdrawal_count | INTEGER | 提现次数 |
| liquidation_count | INTEGER | 爆仓次数 |
| round_count | INTEGER | 交易轮次 |
| win_rounds | INTEGER | 盈利轮次 |
| loss_rounds | INTEGER | 亏损轮次 |
| win_rate | REAL | 胜率 (%) |
| avg_round_profit | REAL | 平均轮次盈亏 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

### capital_history 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| result_id | TEXT | 外键，关联 test_results.result_id |
| statistics_id | INTEGER | 外键，关联 capital_statistics.id |
| timestamp | TEXT | 时间戳 |
| old_capital | REAL | 变化前资金 |
| new_capital | REAL | 变化后资金 |
| profit | REAL | 盈亏金额 |
| event_type | TEXT | 事件类型：trade/withdrawal/liquidation |
| created_at | TEXT | 创建时间 |

### 外键约束

```sql
-- capital_statistics
FOREIGN KEY (result_id) REFERENCES test_results(result_id) ON DELETE CASCADE

-- capital_history
FOREIGN KEY (result_id) REFERENCES test_results(result_id) ON DELETE CASCADE
FOREIGN KEY (statistics_id) REFERENCES capital_statistics(id) ON DELETE CASCADE
```

## 实现方案

### Task 1: 统一命名规范

**修改文件**: `autofish_core.py`

将 `Autofish_CapitalPool` 重命名为 `ProgressiveCapitalTracker`，统一命名规范：
- `FixedCapitalTracker` - 固定模式资金追踪器
- `ProgressiveCapitalTracker` - 递进模式资金追踪器

### Task 2: 封装资金池初始化

**修改文件**: `autofish_core.py`

创建 `CapitalPoolFactory` 工厂类，封装资金池初始化逻辑。

### Task 3: 封装订单金额获取

**修改文件**: `binance_backtest.py`

封装订单金额获取逻辑到 `_get_trading_capital()` 方法。

### Task 4: 统一资金来源

**修改文件**: `binance_backtest.py`

在 `MarketAwareBacktestEngine.__init__` 中：
- `total_amount_quote` 作为资金池的初始交易资金
- 使用工厂类初始化资金池

### Task 5: 回测与资金池对接

**修改文件**: `binance_backtest.py`

- 回测开始时创建资金池
- 每轮交易后更新资金池
- 回测结束时保存资金池数据到数据库

## 详细实现步骤

### Step 1: 创建 FixedCapitalTracker 类

**修改文件**: `autofish_core.py`

```python
@dataclass
class FixedCapitalTracker:
    """固定模式资金追踪器
    
    用于固定模式下的资金追踪，记录每轮交易盈亏
    """
    initial_capital: Decimal
    
    # 轮次盈亏统计
    round_profits: List[Decimal] = field(default_factory=list)
    total_round_profit: Decimal = Decimal('0')
    
    # 历史记录
    capital_history: List[Dict] = field(default_factory=list)
    
    @property
    def trading_capital(self) -> Decimal:
        """固定模式始终返回初始资金"""
        return self.initial_capital
    
    @property
    def capital_mode(self) -> str:
        return 'fixed'
    
    def process_trade_profit(self, profit: Decimal) -> Dict:
        """处理交易盈亏"""
        self.round_profits.append(profit)
        self.total_round_profit += profit
        
        result = {
            'mode': 'fixed',
            'profit': profit,
            'total_round_profit': float(self.total_round_profit),
            'round_count': len(self.round_profits),
        }
        
        self.capital_history.append({
            'timestamp': datetime.now().isoformat(),
            'profit': float(profit),
            'total_profit': float(self.total_round_profit),
        })
        
        return result
    
    def get_statistics(self) -> Dict:
        """获取统计数据"""
        win_rounds = sum(1 for p in self.round_profits if p > 0)
        loss_rounds = sum(1 for p in self.round_profits if p < 0)
        
        return {
            'mode': 'fixed',
            'initial_capital': float(self.initial_capital),
            'final_capital': float(self.initial_capital + self.total_round_profit),
            'trading_capital': float(self.initial_capital),
            'total_round_profit': float(self.total_round_profit),
            'round_count': len(self.round_profits),
            'win_rounds': win_rounds,
            'loss_rounds': loss_rounds,
            'win_rate': win_rounds / len(self.round_profits) * 100 if self.round_profits else 0,
            'avg_round_profit': float(self.total_round_profit / len(self.round_profits)) if self.round_profits else 0,
            'capital_history': self.capital_history,
        }
```

### Step 2: 创建 ProgressiveCapitalTracker 类

**修改文件**: `autofish_core.py`

将 `Autofish_CapitalPool` 重命名为 `ProgressiveCapitalTracker`：

```python
@dataclass
class ProgressiveCapitalTracker:
    """递进模式资金追踪器
    
    管理交易资金的动态变化，支持提现和爆仓恢复机制
    """
    initial_capital: Decimal
    trading_capital: Decimal = None
    profit_pool: Decimal = Decimal('0')
    
    # 交易统计
    total_profit: Decimal = Decimal('0')
    total_loss: Decimal = Decimal('0')
    round_profits: List[Decimal] = field(default_factory=list)
    total_round_profit: Decimal = Decimal('0')
    
    # 阈值参数
    withdrawal_threshold: Decimal = Decimal('2.0')
    withdrawal_retain: Decimal = Decimal('1.5')
    liquidation_threshold: Decimal = Decimal('0.2')  # 默认基于 stop_loss=0.08, leverage=10
    
    # 计数器
    withdrawal_count: int = 0
    liquidation_count: int = 0
    
    # 历史记录
    capital_history: List[Dict] = field(default_factory=list)
    
    def __post_init__(self):
        if self.trading_capital is None:
            self.trading_capital = self.initial_capital
        self.max_capital = self.initial_capital
    
    @property
    def capital_mode(self) -> str:
        return 'progressive'
    
    def set_strategy(self, strategy: str, stop_loss: float = 0.08, leverage: int = 10):
        """设置预设策略
        
        Args:
            strategy: 策略名称
            stop_loss: 止损比例（默认 0.08 = 8%）
            leverage: 杠杆倍数（默认 10）
        """
        # 基于 stop_loss 和 leverage 自动计算 liquidation_threshold
        auto_liquidation_threshold = 1 - (stop_loss * leverage)
        
        strategies = {
            'conservative': {'withdrawal_threshold': 2.0, 'withdrawal_retain': 1.5},
            'aggressive': {'withdrawal_threshold': 1.5, 'withdrawal_retain': 1.2},
            'very_conservative': {'withdrawal_threshold': 3.0, 'withdrawal_retain': 2.0},
        }
        
        if strategy in strategies:
            params = strategies[strategy]
            self.withdrawal_threshold = Decimal(str(params['withdrawal_threshold']))
            self.withdrawal_retain = Decimal(str(params['withdrawal_retain']))
        
        # 使用自动计算的爆仓阈值
        self.liquidation_threshold = Decimal(str(auto_liquidation_threshold))
    
    def update_capital(self, profit: Decimal) -> Dict:
        """更新资金"""
        old_trading_capital = self.trading_capital
        
        if profit > 0:
            self.trading_capital += profit
            self.total_profit += profit
        else:
            self.trading_capital += profit
            self.total_loss += abs(profit)
        
        if self.trading_capital > self.max_capital:
            self.max_capital = self.trading_capital
        
        result = {
            'old_capital': old_trading_capital,
            'new_capital': self.trading_capital,
            'profit': profit,
        }
        
        self.capital_history.append({
            'timestamp': datetime.now().isoformat(),
            'old_capital': float(old_trading_capital),
            'new_capital': float(self.trading_capital),
            'profit': float(profit),
            'event_type': 'trade',
        })
        
        return result
    
    def check_withdrawal(self) -> Optional[Dict]:
        """检查是否触发提现"""
        threshold_amount = self.initial_capital * self.withdrawal_threshold
        
        if self.trading_capital >= threshold_amount:
            retain_amount = self.initial_capital * self.withdrawal_retain
            withdrawal_amount = self.trading_capital - retain_amount
            
            if withdrawal_amount > 0:
                self.profit_pool += withdrawal_amount
                self.trading_capital = retain_amount
                self.withdrawal_count += 1
                
                self.capital_history.append({
                    'timestamp': datetime.now().isoformat(),
                    'old_capital': float(retain_amount + withdrawal_amount),
                    'new_capital': float(retain_amount),
                    'profit': float(withdrawal_amount),
                    'event_type': 'withdrawal',
                })
                
                return {
                    'withdrawal_amount': float(withdrawal_amount),
                    'trading_capital': float(self.trading_capital),
                    'profit_pool': float(self.profit_pool),
                }
        
        return None
    
    def check_liquidation(self) -> bool:
        """检查是否触发爆仓"""
        threshold_amount = self.initial_capital * self.liquidation_threshold
        return self.trading_capital < threshold_amount
    
    def recover_from_liquidation(self):
        """爆仓恢复"""
        if self.profit_pool > 0:
            recover_amount = min(self.profit_pool, self.initial_capital - self.trading_capital)
            self.profit_pool -= recover_amount
            self.trading_capital += recover_amount
            self.liquidation_count += 1
            
            self.capital_history.append({
                'timestamp': datetime.now().isoformat(),
                'old_capital': float(self.trading_capital - recover_amount),
                'new_capital': float(self.trading_capital),
                'profit': float(recover_amount),
                'event_type': 'liquidation',
            })
    
    def process_trade_profit(self, profit: Decimal) -> Dict:
        """处理交易盈亏（封装完整流程）"""
        # 1. 更新资金
        result = self.update_capital(profit)
        
        # 记录轮次盈亏
        self.round_profits.append(profit)
        self.total_round_profit += profit
        
        # 2. 检查提现
        withdrawal = self.check_withdrawal()
        if withdrawal:
            result['withdrawal'] = withdrawal
        
        # 3. 检查爆仓
        if self.check_liquidation():
            result['liquidation_triggered'] = True
            self.recover_from_liquidation()
        
        return result
    
    def get_statistics(self) -> Dict:
        """获取统计数据"""
        total_return = (self.trading_capital + self.profit_pool - self.initial_capital) / self.initial_capital * 100
        
        max_drawdown = 0
        if self.max_capital > self.trading_capital:
            max_drawdown = (self.max_capital - self.trading_capital) / self.max_capital * 100
        
        win_rounds = sum(1 for p in self.round_profits if p > 0)
        loss_rounds = sum(1 for p in self.round_profits if p < 0)
        
        return {
            'mode': 'progressive',
            'initial_capital': float(self.initial_capital),
            'final_capital': float(self.trading_capital + self.profit_pool),
            'trading_capital': float(self.trading_capital),
            'profit_pool': float(self.profit_pool),
            'total_return': float(total_return),
            'total_profit': float(self.total_profit),
            'total_loss': float(self.total_loss),
            'max_capital': float(self.max_capital),
            'max_drawdown': float(max_drawdown),
            'withdrawal_count': self.withdrawal_count,
            'liquidation_count': self.liquidation_count,
            'round_count': len(self.round_profits),
            'win_rounds': win_rounds,
            'loss_rounds': loss_rounds,
            'win_rate': win_rounds / len(self.round_profits) * 100 if self.round_profits else 0,
            'avg_round_profit': float(self.total_round_profit / len(self.round_profits)) if self.round_profits else 0,
            'capital_history': self.capital_history,
        }
```

### Step 3: 创建 CapitalPoolFactory 工厂类

**修改文件**: `autofish_core.py`

```python
class CapitalPoolFactory:
    """资金池工厂类
    
    封装资金池初始化逻辑，提供统一的创建接口
    """
    
    @staticmethod
    def create(
        initial_capital: Decimal, 
        capital_config: Dict,
        stop_loss: float = 0.08,
        leverage: int = 10
    ) -> Union[FixedCapitalTracker, ProgressiveCapitalTracker]:
        """
        创建资金池实例
        
        Args:
            initial_capital: 初始资金（来自 total_amount_quote）
            capital_config: 资金配置
            stop_loss: 止损比例（默认 0.08 = 8%）
            leverage: 杠杆倍数（默认 10）
            
        Returns:
            资金池实例（根据模式返回不同类型）
        """
        mode = capital_config.get('mode', 'fixed')
        
        if mode == 'fixed':
            return FixedCapitalTracker(initial_capital)
        
        strategy = capital_config.get('strategy', 'conservative')
        
        tracker = ProgressiveCapitalTracker(initial_capital)
        
        if strategy == 'custom':
            tracker.withdrawal_threshold = Decimal(str(capital_config.get('withdrawal_threshold', 2.0)))
            tracker.withdrawal_retain = Decimal(str(capital_config.get('withdrawal_retain', 1.5)))
            # 自定义模式下，仍然基于 stop_loss 和 leverage 计算爆仓阈值
            auto_liquidation_threshold = 1 - (stop_loss * leverage)
            tracker.liquidation_threshold = Decimal(str(capital_config.get('liquidation_threshold', auto_liquidation_threshold)))
        else:
            tracker.set_strategy(strategy, stop_loss, leverage)
        
        return tracker
```

### Step 4: 修改 MarketAwareBacktestEngine

**修改文件**: `binance_backtest.py`

```python
class MarketAwareBacktestEngine(MarketAwareBacktest):
    """市场感知回测引擎"""
    
    def __init__(
        self,
        amplitude: Dict,
        market: Dict,
        entry: Dict,
        timeout: Dict,
        capital: Dict,  # 必选参数
    ):
        config = amplitude.copy()
        config['a1_timeout_minutes'] = timeout.get('a1_timeout_minutes', 0)
        
        if entry:
            config['entry_price_strategy'] = entry
        
        super().__init__(config)
        
        # ... 现有初始化代码 ...
        
        # 初始化资金池（使用工厂类封装）
        self.total_amount_quote = Decimal(str(amplitude.get('total_amount_quote', 10000)))
        self.initial_capital = self.total_amount_quote
        
        # 从 amplitude 配置获取 stop_loss 和 leverage
        self.stop_loss = float(amplitude.get('stop_loss', 0.08))
        self.leverage = int(amplitude.get('leverage', 10))
        
        from autofish_core import CapitalPoolFactory
        self.capital_pool = CapitalPoolFactory.create(
            self.initial_capital, 
            capital,
            self.stop_loss,
            self.leverage
        )
        self.capital_mode = self.capital_pool.capital_mode
    
    def _get_trading_capital(self) -> Decimal:
        """获取当前交易资金"""
        return self.capital_pool.trading_capital
    
    def _create_order(self, level: int, base_price: Decimal, klines: List[Dict] = None):
        # 获取当前交易资金
        total_amount = self._get_trading_capital()
        # ... 后续订单计算逻辑 ...
    
    def _update_capital_after_trade(self, profit: Decimal) -> Dict:
        """交易后更新资金池"""
        return self.capital_pool.process_trade_profit(profit)
    
    def get_final_statistics(self) -> Dict:
        """获取最终统计数据"""
        return self.capital_pool.get_statistics()
```

### Step 5: 回测与资金池对接

**修改文件**: `binance_backtest.py`

```python
async def run_backtest(engine: MarketAwareBacktestEngine, ...):
    """运行回测"""
    
    # 回测开始
    logger.info(f"[回测] 开始，初始资金: {engine._get_trading_capital()}")
    
    async for kline in klines:
        # ... 交易逻辑 ...
        
        if trade_completed:
            # 交易完成后更新资金池
            result = engine._update_capital_after_trade(profit)
            logger.info(f"[资金池] 交易完成，盈亏: {profit}, 当前资金: {engine._get_trading_capital()}")
    
    # 回测结束，获取统计数据
    stats = engine.get_final_statistics()
    logger.info(f"[回测] 结束，统计数据: {stats}")
    
    return stats


def _save_to_database(args, engine, ...):
    """保存到数据库"""
    # ... 现有保存逻辑 ...
    
    # 保存资金统计数据
    stats = engine.get_final_statistics()
    db.save_capital_statistics(result_id, stats)
    db.save_capital_history(result_id, stats.get('id', 0), stats.get('capital_history', []))
```

## 类结构图

```
CapitalPoolFactory
    │
    ├── create(initial_capital, capital_config)
    │       │
    │       ├── mode='fixed' → FixedCapitalTracker
    │       └── mode='progressive' → ProgressiveCapitalTracker
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│                    统一接口                                    │
├─────────────────────────────────────────────────────────────┤
│  - trading_capital: Decimal    (当前交易资金)                  │
│  - capital_mode: str           (资金模式)                      │
│  - process_trade_profit(profit) → Dict                       │
│  - get_statistics() → Dict                                   │
└─────────────────────────────────────────────────────────────┘
    │
    ├── FixedCapitalTracker (固定模式)
    │       - initial_capital (固定不变)
    │       - round_profits
    │       - total_round_profit
    │       - capital_history
    │
    └── ProgressiveCapitalTracker (递进模式)
            - initial_capital
            - trading_capital (动态变化)
            - profit_pool
            - withdrawal_count
            - liquidation_count
            - capital_history
```

## 数据流程图

### 回测与资金池对接流程

```
回测开始
    ↓
CapitalPoolFactory.create(total_amount_quote, capital_config)
    ↓
┌─────────────────────────────────────────────────────────────┐
│                    资金池实例                                 │
│  ┌─────────────────────┐  ┌───────────────────────────────┐ │
│  │ FixedCapitalTracker │  │ ProgressiveCapitalTracker     │ │
│  │ (fixed)             │  │ (progressive)                 │ │
│  │                     │  │                               │ │
│  │ - trading_capital   │  │ - trading_capital (动态)       │ │
│  │   = initial_capital │  │ - profit_pool                 │ │
│  │ - round_profits     │  │ - withdrawal_count            │ │
│  │ - capital_history   │  │ - liquidation_count           │ │
│  └─────────────────────┘  │ - capital_history             │ │
│                           └───────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
    ↓
每轮交易:
    _get_trading_capital() → trading_capital
    ↓
    订单金额 = trading_capital * weight
    ↓
    交易盈亏 → _update_capital_after_trade(profit)
    ↓
    capital_pool.process_trade_profit(profit)
    ↓
    记录到 capital_history
    ↓
回测结束
    ↓
get_final_statistics() → 统计数据
    ↓
保存到数据库 (capital_statistics + capital_history)
```

## 封装方法总结

| 类 | 方法 | 功能 | 返回值 |
|------|------|------|--------|
| `CapitalPoolFactory` | `create()` | 创建资金池实例 | `FixedCapitalTracker` 或 `ProgressiveCapitalTracker` |
| `FixedCapitalTracker` | `process_trade_profit()` | 处理交易盈亏（固定模式） | `Dict` |
| `FixedCapitalTracker` | `get_statistics()` | 获取统计数据 | `Dict` |
| `ProgressiveCapitalTracker` | `process_trade_profit()` | 处理交易盈亏（递进模式） | `Dict` |
| `ProgressiveCapitalTracker` | `get_statistics()` | 获取统计数据 | `Dict` |
| `MarketAwareBacktestEngine` | `_get_trading_capital()` | 获取当前交易资金 | `Decimal` |
| `MarketAwareBacktestEngine` | `_update_capital_after_trade()` | 交易后更新资金池 | `Dict` |
| `MarketAwareBacktestEngine` | `get_final_statistics()` | 获取最终统计数据 | `Dict` |

## 需要修改的文件

### autofish_core.py
1. 将 `Autofish_CapitalPool` 重命名为 `ProgressiveCapitalTracker`
2. 新增 `FixedCapitalTracker` 类
3. 新增 `CapitalPoolFactory` 工厂类

### binance_backtest.py
1. 修改 `MarketAwareBacktestEngine.__init__` 使用工厂类
2. 新增 `_get_trading_capital()` 方法
3. 修改 `_create_order()` 使用 `_get_trading_capital()`
4. 新增 `_update_capital_after_trade()` 方法
5. 新增 `get_final_statistics()` 方法
6. 修改 `_save_to_database()` 保存资金统计数据

## 测试验证

### Fix 模式测试
1. 创建 fix 模式测试用例
2. 验证 `_get_trading_capital()` 始终返回 `initial_capital`
3. 验证 round_profits 正确记录
4. 验证 capital_history 正确记录
5. 验证数据库保存正确

### Progressive 模式测试
1. 创建 progressive 模式测试用例
2. 验证初始资金 = total_amount_quote
3. 验证 `_get_trading_capital()` 返回动态变化的资金
4. 验证 `process_trade_profit()` 正确处理盈亏
5. 验证提现触发后资金重置
6. 验证爆仓恢复后资金重置
7. 验证 capital_history 正确记录
8. 验证数据库保存正确

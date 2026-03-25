# 新增复利资金策略计划

## 需求分析

用户需要新增一种资金策略：
1. **一直不提现** - 所有资金始终参与交易
2. **初始资金一直进行交易** - 资金不分割
3. **每一轮交易后，新一轮按最近全量资金按权重再下单** - 复利模式

## 现有资金策略对比

| 策略 | 提现 | 资金变化 | 适用场景 |
|------|------|----------|----------|
| `guding`（固定模式） | 无 | 每轮固定初始资金 | 固定金额测试 |
| `baoshou`（保守） | 有 | 提现后保留 1.5 倍 | 低风险 |
| `wenjian`（稳健） | 有 | 提现后保留 2.0 倍 | 中风险 |
| `jijin`（激进） | 有 | 提现后保留 1.2 倍 | 高风险 |
| **`fuli`（复利）** | **无** | **全量资金复投** | **最大化收益** |

## 实现方案

### 方案一：新增 `CompoundCapitalTracker` 类

创建独立的复利资金追踪器类，与现有类平级。

**优点**：
- 代码独立，不影响现有逻辑
- 易于维护和扩展

**缺点**：
- 代码重复较多

### 方案二：扩展现有 `ProgressiveCapitalTracker` 类（推荐）

在现有类中添加 `fuli` 策略，禁用提现功能。

**优点**：
- 复用现有代码
- 统一管理所有策略

**实现**：
1. 在 `set_strategy` 方法中添加 `fuli` 策略配置
2. 设置 `withdrawal_threshold` 为极大值（如 999），永不触发提现
3. `trading_capital` 随盈亏动态变化

## 详细实现步骤

### 1. 修改 `autofish_core.py`

#### 1.1 在 `set_strategy` 方法中添加 `fuli` 策略

```python
def set_strategy(self, strategy: str, stop_loss: float = 0.08, leverage: int = 10):
    """设置提现策略
    
    Args:
        strategy: 策略名称 (baoshou/wenjian/jijin/fuli/zidingyi)
        stop_loss: 止损比例（默认 0.08 = 8%）
        leverage: 杠杆倍数（默认 10）
    """
    self._strategy = strategy
    auto_liquidation_threshold = 1 - (stop_loss * leverage)
    self.liquidation_threshold = Decimal(str(auto_liquidation_threshold))
    
    if strategy == 'baoshou':
        self.withdrawal_threshold = Decimal('2.0')
        self.withdrawal_retain = Decimal('1.5')
    elif strategy == 'wenjian':
        self.withdrawal_threshold = Decimal('3.0')
        self.withdrawal_retain = Decimal('2.0')
    elif strategy == 'jijin':
        self.withdrawal_threshold = Decimal('1.5')
        self.withdrawal_retain = Decimal('1.2')
    elif strategy == 'fuli':
        # 复利模式：永不提现，全量资金复投
        self.withdrawal_threshold = Decimal('999.0')  # 极大值，永不触发
        self.withdrawal_retain = Decimal('1.0')
    elif strategy == 'zidingyi':
        pass
```

#### 1.2 修改 `get_statistics` 方法

确保 `fuli` 策略返回正确的统计数据：
- `final_capital` = `trading_capital`（无 profit_pool）
- `total_withdrawal` = 0
- `withdrawal_count` = 0

### 2. 修改前端界面

#### 2.1 在策略选择下拉框中添加 `fuli` 选项

文件：`web/test_results/index.html`

```html
<select id="capitalStrategy">
    <option value="baoshou">保守（2倍提现，保留1.5倍）</option>
    <option value="wenjian">稳健（3倍提现，保留2倍）</option>
    <option value="jijin">激进（1.5倍提现，保留1.2倍）</option>
    <option value="fuli">复利（不提现，全量复投）</option>
    <option value="zidingyi">自定义</option>
</select>
```

### 3. 修改测试用例配置

#### 3.1 在测试用例表单中添加 `fuli` 策略选项

文件：`web/test_results/index.html`

### 4. 更新数据库迁移

无需修改数据库结构，现有字段可支持 `fuli` 策略。

## 资金变化示例

假设初始资金 10000，每轮盈利 10%：

| 轮次 | 期初资金 | 盈亏 | 期末资金 | 提现 |
|------|----------|------|----------|------|
| 1 | 10000 | +1000 | 11000 | 无 |
| 2 | 11000 | +1100 | 12100 | 无 |
| 3 | 12100 | +1210 | 13310 | 无 |
| 4 | 13310 | +1331 | 14641 | 无 |

**对比 `jijin` 策略**（1.5倍提现，保留1.2倍）：

| 轮次 | 期初资金 | 盈亏 | 期末资金 | 提现 |
|------|----------|------|----------|------|
| 1 | 10000 | +1000 | 11000 | 触发提现 3000 |
| 2 | 12000 | +1200 | 13200 | 触发提现 1200 |
| ... | ... | ... | ... | ... |

## 风险提示

复利策略虽然收益最大化，但风险也最高：
1. 没有利润锁定机制，回撤时会损失所有盈利
2. 需要设置合理的止损和爆仓阈值
3. 建议配合较低的杠杆使用

## 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `autofish_core.py` | 添加 `fuli` 策略配置 |
| `web/test_results/index.html` | 添加 `fuli` 策略选项 |
| `test_manager.py` | 支持 `fuli` 策略参数 |

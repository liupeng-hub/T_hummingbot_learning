# Web 页面支持创建测试计划功能设计

## 1. 需求分析

在 web 页面上支持：
1. 创建新的测试计划
2. 编辑现有测试计划
3. 删除测试计划

## 2. 数据结构

### 测试计划 JSON 结构
```json
{
  "plan_id": "TP001",
  "plan_name": "BTCUSDT基础回测",
  "description": "BTCUSDT普通回测基准测试",
  "created_at": "2026-03-14T16:00:00",
  "status": "active",
  "test_type": "backtest",
  
  "test_parameters": {
    "symbol": "BTCUSDT",
    "date_range": "20200101-20260310",
    "decay_factor": 0.5,
    "stop_loss": 0.08,
    "total_amount": 10000
  },
  
  "test_scenarios": [
    {
      "scenario_id": "S001",
      "name": "激进策略(d=0.5)",
      "params": {"decay_factor": 0.5}
    }
  ],
  
  "expected_results": {
    "metrics": ["total_trades", "win_rate", "net_profit"],
    "comparison": "S001预期交易次数更多"
  },
  
  "execution": {
    "executor": "binance_backtest.py",
    "command_template": "python binance_backtest.py ...'
  }
}
```

## 3. 实施步骤

### 步骤 1：添加创建测试计划的 API

```python
@app.route('/api/test-plans', methods=['POST'])
def create_test_plan():
    # 创建新测试计划
    # 保存到 out/test_plans/active/{plan_id}_{name}.json
    # 返回创建结果
```

### 步骤 2：添加更新测试计划的 API

```python
@app.route('/api/test-plans/<plan_id>', methods=['PUT'])
def update_test_plan(plan_id):
    # 更新测试计划
    # 保存到文件
```

### 步骤 3：添加删除测试计划的 API

```python
@app.route('/api/test-plans/<plan_id>', methods=['DELETE'])
def delete_test_plan(plan_id):
    # 删除测试计划文件
```

### 步骤 4：前端添加创建测试计划按钮

在测试计划标签页添加"新建测试计划"按钮

### 步骤 5：添加创建/编辑测试计划表单

表单字段：
- 基本信息：plan_id, plan_name, description, test_type
- 测试参数：symbol, date_range, decay_factor, stop_loss, total_amount
- 测试场景：动态添加/删除场景

### 步骤 6：添加删除测试计划 API

```python
@app.route('/api/test-plans/<plan_id>', methods=['DELETE'])
def delete_test_plan(plan_id):
    # 删除测试计划文件
```

## 4. 详细设计

### 4.1 创建测试计划表单

```
基本信息
├─────────────────────────────────────┐
│ 计划ID: [输入框]                       │
│ 计划名称: [输入框]                     │
│ 描述: [文本框]                       │
│ 测试类型: [下拉选择: backtest/market_aware] │
│ 状态: [下拉选择: active/archived]             │
└─────────────────────────────────────┘

测试参数
├─────────────────────────────────────┐
│ 标的: [输入框]                         │
│ 日期范围: [输入框]                     │
│ 衰减因子: [输入框]                     │
│ 止损比例: [输入框]                       │
│ 总金额: [输入框]                       │
└─────────────────────────────────────┘

测试场景
┌─────────────────────────────────────┐
│ [+ 添加场景]                              │
│ 场景1: ID, 名称, 参数                   │
│ 场景2: ID, 名称, 参数                   │
│ ...                                      │
│ [保存] [取消]                             │
└─────────────────────────────────────┘
```

### 4.2 API 设计

**创建测试计划**
```
POST /api/test-plans
Content-Type: application/json

{
  "plan_id": "TP002",
  "plan_name": "新测试计划",
  "description": "描述",
  "test_type": "backtest",
  "test_parameters": {...},
  "test_scenarios": [...]
}
```

**更新测试计划**
```
PUT /api/test-plans/TP002
Content-Type: application/json

{
  "plan_name": "更新后的名称",
  ...
}
```

**删除测试计划**
```
DELETE /api/test-plans/TP002
```

## 5. 验收标准

1. ✅ 页面显示"新建测试计划"按钮
2. ✅ 点击按钮弹出创建表单
3. ✅ 表单支持填写基本信息、测试参数、测试场景
4. ✅ 可以动态添加/删除测试场景
5. ✅ 保存后测试计划出现在列表中
6. ✅ 可以编辑现有测试计划
7. ✅ 可以删除测试计划

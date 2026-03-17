# 页面增加测试计划展示和执行功能

## 1. 需求分析

在 web 页面上增加：
1. 测试计划列表展示
2. 测试计划详情查看
3. 通过页面发起执行测试计划

## 2. 数据结构

### 测试计划 JSON 结构
```json
{
  "plan_id": "TP001",
  "plan_name": "BTCUSDT基础回测",
  "description": "BTCUSDT普通回测基准测试",
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
    {"scenario_id": "S001", "name": "激进策略(d=0.5)", "params": {"decay_factor": 0.5}},
    {"scenario_id": "S002", "name": "保守策略(d=1.0)", "params": {"decay_factor": 1.0}}
  ],
  "execution": {
    "executor": "binance_backtest.py",
    "command_template": "python binance_backtest.py ..."
  }
}
```

## 3. 实施步骤

### 步骤 1：添加执行测试计划的 API

在 `test_manager.py` 中添加：
```python
@app.route('/api/test-plans/<plan_id>/run', methods=['POST'])
def run_test_plan(plan_id):
    # 异步执行测试计划
    # 返回执行状态
```

### 步骤 2：修改前端页面

在 `web/test_results/index.html` 中：
1. 添加"测试计划"标签页
2. 添加测试计划列表表格
3. 添加测试计划详情模态框
4. 添加执行按钮

### 步骤 3：前端 JavaScript 实现

```javascript
// 加载测试计划列表
async function loadTestPlans() { ... }

// 显示测试计划详情
async function showPlanDetail(planId) { ... }

// 执行测试计划
async function runTestPlan(planId) { ... }
```

## 4. 详细设计

### 4.1 测试计划列表表格

| 计划ID | 名称 | 类型 | 状态 | 场景数 | 创建时间 | 操作 |
|--------|------|------|------|--------|----------|------|
| TP001 | BTCUSDT基础回测 | backtest | active | 2 | 2026-03-14 | 详情 执行 |

### 4.2 测试计划详情模态框

- 基本信息：计划ID、名称、描述、类型、状态
- 测试参数：symbol、date_range、decay_factor 等
- 测试场景列表：场景ID、名称、参数
- 执行按钮

### 4.3 执行测试计划 API

**请求**：
```
POST /api/test-plans/<plan_id>/run
Content-Type: application/json

{
  "scenario_id": "S001"  // 可选，不指定则执行所有场景
}
```

**响应**：
```json
{
  "success": true,
  "message": "测试计划执行完成",
  "execution_ids": ["TP001_S001_xxx", "TP001_S002_xxx"]
}
```

## 5. 验收标准

1. ✅ 页面显示测试计划标签页
2. ✅ 测试计划列表正确显示
3. ✅ 点击详情显示测试计划完整信息
4. ✅ 点击执行按钮可以发起执行
5. ✅ 执行完成后显示结果

# capital_statistics 和 capital_history 独立表迁移计划

## 目标
将 `test_results.capital_statistics` JSON 字段迁移到独立的 `capital_statistics` 和 `capital_history` 表。

## 当前状态分析

### 数据库表结构
1. **test_results 表** - 包含 `capital_statistics` TEXT 字段（JSON 格式）
2. **capital_statistics 表** - 已存在，0 条记录
3. **capital_history 表** - 已存在，0 条记录

### 需要修改的代码

#### 1. binance_backtest.py (写入数据)
**位置**: 第 1319-1322 行
```python
# 当前代码
capital=json.dumps(capital),
capital_statistics=json.dumps(capital_stats) if capital_stats else "{}",
```

**修改为**:
```python
capital=json.dumps(capital),
# 不再保存到 test_results.capital_statistics 字段
# 改为调用独立表保存方法
if capital_stats:
    db.save_capital_statistics(result_id, capital_stats)
    if capital_stats.get('capital_history'):
        # 获取 statistics_id
        stats_record = db.get_capital_statistics(result_id)
        if stats_record:
            db.save_capital_history(result_id, stats_record['id'], capital_stats['capital_history'])
```

#### 2. database/test_results_db.py

##### 2.1 TestResult 数据类
**位置**: 第 71 行
```python
# 移除或保留（向后兼容）
capital_statistics: str = "{}"
```

##### 2.2 create_result 方法
**位置**: 第 694-704 行
- 移除 `capital_statistics` 字段的 INSERT

##### 2.3 save_capital_statistics 方法
**位置**: 第 1048-1092 行
- 已存在，需要添加新字段支持：
  - `strategy`
  - `withdrawal_threshold`
  - `withdrawal_retain`
  - `liquidation_threshold`

##### 2.4 save_capital_history 方法
**位置**: 第 1123-1151 行
- 已存在，无需修改

#### 3. test_manager.py (读取数据)

##### 3.1 get_result API
**位置**: 第 1221-1223 行
```python
# 当前代码
capital_stats = db.get_capital_statistics(result_id)
if capital_stats:
    result['capital_statistics'] = capital_stats
```
- 已正确实现，从独立表读取

##### 3.2 get_capital_detail API
**位置**: 第 1237-1253 行
- 已正确实现

#### 4. web/test_results/index.html (前端显示)

##### 4.1 测试结果详情页
**位置**: 第 2058-2082 行
```javascript
${r.capital_statistics ? `
    ...
    ${r.capital_statistics.initial_capital.toFixed(2)}
    ...
`}
```
- 前端已正确处理 `capital_statistics` 对象

##### 4.2 ROI 计算
**位置**: 第 1860 行
```javascript
const capitalReturn = r.capital_statistics ? r.capital_statistics.total_return : r.roi;
```
- 已正确处理

## 实施步骤

### 步骤 1: 更新 save_capital_statistics 方法
添加新字段支持：
- strategy
- withdrawal_threshold
- withdrawal_retain
- liquidation_threshold

### 步骤 2: 修改 binance_backtest.py
- 移除 `capital_statistics` JSON 字段保存
- 调用 `save_capital_statistics` 和 `save_capital_history` 方法

### 步骤 3: 更新 TestResult 数据类
- 移除 `capital_statistics` 字段（或保留默认值用于向后兼容）

### 步骤 4: 更新 create_result 方法
- 移除 `capital_statistics` 字段的 INSERT 语句

### 步骤 5: 数据迁移脚本（可选）
将现有 JSON 数据迁移到独立表

### 步骤 6: 测试验证
- 执行测试用例验证数据正确保存
- 验证 Web 页面正确显示

## 风险评估

### 低风险
- 独立表已存在，结构完整
- 读取逻辑已实现
- 前端已正确处理

### 需要注意
- 现有数据的迁移
- 向后兼容性（旧数据可能仍有 JSON 字段）

## 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `binance_backtest.py` | 修改保存逻辑，调用独立表方法 |
| `database/test_results_db.py` | 更新 `save_capital_statistics` 添加新字段，更新 `create_result` 移除字段 |
| `test_manager.py` | 无需修改（已正确实现） |
| `web/test_results/index.html` | 无需修改（已正确处理） |

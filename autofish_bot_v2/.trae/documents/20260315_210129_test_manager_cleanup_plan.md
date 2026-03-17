# test_manager.py 代码清理计划

## 问题分析

### 1. 冗余的文件系统操作代码

| 方法 | 问题 | 解决方案 |
|------|------|----------|
| `_get_next_plan_id` | 从文件系统获取下一个计划ID | 改为从数据库获取最大ID |
| `_save_plan` | 保存测试计划到JSON文件 | 删除，数据已通过API保存到数据库 |
| `list_plans` | 从文件系统列出测试计划 | 改为从数据库获取 |
| `update_plan_status` | 更新文件状态和移动文件 | 简化为只更新数据库 |
| `create_plan` | 调用 `_save_plan` 保存到文件 | 改为保存到数据库 |

### 2. 目录管理问题

| 问题 | 解决方案 |
|------|----------|
| `_ensure_directories` 检查了 `test_plans/active\|completed\|archived` | 删除这些目录检查，测试计划已存储在数据库 |
| 没有检查 `test_report` 目录 | 添加 `test_report` 目录检查 |

### 3. 数据库不一致问题

| 文件 | 问题 | 解决方案 |
|------|------|----------|
| `market_status_visualizer.py` 使用独立的 `market_visualizer.db` | 迁移到 `test_results.db` | 修改使用 `test_results.db` |

## 实施步骤

### Step 1: 修改 `_ensure_directories` 方法

删除对 `test_plans/active|completed|archived` 目录的检查，添加 `test_report` 目录检查。

### Step 2: 修改 `_get_next_plan_id` 方法

从数据库获取最大计划ID，生成下一个ID。

### Step 3: 删除 `_save_plan` 方法

数据已通过 API 保存到数据库，此方法不再需要。

### Step 4: 修改 `list_plans` 方法

从数据库获取测试计划列表。

### Step 5: 修改 `update_plan_status` 方法

只更新数据库中的状态，不再操作文件。

### Step 6: 修改 `create_plan` 方法

直接保存到数据库，不再调用 `_save_plan`。

### Step 7: 修改 `market_status_visualizer.py`

将 `market_visualizer.db` 改为使用 `test_results.db`。

需要修改的地方：
1. `MarketVisualizerDB.__init__` 中的数据库路径
2. 确保表结构与 `test_results.db` 中已有的 `visualizer_*` 表兼容

## 验证清单

- [ ] 测试计划创建功能正常
- [ ] 测试计划列表获取功能正常
- [ ] 测试计划状态更新功能正常
- [ ] 目录结构正确创建
- [ ] Web API 功能正常
- [ ] 行情可视化功能正常（使用新数据库）

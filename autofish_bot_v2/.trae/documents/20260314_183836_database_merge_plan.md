# 行情可视化数据库融合方案

## 1. 问题分析

### 1.1 当前数据库结构

**market_visualizer.db（行情可视化数据库）**:
| 表名 | 说明 |
|------|------|
| test_cases | 测试用例配置 |
| test_results | 可视化测试结果（与 test_results.db 冲突） |
| daily_statuses | 每日行情状态数据 |

**test_results.db（测试结果数据库）**:
| 表名 | 说明 |
|------|------|
| test_plans | 测试计划 |
| test_scenarios | 测试场景 |
| test_executions | 测试执行记录 |
| test_params | 测试参数 |
| test_results | 回测交易结果（与 market_visualizer.db 冲突） |
| trade_details | 交易明细 |

### 1.2 冲突分析

两个数据库都有 `test_results` 表，但结构完全不同：
- **market_visualizer.db.test_results**: 存储行情状态统计（ranging_days, trending_up_days 等）
- **test_results.db.test_results**: 存储回测交易结果（total_trades, win_rate, net_profit 等）

## 2. 融合方案

### 采用方案A：统一数据库 + 表前缀区分

```
test_results.db
├── test_plans                 # 测试计划（通用）
├── test_scenarios             # 测试场景（通用）
├── test_executions            # 测试执行记录（通用）
├── test_params                # 测试参数（通用）
│
├── backtest_results           # 回测交易结果（原 test_results 重命名）
├── trade_details              # 交易明细
│
├── visualizer_cases           # 可视化测试用例
├── visualizer_results         # 可视化测试结果
└── visualizer_daily_statuses  # 每日行情状态
```

## 3. 详细设计

### 3.1 表结构设计

#### visualizer_cases（可视化测试用例）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PRIMARY KEY | 自增主键 |
| case_id | TEXT UNIQUE | 用例ID (如 VC001) |
| plan_id | TEXT | 关联测试计划ID |
| scenario_id | TEXT | 关联场景ID |
| symbol | TEXT | 交易对 |
| interval | TEXT | K线周期 |
| start_date | TEXT | 开始日期 |
| end_date | TEXT | 结束日期 |
| algorithm | TEXT | 算法名称 |
| algorithm_config | TEXT | 算法配置（JSON） |
| description | TEXT | 描述 |
| status | TEXT | 状态 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

#### visualizer_results（可视化测试结果）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PRIMARY KEY | 自增主键 |
| result_id | TEXT UNIQUE | 结果ID |
| execution_id | TEXT | 关联执行ID |
| case_id | TEXT | 关联用例ID |
| total_days | INTEGER | 总天数 |
| ranging_days | INTEGER | 震荡天数 |
| trending_up_days | INTEGER | 上涨天数 |
| trending_down_days | INTEGER | 下跌天数 |
| ranging_count | INTEGER | 震荡次数 |
| trending_up_count | INTEGER | 上涨次数 |
| trending_down_count | INTEGER | 下跌次数 |
| status_ranges | TEXT | 状态范围（JSON） |
| duration_ms | INTEGER | 执行耗时 |
| created_at | DATETIME | 创建时间 |

#### visualizer_daily_statuses（每日行情状态）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PRIMARY KEY | 自增主键 |
| result_id | TEXT | 关联结果ID |
| date | TEXT | 日期 |
| status | TEXT | 行情状态 |
| confidence | REAL | 置信度 |
| reason | TEXT | 原因 |
| open_price | REAL | 开盘价 |
| close_price | REAL | 收盘价 |
| high_price | REAL | 最高价 |
| low_price | REAL | 最低价 |
| volume | REAL | 成交量 |

## 4. 实施步骤

### 阶段1：修改 test_results.db 表结构
1. 重命名 test_results → backtest_results
2. 创建 visualizer_cases 表
3. 创建 visualizer_results 表
4. 创建 visualizer_daily_statuses 表
5. 创建索引

### 阶段2：更新 test_results_db.py
1. 添加 VisualizerCase, VisualizerResult, VisualizerDailyStatus 数据类
2. 添加 save_visualizer_case 方法
3. 添加 save_visualizer_result 方法
4. 添加 save_visualizer_daily_statuses 方法
5. 添加 query_visualizer_results 方法

### 阶段3：修改行情可视化代码
1. 修改 market_status_visualizer.py 使用新的数据库
2. 添加 --save-to-db 和 --plan-id, --scenario-id 参数
3. 移除旧的 MD/PNG/HTML 文件输出（可选）

### 阶段4：删除旧数据库（可选）
1. 删除 market_visualizer.db（数据已迁移到统一数据库）

## 5. 影响范围

### 需要修改的文件

| 文件 | 修改内容 |
|------|----------|
| database/test_results_db.py | 添加可视化表操作方法 |
| market_status_visualizer.py | 修改数据库连接和表名 |

### 向后兼容

- 新代码使用统一数据库
- 旧行情可视化输出文件不再需要（可选删除）

## 6. 验收标准

1. ✅ test_results.db 包含所有表（backtest_results, visualizer_cases, visualizer_results, visualizer_daily_statuses）
2. ✅ market_status_visualizer.py 正常工作
3. ✅ 回测脚本正常工作
4. ✅ 测试管理器支持可视化测试查询
5. ✅ 可删除旧的 market_visualizer.db 和旧输出文件

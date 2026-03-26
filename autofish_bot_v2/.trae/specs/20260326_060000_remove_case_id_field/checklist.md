# 检查清单

## 数据库表结构变更

- [x] test_cases 表移除 case_id 字段，使用 id 作为主键
- [x] test_cases 表的 name 字段添加 UNIQUE 约束
- [x] test_results 表移除 result_id 字段，使用 id 作为主键
- [x] test_results 表的 case_id 字段类型改为 INTEGER
- [x] test_results 表外键改为 `FOREIGN KEY (case_id) REFERENCES test_cases(id)`
- [x] trade_details 表的 result_id 字段类型改为 INTEGER
- [x] trade_details 表外键改为 `FOREIGN KEY (result_id) REFERENCES test_results(id)`
- [x] capital_history 表的 result_id 字段类型改为 INTEGER
- [x] capital_history 表外键改为 `FOREIGN KEY (result_id) REFERENCES test_results(id) ON DELETE CASCADE`
- [x] capital_statistics 表的 result_id 字段类型改为 INTEGER
- [x] capital_statistics 表外键改为 `FOREIGN KEY (result_id) REFERENCES test_results(id) ON DELETE CASCADE`
- [x] market_visualizer_cases 表移除 case_id 字段，使用 id 作为主键
- [x] market_visualizer_cases 表的 name 字段添加 UNIQUE 约束
- [x] market_visualizer_results 表移除 result_id 字段，使用 id 作为主键
- [x] market_visualizer_results 表的 case_id 字段类型改为 INTEGER
- [x] market_visualizer_results 表外键改为 `FOREIGN KEY (case_id) REFERENCES market_visualizer_cases(id)`
- [x] market_visualizer_details 表的 result_id 字段类型改为 INTEGER
- [x] market_visualizer_details 表外键改为 `FOREIGN KEY (result_id) REFERENCES market_visualizer_results(id)`

## 数据类定义

- [x] TestCase 数据类移除 case_id 字段
- [x] TestCase 数据类添加 id: int 字段
- [x] TestResult 数据类移除 result_id 字段
- [x] TestResult 数据类添加 id: int 字段
- [x] TestResult 数据类的 case_id 类型改为 int
- [x] TradeDetail 数据类的 result_id 类型改为 int
- [x] MarketVisualizerCase 数据类移除 case_id 字段
- [x] MarketVisualizerCase 数据类添加 id: int 字段
- [x] MarketVisualizerResult 数据类移除 result_id 字段
- [x] MarketVisualizerResult 数据类添加 id: int 字段
- [x] MarketVisualizerResult 数据类的 case_id 类型改为 int
- [x] MarketVisualizerDetail 数据类的 result_id 类型改为 int

## 数据库操作方法

- [x] create_case 方法移除 case_id 生成逻辑
- [x] get_case 方法使用 id (INTEGER) 查询
- [x] update_case 方法使用 id (INTEGER) 作为参数
- [x] delete_case 方法使用 id (INTEGER) 作为参数
- [x] create_result 方法移除 result_id 生成逻辑
- [x] create_result 方法的 case_id 改为 INTEGER 类型
- [x] get_result 方法使用 id (INTEGER) 查询
- [x] save_trade_details 方法的 result_id 改为 INTEGER 类型
- [x] save_capital_statistics 方法的 result_id 改为 INTEGER 类型

## 接口 (test_manager.py)

- [x] create_case 接口移除 case_id 生成，返回自增 id
- [x] get_case 接口使用 id (INTEGER) 作为参数
- [x] update_case 接口使用 id (INTEGER) 作为参数
- [x] delete_case 接口使用 id (INTEGER) 作为参数
- [x] copy_case 接口使用 id (INTEGER) 作为参数
- [x] reset_case 接口使用 id (INTEGER) 作为参数
- [x] run_case 接口使用 id (INTEGER) 作为参数
- [x] 结果相关接口使用 id (INTEGER) 作为参数

## Web 前端 (index.html)

- [x] 用例列表的"用例 ID"列显示 test_cases.id (INTEGER)
- [x] 用例列表的操作按钮使用 id 作为参数
- [x] 测试结果列表的"结果 ID"列显示 test_results.id (INTEGER)
- [x] 测试结果列表的操作按钮使用 id 作为参数
- [x] JavaScript 函数中所有 case_id 改为 id
- [x] JavaScript 函数中所有 result_id 改为 id
- [x] 行情可视化用例列表的"用例 ID"列显示 market_visualizer_cases.id (INTEGER)
- [x] 行情可视化用例列表的操作按钮使用 id 作为参数
- [x] 行情可视化结果列表的"结果 ID"列显示 market_visualizer_results.id (INTEGER)
- [x] 行情可视化结果列表的操作按钮使用 id 作为参数

## 回测逻辑 (binance_backtest.py)

- [x] 测试结果保存逻辑的 case_id 改为 INTEGER 类型
- [x] 适配新的数据库接口

## 数据迁移

- [x] 创建数据迁移脚本
- [x] 备份现有数据
- [x] 迁移数据到新表结构
- [x] 验证数据完整性

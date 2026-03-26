# 任务列表

## 任务一：数据库表结构变更

### 子任务 1.1：修改 test_cases 表
- [x] 移除 case_id 字段
- [x] 确认 id (INTEGER PRIMARY KEY AUTOINCREMENT) 作为主键
- [x] name 字段添加 UNIQUE 约束

### 子任务 1.2：修改 test_results 表
- [x] 移除 result_id 字段
- [x] 将 case_id 字段类型改为 INTEGER
- [x] 修改外键为 `FOREIGN KEY (case_id) REFERENCES test_cases(id)`
- [x] 确认 id (INTEGER PRIMARY KEY AUTOINCREMENT) 作为主键

### 子任务 1.3：修改 trade_details 表
- [x] 将 result_id 字段类型改为 INTEGER
- [x] 修改外键为 `FOREIGN KEY (result_id) REFERENCES test_results(id)`

### 子任务 1.4：修改 capital_history 表
- [x] 将 result_id 字段类型改为 INTEGER
- [x] 修改外键为 `FOREIGN KEY (result_id) REFERENCES test_results(id) ON DELETE CASCADE`

### 子任务 1.5：修改 capital_statistics 表
- [x] 将 result_id 字段类型改为 INTEGER
- [x] 修改外键为 `FOREIGN KEY (result_id) REFERENCES test_results(id) ON DELETE CASCADE`

### 子任务 1.6：修改 market_visualizer_cases 表
- [x] 移除 case_id 字段
- [x] 确认 id (INTEGER PRIMARY KEY AUTOINCREMENT) 作为主键
- [x] name 字段添加 UNIQUE 约束

### 子任务 1.7：修改 market_visualizer_results 表
- [x] 移除 result_id 字段
- [x] 将 case_id 字段类型改为 INTEGER
- [x] 修改外键为 `FOREIGN KEY (case_id) REFERENCES market_visualizer_cases(id)`
- [x] 确认 id (INTEGER PRIMARY KEY AUTOINCREMENT) 作为主键

### 子任务 1.8：修改 market_visualizer_details 表
- [x] 将 result_id 字段类型改为 INTEGER
- [x] 修改外键为 `FOREIGN KEY (result_id) REFERENCES market_visualizer_results(id)`

## 任务二：数据类定义更新

### 子任务 2.1：更新 TestCase 数据类
- [x] 移除 case_id 字段
- [x] 添加 id: int = 0 (默认值，由数据库生成)

### 子任务 2.2：更新 TestResult 数据类
- [x] 移除 result_id 字段
- [x] 添加 id: int = 0 (默认值，由数据库生成)
- [x] 将 case_id 类型改为 int

### 子任务 2.3：更新 TradeDetail 数据类
- [x] 将 result_id 类型改为 int

### 子任务 2.4：更新 MarketVisualizerCase 数据类
- [x] 移除 case_id 字段
- [x] 添加 id: int = 0 (默认值，由数据库生成)

### 子任务 2.5：更新 MarketVisualizerResult 数据类
- [x] 移除 result_id 字段
- [x] 添加 id: int = 0 (默认值，由数据库生成)
- [x] 将 case_id 类型改为 int

### 子任务 2.6：更新 MarketVisualizerDetail 数据类
- [x] 将 result_id 类型改为 int

## 任务三：数据库操作方法更新

### 子任务 3.1：更新 create_case 方法
- [x] 移除 case_id 生成逻辑
- [x] 使用数据库返回的自增 id

### 子任务 3.2：更新 get_case 方法
- [x] 使用 id (INTEGER) 查询

### 子任务 3.3：更新 update_case 方法
- [x] 使用 id (INTEGER) 作为参数

### 子任务 3.4：更新 delete_case 方法
- [x] 使用 id (INTEGER) 作为参数
- [x] 更新关联删除逻辑

### 子任务 3.5：更新 create_result 方法
- [x] 移除 result_id 生成逻辑
- [x] case_id 改为 INTEGER 类型

### 子任务 3.6：更新 get_result 方法
- [x] 使用 id (INTEGER) 查询

### 子任务 3.7：更新 save_trade_details 方法
- [x] result_id 改为 INTEGER 类型

### 子任务 3.8：更新 save_capital_statistics 方法
- [x] result_id 改为 INTEGER 类型

## 任务四：接口更新 (test_manager.py)

### 子任务 4.1：更新 create_case 接口
- [x] 移除 case_id 生成
- [x] 返回自增 id

### 子任务 4.2：更新 get_case 接口
- [x] 使用 id (INTEGER) 作为参数

### 子任务 4.3：更新 update_case 接口
- [x] 使用 id (INTEGER) 作为参数

### 子任务 4.4：更新 delete_case 接口
- [x] 使用 id (INTEGER) 作为参数

### 子任务 4.5：更新 copy_case 接口
- [x] 使用 id (INTEGER) 作为参数
- [x] 复制逻辑适配

### 子任务 4.6：更新 reset_case 接口
- [x] 使用 id (INTEGER) 作为参数

### 子任务 4.7：更新 run_case 接口
- [x] 使用 id (INTEGER) 作为参数

### 子任务 4.8：更新结果相关接口
- [x] 使用 id (INTEGER) 作为参数

## 任务五：Web 前端更新 (index.html)

### 子任务 5.1：更新用例列表展示
- [x] "用例 ID" 列显示 test_cases.id (INTEGER)
- [x] 操作按钮使用 id 作为参数

### 子任务 5.2：更新测试结果列表展示
- [x] "结果 ID" 列显示 test_results.id (INTEGER)
- [x] 操作按钮使用 id 作为参数

### 子任务 5.3：更新 JavaScript 函数
- [x] 所有使用 case_id 的地方改为使用 id
- [x] 所有使用 result_id 的地方改为使用 id

## 任务六：回测逻辑更新 (binance_backtest.py)

### 子任务 6.1：更新测试结果保存逻辑
- [x] case_id 改为 INTEGER 类型
- [x] 适配新的数据库接口

## 任务七：行情可视化逻辑更新 (market_status_visualizer.py)

### 子任务 7.1：更新行情可视化用例创建逻辑
- [x] 移除 case_id 生成
- [x] 使用数据库自增 id

### 子任务 7.2：更新行情可视化结果保存逻辑
- [x] case_id 改为 INTEGER 类型
- [x] 移除 result_id 生成

### 子任务 7.3：更新行情可视化详情保存逻辑
- [x] result_id 改为 INTEGER 类型

## 任务八：Web 前端行情可视化适配

### 子任务 8.1：更新行情可视化用例列表展示
- [x] "用例 ID" 列显示 market_visualizer_cases.id (INTEGER)
- [x] 操作按钮使用 id 作为参数

### 子任务 8.2：更新行情可视化结果列表展示
- [x] "结果 ID" 列显示 market_visualizer_results.id (INTEGER)
- [x] 操作按钮使用 id 作为参数

### 子任务 8.3：更新行情可视化相关 JavaScript 函数
- [x] 所有使用 case_id 的地方改为使用 id
- [x] 所有使用 result_id 的地方改为使用 id

## 任务九：数据迁移

### 子任务 9.1：创建数据迁移脚本
- [x] 备份现有数据
- [x] 创建新表结构
- [x] 迁移数据
- [x] 删除旧表

# 任务依赖关系

- 任务二 依赖于 任务一
- 任务三 依赖于 任务二
- 任务四 依赖于 任务三
- 任务五 依赖于 任务四
- 任务六 依赖于 任务三
- 任务七 依赖于 任务三
- 任务八 依赖于 任务四
- 任务九 依赖于 任务一

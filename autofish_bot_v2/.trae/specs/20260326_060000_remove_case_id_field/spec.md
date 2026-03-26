# 移除 case_id 字段，使用自增 ID 作为主键 规格说明

## 背景说明
当前数据库表使用 case_id (UUID) 和 result_id (UUID) 作为主键和外键，这增加了数据管理的复杂性。为了简化数据库结构，统一使用自增 ID (INTEGER PRIMARY KEY AUTOINCREMENT) 作为主键，移除 case_id 和 result_id 字段。

## 变更内容
- **破坏性变更**: 移除 test_cases 表的 case_id 字段，使用 id 作为主键
- **破坏性变更**: 修改 test_results 表的外键引用，从 case_id 改为 test_cases.id
- **破坏性变更**: 修改 trade_details 表的外键引用，从 result_id 改为 test_results.id
- **破坏性变更**: 修改 capital_history 表的外键引用，从 result_id 改为 test_results.id
- **破坏性变更**: 修改 capital_statistics 表的外键引用，从 result_id 改为 test_results.id
- **破坏性变更**: 移除 market_visualizer_cases 表的 case_id 字段，使用 id 作为主键
- **破坏性变更**: 移除 market_visualizer_results 表的 result_id 字段，使用 id 作为主键
- **破坏性变更**: 修改 market_visualizer_results 表的外键引用，从 case_id 改为 market_visualizer_cases.id
- **破坏性变更**: 修改 market_visualizer_details 表的外键引用，从 result_id 改为 market_visualizer_results.id
- 更新所有业务逻辑中字段的填充和读取逻辑
- Web 展示中使用 test_cases.id 和 test_results.id
- Web 展示中使用 market_visualizer_cases.id 和 market_visualizer_results.id

## 影响范围
- 影响功能: 测试用例管理、测试结果查询、资金统计、行情可视化
- 影响代码: 
  - `database/test_results_db.py` (数据库表结构、增删改查方法)
  - `test_manager.py` (接口)
  - `web/test_results/index.html` (前端展示)
  - `binance_backtest.py` (测试结果保存)
  - `market_status_visualizer.py` (行情可视化逻辑)

## 新增需求

### 需求: 数据库表结构变更

#### 场景: test_cases 表变更
- **前提** 当前 test_cases 表有 case_id 字段
- **当** 执行数据库迁移
- **那么** 移除 case_id 字段，使用 id (INTEGER PRIMARY KEY AUTOINCREMENT) 作为主键
- **并且** name 字段添加 UNIQUE 约束避免重复

#### 场景: test_results 表外键变更
- **前提** 当前 test_results 表使用 case_id 作为外键
- **当** 执行数据库迁移
- **那么** 外键改为 `FOREIGN KEY (case_id) REFERENCES test_cases(id)`
- **并且** case_id 字段类型改为 INTEGER

#### 场景: trade_details 表外键变更
- **前提** 当前 trade_details 表使用 result_id 作为外键
- **当** 执行数据库迁移
- **那么** 外键改为 `FOREIGN KEY (result_id) REFERENCES test_results(id)`
- **并且** result_id 字段类型改为 INTEGER

#### 场景: capital_history 表外键变更
- **前提** 当前 capital_history 表使用 result_id 作为外键
- **当** 执行数据库迁移
- **那么** 外键改为 `FOREIGN KEY (result_id) REFERENCES test_results(id) ON DELETE CASCADE`
- **并且** result_id 字段类型改为 INTEGER

#### 场景: capital_statistics 表外键变更
- **前提** 当前 capital_statistics 表使用 result_id 作为外键
- **当** 执行数据库迁移
- **那么** 外键改为 `FOREIGN KEY (result_id) REFERENCES test_results(id) ON DELETE CASCADE`
- **并且** result_id 字段类型改为 INTEGER

#### 场景: market_visualizer_cases 表变更
- **前提** 当前 market_visualizer_cases 表有 case_id 字段
- **当** 执行数据库迁移
- **那么** 移除 case_id 字段，使用 id (INTEGER PRIMARY KEY AUTOINCREMENT) 作为主键
- **并且** name 字段添加 UNIQUE 约束避免重复

#### 场景: market_visualizer_results 表变更
- **前提** 当前 market_visualizer_results 表有 result_id 和 case_id 字段
- **当** 执行数据库迁移
- **那么** 移除 result_id 字段，使用 id (INTEGER PRIMARY KEY AUTOINCREMENT) 作为主键
- **并且** 将 case_id 字段类型改为 INTEGER
- **并且** 外键改为 `FOREIGN KEY (case_id) REFERENCES market_visualizer_cases(id)`

#### 场景: market_visualizer_details 表外键变更
- **前提** 当前 market_visualizer_details 表使用 result_id 作为外键
- **当** 执行数据库迁移
- **那么** 将 result_id 字段类型改为 INTEGER
- **并且** 外键改为 `FOREIGN KEY (result_id) REFERENCES market_visualizer_results(id)`

### 需求: 业务逻辑适配

#### 场景: 创建测试用例
- **当** 创建新的测试用例
- **那么** 不再生成 case_id (UUID)
- **并且** 使用数据库自增的 id 作为主键

#### 场景: 查询测试用例
- **当** 查询测试用例
- **那么** 使用 id (INTEGER) 而不是 case_id (STRING) 作为标识

#### 场景: 创建测试结果
- **当** 创建测试结果
- **那么** case_id 字段存储为 INTEGER (test_cases.id)
- **并且** 不再生成 result_id (UUID)
- **并且** 使用数据库自增的 id 作为主键

#### 场景: 查询测试结果
- **当** 查询测试结果
- **那么** 使用 id (INTEGER) 而不是 result_id (STRING) 作为标识
- **并且** 关联查询时使用 INTEGER 类型的 case_id

### 需求: Web 展示适配

#### 场景: 用例列表展示
- **当** 展示用例列表
- **那么** "用例 ID" 列显示 test_cases.id (INTEGER)
- **并且** 点击操作使用 id 作为参数

#### 场景: 测试结果列表展示
- **当** 展示测试结果列表
- **那么** "结果 ID" 列显示 test_results.id (INTEGER)
- **并且** 点击操作使用 id 作为参数

#### 场景: 行情可视化用例列表展示
- **当** 展示行情可视化用例列表
- **那么** "用例 ID" 列显示 market_visualizer_cases.id (INTEGER)
- **并且** 点击操作使用 id 作为参数

#### 场景: 行情可视化结果列表展示
- **当** 展示行情可视化结果列表
- **那么** "结果 ID" 列显示 market_visualizer_results.id (INTEGER)
- **并且** 点击操作使用 id 作为参数

## 修改的需求

### 需求: TestCase 数据类
- **原定义**: case_id: str
- **新定义**: 移除 case_id 字段，使用 id: int (由数据库生成)

### 需求: TestResult 数据类
- **原定义**: result_id: str, case_id: str
- **新定义**: 移除 result_id 字段，使用 id: int (由数据库生成)，case_id: int

### 需求: TradeDetail 数据类
- **原定义**: result_id: str
- **新定义**: result_id: int

### 需求: MarketVisualizerCase 数据类
- **原定义**: case_id: str
- **新定义**: 移除 case_id 字段，使用 id: int (由数据库生成)

### 需求: MarketVisualizerResult 数据类
- **原定义**: result_id: str, case_id: str
- **新定义**: 移除 result_id 字段，使用 id: int (由数据库生成)，case_id: int

### 需求: MarketVisualizerDetail 数据类
- **原定义**: result_id: str
- **新定义**: result_id: int

## 移除的需求

### 需求: UUID 生成
**原因**: 统一使用自增 ID，不再需要 UUID
**迁移方案**: 删除所有 uuid 导入和 uuid.uuid4() 调用

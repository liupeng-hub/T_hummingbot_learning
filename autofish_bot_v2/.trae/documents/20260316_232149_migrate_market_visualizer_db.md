# 迁移 market_visualizer.db 数据表到 test_results.db 计划

## 背景

`market_status_visualizer.py` 使用独立的 `market_visualizer.db` 数据库，包含 3 个表：
- `test_cases` - 测试用例表
- `test_results` - 测试结果表
- `daily_statuses` - 每日状态表

需要将这些表迁移到 `test_results.db` 中，并重命名表名。

## 表名映射

| 原表名 (market_visualizer.db) | 新表名 (test_results.db) |
|------------------------------|-------------------------|
| test_cases | market_visualizer_cases |
| test_results | market_visualizer_results |
| daily_statuses | market_visualizer_details |

## 实施步骤

### 步骤 1: 更新 database/test_results_db.py

1. **添加新的 dataclass 定义**：
   - `MarketVisualizerCase` - 行情可视化用例
   - `MarketVisualizerResult` - 行情可视化结果
   - `MarketVisualizerDetail` - 行情可视化详情

2. **创建新表 SQL**（在 `_ensure_tables` 方法中）：
   - `market_visualizer_cases` 表
   - `market_visualizer_results` 表
   - `market_visualizer_details` 表

3. **创建索引**

4. **添加 CRUD 方法**：
   - `create_visualizer_case()` - 创建可视化用例
   - `get_visualizer_case()` - 获取单个用例
   - `list_visualizer_cases()` - 列出用例
   - `update_visualizer_case_status()` - 更新用例状态
   - `delete_visualizer_case()` - 删除用例
   - `create_visualizer_result()` - 创建可视化结果
   - `get_visualizer_result()` - 获取单个结果
   - `get_visualizer_result_by_case()` - 根据用例ID获取结果
   - `create_visualizer_details()` - 批量创建详情
   - `get_visualizer_details()` - 获取详情列表
   - `get_visualizer_statistics()` - 获取统计信息
   - `count_visualizer_cases()` - 统计用例数量

5. **删除旧的 visualizer_* 表**（如果存在）

### 步骤 2: 更新 database/__init__.py

添加新的 dataclass 导出：
- `MarketVisualizerCase`
- `MarketVisualizerResult`
- `MarketVisualizerDetail`

### 步骤 3: 更新 market_status_visualizer.py

1. **删除 `MarketVisualizerDB` 类**（第 144-609 行）

2. **删除相关 dataclass**（第 94-141 行）：
   - `TestCase`
   - `TestResult`
   - `DailyStatusDB`

3. **修改导入**：
   - 从 `database.test_results_db` 导入新的 dataclass 和 `TestResultsDB`

4. **修改 `MarketStatusVisualizer` 类**：
   - 将 `self.db = MarketVisualizerDB()` 改为 `self.db = TestResultsDB()`
   - 调整所有数据库方法调用以匹配新的方法名

5. **修改 `VisualizerServer` 类**：
   - 同样使用 `TestResultsDB` 替代 `MarketVisualizerDB`
   - 调整 API 方法中的数据库调用

### 步骤 4: 数据迁移（可选）

如果 `market_visualizer.db` 中有需要保留的数据，编写迁移脚本将数据迁移到新表。

### 步骤 5: 验证

1. 运行 Python 导入测试
2. 启动服务验证功能正常

## 新表结构定义

### market_visualizer_cases 表

```sql
CREATE TABLE IF NOT EXISTS market_visualizer_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL DEFAULT '1d',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    algorithm_config TEXT DEFAULT '{}',
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

### market_visualizer_results 表

```sql
CREATE TABLE IF NOT EXISTS market_visualizer_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id TEXT UNIQUE NOT NULL,
    case_id TEXT NOT NULL,
    total_days INTEGER DEFAULT 0,
    ranging_days INTEGER DEFAULT 0,
    trending_up_days INTEGER DEFAULT 0,
    trending_down_days INTEGER DEFAULT 0,
    ranging_count INTEGER DEFAULT 0,
    trending_up_count INTEGER DEFAULT 0,
    trending_down_count INTEGER DEFAULT 0,
    status_ranges TEXT DEFAULT '[]',
    duration_ms INTEGER DEFAULT 0,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES market_visualizer_cases(case_id)
)
```

### market_visualizer_details 表

```sql
CREATE TABLE IF NOT EXISTS market_visualizer_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id TEXT NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL DEFAULT 0,
    reason TEXT DEFAULT '',
    open_price REAL DEFAULT 0,
    close_price REAL DEFAULT 0,
    high_price REAL DEFAULT 0,
    low_price REAL DEFAULT 0,
    volume REAL DEFAULT 0,
    FOREIGN KEY (result_id) REFERENCES market_visualizer_results(result_id)
)
```

## 影响范围

- `database/test_results_db.py` - 添加新表和方法
- `database/__init__.py` - 添加新导出
- `market_status_visualizer.py` - 删除 MarketVisualizerDB，使用 TestResultsDB

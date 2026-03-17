# 计划：从 test_results.db 移除行情存储

## 背景

用户要求从 `test_results.db` 中移除对行情数据的存储，API 接口暂时不返回行情数据。

## 影响范围

### 1. database/test_results_db.py
- `MarketStatus` 数据类 (第 72-87 行)
- `market_statuses` 表创建 (第 186-205 行)
- 索引 `idx_market_result` 和 `idx_market_date` (第 233-234 行)
- `save_market_statuses` 方法 (第 606-629 行)
- `get_market_statuses` 方法 (第 631-640 行)
- `reset_case` 方法中删除 market_statuses 的代码 (第 454 行)
- `delete_case` 方法中删除 market_statuses 的代码 (第 423 行)

### 2. test_manager.py
- `/api/results/<result_id>/market-statuses` API 端点 (第 2078-2089 行)
- `/api/results/<result_id>/chart` API 中返回 market_statuses 的代码 (第 2098, 2101-2103, 2108 行)

### 3. web/test_results/index.html
- 行情状态显示复选框 (第 607-608 行)
- `renderKlineChart` 函数中处理 market_statuses 的代码 (第 1265, 1276-1308 行)

## 实施步骤

### 步骤 1: 更新 database/test_results_db.py
1. 删除 `MarketStatus` 数据类定义
2. 删除 `market_statuses` 表创建 SQL
3. 删除相关索引创建
4. 删除 `save_market_statuses` 方法
5. 删除 `get_market_statuses` 方法
6. 更新 `reset_case` 方法，移除删除 market_statuses 的代码
7. 更新 `delete_case` 方法，移除删除 market_statuses 的代码

### 步骤 2: 更新 test_manager.py
1. 删除 `/api/results/<result_id>/market-statuses` API 端点
2. 更新 `/api/results/<result_id>/chart` API，不返回 market_statuses 数据

### 步骤 3: 更新 web/test_results/index.html
1. 删除"显示行情状态"复选框
2. 更新 `renderKlineChart` 函数，移除处理 market_statuses 的代码
3. 更新 `currentChartData` 变量，不再期望 market_statuses 字段

## 注意事项
- 保留 `test_results` 表中的 `market_algorithm` 和 `trading_statuses` 字段（这些是测试配置，不是行情数据）
- 数据库中现有的 `market_statuses` 表数据可以保留，只是不再使用
- Web 页面的 K 线图仍然可以显示交易标注

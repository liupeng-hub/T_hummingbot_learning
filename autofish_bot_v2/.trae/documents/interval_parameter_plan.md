# Interval 参数全流程补充计划

## 问题分析

用户指出：
1. `binance_backtest.py` 中 interval 硬编码为 "1m"，需要改为外部传入
2. 测试用例的数据库表需要添加 interval 字段
3. 打通 web-回测程序-db 的全流程 interval 补充

## 当前状态

### 已完成的部分
1. ✅ 数据库 `test_cases` 表已添加 `interval` 字段（默认值 '1m'）
2. ✅ `database/test_results_db.py` 已支持 interval 字段的保存和更新
3. ✅ `test_manager.py` 的 `get_case` API 已返回 interval 字段
4. ✅ `test_manager.py` 的 `get_chart_data` API 已使用 case 的 interval
5. ✅ 前端表单已添加 interval 选择器

### 待完成的部分
1. ❌ `binance_backtest.py` 中 interval 硬编码为 "1m"，需要改为从外部传入
2. ❌ `test_manager.py` 的 `run_case` API 需要传递 interval 参数给回测程序
3. ❌ CLI 的 `run-case` 命令需要传递 interval 参数

## 实施步骤

### 1. 修改 `binance_backtest.py`
- 添加 `--interval` 命令行参数
- 将硬编码的 `interval="1m"` 改为使用参数值

### 2. 修改 `test_manager.py` 的 `run_case` API
- 从 case 中读取 interval 字段
- 构建命令时添加 `--interval` 参数

### 3. 修改 CLI 的 `run-case` 命令
- 从 case 中读取 interval 字段
- 构建命令时添加 `--interval` 参数

## 涉及文件
1. `binance_backtest.py` - 添加 --interval 参数
2. `test_manager.py` - run_case API 和 CLI run-case 命令

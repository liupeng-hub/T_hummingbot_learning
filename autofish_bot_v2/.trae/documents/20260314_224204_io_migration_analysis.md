# 功能组件输入输出迁移分析

## 1. 组件关系分析

### 1.1 组件依赖关系

```
market_status_detector.py (基础库)
        ↓ 被调用
market_status_visualizer.py (上层应用)
        ↓ 被调用
market_aware_backtest.py (回测应用)
```

**设计原则**：
- 基础库只提供功能，不负责数据持久化
- 上层应用负责调用基础库并保存结果
- 避免重复保存

### 1.2 各组件职责

| 组件 | 职责 | 是否保存数据 |
|------|------|-------------|
| `market_status_detector.py` | 行情检测算法库 | ❌ 不保存（基础库） |
| `market_status_visualizer.py` | 行情可视化 + 数据保存 | ✅ 保存到 visualizer_* 表 |
| `binance_backtest.py` | 普通回测 + 数据保存 | ✅ 保存到 test_results 表 |
| `market_aware_backtest.py` | 行情感知回测 + 数据保存 | ✅ 保存到 test_results 表 |
| `longport_backtest.py` | 港股回测 + 数据保存 | ✅ 待实现 |

## 2. 当前状态分析

### 2.1 binance_backtest.py（普通回测）

| 功能 | 输入 | 输出 | 数据库迁移状态 |
|------|------|------|---------------|
| `_save_to_database()` | 回测结果 | test_results 表 | ✅ 完成 |
| `save_report()` | 回测结果 | MD 文件 | ⚠️ 与数据库重复 |

**改进方案**：
- 删除 `save_report()` 方法
- MD 报告通过 `test_manager.py export-md` 从数据库导出

### 2.2 market_aware_backtest.py（行情感知回测）

| 功能 | 输入 | 输出 | 数据库迁移状态 |
|------|------|------|---------------|
| `_save_to_database()` | 回测结果 | test_results 表 | ✅ 完成 |
| `save_report()` | 回测结果 | MD 文件 | ⚠️ 与数据库重复 |

**改进方案**：
- 同上

### 2.3 market_status_visualizer.py（行情可视化）

| 功能 | 输入 | 输出 | 数据库迁移状态 |
|------|------|------|---------------|
| 测试用例 | 配置参数 | visualizer_cases 表 | ✅ 完成 |
| 测试结果 | 统计数据 | visualizer_results 表 | ✅ 完成 |
| 每日状态 | 状态数据 | visualizer_daily_statuses 表 | ✅ 完成 |

**改进方案**：
- 删除 MD/PNG/HTML 文件输出
- 通过 `test_manager.py export-md` 从数据库导出

### 2.4 market_status_detector.py（行情检测器）

| 功能 | 输入 | 输出 | 数据库迁移状态 |
|------|------|------|---------------|
| `save_report()` | 行情分析结果 | MD 文件 | ❌ 不需要迁移 |

**设计决策**：
- **不迁移到数据库**
- 作为基础库，只提供检测功能
- 由上层应用（visualizer）负责保存数据

### 2.5 longport_backtest.py（港股回测）

| 功能 | 输入 | 输出 | 数据库迁移状态 |
|------|------|------|---------------|
| `save_report()` | 回测结果 | MD 文件 | ❌ 待迁移 |

**改进方案**：
- 添加 `_save_to_database()` 方法
- 复用 `test_results` 表结构

## 3. 实施计划

### 阶段 1：完善报告导出功能

**目标**：支持从数据库导出 MD/CSV 报告

1. 完善 `test_results_db.py` 中的 `generate_report()` 方法
   - 生成完整的 MD 报告
   - 包含交易明细表格
   - 包含统计数据

2. 在 `test_manager.py` 中添加导出命令
   - `python test_manager.py export <execution_id> --format md`
   - `python test_manager.py export <execution_id> --format csv`

### 阶段 2：删除冗余的文件输出

**目标**：统一使用数据库，按需导出文件

1. 修改 `binance_backtest.py`
   - 删除 `save_report()` 方法
   - 删除 `--export-md` 参数

2. 修改 `market_aware_backtest.py`
   - 删除 `save_report()` 方法
   - 删除 `--export-md` 参数

3. 修改 `market_status_visualizer.py`
   - 删除 MD/PNG/HTML 文件输出
   - 只保留数据库保存

4. 修改 `market_status_detector.py`
   - 删除 `save_report()` 方法
   - 保持纯算法库职责

### 阶段 3：完善港股回测

**目标**：港股回测集成到统一数据库

1. 修改 `longport_backtest.py`
   - 添加 `_save_to_database()` 方法
   - 复用 `test_results` 表结构
   - 删除 `save_report()` 方法

## 4. 最终数据流

```
用户执行回测
    ↓
回测引擎运行
    ↓
结果保存到数据库 (自动)
    ↓
用户需要报告时
    ↓
从数据库导出 MD/CSV (按需)
```

## 5. 验收标准

1. ✅ 所有回测结果自动保存到数据库
2. ✅ 支持从数据库导出 MD 报告
3. ✅ 支持从数据库导出 CSV 交易明细
4. ✅ 删除冗余的 `save_report()` 方法
5. ✅ `market_status_detector.py` 保持纯算法库职责
6. ✅ 港股回测集成到统一数据库

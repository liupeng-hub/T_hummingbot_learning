# 输出目录重组计划

## 背景

当前输出目录结构混乱，`autofish_output` 混合了多种类型的输出文件。需要重新组织目录结构，使输出更加清晰。

## 新目录结构

```
autofish_bot_v2/
├── out/                       # 输出目录 (统一管理)
│   ├── autofish/              # 基础振幅分析和普通回测输出
│   │   ├── {source}_{symbol}_amplitude_config.json
│   │   ├── {source}_{symbol}_amplitude_report.md
│   │   ├── {source}_{symbol}_backtest_report.md
│   │   └── {source}_{symbol}_backtest_history.md
│   │
│   ├── market_backtest/       # 行情感知回测输出
│   │   ├── {source}_{symbol}_market_aware_backtest_{days}d_{date_range}.md
│   │   ├── {source}_{symbol}_market_aware_history.md
│   │   ├── {source}_{symbol}_market_report_{interval}_{days}d.md
│   │   └── {source}_{symbol}_market_history.md
│   │
│   ├── market_visualizer/     # 市场行情可视化输出
│   │   ├── market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.md
│   │   ├── market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.png
│   │   └── market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.html
│   │
│   └── market_optimization/   # 市场行情优化输出
│       ├── optuna_dual_thrust_results.csv
│       ├── optuna_dual_thrust_report.md
│       ├── optuna_improved_results.csv
│       └── optuna_improved_report.md
│
└── database/                  # 数据库文件
    ├── klines.db              # K线缓存数据库 (从 kline_cache/ 迁移)
    └── market_visualizer.db   # 可视化数据库 (从 market_visualizer_out/ 迁移)
```

## 需要修改的代码文件

### 1. autofish_core.py
- `autofish_output` → `out/autofish`
- 影响行: 950, 1593, 1713

### 2. binance_backtest.py
- `autofish_output` → `out/autofish`
- 影响行: 596, 737

### 3. longport_backtest.py
- `autofish_output` → `out/autofish`
- 影响行: 442

### 4. market_status_detector.py
- `autofish_output` → `out/market_backtest`
- 影响行: 1571, 1627

### 5. market_aware_backtest.py
- `autofish_output` → `out/market_backtest`
- 影响行: 602, 709

### 6. market_status_visualizer.py
- `market_visualizer_out` → `out/market_visualizer`
- 影响行: 147, 1384, 1742, 2261

### 7. optuna_dual_thrust_optimizer.py
- `autofish_output` → `out/market_optimization`
- 影响行: 42, 43, 50

### 8. optuna_improved_strategy_optimizer.py
- `autofish_output` → `out/market_optimization`
- 影响行: 53, 54, 61

### 9. binance_kline_fetcher.py
- `kline_cache/klines.db` → `database/klines.db`
- 影响行: 63, 65 (cache_dir 和 db_path)

### 10. market_status_visualizer.py (数据库路径)
- `market_visualizer_out/market_visualizer.db` → `database/market_visualizer.db`
- 影响行: 149, 1392, 1745
- 注意: 数据库路径需要单独指定，不再放在 output_dir 下

## 需要更新的文档文件

### 1. README.md
- 更新目录结构说明
- 更新日志与输出文件章节

### 2. docs/market_module_architecture.md
- 更新输出文件路径表格

### 3. docs/market_visualizer_design.md
- 更新目录结构说明

### 4. docs/market_status_detector.md
- 更新输出文件路径

### 5. docs/market_aware_backtest.md
- 更新输出文件路径

### 6. docs/optuna_improved_strategy_optimizer.md
- 更新输出文件路径

### 7. docs/binance_backtest_design.md
- 更新输出文件路径

### 8. docs/longport_backtest_design.md
- 更新输出文件路径

## 执行步骤

### 阶段1: 创建新目录结构
1. 创建 `out/autofish/` 目录
2. 创建 `out/market_backtest/` 目录
3. 创建 `out/market_visualizer/` 目录
4. 创建 `out/market_optimization/` 目录
5. 创建 `database/` 目录

### 阶段2: 修改代码文件
1. 修改 `autofish_core.py`
2. 修改 `binance_backtest.py`
3. 修改 `longport_backtest.py`
4. 修改 `market_status_detector.py`
5. 修改 `market_aware_backtest.py`
6. 修改 `market_status_visualizer.py`
7. 修改 `optuna_dual_thrust_optimizer.py`
8. 修改 `optuna_improved_strategy_optimizer.py`
9. 修改 `binance_kline_fetcher.py`

### 阶段3: 迁移现有文件
1. 迁移 `autofish_output/` 中的振幅配置和普通回测文件到 `out/autofish/`
2. 迁移 `autofish_output/` 中的 market_aware 相关文件到 `out/market_backtest/`
3. 迁移 `autofish_output/` 中的优化相关文件到 `out/market_optimization/`
4. 迁移 `market_visualizer_out/` 内容到 `out/market_visualizer/`
5. 迁移数据库文件到 `database/`

### 阶段4: 更新文档
1. 更新 `README.md`
2. 更新 `docs/market_module_architecture.md`
3. 更新 `docs/market_visualizer_design.md`
4. 更新 `docs/market_status_detector.md`
5. 更新 `docs/market_aware_backtest.md`
6. 更新 `docs/optuna_improved_strategy_optimizer.md`
7. 更新 `docs/binance_backtest_design.md`
8. 更新 `docs/longport_backtest_design.md`

### 阶段5: 清理旧目录
1. 删除空的 `autofish_output/` 目录
2. 删除空的 `market_visualizer_out/` 目录
3. 删除空的 `kline_cache/` 目录

## 文件迁移映射表

### autofish_output → out/autofish
- `binance_BTCUSDT_amplitude_config.json`
- `binance_BTCUSDT_amplitude_report.md`
- `binance_BTCUSDT_backtest_report*.md`
- `binance_ETHUSDT_amplitude_*`
- `binance_SOLUSDT_amplitude_*`
- `longport_*_amplitude_*`
- `longport_*_backtest_report.md`

### autofish_output → out/market_backtest
- `binance_BTCUSDT_market_aware_*`
- `binance_ETHUSDT_market_aware_*`
- `binance_BTCUSDT_market_report_*`
- `binance_BTCUSDT_market_history.md`

### autofish_output → out/market_optimization
- `dual_thrust_optimization_*`
- `optimization_*`

### market_visualizer_out → out/market_visualizer
- 所有 `market_visualizer_*` 文件 (md, png, html)

### 数据库迁移
- `kline_cache/klines.db` → `database/klines.db`
- `market_visualizer_out/market_visualizer.db` → `database/market_visualizer.db`

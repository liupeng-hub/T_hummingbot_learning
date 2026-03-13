# 行情可视化查看器任务分解

## 任务列表

### 阶段一：环境准备（预计 0.5 小时）✅

| 任务ID | 任务描述 | 优先级 | 状态 |
|--------|----------|--------|------|
| T1.1 | 安装 mplfinance 依赖 | 高 | ✅ 完成 |
| T1.2 | 创建输出目录 market_visualizer_out/ | 中 | ✅ 完成 |
| T1.3 | 验证现有模块可正常导入 | 高 | ✅ 完成 |

### 阶段二：核心类开发（预计 2.5 小时）✅

| 任务ID | 任务描述 | 优先级 | 状态 |
|--------|----------|--------|------|
| T2.1 | 创建 market_status_visualizer.py 主框架和 MarketStatusVisualizer 主控制器 | 高 | ✅ 完成 |
| T2.2 | 实现 DataProvider 类（复用 KlineFetcher） | 高 | ✅ 完成 |
| T2.3 | 实现 AlgorithmRunner 类（复用现有算法） | 高 | ✅ 完成 |
| T2.4 | 实现 StatusIntegrator 类（区间整合逻辑） | 高 | ✅ 完成 |
| T2.5 | 实现 ReportGenerator 类（MD报告生成） | 高 | ✅ 完成 |
| T2.6 | 实现 ChartVisualizer 类（K线图绘制） | 高 | ✅ 完成 |
| T2.7 | 实现文件命名和序列号管理 | 中 | ✅ 完成 |

### 阶段三：命令行接口（预计 0.5 小时）✅

| 任务ID | 任务描述 | 优先级 | 状态 |
|--------|----------|--------|------|
| T3.1 | 实现命令行参数解析 | 高 | ✅ 完成 |
| T3.2 | 实现算法参数传递 | 高 | ✅ 完成 |
| T3.3 | 实现多图对比模式 | 中 | ✅ 完成 |

### 阶段四：测试和优化（预计 1 小时）✅

| 任务ID | 任务描述 | 优先级 | 状态 |
|--------|----------|--------|------|
| T4.1 | 测试不同算法的可视化效果 | 高 | ✅ 完成 |
| T4.2 | 测试不同时间范围的数据 | 高 | ✅ 完成 |
| T4.3 | 验证 MD 报告格式正确 | 高 | ✅ 完成 |
| T4.4 | 性能优化（大数据量） | 中 | ✅ 完成 |

### 阶段五：文档和验收（预计 0.5 小时）✅

| 任务ID | 任务描述 | 优先级 | 状态 |
|--------|----------|--------|------|
| T5.1 | 更新使用文档 | 中 | ✅ 完成 |
| T5.2 | 添加代码注释 | 中 | ✅ 完成 |
| T5.3 | 验收测试 | 高 | ✅ 完成 |

## 任务依赖关系

```
T1.1 ──┬── T2.1 ── T2.2 ── T2.3 ── T2.4 ── T2.5 ── T2.6 ── T2.7 ──┐
       │                                                          │
T1.2 ──┤                                                          ├── T3.1 ── T3.2 ── T3.3 ──┐
       │                                                          │                          │
T1.3 ──┘                                                          │                          │
                                                                  │                          │
                                                                  └──────────────────────────┴── T4.1 ── T4.2 ── T4.3 ── T4.4 ── T5.1 ── T5.2 ── T5.3
```

## 完成情况

所有任务已完成！生成的文件：

1. **主程序**: `market_status_visualizer.py`
   - DataProvider: K线数据获取
   - AlgorithmRunner: 算法运行
   - StatusIntegrator: 状态区间整合
   - ReportGenerator: MD报告生成
   - ChartVisualizer: K线图可视化
   - MarketStatusVisualizer: 主控制器

2. **输出文件** (market_visualizer_out/):
   - `market_visualizer_BTCUSDT_1d_20200101-20260310_001.md/png`
   - `market_visualizer_BTCUSDT_1d_20220616-20230107_001.md/png`
   - `market_visualizer_BTCUSDT_1d_20230101-20230331_001.md/png`

## 使用方法

```bash
# 基本用法
python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310

# 指定算法
python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 --algorithm dual_thrust

# 传递算法参数
python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 \
    --algorithm dual_thrust --k1 0.5 --k2 0.5 --k2-down-factor 0.6

# 使用 improved 算法
python market_status_visualizer.py --symbol BTCUSDT --date-range 20220616-20230107 --algorithm improved
```

# 行情可视化系统设计文档

## 1. 系统概述

行情可视化系统是一个用于分析加密货币市场状态的工具，能够识别市场的震荡、上涨、下跌状态，并通过K线图直观展示分析结果。

### 1.1 核心功能

- **行情状态识别**: 使用 Dual Thrust 等算法识别市场状态
- **K线图可视化**: 在K线图上以色带形式展示行情状态区间
- **多维度输出**: 支持 MD报告、PNG图表、HTML交互页面
- **Web界面**: 提供Web界面进行测试管理和结果对比
- **数据持久化**: SQLite数据库存储测试用例和结果

### 1.2 运行模式

```bash
# 命令行模式
python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 --algorithm dual_thrust --generate-all

# Web服务器模式
python market_status_visualizer.py --server --port 5001
```

## 2. 系统架构

### 2.1 模块结构

```
market_status_visualizer.py
├── 数据类定义
│   ├── DailyStatus          # 每日行情状态
│   ├── StatusRange          # 行情状态区间
│   ├── StatusChangeEvent    # 状态变化事件
│   ├── TestCase             # 测试用例
│   ├── TestResult           # 测试结果
│   └── DailyStatusDB        # 数据库每日状态
│
├── 核心组件
│   ├── MarketVisualizerDB   # 数据库管理
│   ├── DataProvider         # 数据获取
│   ├── AlgorithmRunner      # 算法运行
│   ├── StatusIntegrator     # 状态整合
│   ├── ReportGenerator      # 报告生成
│   ├── ChartVisualizer      # 图表可视化
│   └── WebChartVisualizer   # Web图表可视化
│
├── 主控制器
│   ├── MarketStatusVisualizer  # 命令行模式控制器
│   └── MarketVisualizerServer  # Web服务器控制器
│
└── 入口函数
    └── main()               # 命令行参数解析和模式选择
```

### 2.2 数据流

```
┌─────────────┐    ┌─────────────────┐    ┌──────────────────┐
│ Binance API │───>│ DataProvider    │───>│ AlgorithmRunner  │
└─────────────┘    │ (K线数据获取)    │    │ (行情状态计算)    │
                   └─────────────────┘    └──────────────────┘
                                                  │
                                                  v
┌─────────────┐    ┌─────────────────┐    ┌──────────────────┐
│   输出文件   │<───│ ReportGenerator │<───│ StatusIntegrator │
│ MD/PNG/HTML │    │ ChartVisualizer │    │ (状态区间整合)    │
└─────────────┘    └─────────────────┘    └──────────────────┘
                           │                       │
                           v                       v
                   ┌─────────────────────────────────────┐
                   │        MarketVisualizerDB           │
                   │        (SQLite 数据持久化)           │
                   └─────────────────────────────────────┘
```

## 3. 核心算法

### 3.1 Dual Thrust 行情判断算法

Dual Thrust 算法通过计算价格突破区间来判断市场状态：

#### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| n_days | 4 | 回看天数，用于计算区间 |
| k1 | 0.5 | 上轨系数，控制上涨判断敏感度 |
| k2 | 0.5 | 下轨系数，控制下跌判断敏感度 |
| k2_down_factor | 0.5 | 下跌敏感系数，增强下跌识别 |
| down_confirm_days | 1 | 下跌确认天数，避免假突破 |
| cooldown_days | 0 | 状态切换冷却期，防止频繁切换 |

#### 算法逻辑

```python
# 1. 计算N日价格区间
high_n = max(前N日最高价)
low_n = min(前N日最低价)
range_n = high_n - low_n

# 2. 计算上下轨
upper_bound = 收盘价 + k1 * range_n
lower_bound = 收盘价 - k2 * range_n

# 3. 判断行情状态
if 当前最高价 > upper_bound:
    状态 = 上涨
elif 当前最低价 < lower_bound * k2_down_factor:
    if 连续down_confirm_days天突破下轨:
        状态 = 下跌
else:
    状态 = 震荡
```

### 3.2 状态区间整合

将每日状态整合为连续区间，便于可视化展示：

```python
# 整合逻辑
for 每日状态 in 所有日期:
    if 当前状态 == 前一日状态:
        扩展当前区间
    else:
        结束当前区间，开始新区间
```

## 4. 可视化方案

### 4.1 两种渲染模式

#### 模式1: 顶部色带
- 使用独立的Grid区域显示状态色带
- 优点：不干扰K线图主体
- 支持：缩放和拖拽时色带自动跟随
- **合并对比模式**：每个算法独立一条色带，多条色带依次排列在K线上方

#### 模式2: K线上方色带
- 在K线图上方叠加状态色带
- 色带高度基于K线最高价计算
- 使用ECharts markArea实现
- **坐标系统**：使用数字索引而非日期字符串，确保单根K线也能正确显示色块

### 4.2 颜色方案

| 状态 | 颜色 | 说明 |
|------|------|------|
| 上涨 | 红色 rgba(239, 68, 68, 0.3) | 与K线阳线颜色一致 |
| 下跌 | 绿色 rgba(34, 197, 94, 0.3) | 与K线阴线颜色一致 |
| 震荡 | 橙色 rgba(249, 115, 22, 0.3) | 独立颜色区分 |

### 4.3 ECharts 实现

#### 单图表色带（主页/分屏对比）
```javascript
// markArea 配置 - 使用数字索引坐标
markArea: {
    silent: true,
    data: [[
        { xAxis: startIndex, yAxis: barY, itemStyle: { color: 'rgba(239, 68, 68, 0.8)' } },
        { xAxis: endIndex + 1, yAxis: barY + barHeight }
    ]]
}
```

#### 合并对比模式顶部色带
```javascript
// 为每个算法创建独立的色带Grid
const colorBarHeight = 18;
const colorBarGap = 4;

for (let i = 0; i < numDatasets; i++) {
    grids.push({
        left: '5%', right: '5%',
        top: 70 + i * (colorBarHeight + colorBarGap),
        height: colorBarHeight,
    });
    // 每个算法独立的状态色带series
}
```

### 4.4 对比模式设计

#### 分屏对比
- 每个测试结果独立显示在单独的图表中
- 图表之间联动缩放
- 支持顶部色带/K线上方色带两种渲染模式

#### 合并对比
- 所有测试结果在同一图表中叠加显示
- **顶部色带模式**：每个算法一条独立色带，按算法顺序从上到下排列
- **K线上方色带模式**：不同算法的色带在不同高度层显示，间距为 `priceRange * 0.08`

### 4.5 色带间距参数

| 参数 | 值 | 说明 |
|------|-----|------|
| gapRatio | 0.03 | 色带与K线最高价之间的间距比例 |
| layerGap | priceRange * 0.08 | 多算法色带之间的层间距 |
| colorBarHeight | 18px | 顶部色带高度 |
| colorBarGap | 4px | 顶部色带之间的间距 |

## 5. 数据库设计

### 5.1 表结构

#### test_cases 表
```sql
CREATE TABLE test_cases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL DEFAULT '1d',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    algorithm_config TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT DEFAULT 'pending'
);
```

#### test_results 表
```sql
CREATE TABLE test_results (
    id TEXT PRIMARY KEY,
    test_case_id TEXT NOT NULL,
    total_days INTEGER,
    ranging_days INTEGER,
    trending_up_days INTEGER,
    trending_down_days INTEGER,
    ranging_count INTEGER,
    trending_up_count INTEGER,
    trending_down_count INTEGER,
    status_ranges TEXT,
    executed_at TEXT NOT NULL,
    duration_ms INTEGER,
    FOREIGN KEY (test_case_id) REFERENCES test_cases(id)
);
```

#### daily_statuses 表
```sql
CREATE TABLE daily_statuses (
    id TEXT PRIMARY KEY,
    test_result_id TEXT NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL,
    reason TEXT,
    open_price REAL,
    close_price REAL,
    high_price REAL,
    low_price REAL,
    volume REAL,
    FOREIGN KEY (test_result_id) REFERENCES test_results(id)
);
```

## 6. Web API

### 6.1 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| /api/test-cases | GET | 获取测试用例列表 |
| /api/test-cases | POST | 创建新测试 |
| /api/test-cases/:id | GET | 获取测试详情 |
| /api/test-cases/:id | DELETE | 删除测试 |
| /api/test-cases/:id/re-run | POST | 重新执行测试 |
| /api/daily-statuses/:result_id | GET | 获取每日状态 |
| /api/statistics/:result_id | GET | 获取统计信息 |
| /api/compare | POST | 对比多个测试 |
| /api/algorithms | GET | 获取算法列表 |
| /api/symbols | GET | 获取交易对列表 |

### 6.2 对比功能

对比功能支持同时查看多个测试结果：

```json
POST /api/compare
{
    "test_case_ids": ["id1", "id2", "id3"]
}
```

## 7. 前端实现

### 7.1 技术栈

- Vue.js 3 (CDN引入)
- ECharts 5.4.3
- 纯CSS样式

### 7.2 核心功能

1. **测试用例管理**: 创建、查看、删除测试
2. **K线图展示**: 带状态色带的交互式K线图
3. **对比模式**: 多测试结果对比
4. **渲染模式切换**: 顶部色带/K线上方色带

### 7.3 Tooltip 增强

鼠标悬停显示完整信息：
- 日期
- 开盘价、收盘价、最高价、最低价
- 成交量
- 震幅度 = (最高价 - 最低价) / 开盘价 × 100%

## 8. 输出文件

### 8.1 文件命名规则

```
market_visualizer_{symbol}_{interval}_{date_range}_{algorithm}_{seq}.{ext}
```

示例：
```
market_visualizer_BTCUSDT_1d_20200101-20260310_dual_thrust_001.md
market_visualizer_BTCUSDT_1d_20200101-20260310_dual_thrust_001.png
market_visualizer_BTCUSDT_1d_20200101-20260310_dual_thrust_001.html
```

### 8.2 MD报告内容

1. 基本信息：交易对、时间范围、算法、参数
2. 统计摘要：各状态天数、占比、区间数
3. 区间行情状态：详细的区间列表
4. 每日行情状态：前30天的每日状态
5. 状态变化事件：状态切换记录

## 9. 扩展性设计

### 9.1 添加新算法

1. 在 `market_status_detector.py` 中实现算法类
2. 在 `AlgorithmRunner.ALGORITHMS` 中注册
3. 在 `ALGORITHMS` 字典中添加参数定义

### 9.2 添加新交易对

在 `SYMBOLS` 列表中添加即可。

### 9.3 自定义输出

通过命令行参数控制输出：
- `--generate-md`: 生成MD报告
- `--generate-png`: 生成PNG图表
- `--generate-html`: 生成HTML页面
- `--generate-all`: 生成所有格式

## 10. 性能优化

### 10.1 数据缓存

- K线数据本地缓存，避免重复请求
- 使用SQLite索引加速查询

### 10.2 异步执行

- Web模式下测试执行使用独立线程
- 避免阻塞API响应

### 10.3 图表优化

- 大数据量时自动调整图表尺寸
- 使用dataZoom实现数据缩放

## 11. 部署说明

### 11.1 依赖

```
pandas
mplfinance
matplotlib
flask
flask-cors
```

### 11.2 目录结构

```
autofish_bot_v2/
├── market_status_visualizer.py   # 主程序（整合版）
├── market_status_detector.py     # 算法模块
├── binance_kline_fetcher.py      # 数据获取
├── templates/
│   └── index.html                # Web界面
├── out/market_visualizer/     # 输出目录
│   ├── market_visualizer.db      # SQLite数据库
│   └── *.md, *.png, *.html       # 输出文件
└── logs/
    └── market_visualizer_server.log
```

## 12. 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 1.0 | 2024-03 | 初始版本，支持命令行模式 |
| 2.0 | 2024-03 | 添加Web界面，支持测试管理 |
| 3.0 | 2025-03 | 整合数据库和服务器模块，优化可视化效果 |
| 3.1 | 2025-03-13 | 修复对比模式色带显示问题：<br>1. K线上方色带改用数字索引坐标，修复单根K线色块不显示问题<br>2. 合并对比模式顶部色带改为每个算法独立一条色带<br>3. 增大多条色带间距(layerGap: 0.04→0.08) |

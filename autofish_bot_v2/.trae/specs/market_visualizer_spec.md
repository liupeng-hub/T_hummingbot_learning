# 行情可视化查看器规格说明

## 1. 项目概述

### 1.1 目标
创建一个可视化的行情查看器，用于：
- 运行行情判断算法获取每日行情状态
- 整合得到时间区间划分的行情状态
- 在日K线图上展示行情状态区间
- 输出详细的行情分析报告（MD文件）
- 人工验证算法正确性，辅助优化算法参数

### 1.2 核心功能
1. **数据获取**: 通过 `binance_kline_fetcher` 获取日K线数据
2. **行情分析**: 通过 `market_status_detector` 运行算法，获取每日行情状态
3. **区间整合**: 将每日状态整合为时间区间（如 A-B 震荡，B-C 趋势）
4. **可视化展示**: 在K线图上标注行情状态区间
5. **报告输出**: 输出 MD 格式的行情分析报告

## 2. 技术方案

### 2.1 文件结构

**单文件设计**: `market_visualizer.py`

```
autofish_bot_v2/
├── market_status_visualizer.py    # 主程序（单文件，包含所有类）
├── market_status_detector.py     # 行情判断算法（已有，复用）
├── binance_kline_fetcher.py      # K线获取（已有，复用）
├── market_visualizer_out/        # 输出目录（新建）
│   ├── market_visualizer_BTCUSDT_1d_20200101-20260310_001.md
│   ├── market_visualizer_BTCUSDT_1d_20200101-20260310_001.png
│   ├── market_visualizer_BTCUSDT_1d_20200101-20260310_002.md
│   └── ...
└── docs/
    └── market_visualizer_spec.md # 本规格说明
```

### 2.2 类设计

```python
# market_visualizer.py 内部类结构

class DataProvider:
    """数据提供者 - 负责获取K线数据"""
    - 使用 binance_kline_fetcher.KlineFetcher
    - 获取指定时间范围的日K线数据
    
class AlgorithmRunner:
    """算法运行器 - 负责运行行情判断算法"""
    - 使用 market_status_detector 中的算法类
    - 计算每日行情状态
    - 返回每日判断结果列表
    
class StatusIntegrator:
    """状态整合器 - 负责将每日状态整合为区间"""
    - 输入: 每日行情状态列表
    - 输出: 时间区间划分的行情状态
    - 例如: 2020-01-01 ~ 2020-03-15: 震荡
    
class ReportGenerator:
    """报告生成器 - 负责生成MD报告"""
    - 生成每日状态表格
    - 生成区间状态表格
    - 生成统计信息
    
class ChartVisualizer:
    """图表可视化器 - 负责绘制K线图"""
    - 使用 mplfinance 绘制K线图
    - 标注行情状态区间
    - 支持多图对比展示
    
class MarketVisualizer:
    """主控制器 - 协调各组件工作"""
    - 解析命令行参数
    - 协调数据获取、算法运行、报告生成、可视化
    - 管理输出文件命名
```

### 2.3 数据流

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  DataProvider   │───▶│ AlgorithmRunner │───▶│ StatusIntegrator│
│  (K线数据获取)   │    │  (每日状态计算)   │    │  (区间整合)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                      │
        ┌─────────────────────────────────────────────┤
        ▼                                             ▼
┌─────────────────┐                         ┌─────────────────┐
│ReportGenerator  │                         │ChartVisualizer  │
│  (MD报告生成)    │                         │  (K线图绘制)     │
└─────────────────┘                         └─────────────────┘
        │                                             │
        ▼                                             ▼
   .md 报告文件                                  .png 图片文件
```

## 3. 功能详细设计

### 3.1 每日行情状态输出

**格式**: 列表，每个元素代表一天的判断结果

```python
daily_status = [
    {
        'date': '2020-01-01',
        'status': MarketStatus.RANGING,
        'confidence': 0.8,
        'reason': '价格在轨道内 [7000, 8000]'
    },
    {
        'date': '2020-01-02',
        'status': MarketStatus.RANGING,
        'confidence': 0.8,
        'reason': '价格在轨道内 [7000, 8000]'
    },
    ...
]
```

### 3.2 区间行情状态整合

**整合逻辑**: 连续相同状态合并为一个区间

```python
status_ranges = [
    {
        'start_date': '2020-01-01',
        'end_date': '2020-03-15',
        'status': MarketStatus.RANGING,
        'duration': 74,  # 天数
        'start_price': 7200,
        'end_price': 7800,
        'price_change': 8.3  # 百分比
    },
    {
        'start_date': '2020-03-16',
        'end_date': '2020-06-01',
        'status': MarketStatus.TRENDING_UP,
        'duration': 77,
        'start_price': 7800,
        'end_price': 9500,
        'price_change': 21.8
    },
    ...
]
```

### 3.3 MD 报告格式

```markdown
# 行情可视化分析报告

## 基本信息
- 交易对: BTCUSDT
- 时间范围: 2020-01-01 ~ 2026-03-10
- K线周期: 1d
- 算法: dual_thrust
- 算法参数: k1=0.5, k2=0.5, k2_down_factor=0.6

## 统计摘要
| 状态 | 天数 | 占比 | 区间数 |
|------|------|------|--------|
| 震荡 | 1200 | 54.5% | 15 |
| 上涨趋势 | 500 | 22.7% | 8 |
| 下跌趋势 | 500 | 22.7% | 10 |

## 区间行情状态

| 序号 | 开始日期 | 结束日期 | 状态 | 持续天数 | 起始价 | 结束价 | 涨跌幅 |
|------|----------|----------|------|----------|--------|--------|--------|
| 1 | 2020-01-01 | 2020-03-15 | 震荡 | 74 | 7200 | 7800 | +8.3% |
| 2 | 2020-03-16 | 2020-06-01 | 上涨 | 77 | 7800 | 9500 | +21.8% |
| ... | ... | ... | ... | ... | ... | ... | ... |

## 每日行情状态（前30天）

| 日期 | 状态 | 置信度 | 原因 |
|------|------|--------|------|
| 2020-01-01 | 震荡 | 0.80 | 价格在轨道内 [7000, 8000] |
| 2020-01-02 | 震荡 | 0.80 | 价格在轨道内 [7000, 8000] |
| ... | ... | ... | ... |

## 状态变化事件

| 日期 | 从状态 | 到状态 | 价格 | 原因 |
|------|--------|--------|------|------|
| 2020-03-16 | 震荡 | 上涨 | 7850 | 突破上轨 7800 |
| 2020-06-02 | 上涨 | 震荡 | 9500 | 价格回到轨道内 |
| ... | ... | ... | ... | ... |
```

### 3.4 可视化展示

**K线图标注**:
- 使用背景色标注行情状态区间
- 震荡区间：绿色背景（透明度 0.3）
- 上涨趋势：红色背景（透明度 0.3）
- 下跌趋势：蓝色背景（透明度 0.3）
- 在区间顶部显示状态标签

**多图对比展示**:
- 支持同时显示多个测试结果
- 每个子图显示不同的算法或参数组合
- 便于直观对比不同配置的效果

### 3.5 文件命名规则

**输出目录**: `autofish_out_2/`

**命名格式**: `market_visualizer_{symbol}_{interval}_{date_range}_{seq}.{ext}`

**示例**:
```
market_visualizer_BTCUSDT_1d_20200101-20260310_001.md
market_visualizer_BTCUSDT_1d_20200101-20260310_001.png
market_visualizer_BTCUSDT_1d_20200101-20260310_002.md  # 第二次测试
market_visualizer_BTCUSDT_1d_20200101-20260310_002.png
```

**序列号规则**:
- 自动检测目录下已有的文件
- 找到最大序列号 + 1
- 如果目录不存在，从 001 开始

## 4. 命令行接口

```bash
# 基本用法
python market_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310

# 指定算法
python market_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 \
    --algorithm dual_thrust

# 指定算法参数
python market_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 \
    --algorithm dual_thrust \
    --k1 0.5 --k2 0.5 --k2-down-factor 0.6

# 指定K线周期
python market_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 \
    --interval 1d

# 对比模式：同时显示多个参数组合
python market_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 \
    --compare "k1=0.5,k2=0.5" "k1=0.6,k2=0.4"

# 仅生成报告（不显示图表）
python market_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 \
    --no-chart
```

## 5. 依赖项

```
# requirements.txt 新增
mplfinance>=0.12.10
pandas>=2.0.0
matplotlib>=3.7.0
```

## 6. 验收标准

### 功能验收
- [ ] 能正确获取指定时间范围的日K线数据
- [ ] 能运行指定算法并获取每日行情状态
- [ ] 能正确整合为时间区间
- [ ] 能生成格式正确的 MD 报告
- [ ] 能在K线图上正确标注行情状态区间
- [ ] 文件命名和序列号正确

### 输出验收
- [ ] MD 报告格式清晰易读
- [ ] 表格数据准确
- [ ] K线图标注清晰
- [ ] 颜色区分明显

### 性能验收
- [ ] 6年日K线数据处理时间 < 10秒
- [ ] 内存占用 < 500MB

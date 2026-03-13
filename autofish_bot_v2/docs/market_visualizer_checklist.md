# 行情可视化查看器检查表

## 开发前检查

### 环境检查
- [x] Python 版本 >= 3.8
- [x] 已安装 pandas
- [x] 已安装 matplotlib
- [x] 安装 mplfinance (`pip install mplfinance`)
- [x] 项目目录结构正确

### 依赖模块检查
- [x] `market_status_detector.py` 可正常导入
- [x] `binance_kline_fetcher.py` 可正常导入
- [x] K线缓存数据库存在或可创建

## 功能检查

### 数据获取功能 (DataProvider)
- [x] 能获取指定交易对的日K线数据
- [x] 能获取指定时间范围的K线数据
- [x] 数据格式正确（timestamp, open, high, low, close, volume）
- [x] 数据缓存正常工作

### 算法运行功能 (AlgorithmRunner)
- [x] 能运行 DualThrustAlgorithm
- [x] 能运行 ImprovedStatusAlgorithm
- [x] 能运行 AlwaysRangingAlgorithm
- [x] 算法参数可正确传递
- [x] 返回的每日状态格式正确

### 区间整合功能 (StatusIntegrator)
- [x] 能正确识别连续相同状态
- [x] 能正确计算区间持续时间
- [x] 能正确计算区间价格变化
- [x] 能正确识别状态变化事件

### 报告生成功能 (ReportGenerator)
- [x] MD 报告格式正确
- [x] 统计摘要数据准确
- [x] 区间行情状态表格正确
- [x] 每日行情状态表格正确
- [x] 状态变化事件表格正确

### 可视化功能 (ChartVisualizer)
- [x] K线图正确显示（蜡烛图）
- [x] 成交量图正确显示
- [x] 行情状态背景色正确标注
  - [x] 震荡：绿色背景
  - [x] 上涨：红色背景
  - [x] 下跌：蓝色背景
- [x] 图例正确显示
- [x] 标题包含交易对和时间范围

### 文件管理功能
- [x] 输出目录正确创建
- [x] 文件命名格式正确
- [x] 序列号自动递增
- [x] MD 和 PNG 文件配对生成

### 命令行功能
- [x] `--symbol` 参数正常工作
- [x] `--date-range` 参数正常工作
- [x] `--algorithm` 参数正常工作
- [x] `--interval` 参数正常工作
- [x] `--output` 参数正常工作
- [x] 算法参数正确传递
- [x] 帮助信息清晰完整

## 输出检查

### MD 报告质量
- [x] 报告结构清晰
- [x] 表格格式正确
- [x] 数据准确无误
- [x] 中文显示正常

### 图片质量
- [x] 图片分辨率足够（>= 1920x1080）
- [x] 文字清晰可读
- [x] 颜色区分明显
- [x] 文件大小合理（< 5MB）

### 文件命名
- [x] 输出文件名包含交易对
- [x] 输出文件名包含时间范围
- [x] 输出文件名包含序列号
- [x] MD 和 PNG 文件名一致

## 测试用例

### 测试用例 1：基本功能测试
```bash
python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310
```
**预期结果**:
- [x] 生成 MD 报告文件
- [x] 生成 PNG 图片文件
- [x] 报告包含完整的统计和表格

### 测试用例 2：Dual Thrust 算法测试
```bash
python market_status_visualizer.py --symbol BTCUSDT --date-range 20200101-20260310 \
    --algorithm dual_thrust \
    --k1 0.5 --k2 0.5 --k2-down-factor 0.6
```
**预期结果**:
- [x] 使用 Dual Thrust 算法
- [x] 参数正确传递
- [x] 结果与回测一致

### 测试用例 3：短时间范围测试
```bash
python market_status_visualizer.py --symbol BTCUSDT --date-range 20230101-20230331
```
**预期结果**:
- [x] 显示 3 个月 K 线图
- [x] 渲染速度快
- [x] 文件序列号正确递增

### 测试用例 4：不同算法对比测试
```bash
python market_status_visualizer.py --symbol BTCUSDT --date-range 20220616-20230107 \
    --algorithm improved
```
**预期结果**:
- [x] 使用 Improved 算法
- [x] 结果与 dual_thrust 不同
- [x] 可用于对比分析

## 验收标准

### 必须满足
1. ✅ 能正确显示 K 线图
2. ✅ 能正确标注行情状态区间
3. ✅ 能生成 MD 格式的报告
4. ✅ 支持多种算法
5. ✅ 命令行参数正常工作
6. ✅ 文件命名和序列号正确

### 应该满足
1. ✅ 渲染速度 < 10秒
2. ✅ 图片质量清晰
3. ✅ 统计信息准确
4. ✅ 报告格式易读

### 可选满足
1. 💡 支持多图对比展示
2. 💡 支持悬停显示详情
3. 💡 支持多交易对对比

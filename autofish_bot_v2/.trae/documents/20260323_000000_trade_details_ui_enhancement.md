# 计划：交易详情列表和资金曲线优化

## 任务概述

1. **交易详情列表**：止盈和止损的行用不同的底色
2. **资金曲线图表**：使用类似 K 线展示的图表，全部 x 轴都显示出来，支持放大缩小

## 变更内容

### 1. 交易详情列表行底色

**当前实现**：
- 止盈：文字绿色 (`text-success`)
- 止损：文字红色 (`text-danger`)

**目标实现**：
- 止盈行：浅绿色背景 (`table-success` 或自定义)
- 止损行：浅红色背景 (`table-danger` 或自定义)

### 2. 资金曲线图表

**当前实现**：
- 使用 ECharts 折线图
- x 轴显示 `#1, #2, #3...`
- 不支持缩放

**目标实现**：
- 使用 ECharts K 线图或带缩放的折线图
- x 轴显示所有数据点
- 支持放大缩小（dataZoom 组件）

## 实现步骤

### 步骤 1：修改交易详情列表行底色

**文件**：`web/test_results/index.html`

**修改位置**：`renderTradeDetailsTable` 函数中的表格行生成部分

**修改内容**：
```javascript
// 当前代码
const typeClass = t.trade_type === 'take_profit' ? 'text-success' : 'text-danger';
html += `<tr data-index="${index}" ...>`;

// 修改后
const rowClass = t.trade_type === 'take_profit' ? 'table-success' : 'table-danger';
html += `<tr data-index="${index}" class="${rowClass}" ...>`;
```

### 步骤 2：修改资金曲线图表

**文件**：`web/test_results/index.html`

**修改位置**：`renderTradeCapitalChart` 函数

**修改内容**：
1. 添加 `dataZoom` 组件支持缩放
2. x 轴显示所有数据点（使用 `axisLabel.interval: 0`）
3. 可选：使用 K 线图样式

**ECharts 配置**：
```javascript
const option = {
    // ... 其他配置
    dataZoom: [
        {
            type: 'inside',
            start: 0,
            end: 100
        },
        {
            type: 'slider',
            start: 0,
            end: 100
        }
    ],
    xAxis: {
        type: 'category',
        data: xData,
        axisLabel: {
            rotate: 45,
            fontSize: 10,
            interval: 0  // 显示所有标签
        }
    }
};
```

## 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `web/test_results/index.html` | `renderTradeDetailsTable` 函数：添加行底色 |
| `web/test_results/index.html` | `renderTradeCapitalChart` 函数：添加缩放功能 |

## 预期效果

### 交易详情列表

| 类型 | 效果 |
|------|------|
| 止盈行 | 浅绿色背景 |
| 止损行 | 浅红色背景 |

### 资金曲线图表

| 功能 | 效果 |
|------|------|
| x 轴 | 显示所有数据点标签 |
| 缩放 | 支持鼠标滚轮缩放和滑块缩放 |
| 交互 | 可拖动查看特定区域 |

# K线图交易标注显示修复计划

## 问题分析

### 当前状态
1. **前端代码**：使用 `t.entry_date` 和 `t.exit_date` 作为坐标
2. **数据库字段**：存储的是 `entry_time` 和 `exit_time`（datetime 格式，如 `2025-01-15 10:30:00`）
3. **K线日期**：使用 `date` 格式（如 `2025-01-15`）
4. **问题**：字段名不匹配，且日期格式不一致，导致交易标注无法显示

### 数据库 trade_details 表结构
```sql
CREATE TABLE trade_details (
    result_id TEXT NOT NULL,
    trade_seq INTEGER NOT NULL,
    level TEXT,              -- 档位 (A1, A2, A3)
    entry_price REAL,        -- 入场价格
    exit_price REAL,         -- 出场价格
    entry_time DATETIME,     -- 入场时间
    exit_time DATETIME,      -- 出场时间
    trade_type TEXT,         -- 交易类型 (take_profit, stop_loss)
    profit REAL,             -- 盈亏
    quantity REAL,           -- 数量
    stake REAL               -- 金额
)
```

## 修复方案

### 方案：后端返回时转换日期格式

在 `test_manager.py` 的 `get_chart_data` API 中，处理 trades 数据时添加日期字段：

```python
# 处理 trades 数据，添加日期字段
for t in trades:
    if t.get('entry_time'):
        t['entry_date'] = t['entry_time'].split()[0] if ' ' in t['entry_time'] else t['entry_time']
    if t.get('exit_time'):
        t['exit_date'] = t['exit_time'].split()[0] if ' ' in t['exit_time'] else t['exit_time']
```

### 前端显示设计

当前已有基础显示，优化显示方式：

1. **入场标记**：
   - 绿色三角形 ▲
   - 标注档位（A1, A2, A3）
   - 显示入场价格

2. **出场标记**：
   - 红色/绿色 pin 标记
   - 显示盈亏金额
   - 颜色：止盈绿色，止损红色

3. **连线显示**（新增）：
   - 使用 markLine 连接入场和出场点
   - 直观显示交易过程

## 实施步骤

### 任务 1: 修复后端日期格式转换
**文件**: `test_manager.py`

在 `get_chart_data` 函数中，处理 trades 数据添加日期字段。

### 任务 2: 优化前端显示
**文件**: `web/test_results/index.html`

1. 修复日期字段名匹配
2. 添加入场-出场连线（markLine）
3. 优化 tooltip 显示完整交易信息

## 预期效果

1. K线图上正确显示入场点（绿色三角形）
2. K线图上正确显示出场点（pin 标记，显示盈亏）
3. 入场-出场之间有连线，直观显示交易过程
4. 鼠标悬停显示完整交易详情

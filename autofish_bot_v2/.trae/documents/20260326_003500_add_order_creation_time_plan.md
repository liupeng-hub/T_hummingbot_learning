# 交易详情添加挂单时间实现计划

## 问题描述

当前交易详情中只显示入场时间（成交时间），没有显示挂单时间。需要在交易详情中增加挂单时间，并在 web 页面上展示，位置在入场时间之前。

## 实现分析

### 当前状态
- `Autofish_Order` 类已包含 `created_at` 字段（挂单时间）
- 订单创建时会设置 `created_at`
- 但交易记录中只保存了 `entry_time`（即 `filled_at`），没有保存 `created_at`

### 实现步骤

## [x] Task 1: 在交易记录中添加挂单时间字段
- **Priority**: P0
- **Depends On**: None
- **Description**: 
  - 在 `_close_order` 方法中，将 `order.created_at` 添加到交易记录字典中
  - 在 `_close_all_positions` 方法中，同样添加 `created_at` 字段
- **Success Criteria**:
  - 交易记录中包含 `creation_time` 字段
  - 该字段的值为订单的 `created_at`
- **Test Requirements**:
  - `programmatic` TR-1.1: 交易记录字典包含 `creation_time` 键
  - `programmatic` TR-1.2: `creation_time` 值与订单的 `created_at` 一致
- **Notes**: 需要修改两个方法：`_close_order` 和 `_close_all_positions`
- **Status**: 已完成 - 已在两个方法中添加 `creation_time` 字段

## [ ] Task 2: 在数据库保存中添加挂单时间
- **Priority**: P0
- **Depends On**: Task 1
- **Description**:
  - 在 `save_trade_details` 方法中，将 `creation_time` 字段保存到数据库
  - 确保 `trade_details` 表结构支持该字段
- **Success Criteria**:
  - 数据库中 `trade_details` 表包含 `creation_time` 字段
  - 新交易记录的 `creation_time` 被正确保存
- **Test Requirements**:
  - `programmatic` TR-2.1: 数据库表包含 `creation_time` 字段
  - `programmatic` TR-2.2: 新交易记录的 `creation_time` 有值
- **Notes**: 可能需要修改数据库表结构

## [ ] Task 3: 在 Web 页面交易详情表格中添加挂单时间列
- **Priority**: P0
- **Depends On**: Task 2
- **Description**:
  - 在 web 页面的交易详情表格中添加 "挂单时间" 列
  - 位置在 "入场时间" 之前
  - 显示订单的 `creation_time`
- **Success Criteria**:
  - Web 页面交易详情表格包含 "挂单时间" 列
  - 挂单时间正确显示
  - 位置在入场时间之前
- **Test Requirements**:
  - `human-judgment` TR-3.1: 表格中存在 "挂单时间" 列
  - `human-judgment` TR-3.2: 挂单时间显示在入场时间之前
  - `programmatic` TR-3.3: 挂单时间值正确显示
- **Notes**: 修改 web/test_results/index.html 文件

## [ ] Task 4: 在 Web 页面其他相关位置添加挂单时间
- **Priority**: P1
- **Depends On**: Task 3
- **Description**:
  - 在交易明细弹窗中添加挂单时间
  - 在其他显示交易信息的地方添加挂单时间
- **Success Criteria**:
  - 交易明细弹窗显示挂单时间
  - 其他相关位置也显示挂单时间
- **Test Requirements**:
  - `human-judgment` TR-4.1: 交易明细弹窗包含挂单时间
  - `human-judgment` TR-4.2: 其他相关位置显示挂单时间
- **Notes**: 检查所有显示交易信息的地方

## 技术实现要点

### Task 1 实现
- 文件: `binance_backtest.py`
- 方法: `_close_order` 和 `_close_all_positions`
- 添加: `"creation_time": order.created_at` 到交易记录字典

### Task 2 实现
- 文件: `database/test_results_db.py`
- 方法: `save_trade_details`
- 添加: `creation_time` 字段到数据库插入语句

### Task 3 实现
- 文件: `web/test_results/index.html`
- 修改交易详情表格的表头和数据行
- 在入场时间列之前添加挂单时间列

## 验证计划

1. 运行回测生成新的交易记录
2. 检查数据库中 `trade_details` 表是否包含 `creation_time` 字段
3. 打开 Web 页面，检查交易详情表格是否显示挂单时间
4. 验证挂单时间是否在入场时间之前
5. 验证挂单时间值是否正确

## 影响范围

- 交易记录结构变更
- 数据库表结构变更（如果需要）
- Web 页面 UI 变更

## 相关文件

- `binance_backtest.py` - 交易记录生成
- `database/test_results_db.py` - 数据库保存
- `web/test_results/index.html` - Web 页面展示

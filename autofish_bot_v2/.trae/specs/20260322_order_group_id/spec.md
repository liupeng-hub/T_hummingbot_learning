# 订单轮次信息与交易详情增强 规范

## 为什么
为订单增加轮次信息（group_id），便于追踪每一轮链式挂单的交易情况；同时增强交易详情列表的交互功能，支持过滤和排序。

## 变更内容
- `Autofish_Order` 类添加 `group_id` 字段，初始值为 1
- `Autofish_ChainState` 类添加 `group_id` 字段（存储当前轮次），初始值为 0
- `TestResult` 数据类添加 `order_group_count` 字段，统计 A1 成交次数（轮次数）
- `TradeDetail` 数据类添加 `order_group_id` 字段，放在 `trade_seq` 之前
- 数据库表 `test_results` 添加 `order_group_count` 列
- 数据库表 `trade_details` 添加 `order_group_id` 列
- 回测代码中统计 A1 成交次数，每次 A1 成交时递增 `chain_state.group_id`
- Web 展示适配：显示轮次信息，支持表头过滤和列排序

## 影响范围
- 受影响规范：订单管理、测试结果统计、交易详情展示
- 受影响代码： 
  - `autofish_core.py` (Autofish_Order, Autofish_ChainState)
  - `database/test_results_db.py` (TestResult, TradeDetail, 数据库表)
  - `binance_backtest.py` (轮次统计逻辑)
  - `web/test_results/index.html` (展示适配)

## 新增需求

### 需求：订单轮次标识
系统应为每个订单提供轮次标识（group_id），用于区分不同轮次的链式挂单。

#### 场景：A1 成交时递增轮次
- **当** A1 订单成交（状态变为 filled）时
- **则** 系统应递增 `chain_state.group_id`，并将新的 `group_id` 赋值给该订单

#### 场景：A1 订单取消不影响轮次
- **当** A1 订单被取消（超时或其他原因）
- **则** 系统不应递增 `chain_state.group_id`，下一个 A1 成交时使用正确的 `group_id`

#### 场景：同一轮次订单
- **当** A2/A3/A4 入场时
- **则** 系统应使用当前 `chain_state.group_id`

### 需求：轮次统计
系统应统计每次测试的轮次数量（A1 成交次数）。

#### 场景：测试完成
- **当** 测试完成时
- **则** 系统应将 `order_group_count`（A1 成交次数，即 `chain_state.group_id` 的最终值）保存到 `test_results` 表

### 需求：交易详情轮次信息
系统应在交易详情中记录每笔交易所属的轮次。

#### 场景：交易记录
- **当** 记录交易详情时
- **则** 系统应将 `order_group_id` 保存到 `trade_details` 表

### 需求：交易详情列表增强
交易详情列表应支持表头过滤和列排序功能。

#### 场景：表头过滤
- **当** 用户点击表头过滤按钮
- **则** 系统应显示过滤选项，允许用户筛选数据

#### 场景：列排序
- **当** 用户点击列标题
- **则** 系统应按该列进行升序或降序排序

## 修改需求

### 需求：Autofish_Order 数据结构
订单数据结构应包含 `group_id` 字段：
- `group_id: int = 1` - 订单所属轮次

### 需求：Autofish_ChainState 数据结构
链状态数据结构应包含 `group_id` 字段：
- `group_id: int = 0` - 当前轮次（存储当前轮次编号，A1 成交时递增）

### 需求：TestResult 数据结构
测试结果数据结构应包含 `order_group_count` 字段：
- `order_group_count: int = 0` - 轮次数量（A1 成交次数）

### 需求：TradeDetail 数据结构
交易详情数据结构应包含 `order_group_id` 字段：
- `order_group_id: int = 0` - 交易所属轮次，位于 `trade_seq` 之前

### 需求：数据库表结构
- `test_results` 表添加 `order_group_count INTEGER DEFAULT 0` 列
- `trade_details` 表添加 `order_group_id INTEGER DEFAULT 0` 列，位于 `trade_seq` 之后

## 关键设计决策

### group_id 存储位置
- **Autofish_ChainState.group_id**：存储当前轮次编号
  - 初始值：0
  - 类型：int
  - 作用：跟踪当前轮次，A1 成交时递增

### group_id 递增逻辑
```python
def _process_entry(self, ...):
    if pending_order.level == 1:
        # A1 成交时递增轮次
        self.chain_state.group_id += 1
    
    # 将当前轮次赋值给订单
    pending_order.group_id = self.chain_state.group_id
```

### 数据流程
```
初始状态: chain_state.group_id = 0

A1 订单创建 (pending) → group_id 不变（仍为 0）
A1 订单成交 (filled) → group_id 递增为 1，订单记录 group_id = 1
A2 入场 → group_id = 1
A1 出场 → 创建新 A1 订单 (pending)

A1 订单取消 (cancelled) → group_id 不变（仍为 1）
新 A1 订单创建 (pending) → group_id 不变（仍为 1）
新 A1 成交 (filled) → group_id 递增为 2，订单记录 group_id = 2

A2/A3/A4 入场 → 使用当前 group_id
```

### 轮次统计
- **order_group_count**：统计 A1 成交次数（即 `chain_state.group_id` 的最终值）

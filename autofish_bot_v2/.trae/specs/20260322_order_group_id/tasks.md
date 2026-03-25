# 任务列表

- [x] 任务 1: 修改 autofish_core.py 数据结构
  - [x] 子任务 1.1: Autofish_Order 类添加 `group_id: int = 1` 字段
  - [x] 子任务 1.2: Autofish_Order.to_dict() 方法添加 `group_id` 字段
  - [x] 子任务 1.3: Autofish_Order.from_dict() 方法添加 `group_id` 字段
  - [x] 子任务 1.4: Autofish_ChainState 类添加 `group_id: int = 0` 字段（存储当前轮次）

- [x] 任务 2: 修改数据库模块 database/test_results_db.py
  - [x] 子任务 2.1: TestResult 数据类添加 `order_group_count: int = 0` 字段
  - [x] 子任务 2.2: TradeDetail 数据类添加 `order_group_id: int = 0` 字段（位于 trade_seq 之前）
  - [x] 子任务 2.3: _ensure_tables() 方法添加数据库列迁移逻辑
  - [x] 子任务 2.4: save_test_result() 方法适配 `order_group_count` 字段
  - [x] 子任务 2.5: save_trade_details() 方法适配 `order_group_id` 字段

- [x] 任务 3: 修改回测模块 binance_backtest.py
  - [x] 子任务 3.1: _process_entry() 方法：A1 成交时递增 `self.chain_state.group_id`
  - [x] 子任务 3.2: _process_entry() 方法：所有订单成交时设置 `order.group_id = self.chain_state.group_id`
  - [x] 子任务 3.3: _record_trade() 方法：交易记录中包含 `group_id`
  - [x] 子任务 3.4: 测试结果中统计 `order_group_count`（A1 成交次数）

- [ ] 任务 4: 修改 Web 展示模块 web/test_results/index.html
  - [ ] 子任务 4.1: 交易详情表头添加"轮次"列
  - [ ] 子任务 4.2: 交易详情表格数据添加 `order_group_id` 显示
  - [ ] 子任务 4.3: 测试结果统计卡片添加"轮次数"显示
  - [ ] 子任务 4.4: 交易详情列表添加表头过滤功能
  - [ ] 子任务 4.5: 交易详情列表添加列排序功能

- [ ] 任务 5: 验证功能
  - [ ] 子任务 5.1: 运行回测，验证 `group_id` 在 A1 成交时正确递增
  - [ ] 子任务 5.2: 验证 A1 订单取消不影响 `group_id`
  - [ ] 子任务 5.3: 验证数据库正确保存轮次信息
  - [ ] 子任务 5.4: 验证 Web 正确显示轮次信息
  - [ ] 子任务 5.5: 验证过滤和排序功能正常工作

# 任务依赖
- [任务 2] 依赖 [任务 1]
- [任务 3] 依赖 [任务 1]
- [任务 4] 依赖 [任务 2]
- [任务 5] 依赖 [任务 1, 任务 2, 任务 3, 任务 4]

# 关键设计决策

## group_id 存储位置
- **Autofish_ChainState.group_id**：存储当前轮次编号
  - 初始值：0
  - 类型：int
  - 作用：跟踪当前轮次，A1 成交时递增

## group_id 递增逻辑
```python
def _process_entry(self, ...):
    if pending_order.level == 1:
        # A1 成交时递增轮次
        self.chain_state.group_id += 1
    
    # 将当前轮次赋值给订单
    pending_order.group_id = self.chain_state.group_id
```

## 数据流程
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

## 轮次统计
- **order_group_count**：统计 A1 成交次数（即 `chain_state.group_id` 的最终值）

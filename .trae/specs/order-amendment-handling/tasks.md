# Tasks

- [x] Task 1: 处理入场单过期事件（EXPIRED）
  - [x] 1.1: 在 `_handle_order_update` 中添加 EXPIRED 状态处理
  - [x] 1.2: 删除本地订单记录
  - [x] 1.3: 取消关联的止盈止损单（如果有）
  - [x] 1.4: 添加日志和通知

- [x] Task 2: 处理条件单过期事件（EXPIRED）
  - [x] 2.1: 在 `_handle_algo_update` 中添加 EXPIRED 状态处理
  - [x] 2.2: 标记止盈/止损单为 None
  - [x] 2.3: 触发补单逻辑（标记需要补单）
  - [x] 2.4: 添加日志和通知

- [x] Task 3: 处理条件单拒绝事件（REJECTED）
  - [x] 3.1: 在 `_handle_algo_update` 中添加 REJECTED 状态处理
  - [x] 3.2: 标记止盈/止损单为 None
  - [x] 3.3: 触发补单逻辑（标记需要补单）
  - [x] 3.4: 添加日志和通知

- [x] Task 4: 处理 STP 触发事件（TRADE_PREVENT）
  - [x] 4.1: 在 `_handle_order_update` 中添加 TRADE_PREVENT 状态处理
  - [x] 4.2: 删除本地订单记录
  - [x] 4.3: 取消关联的止盈止损单
  - [x] 4.4: 添加日志和通知

- [ ] Task 5: 同步更新 longport_live.py
  - [ ] 5.1: 同步所有新增的事件处理逻辑

# Task Dependencies

- Task 5 depends on Task 1, Task 2, Task 3, Task 4

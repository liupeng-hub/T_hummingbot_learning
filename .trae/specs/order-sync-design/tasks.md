# Tasks

- [x] Task 0: 新增 Binance API 方法
  - [x] 0.1: 实现 `get_all_orders` 方法 - 查询历史普通订单
  - [x] 0.2: 实现 `get_all_algo_orders` 方法 - 查询历史 Algo 条件单
  - [x] 0.3: 实现 `get_my_trades` 方法 - 查询历史成交记录
  - [x] 0.4: 实现 `get_position` 方法 - 查询当前仓位（已存在）

- [x] Task 1: 设计并实现订单同步核心逻辑
  - [x] 1.1: 实现 `_get_binance_state` 方法 - 获取 Binance 当前状态（仓位、委托、Algo 条件单）
  - [x] 1.2: 实现 `_sync_pending_order` 方法 - pending 订单同步逻辑
  - [x] 1.3: 实现 `_sync_filled_order` 方法 - filled 订单同步逻辑
  - [x] 1.4: 实现 `_check_position_closed` 方法 - 检查仓位是否已平仓
  - [x] 1.5: 实现 `_get_close_reason` 方法 - 查询历史成交确定平仓原因

- [x] Task 2: 实现残留条件单清理
  - [x] 2.1: 在删除 pending 订单前记录关联的条件单 ID
  - [x] 2.2: 在 filled 订单平仓后取消残留条件单
  - [x] 2.3: 实现 `_cancel_orphan_algo_orders` 方法

- [x] Task 3: 更新恢复通知
  - [x] 3.1: 在恢复通知中显示已平仓订单信息
  - [x] 3.2: 显示平仓原因（止盈/止损/未知）

- [x] Task 4: 添加日志和通知
  - [x] 4.1: 添加订单同步过程日志
  - [x] 4.2: 添加平仓检测通知
  - [x] 4.3: 添加残留条件单取消通知

- [x] Task 5: 同步更新 longport_live.py
  - [x] 5.1: 同步订单恢复逻辑（LongPort API 差异大，保持原有逻辑）
  - [x] 5.2: 同步残留条件单清理逻辑

- [x] Task 6: 启动通知优化
  - [x] 6.1: 添加振幅分析配置信息到启动通知
  - [x] 6.2: 启动通知在订单恢复之前发送
  - [x] 6.3: 显示权重信息

- [x] Task 7: 已平仓订单处理
  - [x] 7.1: 已平仓订单直接删除，不保留 closed 状态

# Task Dependencies

- Task 1 depends on Task 0
- Task 2 depends on Task 1
- Task 3 depends on Task 1
- Task 4 depends on Task 1, Task 2, Task 3
- Task 5 depends on Task 1, Task 2, Task 3, Task 4
- Task 6 depends on Task 1
- Task 7 depends on Task 1

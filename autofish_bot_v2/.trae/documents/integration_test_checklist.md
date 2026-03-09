# 集成测试检查清单

## 测试覆盖检查

### 核心流程覆盖

| 流程 | 测试用例 | 状态 |
|------|----------|------|
| 启动下 A1 | `test_place_initial_order` | ⬜ |
| A1 成交 | `test_entry_filled` | ⬜ |
| 下止盈止损单 | `test_place_exit_orders` | ⬜ |
| 下 A2 入场单 | `test_place_next_level` | ⬜ |
| 止盈触发 | `test_take_profit_trigger` | ⬜ |
| 止损触发 | `test_stop_loss_trigger` | ⬜ |
| 取消下一级 | `test_cancel_next_level` | ⬜ |
| 下新 A1 | `test_place_new_a1` | ⬜ |

### 状态转换覆盖

| 状态转换 | 测试用例 | 状态 |
|----------|----------|------|
| pending -> filled | `test_pending_to_filled` | ⬜ |
| filled -> closed (TP) | `test_filled_to_closed_tp` | ⬜ |
| filled -> closed (SL) | `test_filled_to_closed_sl` | ⬜ |
| pending -> cancelled | `test_pending_to_cancelled` | ⬜ |

### 多层级覆盖

| 场景 | 测试用例 | 状态 |
|------|----------|------|
| A1 成交下 A2 | `test_a1_filled_place_a2` | ⬜ |
| A2 成交下 A3 | `test_a2_filled_place_a3` | ⬜ |
| A3 成交下 A4 | `test_a3_filled_place_a4` | ⬜ |
| A4 成交不下 A5 | `test_a4_filled_no_a5` | ⬜ |
| A1 止盈取消 A2 | `test_a1_tp_cancel_a2` | ⬜ |
| A2 止盈取消 A3 | `test_a2_tp_cancel_a3` | ⬜ |

### 状态恢复覆盖

| 场景 | 测试用例 | 状态 |
|------|----------|------|
| 恢复 pending 订单 | `test_recover_pending` | ⬜ |
| 恢复 filled 订单 | `test_recover_filled` | ⬜ |
| 恢复 closed 订单 | `test_recover_closed` | ⬜ |
| 检测已成交订单 | `test_detect_filled_on_startup` | ⬜ |

### 异常处理覆盖

| 场景 | 测试用例 | 状态 |
|------|----------|------|
| WebSocket 断开 | `test_ws_disconnect` | ⬜ |
| WebSocket 重连 | `test_ws_reconnect` | ⬜ |
| API 请求失败 | `test_api_failure` | ⬜ |
| 订单不存在 | `test_order_not_found` | ⬜ |
| ALGO 订单不存在 | `test_algo_not_found` | ⬜ |

## Mock 功能检查

### Binance API Mock

| 功能 | 实现状态 |
|------|----------|
| place_order | ⬜ |
| place_tp_sl_order | ⬜ |
| cancel_order | ⬜ |
| cancel_algo_order | ⬜ |
| simulate_order_filled | ⬜ |
| simulate_algo_triggered | ⬜ |
| get_listen_key | ⬜ |
| keepalive_listen_key | ⬜ |

### WebSocket Mock

| 功能 | 实现状态 |
|------|----------|
| connect | ⬜ |
| send | ⬜ |
| recv | ⬜ |
| put_message | ⬜ |
| close | ⬜ |

### 市场数据 Mock

| 功能 | 实现状态 |
|------|----------|
| get_current_price | ⬜ |
| get_klines | ⬜ |

## 代码质量检查

| 检查项 | 状态 |
|--------|------|
| 所有测试通过 | ⬜ |
| 代码覆盖率 > 80% | ⬜ |
| 无 lint 错误 | ⬜ |
| 无 type 错误 | ⬜ |

## 文档检查

| 文档 | 状态 |
|------|------|
| 测试设计文档 | ✅ |
| 测试任务列表 | ✅ |
| 测试检查清单 | ✅ |
| 运行测试说明 | ⬜ |

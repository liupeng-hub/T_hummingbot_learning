# Checklist

## Binance API 方法

- [x] `get_all_orders` 方法正确实现，返回历史普通订单列表
- [x] `get_all_algo_orders` 方法正确实现，返回历史 Algo 条件单列表
- [x] `get_my_trades` 方法正确实现，返回历史成交记录
- [x] `get_positions` 方法正确实现，返回当前仓位

## pending 订单同步

- [x] pending 订单在 Binance 仍挂单时，保持 pending 状态
- [x] pending 订单在 Binance 已成交时，更新为 filled 状态
- [x] pending 订单在 Binance 已取消时，删除本地订单
- [x] pending 订单在 Binance 不存在时，删除本地订单
- [x] pending 订单删除前，记录关联的止盈止损单 ID

## filled 订单同步

- [x] filled 订单止盈止损都存在且有仓位时，保持 filled 状态
- [x] filled 订单止盈缺失且有仓位时，补止盈单
- [x] filled 订单止损缺失且有仓位时，补止损单
- [x] filled 订单止盈止损都缺失且有仓位时，补止盈止损单
- [x] filled 订单止盈成交（无仓位 + 止损残留）时，取消止损，更新为 closed
- [x] filled 订单止损成交（无仓位 + 止盈残留）时，取消止盈，更新为 closed
- [x] filled 订单已平仓（无仓位 + 止盈止损都不存在）时，查历史成交，更新为 closed

## 残留条件单清理

- [x] pending 订单删除后，取消关联的残留条件单
- [x] filled 订单平仓后，取消残留的条件单

## 平仓原因检测

- [x] 止盈成交时，close_reason="take_profit"
- [x] 止损成交时，close_reason="stop_loss"
- [x] 无法确定时，close_reason="unknown"

## 恢复通知

- [x] 恢复通知中显示已平仓订单信息
- [x] 显示平仓原因

## 日志输出

- [x] 订单同步过程日志清晰
- [x] 平仓检测过程日志清晰
- [x] 条件单取消过程日志清晰
- [x] 错误情况正确记录

# 检查清单

## 数据结构
- [ ] Autofish_Order 类包含 `group_id` 字段，默认值为 1
- [ ] Autofish_ChainState 类包含 `group_id` 字段，默认值为 0
- [ ] TestResult 数据类包含 `order_group_count` 字段
- [ ] TradeDetail 数据类包含 `order_group_id` 字段，位于 `trade_seq` 之前

## 数据库
- [ ] test_results 表包含 `order_group_count` 列
- [ ] trade_details 表包含 `order_group_id` 列
- [ ] 数据库迁移正确处理现有数据

## 回测逻辑
- [ ] A1 成交时 `group_id` 正确递增
- [ ] A1 取消时 `group_id` 不变
- [ ] A2/A3/A4 入场时使用当前 `group_id`
- [ ] 交易记录中包含正确的 `group_id`
- [ ] 测试结果中 `order_group_count` 正确统计（A1 成交次数）

## Web 展示
- [ ] 交易详情表头显示"轮次"列
- [ ] 交易详情数据正确显示 `order_group_id`
- [ ] 测试结果统计卡片显示"轮次数"
- [ ] 表头过滤功能正常工作
- [ ] 列排序功能正常工作

## 边界场景
- [ ] A1 取消后，下一个 A1 成交时 `group_id` 正确递增
- [ ] 多次 A1 取消后，`group_id` 仍然正确

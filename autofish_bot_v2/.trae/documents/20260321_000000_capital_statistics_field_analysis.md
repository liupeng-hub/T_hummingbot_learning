# 分析：test_results 表中 capital_statistics 字段

## 现状

### 1. test_results 表结构
```
capital_statistics TEXT DEFAULT '{}'
```

### 2. 数据状态
- 所有记录的 `capital_statistics` 字段值都是 `'{}'`（空 JSON）
- 没有实际使用

### 3. 独立的 capital_statistics 表
已存在独立的 `capital_statistics` 表，包含完整的资金统计数据：
- `result_id` - 关联测试结果
- `strategy` - 资金策略
- `initial_capital` - 初始资金
- `final_capital` - 最终资金
- `trading_capital` - 交易资金
- `profit_pool` - 利润池
- `total_return` - 总收益率
- `max_drawdown` - 最大回撤
- `withdrawal_count` - 提现次数
- 等等...

### 4. 代码使用情况
- `binance_backtest.py` 使用 `db.save_capital_statistics()` 保存到独立表
- `test_manager.py` 使用 `db.get_capital_statistics()` 从独立表读取
- 前端 `index.html` 使用 `r.capital_statistics` 显示数据（来自 JOIN 查询）

## 结论

**`test_results` 表中的 `capital_statistics` 字段是冗余的**：
1. 数据始终为空 `{}`
2. 已有独立的 `capital_statistics` 表存储完整数据
3. 代码不使用这个字段

## 建议

**可以删除该字段**，但需要：
1. 修改 `test_results_db.py` 中的表定义
2. 添加迁移脚本删除该列
3. 验证代码中没有引用该字段

## 风险评估

- **低风险**：该字段未被使用，删除不会影响现有功能
- **建议**：保留字段但标记为废弃，未来版本再删除

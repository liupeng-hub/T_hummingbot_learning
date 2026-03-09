---
name: "autofish-developer"
description: "Autofish V2 链式订单交易机器人开发助手。当用户需要开发、调试、测试或优化 autofish_bot_v2 项目时调用此技能。"
---

# Autofish V2 开发助手

此技能帮助开发者维护和扩展 Autofish V2 链式订单交易机器人项目。

## 项目概述

Autofish V2 是一个链式网格交易机器人，支持：
- **Binance 合约交易**（实盘和回测）
- **Longport 股票交易**（实盘和回测）
- **多种入场策略**（ATR、RSI、布林带等）
- **链式订单管理**（A1→A2→A3→A4）
- **止盈止损自动化**

## 项目结构

```
autofish_bot_v2/
├── autofish_core.py        # 核心逻辑（订单计算、状态管理）
├── binance_live.py         # Binance 实盘交易
├── binance_backtest.py     # Binance 回测
├── longport_live.py        # Longport 实盘交易
├── longport_backtest.py    # Longport 回测
├── tests/                  # 测试框架
│   ├── mocks/              # Mock 类
│   └── integration/        # 集成测试
├── docs/                   # 文档
└── autofish_output/        # 输出文件（配置、报告）
```

## 开发规范

### 代码风格

1. **类型注解**：所有函数必须有类型注解
2. **文档字符串**：使用中文文档字符串，说明参数和返回值
3. **日志记录**：使用 `logger.info/warning/error` 记录关键操作
4. **状态保存**：修改状态后必须调用 `_save_state()`

### 订单状态流转

```
pending（挂单中）→ filled（已成交）→ closed（已平仓）
                  ↓
              cancelled（已取消）
```

### 关键类

| 类名 | 文件 | 说明 |
|------|------|------|
| `Autofish_Order` | autofish_core.py | 订单数据类 |
| `Autofish_ChainState` | autofish_core.py | 链状态管理 |
| `Autofish_OrderCalculator` | autofish_core.py | 订单计算器 |
| `BinanceLiveTrader` | binance_live.py | Binance 实盘交易 |
| `AlgoHandler` | binance_live.py | ALGO 订单处理 |

## 常见开发任务

### 1. 添加新的入场策略

在 `autofish_core.py` 中：
1. 创建新的策略类，继承 `EntryStrategy`
2. 实现 `calculate_entry_price()` 方法
3. 在 `DEFAULT_ENTRY_STRATEGY` 中添加默认配置

### 2. 修改止盈止损逻辑

在 `binance_live.py` 中：
1. 修改 `AlgoHandler._handle_take_profit()` 和 `_handle_stop_loss()`
2. 确保更新订单状态字段：`closed_at`、`close_price`、`profit`
3. 调用 `_log_order_closed()` 打印日志

### 3. 添加新的测试用例

在 `tests/integration/` 中：
1. 使用 `MockBinanceClient` 和 `MockWebSocket`
2. 遵循现有测试模式
3. 运行 `python -m pytest tests/ -v` 验证

## 调试技巧

### 查看日志

```bash
tail -f logs/binance_live.log
tail -f logs/binance_live_error.log
```

### 检查状态文件

```bash
cat binance_live_state.json | python -m json.tool
```

### 运行测试

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

## 配置文件格式

```json
{
  "symbol": "BTCUSDT",
  "leverage": 10,
  "total_amount_quote": 5000,
  "grid_spacing": 0.01,
  "exit_profit": 0.01,
  "stop_loss": 0.08,
  "decay_factor": 0.5,
  "max_entries": 4,
  "weights": [0.0831, 0.2996, 0.3167, 0.1365, ...]
}
```

## 注意事项

1. **权重归一化**：下单金额使用 `normalize_weights()` 归一化后的权重
2. **WebSocket 事件**：
   - 普通订单：`ORDER_TRADE_UPDATE`
   - ALGO 订单：`ALGO_UPDATE`
3. **时间字段**：格式统一为 `%Y-%m-%d %H:%M:%S`
4. **价格精度**：使用 `Decimal` 类型，避免浮点数精度问题

## 相关文档

- [autofish_core_design.md](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/docs/autofish_core_design.md)
- [autofish_strategy.md](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/docs/autofish_strategy.md)
- [integration_test.md](file:///Users/liupeng/Documents/trae_projects/hummingbot_learning/autofish_bot_v2/docs/integration_test.md)

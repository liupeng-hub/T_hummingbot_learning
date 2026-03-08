# 代码注释补充计划

## 概述

当前代码库约 6000+ 行，缺少足够的注释和文档说明。本计划旨在为关键函数和类添加详细的注释。

## 文件分析

| 文件 | 行数 | 当前状态 |
|------|------|----------|
| autofish_core.py | ~1200 | 有基本注释，需要补充 |
| binance_live.py | ~2400 | 注释较少，需要大量补充 |
| binance_backtest.py | ~500 | 注释较少 |
| longport_live.py | ~1400 | 注释较少 |
| longport_backtest.py | ~550 | 注释较少 |

## 注释规范

### 函数注释格式

```python
async def _place_entry_order(self, order: Any, is_supplement: bool = False) -> None:
    """下单入场单
    
    创建并提交一个限价买入订单。如果订单金额小于 Binance 最小要求（100 USDT），
    会自动调整数量以满足要求。
    
    Args:
        order: 订单对象，包含入场价、数量等信息
        is_supplement: 是否为补下订单（状态恢复时补下）
    
    Returns:
        None
    
    Raises:
        BinanceAPIError: Binance API 错误
        NetworkError: 网络错误
    
    Side Effects:
        - 更新 order.order_id
        - 更新 order.quantity（可能被调整）
        - 更新 order.stake_amount
        - 保存状态到文件
        - 发送微信通知
    """
```

### 类注释格式

```python
class BinanceLiveTrader:
    """Binance 实盘交易器
    
    实现链式挂单策略的实盘交易，主要功能包括：
    
    1. 状态恢复：程序重启后从本地文件恢复订单状态
    2. 订单同步：与 Binance 同步订单状态
    3. 补单机制：检测并补充缺失的止盈止损单
    4. WebSocket 监听：实时监听订单状态变化
    5. 异常处理：错误重试和通知
    
    Flow:
        启动 -> 状态恢复 -> 补单检查 -> WebSocket 监听 -> 退出处理
    """
```

## 实施步骤

### 步骤 1: autofish_core.py 注释补充

**需要补充的类和方法：**

1. `Autofish_WeightCalculator` 类
   - `__init__()`: 初始化说明
   - `calculate_weights()`: 权重计算公式说明
   - `get_stake_amount()`: 金额计算说明
   - `get_weight_percentage()`: 权重百分比说明

2. `Autofish_OrderCalculator` 类
   - `__init__()`: 初始化说明
   - `calculate_prices()`: 价格计算说明
   - `create_order()`: 订单创建说明
   - `calculate_profit()`: 盈亏计算说明

3. `Autofish_AmplitudeAnalyzer` 类
   - `analyze()`: 分析主流程说明
   - `calculate_amplitude()`: 振幅计算说明
   - `calculate_probabilities()`: 概率计算说明
   - `calculate_expected_returns()`: 预期收益计算说明
   - `calculate_weights_for_decay()`: 权重计算说明
   - `save_to_file()`: 保存配置说明
   - `save_to_markdown()`: 保存报告说明

4. `Autofish_AmplitudeConfig` 类
   - `load()`: 加载配置说明
   - `load_latest()`: 加载最新配置说明
   - 各 getter 方法: 返回值说明

### 步骤 2: binance_live.py 注释补充

**需要补充的类和方法：**

1. `BinanceClient` 类
   - 类注释：REST API 客户端说明
   - `_sign_request()`: 签名说明
   - `_request()`: 请求说明
   - `place_order()`: 下单说明
   - `place_algo_order()`: 条件单说明
   - `get_order_status()`: 查询订单说明
   - `get_positions()`: 查询仓位说明
   - `get_open_algo_orders()`: 查询条件单说明

2. `AlgoHandler` 类
   - 类注释：Algo 条件单处理器说明
   - `handle_algo_triggered()`: 触发处理说明
   - `handle_algo_event()`: 事件处理说明

3. `BinanceLiveTrader` 类
   - 类注释：实盘交易主逻辑说明
   - `run()`: 主流程说明
   - `_restore_orders()`: 状态恢复流程说明
   - `_check_and_supplement_orders()`: 补单检查说明
   - `_place_entry_order()`: 入场单下单说明
   - `_place_exit_orders()`: 止盈止损单下单说明
   - `_place_tp_order()`: 止盈单下单说明
   - `_place_sl_order()`: 止损单下单说明
   - `_handle_order_filled()`: 订单成交处理说明
   - `_process_order_filled()`: 订单成交后处理说明
   - `_place_next_level_order()`: 下一级订单说明
   - `_ws_loop()`: WebSocket 主循环说明
   - `_handle_ws_message()`: 消息处理说明
   - `_adjust_quantity()`: 数量调整说明
   - `_adjust_price()`: 价格调整说明
   - `_create_order()`: 创建订单说明
   - `_handle_exit()`: 退出处理说明

4. 通知函数
   - `notify_entry_order()`: 入场单通知
   - `notify_entry_filled()`: 成交通知
   - `notify_take_profit()`: 止盈通知
   - `notify_stop_loss()`: 止损通知
   - `notify_critical_error()`: 错误通知

### 步骤 3: binance_backtest.py 注释补充

1. `BacktestEngine` 类
   - 类注释：回测引擎说明
   - `run()`: 回测主流程说明
   - `_process_kline()`: K线处理说明
   - `_check_entry_triggered()`: 入场检测说明
   - `_check_exit_triggered()`: 出场检测说明
   - `save_report()`: 报告生成说明

### 步骤 4: longport_live.py 注释补充

1. `LongPortClient` 类
   - 类注释：LongPort API 客户端说明
   - 主要方法注释

2. `LongPortLiveTrader` 类
   - 类注释：LongPort 实盘交易说明
   - 主要方法注释

### 步骤 5: longport_backtest.py 注释补充

1. `LongPortBacktestEngine` 类
   - 类注释：LongPort 回测引擎说明
   - 主要方法注释

## 预期成果

- 所有核心类和函数都有详细注释
- 代码可读性大幅提升
- 便于后续维护和扩展
- 新开发者能快速理解代码结构

## 优先级

1. **高优先级**: binance_live.py（核心实盘交易逻辑）
2. **中优先级**: autofish_core.py（核心算法）
3. **低优先级**: 回测模块和其他文件

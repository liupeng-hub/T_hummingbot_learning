# 集成测试框架

## 概述

本测试框架用于测试 Autofish V2 链式订单策略的核心逻辑，通过 Mock 方式模拟 Binance API、WebSocket 连接和市场数据，实现完整的链式下单、止盈止损触发、下一级订单下发等流程的测试。

## 目录结构

```
tests/
├── __init__.py
├── conftest.py                 # pytest 配置和 fixtures
├── mocks/
│   ├── __init__.py
│   ├── binance_client.py       # Binance API Mock
│   ├── websocket.py            # WebSocket Mock
│   └── market_data.py          # 市场数据 Mock
├── integration/
│   ├── __init__.py
│   ├── test_entry_flow.py      # 入场流程测试
│   ├── test_exit_flow.py       # 出场流程测试
│   └── test_multi_level.py     # 多层级订单测试
└── unit/
    └── __init__.py
```

## 安装依赖

```bash
pip install pytest pytest-asyncio
```

## 运行测试

### 运行所有测试

```bash
cd autofish_bot_v2
source venv/bin/activate
python -m pytest tests/ -v
```

### 运行特定测试文件

```bash
python -m pytest tests/integration/test_entry_flow.py -v
```

### 运行特定测试用例

```bash
python -m pytest tests/integration/test_entry_flow.py::TestEntryFlow::test_place_initial_order -v
```

### 生成测试覆盖率报告

```bash
pip install pytest-cov
python -m pytest tests/ -v --cov=. --cov-report=html
```

## Mock 类说明

### MockBinanceClient

模拟 Binance API 客户端，提供以下方法：

| 方法 | 说明 |
|------|------|
| `place_order()` | 模拟下单 |
| `place_tp_sl_order()` | 模拟下止盈止损单 |
| `cancel_order()` | 模拟取消订单 |
| `cancel_algo_order()` | 模拟取消 ALGO 订单 |
| `simulate_order_filled()` | 模拟订单成交 |
| `simulate_algo_triggered()` | 模拟 ALGO 订单触发 |
| `get_order_ws_message()` | 生成订单 WebSocket 消息 |
| `get_algo_ws_message()` | 生成 ALGO WebSocket 消息 |

### MockWebSocket

模拟 WebSocket 连接，提供以下方法：

| 方法 | 说明 |
|------|------|
| `connect()` | 模拟连接 |
| `send()` | 模拟发送消息 |
| `recv()` | 模拟接收消息 |
| `put_message()` | 放入模拟消息 |
| `put_raw_message()` | 放入原始消息 |
| `close()` | 模拟关闭连接 |

### MockMarketData

模拟市场数据，提供以下方法：

| 方法 | 说明 |
|------|------|
| `get_current_price()` | 获取当前价格 |
| `set_current_price()` | 设置当前价格 |
| `get_klines()` | 获取 K 线数据 |
| `simulate_price_drop()` | 模拟价格下跌 |
| `simulate_price_rise()` | 模拟价格上涨 |

## 测试用例说明

### 入场流程测试 (test_entry_flow.py)

| 测试用例 | 说明 |
|----------|------|
| `test_place_initial_order` | 测试下初始入场单 |
| `test_entry_filled_place_exit_orders` | 测试入场成交后下止盈止损单 |
| `test_entry_filled_place_next_level` | 测试入场成交后下下一级入场单 |
| `test_max_entries_limit` | 测试最大层级限制 |
| `test_normalized_weights` | 测试权重归一化 |
| `test_order_state_transition` | 测试订单状态转换 |

### 出场流程测试 (test_exit_flow.py)

| 测试用例 | 说明 |
|----------|------|
| `test_take_profit_trigger` | 测试止盈触发 |
| `test_stop_loss_trigger` | 测试止损触发 |
| `test_take_profit_place_new_a1` | 测试止盈后下新 A1 |
| `test_stop_loss_clear_all` | 测试止损后清空所有订单 |
| `test_profit_calculation` | 测试盈亏计算 |
| `test_holding_duration_calculation` | 测试持仓时长计算 |

### 多层级订单测试 (test_multi_level.py)

| 测试用例 | 说明 |
|----------|------|
| `test_a1_to_a2_flow` | 测试 A1 成交后下 A2 |
| `test_full_chain_flow` | 测试完整链式订单 A1->A2->A3->A4 |
| `test_a1_tp_cancels_a2` | 测试 A1 止盈取消 A2 |
| `test_weight_distribution` | 测试权重分配 |

## 编写新测试用例

### 基本模板

```python
import pytest
from decimal import Decimal
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from autofish_core import Autofish_Order, Autofish_ChainState, Autofish_OrderCalculator, normalize_weights
from binance_live import CloseReason
from tests.mocks.binance_client import MockBinanceClient
from tests.mocks.websocket import MockWebSocket
from tests.mocks.market_data import MockMarketData


class TestMyFeature:
    """我的功能测试"""
    
    @pytest.mark.asyncio
    async def test_my_case(self, mock_client, config):
        """测试我的用例"""
        # 1. 初始化
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        # 2. 创建订单
        order = order_calculator.create_order(
            level=1,
            base_price=Decimal("67000.00"),
            total_amount=config["total_amount_quote"],
            weights=config["weights"],
            max_entries=config["max_entries"]
        )
        
        # 3. 模拟下单
        result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=order.quantity,
            price=order.entry_price
        )
        
        # 4. 断言
        assert result["status"] == "NEW"
```

### 使用 Fixtures

在 `conftest.py` 中定义的 fixtures 可以直接在测试用例中使用：

```python
@pytest.mark.asyncio
async def test_with_fixtures(self, mock_client, mock_ws, mock_market_data, config):
    # mock_client: MockBinanceClient 实例
    # mock_ws: MockWebSocket 实例
    # mock_market_data: MockMarketData 实例
    # config: 配置字典
    pass
```

## 持续集成

可以在 CI/CD 流程中添加测试步骤：

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: |
          cd autofish_bot_v2
          pip install -r requirements.txt
          pip install pytest pytest-asyncio
      - name: Run tests
        run: |
          cd autofish_bot_v2
          python -m pytest tests/ -v
```

## 注意事项

1. **异步测试**：所有涉及异步操作的测试需要使用 `@pytest.mark.asyncio` 装饰器
2. **Mock 状态**：每个测试用例都会创建新的 Mock 实例，测试之间相互隔离
3. **价格精度**：使用 `Decimal` 类型处理价格，避免浮点数精度问题
4. **时间格式**：时间格式统一使用 `%Y-%m-%d %H:%M:%S`

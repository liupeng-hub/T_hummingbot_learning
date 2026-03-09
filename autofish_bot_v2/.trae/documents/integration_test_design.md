# 集成测试框架设计

## 背景

在多次修改和重构代码后，发现原来支持的功能可能变得不支持，代码稳定性难以维护。需要建立完整的集成测试框架，通过 mock 方式测试完整的链式订单流程。

## 策略概述

### 链式订单流程

```
启动程序
    ↓
下 A1 入场单（LIMIT 订单）
    ↓
等待 A1 成交
    ↓
A1 成交后：
├── 下止盈止损单（ALGO 订单）
├── 下 A2 入场单（LIMIT 订单）
└── 发送通知
    ↓
止盈触发：
├── 更新 A1 状态为 closed
├── 取消 A2 入场单
├── 取消 A1 止损单
├── 下新的 A1 入场单
└── 发送通知
    ↓
止损触发：
├── 更新 A1 状态为 closed
├── 取消 A2 入场单
├── 取消 A1 止盈单
├── 清空所有订单
└── 发送通知
```

### 订单状态流转

```
pending（挂单中）
    ↓ 成交
filled（已成交）
    ↓ 止盈/止损触发
closed（已平仓）
```

## 测试范围

### 1. 启动流程测试

- [ ] 程序启动，加载配置
- [ ] 创建 WebSocket 连接
- [ ] 下 A1 入场单成功

### 2. 入场成交流程测试

- [ ] A1 入场单成交
- [ ] 下止盈止损单成功
- [ ] 下 A2 入场单成功
- [ ] 状态保存正确

### 3. 止盈触发流程测试

- [ ] 收到止盈 ALGO_UPDATE 事件
- [ ] 更新 A1 状态为 closed
- [ ] 取消 A2 入场单
- [ ] 取消 A1 止损单
- [ ] 下新的 A1 入场单
- [ ] 发送通知

### 4. 止损触发流程测试

- [ ] 收到止损 ALGO_UPDATE 事件
- [ ] 更新 A1 状态为 closed
- [ ] 取消 A2 入场单
- [ ] 取消 A1 止盈单
- [ ] 清空所有订单
- [ ] 发送通知

### 5. 多层级订单测试

- [ ] A1 成交后下 A2
- [ ] A2 成交后下 A3
- [ ] A3 成交后下 A4
- [ ] A4 成交后不下 A5（max_entries=4）

### 6. 状态恢复测试

- [ ] 程序重启，恢复 pending 状态订单
- [ ] 程序重启，恢复 filled 状态订单
- [ ] 程序重启，检测已成交订单

### 7. 异常处理测试

- [ ] WebSocket 断开重连
- [ ] API 请求失败重试
- [ ] 订单不存在错误处理

## Mock 设计

### 1. Binance API Mock

```python
class MockBinanceClient:
    """模拟 Binance API 客户端"""
    
    def __init__(self):
        self.orders = {}  # orderId -> order_data
        self.algo_orders = {}  # algoId -> algo_data
        self.next_order_id = 10000000000
        self.next_algo_id = 20000000000
    
    async def place_order(self, symbol, side, type, quantity, price, **kwargs):
        """模拟下单"""
        order_id = self.next_order_id
        self.next_order_id += 1
        
        order = {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "type": type,
            "quantity": quantity,
            "price": price,
            "status": "NEW",
            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.orders[order_id] = order
        return order
    
    async def place_tp_sl_order(self, symbol, side, type, quantity, 
                                  trigger_price, price, **kwargs):
        """模拟下止盈止损单"""
        algo_id = self.next_algo_id
        self.next_algo_id += 1
        
        algo = {
            "algoId": algo_id,
            "symbol": symbol,
            "side": side,
            "type": type,
            "quantity": quantity,
            "triggerPrice": trigger_price,
            "price": price,
            "status": "NEW",
            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.algo_orders[algo_id] = algo
        return algo
    
    async def cancel_order(self, symbol, order_id):
        """模拟取消订单"""
        if order_id in self.orders:
            self.orders[order_id]["status"] = "CANCELED"
            return {"status": "CANCELED"}
        raise Exception(f"Order not found: {order_id}")
    
    async def cancel_algo_order(self, symbol, algo_id):
        """模拟取消 ALGO 订单"""
        if algo_id in self.algo_orders:
            self.algo_orders[algo_id]["status"] = "CANCELED"
            return {"status": "CANCELED"}
        raise Exception(f"Algo order not found: {algo_id}")
    
    def simulate_order_filled(self, order_id, filled_price):
        """模拟订单成交"""
        if order_id in self.orders:
            self.orders[order_id]["status"] = "FILLED"
            self.orders[order_id]["avgPrice"] = str(filled_price)
            return self.orders[order_id]
        return None
    
    def simulate_algo_triggered(self, algo_id):
        """模拟 ALGO 订单触发"""
        if algo_id in self.algo_orders:
            self.algo_orders[algo_id]["status"] = "FINISHED"
            return self.algo_orders[algo_id]
        return None
```

### 2. WebSocket Mock

```python
class MockWebSocket:
    """模拟 WebSocket 连接"""
    
    def __init__(self):
        self.messages = asyncio.Queue()
        self.connected = False
    
    async def connect(self):
        """模拟连接"""
        self.connected = True
    
    async def send(self, message):
        """模拟发送消息"""
        pass
    
    async def recv(self):
        """模拟接收消息"""
        return await self.messages.get()
    
    async def put_message(self, event_type, data):
        """放入模拟消息"""
        message = {
            "e": event_type,
            "o": data
        }
        await self.messages.put(message)
    
    async def close(self):
        """模拟关闭连接"""
        self.connected = False
```

### 3. 测试数据 Mock

```python
class MockMarketData:
    """模拟市场数据"""
    
    @staticmethod
    def get_current_price():
        """获取当前价格"""
        return Decimal("67000.00")
    
    @staticmethod
    def get_klines():
        """获取 K 线数据"""
        return [
            {"high": Decimal("67500"), "low": Decimal("66500")},
            {"high": Decimal("67200"), "low": Decimal("66800")},
        ]
```

## 测试用例设计

### 测试用例 1：完整止盈流程

```python
async def test_take_profit_flow():
    """测试完整止盈流程"""
    # 1. 初始化
    mock_client = MockBinanceClient()
    mock_ws = MockWebSocket()
    trader = BinanceLiveTrader(config, testnet=True)
    trader.client = mock_client
    
    # 2. 启动，下 A1 入场单
    await trader._place_initial_order()
    a1_order = trader.chain_state.orders[0]
    assert a1_order.state == "pending"
    assert a1_order.order_id is not None
    
    # 3. 模拟 A1 成交
    mock_client.simulate_order_filled(a1_order.order_id, a1_order.entry_price)
    await mock_ws.put_message("ORDER_TRADE_UPDATE", {
        "orderId": a1_order.order_id,
        "status": "FILLED",
        "avgPrice": str(a1_order.entry_price)
    })
    await trader._handle_ws_message(await mock_ws.recv())
    
    # 4. 验证止盈止损单已下
    assert a1_order.tp_order_id is not None
    assert a1_order.sl_order_id is not None
    assert a1_order.state == "filled"
    
    # 5. 验证 A2 入场单已下
    a2_order = trader.chain_state.orders[1]
    assert a2_order.state == "pending"
    
    # 6. 模拟止盈触发
    mock_client.simulate_algo_triggered(a1_order.tp_order_id)
    await mock_ws.put_message("ALGO_UPDATE", {
        "algoId": a1_order.tp_order_id,
        "status": "FINISHED",
        "avgPrice": str(a1_order.take_profit_price)
    })
    await trader._handle_ws_message(await mock_ws.recv())
    
    # 7. 验证状态
    assert a1_order.state == "closed"
    assert a1_order.close_reason == "take_profit"
    assert a1_order.close_price == a1_order.take_profit_price
    
    # 8. 验证 A2 已取消
    assert mock_client.orders[a2_order.order_id]["status"] == "CANCELED"
    
    # 9. 验证止损单已取消
    assert mock_client.algo_orders[a1_order.sl_order_id]["status"] == "CANCELED"
    
    # 10. 验证新的 A1 已下
    new_a1 = trader.chain_state.orders[0]
    assert new_a1.state == "pending"
    assert new_a1.level == 1
```

### 测试用例 2：完整止损流程

```python
async def test_stop_loss_flow():
    """测试完整止损流程"""
    # 类似止盈流程，但触发止损
    pass
```

### 测试用例 3：多层级订单

```python
async def test_multi_level_orders():
    """测试多层级订单"""
    # 测试 A1 -> A2 -> A3 -> A4 的完整流程
    pass
```

### 测试用例 4：状态恢复

```python
async def test_state_recovery():
    """测试状态恢复"""
    # 保存状态
    # 重启程序
    # 验证状态恢复正确
    pass
```

## 文件结构

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
│   ├── test_multi_level.py     # 多层级测试
│   └── test_recovery.py        # 状态恢复测试
└── unit/
    ├── __init__.py
    ├── test_order.py           # 订单单元测试
    └── test_chain_state.py     # 链状态单元测试
```

## 实施步骤

1. 创建测试目录结构
2. 实现 Mock 类
3. 编写集成测试用例
4. 编写单元测试用例
5. 配置 pytest
6. 运行测试验证

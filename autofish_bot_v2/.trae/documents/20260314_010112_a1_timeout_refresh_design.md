# A1 订单超时重挂功能设计

## 需求背景

当 A1 订单挂单后，如果行情持续上涨，价格一直无法达到 A1 的入场价格位置，导致 A1 长时间无法成交。需要增加超时机制：

1. A1 挂单超过指定时间（如 1 小时）未成交
2. 取消当前 A1 挂单
3. 使用当前价格重新计算 A1 入场价格
4. 重新挂单 A1

## Binance API 分析

**Binance 不支持直接修改订单价格**，需要：
1. 取消原订单 (`POST /fapi/v1/order`)
2. 创建新订单 (`POST /fapi/v1/order`)

因此实现方式为：**取消 → 重新创建**

## 方案A 详细评估：在 autofish_core.py 中统一实现

### 需要修改的内容

**1. Autofish_Order 类**：
- 已有 `created_at` 字段（字符串格式：'%Y-%m-%d %H:%M:%S'）
- **无需添加新字段**

**2. Autofish_ChainState 类**：添加 2 个方法

```python
def get_pending_a1(self) -> Optional['Autofish_Order']:
    """获取待成交的 A1 订单"""
    for order in self.orders:
        if order.level == 1 and order.state == "pending":
            return order
    return None

def check_a1_timeout(self, current_time: datetime, timeout_minutes: int = 60) -> Optional['Autofish_Order']:
    """检查 A1 是否超时
    
    参数:
        current_time: 当前时间
            - 回测：传入 K 线时间 (datetime.fromtimestamp(kline['open_time'] / 1000))
            - 实盘：传入 datetime.now()
        timeout_minutes: 超时分钟数
        
    返回:
        超时的 A1 订单，如果没有超时则返回 None
    """
    a1 = self.get_pending_a1()
    if not a1 or not a1.created_at:
        return None
    
    created = datetime.strptime(a1.created_at, '%Y-%m-%d %H:%M:%S')
    elapsed = (current_time - created).total_seconds() / 60
    
    if elapsed >= timeout_minutes:
        return a1
    return None
```

### 代价评估

| 项目 | 代价 | 说明 |
|------|------|------|
| 代码修改量 | **小** | 只需添加 2 个方法到 `Autofish_ChainState` |
| 影响范围 | **小** | 不影响现有功能，只是添加辅助方法 |
| 兼容性 | **好** | 回测和实盘都可以使用，只需传入不同的 `current_time` |
| 测试成本 | **低** | 只需测试新增的两个方法 |

### 各模块调用方式

**配置参数传递**：
- 超时时间从配置文件或命令行参数传入
- 配置参数：`a1_timeout_minutes`（默认 60 分钟，0 表示不启用）

**回测 (binance_backtest.py)**：
```python
# 从配置读取超时时间
self.a1_timeout_minutes = self.config.get('a1_timeout_minutes', 60)

# 在 K 线处理中检查
kline_time = datetime.fromtimestamp(kline['open_time'] / 1000)
timeout_a1 = self.chain_state.check_a1_timeout(kline_time, self.a1_timeout_minutes)
if timeout_a1:
    # 处理超时...
```

**实盘 (binance_live.py)**：
```python
# 从配置读取超时时间
self.a1_timeout_minutes = self.config.get('a1_timeout_minutes', 60)

# 在主循环中检查
timeout_a1 = self.chain_state.check_a1_timeout(datetime.now(), self.a1_timeout_minutes)
if timeout_a1:
    # 处理超时...
```

**命令行参数支持**：
```bash
# 回测时指定超时时间
python binance_backtest.py --symbol BTCUSDT --days 30 --a1-timeout 60

# 实盘时指定超时时间
python binance_live.py --symbol BTCUSDT --a1-timeout 60
```

### 结论

**推荐方案A**：在 `autofish_core.py` 中统一实现

理由：
1. 修改量小，只需添加 2 个辅助方法
2. 不影响现有功能
3. 回测和实盘都可以使用相同的接口
4. 各模块只需实现超时后的处理逻辑

## 实现方案对比

### 方案A：在 autofish_core.py 中统一实现 ✅ 推荐

**优点**：
- 代码复用，一处实现多处使用

**缺点**：
- 回测和实盘的时间处理方式不同
  - 回测：使用 K 线时间（虚拟时间）
  - 实盘：使用真实时间（datetime.now()）
- 需要修改核心类，影响范围大
- 回测框架（binance_backtest.py、longport_backtest.py、market_aware_backtest.py）逻辑差异较大

### 方案B：在各个模块中独立实现 ✅ 推荐

**优点**：
- 各模块可根据自身特点定制实现
- 不影响核心类稳定性
- 回测可灵活控制时间逻辑

**缺点**：
- 代码有一定重复

**建议选择方案B**，原因：
1. 回测和实盘的时间处理本质不同
2. 各模块已有独立的订单处理逻辑
3. 实现简单，风险可控

## 实现位置

| 模块 | 文件 | 实现位置 |
|------|------|----------|
| Binance 实盘 | `binance_live.py` | `BinanceLiveTrader` 类 |
| Binance 回测 | `binance_backtest.py` | `BinanceBacktestEngine` 类 |
| LongPort 实盘 | `longport_live.py` | `LongPortLiveTrader` 类 |
| LongPort 回测 | `longport_backtest.py` | `LongPortBacktestEngine` 类 |
| 行情感知回测 | `market_aware_backtest.py` | `MarketAwareBacktestEngine` 类 |

## 详细设计

### 1. autofish_core.py 修改

在 `Autofish_Order` 类中添加字段：

```python
@dataclass
class Autofish_Order:
    # 现有字段...
    
    # 新增字段
    a1_timeout_minutes: Optional[int] = None  # A1 超时时间（分钟），None 表示不超时
```

在 `Autofish_ChainState` 类中添加辅助方法：

```python
class Autofish_ChainState:
    # 现有方法...
    
    def get_pending_a1(self) -> Optional['Autofish_Order']:
        """获取待成交的 A1 订单"""
        for order in self.orders:
            if order.level == 1 and order.state == "pending":
                return order
        return None
    
    def check_a1_timeout(self, current_time: datetime, timeout_minutes: int = 60) -> Optional['Autofish_Order']:
        """检查 A1 是否超时
        
        参数:
            current_time: 当前时间
            timeout_minutes: 超时分钟数
            
        返回:
            超时的 A1 订单，如果没有超时则返回 None
        """
        a1 = self.get_pending_a1()
        if not a1 or not a1.created_at:
            return None
            
        created = datetime.strptime(a1.created_at, '%Y-%m-%d %H:%M:%S')
        elapsed = (current_time - created).total_seconds() / 60
        
        if elapsed >= timeout_minutes:
            return a1
        return None
```

### 2. binance_live.py 实现

在 `BinanceLiveTrader` 类中：

```python
class BinanceLiveTrader:
    def __init__(self, ...):
        # 现有初始化...
        self.a1_timeout_minutes = config.get('a1_timeout_minutes', 60)  # 默认 60 分钟
        self.last_a1_check_time = None
    
    async def _check_and_handle_a1_timeout(self):
        """检查并处理 A1 超时"""
        if self.a1_timeout_minutes <= 0:
            return
            
        now = datetime.now()
        
        # 每 5 分钟检查一次
        if self.last_a1_check_time:
            if (now - self.last_a1_check_time).total_seconds() < 300:
                return
        
        self.last_a1_check_time = now
        
        a1 = self.chain_state.check_a1_timeout(now, self.a1_timeout_minutes)
        if not a1:
            return
        
        logger.info(f"[A1 超时] A1 挂单已超过 {self.a1_timeout_minutes} 分钟未成交")
        print(f"\n{'='*60}")
        print(f"[{now.strftime('%H:%M:%S')}] ⏰ A1 超时重挂")
        print(f"{'='*60}")
        
        # 1. 取消原 A1 订单
        symbol = self.config.get("symbol", "BTCUSDT")
        if a1.order_id:
            try:
                await self.client.cancel_order(symbol, a1.order_id)
                logger.info(f"[取消 A1] orderId={a1.order_id}")
            except Exception as e:
                logger.warning(f"[取消 A1] 失败: {e}")
        
        # 2. 取消关联的止盈止损单
        if a1.tp_order_id:
            try:
                await self.client.cancel_algo_order(symbol, a1.tp_order_id)
            except:
                pass
        if a1.sl_order_id:
            try:
                await self.client.cancel_algo_order(symbol, a1.sl_order_id)
            except:
                pass
        
        # 3. 从链状态中移除原 A1
        self.chain_state.orders.remove(a1)
        
        # 4. 获取当前价格和 K 线
        current_price = await self._get_current_price()
        klines = await self._get_recent_klines()
        
        # 5. 创建新 A1 订单
        new_a1 = await self._create_order(1, current_price, klines)
        self.chain_state.orders.append(new_a1)
        
        logger.info(f"[新 A1] 入场价={new_a1.entry_price:.2f}")
        print(f"   新 A1 入场价: {new_a1.entry_price:.2f}")
        
        # 6. 下单
        await self._place_entry_order(new_a1, is_supplement=False)
        
        self._save_state()
```

在主循环中调用：

```python
async def run(self):
    # 现有代码...
    while True:
        # 现有逻辑...
        
        # 检查 A1 超时
        await self._check_and_handle_a1_timeout()
        
        # 其他逻辑...
```

### 3. binance_backtest.py 实现

```python
class BinanceBacktestEngine:
    def __init__(self, ...):
        # 现有初始化...
        self.a1_timeout_minutes = config.get('a1_timeout_minutes', 60)
    
    def _check_a1_timeout(self, current_kline_time: datetime) -> bool:
        """检查 A1 是否超时（回测版本）
        
        参数:
            current_kline_time: 当前 K 线时间
            
        返回:
            是否需要重挂 A1
        """
        if self.a1_timeout_minutes <= 0:
            return False
        
        a1 = self.chain_state.get_pending_a1()
        if not a1 or not a1.created_at:
            return False
        
        created = datetime.strptime(a1.created_at, '%Y-%m-%d %H:%M:%S')
        elapsed = (current_kline_time - created).total_seconds() / 60
        
        return elapsed >= self.a1_timeout_minutes
    
    def _handle_a1_timeout(self, current_price: Decimal, current_time: datetime):
        """处理 A1 超时"""
        a1 = self.chain_state.get_pending_a1()
        if not a1:
            return
        
        logger.info(f"[A1 超时] A1 挂单已超过 {self.a1_timeout_minutes} 分钟未成交")
        print(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] ⏰ A1 超时重挂")
        
        # 移除原 A1
        self.chain_state.orders.remove(a1)
        
        # 创建新 A1
        new_a1 = self._create_order(1, current_price)
        self.chain_state.orders.append(new_a1)
        
        logger.info(f"[新 A1] 入场价={new_a1.entry_price:.2f}")
        print(f"   新 A1 入场价: {new_a1.entry_price:.2f}")
    
    async def run(self, ...):
        # 在 K 线遍历循环中
        for kline in klines:
            kline_time = datetime.fromtimestamp(kline['open_time'] / 1000)
            current_price = Decimal(str(kline['close']))
            
            # 检查 A1 超时（在处理入场之前）
            if self._check_a1_timeout(kline_time):
                self._handle_a1_timeout(current_price, kline_time)
            
            # 现有逻辑...
```

### 4. 配置参数

在振幅配置 JSON 中添加：

```json
{
  "d_0.5": {
    "grid_spacing": "0.01",
    "exit_profit": "0.01",
    "stop_loss": "0.08",
    "a1_timeout_minutes": 60,  // 新增：A1 超时时间（分钟），0 表示不启用
    ...
  }
}
```

## 执行步骤

### 阶段1: 修改 autofish_core.py
1. 在 `Autofish_Order` 中添加 `a1_timeout_minutes` 字段
2. 在 `Autofish_ChainState` 中添加 `get_pending_a1()` 方法
3. 在 `Autofish_ChainState` 中添加 `check_a1_timeout()` 方法

### 阶段2: 修改 binance_live.py（实盘）
1. 添加 `a1_timeout_minutes` 配置读取
2. 实现 `_check_and_handle_a1_timeout()` 方法
3. 在主循环中调用超时检查

### 阶段3: 修改 binance_backtest.py（回测）
1. 添加 `a1_timeout_minutes` 配置读取
2. 实现 `_check_a1_timeout()` 方法
3. 实现 `_handle_a1_timeout()` 方法
4. 在 K 线遍历中调用超时检查

### 阶段4: 修改其他模块
1. longport_live.py
2. longport_backtest.py
3. **market_aware_backtest.py**（行情感知回测）- 同样需要 A1 超时重挂功能
   - 在 `_on_kline()` 方法中添加 A1 超时检查
   - 超时后调用 `_create_first_order()` 重新创建 A1

### 阶段5: 更新配置和文档
1. 更新振幅配置 JSON 示例
2. 更新 README.md

## 测试计划

1. **单元测试**：测试 `check_a1_timeout()` 方法
2. **回测验证**：使用历史数据验证超时重挂逻辑
3. **实盘测试**：在测试网验证功能

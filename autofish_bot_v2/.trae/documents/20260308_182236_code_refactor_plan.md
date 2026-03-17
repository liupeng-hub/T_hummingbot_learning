# 代码重构计划 - 整合长代码到函数

## 问题分析

### 问题 1: 资金检查代码太长

`run()` 方法中的资金检查代码（约 85 行）太长，影响可读性。

**当前代码位置**: `binance_live.py` 第 2296-2381 行

**包含内容**:
- 预检查最小金额要求
- 严重告警处理（资金不满足）
- 警告处理（资金储备不足）
- 配置确认处理（资金充足）

### 问题 2: 补单逻辑太长

`run()` 方法中的补单逻辑（约 25 行）较长，可以提取为独立方法。

**当前代码位置**: `binance_live.py` 第 2385-2409 行

**包含内容**:
- 检查是否需要补下入场单
- 创建并下新订单

## 解决方案

### 方案 1: 整合资金检查到 `_check_fund_sufficiency()` 方法

```python
async def _check_fund_sufficiency(self) -> bool:
    """检查资金是否充足
    
    返回:
        True: 资金满足要求，继续运行
        False: 资金不满足要求，需要退出
    """
    satisfied, check_result = self._check_min_notional()
    
    if not satisfied:
        # 严重告警：资金不满足最小要求，退出程序
        ...
        return False
    
    # 检查资金是否充足（建议为最小资金的1.5倍）
    ...
    
    return True
```

### 方案 2: 整合补单逻辑到 `_handle_order_supplement()` 方法

```python
async def _handle_order_supplement(self, current_price: Decimal, need_new_order: bool) -> None:
    """处理订单补充逻辑
    
    参数:
        current_price: 当前价格
        need_new_order: 是否需要新订单
    """
    if not need_new_order:
        await self._check_and_supplement_orders()
        
        # 检查是否需要补下入场单
        filled_orders = [o for o in self.chain_state.orders if o.state == "filled"]
        pending_orders = [o for o in self.chain_state.orders if o.state == "pending"]
        
        if filled_orders:
            max_filled_level = max(o.level for o in filled_orders)
            max_level = self.config.get("max_entries", 4)
            next_level = max_filled_level + 1
            
            has_next_pending = any(o.level == next_level for o in pending_orders)
            
            if next_level <= max_level and not has_next_pending:
                new_order = self._create_order(next_level, current_price)
                self.chain_state.orders.append(new_order)
                print(f"\n{'='*60}")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 📥 入场单补下: A{next_level}")
                print(f"{'='*60}")
                await self._place_entry_order(new_order, is_supplement=True)
    
    if need_new_order:
        order = self._create_order(1, current_price)
        self.chain_state = ChainState(base_price=current_price, orders=[order])
        await self._place_entry_order(order)
```

## 实施步骤

### 步骤 1: 添加 `_check_fund_sufficiency()` 方法

在 `_check_min_notional()` 方法之后添加新方法，包含资金检查的所有逻辑。

### 步骤 2: 添加 `_handle_order_supplement()` 方法

在 `_check_and_supplement_orders()` 方法之后添加新方法。

### 步骤 3: 简化 `run()` 方法

将原来的长代码替换为方法调用：

```python
# 预检查资金是否充足
if not await self._check_fund_sufficiency():
    await self.client.close()
    return

# 处理订单补充
await self._handle_order_supplement(current_price, need_new_order)
```

## 预期成果

### 重构前 `run()` 方法

约 150 行，包含大量资金检查和补单逻辑。

### 重构后 `run()` 方法

约 50 行，逻辑清晰：

```python
async def run(self) -> None:
    ...
    
    try:
        while self.running:
            try:
                await self._init_precision()
                current_price = await self._get_current_price()
                notify_startup(self.config, current_price)
                
                # 预检查资金是否充足
                if not await self._check_fund_sufficiency():
                    await self.client.close()
                    return
                
                need_new_order = await self._restore_orders(current_price)
                
                # 处理订单补充
                await self._handle_order_supplement(current_price, need_new_order)
                
                self.consecutive_errors = 0
                await self._ws_loop()
                ...
```

## 新增方法说明

### `_check_fund_sufficiency()`

- **功能**: 检查资金是否充足，发送相应通知
- **返回**: True（继续运行）/ False（退出程序）
- **副作用**: 发送微信通知、打印控制台信息

### `_handle_order_supplement()`

- **功能**: 处理订单补充逻辑
- **参数**: current_price, need_new_order
- **副作用**: 创建订单、下单、更新状态

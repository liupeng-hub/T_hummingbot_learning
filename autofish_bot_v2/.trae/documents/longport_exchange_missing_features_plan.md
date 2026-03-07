# longport_exchange.py 缺失功能适配合入计划

## 概述

根据功能对比分析，`longport_exchange.py` 缺失以下需要从 `longport_live.py` 适配合入的功能。

---

## 缺失功能清单

### 1. FlushFileHandler 类 ⚠️ 重要

**位置**: `longport_live.py` L64-68

**功能**: 每次日志写入后自动刷新到磁盘，确保日志实时持久化

**现状**: `longport_exchange.py` 使用普通 `logging.FileHandler`，日志可能在程序崩溃时丢失

**适配方案**:
```python
class FlushFileHandler(logging.FileHandler):
    """每次写入后自动刷新的 FileHandler"""
    def emit(self, record):
        super().emit(record)
        self.flush()
```

**修改位置**: 在 `setup_logger()` 函数中使用 `FlushFileHandler` 替代普通 `FileHandler`

---

### 2. _get_quantity() 方法 ⚠️ 重要

**位置**: `longport_live.py` L279-292

**功能**: 根据金额和价格计算股票数量，考虑不同市场的整手要求

**现状**: `longport_exchange.py` 使用 `_adjust_quantity()` 方法，但逻辑略有不同

**差异分析**:
- live: `_get_quantity(stake_amount, price, symbol)` - 根据金额计算
- exchange: `_adjust_quantity(quantity)` - 根据已有数量调整

**适配方案**: 添加 `_get_quantity()` 方法，保留 `_adjust_quantity()` 用于调整

```python
def _get_quantity(self, stake_amount: Decimal, price: Decimal) -> int:
    """获取股票数量（股票交易需要整数股）"""
    quantity = stake_amount / price
    return int(quantity // self.lot_size) * self.lot_size
```

---

### 3. _execute_entry() 方法 ⚠️ 建议

**位置**: `longport_live.py` L417-433

**功能**: 独立的入场执行方法，处理入场成交后的逻辑

**现状**: `longport_exchange.py` 没有单独实现，入场逻辑分散在价格监控中

**适配方案**: 添加独立的入场执行方法

```python
async def _execute_entry(self, order: Any, current_price: Decimal) -> None:
    """执行入场"""
    order.state = "filled"
    
    logger.info(f"[入场成交] A{order.level}: 价格={current_price:.2f}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ A{order.level} 成交: 价格={current_price:.2f}")
    
    notify_entry_filled(order, current_price, Decimal("0"), self.config)
    
    await self._place_exit_orders(order)
    
    next_level = order.level + 1
    max_level = self.config.get("max_entries", 4)
    if next_level <= max_level:
        new_order = self._create_order(next_level, order.entry_price)
        self.chain_state.orders.append(new_order)
        await self._place_entry_order(new_order)
```

---

### 4. 账户余额显示 ⚠️ 建议

**位置**: `longport_live.py` L540-544

**功能**: 在启动时显示账户余额信息

**现状**: `longport_exchange.py` 没有显示账户余额

**适配方案**: 在 `run()` 方法中添加账户余额获取和显示

```python
balance = self.trade_ctx.account_balance()
if balance:
    for item in balance:
        if item.currency == self._get_currency():
            print(f"   账户余额: {item.available_cash:.2f} {item.currency}")
```

---

### 5. main() 入口函数 ⚠️ 建议

**位置**: `longport_live.py` L577-594

**功能**: 提供完整的命令行入口，支持参数解析

**现状**: `longport_exchange.py` 没有 main() 函数

**适配方案**: 添加 main() 函数和 `__main__` 入口

```python
async def main():
    """主函数"""
    import argparse
    from dotenv import load_dotenv
    
    parser = argparse.ArgumentParser(description="Autofish V1 LongPort 实盘交易")
    parser.add_argument("--symbol", type=str, default="700.HK", help="交易对 (默认: 700.HK)")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="止损比例 (默认: 0.08)")
    parser.add_argument("--total-amount", type=float, default=1200, help="总投入金额 (默认: 1200)")
    parser.add_argument("--decay-factor", type=float, default=0.5, help="衰减因子 (默认: 0.5)")
    parser.add_argument("--no-amplitude", action="store_true", help="不使用振幅配置")
    
    args = parser.parse_args()
    
    load_dotenv()
    
    config = {
        "symbol": args.symbol,
        "stop_loss": Decimal(str(args.stop_loss)),
        "total_amount_quote": Decimal(str(args.total_amount)),
        "decay_factor": args.decay_factor,
        "grid_spacing": Decimal("0.01"),
        "exit_profit": Decimal("0.01"),
        "max_entries": 4,
        "app_key": os.getenv("LONGPORT_APP_KEY", ""),
        "app_secret": os.getenv("LONGPORT_APP_SECRET", ""),
        "access_token": os.getenv("LONGPORT_ACCESS_TOKEN", ""),
    }
    
    trader = LongPortLiveTrader(config, use_amplitude_config=not args.no_amplitude)
    await trader.run()


if __name__ == "__main__":
    asyncio.run(main())
```

---

### 6. 价格监控间隔统一 ⚠️ 建议

**位置**: 
- `longport_live.py` L411: `await asyncio.sleep(5)`
- `longport_exchange.py` L1052: `await asyncio.sleep(1)`

**差异**: live 使用 5 秒间隔，exchange 使用 1 秒间隔

**建议**: 保持 1 秒间隔（exchange 当前实现），因为：
1. 响应更快，减少滑点
2. LongPort API 调用频率限制较宽松
3. 股票市场波动相对较慢，1 秒间隔合理

---

### 7. 环境变量加载 ⚠️ 重要

**位置**: `longport_live.py` L56-57

**功能**: 加载 .env 文件中的环境变量

**现状**: `longport_exchange.py` 没有显式加载 .env 文件

**适配方案**: 在 main() 函数中添加 `load_dotenv()`

---

### 8. 全局常量定义 ⚠️ 建议

**位置**: `longport_live.py` L54-62

**功能**: 定义 PROJECT_DIR、LOG_DIR、ENV_FILE、LOG_FILE、STATE_FILE 等常量

**现状**: `longport_exchange.py` 使用动态路径

**建议**: 保持 exchange 当前实现，因为：
1. 使用 StateRepository 动态生成状态文件路径更灵活
2. setup_logger 支持自定义日志路径
3. 支持多交易对独立状态文件

---

## 实施优先级

| 优先级 | 功能 | 重要性 | 复杂度 |
|--------|------|--------|--------|
| P0 | FlushFileHandler 类 | 高 | 低 |
| P0 | _get_quantity() 方法 | 高 | 低 |
| P1 | main() 入口函数 | 中 | 中 |
| P1 | 环境变量加载 | 中 | 低 |
| P2 | _execute_entry() 方法 | 中 | 低 |
| P2 | 账户余额显示 | 低 | 低 |

---

## 实施步骤

### 步骤 1: 添加 FlushFileHandler 类
1. 在日志配置部分添加 `FlushFileHandler` 类定义
2. 修改 `setup_logger()` 函数使用 `FlushFileHandler`

### 步骤 2: 添加 _get_quantity() 方法
1. 在 `LongPortLiveTrader` 类中添加 `_get_quantity()` 方法
2. 修改 `_place_entry_order()` 使用新方法

### 步骤 3: 添加 main() 入口函数
1. 在文件末尾添加 `main()` 异步函数
2. 添加 `__main__` 入口
3. 添加 argparse 参数解析

### 步骤 4: 添加环境变量加载
1. 在 main() 函数中添加 `load_dotenv()`
2. 确保环境变量正确传递

### 步骤 5: 添加 _execute_entry() 方法
1. 在 `LongPortLiveTrader` 类中添加 `_execute_entry()` 方法
2. 在价格监控中调用该方法

### 步骤 6: 添加账户余额显示
1. 在 `run()` 方法中添加账户余额获取
2. 显示余额信息

---

## 验证方案

1. **单元测试**: 为新增方法编写单元测试
2. **集成测试**: 运行完整的交易流程测试
3. **日志验证**: 确认日志实时写入磁盘
4. **命令行测试**: 验证 main() 函数参数解析正确

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| FlushFileHandler 性能影响 | 低 | 仅在日志写入时刷新，影响极小 |
| _get_quantity 计算错误 | 高 | 添加单元测试验证计算逻辑 |
| main() 参数解析错误 | 中 | 添加参数验证和默认值 |

---

## 预期结果

完成适配后，`longport_exchange.py` 将具备：
1. ✅ 日志实时持久化能力
2. ✅ 完整的股票数量计算逻辑
3. ✅ 独立运行入口（命令行支持）
4. ✅ 环境变量自动加载
5. ✅ 入场执行独立方法
6. ✅ 账户余额显示

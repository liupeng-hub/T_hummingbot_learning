# 添加 Always Ranging 行情策略计划

## 目标
在 `market_aware_backtest.py` 中增加一个行情策略，此策略始终返回"震荡行情"状态，用于与原 `binance_backtest` 的测试结果对比。

## 背景
当前 `market_status_detector.py` 中已有以下算法：
- `realtime`: 实时市场状态判断算法（价格行为+波动率）
- `adx`: 基于 ADX 的趋势强度判断
- `composite`: ADX + ATR + 布林带宽度组合判断

需要新增 `always_ranging` 算法，始终返回 `MarketStatus.RANGING`，用于对比测试。

## 实现步骤

### 步骤 1: 在 `market_status_detector.py` 中添加 `AlwaysRangingAlgorithm` 类

位置：在 `RealTimeStatusAlgorithm` 类之前添加

```python
class AlwaysRangingAlgorithm(StatusAlgorithm):
    """始终返回震荡行情的算法
    
    用于与原 binance_backtest 的测试结果对比
    """
    
    name = "always_ranging"
    description = "始终返回震荡行情（用于对比测试）"
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        return StatusResult(
            status=MarketStatus.RANGING,
            confidence=1.0,
            indicators={},
            reason="始终震荡模式（对比测试）"
        )
    
    def get_required_periods(self) -> int:
        return 1  # 最小需求，只需要1根K线
```

### 步骤 2: 在 `MarketStatusDetector.ALGORITHMS` 字典中注册新算法

位置：`MarketStatusDetector.ALGORITHMS` 字典（约第821行）

```python
ALGORITHMS = {
    'realtime': RealTimeStatusAlgorithm,
    'adx': ADXAlgorithm,
    'composite': CompositeAlgorithm,
    'always_ranging': AlwaysRangingAlgorithm,  # 新增
}
```

### 步骤 3: 更新 `market_aware_backtest.py` 的 `_create_algorithm` 方法

位置：`_create_algorithm` 方法（约第138-157行）

```python
def _create_algorithm(self) -> StatusAlgorithm:
    algo_name = self.market_config.get('algorithm', 'realtime')
    
    if algo_name == 'realtime':
        return RealTimeStatusAlgorithm({...})
    elif algo_name == 'always_ranging':  # 新增
        return AlwaysRangingAlgorithm()
    else:
        from market_status_detector import ADXAlgorithm, CompositeAlgorithm
        if algo_name == 'adx':
            return ADXAlgorithm()
        else:
            return CompositeAlgorithm()
```

### 步骤 4: 更新命令行参数帮助信息

位置：`main()` 函数中的 `--market-algorithm` 参数（约第745行）

更新 choices 列表以包含 `always_ranging`。

## 使用方式

```bash
# 使用 always_ranging 算法运行回测（等同于原 binance_backtest）
python market_aware_backtest.py --symbol BTCUSDT --days 30 --market-algorithm always_ranging

# 对比测试：使用默认 realtime 算法
python market_aware_backtest.py --symbol BTCUSDT --days 30 --market-algorithm realtime
```

## 预期结果

- 使用 `always_ranging` 算法时，回测引擎将始终认为市场处于震荡状态
- 交易行为与原 `binance_backtest` 一致（不会因趋势行情而停止交易）
- 可用于对比"行情感知"与"始终交易"策略的差异

## 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `market_status_detector.py` | 添加 `AlwaysRangingAlgorithm` 类，注册到 `ALGORITHMS` 字典 |
| `market_aware_backtest.py` | 更新 `_create_algorithm` 方法，更新命令行参数 |

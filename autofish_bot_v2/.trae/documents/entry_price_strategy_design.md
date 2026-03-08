# A1 入场价格策略模式设计

## 一、设计目标

设计一个可扩展的策略模式，让用户可以通过配置选择不同的 A1 入场价格计算策略。

## 二、策略模式设计

### 2.1 策略接口定义

```python
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional

class EntryPriceStrategy(ABC):
    """入场价格策略基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        pass
    
    @abstractmethod
    def calculate_entry_price(
        self,
        current_price: Decimal,
        level: int,
        grid_spacing: Decimal,
        klines: Optional[List[Dict]] = None,
        **kwargs
    ) -> Decimal:
        """计算入场价格
        
        参数:
            current_price: 当前价格
            level: 层级
            grid_spacing: 网格间距
            klines: K 线数据
            **kwargs: 其他参数
            
        返回:
            入场价格
        """
        pass
```

### 2.2 策略实现

#### 策略 1: 固定网格间距策略（默认）

```python
class FixedGridStrategy(EntryPriceStrategy):
    """固定网格间距策略
    
    使用固定的网格间距计算入场价格。
    入场价格 = 当前价格 × (1 - 网格间距 × 层级)
    """
    
    @property
    def name(self) -> str:
        return "fixed"
    
    def calculate_entry_price(
        self,
        current_price: Decimal,
        level: int,
        grid_spacing: Decimal,
        klines: Optional[List[Dict]] = None,
        **kwargs
    ) -> Decimal:
        return current_price * (Decimal("1") - grid_spacing * level)
```

#### 策略 2: ATR 动态策略

```python
class ATRDynamicStrategy(EntryPriceStrategy):
    """ATR 动态策略
    
    基于 ATR（平均真实波幅）动态计算入场价格。
    网格间距 = ATR × 乘数 / 当前价格
    """
    
    def __init__(
        self,
        atr_period: int = 14,
        atr_multiplier: Decimal = Decimal("0.5"),
        min_spacing: Decimal = Decimal("0.005"),
        max_spacing: Decimal = Decimal("0.03")
    ):
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.min_spacing = min_spacing
        self.max_spacing = max_spacing
    
    @property
    def name(self) -> str:
        return "atr"
    
    def calculate_entry_price(
        self,
        current_price: Decimal,
        level: int,
        grid_spacing: Decimal,
        klines: Optional[List[Dict]] = None,
        **kwargs
    ) -> Decimal:
        if not klines or len(klines) < self.atr_period + 1:
            return current_price * (Decimal("1") - grid_spacing * level)
        
        atr = self._calculate_atr(klines)
        if atr == 0:
            return current_price * (Decimal("1") - grid_spacing * level)
        
        atr_percent = atr / current_price
        dynamic_spacing = atr_percent * self.atr_multiplier
        dynamic_spacing = max(self.min_spacing, min(self.max_spacing, dynamic_spacing))
        
        return current_price * (Decimal("1") - dynamic_spacing * level)
    
    def _calculate_atr(self, klines: List[Dict]) -> Decimal:
        """计算 ATR"""
        tr_list = []
        for i in range(1, self.atr_period + 1):
            high = Decimal(str(klines[-i]['high']))
            low = Decimal(str(klines[-i]['low']))
            prev_close = Decimal(str(klines[-i-1]['close']))
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
        return sum(tr_list) / len(tr_list)
```

#### 策略 3: 布林带策略

```python
class BollingerBandStrategy(EntryPriceStrategy):
    """布林带策略
    
    将入场价格设置在布林带下轨附近。
    入场价格 = max(下轨, 当前价格 × (1 - 最小间距))
    """
    
    def __init__(
        self,
        period: int = 20,
        std_multiplier: Decimal = Decimal("2"),
        min_spacing: Decimal = Decimal("0.005")
    ):
        self.period = period
        self.std_multiplier = std_multiplier
        self.min_spacing = min_spacing
    
    @property
    def name(self) -> str:
        return "bollinger"
    
    def calculate_entry_price(
        self,
        current_price: Decimal,
        level: int,
        grid_spacing: Decimal,
        klines: Optional[List[Dict]] = None,
        **kwargs
    ) -> Decimal:
        if not klines or len(klines) < self.period:
            return current_price * (Decimal("1") - grid_spacing * level)
        
        lower_band = self._calculate_lower_band(klines)
        min_entry = current_price * (Decimal("1") - self.min_spacing)
        
        # 取布林带下轨和最小间距的较高值
        entry_price = max(lower_band, min_entry)
        
        # 确保入场价格低于当前价格
        if entry_price >= current_price:
            entry_price = min_entry
        
        return entry_price
    
    def _calculate_lower_band(self, klines: List[Dict]) -> Decimal:
        """计算布林带下轨"""
        closes = [Decimal(str(k['close'])) for k in klines[-self.period:]]
        middle = sum(closes) / self.period
        variance = sum([(c - middle) ** 2 for c in closes]) / self.period
        std = variance.sqrt()
        return middle - self.std_multiplier * std
```

#### 策略 4: 支撑位策略

```python
class SupportLevelStrategy(EntryPriceStrategy):
    """支撑位策略
    
    将入场价格设置在最近支撑位附近。
    支撑位 = 最近 N 根 K 线的最低价
    """
    
    def __init__(
        self,
        lookback: int = 20,
        min_spacing: Decimal = Decimal("0.005")
    ):
        self.lookback = lookback
        self.min_spacing = min_spacing
    
    @property
    def name(self) -> str:
        return "support"
    
    def calculate_entry_price(
        self,
        current_price: Decimal,
        level: int,
        grid_spacing: Decimal,
        klines: Optional[List[Dict]] = None,
        **kwargs
    ) -> Decimal:
        if not klines or len(klines) < self.lookback:
            return current_price * (Decimal("1") - grid_spacing * level)
        
        support = self._find_support(klines)
        min_entry = current_price * (Decimal("1") - self.min_spacing)
        
        # 取支撑位和最小间距的较高值
        entry_price = max(support, min_entry)
        
        # 确保入场价格低于当前价格
        if entry_price >= current_price:
            entry_price = min_entry
        
        return entry_price
    
    def _find_support(self, klines: List[Dict]) -> Decimal:
        """找到最近支撑位"""
        lows = [Decimal(str(k['low'])) for k in klines[-self.lookback:]]
        return min(lows)
```

#### 策略 5: 综合策略（推荐）

```python
class CompositeStrategy(EntryPriceStrategy):
    """综合策略
    
    综合多种技术指标，找到最优入场价格。
    入场价格 = max(布林带下轨, 支撑位, ATR 动态价格)
    """
    
    def __init__(self):
        self.atr_strategy = ATRDynamicStrategy()
        self.bollinger_strategy = BollingerBandStrategy()
        self.support_strategy = SupportLevelStrategy()
    
    @property
    def name(self) -> str:
        return "composite"
    
    def calculate_entry_price(
        self,
        current_price: Decimal,
        level: int,
        grid_spacing: Decimal,
        klines: Optional[List[Dict]] = None,
        **kwargs
    ) -> Decimal:
        if not klines:
            return current_price * (Decimal("1") - grid_spacing * level)
        
        # 计算各种策略的入场价格
        atr_price = self.atr_strategy.calculate_entry_price(
            current_price, level, grid_spacing, klines
        )
        bollinger_price = self.bollinger_strategy.calculate_entry_price(
            current_price, level, grid_spacing, klines
        )
        support_price = self.support_strategy.calculate_entry_price(
            current_price, level, grid_spacing, klines
        )
        
        # 取最高值（最接近当前价格）
        entry_price = max(atr_price, bollinger_price, support_price)
        
        # 确保入场价格低于当前价格
        min_entry = current_price * (Decimal("1") - Decimal("0.005"))
        if entry_price >= current_price:
            entry_price = min_entry
        
        return entry_price
```

### 2.3 策略工厂

```python
class EntryPriceStrategyFactory:
    """入场价格策略工厂"""
    
    _strategies = {
        "fixed": FixedGridStrategy,
        "atr": ATRDynamicStrategy,
        "bollinger": BollingerBandStrategy,
        "support": SupportLevelStrategy,
        "composite": CompositeStrategy,
    }
    
    @classmethod
    def create(cls, strategy_name: str, **kwargs) -> EntryPriceStrategy:
        """创建策略实例
        
        参数:
            strategy_name: 策略名称
            **kwargs: 策略参数
            
        返回:
            策略实例
        """
        if strategy_name not in cls._strategies:
            logger.warning(f"未知策略: {strategy_name}，使用默认策略")
            return FixedGridStrategy()
        
        strategy_class = cls._strategies[strategy_name]
        return strategy_class(**kwargs)
    
    @classmethod
    def register(cls, name: str, strategy_class: type):
        """注册新策略
        
        参数:
            name: 策略名称
            strategy_class: 策略类
        """
        cls._strategies[name] = strategy_class
    
    @classmethod
    def list_strategies(cls) -> List[str]:
        """列出所有可用策略"""
        return list(cls._strategies.keys())
```

## 三、配置文件格式

### 3.1 配置示例

```json
{
  "symbol": "BTCUSDT",
  "total_amount_quote": 5000,
  "leverage": 10,
  "max_entries": 4,
  "grid_spacing": 0.01,
  "exit_profit": 0.01,
  "stop_loss": 0.08,
  
  "entry_price_strategy": {
    "name": "atr",
    "params": {
      "atr_period": 14,
      "atr_multiplier": 0.5,
      "min_spacing": 0.005,
      "max_spacing": 0.03
    }
  }
}
```

### 3.2 不同策略配置

**固定网格策略**：
```json
{
  "entry_price_strategy": {
    "name": "fixed"
  }
}
```

**ATR 动态策略**：
```json
{
  "entry_price_strategy": {
    "name": "atr",
    "params": {
      "atr_period": 14,
      "atr_multiplier": 0.5,
      "min_spacing": 0.005,
      "max_spacing": 0.03
    }
  }
}
```

**布林带策略**：
```json
{
  "entry_price_strategy": {
    "name": "bollinger",
    "params": {
      "period": 20,
      "std_multiplier": 2,
      "min_spacing": 0.005
    }
  }
}
```

**支撑位策略**：
```json
{
  "entry_price_strategy": {
    "name": "support",
    "params": {
      "lookback": 20,
      "min_spacing": 0.005
    }
  }
}
```

**综合策略**：
```json
{
  "entry_price_strategy": {
    "name": "composite"
  }
}
```

## 四、代码集成

### 4.1 修改 Autofish_OrderCalculator

```python
class Autofish_OrderCalculator:
    """订单计算器"""
    
    def __init__(
        self,
        grid_spacing: Decimal = Decimal("0.01"),
        exit_profit: Decimal = Decimal("0.01"),
        stop_loss: Decimal = Decimal("0.08"),
        leverage: Decimal = Decimal("10"),
        entry_strategy: Optional[EntryPriceStrategy] = None
    ):
        self.grid_spacing = grid_spacing
        self.exit_profit = exit_profit
        self.stop_loss = stop_loss
        self.leverage = leverage
        self.entry_strategy = entry_strategy or FixedGridStrategy()
    
    def calculate_entry_price(
        self,
        current_price: Decimal,
        level: int,
        klines: Optional[List[Dict]] = None
    ) -> Decimal:
        """计算入场价格"""
        return self.entry_strategy.calculate_entry_price(
            current_price=current_price,
            level=level,
            grid_spacing=self.grid_spacing,
            klines=klines
        )
```

### 4.2 修改 BinanceLiveTrader

```python
def _create_order(self, level: int, base_price: Decimal, klines: List[Dict] = None) -> Any:
    from autofish_core import Autofish_OrderCalculator, EntryPriceStrategyFactory
    
    # 从配置创建策略
    strategy_config = self.config.get("entry_price_strategy", {"name": "fixed"})
    strategy = EntryPriceStrategyFactory.create(
        strategy_config.get("name", "fixed"),
        **strategy_config.get("params", {})
    )
    
    order_calculator = Autofish_OrderCalculator(
        grid_spacing=self.config.get("grid_spacing", Decimal("0.01")),
        exit_profit=self.config.get("exit_profit", Decimal("0.01")),
        stop_loss=self.config.get("stop_loss", Decimal("0.08")),
        entry_strategy=strategy
    )
    
    # 计算入场价格
    entry_price = order_calculator.calculate_entry_price(
        current_price=base_price,
        level=level,
        klines=klines
    )
    
    ...
```

## 五、实施步骤

### 步骤 1: 创建策略基类和实现类

在 `autofish_core.py` 中添加：
- `EntryPriceStrategy` 基类
- `FixedGridStrategy` 固定网格策略
- `ATRDynamicStrategy` ATR 动态策略
- `BollingerBandStrategy` 布林带策略
- `SupportLevelStrategy` 支撑位策略
- `CompositeStrategy` 综合策略
- `EntryPriceStrategyFactory` 策略工厂

### 步骤 2: 修改 Autofish_OrderCalculator

- 添加 `entry_strategy` 参数
- 修改 `calculate_entry_price()` 方法使用策略

### 步骤 3: 修改 BinanceLiveTrader

- 从配置创建策略
- 传递策略到 OrderCalculator

### 步骤 4: 更新配置文件

- 添加 `entry_price_strategy` 配置项

### 步骤 5: 更新文档

- 更新 `binance_live_design.md`
- 添加策略说明

## 六、预期效果

### 用户使用

```python
# 使用 ATR 策略
config = {
    "entry_price_strategy": {
        "name": "atr",
        "params": {
            "atr_multiplier": 0.5
        }
    }
}

# 使用综合策略
config = {
    "entry_price_strategy": {
        "name": "composite"
    }
}

# 使用自定义策略
class MyStrategy(EntryPriceStrategy):
    @property
    def name(self) -> str:
        return "my_strategy"
    
    def calculate_entry_price(self, ...):
        # 自定义逻辑
        pass

EntryPriceStrategyFactory.register("my_strategy", MyStrategy)
```

### 扩展性

1. **添加新策略**：继承 `EntryPriceStrategy` 并注册到工厂
2. **配置驱动**：通过配置文件选择策略
3. **参数可调**：每个策略支持自定义参数
4. **易于测试**：每个策略独立测试

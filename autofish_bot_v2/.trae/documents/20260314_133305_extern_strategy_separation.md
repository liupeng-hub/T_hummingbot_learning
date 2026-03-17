# 扩展策略配置分离方案

## 背景

当前 `entry_price_strategy` 和 `market_aware` 两个扩展策略配置存储在振幅配置文件中（如 `binance_BTCUSDT_amplitude_config.json`），这些配置是所有标的共用的，应该分离到单独的文件中。

## 设计方案

### 1. 新建扩展策略配置文件

**文件路径**: `out/autofish/autofish_extern_strategy.json`

**文件格式**:
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
  },
  "market_aware": {
    "enabled": true,
    "algorithm": "dual_thrust",
    "lookback_period": 20,
    "breakout_threshold": 0.02,
    "consecutive_bars": 3,
    "down_confirm_days": 1,
    "k2_down_factor": 0.6,
    "cooldown_days": 1,
    "check_interval": 60,
    "trading_statuses": ["ranging"]
  }
}
```

### 2. 修改 autofish_core.py

**新增类**: `Autofish_ExternStrategy`

```python
class Autofish_ExternStrategy:
    """扩展策略配置加载器
    
    管理所有标的共用的扩展策略配置：
    - entry_price_strategy: 入场价格策略
    - market_aware: 行情感知策略
    """
    
    DEFAULT_CONFIG = {
        "entry_price_strategy": {
            "name": "atr",
            "params": {"atr_period": 14, "atr_multiplier": 0.5, "min_spacing": 0.005, "max_spacing": 0.03}
        },
        "market_aware": {
            "enabled": True,
            "algorithm": "dual_thrust",
            ...
        }
    }
    
    def __init__(self, config_path: str = None, output_dir: str = "out/autofish"):
        self.config_path = config_path or os.path.join(output_dir, "autofish_extern_strategy.json")
        self.config = {}
    
    def load(self) -> bool:
        """加载配置"""
        ...
    
    def get_entry_price_strategy(self) -> dict:
        """获取入场价格策略"""
        ...
    
    def get_market_aware(self) -> dict:
        """获取行情感知策略"""
        ...
    
    def save(self) -> bool:
        """保存配置"""
        ...
    
    @classmethod
    def load_config(cls, output_dir: str = "out/autofish") -> 'Autofish_ExternStrategy':
        """加载配置（类方法）"""
        ...
```

### 3. 修改 binance_live.py

**修改 main 函数**:

```python
async def main():
    # ... 现有代码 ...
    
    # 加载振幅配置
    amplitude_config = Autofish_AmplitudeConfig.load_latest(args.symbol, decay_factor=decay_factor)
    
    # 加载扩展策略配置（所有标的共用）
    extern_strategy = Autofish_ExternStrategy.load_config()
    
    if amplitude_config:
        config = {
            # ... 振幅参数 ...
        }
    else:
        config = Autofish_OrderCalculator.get_default_config("binance")
    
    # 添加扩展策略配置
    config["entry_price_strategy"] = extern_strategy.get_entry_price_strategy()
    config["market_aware"] = extern_strategy.get_market_aware()
    
    # ... 后续代码 ...
```

### 4. 修改振幅配置文件

**移除扩展策略配置**，保留振幅参数：

```json
{
  "d_0.5":{
    "symbol":"BTCUSDT",
    "total_amount_quote":5000,
    "leverage":10,
    "decay_factor":0.5,
    "max_entries":4,
    "valid_amplitudes":[1, 2, 3, 4, 5, 6, 7, 8, 9],
    "weights":[0.0831, 0.2996, 0.3167, 0.1365, 0.1005, 0.0281, 0.027, 0.0066, 0.0018],
    "grid_spacing":0.01,
    "exit_profit":0.01,
    "stop_loss":0.08,
    "total_expected_return":0.2944
  },
  "d_1.0":{
    ...
  }
}
```

## 执行步骤

### 阶段1: 创建 Autofish_ExternStrategy 类
1. 在 autofish_core.py 中添加 `Autofish_ExternStrategy` 类
2. 实现加载、保存、获取配置的方法

### 阶段2: 创建默认配置文件
1. 创建 `out/autofish/autofish_extern_strategy.json` 文件
2. 写入默认配置

### 阶段3: 修改 binance_live.py
1. 导入 `Autofish_ExternStrategy`
2. 修改 main 函数中的配置加载逻辑
3. 从扩展策略文件读取配置

### 阶段4: 清理振幅配置文件
1. 从 `binance_BTCUSDT_amplitude_config.json` 中移除扩展策略配置
2. 保留振幅参数

### 阶段5: 测试验证
1. 验证配置加载正确
2. 验证扩展策略生效

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| autofish_core.py | 修改 | 新增 `Autofish_ExternStrategy` 类 |
| binance_live.py | 修改 | 修改配置加载逻辑 |
| autofish_extern_strategy.json | 新建 | 扩展策略配置文件 |
| binance_BTCUSDT_amplitude_config.json | 修改 | 移除扩展策略配置 |

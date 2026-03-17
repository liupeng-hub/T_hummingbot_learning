# 行情判断算法改进实施计划

## 目标

改进行情判断算法，使震荡区间识别更接近人工看K线判断，震荡持续时间从 1-几天 提升到 数周-数月。
参考 market_status_algorithm_improvement.md分析
---

## 实施步骤

### 步骤 1: 添加支撑阻力位检测器

**文件**: `market_status_detector.py`

**位置**: 在 `VolatilityDetector` 类之后添加

**代码**:
```python
class SupportResistanceDetector:
    """支撑阻力位检测器
    
    通过识别局部高低点并聚类，找出关键支撑阻力位
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'lookback_period': 60,
            'swing_window': 5,
            'merge_threshold': 0.03,
            'min_touches': 3,
        }
    
    def detect(self, klines: List[Dict]) -> Dict:
        """检测支撑阻力位"""
        # 实现细节...
    
    def _find_swing_highs(self, klines: List[Dict], window: int) -> List[float]:
        """找出局部高点"""
    
    def _find_swing_lows(self, klines: List[Dict], window: int) -> List[float]:
        """找出局部低点"""
    
    def _cluster_levels(self, prices: List[float]) -> List[float]:
        """聚类合并相近价格水平"""
```

---

### 步骤 2: 添加箱体震荡检测器

**文件**: `market_status_detector.py`

**位置**: 在 `SupportResistanceDetector` 类之后添加

**代码**:
```python
class BoxRangeDetector:
    """箱体震荡检测器
    
    识别价格在固定区间内反复波动的形态
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'min_duration': 10,
            'max_range_pct': 0.15,
            'min_touches': 4,
            'lookback_period': 90,
        }
    
    def detect(self, klines: List[Dict]) -> Dict:
        """检测箱体震荡"""
        # 实现细节...
```

---

### 步骤 3: 创建改进的行情判断算法

**文件**: `market_status_detector.py`

**位置**: 在 `AlwaysRangingAlgorithm` 类之后添加

**代码**:
```python
class ImprovedStatusAlgorithm(StatusAlgorithm):
    """改进的行情判断算法
    
    核心改进：
    1. 更长的回看周期（60-90天）
    2. 支撑阻力位识别
    3. 箱体震荡识别
    4. 更严格的趋势确认
    """
    
    name = "improved"
    description = "改进的行情判断算法（支撑阻力+箱体震荡）"
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'lookback_period': 60,
            'min_range_duration': 10,
            'max_range_pct': 0.15,
            'breakout_threshold': 0.03,
        }
        
        self.sr_detector = SupportResistanceDetector()
        self.box_detector = BoxRangeDetector()
        # ...
    
    def calculate(self, klines: List[Dict], config: Dict) -> StatusResult:
        # 1. 检测支撑阻力位
        # 2. 检测箱体震荡
        # 3. 检测趋势突破
        # 4. 综合判断
```

---

### 步骤 4: 注册新算法

**文件**: `market_status_detector.py`

**位置**: `MarketStatusDetector.ALGORITHMS` 字典

**修改**:
```python
ALGORITHMS = {
    'realtime': RealTimeStatusAlgorithm,
    'adx': ADXAlgorithm,
    'composite': CompositeAlgorithm,
    'always_ranging': AlwaysRangingAlgorithm,
    'improved': ImprovedStatusAlgorithm,  # 新增
}
```

---

### 步骤 5: 更新命令行参数

**文件**: `market_status_detector.py`

**位置**: `main()` 函数

**修改**:
```python
parser.add_argument("--algorithm", type=str, default="improved",
                    choices=['realtime', 'adx', 'composite', 'always_ranging', 'improved'],
                    help="算法 (默认: improved)")
```

---

### 步骤 6: 更新 market_aware_backtest.py

**文件**: `market_aware_backtest.py`

**位置**: `_create_algorithm()` 方法

**修改**:
```python
def _create_algorithm(self) -> StatusAlgorithm:
    algo_name = self.market_config.get('algorithm', 'improved')  # 默认改为 improved
    
    if algo_name == 'realtime':
        return RealTimeStatusAlgorithm({...})
    elif algo_name == 'always_ranging':
        return AlwaysRangingAlgorithm()
    elif algo_name == 'improved':  # 新增
        return ImprovedStatusAlgorithm()
    # ...
```

---

### 步骤 7: 回测验证

运行回测对比新旧算法效果：

```bash
# 使用改进算法
python market_aware_backtest.py --symbol BTCUSDT --date-range 20220616-20230107 --market-algorithm improved

# 对比原算法
python market_aware_backtest.py --symbol BTCUSDT --date-range 20220616-20230107 --market-algorithm realtime
```

---

## 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `market_status_detector.py` | 添加 `SupportResistanceDetector`、`BoxRangeDetector`、`ImprovedStatusAlgorithm`，更新 `ALGORITHMS` 字典和命令行参数 |
| `market_aware_backtest.py` | 更新 `_create_algorithm()` 方法，默认算法改为 `improved` |

---

## 预期效果

| 指标 | 改进前 | 改进后 |
|------|--------|--------|
| 震荡持续天数 | 1-几天 | 数周-数月 |
| 支撑阻力识别 | 无 | 有 |
| 箱体形态识别 | 无 | 有 |
| 与人工判断一致性 | 低 | 高 |

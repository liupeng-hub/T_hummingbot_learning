"""
Autofish V2 - 链式挂单策略

包含：
- autofish_core: 核心算法模块（包含振幅分析器）
- binance_backtest: Binance 回测模块
- binance_live: Binance 实盘交易模块
"""

from .autofish_core import (
    Autofish_Order,
    Autofish_ChainState,
    Autofish_WeightCalculator,
    Autofish_OrderCalculator,
    Autofish_AmplitudeAnalyzer,
    Autofish_AmplitudeConfig,
)


__version__ = "2.0.0"
__all__ = [
    "Autofish_Order",
    "Autofish_ChainState",
    "Autofish_WeightCalculator",
    "Autofish_OrderCalculator",
    "Autofish_AmplitudeAnalyzer",
    "Autofish_AmplitudeConfig",
]

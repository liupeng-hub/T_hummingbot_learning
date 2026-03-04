"""
Autofish V1 - 链式挂单策略

包含：
- autofish_core: 核心算法模块
- binance_backtest: Binance 回测模块
- binance_live: Binance 实盘交易模块
- amplitude_analyzer: 振幅分析模块
"""

from .autofish_core import (
    Order,
    ChainState,
    WeightCalculator,
    create_order,
    calculate_profit,
    calculate_order_prices,
    check_take_profit_triggered,
    check_stop_loss_triggered,
    check_entry_triggered,
    get_default_config,
)
from .amplitude_analyzer import AmplitudeAnalyzer, AmplitudeConfig


__version__ = "1.0.0"
__all__ = [
    "Order",
    "ChainState",
    "WeightCalculator",
    "create_order",
    "calculate_profit",
    "calculate_order_prices",
    "check_take_profit_triggered",
    "check_stop_loss_triggered",
    "check_entry_triggered",
    "get_default_config",
    "AmplitudeAnalyzer",
    "AmplitudeConfig",
]

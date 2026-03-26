"""
Autofish V2 核心算法模块

包含：
- Autofish_Order: 订单数据类
- Autofish_ChainState: 链式挂单状态
- Autofish_WeightCalculator: 权重计算器
- Autofish_OrderCalculator: 订单计算器
- Autofish_AmplitudeAnalyzer: 振幅分析器
- Autofish_AmplitudeConfig: 振幅配置加载器
- Autofish_CapitalPool: 资金池管理类
"""

from decimal import Decimal
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import os
import asyncio

logger = logging.getLogger(__name__)


# ============================================================================
# 全局常量
# ============================================================================

DEFAULT_ENTRY_STRATEGY = {
    "name": "atr",
    "params": {
        "atr_period": 14,
        "atr_multiplier": 0.5,
        "min_spacing": 0.005,
        "max_spacing": 0.03
    }
}


def normalize_weights(weights: List[Decimal], max_entries: int) -> List[Decimal]:
    """归一化权重
    
    取前 max_entries 个权重，然后归一化使总和为 1
    
    参数:
        weights: 原始权重列表
        max_entries: 最大层级数
        
    返回:
        归一化后的权重列表
    """
    if not weights:
        return []
    
    selected_weights = weights[:max_entries]
    
    total = sum(selected_weights)
    if total == 0:
        return selected_weights
    
    return [w / total for w in selected_weights]


@dataclass
class Autofish_Order:
    """
    订单数据类
    
    表示链式挂单中的一个订单，包含入场、止盈、止损等信息。
    
    Attributes:
        level: 订单层级 (1, 2, 3, 4, ...)
        entry_price: 入场价格
        quantity: 数量 (BTC)
        stake_amount: 投入金额 (USDT)
        take_profit_price: 止盈价格
        stop_loss_price: 止损价格
        state: 订单状态 (pending/filled/closed/cancelled)
        order_id: 入场单 ID (Binance orderId)
        tp_order_id: 止盈单 ID (Binance algoId)
        sl_order_id: 止损单 ID (Binance algoId)
        close_price: 平仓价格
        close_reason: 平仓原因 (take_profit/stop_loss)
        profit: 盈亏金额
        created_at: 创建时间
        filled_at: 成交时间
        closed_at: 平仓时间
        tp_supplemented: 止盈单是否为补下
        sl_supplemented: 止损单是否为补下
    
    示例:
        >>> order = Autofish_Order(
        ...     level=1,
        ...     entry_price=Decimal("50000"),
        ...     quantity=Decimal("0.001"),
        ...     stake_amount=Decimal("50"),
        ...     take_profit_price=Decimal("50500"),
        ...     stop_loss_price=Decimal("46000")
        ... )
    """
    level: int
    entry_price: Decimal
    quantity: Decimal
    stake_amount: Decimal
    take_profit_price: Decimal
    stop_loss_price: Decimal
    state: str = "pending"
    order_id: Optional[int] = None
    tp_order_id: Optional[int] = None
    sl_order_id: Optional[int] = None
    close_price: Optional[Decimal] = None
    close_reason: Optional[str] = None
    profit: Optional[Decimal] = None
    created_at: Optional[str] = None
    filled_at: Optional[str] = None
    closed_at: Optional[str] = None
    tp_supplemented: bool = False
    sl_supplemented: bool = False
    entry_capital: Optional[Decimal] = None
    entry_total_capital: Optional[Decimal] = None
    group_id: int = 0  # 默认 0，入场时设置
    
    def set_state(self, new_state: str, reason: str = ""):
        """设置订单状态"""
        old_state = self.state
        self.state = new_state
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if new_state == "filled":
            self.filled_at = now
        elif new_state == "closed":
            self.closed_at = now
            self.close_reason = reason
        
        logger.info(f"[订单状态变更] A{self.level}: {old_state} -> {new_state} {reason}")
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "level": self.level,
            "entry_price": str(self.entry_price),
            "quantity": str(self.quantity),
            "stake_amount": str(self.stake_amount),
            "take_profit_price": str(self.take_profit_price),
            "stop_loss_price": str(self.stop_loss_price),
            "state": self.state,
            "order_id": self.order_id,
            "tp_order_id": self.tp_order_id,
            "sl_order_id": self.sl_order_id,
            "close_price": str(self.close_price) if self.close_price else None,
            "close_reason": self.close_reason,
            "profit": str(self.profit) if self.profit else None,
            "created_at": self.created_at,
            "filled_at": self.filled_at,
            "closed_at": self.closed_at,
            "tp_supplemented": self.tp_supplemented,
            "sl_supplemented": self.sl_supplemented,
            "entry_capital": str(self.entry_capital) if self.entry_capital else None,
            "entry_total_capital": str(self.entry_total_capital) if self.entry_total_capital else None,
            "group_id": self.group_id,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Autofish_Order':
        """从字典创建"""
        return cls(
            level=data.get("level", 1),
            entry_price=Decimal(data.get("entry_price", "0")),
            quantity=Decimal(data.get("quantity", "0")),
            stake_amount=Decimal(data.get("stake_amount", "0")),
            take_profit_price=Decimal(data.get("take_profit_price", "0")),
            stop_loss_price=Decimal(data.get("stop_loss_price", "0")),
            state=data.get("state", "pending"),
            order_id=data.get("order_id"),
            tp_order_id=data.get("tp_order_id"),
            sl_order_id=data.get("sl_order_id"),
            close_price=Decimal(data.get("close_price")) if data.get("close_price") else None,
            close_reason=data.get("close_reason"),
            profit=Decimal(data.get("profit")) if data.get("profit") else None,
            created_at=data.get("created_at"),
            filled_at=data.get("filled_at"),
            closed_at=data.get("closed_at"),
            tp_supplemented=data.get("tp_supplemented", False),
            sl_supplemented=data.get("sl_supplemented", False),
            entry_capital=Decimal(data.get("entry_capital")) if data.get("entry_capital") else None,
            entry_total_capital=Decimal(data.get("entry_total_capital")) if data.get("entry_total_capital") else None,
            group_id=data.get("group_id", 0),
        )


@dataclass
class Autofish_ChainState:
    """
    链式挂单状态
    
    管理所有订单的状态，提供订单查询、保存、加载等功能。
    
    Attributes:
        base_price: 基准价格（用于计算入场价）
        orders: 订单列表
        is_active: 是否活跃
    
    主要方法：
        - get_order_by_order_id(): 根据订单 ID 查找订单
        - get_order_by_algo_id(): 根据 Algo ID 查找订单
        - get_pending_order(): 获取挂单中的订单
        - get_filled_orders(): 获取已成交的订单
        - save_to_file(): 保存状态到文件（原子写入）
        - load_from_file(): 从文件加载状态
    
    示例:
        >>> state = Autofish_ChainState(base_price=Decimal("50000"))
        >>> state.orders.append(order)
        >>> state.save_to_file("state.json")
    """
    base_price: Decimal
    orders: List[Autofish_Order] = field(default_factory=list)
    is_active: bool = True
    round_entry_capital: Optional[Decimal] = None
    round_entry_total_capital: Optional[Decimal] = None
    group_id: int = 0
    
    def get_order_by_order_id(self, order_id: int) -> Optional[Autofish_Order]:
        """根据订单ID查找订单"""
        for order in self.orders:
            if order.order_id == order_id:
                return order
        return None
    
    def get_order_by_algo_id(self, algo_id: int) -> Optional[Autofish_Order]:
        """根据 Algo ID 查找订单"""
        for order in self.orders:
            if order.tp_order_id == algo_id or order.sl_order_id == algo_id:
                return order
        return None
    
    def get_pending_order(self) -> Optional[Autofish_Order]:
        """获取挂单中的订单"""
        for order in self.orders:
            if order.state == "pending":
                return order
        return None
    
    def get_filled_orders(self) -> List[Autofish_Order]:
        """获取已成交的订单"""
        return [o for o in self.orders if o.state == "filled"]
    
    def get_active_orders(self) -> List[Autofish_Order]:
        """获取活跃订单（挂单中或已成交）"""
        return [o for o in self.orders if o.state in ["pending", "filled"]]
    
    def cancel_pending_orders(self):
        """取消所有挂单"""
        for order in self.orders:
            if order.state == "pending":
                order.state = "cancelled"
    
    def is_order_chain_finished(self) -> bool:
        """检查一轮订单链是否结束
        
        一轮订单链结束的条件：
        1. 没有已成交的订单（所有订单都已出场）
        
        返回:
            True: 一轮订单链已结束
            False: 还有订单在场内
        """
        filled_orders = [o for o in self.orders if o.state == "filled"]
        return len(filled_orders) == 0
    
    def get_pending_first_entry(self) -> Optional['Autofish_Order']:
        """获取待成交的第一笔入场订单（Level 1）"""
        for order in self.orders:
            if order.level == 1 and order.state == "pending":
                return order
        return None
    
    def check_first_entry_timeout(self, current_time: datetime, timeout_minutes: int = 10) -> Optional['Autofish_Order']:
        """检查第一笔入场订单是否超时
        
        参数:
            current_time: 当前时间
                - 回测：传入 K 线时间 (datetime.fromtimestamp(kline['open_time'] / 1000))
                - 实盘：传入 datetime.now()
            timeout_minutes: 超时分钟数
            
        返回:
            超时的第一笔入场订单，如果没有超时则返回 None
        """
        if timeout_minutes <= 0:
            return None
        
        first_entry = self.get_pending_first_entry()
        if not first_entry or not first_entry.created_at:
            return None
        
        created = datetime.strptime(first_entry.created_at, '%Y-%m-%d %H:%M:%S')
        elapsed = (current_time - created).total_seconds() / 60
        
        if elapsed >= timeout_minutes:
            return first_entry
        return None
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "base_price": str(self.base_price),
            "orders": [o.to_dict() for o in self.orders],
            "is_active": self.is_active,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Autofish_ChainState':
        """从字典创建"""
        return cls(
            base_price=Decimal(data.get("base_price", "0")),
            orders=[Autofish_Order.from_dict(o) for o in data.get("orders", [])],
            is_active=data.get("is_active", True),
        )
    
    def save_to_file(self, filepath: str):
        """保存到文件（原子写入）"""
        temp_filepath = filepath + '.tmp'
        try:
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            os.replace(temp_filepath, filepath)
            logger.info(f"[状态保存] 成功保存到: {filepath}")
        except Exception as e:
            logger.error(f"[状态保存] 保存失败: {e}")
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            raise
    
    @classmethod
    def load_from_file(cls, filepath: str) -> Optional['Autofish_ChainState']:
        """从文件加载"""
        if not os.path.exists(filepath):
            logger.info(f"[状态加载] 文件不存在: {filepath}")
            return None
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            state = cls.from_dict(data)
            logger.info(f"[状态加载] 成功加载 {len(state.orders)} 个订单")
            return state
        except Exception as e:
            logger.error(f"[状态加载] 加载失败: {e}")
            return None


class Autofish_WeightCalculator:
    """权重计算器
    
    基于价格波动幅度的概率分布，计算各层级的资金权重。
    使用衰减因子调整权重分布。
    """
    
    DEFAULT_AMPLITUDE_PROBABILITIES = {
        1: Decimal("0.36"),
        2: Decimal("0.24"),
        3: Decimal("0.16"),
        4: Decimal("0.09"),
    }
    
    def __init__(self, decay_factor: Decimal = Decimal("0.5")):
        """
        参数:
            decay_factor: 衰减因子，用于调整权重分布
                         值越大，权重越均匀；值越小，权重越集中在前几层
        """
        self.decay_factor = decay_factor
        self.amplitude_probabilities = self.DEFAULT_AMPLITUDE_PROBABILITIES.copy()
    
    def calculate_weights(self) -> List[Decimal]:
        """计算各层级权重
        
        使用公式: weight_i = amp_i * (prob_i ^ (1/decay_factor))
        然后归一化使总权重为1
        """
        beta = Decimal("1") / self.decay_factor
        raw_weights = []
        
        for amp, prob in self.amplitude_probabilities.items():
            raw_weight = Decimal(str(amp)) * (prob ** beta)
            raw_weights.append(raw_weight)
        
        total = sum(raw_weights)
        return [w / total for w in raw_weights]
    
    def get_stake_amount(self, level: int, total_amount: Decimal) -> Decimal:
        """获取指定层级的资金金额
        
        参数:
            level: 层级 (1-4)
            total_amount: 总资金金额
            
        返回:
            该层级的资金金额
        """
        weights = self.calculate_weights()
        if level <= len(weights):
            return total_amount * weights[level - 1]
        return total_amount * weights[-1]
    
    def get_weight_percentage(self, level: int) -> Decimal:
        """获取指定层级的权重百分比"""
        weights = self.calculate_weights()
        if level <= len(weights):
            return weights[level - 1] * 100
        return weights[-1] * 100


# ============================================================================
# 入场价格策略
# ============================================================================

from abc import ABC, abstractmethod


class EntryPriceStrategy(ABC):
    """入场价格策略基类
    
    所有入场价格计算策略都需要继承此类并实现 calculate_entry_price 方法。
    """
    
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
        dynamic_spacing = atr_percent * Decimal(str(self.atr_multiplier))
        dynamic_spacing = max(Decimal(str(self.min_spacing)), min(Decimal(str(self.max_spacing)), dynamic_spacing))
        
        logger.info(f"[ATR策略] atr={atr:.2f}, atr_percent={float(atr_percent)*100:.2f}%, "
                   f"dynamic_spacing={float(dynamic_spacing)*100:.2f}%")
        
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
        min_entry = current_price * (Decimal("1") - Decimal(str(self.min_spacing)))
        
        entry_price = max(lower_band, min_entry)
        
        if entry_price >= current_price:
            entry_price = min_entry
        
        logger.info(f"[布林带策略] lower_band={lower_band:.2f}, entry_price={entry_price:.2f}")
        
        return entry_price
    
    def _calculate_lower_band(self, klines: List[Dict]) -> Decimal:
        """计算布林带下轨"""
        closes = [Decimal(str(k['close'])) for k in klines[-self.period:]]
        middle = sum(closes) / self.period
        variance = sum([(c - middle) ** 2 for c in closes]) / self.period
        std = variance.sqrt()
        return middle - self.std_multiplier * std


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
        min_entry = current_price * (Decimal("1") - Decimal(str(self.min_spacing)))
        
        entry_price = max(support, min_entry)
        
        if entry_price >= current_price:
            entry_price = min_entry
        
        logger.info(f"[支撑位策略] support={support:.2f}, entry_price={entry_price:.2f}")
        
        return entry_price
    
    def _find_support(self, klines: List[Dict]) -> Decimal:
        """找到最近支撑位"""
        lows = [Decimal(str(k['low'])) for k in klines[-self.lookback:]]
        return min(lows)


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
        
        atr_price = self.atr_strategy.calculate_entry_price(
            current_price, level, grid_spacing, klines
        )
        bollinger_price = self.bollinger_strategy.calculate_entry_price(
            current_price, level, grid_spacing, klines
        )
        support_price = self.support_strategy.calculate_entry_price(
            current_price, level, grid_spacing, klines
        )
        
        entry_price = max(atr_price, bollinger_price, support_price)
        
        min_entry = current_price * (Decimal("1") - Decimal("0.005"))
        if entry_price >= current_price:
            entry_price = min_entry
        
        logger.info(f"[综合策略] atr={atr_price:.2f}, bollinger={bollinger_price:.2f}, "
                   f"support={support_price:.2f}, final={entry_price:.2f}")
        
        return entry_price


class EntryPriceStrategyFactory:
    """入场价格策略工厂
    
    用于创建和管理入场价格策略实例。
    """
    
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
            logger.warning(f"[策略工厂] 未知策略: {strategy_name}，使用默认策略")
            return FixedGridStrategy()
        
        strategy_class = cls._strategies[strategy_name]
        
        # 转换参数类型
        params = {}
        for key, value in kwargs.items():
            if isinstance(value, float):
                params[key] = Decimal(str(value))
            else:
                params[key] = value
        
        return strategy_class(**params)
    
    @classmethod
    def register(cls, name: str, strategy_class: type):
        """注册新策略
        
        参数:
            name: 策略名称
            strategy_class: 策略类
        """
        cls._strategies[name] = strategy_class
        logger.info(f"[策略工厂] 注册策略: {name}")
    
    @classmethod
    def list_strategies(cls) -> List[str]:
        """列出所有可用策略"""
        return list(cls._strategies.keys())


class Autofish_OrderCalculator:
    """订单计算器
    
    封装订单相关的计算逻辑，包括价格计算、订单创建、盈亏计算等。
    """
    
    def __init__(
        self,
        grid_spacing: Decimal = Decimal("0.01"),
        exit_profit: Decimal = Decimal("0.01"),
        stop_loss: Decimal = Decimal("0.08"),
        leverage: Decimal = Decimal("10"),
        entry_strategy: Optional[EntryPriceStrategy] = None
        ):
        """
        参数:
            grid_spacing: 网格间距 (小数，如 0.01 表示 1%)
            exit_profit: 止盈比例 (小数，如 0.01 表示 1%)
            stop_loss: 止损比例 (小数，如 0.08 表示 8%)
            leverage: 杠杆倍数
            entry_strategy: 入场价格策略
        """
        self.grid_spacing = grid_spacing
        self.exit_profit = exit_profit
        self.stop_loss = stop_loss
        self.leverage = leverage
        self.entry_strategy = entry_strategy or FixedGridStrategy()
    
    def calculate_atr(self, klines: List[Dict], period: int = 14) -> Decimal:
        """计算 ATR (Average True Range)
        
        参数:
            klines: K 线数据列表，每根 K 线包含 high, low, close
            period: ATR 周期，默认 14
            
        返回:
            ATR 值
        """
        if len(klines) < period + 1:
            logger.warning(f"[ATR计算] K 线数量不足: {len(klines)} < {period + 1}")
            return Decimal("0")
        
        tr_list = []
        for i in range(1, period + 1):
            high = Decimal(str(klines[-i]['high']))
            low = Decimal(str(klines[-i]['low']))
            prev_close = Decimal(str(klines[-i-1]['close']))
            
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
        
        atr = sum(tr_list) / len(tr_list)
        logger.debug(f"[ATR计算] period={period}, atr={atr:.2f}")
        return atr
    
    def calculate_dynamic_entry_price(
        self,
        current_price: Decimal,
        klines: List[Dict],
        level: int,
        atr_multiplier: Decimal = Decimal("0.5"),
        min_spacing: Decimal = Decimal("0.005"),
        max_spacing: Decimal = Decimal("0.03")
        ) -> Decimal:
        """计算动态入场价格（基于 ATR）
        
        参数:
            current_price: 当前价格
            klines: K 线数据
            level: 层级
            atr_multiplier: ATR 乘数，默认 0.5
            min_spacing: 最小网格间距，默认 0.5%
            max_spacing: 最大网格间距，默认 3%
            
        返回:
            入场价格
        """
        atr = self.calculate_atr(klines)
        
        if atr == 0:
            return current_price * (Decimal("1") - self.grid_spacing * level)
        
        atr_percent = atr / current_price
        dynamic_spacing = atr_percent * atr_multiplier
        
        dynamic_spacing = max(min_spacing, min(max_spacing, dynamic_spacing))
        
        entry_price = current_price * (Decimal("1") - dynamic_spacing * level)
        
        logger.info(f"[动态入场价格] level={level}, atr={atr:.2f}, atr_percent={float(atr_percent)*100:.2f}%, "
                   f"dynamic_spacing={float(dynamic_spacing)*100:.2f}%, entry_price={entry_price:.2f}")
        
        return entry_price
    
    def calculate_prices(self, base_price: Decimal) -> Dict[str, Decimal]:
        """计算订单价格
        
        参数:
            base_price: 基准价格
            
        返回:
            包含 entry_price, take_profit_price, stop_loss_price 的字典
        """
        entry_price = base_price * (Decimal("1") - self.grid_spacing)
        take_profit_price = entry_price * (Decimal("1") + self.exit_profit)
        stop_loss_price = entry_price * (Decimal("1") - self.stop_loss)
        
        return {
            "entry_price": entry_price,
            "take_profit_price": take_profit_price,
            "stop_loss_price": stop_loss_price,
        }
    
    def create_order(
        self,
        level: int,
        base_price: Decimal,
        total_amount: Decimal,
        weights: List[Decimal] = None,
        max_entries: int = 4,
        klines: List[Dict] = None
        ) -> Autofish_Order:
        """创建订单
        
        参数:
            level: 层级
            base_price: 基准价格
            total_amount: 总资金金额
            weights: 权重列表（从配置文件读取）
            max_entries: 最大层级数（用于归一化）
            klines: K 线数据（用于策略计算）
            
        返回:
            Autofish_Order 实例
        """
        # 使用策略计算入场价格（仅 A1 使用策略）
        if level == 1:
            entry_price = self.entry_strategy.calculate_entry_price(
                current_price=base_price,
                level=level,
                grid_spacing=self.grid_spacing,
                klines=klines
            )
        else:
            # 其他层级使用固定网格间距
            entry_price = base_price * (Decimal("1") - self.grid_spacing * level)
        
        take_profit_price = entry_price * (Decimal("1") + self.exit_profit)
        stop_loss_price = entry_price * (Decimal("1") - self.stop_loss)
        
        # 归一化权重
        normalized_weights = normalize_weights(weights, max_entries) if weights else None
        
        # 使用归一化后的权重计算金额
        if normalized_weights and level <= len(normalized_weights):
            stake_amount = total_amount * normalized_weights[level - 1]
        else:
            # 默认平均分配
            stake_amount = total_amount / Decimal(str(max_entries))
        quantity = stake_amount / entry_price
        
        order = Autofish_Order(
            level=level,
            entry_price=entry_price,
            quantity=quantity,
            stake_amount=stake_amount,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            state="pending",
            created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        
        logger.info(f"[创建订单] A{level}: entry={entry_price:.2f}, "
                   f"tp={take_profit_price:.2f}, sl={stop_loss_price:.2f}, "
                   f"stake={stake_amount:.2f} USDT, qty={quantity:.6f} BTC, "
                   f"strategy={self.entry_strategy.name}")
        
        return order
    
    def calculate_profit(self, order: Autofish_Order, close_price: Decimal) -> Decimal:
        """计算盈亏
        
        参数:
            order: 订单
            close_price: 平仓价格
            
        返回:
            盈亏金额 (正数为盈利，负数为亏损)
        """
        profit = order.stake_amount * (close_price - order.entry_price) / order.entry_price * self.leverage
        return profit
    
    @staticmethod
    def check_take_profit_triggered(high_price: Decimal, take_profit_price: Decimal) -> bool:
        """检查是否触发止盈"""
        return high_price >= take_profit_price
    
    @staticmethod
    def check_stop_loss_triggered(low_price: Decimal, stop_loss_price: Decimal) -> bool:
        """检查是否触发止损"""
        return low_price <= stop_loss_price
    
    @staticmethod
    def check_entry_triggered(low_price: Decimal, entry_price: Decimal) -> bool:
        """检查是否触发入场"""
        return low_price <= entry_price
    
    @staticmethod
    def get_default_config(source: str = "binance") -> Dict[str, Any]:
        """获取默认配置
        
        参数:
            source: 数据源，支持 binance 或 longport
        """
        if source == "longport":
            return {
                "symbol": "700.HK",
                "grid_spacing": Decimal("0.01"),
                "exit_profit": Decimal("0.01"),
                "stop_loss": Decimal("0.08"),
                "decay_factor": Decimal("0.5"),
                "total_amount_quote": Decimal("10000"),
                "leverage": Decimal("1"),
                "max_entries": 4,
                "valid_amplitudes":[1, 2, 3, 4, 5, 6, 7, 8],
                "weights":[0.3999, 0.3933, 0.1586, 0.0422, 0.0021, 0.0036, 0.0001, 0.0001]
            }
        else:
            return {
                "symbol": "BTCUSDT",
                "grid_spacing": Decimal("0.01"),
                "exit_profit": Decimal("0.01"),
                "stop_loss": Decimal("0.08"),
                "decay_factor": Decimal("0.5"),
                "total_amount_quote": Decimal("10000"),
                "leverage": Decimal("10"),
                "max_entries": 4,
                "valid_amplitudes":[1, 2, 3, 4, 5, 6, 7, 8, 9],
                "weights":[0.0852, 0.2956, 0.3177, 0.137, 0.1008, 0.0282, 0.0271, 0.0066, 0.0019]
            }


class Autofish_AmplitudeAnalyzer:
    """振幅分析器
    
    分析历史K线数据，计算各振幅区间的概率分布，
    根据预期收益计算权重，输出配置文件供回测和实盘使用。
    
    支持数据源：
    - binance: Binance 加密货币（默认）
    - longport: LongPort 港股/美股/A股
    """
    
    AMPLITUDE_RANGES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    DEFAULT_LEVERAGE = Decimal("10")
    LIQUIDATION_AMPLITUDE = 10
    VALID_AMPLITUDE_MIN = 1
    
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "1d", limit: int = 1000, 
                 leverage: int = 10, source: str = "binance", output_dir: str = "out/autofish",
                 log_dir: str = "logs", entry_strategy: dict = None):
        self.symbol = symbol
        self.interval = interval
        self.limit = limit
        self.leverage = Decimal(str(leverage))
        self.source = source
        self.output_dir = output_dir
        self.log_dir = log_dir
        self.entry_strategy = entry_strategy or DEFAULT_ENTRY_STRATEGY.copy()
        self.klines: List[dict] = []
        self.amplitudes: List[Decimal] = []
        self.amplitude_counts: Dict[int, int] = {amp: 0 for amp in self.AMPLITUDE_RANGES}
        self.probabilities: Dict[int, Decimal] = {}
        self.expected_returns: Dict[int, Decimal] = {}
        self.weights: Dict[str, Dict[int, Decimal]] = {}
        
        self._setup_logger()
    
    def _setup_logger(self):
        """配置日志"""
        os.makedirs(self.log_dir, exist_ok=True)
        
        log_file = os.path.join(self.log_dir, "amplitude_analyzer.log")
        
        self.logger = logging.getLogger(f"amplitude_analyzer_{self.symbol}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        
        if not self.logger.handlers:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
            
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
    
    def get_config_filepath(self) -> str:
        """获取配置文件路径"""
        source = "longport" if self.is_longport_symbol(self.symbol) else "binance"
        return os.path.join(self.output_dir, f"{source}_{self.symbol}_amplitude_config.json")
    
    def get_report_filepath(self) -> str:
        """获取报告文件路径"""
        source = "longport" if self.is_longport_symbol(self.symbol) else "binance"
        return os.path.join(self.output_dir, f"{source}_{self.symbol}_amplitude_report.md")
    
    @staticmethod
    def is_longport_symbol(symbol: str) -> bool:
        """判断是否为 LongPort 交易对"""
        symbol_upper = symbol.upper()
        return any(suffix in symbol_upper for suffix in [".HK", ".US", ".SH", ".SZ"])
    
    @staticmethod
    def get_currency_from_symbol(symbol: str) -> str:
        """根据交易对获取货币类型"""
        symbol_upper = symbol.upper()
        if ".HK" in symbol_upper:
            return "HKD"
        elif ".US" in symbol_upper:
            return "USD"
        elif ".SH" in symbol_upper or ".SZ" in symbol_upper:
            return "CNY"
        return "USDT"
    
    async def fetch_klines(self, proxy: str = None) -> List[dict]:
        """获取历史K线数据"""
        if self.source == "longport" or self.is_longport_symbol(self.symbol):
            return await self._fetch_klines_longport()
        else:
            return await self._fetch_klines_binance(proxy)
    
    async def _fetch_klines_binance(self, proxy: str = None) -> List[dict]:
        """从 Binance 获取历史K线数据"""
        import aiohttp
        
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {
            "symbol": self.symbol,
            "interval": self.interval,
            "limit": self.limit,
        }
        
        self.logger.info(f"[获取K线-Binance] symbol={self.symbol}, interval={self.interval}, limit={self.limit}")
        
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            kwargs = {"params": params}
            if proxy:
                kwargs["proxy"] = proxy
            
            async with session.get(url, **kwargs) as response:
                if response.status == 200:
                    data = await response.json()
                    klines = []
                    for item in data:
                        klines.append({
                            "timestamp": item[0],
                            "open": Decimal(item[1]),
                            "high": Decimal(item[2]),
                            "low": Decimal(item[3]),
                            "close": Decimal(item[4]),
                            "volume": Decimal(item[5]),
                        })
                    self.logger.info(f"[获取K线-Binance] 成功获取 {len(klines)} 条数据")
                    return klines
                else:
                    text = await response.text()
                    self.logger.error(f"[获取K线-Binance] 失败: {response.status} - {text}")
                    return []
    
    async def _fetch_klines_longport(self) -> List[dict]:
        """从 LongPort 获取历史K线数据"""
        try:
            from longport.openapi import Config, QuoteContext, Period, AdjustType
        except ImportError:
            self.logger.error("[获取K线-LongPort] 未安装 longport 包")
            return []
        
        self.logger.info(f"[获取K线-LongPort] symbol={self.symbol}, interval={self.interval}, count={self.limit}")
        
        period_map = {
            "1d": Period.Day, "1D": Period.Day,
            "1w": Period.Week, "1W": Period.Week,
            "1M": Period.Month,
        }
        
        period = period_map.get(self.interval, Period.Day)
        
        try:
            config = Config.from_env()
            ctx = QuoteContext(config)
            
            candlesticks = ctx.history_candlesticks_by_offset(
                symbol=self.symbol,
                period=period,
                adjust_type=AdjustType.NoAdjust,
                forward=False,
                time=datetime.now(),
                count=self.limit
            )
            
            klines = []
            for candle in candlesticks:
                klines.append({
                    "timestamp": int(candle.timestamp.timestamp() * 1000),
                    "open": Decimal(str(candle.open)),
                    "high": Decimal(str(candle.high)),
                    "low": Decimal(str(candle.low)),
                    "close": Decimal(str(candle.close)),
                    "volume": Decimal(str(candle.volume)),
                })
            
            self.logger.info(f"[获取K线-LongPort] 成功获取 {len(klines)} 条数据")
            return klines
            
        except Exception as e:
            self.logger.error(f"[获取K线-LongPort] 失败: {e}")
            return []
    
    def calculate_amplitude(self, kline: dict) -> Decimal:
        """计算单根K线的振幅"""
        open_price = kline["open"]
        high_price = kline["high"]
        low_price = kline["low"]
        
        if open_price == 0:
            return Decimal("0")
        
        amplitude = (high_price - low_price) / open_price * 100
        return amplitude
    
    def calculate_all_amplitudes(self):
        """计算所有K线振幅"""
        self.amplitudes = [self.calculate_amplitude(k) for k in self.klines]
        self.logger.info(f"[振幅计算] 完成，共 {len(self.amplitudes)} 条")
    
    def classify_amplitude(self, amplitude: Decimal) -> int:
        """将振幅归类到区间"""
        amp_int = int(amplitude)
        if amp_int < 1:
            return 0
        elif amp_int >= 10:
            return 10
        else:
            return amp_int
    
    def calculate_probabilities(self):
        """计算各振幅区间概率"""
        total = len(self.amplitudes)
        if total == 0:
            self.logger.warning("[概率计算] 无振幅数据")
            return
        
        for amp in self.amplitudes:
            amp_class = self.classify_amplitude(amp)
            if amp_class in self.amplitude_counts:
                self.amplitude_counts[amp_class] += 1
        
        for amp_class, count in self.amplitude_counts.items():
            self.probabilities[amp_class] = Decimal(count) / Decimal(total)
        
        self.logger.info(f"[概率计算] 完成")
    
    def calculate_expected_returns(self):
        """计算各振幅预期收益"""
        for amp in self.AMPLITUDE_RANGES:
            prob = self.probabilities.get(amp, Decimal("0"))
            
            if amp == 0:
                self.expected_returns[amp] = Decimal("0")
            elif amp >= self.LIQUIDATION_AMPLITUDE:
                self.expected_returns[amp] = -prob * self.leverage
            else:
                self.expected_returns[amp] = Decimal(amp) / 100 * self.leverage * prob
        
        self.logger.info(f"[预期收益] 计算（杠杆={self.leverage}x）")
    
    def calculate_weights_for_decay(self, decay_factor: Decimal) -> Dict[int, Decimal]:
        """计算指定衰减因子下的权重"""
        beta = Decimal("1") / decay_factor
        
        positive_items = []
        for amp in self.AMPLITUDE_RANGES:
            prob = self.probabilities.get(amp, Decimal("0"))
            ret = self.expected_returns.get(amp, Decimal("0"))
            
            if ret > 0 and prob > 0:
                raw_weight = Decimal(amp) * (prob ** beta)
                positive_items.append((amp, raw_weight))
        
        total = sum(w for _, w in positive_items)
        
        weights = {}
        for amp, raw_weight in positive_items:
            weights[amp] = (raw_weight / total) if total > 0 else Decimal("0")
        
        return weights
    
    def calculate_all_weights(self):
        """计算所有衰减因子的权重"""
        decay_factors = [Decimal("0.5"), Decimal("1.0")]
        
        for d in decay_factors:
            key = f"d_{float(d)}"
            self.weights[key] = self.calculate_weights_for_decay(d)
            
            self.logger.info(f"[权重计算] d={d}")
    
    def get_recommended_config(self) -> dict:
        """获取推荐配置"""
        weights_d05 = self.weights.get("d_0.5", {})
        
        valid_amplitudes = sorted(weights_d05.keys())
        max_entries = min(4, len(valid_amplitudes))
        
        total_positive = sum(
            self.expected_returns.get(amp, Decimal("0")) 
            for amp in valid_amplitudes
        )
        
        return {
            "valid_amplitudes": valid_amplitudes,
            "max_entries": max_entries,
            "grid_spacing": Decimal("0.01"),
            "decay_factor": Decimal("0.5"),
            "stop_loss": Decimal("0.08"),
            "total_expected_return": float(total_positive),
        }
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "metadata": {
                "symbol": self.symbol,
                "interval": self.interval,
                "limit": self.limit,
                "analyzed_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "kline_count": len(self.klines),
            },
            "amplitude_stats": {
                str(amp): {
                    "count": self.amplitude_counts.get(amp, 0),
                    "probability": round(float(self.probabilities.get(amp, Decimal("0"))), 4),
                }
                for amp in self.AMPLITUDE_RANGES
            },
            "expected_returns": {
                str(amp): round(float(ret), 4)
                for amp, ret in self.expected_returns.items()
            },
            "weights": {
                decay_key: {
                    str(amp): round(float(w), 4)
                    for amp, w in weights.items()
                }
                for decay_key, weights in self.weights.items()
            },
            "recommended_config": {
                "symbol": self.symbol,
                "valid_amplitudes": sorted(self.weights.get("d_0.5", {}).keys()),
                "max_entries": min(4, len(self.weights.get("d_0.5", {}))),
                "grid_spacing": 0.01,
                "exit_profit": 0.01,
                "stop_loss": 0.08,
                "decay_factor": 0.5,
                "total_amount_quote": 1200,
                "leverage": int(self.leverage),
                "total_expected_return": round(float(sum(
                    self.expected_returns.get(amp, Decimal("0")) 
                    for amp in self.weights.get("d_0.5", {}).keys()
                )), 4),
            },
        }
    
    def save_to_file(self, filepath: str = None):
        """保存配置到JSON文件"""
        if filepath is None:
            filepath = self.get_config_filepath()
        
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        def build_entry_strategy_str() -> str:
            """构建入场策略配置字符串"""
            strategy = self.entry_strategy
            name = strategy.get("name", "atr")
            params = strategy.get("params", {})
            
            params_str = ", ".join([f'"{k}": {json.dumps(v)}' for k, v in params.items()])
            
            return (f'    "entry_price_strategy": {{\n'
                    f'      "name": "{name}",\n'
                    f'      "params": {{{params_str}}}\n'
                    f'    }}')
        
        def build_config_str(decay_factor: float, decay_key: str) -> str:
            weights_dict = self.weights.get(decay_key, {})
            max_entries = min(4, len(weights_dict))
            
            weight_list = []
            for amp in sorted(weights_dict.keys()):
                w = weights_dict.get(amp, Decimal("0"))
                weight_list.append(round(float(w), 4))
            
            valid_amps = sorted(weights_dict.keys())
            total_ret = sum(self.expected_returns.get(amp, Decimal("0")) for amp in valid_amps)
            
            return (f'  "d_{decay_factor}":{{\n'
                    f'    "symbol":"{self.symbol}",\n'
                    f'    "total_amount_quote":5000,\n'
                    f'    "leverage":{int(self.leverage)},\n'
                    f'    "decay_factor":{decay_factor},\n'
                    f'    "max_entries":{max_entries},\n'
                    f'    "valid_amplitudes":{json.dumps(valid_amps)},\n'
                    f'    "weights":{json.dumps(weight_list)},\n'
                    f'    "grid_spacing":0.01,\n'
                    f'    "exit_profit":0.01,\n'
                    f'    "stop_loss":0.08,\n'
                    f'    "total_expected_return":{round(float(total_ret), 4)},\n'
                    f'{build_entry_strategy_str()}\n'
                    f'  }}')
        
        config_d05_str = build_config_str(0.5, "d_0.5")
        config_d10_str = build_config_str(1.0, "d_1.0")
        
        lines = []
        lines.append('{')
        lines.append(config_d05_str + ',')
        lines.append(config_d10_str)
        lines.append('}')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        self.logger.info(f"[保存配置] 成功保存到: {filepath}")
    
    def save_to_markdown(self, filepath: str = None):
        """保存分析报告到Markdown文件"""
        if filepath is None:
            filepath = self.get_report_filepath()
        
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        lines = []
        lines.append(f"# Autofish V2 振幅分析报告")
        lines.append(f"")
        lines.append(f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"")
        
        lines.append(f"## 分析结果")
        lines.append(f"")
        lines.append(f"```json")
        lines.append(f"{{")
        
        lines.append(f'  "metadata":{{"symbol":"{self.symbol}","interval":"{self.interval}","limit":{self.limit},"analyzed_at":"{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}","kline_count":{len(self.klines)}}},')
        
        lines.append(f'  "amplitude_stats":{{')
        amp_stat_items = []
        for amp in self.AMPLITUDE_RANGES:
            count = self.amplitude_counts.get(amp, 0)
            prob = round(float(self.probabilities.get(amp, Decimal("0"))), 4)
            amp_stat_items.append(f'    "{amp}":{{"count":{count},"probability":{prob}}}')
        lines.append(',\n'.join(amp_stat_items))
        lines.append(f'  }},')
        
        er_items = [f'"{amp}":{round(float(self.expected_returns.get(amp, Decimal("0"))), 4)}' for amp in self.AMPLITUDE_RANGES]
        lines.append(f'  "expected_returns":{{' + ','.join(er_items) + '},')
        
        lines.append(f'  "weights":{{')
        w_d05_items = [f'"{amp}":{round(float(w), 4)}' for amp, w in sorted(self.weights.get("d_0.5", {}).items())]
        lines.append(f'    "d_0.5":{{' + ','.join(w_d05_items) + '},')
        w_d10_items = [f'"{amp}":{round(float(w), 4)}' for amp, w in sorted(self.weights.get("d_1.0", {}).items())]
        lines.append(f'    "d_1.0":{{' + ','.join(w_d10_items) + '}')
        lines.append(f'  }},')
        
        def build_config_lines(decay_factor: float, decay_key: str) -> list:
            weights_dict = self.weights.get(decay_key, {})
            max_entries = min(4, len(weights_dict))
            weight_list = [round(float(weights_dict.get(amp, Decimal("0"))), 4) for amp in sorted(weights_dict.keys())]
            valid_amps = sorted(weights_dict.keys())
            total_ret = sum(self.expected_returns.get(amp, Decimal("0")) for amp in valid_amps)
            
            strategy = self.entry_strategy
            name = strategy.get("name", "atr")
            params = strategy.get("params", {})
            params_str = ", ".join([f'"{k}": {json.dumps(v)}' for k, v in params.items()])
            
            return [
                f'    "d_{decay_factor}":{{',
                f'      "symbol":"{self.symbol}",',
                f'      "total_amount_quote":5000,',
                f'      "leverage":{int(self.leverage)},',
                f'      "decay_factor":{decay_factor},',
                f'      "max_entries":{max_entries},',
                f'      "valid_amplitudes":{json.dumps(valid_amps)},',
                f'      "weights":{json.dumps(weight_list)},',
                f'      "grid_spacing":0.01,',
                f'      "exit_profit":0.01,',
                f'      "stop_loss":0.08,',
                f'      "total_expected_return":{round(float(total_ret), 4)},',
                f'      "entry_price_strategy":{{"name":"{name}","params":{{{params_str}}}}}',
                f'    }}'
            ]
        
        lines.append(f'  "recommended_configs":{{')
        config_d05_lines = build_config_lines(0.5, "d_0.5")
        for i, line in enumerate(config_d05_lines):
            if i == len(config_d05_lines) - 1:
                lines.append(line + ',')
            else:
                lines.append(line)
        for line in build_config_lines(1.0, "d_1.0"):
            lines.append(line)
        lines.append(f'  }}')
        
        lines.append(f"}}")
        lines.append(f"```")
        lines.append(f"")
        
        lines.append(f"## 元数据")
        lines.append(f"")
        lines.append(f"| 字段 | 值 | 说明 |")
        lines.append(f"|------|-----|------|")
        lines.append(f"| symbol | {self.symbol} | 交易对 |")
        lines.append(f"| interval | {self.interval} | K线周期 |")
        lines.append(f"| limit | {self.limit} | K线数量 |")
        lines.append(f"| leverage | {self.leverage}x | 杠杆倍数 |")
        lines.append(f"| kline_count | {len(self.klines)} | 实际获取K线数 |")
        lines.append(f"")
        
        lines.append(f"## 振幅统计")
        lines.append(f"")
        lines.append(f"| 振幅 | 出现次数 | 概率 | 累计概率 | 预期收益 | 说明 |")
        lines.append(f"|------|----------|------|----------|----------|------|")
        cumulative_prob = Decimal("0")
        for amp in self.AMPLITUDE_RANGES:
            count = self.amplitude_counts.get(amp, 0)
            prob = self.probabilities.get(amp, Decimal("0"))
            cumulative_prob += prob
            ret = self.expected_returns.get(amp, Decimal("0"))
            note = "爆仓风险" if amp >= 10 else "正收益区间" if ret > 0 else "不参与交易" if amp == 0 else "负收益"
            lines.append(f"| {amp}% | {count} | {float(prob)*100:.2f}% | {float(cumulative_prob)*100:.2f}% | {float(ret)*100:.2f}% | {note} |")
        lines.append(f"")
        
        lines.append(f"## 权重分配")
        lines.append(f"")
        lines.append(f"### 衰减因子 d=0.5（激进策略）")
        lines.append(f"")
        lines.append(f"| 振幅 | 权重 | 累计权重 | 说明 |")
        lines.append(f"|------|------|----------|------|")
        cumulative_weight = Decimal("0")
        for amp, w in sorted(self.weights.get("d_0.5", {}).items()):
            cumulative_weight += w
            lines.append(f"| {amp}% | {float(w)*100:.2f}% | {float(cumulative_weight)*100:.2f}% | 第{amp}层资金分配比例 |")
        lines.append(f"")
        
        lines.append(f"### 衰减因子 d=1.0（保守策略）")
        lines.append(f"")
        lines.append(f"| 振幅 | 权重 | 累计权重 | 说明 |")
        lines.append(f"|------|------|----------|------|")
        cumulative_weight = Decimal("0")
        for amp, w in sorted(self.weights.get("d_1.0", {}).items()):
            cumulative_weight += w
            lines.append(f"| {amp}% | {float(w)*100:.2f}% | {float(cumulative_weight)*100:.2f}% | 第{amp}层资金分配比例 |")
        lines.append(f"")
        
        lines.append(f"## 推荐配置说明")
        lines.append(f"")
        
        for decay_factor, decay_key, strategy_name in [(0.5, "d_0.5", "激进策略"), (1.0, "d_1.0", "保守策略")]:
            weights_dict = self.weights.get(decay_key, {})
            valid_amps = sorted(weights_dict.keys())
            max_entries = min(4, len(weights_dict))
            total_ret = sum(self.expected_returns.get(amp, Decimal("0")) for amp in valid_amps)
            
            lines.append(f"### 衰减因子 d={decay_factor}（{strategy_name}）")
            lines.append(f"")
            lines.append(f"| 字段 | 值 | 说明 |")
            lines.append(f"|------|-----|------|")
            lines.append(f"| symbol | {self.symbol} | 交易对 |")
            lines.append(f"| valid_amplitudes | {valid_amps} | 有效振幅区间（正收益区间，≥10%已剔除） |")
            lines.append(f"| max_entries | {max_entries} | 最大层级数（前{max_entries}层权重合计约84%） |")
            lines.append(f"| grid_spacing | 1% | 网格间距，入场价 = 基准价 × (1 - 1%) |")
            lines.append(f"| exit_profit | 1% | 止盈比例，止盈价 = 入场价 × (1 + 1%) |")
            lines.append(f"| stop_loss | 8% | 止损比例，止损价 = 入场价 × (1 - 8%) |")
            lines.append(f"| decay_factor | {decay_factor} | 衰减因子 |")
            lines.append(f"| total_amount_quote | 1200 | 总投入金额（USDT） |")
            lines.append(f"| leverage | {int(self.leverage)}x | 杠杆倍数 |")
            lines.append(f"| total_expected_return | {float(total_ret)*100:.2f}% | 总预期收益（所有正收益区间之和） |")
            lines.append(f"")
        
        lines.append(f"## 入场价格策略")
        lines.append(f"")
        lines.append(f"| 字段 | 值 | 说明 |")
        lines.append(f"|------|-----|------|")
        lines.append(f"| name | {self.entry_strategy.get('name', 'atr')} | 策略名称 |")
        
        params = self.entry_strategy.get('params', {})
        if self.entry_strategy.get('name') == 'atr':
            lines.append(f"| atr_period | {params.get('atr_period', 14)} | ATR 计算周期 |")
            lines.append(f"| atr_multiplier | {params.get('atr_multiplier', 0.5)} | ATR 乘数 |")
            lines.append(f"| min_spacing | {params.get('min_spacing', 0.005) * 100:.1f}% | 最小网格间距 |")
            lines.append(f"| max_spacing | {params.get('max_spacing', 0.03) * 100:.1f}% | 最大网格间距 |")
        elif self.entry_strategy.get('name') == 'bollinger':
            lines.append(f"| period | {params.get('period', 20)} | 布林带周期 |")
            lines.append(f"| std_multiplier | {params.get('std_multiplier', 2)} | 标准差乘数 |")
            lines.append(f"| min_spacing | {params.get('min_spacing', 0.005) * 100:.1f}% | 最小网格间距 |")
        elif self.entry_strategy.get('name') == 'support':
            lines.append(f"| lookback | {params.get('lookback', 20)} | 回溯 K 线数量 |")
            lines.append(f"| min_spacing | {params.get('min_spacing', 0.005) * 100:.1f}% | 最小网格间距 |")
        
        lines.append(f"")
        lines.append(f"**策略说明**: 入场价格策略用于计算 A1 订单的入场价格。")
        lines.append(f"")
        lines.append(f"- **fixed**: 固定网格间距，入场价格 = 当前价格 × (1 - 网格间距)")
        lines.append(f"- **atr**: 基于 ATR 动态计算，适应市场波动性")
        lines.append(f"- **bollinger**: 布林带下轨入场，适用于震荡市场")
        lines.append(f"- **support**: 支撑位入场，适用于趋势市场")
        lines.append(f"- **composite**: 综合多种技术指标")
        lines.append(f"")
        
        lines.append(f"## 算法说明")
        lines.append(f"")
        lines.append(f"### 振幅计算")
        lines.append(f"```")
        lines.append(f"振幅 = (high - low) / open × 100")
        lines.append(f"```")
        lines.append(f"")
        lines.append(f"### 预期收益计算")
        lines.append(f"```")
        lines.append(f"预期收益 = 振幅 × 杠杆 × 概率")
        lines.append(f"```")
        lines.append(f"")
        lines.append(f"### 权重计算")
        lines.append(f"```")
        lines.append(f"权重 = 振幅 × 概率^(1/d)")
        lines.append(f"```")
        lines.append(f"- d=0.5: 幂次β=2，权重集中在前几层（激进）")
        lines.append(f"- d=1.0: 幂次β=1，权重分布均匀（保守）")
        lines.append(f"")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        self.logger.info(f"[保存报告] 成功保存到: {filepath}")
    
    async def analyze(self, proxy: str = None) -> dict:
        """执行完整分析
        
        参数:
            proxy: 代理地址，如果为 None 则自动从环境变量读取
        """
        self.logger.info("=" * 60)
        self.logger.info(f"Autofish V2 振幅分析 ({self.source}: {self.symbol})")
        self.logger.info("=" * 60)
        
        self.logger.info(f"初始化振幅分析器: symbol={self.symbol}, interval={self.interval}, limit={self.limit}, leverage={self.leverage}, source={self.source}")
        
        if proxy is None:
            import os
            proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None
            if proxy:
                self.logger.info(f"[代理配置] 使用代理: {proxy}")
        
        print("=" * 60)
        print(f"Autofish V2 振幅分析 ({self.source}: {self.symbol})")
        print("=" * 60)
        print(f"\n配置:")
        print(f"  交易对: {self.symbol}")
        print(f"  K线周期: {self.interval}")
        print(f"  数据量: {self.limit}")
        
        self.klines = await self.fetch_klines(proxy)
        if not self.klines:
            self.logger.error("获取K线数据失败")
            return {}
        
        print(f"\n📊 数据统计:")
        print(f"  K线数量: {len(self.klines)}")
        
        first_kline = self.klines[0]
        last_kline = self.klines[-1]
        start_time = datetime.fromtimestamp(first_kline["timestamp"] / 1000)
        end_time = datetime.fromtimestamp(last_kline["timestamp"] / 1000)
        print(f"  时间范围: {start_time.strftime('%Y-%m-%d')} - {end_time.strftime('%Y-%m-%d')}")
        
        print(f"\n⏳ 开始分析...")
        
        self.calculate_all_amplitudes()
        self.calculate_probabilities()
        self.calculate_expected_returns()
        self.calculate_all_weights()
        
        return self.to_dict()


class Autofish_AmplitudeConfig:
    """振幅配置加载器"""
    
    def __init__(self, config_path: str = None, symbol: str = None, output_dir: str = "out/autofish",
                 decay_factor: Decimal = Decimal("0.5")):
        if config_path is None:
            if symbol is None:
                symbol = "BTCUSDT"
            source = "longport" if Autofish_AmplitudeAnalyzer.is_longport_symbol(symbol) else "binance"
            config_path = os.path.join(output_dir, f"{source}_{symbol}_amplitude_config.json")
        self.config_path = config_path
        self.decay_factor = decay_factor
        self.data: Dict[str, Any] = {}
    
    def _get_decay_key(self) -> str:
        """获取衰减因子对应的键名"""
        if self.decay_factor == Decimal("0.5"):
            return "d_0.5"
        elif self.decay_factor == Decimal("1.0"):
            return "d_1.0"
        else:
            return f"d_{float(self.decay_factor)}"
    
    def _get_recommended_config(self) -> dict:
        """获取推荐配置"""
        decay_key = self._get_decay_key()
        
        if decay_key in self.data:
            return self.data[decay_key]
        
        if "d_0.5" in self.data:
            return self.data["d_0.5"]
        
        return {}
    
    def load(self) -> bool:
        """加载配置"""
        if not os.path.exists(self.config_path):
            logger.warning(f"[配置加载] 文件不存在: {self.config_path}")
            return False
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            logger.info(f"[配置加载] 成功加载: {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"[配置加载] 失败: {e}")
            return False
    
    def get_probabilities(self) -> Dict[int, Decimal]:
        """获取概率分布"""
        probs = {}
        for amp_str, stats in self.data.get("amplitude_stats", {}).items():
            amp = int(amp_str)
            probs[amp] = Decimal(str(stats.get("probability", 0)))
        return probs
    
    def get_expected_returns(self) -> Dict[int, Decimal]:
        """获取预期收益"""
        returns = {}
        for amp_str, ret in self.data.get("expected_returns", {}).items():
            amp = int(amp_str)
            returns[amp] = Decimal(str(ret))
        return returns
    
    def get_leverage(self) -> Decimal:
        return Decimal(str(self.data.get("leverage", 10)))
    
    def get_symbol(self) -> str:
        config = self._get_recommended_config()
        return config.get("symbol", "BTCUSDT")
    
    def get_grid_spacing(self) -> Decimal:
        config = self._get_recommended_config()
        return Decimal(str(config.get("grid_spacing", 0.01)))
    
    def get_exit_profit(self) -> Decimal:
        config = self._get_recommended_config()
        return Decimal(str(config.get("exit_profit", 0.01)))
    
    def get_stop_loss(self) -> Decimal:
        config = self._get_recommended_config()
        return Decimal(str(config.get("stop_loss", 0.08)))
    
    def get_total_amount_quote(self) -> Decimal:
        config = self._get_recommended_config()
        return Decimal(str(config.get("total_amount_quote", 1200)))
    
    def get_max_entries(self) -> int:
        config = self._get_recommended_config()
        return config.get("max_entries", 4)
    
    def get_valid_amplitudes(self) -> List[int]:
        config = self._get_recommended_config()
        return config.get("valid_amplitudes", [1, 2, 3, 4])
    
    def get_decay_factor(self) -> Decimal:
        return self.decay_factor
    
    def get_total_expected_return(self) -> Decimal:
        config = self._get_recommended_config()
        return Decimal(str(config.get("total_expected_return", 0)))
    
    def get_weights(self) -> list:
        """获取权重列表"""
        config = self._get_recommended_config()
        return config.get("weights", [])

    @classmethod
    def load_latest(cls, symbol: str = "BTCUSDT", output_dir: str = "out/autofish", 
                    decay_factor: Decimal = Decimal("0.5")) -> Optional['Autofish_AmplitudeConfig']:
        """加载最新配置"""
        config = cls(symbol=symbol, output_dir=output_dir, decay_factor=decay_factor)
        if config.load():
            return config
        return None


class Autofish_ExternStrategy:
    """扩展策略配置加载器
    
    管理所有标的共用的扩展策略配置：
    - entry_price_strategy: 入场价格策略
    - market_aware: 行情感知策略
    
    新格式说明：
    - entry_price_strategy: {"strategy": "atr", "atr": {...}, "bollinger": {...}}
    - market_aware: {"algorithm": "dual_thrust", "dual_thrust": {...}, "trading_statuses": [...]}
    """
    
    DEFAULT_CONFIG = {
        "entry_price_strategy": {
            "strategy": "atr",
            "atr": {
                "atr_period": 14,
                "atr_multiplier": 0.5,
                "min_spacing": 0.005,
                "max_spacing": 0.03
            },
            "bollinger": {
                "period": 20,
                "num_std": 2,
                "min_spacing": 0.005,
                "max_spacing": 0.03
            },
            "support": {
                "period": 20,
                "min_touches": 2,
                "price_tolerance": 0.01
            },
            "composite": {
                "atr_period": 14,
                "atr_multiplier": 0.5,
                "bb_period": 20,
                "bb_std": 2
            }
        },
        "market_aware": {
            "algorithm": "dual_thrust",
            "dual_thrust": {
                "n_days": 4,
                "k1": 0.4,
                "k2": 0.4,
                "k2_down_factor": 0.8,
                "down_confirm_days": 2,
                "cooldown_days": 1
            },
            "improved": {
                "lookback_period": 60,
                "min_range_duration": 10,
                "max_range_pct": 0.15,
                "breakout_threshold": 0.03,
                "breakout_confirm_days": 3
            },
            "composite": {
                "adx_period": 14,
                "adx_threshold": 25,
                "atr_period": 14,
                "atr_multiplier": 1.5,
                "bb_period": 20,
                "bb_std": 2
            },
            "adx": {
                "period": 14,
                "threshold": 25
            },
            "trading_statuses": ["ranging"]
        },
        "capital_pool_strategy": {
            "strategy": "guding",
            "baoshou": {
                "withdrawal_threshold": 2.0,
                "withdrawal_retain": 1.5
            },
            "wenjian": {
                "withdrawal_threshold": 3.0,
                "withdrawal_retain": 2.0
            },
            "jijin": {
                "withdrawal_threshold": 1.5,
                "withdrawal_retain": 1.2
            },
            "zidingyi": {}
        }
    }
    
    def __init__(self, config_path: str = None, output_dir: str = "out/autofish"):
        self.output_dir = output_dir
        self.config_path = config_path or os.path.join(output_dir, "autofish_extern_strategy.json")
        self.config = {}
    
    def load(self) -> bool:
        """加载配置文件"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                return True
        except Exception as e:
            print(f"[扩展策略] 加载配置失败: {e}")
        return False
    
    def save(self) -> bool:
        """保存配置文件"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[扩展策略] 保存配置失败: {e}")
            return False
    
    def get_entry_price_strategy(self) -> dict:
        """获取入场价格策略完整配置"""
        if "entry_price_strategy" in self.config:
            return self.config["entry_price_strategy"]
        return self.DEFAULT_CONFIG["entry_price_strategy"]
    
    def get_active_entry_strategy(self) -> dict:
        """获取当前激活的入场价格策略参数
        
        返回格式: {"name": "atr", "params": {...}}
        """
        config = self.get_entry_price_strategy()
        strategy_name = config.get("strategy", "atr")
        
        # 兼容旧格式
        if "name" in config and "params" in config:
            return config
        
        # 新格式
        params = config.get(strategy_name, {})
        return {"name": strategy_name, "params": params}
    
    def get_market_aware(self) -> dict:
        """获取行情感知策略完整配置"""
        if "market_aware" in self.config:
            return self.config["market_aware"]
        return self.DEFAULT_CONFIG["market_aware"]
    
    def get_active_market_algorithm(self) -> dict:
        """获取当前激活的行情算法参数
        
        返回格式: {"name": "dual_thrust", "params": {...}, "trading_statuses": [...]}
        """
        config = self.get_market_aware()
        algorithm_name = config.get("algorithm", "dual_thrust")
        
        # 兼容旧格式（顶层参数）
        if "lookback_period" in config or "n_days" in config:
            params = {k: v for k, v in config.items() 
                     if k not in ["algorithm", "enabled", "trading_statuses"]}
            return {
                "name": algorithm_name,
                "params": params,
                "trading_statuses": config.get("trading_statuses", ["ranging"])
            }
        
        # 新格式
        params = config.get(algorithm_name, {})
        return {
            "name": algorithm_name,
            "params": params,
            "trading_statuses": config.get("trading_statuses", ["ranging"])
        }
    
    def set_entry_price_strategy(self, strategy: dict) -> None:
        """设置入场价格策略配置"""
        self.config["entry_price_strategy"] = strategy
    
    def set_market_aware(self, market_aware: dict) -> None:
        """设置行情感知策略配置"""
        self.config["market_aware"] = market_aware
    
    @classmethod
    def load_config(cls, output_dir: str = "out/autofish") -> 'Autofish_ExternStrategy':
        """加载配置（类方法）"""
        instance = cls(output_dir=output_dir)
        if not instance.load():
            instance.config = instance.DEFAULT_CONFIG.copy()
            instance.save()
        return instance


async def main():
    """主函数 - 振幅分析入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Autofish V2 振幅分析")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--interval", type=str, default="1d", help="K线周期 (默认: 1d)")
    parser.add_argument("--limit", type=int, default=1000, help="K线数量 (默认: 1000)")
    parser.add_argument("--leverage", type=int, default=10, help="杠杆倍数 (默认: 10)")
    parser.add_argument("--source", type=str, default="binance", choices=["binance", "longport"], help="数据源: binance(加密货币) 或 longport(港股/美股/A股)")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径 (默认: {source}_{symbol}_amplitude_config.json)")
    parser.add_argument("--entry-strategy", type=str, default="atr", 
                        choices=["fixed", "atr", "bollinger", "support", "composite"],
                        help="入场价格策略: fixed(固定网格), atr(ATR动态), bollinger(布林带), support(支撑位), composite(综合) (默认: atr)")
    
    args = parser.parse_args()
    
    if args.source == "longport" or Autofish_AmplitudeAnalyzer.is_longport_symbol(args.symbol):
        args.source = "longport"
        args.leverage = 1
    
    # 构建入场策略配置
    entry_strategy = DEFAULT_ENTRY_STRATEGY.copy()
    entry_strategy["name"] = args.entry_strategy
    
    analyzer = Autofish_AmplitudeAnalyzer(
        symbol=args.symbol,
        interval=args.interval,
        limit=args.limit,
        leverage=args.leverage,
        source=args.source,
        entry_strategy=entry_strategy
    )
    
    result = await analyzer.analyze()
    
    if result:
        analyzer.save_to_file(args.output)
        analyzer.save_to_markdown()
        
        weights = result.get('recommended_config', {})
        print(f"\n✅ 分析完成!")
        print(f"  配置文件: {analyzer.get_config_filepath()}")
        print(f"  报告文件: {analyzer.get_report_filepath()}")
        print(f"\n📊 推荐配置:")
        print(f"  有效振幅: {weights.get('valid_amplitudes', [])}")
        print(f"  最大层级: {weights.get('max_entries', 4)}")
        print(f"  总预期收益: {weights.get('total_expected_return', 0)*100:.2f}%")
    else:
        print("❌ 分析失败")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()


# ============================================================================
# 资金池管理
# ============================================================================

@dataclass
class FixedCapitalTracker:
    """固定模式资金追踪器
    
    用于固定模式下的资金追踪，记录每轮交易盈亏。
    每轮交易使用固定的初始资金，不进行提现和爆仓恢复。
    
    Attributes:
        initial_capital: 初始资金（来自 total_amount_quote）
        round_profits: 每轮交易盈亏列表
        total_round_profit: 总轮次盈亏
        capital_history: 资金变化历史
    """
    
    initial_capital: Decimal
    round_profits: List[Decimal] = field(default_factory=list)
    total_round_profit: Decimal = Decimal('0')
    capital_history: List[Dict] = field(default_factory=list)
    
    @property
    def trading_capital(self) -> Decimal:
        """固定模式始终返回初始资金"""
        return self.initial_capital
    
    @property
    def strategy(self) -> str:
        return 'guding'
    
    def process_trade_profit(self, profit: Decimal, kline_time: datetime = None) -> Dict:
        """处理交易盈亏
        
        Args:
            profit: 本次交易盈亏
            kline_time: K线时间
            
        Returns:
            处理结果字典
        """
        self.round_profits.append(profit)
        self.total_round_profit += profit
        
        result = {
            'strategy': 'guding',
            'profit': profit,
            'total_round_profit': float(self.total_round_profit),
            'round_count': len(self.round_profits),
        }
        
        self.capital_history.append({
            'timestamp': (kline_time or datetime.now()).isoformat(),
            'profit': float(profit),
            'total_profit': float(self.total_round_profit),
            'event_type': 'trade',
        })
        
        return result
    
    def get_statistics(self) -> Dict:
        """获取统计数据"""
        win_rounds = sum(1 for p in self.round_profits if p > 0)
        loss_rounds = sum(1 for p in self.round_profits if p < 0)
        
        return {
            'strategy': 'guding',
            'initial_capital': round(float(self.initial_capital), 2),
            'final_capital': round(float(self.initial_capital + self.total_round_profit), 2),
            'trading_capital': round(float(self.initial_capital), 2),
            'total_round_profit': round(float(self.total_round_profit), 2),
            'round_count': len(self.round_profits),
            'win_rounds': win_rounds,
            'loss_rounds': loss_rounds,
            'win_rate': round(win_rounds / len(self.round_profits) * 100, 2) if self.round_profits else 0,
            'avg_round_profit': round(float(self.total_round_profit / len(self.round_profits)), 2) if self.round_profits else 0,
            'capital_history': self.capital_history,
        }
    
    def calculate_entry_capital(self, level: int, chain_state: Any) -> Decimal:
        """计算入场资金
        
        固定模式始终使用初始资金
        
        Args:
            level: 订单层级
            chain_state: 链式挂单状态
            
        Returns:
            入场资金
        """
        return self.initial_capital
    
    def calculate_entry_total_capital(self, level: int, chain_state: Any) -> Decimal:
        """计算入场总资金
        
        固定模式始终使用初始资金
        
        Args:
            level: 订单层级
            chain_state: 链式挂单状态
            
        Returns:
            入场总资金
        """
        return self.initial_capital


# ============================================================================
# 资金池策略类
# ============================================================================

class EntryCapitalStrategy:
    """入场资金策略抽象基类
    
    定义入场资金策略的统一接口，用于计算入场资金和入场总资金。
    """
    
    def calculate_entry_capital(self, capital_pool: Union['FixedCapitalTracker', 'ProgressiveCapitalTracker'], level: int, chain_state: Any) -> Decimal:
        """计算入场资金
        
        Args:
            capital_pool: 资金池实例
            level: 订单层级
            chain_state: 链式挂单状态
            
        Returns:
            入场资金
        """
        raise NotImplementedError
    
    def calculate_entry_total_capital(self, capital_pool: Union['FixedCapitalTracker', 'ProgressiveCapitalTracker'], level: int, chain_state: Any) -> Decimal:
        """计算入场总资金
        
        Args:
            capital_pool: 资金池实例
            level: 订单层级
            chain_state: 链式挂单状态
            
        Returns:
            入场总资金
        """
        raise NotImplementedError
    
    def _get_total_capital(self, capital_pool: Union['FixedCapitalTracker', 'ProgressiveCapitalTracker']) -> Decimal:
        """获取总资金（交易资金 + 利润池）
        
        Args:
            capital_pool: 资金池实例
            
        Returns:
            总资金
        """
        if hasattr(capital_pool, 'trading_capital') and hasattr(capital_pool, 'profit_pool'):
            return capital_pool.trading_capital + capital_pool.profit_pool
        elif hasattr(capital_pool, 'trading_capital'):
            return capital_pool.trading_capital
        elif hasattr(capital_pool, 'initial_capital'):
            return capital_pool.initial_capital
        return Decimal('0')


class FixedCapitalStrategy(EntryCapitalStrategy):
    """固定模式资金策略
    
    始终使用初始资金作为入场资金和入场总资金。
    """
    
    def calculate_entry_capital(self, capital_pool: Union['FixedCapitalTracker', 'ProgressiveCapitalTracker'], level: int, chain_state: Any) -> Decimal:
        """计算入场资金 - 返回初始资金"""
        return capital_pool.initial_capital
    
    def calculate_entry_total_capital(self, capital_pool: Union['FixedCapitalTracker', 'ProgressiveCapitalTracker'], level: int, chain_state: Any) -> Decimal:
        """计算入场总资金 - 返回初始资金"""
        return capital_pool.initial_capital


class CompoundCapitalStrategy(EntryCapitalStrategy):
    """复利策略资金策略
    
    使用总资金（交易资金 + 利润池）作为入场资金和入场总资金。
    """
    
    def calculate_entry_capital(self, capital_pool: Union['FixedCapitalTracker', 'ProgressiveCapitalTracker'], level: int, chain_state: Any) -> Decimal:
        """计算入场资金 - 返回总资金"""
        total_capital = self._get_total_capital(capital_pool)
        if level == 1:
            chain_state.round_entry_capital = total_capital
            chain_state.round_entry_total_capital = total_capital
        return chain_state.round_entry_capital
    
    def calculate_entry_total_capital(self, capital_pool: Union['FixedCapitalTracker', 'ProgressiveCapitalTracker'], level: int, chain_state: Any) -> Decimal:
        """计算入场总资金 - 返回总资金"""
        total_capital = self._get_total_capital(capital_pool)
        if level == 1:
            chain_state.round_entry_capital = total_capital
            chain_state.round_entry_total_capital = total_capital
        return chain_state.round_entry_total_capital


class DefaultCapitalStrategy(EntryCapitalStrategy):
    """默认资金策略
    
    入场资金使用交易资金，入场总资金使用总资金（交易资金 + 利润池）。
    """
    
    def calculate_entry_capital(self, capital_pool: Union['FixedCapitalTracker', 'ProgressiveCapitalTracker'], level: int, chain_state: Any) -> Decimal:
        """计算入场资金 - 返回交易资金"""
        if level == 1:
            if hasattr(capital_pool, 'trading_capital'):
                chain_state.round_entry_capital = capital_pool.trading_capital
            else:
                chain_state.round_entry_capital = capital_pool.initial_capital
        return chain_state.round_entry_capital
    
    def calculate_entry_total_capital(self, capital_pool: Union['FixedCapitalTracker', 'ProgressiveCapitalTracker'], level: int, chain_state: Any) -> Decimal:
        """计算入场总资金 - 返回总资金"""
        if level == 1:
            total_capital = self._get_total_capital(capital_pool)
            chain_state.round_entry_total_capital = total_capital
        return chain_state.round_entry_total_capital


class EntryCapitalStrategyFactory:
    """入场资金策略工厂类
    
    根据 entry_mode 创建对应的入场资金策略实例。
    """
    
    _strategies = {
        'fixed': FixedCapitalStrategy,
        'compound': CompoundCapitalStrategy,
        'default': DefaultCapitalStrategy
    }
    
    @classmethod
    def create_strategy(cls, entry_mode: str) -> EntryCapitalStrategy:
        """创建资金策略实例
        
        Args:
            entry_mode: 入场资金计算模式
            
        Returns:
            资金策略实例
        """
        strategy_class = cls._strategies.get(entry_mode, DefaultCapitalStrategy)
        return strategy_class()


@dataclass
class ProgressiveCapitalTracker:
    """递进模式资金追踪器
    
    管理交易资金的动态变化，支持提现和爆仓恢复机制。
    
    Attributes:
        initial_capital: 初始资金
        trading_capital: 当前交易资金（动态变化）
        profit_pool: 利润池（锁定的利润）
        total_profit: 累计利润
        total_loss: 累计亏损
        max_capital: 历史最高资金
        withdrawal_count: 提现次数
        liquidation_count: 爆仓次数
        withdrawal_threshold: 提现阈值倍数
        withdrawal_retain: 提现后保留倍数
        liquidation_threshold: 爆仓阈值倍数
        round_profits: 每轮交易盈亏列表
        total_round_profit: 总轮次盈亏
        capital_history: 资金变化历史
    """
    
    initial_capital: Decimal
    trading_capital: Decimal = None
    profit_pool: Decimal = Decimal('0')
    total_profit: Decimal = Decimal('0')
    total_loss: Decimal = Decimal('0')
    total_withdrawal: Decimal = Decimal('0')
    max_capital: Decimal = Decimal('0')
    withdrawal_count: int = 0
    liquidation_count: int = 0
    
    withdrawal_threshold: Decimal = Decimal('2.0')
    withdrawal_retain: Decimal = Decimal('1.5')
    liquidation_threshold: Decimal = Decimal('0.2')
    _strategy: str = 'baoshou'
    leverage: Decimal = Decimal('10')  # 杠杆倍数
    entry_mode: str = 'compound'  # 入场资金计算模式: fixed, compound, default
    
    round_profits: List[Decimal] = field(default_factory=list)
    total_round_profit: Decimal = Decimal('0')
    capital_history: List[Dict] = field(default_factory=list)
    
    @property
    def strategy(self) -> str:
        return self._strategy
    
    def __post_init__(self):
        if self.trading_capital is None:
            self.trading_capital = self.initial_capital
        self.max_capital = self.initial_capital
    
    def update_capital(self, profit: Decimal, kline_time: datetime = None) -> Dict:
        """更新资金池
        
        Args:
            profit: 本次交易盈亏（正数为盈利，负数为亏损）
            kline_time: K线时间
            
        Returns:
            更新结果字典
        """
        old_trading_capital = self.trading_capital
        
        # 直接使用包含杠杆的利润来更新资金池
        # 这与实际交易一致：止盈后账户直接增加包含杠杆效应的盈利金额
        actual_profit = profit
        
        if actual_profit > 0:
            self.trading_capital += actual_profit
            self.total_profit += actual_profit
        else:
            self.trading_capital += actual_profit
            self.total_loss += abs(actual_profit)
        
        if self.trading_capital > self.max_capital:
            self.max_capital = self.trading_capital
        
        result = {
            'old_capital': old_trading_capital,
            'new_capital': self.trading_capital,
            'profit': actual_profit,
            'withdrawal_triggered': False,
            'liquidation_triggered': False,
        }
        
        self.capital_history.append({
            'timestamp': (kline_time or datetime.now()).isoformat(),
            'old_capital': float(old_trading_capital),
            'new_capital': float(self.trading_capital),
            'profit': float(actual_profit),
            'total_capital': float(self.trading_capital + self.profit_pool),
            'event_type': 'trade',
        })
        
        return result
    
    def check_withdrawal(self, kline_time: datetime = None) -> Optional[Dict]:
        """检查是否触发提现
        
        Args:
            kline_time: K线时间
            
        Returns:
            提现信息字典，如果未触发则返回 None
        """
        threshold_amount = self.initial_capital * self.withdrawal_threshold
        
        if self.trading_capital >= threshold_amount:
            retain_amount = self.initial_capital * self.withdrawal_retain
            withdrawal_amount = self.trading_capital - retain_amount
            old_total = self.trading_capital + self.profit_pool
            
            if withdrawal_amount > 0:
                self.profit_pool += withdrawal_amount
                self.trading_capital = retain_amount
                self.withdrawal_count += 1
                self.total_withdrawal += withdrawal_amount
                
                # 记录提现资金历史，使用 K 线时间
                self.capital_history.append({
                    'timestamp': (kline_time or datetime.now()).isoformat(),
                    'old_capital': float(retain_amount + withdrawal_amount),
                    'new_capital': float(self.trading_capital),
                    'profit': -float(withdrawal_amount),
                    'total_capital': float(self.trading_capital + self.profit_pool),
                    'event_type': 'withdrawal',
                })
                
                return {
                    'withdrawal_amount': withdrawal_amount,
                    'profit_pool': self.profit_pool,
                    'trading_capital': self.trading_capital,
                    'withdrawal_count': self.withdrawal_count,
                }
        
        return None
    
    def check_liquidation(self) -> bool:
        """检查是否爆仓
        
        Returns:
            是否爆仓
        """
        threshold_amount = self.initial_capital * self.liquidation_threshold
        return self.trading_capital < threshold_amount
    
    def recover_from_liquidation(self) -> bool:
        """爆仓恢复
        
        Returns:
            是否成功恢复
        """
        if self.profit_pool >= self.initial_capital:
            self.profit_pool -= self.initial_capital
            self.trading_capital = self.initial_capital
            self.liquidation_count += 1
            return True
        
        return False
    
    def set_strategy(self, strategy: str, stop_loss: float = 0.08, leverage: int = 10):
        """设置提现策略
        
        Args:
            strategy: 策略名称 (baoshou/wenjian/jijin/zidingyi)
            stop_loss: 止损比例（默认 0.08 = 8%）
            leverage: 杠杆倍数（默认 10）
        """
        self._strategy = strategy
        self.leverage = Decimal(str(leverage))  # 存储杠杆值
        auto_liquidation_threshold = 1 - (stop_loss * leverage)
        self.liquidation_threshold = Decimal(str(auto_liquidation_threshold))
        
        if strategy == 'baoshou':
            self.withdrawal_threshold = Decimal('2.0')
            self.withdrawal_retain = Decimal('1.5')
        elif strategy == 'wenjian':
            self.withdrawal_threshold = Decimal('3.0')
            self.withdrawal_retain = Decimal('2.0')
        elif strategy == 'jijin':
            self.withdrawal_threshold = Decimal('1.5')
            self.withdrawal_retain = Decimal('1.2')
        elif strategy == 'fuli':
            self.withdrawal_threshold = Decimal('999.0')
            self.withdrawal_retain = Decimal('1.0')
        elif strategy == 'zidingyi':
            pass
    
    def process_trade_profit(self, profit: Decimal, kline_time: datetime = None) -> Dict:
        """处理交易盈亏（封装完整流程）
        
        Args:
            profit: 本次交易盈亏
            kline_time: K线时间
            
        Returns:
            处理结果字典
        """
        result = self.update_capital(profit, kline_time)
        
        # 使用修正后的实际利润（不含杠杆）来更新轮次盈亏
        actual_profit = result['profit']
        self.round_profits.append(actual_profit)
        self.total_round_profit += actual_profit
        
        withdrawal = self.check_withdrawal(kline_time)
        if withdrawal:
            result['withdrawal'] = withdrawal
        
        if self.check_liquidation():
            result['liquidation_triggered'] = True
            self.recover_from_liquidation()
        
        return result
    
    def get_statistics(self) -> Dict:
        """获取统计数据"""
        total_return = (self.trading_capital + self.profit_pool - self.initial_capital) / self.initial_capital * 100
        
        max_drawdown = Decimal('0')
        if self.max_capital > self.initial_capital:
            max_drawdown = (self.max_capital - self.trading_capital) / self.max_capital * 100
        
        win_rounds = sum(1 for p in self.round_profits if p > 0)
        loss_rounds = sum(1 for p in self.round_profits if p < 0)
        
        return {
            'strategy': self._strategy,
            'initial_capital': round(float(self.initial_capital), 2),
            'final_capital': round(float(self.trading_capital + self.profit_pool), 2),
            'trading_capital': round(float(self.trading_capital), 2),
            'profit_pool': round(float(self.profit_pool), 2),
            'total_return': round(float(total_return), 2),
            'total_profit': round(float(self.total_profit), 2),
            'total_loss': round(float(self.total_loss), 2),
            'max_capital': round(float(self.max_capital), 2),
            'max_drawdown': round(float(max_drawdown), 2),
            'withdrawal_threshold': round(float(self.withdrawal_threshold), 2),
            'withdrawal_retain': round(float(self.withdrawal_retain), 2),
            'liquidation_threshold': round(float(self.liquidation_threshold), 2),
            'withdrawal_count': self.withdrawal_count,
            'total_withdrawal': round(float(self.total_withdrawal), 2),
            'liquidation_count': self.liquidation_count,
            'round_count': len(self.round_profits),
            'win_rounds': win_rounds,
            'loss_rounds': loss_rounds,
            'win_rate': round(win_rounds / len(self.round_profits) * 100, 2) if self.round_profits else 0,
            'avg_round_profit': round(float(self.total_round_profit / len(self.round_profits)), 2) if self.round_profits else 0,
            'capital_history': self.capital_history,
        }
    
    def calculate_entry_capital(self, level: int, chain_state: Any) -> Decimal:
        """计算入场资金
        
        根据 entry_mode 决定计算方式
        
        Args:
            level: 订单层级
            chain_state: 链式挂单状态
            
        Returns:
            入场资金
        """
        if level == 1:
            if self.entry_mode == 'fixed':
                chain_state.round_entry_capital = self.initial_capital
            elif self.entry_mode == 'compound':
                chain_state.round_entry_capital = self.trading_capital + self.profit_pool
            else:  # default
                chain_state.round_entry_capital = self.trading_capital
        return chain_state.round_entry_capital
    
    def calculate_entry_total_capital(self, level: int, chain_state: Any) -> Decimal:
        """计算入场总资金
        
        根据 entry_mode 决定计算方式
        
        Args:
            level: 订单层级
            chain_state: 链式挂单状态
            
        Returns:
            入场总资金
        """
        if level == 1:
            if self.entry_mode == 'fixed':
                chain_state.round_entry_total_capital = self.initial_capital
            elif self.entry_mode == 'compound':
                chain_state.round_entry_total_capital = self.trading_capital + self.profit_pool
            else:  # default
                chain_state.round_entry_total_capital = self.trading_capital + self.profit_pool
        return chain_state.round_entry_total_capital


class CapitalPoolFactory:
    """资金池工厂类
    
    封装资金池初始化逻辑，提供统一的创建接口
    """
    
    @staticmethod
    def create(
        initial_capital: Decimal,
        capital_config: Dict,
        stop_loss: float = 0.08,
        leverage: int = 10
    ) -> Union[FixedCapitalTracker, ProgressiveCapitalTracker]:
        """创建资金池实例
        
        Args:
            initial_capital: 初始资金（来自 total_amount_quote）
            capital_config: 资金配置
            stop_loss: 止损比例（默认 0.08 = 8%）
            leverage: 杠杆倍数（默认 10）
            
        Returns:
            资金池实例
        """
        strategy = capital_config.get('strategy', 'guding')
        
        if strategy == 'guding':
            return FixedCapitalTracker(initial_capital)
        
        tracker = ProgressiveCapitalTracker(initial_capital)
        tracker._strategy = strategy
        
        # 设置入场资金计算模式
        entry_mode = capital_config.get('entry_mode', 'compound')
        tracker.entry_mode = entry_mode
        
        auto_liquidation_threshold = 1 - (stop_loss * leverage)
        
        strategy_params = capital_config.get(strategy, {})
        
        if strategy == 'zidingyi':
            tracker.withdrawal_threshold = Decimal(str(strategy_params.get('withdrawal_threshold', 2.0)))
            tracker.withdrawal_retain = Decimal(str(strategy_params.get('withdrawal_retain', 1.5)))
            tracker.liquidation_threshold = Decimal(str(strategy_params.get('liquidation_threshold', auto_liquidation_threshold)))
        else:
            tracker.set_strategy(strategy, stop_loss, leverage)
            if 'withdrawal_threshold' in strategy_params:
                tracker.withdrawal_threshold = Decimal(str(strategy_params['withdrawal_threshold']))
            if 'withdrawal_retain' in strategy_params:
                tracker.withdrawal_retain = Decimal(str(strategy_params['withdrawal_retain']))
        
        return tracker

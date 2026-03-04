"""
Autofish V1 核心算法模块

包含：
- Order: 订单数据类
- ChainState: 链式挂单状态
- WeightCalculator: 权重计算器
- 核心计算函数
"""

from decimal import Decimal
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """订单"""
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
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Order':
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
        )


@dataclass
class ChainState:
    """链式挂单状态"""
    base_price: Decimal
    orders: List[Order] = field(default_factory=list)
    is_active: bool = True
    
    def get_order_by_order_id(self, order_id: int) -> Optional[Order]:
        """根据订单ID查找订单"""
        for order in self.orders:
            if order.order_id == order_id:
                return order
        return None
    
    def get_order_by_algo_id(self, algo_id: int) -> Optional[Order]:
        """根据 Algo ID 查找订单"""
        for order in self.orders:
            if order.tp_order_id == algo_id or order.sl_order_id == algo_id:
                return order
        return None
    
    def get_pending_order(self) -> Optional[Order]:
        """获取挂单中的订单"""
        for order in self.orders:
            if order.state == "pending":
                return order
        return None
    
    def get_filled_orders(self) -> List[Order]:
        """获取已成交的订单"""
        return [o for o in self.orders if o.state == "filled"]
    
    def get_active_orders(self) -> List[Order]:
        """获取活跃订单（挂单中或已成交）"""
        return [o for o in self.orders if o.state in ["pending", "filled"]]
    
    def cancel_pending_orders(self):
        """取消所有挂单"""
        for order in self.orders:
            if order.state == "pending":
                order.state = "cancelled"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "base_price": str(self.base_price),
            "orders": [o.to_dict() for o in self.orders],
            "is_active": self.is_active,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ChainState':
        """从字典创建"""
        return cls(
            base_price=Decimal(data.get("base_price", "0")),
            orders=[Order.from_dict(o) for o in data.get("orders", [])],
            is_active=data.get("is_active", True),
        )
    
    def save_to_file(self, filepath: str):
        """保存到文件"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(f"[状态保存] 成功保存到: {filepath}")
    
    @classmethod
    def load_from_file(cls, filepath: str) -> Optional['ChainState']:
        """从文件加载"""
        import os
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


class WeightCalculator:
    """权重计算器
    
    基于价格波动幅度的概率分布，计算各层级的资金权重。
    使用衰减因子调整权重分布。
    """
    
    DEFAULT_AMPLITUDE_PROBABILITIES = {
        1: Decimal("0.36"),  # 1% 波动概率
        2: Decimal("0.24"),  # 2% 波动概率
        3: Decimal("0.16"),  # 3% 波动概率
        4: Decimal("0.09"),  # 4% 波动概率
    }
    
    def __init__(self, decay_factor: Decimal = Decimal("0.5")):
        """
        Args:
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
        
        Args:
            level: 层级 (1-4)
            total_amount: 总资金金额
            
        Returns:
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


def calculate_order_prices(
    base_price: Decimal,
    grid_spacing: Decimal,
    exit_profit: Decimal,
    stop_loss: Decimal
) -> Dict[str, Decimal]:
    """计算订单价格
    
    Args:
        base_price: 基准价格
        grid_spacing: 网格间距 (小数，如 0.01 表示 1%)
        exit_profit: 止盈比例 (小数，如 0.01 表示 1%)
        stop_loss: 止损比例 (小数，如 0.08 表示 8%)
        
    Returns:
        包含 entry_price, take_profit_price, stop_loss_price 的字典
    """
    entry_price = base_price * (Decimal("1") - grid_spacing)
    take_profit_price = entry_price * (Decimal("1") + exit_profit)
    stop_loss_price = entry_price * (Decimal("1") - stop_loss)
    
    return {
        "entry_price": entry_price,
        "take_profit_price": take_profit_price,
        "stop_loss_price": stop_loss_price,
    }


def create_order(
    level: int,
    base_price: Decimal,
    grid_spacing: Decimal,
    exit_profit: Decimal,
    stop_loss: Decimal,
    total_amount: Decimal,
    calculator: WeightCalculator
) -> Order:
    """创建订单
    
    Args:
        level: 层级
        base_price: 基准价格
        grid_spacing: 网格间距
        exit_profit: 止盈比例
        stop_loss: 止损比例
        total_amount: 总资金金额
        calculator: 权重计算器
        
    Returns:
        Order 实例
    """
    prices = calculate_order_prices(base_price, grid_spacing, exit_profit, stop_loss)
    stake_amount = calculator.get_stake_amount(level, total_amount)
    quantity = stake_amount / prices["entry_price"]
    
    order = Order(
        level=level,
        entry_price=prices["entry_price"],
        quantity=quantity,
        stake_amount=stake_amount,
        take_profit_price=prices["take_profit_price"],
        stop_loss_price=prices["stop_loss_price"],
        state="pending",
        created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )
    
    logger.info(f"[创建订单] A{level}: entry={prices['entry_price']:.2f}, "
               f"tp={prices['take_profit_price']:.2f}, sl={prices['stop_loss_price']:.2f}, "
               f"stake={stake_amount:.2f} USDT, qty={quantity:.6f} BTC")
    
    return order


def calculate_profit(
    order: Order,
    close_price: Decimal,
    leverage: Decimal = Decimal("10")
) -> Decimal:
    """计算盈亏
    
    Args:
        order: 订单
        close_price: 平仓价格
        leverage: 杠杆倍数
        
    Returns:
        盈亏金额 (正数为盈利，负数为亏损)
    """
    profit = order.stake_amount * (close_price - order.entry_price) / order.entry_price * leverage
    return profit


def check_take_profit_triggered(
    high_price: Decimal,
    take_profit_price: Decimal
) -> bool:
    """检查是否触发止盈
    
    Args:
        high_price: K线最高价
        take_profit_price: 止盈价
        
    Returns:
        是否触发
    """
    return high_price >= take_profit_price


def check_stop_loss_triggered(
    low_price: Decimal,
    stop_loss_price: Decimal
) -> bool:
    """检查是否触发止损
    
    Args:
        low_price: K线最低价
        stop_loss_price: 止损价
        
    Returns:
        是否触发
    """
    return low_price <= stop_loss_price


def check_entry_triggered(
    low_price: Decimal,
    entry_price: Decimal
) -> bool:
    """检查是否触发入场
    
    Args:
        low_price: K线最低价
        entry_price: 入场价
        
    Returns:
        是否触发
    """
    return low_price <= entry_price


def get_default_config() -> Dict[str, Any]:
    """获取默认配置"""
    return {
        "symbol": "BTCUSDT",
        "grid_spacing": Decimal("0.01"),
        "exit_profit": Decimal("0.01"),
        "stop_loss": Decimal("0.08"),
        "decay_factor": Decimal("0.5"),
        "total_amount_quote": Decimal("1200"),
        "leverage": Decimal("10"),
        "max_entries": 4,
    }

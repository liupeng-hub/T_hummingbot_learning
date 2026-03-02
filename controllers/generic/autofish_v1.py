"""
Autofish Strategy V1 - Hummingbot Implementation

链式挂单策略：
- A1: 首次入场，价格 = P0 × 99%
- A2: A1成交后触发，价格 = A1 × 99%
- A3: A2成交后触发，价格 = A2 × 99%
- A4: A3成交后触发，价格 = A3 × 99%
- E:  出场挂单，价格 = A1 × 101%

版本: V1
创建日期: 2026-03-01
"""

from decimal import Decimal
from typing import List, Optional, Dict
from dataclasses import dataclass, field
from enum import Enum

from pydantic import Field

from hummingbot.core.data_type.common import MarketDict, OrderType, PositionMode, PriceType, TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers import ControllerBase, ControllerConfigBase
from hummingbot.strategy_v2.executors.data_types import ConnectorPair
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig, TripleBarrierConfig
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, ExecutorAction, StopExecutorAction
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo


class ChainLevelState(Enum):
    """链式入场层级状态"""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class ChainLevel:
    """链式入场层级"""
    level: int
    target_price: Decimal
    stake_amount: Decimal
    state: ChainLevelState = ChainLevelState.PENDING
    executor_id: Optional[str] = None
    filled_price: Optional[Decimal] = None


@dataclass
class ChainState:
    """链式挂单状态"""
    base_price: Decimal
    levels: List[ChainLevel] = field(default_factory=list)
    current_level: int = 0
    exit_price: Optional[Decimal] = None
    exit_executor_id: Optional[str] = None
    is_active: bool = True

    def get_next_pending_level(self) -> Optional[ChainLevel]:
        """获取下一个待处理的层级"""
        for level in self.levels:
            if level.state == ChainLevelState.PENDING:
                return level
        return None

    def get_filled_levels(self) -> List[ChainLevel]:
        """获取已成交的层级"""
        return [l for l in self.levels if l.state == ChainLevelState.FILLED]

    def get_total_stake(self) -> Decimal:
        """获取总入场金额"""
        return sum(l.stake_amount for l in self.get_filled_levels())

    def get_average_entry_price(self) -> Optional[Decimal]:
        """获取平均入场价格"""
        filled = self.get_filled_levels()
        if not filled:
            return None
        total_value = sum(l.stake_amount * l.filled_price for l in filled if l.filled_price)
        total_stake = sum(l.stake_amount for l in filled if l.filled_price)
        return total_value / total_stake if total_stake > 0 else None


class AutofishV1Config(ControllerConfigBase):
    """
    Autofish V1 策略配置
    """
    controller_type: str = "generic"
    controller_name: str = "autofish_v1"
    candles_config: List[CandlesConfig] = []

    connector_name: str = "binance"
    trading_pair: str = "BTC-USDT"
    leverage: int = 1
    position_mode: PositionMode = PositionMode.ONEWAY

    total_amount_quote: Decimal = Field(default=Decimal("1000"), json_schema_extra={"is_updatable": True})

    grid_spacing: Decimal = Field(default=Decimal("0.01"), json_schema_extra={"is_updatable": True})
    max_entries: int = Field(default=4, json_schema_extra={"is_updatable": True})
    stop_loss: Decimal = Field(default=Decimal("0.09"), json_schema_extra={"is_updatable": True})
    exit_profit: Decimal = Field(default=Decimal("0.01"), json_schema_extra={"is_updatable": True})

    decay_factor: Decimal = Field(default=Decimal("0.5"), json_schema_extra={"is_updatable": True})

    amplitude_probabilities: Dict[int, Decimal] = Field(
        default={
            1: Decimal("0.36"),
            2: Decimal("0.24"),
            3: Decimal("0.16"),
            4: Decimal("0.09"),
        },
        json_schema_extra={"is_updatable": True}
    )

    triple_barrier_config: TripleBarrierConfig = TripleBarrierConfig(
        take_profit=Decimal("0.01"),
        stop_loss=Decimal("0.09"),
        open_order_type=OrderType.LIMIT_MAKER,
        take_profit_order_type=OrderType.LIMIT_MAKER,
        stop_loss_order_type=OrderType.LIMIT_MAKER,
    )

    def update_markets(self, markets: MarketDict) -> MarketDict:
        return markets.add_or_update(self.connector_name, self.trading_pair)


class AutofishV1Controller(ControllerBase):
    """
    Autofish V1 策略控制器

    实现链式挂单逻辑：
    1. A1入场后触发A2挂单
    2. A2入场后触发A3挂单
    3. A3入场后触发A4挂单
    4. 达到盈利目标后出场
    """

    def __init__(self, config: AutofishV1Config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config
        self.chain_state: Optional[ChainState] = None
        self._initialize_rate_sources()

    def _initialize_rate_sources(self):
        """初始化价格数据源"""
        self.market_data_provider.initialize_rate_sources([
            ConnectorPair(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair
            )
        ])

    def _calculate_weights(self) -> List[Decimal]:
        """
        计算振幅权重

        权重公式：W_i = A_i × P_i^(1/d)
        """
        beta = Decimal("1") / self.config.decay_factor
        raw_weights = []

        for amp, prob in self.config.amplitude_probabilities.items():
            raw_weight = Decimal(str(amp)) * (prob ** beta)
            raw_weights.append(raw_weight)

        total = sum(raw_weights)
        weights = [w / total for w in raw_weights]

        return weights

    def _calculate_stake_amounts(self) -> List[Decimal]:
        """计算每次入场的金额"""
        weights = self._calculate_weights()
        stake_amounts = [self.config.total_amount_quote * w for w in weights]
        return stake_amounts

    def _initialize_chain_state(self, base_price: Decimal):
        """
        初始化链式挂单状态

        Args:
            base_price: 基准价格（当前价格）
        """
        stake_amounts = self._calculate_stake_amounts()
        levels = []

        current_price = base_price
        for i in range(self.config.max_entries):
            target_price = current_price * (Decimal("1") - self.config.grid_spacing)
            levels.append(ChainLevel(
                level=i + 1,
                target_price=target_price,
                stake_amount=stake_amounts[i] if i < len(stake_amounts) else stake_amounts[-1],
                state=ChainLevelState.PENDING,
            ))
            current_price = target_price

        self.chain_state = ChainState(
            base_price=base_price,
            levels=levels,
            current_level=0,
        )

        self.logger().info(f"初始化链式挂单状态: 基准价={base_price}, 层级数={len(levels)}")
        for level in levels:
            self.logger().info(f"  A{level.level}: 目标价={level.target_price:.4f}, 金额={level.stake_amount:.2f}")

    def active_executors(self) -> List[ExecutorInfo]:
        """获取活跃的执行器"""
        return [
            executor for executor in self.executors_info
            if executor.is_active
        ]

    def determine_executor_actions(self) -> List[ExecutorAction]:
        """
        决定执行器动作

        这是策略的核心逻辑：
        1. 如果没有链式状态，初始化并创建第一个入场订单
        2. 如果有订单成交，检查是否需要创建下一个入场订单
        3. 如果达到盈利目标，创建出场订单
        """
        actions = []

        mid_price = self.market_data_provider.get_price_by_type(
            self.config.connector_name,
            self.config.trading_pair,
            PriceType.MidPrice
        )

        if self.chain_state is None:
            self._initialize_chain_state(mid_price)
            first_level = self.chain_state.levels[0] if self.chain_state.levels else None
            if first_level:
                actions.append(self._create_entry_order(first_level))
                self.logger().info(f"初始化后创建A{first_level.level}入场订单: 目标价={first_level.target_price:.4f}")
            return actions

        if not self.chain_state.is_active:
            return actions

        if len(self.active_executors()) == 0:
            next_level = self.chain_state.get_next_pending_level()
            if next_level:
                actions.append(self._create_entry_order(next_level))
                self.logger().info(f"创建A{next_level.level}入场订单: 目标价={next_level.target_price:.4f}")

        return actions

    def _create_entry_order(self, level: ChainLevel) -> CreateExecutorAction:
        """创建入场订单"""
        return CreateExecutorAction(
            controller_id=self.config.id,
            executor_config=PositionExecutorConfig(
                timestamp=self.market_data_provider.time(),
                level_id=f"A{level.level}",
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                entry_price=level.target_price,
                amount=level.stake_amount / level.target_price,
                triple_barrier_config=TripleBarrierConfig(
                    take_profit=self.config.exit_profit,
                    stop_loss=self.config.stop_loss,
                    open_order_type=OrderType.LIMIT_MAKER,
                    take_profit_order_type=OrderType.LIMIT_MAKER,
                    stop_loss_order_type=OrderType.MARKET,
                ),
                leverage=self.config.leverage,
                side=TradeType.BUY,
            )
        )

    def on_executor_filled(self, executor_info: ExecutorInfo):
        """
        执行器成交回调

        当订单成交时，更新链式状态并触发下一个入场订单
        """
        super().on_executor_filled(executor_info)

        if self.chain_state is None:
            return

        level_id = executor_info.level_id
        if level_id and level_id.startswith("A"):
            level_num = int(level_id[1:])
            for level in self.chain_state.levels:
                if level.level == level_num:
                    level.state = ChainLevelState.FILLED
                    level.filled_price = executor_info.executed_amount_quote / executor_info.executed_amount_base
                    level.executor_id = executor_info.id

                    self.logger().info(f"A{level.level}成交: 价格={level.filled_price:.4f}, 金额={level.stake_amount:.2f}")

                    self.chain_state.current_level = level_num

                    avg_price = self.chain_state.get_average_entry_price()
                    if avg_price:
                        self.chain_state.exit_price = avg_price * (Decimal("1") + self.config.exit_profit)
                        self.logger().info(f"更新出场价: {self.chain_state.exit_price:.4f}")
                    break

    def on_executor_cancelled(self, executor_info: ExecutorInfo):
        """执行器取消回调"""
        super().on_executor_cancelled(executor_info)

        if self.chain_state is None:
            return

        level_id = executor_info.level_id
        if level_id and level_id.startswith("A"):
            level_num = int(level_id[1:])
            for level in self.chain_state.levels:
                if level.level == level_num:
                    level.state = ChainLevelState.CANCELLED
                    self.logger().info(f"A{level.level}已取消")
                    break

    async def update_processed_data(self):
        """更新处理后的数据"""
        pass

    def to_format_status(self) -> List[str]:
        """格式化状态显示"""
        status = []

        mid_price = self.market_data_provider.get_price_by_type(
            self.config.connector_name,
            self.config.trading_pair,
            PriceType.MidPrice
        )

        status.append("┌" + "─" * 80 + "┐")
        status.append("│ Autofish V1 Strategy Status" + " " * 51 + "│")
        status.append("├" + "─" * 80 + "┤")

        if self.chain_state:
            status.append(f"│ Base Price: {self.chain_state.base_price:.4f} │ Mid Price: {mid_price:.4f} │ Active: {self.chain_state.is_active}" + " " * 15 + "│")

            avg_entry = self.chain_state.get_average_entry_price()
            if avg_entry:
                status.append(f"│ Avg Entry: {avg_entry:.4f} │ Exit Price: {self.chain_state.exit_price:.4f}" + " " * 26 + "│")

            status.append("├" + "─" * 80 + "┤")
            status.append("│ Chain Levels:" + " " * 66 + "│")

            for level in self.chain_state.levels:
                state_str = level.state.value
                filled_str = f"Filled: {level.filled_price:.4f}" if level.filled_price else "Not filled"
                status.append(f"│   A{level.level}: Target={level.target_price:.4f} | Stake={level.stake_amount:.2f} | {state_str} | {filled_str}" + " " * 10 + "│")
        else:
            status.append("│ Chain state not initialized" + " " * 52 + "│")

        status.append("└" + "─" * 80 + "┘")

        return status

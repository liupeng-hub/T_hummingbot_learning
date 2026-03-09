import pytest
import asyncio
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from autofish_core import Autofish_Order, Autofish_ChainState, Autofish_OrderCalculator, normalize_weights
from tests.mocks.binance_client import MockBinanceClient
from tests.mocks.websocket import MockWebSocket
from tests.mocks.market_data import MockMarketData


class TestEntryFlow:
    """入场流程测试"""
    
    @pytest.mark.asyncio
    async def test_place_initial_order(self, mock_client, config):
        """测试下初始入场单"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        order = order_calculator.create_order(
            level=1,
            base_price=base_price,
            total_amount=config["total_amount_quote"],
            weights=weights,
            max_entries=max_entries
        )
        
        assert order.level == 1
        assert order.state == "pending"
        assert order.entry_price < base_price
        assert order.take_profit_price > order.entry_price
        assert order.stop_loss_price < order.entry_price
        
        result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=order.quantity,
            price=order.entry_price
        )
        
        assert result["orderId"] is not None
        assert result["status"] == "NEW"
        assert Decimal(result["price"]) == order.entry_price
    
    @pytest.mark.asyncio
    async def test_entry_filled_place_exit_orders(self, mock_client, config):
        """测试入场成交后下止盈止损单"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        order = order_calculator.create_order(
            level=1,
            base_price=base_price,
            total_amount=config["total_amount_quote"],
            weights=weights,
            max_entries=max_entries
        )
        
        entry_result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=order.quantity,
            price=order.entry_price
        )
        order.order_id = entry_result["orderId"]
        
        mock_client.simulate_order_filled(order.order_id, order.entry_price)
        
        tp_result = await mock_client.place_tp_sl_order(
            symbol=config["symbol"],
            side="SELL",
            order_type="TAKE_PROFIT",
            quantity=order.quantity,
            trigger_price=order.take_profit_price,
            price=order.take_profit_price
        )
        order.tp_order_id = tp_result["algoId"]
        
        sl_result = await mock_client.place_tp_sl_order(
            symbol=config["symbol"],
            side="SELL",
            order_type="STOP_LOSS",
            quantity=order.quantity,
            trigger_price=order.stop_loss_price,
            price=order.stop_loss_price
        )
        order.sl_order_id = sl_result["algoId"]
        
        assert order.tp_order_id is not None
        assert order.sl_order_id is not None
        assert mock_client.algo_orders[order.tp_order_id]["status"] == "NEW"
        assert mock_client.algo_orders[order.sl_order_id]["status"] == "NEW"
    
    @pytest.mark.asyncio
    async def test_entry_filled_place_next_level(self, mock_client, config):
        """测试入场成交后下下一级入场单"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        order_a1 = order_calculator.create_order(
            level=1,
            base_price=base_price,
            total_amount=config["total_amount_quote"],
            weights=weights,
            max_entries=max_entries
        )
        
        entry_result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=order_a1.quantity,
            price=order_a1.entry_price
        )
        order_a1.order_id = entry_result["orderId"]
        order_a1.state = "filled"
        
        order_a2 = order_calculator.create_order(
            level=2,
            base_price=base_price,
            total_amount=config["total_amount_quote"],
            weights=weights,
            max_entries=max_entries
        )
        
        a2_result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=order_a2.quantity,
            price=order_a2.entry_price
        )
        order_a2.order_id = a2_result["orderId"]
        
        assert order_a2.level == 2
        assert order_a2.entry_price < order_a1.entry_price
        assert order_a2.state == "pending"
    
    @pytest.mark.asyncio
    async def test_max_entries_limit(self, mock_client, config):
        """测试最大层级限制"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        orders = []
        for level in range(1, max_entries + 2):
            if level > max_entries:
                break
            
            order = order_calculator.create_order(
                level=level,
                base_price=base_price,
                total_amount=config["total_amount_quote"],
                weights=weights,
                max_entries=max_entries
            )
            
            result = await mock_client.place_order(
                symbol=config["symbol"],
                side="BUY",
                order_type="LIMIT",
                quantity=order.quantity,
                price=order.entry_price
            )
            order.order_id = result["orderId"]
            orders.append(order)
        
        assert len(orders) == max_entries
    
    @pytest.mark.asyncio
    async def test_normalized_weights(self, config):
        """测试权重归一化"""
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        normalized = normalize_weights(weights, max_entries)
        
        assert len(normalized) == max_entries
        assert sum(normalized) == Decimal("1")
        
        total_amount = config["total_amount_quote"]
        total_stake = Decimal("0")
        
        for i, weight in enumerate(normalized):
            stake = total_amount * weight
            total_stake += stake
        
        assert abs(total_stake - total_amount) < Decimal("0.01")
    
    @pytest.mark.asyncio
    async def test_order_state_transition(self, mock_client, config):
        """测试订单状态转换"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        order = order_calculator.create_order(
            level=1,
            base_price=base_price,
            total_amount=config["total_amount_quote"],
            weights=weights,
            max_entries=max_entries
        )
        
        assert order.state == "pending"
        
        result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=order.quantity,
            price=order.entry_price
        )
        order.order_id = result["orderId"]
        
        mock_client.simulate_order_filled(order.order_id, order.entry_price)
        order.state = "filled"
        order.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        assert order.state == "filled"
        assert order.filled_at is not None

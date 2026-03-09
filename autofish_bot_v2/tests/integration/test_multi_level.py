import pytest
import asyncio
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from autofish_core import Autofish_Order, Autofish_ChainState, Autofish_OrderCalculator, normalize_weights
from binance_live import CloseReason
from tests.mocks.binance_client import MockBinanceClient
from tests.mocks.websocket import MockWebSocket
from tests.mocks.market_data import MockMarketData


class TestMultiLevel:
    """多层级订单测试"""
    
    @pytest.mark.asyncio
    async def test_a1_to_a2_flow(self, mock_client, config):
        """测试 A1 成交后下 A2"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        chain_state = Autofish_ChainState(base_price=base_price)
        
        a1 = order_calculator.create_order(
            level=1,
            base_price=base_price,
            total_amount=config["total_amount_quote"],
            weights=weights,
            max_entries=max_entries
        )
        a1_result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=a1.quantity,
            price=a1.entry_price
        )
        a1.order_id = a1_result["orderId"]
        chain_state.orders.append(a1)
        
        a1.state = "filled"
        a1.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        a2 = order_calculator.create_order(
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
            quantity=a2.quantity,
            price=a2.entry_price
        )
        a2.order_id = a2_result["orderId"]
        chain_state.orders.append(a2)
        
        assert len(chain_state.orders) == 2
        assert chain_state.orders[0].level == 1
        assert chain_state.orders[1].level == 2
        assert chain_state.orders[1].entry_price < chain_state.orders[0].entry_price
    
    @pytest.mark.asyncio
    async def test_full_chain_flow(self, mock_client, config):
        """测试完整链式订单 A1 -> A2 -> A3 -> A4"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        chain_state = Autofish_ChainState(base_price=base_price)
        
        for level in range(1, max_entries + 1):
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
            order.state = "filled"
            order.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            chain_state.orders.append(order)
        
        assert len(chain_state.orders) == max_entries
        
        for i, order in enumerate(chain_state.orders):
            assert order.level == i + 1
            assert order.state == "filled"
            
            if i > 0:
                prev_order = chain_state.orders[i - 1]
                assert order.entry_price < prev_order.entry_price
    
    @pytest.mark.asyncio
    async def test_a1_tp_cancels_a2(self, mock_client, config):
        """测试 A1 止盈取消 A2"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        chain_state = Autofish_ChainState(base_price=base_price)
        
        a1 = order_calculator.create_order(
            level=1,
            base_price=base_price,
            total_amount=config["total_amount_quote"],
            weights=weights,
            max_entries=max_entries
        )
        a1_result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=a1.quantity,
            price=a1.entry_price
        )
        a1.order_id = a1_result["orderId"]
        a1.state = "filled"
        a1.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        chain_state.orders.append(a1)
        
        tp_result = await mock_client.place_tp_sl_order(
            symbol=config["symbol"],
            side="SELL",
            order_type="TAKE_PROFIT",
            quantity=a1.quantity,
            trigger_price=a1.take_profit_price,
            price=a1.take_profit_price
        )
        a1.tp_order_id = tp_result["algoId"]
        
        sl_result = await mock_client.place_tp_sl_order(
            symbol=config["symbol"],
            side="SELL",
            order_type="STOP_LOSS",
            quantity=a1.quantity,
            trigger_price=a1.stop_loss_price,
            price=a1.stop_loss_price
        )
        a1.sl_order_id = sl_result["algoId"]
        
        a2 = order_calculator.create_order(
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
            quantity=a2.quantity,
            price=a2.entry_price
        )
        a2.order_id = a2_result["orderId"]
        chain_state.orders.append(a2)
        
        mock_client.simulate_algo_triggered(a1.tp_order_id, a1.take_profit_price)
        a1.state = "closed"
        a1.close_reason = CloseReason.TAKE_PROFIT.value
        a1.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        a1.close_price = a1.take_profit_price
        
        await mock_client.cancel_order(config["symbol"], a2.order_id)
        await mock_client.cancel_algo_order(config["symbol"], a1.sl_order_id)
        
        assert mock_client.orders[a2.order_id]["status"] == "CANCELED"
        assert mock_client.algo_orders[a1.sl_order_id]["status"] == "CANCELED"
    
    @pytest.mark.asyncio
    async def test_weight_distribution(self, config):
        """测试权重分配"""
        weights = config["weights"]
        max_entries = config["max_entries"]
        total_amount = config["total_amount_quote"]
        
        normalized = normalize_weights(weights, max_entries)
        
        stakes = []
        for i, weight in enumerate(normalized):
            stake = total_amount * weight
            stakes.append(stake)
        
        assert sum(stakes) == total_amount
        
        for i in range(len(stakes) - 1):
            if normalized[i] > normalized[i + 1]:
                assert stakes[i] > stakes[i + 1]

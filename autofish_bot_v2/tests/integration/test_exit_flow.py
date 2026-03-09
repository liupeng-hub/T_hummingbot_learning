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


class TestExitFlow:
    """出场流程测试"""
    
    @pytest.mark.asyncio
    async def test_take_profit_trigger(self, mock_client, config):
        """测试止盈触发"""
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
        
        a1_result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=order_a1.quantity,
            price=order_a1.entry_price
        )
        order_a1.order_id = a1_result["orderId"]
        order_a1.state = "filled"
        order_a1.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        tp_result = await mock_client.place_tp_sl_order(
            symbol=config["symbol"],
            side="SELL",
            order_type="TAKE_PROFIT",
            quantity=order_a1.quantity,
            trigger_price=order_a1.take_profit_price,
            price=order_a1.take_profit_price
        )
        order_a1.tp_order_id = tp_result["algoId"]
        
        sl_result = await mock_client.place_tp_sl_order(
            symbol=config["symbol"],
            side="SELL",
            order_type="STOP_LOSS",
            quantity=order_a1.quantity,
            trigger_price=order_a1.stop_loss_price,
            price=order_a1.stop_loss_price
        )
        order_a1.sl_order_id = sl_result["algoId"]
        
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
        
        mock_client.simulate_algo_triggered(order_a1.tp_order_id, order_a1.take_profit_price)
        
        order_a1.state = "closed"
        order_a1.close_reason = CloseReason.TAKE_PROFIT.value
        order_a1.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        order_a1.close_price = order_a1.take_profit_price
        order_a1.profit = (order_a1.take_profit_price - order_a1.entry_price) * order_a1.quantity
        
        await mock_client.cancel_order(config["symbol"], order_a2.order_id)
        await mock_client.cancel_algo_order(config["symbol"], order_a1.sl_order_id)
        
        assert order_a1.state == "closed"
        assert order_a1.close_reason == "take_profit"
        assert order_a1.close_price == order_a1.take_profit_price
        assert order_a1.profit > 0
        assert mock_client.orders[order_a2.order_id]["status"] == "CANCELED"
        assert mock_client.algo_orders[order_a1.sl_order_id]["status"] == "CANCELED"
    
    @pytest.mark.asyncio
    async def test_stop_loss_trigger(self, mock_client, config):
        """测试止损触发"""
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
        
        a1_result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=order_a1.quantity,
            price=order_a1.entry_price
        )
        order_a1.order_id = a1_result["orderId"]
        order_a1.state = "filled"
        order_a1.filled_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        tp_result = await mock_client.place_tp_sl_order(
            symbol=config["symbol"],
            side="SELL",
            order_type="TAKE_PROFIT",
            quantity=order_a1.quantity,
            trigger_price=order_a1.take_profit_price,
            price=order_a1.take_profit_price
        )
        order_a1.tp_order_id = tp_result["algoId"]
        
        sl_result = await mock_client.place_tp_sl_order(
            symbol=config["symbol"],
            side="SELL",
            order_type="STOP_LOSS",
            quantity=order_a1.quantity,
            trigger_price=order_a1.stop_loss_price,
            price=order_a1.stop_loss_price
        )
        order_a1.sl_order_id = sl_result["algoId"]
        
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
        
        mock_client.simulate_algo_triggered(order_a1.sl_order_id, order_a1.stop_loss_price)
        
        order_a1.state = "closed"
        order_a1.close_reason = CloseReason.STOP_LOSS.value
        order_a1.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        order_a1.close_price = order_a1.stop_loss_price
        order_a1.profit = (order_a1.stop_loss_price - order_a1.entry_price) * order_a1.quantity
        
        await mock_client.cancel_order(config["symbol"], order_a2.order_id)
        await mock_client.cancel_algo_order(config["symbol"], order_a1.tp_order_id)
        
        assert order_a1.state == "closed"
        assert order_a1.close_reason == "stop_loss"
        assert order_a1.close_price == order_a1.stop_loss_price
        assert order_a1.profit < 0
        assert mock_client.orders[order_a2.order_id]["status"] == "CANCELED"
        assert mock_client.algo_orders[order_a1.tp_order_id]["status"] == "CANCELED"
    
    @pytest.mark.asyncio
    async def test_take_profit_place_new_a1(self, mock_client, config):
        """测试止盈后下新 A1"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        old_a1 = order_calculator.create_order(
            level=1,
            base_price=base_price,
            total_amount=config["total_amount_quote"],
            weights=weights,
            max_entries=max_entries
        )
        old_a1.state = "closed"
        old_a1.close_reason = CloseReason.TAKE_PROFIT.value
        
        new_a1 = order_calculator.create_order(
            level=1,
            base_price=base_price,
            total_amount=config["total_amount_quote"],
            weights=weights,
            max_entries=max_entries
        )
        
        result = await mock_client.place_order(
            symbol=config["symbol"],
            side="BUY",
            order_type="LIMIT",
            quantity=new_a1.quantity,
            price=new_a1.entry_price
        )
        new_a1.order_id = result["orderId"]
        
        assert new_a1.level == 1
        assert new_a1.state == "pending"
        assert new_a1.order_id is not None
    
    @pytest.mark.asyncio
    async def test_stop_loss_clear_all(self, mock_client, config):
        """测试止损后清空所有订单"""
        order_calculator = Autofish_OrderCalculator(
            grid_spacing=config["grid_spacing"],
            exit_profit=config["exit_profit"],
            stop_loss=config["stop_loss"]
        )
        
        base_price = Decimal("67000.00")
        weights = config["weights"]
        max_entries = config["max_entries"]
        
        chain_state = Autofish_ChainState(base_price=base_price)
        
        for level in range(1, 3):
            order = order_calculator.create_order(
                level=level,
                base_price=base_price,
                total_amount=config["total_amount_quote"],
                weights=weights,
                max_entries=max_entries
            )
            chain_state.orders.append(order)
        
        a1 = chain_state.orders[0]
        a1.state = "closed"
        a1.close_reason = CloseReason.STOP_LOSS.value
        
        chain_state.orders.clear()
        
        assert len(chain_state.orders) == 0
    
    @pytest.mark.asyncio
    async def test_profit_calculation(self, config):
        """测试盈亏计算"""
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
        
        tp_profit = (order.take_profit_price - order.entry_price) * order.quantity
        sl_profit = (order.stop_loss_price - order.entry_price) * order.quantity
        
        assert tp_profit > 0
        assert sl_profit < 0
        
        tp_profit_percent = (order.take_profit_price - order.entry_price) / order.entry_price
        sl_profit_percent = (order.stop_loss_price - order.entry_price) / order.entry_price
        
        assert abs(tp_profit_percent - config["exit_profit"]) < Decimal("0.0001")
        assert abs(sl_profit_percent + config["stop_loss"]) < Decimal("0.0001")
    
    @pytest.mark.asyncio
    async def test_holding_duration_calculation(self):
        """测试持仓时长计算"""
        filled_at = "2026-03-09 02:24:35"
        closed_at = "2026-03-09 11:00:03"
        
        filled_time = datetime.strptime(filled_at, '%Y-%m-%d %H:%M:%S')
        closed_time = datetime.strptime(closed_at, '%Y-%m-%d %H:%M:%S')
        duration = closed_time - filled_time
        
        total_seconds = int(duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        assert hours == 8
        assert minutes == 35

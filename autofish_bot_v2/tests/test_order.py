"""
Autofish_Order 类单元测试

测试 Autofish_Order 类的初始化、状态转换、序列化和反序列化。
"""

import unittest
from decimal import Decimal
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autofish_core import Autofish_Order


class TestOrder(unittest.TestCase):
    """
    Autofish_Order 类测试用例
    
    测试内容：
        - 订单初始化
        - 状态转换
        - 序列化/反序列化
        - 属性验证
    """
    
    def setUp(self):
        """测试前置：创建测试订单"""
        self.order = Autofish_Order(
            level=1,
            entry_price=Decimal("50000.00"),
            quantity=Decimal("0.001"),
            stake_amount=Decimal("50.00"),
            take_profit_price=Decimal("50500.00"),
            stop_loss_price=Decimal("46000.00"),
        )
    
    def test_order_initialization(self):
        """测试订单初始化"""
        self.assertEqual(self.order.level, 1)
        self.assertEqual(self.order.entry_price, Decimal("50000.00"))
        self.assertEqual(self.order.quantity, Decimal("0.001"))
        self.assertEqual(self.order.stake_amount, Decimal("50.00"))
        self.assertEqual(self.order.take_profit_price, Decimal("50500.00"))
        self.assertEqual(self.order.stop_loss_price, Decimal("46000.00"))
        self.assertEqual(self.order.state, "pending")
        self.assertIsNone(self.order.order_id)
        self.assertIsNone(self.order.tp_order_id)
        self.assertIsNone(self.order.sl_order_id)
    
    def test_order_set_state_to_filled(self):
        """测试订单状态转换为已成交"""
        self.order.set_state("filled")
        
        self.assertEqual(self.order.state, "filled")
        self.assertIsNotNone(self.order.filled_at)
    
    def test_order_set_state_to_closed(self):
        """测试订单状态转换为已平仓"""
        self.order.set_state("closed", "take_profit")
        
        self.assertEqual(self.order.state, "closed")
        self.assertEqual(self.order.close_reason, "take_profit")
        self.assertIsNotNone(self.order.closed_at)
    
    def test_order_to_dict(self):
        """测试订单序列化为字典"""
        self.order.order_id = 12345
        self.order.state = "filled"
        
        data = self.order.to_dict()
        
        self.assertEqual(data["level"], 1)
        self.assertEqual(data["entry_price"], "50000.00")
        self.assertEqual(data["quantity"], "0.001")
        self.assertEqual(data["stake_amount"], "50.00")
        self.assertEqual(data["take_profit_price"], "50500.00")
        self.assertEqual(data["stop_loss_price"], "46000.00")
        self.assertEqual(data["state"], "filled")
        self.assertEqual(data["order_id"], 12345)
    
    def test_order_from_dict(self):
        """测试从字典创建订单"""
        data = {
            "level": 2,
            "entry_price": "49000.00",
            "quantity": "0.002",
            "stake_amount": "98.00",
            "take_profit_price": "49490.00",
            "stop_loss_price": "45080.00",
            "state": "filled",
            "order_id": 67890,
            "tp_order_id": 11111,
            "sl_order_id": 22222,
        }
        
        order = Autofish_Order.from_dict(data)
        
        self.assertEqual(order.level, 2)
        self.assertEqual(order.entry_price, Decimal("49000.00"))
        self.assertEqual(order.quantity, Decimal("0.002"))
        self.assertEqual(order.stake_amount, Decimal("98.00"))
        self.assertEqual(order.take_profit_price, Decimal("49490.00"))
        self.assertEqual(order.stop_loss_price, Decimal("45080.00"))
        self.assertEqual(order.state, "filled")
        self.assertEqual(order.order_id, 67890)
        self.assertEqual(order.tp_order_id, 11111)
        self.assertEqual(order.sl_order_id, 22222)
    
    def test_order_round_trip(self):
        """测试订单序列化后反序列化，数据不变"""
        self.order.order_id = 12345
        self.order.tp_order_id = 11111
        self.order.sl_order_id = 22222
        self.order.state = "filled"
        self.order.tp_supplemented = True
        
        data = self.order.to_dict()
        restored_order = Autofish_Order.from_dict(data)
        
        self.assertEqual(restored_order.level, self.order.level)
        self.assertEqual(restored_order.entry_price, self.order.entry_price)
        self.assertEqual(restored_order.quantity, self.order.quantity)
        self.assertEqual(restored_order.stake_amount, self.order.stake_amount)
        self.assertEqual(restored_order.take_profit_price, self.order.take_profit_price)
        self.assertEqual(restored_order.stop_loss_price, self.order.stop_loss_price)
        self.assertEqual(restored_order.state, self.order.state)
        self.assertEqual(restored_order.order_id, self.order.order_id)
        self.assertEqual(restored_order.tp_order_id, self.order.tp_order_id)
        self.assertEqual(restored_order.sl_order_id, self.order.sl_order_id)
        self.assertEqual(restored_order.tp_supplemented, self.order.tp_supplemented)


if __name__ == "__main__":
    unittest.main()

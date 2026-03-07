"""
Autofish_WeightCalculator 类单元测试

测试权重计算器的权重计算和资金分配功能。
"""

import unittest
from decimal import Decimal

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autofish_core import Autofish_WeightCalculator


class TestWeightCalculator(unittest.TestCase):
    """
    Autofish_WeightCalculator 类测试用例
    
    测试内容：
        - 权重计算
        - 权重归一化
        - 资金分配
        - 权重百分比
    """
    
    def setUp(self):
        """测试前置：创建权重计算器"""
        self.calculator = Autofish_WeightCalculator(decay_factor=Decimal("0.5"))
    
    def test_calculator_initialization(self):
        """测试计算器初始化"""
        self.assertEqual(self.calculator.decay_factor, Decimal("0.5"))
        self.assertIsNotNone(self.calculator.amplitude_probabilities)
    
    def test_calculate_weights(self):
        """测试权重计算"""
        weights = self.calculator.calculate_weights()
        
        # 验证权重数量
        self.assertEqual(len(weights), 4)
        
        # 验证权重总和为1
        total = sum(weights)
        self.assertAlmostEqual(float(total), 1.0, places=6)
        
        # 验证权重递减（层级越高，权重越小）
        for i in range(len(weights) - 1):
            self.assertGreater(weights[i], weights[i + 1])
    
    def test_get_stake_amount(self):
        """测试资金分配"""
        total_amount = Decimal("1000")
        
        # 测试各层级资金分配
        stake_1 = self.calculator.get_stake_amount(1, total_amount)
        stake_2 = self.calculator.get_stake_amount(2, total_amount)
        stake_3 = self.calculator.get_stake_amount(3, total_amount)
        stake_4 = self.calculator.get_stake_amount(4, total_amount)
        
        # 验证资金分配总和等于总资金
        total_stake = stake_1 + stake_2 + stake_3 + stake_4
        self.assertAlmostEqual(float(total_stake), float(total_amount), places=2)
        
        # 验证资金分配递减
        self.assertGreater(stake_1, stake_2)
        self.assertGreater(stake_2, stake_3)
        self.assertGreater(stake_3, stake_4)
    
    def test_get_weight_percentage(self):
        """测试权重百分比"""
        pct_1 = self.calculator.get_weight_percentage(1)
        pct_2 = self.calculator.get_weight_percentage(2)
        
        # 验证百分比总和为100
        weights = self.calculator.calculate_weights()
        total_pct = sum(w * 100 for w in weights)
        self.assertAlmostEqual(float(total_pct), 100.0, places=6)
        
        # 验证百分比递减
        self.assertGreater(pct_1, pct_2)
    
    def test_different_decay_factors(self):
        """测试不同衰减因子的影响"""
        # 低衰减因子：权重更集中
        calculator_low = Autofish_WeightCalculator(decay_factor=Decimal("0.3"))
        weights_low = calculator_low.calculate_weights()
        
        # 高衰减因子：权重更均匀
        calculator_high = Autofish_WeightCalculator(decay_factor=Decimal("0.8"))
        weights_high = calculator_high.calculate_weights()
        
        # 验证低衰减因子时，第一层权重更大
        self.assertGreater(weights_low[0], weights_high[0])
        
        # 验证高衰减因子时，最后一层权重更大
        self.assertGreater(weights_high[-1], weights_low[-1])
    
    def test_stake_amount_for_invalid_level(self):
        """测试无效层级的资金分配"""
        total_amount = Decimal("1000")
        
        # 层级超出范围时，返回最后一层的资金
        stake_5 = self.calculator.get_stake_amount(5, total_amount)
        stake_4 = self.calculator.get_stake_amount(4, total_amount)
        
        self.assertEqual(stake_5, stake_4)


if __name__ == "__main__":
    unittest.main()

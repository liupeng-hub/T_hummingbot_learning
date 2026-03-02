"""
Autofish V1 策略单元测试

运行方式：
    cd /Users/liupeng/Documents/trae_projects/hummingbot_learning
    python3 tests/test_autofish_v1.py
"""

import unittest
from decimal import Decimal
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class ChainLevel:
    """链式入场层级"""
    level: int
    target_price: Decimal
    stake_amount: Decimal
    state: str = "pending"
    executor_id: Optional[str] = None
    filled_price: Optional[Decimal] = None


@dataclass
class ChainState:
    """链式挂单状态"""
    base_price: Decimal
    levels: List[ChainLevel]
    current_level: int = 0
    exit_price: Optional[Decimal] = None
    exit_executor_id: Optional[str] = None
    is_active: bool = True

    def get_next_pending_level(self) -> Optional[ChainLevel]:
        """获取下一个待处理的层级"""
        for level in self.levels:
            if level.state == "pending":
                return level
        return None

    def get_filled_levels(self) -> List[ChainLevel]:
        """获取已成交的层级"""
        return [l for l in self.levels if l.state == "filled"]

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


class WeightCalculator:
    """权重计算器"""

    def __init__(self, decay_factor: Decimal = Decimal("0.5")):
        self.decay_factor = decay_factor
        self.amplitude_probabilities = {
            1: Decimal("0.36"),
            2: Decimal("0.24"),
            3: Decimal("0.16"),
            4: Decimal("0.09"),
        }

    def calculate_weights(self) -> List[Decimal]:
        """计算振幅权重"""
        beta = Decimal("1") / self.decay_factor
        raw_weights = []

        for amp, prob in self.amplitude_probabilities.items():
            raw_weight = Decimal(str(amp)) * (prob ** beta)
            raw_weights.append(raw_weight)

        total = sum(raw_weights)
        weights = [w / total for w in raw_weights]

        return weights

    def calculate_stake_amounts(self, total_amount: Decimal) -> List[Decimal]:
        """计算每次入场的金额"""
        weights = self.calculate_weights()
        stake_amounts = [total_amount * w for w in weights]
        return stake_amounts


class TestWeightCalculator(unittest.TestCase):
    """权重计算测试"""

    def test_calculate_weights(self):
        """测试权重计算"""
        calculator = WeightCalculator()
        weights = calculator.calculate_weights()

        self.assertEqual(len(weights), 4)
        self.assertAlmostEqual(float(sum(weights)), 1.0, places=4)

        print("\n权重计算结果:")
        for i, w in enumerate(weights):
            print(f"  A{i+1}: {float(w)*100:.2f}%")

    def test_calculate_stake_amounts(self):
        """测试入场金额计算"""
        calculator = WeightCalculator()
        amounts = calculator.calculate_stake_amounts(Decimal("10000"))

        self.assertEqual(len(amounts), 4)
        self.assertAlmostEqual(float(sum(amounts)), 10000.0, places=2)

        print("\n入场金额计算结果:")
        for i, a in enumerate(amounts):
            print(f"  A{i+1}: {float(a):.2f} USDT")


class TestChainState(unittest.TestCase):
    """链式状态测试"""

    def setUp(self):
        self.base_price = Decimal("100")
        self.levels = [
            ChainLevel(level=1, target_price=Decimal("99"), stake_amount=Decimal("3600")),
            ChainLevel(level=2, target_price=Decimal("98.01"), stake_amount=Decimal("3200")),
            ChainLevel(level=3, target_price=Decimal("97.03"), stake_amount=Decimal("2100")),
            ChainLevel(level=4, target_price=Decimal("96.06"), stake_amount=Decimal("900")),
        ]
        self.chain_state = ChainState(base_price=self.base_price, levels=self.levels)

    def test_get_next_pending_level(self):
        """测试获取下一个待处理层级"""
        level = self.chain_state.get_next_pending_level()
        self.assertIsNotNone(level)
        self.assertEqual(level.level, 1)

        self.levels[0].state = "filled"
        level = self.chain_state.get_next_pending_level()
        self.assertIsNotNone(level)
        self.assertEqual(level.level, 2)

    def test_get_filled_levels(self):
        """测试获取已成交层级"""
        filled = self.chain_state.get_filled_levels()
        self.assertEqual(len(filled), 0)

        self.levels[0].state = "filled"
        filled = self.chain_state.get_filled_levels()
        self.assertEqual(len(filled), 1)

        self.levels[1].state = "filled"
        filled = self.chain_state.get_filled_levels()
        self.assertEqual(len(filled), 2)

    def test_get_total_stake(self):
        """测试获取总入场金额"""
        total = self.chain_state.get_total_stake()
        self.assertEqual(total, Decimal("0"))

        self.levels[0].state = "filled"
        total = self.chain_state.get_total_stake()
        self.assertEqual(total, Decimal("3600"))

    def test_get_average_entry_price(self):
        """测试获取平均入场价格"""
        avg = self.chain_state.get_average_entry_price()
        self.assertIsNone(avg)

        self.levels[0].state = "filled"
        self.levels[0].filled_price = Decimal("99")
        avg = self.chain_state.get_average_entry_price()
        self.assertEqual(avg, Decimal("99"))

        self.levels[1].state = "filled"
        self.levels[1].filled_price = Decimal("98")
        avg = self.chain_state.get_average_entry_price()
        expected = (Decimal("3600") * Decimal("99") + Decimal("3200") * Decimal("98")) / (Decimal("3600") + Decimal("3200"))
        self.assertAlmostEqual(float(avg), float(expected), places=4)


class TestChainOrderLogic(unittest.TestCase):
    """链式挂单逻辑测试"""

    def test_entry_price_calculation(self):
        """测试入场价格计算"""
        base_price = Decimal("100")
        grid_spacing = Decimal("0.01")

        a1_price = base_price * (Decimal("1") - grid_spacing)
        self.assertEqual(a1_price, Decimal("99"))

        a2_price = a1_price * (Decimal("1") - grid_spacing)
        self.assertAlmostEqual(float(a2_price), 98.01, places=2)

        a3_price = a2_price * (Decimal("1") - grid_spacing)
        self.assertAlmostEqual(float(a3_price), 97.03, places=2)

        a4_price = a3_price * (Decimal("1") - grid_spacing)
        self.assertAlmostEqual(float(a4_price), 96.06, places=2)

    def test_exit_price_calculation(self):
        """测试出场价格计算"""
        entry_price = Decimal("99")
        exit_profit = Decimal("0.01")

        exit_price = entry_price * (Decimal("1") + exit_profit)
        self.assertEqual(exit_price, Decimal("99.99"))


class TestFullChainSimulation(unittest.TestCase):
    """完整链式挂单模拟测试"""

    def test_full_chain_flow(self):
        """测试完整链式流程"""
        print("\n" + "=" * 60)
        print("完整链式挂单模拟测试")
        print("=" * 60)

        calculator = WeightCalculator()
        base_price = Decimal("100")
        grid_spacing = Decimal("0.01")

        stake_amounts = calculator.calculate_stake_amounts(Decimal("10000"))

        levels = []
        current_price = base_price
        for i in range(4):
            target_price = current_price * (Decimal("1") - grid_spacing)
            levels.append(ChainLevel(
                level=i + 1,
                target_price=target_price,
                stake_amount=stake_amounts[i],
            ))
            current_price = target_price

        chain_state = ChainState(base_price=base_price, levels=levels)

        print(f"\n初始化链式状态:")
        print(f"  基准价格: {base_price}")
        for level in levels:
            print(f"  A{level.level}: 目标价={level.target_price:.2f}, 金额={level.stake_amount:.2f}")

        print(f"\n模拟价格下跌:")
        prices = [Decimal("99"), Decimal("98"), Decimal("97"), Decimal("96")]
        for i, price in enumerate(prices):
            next_level = chain_state.get_next_pending_level()
            if next_level and price <= next_level.target_price:
                next_level.state = "filled"
                next_level.filled_price = price
                print(f"  价格={price:.2f}, A{next_level.level}成交")

        filled = chain_state.get_filled_levels()
        print(f"\n成交结果:")
        print(f"  成交层级数: {len(filled)}")
        print(f"  总入场金额: {chain_state.get_total_stake():.2f}")

        avg_price = chain_state.get_average_entry_price()
        if avg_price:
            print(f"  平均入场价: {avg_price:.4f}")

            exit_price = avg_price * Decimal("1.01")
            print(f"  出场目标价: {exit_price:.4f}")

        self.assertEqual(len(filled), 4)


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestWeightCalculator))
    suite.addTests(loader.loadTestsFromTestCase(TestChainState))
    suite.addTests(loader.loadTestsFromTestCase(TestChainOrderLogic))
    suite.addTests(loader.loadTestsFromTestCase(TestFullChainSimulation))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == '__main__':
    run_tests()

#!/usr/bin/env python3
"""
测试资金递进管理功能

对比固定模式和递进模式的效果差异。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decimal import Decimal
from autofish_core import Autofish_CapitalPool

print("=" * 60)
print("资金递进管理功能测试")
print("=" * 60)

print("\n测试场景：")
print("初始资金: 10000 USDT")
print("策略: conservative (提现阈值 2.0x, 保留 1.5x)")
print("爆仓阈值: 0.1x (1000 USDT)")

pool = Autofish_CapitalPool(Decimal('10000'))
pool.set_strategy('conservative')

print("\n" + "=" * 60)
print("场景 1: 连续盈利 - 触发提现")
print("=" * 60)

profits = [1000, 2000, 3000, 4000]
for i, profit in enumerate(profits, 1):
    print(f"\n第 {i} 次交易，盈利 {profit} USDT")
    result = pool.update_capital(Decimal(str(profit)))
    print(f"  交易资金: {result['old_capital']:.0f} → {result['new_capital']:.0f}")
    
    withdrawal = pool.check_withdrawal()
    if withdrawal:
        print(f"  ✅ 触发提现!")
        print(f"  提现金额: {withdrawal['withdrawal_amount']:.0f}")
        print(f"  利润池: {withdrawal['profit_pool']:.0f}")
        print(f"  交易资金: {withdrawal['trading_capital']:.0f}")

stats = pool.get_statistics()
print(f"\n当前统计:")
print(f"  交易资金: {stats['trading_capital']:.0f}")
print(f"  利润池: {stats['profit_pool']:.0f}")
print(f"  提现次数: {stats['withdrawal_count']}")

print("\n" + "=" * 60)
print("场景 2: 连续亏损 - 触发爆仓")
print("=" * 60)

losses = [-3000, -4000, -3000]
for i, loss in enumerate(losses, 1):
    print(f"\n第 {i} 次交易，亏损 {loss} USDT")
    result = pool.update_capital(Decimal(str(loss)))
    print(f"  交易资金: {result['old_capital']:.0f} → {result['new_capital']:.0f}")
    
    if pool.check_liquidation():
        print(f"  ⚠️ 触发爆仓!")
        if pool.recover_from_liquidation():
            print(f"  ✅ 从利润池恢复成功!")
            print(f"  交易资金: {pool.trading_capital:.0f}")
            print(f"  利润池: {pool.profit_pool:.0f}")
        else:
            print(f"  ❌ 利润池不足，无法恢复!")
            break

stats = pool.get_statistics()
print(f"\n最终统计:")
print(f"  初始资金: {stats['initial_capital']:.0f}")
print(f"  最终资金: {stats['final_capital']:.0f}")
print(f"  总收益率: {stats['total_return']:.2f}%")
print(f"  总盈利: {stats['total_profit']:.0f}")
print(f"  总亏损: {stats['total_loss']:.0f}")
print(f"  提现次数: {stats['withdrawal_count']}")
print(f"  爆仓次数: {stats['liquidation_count']}")
print(f"  胜率: {stats['win_rate']:.2f}%")

print("\n" + "=" * 60)
print("测试完成!")
print("=" * 60)

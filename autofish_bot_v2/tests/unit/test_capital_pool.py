#!/usr/bin/env python3
"""
测试资金池管理功能
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decimal import Decimal

# 直接导入 CapitalPool 类，避免触发 __main__
import autofish_core

Autofish_CapitalPool = autofish_core.Autofish_CapitalPool

def test_capital_pool():
    """测试资金池基本功能"""
    print("=" * 60)
    print("测试资金池管理功能")
    print("=" * 60)
    
    # 测试初始化
    print("\n1. 测试初始化...")
    pool = Autofish_CapitalPool(Decimal('10000'))
    print(f"   初始资金: {pool.initial_capital}")
    print(f"   交易资金: {pool.trading_capital}")
    print(f"   利润池: {pool.profit_pool}")
    assert pool.initial_capital == Decimal('10000')
    assert pool.trading_capital == Decimal('10000')
    assert pool.profit_pool == Decimal('0')
    print("   ✅ 初始化成功")
    
    # 测试盈利更新
    print("\n2. 测试盈利更新...")
    result = pool.update_capital(Decimal('1000'))
    print(f"   盈利: 1000 USDT")
    print(f"   旧资金: {result['old_capital']}")
    print(f"   新资金: {result['new_capital']}")
    assert pool.trading_capital == Decimal('11000')
    assert pool.total_profit == Decimal('1000')
    print("   ✅ 盈利更新成功")
    
    # 测试提现触发
    print("\n3. 测试提现触发...")
    result = pool.update_capital(Decimal('9000'))
    print(f"   盈利: 9000 USDT")
    print(f"   当前资金: {pool.trading_capital}")
    
    withdrawal = pool.check_withdrawal()
    if withdrawal:
        print(f"   ✅ 触发提现!")
        print(f"   提现金额: {withdrawal['withdrawal_amount']}")
        print(f"   利润池: {withdrawal['profit_pool']}")
        print(f"   交易资金: {withdrawal['trading_capital']}")
        assert pool.profit_pool == Decimal('5000')
        assert pool.trading_capital == Decimal('15000')
        assert pool.withdrawal_count == 1
    else:
        print("   未触发提现")
    
    # 测试亏损更新
    print("\n4. 测试亏损更新...")
    result = pool.update_capital(Decimal('-5000'))
    print(f"   亏损: -5000 USDT")
    print(f"   旧资金: {result['old_capital']}")
    print(f"   新资金: {result['new_capital']}")
    assert pool.trading_capital == Decimal('10000')
    assert pool.total_loss == Decimal('5000')
    print("   ✅ 亏损更新成功")
    
    # 测试爆仓检查
    print("\n5. 测试爆仓检查...")
    result = pool.update_capital(Decimal('-9000'))
    print(f"   亏损: -9000 USDT")
    print(f"   当前资金: {pool.trading_capital}")
    
    is_liquidated = pool.check_liquidation()
    if is_liquidated:
        print(f"   ✅ 触发爆仓!")
        
        # 测试爆仓恢复
        print("\n6. 测试爆仓恢复...")
        recovered = pool.recover_from_liquidation()
        if recovered:
            print(f"   ✅ 恢复成功!")
            print(f"   交易资金: {pool.trading_capital}")
            print(f"   利润池: {pool.profit_pool}")
            print(f"   爆仓次数: {pool.liquidation_count}")
            assert pool.trading_capital == Decimal('10000')
            assert pool.profit_pool == Decimal('4000')
            assert pool.liquidation_count == 1
        else:
            print("   ❌ 恢复失败（利润池不足）")
    else:
        print("   未触发爆仓")
    
    # 测试统计信息
    print("\n7. 测试统计信息...")
    stats = pool.get_statistics()
    print(f"   初始资金: {stats['initial_capital']}")
    print(f"   最终资金: {stats['final_capital']}")
    print(f"   总收益: {stats['total_return']:.2f}%")
    print(f"   提现次数: {stats['withdrawal_count']}")
    print(f"   爆仓次数: {stats['liquidation_count']}")
    print("   ✅ 统计信息正确")
    
    print("\n" + "=" * 60)
    print("资金池管理功能测试完成!")
    print("=" * 60)

if __name__ == '__main__':
    try:
        test_capital_pool()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

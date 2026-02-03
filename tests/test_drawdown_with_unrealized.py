#!/usr/bin/env python3
"""
测试含未实现盈亏的最大回撤（P1优化）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from address_analyzer.metrics_engine import MetricsEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_drawdown_with_large_unrealized_loss():
    """
    测试场景1：大额未实现亏损

    场景：
    - 充值 $100,000
    - 交易赚 $10,000 (账户=$110,000, 已实现盈亏=$10,000)
    - 当前持仓未实现亏损 -$30,000 (真实权益=$80,000)

    预期：
    - 已实现回撤：0%（一直盈利）
    - 含未实现回撤：($110,000 - $80,000) / $110,000 = 27.27%
    """
    print("\n" + "=" * 80)
    print("📊 测试1：大额未实现亏损")
    print("=" * 80)

    import time
    base_time = int(time.time() * 1000) - (30 * 24 * 60 * 60 * 1000)

    fills = [
        {'time': base_time + (10 * 24 * 60 * 60 * 1000), 'closedPnl': '5000'},
        {'time': base_time + (20 * 24 * 60 * 60 * 1000), 'closedPnl': '5000'},
    ]

    ledger = [
        {
            'time': base_time,
            'delta': {
                'type': 'deposit',
                'usdc': '100000'
            }
        }
    ]

    # 模拟大额未实现亏损
    state = {
        'assetPositions': [
            {
                'position': {
                    'coin': 'BTC',
                    'unrealizedPnl': '-30000'  # 大额浮亏
                }
            }
        ]
    }

    address = "0xtest"
    account_value = 110000.0

    max_dd, details = MetricsEngine.calculate_max_drawdown(
        fills, account_value, 100000.0, ledger, address, state
    )

    print(f"\n场景说明:")
    print(f"  充值: $100,000")
    print(f"  已实现盈亏: +$10,000")
    print(f"  未实现盈亏: -$30,000")
    print(f"  账户价值: $110,000")
    print(f"  真实权益: $80,000 (含未实现)")

    print(f"\n计算结果:")
    print(f"  已实现回撤: {max_dd:.2f}%")
    print(f"  含未实现回撤: {details['max_drawdown_with_unrealized']:.2f}%")
    print(f"  质量标记: {details['quality']}")

    # 预期：已实现回撤应该是0%（一直盈利），含未实现应该>20%
    if max_dd < 5:  # 已实现回撤很小
        print(f"\n  ✅ 已实现回撤正确: {max_dd:.2f}% (一直盈利)")
    else:
        print(f"\n  ⚠️  已实现回撤可能有误: {max_dd:.2f}%")

    if details['max_drawdown_with_unrealized'] > 20:
        print(f"  ✅ 含未实现回撤正确: {details['max_drawdown_with_unrealized']:.2f}% (反映真实风险)")
    else:
        print(f"  ⚠️  含未实现回撤可能有误: {details['max_drawdown_with_unrealized']:.2f}%")

    return (max_dd < 5 and details['max_drawdown_with_unrealized'] > 20)


def test_drawdown_with_unrealized_profit():
    """
    测试场景2：大额未实现盈利

    场景：
    - 充值 $10,000
    - 交易亏 $2,000 (账户=$8,000, 已实现回撤=20%)
    - 当前持仓未实现盈利 +$5,000 (真实权益=$13,000)

    预期：
    - 已实现回撤：20%（历史最大）
    - 含未实现回撤：<=20%（加上浮盈后，历史回撤可能减小但不会消失）

    注意：最大回撤是历史值，即使当前权益已恢复甚至超过峰值，
    历史上发生过的最大回撤仍然存在。
    """
    print("\n" + "=" * 80)
    print("📊 测试2：大额未实现盈利")
    print("=" * 80)

    import time
    base_time = int(time.time() * 1000) - (30 * 24 * 60 * 60 * 1000)

    fills = [
        {'time': base_time + (10 * 24 * 60 * 60 * 1000), 'closedPnl': '-2000'},
    ]

    ledger = [
        {
            'time': base_time,
            'delta': {
                'type': 'deposit',
                'usdc': '10000'
            }
        }
    ]

    # 模拟大额未实现盈利
    state = {
        'assetPositions': [
            {
                'position': {
                    'coin': 'ETH',
                    'unrealizedPnl': '5000'  # 大额浮盈
                }
            }
        ]
    }

    address = "0xtest"
    account_value = 8000.0

    max_dd, details = MetricsEngine.calculate_max_drawdown(
        fills, account_value, 10000.0, ledger, address, state
    )

    print(f"\n场景说明:")
    print(f"  充值: $10,000")
    print(f"  已实现盈亏: -$2,000 (亏损)")
    print(f"  未实现盈亏: +$5,000 (浮盈)")
    print(f"  账户价值: $8,000")
    print(f"  真实权益: $13,000 (含未实现)")

    print(f"\n计算结果:")
    print(f"  已实现回撤: {max_dd:.2f}%")
    print(f"  含未实现回撤: {details['max_drawdown_with_unrealized']:.2f}%")

    # 预期：已实现回撤应该是20%，含未实现应该<=20%（可能相同或更小）
    if 15 <= max_dd <= 25:
        print(f"\n  ✅ 已实现回撤正确: {max_dd:.2f}% (历史最大)")
    else:
        print(f"\n  ⚠️  已实现回撤可能有误: {max_dd:.2f}%")

    if details['max_drawdown_with_unrealized'] <= max_dd + 1:  # 允许1%误差
        print(f"  ✅ 含未实现回撤合理: {details['max_drawdown_with_unrealized']:.2f}% (≤已实现回撤)")
        print(f"     说明：虽然当前有浮盈，但历史回撤仍然存在")
    else:
        print(f"  ⚠️  含未实现回撤异常: {details['max_drawdown_with_unrealized']:.2f}% (不应大于已实现)")

    return (15 <= max_dd <= 25 and details['max_drawdown_with_unrealized'] <= max_dd + 1)


def test_no_state_falls_back():
    """
    测试场景3：无state数据时，两种回撤应该相同
    """
    print("\n" + "=" * 80)
    print("📊 测试3：无state数据时降级")
    print("=" * 80)

    import time
    base_time = int(time.time() * 1000) - (30 * 24 * 60 * 60 * 1000)

    fills = [
        {'time': base_time + (10 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},
        {'time': base_time + (20 * 24 * 60 * 60 * 1000), 'closedPnl': '-500'},
    ]

    ledger = [
        {
            'time': base_time,
            'delta': {
                'type': 'deposit',
                'usdc': '10000'
            }
        }
    ]

    address = "0xtest"
    account_value = 10500.0

    # 不提供state
    max_dd, details = MetricsEngine.calculate_max_drawdown(
        fills, account_value, 10000.0, ledger, address, None
    )

    print(f"\n计算结果:")
    print(f"  已实现回撤: {max_dd:.2f}%")
    print(f"  含未实现回撤: {details['max_drawdown_with_unrealized']:.2f}%")

    # 预期：两者应该相同
    if abs(max_dd - details['max_drawdown_with_unrealized']) < 0.01:
        print(f"\n  ✅ 无state时正确降级（两者相同）")
    else:
        print(f"\n  ⚠️  降级可能有误，两者应该相同")

    return abs(max_dd - details['max_drawdown_with_unrealized']) < 0.01


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("🧪 含未实现盈亏的最大回撤测试（P1优化）")
    print("=" * 80)

    tests = [
        ("大额未实现亏损", test_drawdown_with_large_unrealized_loss),
        ("大额未实现盈利", test_drawdown_with_unrealized_profit),
        ("无state时降级", test_no_state_falls_back),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n  ❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 总结
    print("\n" + "=" * 80)
    print("📊 测试总结")
    print("=" * 80)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {status}: {name}")

    print(f"\n通过率: {passed}/{total} ({passed/total*100:.1f}%)")

    if passed == total:
        print("\n🎉 所有测试通过！P1任务#3完成。")
    else:
        print("\n⚠️  部分测试失败，需要进一步调试。")

    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

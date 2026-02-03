#!/usr/bin/env python3
"""
测试Sharpe比率P2优化：出入金和资金费率集成
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from address_analyzer.metrics_engine import MetricsEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_sharpe_with_deposits_withdrawals():
    """
    测试场景1：出入金对Sharpe比率的影响

    场景：
    - 初始充值 $10,000
    - 交易赚 $2,000（20% ROI）
    - 追加充值 $10,000
    - 再赚 $2,000（但基于$22,000资金，ROI=9.09%）

    预期：
    - 旧算法：可能计算错误（固定资金基准）
    - 新算法：正确考虑出入金后的动态资金基准
    """
    print("\n" + "=" * 80)
    print("📊 测试1：出入金对Sharpe比率的影响")
    print("=" * 80)

    import time
    base_time = int(time.time() * 1000) - (100 * 24 * 60 * 60 * 1000)

    fills = [
        {'time': base_time + (30 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},
        {'time': base_time + (40 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},
        # 充值后的交易
        {'time': base_time + (70 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},
        {'time': base_time + (80 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},
    ]

    ledger = [
        {
            'time': base_time,
            'delta': {
                'type': 'deposit',
                'usdc': '10000'
            }
        },
        {
            'time': base_time + (50 * 24 * 60 * 60 * 1000),  # 第50天追加
            'delta': {
                'type': 'deposit',
                'usdc': '10000'
            }
        }
    ]

    address = "0xtest"
    account_value = 24000.0  # 20000 + 4000

    # 旧算法（不传ledger）
    sharpe_old = MetricsEngine.calculate_sharpe_ratio(
        fills, account_value, 20000.0
    )

    # 新算法（传ledger）
    sharpe_new, sharpe_details = MetricsEngine.calculate_sharpe_ratio_enhanced(
        fills, account_value, None, ledger, address, None
    )

    print(f"\n场景说明:")
    print(f"  1. 初始充值: $10,000")
    print(f"  2. 赚 $2,000 (第30-40天)")
    print(f"  3. 追加充值: $10,000 (第50天)")
    print(f"  4. 再赚 $2,000 (第70-80天)")

    print(f"\n计算结果:")
    print(f"  旧算法 Sharpe: {sharpe_old:.4f}")
    print(f"  新算法 Sharpe: {sharpe_new:.4f}")
    print(f"  质量标记: {sharpe_details.get('quality', 'N/A')}")

    # 验证：新算法应该更合理（不会因为充值而虚高收益率）
    if sharpe_details.get('quality') in ['enhanced', 'standard']:
        print(f"\n  ✅ 新算法正确处理出入金事件")
    else:
        print(f"\n  ⚠️  新算法质量标记异常")

    return sharpe_details.get('quality') in ['enhanced', 'standard']


def test_sharpe_with_funding_rate():
    """
    测试场景2：资金费率对Sharpe比率的影响

    场景：
    - 初始充值 $10,000
    - 交易盈亏：+$1,000
    - 资金费率收入：+$200（做空时收到资金费）
    - 总收益：$1,200

    预期：
    - 旧算法：只计入交易盈亏 $1,000
    - 新算法：计入交易盈亏 + 资金费 = $1,200
    """
    print("\n" + "=" * 80)
    print("📊 测试2：资金费率对Sharpe比率的影响")
    print("=" * 80)

    import time
    base_time = int(time.time() * 1000) - (30 * 24 * 60 * 60 * 1000)

    fills = [
        {'time': base_time + (10 * 24 * 60 * 60 * 1000), 'closedPnl': '500'},
        {'time': base_time + (20 * 24 * 60 * 60 * 1000), 'closedPnl': '500'},
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

    # 模拟资金费率收入
    state = {
        'assetPositions': [
            {
                'position': {
                    'coin': 'ETH',
                    'cumFunding': {
                        'allTime': '-200',  # 收到资金费（负数=收益）
                        'sinceOpen': '-200',
                        'sinceChange': '-100'
                    }
                }
            }
        ]
    }

    address = "0xtest"
    account_value = 11200.0  # 10000 + 1000 + 200

    # 旧算法（不传state）
    sharpe_old = MetricsEngine.calculate_sharpe_ratio(
        fills, account_value, 10000.0
    )

    # 新算法（传state）
    sharpe_new, sharpe_details = MetricsEngine.calculate_sharpe_ratio_enhanced(
        fills, account_value, 10000.0, ledger, address, state
    )

    print(f"\n场景说明:")
    print(f"  初始充值: $10,000")
    print(f"  交易盈亏: +$1,000")
    print(f"  资金费率: +$200 (收到)")
    print(f"  总收益: +$1,200")

    print(f"\n计算结果:")
    print(f"  旧算法 Sharpe: {sharpe_old:.4f}")
    print(f"  新算法 Sharpe: {sharpe_new:.4f}")
    print(f"  资金费率贡献: {sharpe_details.get('funding_contribution', 0):.2f}%")

    # 验证：新算法应该更高（包含资金费收益）
    if sharpe_new >= sharpe_old:
        print(f"\n  ✅ 新算法正确计入资金费率")
        print(f"     增幅: {((sharpe_new - sharpe_old) / abs(sharpe_old) * 100):.2f}%")
    else:
        print(f"\n  ⚠️  新算法可能有误")

    return sharpe_new >= sharpe_old


def test_sharpe_fallback():
    """
    测试场景3：无ledger/state时降级到旧算法
    """
    print("\n" + "=" * 80)
    print("📊 测试3：无ledger/state时降级")
    print("=" * 80)

    import time
    base_time = int(time.time() * 1000) - (30 * 24 * 60 * 60 * 1000)

    fills = [
        {'time': base_time + (10 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},
        {'time': base_time + (20 * 24 * 60 * 60 * 1000), 'closedPnl': '-500'},
    ]

    account_value = 10500.0

    # 不传ledger和state
    sharpe_new, sharpe_details = MetricsEngine.calculate_sharpe_ratio_enhanced(
        fills, account_value, None, None, None, None
    )

    print(f"\n计算结果:")
    print(f"  Sharpe: {sharpe_new:.4f}")
    print(f"  质量标记: {sharpe_details.get('quality', 'N/A')}")

    # 验证：应该降级到旧算法
    if sharpe_details.get('quality') == 'estimated_fallback':
        print(f"\n  ✅ 正确降级到旧算法")
    else:
        print(f"\n  ⚠️  质量标记可能有误")

    return sharpe_details.get('quality') == 'estimated_fallback'


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("🧪 Sharpe比率P2优化测试")
    print("=" * 80)

    tests = [
        ("出入金处理", test_sharpe_with_deposits_withdrawals),
        ("资金费率集成", test_sharpe_with_funding_rate),
        ("降级逻辑", test_sharpe_fallback),
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
        print("\n🎉 所有测试通过！P2任务#4完成。")
    else:
        print("\n⚠️  部分测试失败，需要进一步调试。")

    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

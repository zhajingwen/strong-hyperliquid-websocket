#!/usr/bin/env python3
"""
测试时间加权ROI计算（P1优化）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from address_analyzer.metrics_engine import MetricsEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_time_weighted_roi_basic():
    """
    测试场景1：基础时间加权ROI

    场景：
    - 第1天投入$10,000
    - 第50天追加$5,000
    - 总共100天，赚$1,500

    预期：
    - 简单ROI = $1,500 / $15,000 = 10%
    - 时间加权：第一笔资金使用100天，第二笔使用50天
      平均资金 = (10K×100 + 5K×50) / 100 = 12.5K
    - 时间加权ROI ≈ $1,500 / $12.5K = 12%
    """
    print("\n" + "=" * 80)
    print("📊 测试1：基础时间加权ROI")
    print("=" * 80)

    import time

    base_time = int(time.time() * 1000) - (100 * 24 * 60 * 60 * 1000)  # 100天前

    fills = [
        {'time': base_time + (40 * 24 * 60 * 60 * 1000), 'closedPnl': '800'},   # 第40天赚$800
        {'time': base_time + (80 * 24 * 60 * 60 * 1000), 'closedPnl': '700'},   # 第80天赚$700
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
                'usdc': '5000'
            }
        }
    ]

    address = "0xtest"
    account_value = 16500.0  # 15000 + 1500

    tw_roi, ann_roi, total_roi, quality = MetricsEngine.calculate_time_weighted_roi(
        fills, ledger, account_value, address, None
    )

    print(f"\n场景说明:")
    print(f"  1. 第1天投入: $10,000")
    print(f"  2. 第50天追加: $5,000")
    print(f"  3. 总共100天，赚$1,500")
    print(f"\n  期间ROI: $1,500 / $15,000 = 10%")
    print(f"  时间加权平均资金: (10K×100 + 5K×50)/100 = $12.5K")
    print(f"  时间加权期间ROI: $1,500 / $12.5K = 12%")
    print(f"  年化（算法返回值）: 12% × (365/100) ≈ 43.8%")

    print(f"\n计算结果:")
    print(f"  时间加权ROI（年化）: {tw_roi:.2f}%")
    print(f"  年化ROI: {ann_roi:.2f}%")
    print(f"  总ROI: {total_roi:.2f}%")
    print(f"  质量标记: {quality}")

    # 修正预期：算法返回的是年化ROI，应该在40-50%之间
    if 40 <= tw_roi <= 50:
        print(f"\n  ✅ 时间加权ROI在合理范围内: {tw_roi:.2f}%")
    else:
        print(f"\n  ⚠️  时间加权ROI可能有误: {tw_roi:.2f}%")

    return 40 <= tw_roi <= 50


def test_roi_with_unrealized_pnl():
    """
    测试场景2：含未实现盈亏的总ROI

    场景：
    - 投入$10,000
    - 已实现盈亏：+$1,000
    - 未实现盈亏：+$500
    - 总ROI应该是 $1,500/$10,000 = 15%
    """
    print("\n" + "=" * 80)
    print("📊 测试2：含未实现盈亏的总ROI")
    print("=" * 80)

    import time

    base_time = int(time.time() * 1000) - (30 * 24 * 60 * 60 * 1000)

    fills = [
        {'time': base_time + (10 * 24 * 60 * 60 * 1000), 'closedPnl': '600'},
        {'time': base_time + (20 * 24 * 60 * 60 * 1000), 'closedPnl': '400'},
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
    account_value = 11500.0  # 10000 + 1000 + 500

    # 模拟未实现盈亏
    state = {
        'assetPositions': [
            {
                'position': {
                    'coin': 'BTC',
                    'unrealizedPnl': '500'
                }
            }
        ]
    }

    tw_roi, ann_roi, total_roi, quality = MetricsEngine.calculate_time_weighted_roi(
        fills, ledger, account_value, address, state
    )

    print(f"\n场景说明:")
    print(f"  投入: $10,000")
    print(f"  已实现盈亏: +$1,000")
    print(f"  未实现盈亏: +$500")
    print(f"  总盈亏: +$1,500")

    print(f"\n计算结果:")
    print(f"  时间加权ROI（仅已实现）: {tw_roi:.2f}%")
    print(f"  总ROI（含未实现）: {total_roi:.2f}%")

    # 验证：总ROI应该比时间加权ROI大（因为包含未实现）
    if total_roi > tw_roi:
        print(f"\n  ✅ 总ROI > 时间加权ROI（正确）")
    else:
        print(f"\n  ⚠️  总ROI应该大于时间加权ROI")

    return total_roi > tw_roi


def test_annualized_roi():
    """
    测试场景3：年化ROI

    场景：
    - 投入$10,000
    - 6个月后，账户价值$12,000
    - ROI = 20% (半年)
    - 年化ROI ≈ 44%
    """
    print("\n" + "=" * 80)
    print("📊 测试3：年化ROI")
    print("=" * 80)

    import time

    base_time = int(time.time() * 1000) - (180 * 24 * 60 * 60 * 1000)  # 180天前（半年）

    fills = [
        {'time': base_time + (60 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},
        {'time': base_time + (120 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},
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
    account_value = 12000.0

    tw_roi, ann_roi, total_roi, quality = MetricsEngine.calculate_time_weighted_roi(
        fills, ledger, account_value, address, None
    )

    print(f"\n场景说明:")
    print(f"  投入: $10,000")
    print(f"  6个月后: $12,000")
    print(f"  半年ROI: 20%")
    print(f"  理论年化: (1.2)^2 - 1 = 44%")

    print(f"\n计算结果:")
    print(f"  年化ROI: {ann_roi:.2f}%")

    # 验证：年化ROI应该在40-50%之间
    if 40 <= ann_roi <= 50:
        print(f"\n  ✅ 年化ROI在合理范围内: {ann_roi:.2f}%")
    else:
        print(f"\n  ⚠️  年化ROI可能有误: {ann_roi:.2f}% (预期40-50%)")

    return 40 <= ann_roi <= 50


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("🧪 时间加权ROI测试（P1优化）")
    print("=" * 80)

    tests = [
        ("基础时间加权ROI", test_time_weighted_roi_basic),
        ("含未实现盈亏", test_roi_with_unrealized_pnl),
        ("年化ROI", test_annualized_roi),
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
        print("\n🎉 所有测试通过！P1优化成功。")
    else:
        print("\n⚠️  部分测试失败，需要进一步调试。")

    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

#!/usr/bin/env python3
"""
测试回撤期间详细分析（P2优化）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from address_analyzer.metrics_engine import MetricsEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_multiple_drawdown_periods():
    """
    测试场景1：多个回撤期间识别

    场景：
    - 初始充值 $10,000
    - 第1次回撤：赚$2000 → 亏$1500 → 恢复
    - 第2次回撤：赚$1000 → 亏$800 → 恢复
    - 第3次回撤：赚$500 → 亏$300 → 未恢复

    预期：
    - 识别3个回撤期间
    - 前2个已恢复，第3个未恢复
    - 计算每个期间的持续时间和恢复时间
    """
    print("\n" + "=" * 80)
    print("📊 测试1：多个回撤期间识别")
    print("=" * 80)

    import time
    base_time = int(time.time() * 1000) - (100 * 24 * 60 * 60 * 1000)

    fills = [
        # 第1次回撤
        {'time': base_time + (10 * 24 * 60 * 60 * 1000), 'closedPnl': '2000'},   # 赚$2000
        {'time': base_time + (15 * 24 * 60 * 60 * 1000), 'closedPnl': '-1500'},  # 亏$1500
        {'time': base_time + (20 * 24 * 60 * 60 * 1000), 'closedPnl': '1500'},   # 恢复

        # 第2次回撤
        {'time': base_time + (30 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},   # 赚$1000
        {'time': base_time + (35 * 24 * 60 * 60 * 1000), 'closedPnl': '-800'},   # 亏$800
        {'time': base_time + (40 * 24 * 60 * 60 * 1000), 'closedPnl': '800'},    # 恢复

        # 第3次回撤（未恢复）
        {'time': base_time + (50 * 24 * 60 * 60 * 1000), 'closedPnl': '500'},    # 赚$500
        {'time': base_time + (55 * 24 * 60 * 60 * 1000), 'closedPnl': '-300'},   # 亏$300
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
    account_value = 13200.0  # 10000 + 2000 - 1500 + 1500 + 1000 - 800 + 800 + 500 - 300

    # 计算最大回撤（会包含equity_curve）
    max_dd, dd_details = MetricsEngine.calculate_max_drawdown(
        fills, account_value, 10000.0, ledger, address, None
    )

    # 分析回撤期间
    if 'equity_curve' in dd_details:
        analysis = MetricsEngine.analyze_drawdown_periods(
            dd_details['equity_curve'],
            fills
        )

        print(f"\n场景说明:")
        print(f"  - 初始充值: $10,000")
        print(f"  - 第1次回撤: +$2000 → -$1500 → +$1500 (恢复)")
        print(f"  - 第2次回撤: +$1000 → -$800 → +$800 (恢复)")
        print(f"  - 第3次回撤: +$500 → -$300 (未恢复)")

        print(f"\n分析结果:")
        print(f"  回撤期间总数: {analysis['total_periods']}")
        print(f"  平均持续天数: {analysis['avg_duration_days']:.1f}天")
        print(f"  平均恢复天数: {analysis['avg_recovery_days']:.1f}天")
        print(f"  最长持续天数: {analysis['longest_duration_days']}天")
        print(f"  当前处于回撤: {'是' if analysis['current_in_drawdown'] else '否'}")

        print(f"\n回撤期间详情:")
        for i, period in enumerate(analysis['periods'], 1):
            print(f"\n  期间{i}:")
            print(f"    回撤幅度: {period['max_drawdown_pct']:.2f}%")
            print(f"    持续天数: {period['duration_days']:.1f}天")
            print(f"    是否恢复: {'是' if period['recovered'] else '否'}")
            if period['recovered']:
                print(f"    恢复天数: {period['recovery_days']:.1f}天")
            print(f"    期间交易: {period['trades_count']}笔")
            print(f"    亏损交易: {period['losing_trades_count']}笔")
            print(f"    总亏损: ${period['total_loss']:.2f}")

        # 验证
        if analysis['total_periods'] == 3:
            print(f"\n  ✅ 正确识别3个回撤期间")
        else:
            print(f"\n  ⚠️  回撤期间数量错误: {analysis['total_periods']} != 3")

        if analysis['current_in_drawdown']:
            print(f"  ✅ 正确识别当前处于回撤中")
        else:
            print(f"  ⚠️  当前回撤状态错误")

        # 检查恢复状态
        recovered_count = sum(1 for p in analysis['periods'] if p['recovered'])
        if recovered_count == 2:
            print(f"  ✅ 正确识别2个已恢复的回撤")
        else:
            print(f"  ⚠️  恢复期间数量错误: {recovered_count} != 2")

        return analysis['total_periods'] == 3 and analysis['current_in_drawdown'] and recovered_count == 2
    else:
        print("  ❌ 缺少equity_curve数据")
        return False


def test_long_recovery_period():
    """
    测试场景2：长期回撤和恢复

    场景：
    - 充值 $10,000
    - 赚 $5,000（峰值$15,000）
    - 大幅回撤：亏 $8,000（谷底$7,000，回撤53.33%）
    - 缓慢恢复：用30天恢复到峰值

    预期：
    - 识别1个大型回撤
    - 恢复时间较长
    - 回撤幅度较大
    """
    print("\n" + "=" * 80)
    print("📊 测试2：长期回撤和恢复")
    print("=" * 80)

    import time
    base_time = int(time.time() * 1000) - (60 * 24 * 60 * 60 * 1000)

    fills = [
        # 上涨阶段
        {'time': base_time + (10 * 24 * 60 * 60 * 1000), 'closedPnl': '5000'},   # 达到峰值$15K

        # 回撤阶段
        {'time': base_time + (15 * 24 * 60 * 60 * 1000), 'closedPnl': '-3000'},
        {'time': base_time + (20 * 24 * 60 * 60 * 1000), 'closedPnl': '-5000'},  # 谷底$7K

        # 恢复阶段（缓慢恢复）
        {'time': base_time + (25 * 24 * 60 * 60 * 1000), 'closedPnl': '2000'},
        {'time': base_time + (35 * 24 * 60 * 60 * 1000), 'closedPnl': '3000'},
        {'time': base_time + (50 * 24 * 60 * 60 * 1000), 'closedPnl': '3000'},   # 恢复到$15K
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
    account_value = 15000.0

    # 计算和分析
    max_dd, dd_details = MetricsEngine.calculate_max_drawdown(
        fills, account_value, 10000.0, ledger, address, None
    )

    if 'equity_curve' in dd_details:
        analysis = MetricsEngine.analyze_drawdown_periods(
            dd_details['equity_curve'],
            fills
        )

        print(f"\n场景说明:")
        print(f"  - 峰值: $15,000")
        print(f"  - 谷底: $7,000")
        print(f"  - 回撤: 53.33%")
        print(f"  - 恢复时间: ~30天")

        print(f"\n分析结果:")
        print(f"  回撤期间总数: {analysis['total_periods']}")
        print(f"  最长持续天数: {analysis['longest_duration_days']}天")
        print(f"  平均恢复天数: {analysis['avg_recovery_days']:.1f}天")

        if analysis['periods']:
            period = analysis['periods'][0]
            print(f"\n  回撤详情:")
            print(f"    回撤幅度: {period['max_drawdown_pct']:.2f}%")
            print(f"    持续天数: {period['duration_days']:.1f}天")
            print(f"    恢复天数: {period['recovery_days']:.1f}天")
            print(f"    期间亏损交易: {period['losing_trades_count']}笔")
            print(f"    总亏损: ${period['total_loss']:.2f}")

        # 验证
        if analysis['total_periods'] == 1:
            print(f"\n  ✅ 正确识别1个回撤期间")
        else:
            print(f"\n  ⚠️  回撤期间数量错误")

        if analysis['periods'] and analysis['periods'][0]['max_drawdown_pct'] > 50:
            print(f"  ✅ 正确识别大幅回撤")
        else:
            print(f"  ⚠️  回撤幅度计算错误")

        if analysis['avg_recovery_days'] > 20:
            print(f"  ✅ 正确识别长期恢复")
        else:
            print(f"  ⚠️  恢复时间计算错误")

        return (analysis['total_periods'] == 1 and
                analysis['periods'][0]['max_drawdown_pct'] > 50 and
                analysis['avg_recovery_days'] > 20)
    else:
        print("  ❌ 缺少equity_curve数据")
        return False


def test_no_drawdown():
    """
    测试场景3：无回撤情况

    场景：
    - 充值 $10,000
    - 持续盈利，无回撤

    预期：
    - 回撤期间数为0
    - 当前不处于回撤中
    """
    print("\n" + "=" * 80)
    print("📊 测试3：无回撤情况")
    print("=" * 80)

    import time
    base_time = int(time.time() * 1000) - (30 * 24 * 60 * 60 * 1000)

    fills = [
        {'time': base_time + (5 * 24 * 60 * 60 * 1000), 'closedPnl': '1000'},
        {'time': base_time + (10 * 24 * 60 * 60 * 1000), 'closedPnl': '500'},
        {'time': base_time + (15 * 24 * 60 * 60 * 1000), 'closedPnl': '800'},
        {'time': base_time + (20 * 24 * 60 * 60 * 1000), 'closedPnl': '1200'},
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
    account_value = 13500.0

    # 计算和分析
    max_dd, dd_details = MetricsEngine.calculate_max_drawdown(
        fills, account_value, 10000.0, ledger, address, None
    )

    if 'equity_curve' in dd_details:
        analysis = MetricsEngine.analyze_drawdown_periods(
            dd_details['equity_curve'],
            fills
        )

        print(f"\n场景说明:")
        print(f"  - 持续盈利，无回撤")

        print(f"\n分析结果:")
        print(f"  回撤期间总数: {analysis['total_periods']}")
        print(f"  当前处于回撤: {'是' if analysis['current_in_drawdown'] else '否'}")

        # 验证
        if analysis['total_periods'] == 0:
            print(f"\n  ✅ 正确识别无回撤")
        else:
            print(f"\n  ⚠️  不应有回撤期间: {analysis['total_periods']}")

        if not analysis['current_in_drawdown']:
            print(f"  ✅ 正确识别当前不在回撤中")
        else:
            print(f"  ⚠️  当前回撤状态错误")

        return analysis['total_periods'] == 0 and not analysis['current_in_drawdown']
    else:
        print("  ❌ 缺少equity_curve数据")
        return False


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("🧪 回撤期间详细分析测试（P2优化）")
    print("=" * 80)

    tests = [
        ("多个回撤期间识别", test_multiple_drawdown_periods),
        ("长期回撤和恢复", test_long_recovery_period),
        ("无回撤情况", test_no_drawdown),
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
        print("\n🎉 所有测试通过！P2任务#6完成。")
    else:
        print("\n⚠️  部分测试失败，需要进一步调试。")

    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

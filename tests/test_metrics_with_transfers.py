"""
单元测试 - 出入金整合后的指标计算
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from address_analyzer.metrics_engine import MetricsEngine


def test_actual_initial_capital():
    """测试真实初始资金计算"""
    print("\n测试1: 真实初始资金计算")
    print("=" * 60)

    # 正常情况：有净充值
    result = MetricsEngine.calculate_actual_initial_capital(
        account_value=10500,
        realized_pnl=500,
        net_deposits=5000
    )
    expected = 5000  # 10500 - 500 - 5000
    print(f"测试用例1 - 有净充值:")
    print(f"  账户价值: $10,500")
    print(f"  已实现PNL: $500")
    print(f"  净充值: $5,000")
    print(f"  实际初始资金: ${result:,.2f} (预期: ${expected:,.2f})")
    assert abs(result - expected) < 0.01, f"计算错误: {result} != {expected}"
    print("  ✅ 通过\n")

    # 净提现情况
    result = MetricsEngine.calculate_actual_initial_capital(
        account_value=3000,
        realized_pnl=500,
        net_deposits=-2000  # 提现2000
    )
    expected = 4500  # 3000 - 500 - (-2000)
    print(f"测试用例2 - 有净提现:")
    print(f"  账户价值: $3,000")
    print(f"  已实现PNL: $500")
    print(f"  净充值: -$2,000 (提现)")
    print(f"  实际初始资金: ${result:,.2f} (预期: ${expected:,.2f})")
    assert abs(result - expected) < 0.01, f"计算错误: {result} != {expected}"
    print("  ✅ 通过\n")

    # 边界情况：结果为负（应降级）
    result = MetricsEngine.calculate_actual_initial_capital(
        account_value=1000,
        realized_pnl=-5000,
        net_deposits=10000
    )
    print(f"测试用例3 - 降级场景（结果为负）:")
    print(f"  账户价值: $1,000")
    print(f"  已实现PNL: -$5,000 (亏损)")
    print(f"  净充值: $10,000")
    print(f"  实际初始资金: ${result:,.2f} (应降级到 fallback)")
    assert result > 0, f"降级失败，结果为负: {result}"
    print("  ✅ 通过（已降级到 fallback）\n")


def test_corrected_roi():
    """测试校准ROI计算"""
    print("\n测试2: 校准ROI计算")
    print("=" * 60)

    # 正常盈利
    result = MetricsEngine.calculate_corrected_roi(500, 5000)
    expected = 10.0  # (500 / 5000) * 100
    print(f"测试用例1 - 正常盈利:")
    print(f"  已实现PNL: $500")
    print(f"  实际初始资金: $5,000")
    print(f"  校准ROI: {result:.2f}% (预期: {expected:.2f}%)")
    assert abs(result - expected) < 0.01, f"计算错误: {result} != {expected}"
    print("  ✅ 通过\n")

    # 正常亏损
    result = MetricsEngine.calculate_corrected_roi(-500, 5000)
    expected = -10.0  # (-500 / 5000) * 100
    print(f"测试用例2 - 正常亏损:")
    print(f"  已实现PNL: -$500")
    print(f"  实际初始资金: $5,000")
    print(f"  校准ROI: {result:.2f}% (预期: {expected:.2f}%)")
    assert abs(result - expected) < 0.01, f"计算错误: {result} != {expected}"
    print("  ✅ 通过\n")

    # 边界情况：初始资金为0
    result = MetricsEngine.calculate_corrected_roi(500, 0)
    print(f"测试用例3 - 边界保护（初始资金为0）:")
    print(f"  已实现PNL: $500")
    print(f"  实际初始资金: $0")
    print(f"  校准ROI: {result:.2f}% (应返回 0.0%)")
    assert result == 0.0, f"边界保护失败: {result} != 0.0"
    print("  ✅ 通过\n")


def test_pnl_and_roi_integration():
    """测试PNL和ROI整合计算"""
    print("\n测试3: PNL和ROI整合计算（4个返回值）")
    print("=" * 60)

    # 模拟交易数据
    fills = [
        {'closedPnl': '100'},   # 盈利100
        {'closedPnl': '-50'},   # 亏损50
        {'closedPnl': '200'},   # 盈利200
    ]

    account_value = 10000
    net_deposits = 5000

    # 有出入金数据的情况
    total_pnl, legacy_roi, actual_initial, corrected_roi = MetricsEngine.calculate_pnl_and_roi(
        fills, account_value, net_deposits, has_transfer_data=True
    )

    print(f"测试用例1 - 有出入金数据:")
    print(f"  账户价值: ${account_value:,.0f}")
    print(f"  净充值: ${net_deposits:,.0f}")
    print(f"  总PNL: ${total_pnl:,.2f} (预期: $250)")
    print(f"  旧版ROI: {legacy_roi:.2f}%")
    print(f"  实际初始资金: ${actual_initial:,.2f}")
    print(f"  校准ROI: {corrected_roi:.2f}%")

    assert abs(total_pnl - 250) < 0.01, f"总PNL计算错误: {total_pnl} != 250"
    assert actual_initial > 0, f"实际初始资金应大于0: {actual_initial}"
    print("  ✅ 通过\n")

    # 无出入金数据的情况（降级）
    total_pnl2, legacy_roi2, actual_initial2, corrected_roi2 = MetricsEngine.calculate_pnl_and_roi(
        fills, account_value, 0, has_transfer_data=False
    )

    print(f"测试用例2 - 无出入金数据（降级）:")
    print(f"  账户价值: ${account_value:,.0f}")
    print(f"  总PNL: ${total_pnl2:,.2f}")
    print(f"  旧版ROI: {legacy_roi2:.2f}%")
    print(f"  实际初始资金: ${actual_initial2:,.2f} (应等于推算初始资金)")
    print(f"  校准ROI: {corrected_roi2:.2f}% (应等于旧版ROI)")

    assert abs(total_pnl2 - 250) < 0.01, f"总PNL计算错误"
    assert abs(legacy_roi2 - corrected_roi2) < 0.01, f"降级失败：ROI不相等"
    print("  ✅ 通过（降级成功）\n")


def test_edge_cases():
    """测试边界情况"""
    print("\n测试4: 边界情况")
    print("=" * 60)

    # 空交易列表
    result = MetricsEngine.calculate_pnl_and_roi([], 1000, 0, False)
    print(f"测试用例1 - 空交易列表:")
    print(f"  返回值: {result}")
    assert result == (0.0, 0.0, 0.0, 0.0), "空列表应返回全0"
    print("  ✅ 通过\n")

    # 极大ROI（边界保护）
    fills = [{'closedPnl': '100000'}]
    total_pnl, legacy_roi, actual_initial, corrected_roi = MetricsEngine.calculate_pnl_and_roi(
        fills, 100100, 0, True
    )
    print(f"测试用例2 - 极大ROI:")
    print(f"  总PNL: ${total_pnl:,.0f}")
    print(f"  旧版ROI: {legacy_roi:.2f}% (应在边界范围内)")
    print(f"  校准ROI: {corrected_roi:.2f}% (应在边界范围内)")
    assert -999999.99 <= corrected_roi <= 999999.99, "ROI应在边界范围内"
    print("  ✅ 通过\n")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🧪 出入金整合指标计算单元测试")
    print("=" * 60)

    try:
        test_actual_initial_capital()
        test_corrected_roi()
        test_pnl_and_roi_integration()
        test_edge_cases()

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60 + "\n")

    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)

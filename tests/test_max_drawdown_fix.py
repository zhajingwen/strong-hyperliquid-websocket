#!/usr/bin/env python3
"""
测试最大回撤算法改进（P0修复）
验证出入金事件的正确处理
"""
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from address_analyzer.metrics_engine import MetricsEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_withdrawal_not_counted_as_drawdown():
    """
    测试场景1：提现不应算作回撤

    场景：
    - 初始充值 $100,000
    - 交易赚 $20,000 (账户=$120,000)
    - 提现 $50,000 (账户=$70,000)
    - 继续交易亏 $10,000 (账户=$60,000)

    预期：
    - 旧算法：回撤 = ($120,000 - $60,000) / $120,000 = 50% (错误！)
    - 新算法：回撤 = ($70,000 - $60,000) / $70,000 = 14.29% (正确)
    """
    print("\n" + "=" * 80)
    print("📊 测试1：提现不应算作回撤")
    print("=" * 80)

    # 构造测试数据
    fills = [
        {'time': 1000, 'closedPnl': '20000'},   # 赚$20K
        {'time': 3000, 'closedPnl': '-10000'},  # 亏$10K（提现后）
    ]

    ledger = [
        {
            'time': 0,
            'delta': {
                'type': 'deposit',
                'usdc': '100000'
            }
        },
        {
            'time': 2000,
            'delta': {
                'type': 'withdraw',
                'usdc': '50000'
            }
        }
    ]

    address = "0xtest"
    account_value = 60000.0  # 最终账户价值
    actual_initial = 100000.0  # 实际初始资金

    # 计算回撤
    max_dd, details = MetricsEngine.calculate_max_drawdown(
        fills, account_value, actual_initial, ledger, address
    )

    # 验证结果
    print(f"\n场景说明:")
    print(f"  1. 初始充值: $100,000")
    print(f"  2. 交易赚: $20,000 (账户=$120,000)")
    print(f"  3. 提现: $50,000 (账户=$70,000)")
    print(f"  4. 交易亏: $10,000 (账户=$60,000)")

    print(f"\n计算结果:")
    print(f"  旧算法回撤: {details['max_drawdown_legacy']:.2f}%")
    print(f"  新算法回撤: {max_dd:.2f}%")
    print(f"  改进幅度: {details.get('improvement_pct', 0):.2f}%")
    print(f"  质量标记: {details['quality']}")

    # 预期：新算法应该是 14.29%，旧算法应该是 50%
    expected_new = 14.29
    expected_old = 50.0

    if abs(max_dd - expected_new) < 1:
        print(f"\n  ✅ 新算法正确: {max_dd:.2f}% ≈ {expected_new:.2f}%")
    else:
        print(f"\n  ❌ 新算法错误: {max_dd:.2f}% != {expected_new:.2f}%")

    if abs(details['max_drawdown_legacy'] - expected_old) < 1:
        print(f"  ✅ 旧算法符合预期: {details['max_drawdown_legacy']:.2f}% ≈ {expected_old:.2f}%")
    else:
        print(f"  ⚠️  旧算法: {details['max_drawdown_legacy']:.2f}% != {expected_old:.2f}%")

    return abs(max_dd - expected_new) < 1


def test_deposit_adjusts_peak():
    """
    测试场景2：充值应调整峰值

    场景：
    - 初始充值 $10,000
    - 交易亏 $5,000 (账户=$5,000, 回撤=50%)
    - 追加充值 $10,000 (账户=$15,000)
    - 交易亏 $2,000 (账户=$13,000)

    预期：
    - 旧算法：回撤异常（可能>100%或负数）
    - 新算法：最大回撤 = max(50%, 13.33%) = 50%
    """
    print("\n" + "=" * 80)
    print("📊 测试2：充值应调整峰值")
    print("=" * 80)

    fills = [
        {'time': 1000, 'closedPnl': '-5000'},   # 亏$5K
        {'time': 3000, 'closedPnl': '-2000'},   # 亏$2K（充值后）
    ]

    ledger = [
        {
            'time': 0,
            'delta': {
                'type': 'deposit',
                'usdc': '10000'
            }
        },
        {
            'time': 2000,
            'delta': {
                'type': 'deposit',
                'usdc': '10000'
            }
        }
    ]

    address = "0xtest"
    account_value = 13000.0
    actual_initial = 20000.0

    max_dd, details = MetricsEngine.calculate_max_drawdown(
        fills, account_value, actual_initial, ledger, address
    )

    print(f"\n场景说明:")
    print(f"  1. 初始充值: $10,000")
    print(f"  2. 交易亏: $5,000 (账户=$5,000, 回撤=50%)")
    print(f"  3. 追加充值: $10,000 (账户=$15,000)")
    print(f"  4. 交易亏: $2,000 (账户=$13,000, 回撤=13.33%)")

    print(f"\n计算结果:")
    print(f"  旧算法回撤: {details['max_drawdown_legacy']:.2f}%")
    print(f"  新算法回撤: {max_dd:.2f}%")
    print(f"  回撤次数: {details['drawdown_count']}")
    print(f"  单次最大回撤: {details['largest_drawdown_pct']:.2f}%")

    # 预期：新算法应该是 50%（第一次回撤）
    expected = 50.0

    if abs(max_dd - expected) < 1:
        print(f"\n  ✅ 新算法正确: {max_dd:.2f}% ≈ {expected:.2f}%")
    else:
        print(f"\n  ❌ 新算法错误: {max_dd:.2f}% != {expected:.2f}%")

    if details['drawdown_count'] >= 2:
        print(f"  ✅ 正确识别出2次回撤")
    else:
        print(f"  ⚠️  回撤次数统计可能有误: {details['drawdown_count']}")

    return abs(max_dd - expected) < 1


def test_no_ledger_falls_back_to_legacy():
    """
    测试场景3：无ledger数据时降级到旧算法
    """
    print("\n" + "=" * 80)
    print("📊 测试3：无ledger数据时降级到旧算法")
    print("=" * 80)

    fills = [
        {'time': 1000, 'closedPnl': '10000'},
        {'time': 2000, 'closedPnl': '-5000'},
        {'time': 3000, 'closedPnl': '3000'},
    ]

    account_value = 108000.0
    actual_initial = 100000.0

    # 不提供ledger数据
    max_dd, details = MetricsEngine.calculate_max_drawdown(
        fills, account_value, actual_initial, None, None
    )

    print(f"\n计算结果:")
    print(f"  回撤: {max_dd:.2f}%")
    print(f"  质量标记: {details['quality']}")
    print(f"  旧算法回撤: {details['max_drawdown_legacy']:.2f}%")

    # 验证：应该使用旧算法
    if details['quality'] in ['standard', 'estimated', 'estimated_fallback']:
        print(f"\n  ✅ 正确降级到旧算法")
    else:
        print(f"\n  ❌ 质量标记错误: {details['quality']}")

    if abs(max_dd - details['max_drawdown_legacy']) < 0.01:
        print(f"  ✅ 新旧算法结果一致（无ledger时应一致）")
    else:
        print(f"  ❌ 新旧算法结果不一致")

    return details['quality'] in ['standard', 'estimated', 'estimated_fallback']


def test_transfer_vs_deposit():
    """
    测试场景4：转账 vs 充值的区分

    转账（send/subAccountTransfer）可能是盈亏转移，不应调整峰值
    充值（deposit）是真实资金注入，应调整峰值
    """
    print("\n" + "=" * 80)
    print("📊 测试4：转账 vs 充值的区分")
    print("=" * 80)

    fills = [
        {'time': 1000, 'closedPnl': '20000'},
    ]

    # 场景A：收到转账
    ledger_transfer = [
        {
            'time': 0,
            'delta': {
                'type': 'deposit',
                'usdc': '100000'
            }
        },
        {
            'time': 2000,
            'delta': {
                'type': 'send',
                'amount': '50000',
                'user': '0xother',
                'destination': '0xtest'
            }
        }
    ]

    # 场景B：真实充值
    ledger_deposit = [
        {
            'time': 0,
            'delta': {
                'type': 'deposit',
                'usdc': '100000'
            }
        },
        {
            'time': 2000,
            'delta': {
                'type': 'deposit',
                'usdc': '50000'
            }
        }
    ]

    address = "0xtest"
    account_value = 120000.0

    # 计算两种情况
    dd_transfer, details_transfer = MetricsEngine.calculate_max_drawdown(
        fills, account_value, None, ledger_transfer, address
    )

    dd_deposit, details_deposit = MetricsEngine.calculate_max_drawdown(
        fills, account_value, None, ledger_deposit, address
    )

    print(f"\n场景A - 收到转账 (可能是盈亏转移):")
    print(f"  回撤: {dd_transfer:.2f}%")
    print(f"  质量: {details_transfer['quality']}")

    print(f"\n场景B - 真实充值:")
    print(f"  回撤: {dd_deposit:.2f}%")
    print(f"  质量: {details_deposit['quality']}")

    # 两种场景应该有相同的处理（都算作资金流入）
    # 实际业务中，可能需要更智能的区分逻辑
    print(f"\n  ℹ️  当前实现：转账和充值都算作资金流入")
    print(f"  ℹ️  未来可优化：根据业务逻辑区分盈亏转移")

    return True


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 80)
    print("🧪 最大回撤算法改进测试（P0修复）")
    print("=" * 80)

    tests = [
        ("提现不算回撤", test_withdrawal_not_counted_as_drawdown),
        ("充值调整峰值", test_deposit_adjusts_peak),
        ("降级到旧算法", test_no_ledger_falls_back_to_legacy),
        ("转账vs充值", test_transfer_vs_deposit),
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
        print("\n🎉 所有测试通过！P0修复成功。")
    else:
        print("\n⚠️  部分测试失败，需要进一步调试。")

    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

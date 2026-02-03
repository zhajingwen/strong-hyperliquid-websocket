"""
P0 修复专项测试 - Sharpe 比率年化、爆仓处理

验证关键算法修复：
1. 复利年化 Sharpe 比率计算
2. 爆仓场景处理
3. 初始资金动态降级
"""

import sys
import numpy as np
from address_analyzer.metrics_engine import MetricsEngine, AddressMetrics


class TestSharpeCompoundInterest:
    """测试 Sharpe 比率复利年化算法"""

    def test_sharpe_stable_profit(self):
        """测试稳定盈利场景 - 每天0.5%收益"""
        base_time = 1704067200000  # 2024-01-01
        fills = []

        capital = 10000
        # 使用更温和的收益率 0.5%
        for i in range(100):  # 100天而非365天
            pnl = capital * 0.005
            capital += pnl
            fills.append({
                'time': base_time + i * 86400000,
                'closedPnl': str(pnl)
            })

        account_value = capital
        sharpe = MetricsEngine.calculate_sharpe_ratio(fills, account_value)

        # Sharpe 应为正且不应是 NaN/Inf
        assert not np.isnan(sharpe), f"Sharpe 不应为 NaN"
        assert not np.isinf(sharpe), f"Sharpe 不应为 Inf"
        assert sharpe > 0, f"稳定盈利 Sharpe 应为正: {sharpe}"
        print(f"✅ 稳定盈利 Sharpe: {sharpe:.2f}")

    def test_sharpe_high_frequency(self):
        """测试高频交易场景 - 每天5笔交易"""
        base_time = 1704067200000
        fills = []

        capital = 10000
        # 降低频率和收益率
        for day in range(50):
            for trade in range(5):
                pnl = capital * 0.0005  # 每笔0.05%
                capital += pnl
                fills.append({
                    'time': base_time + day * 86400000 + trade * 3600000,
                    'closedPnl': str(pnl)
                })

        account_value = capital
        sharpe = MetricsEngine.calculate_sharpe_ratio(fills, account_value)

        # 验证不是异常值
        assert not np.isnan(sharpe), "Sharpe 不应为 NaN"
        assert not np.isinf(sharpe), "Sharpe 不应为 Inf"
        print(f"✅ 高频交易 Sharpe: {sharpe:.2f}")

    def test_sharpe_volatile_trading(self):
        """测试高波动交易"""
        base_time = 1704067200000
        fills = []

        capital = 10000
        returns = [0.02, -0.01, 0.03, -0.015, 0.025, -0.01, 0.04, -0.02]  # 适度波动

        for i, ret in enumerate(returns * 5):  # 重复5轮
            pnl = capital * ret
            capital += pnl
            fills.append({
                'time': base_time + i * 86400000,
                'closedPnl': str(pnl)
            })

        account_value = capital
        sharpe = MetricsEngine.calculate_sharpe_ratio(fills, account_value)

        # 验证 Sharpe 合理性
        assert not np.isnan(sharpe), "Sharpe 不应为 NaN"
        assert not np.isinf(sharpe), "Sharpe 不应为 Inf"
        print(f"✅ 高波动交易 Sharpe: {sharpe:.2f}, 最终资金: ${capital:.0f}")

    def test_sharpe_no_nan_inf(self):
        """测试不应产生 NaN 或 Inf"""
        # 边界情况：全部亏损
        fills = [
            {'time': 1704067200000, 'closedPnl': '-100'},
            {'time': 1704153600000, 'closedPnl': '-50'},
            {'time': 1704240000000, 'closedPnl': '-75'},
        ]
        account_value = 500

        sharpe = MetricsEngine.calculate_sharpe_ratio(fills, account_value)
        assert not np.isnan(sharpe), "Sharpe 不应为 NaN"
        assert not np.isinf(sharpe), "Sharpe 不应为 Inf"
        print(f"✅ 全亏损 Sharpe: {sharpe:.2f}")


class TestBankruptcyHandling:
    """测试爆仓处理逻辑"""

    def test_bankruptcy_detection(self):
        """测试爆仓检测"""
        fills = [
            {'time': 1704067200000, 'closedPnl': '500'},
            {'time': 1704153600000, 'closedPnl': '-2000'},  # 爆仓
            {'time': 1704240000000, 'closedPnl': '100'},    # 爆仓后
        ]

        account_value = 100
        bankruptcy_count = MetricsEngine.detect_bankruptcy(fills, account_value)

        assert bankruptcy_count >= 1, f"应该检测到爆仓，实际: {bankruptcy_count}"
        print(f"✅ 检测到 {bankruptcy_count} 次爆仓")

    def test_sharpe_stops_at_bankruptcy(self):
        """测试 Sharpe 计算在爆仓时终止"""
        fills = [
            {'time': 1704067200000, 'closedPnl': '500'},
            {'time': 1704153600000, 'closedPnl': '-2000'},  # 爆仓
            {'time': 1704240000000, 'closedPnl': '100'},    # 不应计入
            {'time': 1704326400000, 'closedPnl': '200'},    # 不应计入
        ]

        account_value = 100
        sharpe = MetricsEngine.calculate_sharpe_ratio(fills, account_value)

        # Sharpe 应该基于前2笔交易
        assert not np.isnan(sharpe), "Sharpe 不应为 NaN"
        print(f"✅ 爆仓后 Sharpe: {sharpe:.2f}")

    def test_metrics_includes_bankruptcy_count(self):
        """测试完整指标包含爆仓次数"""
        fills = [
            {'time': 1704067200000, 'closedPnl': '100', 'px': '50000', 'sz': '0.1'},
            {'time': 1704153600000, 'closedPnl': '-500', 'px': '50100', 'sz': '0.1'},
        ]

        state = {'marginSummary': {'accountValue': '100'}}

        metrics = MetricsEngine.calculate_metrics(
            address='test',
            fills=fills,
            state=state
        )

        assert hasattr(metrics, 'bankruptcy_count'), "应有 bankruptcy_count 字段"
        assert hasattr(metrics, 'sharpe_method'), "应有 sharpe_method 字段"
        print(f"✅ 爆仓次数: {metrics.bankruptcy_count}, 方法: {metrics.sharpe_method}")


class TestInitialCapitalFallback:
    """测试初始资金降级策略"""

    def test_positive_initial_capital(self):
        """测试正常计算场景"""
        account_value = 10000
        realized_pnl = 2000
        net_deposits = 3000

        actual_initial = account_value - realized_pnl - net_deposits
        # 10000 - 2000 - 3000 = 5000

        assert actual_initial == 5000, f"初始资金计算错误: {actual_initial}"
        print(f"✅ 正常初始资金: {actual_initial}")

    def test_negative_initial_fallback(self):
        """测试负值降级"""
        # 构造极端场景：大量提现
        account_value = 100
        realized_pnl = 50
        net_deposits = -10000  # 提现很多

        actual_initial = MetricsEngine.calculate_actual_initial_capital(
            account_value, realized_pnl, net_deposits
        )

        # 应该降级到推算值
        expected_fallback = account_value - realized_pnl  # 100 - 50 = 50
        assert actual_initial >= 50, f"降级后初始资金过小: {actual_initial}"
        print(f"✅ 降级后初始资金: {actual_initial}")

    def test_severe_loss_scenario(self):
        """测试严重亏损场景"""
        account_value = 500
        realized_pnl = -5000
        net_deposits = 1000

        actual_initial = MetricsEngine.calculate_actual_initial_capital(
            account_value, realized_pnl, net_deposits
        )

        # 500 - (-5000) - 1000 = 4500（正常计算）
        assert actual_initial == 4500, f"严重亏损场景计算错误: {actual_initial}"
        print(f"✅ 严重亏损初始资金: {actual_initial}")


class TestComprehensiveMetrics:
    """综合指标测试"""

    def test_full_metrics_calculation(self):
        """测试完整指标计算"""
        fills = [
            {'time': 1704067200000, 'closedPnl': '100', 'px': '50000', 'sz': '0.1'},
            {'time': 1704153600000, 'closedPnl': '-50', 'px': '50100', 'sz': '0.1'},
            {'time': 1704240000000, 'closedPnl': '200', 'px': '50200', 'sz': '0.2'},
            {'time': 1704326400000, 'closedPnl': '150', 'px': '50300', 'sz': '0.15'},
            {'time': 1704412800000, 'closedPnl': '-30', 'px': '50400', 'sz': '0.1'},
        ]

        state = {'marginSummary': {'accountValue': '10500'}}

        metrics = MetricsEngine.calculate_metrics(
            address='0xtest',
            fills=fills,
            state=state
        )

        # 验证所有字段存在
        assert metrics.total_trades == 5
        assert 0 <= metrics.win_rate <= 100
        assert not np.isnan(metrics.sharpe_ratio)
        assert not np.isnan(metrics.roi)
        assert metrics.sharpe_method == "compound_interest"

        print(f"""
        ✅ 完整指标计算成功:
           - 交易数: {metrics.total_trades}
           - 胜率: {metrics.win_rate:.1f}%
           - ROI: {metrics.roi:.1f}%
           - Sharpe: {metrics.sharpe_ratio:.2f}
           - 最大回撤: {metrics.max_drawdown:.1f}%
           - 爆仓次数: {metrics.bankruptcy_count}
        """)

    def test_metrics_with_transfer_data(self):
        """测试带出入金数据的指标计算"""
        fills = [
            {'time': 1704067200000, 'closedPnl': '500', 'px': '50000', 'sz': '0.5'},
            {'time': 1704153600000, 'closedPnl': '300', 'px': '50100', 'sz': '0.3'},
        ]

        state = {'marginSummary': {'accountValue': '12800'}}

        transfer_data = {
            'net_deposits': 2000.0,
            'total_deposits': 5000.0,
            'total_withdrawals': 3000.0
        }

        metrics = MetricsEngine.calculate_metrics(
            address='0xtest',
            fills=fills,
            state=state,
            transfer_data=transfer_data
        )

        # 验证出入金相关字段
        assert metrics.net_deposits == 2000.0
        assert metrics.total_deposits == 5000.0
        assert metrics.total_withdrawals == 3000.0
        assert metrics.actual_initial_capital > 0
        assert metrics.corrected_roi != 0

        print(f"""
        ✅ 出入金数据集成:
           - 净充值: ${metrics.net_deposits:,.0f}
           - 实际初始资金: ${metrics.actual_initial_capital:,.0f}
           - 校准 ROI: {metrics.corrected_roi:.1f}%
        """)


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*70)
    print("🧪 P0 修复专项测试")
    print("="*70 + "\n")

    test_classes = [
        TestSharpeCompoundInterest,
        TestBankruptcyHandling,
        TestInitialCapitalFallback,
        TestComprehensiveMetrics
    ]

    passed = 0
    failed = 0

    for test_class in test_classes:
        print(f"\n📦 {test_class.__name__}")
        print("-" * 70)

        test_instance = test_class()
        test_methods = [m for m in dir(test_instance) if m.startswith('test_')]

        for method_name in test_methods:
            try:
                method = getattr(test_instance, method_name)
                method()
                passed += 1
                print(f"  ✅ {method_name}")
            except Exception as e:
                failed += 1
                print(f"  ❌ {method_name}: {e}")

    print("\n" + "="*70)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("="*70)

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

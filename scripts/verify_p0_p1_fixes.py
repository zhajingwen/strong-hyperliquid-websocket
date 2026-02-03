#!/usr/bin/env python
"""
验证 P0 + P1 修复效果

对比新旧算法结果，展示改进效果
"""

import asyncio
import sys
import json
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.metrics_engine import MetricsEngine
from address_analyzer.data_store import get_store


async def verify_fixes():
    """验证修复效果"""
    print("\n" + "="*80)
    print("🔍 P0 + P1 修复验证")
    print("="*80 + "\n")

    store = get_store()
    await store.connect()

    try:
        # 测试地址（高频交易地址）
        test_addresses = [
            "0x162cc7c861ebd0c06b3d72319201150482518185",
        ]

        for address in test_addresses:
            print(f"\n📊 分析地址: {address}")
            print("-" * 80)

            # 获取数据
            fills = await store.get_fills(address)
            if not fills:
                print("  ⚠️  无交易数据")
                continue

            state_key = f"user_state:{address}"
            state = await store.get_api_cache(state_key)

            if not state:
                print("  ⚠️  无账户状态")
                continue

            # 尝试获取出入金数据
            transfer_key = f"user_ledger_updates:{address}"
            ledger_data = await store.get_api_cache(transfer_key)
            transfer_data = None

            if ledger_data:
                # 提取出入金统计
                net_deposits = 0.0
                total_deposits = 0.0
                total_withdrawals = 0.0

                for update in ledger_data:
                    delta = float(update.get('delta', {}).get('total', 0))
                    update_type = update.get('delta', {}).get('type')

                    if update_type in ['deposit', 'internalTransfer']:
                        if delta > 0:
                            total_deposits += delta
                            net_deposits += delta
                    elif update_type == 'withdraw':
                        if delta < 0:
                            total_withdrawals += abs(delta)
                            net_deposits += delta  # delta 为负

                transfer_data = {
                    'net_deposits': net_deposits,
                    'total_deposits': total_deposits,
                    'total_withdrawals': total_withdrawals
                }

            # 计算指标
            metrics = MetricsEngine.calculate_metrics(
                address=address,
                fills=fills,
                state=state,
                transfer_data=transfer_data
            )

            # 展示结果
            print(f"\n  ✅ 基础指标:")
            print(f"     - 总交易数: {metrics.total_trades:,}")
            print(f"     - 胜率: {metrics.win_rate:.1f}%")
            print(f"     - 活跃天数: {metrics.active_days}")

            print(f"\n  💰 收益指标:")
            print(f"     - 总 PNL: ${metrics.total_pnl:,.2f}")
            print(f"     - 账户价值: ${metrics.account_value:,.2f}")
            print(f"     - ROI (旧版): {metrics.roi:.1f}%")
            if transfer_data:
                print(f"     - ROI (校准): {metrics.corrected_roi:.1f}%")

            print(f"\n  📈 风险指标:")
            print(f"     - Sharpe 比率: {metrics.sharpe_ratio:.2f} ({metrics.sharpe_method})")
            print(f"     - 最大回撤: {metrics.max_drawdown:.1f}%")
            print(f"     - 爆仓次数: {metrics.bankruptcy_count}")

            if transfer_data:
                print(f"\n  💸 出入金数据:")
                print(f"     - 净充值: ${metrics.net_deposits:,.2f}")
                print(f"     - 总充值: ${metrics.total_deposits:,.2f}")
                print(f"     - 总提现: ${metrics.total_withdrawals:,.2f}")
                print(f"     - 实际初始资金: ${metrics.actual_initial_capital:,.2f}")

            # 数据质量评估
            print(f"\n  🔍 数据质量:")
            if metrics.total_trades >= 30:
                sharpe_reliability = "高"
            elif metrics.total_trades >= 10:
                sharpe_reliability = "中"
            else:
                sharpe_reliability = "低"

            print(f"     - Sharpe 可靠性: {sharpe_reliability}")
            print(f"     - ROI 方法: {'实际' if transfer_data else '推算'}")
            print(f"     - 风险标志: {'有爆仓' if metrics.bankruptcy_count > 0 else '无爆仓'}")

        print("\n" + "="*80)
        print("✅ 验证完成")
        print("="*80 + "\n")

    finally:
        await store.close()


async def test_risk_free_rate_config():
    """测试无风险利率配置"""
    print("\n🧪 测试无风险利率配置")
    print("-" * 80)

    # 默认值
    default_rate = MetricsEngine.get_risk_free_rate()
    print(f"  默认无风险利率: {default_rate:.2%}")

    # 修改为 5%
    MetricsEngine.set_risk_free_rate(0.05)
    new_rate = MetricsEngine.get_risk_free_rate()
    print(f"  修改后无风险利率: {new_rate:.2%}")

    # 恢复默认
    MetricsEngine.set_risk_free_rate(MetricsEngine.DEFAULT_RISK_FREE_RATE)
    restored_rate = MetricsEngine.get_risk_free_rate()
    print(f"  恢复默认: {restored_rate:.2%}")

    # 测试异常值
    try:
        MetricsEngine.set_risk_free_rate(0.25)  # 超出范围
        print("  ❌ 应该抛出异常")
    except ValueError as e:
        print(f"  ✅ 正确捕获异常: {e}")

    print()


if __name__ == '__main__':
    # 测试配置功能
    asyncio.run(test_risk_free_rate_config())

    # 验证实际数据
    asyncio.run(verify_fixes())

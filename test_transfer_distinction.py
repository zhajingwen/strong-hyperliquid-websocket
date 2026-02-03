#!/usr/bin/env python3
"""
测试转账类型区分功能
验证修改后的 metrics_engine.py 和 data_store.py 是否正确区分转账类型
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store
from address_analyzer.metrics_engine import MetricsEngine


async def test_transfer_distinction(address: str):
    """测试转账类型区分"""

    print("=" * 80)
    print("🧪 转账类型区分功能测试")
    print("=" * 80)

    # 初始化
    store = get_store()
    await store.connect()

    client = HyperliquidAPIClient(
        store=store,
        max_concurrent=5,
        rate_limit=10.0
    )

    print(f"\n测试地址: {address}")
    print("-" * 80)

    # 1. 获取 ledger 数据并保存
    print("\n【步骤1】获取并保存 ledger 数据")
    try:
        ledger_data = await client.get_user_ledger(
            address,
            start_time=0,
            use_cache=False
        )

        print(f"  获取 {len(ledger_data)} 条 ledger 记录")

        # 分类统计
        type_counts = {}
        for record in ledger_data:
            record_type = record['delta'].get('type', 'unknown')
            type_counts[record_type] = type_counts.get(record_type, 0) + 1

        print(f"\n  Ledger 记录类型分布:")
        for rtype, count in sorted(type_counts.items()):
            print(f"    {rtype:30s}: {count:3d} 条")

        # 保存到数据库
        await store.save_transfers(address, ledger_data)
        print(f"\n  ✅ 已保存到数据库")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        await store.close()
        return

    # 2. 从数据库读取统计数据
    print("\n【步骤2】从数据库读取统计数据")
    try:
        transfer_stats = await store.get_net_deposits(address)

        print(f"\n  ✅ 数据库统计结果:")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  💰 充值/提现（真实本金）")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"    总充值:       ${transfer_stats['total_deposits']:>12,.2f}")
        print(f"    总提现:       ${transfer_stats['total_withdrawals']:>12,.2f}")
        print(f"    真实本金:     ${transfer_stats['true_capital']:>12,.2f}")

        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  🔄 转账（可能是盈亏转移）")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"    转入:         ${transfer_stats['total_transfers_in']:>12,.2f}")
        print(f"    转出:         ${transfer_stats['total_transfers_out']:>12,.2f}")
        print(f"    净转账:       ${transfer_stats['net_transfers']:>12,.2f}")

        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📊 传统方法（包含转账）")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"    净流入:       ${transfer_stats['net_deposits']:>12,.2f}")

    except Exception as e:
        print(f"  ❌ 读取失败: {e}")
        import traceback
        traceback.print_exc()
        await store.close()
        return

    # 3. 计算完整指标
    print("\n【步骤3】计算完整指标")
    try:
        # 获取交易记录
        fills = await client.get_user_fills(address, use_cache=False)
        print(f"  获取 {len(fills)} 条交易记录")

        # 获取账户状态
        state = client.info.user_state(address)
        account_value = float(state['marginSummary']['accountValue'])
        print(f"  当前账户价值: ${account_value:,.2f}")

        # 计算指标
        metrics = MetricsEngine.calculate_metrics(
            address=address,
            fills=fills,
            state=state,
            transfer_data=transfer_stats
        )

        print(f"\n  ✅ 指标计算结果:")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📊 基础指标")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"    总交易数:     {metrics.total_trades:>12,}")
        print(f"    胜率:         {metrics.win_rate:>12.1f}%")
        print(f"    总 PNL:       ${metrics.total_pnl:>12,.2f}")
        print(f"    账户价值:     ${metrics.account_value:>12,.2f}")

        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  💰 本金与 ROI")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"\n    【方法1】真实本金（仅充值/提现）")
        print(f"      真实本金:   ${metrics.true_capital:>12,.2f}")
        print(f"      ROI:        {metrics.true_capital_roi:>12.1f}%")

        print(f"\n    【方法2】传统方法（包含转账）")
        print(f"      总净流入:   ${metrics.net_deposits:>12,.2f}")
        print(f"      ROI:        {metrics.corrected_roi:>12.1f}%")

        print(f"\n    【方法3】推算方法（旧版）")
        print(f"      推算本金:   ${metrics.account_value - metrics.total_pnl:>12,.2f}")
        print(f"      ROI:        {metrics.roi:>12.1f}%")

        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  🔄 转账详情")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"    转入:         ${metrics.total_transfers_in:>12,.2f}")
        print(f"    转出:         ${metrics.total_transfers_out:>12,.2f}")
        print(f"    净转账:       ${metrics.net_transfers:>12,.2f}")

        if metrics.net_transfers > 0:
            print(f"\n    ⚠️  检测到净转入 ${metrics.net_transfers:,.2f}")
            print(f"       这可能是从其他账户转移的盈亏")
            print(f"       建议使用【方法1】真实本金进行 ROI 计算")

        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📈 风险指标")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"    夏普比率:     {metrics.sharpe_ratio:>12.2f}")
        print(f"    最大回撤:     {metrics.max_drawdown:>12.1f}%")
        print(f"    爆仓次数:     {metrics.bankruptcy_count:>12,}")

    except Exception as e:
        print(f"  ❌ 计算失败: {e}")
        import traceback
        traceback.print_exc()

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 测试完成")
    print("=" * 80)


if __name__ == '__main__':
    import sys

    # 默认测试地址
    default_address = "0xde786a32f80731923d6297c14ef43ca1c8fd4b44"

    if len(sys.argv) > 1:
        address = sys.argv[1]
    else:
        address = input(f"请输入地址 (默认={default_address}): ").strip() or default_address

    asyncio.run(test_transfer_distinction(address))

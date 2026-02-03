#!/usr/bin/env python3
"""
完整测试单个地址 - 从 API 获取数据到生成报告
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.data_store import DataStore, get_store
from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.metrics_engine import MetricsEngine
from address_analyzer.output_renderer import OutputRenderer


async def test_complete_single_address():
    """完整测试单个地址"""
    target_address = "0xde786a32f80731923d6297c14ef43ca1c8fd4b44"

    print("=" * 80)
    print(f"🧪 完整测试地址: {target_address}")
    print("=" * 80)

    # 初始化
    store = get_store()
    await store.connect()
    await store.init_schema()

    api_client = HyperliquidAPIClient(store=store)
    metrics_engine = MetricsEngine()
    renderer = OutputRenderer()

    try:
        # 步骤 1: 从 API 获取数据
        print("\n步骤 1/4: 从 API 获取完整数据...")
        print(f"   正在获取地址数据...")

        data = await api_client.fetch_address_data(target_address)

        if not data:
            print(f"❌ 无法获取地址数据")
            return

        fills = data.get('fills', [])
        ledger = data.get('ledger', [])
        funding = data.get('funding', [])
        state = data.get('state')
        spot_state = data.get('spot_state')

        print(f"✅ 数据获取成功:")
        print(f"   - 用户成交: {len(fills)} 条")
        print(f"   - 出入金记录: {len(ledger)} 条")
        print(f"   - 资金费率: {len(funding)} 条")
        print(f"   - 账户状态: {'✓' if state else '✗'}")
        print(f"   - Spot 状态: {'✓' if spot_state else '✗'}")

        # 步骤 2: 准备转账统计
        print("\n步骤 2/4: 计算转账统计...")

        total_deposits = 0.0
        total_withdrawals = 0.0

        for record in ledger:
            delta = record.get('delta', {})
            delta_type = delta.get('type', '')

            if delta_type == 'deposit':
                amount = float(delta.get('usdc', 0))
                total_deposits += amount
            elif delta_type == 'withdraw':
                amount = float(delta.get('usdc', 0))
                total_withdrawals += abs(amount)

        transfer_stats = {
            'total_deposits': total_deposits,
            'total_withdrawals': total_withdrawals,
            'net_deposits': total_deposits - total_withdrawals
        }

        print(f"✅ 转账统计:")
        print(f"   - 总充值: ${total_deposits:,.2f}")
        print(f"   - 总提现: ${total_withdrawals:,.2f}")
        print(f"   - 净充值: ${transfer_stats['net_deposits']:,.2f}")

        # 步骤 3: 计算指标（包含新功能）
        print("\n步骤 3/4: 计算交易指标（包含新的累计收益率和年化收益率）...")

        metrics = metrics_engine.calculate_metrics(
            address=target_address,
            fills=fills,
            state=state,
            transfer_data=transfer_stats,
            spot_state=spot_state
        )

        if not metrics:
            print(f"❌ 指标计算失败")
            return

        print(f"✅ 指标计算成功")

        # 显示完整指标
        print("\n" + "=" * 80)
        print("📊 完整交易指标")
        print("=" * 80)

        print(f"\n基础指标:")
        print(f"  总交易数: {metrics.total_trades}")
        print(f"  胜率: {metrics.win_rate:.1f}%")
        print(f"  夏普比率: {metrics.sharpe_ratio:.2f}")
        print(f"  最大回撤: {metrics.max_drawdown:.1f}%")
        print(f"  活跃天数: {metrics.active_days}")

        print(f"\n账户价值分析:")
        print(f"  总账户价值: ${metrics.account_value:,.2f}")
        if metrics.account_value > 0:
            perp_pct = (metrics.perp_value / metrics.account_value * 100)
            spot_pct = (metrics.spot_value / metrics.account_value * 100)
            print(f"  • Perp 价值: ${metrics.perp_value:,.2f} ({perp_pct:.1f}%)")
            print(f"  • Spot 价值: ${metrics.spot_value:,.2f} ({spot_pct:.1f}%)")

        print(f"\n盈亏分析:")
        print(f"  总 PNL: ${metrics.total_pnl:,.2f}")
        print(f"  总充值: ${total_deposits:,.2f}")
        print(f"  总提现: ${total_withdrawals:,.2f}")
        print(f"  净充值: ${metrics.net_deposits:,.2f}")

        print(f"\n收益率指标:")
        print(f"  ROI(推算): {metrics.roi:+.1f}%")
        print(f"  ROI(校准): {metrics.corrected_roi:+.1f}%")
        print(f"  初始资本(校正): ${metrics.initial_capital_corrected:,.2f}")
        print(f"  ✨ 累计收益率: {metrics.cumulative_return:+.1f}%  ← 新增指标")
        print(f"  ✨ 年化收益率: {metrics.annualized_return:+.1f}%  ← 新增指标")

        # 验证计算
        print(f"\n✅ 算法验证:")
        if metrics.initial_capital_corrected > 0:
            # 验证累计收益率
            expected_cumulative = ((metrics.account_value - metrics.initial_capital_corrected) /
                                 metrics.initial_capital_corrected * 100)
            print(f"  累计收益率验证:")
            print(f"    预期值: {expected_cumulative:+.2f}%")
            print(f"    实际值: {metrics.cumulative_return:+.2f}%")
            diff = abs(expected_cumulative - metrics.cumulative_return)
            if diff < 0.1:
                print(f"    ✅ 验证通过 (误差: {diff:.4f}%)")
            else:
                print(f"    ⚠️  验证失败 (误差: {diff:.4f}%)")

            # 验证年化收益率
            if metrics.active_days > 0:
                years = metrics.active_days / 365.0
                total_return_rate = metrics.account_value / metrics.initial_capital_corrected
                expected_annualized = (pow(total_return_rate, 1/years) - 1) * 100
                print(f"  年化收益率验证:")
                print(f"    活跃年数: {years:.2f} 年")
                print(f"    预期值: {expected_annualized:+.2f}%")
                print(f"    实际值: {metrics.annualized_return:+.2f}%")
                diff = abs(expected_annualized - metrics.annualized_return)
                if diff < 0.1:
                    print(f"    ✅ 验证通过 (误差: {diff:.4f}%)")
                else:
                    print(f"    ⚠️  验证失败 (误差: {diff:.4f}%)")
        else:
            print(f"  ⚠️  初始资本为 0，无法验证收益率")

        # 步骤 4: 生成报告
        print("\n步骤 4/4: 生成完整报告...")

        # 终端报告
        print("\n" + "=" * 80)
        print("📋 终端报告")
        print("=" * 80)
        renderer.render_terminal([metrics], top_n=10)

        # HTML 报告
        html_path = "output/single_address_final_report.html"
        renderer.render_html([metrics], html_path)

        print("\n" + "=" * 80)
        print("✅ 完整测试成功！")
        print("=" * 80)

        print(f"\n📊 生成的报告:")
        print(f"   HTML: {html_path}")

        print(f"\n🎯 测试结论:")
        print(f"   1. ✅ API 数据获取成功")
        print(f"   2. ✅ 指标计算成功（包含新指标）")
        print(f"   3. ✅ 终端报告生成成功")
        print(f"   4. ✅ HTML 报告生成成功")
        print(f"   5. ✅ 累计收益率: {metrics.cumulative_return:+.1f}%")
        print(f"   6. ✅ 年化收益率: {metrics.annualized_return:+.1f}%")

        print(f"\n💡 查看 HTML 报告:")
        print(f"   open {html_path}")

        # 保存到数据库（可选）
        await store.save_metrics(target_address, {
            'total_trades': metrics.total_trades,
            'win_rate': metrics.win_rate,
            'roi': metrics.roi,
            'corrected_roi': metrics.corrected_roi,
            'sharpe_ratio': metrics.sharpe_ratio,
            'total_pnl': metrics.total_pnl,
            'account_value': metrics.account_value,
            'perp_value': metrics.perp_value,
            'spot_value': metrics.spot_value,
            'max_drawdown': metrics.max_drawdown,
            'avg_trade_size': metrics.avg_trade_size,
            'total_volume': metrics.total_volume,
            'first_trade_time': metrics.first_trade_time,
            'last_trade_time': metrics.last_trade_time,
            'active_days': metrics.active_days,
            'net_deposits': metrics.net_deposits,
            'initial_capital_corrected': metrics.initial_capital_corrected,
            'cumulative_return': metrics.cumulative_return,
            'annualized_return': metrics.annualized_return,
        })
        print(f"\n✅ 指标已保存到数据库")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 关闭连接
        if hasattr(api_client, 'session') and api_client.session:
            await api_client.session.close()
        await store.close()


if __name__ == '__main__':
    asyncio.run(test_complete_single_address())

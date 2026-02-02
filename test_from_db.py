#!/usr/bin/env python3
"""
使用数据库已有数据测试完整流程
避免 API 调用，直接验证数据处理和指标计算
"""

import asyncio
import logging
from address_analyzer.data_store import get_store
from address_analyzer.metrics_engine import MetricsEngine
from address_analyzer.output_renderer import OutputRenderer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


async def main():
    """使用数据库数据进行完整测试"""
    print("\n" + "="*70)
    print("📊 使用数据库数据完整测试")
    print("="*70 + "\n")

    store = get_store()
    await store.connect()

    try:
        # 1. 获取有数据的地址
        print("1️⃣ 获取数据库中的地址...")
        async with store.pool.acquire() as conn:
            addresses = await conn.fetch('''
                SELECT DISTINCT address
                FROM fills
                ORDER BY address
            ''')

        address_list = [row['address'] for row in addresses]
        print(f"   发现 {len(address_list)} 个有交易记录的地址\n")

        # 2. 计算每个地址的指标
        print("2️⃣ 计算交易指标...\n")
        engine = MetricsEngine()
        all_metrics = []

        for addr in address_list:
            # 从数据库读取交易记录
            fills = await store.get_fills(addr)

            # 从缓存读取账户状态
            state = await store.get_api_cache(f"user_state:{addr}")

            if not fills:
                continue

            # 计算指标
            metrics = engine.calculate_metrics(addr, fills, state)
            all_metrics.append(metrics)

            # 保存指标
            await store.save_metrics(addr, {
                'total_trades': metrics.total_trades,
                'win_rate': metrics.win_rate,
                'roi': metrics.roi,
                'sharpe_ratio': metrics.sharpe_ratio,
                'total_pnl': metrics.total_pnl,
                'account_value': metrics.account_value,
                'max_drawdown': metrics.max_drawdown,
                'net_deposit': metrics.net_deposit
            })

            print(f"   ✅ {addr[:12]}... - {metrics.total_trades} 笔交易")

        print(f"\n   计算完成: {len(all_metrics)} 个地址\n")

        # 3. 生成输出
        print("3️⃣ 生成报告...\n")
        renderer = OutputRenderer()

        # 终端输出
        print("="*70)
        renderer.render_terminal(all_metrics, top_n=10)
        print("="*70 + "\n")

        # HTML 报告
        html_path = 'output/db_test_report.html'
        renderer.render_html(all_metrics, output_path=html_path)
        print(f"✅ HTML 报告已保存: {html_path}\n")

        # 4. 详细展示前 5 个地址
        print("="*70)
        print("📊 详细指标（前 5 个地址）")
        print("="*70 + "\n")

        # 按总PNL排序
        sorted_metrics = sorted(all_metrics, key=lambda x: x.total_pnl, reverse=True)

        for i, m in enumerate(sorted_metrics[:5], 1):
            print(f"{i}. {m.address}")
            print(f"   交易次数: {m.total_trades}")
            print(f"   胜率: {m.win_rate:.2f}%")
            print(f"   ROI: {m.roi:.2f}%")
            print(f"   夏普比率: {m.sharpe_ratio:.2f}")
            print(f"   总PNL: ${m.total_pnl:,.2f}")
            print(f"   账户价值: ${m.account_value:,.2f}")
            print(f"   最大回撤: {m.max_drawdown:.2f}%")
            print(f"   活跃天数: {m.active_days}")
            print(f"   平均交易规模: ${m.avg_trade_size:,.2f}")
            print()

        # 5. 汇总统计
        print("="*70)
        print("📈 汇总统计")
        print("="*70 + "\n")

        total_trades = sum(m.total_trades for m in all_metrics)
        avg_win_rate = sum(m.win_rate for m in all_metrics) / len(all_metrics)
        profitable_count = sum(1 for m in all_metrics if m.total_pnl > 0)

        print(f"总地址数: {len(all_metrics)}")
        print(f"总交易数: {total_trades:,}")
        print(f"平均胜率: {avg_win_rate:.2f}%")
        print(f"盈利地址: {profitable_count} ({profitable_count/len(all_metrics)*100:.1f}%)")
        print(f"亏损地址: {len(all_metrics) - profitable_count}")

        print(f"\n总PNL: ${sum(m.total_pnl for m in all_metrics):,.2f}")
        print(f"总账户价值: ${sum(m.account_value for m in all_metrics):,.2f}")

    finally:
        await store.close()

    print(f"\n{'='*70}")
    print("✨ 测试完成！")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    asyncio.run(main())

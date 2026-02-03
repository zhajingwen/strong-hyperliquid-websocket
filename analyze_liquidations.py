#!/usr/bin/env python3
"""
清算记录详细分析
从 fills 中提取并分析所有清算记录
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store


async def analyze_liquidations(address: str):
    """分析清算记录"""

    print("=" * 80)
    print("🔍 清算记录详细分析")
    print("=" * 80)

    # 初始化
    store = get_store()
    await store.connect()

    client = HyperliquidAPIClient(
        store=store,
        max_concurrent=5,
        rate_limit=10.0
    )

    print(f"\n分析地址: {address}")
    print("-" * 80)

    # 获取所有交易记录
    print("\n【步骤1】获取交易记录")
    try:
        fills = await client.get_user_fills(address, use_cache=False)
        print(f"  获取 {len(fills)} 条交易记录")

        if not fills:
            print(f"  ⚠️  无交易记录")
            await store.close()
            return

        # 按时间排序
        fills_sorted = sorted(fills, key=lambda x: x['time'])

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        await store.close()
        return

    # 提取清算记录
    print("\n【步骤2】提取清算记录")

    liquidations = [f for f in fills_sorted if f.get('liquidation', False)]
    non_liquidations = [f for f in fills_sorted if not f.get('liquidation', False)]

    print(f"\n  清算交易: {len(liquidations)} 笔")
    print(f"  普通交易: {len(non_liquidations)} 笔")

    if not liquidations:
        print(f"\n  ✅ 恭喜！没有被清算的记录")
        await store.close()
        return

    # 详细展示清算记录
    print(f"\n  {'━' * 76}")
    print(f"  🚨 清算记录详情")
    print(f"  {'━' * 76}")

    total_liquidation_loss = 0.0
    total_liquidation_fee = 0.0

    for i, liq in enumerate(liquidations, 1):
        dt = datetime.fromtimestamp(liq['time'] / 1000)
        coin = liq.get('coin', 'N/A')
        side = '买入(B)' if liq.get('side') == 'B' else '卖出(A)'
        px = float(liq.get('px', 0))
        sz = float(liq.get('sz', 0))
        closed_pnl = float(liq.get('closedPnl', 0))
        fee = float(liq.get('fee', 0))
        dir_str = liq.get('dir', 'N/A')

        total_liquidation_loss += closed_pnl
        total_liquidation_fee += fee

        print(f"\n  ┌─ 清算 #{i} ─────────────────────────────────────────────")
        print(f"  │")
        print(f"  │ ⏰ 时间:       {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  │ 💰 币种:       {coin}")
        print(f"  │ 📊 方向:       {dir_str}")
        print(f"  │ 💵 价格:       ${px:,.2f}")
        print(f"  │ 📦 数量:       {abs(sz):.6f}")
        print(f"  │ 💸 成交额:     ${px * abs(sz):,.2f}")
        print(f"  │")
        print(f"  │ 💔 平仓盈亏:   ${closed_pnl:,.2f}")
        print(f"  │ 🔖 手续费:     ${fee:,.2f}")
        print(f"  │ 📉 净损失:     ${closed_pnl - fee:,.2f}")
        print(f"  │")
        print(f"  │ 🔍 完整数据:")

        # 打印所有字段
        for key in sorted(liq.keys()):
            if key not in ['time', 'coin', 'side', 'px', 'sz', 'closedPnl', 'fee', 'dir']:
                value = liq[key]
                print(f"  │    {key:20s}: {value}")

        print(f"  └────────────────────────────────────────────────────────")

    # 统计
    print(f"\n  {'━' * 76}")
    print(f"  📊 清算统计")
    print(f"  {'━' * 76}")
    print(f"\n  清算次数:       {len(liquidations)} 次")
    print(f"  平仓损失总计:   ${total_liquidation_loss:,.2f}")
    print(f"  手续费总计:     ${total_liquidation_fee:,.2f}")
    print(f"  净损失总计:     ${total_liquidation_loss - total_liquidation_fee:,.2f}")

    # 分析清算时间间隔
    if len(liquidations) > 1:
        print(f"\n  {'━' * 76}")
        print(f"  ⏱️  清算时间间隔分析")
        print(f"  {'━' * 76}")

        for i in range(1, len(liquidations)):
            prev_time = liquidations[i-1]['time']
            curr_time = liquidations[i]['time']
            interval_ms = curr_time - prev_time
            interval_min = interval_ms / (1000 * 60)
            interval_hours = interval_min / 60

            prev_dt = datetime.fromtimestamp(prev_time / 1000)
            curr_dt = datetime.fromtimestamp(curr_time / 1000)

            print(f"\n  清算 #{i} → 清算 #{i+1}:")
            print(f"    {prev_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"    → {curr_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"    间隔: {interval_min:.1f} 分钟 ({interval_hours:.2f} 小时)")

            if interval_min < 120:  # 2小时内
                print(f"    ⚠️  短时间内连续清算！风险很高！")

    # 对比：清算 vs 非清算交易
    print(f"\n  {'━' * 76}")
    print(f"  📈 对比：清算 vs 普通交易")
    print(f"  {'━' * 76}")

    # 计算普通交易的盈亏
    normal_pnl = sum(float(f.get('closedPnl', 0)) for f in non_liquidations)
    normal_fee = sum(float(f.get('fee', 0)) for f in non_liquidations)

    print(f"\n  【普通交易】")
    print(f"    交易次数:   {len(non_liquidations)} 笔")
    print(f"    成交盈亏:   ${normal_pnl:,.2f}")
    print(f"    手续费:     ${normal_fee:,.2f}")
    print(f"    净盈亏:     ${normal_pnl - normal_fee:,.2f}")

    print(f"\n  【清算交易】")
    print(f"    清算次数:   {len(liquidations)} 次")
    print(f"    清算损失:   ${total_liquidation_loss:,.2f}")
    print(f"    手续费:     ${total_liquidation_fee:,.2f}")
    print(f"    净损失:     ${total_liquidation_loss - total_liquidation_fee:,.2f}")

    print(f"\n  【总计】")
    total_pnl = normal_pnl + total_liquidation_loss
    total_fee = normal_fee + total_liquidation_fee
    print(f"    总盈亏:     ${total_pnl:,.2f}")
    print(f"    总手续费:   ${total_fee:,.2f}")
    print(f"    净盈亏:     ${total_pnl - total_fee:,.2f}")

    # 计算清算损失占比
    if normal_pnl > 0:
        loss_ratio = abs(total_liquidation_loss) / normal_pnl * 100
        print(f"\n  ⚠️  清算损失占普通交易盈利的 {loss_ratio:.1f}%")

        if loss_ratio > 50:
            print(f"     🚨 清算损失过大！建议降低杠杆，设置止损")
        elif loss_ratio > 20:
            print(f"     ⚠️  清算损失较高，需要改进风控")

    # 分析清算时的市场情况
    print(f"\n  {'━' * 76}")
    print(f"  🌍 清算时的市场情况（查看附近交易）")
    print(f"  {'━' * 76}")

    for i, liq in enumerate(liquidations, 1):
        liq_time = liq['time']
        liq_dt = datetime.fromtimestamp(liq_time / 1000)

        # 找出清算前后 30 分钟的交易
        nearby_fills = [
            f for f in fills_sorted
            if abs(f['time'] - liq_time) < 30 * 60 * 1000  # 30分钟
        ]

        if len(nearby_fills) > 1:
            print(f"\n  清算 #{i} 时间: {liq_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  前后30分钟内的交易 ({len(nearby_fills)} 笔):")
            print(f"  ┌─────────────────────────────────────────────────────────")

            for nf in sorted(nearby_fills, key=lambda x: x['time']):
                nf_dt = datetime.fromtimestamp(nf['time'] / 1000)
                nf_coin = nf.get('coin', 'N/A')
                nf_side = 'B' if nf.get('side') == 'B' else 'A'
                nf_sz = float(nf.get('sz', 0))
                nf_pnl = float(nf.get('closedPnl', 0))
                nf_is_liq = '🚨' if nf.get('liquidation', False) else '  '

                print(f"  │ {nf_is_liq} {nf_dt.strftime('%H:%M:%S')}  "
                      f"{nf_coin:>6}  {nf_side}  {abs(nf_sz):>10.6f}  "
                      f"PNL: ${nf_pnl:>10,.2f}")

            print(f"  └─────────────────────────────────────────────────────────")

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 分析完成")
    print("=" * 80)


if __name__ == '__main__':
    import sys

    # 默认测试地址
    default_address = "0xde786a32f80731923d6297c14ef43ca1c8fd4b44"

    if len(sys.argv) > 1:
        address = sys.argv[1]
    else:
        address = input(f"请输入地址 (默认={default_address}): ").strip() or default_address

    asyncio.run(analyze_liquidations(address))

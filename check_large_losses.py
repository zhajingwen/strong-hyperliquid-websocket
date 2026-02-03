#!/usr/bin/env python3
"""
检查大额亏损交易的详细信息
分析是否是清算，以及清算费用
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store


async def check_large_losses(address: str):
    """检查大额亏损交易"""

    print("=" * 80)
    print("🔍 大额亏损交易详细分析")
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

    # 获取成交记录
    print("\n【步骤1】获取所有成交记录")
    try:
        fills = await client.get_user_fills(
            address,
            use_cache=False
        )

        print(f"  获取 {len(fills)} 条成交记录")

        # 按时间排序
        fills_sorted = sorted(fills, key=lambda x: x['time'])

        # 找出所有大额亏损（< -$50）
        large_losses = [f for f in fills_sorted if float(f.get('closedPnl', 0)) < -50]

        print(f"\n  发现 {len(large_losses)} 笔大额亏损交易 (PNL < -$50)")

        # 详细分析每笔大额亏损
        for i, fill in enumerate(large_losses, 1):
            print(f"\n  {'━' * 70}")
            print(f"  📉 大额亏损交易 #{i}")
            print(f"  {'━' * 70}")

            dt = datetime.fromtimestamp(fill['time'] / 1000)
            coin = fill.get('coin', 'N/A')
            side = '买入(B)' if fill.get('side') == 'B' else '卖出(A)'
            px = float(fill.get('px', 0))
            sz = float(fill.get('sz', 0))
            closed_pnl = float(fill.get('closedPnl', 0))
            fee = float(fill.get('fee', 0))
            start_position = float(fill.get('startPosition', 0))
            dir_str = fill.get('dir', 'N/A')
            crossed = fill.get('crossed', False)
            liquidation = fill.get('liquidation', False)
            hash_val = fill.get('hash', 'N/A')

            print(f"\n     时间:     {dt.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"     币种:     {coin}")
            print(f"     方向:     {side}")
            print(f"     价格:     ${px:,.2f}")
            print(f"     数量:     {abs(sz):.4f}")
            print(f"     成交额:   ${px * abs(sz):,.2f}")
            print(f"\n     持仓变化:")
            print(f"       开始持仓: {start_position:.4f}")
            print(f"       变化量:   {sz:.4f}")
            print(f"       结束持仓: {start_position + sz:.4f}")
            print(f"\n     盈亏详情:")
            print(f"       平仓盈亏: ${closed_pnl:,.2f}")
            print(f"       手续费:   ${fee:,.2f}")
            print(f"       净盈亏:   ${closed_pnl - fee:,.2f}")
            print(f"\n     交易标记:")
            print(f"       方向标记: {dir_str}")
            print(f"       是否强平: {'✅ 是' if liquidation else '❌ 否'}")
            print(f"       交叉保证金: {'是' if crossed else '否'}")
            print(f"       交易哈希: {hash_val[:30]}...")

            # 打印完整的 fill 信息
            print(f"\n     完整数据:")
            for key, value in sorted(fill.items()):
                if key not in ['time', 'coin', 'side', 'px', 'sz', 'closedPnl',
                              'fee', 'startPosition', 'dir', 'crossed', 'liquidation', 'hash']:
                    print(f"       {key:20s}: {value}")

        # 统计总亏损
        total_large_losses = sum(float(f.get('closedPnl', 0)) for f in large_losses)
        total_large_fees = sum(float(f.get('fee', 0)) for f in large_losses)

        print(f"\n  {'━' * 70}")
        print(f"  📊 大额亏损统计")
        print(f"  {'━' * 70}")
        print(f"\n     平仓亏损总计: ${total_large_losses:,.2f}")
        print(f"     手续费总计:   ${total_large_fees:,.2f}")
        print(f"     净亏损总计:   ${total_large_losses - total_large_fees:,.2f}")

        # 检查是否有清算标记
        liquidations = [f for f in large_losses if f.get('liquidation', False)]
        if liquidations:
            print(f"\n     ⚠️  其中 {len(liquidations)} 笔被标记为强制清算")
        else:
            print(f"\n     ℹ️  没有被标记为强制清算的交易")

        # 分析时间窗口
        if len(large_losses) >= 2:
            first_time = large_losses[0]['time']
            last_time = large_losses[-1]['time']
            time_diff = (last_time - first_time) / 1000 / 60  # 分钟

            print(f"\n     时间跨度: {time_diff:.1f} 分钟")

            if time_diff < 120:  # 2小时内
                print(f"     ⚠️  短时间内发生多笔大额亏损，可能是：")
                print(f"        - 爆仓/强平")
                print(f"        - 市场剧烈波动")
                print(f"        - 止损触发")

        # 查看附近的其他交易
        print(f"\n  {'━' * 70}")
        print(f"  🔎 查看附近的其他交易（前后各5笔）")
        print(f"  {'━' * 70}")

        for loss_fill in large_losses:
            loss_time = loss_fill['time']
            loss_dt = datetime.fromtimestamp(loss_time / 1000)

            # 找出时间前后5笔交易
            nearby_fills = [
                f for f in fills_sorted
                if abs(f['time'] - loss_time) < 5 * 60 * 1000  # 5分钟内
            ]

            if len(nearby_fills) > 1:
                print(f"\n     大额亏损时间: {loss_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"     附近5分钟内的交易 ({len(nearby_fills)} 笔):")

                for nf in sorted(nearby_fills, key=lambda x: x['time']):
                    nf_dt = datetime.fromtimestamp(nf['time'] / 1000)
                    nf_coin = nf.get('coin', 'N/A')
                    nf_side = 'B' if nf.get('side') == 'B' else 'A'
                    nf_sz = float(nf.get('sz', 0))
                    nf_pnl = float(nf.get('closedPnl', 0))

                    marker = "👉" if nf['time'] == loss_time else "  "
                    print(f"       {marker} {nf_dt.strftime('%H:%M:%S')}  {nf_coin:>6}  {nf_side}  {abs(nf_sz):>8.4f}  PNL: ${nf_pnl:>10,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()

    # 获取账本记录，查看是否有清算相关记录
    print(f"\n  {'━' * 70}")
    print(f"  📋 检查账本记录（查找清算费用）")
    print(f"  {'━' * 70}")

    try:
        ledger_data = await client.get_user_ledger(
            address,
            start_time=0,
            use_cache=False
        )

        print(f"\n  获取 {len(ledger_data)} 条账本记录")

        # 查找可能的清算费用
        liquidation_records = []
        for record in ledger_data:
            delta = record.get('delta', {})
            record_type = delta.get('type', '')

            # 可能的清算相关类型
            if 'liquidat' in record_type.lower() or 'internalTransfer' in record_type:
                liquidation_records.append(record)

        if liquidation_records:
            print(f"\n  ⚠️  发现 {len(liquidation_records)} 条可能相关的记录:")
            for lr in liquidation_records:
                dt = datetime.fromtimestamp(lr['time'] / 1000)
                print(f"\n     时间: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"     Delta: {lr['delta']}")
        else:
            print(f"\n  ℹ️  没有发现明确的清算费用记录")

        # 按类型分组所有记录
        record_types = {}
        for record in ledger_data:
            record_type = record['delta'].get('type', 'unknown')
            if record_type not in record_types:
                record_types[record_type] = []
            record_types[record_type].append(record)

        print(f"\n  所有账本记录类型:")
        for rtype, records in sorted(record_types.items()):
            print(f"     {rtype:30s}: {len(records):3d} 条")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")

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

    asyncio.run(check_large_losses(address))

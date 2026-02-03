#!/usr/bin/env python3
"""
详细时间线分析
分析每笔交易和转账的时间顺序，找出盈亏转移的真相
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store


async def analyze_timeline(address: str):
    """详细时间线分析"""

    print("=" * 80)
    print("🔍 详细时间线分析")
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

    # 获取所有数据
    print("\n【数据获取】")

    # 账户状态
    state = client.info.user_state(address)
    account_value = float(state['marginSummary']['accountValue'])
    total_unrealized_pnl = 0.0
    if state.get('assetPositions'):
        for asset_pos in state['assetPositions']:
            total_unrealized_pnl += float(asset_pos['position'].get('unrealizedPnl', 0))

    print(f"  当前账户价值: ${account_value:,.2f}")
    print(f"  未实现盈亏: ${total_unrealized_pnl:,.2f}")

    # Ledger
    ledger_data = await client.get_user_ledger(address, start_time=0, use_cache=False)
    print(f"  Ledger 记录: {len(ledger_data)} 条")

    # Fills
    fills = await client.get_user_fills(address, use_cache=False)
    print(f"  Fills 记录: {len(fills)} 条")

    # Funding
    funding_data = await client.get_user_funding(address, start_time=0)
    total_funding = sum(float(r.get('delta', {}).get('usdc', 0)) for r in funding_data)
    print(f"  资金费率: ${total_funding:,.2f}")

    # 构建完整时间线
    print(f"\n{'=' * 80}")
    print("📅 完整时间线（按时间排序）")
    print("=" * 80)

    timeline = []

    # 添加 deposit/withdraw
    for record in ledger_data:
        record_type = record['delta'].get('type', 'unknown')
        if record_type in ['deposit', 'withdraw']:
            amount = float(record['delta'].get('usdc', 0))
            timeline.append({
                'time': record['time'],
                'type': record_type,
                'amount': amount,
                'record': record
            })

    # 添加转账
    for record in ledger_data:
        record_type = record['delta'].get('type', 'unknown')
        if record_type == 'send':
            delta = record['delta']
            amount = float(delta.get('amount', 0))
            user = delta.get('user', '')
            dest = delta.get('destination', '')

            # 判断方向
            is_in = dest.lower().startswith(address.lower()[:20])
            is_out = user.lower().startswith(address.lower()[:20])

            # 判断是否是外部转账
            is_external = (
                (is_in and not user.lower().startswith(address.lower()[:20])) or
                (is_out and not dest.lower().startswith(address.lower()[:20]))
            )

            timeline.append({
                'time': record['time'],
                'type': 'transfer_in' if is_in else 'transfer_out',
                'amount': amount if is_in else -amount,
                'is_external': is_external,
                'from': user[:20] + '...',
                'to': dest[:20] + '...',
                'record': record
            })

    # 添加交易
    for fill in fills:
        closed_pnl = float(fill.get('closedPnl', 0))
        fee = float(fill.get('fee', 0))
        is_liquidation = fill.get('liquidation', False)

        timeline.append({
            'time': fill['time'],
            'type': 'liquidation' if is_liquidation else 'trade',
            'coin': fill.get('coin', 'N/A'),
            'side': fill.get('side', 'N/A'),
            'px': float(fill.get('px', 0)),
            'sz': float(fill.get('sz', 0)),
            'closed_pnl': closed_pnl,
            'fee': fee,
            'net_pnl': closed_pnl - fee,
            'record': fill
        })

    # 排序
    timeline.sort(key=lambda x: x['time'])

    # 打印时间线
    running_capital = 0.0
    running_realized_pnl = 0.0
    external_transfers_total = 0.0

    print(f"\n{'时间':<20} {'类型':<15} {'金额/盈亏':<15} {'累计本金':<15} {'累计盈亏':<15}")
    print("-" * 80)

    for event in timeline:
        dt = datetime.fromtimestamp(event['time'] / 1000)
        time_str = dt.strftime('%Y-%m-%d %H:%M:%S')

        if event['type'] == 'deposit':
            running_capital += event['amount']
            type_str = '💵 充值'
            amount_str = f"${event['amount']:,.2f}"

        elif event['type'] == 'withdraw':
            running_capital -= event['amount']
            type_str = '💸 提现'
            amount_str = f"-${event['amount']:,.2f}"

        elif event['type'] in ['transfer_in', 'transfer_out']:
            type_str = '🔄 转账'
            if event['is_external']:
                type_str = '⚠️  外部转账'
                if event['type'] == 'transfer_in':
                    external_transfers_total += event['amount']
                    amount_str = f"+${event['amount']:,.2f} (外部)"
                else:
                    external_transfers_total -= event['amount']
                    amount_str = f"-${abs(event['amount']):,.2f} (外部)"
            else:
                amount_str = f"${event['amount']:,.2f} (内部)"

        elif event['type'] == 'trade':
            running_realized_pnl += event['net_pnl']
            type_str = f"📊 {event['coin']}"
            amount_str = f"PNL ${event['net_pnl']:,.2f}"

        elif event['type'] == 'liquidation':
            running_realized_pnl += event['net_pnl']
            type_str = f"🚨 清算 {event['coin']}"
            amount_str = f"PNL ${event['net_pnl']:,.2f}"

        print(f"{time_str:<20} {type_str:<15} {amount_str:<15} ${running_capital:>12,.2f} ${running_realized_pnl:>12,.2f}")

    # 统计分析
    print(f"\n{'=' * 80}")
    print("📊 统计分析")
    print("=" * 80)

    # 计算真实本金
    true_capital = sum(
        e['amount'] for e in timeline
        if e['type'] in ['deposit', 'withdraw']
    )

    # 计算外部转账
    print(f"\n【外部转账】")
    print(f"  外部转入总额: ${external_transfers_total:,.2f}")

    # 计算总已实现盈亏
    total_realized_pnl_from_fills = sum(
        e['net_pnl'] for e in timeline
        if e['type'] in ['trade', 'liquidation']
    ) + total_funding

    print(f"\n【盈亏分析】")
    print(f"  真实本金: ${true_capital:,.2f}")
    print(f"  Fills 总已实现盈亏: ${total_realized_pnl_from_fills:,.2f}")
    print(f"  未实现盈亏: ${total_unrealized_pnl:,.2f}")
    print(f"  理论账户价值:")
    print(f"    = 真实本金 + 已实现盈亏 + 未实现盈亏")
    theoretical_value_1 = true_capital + total_realized_pnl_from_fills + total_unrealized_pnl
    print(f"    = ${true_capital:,.2f} + ${total_realized_pnl_from_fills:,.2f} + ${total_unrealized_pnl:,.2f}")
    print(f"    = ${theoretical_value_1:,.2f}")
    print(f"  实际账户价值: ${account_value:,.2f}")
    print(f"  差异: ${theoretical_value_1 - account_value:,.2f}")

    # 关键分析：账户价值反推已实现盈亏
    print(f"\n{'=' * 80}")
    print("🎯 关键分析：反推已实现盈亏")
    print("=" * 80)

    inferred_realized = account_value - true_capital - total_unrealized_pnl
    print(f"\n  从账户价值反推的已实现盈亏:")
    print(f"    = 账户价值 - 真实本金 - 未实现盈亏")
    print(f"    = ${account_value:,.2f} - ${true_capital:,.2f} - ${total_unrealized_pnl:,.2f}")
    print(f"    = ${inferred_realized:,.2f}")

    print(f"\n  Fills API 返回的已实现盈亏: ${total_realized_pnl_from_fills:,.2f}")
    print(f"  差异: ${total_realized_pnl_from_fills - inferred_realized:,.2f}")
    print(f"  外部转账金额: ${external_transfers_total:,.2f}")

    # 最终结论
    print(f"\n{'=' * 80}")
    print("💡 最终结论")
    print("=" * 80)

    diff = total_realized_pnl_from_fills - inferred_realized

    if abs(diff - external_transfers_total) < 1:
        print(f"\n  ✅ 发现：差异（${diff:,.2f}）≈ 外部转账（${external_transfers_total:,.2f}）")
        print(f"\n  结论：")
        print(f"    1. 本账户的真实已实现盈亏 = ${inferred_realized:,.2f}")
        print(f"    2. Fills API 返回的额外盈亏 = ${diff:,.2f}")
        print(f"    3. 这${diff:,.2f}是从其他账户（0x6b9e...）转入的盈利")
        print(f"    4. Fills API 可能包含了与本地址相关的所有交易")
        print(f"       （包括在其他账户产生但与本地址有关联的交易）")
    else:
        print(f"\n  差异（${diff:,.2f}）与外部转账（${external_transfers_total:,.2f}）")
        print(f"  差值：${abs(diff - external_transfers_total):,.2f}")
        print(f"\n  可能原因：")
        print(f"    1. Ledger 数据不完整")
        print(f"    2. 存在其他未记录的资金流动")
        print(f"    3. API 数据有延迟或不一致")

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

    asyncio.run(analyze_timeline(address))

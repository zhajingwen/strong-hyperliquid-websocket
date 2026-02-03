#!/usr/bin/env python3
"""
深度调试 PNL 差异问题
分析转账记录的性质，找出 $624 差异的根本原因
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


async def debug_pnl_discrepancy(address: str):
    """深度调试 PNL 差异"""

    print("=" * 80)
    print("🔍 PNL 差异深度调试")
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

    # ============================================================
    # 1. 获取当前账户状态
    # ============================================================
    print("\n【步骤1】获取当前账户状态")
    try:
        state = client.info.user_state(address)
        account_value = float(state['marginSummary']['accountValue'])

        total_unrealized_pnl = 0.0
        if state.get('assetPositions'):
            for asset_pos in state['assetPositions']:
                pos = asset_pos['position']
                pnl = float(pos.get('unrealizedPnl', 0))
                total_unrealized_pnl += pnl

        print(f"  账户总价值: ${account_value:,.2f}")
        print(f"  未实现盈亏: ${total_unrealized_pnl:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        await store.close()
        return

    # ============================================================
    # 2. 详细分析出入金记录
    # ============================================================
    print("\n【步骤2】详细分析出入金记录")
    try:
        ledger_data = await client.get_user_ledger(
            address,
            start_time=0,
            use_cache=False
        )

        print(f"  获取 {len(ledger_data)} 条账本记录")

        # 分类统计
        deposits = []
        withdrawals = []
        transfers_in = []
        transfers_out = []
        other_records = []

        for record in ledger_data:
            delta = record['delta']
            record_type = delta['type']
            timestamp = record['time']
            dt = datetime.fromtimestamp(timestamp / 1000)

            if record_type == 'deposit':
                amount = float(delta.get('usdc', 0))
                deposits.append({
                    'time': timestamp,
                    'dt': dt,
                    'amount': amount,
                    'hash': record.get('hash', 'N/A')
                })

            elif record_type == 'withdraw':
                amount = float(delta.get('usdc', 0))
                withdrawals.append({
                    'time': timestamp,
                    'dt': dt,
                    'amount': amount,
                    'hash': record.get('hash', 'N/A')
                })

            elif record_type == 'send':
                amount = float(delta.get('amount', 0))
                user = delta.get('user', '').lower()
                destination = delta.get('destination', '').lower()

                if destination == address.lower() and user != address.lower():
                    transfers_in.append({
                        'time': timestamp,
                        'dt': dt,
                        'amount': amount,
                        'from': user,
                        'type': 'send',
                        'hash': record.get('hash', 'N/A'),
                        'raw_delta': delta
                    })
                elif user == address.lower() and destination != address.lower():
                    transfers_out.append({
                        'time': timestamp,
                        'dt': dt,
                        'amount': amount,
                        'to': destination,
                        'type': 'send',
                        'hash': record.get('hash', 'N/A'),
                        'raw_delta': delta
                    })

            elif record_type == 'subAccountTransfer':
                amount = float(delta.get('usdc', 0))
                user = delta.get('user', '').lower()
                destination = delta.get('destination', '').lower()

                if destination == address.lower():
                    transfers_in.append({
                        'time': timestamp,
                        'dt': dt,
                        'amount': amount,
                        'from': user,
                        'type': 'subAccountTransfer',
                        'hash': record.get('hash', 'N/A'),
                        'raw_delta': delta
                    })
                elif user == address.lower():
                    transfers_out.append({
                        'time': timestamp,
                        'dt': dt,
                        'amount': amount,
                        'to': destination,
                        'type': 'subAccountTransfer',
                        'hash': record.get('hash', 'N/A'),
                        'raw_delta': delta
                    })
            else:
                other_records.append(record)

        # 打印详细的转账记录
        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  💰 充值记录: {len(deposits)} 笔")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        total_deposits = 0.0
        for d in sorted(deposits, key=lambda x: x['time']):
            total_deposits += d['amount']
            print(f"     {d['dt'].strftime('%Y-%m-%d %H:%M:%S')}  ${d['amount']:>10,.2f}")
        print(f"     {'─' * 45}")
        print(f"     总计: ${total_deposits:>10,.2f}")

        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  💸 提现记录: {len(withdrawals)} 笔")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        total_withdrawals = 0.0
        for w in sorted(withdrawals, key=lambda x: x['time']):
            total_withdrawals += w['amount']
            print(f"     {w['dt'].strftime('%Y-%m-%d %H:%M:%S')}  ${w['amount']:>10,.2f}")
        if withdrawals:
            print(f"     {'─' * 45}")
            print(f"     总计: ${total_withdrawals:>10,.2f}")

        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📥 转入记录: {len(transfers_in)} 笔 ⚠️ 可能包含交易盈亏")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        total_transfers_in = 0.0
        for t in sorted(transfers_in, key=lambda x: x['time']):
            total_transfers_in += t['amount']
            from_addr = t.get('from', 'N/A')
            print(f"     {t['dt'].strftime('%Y-%m-%d %H:%M:%S')}  ${t['amount']:>10,.2f}  from {from_addr[:20]}...")
            print(f"        类型: {t['type']}")
            print(f"        Hash: {t['hash'][:20]}...")
            # 打印完整的 delta 信息
            print(f"        Delta: {t['raw_delta']}")
            print()
        if transfers_in:
            print(f"     {'─' * 45}")
            print(f"     总计: ${total_transfers_in:>10,.2f}")

        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📤 转出记录: {len(transfers_out)} 笔")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        total_transfers_out = 0.0
        for t in sorted(transfers_out, key=lambda x: x['time']):
            total_transfers_out += t['amount']
            to_addr = t.get('to', 'N/A')
            print(f"     {t['dt'].strftime('%Y-%m-%d %H:%M:%S')}  ${t['amount']:>10,.2f}  to {to_addr[:20]}...")
            print(f"        类型: {t['type']}")
            print(f"        Hash: {t['hash'][:20]}...")
            print(f"        Delta: {t['raw_delta']}")
            print()
        if transfers_out:
            print(f"     {'─' * 45}")
            print(f"     总计: ${total_transfers_out:>10,.2f}")

        # 其他类型记录
        if other_records:
            print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f"  📋 其他记录: {len(other_records)} 条")
            print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            record_types = defaultdict(list)
            for r in other_records:
                record_types[r['delta']['type']].append(r)

            for rtype, records in record_types.items():
                print(f"\n     类型: {rtype} ({len(records)} 条)")
                for r in records[:5]:  # 只显示前5条
                    dt = datetime.fromtimestamp(r['time'] / 1000)
                    print(f"       {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"       Delta: {r['delta']}")
                if len(records) > 5:
                    print(f"       ... 还有 {len(records) - 5} 条")

        # 计算净流入（两种方法）
        net_deposits = total_deposits - total_withdrawals
        net_transfers = total_transfers_in - total_transfers_out

        method1_net_inflow = net_deposits + net_transfers
        method2_net_inflow = net_deposits  # 不包含转账

        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📊 净流入计算")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"\n  方法1: 包含所有转账")
        print(f"    充值净额: ${net_deposits:,.2f}")
        print(f"    转账净额: ${net_transfers:,.2f}")
        print(f"    总计:     ${method1_net_inflow:,.2f}")

        print(f"\n  方法2: 仅包含充值/提现（假设转账是盈亏转移）")
        print(f"    充值净额: ${net_deposits:,.2f}")
        print(f"    总计:     ${method2_net_inflow:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        await store.close()
        return

    # ============================================================
    # 3. 获取成交记录
    # ============================================================
    print("\n【步骤3】分析成交记录")
    try:
        fills = await client.get_user_fills(
            address,
            use_cache=False
        )

        print(f"  获取 {len(fills)} 条成交记录")

        # 按时间排序
        fills_sorted = sorted(fills, key=lambda x: x['time'])

        # 统计
        fills_realized_pnl = sum(float(f.get('closedPnl', 0)) for f in fills)
        total_fees = sum(float(f.get('fee', 0)) for f in fills)

        print(f"\n  成交盈亏总计: ${fills_realized_pnl:,.2f}")
        print(f"  手续费总计:   ${total_fees:,.2f}")
        print(f"  净盈亏:       ${fills_realized_pnl - total_fees:,.2f}")

        # 显示时间范围
        if fills_sorted:
            first_fill_time = fills_sorted[0]['time']
            last_fill_time = fills_sorted[-1]['time']
            first_dt = datetime.fromtimestamp(first_fill_time / 1000)
            last_dt = datetime.fromtimestamp(last_fill_time / 1000)

            print(f"\n  时间范围:")
            print(f"    首次交易: {first_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"    最后交易: {last_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        # 检查是否有负的 closedPnl 很大的记录（可能是清算）
        large_losses = [f for f in fills if float(f.get('closedPnl', 0)) < -50]
        if large_losses:
            print(f"\n  ⚠️  发现 {len(large_losses)} 笔大额亏损交易 (>$50):")
            for f in sorted(large_losses, key=lambda x: float(x.get('closedPnl', 0))):
                dt = datetime.fromtimestamp(f['time'] / 1000)
                pnl = float(f.get('closedPnl', 0))
                coin = f.get('coin', 'N/A')
                side = '买入' if f.get('side') == 'B' else '卖出'
                print(f"    {dt.strftime('%Y-%m-%d %H:%M:%S')}  {coin:>6}  {side}  PNL: ${pnl:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        fills_realized_pnl = 0.0
        total_fees = 0.0

    # ============================================================
    # 4. 获取资金费率
    # ============================================================
    print("\n【步骤4】分析资金费率")
    try:
        funding_data = await client.get_user_funding(
            address,
            start_time=0
        )

        print(f"  获取 {len(funding_data)} 条资金费率记录")

        total_funding = sum(float(r.get('delta', {}).get('usdc', 0)) for r in funding_data)

        print(f"  资金费率总计: ${total_funding:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        total_funding = 0.0

    # ============================================================
    # 5. 对比分析
    # ============================================================
    print("\n" + "=" * 80)
    print("🎯 对比分析")
    print("=" * 80)

    fills_net_pnl = fills_realized_pnl - total_fees + total_funding

    # 方法1：包含所有转账
    method1_total_trading_pnl = account_value - method1_net_inflow
    method1_realized_pnl = method1_total_trading_pnl - total_unrealized_pnl
    method1_diff = method1_realized_pnl - fills_net_pnl

    print(f"\n【场景1】假设所有转账都是外部资金注入")
    print(f"  净流入:         ${method1_net_inflow:,.2f}")
    print(f"  推算已实现盈亏: ${method1_realized_pnl:,.2f}")
    print(f"  成交盈亏:       ${fills_net_pnl:,.2f}")
    print(f"  差异:           ${method1_diff:,.2f}")

    # 方法2：不包含转账
    method2_total_trading_pnl = account_value - method2_net_inflow
    method2_realized_pnl = method2_total_trading_pnl - total_unrealized_pnl
    method2_diff = method2_realized_pnl - fills_net_pnl

    print(f"\n【场景2】假设转账是盈亏转移（不算净流入）")
    print(f"  净流入:         ${method2_net_inflow:,.2f}")
    print(f"  推算已实现盈亏: ${method2_realized_pnl:,.2f}")
    print(f"  成交盈亏:       ${fills_net_pnl:,.2f}")
    print(f"  差异:           ${method2_diff:,.2f}")

    # 理论账户价值验证
    print(f"\n" + "=" * 80)
    print("💡 理论账户价值验证")
    print("=" * 80)

    theoretical1 = method1_net_inflow + fills_net_pnl + total_unrealized_pnl
    theoretical2 = method2_net_inflow + fills_net_pnl + total_unrealized_pnl

    print(f"\n  场景1 理论价值: ${theoretical1:,.2f}")
    print(f"  场景2 理论价值: ${theoretical2:,.2f}")
    print(f"  实际账户价值:   ${account_value:,.2f}")
    print(f"\n  场景1 差异: ${account_value - theoretical1:,.2f}")
    print(f"  场景2 差异: ${account_value - theoretical2:,.2f}")

    # 判断哪个场景更合理
    print(f"\n" + "=" * 80)
    print("📝 结论")
    print("=" * 80)

    if abs(method1_diff) < abs(method2_diff):
        print(f"\n  ✅ 场景1 更合理（差异 ${abs(method1_diff):,.2f}）")
        print(f"     转账可能是真实的外部资金注入")
        if abs(method1_diff) > 10:
            print(f"     ⚠️  但仍有 ${abs(method1_diff):,.2f} 的差异，可能原因：")
            print(f"        - 清算费用")
            print(f"        - 数据不完整")
            print(f"        - 其他未知费用")
    else:
        print(f"\n  ✅ 场景2 更合理（差异 ${abs(method2_diff):,.2f}）")
        print(f"     转账可能是账户间的盈亏转移，不应算作净流入")
        if abs(method2_diff) > 10:
            print(f"     ⚠️  但仍有 ${abs(method2_diff):,.2f} 的差异，可能原因：")
            print(f"        - 清算费用")
            print(f"        - 数据不完整")
            print(f"        - 其他未知费用")

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 调试完成")
    print("=" * 80)


if __name__ == '__main__':
    import sys

    # 默认测试地址
    default_address = "0xde786a32f80731923d6297c14ef43ca1c8fd4b44"

    if len(sys.argv) > 1:
        address = sys.argv[1]
    else:
        address = input(f"请输入地址 (默认={default_address}): ").strip() or default_address

    asyncio.run(debug_pnl_discrepancy(address))

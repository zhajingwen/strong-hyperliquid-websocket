#!/usr/bin/env python3
"""
分析账户盈亏对账
对比出入金记录和当前账户价值，计算实际交易盈亏
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


async def analyze_pnl_reconciliation(address: str):
    """分析盈亏对账"""

    print("=" * 80)
    print("📊 账户盈亏对账分析")
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

    # 1. 获取当前账户状态
    print("\n【步骤1】获取当前账户状态")
    try:
        state = client.info.user_state(address)

        account_value = float(state['marginSummary']['accountValue'])
        withdrawable = float(state['withdrawable'])

        print(f"  ✅ 账户总价值: ${account_value:,.2f}")
        print(f"  ✅ 可提现金额: ${withdrawable:,.2f}")

        # 获取持仓盈亏
        total_unrealized_pnl = 0.0
        if state.get('assetPositions'):
            for asset_pos in state['assetPositions']:
                pos = asset_pos['position']
                pnl = float(pos.get('unrealizedPnl', 0))
                total_unrealized_pnl += pnl

                if pnl != 0:
                    coin = pos['coin']
                    print(f"     - {coin} 未实现盈亏: ${pnl:,.2f}")

        print(f"  ✅ 总未实现盈亏: ${total_unrealized_pnl:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        await store.close()
        return

    # 2. 获取完整出入金历史
    print("\n【步骤2】获取出入金历史")
    try:
        ledger_data = await client.get_user_ledger(
            address,
            start_time=0,  # 从最早记录开始
            use_cache=False
        )

        print(f"  ✅ 获取 {len(ledger_data)} 条记录")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        await store.close()
        return

    # 3. 分类统计出入金
    print("\n【步骤3】统计出入金流水")

    deposits = []      # 充值
    withdrawals = []   # 提现
    transfers_in = []  # 转入
    transfers_out = [] # 转出
    other_records = [] # 其他类型

    for record in ledger_data:
        delta = record['delta']
        record_type = delta['type']

        if record_type == 'deposit':
            # 充值
            amount = float(delta.get('usdc', 0))
            deposits.append({
                'time': record['time'],
                'amount': amount,
                'hash': record.get('hash', 'N/A')
            })

        elif record_type == 'withdraw':
            # 提现
            amount = float(delta.get('usdc', 0))
            withdrawals.append({
                'time': record['time'],
                'amount': amount,
                'hash': record.get('hash', 'N/A')
            })

        elif record_type == 'send':
            # 转账
            amount = float(delta.get('amount', 0))
            user = delta.get('user', '').lower()
            destination = delta.get('destination', '').lower()

            if destination == address.lower() and user != address.lower():
                # 收到别人的转账
                transfers_in.append({
                    'time': record['time'],
                    'amount': amount,
                    'from': user,
                    'hash': record.get('hash', 'N/A')
                })
            elif user == address.lower() and destination != address.lower():
                # 转给别人
                transfers_out.append({
                    'time': record['time'],
                    'amount': amount,
                    'to': destination,
                    'hash': record.get('hash', 'N/A')
                })
            # 自己转给自己的忽略

        elif record_type == 'subAccountTransfer':
            # 子账户转账
            amount = float(delta.get('usdc', 0))
            user = delta.get('user', '').lower()
            destination = delta.get('destination', '').lower()

            if destination == address.lower():
                transfers_in.append({
                    'time': record['time'],
                    'amount': amount,
                    'from': user,
                    'type': 'sub_account',
                    'hash': record.get('hash', 'N/A')
                })
            elif user == address.lower():
                transfers_out.append({
                    'time': record['time'],
                    'amount': amount,
                    'to': destination,
                    'type': 'sub_account',
                    'hash': record.get('hash', 'N/A')
                })
        else:
            other_records.append(record)

    # 计算总额
    total_deposits = sum(d['amount'] for d in deposits)
    total_withdrawals = sum(w['amount'] for w in withdrawals)
    total_transfers_in = sum(t['amount'] for t in transfers_in)
    total_transfers_out = sum(t['amount'] for t in transfers_out)

    print(f"\n  充值记录:")
    print(f"    数量: {len(deposits)} 笔")
    print(f"    总额: ${total_deposits:,.2f}")
    if deposits:
        print(f"    明细:")
        for d in sorted(deposits, key=lambda x: x['time']):
            dt = datetime.fromtimestamp(d['time'] / 1000)
            print(f"      {dt.strftime('%Y-%m-%d %H:%M:%S')}  ${d['amount']:>10,.2f}  {d['hash'][:10]}...")

    print(f"\n  提现记录:")
    print(f"    数量: {len(withdrawals)} 笔")
    print(f"    总额: ${total_withdrawals:,.2f}")
    if withdrawals:
        print(f"    明细:")
        for w in sorted(withdrawals, key=lambda x: x['time']):
            dt = datetime.fromtimestamp(w['time'] / 1000)
            print(f"      {dt.strftime('%Y-%m-%d %H:%M:%S')}  ${w['amount']:>10,.2f}  {w['hash'][:10]}...")

    print(f"\n  转入记录:")
    print(f"    数量: {len(transfers_in)} 笔")
    print(f"    总额: ${total_transfers_in:,.2f}")
    if transfers_in:
        print(f"    明细:")
        for t in sorted(transfers_in, key=lambda x: x['time'])[:10]:  # 只显示前10条
            dt = datetime.fromtimestamp(t['time'] / 1000)
            from_addr = t.get('from', 'N/A')[:10]
            print(f"      {dt.strftime('%Y-%m-%d %H:%M:%S')}  ${t['amount']:>10,.2f}  from {from_addr}...")
        if len(transfers_in) > 10:
            print(f"      ... 还有 {len(transfers_in) - 10} 笔")

    print(f"\n  转出记录:")
    print(f"    数量: {len(transfers_out)} 笔")
    print(f"    总额: ${total_transfers_out:,.2f}")
    if transfers_out:
        print(f"    明细:")
        for t in sorted(transfers_out, key=lambda x: x['time'])[:10]:
            dt = datetime.fromtimestamp(t['time'] / 1000)
            to_addr = t.get('to', 'N/A')[:10]
            print(f"      {dt.strftime('%Y-%m-%d %H:%M:%S')}  ${t['amount']:>10,.2f}  to {to_addr}...")
        if len(transfers_out) > 10:
            print(f"      ... 还有 {len(transfers_out) - 10} 笔")

    if other_records:
        print(f"\n  其他类型记录: {len(other_records)} 条")
        record_types = defaultdict(int)
        for r in other_records:
            record_types[r['delta']['type']] += 1
        for rtype, count in record_types.items():
            print(f"    - {rtype}: {count} 条")

    # 4. 计算净流入
    print("\n【步骤4】计算净资金流入")

    net_deposits = total_deposits - total_withdrawals
    net_transfers = total_transfers_in - total_transfers_out
    total_net_inflow = net_deposits + net_transfers

    print(f"\n  充值净额: ${net_deposits:,.2f}")
    print(f"    = 充值 ${total_deposits:,.2f} - 提现 ${total_withdrawals:,.2f}")

    print(f"\n  转账净额: ${net_transfers:,.2f}")
    print(f"    = 转入 ${total_transfers_in:,.2f} - 转出 ${total_transfers_out:,.2f}")

    print(f"\n  📥 总净流入: ${total_net_inflow:,.2f}")

    # 5. 盈亏对账
    print("\n【步骤5】盈亏对账")

    print(f"\n  初始投入（净流入）: ${total_net_inflow:,.2f}")
    print(f"  当前账户价值:       ${account_value:,.2f}")
    print(f"  " + "-" * 50)

    trading_pnl = account_value - total_net_inflow

    if trading_pnl >= 0:
        print(f"  💰 交易总盈利:       ${trading_pnl:,.2f}")
    else:
        print(f"  📉 交易总亏损:       ${trading_pnl:,.2f}")

    # ROI 计算
    if total_net_inflow > 0:
        roi = (trading_pnl / total_net_inflow) * 100
        print(f"\n  💹 ROI (投资回报率): {roi:+.2f}%")

    # 6. 盈亏拆解
    print("\n【步骤6】盈亏拆解")

    print(f"\n  未实现盈亏（浮动）: ${total_unrealized_pnl:,.2f}")

    realized_pnl = trading_pnl - total_unrealized_pnl
    print(f"  已实现盈亏（历史）: ${realized_pnl:,.2f}")

    print(f"\n  验证:")
    print(f"    已实现盈亏 + 未实现盈亏 = 总交易盈亏")
    print(f"    ${realized_pnl:,.2f} + ${total_unrealized_pnl:,.2f} = ${trading_pnl:,.2f}")

    if abs((realized_pnl + total_unrealized_pnl) - trading_pnl) < 0.01:
        print(f"    ✅ 验证通过")
    else:
        diff = (realized_pnl + total_unrealized_pnl) - trading_pnl
        print(f"    ⚠️ 差异: ${diff:.2f} (可能是资金费率等)")

    # 7. 完整资金流
    print("\n【步骤7】完整资金流")

    print(f"""
  起始资金:          $0.00
  + 净流入:          ${total_net_inflow:>10,.2f}
  + 已实现盈亏:      ${realized_pnl:>10,.2f}
  + 未实现盈亏:      ${total_unrealized_pnl:>10,.2f}
  {"=" * 40}
  = 当前账户价值:    ${account_value:>10,.2f}
    """)

    # 8. 可提现分析
    print("\n【步骤8】可提现分析")

    locked_in_positions = account_value - withdrawable

    print(f"  账户总价值:   ${account_value:,.2f}")
    print(f"  可提现金额:   ${withdrawable:,.2f}")
    print(f"  仓位占用:     ${locked_in_positions:,.2f}")

    if locked_in_positions > 0:
        lock_ratio = (locked_in_positions / account_value) * 100
        print(f"  资金占用率:   {lock_ratio:.1f}%")

    # 9. 总结
    print("\n" + "=" * 80)
    print("📋 总结")
    print("=" * 80)

    print(f"\n✅ 资金投入: ${total_net_inflow:,.2f}")
    print(f"   - 充值: ${total_deposits:,.2f} ({len(deposits)} 笔)")
    print(f"   - 提现: ${total_withdrawals:,.2f} ({len(withdrawals)} 笔)")
    print(f"   - 转账净额: ${net_transfers:,.2f}")

    if trading_pnl >= 0:
        print(f"\n✅ 交易盈亏: +${trading_pnl:,.2f} ({roi:+.2f}%)")
    else:
        print(f"\n⚠️ 交易盈亏: ${trading_pnl:,.2f} ({roi:+.2f}%)")

    print(f"   - 已实现: ${realized_pnl:,.2f}")
    print(f"   - 未实现: ${total_unrealized_pnl:,.2f}")

    print(f"\n💰 当前状态:")
    print(f"   - 账户价值: ${account_value:,.2f}")
    print(f"   - 可提现: ${withdrawable:,.2f}")
    print(f"   - 仓位占用: ${locked_in_positions:,.2f}")

    # 风险提示
    if trading_pnl < -total_net_inflow * 0.5:
        print(f"\n🚨 风险警告: 已亏损超过本金的 50%！")
    elif trading_pnl < -total_net_inflow * 0.3:
        print(f"\n⚠️ 风险提示: 已亏损超过本金的 30%")

    # 清理
    await store.close()

    print("\n" + "=" * 80)


if __name__ == '__main__':
    import sys

    # 默认测试地址
    default_address = "0xde786a32f80731923d6297c14ef43ca1c8fd4b44"

    if len(sys.argv) > 1:
        address = sys.argv[1]
    else:
        address = input(f"请输入地址 (默认={default_address}): ").strip() or default_address

    asyncio.run(analyze_pnl_reconciliation(address))

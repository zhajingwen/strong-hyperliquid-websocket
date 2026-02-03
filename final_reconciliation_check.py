#!/usr/bin/env python3
"""
最终对账检查
找出所有资金流动，解释$336.23的差异
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store


async def final_check(address: str):
    """最终对账检查"""

    print("=" * 80)
    print("🔍 最终对账检查 - 寻找消失的$336.23")
    print("=" * 80)

    # 初始化
    store = get_store()
    await store.connect()

    client = HyperliquidAPIClient(
        store=store,
        max_concurrent=5,
        rate_limit=10.0
    )

    print(f"\n目标地址: {address}")
    print("-" * 80)

    # 1. 获取账户状态
    state = client.info.user_state(address)
    account_value = float(state['marginSummary']['accountValue'])
    withdrawable = float(state['withdrawable'])

    total_unrealized_pnl = 0.0
    if state.get('assetPositions'):
        for asset_pos in state['assetPositions']:
            total_unrealized_pnl += float(asset_pos['position'].get('unrealizedPnl', 0))

    print(f"\n【当前账户状态】")
    print(f"  账户总价值: ${account_value:,.2f}")
    print(f"  可提现: ${withdrawable:,.2f}")
    print(f"  未实现盈亏: ${total_unrealized_pnl:,.2f}")

    # 2. 获取所有 ledger 记录
    ledger_data = await client.get_user_ledger(address, start_time=0, use_cache=False)

    print(f"\n【Ledger 完整记录】{len(ledger_data)} 条")

    # 按类型分类
    from collections import defaultdict
    by_type = defaultdict(list)
    for r in ledger_data:
        by_type[r['delta'].get('type', 'unknown')].append(r)

    for rtype, records in sorted(by_type.items()):
        print(f"  {rtype:30s}: {len(records):3d} 条")

    # 3. 详细计算所有资金流动
    print(f"\n{'=' * 80}")
    print("💰 资金流动详细分析")
    print("=" * 80)

    # Deposit
    deposits = sum(float(r['delta'].get('usdc', 0)) for r in by_type.get('deposit', []))
    print(f"\n  充值（Deposit）: ${deposits:,.2f}")

    # Withdraw
    withdraws = sum(float(r['delta'].get('usdc', 0)) for r in by_type.get('withdraw', []))
    print(f"  提现（Withdraw）: ${withdraws:,.2f}")

    # Send 转账
    send_in = 0.0
    send_out = 0.0
    send_internal = 0.0

    addr_lower = address.lower()
    for r in by_type.get('send', []):
        delta = r['delta']
        amount = float(delta.get('amount', 0))
        user = delta.get('user', '').lower()
        dest = delta.get('destination', '').lower()

        if dest == addr_lower and user != addr_lower:
            send_in += amount
        elif user == addr_lower and dest != addr_lower:
            send_out += amount
        elif user == addr_lower and dest == addr_lower:
            send_internal += amount

    print(f"\n  Send 转入（外部）: ${send_in:,.2f}")
    print(f"  Send 转出（外部）: ${send_out:,.2f}")
    print(f"  Send 内部转账: ${send_internal:,.2f}")

    # SubAccountTransfer
    sub_in = 0.0
    sub_out = 0.0

    for r in by_type.get('subAccountTransfer', []):
        delta = r['delta']
        amount = float(delta.get('usdc', 0))
        user = delta.get('user', '').lower()
        dest = delta.get('destination', '').lower()

        if dest.startswith(addr_lower[:20]):
            sub_in += amount
        elif user.startswith(addr_lower[:20]):
            sub_out += amount

    print(f"\n  SubAccount 转入: ${sub_in:,.2f}")
    print(f"  SubAccount 转出: ${sub_out:,.2f}")

    # 其他类型
    print(f"\n  其他类型记录:")
    for rtype in by_type.keys():
        if rtype not in ['deposit', 'withdraw', 'send', 'subAccountTransfer']:
            print(f"    {rtype}: {len(by_type[rtype])} 条")
            # 打印样例
            if by_type[rtype]:
                sample = by_type[rtype][0]
                print(f"      样例: {sample['delta']}")

    # 4. 获取交易盈亏
    fills = await client.get_user_fills(address, use_cache=False)

    total_pnl = sum(float(f.get('closedPnl', 0)) for f in fills)
    total_fee = sum(float(f.get('fee', 0)) for f in fills)

    funding_data = await client.get_user_funding(address, start_time=0)
    total_funding = sum(float(r.get('delta', {}).get('usdc', 0)) for r in funding_data)

    realized_pnl_from_fills = total_pnl - total_fee + total_funding

    print(f"\n【交易盈亏（从 Fills）】")
    print(f"  Total closedPnl: ${total_pnl:,.2f}")
    print(f"  - 手续费: ${total_fee:,.2f}")
    print(f"  + 资金费率: ${total_funding:,.2f}")
    print(f"  = 净盈亏: ${realized_pnl_from_fills:,.2f}")

    # 5. 完整账本核算
    print(f"\n{'=' * 80}")
    print("📊 完整账本核算")
    print("=" * 80)

    # 方法1：基于真实本金
    true_capital = deposits - withdraws
    external_net = send_in - send_out + sub_in - sub_out

    print(f"\n【方法1】只算充值/提现为本金")
    print(f"  真实本金: ${true_capital:,.2f}")
    print(f"  + 外部净转入: ${external_net:,.2f}")
    print(f"  + 本账户已实现盈亏（反推）: ${account_value - true_capital - total_unrealized_pnl:,.2f}")
    print(f"  + 未实现盈亏: ${total_unrealized_pnl:,.2f}")
    print(f"  = 账户价值: ${account_value:,.2f} ✅")

    inferred_realized = account_value - true_capital - total_unrealized_pnl

    print(f"\n【关键对比】")
    print(f"  本账户实际已实现盈亏: ${inferred_realized:,.2f}")
    print(f"  Fills API 返回的盈亏: ${realized_pnl_from_fills:,.2f}")
    print(f"  差异: ${realized_pnl_from_fills - inferred_realized:,.2f}")
    print(f"  外部净转入: ${external_net:,.2f}")
    print(f"  差异与外部转入之差: ${abs((realized_pnl_from_fills - inferred_realized) - external_net):,.2f}")

    # 6. 假设检验
    print(f"\n{'=' * 80}")
    print("💡 假设检验")
    print("=" * 80)

    diff = realized_pnl_from_fills - inferred_realized

    print(f"\n【假设1】Fills API 包含了跨账户的交易记录")
    print(f"  如果 Fills API 返回的是【本地址 + 关联账户】的所有交易:")
    print(f"    • 本账户实际赚的: ${inferred_realized:,.2f}")
    print(f"    • 关联账户赚的: ${diff:,.2f}")
    print(f"    • 从关联账户转入的: ${external_net:,.2f}")
    print(f"    • 还在关联账户的: ${diff - external_net:,.2f}")

    if abs(diff - external_net) < 50:
        print(f"\n  ✅ 假设基本成立！")
        print(f"     差异 ${abs(diff - external_net):,.2f} 可能是:")
        print(f"       • 手续费差异")
        print(f"       • 资金费率差异")
        print(f"       • 时间差导致的价格变化")
        print(f"       • API 数据精度问题")
    else:
        print(f"\n  ❌ 假设不完全成立，差异过大")

    print(f"\n【假设2】检查是否有隐藏的资金流出")
    total_inflow = deposits + send_in + sub_in
    total_outflow = withdraws + send_out + sub_out
    net_flow = total_inflow - total_outflow

    print(f"  总流入: ${total_inflow:,.2f}")
    print(f"  总流出: ${total_outflow:,.2f}")
    print(f"  净流入: ${net_flow:,.2f}")
    print(f"  账户价值 + 已提取盈亏理论值: ${net_flow + realized_pnl_from_fills + total_unrealized_pnl:,.2f}")
    print(f"  实际账户价值: ${account_value:,.2f}")

    hidden_outflow = net_flow + realized_pnl_from_fills + total_unrealized_pnl - account_value
    print(f"  推算的隐藏流出: ${hidden_outflow:,.2f}")

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 检查完成")
    print("=" * 80)


if __name__ == '__main__':
    import sys

    # 默认测试地址
    default_address = "0xde786a32f80731923d6297c14ef43ca1c8fd4b44"

    if len(sys.argv) > 1:
        address = sys.argv[1]
    else:
        address = input(f"请输入地址 (默认={default_address}): ").strip() or default_address

    asyncio.run(final_check(address))

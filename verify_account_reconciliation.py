#!/usr/bin/env python3
"""
账户完整对账验证
使用真实 API 数据验证每一笔记录
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


async def verify_reconciliation(address: str):
    """完整对账验证"""

    print("=" * 80)
    print("🔍 账户完整对账验证")
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
        withdrawable = float(state['withdrawable'])

        print(f"  账户总价值: ${account_value:,.2f}")
        print(f"  可提现金额: ${withdrawable:,.2f}")

        # 未实现盈亏
        total_unrealized_pnl = 0.0
        if state.get('assetPositions'):
            print(f"\n  当前持仓:")
            for asset_pos in state['assetPositions']:
                pos = asset_pos['position']
                coin = pos['coin']
                szi = float(pos['szi'])
                pnl = float(pos.get('unrealizedPnl', 0))
                total_unrealized_pnl += pnl

                direction = "做空" if szi < 0 else "做多"
                print(f"    {coin}: {direction} {abs(szi):.4f}, 未实现盈亏 ${pnl:,.2f}")

        print(f"\n  ✅ 未实现盈亏总计: ${total_unrealized_pnl:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        await store.close()
        return

    # ============================================================
    # 2. 获取完整的 ledger 数据（user_non_funding_ledger_updates）
    # ============================================================
    print("\n【步骤2】获取完整 ledger 数据")
    try:
        ledger_data = await client.get_user_ledger(
            address,
            start_time=0,
            use_cache=False
        )

        print(f"  获取 {len(ledger_data)} 条 ledger 记录")

        # 按类型分类
        ledger_by_type = defaultdict(list)
        for record in ledger_data:
            record_type = record['delta'].get('type', 'unknown')
            ledger_by_type[record_type].append(record)

        print(f"\n  Ledger 记录类型分布:")
        for rtype, records in sorted(ledger_by_type.items()):
            print(f"    {rtype:30s}: {len(records):3d} 条")

        # 详细分析每种类型
        print(f"\n  {'━' * 76}")
        print(f"  📋 Ledger 详细记录")
        print(f"  {'━' * 76}")

        # Deposit
        if 'deposit' in ledger_by_type:
            print(f"\n  【Deposit - 充值】{len(ledger_by_type['deposit'])} 笔")
            total = 0.0
            for r in sorted(ledger_by_type['deposit'], key=lambda x: x['time']):
                dt = datetime.fromtimestamp(r['time'] / 1000)
                amount = float(r['delta'].get('usdc', 0))
                total += amount
                print(f"    {dt.strftime('%Y-%m-%d %H:%M:%S')}  ${amount:>10,.2f}")
            print(f"    {'─' * 40}")
            print(f"    总计: ${total:>10,.2f}")

        # Withdraw
        if 'withdraw' in ledger_by_type:
            print(f"\n  【Withdraw - 提现】{len(ledger_by_type['withdraw'])} 笔")
            total = 0.0
            for r in sorted(ledger_by_type['withdraw'], key=lambda x: x['time']):
                dt = datetime.fromtimestamp(r['time'] / 1000)
                amount = float(r['delta'].get('usdc', 0))
                total += amount
                print(f"    {dt.strftime('%Y-%m-%d %H:%M:%S')}  ${amount:>10,.2f}")
            print(f"    {'─' * 40}")
            print(f"    总计: ${total:>10,.2f}")

        # Send
        if 'send' in ledger_by_type:
            print(f"\n  【Send - 转账】{len(ledger_by_type['send'])} 笔")
            for r in sorted(ledger_by_type['send'], key=lambda x: x['time']):
                dt = datetime.fromtimestamp(r['time'] / 1000)
                delta = r['delta']
                amount = float(delta.get('amount', 0))
                user = delta.get('user', '')[:20]
                dest = delta.get('destination', '')[:20]

                direction = "转入" if dest.lower().startswith(address[:20].lower()) else "转出"
                print(f"    {dt.strftime('%Y-%m-%d %H:%M:%S')}  ${amount:>10,.2f}  {direction}")
                print(f"      from: {user}...")
                print(f"      to:   {dest}...")

        # SubAccountTransfer
        if 'subAccountTransfer' in ledger_by_type:
            print(f"\n  【SubAccountTransfer - 子账户转账】{len(ledger_by_type['subAccountTransfer'])} 笔")
            for r in sorted(ledger_by_type['subAccountTransfer'], key=lambda x: x['time']):
                dt = datetime.fromtimestamp(r['time'] / 1000)
                delta = r['delta']
                amount = float(delta.get('usdc', 0))
                user = delta.get('user', '')[:20]
                dest = delta.get('destination', '')[:20]

                direction = "转入" if dest.lower().startswith(address[:20].lower()) else "转出"
                print(f"    {dt.strftime('%Y-%m-%d %H:%M:%S')}  ${amount:>10,.2f}  {direction}")
                print(f"      from: {user}...")
                print(f"      to:   {dest}...")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()

    # ============================================================
    # 3. 获取 fills 数据（userFillsByTime）
    # ============================================================
    print(f"\n{'━' * 80}")
    print("\n【步骤3】获取 fills 数据")
    try:
        fills = await client.get_user_fills(address, use_cache=False)
        print(f"  获取 {len(fills)} 条 fills 记录")

        if fills:
            fills_sorted = sorted(fills, key=lambda x: x['time'])
            first_time = datetime.fromtimestamp(fills_sorted[0]['time'] / 1000)
            last_time = datetime.fromtimestamp(fills_sorted[-1]['time'] / 1000)

            print(f"\n  时间范围:")
            print(f"    首次: {first_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"    最后: {last_time.strftime('%Y-%m-%d %H:%M:%S')}")

            # 统计
            total_pnl = sum(float(f.get('closedPnl', 0)) for f in fills)
            total_fee = sum(float(f.get('fee', 0)) for f in fills)

            # 清算
            liquidations = [f for f in fills if f.get('liquidation', False)]
            liquidation_pnl = sum(float(f.get('closedPnl', 0)) for f in liquidations)

            # 普通交易
            normal_fills = [f for f in fills if not f.get('liquidation', False)]
            normal_pnl = sum(float(f.get('closedPnl', 0)) for f in normal_fills)

            print(f"\n  Fills 统计:")
            print(f"    总交易数:     {len(fills)} 笔")
            print(f"    普通交易:     {len(normal_fills)} 笔, PNL: ${normal_pnl:,.2f}")
            print(f"    清算交易:     {len(liquidations)} 笔, PNL: ${liquidation_pnl:,.2f}")
            print(f"    总 PNL:       ${total_pnl:,.2f}")
            print(f"    总手续费:     ${total_fee:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        total_pnl = 0.0
        total_fee = 0.0

    # ============================================================
    # 4. 获取资金费率（userFundingPayments）
    # ============================================================
    print(f"\n{'━' * 80}")
    print("\n【步骤4】获取资金费率数据")
    try:
        funding_data = await client.get_user_funding(address, start_time=0)
        print(f"  获取 {len(funding_data)} 条资金费率记录")

        total_funding = sum(float(r.get('delta', {}).get('usdc', 0)) for r in funding_data)
        print(f"  资金费率总计: ${total_funding:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        total_funding = 0.0

    # ============================================================
    # 5. 完整对账
    # ============================================================
    print(f"\n{'=' * 80}")
    print("📊 完整对账")
    print("=" * 80)

    # 从 ledger 计算净流入（两种方法）
    deposit_total = sum(
        float(r['delta'].get('usdc', 0))
        for r in ledger_by_type.get('deposit', [])
    )
    withdraw_total = sum(
        float(r['delta'].get('usdc', 0))
        for r in ledger_by_type.get('withdraw', [])
    )

    # Send 转账
    send_in = 0.0
    send_out = 0.0
    for r in ledger_by_type.get('send', []):
        delta = r['delta']
        amount = float(delta.get('amount', 0))
        user = delta.get('user', '').lower()
        dest = delta.get('destination', '').lower()

        if dest.startswith(address.lower()[:20]) and not user.startswith(address.lower()[:20]):
            send_in += amount
        elif user.startswith(address.lower()[:20]) and not dest.startswith(address.lower()[:20]):
            send_out += amount

    # SubAccountTransfer
    sub_in = 0.0
    sub_out = 0.0
    for r in ledger_by_type.get('subAccountTransfer', []):
        delta = r['delta']
        amount = float(delta.get('usdc', 0))
        user = delta.get('user', '').lower()
        dest = delta.get('destination', '').lower()

        if dest.startswith(address.lower()[:20]):
            sub_in += amount
        elif user.startswith(address.lower()[:20]):
            sub_out += amount

    # 汇总
    true_capital = deposit_total - withdraw_total
    total_transfers_in = send_in + sub_in
    total_transfers_out = send_out + sub_out
    net_transfers = total_transfers_in - total_transfers_out

    print(f"\n【资金流入】")
    print(f"  充值（Deposit）:        ${deposit_total:>12,.2f}")
    print(f"  提现（Withdraw）:       ${withdraw_total:>12,.2f}")
    print(f"  {'─' * 50}")
    print(f"  真实本金:               ${true_capital:>12,.2f}  ✅")

    print(f"\n【转账】")
    print(f"  转入（Send/Sub）:       ${total_transfers_in:>12,.2f}")
    print(f"  转出（Send/Sub）:       ${total_transfers_out:>12,.2f}")
    print(f"  {'─' * 50}")
    print(f"  净转账:                 ${net_transfers:>12,.2f}  ⚠️")

    print(f"\n【交易盈亏（从 fills）】")
    print(f"  成交盈亏（closedPnl）:  ${total_pnl:>12,.2f}")
    print(f"  - 手续费:               ${total_fee:>12,.2f}")
    print(f"  + 资金费率:             ${total_funding:>12,.2f}")
    print(f"  {'─' * 50}")
    print(f"  净盈亏:                 ${total_pnl - total_fee + total_funding:>12,.2f}  ✅")

    print(f"\n【当前状态】")
    print(f"  账户价值:               ${account_value:>12,.2f}")
    print(f"  未实现盈亏:             ${total_unrealized_pnl:>12,.2f}")

    # 对账验证
    print(f"\n{'=' * 80}")
    print("🔍 对账验证")
    print("=" * 80)

    realized_pnl_from_fills = total_pnl - total_fee + total_funding

    print(f"\n【方法1】基于真实本金（不含转账）")
    print(f"  理论公式:")
    print(f"    账户价值 = 真实本金 + 已实现盈亏 + 未实现盈亏")
    print(f"\n  推算已实现盈亏:")
    inferred_realized_1 = account_value - true_capital - total_unrealized_pnl
    print(f"    = 账户价值 - 真实本金 - 未实现盈亏")
    print(f"    = ${account_value:,.2f} - ${true_capital:,.2f} - ${total_unrealized_pnl:,.2f}")
    print(f"    = ${inferred_realized_1:,.2f}")
    print(f"\n  Fills 记录的已实现盈亏: ${realized_pnl_from_fills:,.2f}")
    print(f"\n  差异: ${realized_pnl_from_fills - inferred_realized_1:,.2f}")

    diff1 = abs(realized_pnl_from_fills - inferred_realized_1)
    if diff1 < 1:
        print(f"  ✅ 完美匹配！差异 <$1")
    elif diff1 < 10:
        print(f"  ⚠️  小差异，可能是舍入误差")
    else:
        print(f"  ❌ 大差异！可能原因:")
        print(f"     1. Fills 包含了其他账户的交易记录")
        print(f"     2. 转账金额实际上是交易盈亏的转移")
        print(f"     3. Ledger 数据不完整")

    print(f"\n【方法2】包含转账（传统方法）")
    print(f"  假设转账是外部资金注入:")
    total_inflow = true_capital + net_transfers
    inferred_realized_2 = account_value - total_inflow - total_unrealized_pnl
    print(f"    总净流入 = ${total_inflow:,.2f}")
    print(f"    推算已实现盈亏 = ${inferred_realized_2:,.2f}")
    print(f"    Fills 已实现盈亏 = ${realized_pnl_from_fills:,.2f}")
    print(f"    差异 = ${realized_pnl_from_fills - inferred_realized_2:,.2f}")

    # 关键发现
    print(f"\n{'=' * 80}")
    print("💡 关键发现")
    print("=" * 80)

    if abs(net_transfers - diff1) < 10:
        print(f"\n  🎯 发现：差异金额（${diff1:,.2f}）≈ 净转账（${net_transfers:,.2f}）")
        print(f"\n  这说明：")
        print(f"    1. Fills 中的 closedPnl 包含了在其他账户的交易盈亏")
        print(f"    2. 这部分盈亏（约 ${net_transfers:,.2f}）是在其他账户赚的")
        print(f"    3. 然后通过转账转入本账户")
        print(f"    4. 但 userFillsByTime API 可能返回了跨账户的记录")
        print(f"\n  验证方法：")
        print(f"    - 检查 fills 中是否有交易时间在第一笔转账之前")
        print(f"    - 如果有，说明这些是其他账户的交易记录")

        # 检查
        if fills and ledger_by_type.get('send'):
            first_transfer_time = min(r['time'] for r in ledger_by_type['send'])
            fills_before_transfer = [
                f for f in fills
                if f['time'] < first_transfer_time
            ]

            if fills_before_transfer:
                pnl_before_transfer = sum(
                    float(f.get('closedPnl', 0)) for f in fills_before_transfer
                )
                print(f"\n  ⚠️  发现：")
                print(f"    第一笔转账时间: {datetime.fromtimestamp(first_transfer_time/1000).strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"    转账前的交易: {len(fills_before_transfer)} 笔")
                print(f"    转账前的盈亏: ${pnl_before_transfer:,.2f}")
                print(f"\n  这证实了：Fills 包含了转账前在其他账户的交易！")

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 验证完成")
    print("=" * 80)


if __name__ == '__main__':
    import sys

    # 默认测试地址
    default_address = "0xde786a32f80731923d6297c14ef43ca1c8fd4b44"

    if len(sys.argv) > 1:
        address = sys.argv[1]
    else:
        address = input(f"请输入地址 (默认={default_address}): ").strip() or default_address

    asyncio.run(verify_reconciliation(address))

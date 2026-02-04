#!/usr/bin/env python3
"""
修正版 PNL 分析脚本
考虑转账可能是盈亏转移，而非外部资金注入
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store


async def analyze_pnl_corrected(address: str):
    """修正版 PNL 分析"""

    print("=" * 80)
    print("📊 PNL 分析（修正版）")
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
    print("\n【步骤1】当前账户状态")
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

        print(f"\n  未实现盈亏总计: ${total_unrealized_pnl:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        await store.close()
        return

    # 2. 获取出入金记录
    print("\n【步骤2】出入金分析")
    try:
        ledger_data = await client.get_user_ledger(
            address,
            start_time=0,
            use_cache=False
        )

        print(f"  获取 {len(ledger_data)} 条记录")

        # 统计
        total_deposits = 0.0
        total_withdrawals = 0.0
        total_transfers_in = 0.0
        total_transfers_out = 0.0

        for record in ledger_data:
            delta = record['delta']
            record_type = delta['type']

            if record_type == 'deposit':
                total_deposits += float(delta.get('usdc', 0))

            elif record_type == 'withdraw':
                total_withdrawals += float(delta.get('usdc', 0))

            elif record_type == 'send':
                amount = float(delta.get('amount', 0))
                user = delta.get('user', '').lower()
                destination = delta.get('destination', '').lower()

                if destination == address.lower() and user != address.lower():
                    total_transfers_in += amount
                elif user == address.lower() and destination != address.lower():
                    total_transfers_out += amount

            elif record_type == 'subAccountTransfer':
                amount = float(delta.get('usdc', 0))
                user = delta.get('user', '').lower()
                destination = delta.get('destination', '').lower()

                if destination == address.lower():
                    total_transfers_in += amount
                elif user == address.lower():
                    total_transfers_out += amount

        net_deposits = total_deposits - total_withdrawals
        net_transfers = total_transfers_in - total_transfers_out

        print(f"\n  充值/提现:")
        print(f"    充值: ${total_deposits:,.2f}")
        print(f"    提现: ${total_withdrawals:,.2f}")
        print(f"    净额: ${net_deposits:,.2f}")

        print(f"\n  转账:")
        print(f"    转入: ${total_transfers_in:,.2f}")
        print(f"    转出: ${total_transfers_out:,.2f}")
        print(f"    净额: ${net_transfers:,.2f}")

        # ⚠️ 修正点：区分外部资金和盈亏转移
        if net_transfers > 0:
            print(f"\n  ⚠️  检测到净转入 ${net_transfers:,.2f}")
            print(f"     转账可能是：")
            print(f"     1. 外部资金注入（应计入本金）")
            print(f"     2. 盈亏转移（不应计入本金）")
            print(f"\n     本分析采用方案2（盈亏转移），仅充值/提现算本金")

        # 计算真实本金
        true_capital = net_deposits  # 仅充值/提现
        total_net_inflow_legacy = net_deposits + net_transfers  # 传统方法（包含转账）

        print(f"\n  💰 真实投入本金: ${true_capital:,.2f}")
        print(f"     （仅充值/提现，不含转账）")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        await store.close()
        return

    # 3. 获取成交记录
    print("\n【步骤3】交易盈亏")
    try:
        fills = await client.get_user_fills(
            address,
            use_cache=False
        )

        print(f"  获取 {len(fills)} 条成交记录")

        if not fills:
            fills_realized_pnl = 0.0
            total_fees = 0.0
        else:
            fills_realized_pnl = sum(float(f.get('closedPnl', 0)) for f in fills)
            total_fees = sum(float(f.get('fee', 0)) for f in fills)

            print(f"\n  成交盈亏: ${fills_realized_pnl:,.2f}")
            print(f"  手续费:   ${total_fees:,.2f}")

            # 检查清算
            liquidations = [f for f in fills if f.get('liquidation', False)]
            if liquidations:
                liquidation_loss = sum(float(f.get('closedPnl', 0)) for f in liquidations)
                print(f"\n  ⚠️  发现 {len(liquidations)} 笔强制清算")
                print(f"     清算损失: ${liquidation_loss:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        fills_realized_pnl = 0.0
        total_fees = 0.0

    # 4. 获取资金费率
    print("\n【步骤4】资金费率")
    try:
        funding_data = await client.get_user_funding(
            address,
            start_time=0
        )

        total_funding = sum(float(r.get('delta', {}).get('usdc', 0)) for r in funding_data)

        print(f"  资金费率总计: ${total_funding:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        total_funding = 0.0

    # 5. 盈亏汇总
    print("\n" + "=" * 80)
    print("💰 盈亏汇总")
    print("=" * 80)

    fills_net_pnl = fills_realized_pnl - total_fees + total_funding

    print(f"\n【本金投入】")
    print(f"  真实本金:           ${true_capital:,.2f}")

    print(f"\n【交易盈亏】")
    print(f"  成交盈亏:           ${fills_realized_pnl:,.2f}")
    print(f"  - 手续费:           ${total_fees:,.2f}")
    print(f"  + 资金费率:         ${total_funding:,.2f}")
    print(f"  {'─' * 50}")
    print(f"  净盈亏:             ${fills_net_pnl:,.2f}")

    print(f"\n【当前状态】")
    print(f"  账户价值:           ${account_value:,.2f}")
    print(f"  未实现盈亏:         ${total_unrealized_pnl:,.2f}")

    # 推算已实现盈亏
    total_trading_pnl = account_value - true_capital
    inferred_realized_pnl = total_trading_pnl - total_unrealized_pnl

    print(f"\n【验证】")
    print(f"  推算已实现盈亏:     ${inferred_realized_pnl:,.2f}")
    print(f"    = (账户价值 - 本金) - 未实现盈亏")
    print(f"    = (${account_value:,.2f} - ${true_capital:,.2f}) - ${total_unrealized_pnl:,.2f}")

    print(f"\n  成交盈亏:           ${fills_net_pnl:,.2f}")

    diff = inferred_realized_pnl - fills_net_pnl
    print(f"\n  差异:               ${diff:,.2f}")

    if abs(diff) < 1:
        print(f"  ✅ 差异很小 (<$1)，计算准确")
    elif abs(diff) < 50:
        print(f"  ⚠️  有差异，可能是清算罚金或其他费用")
    else:
        print(f"  ❌ 差异较大，需要进一步调查")

    # ROI 计算
    print("\n" + "=" * 80)
    print("📊 ROI 分析")
    print("=" * 80)

    if true_capital > 0:
        total_roi = (total_trading_pnl / true_capital) * 100
        realized_roi = (fills_net_pnl / true_capital) * 100
        unrealized_roi = (total_unrealized_pnl / true_capital) * 100

        print(f"\n  投入本金:    ${true_capital:,.2f}")
        print(f"\n  总 ROI:      {total_roi:+.2f}%")
        print(f"    已实现:    {realized_roi:+.2f}%")
        print(f"    未实现:    {unrealized_roi:+.2f}%")

        if total_roi < -50:
            print(f"\n  🚨 风险警告: 已亏损超过本金 50%")
        elif total_roi < -30:
            print(f"\n  ⚠️  风险提示: 已亏损超过本金 30%")
        elif total_roi > 50:
            print(f"\n  🎉 收益优秀: ROI 超过 50%")

    # 对比传统方法
    if net_transfers != 0:
        print("\n" + "=" * 80)
        print("📋 对比：传统方法（包含转账）")
        print("=" * 80)

        legacy_trading_pnl = account_value - total_net_inflow_legacy
        legacy_realized_pnl = legacy_trading_pnl - total_unrealized_pnl
        legacy_diff = legacy_realized_pnl - fills_net_pnl

        print(f"\n  如果将转账算作本金投入:")
        print(f"    总本金:            ${total_net_inflow_legacy:,.2f}")
        print(f"    推算已实现盈亏:    ${legacy_realized_pnl:,.2f}")
        print(f"    成交盈亏:          ${fills_net_pnl:,.2f}")
        print(f"    差异:              ${legacy_diff:,.2f}")

        if abs(diff) < abs(legacy_diff):
            print(f"\n  ✅ 当前方法更准确（差异更小）")
        else:
            print(f"\n  ⚠️  传统方法可能更准确，转账可能是真实资金注入")

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 分析完成")
    print("=" * 80)


if __name__ == '__main__':
    import sys

    # 默认测试地址
    default_address = "0x324f74880ccee9a05282614d3f80c09831a36774"

    if len(sys.argv) > 1:
        address = sys.argv[1]
    else:
        address = input(f"请输入地址 (默认={default_address}): ").strip() or default_address

    asyncio.run(analyze_pnl_corrected(address))

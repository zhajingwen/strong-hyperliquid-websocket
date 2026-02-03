#!/usr/bin/env python3
"""
对比三种 PNL 计算方式
1. userFillsByTime (成交记录)
2. 出入金对账法 (accountValue - 净流入)
3. userFundingPayments (资金费率)

找出差异原因
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store


async def compare_pnl_methods(address: str):
    """对比不同方法计算的 PNL"""

    print("=" * 80)
    print("📊 PNL 计算方式对比分析")
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
    # 方法1: 从 user_state 获取当前状态
    # ============================================================
    print("\n【方法1】user_state - 当前账户状态")
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
                print(f"    {coin}: {direction} {abs(szi):.2f}, 未实现盈亏 ${pnl:,.2f}")

        print(f"\n  ✅ 未实现盈亏总计: ${total_unrealized_pnl:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        await store.close()
        return

    # ============================================================
    # 方法2: 从出入金记录计算净流入
    # ============================================================
    print("\n【方法2】出入金对账 - 计算净流入")
    try:
        ledger_data = await client.get_user_ledger(
            address,
            start_time=0,
            use_cache=False
        )

        print(f"  获取 {len(ledger_data)} 条出入金记录")

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
        total_net_inflow = net_deposits + net_transfers

        print(f"\n  充值: ${total_deposits:,.2f}")
        print(f"  提现: ${total_withdrawals:,.2f}")
        print(f"  净充提: ${net_deposits:,.2f}")
        print(f"\n  转入: ${total_transfers_in:,.2f}")
        print(f"  转出: ${total_transfers_out:,.2f}")
        print(f"  净转账: ${net_transfers:,.2f}")
        print(f"\n  ✅ 总净流入: ${total_net_inflow:,.2f}")

        # 计算总交易盈亏
        total_trading_pnl = account_value - total_net_inflow
        print(f"\n  总交易盈亏 = accountValue - 净流入")
        print(f"              = ${account_value:,.2f} - ${total_net_inflow:,.2f}")
        print(f"              = ${total_trading_pnl:,.2f}")

        # 推算已实现盈亏
        inferred_realized_pnl = total_trading_pnl - total_unrealized_pnl
        print(f"\n  推算已实现盈亏 = 总交易盈亏 - 未实现盈亏")
        print(f"                  = ${total_trading_pnl:,.2f} - ${total_unrealized_pnl:,.2f}")
        print(f"                  = ${inferred_realized_pnl:,.2f}")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        await store.close()
        return

    # ============================================================
    # 方法3: 从 userFillsByTime 计算成交盈亏
    # ============================================================
    print("\n【方法3】userFillsByTime - 成交记录计算")
    try:
        fills = await client.get_user_fills(
            address,
            use_cache=False
        )

        print(f"  获取 {len(fills)} 条成交记录")

        if not fills:
            print(f"  ⚠️  无成交记录")
            fills_realized_pnl = 0.0
            total_fees = 0.0
        else:
            # 计算总盈亏和手续费
            fills_realized_pnl = 0.0
            total_fees = 0.0

            for fill in fills:
                # closedPnl 是已实现盈亏
                closed_pnl = float(fill.get('closedPnl', 0))
                fills_realized_pnl += closed_pnl

                # 手续费
                fee = float(fill.get('fee', 0))
                total_fees += fee

            print(f"\n  成交盈亏总计: ${fills_realized_pnl:,.2f}")
            print(f"  手续费总计: ${total_fees:,.2f}")
            print(f"\n  ✅ 扣除手续费后盈亏: ${fills_realized_pnl - total_fees:,.2f}")

            # 显示统计
            buy_fills = [f for f in fills if f.get('side') == 'B']
            sell_fills = [f for f in fills if f.get('side') == 'A']

            print(f"\n  交易统计:")
            print(f"    买入: {len(buy_fills)} 笔")
            print(f"    卖出: {len(sell_fills)} 笔")
            print(f"    总计: {len(fills)} 笔")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        await store.close()
        return

    # ============================================================
    # 方法4: 从 userFundingPayments 获取资金费率
    # ============================================================
    print("\n【方法4】userFundingPayments - 资金费率")
    try:
        funding_data = await client.get_user_funding(
            address,
            start_time=0
        )

        print(f"  获取 {len(funding_data)} 条资金费率记录")

        if not funding_data:
            print(f"  ⚠️  无资金费率记录")
            total_funding = 0.0
        else:
            # 计算总资金费率
            total_funding = 0.0

            for record in funding_data:
                delta = record.get('delta', {})
                # usdc 字段可能是字符串
                usdc = float(delta.get('usdc', 0))
                total_funding += usdc

            print(f"\n  ✅ 资金费率总计: ${total_funding:,.2f}")

            # 正数表示收到，负数表示支付
            if total_funding > 0:
                print(f"     (收到资金费)")
            elif total_funding < 0:
                print(f"     (支付资金费)")

    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        total_funding = 0.0

    # ============================================================
    # 对比分析
    # ============================================================
    print("\n" + "=" * 80)
    print("📊 对比分析")
    print("=" * 80)

    print(f"\n【已实现盈亏对比】")
    print(f"  方法2 (推算): ${inferred_realized_pnl:,.2f}")
    print(f"  方法3 (成交): ${fills_realized_pnl:,.2f}")
    print(f"  手续费:       ${total_fees:,.2f}")
    print(f"  资金费率:     ${total_funding:,.2f}")

    # 计算差异
    fills_with_fees = fills_realized_pnl - total_fees
    fills_with_funding = fills_with_fees + total_funding

    print(f"\n【调整后对比】")
    print(f"  成交盈亏 - 手续费 = ${fills_with_fees:,.2f}")
    print(f"  + 资金费率 = ${fills_with_funding:,.2f}")

    diff = inferred_realized_pnl - fills_with_funding
    print(f"\n  差异 = 推算盈亏 - (成交 - 手续费 + 资金费)")
    print(f"       = ${inferred_realized_pnl:,.2f} - ${fills_with_funding:,.2f}")
    print(f"       = ${diff:,.2f}")

    if abs(diff) < 1:
        print(f"\n  ✅ 差异很小 (<$1)，计算基本一致")
    elif abs(diff) < 10:
        print(f"\n  ⚠️  差异较小 (<$10)，可能是舍入误差")
    else:
        print(f"\n  ❌ 差异较大 (≥$10)，可能存在问题:")
        print(f"     - 清算费用未计入？")
        print(f"     - 数据不完整？")
        print(f"     - 其他未知费用？")

    # ============================================================
    # 完整盈亏构成
    # ============================================================
    print("\n" + "=" * 80)
    print("📋 完整盈亏构成")
    print("=" * 80)

    print(f"""
  1️⃣  资金投入
      净流入:                    ${total_net_inflow:>12,.2f}

  2️⃣  已实现盈亏（历史交易）
      成交盈亏:                  ${fills_realized_pnl:>12,.2f}
      - 手续费:                  ${total_fees:>12,.2f}
      + 资金费率:                ${total_funding:>12,.2f}
      {"─" * 50}
      小计:                      ${fills_with_funding:>12,.2f}

  3️⃣  未实现盈亏（当前持仓）
      浮动盈亏:                  ${total_unrealized_pnl:>12,.2f}

  {"=" * 50}
  理论账户价值:
      净流入 + 已实现 + 未实现
    = ${total_net_inflow:,.2f} + ${fills_with_funding:,.2f} + ${total_unrealized_pnl:,.2f}
    = ${total_net_inflow + fills_with_funding + total_unrealized_pnl:,.2f}

  实际账户价值:                ${account_value:>12,.2f}

  差异:                        ${account_value - (total_net_inflow + fills_with_funding + total_unrealized_pnl):>12,.2f}
    """)

    # 验证
    theoretical_value = total_net_inflow + fills_with_funding + total_unrealized_pnl
    actual_diff = account_value - theoretical_value

    if abs(actual_diff) < 1:
        print(f"  ✅ 账户价值计算准确 (差异 <$1)")
    elif abs(actual_diff) < 10:
        print(f"  ⚠️  账户价值有小差异 (${actual_diff:.2f})")
    else:
        print(f"  ❌ 账户价值差异较大 (${actual_diff:.2f})")
        print(f"     可能原因:")
        print(f"     - 清算费用: 查看是否有被强平记录")
        print(f"     - 其他费用: 可能存在其他平台费用")
        print(f"     - 数据延迟: API 数据可能不同步")

    # ============================================================
    # ROI 计算
    # ============================================================
    print("\n" + "=" * 80)
    print("💹 ROI 计算")
    print("=" * 80)

    if total_net_inflow > 0:
        # 总 ROI
        total_roi = (total_trading_pnl / total_net_inflow) * 100

        # 已实现 ROI
        realized_roi = (fills_with_funding / total_net_inflow) * 100

        # 未实现 ROI
        unrealized_roi = (total_unrealized_pnl / total_net_inflow) * 100

        print(f"\n  投入本金:    ${total_net_inflow:,.2f}")
        print(f"\n  总 ROI:      {total_roi:+.2f}%")
        print(f"    已实现:    {realized_roi:+.2f}%")
        print(f"    未实现:    {unrealized_roi:+.2f}%")

        if total_roi < -50:
            print(f"\n  🚨 风险警告: 已亏损超过本金 50%")
        elif total_roi < -30:
            print(f"\n  ⚠️  风险提示: 已亏损超过本金 30%")
        elif total_roi > 50:
            print(f"\n  🎉 收益优秀: ROI 超过 50%")

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

    asyncio.run(compare_pnl_methods(address))

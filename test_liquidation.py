#!/usr/bin/env python3
"""
爆仓检测测试脚本
直接从 API 获取数据，验证 liquidation 字段
"""
from hyperliquid.info import Info
from datetime import datetime
import sys


def test_liquidation(address: str):
    """检测指定地址的爆仓记录"""

    print("=" * 80)
    print("🔍 爆仓检测测试")
    print("=" * 80)
    print(f"\n地址: {address}")
    print("-" * 80)

    info = Info(skip_ws=True)

    # 1. 直接从 API 获取 fills 数据
    print("\n【步骤1】从 API 获取交易记录...")
    fills = info.user_fills_by_time(address, start_time=0)
    print(f"  获取 {len(fills)} 条记录")

    # 2. 检测爆仓记录
    print("\n【步骤2】检测爆仓记录...")
    liquidations = []

    for fill in fills:
        liq_info = fill.get('liquidation')
        if liq_info:
            liquidations.append({
                'time': fill.get('time'),
                'coin': fill.get('coin'),
                'side': fill.get('side'),
                'price': fill.get('px'),
                'size': fill.get('sz'),
                'closedPnl': fill.get('closedPnl'),
                'dir': fill.get('dir'),
                'liquidation': liq_info,
                'hash': fill.get('hash')
            })

    if liquidations:
        print(f"\n  ⚠️  发现 {len(liquidations)} 笔爆仓记录:")
        print("-" * 80)

        total_loss = 0.0
        for i, liq in enumerate(liquidations, 1):
            time_str = datetime.fromtimestamp(liq['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            pnl = float(liq['closedPnl'])
            total_loss += pnl

            print(f"\n  [{i}] {time_str}")
            print(f"      币种: {liq['coin']}")
            print(f"      方向: {liq['dir']} ({liq['side']})")
            print(f"      价格: {liq['price']}")
            print(f"      数量: {liq['size']}")
            print(f"      已实现盈亏: ${pnl:,.2f}")
            print(f"      清算详情:")
            print(f"        - 被清算用户: {liq['liquidation'].get('liquidatedUser', 'N/A')}")
            print(f"        - 标记价格: {liq['liquidation'].get('markPx', 'N/A')}")
            print(f"        - 清算方式: {liq['liquidation'].get('method', 'N/A')}")
            print(f"      交易哈希: {liq['hash']}")

        print("\n" + "=" * 80)
        print(f"📊 爆仓统计")
        print("=" * 80)
        print(f"  总爆仓次数: {len(liquidations)}")
        print(f"  总爆仓损失: ${total_loss:,.2f}")

        # 按币种统计
        coin_stats = {}
        for liq in liquidations:
            coin = liq['coin']
            if coin not in coin_stats:
                coin_stats[coin] = {'count': 0, 'loss': 0.0}
            coin_stats[coin]['count'] += 1
            coin_stats[coin]['loss'] += float(liq['closedPnl'])

        print(f"\n  按币种统计:")
        for coin, stats in sorted(coin_stats.items(), key=lambda x: x[1]['loss']):
            print(f"    {coin}: {stats['count']} 次, ${stats['loss']:,.2f}")
    else:
        print("\n  ✅ 未发现爆仓记录")

    # 3. 对比数据库数据（可选）
    print("\n" + "=" * 80)
    print("📋 数据结构对比")
    print("=" * 80)

    if fills:
        last_fill = fills[-1]
        print("\n  API 返回的完整字段:")
        for key in sorted(last_fill.keys()):
            value = last_fill[key]
            if key == 'liquidation' and value:
                print(f"    ✅ {key}: {value}")
            else:
                print(f"    {key}: {type(value).__name__}")

        print("\n  数据库存储的字段:")
        db_fields = ['address', 'time', 'coin', 'side', 'price', 'size', 'closed_pnl', 'fee', 'hash']
        for field in db_fields:
            print(f"    {field}")
        print(f"    ❌ liquidation (未存储)")

    return liquidations


def main():
    # 默认测试地址
    default_address = "0x324f74880ccee9a05282614d3f80c09831a36774"

    if len(sys.argv) > 1:
        address = sys.argv[1]
    else:
        address = input(f"请输入地址 (默认={default_address}): ").strip()
        if not address:
            address = default_address

    test_liquidation(address)


if __name__ == "__main__":
    main()

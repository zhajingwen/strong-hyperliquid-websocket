#!/usr/bin/env python3
"""
验证转账方向
仔细检查每笔转账是真的转入还是转出
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store


async def verify_transfers(address: str):
    """验证转账方向"""

    print("=" * 80)
    print("🔍 转账方向详细验证")
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

    # 获取 ledger
    ledger_data = await client.get_user_ledger(address, start_time=0, use_cache=False)

    # 提取转账记录
    send_records = [r for r in ledger_data if r['delta'].get('type') == 'send']

    print(f"\n找到 {len(send_records)} 笔 Send 转账记录")
    print("=" * 80)

    for i, record in enumerate(sorted(send_records, key=lambda x: x['time']), 1):
        dt = datetime.fromtimestamp(record['time'] / 1000)
        delta = record['delta']

        amount = float(delta.get('amount', 0))
        user = delta.get('user', '')
        dest = delta.get('destination', '')

        print(f"\n【转账 #{i}】")
        print(f"  时间: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  金额: ${amount:,.2f}")
        print(f"  From: {user}")
        print(f"  To:   {dest}")

        # 目标地址规范化（小写）
        target_addr = address.lower()
        user_lower = user.lower()
        dest_lower = dest.lower()

        print(f"\n  目标地址: {target_addr}")
        print(f"  From匹配: {user_lower == target_addr}")
        print(f"  To匹配:   {dest_lower == target_addr}")

        # 判断方向
        if dest_lower == target_addr and user_lower != target_addr:
            direction = "✅ 转入（FROM 其他地址 TO 本地址）"
            is_inflow = True
        elif user_lower == target_addr and dest_lower != target_addr:
            direction = "⚠️  转出（FROM 本地址 TO 其他地址）"
            is_inflow = False
        elif user_lower == target_addr and dest_lower == target_addr:
            direction = "🔄 内部转账（本地址 TO 本地址）"
            is_inflow = None  # 内部转账不影响净流入
        else:
            direction = "❓ 未知（两个地址都不是本地址）"
            is_inflow = None

        print(f"\n  方向判断: {direction}")

        # 完整数据
        print(f"\n  完整 delta:")
        for key, value in delta.items():
            print(f"    {key}: {value}")

    # 统计
    print(f"\n{'=' * 80}")
    print("📊 统计汇总")
    print("=" * 80)

    total_in = 0.0
    total_out = 0.0
    total_internal = 0.0

    target_addr = address.lower()

    for record in send_records:
        delta = record['delta']
        amount = float(delta.get('amount', 0))
        user = delta.get('user', '').lower()
        dest = delta.get('destination', '').lower()

        if dest == target_addr and user != target_addr:
            total_in += amount
        elif user == target_addr and dest != target_addr:
            total_out += amount
        elif user == target_addr and dest == target_addr:
            total_internal += amount

    print(f"\n  转入（外部 → 本地址）: ${total_in:,.2f}")
    print(f"  转出（本地址 → 外部）: ${total_out:,.2f}")
    print(f"  内部转账（本地址 ↔ 本地址）: ${total_internal:,.2f}")
    print(f"  ───────────────────────────────")
    print(f"  净流入: ${total_in - total_out:,.2f}")

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

    asyncio.run(verify_transfers(address))

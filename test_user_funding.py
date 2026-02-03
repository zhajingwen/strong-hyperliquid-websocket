#!/usr/bin/env python3
"""
测试 user_funding_history 接口
"""
import asyncio
import sys
from pathlib import Path
import time
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store


async def test_user_funding():
    """测试资金费率接口"""

    print("=" * 80)
    print("user_funding_history() 接口测试")
    print("=" * 80)

    # 初始化
    store = get_store()
    await store.connect()

    client = HyperliquidAPIClient(
        store=store,
        max_concurrent=5,
        rate_limit=10.0
    )

    # 测试地址（已知有数据）
    test_address = "0xde786a32f80731923d6297c14ef43ca1c8fd4b44"

    # 计算时间范围（最近30天）
    current_time = int(time.time() * 1000)
    start_time = current_time - (30 * 24 * 60 * 60 * 1000)

    print(f"\n【测试参数】")
    print(f"  地址: {test_address}")
    print(f"  起始时间: {datetime.fromtimestamp(start_time/1000).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  结束时间: {datetime.fromtimestamp(current_time/1000).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  时间范围: 30 天")

    # 获取数据
    print(f"\n【获取数据】")
    funding_data = await client.get_user_funding(test_address, start_time)

    if not funding_data:
        print("  ❌ 未获取到数据")
        await store.close()
        return

    print(f"  ✅ 成功获取 {len(funding_data)} 条记录")

    # 数据分析
    print(f"\n【数据分析】")

    # 涉及币种
    coins = set(record['delta']['coin'] for record in funding_data)
    print(f"  涉及币种: {', '.join(sorted(coins))}")

    # 累计费用
    total_funding = sum(float(record['delta']['usdc']) for record in funding_data)
    print(f"  累计资金费: {total_funding:.2f} USDC")

    # 收入/支出统计
    income_records = [r for r in funding_data if float(r['delta']['usdc']) > 0]
    expense_records = [r for r in funding_data if float(r['delta']['usdc']) < 0]

    income = sum(float(r['delta']['usdc']) for r in income_records)
    expense = sum(float(r['delta']['usdc']) for r in expense_records)

    print(f"\n  收入统计:")
    print(f"    • 次数: {len(income_records)}")
    print(f"    • 总额: +{income:.2f} USDC")

    print(f"\n  支出统计:")
    print(f"    • 次数: {len(expense_records)}")
    print(f"    • 总额: {expense:.2f} USDC")

    # 平均费率
    avg_rate = sum(float(r['delta']['fundingRate']) for r in funding_data) / len(funding_data)
    annual_rate = avg_rate * 8 * 365 * 100

    print(f"\n  费率统计:")
    print(f"    • 平均费率: {avg_rate:.6f} ({avg_rate*100:.4f}%)")
    print(f"    • 年化费率: {annual_rate:.2f}%")

    # 前5条记录示例
    print(f"\n【数据示例】（前3条）")
    for i, record in enumerate(funding_data[:3]):
        ts = record['time']
        dt = datetime.fromtimestamp(ts / 1000)
        delta = record['delta']

        print(f"\n  --- 记录 {i+1} ({dt.strftime('%Y-%m-%d %H:%M:%S')}) ---")
        print(f"  币种: {delta['coin']}")
        print(f"  持仓: {delta['szi']}")
        print(f"  费用: {delta['usdc']} USDC")
        print(f"  费率: {delta['fundingRate']}")

    # 统计信息
    stats = client.get_stats()
    print(f"\n【API 统计】")
    print(f"  总请求数: {stats['total_requests']}")
    print(f"  缓存命中: {stats['cache_hits']}")
    print(f"  命中率: {stats['cache_hit_rate']:.1%}")
    print(f"  错误次数: {stats['api_errors']}")

    # 清理
    await store.close()

    print("\n" + "=" * 80)
    print("✅ 测试完成")
    print("=" * 80)


if __name__ == '__main__':
    asyncio.run(test_user_funding())

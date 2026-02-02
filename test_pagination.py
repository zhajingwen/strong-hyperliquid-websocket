#!/usr/bin/env python3
"""
测试分页获取功能
"""

import asyncio
import logging
from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.data_store import get_store

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


async def test_pagination():
    """测试完整交易历史获取"""
    print("\n" + "="*60)
    print("测试分页获取完整交易历史")
    print("="*60 + "\n")

    # 初始化
    store = get_store()
    await store.connect()

    client = HyperliquidAPIClient(
        store=store,
        max_concurrent=3,
        rate_limit=15
    )

    # 测试一个活跃地址
    test_addr = "0xc1914d36f97dc5557e4df26cbdab98e9c988ef37"

    print(f"测试地址: {test_addr}\n")
    print("正在获取完整交易历史（支持分页）...\n")

    # 获取完整历史
    fills = await client.get_user_fills(test_addr, use_cache=False)

    print(f"\n{'='*60}")
    print(f"结果统计")
    print(f"{'='*60}")
    print(f"总交易记录: {len(fills)} 条")

    if fills:
        # 时间范围
        times = [f.get('time', 0) for f in fills]
        from datetime import datetime
        earliest = datetime.fromtimestamp(min(times) / 1000)
        latest = datetime.fromtimestamp(max(times) / 1000)

        print(f"最早交易: {earliest}")
        print(f"最新交易: {latest}")
        print(f"时间跨度: {(latest - earliest).days} 天")

        # 前5笔和后5笔
        print(f"\n前5笔交易:")
        for i, fill in enumerate(sorted(fills, key=lambda x: x.get('time', 0))[:5], 1):
            t = datetime.fromtimestamp(fill.get('time', 0) / 1000)
            print(f"  {i}. {t} - {fill.get('coin')} {fill.get('side')} @ ${fill.get('px')}")

        print(f"\n最后5笔交易:")
        for i, fill in enumerate(sorted(fills, key=lambda x: x.get('time', 0), reverse=True)[:5], 1):
            t = datetime.fromtimestamp(fill.get('time', 0) / 1000)
            print(f"  {i}. {t} - {fill.get('coin')} {fill.get('side')} @ ${fill.get('px')}")

    # 统计
    stats = client.get_stats()
    print(f"\nAPI统计:")
    print(f"  总请求: {stats['total_requests']}")
    print(f"  缓存命中: {stats['cache_hits']}")
    print(f"  错误: {stats['api_errors']}")

    await store.close()


if __name__ == '__main__':
    asyncio.run(test_pagination())

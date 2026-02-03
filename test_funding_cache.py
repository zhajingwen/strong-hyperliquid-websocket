"""
测试资金费率缓存功能
"""
import asyncio
import logging
import time
from address_analyzer.data_store import get_store
from address_analyzer.api_client import HyperliquidAPIClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_funding_cache():
    """测试资金费率缓存功能"""
    # 初始化数据存储
    store = get_store()
    await store.connect()

    # 创建 API 客户端
    client = HyperliquidAPIClient(store, cache_ttl_hours=1)

    # 测试地址
    test_address = "0xc1914d36a60e299ba004bac2c9edcb973c988ef7"

    print(f"\n{'='*70}")
    print(f"资金费率缓存功能测试")
    print(f"{'='*70}")
    print(f"测试地址: {test_address}\n")

    # ============ 测试 1: 首次请求（无缓存）============
    print("📌 测试 1: 首次请求（应该从 API 获取）")
    start_time_1 = time.time()
    funding_1 = await client.get_user_funding(test_address, use_cache=True)
    elapsed_1 = time.time() - start_time_1

    print(f"   ✓ 获取 {len(funding_1)} 条资金费率记录")
    print(f"   ⏱️  耗时: {elapsed_1:.2f} 秒")
    print(f"   📊 统计: {client.get_stats()}\n")

    # ============ 测试 2: 第二次请求（应该命中缓存）============
    print("📌 测试 2: 第二次请求（应该命中缓存）")
    start_time_2 = time.time()
    funding_2 = await client.get_user_funding(test_address, use_cache=True)
    elapsed_2 = time.time() - start_time_2

    print(f"   ✓ 获取 {len(funding_2)} 条资金费率记录")
    print(f"   ⏱️  耗时: {elapsed_2:.2f} 秒")
    print(f"   📊 统计: {client.get_stats()}")

    # 验证缓存效果
    speedup = elapsed_1 / elapsed_2 if elapsed_2 > 0 else 0
    print(f"   🚀 加速比: {speedup:.1f}x")
    print(f"   {'✅ 缓存生效' if speedup > 5 else '⚠️  缓存可能未生效'}\n")

    # ============ 测试 3: 禁用缓存 ============
    print("📌 测试 3: 禁用缓存（强制从 API 获取）")
    start_time_3 = time.time()
    funding_3 = await client.get_user_funding(test_address, use_cache=False)
    elapsed_3 = time.time() - start_time_3

    print(f"   ✓ 获取 {len(funding_3)} 条资金费率记录")
    print(f"   ⏱️  耗时: {elapsed_3:.2f} 秒")
    print(f"   📊 统计: {client.get_stats()}\n")

    # ============ 测试 4: 数据一致性验证 ============
    print("📌 测试 4: 数据一致性验证")
    print(f"   首次请求记录数: {len(funding_1)}")
    print(f"   缓存请求记录数: {len(funding_2)}")
    print(f"   强制刷新记录数: {len(funding_3)}")

    if len(funding_1) == len(funding_2) == len(funding_3):
        print(f"   ✅ 数据一致性验证通过\n")
    else:
        print(f"   ⚠️  数据数量不一致\n")

    # ============ 测试 5: 分页功能测试 ============
    print("📌 测试 5: 分页功能测试")
    print("   测试禁用分页 vs 启用分页...")

    # 清除缓存
    cache_key = f"user_funding:{test_address}:0:None"
    await store.delete_api_cache(cache_key)

    # 禁用分页
    funding_no_page = await client.get_user_funding(
        test_address,
        use_cache=False,
        enable_pagination=False
    )

    # 清除缓存
    await store.delete_api_cache(cache_key)

    # 启用分页
    funding_with_page = await client.get_user_funding(
        test_address,
        use_cache=False,
        enable_pagination=True
    )

    print(f"   禁用分页: {len(funding_no_page)} 条")
    print(f"   启用分页: {len(funding_with_page)} 条")

    if len(funding_with_page) >= len(funding_no_page):
        print(f"   ✅ 分页功能正常（获取更多或相同数量的数据）\n")
    else:
        print(f"   ⚠️  分页功能可能有问题\n")

    # ============ 最终统计 ============
    final_stats = client.get_stats()
    print(f"{'='*70}")
    print(f"最终统计")
    print(f"{'='*70}")
    print(f"总请求数: {final_stats['total_requests']}")
    print(f"缓存命中: {final_stats['cache_hits']}")
    print(f"命中率: {final_stats['cache_hit_rate']:.1%}")
    print(f"API错误: {final_stats['api_errors']}")

    # 示例数据展示
    if funding_1:
        print(f"\n{'='*70}")
        print(f"示例数据（前3条）")
        print(f"{'='*70}")
        for i, record in enumerate(funding_1[:3]):
            print(f"{i+1}. 时间: {record.get('time')}, "
                  f"币种: {record.get('coin')}, "
                  f"费率: {record.get('fundingRate')}, "
                  f"金额: {record.get('usdc')}")

    # 关闭连接
    await store.close()
    print(f"\n✅ 测试完成！")


if __name__ == '__main__':
    asyncio.run(test_funding_cache())

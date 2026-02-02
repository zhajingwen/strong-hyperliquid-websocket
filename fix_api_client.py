#!/usr/bin/env python3
"""
修复后的分页逻辑 - 正确处理 user_fills_by_time 返回最旧数据的行为
"""

import asyncio
import logging
from hyperliquid.info import Info
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def format_time(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


async def get_user_fills_correct(address: str, info: Info) -> list:
    """
    修复后的完整分页逻辑

    策略：从旧到新逐步获取，避免数据丢失

    工作原理：
    1. 先用 user_fills() 获取最新的 2000 条 → 确定最早时间 oldest_time
    2. 然后从 start_time=0 开始，逐步向新获取，直到接近 oldest_time
    3. 确保没有数据丢失
    """
    all_fills = []
    page_size = 2000

    # 第1步：获取最新的记录
    logger.info("第1步：获取最新记录...")
    latest_fills = info.user_fills(address)

    if not latest_fills:
        logger.info("无交易记录")
        return []

    all_fills.extend(latest_fills)
    latest_count = len(latest_fills)

    # 最新批次的时间范围
    latest_min_time = min(f.get('time', 0) for f in latest_fills)
    latest_max_time = max(f.get('time', 0) for f in latest_fills)

    logger.info(f"  获取最新 {latest_count} 条")
    logger.info(f"  时间范围: {format_time(latest_min_time)} → {format_time(latest_max_time)}")

    # 如果记录少于 2000，说明已经是全部数据
    if latest_count < page_size:
        logger.info(f"✅ 总记录数 < {page_size}，无需分页")
        return all_fills

    # 第2步：向前分页获取更早的数据
    logger.info(f"\n第2步：向前分页获取更早的数据...")
    logger.info(f"  目标：填充 [0, {latest_min_time - 1}] 区间\n")

    # 从 start_time=0 开始，逐步向新推进
    current_start_time = 0
    target_end_time = latest_min_time - 1  # 到最新批次的前一毫秒

    page_num = 2
    historical_fills = []  # 存储历史数据（从旧到新）

    while current_start_time <= target_end_time:
        logger.info(f"第{page_num}页: 查询 [{format_time(current_start_time)}, {format_time(target_end_time)}]")

        older_fills = info.user_fills_by_time(
            address,
            start_time=current_start_time,
            end_time=target_end_time
        )

        if not older_fills:
            logger.info(f"  ✅ 无更多数据")
            break

        # 这批数据的时间范围
        batch_min_time = min(f.get('time', 0) for f in older_fills)
        batch_max_time = max(f.get('time', 0) for f in older_fills)

        logger.info(f"  获取 {len(older_fills)} 条")
        logger.info(f"  范围: {format_time(batch_min_time)} → {format_time(batch_max_time)}")

        # 添加到历史数据（从旧到新的顺序）
        historical_fills.extend(older_fills)

        # 如果这批数据少于 2000，说明已经获取完了
        if len(older_fills) < page_size:
            logger.info(f"  ✅ 已获取完整区间数据（返回 < {page_size} 条）")
            break

        # 更新 start_time 为这批数据的最新时间+1
        current_start_time = batch_max_time + 1

        # 检查是否已经接近目标时间
        if current_start_time > target_end_time:
            logger.info(f"  ✅ 已到达目标时间")
            break

        page_num += 1

        # 避免无限循环
        if page_num > 100:
            logger.warning(f"  ⚠️  达到最大分页限制 (100页)")
            break

    # 合并数据：历史数据（旧→新）+ 最新数据（旧→新）
    # 注意：需要确保时间顺序正确
    all_fills_sorted = historical_fills + all_fills

    logger.info(f"\n✅ 获取完整交易记录:")
    logger.info(f"  历史数据: {len(historical_fills)} 条")
    logger.info(f"  最新数据: {latest_count} 条")
    logger.info(f"  总计: {len(all_fills_sorted)} 条")

    # 验证数据完整性
    if all_fills_sorted:
        all_times = [f.get('time', 0) for f in all_fills_sorted]
        final_min = min(all_times)
        final_max = max(all_times)

        logger.info(f"\n数据范围:")
        logger.info(f"  最早: {format_time(final_min)}")
        logger.info(f"  最新: {format_time(final_max)}")
        logger.info(f"  跨度: {(final_max - final_min) / 1000 / 3600:.2f} 小时")

        # 检查是否有时间重叠或断层
        sorted_times = sorted(all_times)
        max_gap = 0
        max_gap_idx = 0
        for i in range(len(sorted_times) - 1):
            gap = sorted_times[i + 1] - sorted_times[i]
            if gap > max_gap:
                max_gap = gap
                max_gap_idx = i

        if max_gap > 3600000:  # 1小时
            logger.warning(f"  ⚠️  发现大时间间隔: {max_gap / 1000 / 3600:.2f} 小时")
            logger.warning(f"     位置: {format_time(sorted_times[max_gap_idx])} → {format_time(sorted_times[max_gap_idx + 1])}")

    return all_fills_sorted


async def test_correct_pagination():
    """测试修复后的分页逻辑"""
    print("=" * 80)
    print("测试修复后的分页逻辑")
    print("=" * 80 + "\n")

    info = Info(skip_ws=True)
    test_address = "0xc1914d36f97dc5557e4df26cbdab98e9c988ef37"

    print(f"测试地址: {test_address}\n")

    # 使用修复后的逻辑
    all_fills = await get_user_fills_correct(test_address, info)

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)
    print(f"\n总记录数: {len(all_fills)}")


if __name__ == '__main__':
    asyncio.run(test_correct_pagination())

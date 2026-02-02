#!/usr/bin/env python3
"""
调查时间断层问题：为什么第1批和第2批之间有 36 小时的时间差？
"""

import asyncio
from hyperliquid.info import Info
from datetime import datetime


def format_time(timestamp_ms):
    """格式化时间戳"""
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')


async def test_time_gap():
    """测试时间断层"""
    print("=" * 80)
    print("调查时间断层问题")
    print("=" * 80)

    info = Info(skip_ws=True)
    test_address = "0xc1914d36f97dc5557e4df26cbdab98e9c988ef37"

    # 第1批：最新数据
    print("\n第1批：user_fills()")
    fills1 = info.user_fills(test_address)
    time1_min = min(f.get('time', 0) for f in fills1)
    time1_max = max(f.get('time', 0) for f in fills1)
    print(f"  记录数: {len(fills1)}")
    print(f"  时间范围: {format_time(time1_min)} → {format_time(time1_max)}")
    print(f"  最早时间戳: {time1_min}")

    # 第2批：end_time = time1_min - 1
    print(f"\n第2批：user_fills_by_time(0, {time1_min - 1})")
    fills2 = info.user_fills_by_time(test_address, 0, time1_min - 1)

    if not fills2:
        print("  ❌ 无数据返回")
        return

    time2_min = min(f.get('time', 0) for f in fills2)
    time2_max = max(f.get('time', 0) for f in fills2)
    print(f"  记录数: {len(fills2)}")
    print(f"  时间范围: {format_time(time2_min)} → {format_time(time2_max)}")
    print(f"  最新时间戳: {time2_max}")

    # 计算时间断层
    gap_ms = time1_min - time2_max
    gap_hours = gap_ms / 1000 / 3600
    print(f"\n⚠️  时间断层:")
    print(f"  第1批最早: {time1_min} ({format_time(time1_min)})")
    print(f"  第2批最新: {time2_max} ({format_time(time2_max)})")
    print(f"  断层大小: {gap_ms} ms = {gap_hours:.2f} 小时")

    # 测试1：查询断层区间内是否有数据
    print(f"\n" + "=" * 80)
    print("测试1：查询断层区间是否有数据")
    print("=" * 80)

    gap_fills = info.user_fills_by_time(
        test_address,
        start_time=time2_max + 1,  # 从第2批最新时间开始
        end_time=time1_min - 1      # 到第1批最早时间
    )

    print(f"\nuser_fills_by_time({time2_max + 1}, {time1_min - 1})")
    print(f"查询时间范围: {format_time(time2_max + 1)} → {format_time(time1_min - 1)}")
    print(f"返回记录数: {len(gap_fills)}")

    if gap_fills:
        gap_min = min(f.get('time', 0) for f in gap_fills)
        gap_max = max(f.get('time', 0) for f in gap_fills)
        print(f"实际时间范围: {format_time(gap_min)} → {format_time(gap_max)}")
        print(f"\n✅ 断层区间内有数据！说明第2批没有返回这部分数据")

        # 打印前5条记录
        print(f"\n前5条记录的时间:")
        for i, fill in enumerate(sorted(gap_fills, key=lambda x: x.get('time', 0))[:5], 1):
            t = fill.get('time', 0)
            print(f"  {i}. {format_time(t)} ({t})")
    else:
        print(f"\n⚠️  断层区间内无数据，可能该时间段真的没有交易")

    # 测试2：查看第2批数据的排序
    print(f"\n" + "=" * 80)
    print("测试2：分析第2批数据的排序规律")
    print("=" * 80)

    print(f"\n第2批前10条记录（按返回顺序）:")
    for i, fill in enumerate(fills2[:10], 1):
        t = fill.get('time', 0)
        print(f"  {i}. {format_time(t)} ({t})")

    print(f"\n第2批后10条记录（按返回顺序）:")
    for i, fill in enumerate(fills2[-10:], -10):
        t = fill.get('time', 0)
        print(f"  {i}. {format_time(t)} ({t})")

    # 测试3：检查第2批是否按时间排序
    times2 = [f.get('time', 0) for f in fills2]
    is_ascending = all(times2[i] <= times2[i+1] for i in range(len(times2)-1))
    is_descending = all(times2[i] >= times2[i+1] for i in range(len(times2)-1))

    print(f"\n第2批排序规律:")
    print(f"  升序（从旧到新）: {is_ascending}")
    print(f"  降序（从新到旧）: {is_descending}")
    print(f"  无序: {not is_ascending and not is_descending}")

    # 测试4：检查时间分布
    print(f"\n" + "=" * 80)
    print("测试4：第2批时间分布分析")
    print("=" * 80)

    # 按时间排序
    fills2_sorted = sorted(fills2, key=lambda x: x.get('time', 0))
    times_sorted = [f.get('time', 0) for f in fills2_sorted]

    # 找出最大时间跳跃
    max_gap = 0
    max_gap_idx = 0
    for i in range(len(times_sorted) - 1):
        gap = times_sorted[i+1] - times_sorted[i]
        if gap > max_gap:
            max_gap = gap
            max_gap_idx = i

    print(f"\n第2批内部最大时间跳跃:")
    print(f"  位置: {max_gap_idx} → {max_gap_idx + 1}")
    print(f"  时间: {format_time(times_sorted[max_gap_idx])} → {format_time(times_sorted[max_gap_idx + 1])}")
    print(f"  跳跃: {max_gap} ms = {max_gap / 1000 / 60:.2f} 分钟")

    print("\n" + "=" * 80)
    print("总结")
    print("=" * 80)

    if gap_fills:
        print(f"\n❌ API 行为异常：")
        print(f"   - 请求时间范围: [0, {time1_min - 1}]")
        print(f"   - 实际返回范围: [{time2_min}, {time2_max}]")
        print(f"   - 缺失范围: [{time2_max + 1}, {time1_min - 1}]")
        print(f"   - 缺失数据量: {len(gap_fills)} 条")
        print(f"\n🤔 可能原因:")
        print(f"   1. API 返回的是某个特定时间窗口的数据")
        print(f"   2. API 有其他的排序/过滤逻辑")
        print(f"   3. API 有额外的限制条件")
    else:
        print(f"\n✅ 断层区间内确实没有交易数据")
        print(f"   该用户在 {format_time(time2_max)} 到 {format_time(time1_min)} 期间没有交易")


if __name__ == '__main__':
    asyncio.run(test_time_gap())

#!/usr/bin/env python3
"""
测试 API 的真实返回逻辑
"""

import asyncio
from hyperliquid.info import Info
from datetime import datetime


def format_time(timestamp_ms):
    """格式化时间戳"""
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')


async def test_api_logic():
    """测试 API 返回逻辑"""
    print("=" * 80)
    print("测试 user_fills_by_time API 的真实返回逻辑")
    print("=" * 80)

    info = Info(skip_ws=True)
    test_address = "0xc1914d36f97dc5557e4df26cbdab98e9c988ef37"

    # 获取一个已知的时间范围
    fills1 = info.user_fills(test_address)
    time1_min = min(f.get('time', 0) for f in fills1)
    time1_max = max(f.get('time', 0) for f in fills1)

    print(f"\n参考数据（user_fills）:")
    print(f"  时间范围: [{time1_min}, {time1_max}]")
    print(f"  可读时间: {format_time(time1_min)} → {format_time(time1_max)}")

    # 测试1：查询整个范围
    print(f"\n" + "=" * 80)
    print("测试1：查询整个已知范围")
    print("=" * 80)

    test1 = info.user_fills_by_time(test_address, time1_min, time1_max)
    if test1:
        t1_min = min(f.get('time', 0) for f in test1)
        t1_max = max(f.get('time', 0) for f in test1)
        print(f"查询: user_fills_by_time({time1_min}, {time1_max})")
        print(f"返回: {len(test1)} 条")
        print(f"范围: [{t1_min}, {t1_max}]")
        print(f"可读: {format_time(t1_min)} → {format_time(t1_max)}")

    # 测试2：查询从0到某个时间点
    print(f"\n" + "=" * 80)
    print("测试2：查询从0到某个时间点")
    print("=" * 80)

    test2 = info.user_fills_by_time(test_address, 0, time1_max)
    if test2:
        t2_min = min(f.get('time', 0) for f in test2)
        t2_max = max(f.get('time', 0) for f in test2)
        print(f"查询: user_fills_by_time(0, {time1_max})")
        print(f"返回: {len(test2)} 条")
        print(f"范围: [{t2_min}, {t2_max}]")
        print(f"可读: {format_time(t2_min)} → {format_time(t2_max)}")

        # 分析：是贴近 start_time 还是 end_time？
        dist_to_start = t2_min - 0
        dist_to_end = time1_max - t2_max

        print(f"\n分析:")
        print(f"  到 start_time(0) 的距离: {dist_to_start} ms")
        print(f"  到 end_time({time1_max}) 的距离: {dist_to_end} ms")

        if dist_to_end < dist_to_start:
            print(f"  ✅ 贴近 end_time（前面被截断）")
        else:
            print(f"  ✅ 贴近 start_time（后面被截断）")

    # 测试3：多次查询不同的 end_time
    print(f"\n" + "=" * 80)
    print("测试3：逐步减小 end_time，观察返回数据的变化")
    print("=" * 80)

    # 获取一个基准时间
    base_time = time1_max

    for i in range(3):
        offset = i * 10000000  # 每次减少约 2.78 小时
        end_time = base_time - offset

        test = info.user_fills_by_time(test_address, 0, end_time)
        if test:
            t_min = min(f.get('time', 0) for f in test)
            t_max = max(f.get('time', 0) for f in test)

            print(f"\n查询 {i+1}:")
            print(f"  end_time: {end_time} ({format_time(end_time)})")
            print(f"  返回: {len(test)} 条")
            print(f"  范围: {format_time(t_min)} → {format_time(t_max)}")
            print(f"  最新时间: {t_max}")

            if t_max <= end_time:
                print(f"  ✅ 最新时间 <= end_time（符合预期）")
            else:
                print(f"  ❌ 最新时间 > end_time（异常！）")

    # 测试4：测试 start_time 的影响
    print(f"\n" + "=" * 80)
    print("测试4：固定 end_time，逐步增大 start_time")
    print("=" * 80)

    end_time_fixed = time1_max

    for i in range(3):
        start_time = time1_min + i * 5000000  # 每次增加约 1.39 小时

        test = info.user_fills_by_time(test_address, start_time, end_time_fixed)
        if test:
            t_min = min(f.get('time', 0) for f in test)
            t_max = max(f.get('time', 0) for f in test)

            print(f"\n查询 {i+1}:")
            print(f"  start_time: {start_time} ({format_time(start_time)})")
            print(f"  返回: {len(test)} 条")
            print(f"  范围: {format_time(t_min)} → {format_time(t_max)}")

            if t_min >= start_time:
                print(f"  ✅ 最早时间 >= start_time（符合预期）")
            else:
                print(f"  ❌ 最早时间 < start_time（异常！）")

    print("\n" + "=" * 80)


if __name__ == '__main__':
    asyncio.run(test_api_logic())

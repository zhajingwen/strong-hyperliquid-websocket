#!/usr/bin/env python3
"""
测试 user_fills_by_time API 的返回行为
验证：当数据量超过2000条时，返回的是贴近 start_time 还是 end_time 的数据
"""

import asyncio
from hyperliquid.info import Info
from datetime import datetime


def print_time_range(fills, label):
    """打印交易记录的时间范围"""
    if not fills:
        print(f"{label}: 无数据")
        return

    times = [f.get('time', 0) for f in fills]
    min_time = min(times)
    max_time = max(times)

    min_dt = datetime.fromtimestamp(min_time / 1000)
    max_dt = datetime.fromtimestamp(max_time / 1000)

    print(f"\n{label}:")
    print(f"  记录数: {len(fills)}")
    print(f"  最早时间: {min_dt} (timestamp: {min_time})")
    print(f"  最新时间: {max_dt} (timestamp: {max_time})")
    print(f"  时间跨度: {(max_time - min_time) / 1000 / 3600:.2f} 小时")

    # 打印前3条和后3条的时间（按原始顺序）
    print(f"  前3条时间戳: {[f.get('time') for f in fills[:3]]}")
    print(f"  后3条时间戳: {[f.get('time') for f in fills[-3:]]}")


async def test_api_behavior():
    """测试 API 返回行为"""
    print("=" * 80)
    print("测试 user_fills_by_time API 行为")
    print("=" * 80)

    # 初始化客户端
    info = Info(skip_ws=True)

    # 使用一个活跃地址（有足够多的交易记录）
    test_address = "0xc1914d36f97dc5557e4df26cbdab98e9c988ef37"

    print(f"\n测试地址: {test_address}")

    # 第1步：获取最新的交易记录
    print("\n" + "=" * 80)
    print("第1步：调用 user_fills() 获取最新记录")
    print("=" * 80)

    fills_latest = info.user_fills(test_address)
    print_time_range(fills_latest, "user_fills() 返回")

    if len(fills_latest) < 2000:
        print("\n⚠️  交易记录少于2000条，无法测试分页行为")
        return

    # 获取最早的时间戳
    oldest_time = min(f.get('time', 0) for f in fills_latest)
    print(f"\n从 user_fills() 中提取的 oldest_time: {oldest_time}")
    print(f"对应日期: {datetime.fromtimestamp(oldest_time / 1000)}")

    # 第2步：测试 user_fills_by_time 的返回行为
    print("\n" + "=" * 80)
    print(f"第2步：调用 user_fills_by_time(start_time=0, end_time={oldest_time - 1})")
    print("=" * 80)
    print("\n❓ 问题：如果有超过2000条记录，返回的是：")
    print("   方案A：贴近 start_time=0 的最旧 2000 条？")
    print("   方案B：贴近 end_time 的最新 2000 条？")

    older_fills = info.user_fills_by_time(
        test_address,
        start_time=0,
        end_time=oldest_time - 1
    )

    print_time_range(older_fills, f"\nuser_fills_by_time(0, {oldest_time - 1}) 返回")

    # 第3步：分析结果
    print("\n" + "=" * 80)
    print("结论分析")
    print("=" * 80)

    if not older_fills:
        print("\n✅ 无更早的记录，说明已经获取到最早的数据")
    else:
        older_max_time = max(f.get('time', 0) for f in older_fills)
        older_min_time = min(f.get('time', 0) for f in older_fills)

        print(f"\n对比分析:")
        print(f"  第1批（user_fills）最早时间: {oldest_time}")
        print(f"  第2批（user_fills_by_time）最新时间: {older_max_time}")
        print(f"  第2批（user_fills_by_time）最早时间: {older_min_time}")
        print(f"  时间差: {oldest_time - older_max_time} ms")

        # 判断返回行为
        if older_max_time < oldest_time and older_max_time > 0:
            print(f"\n✅ 结论：返回的是 **贴近 end_time 的数据**（前面被截断）")
            print(f"   - 第2批的最新时间 ({older_max_time}) 紧接着第1批的最早时间 ({oldest_time})")
            print(f"   - 这是正确的向前分页获取历史数据的方式")

            if len(older_fills) >= 2000:
                print(f"   - 第2批也有 {len(older_fills)} 条记录，说明还有更早的数据")
                print(f"   - 可以继续用 end_time={older_min_time - 1} 向前获取")
        elif older_min_time == 0 or older_min_time < 1000:
            print(f"\n❌ 结论：返回的是 **贴近 start_time=0 的数据**（后面被截断）")
            print(f"   - 这种情况下，代码逻辑会出现问题")
        else:
            print(f"\n⚠️  无法判断，需要更多数据")

    print("\n" + "=" * 80)


if __name__ == '__main__':
    asyncio.run(test_api_behavior())

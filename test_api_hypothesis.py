#!/usr/bin/env python3
"""
假设：API 可能返回的是 [start_time, end_time] 区间内最旧的 2000 条
"""

import asyncio
from hyperliquid.info import Info
from datetime import datetime


def format_time(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')


async def test_hypothesis():
    """测试假设"""
    print("=" * 80)
    print("假设：user_fills_by_time 返回的是区间内 **最旧的** 2000 条")
    print("=" * 80)

    info = Info(skip_ws=True)
    test_address = "0xc1914d36f97dc5557e4df26cbdab98e9c988ef37"

    # 获取参考数据
    fills1 = info.user_fills(test_address)
    time1_min = min(f.get('time', 0) for f in fills1)

    print(f"\n参考时间: {time1_min} ({format_time(time1_min)})")

    # 测试：逐步增大 start_time，看返回的数据是否会变化
    print(f"\n" + "=" * 80)
    print("测试：固定 end_time，逐步增大 start_time")
    print("=" * 80)
    print("如果 API 返回最旧的 2000 条，那么增大 start_time 应该会跳过前面的数据\n")

    # 固定一个很大的 end_time
    end_time_fixed = time1_min - 1

    # 从 0 开始查询
    print("查询 1: start_time=0")
    test1 = info.user_fills_by_time(test_address, 0, end_time_fixed)
    if test1:
        t1_min = min(f.get('time', 0) for f in test1)
        t1_max = max(f.get('time', 0) for f in test1)
        print(f"  返回: {len(test1)} 条")
        print(f"  范围: {format_time(t1_min)} → {format_time(t1_max)}")
        print(f"  最早: {t1_min}")
        print(f"  最新: {t1_max}")

        # 测试：start_time 设置为第一次查询返回的最新时间+1
        print(f"\n查询 2: start_time={t1_max + 1} (跳过第1批)")
        test2 = info.user_fills_by_time(test_address, t1_max + 1, end_time_fixed)
        if test2:
            t2_min = min(f.get('time', 0) for f in test2)
            t2_max = max(f.get('time', 0) for f in test2)
            print(f"  返回: {len(test2)} 条")
            print(f"  范围: {format_time(t2_min)} → {format_time(t2_max)}")
            print(f"  最早: {t2_min}")
            print(f"  最新: {t2_max}")

            # 验证是否紧接着
            gap = t2_min - t1_max
            print(f"\n  时间间隔: {gap} ms = {gap/1000:.2f} 秒")

            if gap <= 10000:  # 10秒内
                print(f"  ✅ 数据紧接着！说明 API 返回的是 **最旧的 2000 条**")
            else:
                print(f"  ❌ 有时间断层！")

            # 继续查询第3批
            print(f"\n查询 3: start_time={t2_max + 1} (跳过第1、2批)")
            test3 = info.user_fills_by_time(test_address, t2_max + 1, end_time_fixed)
            if test3:
                t3_min = min(f.get('time', 0) for f in test3)
                t3_max = max(f.get('time', 0) for f in test3)
                print(f"  返回: {len(test3)} 条")
                print(f"  范围: {format_time(t3_min)} → {format_time(t3_max)}")
                print(f"  最早: {t3_min}")
                print(f"  最新: {t3_max}")

                gap2 = t3_min - t2_max
                print(f"\n  时间间隔: {gap2} ms = {gap2/1000:.2f} 秒")

        else:
            print(f"  ❌ 无数据返回")

    # 总结
    print(f"\n" + "=" * 80)
    print("结论")
    print("=" * 80)
    print("""
如果以上测试显示：
  ✅ 每次增大 start_time 后，返回的数据紧接着上一批
  → 说明 API 返回的是 [start_time, end_time] 区间内 **最旧的** 2000 条

那么 address_analyzer/api_client.py 中的分页逻辑就是错误的！

正确的逻辑应该是：
  1. 第1次：user_fills() → 最新 2000 条 [A, B]
  2. 第2次：user_fills_by_time(0, A-1) → 最旧 2000 条 [C, D]
  3. 第3次：user_fills_by_time(D+1, A-1) → 接着第2批的 2000 条 [E, F]
  4. ...

而不是：
  ❌ 第3次：user_fills_by_time(0, C-1) ← 会重复返回第2批的数据！
""")


if __name__ == '__main__':
    asyncio.run(test_hypothesis())

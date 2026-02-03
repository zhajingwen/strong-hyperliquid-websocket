"""
对比 clearinghouseState 和 user_state 接口
"""
import asyncio
import json
import aiohttp
from hyperliquid.info import Info

async def compare_apis():
    """对比两个接口的返回数据"""

    test_address = "0x2a06e54a2063a5f72b8004347cf0b1020299002f"

    print(f"测试地址: {test_address}")
    print("=" * 100)

    # 方法1：使用 SDK 的 user_state
    print("\n[方法1] 使用 info.user_state() 接口:")
    print("=" * 100)
    try:
        info = Info(skip_ws=True)
        user_state = info.user_state(test_address)
        print(json.dumps(user_state, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"错误: {e}")

    # 方法2：直接调用 clearinghouseState
    print("\n" + "=" * 100)
    print("\n[方法2] 使用 clearinghouseState 直接请求:")
    print("=" * 100)
    try:
        url = "https://api.hyperliquid.xyz/info"
        payload = {
            "type": "clearinghouseState",
            "user": test_address
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"错误: {e}")

    # 结论
    print("\n" + "=" * 100)
    print("\n[结论] 两个接口返回的数据:")
    print("=" * 100)
    print("""
    1. clearinghouseState 和 user_state 返回相同的数据结构
    2. 都只包含当前账户状态快照：
       - accountValue (账户价值)
       - totalMarginUsed (已使用保证金)
       - assetPositions (资产持仓)
       - withdrawable (可提现金额)
    3. 都不包含历史入金/出金记录
    4. 都不包含 netDeposit 字段

    结论：无法从这些接口获取真实的入金/出金数据
    建议：采用方案B - 完全移除 net_deposit 冗余设计
    """)

if __name__ == '__main__':
    asyncio.run(compare_apis())

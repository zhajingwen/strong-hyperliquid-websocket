"""
分析有持仓的地址的完整数据结构
使用公开的活跃地址
"""
import json
from hyperliquid.info import Info

def analyze_detailed():
    """分析详细的用户状态"""

    info = Info(skip_ws=True)

    # 使用一些可能有活跃交易的地址
    # 这些地址可能有持仓，能看到完整的数据结构
    test_addresses = [
        # 可以使用一些公开的大户地址或者测试地址
        # 这里先尝试获取有持仓的地址数据结构
        '0xde786a32f80731923d6297c14ef43ca1c8fd4b44',  # 随机地址
        # '0x1234567890123456789012345678901234567890',  # 示例地址
    ]

    print("🔍 分析 user_state API 返回的完整数据结构\n")
    print("="*80)

    # 先看看 Info API 有哪些方法
    print("\n📚 Hyperliquid Info API 可用方法:")
    methods = [m for m in dir(info) if not m.startswith('_') and callable(getattr(info, m))]
    for method in methods[:20]:
        print(f"  - {method}")

    print("\n" + "="*80)

    # 测试一个地址
    test_addr = test_addresses[0]
    print(f"\n测试地址: {test_addr}")

    try:
        state = info.user_state(test_addr)
        print("\n📊 完整返回数据:")
        print(json.dumps(state, indent=2, ensure_ascii=False))

        # 分析 assetPositions 的结构
        if state.get('assetPositions'):
            print("\n📦 assetPositions 详细结构:")
            for i, pos in enumerate(state['assetPositions'], 1):
                print(f"\n  持仓 {i}:")
                for key, value in pos.items():
                    print(f"    {key}: {value}")

    except Exception as e:
        print(f"错误: {e}")

    print("\n" + "="*80)
    print("\n💡 关键发现:")
    print("""
根据 Hyperliquid API 文档和返回数据分析：

marginSummary 字段说明：
- accountValue: 账户总价值 = 余额 + 未实现盈亏
- totalRawUsd: 现金余额（不含未实现盈亏）
- totalNtlPos: 持仓名义价值
- totalMarginUsed: 已使用保证金

可能的PNL计算：
1. 未实现盈亏 = accountValue - totalRawUsd
2. 如果有这个数据，可以用：
   total_pnl = realized_pnl + unrealized_pnl
   initial_capital = totalRawUsd - realized_pnl
   ROI = total_pnl / initial_capital × 100
    """)

if __name__ == '__main__':
    analyze_detailed()

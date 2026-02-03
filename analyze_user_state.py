"""
分析 user_state API 返回的数据结构
目的：查找可用于PNL计算的字段
"""
import asyncio
import json
from hyperliquid.info import Info

async def analyze_user_state():
    """分析多个地址的 user_state 数据"""

    # 测试地址列表
    addresses = [
        "0xde786a32f80731923d6297c14ef43ca1c8fd4b44"
    ]

    info = Info(skip_ws=True)

    for i, address in enumerate(addresses, 1):
        print(f"\n{'='*80}")
        print(f"地址 {i}: {address}")
        print('='*80)

        try:
            state = info.user_state(address)
            print(state)

            print("\n📊 完整数据结构:")
            print(json.dumps(state, indent=2, ensure_ascii=False))

            # 分析关键字段
            print("\n🔍 关键字段分析:")

            if 'marginSummary' in state:
                ms = state['marginSummary']
                print("\n1️⃣ marginSummary:")
                for key, value in ms.items():
                    print(f"  - {key}: {value}")

            if 'crossMarginSummary' in state:
                cms = state['crossMarginSummary']
                print("\n2️⃣ crossMarginSummary:")
                for key, value in cms.items():
                    print(f"  - {key}: {value}")

            if 'assetPositions' in state and state['assetPositions']:
                print(f"\n3️⃣ assetPositions ({len(state['assetPositions'])} 个持仓):")
                for j, pos in enumerate(state['assetPositions'], 1):
                    print(f"\n  持仓 {j}:")
                    print(f"    完整数据: {json.dumps(pos, indent=6, ensure_ascii=False)}")
            else:
                print("\n3️⃣ assetPositions: 无持仓")

            # 查找所有可能与PNL相关的字段
            print("\n💡 可能的PNL相关字段:")
            all_keys = []

            def extract_keys(obj, prefix=""):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        full_key = f"{prefix}.{k}" if prefix else k
                        all_keys.append(full_key)
                        if k.lower() in ['pnl', 'profit', 'loss', 'unrealized', 'realized']:
                            print(f"  ✓ {full_key}: {v}")
                        extract_keys(v, full_key)
                elif isinstance(obj, list) and obj:
                    extract_keys(obj[0], f"{prefix}[0]")

            extract_keys(state)

            # 计算分析
            print("\n📐 基于当前数据的可能算法:")
            account_value = float(ms.get('accountValue', 0))
            total_ntl_pos = float(ms.get('totalNtlPos', 0))
            total_raw_usd = float(ms.get('totalRawUsd', 0))

            print(f"  accountValue: ${account_value:,.2f}")
            print(f"  totalNtlPos: ${total_ntl_pos:,.2f}")
            print(f"  totalRawUsd: ${total_raw_usd:,.2f}")

            if account_value > 0:
                print(f"\n  可能的关系:")
                print(f"  - accountValue - totalRawUsd = {account_value - total_raw_usd:,.2f}")
                print(f"  - accountValue - totalNtlPos = {account_value - total_ntl_pos:,.2f}")

        except Exception as e:
            print(f"❌ 错误: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*80)
    print("🎯 总结分析")
    print("="*80)
    print("""
基于以上数据分析，我们可以：
1. 确认哪些字段包含PNL信息
2. 理解字段之间的关系
3. 设计更准确的ROI计算算法
    """)

if __name__ == '__main__':
    asyncio.run(analyze_user_state())

"""
测试 clearinghouseState API 接口
"""
import asyncio
import json
import aiohttp

async def test_clearinghouse_state():
    """测试 clearinghouseState 接口"""

    test_address = "0xfff8dbe7fbe7ae8e0172043491d77402020200cd"

    print(f"测试地址: {test_address}")
    print("=" * 100)

    # 测试 clearinghouseState 接口
    url = "https://api.hyperliquid.xyz/info"
    payload = {
        "type": "clearinghouseState",
        "user": test_address
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                print(f"\nHTTP 状态码: {resp.status}")

                if resp.status == 200:
                    data = await resp.json()

                    print(f"\n返回数据类型: {type(data)}")
                    print("\n" + "=" * 100)
                    print("完整数据结构:")
                    print("=" * 100)
                    print(json.dumps(data, indent=2, ensure_ascii=False))

                    # 分析关键字段
                    print("\n" + "=" * 100)
                    print("关键字段分析:")
                    print("=" * 100)

                    if isinstance(data, dict):
                        print(f"\n顶层键: {list(data.keys())}")

                        # 查找入金/出金相关字段
                        keywords = ['deposit', 'withdraw', 'transfer', 'balance',
                                   'equity', 'margin', 'pnl', 'asset', 'cross',
                                   'account', 'value', 'net']

                        print("\n包含关键字的字段:")
                        for key in data.keys():
                            if any(kw in key.lower() for kw in keywords):
                                print(f"\n  字段: {key}")
                                print(f"    类型: {type(data[key])}")
                                if isinstance(data[key], (str, int, float, bool)):
                                    print(f"    值: {data[key]}")
                                elif isinstance(data[key], dict):
                                    print(f"    子键: {list(data[key].keys())}")
                                elif isinstance(data[key], list):
                                    print(f"    列表长度: {len(data[key])}")
                                    if data[key]:
                                        print(f"    第一个元素类型: {type(data[key][0])}")
                                        if isinstance(data[key][0], dict):
                                            print(f"    第一个元素的键: {list(data[key][0].keys())}")

                        # 递归查找所有字段路径
                        def get_all_paths(obj, prefix=""):
                            """递归获取所有字段路径"""
                            paths = []
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    full_key = f"{prefix}.{k}" if prefix else k
                                    paths.append(full_key)
                                    paths.extend(get_all_paths(v, full_key))
                            elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
                                paths.extend(get_all_paths(obj[0], f"{prefix}[0]"))
                            return paths

                        all_paths = get_all_paths(data)
                        print(f"\n所有字段路径 (共 {len(all_paths)} 个):")
                        for path in all_paths[:50]:  # 显示前50个
                            print(f"  - {path}")
                        if len(all_paths) > 50:
                            print(f"  ... 还有 {len(all_paths) - 50} 个字段")

                        # 查找包含关键字的路径
                        print("\n包含关键字的路径:")
                        relevant_paths = [p for p in all_paths if any(kw in p.lower() for kw in keywords)]
                        for path in relevant_paths:
                            print(f"  ✓ {path}")

                else:
                    error_text = await resp.text()
                    print(f"错误响应: {error_text}")

    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(test_clearinghouse_state())

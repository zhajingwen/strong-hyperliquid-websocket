#!/usr/bin/env python3
"""
修复爆仓检测：
1. 添加 liquidation 字段到数据库
2. 清除指定地址的缓存数据
3. 重新获取数据（包含 liquidation 字段）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from address_analyzer.data_store import get_store
from address_analyzer.api_client import HyperliquidAPIClient


async def fix_liquidation(address: str = None):
    """修复爆仓检测"""

    print("=" * 80)
    print("🔧 修复爆仓检测")
    print("=" * 80)

    # 1. 连接数据库并执行迁移
    store = get_store()
    await store.connect()

    print("\n【步骤1】检查/添加 liquidation 字段...")
    try:
        async with store.pool.acquire() as conn:
            # 检查字段是否存在
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'fills' AND column_name = 'liquidation'
                )
            """)

            if exists:
                print("  ✅ liquidation 字段已存在")
            else:
                # 添加字段
                await conn.execute("ALTER TABLE fills ADD COLUMN liquidation JSONB")
                print("  ✅ 已添加 liquidation 字段")

            # 创建索引
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fills_liquidation
                ON fills ((liquidation IS NOT NULL))
                WHERE liquidation IS NOT NULL
            """)
            print("  ✅ 索引已创建/确认")

    except Exception as e:
        print(f"  ❌ 数据库迁移失败: {e}")
        await store.close()
        return

    # 2. 如果指定了地址，清除该地址的缓存并重新获取
    if address:
        print(f"\n【步骤2】清除地址 {address} 的缓存...")

        try:
            async with store.pool.acquire() as conn:
                # 删除该地址的 fills 数据（强制重新获取）
                result = await conn.execute(
                    "DELETE FROM fills WHERE address = $1",
                    address
                )
                print(f"  ✅ 已删除旧的 fills 数据")

                # 删除数据新鲜度标记
                await conn.execute(
                    "DELETE FROM data_freshness WHERE address = $1 AND data_type = 'fills'",
                    address
                )
                print(f"  ✅ 已清除新鲜度标记")

        except Exception as e:
            print(f"  ❌ 清除缓存失败: {e}")

        # 3. 重新获取数据
        print(f"\n【步骤3】重新获取 {address} 的交易数据...")

        client = HyperliquidAPIClient(
            store=store,
            max_concurrent=5,
            rate_limit=10.0
        )

        try:
            fills = await client.get_user_fills(address, incremental=False)
            print(f"  ✅ 获取 {len(fills)} 条记录")

            # 检查爆仓记录
            liquidations = [f for f in fills if f.get('liquidation')]
            if liquidations:
                print(f"\n  ⚠️  发现 {len(liquidations)} 笔爆仓记录:")
                for liq in liquidations:
                    print(f"    - {liq.get('coin')}: ${float(liq.get('closedPnl', 0)):,.2f}")
            else:
                print(f"\n  ✅ 未发现爆仓记录")

        except Exception as e:
            print(f"  ❌ 获取数据失败: {e}")

        # 4. 验证数据库中的 liquidation 字段
        print(f"\n【步骤4】验证数据库存储...")

        try:
            async with store.pool.acquire() as conn:
                # 查询有 liquidation 的记录
                rows = await conn.fetch("""
                    SELECT coin, closed_pnl, liquidation
                    FROM fills
                    WHERE address = $1 AND liquidation IS NOT NULL
                """, address)

                if rows:
                    print(f"  ✅ 数据库中有 {len(rows)} 条爆仓记录:")
                    for row in rows:
                        print(f"    - {row['coin']}: ${float(row['closed_pnl']):,.2f}")
                        print(f"      liquidation: {row['liquidation']}")
                else:
                    print(f"  ✅ 数据库中无爆仓记录（或该地址无爆仓）")

        except Exception as e:
            print(f"  ❌ 验证失败: {e}")

    await store.close()
    print("\n" + "=" * 80)
    print("✅ 修复完成")
    print("=" * 80)


async def main():
    default_address = "0x324f74880ccee9a05282614d3f80c09831a36774"

    if len(sys.argv) > 1:
        address = sys.argv[1]
    else:
        print("用法:")
        print("  python fix_liquidation.py                    # 仅添加字段")
        print("  python fix_liquidation.py <address>          # 添加字段并刷新指定地址")
        print(f"\n默认测试地址: {default_address}")
        address = input(f"\n请输入地址 (直接回车使用默认地址，输入 'n' 仅添加字段): ").strip()

        if address.lower() == 'n':
            address = None
        elif not address:
            address = default_address

    await fix_liquidation(address)


if __name__ == "__main__":
    asyncio.run(main())

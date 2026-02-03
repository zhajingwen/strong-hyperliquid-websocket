"""
从数据库中找有交易记录的地址
"""
import asyncio
from address_analyzer.data_store import get_store

async def find_active_addresses():
    """找到有交易记录的地址"""
    store = get_store()
    await store.connect()

    try:
        # 查找有交易记录的地址
        query = """
        SELECT DISTINCT address
        FROM user_fills
        LIMIT 10
        """
        rows = await store.pool.fetch(query)

        print(f"找到 {len(rows)} 个有交易记录的地址:")
        for row in rows:
            print(f"  - {row['address']}")

        return [row['address'] for row in rows]

    finally:
        await store.close()

if __name__ == '__main__':
    addresses = asyncio.run(find_active_addresses())

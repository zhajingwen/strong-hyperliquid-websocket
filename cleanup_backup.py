#!/usr/bin/env python3
"""
清理备份表 fills_old

运行前请确保：
1. 新的 fills 表工作正常
2. analyze_addresses.py 运行无误
3. 数据已验证完整
"""
import asyncio
import asyncpg
import os


async def cleanup():
    """删除备份表"""
    db_config = {
        'user': os.getenv('TIMESCALEDB_USER', 'postgres'),
        'password': os.getenv('TIMESCALEDB_PASSWORD', 'postgres'),
        'host': os.getenv('TIMESCALEDB_HOST', '127.0.0.1'),
        'port': int(os.getenv('TIMESCALEDB_PORT', 5432)),
        'database': os.getenv('TIMESCALEDB_DATABASE', 'hyperliquid_analysis')
    }

    print("=" * 60)
    print("清理备份表")
    print("=" * 60)

    try:
        conn = await asyncpg.connect(**db_config)

        # 检查表是否存在
        old_exists = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'fills_old'
            )
        """)

        if not old_exists:
            print("\n✅ fills_old 表不存在，无需清理")
            await conn.close()
            return True

        # 获取表大小
        old_count = await conn.fetchval("SELECT COUNT(*) FROM fills_old")
        old_size = await conn.fetchval("""
            SELECT pg_size_pretty(pg_total_relation_size('fills_old'::regclass))
        """)

        new_count = await conn.fetchval("SELECT COUNT(*) FROM fills")

        print(f"\n📊 当前状态:")
        print(f"   fills_old: {old_count:,} 条记录, {old_size}")
        print(f"   fills: {new_count:,} 条记录")

        # 确认删除
        print(f"\n⚠️  确认删除 fills_old 表？")
        print(f"   此操作不可恢复！")
        print(f"\n   输入 'yes' 确认删除: ", end='')

        import sys
        if sys.stdin.isatty():
            response = input()
            if response.lower() != 'yes':
                print("\n❌ 已取消")
                await conn.close()
                return False

        # 删除表
        print("\n🗑️  删除 fills_old...")
        await conn.execute("DROP TABLE fills_old CASCADE")
        print("   ✓ 已删除")

        print("\n✅ 清理完成")

        await conn.close()
        return True

    except Exception as e:
        print(f"\n❌ 清理失败: {e}")
        return False


if __name__ == '__main__':
    success = asyncio.run(cleanup())
    exit(0 if success else 1)

#!/usr/bin/env python3
"""
修复 fills 表 - 使用序列生成 id，主键为 (time, id)
"""
import asyncio
import asyncpg
import os
from datetime import datetime


async def fix_fills_table():
    """修复 fills 表结构"""
    db_config = {
        'user': os.getenv('TIMESCALEDB_USER', 'postgres'),
        'password': os.getenv('TIMESCALEDB_PASSWORD', 'postgres'),
        'host': os.getenv('TIMESCALEDB_HOST', '127.0.0.1'),
        'port': int(os.getenv('TIMESCALEDB_PORT', 5432)),
        'database': os.getenv('TIMESCALEDB_DATABASE', 'hyperliquid_analysis'),
        'command_timeout': 600
    }

    print("=" * 60)
    print("修复 fills 表结构（使用序列生成 ID）")
    print("=" * 60)

    try:
        print("\n📡 连接数据库...")
        conn = await asyncpg.connect(**db_config)
        print("   ✓ 连接成功")

        # 检查当前状态
        print("\n1️⃣  检查当前状态...")

        # 检查是否有 fills 表
        fills_exists = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'fills'
            )
        """)

        # 检查是否有 fills_old 表
        old_exists = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'fills_old'
            )
        """)

        print(f"   fills 表存在: {fills_exists}")
        print(f"   fills_old 表存在: {old_exists}")

        if not old_exists:
            print("\n❌ 错误: fills_old 表不存在，无法继续")
            print("   请确保已运行过第一个修复脚本")
            await conn.close()
            return False

        # 获取记录数
        old_count = await conn.fetchval("SELECT COUNT(*) FROM fills_old")
        print(f"   fills_old 记录数: {old_count:,}")

        if fills_exists:
            new_count = await conn.fetchval("SELECT COUNT(*) FROM fills")
            print(f"   fills 记录数: {new_count:,}")

            # 删除现有的 fills 表
            print("\n2️⃣  删除现有的 fills 表...")
            await conn.execute("DROP TABLE fills CASCADE")
            print("   ✓ 已删除")

        # 创建序列（如果不存在）
        print("\n3️⃣  创建序列...")
        await conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS fills_id_seq
            START WITH 1
            INCREMENT BY 1
        """)

        # 获取最大 ID 并重置序列
        max_id = await conn.fetchval("SELECT MAX(id) FROM fills_old")
        await conn.execute(f"ALTER SEQUENCE fills_id_seq RESTART WITH {max_id + 1}")
        print(f"   ✓ 序列已创建/重置（起始值: {max_id + 1}）")

        # 创建新表
        print("\n4️⃣  创建新表结构...")
        await conn.execute("""
            CREATE TABLE fills (
                id BIGINT NOT NULL DEFAULT nextval('fills_id_seq'),
                address VARCHAR(42) NOT NULL,
                time TIMESTAMPTZ NOT NULL,
                coin VARCHAR(20),
                side VARCHAR(1),
                price DECIMAL(20, 8),
                size DECIMAL(20, 4),
                closed_pnl DECIMAL(20, 8),
                fee DECIMAL(20, 8),
                hash VARCHAR(66),
                PRIMARY KEY (time, id)
            )
        """)
        print("   ✓ 新表已创建（主键: time, id）")

        # 转换为 hypertable
        print("\n5️⃣  转换为 hypertable...")
        await conn.execute("""
            SELECT create_hypertable('fills', 'time',
                chunk_time_interval => INTERVAL '7 days',
                if_not_exists => true
            )
        """)
        print("   ✓ 已转换为 hypertable")

        # 迁移数据
        print(f"\n6️⃣  迁移数据（{old_count:,} 条记录）...")
        start_time = datetime.now()

        # 使用 INSERT SELECT 一次性迁移
        print("   使用 INSERT SELECT 批量迁移...")
        await conn.execute("""
            INSERT INTO fills (id, address, time, coin, side, price, size, closed_pnl, fee, hash)
            SELECT id, address, time, coin, side, price, size, closed_pnl, fee, hash
            FROM fills_old
            ORDER BY time, id
        """)

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"   ✓ 数据迁移完成 ({elapsed:.1f}秒)")

        # 验证数据
        print("\n7️⃣  验证数据...")
        new_count = await conn.fetchval("SELECT COUNT(*) FROM fills")
        print(f"   新表记录数: {new_count:,}")
        print(f"   原表记录数: {old_count:,}")

        if new_count == old_count:
            print("   ✓ 数据完整")
        else:
            print(f"   ⚠️  警告: 记录数不匹配（差异: {abs(new_count - old_count):,}）")

        # 创建索引
        print("\n8️⃣  创建索引...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fills_address_time
            ON fills(address, time DESC)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fills_hash
            ON fills(hash) WHERE hash IS NOT NULL
        """)
        print("   ✓ 索引已创建")

        # 最终状态
        print("\n9️⃣  最终状态:")
        pk_columns = await conn.fetch("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = 'fills'::regclass
                AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
        """)
        pk_order = [r['attname'] for r in pk_columns]
        print(f"   主键: ({', '.join(pk_order)})")
        print(f"   记录数: {new_count:,}")

        # 获取表大小
        total_size = await conn.fetchval("""
            SELECT pg_size_pretty(pg_total_relation_size('fills'::regclass))
        """)
        print(f"   表大小: {total_size}")

        # 性能测试
        print("\n🔟 性能测试:")
        import time

        # 测试插入
        test_record = (
            'test_address',
            datetime.now(),
            'BTC',
            'A',
            50000.0,
            0.1,
            100.0,
            0.5,
            'test_hash_' + str(datetime.now().timestamp())
        )

        start = time.time()
        await conn.execute("""
            INSERT INTO fills (address, time, coin, side, price, size, closed_pnl, fee, hash)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """, *test_record)
        elapsed = (time.time() - start) * 1000
        print(f"   插入性能: {elapsed:.2f}ms")

        # 删除测试记录
        await conn.execute("DELETE FROM fills WHERE address = 'test_address'")

        # 清理说明
        print("\n" + "=" * 60)
        print("✅ 修复完成")
        print("=" * 60)
        print("\n📝 后续步骤:")
        print("   1. ✓ 测试系统:")
        print("      uv run python analyze_addresses.py --concurrent 1 --rate-limit 0.1")
        print("   2. ⚠️  确认无问题后删除备份表:")
        print("      DROP TABLE fills_old;")

        await conn.close()
        return True

    except Exception as e:
        print(f"\n❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()

        # 尝试恢复
        print("\n⚠️  尝试恢复...")
        try:
            conn = await asyncpg.connect(**db_config)

            old_exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'fills_old'
                )
            """)

            if old_exists:
                print("   删除损坏的表...")
                await conn.execute("DROP TABLE IF EXISTS fills CASCADE")
                print("   ✓ 已清理")
                print("\n   请重新运行此脚本")

            await conn.close()
        except Exception as recovery_error:
            print(f"   ✗ 恢复失败: {recovery_error}")

        return False


if __name__ == '__main__':
    success = asyncio.run(fix_fills_table())
    exit(0 if success else 1)

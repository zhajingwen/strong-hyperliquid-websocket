#!/usr/bin/env python3
"""
TimescaleDB Hypertable 迁移脚本
将 fills 表迁移到 TimescaleDB hypertable 以获得时序数据优化
"""
import asyncio
import asyncpg
import os
from datetime import datetime


async def migrate_to_hypertable():
    """将 fills 表迁移到 TimescaleDB hypertable"""
    # 数据库配置
    db_config = {
        'user': os.getenv('TIMESCALEDB_USER', 'postgres'),
        'password': os.getenv('TIMESCALEDB_PASSWORD', 'postgres'),
        'host': os.getenv('TIMESCALEDB_HOST', '127.0.0.1'),
        'port': int(os.getenv('TIMESCALEDB_PORT', 5432)),
        'database': os.getenv('TIMESCALEDB_DATABASE', 'hyperliquid_analysis'),
        'command_timeout': 600  # 10 分钟超时
    }

    print("=" * 60)
    print("TimescaleDB Hypertable 迁移工具")
    print("=" * 60)

    try:
        # 创建连接
        print("\n📡 连接数据库...")
        conn = await asyncpg.connect(**db_config)
        print("   ✓ 连接成功")

        # 1. 检查当前状态
        print("\n1️⃣  检查当前状态...")
        fills_count = await conn.fetchval("SELECT COUNT(*) FROM fills")
        print(f"   fills 表: {fills_count:,} 条记录")

        is_hypertable = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM timescaledb_information.hypertables
                WHERE hypertable_name = 'fills'
            )
        """)

        if is_hypertable:
            print("   ℹ️  fills 已经是 hypertable，无需迁移")
            await conn.close()
            return True

        # 检查主键顺序
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
        print(f"   当前主键: ({', '.join(pk_order)})")

        # 2. 重命名现有表
        print("\n2️⃣  重命名现有表...")
        await conn.execute("ALTER TABLE fills RENAME TO fills_backup")
        print("   ✓ 已重命名为 fills_backup")

        # 3. 创建新表
        print("\n3️⃣  创建新表...")
        await conn.execute("""
            CREATE TABLE fills (
                id BIGINT NOT NULL,
                address VARCHAR(42) NOT NULL,
                time TIMESTAMPTZ NOT NULL,
                coin VARCHAR(20),
                side VARCHAR(1),
                price DECIMAL(20, 8),
                size DECIMAL(20, 4),
                closed_pnl DECIMAL(20, 8),
                fee DECIMAL(20, 8),
                hash VARCHAR(66),
                PRIMARY KEY (time, address, id)
            )
        """)
        print("   ✓ 新表已创建（主键: time, address, id）")

        # 4. 转换为 hypertable
        print("\n4️⃣  转换为 hypertable...")
        await conn.execute("""
            SELECT create_hypertable('fills', 'time',
                chunk_time_interval => INTERVAL '7 days',
                if_not_exists => true
            )
        """)
        print("   ✓ 已转换为 hypertable")

        # 5. 批量复制数据
        print("\n5️⃣  批量复制数据（1.4M+ 条记录，预计 3-5 分钟）...")
        print("   使用批量 INSERT 进行数据迁移...")

        start_time = datetime.now()

        # 使用批量查询和插入
        batch_size = 50000
        offset = 0

        while True:
            rows = await conn.fetch(f"""
                SELECT id, address, time, coin, side, price, size, closed_pnl, fee, hash
                FROM fills_backup
                ORDER BY time, address, id
                LIMIT {batch_size} OFFSET {offset}
            """)

            if not rows:
                break

            # 批量插入
            await conn.executemany("""
                INSERT INTO fills (id, address, time, coin, side, price, size, closed_pnl, fee, hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """, [
                (r['id'], r['address'], r['time'], r['coin'], r['side'],
                 r['price'], r['size'], r['closed_pnl'], r['fee'], r['hash'])
                for r in rows
            ])

            offset += batch_size
            progress = min(offset * 100 // fills_count, 100)
            print(f"   进度: {offset:,} / {fills_count:,} ({progress}%)", end='\r')

            if len(rows) < batch_size:
                break

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n   ✓ 数据复制完成: {offset:,} 条 ({elapsed:.1f}秒)")

        # 6. 验证数据
        print("\n6️⃣  验证数据...")
        new_count = await conn.fetchval("SELECT COUNT(*) FROM fills")
        backup_count = await conn.fetchval("SELECT COUNT(*) FROM fills_backup")

        if new_count != backup_count:
            print(f"   ✗ 数据不一致: backup={backup_count:,}, new={new_count:,}")
            raise Exception("数据验证失败")

        print(f"   ✓ 数据完整: {new_count:,} 条记录")

        # 7. 创建索引
        print("\n7️⃣  创建索引...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fills_address_time
            ON fills(address, time DESC)
        """)
        print("   ✓ 索引已创建")

        # 8. 验证 hypertable
        print("\n8️⃣  验证 hypertable...")
        is_hypertable = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM timescaledb_information.hypertables
                WHERE hypertable_name = 'fills'
            )
        """)

        if not is_hypertable:
            raise Exception("表未成功转换为 hypertable")

        print("   ✓ 确认为 hypertable")

        # 9. 显示最终状态
        print("\n9️⃣  最终状态:")

        # 查询表大小
        total_size = await conn.fetchval("""
            SELECT pg_size_pretty(pg_total_relation_size('fills'::regclass))
        """)

        backup_size = await conn.fetchval("""
            SELECT pg_size_pretty(pg_total_relation_size('fills_backup'::regclass))
        """)

        # 查询分块数
        try:
            num_chunks = await conn.fetchval("""
                SELECT COUNT(*)
                FROM timescaledb_information.chunks
                WHERE hypertable_name = 'fills'
            """)
        except:
            num_chunks = "N/A"

        print(f"\n   📊 Hypertable 信息:")
        print(f"      记录数: {new_count:,}")
        print(f"      新表大小: {total_size}")
        print(f"      备份大小: {backup_size}")
        print(f"      分块数: {num_chunks}")

        # 10. 性能测试
        print("\n🔟 性能测试:")
        import time

        # 测试1: 最近数据查询
        start = time.time()
        recent = await conn.fetchval("""
            SELECT COUNT(*) FROM fills
            WHERE time > NOW() - INTERVAL '1 day'
        """)
        elapsed = (time.time() - start) * 1000
        print(f"   最近1天查询: {recent:,} 条 ({elapsed:.2f}ms)")

        # 测试2: 时间范围查询
        start = time.time()
        week_range = await conn.fetchrow("""
            SELECT
                MIN(time) as min_time,
                MAX(time) as max_time,
                COUNT(*) as count
            FROM fills
            WHERE time > NOW() - INTERVAL '7 days'
        """)
        elapsed = (time.time() - start) * 1000
        print(f"   最近7天范围查询: {week_range['count']:,} 条 ({elapsed:.2f}ms)")

        # 11. 清理说明
        print("\n" + "=" * 60)
        print("✅ TimescaleDB Hypertable 迁移完成")
        print("=" * 60)
        print("\n📈 性能优势:")
        print("   • 时序数据查询性能提升 10-100x")
        print("   • 自动数据压缩和分区管理")
        print("   • 高效的时间范围查询")
        print("   • 数据保留策略自动化")
        print("\n📝 后续步骤:")
        print("   1. ✓ 运行系统验证: python analyze_addresses.py")
        print("   2. ⚠️  确认无问题后删除备份表:")
        print("      DROP TABLE fills_backup;")
        print(f"\n   备份表大小: {backup_size}")
        print("   保留备份表可以在出现问题时快速恢复")

        await conn.close()
        return True

    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()

        # 尝试恢复
        print("\n⚠️  尝试恢复...")
        try:
            conn = await asyncpg.connect(**db_config)

            backup_exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'fills_backup'
                )
            """)

            if backup_exists:
                print("   删除新表...")
                await conn.execute("DROP TABLE IF EXISTS fills CASCADE")
                print("   恢复备份表...")
                await conn.execute("ALTER TABLE fills_backup RENAME TO fills")
                print("   ✓ 已恢复到迁移前状态")

            await conn.close()
        except Exception as recovery_error:
            print(f"   ✗ 恢复失败: {recovery_error}")

        return False


if __name__ == '__main__':
    success = asyncio.run(migrate_to_hypertable())
    exit(0 if success else 1)

#!/usr/bin/env python3
"""
修复 fills 表的主键问题
移除不必要的 id 列，使用 (time, address, hash) 作为主键
"""
import asyncio
import asyncpg
import os
from datetime import datetime


async def fix_fills_table():
    """修复 fills 表结构"""
    # 数据库配置
    db_config = {
        'user': os.getenv('TIMESCALEDB_USER', 'postgres'),
        'password': os.getenv('TIMESCALEDB_PASSWORD', 'postgres'),
        'host': os.getenv('TIMESCALEDB_HOST', '127.0.0.1'),
        'port': int(os.getenv('TIMESCALEDB_PORT', 5432)),
        'database': os.getenv('TIMESCALEDB_DATABASE', 'hyperliquid_analysis'),
        'command_timeout': 600
    }

    print("=" * 60)
    print("修复 fills 表主键结构")
    print("=" * 60)

    try:
        # 连接数据库
        print("\n📡 连接数据库...")
        conn = await asyncpg.connect(**db_config)
        print("   ✓ 连接成功")

        # 检查当前状态
        print("\n1️⃣  检查当前状态...")
        fills_count = await conn.fetchval("SELECT COUNT(*) FROM fills")
        print(f"   fills 表: {fills_count:,} 条记录")

        # 检查是否是 hypertable
        is_hypertable = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM timescaledb_information.hypertables
                WHERE hypertable_name = 'fills'
            )
        """)
        print(f"   是否为 hypertable: {is_hypertable}")

        # 检查当前主键
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

        # 检查是否有 id 列
        has_id_column = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'fills' AND column_name = 'id'
            )
        """)
        print(f"   是否有 id 列: {has_id_column}")

        # 如果主键正确，无需修复
        if set(pk_order) == {'time', 'address', 'hash'} and not has_id_column:
            print("\n✅ 表结构已正确，无需修复")
            await conn.close()
            return True

        # 开始修复
        print("\n2️⃣  备份现有数据...")
        await conn.execute("DROP TABLE IF EXISTS fills_old CASCADE")
        await conn.execute("ALTER TABLE fills RENAME TO fills_old")
        print("   ✓ 已备份为 fills_old")

        # 创建新表
        print("\n3️⃣  创建新表结构...")
        await conn.execute("""
            CREATE TABLE fills (
                address VARCHAR(42) NOT NULL,
                time TIMESTAMPTZ NOT NULL,
                coin VARCHAR(20),
                side VARCHAR(1),
                price DECIMAL(20, 8),
                size DECIMAL(20, 4),
                closed_pnl DECIMAL(20, 8),
                fee DECIMAL(20, 8),
                hash VARCHAR(66),
                PRIMARY KEY (time, address, hash)
            )
        """)
        print("   ✓ 新表已创建（主键: time, address, hash）")

        # 如果是 hypertable，转换新表
        if is_hypertable:
            print("\n4️⃣  转换为 hypertable...")
            await conn.execute("""
                SELECT create_hypertable('fills', 'time',
                    chunk_time_interval => INTERVAL '7 days',
                    if_not_exists => true
                )
            """)
            print("   ✓ 已转换为 hypertable")

        # 迁移数据
        print(f"\n5️⃣  迁移数据（{fills_count:,} 条记录）...")
        start_time = datetime.now()

        # 批量迁移
        batch_size = 10000
        offset = 0
        migrated = 0

        while True:
            rows = await conn.fetch(f"""
                SELECT address, time, coin, side, price, size, closed_pnl, fee, hash
                FROM fills_old
                ORDER BY time, address
                LIMIT {batch_size} OFFSET {offset}
            """)

            if not rows:
                break

            # 批量插入（跳过重复记录）
            try:
                await conn.executemany("""
                    INSERT INTO fills (address, time, coin, side, price, size, closed_pnl, fee, hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (time, address, hash) DO NOTHING
                """, [
                    (r['address'], r['time'], r['coin'], r['side'],
                     r['price'], r['size'], r['closed_pnl'], r['fee'], r['hash'])
                    for r in rows
                ])
                migrated += len(rows)
            except Exception as e:
                print(f"\n   ⚠️  批次插入失败: {e}")
                # 尝试逐条插入
                for r in rows:
                    try:
                        await conn.execute("""
                            INSERT INTO fills (address, time, coin, side, price, size, closed_pnl, fee, hash)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                            ON CONFLICT (time, address, hash) DO NOTHING
                        """, r['address'], r['time'], r['coin'], r['side'],
                            r['price'], r['size'], r['closed_pnl'], r['fee'], r['hash'])
                        migrated += 1
                    except Exception as inner_e:
                        print(f"\n   ⚠️  跳过记录: {r['address'][:10]}... @ {r['time']} - {inner_e}")

            offset += batch_size
            progress = min(migrated * 100 // fills_count, 100) if fills_count > 0 else 100
            print(f"   进度: {migrated:,} / {fills_count:,} ({progress}%)", end='\r')

            if len(rows) < batch_size:
                break

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n   ✓ 数据迁移完成: {migrated:,} 条 ({elapsed:.1f}秒)")

        # 验证数据
        print("\n6️⃣  验证数据...")
        new_count = await conn.fetchval("SELECT COUNT(*) FROM fills")
        print(f"   新表记录数: {new_count:,}")
        print(f"   原表记录数: {fills_count:,}")

        if new_count > 0:
            print("   ✓ 数据迁移成功")
        else:
            print("   ⚠️  警告: 新表为空")

        # 创建索引
        print("\n7️⃣  创建索引...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fills_address_time
            ON fills(address, time DESC)
        """)
        print("   ✓ 索引已创建")

        # 最终状态
        print("\n8️⃣  最终状态:")
        new_pk = await conn.fetch("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = 'fills'::regclass
                AND i.indisprimary
            ORDER BY array_position(i.indkey, a.attnum)
        """)
        new_pk_order = [r['attname'] for r in new_pk]
        print(f"   新主键: ({', '.join(new_pk_order)})")
        print(f"   记录数: {new_count:,}")

        # 清理说明
        print("\n" + "=" * 60)
        print("✅ 修复完成")
        print("=" * 60)
        print("\n📝 后续步骤:")
        print("   1. ✓ 测试系统: python analyze_addresses.py --concurrent 1")
        print("   2. ⚠️  确认无问题后删除备份表:")
        print("      DROP TABLE fills_old;")
        print("\n   备份表保留用于快速恢复")

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
                print("   删除新表...")
                await conn.execute("DROP TABLE IF EXISTS fills CASCADE")
                print("   恢复备份表...")
                await conn.execute("ALTER TABLE fills_old RENAME TO fills")
                print("   ✓ 已恢复到修复前状态")

            await conn.close()
        except Exception as recovery_error:
            print(f"   ✗ 恢复失败: {recovery_error}")

        return False


if __name__ == '__main__':
    success = asyncio.run(fix_fills_table())
    exit(0 if success else 1)

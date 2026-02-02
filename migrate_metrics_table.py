#!/usr/bin/env python3
"""
数据库表结构迁移脚本 - 修复 metrics_cache 字段溢出问题
"""

import asyncio
import asyncpg
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def migrate():
    """执行数据库迁移"""
    # 数据库配置
    config = {
        'user': os.getenv('TIMESCALEDB_USER', 'postgres'),
        'password': os.getenv('TIMESCALEDB_PASSWORD', 'postgres'),
        'host': os.getenv('TIMESCALEDB_HOST', '127.0.0.1'),
        'port': int(os.getenv('TIMESCALEDB_PORT', 5432)),
        'database': os.getenv('TIMESCALEDB_DATABASE', 'hyperliquid_analysis')
    }

    logger.info(f"连接数据库: {config['host']}:{config['port']}/{config['database']}")

    try:
        conn = await asyncpg.connect(**config)

        # 检查表是否存在
        table_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'metrics_cache')"
        )

        if not table_exists:
            logger.info("表 metrics_cache 不存在，无需迁移")
            await conn.close()
            return

        logger.info("开始迁移 metrics_cache 表...")

        # 开启事务
        async with conn.transaction():
            # 1. 修改 win_rate: DECIMAL(5,2) -> DECIMAL(6,2)
            logger.info("修改 win_rate 字段精度...")
            await conn.execute(
                "ALTER TABLE metrics_cache ALTER COLUMN win_rate TYPE DECIMAL(6, 2)"
            )

            # 2. 修改 roi: DECIMAL(10,2) -> DECIMAL(12,2)
            logger.info("修改 roi 字段精度...")
            await conn.execute(
                "ALTER TABLE metrics_cache ALTER COLUMN roi TYPE DECIMAL(12, 2)"
            )

            # 3. 修改 max_drawdown: DECIMAL(5,2) -> DECIMAL(8,2)
            logger.info("修改 max_drawdown 字段精度...")
            await conn.execute(
                "ALTER TABLE metrics_cache ALTER COLUMN max_drawdown TYPE DECIMAL(8, 2)"
            )

        logger.info("✅ 数据库迁移成功！")

        # 验证修改
        columns = await conn.fetch("""
            SELECT column_name, data_type, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_name = 'metrics_cache'
              AND column_name IN ('win_rate', 'roi', 'max_drawdown')
            ORDER BY column_name
        """)

        logger.info("\n修改后的字段定义:")
        for col in columns:
            logger.info(
                f"  {col['column_name']}: {col['data_type']}({col['numeric_precision']},{col['numeric_scale']})"
            )

        await conn.close()

    except Exception as e:
        logger.error(f"❌ 迁移失败: {e}")
        raise


if __name__ == '__main__':
    asyncio.run(migrate())

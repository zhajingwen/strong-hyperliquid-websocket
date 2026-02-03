"""
数据持久化 - PostgreSQL + TimescaleDB 数据库管理
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import asyncpg
from asyncpg.pool import Pool

logger = logging.getLogger(__name__)


class DataStore:
    """PostgreSQL + TimescaleDB 数据存储管理器"""

    def __init__(self):
        """初始化数据库配置"""
        self.config = {
            'user': os.getenv('TIMESCALEDB_USER', 'postgres'),
            'password': os.getenv('TIMESCALEDB_PASSWORD', 'postgres'),
            'host': os.getenv('TIMESCALEDB_HOST', '127.0.0.1'),
            'port': int(os.getenv('TIMESCALEDB_PORT', 5432)),
            'database': os.getenv('TIMESCALEDB_DATABASE', 'hyperliquid_analysis')
        }
        self.pool: Optional[Pool] = None

    async def connect(self, max_connections: int = 20):
        """
        创建数据库连接池

        Args:
            max_connections: 最大连接数
        """
        if self.pool:
            logger.warning("连接池已存在，跳过创建")
            return

        try:
            # 创建连接池
            min_size = min(5, max_connections)  # 确保 min_size <= max_size
            self.pool = await asyncpg.create_pool(
                **self.config,
                min_size=min_size,
                max_size=max_connections,
                command_timeout=60
            )
            logger.info(f"数据库连接池已创建: {self.config['host']}:{self.config['port']}/{self.config['database']}")

            # 初始化数据库Schema
            await self.init_schema()

        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            raise

    async def close(self):
        """关闭连接池"""
        if self.pool:
            await self.pool.close()
            logger.info("数据库连接池已关闭")
            self.pool = None

    async def init_schema(self):
        """初始化数据库Schema和TimescaleDB hypertables"""
        schema_sql = """
        -- 1. 地址表
        CREATE TABLE IF NOT EXISTS addresses (
            address VARCHAR(42) PRIMARY KEY,
            taker_count INTEGER DEFAULT 0,
            maker_count INTEGER DEFAULT 0,
            first_seen TIMESTAMPTZ DEFAULT NOW(),
            last_updated TIMESTAMPTZ DEFAULT NOW(),
            data_complete BOOLEAN DEFAULT FALSE
        );

        -- 2. 交易记录表
        CREATE TABLE IF NOT EXISTS fills (
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
        );

        -- 3. 转账记录表
        CREATE TABLE IF NOT EXISTS transfers (
            id BIGSERIAL,
            address VARCHAR(42) NOT NULL,
            time TIMESTAMPTZ NOT NULL,
            type VARCHAR(10),
            amount DECIMAL(20, 8),
            tx_hash VARCHAR(66),
            PRIMARY KEY (id, time)
        );

        -- 4. 账户快照表
        CREATE TABLE IF NOT EXISTS account_snapshots (
            address VARCHAR(42) NOT NULL,
            snapshot_time TIMESTAMPTZ NOT NULL,
            account_value DECIMAL(20, 8),
            margin_used DECIMAL(20, 8),
            unrealized_pnl DECIMAL(20, 8),
            PRIMARY KEY (address, snapshot_time)
        );

        -- 5. 指标缓存表
        CREATE TABLE IF NOT EXISTS metrics_cache (
            address VARCHAR(42) PRIMARY KEY,
            total_trades INTEGER,
            win_rate DECIMAL(6, 2),
            roi DECIMAL(12, 2),
            sharpe_ratio DECIMAL(10, 4),
            total_pnl DECIMAL(20, 8),
            account_value DECIMAL(20, 8),
            max_drawdown DECIMAL(8, 2),
            net_deposit DECIMAL(20, 8),
            calculated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- 6. API缓存表
        CREATE TABLE IF NOT EXISTS api_cache (
            cache_key VARCHAR(255) PRIMARY KEY,
            response_data JSONB,
            cached_at TIMESTAMPTZ DEFAULT NOW(),
            expires_at TIMESTAMPTZ
        );

        -- 7. 处理状态表
        CREATE TABLE IF NOT EXISTS processing_status (
            address VARCHAR(42) PRIMARY KEY,
            status VARCHAR(20),
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- 索引优化
        CREATE INDEX IF NOT EXISTS idx_fills_address_time ON fills(address, time DESC);
        CREATE INDEX IF NOT EXISTS idx_transfers_address_time ON transfers(address, time DESC);
        CREATE INDEX IF NOT EXISTS idx_api_cache_expires ON api_cache(expires_at);
        CREATE INDEX IF NOT EXISTS idx_processing_status ON processing_status(status, retry_count);
        """

        # TimescaleDB hypertable 转换（需要单独执行）
        hypertable_sql = """
        -- 转换为 TimescaleDB hypertable
        SELECT create_hypertable('fills', 'time',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        );

        SELECT create_hypertable('transfers', 'time',
            chunk_time_interval => INTERVAL '30 days',
            if_not_exists => TRUE
        );
        """

        async with self.pool.acquire() as conn:
            try:
                # 创建基础表
                await conn.execute(schema_sql)
                logger.info("基础表创建成功")

                # 尝试创建 TimescaleDB hypertable（如果 TimescaleDB 扩展已安装）
                try:
                    # 先检查 TimescaleDB 扩展是否已安装
                    extension_exists = await conn.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')"
                    )

                    if extension_exists:
                        # 检查表是否已有数据
                        has_data = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM fills LIMIT 1)")

                        if not has_data:
                            # 只有空表才转换为 hypertable
                            await conn.execute(hypertable_sql)
                            logger.info("✓ TimescaleDB hypertables 创建成功")
                        else:
                            logger.info("ℹ️  fills 表已有数据，跳过 hypertable 转换")
                            logger.info("   提示: hypertable 是可选的性能优化功能，不影响业务逻辑")
                            logger.info("   详见: TIMESCALEDB_MIGRATION.md")
                    else:
                        logger.info("ℹ️  TimescaleDB 扩展未安装，跳过 hypertable 创建（不影响基础功能）")
                        logger.info("   安装方法: CREATE EXTENSION timescaledb;")
                except Exception as e:
                    # 降低日志级别，避免用户困惑
                    logger.info(f"ℹ️  跳过 TimescaleDB hypertable 创建: {e}")
                    logger.info("   提示: 这不影响系统功能，仅是时序数据优化")

            except Exception as e:
                logger.error(f"Schema 初始化失败: {e}")
                raise

    async def upsert_addresses(self, addresses: List[Dict[str, Any]]):
        """
        批量插入/更新地址信息

        Args:
            addresses: 地址列表 [{'address': '0x...', 'taker_count': 10, 'maker_count': 5}]
        """
        if not addresses:
            return

        sql = """
        INSERT INTO addresses (address, taker_count, maker_count, first_seen)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (address) DO UPDATE
        SET taker_count = EXCLUDED.taker_count,
            maker_count = EXCLUDED.maker_count,
            last_updated = NOW()
        """

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    sql,
                    [(a['address'], a['taker_count'], a['maker_count']) for a in addresses]
                )
        logger.info(f"批量更新 {len(addresses)} 个地址")

    async def get_pending_addresses(self, limit: Optional[int] = None) -> List[str]:
        """
        获取待处理地址列表

        Args:
            limit: 限制返回数量

        Returns:
            地址列表
        """
        sql = """
        SELECT DISTINCT address FROM (
            -- 待处理或失败的地址
            SELECT address FROM processing_status
            WHERE status IN ('pending', 'failed')
              AND retry_count < 3
            UNION
            -- 24小时未更新的地址
            SELECT address FROM addresses
            WHERE last_updated < NOW() - INTERVAL '24 hours'
               OR data_complete = FALSE
        ) AS pending_addrs
        ORDER BY address
        """

        if limit:
            sql += f" LIMIT {limit}"

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql)
            return [row['address'] for row in rows]

    async def update_processing_status(
        self,
        address: str,
        status: str,
        error_message: Optional[str] = None
    ):
        """
        更新地址处理状态

        Args:
            address: 地址
            status: 状态 (pending/processing/completed/failed)
            error_message: 错误信息（可选）
        """
        sql = """
        INSERT INTO processing_status (address, status, error_message, updated_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (address) DO UPDATE
        SET status = EXCLUDED.status,
            error_message = EXCLUDED.error_message,
            retry_count = CASE
                WHEN EXCLUDED.status = 'failed' THEN processing_status.retry_count + 1
                ELSE 0
            END,
            updated_at = NOW()
        """

        async with self.pool.acquire() as conn:
            await conn.execute(sql, address, status, error_message)

    async def mark_address_complete(self, address: str):
        """
        标记地址数据已完整获取

        Args:
            address: 地址
        """
        sql = """
        UPDATE addresses
        SET data_complete = TRUE,
            last_updated = NOW()
        WHERE address = $1
        """

        async with self.pool.acquire() as conn:
            await conn.execute(sql, address)

    async def get_api_cache(self, cache_key: str) -> Optional[Dict]:
        """
        获取API缓存

        Args:
            cache_key: 缓存键

        Returns:
            缓存数据或None
        """
        sql = """
        SELECT response_data FROM api_cache
        WHERE cache_key = $1
          AND expires_at > NOW()
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, cache_key)
            if not row:
                return None

            # asyncpg 返回 JSONB 数据，如果是字符串则需要再次解析
            data = row['response_data']
            if isinstance(data, str):
                return json.loads(data)
            return data

    async def set_api_cache(
        self,
        cache_key: str,
        data: Dict,
        ttl_hours: int = 1
    ):
        """
        设置API缓存

        Args:
            cache_key: 缓存键
            data: 缓存数据
            ttl_hours: 过期时间（小时）
        """
        sql = """
        INSERT INTO api_cache (cache_key, response_data, expires_at)
        VALUES ($1, $2, NOW() + $3::INTERVAL)
        ON CONFLICT (cache_key) DO UPDATE
        SET response_data = EXCLUDED.response_data,
            cached_at = NOW(),
            expires_at = NOW() + $3::INTERVAL
        """

        async with self.pool.acquire() as conn:
            # 转换为JSON字符串，asyncpg 会将其存储为 JSONB
            await conn.execute(sql, cache_key, json.dumps(data), timedelta(hours=ttl_hours))

    async def save_fills(self, address: str, fills: List[Dict]):
        """
        批量保存交易记录

        Args:
            address: 地址
            fills: 交易记录列表
        """
        if not fills:
            return

        # 先查询已存在的 hash，避免重复插入
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 获取所有待插入记录的 hash
                hashes = [fill.get('hash') for fill in fills if fill.get('hash')]

                if hashes:
                    # 查询已存在的 hash
                    existing_hashes = await conn.fetch(
                        "SELECT hash FROM fills WHERE hash = ANY($1::varchar[])",
                        hashes
                    )
                    existing_hash_set = {row['hash'] for row in existing_hashes}
                else:
                    existing_hash_set = set()

                # 过滤掉已存在的记录
                records_to_insert = []
                for fill in fills:
                    fill_hash = fill.get('hash')
                    if not fill_hash or fill_hash not in existing_hash_set:
                        records_to_insert.append((
                            address,
                            datetime.fromtimestamp(fill['time'] / 1000),  # 毫秒转秒
                            fill.get('coin'),
                            fill.get('side'),
                            float(fill.get('px', 0)),
                            float(fill.get('sz', 0)),
                            float(fill.get('closedPnl', 0)),
                            float(fill.get('fee', 0)),
                            fill_hash
                        ))

                # 批量插入
                if records_to_insert:
                    sql = """
                    INSERT INTO fills (address, time, coin, side, price, size, closed_pnl, fee, hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """
                    await conn.executemany(sql, records_to_insert)
                    logger.info(f"保存 {len(records_to_insert)} 条交易记录: {address[:10]}... (跳过 {len(fills) - len(records_to_insert)} 条重复)")
                else:
                    logger.info(f"无新记录需要保存: {address[:10]}... (全部重复)")

    async def get_fills(self, address: str) -> List[Dict]:
        """
        获取地址的所有交易记录

        Args:
            address: 地址

        Returns:
            交易记录列表
        """
        sql = """
        SELECT * FROM fills
        WHERE address = $1
        ORDER BY time ASC
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, address)
            return [dict(row) for row in rows]

    async def save_metrics(self, address: str, metrics: Dict):
        """
        保存计算的指标

        Args:
            address: 地址
            metrics: 指标数据
        """
        sql = """
        INSERT INTO metrics_cache (
            address, total_trades, win_rate, roi, sharpe_ratio,
            total_pnl, account_value, max_drawdown, net_deposit, calculated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
        ON CONFLICT (address) DO UPDATE
        SET total_trades = EXCLUDED.total_trades,
            win_rate = EXCLUDED.win_rate,
            roi = EXCLUDED.roi,
            sharpe_ratio = EXCLUDED.sharpe_ratio,
            total_pnl = EXCLUDED.total_pnl,
            account_value = EXCLUDED.account_value,
            max_drawdown = EXCLUDED.max_drawdown,
            net_deposit = EXCLUDED.net_deposit,
            calculated_at = NOW()
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                sql,
                address,
                metrics.get('total_trades', 0),
                metrics.get('win_rate', 0),
                metrics.get('roi', 0),
                metrics.get('sharpe_ratio', 0),
                metrics.get('total_pnl', 0),
                metrics.get('account_value', 0),
                metrics.get('max_drawdown', 0),
                metrics.get('net_deposit', 0)
            )

    async def get_all_metrics(self) -> List[Dict]:
        """
        获取所有已计算的指标

        Returns:
            指标列表
        """
        sql = """
        SELECT * FROM metrics_cache
        ORDER BY total_pnl DESC
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql)
            return [dict(row) for row in rows]


# 单例模式
_store_instance: Optional[DataStore] = None


def get_store() -> DataStore:
    """获取 DataStore 单例"""
    global _store_instance
    if _store_instance is None:
        _store_instance = DataStore()
    return _store_instance

"""
数据持久化 - PostgreSQL + TimescaleDB 数据库管理
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
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
            liquidation JSONB,
            PRIMARY KEY (time, address, hash)
        );

        -- 为已有表添加 liquidation 字段（如果不存在）
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'fills' AND column_name = 'liquidation'
            ) THEN
                ALTER TABLE fills ADD COLUMN liquidation JSONB;
            END IF;
        END $$;

        -- 3. 转账记录表
        CREATE TABLE IF NOT EXISTS transfers (
            id BIGSERIAL,
            address VARCHAR(42) NOT NULL,
            time TIMESTAMPTZ NOT NULL,
            type VARCHAR(25),
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
            total_pnl DECIMAL(20, 8),
            account_value DECIMAL(20, 8),
            net_deposit DECIMAL(20, 8),
            calculated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- 6. 处理状态表
        CREATE TABLE IF NOT EXISTS processing_status (
            address VARCHAR(42) PRIMARY KEY,
            status VARCHAR(20),
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- 8. 用户账户状态表 (Perp)
        CREATE TABLE IF NOT EXISTS user_states (
            id BIGSERIAL,
            address VARCHAR(42) NOT NULL,
            snapshot_time TIMESTAMPTZ NOT NULL,
            account_value DECIMAL(20, 8),
            total_margin_used DECIMAL(20, 8),
            total_ntl_pos DECIMAL(20, 8),
            total_raw_usd DECIMAL(20, 8),
            withdrawable DECIMAL(20, 8),
            cross_margin_summary JSONB,
            asset_positions JSONB,
            PRIMARY KEY (id, snapshot_time)
        );

        -- 9. Spot账户状态表
        CREATE TABLE IF NOT EXISTS spot_states (
            id BIGSERIAL,
            address VARCHAR(42) NOT NULL,
            snapshot_time TIMESTAMPTZ NOT NULL,
            balances JSONB,
            PRIMARY KEY (id, snapshot_time)
        );

        -- 10. 资金费率历史表
        CREATE TABLE IF NOT EXISTS funding_history (
            address VARCHAR(42) NOT NULL,
            time TIMESTAMPTZ NOT NULL,
            coin VARCHAR(20) NOT NULL,
            usdc DECIMAL(20, 8),
            szi DECIMAL(20, 8),
            funding_rate DECIMAL(20, 10),
            PRIMARY KEY (time, address, coin)
        );

        -- 11. 数据新鲜度跟踪表
        CREATE TABLE IF NOT EXISTS data_freshness (
            address VARCHAR(42) NOT NULL,
            data_type VARCHAR(20) NOT NULL,  -- 'fills', 'user_state', 'spot_state', 'funding', 'transfers'
            last_fetched TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (address, data_type)
        );

        -- 索引优化
        CREATE INDEX IF NOT EXISTS idx_fills_address_time ON fills(address, time DESC);
        CREATE INDEX IF NOT EXISTS idx_transfers_address_time ON transfers(address, time DESC);
        CREATE INDEX IF NOT EXISTS idx_processing_status ON processing_status(status, retry_count);
        CREATE INDEX IF NOT EXISTS idx_user_states_address_time ON user_states(address, snapshot_time DESC);
        CREATE INDEX IF NOT EXISTS idx_spot_states_address_time ON spot_states(address, snapshot_time DESC);
        CREATE INDEX IF NOT EXISTS idx_funding_history_address_time ON funding_history(address, time DESC);
        CREATE INDEX IF NOT EXISTS idx_data_freshness_time ON data_freshness(data_type, last_fetched);
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

        SELECT create_hypertable('user_states', 'snapshot_time',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        );

        SELECT create_hypertable('spot_states', 'snapshot_time',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        );

        SELECT create_hypertable('funding_history', 'time',
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
                        # 处理 liquidation 字段（可能是 dict 或 None）
                        liquidation_data = fill.get('liquidation')
                        liquidation_json = json.dumps(liquidation_data) if liquidation_data else None

                        records_to_insert.append((
                            address,
                            datetime.fromtimestamp(fill['time'] / 1000),  # 毫秒转秒
                            fill.get('coin'),
                            fill.get('side'),
                            float(fill.get('px', 0)),
                            float(fill.get('sz', 0)),
                            float(fill.get('closedPnl', 0)),
                            float(fill.get('fee', 0)),
                            fill_hash,
                            liquidation_json
                        ))

                # 批量插入
                if records_to_insert:
                    sql = """
                    INSERT INTO fills (address, time, coin, side, price, size, closed_pnl, fee, hash, liquidation)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """
                    await conn.executemany(sql, records_to_insert)
                    logger.info(f"保存 {len(records_to_insert)} 条交易记录: {address} (跳过 {len(fills) - len(records_to_insert)} 条重复)")
                else:
                    logger.info(f"无新记录需要保存: {address} (全部重复)")

    async def save_transfers(self, address: str, ledger: List[Dict]):
        """
        批量保存出入金记录到 transfers 表

        支持类型：
        - deposit: 充值（正数）
        - withdraw: 提现（负数）
        - send: 转账（根据流向判断正负）
        - subAccountTransfer: 子账户转账（根据流向判断正负）

        Args:
            address: 地址
            ledger: 账本变动列表（来自 user_non_funding_ledger_updates）
        """
        if not ledger:
            return

        records_to_insert = []

        for record in ledger:
            time_ms = record.get('time', 0)
            delta = record.get('delta', {})
            record_type = delta.get('type')

            # 支持所有出入金类型
            if record_type not in ['deposit', 'withdraw', 'send', 'subAccountTransfer']:
                continue

            # 提取金额和流向
            amount = 0.0
            signed_amount = 0.0
            tx_hash = record.get('hash', '')

            if record_type == 'deposit':
                # 充值：正数
                amount = float(delta.get('usdc', 0))
                signed_amount = amount

            elif record_type == 'withdraw':
                # 提现：负数
                amount = float(delta.get('usdc', 0))
                signed_amount = -amount

            elif record_type == 'send':
                # 转账：根据流向判断
                amount = float(delta.get('amount', 0))
                destination = delta.get('destination', '').lower()
                user = delta.get('user', '').lower()
                is_incoming = (destination == address.lower() and user != address.lower())
                is_outgoing = (user == address.lower() and destination != address.lower())

                if is_incoming:
                    signed_amount = amount
                elif is_outgoing:
                    signed_amount = -amount
                else:
                    # 自己转给自己，忽略
                    continue

            elif record_type == 'subAccountTransfer':
                # 子账户转账：根据流向判断
                amount = float(delta.get('usdc', 0))
                destination = delta.get('destination', '').lower()
                user = delta.get('user', '').lower()

                if destination == address.lower():
                    signed_amount = amount
                elif user == address.lower():
                    signed_amount = -amount
                else:
                    # 不相关，忽略
                    continue

            if amount > 0:
                # 转换时间戳为 datetime
                time_dt = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)

                records_to_insert.append((
                    address,
                    time_dt,
                    record_type,
                    signed_amount,
                    tx_hash
                ))

        if records_to_insert:
            async with self.pool.acquire() as conn:
                # 注意：transfers 表的主键是 (id, time)，使用 ON CONFLICT DO UPDATE 更新策略
                sql = """
                INSERT INTO transfers (address, time, type, amount, tx_hash)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id, time) DO UPDATE
                SET type = EXCLUDED.type,
                    amount = EXCLUDED.amount,
                    tx_hash = EXCLUDED.tx_hash
                """
                # 由于可能存在重复，先检查是否已存在
                check_sql = """
                SELECT COUNT(*) FROM transfers
                WHERE address = $1 AND time = $2 AND tx_hash = $3
                """

                inserted_count = 0
                for record in records_to_insert:
                    addr, time_dt, rec_type, amount, tx_hash = record
                    # 检查是否已存在
                    count = await conn.fetchval(check_sql, addr, time_dt, tx_hash)
                    if count == 0:
                        # 不存在，插入
                        insert_sql = """
                        INSERT INTO transfers (address, time, type, amount, tx_hash)
                        VALUES ($1, $2, $3, $4, $5)
                        """
                        await conn.execute(insert_sql, addr, time_dt, rec_type, amount, tx_hash)
                        inserted_count += 1

                logger.info(f"保存 {inserted_count}/{len(records_to_insert)} 条出入金记录: {address}")

    async def get_net_deposits(self, address: str) -> Dict[str, float]:
        """
        计算净充值统计（区分充值/提现 vs 转账）

        Args:
            address: 地址

        Returns:
            {
                # 充值/提现（deposit/withdraw）
                'total_deposits': float,          # 总充值
                'total_withdrawals': float,       # 总提现
                'net_deposits': float,            # 净充值 - 传统方法（包含转账）

                # 转账（send/subAccountTransfer）
                'total_transfers_in': float,      # 转入总额
                'total_transfers_out': float,     # 转出总额
                'net_transfers': float,           # 净转账

                # 真实本金（仅充值/提现，不含转账）
                'true_capital': float             # 真实本金 = 总充值 - 总提现
            }
        """
        sql = """
        SELECT
            -- 充值/提现统计
            COALESCE(SUM(CASE WHEN type = 'deposit' THEN amount ELSE 0 END), 0) as deposit_total,
            COALESCE(SUM(CASE WHEN type = 'withdraw' THEN ABS(amount) ELSE 0 END), 0) as withdraw_total,

            -- 转账统计
            COALESCE(SUM(CASE WHEN type IN ('send', 'subAccountTransfer') AND amount > 0 THEN amount ELSE 0 END), 0) as transfer_in_total,
            COALESCE(SUM(CASE WHEN type IN ('send', 'subAccountTransfer') AND amount < 0 THEN ABS(amount) ELSE 0 END), 0) as transfer_out_total,

            -- 总计（传统方法）
            COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) as all_in_total,
            COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) as all_out_total
        FROM transfers
        WHERE address = $1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, address)

            # 充值/提现
            deposit_total = float(row['deposit_total'])
            withdraw_total = float(row['withdraw_total'])

            # 转账
            transfer_in_total = float(row['transfer_in_total'])
            transfer_out_total = float(row['transfer_out_total'])

            # 总计（传统方法）
            all_in_total = float(row['all_in_total'])
            all_out_total = float(row['all_out_total'])

            return {
                # 充值/提现
                'total_deposits': deposit_total,
                'total_withdrawals': withdraw_total,

                # 转账
                'total_transfers_in': transfer_in_total,
                'total_transfers_out': transfer_out_total,
                'net_transfers': transfer_in_total - transfer_out_total,

                # 真实本金（仅充值/提现）
                'true_capital': deposit_total - withdraw_total,

                # 传统方法（包含转账）
                'net_deposits': all_in_total - all_out_total
            }

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

    async def has_recent_liquidation(self, address: str, days: int = 7) -> bool:
        """
        检查地址在最近指定天数内是否有爆仓记录

        Args:
            address: 用户地址
            days: 检查的天数范围，默认7天

        Returns:
            True 表示有爆仓记录，False 表示无爆仓记录
        """
        sql = """
        SELECT EXISTS (
            SELECT 1 FROM fills
            WHERE address = $1
              AND liquidation IS NOT NULL
              AND time >= NOW() - INTERVAL '%s days'
        ) AS has_liquidation
        """ % days

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, address)
            has_liq = row['has_liquidation'] if row else False
            if has_liq:
                logger.info(f"[{address[:10]}...] 检测到最近 {days} 天内有爆仓记录")
            return has_liq

    async def get_latest_fill_time(self, address: str) -> Optional[int]:
        """
        获取地址最新的交易时间戳（用于增量更新）

        Args:
            address: 用户地址

        Returns:
            最新交易的时间戳（毫秒），如果没有记录返回None
        """
        sql = """
        SELECT EXTRACT(EPOCH FROM MAX(time)) * 1000 AS latest_time_ms
        FROM fills
        WHERE address = $1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, address)
            if row and row['latest_time_ms']:
                return int(row['latest_time_ms'])
            return None

    async def is_data_fresh(self, address: str, data_type: str, ttl_hours: int = 24) -> bool:
        """
        检查指定数据类型是否在 TTL 内（数据新鲜度检查）

        基于 data_freshness 表的 last_fetched 时间判断，而非数据记录本身的时间。
        这样可以避免不活跃用户（无新交易）每次都被判断为"不新鲜"而触发无效 API 调用。

        Args:
            address: 用户地址
            data_type: 数据类型 ('fills', 'user_state', 'spot_state', 'funding', 'transfers')
            ttl_hours: 数据有效期（小时），默认24小时

        Returns:
            True 表示数据新鲜（在TTL内），False 表示数据过期或不存在
        """
        valid_types = {'fills', 'user_state', 'spot_state', 'funding', 'transfers'}
        if data_type not in valid_types:
            logger.warning(f"未知的数据类型: {data_type}")
            return False

        sql = """
        SELECT last_fetched FROM data_freshness
        WHERE address = $1 AND data_type = $2
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, address, data_type)
            if not row or not row['last_fetched']:
                logger.debug(f"[{address}] {data_type} 无获取记录，数据不新鲜")
                return False

            last_fetched = row['last_fetched']
            # 计算时间差
            now = datetime.now(timezone.utc)
            age = now - last_fetched.replace(tzinfo=timezone.utc)
            is_fresh = age.total_seconds() < ttl_hours * 3600

            logger.debug(f"[{address}] {data_type} 新鲜度检查: 上次获取={last_fetched}, 年龄={age}, 新鲜={is_fresh}")
            return is_fresh

    async def update_data_freshness(self, address: str, data_type: str):
        """
        记录数据获取时间（用于新鲜度检查）

        在成功从 API 获取数据后调用此方法，更新 last_fetched 时间戳。

        Args:
            address: 用户地址
            data_type: 数据类型 ('fills', 'user_state', 'spot_state', 'funding', 'transfers')
        """
        sql = """
        INSERT INTO data_freshness (address, data_type, last_fetched)
        VALUES ($1, $2, NOW())
        ON CONFLICT (address, data_type)
        DO UPDATE SET last_fetched = NOW()
        """

        async with self.pool.acquire() as conn:
            await conn.execute(sql, address, data_type)
            logger.debug(f"[{address}] 更新 {data_type} 新鲜度标记")

    async def get_latest_transfer_time(self, address: str) -> Optional[int]:
        """
        获取地址最新的出入金时间戳（用于增量更新）

        Args:
            address: 用户地址

        Returns:
            最新出入金的时间戳（毫秒），如果没有记录返回None
        """
        sql = """
        SELECT EXTRACT(EPOCH FROM MAX(time)) * 1000 AS latest_time_ms
        FROM transfers
        WHERE address = $1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, address)
            if row and row['latest_time_ms']:
                return int(row['latest_time_ms'])
            return None

    async def get_transfers(self, address: str) -> List[Dict]:
        """
        获取地址的所有出入金记录

        Args:
            address: 地址

        Returns:
            出入金记录列表
        """
        sql = """
        SELECT * FROM transfers
        WHERE address = $1
        ORDER BY time ASC
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, address)
            return [dict(row) for row in rows]

    async def save_user_state(self, address: str, state: Dict):
        """
        保存用户 Perp 账户状态快照

        Args:
            address: 用户地址
            state: 账户状态数据（来自 user_state API）
        """
        if not state:
            return

        try:
            # 提取关键字段
            margin_summary = state.get('marginSummary', {})
            cross_margin_summary = state.get('crossMarginSummary', {})
            asset_positions = state.get('assetPositions', [])

            sql = """
            INSERT INTO user_states (
                address, snapshot_time, account_value, total_margin_used,
                total_ntl_pos, total_raw_usd, withdrawable,
                cross_margin_summary, asset_positions
            ) VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8)
            """

            async with self.pool.acquire() as conn:
                await conn.execute(
                    sql,
                    address,
                    float(margin_summary.get('accountValue', 0)),
                    float(margin_summary.get('totalMarginUsed', 0)),
                    float(margin_summary.get('totalNtlPos', 0)),
                    float(margin_summary.get('totalRawUsd', 0)),
                    float(state.get('withdrawable', 0)),
                    json.dumps(cross_margin_summary),
                    json.dumps(asset_positions)
                )
            logger.info(f"保存 Perp 账户状态快照: {address}")

        except Exception as e:
            logger.error(f"保存 user_state 失败: {address} - {e}")

    async def save_spot_state(self, address: str, spot_state: Dict):
        """
        保存用户 Spot 账户状态快照

        Args:
            address: 用户地址
            spot_state: Spot 账户状态数据（来自 spotClearinghouseState API）
        """
        if not spot_state:
            return

        try:
            # 提取 balances
            balances = spot_state.get('balances', [])

            sql = """
            INSERT INTO spot_states (address, snapshot_time, balances)
            VALUES ($1, NOW(), $2)
            """

            async with self.pool.acquire() as conn:
                await conn.execute(
                    sql,
                    address,
                    json.dumps(balances)
                )
            logger.info(f"保存 Spot 账户状态快照: {address}")

        except Exception as e:
            logger.error(f"保存 spot_state 失败: {address} - {e}")

    async def save_funding_history(self, address: str, funding: List[Dict]):
        """
        保存资金费率历史记录

        Args:
            address: 用户地址
            funding: 资金费率记录列表（来自 user_funding_history API）
        """
        if not funding:
            return

        # 先查询已存在的记录，避免重复插入
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # 获取所有待插入记录的 (time, coin) 组合
                keys = [(f.get('time'), f.get('coin')) for f in funding if f.get('time') and f.get('coin')]

                if keys:
                    # 查询已存在的记录
                    existing = await conn.fetch(
                        """
                        SELECT time, coin FROM funding_history
                        WHERE address = $1
                        AND (time, coin) IN (SELECT unnest($2::timestamptz[]), unnest($3::varchar[]))
                        """,
                        address,
                        [datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc) for k in keys],
                        [k[1] for k in keys]
                    )
                    existing_keys = {(row['time'], row['coin']) for row in existing}
                else:
                    existing_keys = set()

                # 过滤掉已存在的记录
                records_to_insert = []
                for record in funding:
                    time_ms = record.get('time')
                    coin = record.get('coin')

                    if not time_ms or not coin:
                        continue

                    time_dt = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)

                    # 检查是否已存在
                    if (time_dt, coin) in existing_keys:
                        continue

                    records_to_insert.append((
                        address,
                        time_dt,
                        coin,
                        float(record.get('usdc', 0)),
                        float(record.get('szi', 0)),
                        float(record.get('fundingRate', 0))
                    ))

                # 批量插入
                if records_to_insert:
                    sql = """
                    INSERT INTO funding_history (address, time, coin, usdc, szi, funding_rate)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (time, address, coin) DO NOTHING
                    """
                    await conn.executemany(sql, records_to_insert)
                    logger.info(f"保存 {len(records_to_insert)} 条资金费率记录: {address} (跳过 {len(funding) - len(records_to_insert)} 条重复)")
                else:
                    logger.info(f"无新资金费率记录需要保存: {address}")

    async def get_funding_history(self, address: str) -> List[Dict]:
        """
        获取地址的所有资金费率记录

        Args:
            address: 地址

        Returns:
            资金费率记录列表
        """
        sql = """
        SELECT * FROM funding_history
        WHERE address = $1
        ORDER BY time ASC
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, address)
            return [dict(row) for row in rows]

    async def get_latest_funding_time(self, address: str) -> Optional[int]:
        """
        获取地址最新的资金费率时间戳（用于增量更新）

        Args:
            address: 用户地址

        Returns:
            最新资金费率的时间戳（毫秒），如果没有记录返回None
        """
        sql = """
        SELECT EXTRACT(EPOCH FROM MAX(time)) * 1000 AS latest_time_ms
        FROM funding_history
        WHERE address = $1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, address)
            if row and row['latest_time_ms']:
                return int(row['latest_time_ms'])
            return None

    async def get_latest_user_state(self, address: str) -> Optional[Dict]:
        """
        获取地址最新的 Perp 账户状态

        Args:
            address: 用户地址

        Returns:
            最新账户状态
        """
        sql = """
        SELECT * FROM user_states
        WHERE address = $1
        ORDER BY snapshot_time DESC
        LIMIT 1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, address)
            if row:
                result = dict(row)
                # 解析 JSONB 字段
                if result.get('cross_margin_summary'):
                    result['cross_margin_summary'] = json.loads(result['cross_margin_summary']) if isinstance(result['cross_margin_summary'], str) else result['cross_margin_summary']
                if result.get('asset_positions'):
                    result['asset_positions'] = json.loads(result['asset_positions']) if isinstance(result['asset_positions'], str) else result['asset_positions']
                return result
            return None

    async def get_latest_spot_state(self, address: str) -> Optional[Dict]:
        """
        获取地址最新的 Spot 账户状态

        Args:
            address: 用户地址

        Returns:
            最新 Spot 账户状态
        """
        sql = """
        SELECT * FROM spot_states
        WHERE address = $1
        ORDER BY snapshot_time DESC
        LIMIT 1
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, address)
            if row:
                result = dict(row)
                # 解析 JSONB 字段
                if result.get('balances'):
                    result['balances'] = json.loads(result['balances']) if isinstance(result['balances'], str) else result['balances']
                return result
            return None

    async def save_metrics(self, address: str, metrics: Dict):
        """
        保存计算的指标

        Args:
            address: 地址
            metrics: 指标数据
        """
        # 数据库字段边界保护
        def safe_value(key: str, max_val: float, min_val: float = None) -> float:
            """安全地获取指标值，确保在数据库字段范围内"""
            value = float(metrics.get(key, 0))
            if min_val is not None:
                value = max(min_val, min(max_val, value))
            else:
                value = min(max_val, value)
            return value

        # 应用边界保护
        safe_metrics = {
            'total_trades': int(metrics.get('total_trades', 0)),
            'win_rate': safe_value('win_rate', 100.0, 0.0),  # DECIMAL(6, 2): 0-100
            'total_pnl': safe_value('total_pnl', 999999999999.99999999, -999999999999.99999999),  # DECIMAL(20, 8)
            'net_deposit': safe_value('net_deposit', 999999999999.99999999, -999999999999.99999999)  # DECIMAL(20, 8)
        }

        sql = """
        INSERT INTO metrics_cache (
            address, total_trades, win_rate,
            total_pnl, net_deposit, calculated_at
        ) VALUES ($1, $2, $3, $4, $5, NOW())
        ON CONFLICT (address) DO UPDATE
        SET total_trades = EXCLUDED.total_trades,
            win_rate = EXCLUDED.win_rate,
            total_pnl = EXCLUDED.total_pnl,
            net_deposit = EXCLUDED.net_deposit,
            calculated_at = NOW()
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                sql,
                address,
                safe_metrics['total_trades'],
                safe_metrics['win_rate'],
                safe_metrics['total_pnl'],
                safe_metrics['net_deposit']
            )



# 单例模式
_store_instance: Optional[DataStore] = None


def get_store() -> DataStore:
    """获取 DataStore 单例"""
    global _store_instance
    if _store_instance is None:
        _store_instance = DataStore()
    return _store_instance

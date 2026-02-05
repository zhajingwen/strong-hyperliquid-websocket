# 资金费率功能实施指南

## 📋 概述

本文档提供**资金费率分析功能**的**分步实施指南**,包括数据库迁移、代码实现、测试验证和部署上线的完整流程。

**实施范围**: 为 `analyze_addresses.py` 添加资金费率历史分析功能

**预计工作量**: 2-3天(包含测试和文档)

**依赖文档**:
- [FUNDING_RATE_SYSTEM_DESIGN.md](./FUNDING_RATE_SYSTEM_DESIGN.md) - 系统设计详情
- [API_user_funding_history.md](./API_user_funding_history.md) - API 使用说明

---

## 🎯 实施目标

### 核心功能

✅ 从 Hyperliquid API 获取资金费率历史数据
✅ 存储到 PostgreSQL + TimescaleDB 数据库
✅ 计算资金费率相关指标
✅ 在终端和 HTML 报告中展示分析结果
✅ 提供缓存和性能优化

### 技术指标

- **数据完整性**: 99%+ 的数据准确率
- **查询性能**: <500ms 查询响应时间
- **缓存命中率**: >80% API 调用缓存命中
- **并发处理**: 支持 10+ 并发地址分析

---

## 📝 实施步骤

### 阶段 1: 数据库准备 (30分钟)

#### 步骤 1.1: 创建数据库迁移脚本

**文件**: `migrations/003_add_funding_tables.sql`

```sql
-- ============================================
-- 资金费率功能数据库迁移脚本
-- 版本: v1.0
-- 创建日期: 2026-02-03
-- ============================================

BEGIN;

-- 1. 创建资金费率记录表
CREATE TABLE IF NOT EXISTS funding_payments (
    id BIGSERIAL,
    address VARCHAR(42) NOT NULL,
    time TIMESTAMPTZ NOT NULL,
    coin VARCHAR(20) NOT NULL,
    funding_usdc DECIMAL(20, 8),
    position_size DECIMAL(20, 4),
    funding_rate DECIMAL(12, 8),
    n_samples INTEGER,
    tx_hash VARCHAR(66),
    PRIMARY KEY (id, time)
);

-- 2. 创建资金费率统计表
CREATE TABLE IF NOT EXISTS funding_stats (
    address VARCHAR(42) PRIMARY KEY,
    total_funding_usdc DECIMAL(20, 8),
    total_funding_income DECIMAL(20, 8),
    total_funding_expense DECIMAL(20, 8),
    avg_funding_rate DECIMAL(12, 8),
    annual_funding_rate DECIMAL(8, 4),
    funding_payment_count INTEGER,
    funding_income_count INTEGER,
    funding_expense_count INTEGER,
    funding_coin_count INTEGER,
    first_funding_time TIMESTAMPTZ,
    last_funding_time TIMESTAMPTZ,
    calculated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 创建币种统计表
CREATE TABLE IF NOT EXISTS funding_coin_stats (
    address VARCHAR(42) NOT NULL,
    coin VARCHAR(20) NOT NULL,
    total_funding_usdc DECIMAL(20, 8),
    avg_position_size DECIMAL(20, 4),
    avg_funding_rate DECIMAL(12, 8),
    payment_count INTEGER,
    holding_days DECIMAL(8, 2),
    first_payment_time TIMESTAMPTZ,
    last_payment_time TIMESTAMPTZ,
    calculated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (address, coin)
);

-- 4. 创建索引
CREATE INDEX IF NOT EXISTS idx_funding_address_time ON funding_payments(address, time DESC);
CREATE INDEX IF NOT EXISTS idx_funding_coin_time ON funding_payments(coin, time DESC);
CREATE INDEX IF NOT EXISTS idx_funding_address_coin ON funding_payments(address, coin, time DESC);
CREATE INDEX IF NOT EXISTS idx_funding_stats_total ON funding_stats(total_funding_usdc DESC);
CREATE INDEX IF NOT EXISTS idx_funding_stats_rate ON funding_stats(annual_funding_rate DESC);
CREATE INDEX IF NOT EXISTS idx_funding_coin_stats_addr ON funding_coin_stats(address);
CREATE INDEX IF NOT EXISTS idx_funding_coin_stats_coin ON funding_coin_stats(coin);

-- 5. 转换为 TimescaleDB hypertable (可选)
DO $$
BEGIN
    -- 检查 TimescaleDB 扩展是否存在
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        -- 检查表是否为空
        IF NOT EXISTS (SELECT 1 FROM funding_payments LIMIT 1) THEN
            -- 转换为 hypertable
            PERFORM create_hypertable('funding_payments', 'time',
                chunk_time_interval => INTERVAL '30 days',
                if_not_exists => TRUE
            );
            RAISE NOTICE 'funding_payments 已转换为 TimescaleDB hypertable';
        ELSE
            RAISE NOTICE 'funding_payments 表已有数据,跳过 hypertable 转换';
        END IF;
    ELSE
        RAISE NOTICE 'TimescaleDB 扩展未安装,跳过 hypertable 创建';
    END IF;
END $$;

COMMIT;

-- 验证表创建
SELECT
    table_name,
    table_type,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) as column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
  AND table_name IN ('funding_payments', 'funding_stats', 'funding_coin_stats')
ORDER BY table_name;
```

#### 步骤 1.2: 执行迁移

```bash
# 方式 1: 使用 psql 命令行
psql -U postgres -d hyperliquid_analysis -f migrations/003_add_funding_tables.sql

# 方式 2: 使用 Python 脚本
python scripts/run_migration.py migrations/003_add_funding_tables.sql

# 验证表创建成功
psql -U postgres -d hyperliquid_analysis -c "\dt funding*"
```

---

### 阶段 2: 数据存储层实现 (60分钟)

#### 步骤 2.1: 扩展 DataStore 类

**文件**: `address_analyzer/data_store.py`

在现有 `DataStore` 类中添加以下方法:

```python
# ============================================
# 在 DataStore 类中添加以下方法
# ============================================

async def save_funding_payments(self, address: str, funding_data: List[Dict]):
    """
    批量保存资金费率记录

    Args:
        address: 用户地址
        funding_data: API 返回的资金费率列表
    """
    if not funding_data:
        return

    records_to_insert = []

    for record in funding_data:
        time_ms = record.get('time', 0)
        delta = record.get('delta', {})

        # 验证数据类型
        if delta.get('type') != 'funding':
            continue

        # 转换时间戳
        time_dt = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)

        records_to_insert.append((
            address,
            time_dt,
            delta.get('coin'),
            float(delta.get('usdc', 0)),
            float(delta.get('szi', 0)),
            float(delta.get('fundingRate', 0)),
            delta.get('nSamples', 0),
            record.get('hash', '')
        ))

    if not records_to_insert:
        logger.info(f"无资金费率记录需要保存: {address}")
        return

    async with self.pool.acquire() as conn:
        # 去重检查
        check_sql = """
        SELECT time, coin FROM funding_payments
        WHERE address = $1 AND time = ANY($2::timestamptz[]) AND coin = ANY($3::varchar[])
        """

        times = [r[1] for r in records_to_insert]
        coins = [r[2] for r in records_to_insert]

        existing = await conn.fetch(check_sql, address, times, coins)
        existing_set = {(row['time'], row['coin']) for row in existing}

        # 过滤已存在的记录
        new_records = [
            r for r in records_to_insert
            if (r[1], r[2]) not in existing_set
        ]

        if new_records:
            insert_sql = """
            INSERT INTO funding_payments (
                address, time, coin, funding_usdc, position_size,
                funding_rate, n_samples, tx_hash
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """
            await conn.executemany(insert_sql, new_records)
            logger.info(f"保存 {len(new_records)}/{len(records_to_insert)} 条资金费率记录: {address}")
        else:
            logger.info(f"无新记录需要保存: {address} (全部重复)")


async def get_funding_payments(
    self,
    address: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    coin: Optional[str] = None
) -> List[Dict]:
    """
    查询资金费率记录

    Args:
        address: 用户地址
        start_time: 起始时间
        end_time: 结束时间
        coin: 币种过滤

    Returns:
        资金费率记录列表
    """
    conditions = ["address = $1"]
    params = [address]
    param_idx = 2

    if start_time:
        conditions.append(f"time >= ${param_idx}")
        params.append(start_time)
        param_idx += 1

    if end_time:
        conditions.append(f"time <= ${param_idx}")
        params.append(end_time)
        param_idx += 1

    if coin:
        conditions.append(f"coin = ${param_idx}")
        params.append(coin)

    sql = f"""
    SELECT
        time,
        coin,
        funding_usdc,
        position_size,
        funding_rate,
        n_samples,
        tx_hash
    FROM funding_payments
    WHERE {' AND '.join(conditions)}
    ORDER BY time ASC
    """

    async with self.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
        return [dict(row) for row in rows]


async def get_funding_stats(self, address: str) -> Optional[Dict]:
    """
    获取资金费率统计

    Args:
        address: 用户地址

    Returns:
        统计数据字典,如果不存在则返回 None
    """
    sql = """
    SELECT * FROM funding_stats
    WHERE address = $1
    """

    async with self.pool.acquire() as conn:
        row = await conn.fetchrow(sql, address)
        return dict(row) if row else None


async def save_funding_stats(self, address: str, stats: Dict):
    """
    保存资金费率统计数据

    Args:
        address: 用户地址
        stats: 统计指标字典
    """
    sql = """
    INSERT INTO funding_stats (
        address, total_funding_usdc, total_funding_income,
        total_funding_expense, avg_funding_rate, annual_funding_rate,
        funding_payment_count, funding_income_count,
        funding_expense_count, funding_coin_count,
        first_funding_time, last_funding_time, calculated_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
    ON CONFLICT (address) DO UPDATE
    SET total_funding_usdc = EXCLUDED.total_funding_usdc,
        total_funding_income = EXCLUDED.total_funding_income,
        total_funding_expense = EXCLUDED.total_funding_expense,
        avg_funding_rate = EXCLUDED.avg_funding_rate,
        annual_funding_rate = EXCLUDED.annual_funding_rate,
        funding_payment_count = EXCLUDED.funding_payment_count,
        funding_income_count = EXCLUDED.funding_income_count,
        funding_expense_count = EXCLUDED.funding_expense_count,
        funding_coin_count = EXCLUDED.funding_coin_count,
        first_funding_time = EXCLUDED.first_funding_time,
        last_funding_time = EXCLUDED.last_funding_time,
        calculated_at = NOW()
    """

    async with self.pool.acquire() as conn:
        await conn.execute(
            sql,
            address,
            stats.get('total_funding_usdc', 0.0),
            stats.get('total_funding_income', 0.0),
            stats.get('total_funding_expense', 0.0),
            stats.get('avg_funding_rate', 0.0),
            stats.get('annual_funding_rate', 0.0),
            stats.get('funding_payment_count', 0),
            stats.get('funding_income_count', 0),
            stats.get('funding_expense_count', 0),
            stats.get('funding_coin_count', 0),
            stats.get('first_funding_time'),
            stats.get('last_funding_time')
        )

    # 保存币种分解统计
    if 'coin_breakdown' in stats:
        await self._save_funding_coin_stats(address, stats['coin_breakdown'])


async def _save_funding_coin_stats(self, address: str, coin_breakdown: Dict):
    """
    保存币种分解统计

    Args:
        address: 用户地址
        coin_breakdown: {coin: {total_funding, count, avg_position, holding_days, ...}}
    """
    if not coin_breakdown:
        return

    sql = """
    INSERT INTO funding_coin_stats (
        address, coin, total_funding_usdc, avg_position_size,
        avg_funding_rate, payment_count, holding_days,
        first_payment_time, last_payment_time, calculated_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
    ON CONFLICT (address, coin) DO UPDATE
    SET total_funding_usdc = EXCLUDED.total_funding_usdc,
        avg_position_size = EXCLUDED.avg_position_size,
        avg_funding_rate = EXCLUDED.avg_funding_rate,
        payment_count = EXCLUDED.payment_count,
        holding_days = EXCLUDED.holding_days,
        first_payment_time = EXCLUDED.first_payment_time,
        last_payment_time = EXCLUDED.last_payment_time,
        calculated_at = NOW()
    """

    records = []
    for coin, stats in coin_breakdown.items():
        records.append((
            address,
            coin,
            stats.get('total_funding', 0.0),
            stats.get('avg_position', 0.0),
            stats.get('avg_rate', 0.0),
            stats.get('count', 0),
            stats.get('holding_days', 0.0),
            stats.get('first_time'),
            stats.get('last_time')
        ))

    async with self.pool.acquire() as conn:
        await conn.executemany(sql, records)

    logger.info(f"保存 {len(records)} 个币种的统计数据: {address}")
```

#### 步骤 2.2: 更新 init_schema 方法

在 `DataStore.init_schema()` 方法中添加资金费率表的创建:

```python
async def init_schema(self):
    """初始化数据库Schema"""
    # ... 现有代码 ...

    # 添加资金费率表创建
    funding_tables_sql = """
    -- 资金费率记录表
    CREATE TABLE IF NOT EXISTS funding_payments (
        id BIGSERIAL,
        address VARCHAR(42) NOT NULL,
        time TIMESTAMPTZ NOT NULL,
        coin VARCHAR(20) NOT NULL,
        funding_usdc DECIMAL(20, 8),
        position_size DECIMAL(20, 4),
        funding_rate DECIMAL(12, 8),
        n_samples INTEGER,
        tx_hash VARCHAR(66),
        PRIMARY KEY (id, time)
    );

    -- 资金费率统计表
    CREATE TABLE IF NOT EXISTS funding_stats (
        address VARCHAR(42) PRIMARY KEY,
        total_funding_usdc DECIMAL(20, 8),
        total_funding_income DECIMAL(20, 8),
        total_funding_expense DECIMAL(20, 8),
        avg_funding_rate DECIMAL(12, 8),
        annual_funding_rate DECIMAL(8, 4),
        funding_payment_count INTEGER,
        funding_income_count INTEGER,
        funding_expense_count INTEGER,
        funding_coin_count INTEGER,
        first_funding_time TIMESTAMPTZ,
        last_funding_time TIMESTAMPTZ,
        calculated_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- 币种统计表
    CREATE TABLE IF NOT EXISTS funding_coin_stats (
        address VARCHAR(42) NOT NULL,
        coin VARCHAR(20) NOT NULL,
        total_funding_usdc DECIMAL(20, 8),
        avg_position_size DECIMAL(20, 4),
        avg_funding_rate DECIMAL(12, 8),
        payment_count INTEGER,
        holding_days DECIMAL(8, 2),
        first_payment_time TIMESTAMPTZ,
        last_payment_time TIMESTAMPTZ,
        calculated_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (address, coin)
    );

    -- 索引
    CREATE INDEX IF NOT EXISTS idx_funding_address_time ON funding_payments(address, time DESC);
    CREATE INDEX IF NOT EXISTS idx_funding_coin_time ON funding_payments(coin, time DESC);
    CREATE INDEX IF NOT EXISTS idx_funding_address_coin ON funding_payments(address, coin, time DESC);
    """

    async with self.pool.acquire() as conn:
        # 创建基础表
        await conn.execute(schema_sql)  # 现有表
        await conn.execute(funding_tables_sql)  # 新增表
        logger.info("资金费率表创建成功")

        # ... TimescaleDB hypertable 转换 ...
```

---

### 阶段 3: API 客户端扩展 (45分钟)

#### 步骤 3.1: 添加资金费率获取方法

**文件**: `address_analyzer/api_client.py`

```python
# ============================================
# 在 HyperliquidAPIClient 类中添加以下方法
# ============================================

async def fetch_funding_data(
    self,
    address: str,
    lookback_days: int = 90,
    save_to_db: bool = True
) -> Dict:
    """
    获取并保存资金费率数据

    Args:
        address: 用户地址
        lookback_days: 回溯天数(默认90天)
        save_to_db: 是否保存到数据库

    Returns:
        {'funding_payments': List[Dict], 'stats': Dict}
    """
    # 1. 检查数据新鲜度
    if not self.force_refresh:
        is_fresh = await self.store.is_data_fresh(address, 'funding')
        if is_fresh:
            # 从数据库获取已有数据
            existing_data = await self.store.get_funding_payments(address)
            if existing_data:
                logger.info(f"使用缓存的资金费率数据: {address[:10]}...")
                stats = self._calculate_funding_stats(existing_data)
                return {'funding_payments': existing_data, 'stats': stats}

    # 2. 调用 API
    try:
        # 计算时间范围
        current_time = int(time.time() * 1000)
        start_time = current_time - (lookback_days * 24 * 60 * 60 * 1000)

        async with self.rate_limiter:
            async with self.semaphore:
                funding_history = self.info.user_funding_history(
                    user=address,
                    startTime=start_time
                )

        logger.info(f"获取资金费率数据: {address[:10]}... ({len(funding_history)} 条)")

        # 3. 保存到数据库
        if save_to_db and funding_history:
            await self.store.save_funding_payments(address, funding_history)

        # 4. 计算统计数据
        stats = self._calculate_funding_stats(funding_history)

        # 5. 更新数据新鲜度标记
        await self.store.update_data_freshness(address, 'funding')

        result = {
            'funding_payments': funding_history,
            'stats': stats
        }

        # 更新统计
        self.stats['total_requests'] += 1

        return result

    except Exception as e:
        logger.error(f"获取资金费率数据失败: {address[:10]}... - {e}")
        self.stats['api_errors'] += 1
        return {'funding_payments': [], 'stats': {}}


def _calculate_funding_stats(self, funding_data: List[Dict]) -> Dict:
    """
    计算资金费率基础统计

    Args:
        funding_data: 资金费率记录列表

    Returns:
        统计数据字典
    """
    if not funding_data:
        return {
            'total_funding_usdc': 0.0,
            'total_funding_income': 0.0,
            'total_funding_expense': 0.0,
            'avg_funding_rate': 0.0,
            'annual_funding_rate': 0.0,
            'funding_payment_count': 0,
            'funding_income_count': 0,
            'funding_expense_count': 0,
            'funding_coin_count': 0
        }

    # 提取基础数据
    funding_values = []
    income_records = []
    expense_records = []
    rates = []
    coins = set()

    for record in funding_data:
        delta = record.get('delta', {})
        usdc = float(delta.get('usdc', 0))
        rate = float(delta.get('fundingRate', 0))
        coin = delta.get('coin')

        funding_values.append(usdc)
        rates.append(rate)
        coins.add(coin)

        if usdc > 0:
            income_records.append(usdc)
        elif usdc < 0:
            expense_records.append(abs(usdc))

    # 计算统计指标
    total_funding = sum(funding_values)
    total_income = sum(income_records)
    total_expense = sum(expense_records)
    avg_rate = sum(rates) / len(rates) if rates else 0.0
    annual_rate = avg_rate * 8 * 365 * 100  # 年化百分比

    return {
        'total_funding_usdc': total_funding,
        'total_funding_income': total_income,
        'total_funding_expense': total_expense,
        'avg_funding_rate': avg_rate,
        'annual_funding_rate': annual_rate,
        'funding_payment_count': len(funding_data),
        'funding_income_count': len(income_records),
        'funding_expense_count': len(expense_records),
        'funding_coin_count': len(coins)
    }
```

---

### 阶段 4: 指标计算引擎扩展 (60分钟)

#### 步骤 4.1: 扩展 AddressMetrics 数据类

**文件**: `address_analyzer/metrics_engine.py`

```python
# ============================================
# 修改 AddressMetrics 数据类
# ============================================

from dataclasses import dataclass, field
from typing import Optional, Dict

@dataclass
class AddressMetrics:
    """地址综合指标"""

    # ... 现有字段 ...

    # 新增: 资金费率指标
    total_funding_usdc: float = 0.0          # 累计资金费用
    funding_income: float = 0.0              # 资金费收入
    funding_expense: float = 0.0             # 资金费支出
    annual_funding_rate: float = 0.0         # 年化资金费率(%)
    funding_payment_count: int = 0           # 结算次数
    funding_income_count: int = 0            # 收入次数
    funding_expense_count: int = 0           # 支出次数
    funding_coin_count: int = 0              # 涉及币种数
    funding_adjusted_pnl: float = 0.0        # 资金费调整后的盈亏
    funding_to_pnl_ratio: float = 0.0        # 资金费占盈亏比例(%)

    # 币种分解(可选)
    funding_coin_breakdown: Dict = field(default_factory=dict)
```

#### 步骤 4.2: 添加资金费率指标计算

```python
# ============================================
# 在 MetricsEngine 类中添加方法
# ============================================

def calculate_funding_metrics(
    self,
    address: str,
    funding_payments: List[Dict]
) -> Dict:
    """
    计算资金费率指标

    Args:
        address: 用户地址
        funding_payments: 资金费率记录列表

    Returns:
        资金费率指标字典
    """
    if not funding_payments:
        return self._empty_funding_metrics()

    # 1. 基础统计
    total_funding = 0.0
    income_records = []
    expense_records = []
    rates = []
    coin_stats = defaultdict(lambda: {
        'total_funding': 0.0,
        'count': 0,
        'position_sum': 0.0,
        'rate_sum': 0.0,
        'times': []
    })

    for record in funding_payments:
        delta = record.get('delta', {})
        usdc = float(delta.get('usdc', 0))
        rate = float(delta.get('fundingRate', 0))
        position = float(delta.get('szi', 0))
        coin = delta.get('coin')
        time_ms = record.get('time', 0)

        # 总统计
        total_funding += usdc
        rates.append(rate)

        if usdc > 0:
            income_records.append(usdc)
        elif usdc < 0:
            expense_records.append(abs(usdc))

        # 币种统计
        coin_stats[coin]['total_funding'] += usdc
        coin_stats[coin]['count'] += 1
        coin_stats[coin]['position_sum'] += abs(position)
        coin_stats[coin]['rate_sum'] += rate
        coin_stats[coin]['times'].append(time_ms)

    # 2. 聚合计算
    total_income = sum(income_records)
    total_expense = sum(expense_records)
    avg_rate = np.mean(rates) if rates else 0.0
    annual_rate = avg_rate * 8 * 365 * 100  # 年化百分比

    # 3. 币种分解
    coin_breakdown = {}
    for coin, stats in coin_stats.items():
        coin_breakdown[coin] = {
            'total_funding': stats['total_funding'],
            'count': stats['count'],
            'avg_position': stats['position_sum'] / stats['count'],
            'avg_rate': stats['rate_sum'] / stats['count'],
            'holding_days': stats['count'] / 8,
            'first_time': datetime.fromtimestamp(min(stats['times']) / 1000, tz=timezone.utc),
            'last_time': datetime.fromtimestamp(max(stats['times']) / 1000, tz=timezone.utc)
        }

    # 4. 时间范围
    all_times = [r['time'] for r in funding_payments]
    first_time = datetime.fromtimestamp(min(all_times) / 1000, tz=timezone.utc)
    last_time = datetime.fromtimestamp(max(all_times) / 1000, tz=timezone.utc)

    return {
        'address': address,
        'total_funding_usdc': total_funding,
        'total_funding_income': total_income,
        'total_funding_expense': total_expense,
        'avg_funding_rate': avg_rate,
        'annual_funding_rate': annual_rate,
        'funding_payment_count': len(funding_payments),
        'funding_income_count': len(income_records),
        'funding_expense_count': len(expense_records),
        'funding_coin_count': len(coin_stats),
        'coin_breakdown': coin_breakdown,
        'first_funding_time': first_time,
        'last_funding_time': last_time
    }


def _empty_funding_metrics(self) -> Dict:
    """返回空的资金费率指标"""
    return {
        'total_funding_usdc': 0.0,
        'total_funding_income': 0.0,
        'total_funding_expense': 0.0,
        'avg_funding_rate': 0.0,
        'annual_funding_rate': 0.0,
        'funding_payment_count': 0,
        'funding_income_count': 0,
        'funding_expense_count': 0,
        'funding_coin_count': 0,
        'coin_breakdown': {},
        'first_funding_time': None,
        'last_funding_time': None
    }
```

#### 步骤 4.3: 整合到主计算方法

修改 `calculate_metrics()` 方法,集成资金费率指标:

```python
async def calculate_metrics(
    self,
    address: str,
    fills: List[Dict],
    state: Optional[Dict] = None,
    transfer_data: Optional[Dict] = None,
    spot_state: Optional[Dict] = None,
    funding_stats: Optional[Dict] = None  # 新增参数
) -> AddressMetrics:
    """计算综合指标"""

    # ... 现有计算逻辑 ...

    # 新增: 集成资金费率指标
    if funding_stats:
        metrics.total_funding_usdc = funding_stats.get('total_funding_usdc', 0.0)
        metrics.funding_income = funding_stats.get('total_funding_income', 0.0)
        metrics.funding_expense = funding_stats.get('total_funding_expense', 0.0)
        metrics.annual_funding_rate = funding_stats.get('annual_funding_rate', 0.0)
        metrics.funding_payment_count = funding_stats.get('funding_payment_count', 0)
        metrics.funding_income_count = funding_stats.get('funding_income_count', 0)
        metrics.funding_expense_count = funding_stats.get('funding_expense_count', 0)
        metrics.funding_coin_count = funding_stats.get('funding_coin_count', 0)
        metrics.funding_coin_breakdown = funding_stats.get('coin_breakdown', {})

        # 计算资金费调整后的真实盈亏
        metrics.funding_adjusted_pnl = metrics.total_pnl + metrics.total_funding_usdc

        # 计算资金费占盈亏比例
        if metrics.total_pnl != 0:
            metrics.funding_to_pnl_ratio = (
                abs(metrics.total_funding_usdc) / abs(metrics.total_pnl) * 100
            )

    return metrics
```

---

### 阶段 5: 主控制器集成 (30分钟)

#### 步骤 5.1: 修改 Orchestrator

**文件**: `address_analyzer/orchestrator.py`

在 `run()` 方法中添加资金费率数据获取:

```python
async def run(self, ...):
    """运行完整分析流程"""

    # ... 步骤 1-3: 现有代码 ...

    # 新增步骤 3.5: 获取资金费率数据
    self.renderer.console.print(
        f"[bold cyan]步骤 3.5/6:[/bold cyan] 获取资金费率数据({len(pending_addresses)} 个地址)..."
    )

    funding_results = []
    with Progress(...) as progress:
        task = progress.add_task("正在获取资金费率...", total=len(pending_addresses))

        async def fetch_funding(addr: str):
            try:
                result = await self.api_client.fetch_funding_data(addr, save_to_db=True)
                progress.advance(task)
                return (addr, result)
            except Exception as e:
                logger.error(f"获取资金费率失败: {addr[:10]}... - {e}")
                progress.advance(task)
                return (addr, None)

        tasks = [fetch_funding(addr) for addr in pending_addresses]
        funding_results = await asyncio.gather(*tasks)

    # 统计成功率
    successful_funding = sum(1 for _, result in funding_results if result and result['funding_payments'])
    self.renderer.console.print(
        f"✅ 成功获取 [bold]{successful_funding}[/bold] 个地址的资金费率数据\n"
    )

    # ... 步骤 4-5: 现有代码(计算指标) ...

    # 修改指标计算部分
    all_metrics = []
    for addr in addresses:
        # 现有数据
        fills = await self.store.get_fills(addr)
        state = await self.store.get_latest_user_state(addr)
        spot_state = await self.store.get_latest_spot_state(addr)
        transfer_stats = await self.store.get_net_deposits(addr)

        # 新增: 获取资金费率统计
        funding_stats = await self.store.get_funding_stats(addr)

        # 计算指标(传入 funding_stats)
        metrics = self.metrics_engine.calculate_metrics(
            address=addr,
            fills=fills,
            state=state,
            transfer_data=transfer_stats,
            spot_state=spot_state,
            funding_stats=funding_stats  # 新增参数
        )
        all_metrics.append(metrics)

        # 如果没有缓存的统计数据,实时计算并保存
        if not funding_stats:
            funding_payments = await self.store.get_funding_payments(addr)
            if funding_payments:
                fresh_stats = self.metrics_engine.calculate_funding_metrics(
                    addr,
                    funding_payments
                )
                await self.store.save_funding_stats(addr, fresh_stats)

    # ... 继续报告生成 ...
```

---

### 阶段 6: 报告展示实现 (60分钟)

#### 步骤 6.1: 扩展终端输出

**文件**: `address_analyzer/output_renderer.py`

```python
def render_terminal(self, metrics: List[AddressMetrics], top_n: int = 50, save_path: Optional[str] = None):
    """渲染终端表格"""

    # 创建主表格
    table = Table(
        title=f"[bold cyan]交易地址综合分析[/bold cyan] (前 {top_n} 名)",
        show_header=True,
        header_style="bold magenta"
    )

    # 现有列
    table.add_column("排名", style="dim", width=4)
    table.add_column("地址", style="cyan", width=12)
    table.add_column("总盈亏", style="green", justify="right", width=12)
    table.add_column("ROI", style="yellow", justify="right", width=8)
    table.add_column("夏普", style="blue", justify="right", width=7)

    # 新增列
    table.add_column("资金费用", style="magenta", justify="right", width=12)
    table.add_column("调整后PnL", style="green", justify="right", width=12)
    table.add_column("年化费率", style="red", justify="right", width=9)

    # 按 total_pnl 排序
    sorted_metrics = sorted(metrics, key=lambda m: m.total_pnl, reverse=True)[:top_n]

    for rank, m in enumerate(sorted_metrics, 1):
        # 资金费用显示(绿色=收入,红色=支出)
        funding_style = "green" if m.total_funding_usdc > 0 else "red"
        funding_str = f"[{funding_style}]{m.total_funding_usdc:+,.2f}[/{funding_style}]"

        # 调整后PnL
        adjusted_pnl_style = "green" if m.funding_adjusted_pnl > 0 else "red"
        adjusted_pnl_str = f"[{adjusted_pnl_style}]{m.funding_adjusted_pnl:+,.2f}[/{adjusted_pnl_style}]"

        table.add_row(
            str(rank),
            m.address[:10] + "...",
            f"{m.total_pnl:+,.2f}",
            f"{m.roi:+.2f}%",
            f"{m.sharpe_ratio:.2f}",
            funding_str,
            adjusted_pnl_str,
            f"{m.annual_funding_rate:+.2f}%"
        )

    self.console.print("\n")
    self.console.print(table)

    # 新增: 资金费率专题表格
    self._render_funding_summary(metrics)

    # ... 保存到文件逻辑 ...


def _render_funding_summary(self, metrics: List[AddressMetrics]):
    """渲染资金费率汇总表"""

    # 过滤有资金费数据的地址
    funding_metrics = [m for m in metrics if m.funding_payment_count > 0]

    if not funding_metrics:
        return

    # 创建资金费率汇总表
    funding_table = Table(
        title="[bold yellow]💰 资金费率分析汇总[/bold yellow]",
        show_header=True,
        header_style="bold yellow"
    )

    funding_table.add_column("地址", style="cyan", width=12)
    funding_table.add_column("累计费用", justify="right", width=12)
    funding_table.add_column("收入次数", justify="right", width=10)
    funding_table.add_column("支出次数", justify="right", width=10)
    funding_table.add_column("年化费率", justify="right", width=10)
    funding_table.add_column("币种数", justify="right", width=8)

    # 按累计资金费用排序
    sorted_funding = sorted(funding_metrics, key=lambda m: m.total_funding_usdc, reverse=True)[:20]

    for m in sorted_funding:
        funding_style = "green" if m.total_funding_usdc > 0 else "red"
        funding_str = f"[{funding_style}]{m.total_funding_usdc:+,.2f}[/{funding_style}]"

        funding_table.add_row(
            m.address[:10] + "...",
            funding_str,
            f"{m.funding_income_count}",
            f"{m.funding_expense_count}",
            f"{m.annual_funding_rate:+.2f}%",
            str(m.funding_coin_count)
        )

    self.console.print("\n")
    self.console.print(funding_table)
```

#### 步骤 6.2: 扩展 HTML 报告

在 HTML 模板中添加资金费率模块(此处简化,实际需要修改模板文件):

```python
def render_html(self, metrics: List[AddressMetrics], output_path: str = "output/analysis_report.html"):
    """生成 HTML 报告"""

    # ... 现有代码 ...

    # 新增: 资金费率数据准备
    funding_data = []
    for m in metrics:
        if m.funding_payment_count > 0:
            funding_data.append({
                'address': m.address,
                'total_funding': m.total_funding_usdc,
                'income': m.funding_income,
                'expense': m.funding_expense,
                'annual_rate': m.annual_funding_rate,
                'payment_count': m.funding_payment_count,
                'coin_count': m.funding_coin_count,
                'funding_adjusted_pnl': m.funding_adjusted_pnl,
                'funding_ratio': m.funding_to_pnl_ratio
            })

    # 传递给模板
    context = {
        'metrics': metrics,
        'funding_data': funding_data,  # 新增
        # ... 其他上下文 ...
    }

    # ... 渲染模板 ...
```

---

## ✅ 测试验证

### 单元测试

**文件**: `tests/test_funding_rate.py`

```python
import pytest
import asyncio
from address_analyzer.data_store import DataStore, get_store
from address_analyzer.api_client import HyperliquidAPIClient
from address_analyzer.metrics_engine import MetricsEngine

@pytest.fixture
async def store():
    """测试数据库连接"""
    store = get_store()
    await store.connect(max_connections=5)
    yield store
    await store.close()


@pytest.mark.asyncio
async def test_save_funding_payments(store):
    """测试保存资金费率记录"""
    test_address = "0x1234567890abcdef1234567890abcdef12345678"

    # 模拟API返回数据
    funding_data = [
        {
            'time': 1704067200000,
            'hash': '0x0000000000000000000000000000000000000000000000000000000000000000',
            'delta': {
                'type': 'funding',
                'coin': 'BTC',
                'usdc': '-14.391152',
                'szi': '0.54353',
                'fundingRate': '0.0000106497',
                'nSamples': 24
            }
        }
    ]

    # 保存
    await store.save_funding_payments(test_address, funding_data)

    # 验证
    payments = await store.get_funding_payments(test_address)
    assert len(payments) == 1
    assert payments[0]['coin'] == 'BTC'
    assert float(payments[0]['funding_usdc']) == -14.391152


@pytest.mark.asyncio
async def test_calculate_funding_metrics():
    """测试资金费率指标计算"""
    engine = MetricsEngine()

    funding_payments = [
        {
            'time': 1704067200000,
            'delta': {
                'coin': 'BTC',
                'usdc': '-14.391152',
                'szi': '0.54353',
                'fundingRate': '0.0000106497'
            }
        },
        {
            'time': 1704070800000,
            'delta': {
                'coin': 'ETH',
                'usdc': '5.123456',
                'szi': '-10.5',
                'fundingRate': '-0.0000245678'
            }
        }
    ]

    metrics = engine.calculate_funding_metrics('test_address', funding_payments)

    assert metrics['funding_payment_count'] == 2
    assert metrics['funding_coin_count'] == 2
    assert metrics['total_funding_usdc'] < 0  # 净支出
    assert metrics['funding_income_count'] == 1
    assert metrics['funding_expense_count'] == 1


# 运行测试
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
```

---

### 集成测试

```bash
# 1. 测试单个地址分析
python analyze_addresses.py --force-refresh --output terminal --top-n 10

# 2. 验证数据库记录
psql -U postgres -d hyperliquid_analysis -c "SELECT COUNT(*) FROM funding_payments;"

# 3. 检查统计数据
psql -U postgres -d hyperliquid_analysis -c "SELECT * FROM funding_stats LIMIT 5;"

# 4. 生成完整报告
python analyze_addresses.py --output both --html-path output/full_report.html
```

---

## 🚀 部署上线

### 部署清单

- [x] 数据库迁移脚本执行
- [x] 代码部署到生产环境
- [x] 环境变量配置
- [x] 缓存预热
- [x] 监控告警配置

### 监控指标

```python
# 关键监控指标
- funding_api_success_rate  # API 成功率 > 95%
- funding_cache_hit_rate    # 缓存命中率 > 80%
- funding_calc_time         # 计算耗时 < 500ms
- funding_data_quality      # 数据完整性 > 99%
```

---

## 📚 相关文档

- [FUNDING_RATE_SYSTEM_DESIGN.md](./FUNDING_RATE_SYSTEM_DESIGN.md) - 系统设计文档
- [API_user_funding_history.md](./API_user_funding_history.md) - API 接口说明
- [Database Schema](../address_analyzer/data_store.py) - 数据库表结构

---

**文档版本**: v1.0
**创建日期**: 2026-02-03
**预计完成**: 2-3天
**状态**: ✅ 实施指南完成

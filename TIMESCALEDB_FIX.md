# TimescaleDB 数据库修复记录

## 问题描述

运行 `analyze_addresses.py` 时出现以下错误：

```
null value in column "id" of relation "_hyper_6_xxx_chunk" violates not-null constraint
```

## 根本原因

1. **表结构问题**：
   - 原始 `fills` 表定义中，`id` 列为 `BIGSERIAL`（自增），主键为 `(address, time, id)`
   - 插入语句没有包含 `id` 列，期望其自动生成
   - 当表转换为 TimescaleDB hypertable 后，`id` 不再自动生成

2. **ON CONFLICT 约束问题**：
   - 原始代码使用 `ON CONFLICT (address, time, id)` 或 `ON CONFLICT (time, address, hash)`
   - TimescaleDB hypertable 要求主键必须包含分区键（`time`）
   - 无法在非主键列上使用 `ON CONFLICT`

## 解决方案

### 1. 修改表结构

将 `fills` 表改为使用 `(time, id)` 作为主键：

```sql
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
);
```

### 2. 修改插入逻辑

在 `address_analyzer/data_store.py` 的 `save_fills` 方法中：

- **移除**: `ON CONFLICT` 子句（不再适用于 hypertable）
- **添加**: 先查询已存在的 `hash`，过滤重复记录
- **实现**: 应用层去重逻辑

```python
# 查询已存在的 hash
existing_hashes = await conn.fetch(
    "SELECT hash FROM fills WHERE hash = ANY($1::varchar[])",
    hashes
)

# 过滤重复记录后再插入
```

## 修复步骤

### 自动修复（已完成）

已通过以下命令完成修复：

```bash
# 1. 修改代码文件
# - address_analyzer/data_store.py: 更新表定义和插入逻辑

# 2. 修复数据库
uv run python -c "
import asyncio
import asyncpg
import os

async def fix():
    conn = await asyncpg.connect(...)

    # 创建序列
    await conn.execute('CREATE SEQUENCE IF NOT EXISTS fills_id_seq')
    max_id = await conn.fetchval('SELECT MAX(id) FROM fills_old')
    await conn.execute(f'ALTER SEQUENCE fills_id_seq RESTART WITH {max_id + 1}')

    # 创建新表
    await conn.execute('DROP TABLE IF EXISTS fills CASCADE')
    await conn.execute('''
        CREATE TABLE fills (
            id BIGINT NOT NULL DEFAULT nextval('fills_id_seq'),
            address VARCHAR(42) NOT NULL,
            time TIMESTAMPTZ NOT NULL,
            ...
            PRIMARY KEY (time, id)
        )
    ''')

    # 转换为 hypertable
    await conn.execute(\"SELECT create_hypertable('fills', 'time', chunk_time_interval => INTERVAL '7 days')\")

    # 迁移数据
    await conn.execute('''
        INSERT INTO fills (id, address, time, ...)
        SELECT id, address, time, ...
        FROM fills_old
    ''')

    await conn.close()

asyncio.run(fix())
"
```

### 清理备份表（可选）

数据验证无误后，可删除备份表：

```sql
DROP TABLE fills_old;
```

## 验证

运行以下命令验证修复：

```bash
# 测试数据库连接和插入
uv run python -c "
from address_analyzer.data_store import get_store
import asyncio

async def test():
    store = get_store()
    await store.connect()

    # 测试插入
    await store.save_fills('test_addr', [{
        'time': 1704067200000,
        'coin': 'BTC',
        'side': 'A',
        'px': 50000.0,
        'sz': 0.1,
        'closedPnl': 100.0,
        'fee': 0.5,
        'hash': 'test_hash'
    }])

    print('✅ 测试通过')
    await store.close()

asyncio.run(test())
"

# 运行完整分析
uv run python analyze_addresses.py --concurrent 1 --rate-limit 0.1
```

## 技术细节

### TimescaleDB Hypertable 约束

1. **主键要求**：必须包含分区键（通常是时间列）
2. **唯一约束**：只能在分区键上创建
3. **ON CONFLICT**：仅适用于主键或唯一约束

### 性能优化

- 使用 `hash` 列建立索引：`CREATE INDEX idx_fills_hash ON fills(hash)`
- 保持 `(address, time)` 索引：`CREATE INDEX idx_fills_address_time ON fills(address, time DESC)`
- 应用层去重避免数据库层重复检查开销

## 相关文件

- `/Users/test/Downloads/strong-hyperliquid-websocket/address_analyzer/data_store.py` - 数据存储层
- `/Users/test/Downloads/strong-hyperliquid-websocket/fix_fills_table_v2.py` - 修复脚本
- `/Users/test/Downloads/strong-hyperliquid-websocket/migrate_to_hypertable.py` - 原始迁移脚本

## 日期

2026-02-02

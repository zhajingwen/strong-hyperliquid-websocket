# Hyperliquid 分析系统数据库表结构设计文档

## 📋 文档概述

本文档详细描述了 Hyperliquid 交易地址分析系统的**完整数据库表结构设计**,包括所有表的字段定义、索引、约束、关系和使用场景。

**数据库**: PostgreSQL 14+ with TimescaleDB Extension
**字符集**: UTF-8
**时区**: UTC
**最后更新**: 2026-02-05
**表总数**: 11 张

---

## 📝 变更历史

### 2026-02-05 - fills 表添加 liquidation 字段
- 🆕 **新增** `fills.liquidation` 字段（JSONB 类型）
- ✅ **修复** 爆仓检测功能：从数据库读取时也能正确检测强平记录
- 📄 **原因**: 原 `save_fills()` 未存储 `liquidation` 字段，导致从缓存读取时爆仓检测失败
- 🔧 **效果**: 爆仓检测结果稳定一致（无论数据来源是 API 还是数据库）
- 📊 **迁移**: 执行 `migrations/002_add_liquidation_field.sql` 或运行 `fix_liquidation.py`

### 2026-02-04 - 数据新鲜度跟踪表
- 🆕 **新增** `data_freshness` 表（数据新鲜度跟踪）
- ✅ **修复** `is_data_fresh()` 逻辑：基于 `last_fetched` 时间判断，而非数据记录时间
- 📄 **原因**: 不活跃用户（无新交易）每次都被判断为"不新鲜"，触发无效 API 调用
- 🔧 **效果**: 减少 50-80% 无效 API 调用

### 2026-02-04 - ROI字段优化
- ✅ **删除** `metrics_cache` 表的 `roi` 列（ROI推算指标）
- ✅ **删除** 相关索引 `idx_metrics_roi`
- ✅ **保留** 更精确的ROI指标：
  - `true_capital_roi` - 基于真实本金的ROI（仅充值/提现）
  - `time_weighted_roi` - 时间加权ROI
  - `annualized_roi` - 年化ROI
  - `total_roi` - 总ROI（含未实现盈亏）
- 📄 **原因**: 简化指标系统，避免误导性的推算ROI，使用更准确的真实本金ROI
- 🔧 **迁移**: 使用 `migrations/drop_roi_column.sql` 或 `migrations/run_migration_auto.py`

---

## 📊 表结构总览

### 核心业务表 (11张)

| 表名 | 用途 | 记录数量级 | TimescaleDB | 更新频率 |
|------|------|-----------|-------------|---------|
| `addresses` | 地址主表 | 10K - 100K | ❌ | 每日 |
| `fills` | 交易成交记录 | 1M - 10M | ✅ | 实时 |
| `transfers` | 出入金记录 | 100K - 1M | ✅ | 实时 |
| `user_states` | Perp账户状态快照 | 100K - 1M | ✅ | 实时 |
| `spot_states` | Spot账户状态快照 | 100K - 1M | ✅ | 实时 |
| `funding_history` | 资金费率历史 | 500K - 5M | ✅ | 每3小时 |
| `account_snapshots` | 账户快照 | 100K - 1M | ❌ | 每小时 |
| `metrics_cache` | 指标缓存 | 10K - 100K | ❌ | 每小时 |
| `api_cache` | API响应缓存 | 10K - 100K | ❌ | 按TTL |
| `processing_status` | 处理状态表 | 10K - 100K | ❌ | 实时 |
| `data_freshness` | 数据新鲜度跟踪 🆕 | 10K - 500K | ❌ | 实时 |

---

## 🗂️ 详细表结构

### 1. addresses - 地址主表

**用途**: 存储所有交易地址的基本信息和元数据

**表结构**:

```sql
CREATE TABLE addresses (
    address VARCHAR(42) PRIMARY KEY,           -- 用户地址
    taker_count INTEGER DEFAULT 0,             -- Taker成交次数
    maker_count INTEGER DEFAULT 0,             -- Maker成交次数
    first_seen TIMESTAMPTZ DEFAULT NOW(),      -- 首次发现时间
    last_updated TIMESTAMPTZ DEFAULT NOW(),    -- 最后更新时间
    data_complete BOOLEAN DEFAULT FALSE,       -- 数据是否完整
    CONSTRAINT chk_address_format CHECK (address ~ '^0x[a-fA-F0-9]{40}$')
);

COMMENT ON TABLE addresses IS '交易地址主表';
COMMENT ON COLUMN addresses.address IS '以太坊地址格式(0x开头,42字符)';
COMMENT ON COLUMN addresses.taker_count IS 'Taker成交次数(主动吃单)';
COMMENT ON COLUMN addresses.maker_count IS 'Maker成交次数(挂单成交)';
COMMENT ON COLUMN addresses.data_complete IS '是否已完整获取API数据';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `address` | VARCHAR(42) | PRIMARY KEY | 用户地址(0x+40位十六进制) | `0x162cc7c861ebd0c06b3d72319201150482518185` |
| `taker_count` | INTEGER | DEFAULT 0 | Taker成交次数 | `1523` |
| `maker_count` | INTEGER | DEFAULT 0 | Maker成交次数 | `347` |
| `first_seen` | TIMESTAMPTZ | DEFAULT NOW() | 首次发现时间(UTC) | `2024-01-15 08:23:45+00` |
| `last_updated` | TIMESTAMPTZ | DEFAULT NOW() | 最后更新时间(UTC) | `2026-02-03 14:30:22+00` |
| `data_complete` | BOOLEAN | DEFAULT FALSE | 数据完整性标记 | `true` |

**索引**:

```sql
-- 主键索引(自动创建)
-- PRIMARY KEY (address)

-- 按更新时间查询
CREATE INDEX idx_addresses_updated ON addresses(last_updated DESC);

-- 按数据完整性过滤
CREATE INDEX idx_addresses_complete ON addresses(data_complete) WHERE data_complete = FALSE;
```

**查询示例**:

```sql
-- 1. 查找需要更新的地址(24小时未更新)
SELECT address, last_updated
FROM addresses
WHERE last_updated < NOW() - INTERVAL '24 hours'
   OR data_complete = FALSE
ORDER BY last_updated ASC
LIMIT 100;

-- 2. 统计地址分布
SELECT
    CASE
        WHEN taker_count + maker_count < 100 THEN '新手(<100单)'
        WHEN taker_count + maker_count < 1000 THEN '中级(100-1000单)'
        ELSE '高频(>1000单)'
    END AS trader_level,
    COUNT(*) AS address_count,
    AVG(taker_count) AS avg_taker,
    AVG(maker_count) AS avg_maker
FROM addresses
GROUP BY trader_level;
```

**数据来源**: `trades.log` 日志解析

**更新频率**: 每次运行 `analyze_addresses.py` 时更新

---

### 2. fills - 交易成交记录表 (TimescaleDB Hypertable)

**用途**: 存储所有交易的成交明细记录(开仓/平仓/加减仓)

**表结构**:

```sql
CREATE TABLE fills (
    address VARCHAR(42) NOT NULL,              -- 用户地址
    time TIMESTAMPTZ NOT NULL,                 -- 成交时间(分区键)
    coin VARCHAR(20),                          -- 交易币种
    side VARCHAR(1),                           -- 方向(L=Long多/S=Short空)
    price DECIMAL(20, 8),                      -- 成交价格
    size DECIMAL(20, 4),                       -- 成交数量
    closed_pnl DECIMAL(20, 8),                 -- 已实现盈亏
    fee DECIMAL(20, 8),                        -- 手续费
    hash VARCHAR(66),                          -- 交易哈希
    liquidation JSONB,                         -- 强平信息(爆仓时有值) 🆕
    PRIMARY KEY (time, address, hash),
    CONSTRAINT chk_fills_side CHECK (side IN ('L', 'S')),
    CONSTRAINT chk_fills_price CHECK (price > 0),
    CONSTRAINT chk_fills_size CHECK (size > 0)
);

-- 转换为 TimescaleDB hypertable
SELECT create_hypertable('fills', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- 爆仓记录索引(可选,用于快速查询强平记录)
CREATE INDEX IF NOT EXISTS idx_fills_liquidation
ON fills ((liquidation IS NOT NULL))
WHERE liquidation IS NOT NULL;

COMMENT ON TABLE fills IS '交易成交记录表(按7天分区)';
COMMENT ON COLUMN fills.side IS 'L=做多Long, S=做空Short';
COMMENT ON COLUMN fills.closed_pnl IS '平仓盈亏(仅平仓时有值)';
COMMENT ON COLUMN fills.liquidation IS '强平信息JSON(爆仓时有值,包含liquidatedUser/markPx/method)';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `address` | VARCHAR(42) | NOT NULL | 用户地址 | `0x162cc7c861...` |
| `time` | TIMESTAMPTZ | NOT NULL, PK | 成交时间(UTC,分区键) | `2026-01-15 14:23:45+00` |
| `coin` | VARCHAR(20) | - | 交易币种代码 | `BTC`, `ETH`, `SOL` |
| `side` | VARCHAR(1) | CHECK | 交易方向(L/S) | `L` (做多) |
| `price` | DECIMAL(20,8) | >0 | 成交价格(USDC) | `67823.45678900` |
| `size` | DECIMAL(20,4) | >0 | 成交数量 | `0.5432` |
| `closed_pnl` | DECIMAL(20,8) | - | 已实现盈亏(USDC) | `123.45678900` |
| `fee` | DECIMAL(20,8) | - | 手续费(USDC) | `3.39117284` |
| `hash` | VARCHAR(66) | PK | 交易哈希(0x+64位) | `0xabcd1234...` |
| `liquidation` 🆕 | JSONB | - | 强平信息(爆仓时有值) | `{"liquidatedUser": "0x...", "markPx": "214.04", "method": "market"}` |

**liquidation 字段详解** 🆕:

当交易为强制平仓（爆仓）时，`liquidation` 字段包含以下信息：

| 子字段 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `liquidatedUser` | string | 被清算用户地址 | `0x324f74880ccee9a05282614d3f80c09831a36774` |
| `markPx` | string | 触发清算时的标记价格 | `214.04` |
| `method` | string | 清算方式 | `market` (市价清算) |

**爆仓检测逻辑**:

```python
# 检测爆仓记录
liquidations = [f for f in fills if f.get('liquidation')]
if liquidations:
    total_loss = sum(float(f.get('closed_pnl', 0)) for f in liquidations)
    print(f"发现 {len(liquidations)} 笔爆仓，总损失: ${total_loss:,.2f}")
```

**索引**:

```sql
-- 复合主键索引(自动创建)
-- PRIMARY KEY (time, address, hash)

-- 按地址和时间查询(最常用)
CREATE INDEX idx_fills_address_time ON fills(address, time DESC);

-- 按币种统计
CREATE INDEX idx_fills_coin ON fills(coin);

-- 按地址和币种查询
CREATE INDEX idx_fills_address_coin ON fills(address, coin);
```

**TimescaleDB 分区策略**:

```sql
-- 按7天分区(chunk_time_interval)
-- 例如: 2026-01-01 到 2026-01-07 为一个chunk
-- 优化: 历史数据压缩
SELECT add_compression_policy('fills', INTERVAL '30 days');

-- 自动删除旧数据(可选)
SELECT add_retention_policy('fills', INTERVAL '1 year');
```

**查询示例**:

```sql
-- 1. 查询某地址最近30天的交易记录
SELECT
    time,
    coin,
    side,
    price,
    size,
    closed_pnl,
    fee
FROM fills
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND time >= NOW() - INTERVAL '30 days'
ORDER BY time DESC;

-- 2. 统计每个币种的交易量
SELECT
    coin,
    COUNT(*) AS trade_count,
    SUM(size * price) AS total_volume_usdc,
    SUM(closed_pnl) AS total_pnl,
    AVG(fee) AS avg_fee
FROM fills
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND time >= NOW() - INTERVAL '90 days'
GROUP BY coin
ORDER BY total_volume_usdc DESC;

-- 3. 计算胜率(使用 TimescaleDB 时间桶聚合)
SELECT
    time_bucket('1 day', time) AS day,
    COUNT(*) AS total_trades,
    COUNT(*) FILTER (WHERE closed_pnl > 0) AS winning_trades,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE closed_pnl > 0) / COUNT(*),
        2
    ) AS win_rate_pct
FROM fills
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND closed_pnl IS NOT NULL
  AND time >= NOW() - INTERVAL '30 days'
GROUP BY day
ORDER BY day DESC;

-- 4. 查询爆仓记录 🆕
SELECT
    time,
    coin,
    side,
    price,
    size,
    closed_pnl,
    liquidation->>'liquidatedUser' AS liquidated_user,
    liquidation->>'markPx' AS mark_price,
    liquidation->>'method' AS liquidation_method
FROM fills
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND liquidation IS NOT NULL
ORDER BY time DESC;

-- 5. 统计爆仓汇总 🆕
SELECT
    address,
    COUNT(*) AS liquidation_count,
    SUM(closed_pnl) AS total_liquidation_loss,
    COUNT(DISTINCT coin) AS affected_coins
FROM fills
WHERE liquidation IS NOT NULL
GROUP BY address
ORDER BY total_liquidation_loss ASC;

-- 6. 按币种统计爆仓 🆕
SELECT
    coin,
    COUNT(*) AS liquidation_count,
    SUM(closed_pnl) AS total_loss,
    AVG(closed_pnl) AS avg_loss_per_liquidation
FROM fills
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND liquidation IS NOT NULL
GROUP BY coin
ORDER BY total_loss ASC;
```

**数据来源**: Hyperliquid API `user_fills()`

**更新频率**: 实时追加(每次运行时获取增量数据)

**性能优化**:
- ✅ TimescaleDB 分区: 按7天分区,查询性能提升 10-100x
- ✅ 压缩策略: 30天后自动压缩,节省存储空间 50-90%
- ✅ 索引优化: 按 (address, time) 复合索引

---

### 3. transfers - 出入金记录表 (TimescaleDB Hypertable)

**用途**: 存储充值、提现、转账等资金流动记录

**表结构**:

```sql
CREATE TABLE transfers (
    id BIGSERIAL,                              -- 自增ID
    address VARCHAR(42) NOT NULL,              -- 用户地址
    time TIMESTAMPTZ NOT NULL,                 -- 时间(分区键)
    type VARCHAR(25),                          -- 类型(扩展至25以支持subAccountTransfer)
    amount DECIMAL(20, 8),                     -- 金额(带正负)
    tx_hash VARCHAR(66),                       -- 交易哈希
    PRIMARY KEY (id, time),
    CONSTRAINT chk_transfers_type CHECK (
        type IN ('deposit', 'withdraw', 'send', 'subAccountTransfer')
    )
);

-- 转换为 TimescaleDB hypertable
SELECT create_hypertable('transfers', 'time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

COMMENT ON TABLE transfers IS '出入金记录表(按30天分区)';
COMMENT ON COLUMN transfers.type IS 'deposit(7字符)=充值, withdraw(8字符)=提现, send(4字符)=转账, subAccountTransfer(19字符)=子账户转账';
COMMENT ON COLUMN transfers.amount IS '金额(正数=流入, 负数=流出)';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `id` | BIGSERIAL | PK | 自增主键 | `123456` |
| `address` | VARCHAR(42) | NOT NULL | 用户地址 | `0x162cc7c861...` |
| `time` | TIMESTAMPTZ | NOT NULL, PK | 时间(UTC,分区键) | `2026-01-15 08:00:00+00` |
| `type` | VARCHAR(25) | CHECK | 记录类型(最长19字符) | `deposit`, `subAccountTransfer` |
| `amount` | DECIMAL(20,8) | - | 金额(USDC,带正负号) | `5000.00000000` |
| `tx_hash` | VARCHAR(66) | - | 区块链交易哈希 | `0x1234abcd...` |

**类型说明**:

| Type | 字符数 | 中文名 | 方向 | 金额符号 | 说明 |
|------|--------|--------|------|---------|------|
| `deposit` | 7 | 充值 | 流入 | 正数 | 从外部钱包充值到交易账户 |
| `withdraw` | 8 | 提现 | 流出 | 负数 | 从交易账户提现到外部钱包 |
| `send` | 4 | 转账 | 双向 | 根据流向 | P2P转账(收款=正,付款=负) |
| `subAccountTransfer` | 19 | 子账户转账 | 双向 | 根据流向 | 主账户与子账户间转账 |

⚠️ **字段长度说明**: `type` 字段长度从 `VARCHAR(10)` 扩展至 `VARCHAR(25)` 以支持最长的类型 `subAccountTransfer`(19字符)。详见迁移脚本 `migrations/fix_transfer_type_length.sql`。

**索引**:

```sql
-- 复合主键索引(自动创建)
-- PRIMARY KEY (id, time)

-- 按地址和时间查询
CREATE INDEX idx_transfers_address_time ON transfers(address, time DESC);

-- 按类型统计
CREATE INDEX idx_transfers_type ON transfers(type);

-- 按交易哈希查询(去重)
CREATE INDEX idx_transfers_tx_hash ON transfers(tx_hash);
```

**查询示例**:

```sql
-- 1. 计算净充值(传统方法: 包含转账)
SELECT
    address,
    SUM(amount) AS net_deposits_traditional
FROM transfers
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
GROUP BY address;

-- 2. 计算真实本金(仅充值/提现,不含转账)
SELECT
    address,
    COALESCE(SUM(CASE WHEN type = 'deposit' THEN amount ELSE 0 END), 0) AS total_deposits,
    COALESCE(SUM(CASE WHEN type = 'withdraw' THEN ABS(amount) ELSE 0 END), 0) AS total_withdrawals,
    COALESCE(
        SUM(CASE WHEN type = 'deposit' THEN amount ELSE 0 END) -
        SUM(CASE WHEN type = 'withdraw' THEN ABS(amount) ELSE 0 END),
        0
    ) AS true_capital
FROM transfers
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
GROUP BY address;

-- 3. 区分充值/提现 vs 转账
SELECT
    address,
    -- 充值/提现
    COALESCE(SUM(CASE WHEN type = 'deposit' THEN amount ELSE 0 END), 0) AS deposits,
    COALESCE(SUM(CASE WHEN type = 'withdraw' THEN ABS(amount) ELSE 0 END), 0) AS withdrawals,
    -- 转账
    COALESCE(SUM(CASE WHEN type IN ('send', 'subAccountTransfer') AND amount > 0 THEN amount ELSE 0 END), 0) AS transfers_in,
    COALESCE(SUM(CASE WHEN type IN ('send', 'subAccountTransfer') AND amount < 0 THEN ABS(amount) ELSE 0 END), 0) AS transfers_out
FROM transfers
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
GROUP BY address;

-- 4. 按月统计资金流动
SELECT
    time_bucket('1 month', time) AS month,
    SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS inflow,
    SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS outflow,
    SUM(amount) AS net_flow
FROM transfers
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
GROUP BY month
ORDER BY month DESC;
```

**数据来源**: Hyperliquid API `user_non_funding_ledger_updates()`

**更新频率**: 实时追加

**重要说明**:

⚠️ **净充值计算的两种方法**:

1. **传统方法** (包含转账):
   ```sql
   net_deposits = SUM(amount)  -- 包含所有流入流出
   ```
   - ✅ 简单直接
   - ❌ 包含了转账,可能导致 ROI 计算偏差

2. **真实本金法** (仅充值/提现):
   ```sql
   true_capital = deposits - withdrawals  -- 仅充值和提现
   ```
   - ✅ 更准确反映真实投入
   - ✅ 推荐用于 ROI 计算
   - ❌ 需要区分记录类型

**数据来源逻辑** (`address_analyzer/data_store.py:433-550`):

```python
# 充值: 正数
if record_type == 'deposit':
    signed_amount = amount

# 提现: 负数
elif record_type == 'withdraw':
    signed_amount = -amount

# 转账: 根据流向判断
elif record_type == 'send':
    if destination == address:
        signed_amount = amount  # 收款
    elif user == address:
        signed_amount = -amount  # 付款

# 子账户转账: 根据流向判断
elif record_type == 'subAccountTransfer':
    if destination == address:
        signed_amount = amount  # 转入
    elif user == address:
        signed_amount = -amount  # 转出
```

---

### 4. funding_payments - 资金费率记录表 (TimescaleDB Hypertable) 🆕

**用途**: 存储永续合约的资金费率结算历史记录

**表结构**:

```sql
CREATE TABLE funding_payments (
    id BIGSERIAL,                              -- 自增主键
    address VARCHAR(42) NOT NULL,              -- 用户地址
    time TIMESTAMPTZ NOT NULL,                 -- 结算时间(分区键)
    coin VARCHAR(20) NOT NULL,                 -- 币种代码
    funding_usdc DECIMAL(20, 8),               -- 资金费用(USDC)
    position_size DECIMAL(20, 4),              -- 持仓量(带正负号)
    funding_rate DECIMAL(12, 8),               -- 资金费率
    n_samples INTEGER,                         -- 样本数
    tx_hash VARCHAR(66),                       -- 交易哈希
    PRIMARY KEY (id, time),
    CONSTRAINT chk_funding_rate CHECK (ABS(funding_rate) < 1)
);

-- 转换为 TimescaleDB hypertable
SELECT create_hypertable('funding_payments', 'time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

COMMENT ON TABLE funding_payments IS '资金费率结算记录(每3小时结算一次)';
COMMENT ON COLUMN funding_payments.funding_usdc IS '正数=收入, 负数=支出';
COMMENT ON COLUMN funding_payments.position_size IS '正数=多头, 负数=空头';
COMMENT ON COLUMN funding_payments.funding_rate IS '正费率=多付空, 负费率=空付多';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `id` | BIGSERIAL | PK | 自增主键 | `789012` |
| `address` | VARCHAR(42) | NOT NULL | 用户地址 | `0x162cc7c861...` |
| `time` | TIMESTAMPTZ | NOT NULL, PK | 结算时间(UTC,分区键) | `2026-01-15 00:00:00+00` |
| `coin` | VARCHAR(20) | NOT NULL | 币种代码 | `BTC`, `ETH` |
| `funding_usdc` | DECIMAL(20,8) | - | 资金费用(正=收入,负=支出) | `-14.39115200` |
| `position_size` | DECIMAL(20,4) | - | 持仓量(正=多头,负=空头) | `0.5435` |
| `funding_rate` | DECIMAL(12,8) | ABS<1 | 资金费率(小数) | `0.00001065` |
| `n_samples` | INTEGER | - | 统计样本数(通常24) | `24` |
| `tx_hash` | VARCHAR(66) | - | 交易哈希 | `0x00000000...` |

**资金费率机制说明**:

```
资金费用 = 持仓量 × 标记价格 × 资金费率
funding_usdc = position_size × mark_price × funding_rate
```

**费用方向判断**:

| 持仓方向 | 费率符号 | 费用方向 | 说明 |
|---------|---------|---------|------|
| 多头 (+) | 正费率 (+) | 支出 (-) | 多头支付给空头 |
| 多头 (+) | 负费率 (-) | 收入 (+) | 空头支付给多头 |
| 空头 (-) | 正费率 (+) | 收入 (+) | 多头支付给空头 |
| 空头 (-) | 负费率 (-) | 支出 (-) | 空头支付给多头 |

**索引**:

```sql
-- 复合主键索引(自动创建)
-- PRIMARY KEY (id, time)

-- 按地址和时间查询
CREATE INDEX idx_funding_address_time ON funding_payments(address, time DESC);

-- 按币种统计
CREATE INDEX idx_funding_coin_time ON funding_payments(coin, time DESC);

-- 按地址和币种查询
CREATE INDEX idx_funding_address_coin ON funding_payments(address, coin, time DESC);
```

**查询示例**:

```sql
-- 1. 计算最近30天的累计资金费用
SELECT
    address,
    SUM(funding_usdc) AS total_funding,
    COUNT(*) AS payment_count,
    COUNT(*) FILTER (WHERE funding_usdc > 0) AS income_count,
    COUNT(*) FILTER (WHERE funding_usdc < 0) AS expense_count
FROM funding_payments
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND time >= NOW() - INTERVAL '30 days'
GROUP BY address;

-- 2. 按币种分解资金费用
SELECT
    coin,
    SUM(funding_usdc) AS total_funding,
    AVG(funding_rate) AS avg_rate,
    AVG(funding_rate) * 8 * 365 * 100 AS annual_rate_pct,
    COUNT(*) AS payment_count,
    COUNT(*) / 8.0 AS holding_days
FROM funding_payments
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND time >= NOW() - INTERVAL '90 days'
GROUP BY coin
ORDER BY total_funding DESC;

-- 3. 分析持仓偏好(多头 vs 空头)
SELECT
    COUNT(*) AS total_payments,
    COUNT(*) FILTER (WHERE position_size > 0) AS long_count,
    COUNT(*) FILTER (WHERE position_size < 0) AS short_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE position_size > 0) / COUNT(*), 2) AS long_pct,
    AVG(CASE WHEN position_size > 0 THEN position_size ELSE 0 END) AS avg_long_size,
    AVG(CASE WHEN position_size < 0 THEN ABS(position_size) ELSE 0 END) AS avg_short_size
FROM funding_payments
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND time >= NOW() - INTERVAL '90 days';

-- 4. 资金费率时间序列(每日汇总)
SELECT
    time_bucket('1 day', time) AS day,
    SUM(funding_usdc) AS daily_funding,
    AVG(funding_rate) AS avg_rate,
    COUNT(DISTINCT coin) AS coin_count
FROM funding_payments
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND time >= NOW() - INTERVAL '30 days'
GROUP BY day
ORDER BY day DESC;
```

**数据来源**: Hyperliquid API `user_funding_history()`

**更新频率**: 每3小时追加新记录(Hyperliquid 结算频率: 00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 UTC)

**性能优化**:
- ✅ TimescaleDB 分区: 按30天分区
- ✅ 复合索引: (address, coin, time) 三维查询优化

---

### 5. account_snapshots - 账户快照表 (TimescaleDB Hypertable)

**用途**: 存储账户价值的时间序列快照(用于计算夏普比率、最大回撤等)

**表结构**:

```sql
CREATE TABLE account_snapshots (
    address VARCHAR(42) NOT NULL,              -- 用户地址
    snapshot_time TIMESTAMPTZ NOT NULL,        -- 快照时间
    account_value DECIMAL(20, 8),              -- 账户总价值
    margin_used DECIMAL(20, 8),                -- 已用保证金
    unrealized_pnl DECIMAL(20, 8),             -- 未实现盈亏
    PRIMARY KEY (address, snapshot_time),
    CONSTRAINT chk_snapshot_value CHECK (account_value >= 0),
    CONSTRAINT chk_snapshot_margin CHECK (margin_used >= 0)
);

-- 转换为 TimescaleDB hypertable
SELECT create_hypertable('account_snapshots', 'snapshot_time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

COMMENT ON TABLE account_snapshots IS '账户价值时间序列快照';
COMMENT ON COLUMN account_snapshots.account_value IS '账户总价值 = 余额 + 未实现盈亏';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `address` | VARCHAR(42) | NOT NULL, PK | 用户地址 | `0x162cc7c861...` |
| `snapshot_time` | TIMESTAMPTZ | NOT NULL, PK | 快照时间(UTC) | `2026-01-15 12:00:00+00` |
| `account_value` | DECIMAL(20,8) | >=0 | 账户总价值(USDC) | `50234.56789012` |
| `margin_used` | DECIMAL(20,8) | >=0 | 已用保证金(USDC) | `15234.56789012` |
| `unrealized_pnl` | DECIMAL(20,8) | - | 未实现盈亏(USDC) | `1234.56789012` |

**索引**:

```sql
-- 复合主键索引(自动创建)
-- PRIMARY KEY (address, snapshot_time)

-- 按地址查询时间序列
CREATE INDEX idx_snapshots_address_time ON account_snapshots(address, snapshot_time DESC);
```

**查询示例**:

```sql
-- 1. 查询最近30天的账户价值曲线
SELECT
    snapshot_time,
    account_value,
    margin_used,
    unrealized_pnl
FROM account_snapshots
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND snapshot_time >= NOW() - INTERVAL '30 days'
ORDER BY snapshot_time ASC;

-- 2. 计算最大回撤(Maximum Drawdown)
WITH value_series AS (
    SELECT
        snapshot_time,
        account_value,
        MAX(account_value) OVER (ORDER BY snapshot_time) AS peak_value
    FROM account_snapshots
    WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
      AND snapshot_time >= NOW() - INTERVAL '90 days'
)
SELECT
    MAX((peak_value - account_value) / peak_value * 100) AS max_drawdown_pct
FROM value_series
WHERE peak_value > 0;

-- 3. 按天汇总账户价值
SELECT
    time_bucket('1 day', snapshot_time) AS day,
    AVG(account_value) AS avg_value,
    MAX(account_value) AS peak_value,
    MIN(account_value) AS low_value
FROM account_snapshots
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND snapshot_time >= NOW() - INTERVAL '30 days'
GROUP BY day
ORDER BY day DESC;
```

**数据来源**: Hyperliquid API `user_state()` + 定时采集

**更新频率**: 每小时采集一次快照

**用途场景**:
- 📈 计算夏普比率(收益标准差)
- 📉 计算最大回撤
- 📊 绘制账户价值曲线
- 🔍 风险管理分析

---

### 6. metrics_cache - 指标缓存表

**用途**: 缓存各地址计算后的综合指标,避免重复计算

> **💡 ROI指标说明** (2026-02-04更新)
> - ❌ **已删除**: `roi` 列（基于推算初始资金的ROI，可能不准确）
> - ✅ **推荐使用**: 应用层计算的更精确ROI指标：
>   - `AddressMetrics.true_capital_roi` - 基于真实本金的ROI
>   - `AddressMetrics.time_weighted_roi` - 时间加权ROI
>   - `AddressMetrics.annualized_roi` - 年化ROI
>   - `AddressMetrics.total_roi` - 总ROI（含未实现盈亏）
> - 📊 这些指标在 `AddressMetrics` 数据类中计算，不存储在数据库中

**表结构**:

```sql
CREATE TABLE metrics_cache (
    address VARCHAR(42) PRIMARY KEY,           -- 用户地址
    total_trades INTEGER,                      -- 总交易次数
    win_rate DECIMAL(6, 2),                    -- 胜率(0-100)
    sharpe_ratio DECIMAL(10, 4),               -- 夏普比率
    total_pnl DECIMAL(20, 8),                  -- 总盈亏
    account_value DECIMAL(20, 8),              -- 账户价值
    max_drawdown DECIMAL(8, 2),                -- 最大回撤(百分比)
    net_deposit DECIMAL(20, 8),                -- 净充值
    calculated_at TIMESTAMPTZ DEFAULT NOW(),   -- 计算时间
    CONSTRAINT chk_metrics_win_rate CHECK (win_rate BETWEEN 0 AND 100),
    CONSTRAINT chk_metrics_drawdown CHECK (max_drawdown >= 0)
);

COMMENT ON TABLE metrics_cache IS '计算指标缓存表(避免重复计算)';
COMMENT ON COLUMN metrics_cache.win_rate IS '胜率百分比(0-100)';
COMMENT ON COLUMN metrics_cache.sharpe_ratio IS '夏普比率(风险调整收益)';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `address` | VARCHAR(42) | PRIMARY KEY | 用户地址 | `0x162cc7c861...` |
| `total_trades` | INTEGER | - | 总交易次数 | `1523` |
| `win_rate` | DECIMAL(6,2) | 0-100 | 胜率(%) | `58.32` |
| `sharpe_ratio` | DECIMAL(10,4) | - | 夏普比率 | `2.4567` |
| `total_pnl` | DECIMAL(20,8) | - | 总盈亏(USDC) | `50234.56789012` |
| `account_value` | DECIMAL(20,8) | - | 账户价值(USDC) | `75000.00000000` |
| `max_drawdown` | DECIMAL(8,2) | >=0 | 最大回撤(%) | `15.67` |
| `net_deposit` | DECIMAL(20,8) | - | 净充值(USDC) | `25000.00000000` |
| `calculated_at` | TIMESTAMPTZ | DEFAULT NOW() | 计算时间 | `2026-02-03 14:30:00+00` |

**索引**:

```sql
-- 主键索引(自动创建)
-- PRIMARY KEY (address)

-- 按总盈亏排序查询
CREATE INDEX idx_metrics_total_pnl ON metrics_cache(total_pnl DESC);

-- 按夏普比率排序查询
CREATE INDEX idx_metrics_sharpe ON metrics_cache(sharpe_ratio DESC);

-- 按计算时间过滤(找过期数据)
CREATE INDEX idx_metrics_calculated ON metrics_cache(calculated_at);
```

**查询示例**:

```sql
-- 1. 查询Top 50盈利地址
SELECT
    address,
    total_trades,
    win_rate,
    sharpe_ratio,
    total_pnl,
    account_value
FROM metrics_cache
ORDER BY total_pnl DESC
LIMIT 50;

-- 2. 查询高夏普比率地址(风险调整收益好)
SELECT
    address,
    sharpe_ratio,
    total_pnl,
    win_rate
FROM metrics_cache
WHERE sharpe_ratio > 2.0
  AND total_trades >= 100
ORDER BY sharpe_ratio DESC;

-- 3. 查询需要更新的缓存(超过1小时)
SELECT
    address,
    calculated_at,
    EXTRACT(EPOCH FROM (NOW() - calculated_at))/3600 AS hours_ago
FROM metrics_cache
WHERE calculated_at < NOW() - INTERVAL '1 hour'
ORDER BY calculated_at ASC;
```

**数据来源**: `metrics_engine.calculate_metrics()` 计算结果

**更新频率**: 每次运行分析时更新

**缓存失效策略**:
- 超过1小时视为过期
- `--force-refresh` 标志强制刷新

---

### 7. funding_stats - 资金费率统计表 🆕

**用途**: 缓存各地址的资金费率聚合统计数据

**表结构**:

```sql
CREATE TABLE funding_stats (
    address VARCHAR(42) PRIMARY KEY,           -- 用户地址
    total_funding_usdc DECIMAL(20, 8),         -- 累计资金费用
    total_funding_income DECIMAL(20, 8),       -- 累计收入
    total_funding_expense DECIMAL(20, 8),      -- 累计支出
    avg_funding_rate DECIMAL(12, 8),           -- 平均资金费率
    annual_funding_rate DECIMAL(8, 4),         -- 年化资金费率(%)
    funding_payment_count INTEGER,             -- 结算次数
    funding_income_count INTEGER,              -- 收入次数
    funding_expense_count INTEGER,             -- 支出次数
    funding_coin_count INTEGER,                -- 涉及币种数
    first_funding_time TIMESTAMPTZ,            -- 首次结算时间
    last_funding_time TIMESTAMPTZ,             -- 最后结算时间
    calculated_at TIMESTAMPTZ DEFAULT NOW(),   -- 计算时间
    CONSTRAINT chk_funding_counts CHECK (funding_payment_count >= 0)
);

COMMENT ON TABLE funding_stats IS '资金费率聚合统计缓存';
COMMENT ON COLUMN funding_stats.annual_funding_rate IS '年化资金费率 = avg_rate × 8 × 365 × 100';
```

**字段详解**:

| 字段 | 类型 | 说明 | 计算公式 |
|------|------|------|----------|
| `address` | VARCHAR(42) | 用户地址 | - |
| `total_funding_usdc` | DECIMAL(20,8) | 累计净资金费 | `SUM(funding_usdc)` |
| `total_funding_income` | DECIMAL(20,8) | 累计收入 | `SUM(funding_usdc WHERE > 0)` |
| `total_funding_expense` | DECIMAL(20,8) | 累计支出 | `SUM(ABS(funding_usdc) WHERE < 0)` |
| `avg_funding_rate` | DECIMAL(12,8) | 平均费率 | `AVG(funding_rate)` |
| `annual_funding_rate` | DECIMAL(8,4) | 年化费率(%) | `avg_rate × 8 × 365 × 100` |
| `funding_payment_count` | INTEGER | 总结算次数 | `COUNT(*)` |
| `funding_income_count` | INTEGER | 收入次数 | `COUNT(*) WHERE funding_usdc > 0` |
| `funding_expense_count` | INTEGER | 支出次数 | `COUNT(*) WHERE funding_usdc < 0` |
| `funding_coin_count` | INTEGER | 币种数 | `COUNT(DISTINCT coin)` |
| `first_funding_time` | TIMESTAMPTZ | 首次结算 | `MIN(time)` |
| `last_funding_time` | TIMESTAMPTZ | 最后结算 | `MAX(time)` |
| `calculated_at` | TIMESTAMPTZ | 计算时间 | `NOW()` |

**索引**:

```sql
-- 主键索引(自动创建)
-- PRIMARY KEY (address)

-- 按累计资金费用排序
CREATE INDEX idx_funding_stats_total ON funding_stats(total_funding_usdc DESC);

-- 按年化费率排序
CREATE INDEX idx_funding_stats_rate ON funding_stats(annual_funding_rate DESC);
```

**查询示例**:

```sql
-- 1. 查询资金费收益Top 20
SELECT
    address,
    total_funding_usdc,
    annual_funding_rate,
    funding_payment_count,
    funding_payment_count / 8.0 AS holding_days
FROM funding_stats
ORDER BY total_funding_usdc DESC
LIMIT 20;

-- 2. 识别资金费套利策略
SELECT
    address,
    total_funding_usdc,
    funding_income_count,
    funding_expense_count,
    ROUND(100.0 * funding_income_count / funding_payment_count, 2) AS income_rate_pct
FROM funding_stats
WHERE funding_payment_count > 100
  AND funding_income_count::float / funding_payment_count > 0.6  -- 60%时间在收费
ORDER BY total_funding_usdc DESC;
```

**数据来源**: 从 `funding_payments` 表聚合计算

**更新频率**: 每次运行分析时更新

---

### 8. funding_coin_stats - 币种资金费统计表 🆕

**用途**: 按地址和币种分解的资金费率统计

**表结构**:

```sql
CREATE TABLE funding_coin_stats (
    address VARCHAR(42) NOT NULL,              -- 用户地址
    coin VARCHAR(20) NOT NULL,                 -- 币种代码
    total_funding_usdc DECIMAL(20, 8),         -- 累计资金费用
    avg_position_size DECIMAL(20, 4),          -- 平均持仓量
    avg_funding_rate DECIMAL(12, 8),           -- 平均费率
    payment_count INTEGER,                     -- 结算次数
    holding_days DECIMAL(8, 2),                -- 持仓天数
    first_payment_time TIMESTAMPTZ,            -- 首次结算时间
    last_payment_time TIMESTAMPTZ,             -- 最后结算时间
    calculated_at TIMESTAMPTZ DEFAULT NOW(),   -- 计算时间
    PRIMARY KEY (address, coin)
);

COMMENT ON TABLE funding_coin_stats IS '按币种分解的资金费率统计';
COMMENT ON COLUMN funding_coin_stats.holding_days IS '持仓天数 = payment_count / 8';
```

**字段详解**:

| 字段 | 类型 | 说明 | 计算公式 |
|------|------|------|----------|
| `address` | VARCHAR(42) | 用户地址 | - |
| `coin` | VARCHAR(20) | 币种代码 | - |
| `total_funding_usdc` | DECIMAL(20,8) | 该币种累计费用 | `SUM(funding_usdc)` |
| `avg_position_size` | DECIMAL(20,4) | 平均持仓量 | `AVG(ABS(position_size))` |
| `avg_funding_rate` | DECIMAL(12,8) | 平均费率 | `AVG(funding_rate)` |
| `payment_count` | INTEGER | 结算次数 | `COUNT(*)` |
| `holding_days` | DECIMAL(8,2) | 持仓天数 | `payment_count / 8` |
| `first_payment_time` | TIMESTAMPTZ | 首次结算 | `MIN(time)` |
| `last_payment_time` | TIMESTAMPTZ | 最后结算 | `MAX(time)` |
| `calculated_at` | TIMESTAMPTZ | 计算时间 | `NOW()` |

**索引**:

```sql
-- 复合主键索引(自动创建)
-- PRIMARY KEY (address, coin)

-- 按地址查询
CREATE INDEX idx_funding_coin_stats_addr ON funding_coin_stats(address);

-- 按币种查询
CREATE INDEX idx_funding_coin_stats_coin ON funding_coin_stats(coin);

-- 按累计费用排序
CREATE INDEX idx_funding_coin_stats_total ON funding_coin_stats(total_funding_usdc DESC);
```

**查询示例**:

```sql
-- 1. 查询某地址在各币种上的资金费用
SELECT
    coin,
    total_funding_usdc,
    avg_position_size,
    payment_count,
    holding_days
FROM funding_coin_stats
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
ORDER BY total_funding_usdc DESC;

-- 2. 识别高成本币种(资金费支出最多)
SELECT
    coin,
    COUNT(DISTINCT address) AS address_count,
    AVG(total_funding_usdc) AS avg_funding_per_address
FROM funding_coin_stats
WHERE total_funding_usdc < 0  -- 支出
GROUP BY coin
ORDER BY avg_funding_per_address ASC
LIMIT 10;
```

**数据来源**: 从 `funding_payments` 表按币种聚合

**更新频率**: 每次运行分析时更新

---

### 9. api_cache - API响应缓存表

**用途**: 缓存 Hyperliquid API 的响应数据,减少重复请求

**表结构**:

```sql
CREATE TABLE api_cache (
    cache_key VARCHAR(255) PRIMARY KEY,        -- 缓存键
    response_data JSONB,                       -- 响应数据(JSON格式)
    cached_at TIMESTAMPTZ DEFAULT NOW(),       -- 缓存时间
    expires_at TIMESTAMPTZ,                    -- 过期时间
    CONSTRAINT chk_cache_expiry CHECK (expires_at > cached_at)
);

COMMENT ON TABLE api_cache IS 'API响应缓存(减少重复请求)';
COMMENT ON COLUMN api_cache.response_data IS 'JSONB格式,支持JSON查询';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `cache_key` | VARCHAR(255) | PRIMARY KEY | 缓存键 | `user_state:0x162cc7...` |
| `response_data` | JSONB | - | API响应数据(JSON) | `{"accountValue": "50234.56", ...}` |
| `cached_at` | TIMESTAMPTZ | DEFAULT NOW() | 缓存时间 | `2026-02-03 14:00:00+00` |
| `expires_at` | TIMESTAMPTZ | - | 过期时间 | `2026-02-03 15:00:00+00` |

**缓存键格式**:

| 缓存键格式 | API方法 | TTL | 说明 |
|-----------|---------|-----|------|
| `user_state:{address}` | `user_state()` | 1小时 | 用户账户状态 |
| `spot_state:{address}` | `spot_user_state()` | 1小时 | Spot账户状态 |
| `user_fills:{address}` | `user_fills()` | 1小时 | 用户成交记录 |
| `user_ledger:{address}` | `user_non_funding_ledger_updates()` | 1小时 | 账本变动 |
| `user_funding:{address}` | `user_funding_history()` | 1小时 | 资金费率历史 |

**索引**:

```sql
-- 主键索引(自动创建)
-- PRIMARY KEY (cache_key)

-- 按过期时间查询(清理过期缓存)
CREATE INDEX idx_api_cache_expires ON api_cache(expires_at);

-- JSONB字段索引(可选,用于JSON查询)
CREATE INDEX idx_api_cache_data ON api_cache USING GIN (response_data);
```

**查询示例**:

```sql
-- 1. 查询有效缓存
SELECT
    cache_key,
    response_data,
    cached_at,
    expires_at
FROM api_cache
WHERE cache_key = 'user_state:0x162cc7c861ebd0c06b3d72319201150482518185'
  AND expires_at > NOW();

-- 2. 清理过期缓存
DELETE FROM api_cache
WHERE expires_at < NOW();

-- 3. 查询缓存统计
SELECT
    CASE
        WHEN cache_key LIKE 'user_state:%' THEN 'user_state'
        WHEN cache_key LIKE 'spot_state:%' THEN 'spot_state'
        WHEN cache_key LIKE 'user_fills:%' THEN 'user_fills'
        WHEN cache_key LIKE 'user_ledger:%' THEN 'user_ledger'
        WHEN cache_key LIKE 'user_funding:%' THEN 'user_funding'
        ELSE 'other'
    END AS cache_type,
    COUNT(*) AS cache_count,
    COUNT(*) FILTER (WHERE expires_at > NOW()) AS valid_count,
    COUNT(*) FILTER (WHERE expires_at <= NOW()) AS expired_count
FROM api_cache
GROUP BY cache_type;

-- 4. JSON查询示例(查询账户价值)
SELECT
    cache_key,
    response_data->>'accountValue' AS account_value,
    cached_at
FROM api_cache
WHERE cache_key LIKE 'user_state:%'
  AND (response_data->>'accountValue')::numeric > 10000
ORDER BY (response_data->>'accountValue')::numeric DESC;
```

**数据来源**: Hyperliquid API 调用结果

**更新频率**: 按需更新,过期后自动刷新

**清理策略**:

```python
# 定期清理过期缓存(建议每小时运行)
async def cleanup_expired_cache():
    await store.pool.execute(
        "DELETE FROM api_cache WHERE expires_at < NOW()"
    )
```

---

### 10. processing_status - 处理状态表

**用途**: 跟踪地址数据获取和处理的状态,支持错误重试

**表结构**:

```sql
CREATE TABLE processing_status (
    address VARCHAR(42) PRIMARY KEY,           -- 用户地址
    status VARCHAR(20),                        -- 状态
    error_message TEXT,                        -- 错误信息
    retry_count INTEGER DEFAULT 0,             -- 重试次数
    updated_at TIMESTAMPTZ DEFAULT NOW(),      -- 更新时间
    CONSTRAINT chk_status_value CHECK (
        status IN ('pending', 'processing', 'completed', 'failed')
    ),
    CONSTRAINT chk_retry_count CHECK (retry_count >= 0 AND retry_count <= 10)
);

COMMENT ON TABLE processing_status IS '地址数据处理状态跟踪';
COMMENT ON COLUMN processing_status.status IS 'pending=待处理, processing=处理中, completed=完成, failed=失败';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `address` | VARCHAR(42) | PRIMARY KEY | 用户地址 | `0x162cc7c861...` |
| `status` | VARCHAR(20) | CHECK | 处理状态 | `completed` |
| `error_message` | TEXT | - | 错误信息(失败时) | `API timeout after 3 retries` |
| `retry_count` | INTEGER | 0-10 | 重试次数 | `2` |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | 最后更新时间 | `2026-02-03 14:30:00+00` |

**状态流转**:

```
pending → processing → completed
                ↓
              failed (重试 ≤ 3次)
                ↓
              pending (重试 > 3次后放弃)
```

**索引**:

```sql
-- 主键索引(自动创建)
-- PRIMARY KEY (address)

-- 按状态和重试次数查询(找待重试地址)
CREATE INDEX idx_processing_status ON processing_status(status, retry_count);

-- 按更新时间查询
CREATE INDEX idx_processing_updated ON processing_status(updated_at);
```

**查询示例**:

```sql
-- 1. 查询待处理地址(包括失败重试)
SELECT address, retry_count, updated_at
FROM processing_status
WHERE status IN ('pending', 'failed')
  AND retry_count < 3
ORDER BY retry_count ASC, updated_at ASC
LIMIT 100;

-- 2. 查询处理统计
SELECT
    status,
    COUNT(*) AS address_count,
    AVG(retry_count) AS avg_retries
FROM processing_status
GROUP BY status;

-- 3. 查询失败地址详情
SELECT
    address,
    error_message,
    retry_count,
    updated_at
FROM processing_status
WHERE status = 'failed'
  AND retry_count >= 3
ORDER BY updated_at DESC;

-- 4. 重置失败地址状态(手动重试)
UPDATE processing_status
SET status = 'pending',
    retry_count = 0,
    error_message = NULL,
    updated_at = NOW()
WHERE status = 'failed'
  AND retry_count >= 3
  AND address = '0x162cc7c861ebd0c06b3d72319201150482518185';
```

**数据来源**: 程序运行时自动维护

**更新频率**: 每次处理地址时更新

**错误处理策略**:

```python
# 地址处理流程
async def process_address(addr: str):
    try:
        # 1. 标记为处理中
        await store.update_processing_status(addr, 'processing')

        # 2. 获取数据
        data = await api_client.fetch_address_data(addr)

        # 3. 标记为完成
        await store.update_processing_status(addr, 'completed')

    except Exception as e:
        # 4. 标记为失败(自动增加重试次数)
        await store.update_processing_status(addr, 'failed', str(e))

        # 5. 如果重试次数 < 3,稍后自动重试
        # 如果重试次数 >= 3,放弃处理
```

---

### 11. user_states - 用户Perp账户状态表 (TimescaleDB Hypertable)

**用途**: 存储永续合约账户的状态快照（账户价值、保证金、持仓等）

**表结构**:

```sql
CREATE TABLE user_states (
    id BIGSERIAL,                              -- 自增主键
    address VARCHAR(42) NOT NULL,              -- 用户地址
    snapshot_time TIMESTAMPTZ NOT NULL,        -- 快照时间(分区键)
    account_value DECIMAL(20, 8),              -- 账户总价值
    total_margin_used DECIMAL(20, 8),          -- 已用保证金
    total_ntl_pos DECIMAL(20, 8),              -- 名义持仓价值
    total_raw_usd DECIMAL(20, 8),              -- 原始USD价值
    withdrawable DECIMAL(20, 8),               -- 可提取金额
    cross_margin_summary JSONB,                -- 全仓保证金摘要
    asset_positions JSONB,                     -- 持仓明细
    PRIMARY KEY (id, snapshot_time)
);

-- 转换为 TimescaleDB hypertable
SELECT create_hypertable('user_states', 'snapshot_time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

COMMENT ON TABLE user_states IS 'Perp账户状态快照表(按7天分区)';
COMMENT ON COLUMN user_states.cross_margin_summary IS 'JSON格式的全仓保证金摘要';
COMMENT ON COLUMN user_states.asset_positions IS 'JSON格式的持仓明细数组';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `id` | BIGSERIAL | PK | 自增主键 | `123456` |
| `address` | VARCHAR(42) | NOT NULL | 用户地址 | `0x162cc7c861...` |
| `snapshot_time` | TIMESTAMPTZ | NOT NULL, PK | 快照时间(UTC,分区键) | `2026-02-04 12:00:00+00` |
| `account_value` | DECIMAL(20,8) | - | 账户总价值(USDC) | `50234.56789012` |
| `total_margin_used` | DECIMAL(20,8) | - | 已用保证金(USDC) | `15234.56789012` |
| `total_ntl_pos` | DECIMAL(20,8) | - | 名义持仓价值(USDC) | `100000.00000000` |
| `total_raw_usd` | DECIMAL(20,8) | - | 原始USD价值 | `35000.00000000` |
| `withdrawable` | DECIMAL(20,8) | - | 可提取金额(USDC) | `20000.00000000` |
| `cross_margin_summary` | JSONB | - | 全仓保证金摘要 | `{"totalRawUsd": "35000.00", ...}` |
| `asset_positions` | JSONB | - | 持仓明细数组 | `[{"coin": "BTC", "szi": "0.5", ...}]` |

**索引**:

```sql
-- 复合主键索引(自动创建)
-- PRIMARY KEY (id, snapshot_time)

-- 按地址和时间查询
CREATE INDEX idx_user_states_address_time ON user_states(address, snapshot_time DESC);
```

**查询示例**:

```sql
-- 1. 查询某地址最新的账户状态
SELECT * FROM user_states
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
ORDER BY snapshot_time DESC
LIMIT 1;

-- 2. 查询账户价值变化趋势
SELECT
    snapshot_time,
    account_value,
    total_margin_used,
    withdrawable
FROM user_states
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND snapshot_time >= NOW() - INTERVAL '7 days'
ORDER BY snapshot_time ASC;
```

**数据来源**: Hyperliquid API `user_state()`

**更新频率**: 每次分析运行时获取

---

### 12. spot_states - Spot账户状态表 (TimescaleDB Hypertable)

**用途**: 存储现货账户的余额快照

**表结构**:

```sql
CREATE TABLE spot_states (
    id BIGSERIAL,                              -- 自增主键
    address VARCHAR(42) NOT NULL,              -- 用户地址
    snapshot_time TIMESTAMPTZ NOT NULL,        -- 快照时间(分区键)
    balances JSONB,                            -- 余额明细
    PRIMARY KEY (id, snapshot_time)
);

-- 转换为 TimescaleDB hypertable
SELECT create_hypertable('spot_states', 'snapshot_time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

COMMENT ON TABLE spot_states IS 'Spot账户状态快照表(按7天分区)';
COMMENT ON COLUMN spot_states.balances IS 'JSON格式的余额数组';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `id` | BIGSERIAL | PK | 自增主键 | `123456` |
| `address` | VARCHAR(42) | NOT NULL | 用户地址 | `0x162cc7c861...` |
| `snapshot_time` | TIMESTAMPTZ | NOT NULL, PK | 快照时间(UTC,分区键) | `2026-02-04 12:00:00+00` |
| `balances` | JSONB | - | 余额明细数组 | `[{"coin": "USDC", "hold": "1000.00", ...}]` |

**索引**:

```sql
-- 复合主键索引(自动创建)
-- PRIMARY KEY (id, snapshot_time)

-- 按地址和时间查询
CREATE INDEX idx_spot_states_address_time ON spot_states(address, snapshot_time DESC);
```

**查询示例**:

```sql
-- 1. 查询某地址最新的Spot账户状态
SELECT * FROM spot_states
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
ORDER BY snapshot_time DESC
LIMIT 1;

-- 2. 解析余额JSON
SELECT
    snapshot_time,
    jsonb_array_elements(balances)->>'coin' AS coin,
    (jsonb_array_elements(balances)->>'hold')::numeric AS hold
FROM spot_states
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
ORDER BY snapshot_time DESC
LIMIT 1;
```

**数据来源**: Hyperliquid API `spotClearinghouseState`

**更新频率**: 每次分析运行时获取

---

### 13. funding_history - 资金费率历史表 (TimescaleDB Hypertable)

**用途**: 存储永续合约的资金费率结算历史记录

**表结构**:

```sql
CREATE TABLE funding_history (
    address VARCHAR(42) NOT NULL,              -- 用户地址
    time TIMESTAMPTZ NOT NULL,                 -- 结算时间(分区键)
    coin VARCHAR(20) NOT NULL,                 -- 币种代码
    usdc DECIMAL(20, 8),                       -- 资金费用(USDC)
    szi DECIMAL(20, 8),                        -- 持仓量
    funding_rate DECIMAL(20, 10),              -- 资金费率
    PRIMARY KEY (time, address, coin)
);

-- 转换为 TimescaleDB hypertable
SELECT create_hypertable('funding_history', 'time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

COMMENT ON TABLE funding_history IS '资金费率结算历史(每3小时结算一次)';
COMMENT ON COLUMN funding_history.usdc IS '正数=收入, 负数=支出';
COMMENT ON COLUMN funding_history.szi IS '正数=多头, 负数=空头';
COMMENT ON COLUMN funding_history.funding_rate IS '正费率=多付空, 负费率=空付多';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `address` | VARCHAR(42) | NOT NULL, PK | 用户地址 | `0x162cc7c861...` |
| `time` | TIMESTAMPTZ | NOT NULL, PK | 结算时间(UTC,分区键) | `2026-02-04 00:00:00+00` |
| `coin` | VARCHAR(20) | NOT NULL, PK | 币种代码 | `BTC`, `ETH` |
| `usdc` | DECIMAL(20,8) | - | 资金费用(正=收入,负=支出) | `-14.39115200` |
| `szi` | DECIMAL(20,8) | - | 持仓量(正=多头,负=空头) | `0.5435` |
| `funding_rate` | DECIMAL(20,10) | - | 资金费率(小数) | `0.0000106500` |

**索引**:

```sql
-- 复合主键索引(自动创建)
-- PRIMARY KEY (time, address, coin)

-- 按地址和时间查询
CREATE INDEX idx_funding_history_address_time ON funding_history(address, time DESC);
```

**查询示例**:

```sql
-- 1. 计算最近30天的累计资金费用
SELECT
    address,
    SUM(usdc) AS total_funding,
    COUNT(*) AS payment_count
FROM funding_history
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND time >= NOW() - INTERVAL '30 days'
GROUP BY address;

-- 2. 按币种分解资金费用
SELECT
    coin,
    SUM(usdc) AS total_funding,
    AVG(funding_rate) AS avg_rate,
    COUNT(*) AS payment_count
FROM funding_history
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND time >= NOW() - INTERVAL '90 days'
GROUP BY coin
ORDER BY total_funding DESC;
```

**数据来源**: Hyperliquid API `user_funding_history()`

**更新频率**: 每3小时追加新记录(Hyperliquid 结算频率: 00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 UTC)

---

### 14. data_freshness - 数据新鲜度跟踪表 🆕

**用途**: 跟踪各数据类型的最后成功获取时间，用于智能缓存判断

**背景问题**:
- 原 `is_data_fresh()` 基于数据记录时间判断新鲜度
- 不活跃用户（超过 24 小时无新交易）每次都被判断为"不新鲜"
- 导致大量无效 API 调用（返回 0 条新记录）

**解决方案**:
- 新增 `data_freshness` 表记录**最后成功获取数据的时间**
- 新鲜度判断基于 `last_fetched` 而非数据记录时间

**表结构**:

```sql
CREATE TABLE data_freshness (
    address VARCHAR(42) NOT NULL,              -- 用户地址
    data_type VARCHAR(20) NOT NULL,            -- 数据类型
    last_fetched TIMESTAMPTZ DEFAULT NOW(),    -- 最后获取时间
    PRIMARY KEY (address, data_type)
);

CREATE INDEX idx_data_freshness_time ON data_freshness(data_type, last_fetched);

COMMENT ON TABLE data_freshness IS '数据新鲜度跟踪(记录最后成功获取时间)';
COMMENT ON COLUMN data_freshness.data_type IS 'fills, user_state, spot_state, funding, transfers';
COMMENT ON COLUMN data_freshness.last_fetched IS 'API调用成功后更新此时间';
```

**字段详解**:

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| `address` | VARCHAR(42) | NOT NULL, PK | 用户地址 | `0x162cc7c861...` |
| `data_type` | VARCHAR(20) | NOT NULL, PK | 数据类型 | `fills`, `user_state` |
| `last_fetched` | TIMESTAMPTZ | DEFAULT NOW() | 最后获取时间(UTC) | `2026-02-04 14:30:00+00` |

**支持的数据类型**:

| data_type | 对应表 | API方法 |
|-----------|--------|---------|
| `fills` | `fills` | `user_fills_by_time()` |
| `user_state` | `user_states` | `user_state()` |
| `spot_state` | `spot_states` | `spotClearinghouseState` |
| `funding` | `funding_history` | `user_funding_history()` |
| `transfers` | `transfers` | `user_non_funding_ledger_updates()` |

**索引**:

```sql
-- 复合主键索引(自动创建)
-- PRIMARY KEY (address, data_type)

-- 按数据类型和时间查询(用于批量过期检查)
CREATE INDEX idx_data_freshness_time ON data_freshness(data_type, last_fetched);
```

**查询示例**:

```sql
-- 1. 检查某地址某数据类型的新鲜度
SELECT
    last_fetched,
    EXTRACT(EPOCH FROM (NOW() - last_fetched))/3600 AS hours_ago,
    CASE
        WHEN NOW() - last_fetched < INTERVAL '24 hours' THEN 'FRESH'
        ELSE 'STALE'
    END AS status
FROM data_freshness
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND data_type = 'fills';

-- 2. 查询所有过期数据(需要刷新)
SELECT address, data_type, last_fetched
FROM data_freshness
WHERE last_fetched < NOW() - INTERVAL '24 hours'
ORDER BY last_fetched ASC;

-- 3. 统计各数据类型的新鲜度分布
SELECT
    data_type,
    COUNT(*) AS total_count,
    COUNT(*) FILTER (WHERE NOW() - last_fetched < INTERVAL '24 hours') AS fresh_count,
    COUNT(*) FILTER (WHERE NOW() - last_fetched >= INTERVAL '24 hours') AS stale_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE NOW() - last_fetched < INTERVAL '24 hours') / COUNT(*),
        2
    ) AS fresh_rate_pct
FROM data_freshness
GROUP BY data_type;

-- 4. 更新新鲜度标记(API成功后调用)
INSERT INTO data_freshness (address, data_type, last_fetched)
VALUES ('0x162cc7c861ebd0c06b3d72319201150482518185', 'fills', NOW())
ON CONFLICT (address, data_type)
DO UPDATE SET last_fetched = NOW();
```

**使用方式**:

```python
# is_data_fresh() - 检查新鲜度
async def is_data_fresh(address: str, data_type: str, ttl_hours: int = 24) -> bool:
    """基于 last_fetched 判断数据是否新鲜"""
    sql = """
    SELECT last_fetched FROM data_freshness
    WHERE address = $1 AND data_type = $2
    """
    row = await conn.fetchrow(sql, address, data_type)
    if not row or not row['last_fetched']:
        return False  # 无记录,需要获取

    age = now - row['last_fetched']
    return age.total_seconds() < ttl_hours * 3600

# update_data_freshness() - 更新新鲜度标记
async def update_data_freshness(address: str, data_type: str):
    """API成功后调用此方法"""
    sql = """
    INSERT INTO data_freshness (address, data_type, last_fetched)
    VALUES ($1, $2, NOW())
    ON CONFLICT (address, data_type)
    DO UPDATE SET last_fetched = NOW()
    """
    await conn.execute(sql, address, data_type)
```

**数据来源**: 程序运行时自动维护

**更新频率**: 每次 API 调用成功后更新

**预期效果**:
- ✅ 减少 50-80% 无效 API 调用
- ✅ 不活跃用户 24 小时内不再重复请求
- ✅ 日志中 "共 0 条新记录" 的情况大幅减少

---

## 📈 表关系图

```
┌─────────────────┐
│   addresses     │ ◄────────────────────────────────────────┐
│  (地址主表)     │                                          │
└────────┬────────┘                                          │
         │ 1:N                                               │
         │                                                   │
    ┌────┴───────────────────────────────────────────────────┤
    │                                                         │
    v                                                         │ FK: address
┌─────────────┐  ┌────────────────┐  ┌──────────────────┐    │
│   fills     │  │   transfers    │  │ funding_history  │    │
│ (交易记录)  │  │  (出入金记录)  │  │  (资金费率记录)  │    │
└─────────────┘  └────────────────┘  └──────────────────┘    │
                                                              │
┌─────────────┐  ┌────────────────┐  ┌──────────────────┐    │
│ user_states │  │  spot_states   │  │  data_freshness  │ ◄──┘
│ (Perp状态)  │  │  (Spot状态)   │  │  (新鲜度跟踪)🆕  │
└─────────────┘  └────────────────┘  └──────────────────┘

                    聚合计算
    ┌────────────────────────────────────────┐
    v                                        │
┌──────────────────┐  ┌──────────────────────┐
│  metrics_cache   │  │  account_snapshots   │
│   (综合指标)     │  │   (账户快照)         │
└──────────────────┘  └──────────────────────┘

┌──────────────────┐  ┌──────────────────────┐
│   api_cache      │  │  processing_status   │
│  (API响应缓存)   │  │   (处理状态跟踪)     │
└──────────────────┘  └──────────────────────┘
```

**表分类说明**:

| 类别 | 表名 | 说明 |
|------|------|------|
| **核心数据** | `fills`, `transfers`, `funding_history` | 时序交易数据(TimescaleDB) |
| **状态快照** | `user_states`, `spot_states`, `account_snapshots` | 账户状态历史 |
| **元数据** | `addresses`, `processing_status`, `data_freshness` | 地址和处理状态 |
| **缓存层** | `api_cache`, `metrics_cache` | 性能优化缓存 |

---

## 🔧 数据库管理脚本

### 数据库迁移记录

#### 迁移 #001: 修复 transfers.type 字段长度不足 (2026-02-04)

**问题描述**:
- `transfers.type` 字段原定义为 `VARCHAR(10)`
- 无法存储 `subAccountTransfer` 类型（19个字符）
- 导致插入错误: `value too long for type character varying(10)`

**解决方案**:
```sql
ALTER TABLE transfers
ALTER COLUMN type TYPE VARCHAR(25);
```

**影响范围**:
- ✅ 数据库 Schema: `transfers` 表
- ✅ 受影响记录: 0条（该类型数据之前无法插入）
- ✅ 应用程序: 无需修改，自动支持
- ✅ 性能影响: 无（VARCHAR扩展不影响性能）

**验证方法**:
```sql
-- 检查字段长度
SELECT column_name, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'transfers' AND column_name = 'type';

-- 预期结果: character_maximum_length = 25
```

**迁移脚本**: `migrations/fix_transfer_type_length.sql`

**执行状态**: ✅ 已完成 (2026-02-04 00:36)

---

### 完整初始化脚本

**文件**: `scripts/init_database.sql`

```sql
-- ============================================
-- Hyperliquid 分析系统数据库初始化脚本
-- 版本: v2.0
-- 创建日期: 2026-02-03
-- ============================================

-- 1. 创建数据库(如果不存在)
CREATE DATABASE IF NOT EXISTS hyperliquid_analysis;
\c hyperliquid_analysis;

-- 2. 启用 TimescaleDB 扩展(可选)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 3. 创建所有表
\i migrations/001_create_core_tables.sql
\i migrations/002_create_indexes.sql
\i migrations/003_add_funding_tables.sql

-- 4. 验证表创建
SELECT
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) AS column_count
FROM information_schema.tables t
WHERE table_schema = 'public'
ORDER BY table_name;

-- 5. 显示 TimescaleDB hypertables
SELECT
    hypertable_name,
    chunk_time_interval
FROM timescaledb_information.hypertables;
```

### 数据清理脚本

```sql
-- 清理过期缓存
DELETE FROM api_cache WHERE expires_at < NOW();

-- 清理旧的账户快照(保留90天)
DELETE FROM account_snapshots
WHERE snapshot_time < NOW() - INTERVAL '90 days';

-- 清理已完成的处理状态(保留7天)
DELETE FROM processing_status
WHERE status = 'completed'
  AND updated_at < NOW() - INTERVAL '7 days';

-- 真空优化
VACUUM ANALYZE;
```

---

## 📊 数据统计查询

### 系统整体统计

```sql
-- 数据库表大小统计
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) AS index_size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- 记录数统计
SELECT
    'addresses' AS table_name, COUNT(*) AS row_count FROM addresses
UNION ALL
SELECT 'fills', COUNT(*) FROM fills
UNION ALL
SELECT 'transfers', COUNT(*) FROM transfers
UNION ALL
SELECT 'funding_payments', COUNT(*) FROM funding_payments
UNION ALL
SELECT 'metrics_cache', COUNT(*) FROM metrics_cache
UNION ALL
SELECT 'funding_stats', COUNT(*) FROM funding_stats
UNION ALL
SELECT 'api_cache', COUNT(*) FROM api_cache
UNION ALL
SELECT 'processing_status', COUNT(*) FROM processing_status;
```

---

## 🚀 性能优化建议

### 1. 索引优化

```sql
-- 定期重建索引
REINDEX TABLE fills;
REINDEX TABLE transfers;
REINDEX TABLE funding_payments;

-- 分析表统计信息
ANALYZE addresses;
ANALYZE fills;
ANALYZE transfers;
```

### 2. TimescaleDB 优化

```sql
-- 启用压缩(历史数据)
SELECT add_compression_policy('fills', INTERVAL '30 days');
SELECT add_compression_policy('transfers', INTERVAL '60 days');
SELECT add_compression_policy('funding_payments', INTERVAL '60 days');

-- 数据保留策略
SELECT add_retention_policy('fills', INTERVAL '1 year');
SELECT add_retention_policy('transfers', INTERVAL '2 years');
```

### 3. 查询优化

```sql
-- 使用 EXPLAIN ANALYZE 分析慢查询
EXPLAIN ANALYZE
SELECT * FROM fills
WHERE address = '0x162cc7c861ebd0c06b3d72319201150482518185'
  AND time >= NOW() - INTERVAL '30 days';

-- 创建物化视图(常用聚合查询)
CREATE MATERIALIZED VIEW daily_funding_summary AS
SELECT
    time_bucket('1 day', time) AS day,
    address,
    coin,
    SUM(funding_usdc) AS daily_funding,
    AVG(funding_rate) AS avg_rate,
    COUNT(*) AS payment_count
FROM funding_payments
GROUP BY day, address, coin;

-- 刷新物化视图
REFRESH MATERIALIZED VIEW daily_funding_summary;
```

---

## 📚 相关文档

- [FUNDING_RATE_SYSTEM_DESIGN.md](./FUNDING_RATE_SYSTEM_DESIGN.md) - 资金费率系统设计
- [FUNDING_RATE_IMPLEMENTATION_GUIDE.md](./FUNDING_RATE_IMPLEMENTATION_GUIDE.md) - 实施指南
- [API_user_funding_history.md](./API_user_funding_history.md) - API 接口说明

---

## 📝 变更日志

### v3.1 (2026-02-05)
- 🆕 新增: `fills.liquidation` 字段（JSONB 类型，存储强平信息）
- ✅ 修复: 爆仓检测功能，从数据库读取时也能正确检测
- 📊 新增: 爆仓相关查询示例
- 🔧 迁移: `migrations/002_add_liquidation_field.sql`

### v3.0 (2026-02-04)
- 🆕 新增: `data_freshness` 表（数据新鲜度跟踪）
- 🆕 新增: `user_states` 表（Perp账户状态快照）
- 🆕 新增: `spot_states` 表（Spot账户状态快照）
- 🔄 重命名: `funding_payments` → `funding_history`（与代码一致）
- ✅ 修复: `is_data_fresh()` 基于 `last_fetched` 判断，减少无效 API 调用
- 📊 总表数: 11 张

### v2.1 (2026-02-04)
- ✅ 修复: `transfers.type` 字段长度从 `VARCHAR(10)` 扩展至 `VARCHAR(25)`
- ✅ 原因: 支持 `subAccountTransfer` 类型（19字符）
- ✅ 迁移: 执行 `migrations/fix_transfer_type_length.sql`
- ✅ 影响: 解决 "value too long" 插入错误

### v2.0 (2026-02-03)
- 🆕 新增: `funding_history` 表（资金费率记录）
- 📝 完善: 所有表的详细文档和查询示例

---

**文档版本**: v3.1
**最后更新**: 2026-02-05
**包含表数**: 11张
**数据库**: PostgreSQL 14+ with TimescaleDB 2.0+
**代码对应**: `address_analyzer/data_store.py`

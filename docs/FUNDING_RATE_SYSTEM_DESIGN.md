# 资金费率系统详细设计文档

## 📋 文档概述

本文档详细说明了 Hyperliquid 资金费率历史数据的**完整系统设计**,包括数据库表结构、数据处理流程、计算逻辑、集成方案和性能优化策略。

**适用范围**: `analyze_addresses.py` 资金费率分析功能扩展

**依赖文档**:
- `API_user_funding_history.md` - API 接口说明
- `address_analyzer/data_store.py` - 数据存储层实现

---

## 📊 数据库表设计

### 1. 资金费率记录表 (funding_payments)

**表名**: `funding_payments`

**用途**: 存储用户的资金费率结算历史记录

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
    PRIMARY KEY (id, time)
);

-- TimescaleDB hypertable 配置
SELECT create_hypertable('funding_payments', 'time',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

-- 性能优化索引
CREATE INDEX idx_funding_address_time ON funding_payments(address, time DESC);
CREATE INDEX idx_funding_coin_time ON funding_payments(coin, time DESC);
CREATE INDEX idx_funding_address_coin ON funding_payments(address, coin, time DESC);
```

**字段说明**:

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGSERIAL | PRIMARY KEY | 自增主键 |
| `address` | VARCHAR(42) | NOT NULL | 用户地址(0x开头) |
| `time` | TIMESTAMPTZ | NOT NULL | 结算时间(UTC,分区键) |
| `coin` | VARCHAR(20) | NOT NULL | 币种代码(BTC/ETH/等) |
| `funding_usdc` | DECIMAL(20, 8) | - | 资金费用(正=收入,负=支出) |
| `position_size` | DECIMAL(20, 4) | - | 持仓量(正=多头,负=空头) |
| `funding_rate` | DECIMAL(12, 8) | - | 资金费率(正=多付空,负=空付多) |
| `n_samples` | INTEGER | - | 统计样本数(通常24) |
| `tx_hash` | VARCHAR(66) | - | 区块链交易哈希 |

**设计要点**:

1. **时间分区**: 使用 TimescaleDB hypertable,按30天分区以优化历史数据查询
2. **复合索引**: 支持按地址、币种、时间的多维度查询
3. **数据类型**:
   - `funding_usdc`: DECIMAL(20,8) 支持高精度计算
   - `position_size`: DECIMAL(20,4) 匹配永续合约精度
   - `funding_rate`: DECIMAL(12,8) 存储小数点后8位费率

---

### 2. 资金费率统计表 (funding_stats)

**表名**: `funding_stats`

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
    calculated_at TIMESTAMPTZ DEFAULT NOW()    -- 计算时间
);

-- 索引优化
CREATE INDEX idx_funding_stats_total ON funding_stats(total_funding_usdc DESC);
CREATE INDEX idx_funding_stats_rate ON funding_stats(annual_funding_rate DESC);
```

**字段说明**:

| 字段 | 说明 | 计算公式 |
|------|------|----------|
| `total_funding_usdc` | 累计净资金费 | SUM(funding_usdc) |
| `total_funding_income` | 累计收入 | SUM(funding_usdc WHERE funding_usdc > 0) |
| `total_funding_expense` | 累计支出 | SUM(ABS(funding_usdc) WHERE funding_usdc < 0) |
| `avg_funding_rate` | 平均费率 | AVG(funding_rate) |
| `annual_funding_rate` | 年化费率 | avg_funding_rate × 8 × 365 × 100 |
| `funding_payment_count` | 总结算次数 | COUNT(*) |
| `funding_income_count` | 收入次数 | COUNT(*) WHERE funding_usdc > 0 |
| `funding_expense_count` | 支出次数 | COUNT(*) WHERE funding_usdc < 0 |
| `funding_coin_count` | 币种数 | COUNT(DISTINCT coin) |

---

### 3. 币种资金费率统计表 (funding_coin_stats)

**表名**: `funding_coin_stats`

**用途**: 缓存各地址在不同币种上的资金费率统计

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

-- 索引优化
CREATE INDEX idx_funding_coin_stats_addr ON funding_coin_stats(address);
CREATE INDEX idx_funding_coin_stats_coin ON funding_coin_stats(coin);
CREATE INDEX idx_funding_coin_stats_total ON funding_coin_stats(total_funding_usdc DESC);
```

**设计要点**:

1. **复合主键**: (address, coin) 唯一标识用户在某币种上的统计
2. **持仓天数**: `holding_days = payment_count / 8` (每天8次结算)
3. **平均持仓**: 反映用户在该币种上的平均仓位规模

---

## 🔄 数据处理流程

### 整体架构

```
┌─────────────────┐
│   trades.log    │
│ (日志解析)      │
└────────┬────────┘
         │
         v
┌─────────────────┐      ┌──────────────────┐
│  addresses 表   │      │  Hyperliquid API │
│ (地址列表)      │◄────►│ user_funding_    │
└────────┬────────┘      │ history()        │
         │               └────────┬─────────┘
         │                        │
         v                        v
┌─────────────────────────────────────────┐
│          funding_payments 表            │
│        (原始资金费率记录)               │
└────────┬────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────┐
│         MetricsEngine                   │
│       (指标计算引擎)                    │
└────────┬────────────────────────────────┘
         │
         ├─────────────────┬───────────────┐
         v                 v               v
┌─────────────────┐ ┌─────────────┐ ┌─────────────────┐
│ funding_stats   │ │ funding_    │ │  metrics_cache  │
│    (总统计)     │ │ coin_stats  │ │  (综合指标)     │
└─────────────────┘ └─────────────┘ └─────────────────┘
```

### 数据流向详解

#### 阶段 1: 数据获取 (API Client)

**模块**: `address_analyzer/api_client.py`

```python
async def fetch_funding_data(self, address: str, save_to_db: bool = True) -> Dict:
    """
    获取并保存资金费率数据

    Args:
        address: 用户地址
        save_to_db: 是否保存到数据库

    Returns:
        {'funding_payments': List[Dict], 'stats': Dict}
    """
    # 1. 检查数据新鲜度
    if not self.force_refresh:
        is_fresh = await self.store.is_data_fresh(address, 'funding')
        if is_fresh:
            existing_data = await self.store.get_funding_payments(address)
            if existing_data:
                logger.info(f"使用缓存的资金费率数据: {address}")
                stats = self._calculate_funding_stats(existing_data)
                return {'funding_payments': existing_data, 'stats': stats}

    # 2. 调用 API
    try:
        # 获取最近90天数据
        current_time = int(time.time() * 1000)
        start_time = current_time - (90 * 24 * 60 * 60 * 1000)

        async with self.rate_limiter:
            async with self.semaphore:
                funding_history = self.info.user_funding_history(
                    user=address,
                    startTime=start_time
                )

        logger.info(f"获取资金费率数据: {address} ({len(funding_history)} 条)")

        # 3. 保存到数据库
        if save_to_db and funding_history:
            await self.store.save_funding_payments(address, funding_history)

        # 4. 更新数据新鲜度标记
        await self.store.update_data_freshness(address, 'funding')

        result = {
            'funding_payments': funding_history,
            'stats': self._calculate_funding_stats(funding_history)
        }

        return result

    except Exception as e:
        logger.error(f"获取资金费率数据失败: {address} - {e}")
        return {'funding_payments': [], 'stats': {}}
```

#### 阶段 2: 数据存储 (Data Store)

**模块**: `address_analyzer/data_store.py`

```python
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

    if records_to_insert:
        async with self.pool.acquire() as conn:
            # 去重检查
            check_sql = """
            SELECT COUNT(*) FROM funding_payments
            WHERE address = $1 AND time = $2 AND coin = $3
            """

            insert_sql = """
            INSERT INTO funding_payments (
                address, time, coin, funding_usdc, position_size,
                funding_rate, n_samples, tx_hash
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """

            inserted_count = 0
            for record in records_to_insert:
                addr, time_dt, coin = record[0], record[1], record[2]

                # 检查是否已存在
                exists = await conn.fetchval(check_sql, addr, time_dt, coin)
                if not exists:
                    await conn.execute(insert_sql, *record)
                    inserted_count += 1

            logger.info(f"保存 {inserted_count}/{len(records_to_insert)} 条资金费率记录: {address}")
```

#### 阶段 3: 统计计算 (Metrics Engine)

**模块**: `address_analyzer/metrics_engine.py`

```python
def calculate_funding_metrics(self, address: str, funding_data: List[Dict]) -> Dict:
    """
    计算资金费率指标

    Args:
        address: 用户地址
        funding_data: 资金费率记录列表

    Returns:
        统计指标字典
    """
    if not funding_data:
        return self._empty_funding_metrics()

    # 1. 基础统计
    total_funding = sum(float(r['funding_usdc']) for r in funding_data)
    income_records = [r for r in funding_data if float(r['funding_usdc']) > 0]
    expense_records = [r for r in funding_data if float(r['funding_usdc']) < 0]

    total_income = sum(float(r['funding_usdc']) for r in income_records)
    total_expense = sum(abs(float(r['funding_usdc'])) for r in expense_records)

    # 2. 费率统计
    avg_rate = np.mean([float(r['funding_rate']) for r in funding_data])
    annual_rate = avg_rate * 8 * 365 * 100  # 年化百分比

    # 3. 币种统计
    coin_stats = defaultdict(lambda: {
        'total_funding': 0.0,
        'count': 0,
        'avg_position': 0.0
    })

    for record in funding_data:
        coin = record['coin']
        coin_stats[coin]['total_funding'] += float(record['funding_usdc'])
        coin_stats[coin]['count'] += 1
        coin_stats[coin]['avg_position'] += float(record['position_size'])

    # 计算平均值
    for coin, stats in coin_stats.items():
        stats['avg_position'] /= stats['count']
        stats['holding_days'] = stats['count'] / 8

    # 4. 时间范围
    times = [r['time'] for r in funding_data]
    first_time = min(times)
    last_time = max(times)

    return {
        'address': address,
        'total_funding_usdc': total_funding,
        'total_funding_income': total_income,
        'total_funding_expense': total_expense,
        'avg_funding_rate': avg_rate,
        'annual_funding_rate': annual_rate,
        'funding_payment_count': len(funding_data),
        'funding_income_count': len(income_records),
        'funding_expense_count': len(expense_records),
        'funding_coin_count': len(coin_stats),
        'coin_breakdown': dict(coin_stats),
        'first_funding_time': first_time,
        'last_funding_time': last_time
    }
```

#### 阶段 4: 数据持久化 (Cache Update)

**模块**: `address_analyzer/data_store.py`

```python
async def save_funding_stats(self, address: str, stats: Dict):
    """
    保存资金费率统计数据

    Args:
        address: 用户地址
        stats: 统计指标字典
    """
    # 1. 保存总统计
    sql_stats = """
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
            sql_stats,
            address,
            stats['total_funding_usdc'],
            stats['total_funding_income'],
            stats['total_funding_expense'],
            stats['avg_funding_rate'],
            stats['annual_funding_rate'],
            stats['funding_payment_count'],
            stats['funding_income_count'],
            stats['funding_expense_count'],
            stats['funding_coin_count'],
            stats['first_funding_time'],
            stats['last_funding_time']
        )

    # 2. 保存币种统计
    if 'coin_breakdown' in stats:
        await self._save_funding_coin_stats(address, stats['coin_breakdown'])
```

---

## 🧮 核心计算逻辑

### 1. 资金费用计算

**公式**:
```
资金费用(USDC) = 持仓量 × 标记价格 × 资金费率
funding_usdc = position_size × mark_price × funding_rate
```

**实现**:
```python
def calculate_funding_payment(
    position_size: float,
    mark_price: float,
    funding_rate: float
) -> float:
    """
    计算资金费用

    Args:
        position_size: 持仓量(正=多头,负=空头)
        mark_price: 标记价格(USDC)
        funding_rate: 资金费率

    Returns:
        资金费用(USDC)
    """
    return position_size * mark_price * funding_rate
```

**示例**:
```python
# 多头持仓,正费率
position = 0.5  # 0.5 BTC 多头
mark_price = 50000  # BTC价格 $50,000
funding_rate = 0.0001  # 0.01% 费率

payment = calculate_funding_payment(position, mark_price, funding_rate)
# payment = 0.5 × 50000 × 0.0001 = -2.5 USDC (支付)
```

---

### 2. 年化资金费率

**公式**:
```
年化费率(%) = 平均费率 × 每日结算次数 × 365 × 100
annual_rate = avg_rate × 8 × 365 × 100
```

**实现**:
```python
def calculate_annual_funding_rate(avg_rate: float) -> float:
    """
    计算年化资金费率

    Args:
        avg_rate: 平均资金费率(小数)

    Returns:
        年化费率(百分比)
    """
    SETTLEMENTS_PER_DAY = 8  # Hyperliquid每天结算8次
    DAYS_PER_YEAR = 365

    return avg_rate * SETTLEMENTS_PER_DAY * DAYS_PER_YEAR * 100
```

**示例**:
```python
avg_rate = 0.0001  # 平均费率 0.01%
annual_rate = calculate_annual_funding_rate(avg_rate)
# annual_rate = 0.0001 × 8 × 365 × 100 = 29.2%
```

---

### 3. 持仓天数估算

**公式**:
```
持仓天数 = 结算次数 / 每日结算次数
holding_days = payment_count / 8
```

**实现**:
```python
def estimate_holding_days(payment_count: int) -> float:
    """
    估算持仓天数

    Args:
        payment_count: 资金费结算次数

    Returns:
        持仓天数
    """
    SETTLEMENTS_PER_DAY = 8
    return payment_count / SETTLEMENTS_PER_DAY
```

---

### 4. 资金费用占比

**公式**:
```
资金费用占总PnL比例 = |累计资金费用| / |总交易盈亏| × 100%
funding_ratio = |total_funding| / |total_pnl| × 100
```

**实现**:
```python
def calculate_funding_impact(
    total_funding: float,
    total_pnl: float
) -> Dict[str, float]:
    """
    计算资金费用对盈亏的影响

    Args:
        total_funding: 累计资金费用
        total_pnl: 总交易盈亏

    Returns:
        影响分析结果
    """
    if total_pnl == 0:
        return {'ratio': 0.0, 'adjusted_pnl': total_funding}

    funding_ratio = abs(total_funding) / abs(total_pnl) * 100
    adjusted_pnl = total_pnl + total_funding  # 加上资金费收支

    return {
        'funding_ratio': funding_ratio,      # 资金费占比
        'adjusted_pnl': adjusted_pnl,        # 调整后的真实盈亏
        'funding_contribution': (total_funding / adjusted_pnl * 100) if adjusted_pnl != 0 else 0
    }
```

---

## 🔗 系统集成方案

### 1. 与现有指标系统整合

**修改 `address_analyzer/orchestrator.py`**:

```python
async def run(self, ...):
    """运行完整分析流程"""

    # ... 现有代码 ...

    # 新增: 获取资金费率数据
    self.renderer.console.print("[bold cyan]步骤 3.5/5:[/bold cyan] 获取资金费率数据...")

    for addr in pending_addresses:
        try:
            # 获取并保存资金费率数据
            funding_data = await self.api_client.fetch_funding_data(
                addr,
                save_to_db=True
            )

            # 计算并保存统计指标
            if funding_data['funding_payments']:
                funding_stats = self.metrics_engine.calculate_funding_metrics(
                    addr,
                    funding_data['funding_payments']
                )
                await self.store.save_funding_stats(addr, funding_stats)

        except Exception as e:
            logger.error(f"处理资金费率失败: {addr} - {e}")

    # ... 继续现有流程 ...
```

### 2. 扩展 AddressMetrics 数据模型

**修改 `address_analyzer/metrics_engine.py`**:

```python
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
    funding_adjusted_pnl: float = 0.0        # 资金费调整后的盈亏
    funding_to_pnl_ratio: float = 0.0        # 资金费占盈亏比例(%)
```

### 3. 修改计算引擎

**修改 `calculate_metrics()` 方法**:

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

## 📈 报告展示增强

### 1. 终端输出扩展

**修改 `address_analyzer/output_renderer.py`**:

```python
def render_terminal(self, metrics: List[AddressMetrics], ...):
    """渲染终端表格"""

    table = Table(title="交易地址综合分析")

    # 现有列
    table.add_column("地址", style="cyan")
    table.add_column("总盈亏", style="green")
    table.add_column("ROI", style="yellow")

    # 新增列
    table.add_column("资金费用", style="magenta")          # 新增
    table.add_column("资金费调整PnL", style="blue")       # 新增
    table.add_column("年化费率", style="red")             # 新增

    for m in metrics:
        # 资金费用显示(绿色=收入,红色=支出)
        funding_style = "green" if m.total_funding_usdc > 0 else "red"
        funding_str = f"[{funding_style}]{m.total_funding_usdc:+,.2f}[/{funding_style}]"

        table.add_row(
            m.address[:10] + "...",
            f"{m.total_pnl:+,.2f}",
            f"{m.roi:+.2f}%",
            funding_str,                                    # 新增
            f"{m.funding_adjusted_pnl:+,.2f}",             # 新增
            f"{m.annual_funding_rate:+.2f}%"               # 新增
        )

    self.console.print(table)
```

### 2. HTML 报告扩展

**新增资金费率分析模块**:

```html
<!-- 新增: 资金费率分析卡片 -->
<div class="metric-card">
    <h3>💰 资金费率分析</h3>
    <div class="metrics-grid">
        <div class="metric-item">
            <span class="metric-label">累计资金费用</span>
            <span class="metric-value {{ 'positive' if total_funding > 0 else 'negative' }}">
                {{ total_funding|format_currency }}
            </span>
        </div>
        <div class="metric-item">
            <span class="metric-label">年化资金费率</span>
            <span class="metric-value">{{ annual_rate|format_percent }}</span>
        </div>
        <div class="metric-item">
            <span class="metric-label">结算次数</span>
            <span class="metric-value">{{ payment_count }}</span>
        </div>
        <div class="metric-item">
            <span class="metric-label">资金费占盈亏比例</span>
            <span class="metric-value">{{ funding_ratio|format_percent }}</span>
        </div>
    </div>

    <!-- 资金费用时间序列图表 -->
    <div id="funding-chart"></div>

    <!-- 币种分解表格 -->
    <table class="coin-breakdown">
        <thead>
            <tr>
                <th>币种</th>
                <th>累计费用</th>
                <th>结算次数</th>
                <th>持仓天数</th>
            </tr>
        </thead>
        <tbody>
            {% for coin, stats in coin_breakdown.items() %}
            <tr>
                <td>{{ coin }}</td>
                <td class="{{ 'positive' if stats.total > 0 else 'negative' }}">
                    {{ stats.total|format_currency }}
                </td>
                <td>{{ stats.count }}</td>
                <td>{{ stats.holding_days|round(1) }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
```

---

## ⚡ 性能优化策略

### 1. 缓存策略

**多级缓存架构**:

```python
# Level 1: 内存缓存(最快)
memory_cache = {}  # {address: funding_stats}

# Level 2: Redis 缓存(可选,快)
redis_cache_key = f"funding:{address}"
ttl = 3600  # 1小时

# Level 3: PostgreSQL 专用数据表 + data_freshness(推荐)
# - funding_payments 表: 完整历史数据
# - data_freshness 表: 跟踪数据新鲜度
```

**缓存失效策略**:

```python
async def get_funding_stats(address: str) -> Dict:
    """智能缓存获取"""

    # 1. 检查内存缓存
    if address in memory_cache:
        cache_time = memory_cache[address]['cached_at']
        if (datetime.now() - cache_time).seconds < 300:  # 5分钟有效
            return memory_cache[address]['data']

    # 2. 检查 Redis 缓存(可选)
    redis_data = await redis_client.get(f"funding:{address}")
    if redis_data:
        memory_cache[address] = {
            'data': redis_data,
            'cached_at': datetime.now()
        }
        return redis_data

    # 3. 检查数据新鲜度 + 从专用表获取
    is_fresh = await store.is_data_fresh(address, 'funding')
    if is_fresh:
        db_data = await store.get_funding_payments(address)
        if db_data:
            stats = calculate_funding_stats(db_data)
            await redis_client.setex(f"funding:{address}", 3600, stats)
            memory_cache[address] = {
                'data': stats,
                'cached_at': datetime.now()
            }
            return stats

    # 4. 从 API 获取并保存到专用表
    fresh_data = await fetch_from_api(address)
    await store.save_funding_payments(address, fresh_data)
    await store.update_data_freshness(address, 'funding')

    # 缓存传播
    stats = calculate_funding_stats(fresh_data)
    memory_cache[address] = {'data': stats, 'cached_at': datetime.now()}
    await redis_client.setex(f"funding:{address}", 3600, stats)

    return stats
```

---

### 2. 批量处理优化

**分批获取策略**:

```python
async def batch_fetch_funding_data(
    addresses: List[str],
    batch_size: int = 50,
    max_concurrent: int = 10
) -> Dict[str, Dict]:
    """
    批量获取资金费率数据

    Args:
        addresses: 地址列表
        batch_size: 每批处理数量
        max_concurrent: 最大并发数

    Returns:
        {address: funding_stats}
    """
    results = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_one(addr: str):
        async with semaphore:
            try:
                data = await get_funding_stats(addr)
                results[addr] = data
            except Exception as e:
                logger.error(f"获取失败: {addr} - {e}")
                results[addr] = None

    # 分批处理
    for i in range(0, len(addresses), batch_size):
        batch = addresses[i:i + batch_size]
        tasks = [fetch_one(addr) for addr in batch]
        await asyncio.gather(*tasks)

        # 批次间延迟,避免API限流
        if i + batch_size < len(addresses):
            await asyncio.sleep(1)

    return results
```

---

### 3. 数据库查询优化

**使用 TimescaleDB 连续聚合**:

```sql
-- 创建物化视图: 每日资金费用汇总
CREATE MATERIALIZED VIEW funding_daily_summary
WITH (timescaledb.continuous) AS
SELECT
    address,
    coin,
    time_bucket('1 day', time) AS day,
    SUM(funding_usdc) AS daily_funding,
    AVG(funding_rate) AS avg_rate,
    COUNT(*) AS payment_count
FROM funding_payments
GROUP BY address, coin, day;

-- 自动刷新策略
SELECT add_continuous_aggregate_policy('funding_daily_summary',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);
```

**高效查询最近统计**:

```sql
-- 使用物化视图查询(快)
SELECT
    coin,
    SUM(daily_funding) AS total_funding,
    AVG(avg_rate) AS overall_avg_rate
FROM funding_daily_summary
WHERE address = $1
  AND day >= NOW() - INTERVAL '30 days'
GROUP BY coin;

-- vs 直接查询原表(慢)
SELECT
    coin,
    SUM(funding_usdc) AS total_funding,
    AVG(funding_rate) AS avg_rate
FROM funding_payments
WHERE address = $1
  AND time >= NOW() - INTERVAL '30 days'
GROUP BY coin;
```

---

## 🎯 使用场景与最佳实践

### 场景 1: 交易员盈亏分析

**需求**: 计算真实盈亏(包含资金费用)

**实现**:

```python
async def calculate_true_pnl(address: str) -> Dict:
    """计算包含资金费的真实盈亏"""

    # 1. 获取交易盈亏
    fills = await store.get_fills(address)
    trade_pnl = sum(float(f['closed_pnl']) for f in fills)

    # 2. 获取资金费用
    funding_stats = await store.get_funding_stats(address)
    funding_total = funding_stats['total_funding_usdc']

    # 3. 计算真实盈亏
    true_pnl = trade_pnl + funding_total

    # 4. 计算资金费影响
    funding_impact = abs(funding_total) / abs(trade_pnl) * 100 if trade_pnl != 0 else 0

    return {
        'trade_pnl': trade_pnl,
        'funding_total': funding_total,
        'true_pnl': true_pnl,
        'funding_impact_pct': funding_impact,
        'analysis': '资金费用' + ('增加' if funding_total > 0 else '减少') + f'了 {funding_impact:.1f}% 的盈亏'
    }
```

---

### 场景 2: 持仓策略分析

**需求**: 识别用户偏好的持仓方向(多头 vs 空头)

**实现**:

```python
async def analyze_position_bias(address: str) -> Dict:
    """分析持仓偏好"""

    sql = """
    SELECT
        COUNT(*) as total_payments,
        SUM(CASE WHEN position_size > 0 THEN 1 ELSE 0 END) as long_count,
        SUM(CASE WHEN position_size < 0 THEN 1 ELSE 0 END) as short_count,
        AVG(CASE WHEN position_size > 0 THEN position_size ELSE 0 END) as avg_long_size,
        AVG(CASE WHEN position_size < 0 THEN ABS(position_size) ELSE 0 END) as avg_short_size
    FROM funding_payments
    WHERE address = $1
    """

    async with store.pool.acquire() as conn:
        result = await conn.fetchrow(sql, address)

    long_pct = result['long_count'] / result['total_payments'] * 100
    short_pct = result['short_count'] / result['total_payments'] * 100

    bias = 'Long Bias' if long_pct > 55 else ('Short Bias' if short_pct > 55 else 'Balanced')

    return {
        'position_bias': bias,
        'long_percentage': long_pct,
        'short_percentage': short_pct,
        'avg_long_size': float(result['avg_long_size']),
        'avg_short_size': float(result['avg_short_size']),
        'interpretation': f"用户 {long_pct:.1f}% 时间持多头, {short_pct:.1f}% 时间持空头"
    }
```

---

### 场景 3: 费率套利检测

**需求**: 识别通过资金费套利获利的地址

**实现**:

```python
async def detect_funding_arbitrage(address: str) -> Dict:
    """检测资金费套利行为"""

    funding_stats = await store.get_funding_stats(address)

    # 套利特征:
    # 1. 资金费收入远大于交易盈亏
    # 2. 高频率结算(持仓时间长)
    # 3. 持仓方向频繁切换

    trade_pnl = await get_trade_pnl(address)
    funding_income = funding_stats['total_funding_income']

    # 计算资金费占总收益比例
    total_profit = trade_pnl + funding_income
    funding_contribution = (funding_income / total_profit * 100) if total_profit > 0 else 0

    # 判断是否为套利策略
    is_arbitrage = (
        funding_contribution > 50  # 资金费收入占比 > 50%
        and funding_stats['funding_payment_count'] > 100  # 结算次数 > 100
        and funding_stats['funding_income_count'] / funding_stats['funding_payment_count'] > 0.6  # 收入次数占比 > 60%
    )

    return {
        'is_funding_arbitrage': is_arbitrage,
        'funding_contribution_pct': funding_contribution,
        'avg_holding_days': funding_stats['funding_payment_count'] / 8,
        'strategy_type': 'Funding Arbitrage' if is_arbitrage else 'Directional Trading',
        'confidence': 'High' if funding_contribution > 70 else ('Medium' if funding_contribution > 50 else 'Low')
    }
```

---

## 🔍 监控与告警

### 1. 数据质量监控

```python
async def monitor_data_quality():
    """监控资金费率数据质量"""

    checks = []

    # 1. 检查数据完整性
    sql_gaps = """
    SELECT address, COUNT(*) as gap_count
    FROM (
        SELECT address, coin, time,
               LAG(time) OVER (PARTITION BY address, coin ORDER BY time) as prev_time,
               EXTRACT(EPOCH FROM (time - LAG(time) OVER (PARTITION BY address, coin ORDER BY time))) / 3600 as gap_hours
        FROM funding_payments
    ) AS gaps
    WHERE gap_hours > 4  -- 超过4小时间隔视为数据缺失
    GROUP BY address
    HAVING COUNT(*) > 5
    """

    # 2. 检查异常费率
    sql_outliers = """
    SELECT address, coin, time, funding_rate
    FROM funding_payments
    WHERE ABS(funding_rate) > 0.01  -- 费率超过1%视为异常
    ORDER BY time DESC
    LIMIT 100
    """

    # 3. 检查计算一致性
    sql_consistency = """
    SELECT
        fp.address,
        SUM(fp.funding_usdc) as calculated_total,
        fs.total_funding_usdc as cached_total,
        ABS(SUM(fp.funding_usdc) - fs.total_funding_usdc) as difference
    FROM funding_payments fp
    JOIN funding_stats fs ON fp.address = fs.address
    GROUP BY fp.address, fs.total_funding_usdc
    HAVING ABS(SUM(fp.funding_usdc) - fs.total_funding_usdc) > 1
    """

    async with store.pool.acquire() as conn:
        gaps = await conn.fetch(sql_gaps)
        outliers = await conn.fetch(sql_outliers)
        inconsistencies = await conn.fetch(sql_consistency)

    # 生成告警
    if gaps:
        logger.warning(f"发现 {len(gaps)} 个地址存在数据缺失")

    if outliers:
        logger.warning(f"发现 {len(outliers)} 条异常费率记录")

    if inconsistencies:
        logger.error(f"发现 {len(inconsistencies)} 个地址数据不一致")

    return {
        'data_gaps': len(gaps),
        'outliers': len(outliers),
        'inconsistencies': len(inconsistencies),
        'status': 'OK' if not (gaps or outliers or inconsistencies) else 'WARNING'
    }
```

---

### 2. 性能监控

```python
@dataclass
class PerformanceMetrics:
    """性能指标"""
    api_call_time: float          # API调用耗时
    db_insert_time: float          # 数据库插入耗时
    calculation_time: float        # 指标计算耗时
    cache_hit_rate: float          # 缓存命中率
    records_per_second: float      # 处理速率

async def monitor_performance() -> PerformanceMetrics:
    """监控系统性能"""

    # 采样性能数据
    start_time = time.time()

    # 1. API 性能
    api_start = time.time()
    await api_client.fetch_funding_data(test_address)
    api_time = time.time() - api_start

    # 2. 数据库性能
    db_start = time.time()
    await store.save_funding_payments(test_address, sample_data)
    db_time = time.time() - db_start

    # 3. 计算性能
    calc_start = time.time()
    metrics_engine.calculate_funding_metrics(test_address, sample_data)
    calc_time = time.time() - calc_start

    # 4. 缓存命中率
    cache_stats = await store.get_cache_stats()

    return PerformanceMetrics(
        api_call_time=api_time,
        db_insert_time=db_time,
        calculation_time=calc_time,
        cache_hit_rate=cache_stats['hit_rate'],
        records_per_second=len(sample_data) / (time.time() - start_time)
    )
```

---

## 📚 API 参考

### DataStore 新增方法

```python
class DataStore:

    async def save_funding_payments(self, address: str, funding_data: List[Dict]):
        """保存资金费率记录"""
        pass

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
        pass

    async def get_funding_stats(self, address: str) -> Dict:
        """获取资金费率统计"""
        pass

    async def save_funding_stats(self, address: str, stats: Dict):
        """保存资金费率统计"""
        pass

    async def get_funding_coin_stats(
        self,
        address: str,
        coin: Optional[str] = None
    ) -> List[Dict]:
        """获取币种分解统计"""
        pass
```

---

## 🚀 部署清单

### 1. 数据库迁移脚本

**文件**: `migrations/003_add_funding_tables.sql`

```sql
-- 创建资金费率相关表
\i scripts/create_funding_tables.sql

-- 添加索引
CREATE INDEX CONCURRENTLY idx_funding_address_time
    ON funding_payments(address, time DESC);

-- 创建物化视图
CREATE MATERIALIZED VIEW funding_daily_summary ...;

-- 数据迁移(如果需要)
INSERT INTO funding_payments (...)
SELECT ... FROM legacy_funding_data;
```

---

### 2. 环境变量配置

```bash
# 资金费率功能开关
ENABLE_FUNDING_ANALYSIS=true

# 数据获取配置
FUNDING_LOOKBACK_DAYS=90          # 回溯天数
FUNDING_CACHE_TTL_HOURS=1         # 缓存有效期

# 性能配置
FUNDING_BATCH_SIZE=50             # 批处理大小
FUNDING_MAX_CONCURRENT=10         # 最大并发数
```

---

## 📖 相关文档

- [API_user_funding_history.md](./API_user_funding_history.md) - API 接口详细说明
- [Database Schema](../address_analyzer/data_store.py) - 数据库表结构
- [Metrics Engine](../address_analyzer/metrics_engine.py) - 指标计算逻辑

---

**文档版本**: v1.0
**创建日期**: 2026-02-03
**作者**: Claude Code
**状态**: ✅ 设计完成,待实现

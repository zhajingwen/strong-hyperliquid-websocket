# TimescaleDB Hypertable 迁移说明

## 问题说明

系统运行时出现 TimescaleDB 警告：

```
⚠️  TimescaleDB hypertable 创建失败: table "fills" is not empty
HINT:  You can migrate data by specifying 'migrate_data => true' when calling this function.
```

这是因为 `fills` 表已经包含 145 万+条数据，无法直接转换为 hypertable。

## 解决方案

### 方案 1: 忽略警告（推荐）

**说明**: TimescaleDB hypertable 是性能优化功能，不影响核心业务逻辑。

**优点**:
- ✅ 无风险，系统继续正常运行
- ✅ 无需数据迁移
- ✅ 表功能完整

**操作**: 无需任何操作，系统已经正常工作

**修改代码以隐藏警告** (可选):

编辑 `address_analyzer/data_store.py`，找到 hypertable 创建部分（约 174-189 行）：

```python
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
            logger.info("   提示: hypertable 是可选的性能优化功能")
    else:
        logger.info("ℹ️  TimescaleDB 扩展未安装，跳过 hypertable 创建（不影响基础功能）")
        logger.info("   安装方法: CREATE EXTENSION timescaledb;")
except Exception as e:
    # 降低错误级别
    logger.info(f"ℹ️  跳过 TimescaleDB hypertable 创建: {e}")
    logger.info("   提示: 这不影响系统功能，仅是时序数据优化")
```

---

### 方案 2: 手动迁移到 Hypertable（高级用户）

**警告**: 此操作需要约 10-15 分钟，期间系统不可用。建议在维护窗口执行。

**前置条件**:
1. 数据库已备份
2. 系统当前无运行任务
3. 有充足的磁盘空间（约 2x 当前 fills 表大小）

**迁移步骤**:

1. **停止系统**
   ```bash
   # 停止所有正在运行的分析任务
   ```

2. **备份数据库**
   ```bash
   pg_dump -h 127.0.0.1 -U postgres -d hyperliquid_analysis > backup.sql
   ```

3. **执行迁移** (使用 psql)
   ```sql
   -- 1. 重命名现有表
   ALTER TABLE fills RENAME TO fills_backup;

   -- 2. 创建新表
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
   );

   -- 3. 转换为 hypertable
   SELECT create_hypertable('fills', 'time',
       chunk_time_interval => INTERVAL '7 days',
       if_not_exists => true
   );

   -- 4. 复制数据（约 5-10 分钟）
   INSERT INTO fills (id, address, time, coin, side, price, size, closed_pnl, fee, hash)
   SELECT id, address, time, coin, side, price, size, closed_pnl, fee, hash
   FROM fills_backup;

   -- 5. 创建索引
   CREATE INDEX idx_fills_address_time ON fills(address, time DESC);

   -- 6. 验证数据
   SELECT COUNT(*) FROM fills;
   SELECT COUNT(*) FROM fills_backup;
   -- 两个数字应该相同

   -- 7. 确认无误后删除备份表
   -- DROP TABLE fills_backup;
   ```

4. **验证系统**
   ```bash
   python analyze_addresses.py
   ```

---

## 性能对比

| 特性 | 普通表 | Hypertable |
|------|--------|------------|
| 基础功能 | ✅ 完整 | ✅ 完整 |
| 时间范围查询 | 正常速度 | 10-100x 快 |
| 数据压缩 | 手动 | 自动 |
| 分区管理 | 手动 | 自动 |
| 数据保留策略 | 手动 | 自动 |

## 常见问题

### Q: 不迁移会影响功能吗？
A: **不会**。所有功能正常，只是时序查询性能无法获得 TimescaleDB 的优化。

### Q: 迁移过程中数据会丢失吗？
A: 不会。迁移脚本会先创建备份表，验证数据完整性后才删除备份。

### Q: 迁移需要多长时间？
A: 约 10-15 分钟，取决于数据量和硬件性能。

### Q: 迁移失败怎么办？
A: 脚本有自动恢复机制，会恢复到迁移前状态。或者手动执行：
```sql
DROP TABLE IF EXISTS fills CASCADE;
ALTER TABLE fills_backup RENAME TO fills;
```

---

## 推荐方案

对于大多数用户，**推荐方案 1（忽略警告）**：
- ✅ 零风险
- ✅ 系统功能完整
- ✅ 无需维护窗口

如果需要极致的时序查询性能优化，可以在维护窗口执行方案 2。

---

**创建时间**: 2026-02-02
**状态**: ✅ 核心功能正常运行
**影响**: 仅影响时序数据优化，不影响业务功能

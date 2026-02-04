# 数据库迁移记录

本文档记录所有数据库Schema变更历史，确保数据库版本可追溯。

---

## 📋 迁移总览

| 迁移编号 | 日期 | 类型 | 说明 | 状态 |
|---------|------|------|------|------|
| #001 | 2026-02-04 | 字段修改 | 修复 transfers.type 字段长度不足 | ✅ 已完成 |

---

## 📝 详细迁移记录

### 迁移 #001: 修复 transfers.type 字段长度不足

**迁移日期**: 2026-02-04 00:36 UTC

**问题背景**:
```
错误日志:
address_analyzer.orchestrator - ERROR - 处理地址失败: 0x6503fa99...
- value too long for type character varying(10)
```

数据库 `transfers` 表的 `type` 字段定义为 `VARCHAR(10)`，无法存储 `subAccountTransfer` 类型（19个字符），导致插入失败。

**影响范围**:
- **表**: `transfers`
- **字段**: `type`
- **原定义**: `VARCHAR(10)`
- **新定义**: `VARCHAR(25)`
- **受影响记录**: 0条（该类型数据之前无法插入）

**数据类型长度对比**:

| 类型 | 字符数 | 原状态 | 新状态 |
|------|--------|--------|--------|
| `deposit` | 7 | ✅ 正常 | ✅ 正常 |
| `withdraw` | 8 | ✅ 正常 | ✅ 正常 |
| `send` | 4 | ✅ 正常 | ✅ 正常 |
| `subAccountTransfer` | 19 | ❌ 超限 | ✅ 正常 |

**迁移SQL**:
```sql
-- 修改字段长度
ALTER TABLE transfers
ALTER COLUMN type TYPE VARCHAR(25);

-- 添加字段注释
COMMENT ON COLUMN transfers.type IS
'转账类型: deposit(7), withdraw(8), send(4), subAccountTransfer(19)';
```

**迁移脚本**: [`migrations/fix_transfer_type_length.sql`](../migrations/fix_transfer_type_length.sql)

**执行方法**:
```bash
# 方法1: 使用 psql
psql -U postgres -d hyperliquid_analysis -f migrations/fix_transfer_type_length.sql

# 方法2: 使用 Python 脚本
python3 -c "
import asyncio
import asyncpg
import os

async def migrate():
    conn = await asyncpg.connect(
        user=os.getenv('TIMESCALEDB_USER', 'postgres'),
        password=os.getenv('TIMESCALEDB_PASSWORD', 'postgres'),
        host=os.getenv('TIMESCALEDB_HOST', '127.0.0.1'),
        port=int(os.getenv('TIMESCALEDB_PORT', 5432)),
        database=os.getenv('TIMESCALEDB_DATABASE', 'hyperliquid_analysis')
    )

    await conn.execute('ALTER TABLE transfers ALTER COLUMN type TYPE VARCHAR(25)')
    print('✅ 迁移完成')

    await conn.close()

asyncio.run(migrate())
"
```

**验证结果**:
```sql
-- 检查字段长度
SELECT column_name, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'transfers' AND column_name = 'type';

-- 结果: character_maximum_length = 25 ✅

-- 检查现有数据分布
SELECT type, COUNT(*) as count
FROM transfers
GROUP BY type
ORDER BY type;

-- 结果:
-- deposit: 2750 条
-- send: 988 条
-- withdraw: 2060 条
```

**影响评估**:
- ✅ **数据完整性**: 无影响（仅扩展字段长度）
- ✅ **性能影响**: 无影响（VARCHAR扩展不影响性能）
- ✅ **应用程序**: 无需修改（自动支持）
- ✅ **回滚风险**: 低（可安全回滚）

**回滚方案**:
```sql
-- 如需回滚（仅当确认无 subAccountTransfer 数据时）
ALTER TABLE transfers
ALTER COLUMN type TYPE VARCHAR(10);

-- ⚠️ 警告: 如果已有 subAccountTransfer 数据，回滚会失败
```

**相关文档**:
- [DATABASE_SCHEMA_DESIGN.md](./DATABASE_SCHEMA_DESIGN.md#3-transfers---出入金记录表-timescaledb-hypertable) - 表结构设计
- [API_user_ledger_updates.md](./API_user_ledger_updates.md) - API 数据格式说明

**执行者**: Database Migration Script
**审核者**: System Administrator
**状态**: ✅ 已完成并验证

---

## 🔍 迁移验证清单

### 迁移前检查
- [x] 备份数据库
- [x] 检查字段当前长度
- [x] 评估影响范围
- [x] 准备回滚方案

### 迁移执行
- [x] 执行 ALTER TABLE 语句
- [x] 添加字段注释
- [x] 验证字段长度修改成功

### 迁移后验证
- [x] 检查字段长度 (character_maximum_length = 25)
- [x] 检查现有数据完整性
- [x] 测试新类型数据插入
- [x] 更新文档

---

## 📚 迁移最佳实践

### 1. 执行前准备
```bash
# 备份数据库
pg_dump -U postgres -d hyperliquid_analysis > backup_$(date +%Y%m%d).sql

# 检查当前状态
psql -U postgres -d hyperliquid_analysis -c "\d transfers"
```

### 2. 测试环境验证
```bash
# 在测试环境先执行
psql -U postgres -d hyperliquid_analysis_test -f migrations/fix_transfer_type_length.sql
```

### 3. 生产环境执行
```bash
# 在低峰期执行
psql -U postgres -d hyperliquid_analysis -f migrations/fix_transfer_type_length.sql

# 验证
psql -U postgres -d hyperliquid_analysis -c "
SELECT column_name, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'transfers' AND column_name = 'type';
"
```

### 4. 监控和回滚
```bash
# 监控应用程序日志
tail -f logs/app.log | grep "transfers"

# 如需回滚
psql -U postgres -d hyperliquid_analysis -f migrations/rollback_001.sql
```

---

## 🔗 相关资源

### 文档
- [DATABASE_SCHEMA_DESIGN.md](./DATABASE_SCHEMA_DESIGN.md) - 完整数据库设计
- [INCREMENTAL_UPDATE_GUIDE.md](./INCREMENTAL_UPDATE_GUIDE.md) - 增量更新指南

### 迁移脚本
- [`migrations/fix_transfer_type_length.sql`](../migrations/fix_transfer_type_length.sql) - 字段长度修复

### 相关代码
- `address_analyzer/data_store.py:458-493` - 转账数据处理逻辑
- `address_analyzer/api_client.py:675-741` - 转账数据分类

---

**文档版本**: v1.0
**最后更新**: 2026-02-04
**维护者**: Database Team

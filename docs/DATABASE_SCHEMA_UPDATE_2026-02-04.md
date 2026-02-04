# 数据库表结构设计文档更新说明

**更新日期**: 2026-02-04
**更新人**: Claude
**相关文档**: `docs/DATABASE_SCHEMA_DESIGN.md`

---

## 📋 更新摘要

本次更新主要涉及 **metrics_cache** 表的ROI字段优化，删除了不准确的推算ROI指标，改用更精确的计算方法。

### 核心变更

| 变更类型 | 详情 | 影响范围 |
|---------|------|---------|
| 🗑️ 删除字段 | `metrics_cache.roi` DECIMAL(12,2) | 数据库表结构 |
| 🗑️ 删除索引 | `idx_metrics_roi` | 查询性能优化 |
| 📝 更新文档 | 添加变更历史和ROI指标说明 | 开发文档 |
| ✅ 保留指标 | 应用层计算的精确ROI指标 | 业务逻辑层 |

---

## 🔍 详细变更内容

### 1. 添加变更历史部分

**位置**: 文档第11-25行

**内容**:
```markdown
## 📝 变更历史

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
```

**目的**: 记录重要的表结构变更，便于未来追溯

---

### 2. 更新 metrics_cache 表定义

**位置**: 第678-700行

**修改前**:
```sql
CREATE TABLE metrics_cache (
    address VARCHAR(42) PRIMARY KEY,
    total_trades INTEGER,
    win_rate DECIMAL(6, 2),
    roi DECIMAL(12, 2),           -- ❌ 已删除
    sharpe_ratio DECIMAL(10, 4),
    ...
);
```

**修改后**:
```sql
CREATE TABLE metrics_cache (
    address VARCHAR(42) PRIMARY KEY,
    total_trades INTEGER,
    win_rate DECIMAL(6, 2),
    sharpe_ratio DECIMAL(10, 4),  -- roi列已删除
    ...
);
```

**新增说明框**:
```markdown
> **💡 ROI指标说明** (2026-02-04更新)
> - ❌ **已删除**: `roi` 列（基于推算初始资金的ROI，可能不准确）
> - ✅ **推荐使用**: 应用层计算的更精确ROI指标：
>   - `AddressMetrics.true_capital_roi` - 基于真实本金的ROI
>   - `AddressMetrics.time_weighted_roi` - 时间加权ROI
>   - `AddressMetrics.annualized_roi` - 年化ROI
>   - `AddressMetrics.total_roi` - 总ROI（含未实现盈亏）
> - 📊 这些指标在 `AddressMetrics` 数据类中计算，不存储在数据库中
```

---

### 3. 删除字段详解表中的roi行

**位置**: 第690-710行

**修改**: 删除了字段详解表格中的以下行：

| 字段 | 类型 | 约束 | 说明 | 示例值 |
|------|------|------|------|--------|
| ~~`roi`~~ | ~~DECIMAL(12,2)~~ | ~~-~~ | ~~ROI百分比~~ | ~~`123.45`~~ |

**当前字段列表**:
1. `address` - 用户地址
2. `total_trades` - 总交易次数
3. `win_rate` - 胜率(%)
4. `sharpe_ratio` - 夏普比率
5. `total_pnl` - 总盈亏(USDC)
6. `account_value` - 账户价值(USDC)
7. `max_drawdown` - 最大回撤(%)
8. `net_deposit` - 净充值(USDC)
9. `calculated_at` - 计算时间

---

### 4. 删除索引定义

**位置**: 第705-720行

**修改前**:
```sql
-- 按总盈亏排序查询
CREATE INDEX idx_metrics_total_pnl ON metrics_cache(total_pnl DESC);

-- 按ROI排序查询
CREATE INDEX idx_metrics_roi ON metrics_cache(roi DESC);  -- ❌ 已删除

-- 按夏普比率排序查询
CREATE INDEX idx_metrics_sharpe ON metrics_cache(sharpe_ratio DESC);
```

**修改后**:
```sql
-- 按总盈亏排序查询
CREATE INDEX idx_metrics_total_pnl ON metrics_cache(total_pnl DESC);

-- 按夏普比率排序查询
CREATE INDEX idx_metrics_sharpe ON metrics_cache(sharpe_ratio DESC);
```

**影响**: 删除了 `idx_metrics_roi` 索引定义

---

### 5. 更新查询示例

**位置**: 第721-755行

#### 示例1: 查询Top 50盈利地址

**修改前**:
```sql
SELECT
    address,
    total_trades,
    win_rate,
    roi,              -- ❌ 已删除
    sharpe_ratio,
    total_pnl,
    account_value
FROM metrics_cache
ORDER BY total_pnl DESC
LIMIT 50;
```

**修改后**:
```sql
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
```

#### 示例2: 查询高夏普比率地址

**修改前**:
```sql
SELECT
    address,
    sharpe_ratio,
    roi,              -- ❌ 已删除
    total_pnl,
    win_rate
FROM metrics_cache
WHERE sharpe_ratio > 2.0
  AND total_trades >= 100
ORDER BY sharpe_ratio DESC;
```

**修改后**:
```sql
SELECT
    address,
    sharpe_ratio,
    total_pnl,
    win_rate
FROM metrics_cache
WHERE sharpe_ratio > 2.0
  AND total_trades >= 100
ORDER BY sharpe_ratio DESC;
```

---

## 📊 ROI指标对比

### 删除的指标

| 指标 | 字段名 | 计算方法 | 问题 |
|------|--------|---------|------|
| ❌ ROI(推算) | `roi` | `(已实现PNL / 推算初始资金) × 100` | 推算初始资金不准确 |
| ❌ ROI(校准) | `corrected_roi` | `(已实现PNL / 实际初始资金) × 100` | 包含转账，不反映真实投入 |

### 保留的指标

| 指标 | 字段名 | 计算方法 | 优点 |
|------|--------|---------|------|
| ✅ 真实本金ROI | `true_capital_roi` | `(已实现PNL / 真实本金) × 100` | 仅统计充值/提现，最准确 |
| ✅ 时间加权ROI | `time_weighted_roi` | 考虑资金使用时长的加权计算 | 更公平地评估收益率 |
| ✅ 年化ROI | `annualized_roi` | 标准化为年化收益率 | 便于不同周期比较 |
| ✅ 总ROI | `total_roi` | 包含未实现盈亏 | 完整的收益评估 |

**数据存储位置**:
- ❌ 数据库层（已删除）: `metrics_cache.roi`
- ✅ 应用层（保留）: `AddressMetrics` 数据类字段

---

## 🔄 升级影响分析

### 影响的组件

| 组件 | 影响 | 状态 |
|------|------|------|
| 数据库表 | `metrics_cache` 少一列 | ✅ 已迁移 |
| 数据模型 | `AddressMetrics` 删除字段 | ✅ 已更新 |
| 计算引擎 | `calculate_pnl_and_roi()` 返回值变更 | ✅ 已更新 |
| 输出渲染 | 终端和HTML删除ROI列 | ✅ 已更新 |
| 数据存储 | `save_metrics()` 删除roi键 | ✅ 已更新 |
| 业务协调 | `orchestrator.py` 删除roi引用 | ✅ 已更新 |

### 需要用户操作

1. **运行数据库迁移**:
   ```bash
   python migrations/run_migration_auto.py
   ```

2. **更新依赖代码**:
   - 如有自定义查询使用了 `roi` 字段，需要更新为其他指标
   - 如有报表依赖 `roi` 列，需要调整为使用应用层计算的ROI

3. **测试验证**:
   - 运行分析程序验证输出正常
   - 检查报告中不再显示ROI(推算)和ROI(校准)列

---

## 📚 相关文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 数据库Schema | `docs/DATABASE_SCHEMA_DESIGN.md` | 本次更新的主文档 |
| 清理指南 | `ROI_CLEANUP_GUIDE.md` | 完整的ROI清理操作指南 |
| 迁移脚本 | `migrations/drop_roi_column.sql` | SQL迁移脚本 |
| 自动迁移工具 | `migrations/run_migration_auto.py` | Python自动化迁移脚本 |

---

## ✅ 验证检查清单

- [x] 数据库表结构定义已更新
- [x] 字段详解表格已更新
- [x] 索引定义已更新（删除idx_metrics_roi）
- [x] 查询示例已更新（删除roi字段引用）
- [x] 添加了变更历史记录
- [x] 添加了ROI指标说明框
- [x] 文档内容完整一致
- [x] 所有代码引用已清理

---

## 🎯 更新总结

本次文档更新与代码重构保持一致，确保文档准确反映当前的数据库设计：

1. ✅ **删除过时内容**: roi字段及其相关索引、查询
2. ✅ **添加变更说明**: 记录重要的架构变更
3. ✅ **保持文档质量**: 1477行完整文档，10个表定义
4. ✅ **用户友好**: 提供清晰的迁移指引和ROI指标对比

文档现已与最新的数据库结构和代码实现完全同步！

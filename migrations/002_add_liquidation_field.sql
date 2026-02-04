-- 迁移脚本：为 fills 表添加 liquidation 字段
-- 用于修复爆仓检测功能

-- 1. 添加 liquidation 字段（如果不存在）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'fills' AND column_name = 'liquidation'
    ) THEN
        ALTER TABLE fills ADD COLUMN liquidation JSONB;
        RAISE NOTICE 'Added liquidation column to fills table';
    ELSE
        RAISE NOTICE 'liquidation column already exists';
    END IF;
END $$;

-- 2. 创建索引以便快速查询爆仓记录（可选）
CREATE INDEX IF NOT EXISTS idx_fills_liquidation
ON fills ((liquidation IS NOT NULL))
WHERE liquidation IS NOT NULL;

-- 3. 查看当前表结构
-- \d fills

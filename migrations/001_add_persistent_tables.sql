-- Migration: 001_add_persistent_tables
-- Description: 添加 user_states, spot_states, funding_history 表用于持久化所有API数据
-- Date: 2026-02-04

-- 1. 用户账户状态表 (Perp)
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

-- 2. Spot账户状态表
CREATE TABLE IF NOT EXISTS spot_states (
    id BIGSERIAL,
    address VARCHAR(42) NOT NULL,
    snapshot_time TIMESTAMPTZ NOT NULL,
    balances JSONB,
    PRIMARY KEY (id, snapshot_time)
);

-- 3. 资金费率历史表
CREATE TABLE IF NOT EXISTS funding_history (
    address VARCHAR(42) NOT NULL,
    time TIMESTAMPTZ NOT NULL,
    coin VARCHAR(20) NOT NULL,
    usdc DECIMAL(20, 8),
    szi DECIMAL(20, 8),
    funding_rate DECIMAL(20, 10),
    PRIMARY KEY (time, address, coin)
);

-- 4. 索引优化
CREATE INDEX IF NOT EXISTS idx_user_states_address_time ON user_states(address, snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_spot_states_address_time ON spot_states(address, snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_funding_history_address_time ON funding_history(address, time DESC);

-- 5. TimescaleDB hypertable 转换（如果 TimescaleDB 已安装）
-- 注意：如果表已有数据，需要先清空或使用 migrate_data 参数
DO $$
BEGIN
    -- 检查 TimescaleDB 是否已安装
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        -- 尝试创建 hypertable
        BEGIN
            PERFORM create_hypertable('user_states', 'snapshot_time',
                chunk_time_interval => INTERVAL '7 days',
                if_not_exists => TRUE
            );
            RAISE NOTICE 'user_states hypertable created';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'user_states hypertable creation skipped: %', SQLERRM;
        END;

        BEGIN
            PERFORM create_hypertable('spot_states', 'snapshot_time',
                chunk_time_interval => INTERVAL '7 days',
                if_not_exists => TRUE
            );
            RAISE NOTICE 'spot_states hypertable created';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'spot_states hypertable creation skipped: %', SQLERRM;
        END;

        BEGIN
            PERFORM create_hypertable('funding_history', 'time',
                chunk_time_interval => INTERVAL '30 days',
                if_not_exists => TRUE
            );
            RAISE NOTICE 'funding_history hypertable created';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'funding_history hypertable creation skipped: %', SQLERRM;
        END;
    ELSE
        RAISE NOTICE 'TimescaleDB not installed, skipping hypertable creation';
    END IF;
END $$;

-- 6. 添加注释
COMMENT ON TABLE user_states IS '用户 Perp 账户状态快照（来自 user_state API）';
COMMENT ON TABLE spot_states IS '用户 Spot 账户状态快照（来自 spotClearinghouseState API）';
COMMENT ON TABLE funding_history IS '用户资金费率历史记录（来自 user_funding_history API）';

-- ClickHouse 表结构：行情数据存储
-- 在 192.168.1.18 的 ClickHouse strategy2560 数据库上执行
--
-- MySQL 存储：workspace_status, analysis_batch, structure_2560_*, job_queue,
--             job_execution, data_import_*, stock_info, strategy_config 等
-- ClickHouse 仅存储：daily_kline, minute_kline_period

-- 清理多余的 MySQL 副本表（ClickHouse 不需要这些）
DROP TABLE IF EXISTS analysis_batch;
DROP TABLE IF EXISTS analysis_job_log;
DROP TABLE IF EXISTS concept_tags;
DROP TABLE IF EXISTS data_quality_check;
DROP TABLE IF EXISTS stock_calc_status;
DROP TABLE IF EXISTS stock_info;
DROP TABLE IF EXISTS strategy_config;
DROP TABLE IF EXISTS structure_2560_analysis;
DROP TABLE IF EXISTS structure_2560_statistics;
DROP TABLE IF EXISTS structure_2560_tag_detail;
DROP TABLE IF EXISTS sync_status;
DROP TABLE IF EXISTS workspace_status;

-- ── 行情数据表 ──

-- 日线 K 线
DROP TABLE IF EXISTS daily_kline;
CREATE TABLE daily_kline (
    code String,
    date Date,
    source LowCardinality(String) DEFAULT 'vipdoc',
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume Float64,
    amount Float64
) ENGINE = MergeTree()
ORDER BY (code, date)
PRIMARY KEY (code, date);

-- 分钟 K 线（5m / 30m 统一存储）
DROP TABLE IF EXISTS minute_kline_period;
CREATE TABLE minute_kline_period (
    code String,
    date DateTime64(0),
    period LowCardinality(String),
    source LowCardinality(String) DEFAULT 'vipdoc',
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume Float64,
    amount Float64
) ENGINE = MergeTree()
ORDER BY (code, period, date)
PRIMARY KEY (code, period, date);

-- 技术指标（对应 MySQL `technical_indicator` 字段，转 ClickHouse 语法）
DROP TABLE IF EXISTS technical_indicator;
CREATE TABLE technical_indicator (
    code String,
    period LowCardinality(String),
    date DateTime64(3),
    source LowCardinality(String) DEFAULT 'vipdoc',
    stock_status Nullable(String),
    is_st Nullable(UInt8) DEFAULT 0,
    ma25 Nullable(Float64),
    ma60 Nullable(Float64),
    ma200 Nullable(Float64),
    ma25_slope_3 Nullable(Float64),
    ma60_slope_3 Nullable(Float64),
    atr14 Nullable(Float64),
    atr20_avg Nullable(Float64),
    vol_ma5 Nullable(Float64),
    vol_ma60 Nullable(Float64),
    vol_ratio Nullable(Float64),
    vol_ma5_cross_vol_ma60 Nullable(UInt8) DEFAULT 0,
    price_ma25_deviation_pct Nullable(Float64),
    high_20 Nullable(Float64),
    low_20 Nullable(Float64),
    low_30 Nullable(Float64),
    resistance_level Nullable(Float64),
    is_abnormal_bar Nullable(UInt8) DEFAULT 0,
    data_quality_status Nullable(String),
    created_at DateTime64(3) DEFAULT now64(3),
    updated_at DateTime64(3) DEFAULT now64(3)
) ENGINE = MergeTree()
ORDER BY (code, period, date, source);

SELECT 'ClickHouse tables created' AS result;
SELECT name AS table_name FROM system.tables WHERE database = 'strategy2560' ORDER BY name;

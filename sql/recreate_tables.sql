-- MySQL 表结构重建（空表，无数据）
-- WARNING: 本脚本会 DROP 并重建表，只能用于空库初始化；生产增量迁移请使用 scripts/apply_2560_v122_schema.py。
-- 在 192.168.1.254 的 MySQL 上执行

USE watchlist_decision_support;

-- 1. 行情数据表
DROP TABLE IF EXISTS daily_kline;
CREATE TABLE daily_kline (
  code VARCHAR(20) NOT NULL,
  date INT NOT NULL,
  source VARCHAR(20) NOT NULL DEFAULT 'vipdoc',
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume BIGINT, amount DOUBLE,
  PRIMARY KEY (code, date, source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS minute_kline_period;
CREATE TABLE minute_kline_period (
  code VARCHAR(20) NOT NULL,
  date BIGINT NOT NULL,
  period VARCHAR(10) NOT NULL,
  source VARCHAR(20) NOT NULL DEFAULT 'vipdoc',
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume DOUBLE, amount DOUBLE,
  PRIMARY KEY (code, date, period, source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- technical_indicator 已迁移至 ClickHouse，MySQL 不再存储

DROP TABLE IF EXISTS minute_kline;
CREATE TABLE minute_kline (
  code VARCHAR(20) NOT NULL,
  date INT NOT NULL,
  source VARCHAR(20) NOT NULL,
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume BIGINT, amount DOUBLE,
  PRIMARY KEY (code, date, source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 股票基础
DROP TABLE IF EXISTS stock_info;
CREATE TABLE stock_info (
  code VARCHAR(20) NOT NULL PRIMARY KEY,
  name VARCHAR(100), market VARCHAR(20), code_type VARCHAR(20),
  source VARCHAR(20), record_count INT,
  first_date INT, last_date INT, updated_at DATETIME(3),
  industry_code VARCHAR(20), industry_name VARCHAR(100),
  region_code VARCHAR(20), region_name VARCHAR(100),
  board_code VARCHAR(20), board_name VARCHAR(100),
  total_shares DOUBLE, circulating_shares DOUBLE,
  total_assets DOUBLE, net_assets DOUBLE,
  net_profit DOUBLE, main_profit DOUBLE, revenue DOUBLE,
  eps_adjusted DOUBLE, list_date VARCHAR(20)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS concept_tags;
CREATE TABLE concept_tags (
  code VARCHAR(20) NOT NULL,
  concept_code VARCHAR(20) NOT NULL,
  concept_name VARCHAR(100),
  PRIMARY KEY (code, concept_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 策略配置
DROP TABLE IF EXISTS strategy_config;
CREATE TABLE strategy_config (
  strategy_code VARCHAR(30) NOT NULL,
  config_key VARCHAR(100) NOT NULL,
  config_group VARCHAR(50),
  config_value VARCHAR(100),
  value_type VARCHAR(20),
  description VARCHAR(500),
  enabled TINYINT(1) DEFAULT 1,
  updated_at DATETIME,
  PRIMARY KEY (strategy_code, config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. 2560 分析
-- 注：technical_indicator 已迁移至 ClickHouse，MySQL 不再存储（见 sql/clickhouse_tables.sql）
DROP TABLE IF EXISTS structure_2560_analysis;
CREATE TABLE structure_2560_analysis (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  signal_uid VARCHAR(32) UNIQUE,
  batch_id VARCHAR(64),
  strategy_code VARCHAR(30),
  strategy_version VARCHAR(50),
  code VARCHAR(20), name VARCHAR(100),
  signal_time DATETIME,
  signal_period VARCHAR(10),
  price DOUBLE,
  source VARCHAR(20),
  stock_status VARCHAR(20),
  has_2560_signal TINYINT(1) DEFAULT 0,
  price_near_ma25 TINYINT(1) DEFAULT 0,
  ma25_slope_ok TINYINT(1) DEFAULT 0,
  volume_structure_ok TINYINT(1) DEFAULT 0,
  abnormal_filter_ok TINYINT(1) DEFAULT 0,
  trend_price_ok TINYINT(1) DEFAULT 0,
  trend_slope_ok TINYINT(1) DEFAULT 0,
  volatility_ok TINYINT(1) DEFAULT 0,
  breakout_ok TINYINT(1) DEFAULT 0,
  volume_ok TINYINT(1) DEFAULT 0,
  near_resistance TINYINT(1) DEFAULT 0,
  pullback_ok TINYINT(1) DEFAULT 0,
  bullish_confirm TINYINT(1) DEFAULT 0,
  structure_status VARCHAR(20),
  strength_score_raw DOUBLE,
  missing_tags JSON,
  missing_tag_count INT,
  explain_text TEXT,
  data_quality_status VARCHAR(30),
  is_duplicate_signal TINYINT(1) DEFAULT 0,
  selected_signal TINYINT(1) DEFAULT 0,
  selection_status VARCHAR(20),
  final_score DECIMAL(5,4),
  recent_3d_pct DECIMAL(6,3),
  explode_status VARCHAR(20),
  market_state VARCHAR(20),
  environment_score DECIMAL(5,4),
  hot_topic_strength VARCHAR(20),
  position_in_hot_topic VARCHAR(20),
  hot_topic_score DECIMAL(5,4),
  volume_score DECIMAL(5,4),
  structure_score DECIMAL(5,4),
  intraday_score DECIMAL(5,4),
  pressure_score DECIMAL(5,4),
  signal_type VARCHAR(30),
  status VARCHAR(20) DEFAULT 'active',
  entry_price DOUBLE, stop_loss DOUBLE, target_price DOUBLE,
  confidence DOUBLE, reason TEXT,
  created_at DATETIME, updated_at DATETIME,
  INDEX idx_code (code), INDEX idx_batch (batch_id),
  INDEX idx_signal_time (signal_time),
  INDEX idx_structure_status (structure_status),
  INDEX idx_strategy_code (strategy_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS structure_2560_tag_detail;
CREATE TABLE structure_2560_tag_detail (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  analysis_id BIGINT,
  batch_id BIGINT,
  code VARCHAR(20),
  signal_time BIGINT,
  tag_code VARCHAR(50),
  tag_name VARCHAR(100),
  tag_type VARCHAR(50),
  tag_value VARCHAR(500),
  created_at DATETIME,
  INDEX idx_analysis (analysis_id),
  INDEX idx_code (code),
  INDEX idx_tag_name (tag_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS structure_2560_statistics;
CREATE TABLE structure_2560_statistics (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id BIGINT,
  stat_date DATE,
  strategy_code VARCHAR(30),
  code VARCHAR(20),
  total_signals INT, win_count INT, loss_count INT,
  win_rate DOUBLE, avg_return DOUBLE, max_drawdown DOUBLE,
  updated_at DATETIME,
  INDEX idx_strategy_code (strategy_code),
  INDEX idx_code (code),
  INDEX idx_stat_date (stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS market_state_daily;
CREATE TABLE market_state_daily (
  trade_date DATE NOT NULL,
  index_code VARCHAR(20) NOT NULL,
  index_close DECIMAL(10,2),
  index_pct DECIMAL(6,3),
  limit_up_count INT,
  limit_down_count INT,
  up_count INT,
  down_count INT,
  up_ratio DECIMAL(5,4),
  market_state VARCHAR(20),
  environment_score DECIMAL(5,4),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (trade_date, index_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS hot_topic_daily;
CREATE TABLE hot_topic_daily (
  trade_date DATE NOT NULL,
  topic_code VARCHAR(50) NOT NULL,
  topic_name VARCHAR(100),
  topic_pct DECIMAL(6,3),
  topic_pct_rank INT,
  limit_up_count INT,
  consecutive_high INT,
  leader_code VARCHAR(20),
  leader_name VARCHAR(50),
  hot_topic_strength VARCHAR(20),
  topic_score DECIMAL(5,4),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (trade_date, topic_code),
  INDEX idx_strength (trade_date, hot_topic_strength)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS stock_topic_position_daily;
CREATE TABLE stock_topic_position_daily (
  trade_date DATE NOT NULL,
  code VARCHAR(20) NOT NULL,
  topic_code VARCHAR(50) NOT NULL,
  rank_in_topic INT,
  is_leader TINYINT,
  is_consecutive_limit_up TINYINT,
  consecutive_days INT,
  position_label VARCHAR(20),
  position_score DECIMAL(5,4),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (trade_date, code, topic_code),
  INDEX idx_code (trade_date, code),
  INDEX idx_position (trade_date, position_label)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS morning_confirm_daily;
CREATE TABLE morning_confirm_daily (
  trade_date DATE NOT NULL,
  code VARCHAR(20) NOT NULL,
  yesterday_status VARCHAR(20),
  yesterday_final_score DECIMAL(5,4),
  yesterday_hot_topic VARCHAR(100),
  today_auction_volume BIGINT,
  yesterday_auction_volume BIGINT,
  avg5_auction_volume DOUBLE,
  auction_amplify_ratio DECIMAL(8,4),
  is_significantly_amplified TINYINT,
  open_gap_pct DECIMAL(6,3),
  pre_market_state VARCHAR(20),
  morning_grade VARCHAR(20),
  morning_score DECIMAL(5,4),
  missing_reason VARCHAR(100),
  confirm_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (trade_date, code),
  INDEX idx_grade (trade_date, morning_grade),
  CONSTRAINT chk_skipped_code CHECK (
    morning_grade IS NOT NULL
    AND (
      (morning_grade = 'skipped' AND code = '__skip__')
      OR
      (morning_grade != 'skipped' AND code != '__skip__')
    )
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS external_data_cache;
CREATE TABLE external_data_cache (
  cache_key VARCHAR(120) NOT NULL PRIMARY KEY,
  source VARCHAR(50),
  data_json JSON,
  cache_date DATE,
  ttl_hours INT DEFAULT 24 COMMENT 'NULL=仅审计; 0=立即过期; >0=正常TTL',
  expire_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_expire (expire_at),
  INDEX idx_source (source, cache_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS external_call_budget;
CREATE TABLE external_call_budget (
  source VARCHAR(50) NOT NULL PRIMARY KEY,
  daily_limit INT,
  today_used INT DEFAULT 0,
  reset_at DATE,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS external_call_log;
CREATE TABLE external_call_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  call_time DATETIME,
  source VARCHAR(50),
  endpoint VARCHAR(100),
  params JSON,
  status VARCHAR(20),
  duration_ms INT,
  response_size INT,
  error_msg TEXT,
  INDEX idx_time (call_time),
  INDEX idx_source (source, call_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS analysis_batch;
CREATE TABLE analysis_batch (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id BIGINT,
  batch_name VARCHAR(255),
  run_time DATETIME,
  data_source VARCHAR(100),
  strategy_code VARCHAR(30),
  strategy_version VARCHAR(50),
  param_snapshot JSON,
  status VARCHAR(20),
  message TEXT,
  total_codes INT, success_codes INT, failed_codes INT,
  started_at DATETIME, finished_at DATETIME,
  updated_at DATETIME,
  INDEX idx_strategy_code (strategy_code),
  INDEX idx_status (status),
  INDEX idx_run_time (run_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS analysis_job_log;
CREATE TABLE analysis_job_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id BIGINT, code VARCHAR(20), status VARCHAR(20),
  error_message TEXT, duration_ms BIGINT, created_at DATETIME,
  INDEX idx_batch (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. 任务队列
DROP TABLE IF EXISTS job_queue;
CREATE TABLE job_queue (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  job_type VARCHAR(50) NOT NULL,
  strategy_code VARCHAR(20) NOT NULL,
  priority INT NOT NULL DEFAULT 5,
  payload JSON NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_queue (status, priority, created_at),
  KEY idx_strategy (strategy_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS job_execution;
CREATE TABLE job_execution (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  job_type VARCHAR(50) NOT NULL,
  batch_id VARCHAR(100) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'running',
  cancel_requested_at DATETIME NULL,
  progress_current INT NOT NULL DEFAULT 0,
  progress_total INT NOT NULL DEFAULT 0,
  success_count INT NOT NULL DEFAULT 0,
  failed_count INT NOT NULL DEFAULT 0,
  current_code VARCHAR(30) NULL,
  market VARCHAR(20) NULL,
  shards INT NULL,
  pid BIGINT NULL,
  log_file VARCHAR(500) NULL,
  message TEXT NULL,
  started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_status_started (status, started_at),
  KEY idx_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS job_task_item;
CREATE TABLE job_task_item (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  job_id BIGINT NOT NULL,
  shard_id INT NOT NULL DEFAULT 0,
  code VARCHAR(30) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  retry_count INT NOT NULL DEFAULT 0,
  elapsed_ms INT NULL,
  last_error TEXT NULL,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_job_code (job_id, code),
  KEY idx_job_status (job_id, status),
  KEY idx_shard (job_id, shard_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. 数据导入
DROP TABLE IF EXISTS data_import_batch;
CREATE TABLE data_import_batch (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  import_type VARCHAR(50) NOT NULL DEFAULT 'vipdoc',
  source_dir VARCHAR(500),
  market VARCHAR(20),
  status VARCHAR(20) NOT NULL DEFAULT 'queued',
  total_files INT NOT NULL DEFAULT 0,
  success_files INT NOT NULL DEFAULT 0,
  failed_files INT NOT NULL DEFAULT 0,
  total_rows BIGINT NOT NULL DEFAULT 0,
  started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME,
  message TEXT,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_status_started (status, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS data_import_file;
CREATE TABLE data_import_file (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  import_batch_id BIGINT NOT NULL,
  file_path VARCHAR(700) NOT NULL,
  market VARCHAR(20),
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  rows_imported INT NOT NULL DEFAULT 0,
  last_error TEXT,
  started_at DATETIME,
  finished_at DATETIME,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_batch (import_batch_id),
  INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. 工作区 / 状态
DROP TABLE IF EXISTS workspace_status;
CREATE TABLE workspace_status (
    market VARCHAR(10) PRIMARY KEY,
    daily_latest     INT DEFAULT NULL COMMENT '日线最新日期 YYYYMMDD',
    k5m_latest       BIGINT DEFAULT NULL COMMENT '5m K线最新日期 YYYYMMDDHHMMSS',
    k30m_latest      BIGINT DEFAULT NULL COMMENT '30m K线最新日期',
    ind_daily        INT DEFAULT NULL COMMENT '日线指标最新日期',
    ind_5m           BIGINT DEFAULT NULL COMMENT '5m 指标最新日期',
    ind_30m          BIGINT DEFAULT NULL COMMENT '30m 指标最新日期',
    source_daily     INT DEFAULT NULL COMMENT '源文件日线最新日期',
    indicators_fresh TINYINT(1) DEFAULT 0,
    ready            TINYINT(1) DEFAULT 0,
    missing_json     JSON DEFAULT NULL,
    status_text      VARCHAR(50) DEFAULT '',
    daily_gap_label  VARCHAR(20) DEFAULT '',
    daily_gap        INT DEFAULT NULL,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO workspace_status (market) VALUES ('sh60'), ('sh68'), ('sz00'), ('sz30');

DROP TABLE IF EXISTS stock_calc_status;
CREATE TABLE stock_calc_status (
  code VARCHAR(20) NOT NULL,
  strategy_code VARCHAR(30) NOT NULL,
  last_import_at DATETIME,
  last_calc_at DATETIME,
  status VARCHAR(20),
  error_message TEXT,
  updated_at DATETIME,
  PRIMARY KEY (code, strategy_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS sync_status;
CREATE TABLE sync_status (
  source_name VARCHAR(100) NOT NULL PRIMARY KEY,
  source_type VARCHAR(50),
  last_sync_time DATETIME,
  status VARCHAR(20),
  message TEXT,
  updated_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS data_quality_check;
CREATE TABLE data_quality_check (
  code VARCHAR(20),
  date DATE,
  period VARCHAR(20),
  check_type VARCHAR(50),
  status VARCHAR(20),
  message TEXT,
  created_at DATETIME,
  INDEX idx_code_date (code, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 插入默认策略配置
INSERT INTO strategy_config (strategy_code, config_key, config_group, config_value, value_type, description, enabled) VALUES
('S2560', 'ma_price_period', '盘后均线参数', '25', 'int', '关键均线周期', 1),
('S2560', 'vol_short_period', '盘后量能参数', '5', 'int', '短期均量周期', 1),
('S2560', 'vol_long_period', '盘后量能参数', '60', 'int', '长期均量周期', 1),
('S2560', 'atr_period', '盘后ATR参数', '14', 'int', 'ATR计算周期', 1),
('S2560', 'atr_compare_period', '盘后ATR参数', '20', 'int', 'ATR对比周期', 1),
('S2560', 'breakout_period', '盘后突破参数', '20', 'int', '突破计算周期', 1),
('S2560', 'core_pullback_pct', '盘后回踩参数', '3.0', 'double', '核心回踩百分比', 1),
('S2560', 'pullback_max_pct', '盘后回踩参数', '5.0', 'double', '价格距离关键均线最大百分比', 1),
('S2560', 'recent_3d_normal_max', '盘后起爆段参数', '12.0', 'double', '近3日普通状态最大涨幅', 1),
('S2560', 'recent_3d_warm_max', '盘后起爆段参数', '18.0', 'double', '近3日温热状态最大涨幅', 1),
('S2560', 'recent_3d_acceleration_max', '盘后起爆段参数', '20.0', 'double', '近3日加速状态最大涨幅', 1),
('S2560', 'recent_3d_overheat_min', '盘后起爆段参数', '20.0', 'double', '近3日过热状态最小涨幅', 1),
('S2560', 'high_window_30m', '盘后30m参数', '20', 'int', '30m压力位窗口', 1),
('S2560', 'confirm_5m_bars', '盘后5m参数', '6', 'int', '5m确认K线数量', 1),
('S2560', 'volume_cross_fallback_enabled', '盘后量能参数', 'true', 'bool', '启用量能金叉回退确认', 1),
('S2560', 'volume_cross_confirm_ratio', '盘后量能参数', '0.9', 'double', '量能金叉确认比例', 1),
('S2560', 'market_state_enabled', '盘后市场状态参数', 'true', 'bool', '启用市场状态过滤', 1),
('S2560', 'rebound_index_pct_min', '盘后市场状态参数', '0.5', 'double', '反弹环境指数涨幅下限', 1),
('S2560', 'rebound_limitup_min', '盘后市场状态参数', '30', 'int', '反弹环境涨停家数下限', 1),
('S2560', 'rebound_up_ratio_min', '盘后市场状态参数', '0.6', 'double', '反弹环境上涨比例下限', 1),
('S2560', 'hot_topic_required', '盘后热点参数', 'true', 'bool', '要求热点题材匹配', 1),
('S2560', 'hot_topic_strength_required', '盘后热点参数', 'medium', 'string', '要求热点强度下限', 1),
('S2560', 'position_required_for_focus', '盘后热点参数', 'strong', 'string', 'focus要求题材地位下限', 1),
('S2560', 'auction_amplify_ratio', '早盘竞价参数', '1.0', 'double', '集合竞价放量确认比例', 1),
('S2560', 'auction_gap_pct_max', '早盘竞价参数', '3.0', 'double', '集合竞价高开谨慎阈值', 1),
('S2560', 'auction_fallback_to_avg5', '早盘竞价参数', 'true', 'bool', '昨日竞价缺失时允许使用avg5兜底', 1),
('S2560', 'avg5_min_valid_days', '早盘竞价参数', '3', 'int', 'avg5竞价量最少有效天数', 1),
('S2560', 'display_emoji_enabled', '盘后展示参数', 'false', 'bool', '启用emoji展示', 1);

SELECT 'Tables recreated successfully' AS result;
SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema = 'watchlist_decision_support';

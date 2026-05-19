-- MySQL 表结构重建（空表，无数据）
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

DROP TABLE IF EXISTS technical_indicator;
CREATE TABLE technical_indicator (
  code VARCHAR(20) NOT NULL,
  period VARCHAR(10) NOT NULL,
  date BIGINT NOT NULL,
  source VARCHAR(20) NOT NULL DEFAULT 'vipdoc',
  stock_status VARCHAR(20),
  is_st TINYINT(1) DEFAULT 0,
  ma25 DOUBLE, ma60 DOUBLE, ma200 DOUBLE,
  ma25_slope_3 DOUBLE, ma60_slope_3 DOUBLE,
  atr14 DOUBLE, atr20_avg DOUBLE,
  vol_ma5 DOUBLE, vol_ma60 DOUBLE, vol_ratio DOUBLE,
  vol_ma5_cross_vol_ma60 TINYINT(1) DEFAULT 0,
  price_ma25_deviation_pct DOUBLE,
  high_20 DOUBLE, low_20 DOUBLE, low_30 DOUBLE, resistance_level DOUBLE,
  is_abnormal_bar TINYINT(1) DEFAULT 0,
  data_quality_status VARCHAR(30),
  created_at DATETIME(3), updated_at DATETIME(3),
  PRIMARY KEY (code, period, date, source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

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
  job_type VARCHAR(50),
  priority INT DEFAULT 3,
  status VARCHAR(20) DEFAULT 'pending',
  payload JSON,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME,
  finished_at DATETIME,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_status_priority (status, priority),
  INDEX idx_job_type (job_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS job_execution;
CREATE TABLE job_execution (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  job_type VARCHAR(50),
  status VARCHAR(20),
  batch_id VARCHAR(64),
  progress_current INT,
  progress_total INT,
  success_count INT,
  failed_count INT,
  current_code VARCHAR(30),
  market VARCHAR(20),
  shards INT,
  pid BIGINT,
  log_file TEXT,
  message TEXT,
  cancel_requested_at DATETIME,
  started_at DATETIME,
  finished_at DATETIME,
  updated_at DATETIME,
  INDEX idx_status (status),
  INDEX idx_batch (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS job_task_item;
CREATE TABLE job_task_item (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  job_id BIGINT,
  code VARCHAR(20),
  status VARCHAR(20),
  attempt INT DEFAULT 0,
  error_message TEXT,
  started_at DATETIME,
  finished_at DATETIME,
  INDEX idx_job (job_id, status)
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
('S2560', 'ma_short', '均线参数', '25', 'int', '短期均线周期', 1),
('S2560', 'ma_mid', '均线参数', '60', 'int', '中期均线周期', 1),
('S2560', 'ma_long', '均线参数', '200', 'int', '长期均线周期', 1),
('S2560', 'slope_periods', '斜率参数', '3', 'int', '斜率计算周期数', 1),
('S2560', 'atp_period', 'ATR参数', '14', 'int', 'ATR 计算周期', 1),
('S2560', 'vol_short', '量能参数', '5', 'int', '短期均量周期', 1),
('S2560', 'vol_long', '量能参数', '60', 'int', '长期均量周期', 1),
('S2560', 'high_low_window', '高低点窗口', '20', 'int', '高低点计算窗口', 1);

SELECT 'Tables recreated successfully' AS result;
SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema = 'watchlist_decision_support';

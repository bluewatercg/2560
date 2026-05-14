-- ============================================================
-- 1. 清理数据表（为重新导入日线和 5m 数据做准备）
-- ============================================================
-- 保留 stock_info 和 strategy_config（基础配置表）

TRUNCATE TABLE daily_kline;
TRUNCATE TABLE minute_kline;
TRUNCATE TABLE minute_kline_period;
TRUNCATE TABLE technical_indicator;
TRUNCATE TABLE job_task_item;
TRUNCATE TABLE data_import_file;
TRUNCATE TABLE data_import_batch;
TRUNCATE TABLE job_execution;
TRUNCATE TABLE job_queue;
TRUNCATE TABLE analysis_batch;
TRUNCATE TABLE analysis_job_log;
TRUNCATE TABLE structure_2560_analysis;
TRUNCATE TABLE structure_2560_statistics;
TRUNCATE TABLE structure_2560_tag_detail;
TRUNCATE TABLE stock_calc_status;
TRUNCATE TABLE sync_status;
-- workspace_status 保留四行基础记录，只清空数据列
UPDATE workspace_status SET
    daily_latest=NULL, k5m_latest=NULL, k30m_latest=NULL,
    ind_daily=NULL, ind_5m=NULL, ind_30m=NULL,
    source_daily=NULL, indicators_fresh=0, ready=0,
    missing_json=NULL, status_text='', daily_gap_label='', daily_gap=NULL;
-- 概念标签表保留（不属于导入数据范畴）

-- ============================================================
-- 2. 为所有表和字段添加注释
-- ============================================================

-- --- daily_kline ---
ALTER TABLE daily_kline COMMENT='日线 K 线行情数据';
ALTER TABLE daily_kline MODIFY COLUMN code VARCHAR(20) NOT NULL COMMENT '股票代码';
ALTER TABLE daily_kline MODIFY COLUMN date INT NOT NULL COMMENT '交易日期 YYYYMMDD';
ALTER TABLE daily_kline MODIFY COLUMN `open` DOUBLE COMMENT '开盘价';
ALTER TABLE daily_kline MODIFY COLUMN high DOUBLE COMMENT '最高价';
ALTER TABLE daily_kline MODIFY COLUMN low DOUBLE COMMENT '最低价';
ALTER TABLE daily_kline MODIFY COLUMN `close` DOUBLE COMMENT '收盘价';
ALTER TABLE daily_kline MODIFY COLUMN volume BIGINT COMMENT '成交量(股)';
ALTER TABLE daily_kline MODIFY COLUMN amount DOUBLE COMMENT '成交额(元)';
ALTER TABLE daily_kline MODIFY COLUMN `source` VARCHAR(20) NOT NULL COMMENT '数据源: vipdoc/import';

-- --- minute_kline ---
ALTER TABLE minute_kline COMMENT='分钟 K 线行情数据（未分周期，已废弃，用 minute_kline_period 替代）';
ALTER TABLE minute_kline MODIFY COLUMN code VARCHAR(20) NOT NULL COMMENT '股票代码';
ALTER TABLE minute_kline MODIFY COLUMN date INT NOT NULL COMMENT '交易日期时间 YYYYMMDDHHMMSS';
ALTER TABLE minute_kline MODIFY COLUMN `open` DOUBLE COMMENT '开盘价';
ALTER TABLE minute_kline MODIFY COLUMN high DOUBLE COMMENT '最高价';
ALTER TABLE minute_kline MODIFY COLUMN low DOUBLE COMMENT '最低价';
ALTER TABLE minute_kline MODIFY COLUMN `close` DOUBLE COMMENT '收盘价';
ALTER TABLE minute_kline MODIFY COLUMN volume BIGINT COMMENT '成交量(股)';
ALTER TABLE minute_kline MODIFY COLUMN amount DOUBLE COMMENT '成交额(元)';
ALTER TABLE minute_kline MODIFY COLUMN `source` VARCHAR(20) NOT NULL COMMENT '数据源';

-- --- minute_kline_period ---
ALTER TABLE minute_kline_period COMMENT='分钟 K 线行情数据（按周期分表: 5m/30m/60m）';
ALTER TABLE minute_kline_period MODIFY COLUMN date BIGINT NOT NULL COMMENT '交易日期时间 YYYYMMDDHHMMSS';
ALTER TABLE minute_kline_period MODIFY COLUMN `open` DOUBLE COMMENT '开盘价';
ALTER TABLE minute_kline_period MODIFY COLUMN high DOUBLE COMMENT '最高价';
ALTER TABLE minute_kline_period MODIFY COLUMN low DOUBLE COMMENT '最低价';
ALTER TABLE minute_kline_period MODIFY COLUMN `close` DOUBLE COMMENT '收盘价';
ALTER TABLE minute_kline_period MODIFY COLUMN volume DOUBLE COMMENT '成交量(股)';
ALTER TABLE minute_kline_period MODIFY COLUMN amount DOUBLE COMMENT '成交额(元)';

-- --- technical_indicator ---
ALTER TABLE technical_indicator COMMENT='技术指标计算结果（日线/5m/30m）';
ALTER TABLE technical_indicator MODIFY COLUMN date BIGINT NOT NULL COMMENT '指标日期 YYYYMMDD(HHMMSS)';
ALTER TABLE technical_indicator MODIFY COLUMN ma25 DOUBLE COMMENT 'MA25 均线值';
ALTER TABLE technical_indicator MODIFY COLUMN ma60 DOUBLE COMMENT 'MA60 均线值';
ALTER TABLE technical_indicator MODIFY COLUMN ma200 DOUBLE COMMENT 'MA200 均线值';
ALTER TABLE technical_indicator MODIFY COLUMN atr14 DOUBLE COMMENT 'ATR14 真实波动幅度';
ALTER TABLE technical_indicator MODIFY COLUMN atr20_avg DOUBLE COMMENT 'ATR20 平均值';
ALTER TABLE technical_indicator MODIFY COLUMN vol_ma5 DOUBLE COMMENT '5 周期均量';
ALTER TABLE technical_indicator MODIFY COLUMN vol_ma60 DOUBLE COMMENT '60 周期均量';
ALTER TABLE technical_indicator MODIFY COLUMN price_ma25_deviation_pct DOUBLE COMMENT '当前价偏离 MA25 百分比';
ALTER TABLE technical_indicator MODIFY COLUMN high_20 DOUBLE COMMENT '过去 20 周期最高价';
ALTER TABLE technical_indicator MODIFY COLUMN low_20 DOUBLE COMMENT '过去 20 周期最低价(前低)';
ALTER TABLE technical_indicator MODIFY COLUMN low_30 DOUBLE COMMENT '过去 30 周期最低价';
ALTER TABLE technical_indicator MODIFY COLUMN resistance_level DOUBLE COMMENT '当前压力位价格';

-- --- job_queue ---
ALTER TABLE job_queue COMMENT='任务队列（job orchestrator 核心表）';
ALTER TABLE job_queue MODIFY COLUMN job_type VARCHAR(50) NOT NULL COMMENT '任务类型: import/run_2560/build_30m/rebuild_indicators';
ALTER TABLE job_queue MODIFY COLUMN strategy_code VARCHAR(20) NOT NULL COMMENT '关联策略编码';
ALTER TABLE job_queue MODIFY COLUMN priority INT NOT NULL COMMENT '优先级(数字越大优先级越高)';
ALTER TABLE job_queue MODIFY COLUMN payload JSON NOT NULL COMMENT '任务参数(JSON)';
ALTER TABLE job_queue MODIFY COLUMN status VARCHAR(20) NOT NULL COMMENT '状态: pending/running/success/failed/cancelled';
ALTER TABLE job_queue MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE job_queue MODIFY COLUMN started_at DATETIME COMMENT '开始执行时间';
ALTER TABLE job_queue MODIFY COLUMN finished_at DATETIME COMMENT '完成时间';
ALTER TABLE job_queue MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';

-- --- job_execution ---
ALTER TABLE job_execution COMMENT='任务执行记录（进度/状态/日志）';
ALTER TABLE job_execution MODIFY COLUMN job_type VARCHAR(50) NOT NULL COMMENT '任务类型';
ALTER TABLE job_execution MODIFY COLUMN strategy_code VARCHAR(32) COMMENT '关联策略编码';
ALTER TABLE job_execution MODIFY COLUMN batch_id VARCHAR(100) COMMENT '关联批次 ID';
ALTER TABLE job_execution MODIFY COLUMN status VARCHAR(20) NOT NULL COMMENT '状态: running/success/failed/cancelled';
ALTER TABLE job_execution MODIFY COLUMN progress_current INT NOT NULL COMMENT '当前进度';
ALTER TABLE job_execution MODIFY COLUMN progress_total INT NOT NULL COMMENT '总进度';
ALTER TABLE job_execution MODIFY COLUMN success_count INT NOT NULL COMMENT '成功数量';
ALTER TABLE job_execution MODIFY COLUMN failed_count INT NOT NULL COMMENT '失败数量';
ALTER TABLE job_execution MODIFY COLUMN current_code VARCHAR(30) COMMENT '当前处理代码';
ALTER TABLE job_execution MODIFY COLUMN market VARCHAR(20) COMMENT '关联市场';
ALTER TABLE job_execution MODIFY COLUMN shards INT COMMENT '分片数量';
ALTER TABLE job_execution MODIFY COLUMN batch_size INT COMMENT '每批次大小';
ALTER TABLE job_execution MODIFY COLUMN log_file VARCHAR(500) COMMENT '日志文件路径';
ALTER TABLE job_execution MODIFY COLUMN pid INT COMMENT '进程 ID';
ALTER TABLE job_execution MODIFY COLUMN cancel_requested_at DATETIME COMMENT '取消请求时间';
ALTER TABLE job_execution MODIFY COLUMN message TEXT COMMENT '执行消息';
ALTER TABLE job_execution MODIFY COLUMN started_at DATETIME NOT NULL COMMENT '开始时间';
ALTER TABLE job_execution MODIFY COLUMN finished_at DATETIME COMMENT '结束时间';
ALTER TABLE job_execution MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';

-- --- job_task_item ---
ALTER TABLE job_task_item COMMENT='任务子项（分片级粒度）';
ALTER TABLE job_task_item MODIFY COLUMN job_id BIGINT NOT NULL COMMENT '关联任务 ID';
ALTER TABLE job_task_item MODIFY COLUMN batch_id VARCHAR(64) COMMENT '关联批次 ID';
ALTER TABLE job_task_item MODIFY COLUMN shard_id INT NOT NULL COMMENT '分片编号';
ALTER TABLE job_task_item MODIFY COLUMN code VARCHAR(30) NOT NULL COMMENT '股票代码';
ALTER TABLE job_task_item MODIFY COLUMN status VARCHAR(20) NOT NULL COMMENT '状态: pending/running/success/failed';
ALTER TABLE job_task_item MODIFY COLUMN retry_count INT NOT NULL COMMENT '重试次数';
ALTER TABLE job_task_item MODIFY COLUMN elapsed_ms INT COMMENT '执行耗时(毫秒)';
ALTER TABLE job_task_item MODIFY COLUMN last_error TEXT COMMENT '最后错误信息';
ALTER TABLE job_task_item MODIFY COLUMN started_at DATETIME COMMENT '开始时间';
ALTER TABLE job_task_item MODIFY COLUMN finished_at DATETIME COMMENT '完成时间';
ALTER TABLE job_task_item MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';

-- --- data_import_batch ---
ALTER TABLE data_import_batch COMMENT '数据导入批次记录';
ALTER TABLE data_import_batch MODIFY COLUMN import_type VARCHAR(50) NOT NULL COMMENT '导入类型: lday/5m/30m';
ALTER TABLE data_import_batch MODIFY COLUMN source_dir VARCHAR(500) COMMENT 'vipdoc 源目录路径';
ALTER TABLE data_import_batch MODIFY COLUMN market VARCHAR(20) COMMENT '市场: sh60/sh68/sz00/sz30/all';
ALTER TABLE data_import_batch MODIFY COLUMN status VARCHAR(20) NOT NULL COMMENT '状态: pending/running/success/failed';
ALTER TABLE data_import_batch MODIFY COLUMN total_files INT NOT NULL COMMENT '文件总数';
ALTER TABLE data_import_batch MODIFY COLUMN success_files INT NOT NULL COMMENT '成功文件数';
ALTER TABLE data_import_batch MODIFY COLUMN failed_files INT NOT NULL COMMENT '失败文件数';
ALTER TABLE data_import_batch MODIFY COLUMN total_rows BIGINT NOT NULL COMMENT '导入总行数';
ALTER TABLE data_import_batch MODIFY COLUMN started_at DATETIME NOT NULL COMMENT '开始时间';
ALTER TABLE data_import_batch MODIFY COLUMN finished_at DATETIME COMMENT '完成时间';
ALTER TABLE data_import_batch MODIFY COLUMN message TEXT COMMENT '批次消息';
ALTER TABLE data_import_batch MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';

-- --- data_import_file ---
ALTER TABLE data_import_file COMMENT '数据导入文件级跟踪';
ALTER TABLE data_import_file MODIFY COLUMN import_batch_id BIGINT NOT NULL COMMENT '关联批次 ID';
ALTER TABLE data_import_file MODIFY COLUMN file_path VARCHAR(700) NOT NULL COMMENT 'vipdoc 文件路径';
ALTER TABLE data_import_file MODIFY COLUMN market VARCHAR(20) COMMENT '市场';
ALTER TABLE data_import_file MODIFY COLUMN status VARCHAR(20) NOT NULL COMMENT '状态: pending/running/success/failed';
ALTER TABLE data_import_file MODIFY COLUMN rows_imported INT NOT NULL COMMENT '导入行数';
ALTER TABLE data_import_file MODIFY COLUMN last_error TEXT COMMENT '最后错误信息';
ALTER TABLE data_import_file MODIFY COLUMN started_at DATETIME COMMENT '开始时间';
ALTER TABLE data_import_file MODIFY COLUMN finished_at DATETIME COMMENT '完成时间';
ALTER TABLE data_import_file MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';

-- --- analysis_batch ---
ALTER TABLE analysis_batch COMMENT '2560 分析批次记录';
ALTER TABLE analysis_batch MODIFY COLUMN batch_id VARCHAR(64) NOT NULL COMMENT '批次唯一 ID';
ALTER TABLE analysis_batch MODIFY COLUMN batch_name VARCHAR(255) COMMENT '批次名称';
ALTER TABLE analysis_batch MODIFY COLUMN run_time DATETIME COMMENT '运行时间';
ALTER TABLE analysis_batch MODIFY COLUMN data_source VARCHAR(100) COMMENT '数据源';
ALTER TABLE analysis_batch MODIFY COLUMN job_id BIGINT COMMENT '关联任务 ID';
ALTER TABLE analysis_batch MODIFY COLUMN strategy_code VARCHAR(32) NOT NULL COMMENT '策略编码';
ALTER TABLE analysis_batch MODIFY COLUMN strategy_version VARCHAR(50) COMMENT '策略版本';
ALTER TABLE analysis_batch MODIFY COLUMN param_snapshot JSON COMMENT '参数快照(JSON)';
ALTER TABLE analysis_batch MODIFY COLUMN market VARCHAR(20) COMMENT '市场';
ALTER TABLE analysis_batch MODIFY COLUMN trade_date DATE COMMENT '目标交易日';
ALTER TABLE analysis_batch MODIFY COLUMN status VARCHAR(20) NOT NULL COMMENT '状态: pending/running/success/failed';
ALTER TABLE analysis_batch MODIFY COLUMN total_count INT NOT NULL COMMENT '标的总数';
ALTER TABLE analysis_batch MODIFY COLUMN success_count INT NOT NULL COMMENT '成功数';
ALTER TABLE analysis_batch MODIFY COLUMN failed_count INT NOT NULL COMMENT '失败数';
ALTER TABLE analysis_batch MODIFY COLUMN started_at DATETIME COMMENT '开始时间';
ALTER TABLE analysis_batch MODIFY COLUMN finished_at DATETIME COMMENT '完成时间';
ALTER TABLE analysis_batch MODIFY COLUMN duration_seconds INT COMMENT '耗时(秒)';
ALTER TABLE analysis_batch MODIFY COLUMN message TEXT COMMENT '批次消息(含信号数等)';
ALTER TABLE analysis_batch MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE analysis_batch MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';

-- --- analysis_job_log ---
ALTER TABLE analysis_job_log COMMENT '分析任务日志';
ALTER TABLE analysis_job_log MODIFY COLUMN batch_id BIGINT NOT NULL COMMENT '关联批次 ID';

-- --- structure_2560_analysis ---
ALTER TABLE structure_2560_analysis COMMENT='2560 结构分析结果（信号+条件判断+分层）';
ALTER TABLE structure_2560_analysis MODIFY COLUMN signal_time BIGINT NOT NULL COMMENT '信号时间戳 YYYYMMDDHHMMSS';
ALTER TABLE structure_2560_analysis MODIFY COLUMN future_return_1d DOUBLE COMMENT '未来 1 日收益率';
ALTER TABLE structure_2560_analysis MODIFY COLUMN future_return_3d DOUBLE COMMENT '未来 3 日收益率';
ALTER TABLE structure_2560_analysis MODIFY COLUMN future_return_5d DOUBLE COMMENT '未来 5 日收益率';
ALTER TABLE structure_2560_analysis MODIFY COLUMN future_max_gain_5d DOUBLE COMMENT '未来 5 日最大涨幅';
ALTER TABLE structure_2560_analysis MODIFY COLUMN future_max_drawdown_5d DOUBLE COMMENT '未来 5 日最大回撤';
ALTER TABLE structure_2560_analysis MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';
ALTER TABLE structure_2560_analysis MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';

-- --- structure_2560_statistics ---
ALTER TABLE structure_2560_statistics COMMENT='2560 分析统计数据（按标签/状态/行业分组）';
ALTER TABLE structure_2560_statistics MODIFY COLUMN avg_return_1d DOUBLE COMMENT '平均 1 日收益率';
ALTER TABLE structure_2560_statistics MODIFY COLUMN avg_return_3d DOUBLE COMMENT '平均 3 日收益率';
ALTER TABLE structure_2560_statistics MODIFY COLUMN avg_return_5d DOUBLE COMMENT '平均 5 日收益率';
ALTER TABLE structure_2560_statistics MODIFY COLUMN win_rate_1d DOUBLE COMMENT '1 日胜率';
ALTER TABLE structure_2560_statistics MODIFY COLUMN win_rate_3d DOUBLE COMMENT '3 日胜率';
ALTER TABLE structure_2560_statistics MODIFY COLUMN win_rate_5d DOUBLE COMMENT '5 日胜率';
ALTER TABLE structure_2560_statistics MODIFY COLUMN avg_max_gain_5d DOUBLE COMMENT '平均最大涨幅(5日)';
ALTER TABLE structure_2560_statistics MODIFY COLUMN avg_max_drawdown_5d DOUBLE COMMENT '平均最大回撤(5日)';
ALTER TABLE structure_2560_statistics MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';

-- --- structure_2560_tag_detail ---
ALTER TABLE structure_2560_tag_detail COMMENT='2560 信号标签明细';
ALTER TABLE structure_2560_tag_detail MODIFY COLUMN signal_time BIGINT NOT NULL COMMENT '信号时间戳';

-- --- stock_calc_status ---
ALTER TABLE stock_calc_status COMMENT='个股计算状态跟踪（增量计算用）';
ALTER TABLE stock_calc_status MODIFY COLUMN code VARCHAR(30) NOT NULL COMMENT '股票代码';
ALTER TABLE stock_calc_status MODIFY COLUMN strategy_code VARCHAR(32) NOT NULL COMMENT '策略编码';
ALTER TABLE stock_calc_status MODIFY COLUMN last_job_id BIGINT COMMENT '最后一次任务 ID';
ALTER TABLE stock_calc_status MODIFY COLUMN last_batch_id VARCHAR(64) COMMENT '最后一次批次 ID';
ALTER TABLE stock_calc_status MODIFY COLUMN last_trade_date DATE COMMENT '最后计算交易日';
ALTER TABLE stock_calc_status MODIFY COLUMN last_calculated_at DATETIME COMMENT '最后计算时间';
ALTER TABLE stock_calc_status MODIFY COLUMN last_signal_at DATETIME COMMENT '最后信号时间';
ALTER TABLE stock_calc_status MODIFY COLUMN last_indicator_at DATETIME COMMENT '最后指标更新时间';
ALTER TABLE stock_calc_status MODIFY COLUMN last_import_at DATETIME COMMENT '最后导入时间';
ALTER TABLE stock_calc_status MODIFY COLUMN last_status VARCHAR(20) COMMENT '最后状态';
ALTER TABLE stock_calc_status MODIFY COLUMN last_error TEXT COMMENT '最后错误信息';
ALTER TABLE stock_calc_status MODIFY COLUMN updated_at DATETIME NOT NULL COMMENT '更新时间';

-- --- stock_info ---
ALTER TABLE stock_info COMMENT='股票基础信息表';
ALTER TABLE stock_info MODIFY COLUMN code VARCHAR(20) NOT NULL COMMENT '股票代码';
ALTER TABLE stock_info MODIFY COLUMN name VARCHAR(100) COMMENT '股票名称';
ALTER TABLE stock_info MODIFY COLUMN market VARCHAR(20) COMMENT '市场: sh60/sh68/sz00/sz30';
ALTER TABLE stock_info MODIFY COLUMN code_type VARCHAR(20) COMMENT '股票类型';
ALTER TABLE stock_info MODIFY COLUMN source VARCHAR(20) COMMENT '数据源';
ALTER TABLE stock_info MODIFY COLUMN record_count INT COMMENT '行情记录数';
ALTER TABLE stock_info MODIFY COLUMN first_date INT COMMENT '最早日期';
ALTER TABLE stock_info MODIFY COLUMN last_date INT COMMENT '最新日期';
ALTER TABLE stock_info MODIFY COLUMN updated_at DATETIME(3) COMMENT '更新时间';
ALTER TABLE stock_info MODIFY COLUMN industry_code VARCHAR(20) COMMENT '行业编码';
ALTER TABLE stock_info MODIFY COLUMN industry_name VARCHAR(100) COMMENT '行业名称';
ALTER TABLE stock_info MODIFY COLUMN region_code VARCHAR(20) COMMENT '地区编码';
ALTER TABLE stock_info MODIFY COLUMN region_name VARCHAR(100) COMMENT '地区名称';
ALTER TABLE stock_info MODIFY COLUMN board_code VARCHAR(20) COMMENT '板块编码';
ALTER TABLE stock_info MODIFY COLUMN board_name VARCHAR(100) COMMENT '板块名称';
ALTER TABLE stock_info MODIFY COLUMN total_shares DOUBLE COMMENT '总股本';
ALTER TABLE stock_info MODIFY COLUMN circulating_shares DOUBLE COMMENT '流通股本';
ALTER TABLE stock_info MODIFY COLUMN total_assets DOUBLE COMMENT '总资产';
ALTER TABLE stock_info MODIFY COLUMN net_assets DOUBLE COMMENT '净资产';
ALTER TABLE stock_info MODIFY COLUMN net_profit DOUBLE COMMENT '净利润';
ALTER TABLE stock_info MODIFY COLUMN main_profit DOUBLE COMMENT '主营业务利润';
ALTER TABLE stock_info MODIFY COLUMN revenue DOUBLE COMMENT '营业收入';
ALTER TABLE stock_info MODIFY COLUMN eps_adjusted DOUBLE COMMENT '每股收益(调整后)';
ALTER TABLE stock_info MODIFY COLUMN list_date VARCHAR(20) COMMENT '上市日期';

-- --- strategy_config ---
ALTER TABLE strategy_config COMMENT='策略配置参数表';

-- --- concept_tags ---
ALTER TABLE concept_tags COMMENT='概念板块标签映射';
ALTER TABLE concept_tags MODIFY COLUMN code VARCHAR(20) NOT NULL COMMENT '股票代码';
ALTER TABLE concept_tags MODIFY COLUMN concept_code VARCHAR(20) NOT NULL COMMENT '概念编码';
ALTER TABLE concept_tags MODIFY COLUMN concept_name VARCHAR(100) COMMENT '概念名称';

-- --- data_quality_check ---
ALTER TABLE data_quality_check COMMENT='数据质量检查记录';
ALTER TABLE data_quality_check MODIFY COLUMN created_at DATETIME NOT NULL COMMENT '创建时间';

-- --- sync_status ---
ALTER TABLE sync_status COMMENT='外部数据源同步状态';
ALTER TABLE sync_status MODIFY COLUMN source VARCHAR(20) NOT NULL COMMENT '数据源';
ALTER TABLE sync_status MODIFY COLUMN last_sync VARCHAR(50) COMMENT '最后同步时间';
ALTER TABLE sync_status MODIFY COLUMN record_count INT COMMENT '同步记录数';
ALTER TABLE sync_status MODIFY COLUMN status VARCHAR(20) COMMENT '状态';

-- --- workspace_status ---
ALTER TABLE workspace_status COMMENT='工作区数据就绪状态（预计算 4 市场行）';
ALTER TABLE workspace_status MODIFY COLUMN market VARCHAR(10) NOT NULL COMMENT '市场: sh60/sh68/sz00/sz30';
ALTER TABLE workspace_status MODIFY COLUMN k5m_latest BIGINT COMMENT '5m K 线最新日期 YYYYMMDDHHMMSS';
ALTER TABLE workspace_status MODIFY COLUMN k30m_latest BIGINT COMMENT '30m K 线最新日期';
ALTER TABLE workspace_status MODIFY COLUMN ind_5m BIGINT COMMENT '5m 指标最新日期';
ALTER TABLE workspace_status MODIFY COLUMN ind_30m BIGINT COMMENT '30m 指标最新日期';
ALTER TABLE workspace_status MODIFY COLUMN indicators_fresh TINYINT(1) COMMENT '指标是否已最新(0/1)';
ALTER TABLE workspace_status MODIFY COLUMN ready TINYINT(1) COMMENT '工作区是否就绪(0/1)';
ALTER TABLE workspace_status MODIFY COLUMN missing_json JSON COMMENT '缺失数据类型列表(JSON)';
ALTER TABLE workspace_status MODIFY COLUMN status_text VARCHAR(50) COMMENT '状态文字';
ALTER TABLE workspace_status MODIFY COLUMN daily_gap_label VARCHAR(20) COMMENT '日线 gap 标签';
ALTER TABLE workspace_status MODIFY COLUMN daily_gap INT COMMENT '日线 gap 天数';
ALTER TABLE workspace_status MODIFY COLUMN updated_at DATETIME COMMENT '更新时间';

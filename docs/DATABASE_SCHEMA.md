# 数据库表结构设计

> **数据库:** `watchlist_decision_support` @ `192.168.1.254:3306`
> **字符集:** utf8mb4
> **更新日期:** 2026-05-19
> **表数量:** 21（MySQL）+ 3（ClickHouse）

---

## 表分类

| 分类 | 表 | 说明 |
|------|-----|------|
| **行情数据** | `daily_kline` | 日线 K 线 |
| | `minute_kline` | 分钟 K 线（未分周期，已废弃） |
| | `minute_kline_period` | 分钟 K 线（按周期: 5m/30m/60m） |
| **技术指标** | `technical_indicator` | 技术指标（日线/5m/30m） |
| **股票基础** | `stock_info` | 股票基础信息 |
| | `concept_tags` | 概念板块标签映射 |
| **策略配置** | `strategy_config` | 策略参数配置 |
| **2560 分析** | `structure_2560_analysis` | 2560 结构分析结果 |
| | `structure_2560_tag_detail` | 2560 信号标签明细 |
| | `structure_2560_statistics` | 2560 统计数据 |
| | `analysis_batch` | 分析批次记录 |
| | `analysis_job_log` | 分析任务日志 |
| **任务队列** | `job_queue` | 任务队列 |
| | `job_execution` | 任务执行记录 |
| | `job_task_item` | 任务子项（分片级） |
| **数据导入** | `data_import_batch` | 导入批次 |
| | `data_import_file` | 导入文件跟踪 |
| **工作区** | `workspace_status` | 工作区就绪状态（4 行预计算表） |
| **状态跟踪** | `stock_calc_status` | 个股计算状态 |
| | `sync_status` | 外部数据源同步状态 |
| | `data_quality_check` | 数据质量检查 |

---

## 1. daily_kline — 日线 K 线行情数据

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| code | VARCHAR(20) | PK | 股票代码 |
| date | INT | PK | 交易日期 YYYYMMDD |
| source | VARCHAR(20) | PK | 数据源: vipdoc/import |
| open | DOUBLE | | 开盘价 |
| high | DOUBLE | | 最高价 |
| low | DOUBLE | | 最低价 |
| close | DOUBLE | | 收盘价 |
| volume | BIGINT | | 成交量(股) |
| amount | DOUBLE | | 成交额(元) |

**复合主键:** `(code, date, source)`

---

## 2. minute_kline — 分钟 K 线（已废弃）

> 已被 `minute_kline_period` 替代，保留用于兼容。

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| code | VARCHAR(20) | PK | 股票代码 |
| date | INT | PK | 交易日期时间 YYYYMMDDHHMMSS |
| source | VARCHAR(20) | PK | 数据源 |
| open | DOUBLE | | 开盘价 |
| high | DOUBLE | | 最高价 |
| low | DOUBLE | | 最低价 |
| close | DOUBLE | | 收盘价 |
| volume | BIGINT | | 成交量(股) |
| amount | DOUBLE | | 成交额(元) |

**复合主键:** `(code, date, source)`

---

## 3. minute_kline_period — 分钟 K 线（按周期）

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| code | VARCHAR(20) | PK | 股票代码 |
| date | **BIGINT** | PK | 交易日期时间 YYYYMMDDHHMMSS |
| period | VARCHAR(10) | PK | 周期: 5m, 30m, 60m |
| source | VARCHAR(20) | PK | 数据源 |
| open | DOUBLE | | 开盘价 |
| high | DOUBLE | | 最高价 |
| low | DOUBLE | | 最低价 |
| close | DOUBLE | | 收盘价 |
| volume | DOUBLE | | 成交量(股) |
| amount | DOUBLE | | 成交额(元) |

**复合主键:** `(code, date, period, source)`

> **注意:** `date` 使用 BIGINT，因为 `YYYYMMDDHHMMSS` 格式值 `20260512150000` 超出 INT 范围(~21亿)。

---

## 4. technical_indicator — 技术指标计算结果

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| code | VARCHAR(20) | PK | 股票代码 |
| period | VARCHAR(10) | PK | 周期: daily/5m/30m |
| date | BIGINT | PK | 指标日期 YYYYMMDD(HHMMSS) |
| source | VARCHAR(20) | PK | 数据源 |
| stock_status | VARCHAR(20) | | 状态: NORMAL/ST/*ST/SUSPENDED |
| is_st | TINYINT(1) | | 是否 ST |
| ma25 | DOUBLE | | MA25 均线值 |
| ma60 | DOUBLE | | MA60 均线值 |
| ma200 | DOUBLE | | MA200 均线值 |
| ma25_slope_3 | DOUBLE | | MA25 近 3 周期百分比斜率(%) |
| ma60_slope_3 | DOUBLE | | MA60 近 3 周期百分比斜率(%) |
| atr14 | DOUBLE | | ATR14 真实波动幅度 |
| atr20_avg | DOUBLE | | ATR20 平均值 |
| vol_ma5 | DOUBLE | | 5 周期均量 |
| vol_ma60 | DOUBLE | | 60 周期均量 |
| vol_ratio | DOUBLE | | vol_ma5 / vol_ma60 量比 |
| vol_ma5_cross_vol_ma60 | TINYINT(1) | | 近期是否量金叉 |
| price_ma25_deviation_pct | DOUBLE | | 当前价偏离 MA25 百分比 |
| high_20 | DOUBLE | | 过去 20 周期最高价 |
| low_20 | DOUBLE | | 过去 20 周期最低价(前低) |
| low_30 | DOUBLE | | 过去 30 周期最低价 |
| resistance_level | DOUBLE | | 当前压力位价格 |
| is_abnormal_bar | TINYINT(1) | | 是否异常 K 线 |
| data_quality_status | VARCHAR(30) | | normal/missing/abnormal |
| created_at | DATETIME | | 创建时间 |
| updated_at | DATETIME | | 更新时间 |

**复合主键:** `(code, period, date, source)`

---

## 5. stock_info — 股票基础信息

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| code | VARCHAR(20) | PK | 股票代码 |
| name | VARCHAR(100) | | 股票名称 |
| market | VARCHAR(20) | | 市场: sh60/sh68/sz00/sz30 |
| code_type | VARCHAR(20) | | 股票类型 |
| source | VARCHAR(20) | | 数据源 |
| record_count | INT | | 行情记录数 |
| first_date | INT | | 最早日期 |
| last_date | INT | | 最新日期 |
| updated_at | DATETIME(3) | | 更新时间 |
| industry_code | VARCHAR(20) | | 行业编码 |
| industry_name | VARCHAR(100) | | 行业名称 |
| region_code | VARCHAR(20) | | 地区编码 |
| region_name | VARCHAR(100) | | 地区名称 |
| board_code | VARCHAR(20) | | 板块编码 |
| board_name | VARCHAR(100) | | 板块名称 |
| total_shares | DOUBLE | | 总股本 |
| circulating_shares | DOUBLE | | 流通股本 |
| total_assets | DOUBLE | | 总资产 |
| net_assets | DOUBLE | | 净资产 |
| net_profit | DOUBLE | | 净利润 |
| main_profit | DOUBLE | | 主营业务利润 |
| revenue | DOUBLE | | 营业收入 |
| eps_adjusted | DOUBLE | | 每股收益(调整后) |
| list_date | VARCHAR(20) | | 上市日期 |

---

## 6. strategy_config — 策略配置参数

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| strategy_code | VARCHAR(30) | PK | 策略编码 |
| config_key | VARCHAR(100) | PK | 参数名 |
| config_group | VARCHAR(50) | IDX | 参数分组 |
| config_value | VARCHAR(100) | | 参数值 |
| value_type | VARCHAR(20) | | int / double / string / bool |
| description | VARCHAR(500) | | 说明 |
| enabled | TINYINT(1) | | 是否启用 |
| updated_at | DATETIME | | 更新时间 |

**复合主键:** `(strategy_code, config_key)`

---

## 7. concept_tags — 概念板块标签映射

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| code | VARCHAR(20) | PK | 股票代码 |
| concept_code | VARCHAR(20) | PK | 概念编码 |
| concept_name | VARCHAR(100) | | 概念名称 |

**复合主键:** `(code, concept_code)`

---

## 8. structure_2560_analysis — 2560 结构分析结果

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| signal_uid | VARCHAR(32) | UNIQUE | 唯一防重 ID: MD5(code+signal_time+signal_period) |
| batch_id | VARCHAR(64) | IDX | 批次 ID |
| strategy_code | VARCHAR(30) | | 策略编码 |
| strategy_version | VARCHAR(30) | | 策略版本 |
| code | VARCHAR(20) | IDX | 股票代码 |
| name | VARCHAR(100) | | 股票名称 |
| signal_time | BIGINT | IDX | 信号时间戳 YYYYMMDDHHMMSS |
| signal_period | VARCHAR(10) | | 信号周期 |
| price | DOUBLE | | 信号价 |
| source | VARCHAR(20) | | 数据源 |
| stock_status | VARCHAR(20) | | 股票状态 |
| **条件判断字段** | | | |
| has_2560_signal | TINYINT(1) | | 是否有 2560 信号 |
| price_near_ma25 | TINYINT(1) | | 价格贴 MA25 |
| ma25_slope_ok | TINYINT(1) | | MA25 向上 |
| volume_structure_ok | TINYINT(1) | | 量能结构 OK |
| abnormal_filter_ok | TINYINT(1) | | 非异常 K 线 |
| trend_price_ok | TINYINT(1) | | 趋势价格 |
| trend_slope_ok | TINYINT(1) | | 趋势斜率 |
| volatility_ok | TINYINT(1) | | 波动率 |
| breakout_ok | TINYINT(1) | | 突破 |
| volume_ok | TINYINT(1) | | 量能 |
| near_resistance | TINYINT(1) | | 接近压力位 |
| pullback_ok | TINYINT(1) | | 回踩 |
| bullish_confirm | TINYINT(1) | | 多头确认 |
| structure_status | VARCHAR(20) | | 结构状态: 完整/部分/缺失/不足 |
| strength_score_raw | DOUBLE | | 强度计算原始分数 |
| missing_tags | VARCHAR(500) | | 缺失标签 |
| missing_tag_count | INT | | 缺失标签数量 |
| explain_text | VARCHAR(1000) | | 自动解释文本 |
| data_quality_status | VARCHAR(30) | | normal/missing/abnormal |
| is_duplicate_signal | TINYINT(1) | | 是否重复信号 |
| selected_signal | TINYINT(1) | | 去重后是否保留 |
| **回测字段** | | | |
| future_return_1d | DOUBLE | | 未来 1 日收益率 |
| future_return_3d | DOUBLE | | 未来 3 日收益率 |
| future_return_5d | DOUBLE | | 未来 5 日收益率 |
| future_max_gain_5d | DOUBLE | | 未来 5 日最大涨幅 |
| future_max_drawdown_5d | DOUBLE | | 未来 5 日最大回撤 |
| created_at | DATETIME | | 创建时间 |
| updated_at | DATETIME | | 更新时间 |

---

## 9. structure_2560_tag_detail — 2560 信号标签明细

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| analysis_id | BIGINT | IDX | 对应主表 ID |
| batch_id | VARCHAR(64) | IDX | 批次 ID |
| code | VARCHAR(20) | | 股票代码 |
| signal_time | BIGINT | | 信号时间戳 |
| tag_code | VARCHAR(50) | IDX | 标签编码 |
| tag_name | VARCHAR(100) | | 标签名称 |
| tag_type | VARCHAR(50) | | negative/positive/system |
| created_at | DATETIME | | 创建时间 |

---

## 10. structure_2560_statistics — 2560 统计数据

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| batch_id | VARCHAR(64) | IDX | 批次 ID |
| stat_date | INT | | 统计日期 |
| stat_type | VARCHAR(50) | | 统计类型: BY_TAG/BY_STATUS/BY_INDUSTRY |
| group_key | VARCHAR(100) | | 分组键 |
| sample_count | INT | | 样本数 |
| avg_return_1d | DOUBLE | | 平均 1 日收益率 |
| avg_return_3d | DOUBLE | | 平均 3 日收益率 |
| avg_return_5d | DOUBLE | | 平均 5 日收益率 |
| win_rate_1d | DOUBLE | | 1 日胜率 |
| win_rate_3d | DOUBLE | | 3 日胜率 |
| win_rate_5d | DOUBLE | | 5 日胜率 |
| avg_max_gain_5d | DOUBLE | | 平均最大涨幅(5 日) |
| avg_max_drawdown_5d | DOUBLE | | 平均最大回撤(5 日) |
| created_at | DATETIME | | 创建时间 |

---

## 11. analysis_batch — 2560 分析批次记录

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| batch_id | VARCHAR(64) | PK | 批次唯一 ID |
| batch_name | VARCHAR(255) | | 批次名称 |
| run_time | DATETIME | | 运行时间 |
| data_source | VARCHAR(100) | | 数据源 |
| job_id | BIGINT | IDX | 关联任务 ID |
| strategy_code | VARCHAR(32) | IDX | 策略编码 |
| strategy_version | VARCHAR(50) | | 策略版本 |
| param_snapshot | JSON | | 参数快照 |
| market | VARCHAR(20) | | 市场 |
| trade_date | DATE | | 目标交易日 |
| status | VARCHAR(20) | IDX | pending/running/success/failed |
| total_count | INT | | 标的总数 |
| success_count | INT | | 成功数 |
| failed_count | INT | | 失败数 |
| started_at | DATETIME | | 开始时间 |
| finished_at | DATETIME | | 完成时间 |
| duration_seconds | INT | | 耗时(秒) |
| message | TEXT | | 批次消息(含信号数) |
| created_at | DATETIME | | 创建时间 |
| updated_at | DATETIME | | 更新时间 |

---

## 12. analysis_job_log — 分析任务日志

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| batch_id | BIGINT | IDX | 关联批次 ID |
| job_name | VARCHAR(100) | | 任务名称 |
| step_name | VARCHAR(100) | | 步骤名称 |
| status | VARCHAR(20) | | success/failed/running |
| message | TEXT | | 日志说明 |
| started_at | DATETIME | | 开始时间 |
| finished_at | DATETIME | | 完成时间 |

---

## 13. job_queue — 任务队列

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| job_type | VARCHAR(50) | | 任务类型: import/run_2560/build_30m/rebuild_indicators |
| strategy_code | VARCHAR(20) | IDX | 关联策略编码 |
| priority | INT | | 优先级(数字越大优先级越高) |
| payload | JSON | | 任务参数 |
| status | VARCHAR(20) | IDX | pending/running/success/failed/cancelled |
| created_at | DATETIME | | 创建时间 |
| started_at | DATETIME | | 开始执行时间 |
| finished_at | DATETIME | | 完成时间 |
| updated_at | DATETIME | | 更新时间 |

---

## 14. job_execution — 任务执行记录

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| job_type | VARCHAR(50) | | 任务类型 |
| strategy_code | VARCHAR(32) | | 关联策略编码 |
| batch_id | VARCHAR(100) | | 关联批次 ID |
| status | VARCHAR(20) | IDX | running/success/failed/cancelled |
| progress_current | INT | | 当前进度 |
| progress_total | INT | | 总进度 |
| success_count | INT | | 成功数量 |
| failed_count | INT | | 失败数量 |
| current_code | VARCHAR(30) | | 当前处理代码 |
| market | VARCHAR(20) | | 关联市场 |
| shards | INT | | 分片数量 |
| batch_size | INT | | 每批次大小 |
| log_file | VARCHAR(500) | | 日志文件路径 |
| pid | INT | | 进程 ID |
| cancel_requested_at | DATETIME | | 取消请求时间 |
| message | TEXT | | 执行消息 |
| started_at | DATETIME | | 开始时间 |
| finished_at | DATETIME | | 结束时间 |
| updated_at | DATETIME | IDX | 更新时间 |

---

## 15. job_task_item — 任务子项

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| job_id | BIGINT | IDX | 关联任务 ID |
| batch_id | VARCHAR(64) | | 关联批次 ID |
| shard_id | INT | | 分片编号 |
| code | VARCHAR(30) | | 股票代码 |
| status | VARCHAR(20) | | pending/running/success/failed |
| retry_count | INT | | 重试次数 |
| elapsed_ms | INT | | 执行耗时(毫秒) |
| last_error | TEXT | | 最后错误信息 |
| started_at | DATETIME | | 开始时间 |
| finished_at | DATETIME | | 完成时间 |
| updated_at | DATETIME | | 更新时间 |

---

## 16. data_import_batch — 数据导入批次

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| import_type | VARCHAR(50) | | 导入类型: lday/5m/30m |
| source_dir | VARCHAR(500) | | vipdoc 源目录路径 |
| market | VARCHAR(20) | | 市场: sh60/sh68/sz00/sz30/all |
| status | VARCHAR(20) | IDX | pending/queued/running/success/failed/cancelling |
| total_files | INT | | 文件总数 |
| success_files | INT | | 成功文件数 |
| failed_files | INT | | 失败文件数 |
| total_rows | BIGINT | | 导入总行数 |
| started_at | DATETIME | | 开始时间 |
| finished_at | DATETIME | | 完成时间 |
| message | TEXT | | 批次消息 |
| updated_at | DATETIME | | 更新时间 |

---

## 17. data_import_file — 数据导入文件跟踪

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| import_batch_id | BIGINT | IDX | 关联批次 ID |
| file_path | VARCHAR(700) | | vipdoc 文件路径 |
| market | VARCHAR(20) | | 市场 |
| status | VARCHAR(20) | IDX | pending/running/success/failed |
| rows_imported | INT | | 导入行数 |
| last_error | TEXT | | 最后错误信息 |
| started_at | DATETIME | | 开始时间 |
| finished_at | DATETIME | | 完成时间 |
| updated_at | DATETIME | | 更新时间 |

---

## 18. workspace_status — 工作区数据就绪状态

> **关键设计:** 预计算 4 行小表，替代实时 MAX() 聚合。每次数据操作完成后由 runner 脚本刷新。
> 详见 `app/services/workspace_service.py`。

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| market | VARCHAR(10) | PK | 市场: sh60/sh68/sz00/sz30 |
| daily_latest | INT | | 日线最新日期 YYYYMMDD |
| k5m_latest | BIGINT | | 5m K 线最新日期 YYYYMMDDHHMMSS |
| k30m_latest | BIGINT | | 30m K 线最新日期 |
| ind_daily | INT | | 日线指标最新日期 |
| ind_5m | BIGINT | | 5m 指标最新日期 |
| ind_30m | BIGINT | | 30m 指标最新日期 |
| source_daily | INT | | 源文件日线最新日期 |
| indicators_fresh | TINYINT(1) | | 指标是否已最新(0/1) |
| ready | TINYINT(1) | | 工作区是否就绪(0/1) |
| missing_json | JSON | | 缺失数据类型列表(JSON) |
| status_text | VARCHAR(50) | | 状态文字: 数据不足/指标未更新/可跑2560 |
| daily_gap_label | VARCHAR(20) | | 日线 gap 标签 |
| daily_gap | INT | | 日线 gap 天数 |
| updated_at | DATETIME | | 更新时间 |

**ready 计算逻辑:** `有 daily + 5m + 30m 数据 AND indicators_fresh = 1`
**indicators_fresh 计算逻辑:** 每个周期的指标日期 >= 对应 K 线日期

### Runner 刷新映射

| Runner | 刷新列 |
|--------|--------|
| `import_job_runner` (lday) | daily + source_daily |
| `import_job_runner` (5m) | k5m |
| `build_30m_job_runner` | k30m |
| `rebuild_indicator_job_runner` | 按 periods 参数刷新对应指标列 |

---

## 19. stock_calc_status — 个股计算状态

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| code | VARCHAR(30) | PK | 股票代码 |
| strategy_code | VARCHAR(32) | PK | 策略编码 |
| last_job_id | BIGINT | IDX | 最后任务 ID |
| last_batch_id | VARCHAR(64) | IDX | 最后批次 ID |
| last_trade_date | DATE | | 最后计算交易日 |
| last_calculated_at | DATETIME | IDX | 最后计算时间 |
| last_signal_at | DATETIME | | 最后信号时间 |
| last_indicator_at | DATETIME | | 最后指标更新时间 |
| last_import_at | DATETIME | | 最后导入时间 |
| last_status | VARCHAR(20) | | 最后状态 |
| last_error | TEXT | | 最后错误信息 |
| updated_at | DATETIME | | 更新时间 |

**复合主键:** `(code, strategy_code)`

---

## 20. sync_status — 外部数据源同步状态

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| source | VARCHAR(20) | PK | 数据源 |
| last_sync | VARCHAR(50) | | 最后同步时间 |
| record_count | INT | | 同步记录数 |
| status | VARCHAR(20) | | 状态 |

---

## 21. data_quality_check — 数据质量检查

| 字段 | 类型 | 键 | 说明 |
|------|------|-----|------|
| id | BIGINT | PK | 主键 |
| check_date | INT | IDX | 检查日期 |
| source | VARCHAR(20) | | 数据源 |
| period | VARCHAR(10) | | daily/5m/30m |
| total_symbols | INT | | 应有标的数 |
| available_symbols | INT | | 实际有数据标的数 |
| missing_symbols | INT | | 缺失标的数 |
| abnormal_bar_count | INT | | 异常 K 线数量 |
| status | VARCHAR(30) | | normal/warning/error |
| created_at | DATETIME | | 创建时间 |

---

## 表关系图

```
stock_info ─┬─> concept_tags (code)
            │
            ├─> daily_kline (code)
            ├─> minute_kline_period (code)
            ├─> technical_indicator (code)
            │
            ├─> structure_2560_analysis (code) ─> structure_2560_tag_detail (analysis_id)
            │                                     └> structure_2560_statistics (batch_id)
            │
            ├─> stock_calc_status (code, strategy_code)
            │
strategy_config ─> analysis_batch (strategy_code)
                      │
                      ├─> job_queue (strategy_code)
                      │     └> job_execution (batch_id)
                      │           └> job_task_item (job_id)
                      │
                      ├─> data_import_batch (job_id)
                      │     └> data_import_file (import_batch_id)
                      │
                      └─> analysis_job_log (batch_id)

workspace_status ←── (独立 4 行预计算表，由 runner 脚本刷新)
```

## 索引清单

| 表 | 索引 | 类型 | 用途 |
|----|------|------|------|
| daily_kline | (code, date, source) | PK | 唯一行 |
| minute_kline_period | (code, date, period, source) | PK | 唯一行 |
| technical_indicator | (code, period, date, source) | PK | 唯一行 |
| structure_2560_analysis | signal_uid | UNIQUE | 防重 |
| structure_2560_analysis | (code, signal_time, batch_id) | IDX | 查询信号 |
| job_queue | (status, strategy_code, created_at) | IDX | 取任务 |
| job_queue | (strategy_code) | IDX | 策略关联 |
| job_execution | (status, updated_at) | IDX | 进度查询 |
| job_task_item | (job_id) | IDX | 子项查询 |
| data_import_file | (import_batch_id) | IDX | 批次文件 |
| data_import_batch | (status) | IDX | 批次状态 |
| analysis_batch | (job_id, strategy_code, status) | IDX | 分析查询 |
| stock_calc_status | (last_job_id, last_batch_id, last_calculated_at) | IDX | 增量计算 |
| structure_2560_tag_detail | (analysis_id, batch_id, tag_code) | IDX | 标签查询 |
| data_quality_check | (check_date) | IDX | 按日期查询 |

---

## ClickHouse 表结构（行情数据）

> **数据库:** `strategy2560` @ `192.168.1.18:8123`
> ClickHouse 仅存储行情数据与技术指标，不存储任务队列、分析结果、配置等业务数据。

### CH-1. daily_kline — 日线 K 线

| 字段 | 类型 | 说明 |
|------|------|------|
| code | String | 股票代码（如 `sh.600000`）|
| date | Date | 交易日期 |
| source | LowCardinality(String) | 数据源，默认 `vipdoc` |
| open | Float64 | 开盘价 |
| high | Float64 | 最高价 |
| low | Float64 | 最低价 |
| close | Float64 | 收盘价 |
| volume | Float64 | 成交量 |
| amount | Float64 | 成交额 |

**引擎:** `MergeTree()`
**排序键:** `(code, date)`
**主键:** `(code, date)`

### CH-2. minute_kline_period — 分钟 K 线（5m/30m/60m 统一存储）

| 字段 | 类型 | 说明 |
|------|------|------|
| code | String | 股票代码 |
| date | DateTime64(0) | K 线时间戳 |
| period | LowCardinality(String) | 周期: `5m` / `30m` / `60m` |
| source | LowCardinality(String) | 数据源，默认 `vipdoc` |
| open | Float64 | 开盘价 |
| high | Float64 | 最高价 |
| low | Float64 | 最低价 |
| close | Float64 | 收盘价 |
| volume | Float64 | 成交量 |
| amount | Float64 | 成交额 |

**引擎:** `MergeTree()`
**排序键:** `(code, period, date)`
**主键:** `(code, period, date)`

### CH-3. technical_indicator — 技术指标

| 字段 | 类型 | 说明 |
|------|------|------|
| code | String | 股票代码 |
| period | LowCardinality(String) | 周期: `daily` / `5m` / `30m` |
| date | Date | 指标日期 |
| source | LowCardinality(String) | 数据源，默认 `vipdoc` |
| stock_status | Nullable(String) | 状态: NORMAL / ST / *ST / SUSPENDED |
| is_st | UInt8 | 是否 ST（0/1）|
| ma25 ~ ma200 | Nullable(Float64) | 均线值 |
| ma25_slope_3 | Nullable(Float64) | MA25 近 3 周期百分比斜率(%) |
| atr14 | Nullable(Float64) | ATR14 |
| atr20_avg | Nullable(Float64) | ATR20 均值 |
| vol_ma5 / vol_ma60 | Nullable(Float64) | 均量 |
| vol_ratio | Nullable(Float64) | 量比 |
| vol_ma5_cross_vol_ma60 | UInt8 | 量金叉标记 |
| price_ma25_deviation_pct | Nullable(Float64) | 价格偏离 MA25 百分比 |
| high_20 / low_20 / low_30 | Nullable(Float64) | 高低点 |
| resistance_level | Nullable(Float64) | 压力位 |
| is_abnormal_bar | UInt8 | 异常 K 线标记 |
| data_quality_status | Nullable(String) | normal / missing / abnormal |

**引擎:** `MergeTree()`
**排序键:** `(code, period, date)`

> **注意:** ClickHouse 的 `technical_indicator` 无 `PRIMARY KEY`（与 MySQL 的复合主键不同），靠 `ORDER BY` 保证查询效率。

---

## 状态枚举速查

### job_queue.status
`pending` → `running` → `success` / `failed` / `cancelled`

### job_execution.status
`running` → `success` / `failed` / `cancelled`

### data_import_batch.status
`pending` → `queued` → `running` → `success` / `failed` / `cancelling`

### job_task_item.status
`pending` → `running` → `success` / `failed`

### structure_2560_analysis.structure_status
`完整` / `部分` / `缺失` / `不足`

### technical_indicator.data_quality_status
`normal` / `missing` / `abnormal`

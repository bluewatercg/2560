# 数据库架构：双数据库职责分工

> **更新日期:** 2026-05-20
> **架构原则:** ClickHouse 处理高频读写的行情数据（DELETE + INSERT 热路径），MySQL 负责任务管理、分析结果与配置（低频读写的业务数据）。

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        应用层 (FastAPI)                          │
│                                                                 │
│  import  →  build_30m  →  rebuild_indicator  →  run_2560        │
│       │              │                │              │          │
│       ▼              ▼                ▼              ▼          │
│  ┌──────────────────────┐    ┌─────────────────────────────┐    │
│  │   MySQL 业务管理      │    │   ClickHouse 行情数据        │    │
│  │   job / batch /      │    │   daily_kline               │    │
│  │   config / analysis  │    │   minute_kline_period       │    │
│  │   workspace_status   │    │   technical_indicator       │    │
│  └──────────┬───────────┘    └──────────────┬──────────────┘    │
│             │                               │                   │
│  SQLAlchemy │                    get_clickhouse()              │
│  Session    │                    HTTP 接口                     │
└─────────────┼───────────────────────────────┼───────────────────┘
              │                               │
    192.168.1.254:3306              192.168.1.18:8123
    watchlist_decision_support      strategy2560
```

---

## ClickHouse（192.168.1.18）

**职责：** 存储行情 K 线数据与技术指标 —— 数据量大（百万~亿级行）、查询密集、需要频繁 DELETE + INSERT 的场景。

| 表 | 数据量级 | 读写特征 | 说明 |
|----|---------|---------|------|
| `daily_kline` | 百万级 | 批量导入 + 分析读取 | 日线 K 线 |
| `minute_kline_period` | 千万~亿级 | 批量导入 + 分析读取 | 5m / 30m K 线统一存储 |
| `technical_indicator` | 千万~亿级 | 频繁 DELETE + INSERT（重建） | MA / ATR / 量能等技术指标 |

**选型理由：**
- 列式存储，适合全市场扫描的行情分析查询
- `DELETE` 使用 `ALTER TABLE ... DELETE WHERE`（mutation 机制），适合按 code + period 批量清除重建
- `INSERT` 使用 Native JSON 批量写入，性能远高于 MySQL
- 无事务锁，避免了 MySQL 的 deadlock 问题

**不使用 ClickHouse 的原因：**
- 不支持行级事务（不适合 job 状态管理）
- 不支持外键和复杂 JOIN（不适合分析结果的关联查询）
- 不支持 JSON 类型（不适合存储配置快照）

---

## MySQL（192.168.1.254）

**职责：** 负责任务调度、批次管理、分析结果、配置存储、工作区状态 —— 低数据量、需要事务和行级更新的场景。

### 任务调度（job 系统）

| 表 | 说明 |
|----|------|
| `job_queue` | 待执行任务队列 |
| `job_execution` | 正在执行任务的进度（实时 UPDATE） |
| `job_task_item` | 任务子项（分片级进度） |

### 数据导入

| 表 | 说明 |
|----|------|
| `data_import_batch` | 导入批次记录 |
| `data_import_file` | 文件级导入进度 |

### 2560 策略分析结果

| 表 | 说明 |
|----|------|
| `analysis_batch` | 分析批次 |
| `analysis_job_log` | 分析日志 |
| `structure_2560_analysis` | 信号分析结果 |
| `structure_2560_tag_detail` | 信号标签明细 |
| `structure_2560_statistics` | 统计汇总 |

### 基础配置与状态

| 表 | 说明 |
|----|------|
| `stock_info` | 股票基础信息 |
| `concept_tags` | 概念板块标签 |
| `strategy_config` | 策略参数配置 |
| `workspace_status` | 工作区数据就绪状态（仅 4 行预计算表） |
| `stock_calc_status` | 个股计算状态 |
| `sync_status` | 外部数据源同步状态 |

**选型理由：**
- 支持事务，保证 job 状态更新的原子性
- 支持行级 UPDATE（进度每 2 秒更新一次）
- 支持外键和复杂查询（适合分析结果的关联查询）
- JSON 类型适合存储配置快照和标签列表

---

## 数据流向

```
vipdoc 源文件
    │
    ▼
[import_job_runner] ──写入──▶ ClickHouse: daily_kline / minute_kline_period
                           ──写入──▶ MySQL: data_import_batch, data_import_file
    │
    ▼
[build_30m_job_runner] ──读取──▶ ClickHouse: minute_kline_period (5m)
                             ──写入──▶ ClickHouse: minute_kline_period (30m)
                             ──更新──▶ MySQL: data_import_batch, job_execution
    │
    ▼
[rebuild_indicator_job_runner] ──读取──▶ ClickHouse: daily_kline / minute_kline_period
                                    ──写入──▶ ClickHouse: technical_indicator (DELETE + INSERT)
                                    ──更新──▶ MySQL: job_execution
    │
    ▼
[run_2560] ──读取──▶ ClickHouse: daily_kline, technical_indicator
                 ──读取──▶ MySQL: strategy_config, stock_info
                 ──写入──▶ MySQL: structure_2560_analysis, analysis_batch
```

### 边界规则

| 场景 | 存储 | 原因 |
|------|------|------|
| K 线原始数据（导入/查询） | ClickHouse | 数据量大，列式扫描高效 |
| 技术指标（计算/重建） | ClickHouse | 频繁 DELETE + INSERT，MySQL 会 deadlock |
| 任务队列与进度 | MySQL | 需要事务和行级 UPDATE |
| 导入批次与文件进度 | MySQL | 需要事务，与 job 系统关联 |
| 分析结果 | MySQL | 需要关联查询、JSON 字段、外键 |
| 策略配置 | MySQL | 低频读写，需要事务和 JSON |
| 股票基础信息 | MySQL | 低频读写，需要事务 |
| 工作区状态 | MySQL | 仅 4 行，需事务保证原子更新 |

---

## ClickHouse 表结构

> **数据库:** `strategy2560` @ `192.168.1.18:8123`

### CH-1. daily_kline — 日线 K 线

| 字段 | 类型 | 说明 |
|------|------|------|
| code | String | 股票代码（如 `sh.600000`） |
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
| date | DateTime64(3) | 指标时间戳 |
| source | LowCardinality(String) | 数据源，默认 `rebuild` |
| stock_status | Nullable(String) | 状态: NORMAL / ST / *ST / SUSPENDED |
| is_st | Nullable(UInt8) | 是否 ST（0/1） |
| ma25 ~ ma200 | Nullable(Float64) | 均线值 |
| ma25_slope_3 | Nullable(Float64) | MA25 近 3 周期百分比斜率(%) |
| atr14 | Nullable(Float64) | ATR14 |
| atr20_avg | Nullable(Float64) | ATR20 均值 |
| vol_ma5 / vol_ma60 | Nullable(Float64) | 均量 |
| vol_ratio | Nullable(Float64) | 量比 |
| vol_ma5_cross_vol_ma60 | Nullable(UInt8) | 量金叉标记 |
| price_ma25_deviation_pct | Nullable(Float64) | 价格偏离 MA25 百分比 |
| high_20 / low_20 / low_30 | Nullable(Float64) | 高低点 |
| resistance_level | Nullable(Float64) | 压力位 |
| is_abnormal_bar | Nullable(UInt8) | 异常 K 线标记 |
| data_quality_status | Nullable(String) | normal / missing / abnormal |

**引擎:** `MergeTree()`
**排序键:** `(code, period, date, source)`

---

## MySQL 表结构

> **数据库:** `watchlist_decision_support` @ `192.168.1.254:3306`
> **字符集:** utf8mb4

详细表结构见 `sql/recreate_tables.sql` 及各表 DDL。

核心表分类见上方"职责"章节。

---

## 代码层访问方式

| 数据源 | 访问方式 | 入口 |
|--------|---------|------|
| **MySQL** | `from app.db.session import SessionLocal` | `SessionLocal()` 创建 SQLAlchemy Session |
| **ClickHouse** | `from app.db.clickhouse import get_clickhouse` | `get_clickhouse().query(...)` |

### 典型用法

```python
# MySQL：事务 + 行级更新
from app.db.session import SessionLocal
from sqlalchemy.orm import Session

with SessionLocal() as db:
    db.execute(text("UPDATE job_execution SET progress_current = :n WHERE id = :id"),
               {"n": 50, "id": job_id})
    db.commit()

# ClickHouse：分析查询
from app.db.clickhouse import get_clickhouse

ch = get_clickhouse()
rows = ch.query("SELECT code, max(date) AS d FROM daily_kline GROUP BY code")
```

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

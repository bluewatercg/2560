# 第一轮审计结果 - Agent C

## 1. 审计范围

本轮覆盖 schema / config / repository 契约，对照文件：

- `sql/recreate_tables.sql`
- `sql/clickhouse_tables.sql`
- `scripts/apply_2560_v122_schema.py`
- `app/services/config_service.py`
- `app/db/repository.py`
- `app/services/external_call_service.py`
- `app/services/market_state_service.py`
- `app/services/hot_topic_service.py`
- `app/services/auction_volume_service.py`
- `app/services/morning_confirm_engine.py`

## 2. 结论总览

从“表结构是否存在”角度看，v1.2.2 需要的大部分 MySQL / ClickHouse 对象已经进入主建表 SQL 和增量迁移脚本。

但从“契约是否闭环”角度看，当前仍有三类明显缺口：

1. schema 已经扩出来了，但 repository 还没有同步扩成可用的数据访问层。
2. 配置默认值和种子数据大致齐了，但仍缺少部分真正参与运行的阈值键。
3. 部分服务仍停留在纯函数 / Protocol 级别，没有落到真实数据库读写实现。

结论：

- schema 基本进入“可建表”阶段。
- config 进入“半统一”阶段。
- repository 仍明显落后于 schema 和服务设计。

## 3. 目标 vs 当前实现差异表

| 主题 | v1.2.2 目标 | 当前实现 | 结论 |
|---|---|---|---|
| MySQL 新表 | `market_state_daily`、`hot_topic_daily`、`stock_topic_position_daily`、`morning_confirm_daily`、外部调用三表 | 主建表 SQL 和迁移脚本都已包含 | 基本达标 |
| ClickHouse 新字段 | KDJ、MACD、recent gain、`auction_volume` | 主建表 SQL 和迁移脚本都已包含 | 基本达标 |
| skipped 约束 | `chk_skipped_code` + 非空约束语义 | 主建表 SQL 已包含；迁移脚本也会补约束 | 基本达标 |
| 配置体系 | v1.2.2 关键参数全部可审计、可覆盖 | 多数 key 已有，但 `focus_score_min` / `watch_score_min` 缺席 | 未完全达标 |
| repository 能力 | 提供 canonical / market / topic / morning / external governance 读写接口 | 目前主要还是行情读写 + analysis upsert | 明显未达标 |
| 外部调用治理落地 | cache / budget / log 有真实存取实现 | `ExternalCallService` 只有 Protocol，未见 MySQL repository 实现 | 未达标 |
| schema 漂移控制 | 空库建表 SQL 与增量迁移脚本一致 | 大体一致，但能力层没有跟上，仍有逻辑漂移风险 | 部分达标 |

## 4. 具体发现

### 4.1 MySQL 新表已经进入主建表 SQL

`sql/recreate_tables.sql` 已经包含以下 v1.2.2 目标表：

- `market_state_daily` [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:171)
- `hot_topic_daily` [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:188)
- `stock_topic_position_daily` [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:206)
- `morning_confirm_daily` [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:223)
- `external_data_cache` [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:253)
- `external_call_budget` [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:266)
- `external_call_log` [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:275)

结论：

- 从空库初始化视角，这部分已经明显向 v1.2.2 靠拢。

### 4.2 `morning_confirm_daily` 的 skipped 约束已经进入主建表 SQL

`FinalFreeze` 要求 `morning_grade=skipped` 与 `code=__skip__` 双向绑定。

当前主建表 SQL 已有：

- `CONSTRAINT chk_skipped_code CHECK (...)` [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:243)

迁移脚本也会检查并补上该约束 [apply_2560_v122_schema.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/scripts/apply_2560_v122_schema.py:374)。

结论：

- schema 层已经具备这项冻结约束。

### 4.3 ClickHouse 指标表和 `auction_volume` 已覆盖目标字段

`technical_indicator` 已包含：

- `kdj_*`、`macd_*`、`recent_3d_pct`、`recent_5d_pct`
- `ma25_slope_days`、`ma25_angle_deg`、`ma5_slope_dir`

见 [clickhouse_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/clickhouse_tables.sql:61)。

`auction_volume` 也已包含：

- `auction_volume`
- `auction_amount`
- `auction_open_price`
- `prev_close`
- `open_gap_pct`
- `yesterday_auction_volume`
- `avg5_auction_volume`

见 [clickhouse_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/clickhouse_tables.sql:106)。

结论：

- 指标和竞价量基础数据的底层表结构已基本齐备。

### 4.4 增量迁移脚本与主建表 SQL 基本同向，但不是完全闭环

迁移脚本 `scripts/apply_2560_v122_schema.py` 会：

- 创建新 MySQL 表 [apply_2560_v122_schema.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/scripts/apply_2560_v122_schema.py:120)
- 给 `structure_2560_analysis` 增加 canonical 字段 [apply_2560_v122_schema.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/scripts/apply_2560_v122_schema.py:247)
- 追加/修复 `chk_skipped_code` [apply_2560_v122_schema.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/scripts/apply_2560_v122_schema.py:374)
- upsert v1.2.2 配置项 [apply_2560_v122_schema.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/scripts/apply_2560_v122_schema.py:416)
- 创建/修补 ClickHouse `auction_volume` [apply_2560_v122_schema.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/scripts/apply_2560_v122_schema.py:503)

问题不在 SQL 本身，而在能力层：

- 表虽然能建，repository 并没有同步暴露对应的读写接口。

结论：

- schema 与 migration 大体一致。
- schema 与 code access layer 仍未闭环。

### 4.5 `structure_2560_analysis` 的 canonical 字段已贯通到 upsert

`structure_2560_analysis` 中已包含 canonical 字段，例如：

- `selection_status`
- `final_score`
- `recent_3d_pct`
- `explode_status`
- `market_state`
- `hot_topic_strength`
- `position_in_hot_topic`

见 [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:115)。

`KlineRepository.upsert_analysis()` 也已经把这些字段写入 MySQL [repository.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/db/repository.py:121)。

结论：

- analysis 主结果表的 canonical 写入链路已经初步打通。

### 4.6 repository 仍然严重偏向“行情 + analysis”，缺少 v1.2.2 新域接口

`app/db/repository.py` 当前已具备：

- 读日线 / 分钟线 [repository.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/db/repository.py:69)
- 指标写入 / 删除 [repository.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/db/repository.py:94)
- batch 写入 [repository.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/db/repository.py:110)
- analysis / tags 写入 [repository.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/db/repository.py:121)

但没有看到明确的 repository 方法用于：

- `market_state_daily` 读写
- `hot_topic_daily` / `stock_topic_position_daily` 读写
- `morning_confirm_daily` 读写
- `external_data_cache` / `external_call_budget` / `external_call_log` 读写
- `auction_volume` 批量读取/写入

结论：

- 表结构先行了，但 repository 还停留在旧中心模型。
- 这会逼迫新服务绕开统一 repository，后期更难维护。

### 4.7 `ExternalCallService` 只有抽象契约，没有看到真实持久化实现

`ExternalCallService` 已把 TTL、预算和日志语义写清楚：

- TTL hit 判定 [external_call_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/external_call_service.py:167)
- budget 跨日重置 [external_call_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/external_call_service.py:124)
- `invalidate_cache()` 语义 [external_call_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/external_call_service.py:116)

但它依赖的是 `ExternalCallRepository` Protocol [external_call_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/external_call_service.py:20)。

在当前代码中，没有看到一个明确的 MySQL-backed repository 实现去落地：

- `get_cache`
- `upsert_cache`
- `get_budget`
- `upsert_budget`
- `write_log`

结论：

- 外部调用治理规则已设计完成。
- 数据库契约还没有真正接上实现。

### 4.8 market / topic / auction / morning 服务多数还是纯计算层

目前这些服务更多是“业务计算函数”：

- `market_state_service.py` 只做分类与打分 [market_state_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/market_state_service.py:32)
- `hot_topic_service.py` 只做强度与位置判定 [hot_topic_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/hot_topic_service.py:20)
- `auction_volume_service.py` 只做 avg5 计算 [auction_volume_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/auction_volume_service.py:12)
- `morning_confirm_engine.py` 只做行构造与 grade 判定 [morning_confirm_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/morning_confirm_engine.py:22)

结论：

- 算法层已经存在。
- “从表里读、写回表里”的仓储层和 orchestration 层还不完整。

### 4.9 配置体系缺少 `focus_score_min` / `watch_score_min`

`config_service.DEFAULT_CONFIG` 已包含很多 v1.2.2 配置项，如：

- `pullback_max_pct`
- `volume_cross_confirm_ratio`
- `hot_topic_required`
- `position_required_for_focus`
- `auction_fallback_to_avg5`
- `avg5_min_valid_days`

见 [config_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/config_service.py:15)。

但没有看到：

- `focus_score_min`
- `watch_score_min`

同时主建表 SQL 的配置种子也没有这两个 key [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:470)，迁移脚本的 upsert 配置列表里也没有 [apply_2560_v122_schema.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/scripts/apply_2560_v122_schema.py:416)。

结论：

- 运行时阈值部分仍依赖代码隐式默认值，而不是 DB 可审计配置。

### 4.10 配置兼容映射仍然混合 canonical 与 legacy 语义

`CANONICAL_COMPAT_KEYS` 当前包含：

- `pullback_threshold_pct <- pullback_max_pct`
- `min_volume_ratio <- volume_cross_confirm_ratio`

见 [config_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/config_service.py:64)。

这意味着：

- legacy 调用方继续读老 key
- 但值来自 canonical key

结论：

- 这会让“配置有了”看起来没问题，但真实生效路径并不透明。
- 属于 config contract 层的关键风险。

## 5. schema / config / repository 的 Top 5 风险

1. schema 已齐但 repository 没齐，导致新能力只能散落在服务层
   依据：[repository.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/db/repository.py:49)

2. 外部调用三表已建，但没有看到真实持久化 repository，实现仍停留在 Protocol
   依据：[external_call_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/external_call_service.py:20)

3. `focus_score_min` / `watch_score_min` 缺少 schema/config 种子支撑，实际阈值不可审计
   依据：[config_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/config_service.py:15), [sql/recreate_tables.sql](/mnt/d/Project/Miller/strategy2560_project_v2_engine/sql/recreate_tables.sql:470)

4. config 兼容映射仍在回灌 legacy 语义，可能造成运行口径漂移
   依据：[config_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/config_service.py:64)

5. market / topic / auction / morning 仍以纯计算函数为主，缺少稳定的数据读写编排
   依据：[market_state_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/market_state_service.py:32), [hot_topic_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/hot_topic_service.py:20), [auction_volume_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/auction_volume_service.py:12), [morning_confirm_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/morning_confirm_engine.py:22)

## 6. 建议的后续实现顺序

1. 先补 repository：把 market/topic/morning/external/auction 的读写接口收进统一数据访问层。
2. 把 `ExternalCallService` 接到真实 MySQL repository，实现 cache/budget/log 三表闭环。
3. 把 `focus_score_min` / `watch_score_min` 加入默认配置、种子 SQL 和迁移脚本。
4. 清理 config 兼容映射，区分“legacy 过渡用键”和“canonical 正式键”。
5. 再让 market/topic/auction/morning 服务从“纯计算函数”升级为“带仓储调用的业务服务”。

## 7. 本轮审计结论

Agent C 的结论是：

- 底层表结构已经大幅跟上 v1.2.2。
- 最大短板不是 schema，而是 repository 和配置契约没有完全收口。
- 当前已经具备“继续实现”的基础，但还不具备“无歧义落地 canonical 全链路”的数据访问契约。

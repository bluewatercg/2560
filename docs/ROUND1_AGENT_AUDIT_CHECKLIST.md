# 第一轮代理差异审计清单

## 1. 目的

这份清单用于启动第一轮差异审计，不直接改代码，先把“当前实现是什么”和“目标方案要求什么”分开。

审计输出必须满足：

- 明确指出现状、目标、差异、风险。
- 每条结论都标注依据文件。
- 不做大规模文件迁移。
- 先产出审计，再决定是否进入实现。

## 2. 审计范围

本轮聚焦四条线：

1. canonical 2560 规则线
2. 报告包与工作台入口线
3. schema / config / repository 契约线
4. 测试覆盖与回归风险线

## 3. Agent A：2560 核心规则与引擎差异

### 输入

- `docs/2560短线结构算法统一改造方案_v1.2.2_FinalFreeze.md`
- `docs/BUSINESS_LOGIC_2560.md`
- `docs/BUSINESS_LOGIC_SUMMARY.md`
- `app/services/signal_engine_2560.py`
- `app/services/signal_engine_2560_fast.py`
- `app/services/canonical_signal_engine.py`
- `app/services/indicator_engine.py`
- `app/services/config_service.py`

### 必查项

- slow / fast / canonical 三套入口当前分别承担什么职责。
- `high_20` 是否仍存在“是否包含当前 K”的不一致。
- 5m 确认是否严格使用 `signal_time` 前 6 根。
- canonical 是否已实际成为主执行路径，还是仅部分接入。
- 配置 key 是否仍存在旧 key 与新 key 并存问题。

### 预期输出

- 一份“目标规则 vs 当前实现”差异表。
- 一份“当前最可能导致业务口径不一致”的 Top 5 风险。

## 4. Agent B：报告包、API 与工作台链路

### 输入

- `docs/2560_v1.2.2_报告驱动工作流设计_完整版.md`
- `docs/2560_v1.2.2_产品评估报告与改进点清单_v1.0.md`
- `docs/superpowers/plans/2026-06-09-workspace-report-package-entry.md`
- `app/api/reports.py`
- `app/api/latest.py`
- `app/services/daily_selection_report.py`
- `app/services/report_package_service.py`
- `app/services/morning_report_package_service.py`
- `app/services/morning_confirm_report.py`
- `app/static/index.html`
- `app/static/app.js`
- `app/static/results_workbench.js`
- `app/static/post_workflow.js`

### 必查项

- 报告包 01-10 的目标产物里，当前已经能生成哪些，缺哪些。
- 工作台是否已有报告包入口、状态反馈和结果展示位。
- 页面定位是否仍偏“结果中心”，与“报告驱动 + Skill 输入”目标的差距有多大。
- `daily-selection` 及对外文案是否还保留内部术语或交易化表述。
- 早盘确认报告链路是否已经打通到 UI 或 API。

### 预期输出

- 一份报告产物覆盖矩阵。
- 一份工作台入口缺口清单。
- 一份对外文案风险清单。

## 5. Agent C：Schema、Config、Repository 契约

### 输入

- `docs/DATABASE_SCHEMA.md`
- `sql/recreate_tables.sql`
- `sql/clickhouse_tables.sql`
- `scripts/apply_2560_v122_schema.py`
- `app/services/config_service.py`
- `app/db/repository.py`
- `app/services/external_call_service.py`
- `app/services/auction_volume_service.py`
- `app/services/market_state_service.py`
- `app/services/hot_topic_service.py`
- `app/services/morning_confirm_engine.py`

### 必查项

- MySQL 是否已经具备 `market_state_daily`、`hot_topic_daily`、`stock_topic_position_daily`、`morning_confirm_daily`、外部调用三表。
- ClickHouse 是否已具备 KDJ、MACD、recent gain、auction volume 等字段。
- `config_service` 是否真正以 v1.2.2 配置为主，旧 key 如何处理。
- `repository.py` 是否已提供 canonical / morning / report / external governance 所需读写接口。
- schema 变更脚本与主建表 SQL 是否存在漂移。

### 预期输出

- 一份 schema 契约差异清单。
- 一份 config key 现状与目标映射表。
- 一份 repository 能力缺口表。

## 6. Agent D：测试覆盖与回归风险

### 输入

- `tests/test_canonical_signal_engine.py`
- `tests/test_indicator_engine.py`
- `tests/test_external_call_service.py`
- `tests/test_market_state_service.py`
- `tests/test_hot_topic_service.py`
- `tests/test_morning_confirm_engine.py`
- `tests/test_report_package_service.py`
- `tests/test_reports_api_package.py`
- `tests/test_report_driven_workflow_acceptance.py`
- `tests/test_strategy2560_config_contract.py`
- `tests/test_strategy2560_constants.py`
- `tests/test_strategy2560_forbidden_output.py`
- `tests/test_strategy2560_public_wording.py`
- `tests/test_strategy2560_schema_contracts.py`
- `tests/test_structure_2560_repository_contract.py`

### 必查项

- 每条主线是否已经有契约测试，不只是单元测试。
- 是否已经覆盖 forbidden wording、public wording、schema contract、repository contract。
- morning confirm、external call governance、report package 是否有关键缺口。
- 当前测试命名与计划文档中的测试目标是否一致。
- 哪些高风险模块改动后最需要先跑 focused suite。

### 预期输出

- 一份测试覆盖矩阵。
- 一份高风险回归清单。
- 一份“先跑哪些测试”的最小验证集。

## 7. 控制人汇总模板

所有代理返回后，控制人按下面结构汇总：

1. 当前最严重的 5 个差异
2. 哪些差异只是文档问题，哪些已经是代码/数据契约问题
3. 哪些事项可并行改，哪些必须按顺序改
4. 哪些测试要作为后续每轮改动的准入门槛

## 8. 本轮完成标准

满足以下条件即可视为第一轮审计完成：

- 四条线都有书面差异清单。
- 每条差异都能落到文件依据。
- 已区分“当前实现”与“目标方案”。
- 已形成下一轮可执行的实现优先级，而不是泛泛建议。

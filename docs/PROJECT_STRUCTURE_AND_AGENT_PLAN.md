# 项目结构与代理执行说明

## 1. 文档目的

这份文档用于统一三件事：

1. 说明当前代码目录和主要模块职责。
2. 给出 `docs/` 目录中文档的定位、重叠和使用顺序。
3. 把后续工作拆成适合小组代理执行的计划，而不先做大规模文件迁移。

当前原则：

- 先做结构梳理、说明文档和执行计划。
- 尽量不移动代码文件，避免与现有未提交改动冲突。
- 区分“现状文档”和“目标蓝图文档”，避免规则来源混淆。

## 2. 当前代码结构

### 2.1 顶层目录

| 目录 | 作用 |
|---|---|
| `app/` | FastAPI 服务与前端静态资源 |
| `scripts/` | 数据导入、批处理、部署、修复脚本 |
| `sql/` | MySQL / ClickHouse 建表与重建脚本 |
| `tests/` | pytest 测试，覆盖配置、服务、API、报表和契约 |
| `docs/` | 业务规则、数据库、部署、评估、计划 |
| `reports/` | 按交易日输出的报告包 |

### 2.2 `app/` 结构

| 路径 | 作用 |
|---|---|
| `app/main.py` | FastAPI 入口 |
| `app/api/` | 路由层，负责导入、任务、最新结果、报告、2560/2568 接口 |
| `app/core/` | 配置、市场范围、Redis 等基础能力 |
| `app/db/` | MySQL / ClickHouse 连接与 Repository |
| `app/schemas/` | 通用响应模型 |
| `app/services/` | 核心业务逻辑 |
| `app/static/` | 无构建前端页面与脚本 |

### 2.3 `app/services/` 现状分层

`services/` 是当前复杂度最高的区域，建议按职责理解，而不是按文件名零散阅读。

| 分组 | 文件 | 说明 |
|---|---|---|
| 2560 核心 | `signal_engine_2560.py`, `signal_engine_2560_fast.py`, `canonical_signal_engine.py`, `strategy2560_service.py` | 历史 slow/fast 与 canonical 并存，正在向统一引擎收敛 |
| 规则与契约 | `strategy2560_constants.py`, `strategy2560_contract.py`, `config_service.py` | 常量、配置、输出约束 |
| 指标与环境 | `indicator_engine.py`, `market_state_service.py`, `hot_topic_service.py`, `market_hotspot_service.py`, `auction_volume_service.py` | 指标、市场环境、主线、竞价量等输入 |
| 早盘确认 | `morning_confirm_engine.py`, `morning_confirm_report.py`, `morning_report_package_service.py` | T+1 早盘确认与对应报告 |
| 报告产物 | `daily_selection_report.py`, `report_package_service.py`, `report_2568_pdf.py` | 盘后报告、报告包、PDF 输出 |
| 外部调用治理 | `external_call_service.py`, `announcement_risk_service.py` | 外部数据访问、缓存、预算、公告风险 |
| 任务与运行时 | `job_orchestrator.py`, `job_runtime_store.py`, `workspace_service.py`, `data_freshness_service.py` | 队列、运行时状态、工作台准备度 |
| 其他策略能力 | `annotation_engine_2568.py`, `tag_service.py`, `statistics_engine.py`, `future_return_engine.py` | 2568 标注、标签、统计、回溯 |

### 2.4 `app/static/` 现状

前端是原生 HTML/CSS/JS，无构建步骤。现状特征：

- `index.html` + `app.js` 是主入口。
- 页面脚本以功能拆分，但仍有历史增量文件并存。
- `results_workbench.js`、`post_workflow.js`、`nested_menu_reorg.js` 代表当前“工作台/流程化入口”方向。
- 适合继续做“入口整合”，不适合在这轮文档整理里先做前端文件迁移。

## 3. 当前文档地图

### 3.1 推荐阅读顺序

1. `README.md`
2. 本文档 `docs/PROJECT_STRUCTURE_AND_AGENT_PLAN.md`
3. `docs/2560短线结构算法统一改造方案_v1.2.2_FinalFreeze.md`
4. `docs/2560_v1.2.2_报告驱动工作流设计_完整版.md`
5. `docs/DATABASE_SCHEMA.md` / `docs/DEPLOYMENT.md`
6. `docs/superpowers/plans/*.md`

### 3.2 `docs/` 文件定位分析

| 文档 | 当前定位 | 判断 |
|---|---|---|
| `2560短线结构算法统一改造方案_v1.2.2_FinalFreeze.md` | 业务与工程目标蓝图 | 保留，作为目标规则源 |
| `2560_v1.2.2_报告驱动工作流设计_完整版.md` | 报告包与 Skill 工作流设计 | 保留，作为产品交付形态说明 |
| `2560_v1.2.2_产品评估报告与改进点清单_v1.0.md` | 产品现状评审材料 | 保留，但作为评估记录，不作为主说明 |
| `BUSINESS_LOGIC_2560.md` | 旧版/现状业务逻辑审计 | 保留，但应明确是“现状审计” |
| `BUSINESS_LOGIC_SUMMARY.md` | 旧版/现状逻辑摘要 | 保留，但应明确是“快速审计摘要” |
| `strategy2560-current-rules.md` | 面向人读的简化规则 | 保留，但容易与 Final Freeze 竞争，应降级为“当前口径说明” |
| `DATABASE_SCHEMA.md` | 数据库职责与表结构说明 | 保留 |
| `DEPLOYMENT.md` | 部署说明 | 保留 |
| `CLICKHOUSE_INSTALL.md` | ClickHouse 安装手册 | 保留，偏基础设施 |
| `REFACTORING_ROADMAP.md` | 历史路线图与进度记录 | 保留，作为过程文档 |
| `superpowers/plans/*.md` | 代理执行计划 | 保留，作为执行输入，不作为项目总览 |

### 3.3 当前文档问题

| 问题 | 表现 |
|---|---|
| 规则源混杂 | `FinalFreeze`、`BUSINESS_LOGIC_*`、`current-rules` 都在描述 2560 |
| 受众混杂 | 有的写给开发，有的写给产品，有的写给运维，但入口没分层 |
| 现状与目标混杂 | 一部分文档描述当前实现，一部分描述目标 canonical 方案 |
| 执行文档下沉 | 代理可执行计划已经存在，但没有被主文档清晰引用 |

### 3.4 文档治理结论

- `FinalFreeze` 是唯一的目标规则源。
- `BUSINESS_LOGIC_2560.md` 和 `BUSINESS_LOGIC_SUMMARY.md` 应视为现状审计材料。
- `报告驱动工作流设计_完整版` 是产品与交付设计，不替代代码结构说明。
- `superpowers/plans/*.md` 是代理执行输入，不用于项目概览。
- `project.md` 不再作为主文档体系的一部分。

## 4. 当前代码整理判断

这轮不移动文件，但需要先统一“怎么看代码”：

### 4.1 当前可接受的结构边界

- `api/` 作为入口层继续保留。
- `services/` 继续作为业务层，但阅读和分工时必须按职责分组。
- `scripts/` 保留混合状态，后续可再拆为导入、运维、修复三类。
- `docs/` 先做分层导航，不先做物理归档。

### 4.2 暂不建议立即做的事情

- 不先移动 `app/services/` 文件，否则会放大当前未提交改动冲突。
- 不先批量重命名前端脚本。
- 不先删除旧逻辑文档；应先明确其“历史/审计”属性。
- 不先删除 `project.md`，除非后续专门做清理提交。

## 5. 小组代理执行计划

本节用于安排代理并行工作。目标不是让代理各自随意重构，而是围绕现有代码完成受控整理。

### 5.1 适合并行的工作流

| 代理 | 范围 | 输入文档 | 产出 |
|---|---|---|---|
| Agent A | 2560 核心规则与代码对照 | `FinalFreeze`, `BUSINESS_LOGIC_*`, `app/services/*2560*` | 现状与目标差异清单 |
| Agent B | 报告产物与工作台流程 | `报告驱动工作流设计`, `app/api/reports.py`, `app/services/*report*`, `app/static/*` | 报告链路说明与缺口 |
| Agent C | 数据层与配置契约 | `DATABASE_SCHEMA.md`, `sql/*.sql`, `config_service.py`, `repository.py` | schema/config 契约清单 |
| Agent D | 测试覆盖与回归风险 | `tests/`, 上述关键服务 | 风险点与缺失测试列表 |

### 5.2 建议执行顺序

1. Agent A 先确认 canonical 规则差异。
2. Agent C 同步确认 schema/config 是否支撑目标规则。
3. Agent B 梳理报告包与工作台入口是否对齐。
4. Agent D 最后整合测试缺口，形成回归清单。

### 5.3 每个代理的约束

- 不做大规模文件移动。
- 不修改无关模块。
- 先输出“差异/问题/建议”，再进入实现。
- 所有判断都要标注依据文件。
- 若发现 `FinalFreeze` 与当前实现冲突，以 `FinalFreeze` 为目标，以代码为现状。

### 5.4 可直接派发的现有计划

当前已有两份可直接作为代理实施输入的计划：

| 计划 | 用途 |
|---|---|
| `docs/superpowers/plans/2026-06-09-2560-canonical-refactor.md` | canonical 2560 改造主计划 |
| `docs/superpowers/plans/2026-06-09-workspace-report-package-entry.md` | 工作台新增报告包入口 |

建议做法：

- 对 canonical 规则改造，优先按 `2026-06-09-2560-canonical-refactor.md` 派发。
- 对工作台报告包入口，按 `2026-06-09-workspace-report-package-entry.md` 单独派发。
- 若要继续并行扩展，先补一份“文档治理与命名清理计划”，再分配给新代理。

## 6. 下一步建议

如果后续继续推进，建议按下面顺序执行：

1. 给 `BUSINESS_LOGIC_2560.md`、`BUSINESS_LOGIC_SUMMARY.md`、`strategy2560-current-rules.md` 补上“现状/历史/口径”标签。
2. 让代理完成 canonical、报告包、schema、测试四条线的差异审计。
3. 审计通过后，再做代码级改造，而不是先重排目录。
4. 待核心改造稳定后，再决定是否删除 `project.md` 和归档部分旧文档。

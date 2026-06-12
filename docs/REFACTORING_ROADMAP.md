# 系统重构路线图

> 文档属性：历史过程文档
>
> 用途：记录阶段性重构目标、完成状态和验收进度。
>
> 本文档用于追踪历史推进过程，不作为当前系统总说明，也不替代最新的目标规则或代理执行计划。

> **Created:** 2026-05-13
> **Status:** P0 + P1 已验收通过；P2 #11 已实现且 review findings 已关闭，待完整流程验收；#12/#13 待启动
> **Goal:** 用户每天打开系统后，只需要回答：今天数据齐了吗，缺什么，点哪里补，2560 跑完了吗，最后看哪几只。

---

## 当前判断

P0/P1 已经从“功能实现”推进到“验收通过”。P2 #11 一键盘后流程已实现，review 中发现的问题已经关闭；下一步不再继续放宽功能范围，而是跑完整流程验收。

1. **P0 已验收通过**：#1、#2、#3、#4、#5、#6 以及 P0-R1/R2/R3/R4 均已完成并通过 review。
2. **P1 已验收通过**：#7、#8、#9、#10 已完成；市场修复按钮的日期范围、失败检查、lane enqueue、批次日志降级等 review findings 已关闭。
3. **P2 #11 已实现，待完整流程验收**：一键盘后流程已能根据 readiness 自动跳过/执行步骤，并在导入、构建 30m 后刷新后续计划。

“可执行买点为 0”不等于系统失败。2560 标准买点本来不是每天都有，尤其当市场高位冲刺、快速轮动、个股离 MA25 太远、或缺 30m 右侧确认时，0 命中可能是在避免追高。真正需要报警的是四市场连续多日都 0，且漏斗显示卡在 30m 确认、热点匹配或数据/指标完整性，而不是市场结构本身。

## 已实现

### P0 #1 修复导航切页 bug ✅
- `app.js` 新增 `navigateTo(view)` 统一管理 view 切换、标题更新、active 高亮、手风琴展开
- `nested_menu_reorg.js` 的 `bindNav` 委托给 `window.navigateTo(view)`
- 验收：任意页面来回切换 20 次，标题、内容、active 菜单始终一致

### P0 #5 增加 2560 market lane worker ✅
- `job_worker.py` 支持 `WORKER_MARKET` 环境变量（sh60/sh68/sz00/sz30）
- 取任务使用 `FOR UPDATE SKIP LOCKED`
- 同 market 同一时间只允许一个 active `run_2560`（running / queued / pending）
- `docker-compose.yml` 改为 1 个 data worker + 4 个 market worker
- `jobs.py` 新增 `/api/jobs/run-all-markets` 一键创建 4 个 market 任务
- 同 market 重复提交返回失败提示
- data worker 不消费 `run_2560`，market worker 只消费精确匹配自己的 market，不消费 `market=all`
- 验收：`docker compose ps` 显示 5 个 worker；同 market 不重复跑；4 市场可并行

## 两条主线

### UI 主线：盘后工作流控制台

从"功能按钮集合"改成"今日工作台"：

```
今日工作台
  → 数据准备
  → 2560 计算
  → 今日观察池
  → 报告导出
  → 系统诊断
```

### 执行主线：市场 Lane Worker

从"一个通用 worker"改成"数据准备 worker + 2560 四市场 lane worker"：

| Worker | 职责 |
|--------|------|
| `strategy2560-worker-data` | 负责导入 / 30m / 指标 |
| `strategy2560-worker-sh60` | 只跑 sh60 2560 |
| `strategy2560-worker-sh68` | 只跑 sh68 2560 |
| `strategy2560-worker-sz00` | 只跑 sz00 2560 |
| `strategy2560-worker-sz30` | 只跑 sz30 2560 |

**关键原则：**

- 任务按 `market` 分 lane，worker 只消费自己的 market
- 同一个 market 同一时间只允许一个 `run_2560`
- 共享结果表，补充必要索引
- 取任务使用 `FOR UPDATE SKIP LOCKED`
- UI 一键运行四类时，后台创建 4 个 market 任务
- 逻辑隔离，不拆 4 套数据库

## P0 修复清单

| # | 项目 | 说明 | 验收 |
|---|------|------|------|
| 1 ✅ | 修复导航切页 bug | 统一导航状态管理，避免 app.js / nested_menu_reorg.js / 动态注入脚本重复绑定 click | 任意页面来回切换 20 次，标题、内容、active 菜单始终一致 |
| 2 ✅ | 首页改"今日工作台" | 目标交易日、四市场 readiness、下一步建议、今日观察池摘要；readiness 同时检查 K 线和 technical_indicator 新鲜度 | 用户不看日志也能知道"今天能不能跑、缺什么、下一步点哪里" |
| 3 ✅ | 数据准备拆成四步 | 导入前检查、行情导入、30m 构建、指标重算；左侧子菜单可切到对应步骤 | 每个页面只做一件事 |
| 4 ✅ | 2560 四类一键运行 | UI 选择 sh60/sh68/sz00/sz30，一次点击创建 4 个 market 任务 | 点击一次后生成 4 个任务；每个 market 由对应 worker 消费；同 market 不重复并发 |
| 5 ✅ | 增加 2560 market lane worker | worker 支持 `WORKER_MARKET=sh60/sh68/sz00/sz30`；data worker 不抢跑 2560；market worker 精确匹配 market | worker-sh60 不消费 sz00 / all 任务；4 市场可并行；任务状态独立 |
| 6 ✅ | 今日观察池表格化 | 页面直接回答：看什么、为什么看、持有怎么办、没持有怎么买、什么情况跑；观察池入口已接入统一导航 | 不用再查原始信号表，就能做盘后决策 |

## P0 收口与校准

### P0-R1 Review 阻断项修复 ✅

已修复：

- 今日观察池入口不可达：`observation-pool` 已加入统一导航白名单。
- `worker-data` 抢跑 2560 market lane：无 `WORKER_MARKET` 的 worker 已排除 `run_2560`。
- 同 market 防重只拦 running：已扩展到 running / queued / pending。
- 数据导入子菜单不会切到正确步骤：`data-update` / `data-import-run` / `data-import-batches` 已映射到步骤 1 / 2 / 4。
- 工作台 readiness 对 market / 指标状态判断不准：market 查询改用 `market_sql_where()`，并检查 `technical_indicator` 是否跟上 K 线日期。

验收：

- ✅ P0 #1/#2/#3/#4/#5/#6 的主要用户流程已通过 review 验收。
- ✅ `market=all` 的 `run_2560` 在 UI / API 层禁用或提示，避免生成不会被 lane worker 消费的 pending 任务。

### P0-R2 增加 2560 漏斗诊断 ✅

已实现：

- `/api/strategy/2560/funnel/{market}` — 单市场漏斗诊断端点
- `/api/strategy/2560/funnel-all` — 全市场漏斗聚合
- 工作台集成：对可跑/指标未更新的市场自动计算漏斗摘要
- UI 展示：横向条形图 + 百分比 + 过率 + 最大卡点标注 + 原因标签

漏斗阶段：

| 阶段 | 口径 |
|------|------|
| 总数 | 市场内全部股票 |
| 有数据 | 同时拥有日线 + 30m K线 |
| 有30m指标 | 存在 30m `technical_indicator`；是否最新由 workspace readiness 单独判断 |
| 价格贴MA25 | 偏离 ≤ 阈值 |
| MA25向上 | 斜率 ≥ 0 |
| 量能OK | 量比 ≥ 阈值或均量金叉 |
| 核心4通过 | 价格+斜率+量能+非异常均通过 |
| 基础通过 | 核心条件全部满足；尚不等同于 A 层可执行买点 |

验收：

- ✅ 全市场可执行为 0 时，页面能说明卡点，不需要翻日志。
- 连续多日 0 命中时，可以区分是市场结构问题、算法口径问题，还是数据/指标问题。（待 P0-R3 完整验收）

### P0-R3 2560 输出分层 ✅

已实现：在 `_compute_funnel()` 中基于 `build_probe` 可用字段输出 A/B/C/D 分层：

| 层级 | 名称 | 口径 | 用途 |
|------|------|------|------|
| A | 严格结构 | 核心4全通过（价格贴MA25、MA25向上、量能OK、非异常K线）；尚不等同于完整可执行买点 | 严格结构，允许经常为 0 |
| B | 重点观察 | 接近可执行（core_fail ≤ 1）但未基础通过 | 明日观察池 |
| C | 条件触发 | 有30m指标但未进入接近可执行 | 预备跟踪 |
| D | 剔除 | 有数据但无30m指标 | 不给提示 |

UI 集成：漏斗诊断每市场卡片顶部显示 A/B/C/D 数量徽章。

原则：

- 不为了有票而放松 A 层。
- 30m 确认不作为分层的一票否决，只决定是否进入完整 A 层执行。
- 热点 / 妙梦 / 妙想作为加分和降级，不在本地结构筛选阶段硬过滤。

验收：

- ✅ 可执行为 0 时，系统仍能输出观察池和预备池（B/C 层）。
- ✅ 每只票都有层级归属。
- 入选原因、风险标签和下一步触发条件 → P0-R3 细化 + P1 观察池增强。

### P0-R4 0 命中解释口径 ✅

已实现：`_zero_hit_explain()` 先基于当前 `funnel_summary.tiers.A.count` 判断当前 A 层是否为 0；若当前 A 层为 0，再基于成功的 `analysis_batch` 历史信号数估算连续 0 命中天数。

| 档位 | 条件 | 级别 | 说明 |
|------|------|------|------|
| 当前非 0 | 当前漏斗 A 层 > 0 | ok | 当前已有严格结构，0 命中解释不触发 |
| 单日 0 | 当前 A 层为 0，最近成功运行日信号为 0 | ok | 市场没有标准回踩买点，正常 |
| 连续 3-5 日 | 当前 A 层为 0，历史成功批次信号连续 3+ 日为 0 | warn | 进入算法诊断，显示漏斗卡点 |
| 连续 10 日+ | 当前 A 层为 0，历史成功批次信号连续 10+ 日为 0 | error | 口径或实现异常，必须检查 |

UI 集成：工作台"下一步建议"之后、"正在执行的任务"之前，显示带 severity 颜色的面板。

当前判断：

- 2560 严格结构规则偏严 + 市场没有给非常标准的回踩买点，0 命中不等于失败。
- 系统不放松 A 层，通过 B/C 层观察输出和漏斗统计补充诊断。

验收：

- ✅ 当前 A 层为 0 时，能区分单日 0、连续 3-5 日、连续 10 日+，不会误报。
- ✅ 当前 A 层 > 0 时，0 命中解释不触发。
- ✅ 历史连续天数基于 `analysis_batch.message` 的 `signals=N` 估算；文档已标注为"估算"，非精确每日 A 层快照（可放入 P1/P2 增强）。

残余风险：历史连续天数是估算值，非真实每日 A 层快照。作为 P0-R4 可接受。

## P1 修复清单

| # | 项目 | 说明 | 验收 |
|---|------|------|------|
| 7 ✅ | 批次/日志降级为高级页面 | `import-panel-batches/execution/shards` 默认 `display:none`，底部加 `advancedToggleBtn` 折叠按钮 | 打开数据导入页只显示主面板，点"显示高级"后展开批次/日志/shard 三个 panel |
| 8 ✅ | 数据健康增加修复按钮 | `renderWorkspace()` 市场卡片底部加 context-aware 操作按钮：缺30m→构建30m、指标未更新→重算指标、可跑→运行2560；带 loading 状态；日期从 `state.workspaceMarketReadiness` 结构化数据取，`start = end - 5天`，不用 DOM 文本解析或硬编码默认值 | 工作台每个市场卡片显示对应操作按钮，点击可执行并自动刷新；不会因日期范围过大或过期导致 422/危险范围 |
| 9 ✅ | 观察池增加报告动作 | `observation_pool.js` 新增 `copyObservationPoolDetail()` 函数和"复制详细版"按钮 | 点击"复制详细版"输出含生成时间戳、完整字段（含2560状态）的每只票独立区块格式 |
| 10 ✅ | 页面顶部统一目标交易日 | topbar 新增 `#topbarDate` 日期和 `#pagePhase` 阶段标签；`navigateTo()` 根据 view 设置阶段文字 | topbar 右侧始终显示目标交易日；导航到数据导入→阶段标签显示"数据准备" |

### P1 Review Findings ✅

已关闭：

- 市场修复按钮请求体不符合后端契约：`build-30m` / `rebuild-indicators` 已传 `start/end`，`periods` 使用后端要求的字符串格式。
- 裸 `fetch()` 不检查失败：新增 `postJsonChecked()`，统一检查 HTTP 状态和业务 `ok/success`。
- `运行2560` 绕过 lane worker：工作台按钮改走 `/api/jobs/enqueue`，创建 `run_2560` 队列任务，继续使用 P0 market lane 防重。
- 批次/日志降级被步骤 4 自动展开打破：移除步骤 4 自动展示批次/执行/shard 的逻辑，高级面板只由折叠按钮控制。
- 日期范围危险默认值：移除 DOM 文本解析、`2020-01-01` 和固定日期 fallback；操作按钮使用 `state.workspaceMarketReadiness` 结构化数据推导 `end`，`start = end - 5天`。

验收：

- ✅ 盘后主流程 review 验收通过：打开今日工作台 → 查看 readiness → 执行对应修复按钮 → 运行 2560 → 查看漏斗/观察池 → 复制详细版。

## P2 增强

| # | 项目 | 说明 | 验收 |
|---|------|------|------|
| 11 ✅ | 一键盘后流程 | 按 readiness 自动串联：检查 → 导入 → 30m → 指标 → 2560 → 观察池 | 替换原 view-workflow 为交互式 wizard；根据 readiness 自动跳过不需要的步骤；每步可跳过/重试/查看详情；导入分 lday+5m 两步执行；run2560 走 run-all-markets（lane worker 防重）；导入/构建30m后会刷新后续计划 |
| 12 | 妙梦/妙想交叉验证 | 观察池增强，外部验证结果影响 A/B/C/D 分层 | 不放进 P0 |
| 13 | 自动观察池分层 | 基于 2560、题材、30m、MA25距离、风险条件生成 A/B/C/D | 每只票有明确分层理由 |

### P2 #11 Review Findings ✅

已关闭：

- workflow HTML 弯引号导致节点不可达：`view-workflow`、`workflowStartBtn`、`workflowSteps`、`workflowStepDetail` 已改为正常 ASCII 属性引号。
- API 步骤缺 `endpoint`：`import` / `build30m` / `indicators` / `run2560` 已补齐对应端点。
- 进度字段读错：轮询改读 `/api/jobs/executions/{id}/progress` 返回的 `percent`。
- `run2560` 不等待 market lane：`run-all-markets` 创建任务后等待所有 created market lane 完成；全部 skipped 时标记 failed，不进入观察池。
- `getJson()` 不检查失败：已统一检查 HTTP 状态和业务 `ok/success`。
- 指标过期误触发行情导入：导入只由 K 线缺失触发，指标过期只触发重算指标。
- poll 失败被覆盖为 done：导入、构建 30m、指标重算轮询失败后立即停止后续步骤。
- 后续计划不重算：import 成功后刷新计划，build30m 成功后刷新计划，只更新后续 pending/skipped 步骤。

待验收：

- 完整流程手工跑通：打开 workflow 页 → 点击“一键盘后流程” → 确认跳过/执行逻辑 → 等待 2560 lane 完成 → 到观察池。

## 性能优化

### workspace_status 持久化表 ✅

`/api/strategy/2560/workspace` 原来对 4 个市场做 20+ 次 `MAX(date)` 实时聚合扫描大表（`daily_kline` / `minute_kline_period` / `technical_indicator`），导致端点卡顿。

改为 `workspace_status` 预计算表，workspace 端点只读 4 行小表。每次数据操作完成后由 runner 脚本自动刷新对应 market 的列。

| Runner | 成功后刷新列 |
|--------|-------------|
| `import_job_runner` (lday) | `daily` + `source_daily` |
| `import_job_runner` (5m) | `5m` |
| `build_30m_job_runner` | `30m` |
| `rebuild_indicator_job_runner` | 按 periods 参数刷新对应指标列 |

关键设计：
- `update_market_latest()` 的 `replace_fields` 机制：MAX=NULL 时可清空旧值，不会保留假数据
- 指标查询按 `periods` 过滤，不扫不必要的表
- `market=all` 展开四市场逐个刷新
- 首次建表后自动做一次 MAX() 扫描初始化真实数据

## 执行层验收

- `docker compose ps` 能看到 1 个 data worker + 4 个 market worker
- 四个 market 同时跑时，job 状态互不串扰
- 同一个 market 连续提交两次，只允许一个 running，另一个 queued 或被拒绝
- MySQL iowait、CPU、慢查询可观察
- 任一 worker 挂掉重启后，不会重复处理已完成任务

## 推荐实施顺序

1. 先修导航 bug
2. 再改 worker market lane 和任务领取逻辑
3. 然后做"运行 2560"四类一键任务
4. 再改"今日工作台"和"数据健康"
5. 最后重构数据准备页面、观察池、报告导出

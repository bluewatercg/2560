# 第一轮审计结果 - Agent B

## 1. 审计范围

本轮覆盖报告包、API 与工作台链路，对照文件：

- `docs/2560_v1.2.2_报告驱动工作流设计_完整版.md`
- `docs/2560_v1.2.2_产品评估报告与改进点清单_v1.0.md`
- `docs/superpowers/plans/2026-06-09-workspace-report-package-entry.md`
- `app/api/reports.py`
- `app/services/report_package_service.py`
- `app/services/morning_report_package_service.py`
- `app/services/morning_confirm_report.py`
- `app/services/daily_selection_report.py`
- `app/static/index.html`
- `app/static/app.js`
- `app/static/results_workbench.js`
- `app/static/post_workflow.js`

## 2. 结论总览

报告驱动方向已经明显落到代码里了，但还处于“新入口已接上，旧产品心智仍占主导”的过渡态。

当前状态可以概括为：

1. 报告包接口和工作台入口已经存在，盘后 `01-08` 与早盘 `09-10` 都能生成。
2. 工作台已经具备报告包按钮、结果面板和恢复已生成产物的能力。
3. 但产品整体仍然保留强烈的“结果中心 / 列表中心”形态，尚未真正降级为辅助排查入口。
4. `01_daily_selection.md` 仍直接沿用旧 `daily_selection_report` 输出，因此保留大量交易化、内部化措辞。
5. morning 报告链路已能生成文件，但对真实 `pre_market_state` 的承载仍是占位级别。

## 3. 目标 vs 当前实现差异表

| 主题 | 目标设计 | 当前实现 | 结论 |
|---|---|---|---|
| 报告包产物 | 同目录承载 01-10 | 盘后服务生成 01-08，早盘服务生成 09-10 | 基本达标 |
| 工作台入口 | 页面直接生成报告包并查看核心文件 | 已有按钮、结果面板、直达链接 | 达标 |
| Skill 入口 | 以 `08_skill_input.md` / `10_skill_morning_input.md` 为核心 | 已有 API 和工作台快捷入口 | 达标 |
| 产品定位 | 页面降级为排查入口，主产品是报告包 | 仍保留大量“结果工作台/信号列表/最新结果”主入口 | 未完全达标 |
| 报告文案 | 对外口径去交易化、去内部术语 | `daily_selection_report` 仍保留“可执行/开仓/止损/淘汰交易”等表达 | 明显未达标 |
| 早盘链路 | 早盘确认 + Skill 输入完整承载 | 文件能生成，但 `pre_market_state` 当前为 `None` | 部分达标 |

## 4. 报告产物覆盖矩阵

| 文件 | 目标 | 当前生成方式 | 结论 |
|---|---|---|---|
| `01_daily_selection.md` | 盘后总报告 | `ReportPackageService` 直接写入 `report["markdown"]` [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:34) | 已生成，但沿用旧口径 |
| `02_focus_full_reports.md` | focus 全维度报告 | `render_focus_full_reports()` [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:35) | 已生成 |
| `03_watch_lite_reports.md` | watch 简版报告 | `render_watch_lite_reports()` [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:36) | 已生成 |
| `04_scan_summary.json` | 全市场扫描汇总 | `build_scan_summary()` [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:37) | 已生成 |
| `05_focus_watch_list.json` | focus/watch 清单 | `build_focus_watch_list()` [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:38) | 已生成 |
| `06_reject_summary.json` | reject 汇总 | `build_reject_summary()` [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:39) | 已生成 |
| `07_field_audit.json` | 字段审计 | `build_field_audit()` [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:40) | 已生成 |
| `08_skill_input.md` | 盘后 Skill 输入 | `render_after_market_skill_input()` [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:41) | 已生成 |
| `09_morning_confirm.md` | 早盘确认报告 | `MorningReportPackageService` [morning_report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/morning_report_package_service.py:26) | 已生成 |
| `10_skill_morning_input.md` | 早盘 Skill 输入 | `MorningReportPackageService` [morning_report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/morning_report_package_service.py:26) | 已生成 |

补充说明：

- `app/api/reports.py` 的允许文件列表已经覆盖 `01-10` [reports.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/api/reports.py:46)。
- 但盘后和早盘是两个生成入口，不是一次性生成 `01-10`。

结论：

- 从产物覆盖角度，Agent B 判断为“基本齐备”。
- 主要问题不是缺文件，而是文件内容和产品定位。

## 5. 工作台入口审计

### 5.1 报告包入口已经接上 UI

工作台页面中已存在：

- 盘后报告包区域 [index.html](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/index.html:157)
- 早盘确认报告区域 [index.html](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/index.html:169)

对应按钮：

- `dailyGenerateReportPackageBtn`
- `dailyGenerateMorningReportBtn`

对应结果挂载点：

- `workspaceReportPackage`
- `workspaceMorningReportPackage`

结论：

- 页面入口已经不是“待建”，而是“已接线”。

### 5.2 工作台逻辑已经支持生成、展示、恢复已有文件

`app.js` 已实现：

- 盘后报告包结果渲染 [app.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/app.js:1068)
- 早盘报告包结果渲染 [app.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/app.js:1108)
- 恢复已存在的盘后报告包 [app.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/app.js:1146)
- 恢复已存在的早盘报告包 [app.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/app.js:1167)
- 调用 `/api/reports/daily-package/new` [app.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/app.js:1241)
- 调用 `/api/reports/morning-package/new` [app.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/app.js:1271)

并且会给出快捷链接：

- `08_skill_input.md` [app.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/app.js:1092)
- `09_morning_confirm.md` / `10_skill_morning_input.md` [app.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/app.js:1133)

结论：

- “工作台新增报告包入口”这件事已经实现，不再是缺口。

### 5.3 但产品整体仍然不是“页面降级为排查入口”

虽然工作台中已经加入报告包入口，但 UI 仍保留大量传统结果页心智：

- 侧栏仍强调 `信号列表`、`最新分析结果`、`任务队列`、`结构统计` [index.html](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/index.html:20)
- `results_workbench.js` 仍以“今日可看 / 全部最新 / 历史信号 / 标注明细”组织主视图 [results_workbench.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/results_workbench.js:22)

结论：

- 工作台报告入口已经有了。
- 但页面整体定位仍没有真正降级为“辅助排查工具”。

## 6. API 与生成链路审计

### 6.1 报告 API 已经比较完整

当前 API 已提供：

- `POST /api/reports/daily-package/new` [reports.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/api/reports.py:134)
- `POST /api/reports/morning-package/new` [reports.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/api/reports.py:150)
- `GET /api/reports/skill-input.md` [reports.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/api/reports.py:167)
- `GET /api/reports/morning-confirm.md` [reports.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/api/reports.py:174)
- `GET /api/reports/skill-morning-input.md` [reports.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/api/reports.py:181)
- `GET /api/reports/daily-package/file` [reports.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/api/reports.py:188)

结论：

- API 链路在“生成 + 读取关键文件”层面已经够用。

### 6.2 早盘报告依赖前一交易日 `05_focus_watch_list.json`

`MorningReportPackageService` 通过读取：

- `reports/<source_trade_date>/05_focus_watch_list.json`

来恢复昨日 focus/watch 候选 [morning_report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/morning_report_package_service.py:69)。

结论：

- 这符合“报告包驱动”的思路。
- 但如果前一日盘后报告包没生成，早盘链路就会失败。

### 6.3 `pre_market_state` 还未真正接入

`MorningReportPackageService` 的 `_MorningMarketDataClient.load_pre_market_state()` 目前直接返回 `None` [morning_report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/morning_report_package_service.py:117)。

结论：

- 09/10 文件能生成。
- 但“早盘市场环境”字段当前只是框架到位，不是完整数据承载。

## 7. 对外文案风险清单

### 7.1 `01_daily_selection.md` 仍直接继承旧交易化报告口径

`ReportPackageService` 对 `01_daily_selection.md` 的处理是直接取：

- `report["markdown"]`

见 [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:34)。

而 `daily_selection_report.py` 中仍大量存在：

- `可执行`
- `开仓条件`
- `止损条件`
- `淘汰交易`
- `不符合2560买点`
- `交易`

例如：

- `当前不符合开仓条件` [daily_selection_report.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/daily_selection_report.py:577)
- `开仓条件` [daily_selection_report.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/daily_selection_report.py:1199)
- `止损条件` [daily_selection_report.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/daily_selection_report.py:1200)
- `可执行交易与淘汰交易` [daily_selection_report.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/daily_selection_report.py:1207)

结论：

- 盘后报告包已经生成，但主报告文案还没有完成对外脱敏。

### 7.2 盘后 Skill 输入文档比旧总报告更干净，但仍保留内部状态词

`08_skill_input.md` 以：

- `focus`
- `watch`
- `reject`
- `market_state`
- `environment_score`

作为结构主轴 [report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:203)。

这相比 `01_daily_selection.md` 已经更接近结构化输入文档，但仍属于内部模型口径，不是完全对外表述。

结论：

- 更适合 Skill 消费，不一定适合面向普通阅读者。

### 7.3 早盘报告天然包含“竞价/早盘”术语，这是目标内术语，不是问题本身

`09_morning_confirm.md` / `10_skill_morning_input.md` 中包含：

- `竞价`
- `早盘`
- `morning_grade`

见 [morning_confirm_report.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/morning_confirm_report.py:34)。

这部分不应与“盘后总报告的脱敏要求”混为一谈。

结论：

- 早盘链路的术语属于目标设计本身。
- 真正的文案风险集中在 `01_daily_selection.md`。

## 8. 工作台入口缺口清单

1. 已有生成按钮，但没有把“报告驱动是主入口”提升为全局主叙事。
2. 报告包区域已存在，但页面其他导航仍把“列表结果”放在同等主层级。
3. 盘后报告和早盘报告是两个独立按钮，尚未形成更明确的“盘后 -> 次日早盘”连续心智。
4. 早盘报告结果面板只列文件名和链接，没有展示关键摘要。

## 9. Top 5 风险

1. `01_daily_selection.md` 直接沿用旧报告输出，交易化措辞仍然明显
   依据：[report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/report_package_service.py:34), [daily_selection_report.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/daily_selection_report.py:1199)

2. 产品整体仍以结果中心思维组织，尚未完全转向“报告包主产品”
   依据：[index.html](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/index.html:20), [results_workbench.js](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/results_workbench.js:22)

3. 早盘报告依赖前一交易日报告包存在，缺乏更强的失败恢复路径
   依据：[morning_report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/morning_report_package_service.py:69)

4. `pre_market_state` 目前仍为空，占位意义大于实际承载
   依据：[morning_report_package_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/morning_report_package_service.py:117)

5. 盘后/早盘报告入口虽已具备，但页面信息架构还没有彻底重排
   依据：[index.html](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/static/index.html:138)

## 10. 建议的后续实现顺序

1. 优先清理 `daily_selection_report.py` 的交易化/内部化措辞，让 `01_daily_selection.md` 可直接作为外部报告。
2. 把工作台文案进一步改成“报告包主入口，列表页为排查入口”。
3. 补齐 `pre_market_state` 真正数据来源，让 09/10 不再只是格式完整。
4. 在工作台结果面板中展示关键摘要，而不只是文件列表。

## 11. 本轮审计结论

Agent B 的结论是：

- 报告包能力和工作台生成入口已经基本落地。
- 当前最大的缺口不是“能不能生成”，而是“生成出来的内容是否已经符合目标口径”，以及“产品是否真正以报告为主入口”。

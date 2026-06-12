# 第一轮审计汇总 - Agent A / B / C

## 1. 汇总范围

本汇总基于三份审计结果：

- [ROUND1_AGENT_A_AUDIT.md](/mnt/d/Project/Miller/strategy2560_project_v2_engine/docs/ROUND1_AGENT_A_AUDIT.md)
- [ROUND1_AGENT_B_AUDIT.md](/mnt/d/Project/Miller/strategy2560_project_v2_engine/docs/ROUND1_AGENT_B_AUDIT.md)
- [ROUND1_AGENT_C_AUDIT.md](/mnt/d/Project/Miller/strategy2560_project_v2_engine/docs/ROUND1_AGENT_C_AUDIT.md)

## 2. 总体判断

项目已经进入一个典型的“目标设计先于主路径收敛”的阶段：

- canonical 目标规则已经明确
- schema 与报告包能力已经大幅铺开
- 但主执行路径、配置口径、repository 契约、页面主入口心智还没有完全收拢

换句话说：

当前不是“缺少方向”，而是“方向已经写进文档和部分代码，但系统主路径仍有明显过渡态”。

## 3. 当前最严重的 5 个差异

1. `canonical` 还不是唯一主引擎，`fast != slow != canonical`
   来源：Agent A

2. schema 已经扩到 v1.2.2，但 repository 和外部调用持久化实现没有同步跟上
   来源：Agent C

3. `01_daily_selection.md` 仍直接复用旧交易化报告输出，不符合目标对外口径
   来源：Agent B

4. `market_state` / `hot_topic_strength` / `position_in_hot_topic` 在主扫描路径里仍大量使用占位值
   来源：Agent A

5. 配置体系仍处于 canonical 与 legacy 混合阶段，部分真实阈值不可审计
   来源：Agent A + Agent C

## 4. 这些差异分别属于哪一类

### 4.1 主要是文档/口径问题

- `01_daily_selection.md` 的交易化措辞
- 页面整体“结果中心”而非“报告主入口”的产品叙事
- 部分旧文档仍然描述历史状态

### 4.2 已经是代码/数据契约问题

- canonical 仍不是唯一主引擎
- fast 5m 确认与 slow/canonical 不一致
- fast 候选筛选缺少 volume-cross fallback
- `market_state` / `hot_topic_strength` / `position_in_hot_topic` 未接真实数据
- repository 缺少 morning / topic / external governance 等读写接口
- `focus_score_min` / `watch_score_min` 没有进入配置契约

## 5. 哪些可以并行，哪些必须串行

### 可并行

1. 报告口径清理
2. repository 能力扩展
3. 工作台产品心智整理
4. 外部调用治理持久化实现

### 必须串行

1. 先统一 canonical 输入和 gate 逻辑，再追求 fast/slow/canonical parity
2. 先补 config contract，再做大规模调参与验收
3. 先补 repository / schema 访问层，再让 market/topic/morning 服务接真实数据

## 6. 建议的实现优先级

### P1. canonical 主路径收敛

- 让 `market_state` / `hot_topic_strength` / `position_in_hot_topic` 接上真实输入
- 修正 fast 5m 确认为逐信号窗口
- 统一 volume gate

### P2. config / repository 契约收口

- 补 `focus_score_min` / `watch_score_min`
- 清理 legacy/canonical 混合映射
- 给 repository 增加 market/topic/morning/external 读写接口

### P3. 报告与工作台口径整理

- 清理 `daily_selection_report.py` 的交易化措辞
- 保持工作台为主入口，列表页降级为排查页
- 完善 09/10 结果摘要展示

## 7. 后续每轮改动的准入门槛

至少应把下面这些测试视为后续改动的最小准入门槛：

- `tests/test_canonical_signal_engine.py`
- `tests/test_indicator_engine.py`
- `tests/test_strategy2560_config_contract.py`
- `tests/test_strategy2560_schema_contracts.py`
- `tests/test_structure_2560_repository_contract.py`
- `tests/test_report_package_service.py`
- `tests/test_reports_api_package.py`
- `tests/test_report_driven_workflow_acceptance.py`

如果触及早盘确认或外部调用治理，再追加：

- `tests/test_morning_confirm_engine.py`
- `tests/test_morning_report_package_service.py`
- `tests/test_external_call_service.py`

## 8. 最后结论

这轮审计之后，项目的真实状态可以总结成一句话：

“v1.2.2 的目标蓝图、底层表结构和报告入口已经基本搭起来了，但主扫描路径、数据访问契约和对外报告口径还没有真正收敛到同一套 canonical 体系。”

下一轮如果进入实现，最值得优先做的不是继续加新功能，而是把这三件事收口：

1. canonical 主路径
2. config / repository 契约
3. 报告口径去交易化

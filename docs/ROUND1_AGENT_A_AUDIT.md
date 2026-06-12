# 第一轮审计结果 - Agent A

## 1. 审计范围

本轮仅覆盖 2560 核心规则与引擎差异，对照目标文档：

- `docs/2560短线结构算法统一改造方案_v1.2.2_FinalFreeze.md`

对照实现文件：

- `app/services/signal_engine_2560.py`
- `app/services/signal_engine_2560_fast.py`
- `app/services/canonical_signal_engine.py`
- `app/services/config_service.py`
- `app/services/indicator_engine.py`

## 2. 结论总览

当前系统还没有达到 `FinalFreeze` 定义的“废除 Fast / Slow 分叉，统一为 canonical_signal_engine”状态。

更准确地说，当前状态是：

1. slow 引擎和 fast 引擎仍然各自独立完成候选扫描与大部分 gate。
2. `canonical_signal_engine.py` 目前主要承担“把 legacy 扫描结果补成 canonical 字段并打分”的角色。
3. canonical 所需的 `market_state`、`hot_topic_strength`、`position_in_hot_topic` 在主扫描路径中仍未真正接入业务数据，而是使用占位上下文。
4. `high_20` 与 5m 前 6 根这两个关键冻结约束，在当前实现里已经基本满足。
5. 配置体系已经开始向 v1.2.2 靠拢，但兼容映射存在语义污染，仍可能导致 legacy gate 与 canonical gate 混用。

## 3. 目标 vs 当前实现差异表

| 主题 | FinalFreeze 目标 | 当前实现 | 结论 |
|---|---|---|---|
| 主执行架构 | fast / slow 废除分叉，统一 canonical | slow 和 fast 各自扫描，最后调用 `build_canonical_fields_from_legacy_signal()` 补字段 | 未达标 |
| 30m `high_20` | 必须排除当前 K | pandas 用 `shift(1).rolling(...)`；fast SQL 用 `ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING` | 已基本达标 |
| 5m 确认 | 只看 `signal_time` 前 6 根 | slow 用 `< signal_time` 且 `tail(confirm_5m_bars)`；fast 仍按整日聚合近似 | 部分达标 |
| KDJ / MACD 角色 | 不做硬 gate，只进入评分 | 指标已计算，但 canonical 打分函数未实际使用 KDJ/MACD 字段 | 未达标 |
| market_state / 主线 / 个股位置 | 进入 canonical 输入并影响 focus/watch/reject | 扫描时传入固定占位值：`unknown` / `none` / `edge` | 未达标 |
| volume gate | 5/60 量结构 + 金叉兜底统一 | slow 和 canonical 都允许 fallback；fast SQL 的初筛仍只看 `vol_ratio >= min_volume` | 未统一 |
| 配置体系 | 统一读取 v1.2.2 配置，并与旧 key 脱钩 | 新配置已存在，但兼容映射把 legacy key 继续喂给旧 gate | 部分达标 |
| 输出一致性 | `fast == slow == canonical` | 代码结构上仍无法保证三者等价，只是共享尾部 canonical 补字段 | 未达标 |

## 4. 具体发现

### 4.1 canonical 还不是主扫描引擎

`FinalFreeze` 明确要求“废除 Fast / Slow 分叉，统一为 canonical_signal_engine”。当前代码并非如此：

- slow 路径仍在 [signal_engine_2560.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560.py:85) 的 `scan()` 中自行做候选筛选、趋势判断、波动判断、5m 确认、突破判断。
- fast 路径仍在 [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:44) 的 `_candidate_sql()` 中自行做大部分候选筛选。
- `canonical_signal_engine.py` 当前提供的是 `build_canonical_fields_from_legacy_signal()`，它接收 legacy 结果行后再生成 `selection_status`、`final_score` 等字段 [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:63)。

结论：

- canonical 目前是“尾部评分器/字段补全器”，不是“唯一引擎”。

### 4.2 `high_20` 已修到接近目标状态

`FinalFreeze` 要求 `high_20` 必须排除当前 K。

当前实现：

- pandas 指标路径在 [indicator_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/indicator_engine.py:73) 使用 `shift(1).rolling(...)`，符合目标。
- fast SQL 在 [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:77) 使用 `ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING`，也排除了当前行。

结论：

- 这是本轮较少数已经贴近冻结方案的点。
- 但文档里对 fast 路径“曾经包含当前 K”的描述仍是历史审计结论，不再完全等于当前代码现状。

### 4.3 slow 的 5m 确认符合目标，fast 仍是近似逻辑

`FinalFreeze` 要求 5m 只看 `signal_time` 前 6 根。

当前实现：

- slow 路径在 [signal_engine_2560.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560.py:73) 到 [signal_engine_2560.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560.py:82) 中使用 `m5_i[m5_i['date'] < signal_time].tail(confirm_bars)`，符合“严格前 6 根”。
- fast 路径的 `m5_recent` 在 [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:137) 到 [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:151) 是按整日 5m 数据聚合出 `last_5m_close`、`avg(close)`、`has_bullish`，并不是“信号时点前 6 根”的逐信号窗口。

结论：

- slow 路径已符合冻结约束。
- fast 路径仍不符合“逐信号时点前 6 根”的 canonical 要求。

### 4.4 fast 与 slow 的 volume gate 仍未统一

当前实现差异：

- slow 路径在 [signal_engine_2560.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560.py:101) 允许 `vol_ratio >= min_volume` 或 `vol_ma5_cross_vol_ma60 == 1`。
- canonical 的 `_volume_structure_ok()` 在 [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:147) 到 [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:153) 也允许金叉 fallback。
- fast SQL 在 [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:178) 只要求 `m.vol_ratio >= {min_volume}`，并未在候选筛选阶段加入 volume-cross fallback。

结论：

- 即使 fast 末尾也会补 canonical 字段，候选集合本身已经提前被筛掉，因此三条路径天然不等价。

### 4.5 canonical 上下文目前还是占位值，不是真实业务输入

`FinalFreeze` 要求 Step 9 / Step 10 接入 `market_state`、`hot_topic_strength`、`position_in_hot_topic`。

当前实现：

- slow 路径固定传入 `{'market_state': 'unknown', 'environment_score': 0.4, 'hot_topic_strength': 'none', 'position_in_hot_topic': 'edge'}` [signal_engine_2560.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560.py:119)。
- fast 路径也固定传入同样占位值 [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:231)。

这会带来直接后果：

- `hot_topic_required=True` 时，canonical `_hard_gate_failures()` 会因为 `hot_topic_strength='none'` 默认失败 [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:139)。
- `position_required_for_focus='strong'` 时，默认 `edge` 也无法达成 `focus` [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:44)。

结论：

- 这说明 canonical 输出字段已经存在，但并没有接上真实环境数据。
- 如果没有其他上游覆盖，这会系统性扭曲 `selection_status`。

### 4.6 KDJ / MACD 已计算，但尚未真正进入 canonical 评分

`indicator_engine.py` 已经生成 KDJ 和 MACD 相关字段 [indicator_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/indicator_engine.py:82) 到 [indicator_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/indicator_engine.py:96)。

但在 `build_canonical_fields_from_legacy_signal()` 中，评分输入只使用：

- 结构 flags
- volume ratio / volume cross
- hot topic
- pullback / bullish
- breakout / near resistance
- environment score

对应代码见 [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:72) 到 [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:98)。

结论：

- 指标字段已存在，评分规则尚未接入。
- 当前实现还没达到“右侧确认进入评分”的冻结要求。

### 4.7 配置体系已迁移一半，但兼容映射存在语义污染

优点：

- `DEFAULT_CONFIG` 已包含大量 v1.2.2 键，如 `pullback_max_pct`、`confirm_5m_bars`、`hot_topic_required`、`position_required_for_focus` [config_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/config_service.py:15)。
- 旧 DB key 被列入 `DEPRECATED_DB_KEYS` 并忽略 [config_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/config_service.py:53)。

问题：

- `CANONICAL_COMPAT_KEYS` 把 `pullback_threshold_pct <- pullback_max_pct`，`min_volume_ratio <- volume_cross_confirm_ratio` [config_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/config_service.py:64)。
- 这会让 legacy slow/fast gate 继续读取兼容键，但其值已经来自 canonical 语义。
- 例如 `min_volume_ratio` 本来是候选筛选门槛，却被映射成 `volume_cross_confirm_ratio=0.9`，这改变了 legacy 筛选含义 [signal_engine_2560.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560.py:88) 与 [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:47)。

结论：

- 当前配置层不是“彻底 canonical 化”，而是“canonical 默认值 + legacy 消费接口并存”。
- 这会让调参结果难以解释。

### 4.8 `focus_score_min` / `watch_score_min` 依赖隐式默认值

`evaluate_after_market_signal()` 使用：

- `focus_score_min` 默认 `0.75`
- `watch_score_min` 默认 `0.45`

见 [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:47) 到 [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:49)。

但 `DEFAULT_CONFIG` 中没有这两个 key [config_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/config_service.py:15)。

结论：

- 这不会立刻报错，因为代码内置了函数默认值。
- 但它破坏了“配置统一可审计”的目标：数据库快照看不出真正生效的阈值。

## 5. 当前最严重的 Top 5 风险

1. canonical 不是主引擎，导致 `fast != slow != canonical`
   依据：[signal_engine_2560.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560.py:85), [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:44), [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:63)

2. fast 5m 确认仍是整日近似，不是“信号前 6 根”
   依据：[signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:137)

3. `market_state` / `hot_topic_strength` / `position_in_hot_topic` 仍是占位值，可能系统性扭曲 `selection_status`
   依据：[signal_engine_2560.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560.py:119), [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:231)

4. fast 候选筛选未接入 volume-cross fallback，导致候选集合先天不同
   依据：[signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:176), [canonical_signal_engine.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/canonical_signal_engine.py:147)

5. 配置兼容映射把 canonical 语义回灌给 legacy gate，导致调参与口径解释变得不透明
   依据：[config_service.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/config_service.py:64), [signal_engine_2560.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560.py:87), [signal_engine_2560_fast.py](/mnt/d/Project/Miller/strategy2560_project_v2_engine/app/services/signal_engine_2560_fast.py:46)

## 6. 建议的后续实现顺序

1. 先把 canonical 输入上下文接上真实 `market_state` / `hot_topic_strength` / `position_in_hot_topic`。
2. 把 fast 的 5m 确认改为逐信号窗口逻辑，否则 parity 永远不成立。
3. 把 volume gate 收敛到同一逻辑，避免 fast 先筛掉本应由 canonical 通过的票。
4. 明确配置层：区分 canonical key 与 legacy key，禁止继续通过兼容映射改写 legacy 含义。
5. 最后再把 slow / fast 退化成 wrapper，而不是继续各自保留扫描逻辑。

## 7. 本轮审计结论

如果按 `FinalFreeze` 验收标准判断，Agent A 结论是：

- 已接近达标：`high_20` 排除当前 K、slow 5m 前 6 根、recent_3d/KDJ/MACD 指标落表能力。
- 明显未达标：唯一 canonical 引擎、真实环境/主线输入、fast/slow/canonical 一致性、统一 volume gate、配置口径统一。

当前最关键的问题不是“缺少 canonical 字段”，而是“canonical 字段已经有了，但主扫描路径仍不是 canonical 驱动”。

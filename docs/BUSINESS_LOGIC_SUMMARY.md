# 2560计算与ABCD评分业务逻辑摘要

> 文档属性：现状审计摘要
>
> 用途：快速总结当前实现中的 2560/2568 逻辑、已知差异和历史问题。
>
> 不作为目标规则源。若与 canonical 改造目标冲突，请以 `docs/2560短线结构算法统一改造方案_v1.2.2_FinalFreeze.md` 为准。

## 2560信号扫描核心流程
1. **技术指标计算** - MA25/MA60/ATR/量比等24个指标
2. **核心4条件必须全部满足**：
   - 价格偏离MA25 ≤ 2%
   - MA25斜率 ≥ 0（变量名ma25实际周期由 `ma_price_period` 配置，默认25）
   - 量比 ≥ 1.0 或 5日均量金叉60日均量（Slow引擎有金叉兜底，Fast引擎无）
   - 非异常K线（非一字线、有成交量）
3. **扩展条件**：日线趋势、波动率、5m确认、突破/压力位
4. **信号冷却**：同一股票间隔 ≥ 3个交易日

## 标签系统（11种标签）
- **10种negative标签**：缺量、高位、震荡、未突破、逆势、趋势走弱、未确认、偏离MA25、MA25走弱、数据不足
- **1种positive标签**：结构完整（所有negative标签都没有时触发）

## 结构状态判定
- **结构完整**：0个negative标签
- **部分满足**：1-2个negative标签
- **明显缺失**：3个及以上negative标签
- **数据不足**：存在DATA_INSUFFICIENT标签

## 强度评分（strength_score_raw）
```python
score = max(0, 2.0 - negative_tag_count × 0.2)
```
- 0个标签：2.0分
- 1个标签：1.8分
- 2个标签：1.6分
- 5个标签：1.0分

## ABCD分级系统（2568标注）
### 5项硬性条件
1. MA25上行
2. MA60上行/走平
3. 价格站上MA25
4. 均量放量（5日均量 > 60日均量）
5. 趋势结构健康（MA25 > MA60）

### 4维亮点标签（代码实际带emoji符号）
1. **趋势亮点**："⭐ 趋势双线共振"(A)、"🟦 趋势健康"(B)、"❌ 趋势弱"(D)
2. **量能亮点**："🔥 强放量"(A)、"⭐ 放量良好"(B)、"~ 弱放量"(C)、"✘ 无放量"(D)
3. **结构亮点**："🟩 结构强"(A)、"🟦 结构一般"(B)、"⚠ 结构破位"(D)
4. **安全亮点**："🟩 回踩确认"(A)、"⚠ 跌破 MA25"(D)、"🟦 趋势主升段"(B)

### 人工处理建议
- **A2+**：强势票｜重点关注
- **A1**：有核心亮点｜可关注
- **B3+**：中强票｜观察池
- **D3+**：风险较多｜建议移出

## ⚠️ Slow vs Fast 引擎差异
| 差异点 | Slow 引擎 | Fast 引擎 |
|--------|-----------|-----------|
| 核心 gate | 仅核心4（价格贴近+斜率+量能+非异常） | 额外 gate 日线趋势（daily_close > daily_ma） |
| 量能金叉 | `vol_ratio >= min OR cross == 1` | 仅 `vol_ratio >= min`，无金叉兜底 |
| high_20 | `shift(1).rolling(20).max()` 排除当前K | `ROWS BETWEEN 19 PRECEDING AND CURRENT ROW` 包含当前K |
| 5m 确认 | 信号时点前最近6根5m，最近2根阳线 | 全日5m均价近似 + 全日是否有阳线 |

## ⚠️ 配置 key 不一致
SQL种子（`sql/recreate_tables.sql`）使用 `ma_short`/`vol_short`/`atp_period` 等key，但代码读取 `ma_price_period`/`vol_short_period`/`atr_period` 等。种子数据不会覆盖默认配置。

## 关键文件
- `app/services/signal_engine_2560.py` - 2560扫描引擎（Slow）
- `app/services/signal_engine_2560_fast.py` - 2560扫描引擎（Fast）
- `app/services/tag_service.py` - 标签系统
- `app/services/annotation_engine_2568.py` - ABCD分级
- `app/services/indicator_engine.py` - 技术指标计算
- `app/services/config_service.py` - 策略参数配置
- `docs/BUSINESS_LOGIC_2560.md` - 完整业务逻辑文档

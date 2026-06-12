# Strategy2560 业务逻辑详细文档

> 文档属性：现状审计文档
>
> 用途：描述当前代码实现、历史配置差异和已发现的问题，便于审计与对照。
>
> 不作为目标规则源。涉及 v1.2.2 canonical 目标规则时，请以 `docs/2560短线结构算法统一改造方案_v1.2.2_FinalFreeze.md` 为准。

## 一、项目架构概览

### 双数据库架构
| 存储 | 地址 | 职责 |
|------|------|------|
| **ClickHouse** | 192.168.1.18:8123 | 行情数据存储（daily_kline / minute_kline_period / technical_indicator） |
| **MySQL** | 192.168.1.254:3306 | 业务数据（任务队列、分析结果、配置、标签明细） |

### 核心数据流
```
导入行情 → 构建30m → 重算指标 → 2560信号扫描 → 标签+评分 → 2568标注分级 → PDF报告
```

---

## 二、2560信号扫描计算逻辑

### 2.1 策略参数配置
**文件**: `app/services/config_service.py`

#### 代码读取的 key（DEFAULT_CONFIG）

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `ma_price_period` | 25 | 短期均线周期 |
| `vol_short_period` | 5 | 短期均量周期 |
| `vol_long_period` | 60 | 长期均量周期 |
| `pullback_threshold_pct` | 2.0 | 价格偏离MA25阈值(%) |
| `min_volume_ratio` | 1.0 | 最小量比 |
| `resistance_threshold` | 0.95 | 压力位比例 |
| `breakout_threshold` | 1.0 | 突破阈值 |
| `atr_period` | 14 | ATR周期 |
| `atr_compare_period` | 20 | ATR对比周期 |
| `atr_weak_ratio` | 0.85 | ATR弱势比率 |
| `breakout_period` | 20 | 突破周期 |
| `signal_cooldown_days` | 3 | 信号冷却天数 |
| `ma_slope_medium_threshold` | 0.0 | MA斜率阈值 |

#### ⚠️ SQL 种子 key 与代码不一致（`sql/recreate_tables.sql`）

| 种子 key | 种子值 | 对应代码 key | 代码默认值 |
|----------|--------|-------------|-----------|
| `ma_short` | 25 | `ma_price_period` | 25 |
| `ma_mid` | 60 | *(无对应)* | - |
| `ma_long` | 200 | *(无对应)* | - |
| `slope_periods` | 3 | *(无对应，硬编码)* | - |
| `atp_period` | 14 | `atr_period` | 14 |
| `vol_short` | 5 | `vol_short_period` | 5 |
| `vol_long` | 60 | `vol_long_period` | 60 |
| `high_low_window` | 20 | `breakout_period` | 20 |

**结论**: SQL 种子 key 与代码读取 key 不匹配，除非线上表另有新配置，否则种子数据不会覆盖 DEFAULT_CONFIG。

---

### 2.2 技术指标计算
**文件**: `app/services/indicator_engine.py`

#### 均线指标
```python
ma_period = cfg.get('ma_price_period', 25)  # 默认25周期
ma25 = close.rolling(ma_period, min_periods=ma_period).mean()  # 变量名ma25是历史命名，实际周期由配置决定
ma60 = close.rolling(60, min_periods=60).mean()
ma200 = close.rolling(200, min_periods=200).mean()
```

#### 斜率指标（3周期变化率）
```python
ma25_slope_3 = (ma25 - ma25.shift(3)) / ma25.shift(3) * 100  # 百分比
ma60_slope_3 = (ma60 - ma60.shift(3)) / ma60.shift(3) * 100
```

#### ATR指标（真实波幅）
```python
tr = max(high-low, abs(high-prev_close), abs(low-prev_close))
atr14 = tr.rolling(14).mean()
atr20_avg = atr14.rolling(20).mean()
```

#### 量能指标
```python
vol_ma5 = volume.rolling(5).mean()
vol_ma60 = volume.rolling(60).mean()
vol_ratio = vol_ma5 / vol_ma60
vol_ma5_cross_vol_ma60 = (vol_ratio.shift(1) <= 1) & (vol_ratio > 1)  # 金叉标记
```

#### 价格偏离
```python
price_ma25_deviation_pct = (close - ma25) / ma25 * 100
```

#### 高低点与压力位
```python
high_20 = high.shift(1).rolling(20).max()  # 前1根K线的20周期最高价
low_20 = low.shift(1).rolling(20).min()
low_30 = low.shift(1).rolling(30).min()
resistance_level = high_20
```

#### 异常K线标记
```python
is_abnormal_bar = 1 if:
  - OHLCV 任一为空
  - open == high == low == close  # 一字线
  - volume <= 0
else 0
```

---

### 2.3 信号扫描引擎（核心漏斗）

系统有**两个引擎**，核心逻辑一致但有**实质口径差异**：

#### 引擎1: `SignalEngine2560` (逐股票扫描)
**文件**: `app/services/signal_engine_2560.py`

#### 引擎2: `SignalEngine2560Fast` (ClickHouse批量扫描)
**文件**: `app/services/signal_engine_2560_fast.py`

#### ⚠️ 两个引擎的关键差异

| 差异点 | Slow 引擎 | Fast 引擎 |
|--------|-----------|-----------|
| **核心 gate 条件** | 仅 gate 核心4（价格贴近+MA25斜率+量能+非异常） | 额外 gate `daily_close > daily_ma` 和 `daily_slope > slope_threshold` |
| **量能金叉兜底** | `vol_ratio >= min_volume OR vol_ma5_cross_vol_ma60 == 1` | 仅 `vol_ratio >= min_volume`，无金叉兜底 |
| **high_20 计算** | `shift(1).rolling(20).max()` 排除当前 K | `ROWS BETWEEN 19 PRECEDING AND CURRENT ROW` 包含当前 K |
| **5m 确认** | 取信号时点前最近6根5m，检查最近2根阳线 | 全日5m均价近似 + 全日是否有阳线 |
| **执行方式** | 逐股票 Python 循环 | 单条 ClickHouse SQL 批量 |

#### 核心漏斗条件（按顺序）

| 步骤 | 条件 | 阈值 | 变量名 |
|------|------|------|--------|
| **1. 价格贴近MA25** | `abs(price_ma25_deviation_pct) <= pullback_threshold_pct` | 2.0% | `price_near` |
| **2. MA25斜率正常** | `ma25_slope_3 >= ma_slope_medium_threshold` | 0.0 | `slope_ok` |
| **3. 量能结构满足** | `vol_ratio >= min_volume_ratio` 或 `vol_ma5_cross_vol_ma60 == 1` | 1.0 | `volume_ok` |
| **4. 非异常K线** | `is_abnormal_bar == 0` | - | `abnormal_ok` |
| **5. 日线趋势价格** | `daily_close > daily_ma60(或ma25)` | - | `trend_price` |
| **6. 日线趋势斜率** | `daily_slope > slope_threshold` | - | `trend_slope` |
| **7. 波动率充足** | `atr14 > atr20_avg * atr_weak_ratio` | 0.85 | `volatility` |
| **8. 5m确认-回踩** | `m5_close >= m5_ma25` 或 `偏离<=2%` | - | `pullback` |
| **9. 5m确认-阳线** | 最近2根5m有阳线 `close > open` | - | `bullish` |
| **10. 突破** | `close > high_20 * breakout_threshold` | 1.0 | `breakout` |
| **11. 接近压力位** | `close >= high_20 * resistance_threshold` | 0.95 | `near` |

#### 核心判定规则
- **前4个条件（核心4）必须全部满足**才进入后续判断
- **信号冷却**: 同一股票两次信号间隔 >= `signal_cooldown_days(3)` 个交易日

---

## 三、标签系统（Tag System）

**文件**: `app/services/tag_service.py`

### 3.1 标签定义（11种）

| 标签代码 | 标签名 | 类型 | 触发条件 |
|----------|--------|------|----------|
| `LACK_VOLUME` | #缺量 | negative | `volume_ok` 或 `volume_structure_ok` 为假 |
| `HIGH_POSITION` | #高位 | negative | `near_resistance` 为真（接近压力位） |
| `SIDEWAYS` | #震荡 | negative | `volatility_ok` 为假（波动率不足） |
| `NO_BREAKOUT` | #未突破 | negative | `breakout_ok` 为假 |
| `AGAINST_TREND` | #逆势 | negative | `trend_price_ok` 为假（价格在趋势线下方） |
| `WEAK_TREND` | #趋势走弱 | negative | `trend_slope_ok` 为假（趋势斜率不足） |
| `NO_CONFIRM` | #未确认 | negative | `pullback_ok` 或 `bullish_confirm` 为假 |
| `PRICE_AWAY_MA25` | #偏离MA25 | negative | `price_near_ma25` 为假 |
| `MA25_WEAK` | #MA25走弱 | negative | `ma25_slope_ok` 为假 |
| `DATA_INSUFFICIENT` | #数据不足 | negative | `data_quality_status` != "normal" |
| `COMPLETE_STRUCTURE` | #结构完整 | **positive** | 以上所有negative标签都没有 |

### 3.2 结构状态判定
```python
def structure_status(tags):
    neg = len([t for t in tags if t.tag_type == "negative"])
    if any(t.tag_code == "DATA_INSUFFICIENT" for t in tags):
        return "数据不足"
    if neg == 0:
        return "结构完整"
    if neg <= 2:
        return "部分满足"
    return "明显缺失"
```

### 3.3 解释文本生成
- **结构完整**: "该标的在{period}周期出现2560结构，价格接近MA25，MA25趋势正常，量能结构满足，当前结构状态为'结构完整'。"
- **其他**: "该标的出现2560相关结构，但存在{缺失标签列表}，当前结构状态为'{status}'。"

---

## 四、Strength Score（强度评分）

**文件**: `signal_engine_2560.py` 行122 / `signal_engine_2560_fast.py` 行235

### 计算公式
```python
strength_score_raw = max(0, 2.0 - missing_tag_count * 0.2)
```

### 业务含义
- 基础分 = 2.0
- 每有一个negative标签扣 0.2 分
- 最低分 = 0

| negative标签数 | strength_score_raw | 结构状态 |
|----------------|-------------------|----------|
| 0 | 2.0 | 结构完整 |
| 1 | 1.8 | 部分满足 |
| 2 | 1.6 | 部分满足 |
| 3 | 1.4 | 明显缺失 |
| 5 | 1.0 | 明显缺失 |
| 10 | 0 | 明显缺失 |

---

## 五、ABCD分级系统（2568标注）

**文件**: `app/services/annotation_engine_2568.py`

### 5.1 设计原则
```
不打分、不排序、不自动剔除
只输出：结构标注、亮点总结、A/B/C/D分级、人工处理建议
```

### 5.2 硬性条件检查（5项）

| 检查项 | 通过条件 | 状态标签 |
|--------|----------|----------|
| MA25上行 | `ma25 > ma25_yesterday` | "✔ MA25 上行" / "✘ MA25 下弯" |
| MA60上行/走平 | `ma60 >= ma60_yesterday` | "✔ MA60 上行/走平" / "✘ MA60 下行" |
| 价格站上MA25 | `close >= ma25` | "✔ 站上 MA25" / "✘ 跌破 MA25" |
| 均量放量 | `vol_ma5 > vol_ma60` | "✔ 均量放量" / "✘ 均量不足" |
| 趋势结构健康 | `ma25 > ma60` | "✔ 趋势结构健康" / "✘ 趋势结构弱" |

**hard_ok** = 满足条件的数量（0-5）

### 5.3 亮点标签生成（4个维度）

> **注意**: 代码中实际显示文本带 emoji 符号，筛选/匹配需使用完整字符串。

#### 趋势亮点 `_trend_highlight()`
| 条件 | 亮点标签（代码实际值） | 等级 |
|------|------------------------|------|
| MA25上行 且 MA60上行 | `"⭐ 趋势双线共振"` | **A** |
| MA25上行 且 MA60走平 | `"🟦 趋势健康"` | **B** |
| MA25下弯 且 MA60上行 | `"⚠ 短期走弱但中期强"` | **D** |
| 其他 | `"❌ 趋势弱"` | **D** |

#### 量能亮点 `_volume_highlight()`
| 条件 | 亮点标签（代码实际值） | 等级 |
|------|------------------------|------|
| `vol_ratio >= 1.5` | `"🔥 强放量"` | **A** |
| `vol_ratio >= 1.2` | `"⭐ 放量良好"` | **B** |
| `vol_ratio >= 1.0` | `"~ 弱放量"` | **C** |
| `vol_ratio < 1.0` | `"✘ 无放量"` | **D** |

#### 结构亮点 `_structure_highlight()`
| 条件 | 亮点标签（代码实际值） | 等级 |
|------|------------------------|------|
| `ma25 > ma60` 且 `close > ma25` | `"🟩 结构强"` | **A** |
| `close > ma25` | `"🟦 结构一般"` | **B** |
| `close < ma25` | `"⚠ 结构破位"` | **D** |

#### 安全亮点 `_safety_highlight()`
| 条件 | 亮点标签（代码实际值） | 等级 |
|------|------------------------|------|
| 回踩确认（low在MA25和MA60之间） | `"🟩 回踩确认"` | **A** |
| 跌破MA25 | `"⚠ 跌破 MA25"` | **D** |
| 趋势双线共振 或 趋势健康 | `"🟦 趋势主升段"` | **B** |
| 其他 | `"~ 安全结构一般"` | **C** |

### 5.4 风险标签 `_risk_tags()`
| 风险条件 | 风险标签 |
|----------|----------|
| 名称含 "ST" | "⚠ ST 风险" |
| 连续3日缩量（vols[2]<vols[1]<vols[0]） | "⚠ 连续缩量" |
| `close < MA25` 且 单日跌幅 > 2% | "⚠ 跌破 MA25（大阴）" |
| `close/MA25 > 1.10`（加速超10%） | "⚠ 加速段（非买点）" |

### 5.5 ABCD分级规则 `_abcd_fields()`

| 等级 | 对应的亮点 | 判定规则 |
|------|-----------|----------|
| **A级** | "⭐ 趋势双线共振"、"🔥 强放量"、"🟩 结构强"、"🟩 回踩确认" | 最强信号 |
| **B级** | "🟦 趋势主升段"、"⭐ 放量良好"、"🟦 结构一般"、"🟦 趋势健康" | 良好信号 |
| **C级** | 以"~"开头的标签（弱放量、安全结构一般等） | 中性参考 |
| **D级** | 以"⚠"/"❌"/"✘"开头的标签 + 所有风险标签 + MA25下弯 + MA60下行 | 风险信号 |

### 5.6 人工处理建议 `manual_action_label`

| 条件 | 等级 | 人工建议 |
|------|------|----------|
| A >= 2 | A2+ | "强势票｜重点关注" |
| A == 1 | A1 | "有核心亮点｜可关注" |
| B >= 3 | B3+ | "中强票｜观察池" |
| B == 2 | B2 | "健康趋势｜可观察" |
| D >= 3 | D3+ | "风险较多｜建议移出" |
| D == 2 | D2 | "风险偏多｜谨慎观察" |
| D == 1 | D1 | "有风险｜人工确认" |
| 其他 | 普通 | "普通结构｜低优先级" |

### 5.7 总结标签 `summary_label`
```python
summary_label = "强满足" if hard_ok >= 4 and not risks else ("临界" if hard_ok >= 3 else "弱满足")
```

---

## 六、数据库表结构

### MySQL 核心表（`watchlist_decision_support`）

#### `structure_2560_analysis` — 信号分析结果

> **注意**: 表中还保留了兼容字段（signal_type/status/entry_price/stop_loss/target_price/confidence/reason），但主业务逻辑围绕以下字段运行。

| 字段 | 类型 | 说明 |
|------|------|------|
| `signal_uid` | VARCHAR(32) | MD5(code+signal_time+period+version) |
| `batch_id` | VARCHAR(64) | 批次ID |
| `code` / `name` | VARCHAR | 股票代码/名称 |
| `signal_time` | DATETIME | 信号时间 |
| `signal_period` | VARCHAR(10) | 信号周期（30m） |
| `price` | DOUBLE | 信号价格 |
| `has_2560_signal` | TINYINT(1) | 是否有2560信号 |
| `price_near_ma25` | TINYINT(1) | 价格贴近MA25 |
| `ma25_slope_ok` | TINYINT(1) | MA25斜率正常 |
| `volume_structure_ok` | TINYINT(1) | 量能结构满足 |
| `abnormal_filter_ok` | TINYINT(1) | 非异常K线 |
| `trend_price_ok` | TINYINT(1) | 趋势价格OK |
| `trend_slope_ok` | TINYINT(1) | 趋势斜率OK |
| `volatility_ok` | TINYINT(1) | 波动率充足 |
| `breakout_ok` | TINYINT(1) | 突破 |
| `volume_ok` | TINYINT(1) | 量能OK |
| `near_resistance` | TINYINT(1) | 接近压力位 |
| `pullback_ok` | TINYINT(1) | 回踩OK |
| `bullish_confirm` | TINYINT(1) | 阳线确认 |
| `structure_status` | VARCHAR(20) | "结构完整"/"部分满足"/"明显缺失"/"数据不足" |
| **`strength_score_raw`** | **DOUBLE** | **强度评分：max(0, 2.0 - missing_tag_count * 0.2)** |
| `missing_tags` | JSON | 缺失标签列表 |
| `missing_tag_count` | INT | 缺失标签数 |
| `explain_text` | TEXT | 说明文本 |
| `selected_signal` | TINYINT(1) | 是否选中信号 |
| `data_quality_status` | VARCHAR(30) | 数据质量 |
| *(兼容)* `signal_type` | VARCHAR(30) | 未使用 |
| *(兼容)* `status` | VARCHAR(20) | 默认 'active' |
| *(兼容)* `entry_price` | DOUBLE | 未使用 |
| *(兼容)* `stop_loss` | DOUBLE | 未使用 |
| *(兼容)* `target_price` | DOUBLE | 未使用 |
| *(兼容)* `confidence` | DOUBLE | 未使用 |
| *(兼容)* `reason` | TEXT | 未使用 |

#### `structure_2560_tag_detail` — 标签明细
| 字段 | 类型 | 说明 |
|------|------|------|
| `analysis_id` | BIGINT | 关联 analysis 主表 |
| `tag_code` | VARCHAR(50) | 标签代码（如 LACK_VOLUME） |
| `tag_name` | VARCHAR(100) | 标签名（如 #缺量） |
| `tag_type` | VARCHAR(50) | "negative" 或 "positive" |

#### `strategy_config` — 策略配置
| config_key | config_value | 说明 |
|------------|-------------|------|
| `ma_short` | 25 | 短期均线 |
| `ma_mid` | 60 | 中期均线 |
| `ma_long` | 200 | 长期均线 |
| `slope_periods` | 3 | 斜率周期 |
| `atp_period` | 14 | ATR周期 |
| `vol_short` | 5 | 短期均量 |
| `vol_long` | 60 | 长期均量 |
| `high_low_window` | 20 | 高低点窗口 |

### ClickHouse 表（`strategy2560`）
- `daily_kline`: 日线K线（code, date, OHLCV）
- `minute_kline_period`: 分钟K线（code, date, period=5m/30m, OHLCV）
- `technical_indicator`: 技术指标（MA25/MA60/ATR/量比/偏离率等24个字段）

---

## 七、关键文件索引

| 文件路径 | 核心职责 |
|----------|----------|
| `app/services/signal_engine_2560.py` | 2560逐股扫描引擎 |
| `app/services/signal_engine_2560_fast.py` | 2560 ClickHouse批量快速引擎 |
| `app/services/indicator_engine.py` | 技术指标计算（MA/ATR/量比） |
| `app/services/tag_service.py` | 标签构建/结构状态/解释文本 |
| `app/services/annotation_engine_2568.py` | ABCD标注与分级（804行） |
| `app/services/config_service.py` | 策略参数加载 |
| `app/services/strategy2560_service.py` | 查询服务（信号列表/统计/概览） |
| `app/services/statistics_engine.py` | 统计重建 |
| `app/services/report_2568_pdf.py` | PDF报告生成 |
| `app/services/data_freshness_service.py` | 数据完整性检测 |
| `app/api/strategy2560.py` | 2560 API路由（857行） |
| `app/api/strategy2568.py` | 2568 标注API |
| `app/db/repository.py` | 数据访问层（upsert/replace） |
| `sql/recreate_tables.sql` | MySQL表结构DDL |
| `sql/clickhouse_tables.sql` | ClickHouse表结构DDL |

---

## 八、业务流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    2560 信号扫描（漏斗）                          │
│                                                                 │
│  全市场股票 ──排除ST──▶ 日线+30m+5m指标计算                       │
│                              │                                  │
│              ┌───────────────┼───────────────┐                  │
│              ▼               ▼               ▼                  │
│         核心4条件        日线趋势         5m确认                │
│     ┌─────────────┐  ┌──────────┐  ┌──────────────┐            │
│     │价格贴MA25≤2%│  │收盘>MA60 │  │回踩MA25/阳线  │            │
│     │MA25斜率≥0  │  │斜率>0    │  │              │            │
│     │量比≥1.0    │  │ATR>ATR20*│  │              │            │
│     │非异常K线    │  │  0.85    │  │              │            │
│     └──────┬──────┘  └────┬─────┘  └──────┬───────┘            │
│            └──────────────┼───────────────┘                     │
│                           ▼                                     │
│              标签系统 tag_service.build_tags()                   │
│         11种标签（negative/positive）→ structure_status          │
│                           │                                     │
│              strength_score_raw = 2.0 - tag_count*0.2           │
│                           │                                     │
│                    写入 MySQL                                    │
│              structure_2560_analysis + tag_detail               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    2568 标注分级                                  │
│                                                                 │
│  5项硬性条件（MA25方向/MA60方向/价格位置/量能/趋势结构）            │
│                           │                                     │
│              4维亮点标签（趋势/量能/结构/安全）                    │
│                           │                                     │
│              A/B/C/D 亮点分级 + 风险标签                          │
│                           │                                     │
│     A≥2→重点关注  A≥1→可关注  B≥3→观察池                         │
│     D≥3→建议移出  D≥2→谨慎观察  D1→人工确认                      │
│                           │                                     │
│     summary_label: 强满足 / 临界 / 弱满足                         │
│                           │                                     │
│     PDF报告导出 (report_2568_pdf.py)                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 九、API接口

### 2560 策略 API（`/api/strategy/2560`）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/workspace` | 今日工作台（市场就绪/漏斗/观察池） |
| GET | `/overview` | 总览（最新批次+统计+标签分布） |
| GET | `/signals` | 信号列表（分页/筛选/标签过滤） |
| GET | `/signals/{signal_id}` | 信号详情 |
| GET | `/complete-cases` | 结构完整的案例 |
| GET | `/statistics` | 统计数据 |
| GET | `/batches` | 批次列表 |
| POST | `/run` | 运行2560分析（核心入口） |
| GET | `/funnel/{market}` | 单市场漏斗 |
| GET | `/funnel-all` | 全市场漏斗 |

### 2568 标注 API（`/api/strategy/2568`）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/annotations` | 标注列表（支持筛选） |
| GET | `/report.pdf` | PDF报告导出 |

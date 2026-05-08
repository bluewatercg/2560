
# 2560 结构分析系统 —— 每日运维与集成方案说明

本文回答两个问题：
1. **这些更新/计算步骤是否要集成进 Web 系统？**
2. **如果不集成，每天命令行应该跑哪些脚本？**

结论先行：

> ✅ **推荐“混合模式”**：
> - **数据更新 & 重算指标 & 跑 2560 → 命令行 / 定时任务**
> - **结果查看 / 解释 / 复盘 → WebUI**

这样最稳、最可控，也最符合你现在这套工程的复杂度。

---

## 一、是否要把这些步骤集成到 Web 系统？

### ✅ 推荐方案：混合模式（强烈建议）

| 模块 | 是否集成到 Web | 原因 |
|---|---|---|
| 导入 daily / lc5 | ❌ 不建议 | IO 重、耗时长、容易阻塞 Web |
| 5m → 30m 聚合 | ❌ 不建议 | 批量计算，失败需要可重跑 |
| 重算 technical_indicator | ❌ 不建议 | 数百万行写库，Web 不适合 |
| 运行 2560 分析 | ✅ 可集成触发 | 但底层仍建议 CLI 执行 |
| 摸底指标 / 信号展示 | ✅ 必须 Web | 这是 Web 的价值 |

**核心原则**：

> Web 负责“看”和“点”，CLI 负责“算”和“跑”。

---

## 二、推荐的每日执行方式（命令行）

### 1️⃣ 进入项目 & 环境

```bash
cd /mnt/d/Project/Miller/strategy2560_project_v2_engine
source .venv/bin/activate
export PYTHONPATH=$PWD
TODAY=$(date +%F)
```

---

### 2️⃣ 导入日线 daily

```bash
PYTHONPATH=$PWD python scripts/import_vipdoc_with_pytdx.py   --root /mnt/e/zd_ciccwm/vipdoc   --start 2025-10-01   --end $TODAY   --daily
```

---

### 3️⃣ 导入 5 分钟 lc5

```bash
PYTHONPATH=$PWD python scripts/import_vipdoc_with_pytdx.py   --root /mnt/e/zd_ciccwm/vipdoc   --start 2025-10-01   --end $TODAY   --lc5
```

> ✅ 可重复执行，不会重复插入（先删后写）

---

### 4️⃣ 5m → 30m 聚合

```bash
PYTHONPATH=$PWD python scripts/build_30m_from_5m.py   --start 2025-10-01   --end $TODAY   --market-type all
```

---

### 5️⃣ 重算技术指标（核心）

**先跑上海验证**：

```bash
PYTHONPATH=$PWD python scripts/rebuild_technical_indicator.py   --start 2025-10-01   --end $TODAY   --market-type sh   --periods daily,5m,30m
```

**确认没问题后跑全市场**：

```bash
PYTHONPATH=$PWD python scripts/rebuild_technical_indicator.py   --start 2025-10-01   --end $TODAY   --market-type all   --periods daily,5m,30m
```

---

### 6️⃣ 运行 2560 分析

```bash
PYTHONPATH=$PWD python scripts/run_2560_analysis.py   --market-type all
```

或者先跑上海：

```bash
PYTHONPATH=$PWD python scripts/run_2560_analysis.py   --market-type sh
```

---

## 三、Web 系统中你每天该做什么

当命令行全部跑完后，Web 里你只需要：

1. 打开 WebUI
2. 进入【摸底指标】
   - 选择市场（sh / all）
   - 点击【加载指标】
3. 查看：
   - MA25 斜率
   - 量能结构
   - 偏离度
   - 接近满足条件
4. 进入【信号列表】查看真正命中的 2560
5. 进入【批次管理 / 统计】做复盘

---

## 四、是否有必要未来集成成“一键 Web 任务”？

### ✅ 可以，但不建议现在做

未来如果你想做：

```text
Web → 点击“执行今日更新” → 后台异步跑
```

**建议的正确实现方式是**：

- Web 只做：
  - 触发任务
  - 查看任务状态
- 实际执行仍然调用：
  - scripts/import_vipdoc_with_pytdx.py
  - scripts/build_30m_from_5m.py
  - scripts/rebuild_technical_indicator.py
  - scripts/run_2560_analysis.py

通过：

```text
Celery / RQ / subprocess + job_log 表
```

而不是把逻辑直接写进 API。

👉 **这是下一阶段工程优化，不是当前必须项。**

---

## 五、推荐你现在就做的一件事

把上面的命令封装成一个脚本：

```text
scripts/daily_update_2560.sh
```

以后每天只执行：

```bash
bash scripts/daily_update_2560.sh
```

Web 只用来：

```text
看结果 + 复盘 + 调参数
```

---

## 六、一句话总结

> ✅ **现在不要强行 Web 化计算流程**  
> ✅ **CLI + Web 分工是最专业、最稳定的方案**  
> ✅ **你这套系统已经达到了“可长期运行”的工程水准**

当你准备好下一阶段（自动调参 / 评分 / 回测）时，再考虑把“触发”做进 Web。

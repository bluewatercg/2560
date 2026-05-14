# 2560 结构分析系统

面向 A 股行情复盘的结构化分析系统。核心流程：导入行情数据 → 计算技术指标 → 扫描 2560/2568 结构 → 通过 FastAPI + 单页 WebUI 查看批次、任务、信号和数据质量。

> 本系统仅用于结构化行情分析与历史复盘，不构成任何投资建议。

## 快速入口

| 地址 | 说明 |
|------|------|
| `http://localhost:8000` | WebUI 主界面 |
| `http://localhost:8000/docs` | Swagger API 文档 |
| `http://localhost:8000/health` | 系统健康检查 |

## 项目结构

```text
strategy2560_project_v2_engine/
├── app/
│   ├── main.py                 FastAPI 入口（路由注册、静态文件、/、/health）
│   ├── api/                    HTTP 路由
│   │   ├── strategy2560.py     2560 策略：概览/信号/批次/统计/质量
│   │   ├── strategy2568.py     2568 标注策略
│   │   ├── strategy2568_report.py  2568 PDF 报告
│   │   ├── latest.py           最新分析结果
│   │   ├── jobs.py             任务队列与执行记录
│   │   ├── import_data.py      行情数据导入
│   │   └── data_quality.py     数据质量检测
│   ├── core/                   配置（环境、数据库 URL）
│   ├── db/                     SQLAlchemy 会话和仓库
│   ├── schemas/                Pydantic 响应 schema
│   ├── services/               业务逻辑（指标、信号、统计、标注）
│   └── static/                 WebUI（原生 HTML/CSS/JS，无构建步骤）
│       ├── index.html          SPA 入口（10 个视图页）
│       ├── styles.css          主样式表（暗色主题）
│       ├── nested_menu_reorg.css    侧栏分组样式
│       ├── app.js              主逻辑（视图切换、API 调用、渲染）
│       ├── nested_menu_reorg.js     侧栏手风琴菜单
│       ├── data_import_page.js      数据导入页面
│       ├── data_import_type_addon.js  导入类型扩展
│       ├── job_progress_monitor.js    任务进度监控
│       ├── jobs_actions.js          任务操作面板
│       ├── jobs_page_bootstrap.js   任务页引导
│       ├── annotation2568.js        2568 标注
│       └── ...                      其他模块
├── scripts/
│   ├── job_worker.py            后台队列 worker
│   ├── progress_run_now.py      2560 并行 runner
│   ├── import_job_runner.py     导入后台执行器
│   ├── build_30m_from_5m.py     5m → 30m 聚合
│   ├── rebuild_technical_indicator.py  指标重算
│   ├── rebuild_statistics.py    统计重建
│   ├── run_2560_analysis.py     旧 CLI（不绕过队列使用）
│   └── sync_vipdoc_to_server.*  行情同步脚本
├── .planning/codebase/          架构文档
├── design-system/               前端设计系统
├── Dockerfile                   镜像构建
├── docker-compose.yml           编排（web + worker）
├── requirements.txt             Python 依赖
└── requirements-dev.txt         开发依赖
```

## 本地运行

```bash
cd strategy2560_project_v2_engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$PWD
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Docker 运行

```bash
docker build -t strategy2560:latest .
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml logs -f web
```

Compose 服务（5 worker 架构）：

| 服务 | 职责 | 环境变量 |
|------|------|------|
| `web` | FastAPI + WebUI，端口 8000 | — |
| `worker-data` | 数据导入 / 30m / 指标重算 | — |
| `worker-sh60` | 只跑 sh60 2560 | `WORKER_MARKET=sh60` |
| `worker-sh68` | 只跑 sh68 2560 | `WORKER_MARKET=sh68` |
| `worker-sz00` | 只跑 sz00 2560 | `WORKER_MARKET=sz00` |
| `worker-sz30` | 只跑 sz30 2560 | `WORKER_MARKET=sz30` |

行情数据通过 `./zd_ciccwm/vipdoc` 挂载到容器 `/data/vipdoc:ro`。

**Market Lane 机制：**
- 每个 market worker 只消费 `WORKER_MARKET` 匹配的任务
- 同 market 同一时间只允许一个 `run_2560` running
- 任务领取使用 `FOR UPDATE SKIP LOCKED` 避免多 worker 争抢
- UI 一键运行四类时，后台创建 4 个 market 任务各自独立

## WebUI 功能

### 视图页

| 视图 | 说明 |
|------|------|
| **首页总览** | 信号总数、结构完整率、标签分布、最新批次 |
| **工作流说明** | 每天使用流程指引：数据准备 → 指标计算 → 任务执行 → 结果查看 |
| **自选股计算** | 搜索/筛选股票、手动计算单只或少量 |
| **信号中心** | 历史信号列表，支持按代码/状态/标签筛选，点击查看详情 |
| **最新结果** | 每只股票最近一次分析状态 |
| **创建批量任务** | 全市场/分市场后台批量扫描，支持分片和优先级 |
| **当前执行进度** | 实时进度条 + Shard 汇总 + 后台日志 |
| **批次管理** | 分析批次列表 |
| **市场统计** | 按状态/标签/行业/板块统计 |
| **数据质量** | 日线/分钟线完整性检测 |

### 数据导入（独立入口）

| 功能 | 说明 |
|------|------|
| **导入前检查** | 扫描 `/data/vipdoc` 源文件日期范围 |
| **发起导入** | 选择市场、类型（日线/5m/全部）、日期范围、并发数 |
| **批次/日志** | 导入批次追踪、实时进度、Shard 汇总、文件明细 |
| **30m 构建** | 从 5m 聚合生成 30m 数据 |
| **指标重算** | 重建 `daily/5m/30m` 技术指标 |

### 任务队列

| 功能 | 说明 |
|------|------|
| **创建任务** | 选择市场、分片数、优先级，后台批量执行 |
| **执行记录** | 进度追踪、状态、开始/结束时间 |
| **Shard 汇总** | 每组并发线程的完成进度、成功/失败数 |
| **任务明细** | 每只股票的执行状态和错误信息 |
| **自动刷新** | 运行中任务每 5 秒自动刷新 |

## 侧栏导航交互

左侧菜单采用**手风琴分组**模式：

- **3 个顶层按钮**：首页总览 / 工作流说明 / 自选股计算（始终可见）
- **4 个折叠分组**：数据导入 / 计算任务 / 分析结果 / 系统诊断（默认折叠）
- **点击标题**：展开该分组，同时折叠其他分组（手风琴）
- **点击已展开标题**：折叠该分组
- **点击折叠分组内子项**：自动展开该分组并折叠其他
- **键盘支持**：标题支持 `Enter`/`Space` 切换折叠状态

## 前端技术栈

- **纯 HTML/CSS/JS**，无构建步骤，无框架依赖
- **SPA 架构**：`index.html` 单页 + 视图切换
- **FastAPI StaticFiles** 直接服务静态文件
- **暗色主题**（OLED）：深色背景 + 高对比文字
- **字体**：Fira Code（标题）+ Fira Sans（正文），通过 Google Fonts 加载
- **响应式**：1100px / 760px 两个断点
- **无障碍**：`focus-visible` 状态、`prefers-reduced-motion` 支持

## 数据流

```
中金客户端（盘后下载）
  → E:\zd_ciccwm\vipdoc
  → sync_vipdoc_to_server 同步到服务器 /data/vipdoc
  → WebUI 数据导入页（扫描 → 导入 → 构建30m → 重算指标）
  → WebUI 任务队列（2560 批量扫描）
  → 结果查看（信号/最新/批次）
```

## 常用命令

```bash
# 测试数据库连接
PYTHONPATH=$PWD python -c "from app.db.session import ping_database; print(ping_database())"

# 后台 worker 正式执行 2560 队列任务
PYTHONPATH=$PWD python scripts/job_worker.py

# 本地小批量验证（需要先有 job_execution.id）
JOB_ID=1 MARKET=sh60 LIMIT_CODES=20 PYTHONPATH=$PWD python scripts/progress_run_now.py

# 启动 WebUI
export PYTHONPATH=$PWD
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 盘后行情同步

1. Windows 中金客户端执行盘后数据下载
2. 同步 vipdoc 到服务器（PowerShell 或 bash）
3. WebUI 数据导入页扫描并导入
4. 构建 30m → 重算指标 → 创建批量任务跑 2560

## 设计系统

详见 `design-system/MASTER.md`。

- 主题：Dark Mode (OLED)
- 色板：背景 `#020617` / 面板 `#1E293B` / 主色 `#3B82F6` / 强调 `#22C55E`
- 字体：Fira Code / Fira Sans
- 过渡：200ms ease-out
- 无障碍：4.5:1 对比度、focus-visible、prefers-reduced-motion

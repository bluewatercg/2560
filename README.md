# Strategy2560 v2 Engine

面向 A 股行情复盘的结构化分析系统。核心流程：**导入行情数据 → 计算技术指标 → 扫描 2560/2568 结构 → WebUI 查看结果**。

> 本系统仅用于结构化行情分析与历史复盘，不构成任何投资建议。

## 快速入口

| 地址 | 说明 |
|------|------|
| `http://localhost:8000` | WebUI 主界面 |
| `http://localhost:8000/docs` | Swagger API 文档 |
| `http://localhost:8000/health` | 系统健康检查 |

## 架构概览

```
┌─────────────────┐    ┌──────────────────┐    ┌────────────────────┐
│  Windows 中金    │    │  192.168.1.18    │    │  192.168.1.254     │
│  E:\vipdoc      │───▶│  ClickHouse      │◀──▶│  MySQL             │
│  (盘后下载)      │sync│  (行情存储)       │    │  (任务/分析结果)     │
└─────────────────┘    └──────────────────┘    └────────────────────┘
                              ▲                       ▲
                              │                       │
                    ┌─────────┴───────────────────────┴─────────┐
                    │              FastAPI + WebUI               │
                    │  导入 → 指标 → 扫描 → 信号 → 统计 → 标注    │
                    └───────────────────────────────────────────┘
```

## 核心特性

- **双存储架构**：ClickHouse 存储行情数据（高吞吐写入），MySQL 存储任务队列/分析结果/配置
- **四市场并行导入**：sh60/sh68/sz00/sz30 独立 job，每市场可配置并发线程数（默认 32）
- **多卡进度 UI**：页面自动检测正在运行的导入，每张卡显示市场名称、批次号、状态、并发数、完成进度
- **五 Worker 编排**：1 个 web + 1 个 data worker + 4 个 market worker，通过 `WORKER_MARKET` 隔离
- **2560 结构扫描**：基于 MA25/MA60/MA200、ATR14、成交量结构的多条件漏斗扫描
- **2568 标注系统**：A/B/C/D 分级标注，支持 PDF 报告导出

## 项目结构

```
strategy2560_project_v2_engine/
├── app/
│   ├── main.py                      FastAPI 入口
│   ├── api/
│   │   ├── strategy2560.py          2560 策略：概览/信号/批次/漏斗/统计
│   │   ├── strategy2568.py          2568 标注（A/B/C/D 分级）
│   │   ├── strategy2568_report.py   2568 PDF 报告导出
│   │   ├── latest.py                最新分析结果（按股票）
│   │   ├── jobs.py                  任务队列：创建/进度/Shard/取消
│   │   ├── import_data.py           行情导入：扫描/导入/30m/指标重算
│   │   └── data_quality.py          数据质量检测
│   ├── core/
│   │   ├── config.py                Pydantic 设置（MySQL/ClickHouse/Redis）
│   │   ├── market_scope.py          市场前缀（sh60/sh68/sz00/sz30）、SQL WHERE 辅助
│   │   └── redis_client.py          Redis 客户端（可选，导入进度缓冲）
│   ├── db/
│   │   ├── session.py               SQLAlchemy 引擎、会话管理
│   │   ├── clickhouse.py            ClickHouse HTTP 客户端
│   │   └── repository.py            KlineRepository（查询/写入封装）
│   ├── schemas/
│   │   └── common.py                ApiResponse 统一响应模型
│   ├── services/
│   │   ├── strategy2560_service.py  信号/批次/统计查询
│   │   ├── signal_engine_2560.py    2560 扫描引擎（核心）
│   │   ├── indicator_engine.py      技术指标计算（MA/ATR/成交量）
│   │   ├── annotation_engine_2568.py 2568 标注与分级
│   │   ├── statistics_engine.py     统计重建
│   │   ├── config_service.py        策略配置加载
│   │   ├── tag_service.py           标签构建/结构状态/解释文本
│   │   ├── data_freshness_service.py 数据完整性检测
│   │   ├── workspace_service.py     工作区状态缓存（4 行市场就绪标记）
│   │   ├── job_orchestrator.py      任务队列 CRUD / 批次追踪
│   │   └── report_2568_pdf.py       PDF 报告生成（reportlab + 中文字体）
│   └── static/                      SPA WebUI（纯 HTML/CSS/JS，无构建）
│       ├── index.html               主页面（10+ 视图）
│       ├── styles.css               暗色主题
│       ├── app.js                   主逻辑
│       ├── data_import_page.js      数据导入（多卡进度）
│       ├── data_import_type_addon.js 导入类型增强
│       ├── job_progress_monitor.js  任务进度轮询
│       ├── jobs_actions.js          任务操作
│       ├── observation_pool.js      观察池展示
│       └── annotation2568.js        2568 标注 UI
├── scripts/
│   ├── job_worker.py                后台队列 worker（市场感知）
│   ├── import_job_runner.py         导入执行器（vipdoc → ClickHouse）
│   ├── import_vipdoc_clickhouse.py  vipdoc 解析 + ClickHouse 批量写入
│   ├── build_30m_from_5m.py         5m → 30m 聚合引擎
│   ├── build_30m_job_runner.py      30m 构建包装器
│   ├── rebuild_technical_indicator.py 指标重算 CLI
│   ├── rebuild_indicator_job_runner.py 指标重算包装器
│   ├── rebuild_statistics.py        统计重建
│   ├── progress_run_now.py          高性能并行 2560 执行器
│   ├── load_deploy.sh               Docker 镜像加载 + 重启
│   └── sync_vipdoc_to_server.*      行情同步脚本（sh/ps1）
├── sql/
│   ├── recreate_tables.sql          MySQL 表结构（21 表 + 种子数据）
│   └── clickhouse_tables.sql        ClickHouse 表结构（3 表）
├── docs/
│   ├── DATABASE_SCHEMA.md           MySQL 详细表结构
│   ├── CLICKHOUSE_INSTALL.md        ClickHouse 安装指南
│   ├── DEPLOYMENT.md                部署文档
│   └── REFACTORING_ROADMAP.md       重构路线图
├── Dockerfile
├── docker-compose.yml               编排（web + 5 workers）
├── requirements.txt
└── .env.example
```

## 环境依赖

| 组件 | 地址 | 用途 |
|------|------|------|
| MySQL | `192.168.1.254:3306` | 任务队列、分析结果、配置、导入追踪 |
| ClickHouse | `192.168.1.18:8123` | 行情数据存储（daily_kline、minute_kline、technical_indicator）|
| Redis | `192.168.1.160:6379` | 导入进度缓冲（可选，默认关闭）|
| vipdoc | `/data/vipdoc` | 通达信行情文件目录（只读挂载）|

## 本地运行

```bash
cd strategy2560_project_v2_engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$PWD
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Docker 部署

### 1. 构建镜像

```bash
docker build -t strategy2560:latest .
```

### 2. 配置环境

```bash
cp .env.example .env
# 编辑 .env，填入 MySQL/ClickHouse/Redis 连接信息
```

### 3. 启动服务

```bash
docker compose up -d
docker compose ps
```

### 4. 18 服务器更新

```bash
# 本地构建并保存镜像
docker save strategy2560:latest > /tmp/strategy2560_$(date +%Y%m%d_%H%M%S).tar

# 或使用 CI 生成的 tar.gz 产物
scp strategy2560_*.tar.gz user@192.168.1.18:/tmp/

# 在 18 服务器上加载并重启
ssh user@192.168.1.18
cd /data1/2560/strategy2560_project_v2_engine
./scripts/load_deploy.sh /tmp/strategy2560_xxx.tar.gz

# 验证
docker compose ps
docker compose logs -f web
curl http://127.0.0.1:8000/health
```

## 完整数据流

```
1. Windows: CICC 客户端盘后下载 → E:\zd_ciccwm\vipdoc
2. 同步: sync_vipdoc_to_server.sh → 192.168.1.18:/data/vipdoc
3. 扫描: POST /api/import/scan → 确认文件日期范围
4. 导入: POST /api/import/run → 创建 4 个独立 job（sh60/sh68/sz00/sz30）
   ├─ worker-data 执行 import_vipdoc
   ├─ 每个文件解析后写入 ClickHouse（daily_kline 或 minute_kline_period）
   └─ 后台 reporter 每 2s 更新 MySQL 进度
5. 构建 30m: POST /api/import/build-30m → 从 5m 聚合 30m K 线
6. 重算指标: POST /api/import/rebuild-indicators → 计算 technical_indicator
7. 运行 2560: /api/jobs/enqueue 或一键运行四类 → 4 个 market worker 并行扫描
   └─ 结果写入 structure_2560_analysis + structure_2560_tag_detail
```

## 盘后行情同步

1. Windows 中金客户端执行盘后数据下载
2. 同步 vipdoc 到服务器：
   ```bash
   ./scripts/sync_vipdoc_to_server.sh /mnt/e/zd_ciccwm/vipdoc user@192.168.1.18:/data1/2560/zd_ciccwm/vipdoc
   ```
3. WebUI 数据导入页：扫描 → 导入 → 构建 30m → 重算指标 → 创建批量任务

## Compose 服务架构

| 服务 | 容器 | 命令 | 市场 | 职责 |
|------|------|------|------|------|
| `web` | strategy2560-web | uvicorn | — | FastAPI + WebUI，端口 8000 |
| `worker-data` | strategy2560-worker-data | job_worker.py | 无 | 数据导入 / 30m 构建 / 指标重算 |
| `worker-sh60` | strategy2560-worker-sh60 | job_worker.py | sh60 | 沪主板 2560 扫描 |
| `worker-sh68` | strategy2560-worker-sh68 | job_worker.py | sh68 | 科创板 2560 扫描 |
| `worker-sz00` | strategy2560-worker-sz00 | job_worker.py | sz00 | 深主板 2560 扫描 |
| `worker-sz30` | strategy2560-worker-sz30 | job_worker.py | sz30 | 创业板 2560 扫描 |

### Market Lane 机制

- 每个 market worker 只消费 `WORKER_MARKET` 匹配的任务
- 同 market 同一时间只允许一个 `run_2560` 运行（去重检查）
- 任务领取使用 `FOR UPDATE SKIP LOCKED` 避免多 worker 争抢
- UI 一键运行四类时，后台创建 4 个独立任务（每市场一个 batch + job）

## 前端架构

- **纯 HTML/CSS/JS**，无构建步骤，无框架依赖
- **SPA 架构**：`index.html` 单页 + JS 视图切换
- **暗色主题**（OLED）：深色背景 + 高对比文字
- **手风琴分组侧栏**：3 个顶层按钮 + 4 个折叠分组
- **多卡进度 UI**：页面加载自动检测运行中导入，每市场一张进度卡
- **响应式**：1100px / 760px 两个断点

## 常用命令

```bash
# 测试数据库连接
PYTHONPATH=$PWD python -c "from app.db.session import ping_database; ping_database()"

# 后台 worker 执行队列任务
PYTHONPATH=$PWD python scripts/job_worker.py

# 本地小批量验证
JOB_ID=1 MARKET=sh60 LIMIT_CODES=20 PYTHONPATH=$PWD python scripts/progress_run_now.py

# ClickHouse 直接导入（不经过 MySQL 任务队列）
PYTHONPATH=$PWD python scripts/import_vipdoc_clickhouse.py --source-dir /data/vipdoc --market sh60 --workers 4

# 查看 worker 日志
docker compose logs -f worker-sh60
docker compose logs -f worker-data

# 查看实时 job 日志
curl http://localhost:8000/api/jobs/executions/14/logs?tail=200
```

## API 参考

| 前缀 | 说明 |
|------|------|
| `/api/strategy/2560` | 2560 策略：概览/信号/漏斗/批次/统计 |
| `/api/strategy/2568` | 2568 标注（A/B/C/D 分级）|
| `/api/jobs` | 任务队列：创建/进度/Shard/取消 |
| `/api/import` | 行情导入：扫描/导入/30m/指标重算 |
| `/api/latest` | 最新分析结果 |
| `/api/data-quality` | 数据质量 |
| `/health` | 系统健康（DB + ClickHouse 连通性）|
| `/docs` | Swagger 自动 API 文档 |

## 设计系统

详见 `design-system/MASTER.md`。

- 主题：Dark Mode (OLED)
- 色板：背景 `#020617` / 面板 `#1E293B` / 主色 `#3B82F6` / 强调 `#22C55E`
- 字体：Fira Code（标题）+ Fira Sans（正文）
- 过渡：200ms ease-out
- 无障碍：4.5:1 对比度、focus-visible、prefers-reduced-motion

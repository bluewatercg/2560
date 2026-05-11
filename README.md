# 2560 结构分析系统

本项目是一个面向 A 股行情复盘的结构化分析系统。核心流程是导入行情数据、计算技术指标、扫描 2560/2568 结构，并通过 FastAPI + 单页 WebUI 查看批次、任务、信号和数据质量。

> 本系统仅用于结构化行情分析与历史复盘，不构成任何投资建议。

## 当前主入口

- Web 服务入口：`app/main.py`
- 前端入口：`app/static/index.html`
- 主要依赖：`requirements.txt`
- Docker 镜像：`Dockerfile`
- Docker 编排：`docker-compose.yml`
- 后台 worker：`scripts/job_worker.py`
- 并行任务 runner：`scripts/progress_run_now.py`

`docker-compose.yml` 是当前保留的唯一 Compose 文件；历史 `compose.yaml`、`Dockerfile.prod`、旧部署说明和补丁脚本已清理。

## 本次清理说明

清理目标是让仓库只保留当前主运行链路，减少历史补丁包、重复部署入口和过期说明造成的歧义。

已保留：

- `Dockerfile`：唯一镜像构建入口。
- `docker-compose.yml`：唯一 Compose 编排入口，按当前最新部署方式保留。
- `requirements.txt`：唯一 Python 依赖入口。
- `README.md`：唯一项目主说明。
- `.planning/codebase/`：当前架构和代码结构说明。

已移除：

- 重复部署入口：`compose.yaml`、`Dockerfile.prod`。
- 重复依赖文件：`requirements.backend.txt`。
- 旧说明文件：`PROJECT_OVERVIEW.md`、`README_DOCKER_DEPLOY.md`、`README_2560_DAILY_OPS.md`、`README_FINAL_REORG_DEPLOY.md`、`docs/README_V2.4.md`。
- 历史补丁脚本：`scripts/apply_*_patch.py`。
- 旧前端备份：`app/static/index.html.bak_*`。
- 生成报告：`BUILD_REPORT.json`、`PATCH_REPORT.json`。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export PYTHONPATH=$PWD
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问：

```text
http://localhost:8000
http://localhost:8000/docs
http://localhost:8000/health
```

如果需要初始化数据库，`scripts/apply_schema.py` 会读取 `sql/2560_schema_v2.4.sql`。当前仓库未包含 `sql/` 目录，部署前需要确认数据库 schema 已在目标环境准备好，或补回对应 SQL 文件。

## Docker 运行

```bash
docker build -t strategy2560:latest .
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml logs -f web
```

`docker-compose.yml` 定义：

- `web`：FastAPI + WebUI，监听 `APP_PORT`，默认 8000。
- `worker`：后台任务 worker，执行 `scripts/job_worker.py`。
- `./logs`：挂载到容器 `/app/logs`。
- `./zd_ciccwm/vipdoc`：按当前 compose 文件挂载到 `/data/vipdoc:ro`。

## 常用命令

```bash
# 测试数据库连接
PYTHONPATH=$PWD python -c "from app.db.session import ping_database; print(ping_database())"

# 手动运行少量 2560 分析
PYTHONPATH=$PWD python scripts/run_2560_analysis.py --limit 20

# 指定股票代码
PYTHONPATH=$PWD python scripts/run_2560_analysis.py --codes 000001,600000

# 启动 WebUI
bash scripts/start_webui.sh
```

## 目录结构

```text
app/
  main.py                  FastAPI 应用入口
  api/                     HTTP 路由：策略、任务、导入、数据质量、报告
  core/                    环境配置
  db/                      SQLAlchemy 会话和数据访问
  schemas/                 Pydantic schema
  services/                指标、信号、统计、标注、PDF 等业务逻辑
  static/                  原生 HTML/CSS/JS WebUI

scripts/
  run_2560_analysis.py     2560 分析 CLI
  job_worker.py            后台队列 worker
  progress_run_now.py      并行任务 runner
  import_vipdoc_with_pytdx.py
  build_30m_from_5m.py
  rebuild_technical_indicator.py
  rebuild_statistics.py

.planning/codebase/        当前代码结构和架构说明
.github/workflows/         Docker 镜像构建 workflow
docker-compose.yml         当前 Docker Compose 入口
Dockerfile                 当前镜像构建入口
requirements.txt           当前 Python 依赖入口
```

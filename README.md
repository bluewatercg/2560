# Strategy2560 v2 Engine

面向 A 股盘后复盘的结构化分析系统。核心链路是：

```text
行情导入 -> 指标计算 -> 2560/2568 分析 -> 报告产物 -> WebUI/Skill 使用
```

本项目用于结构化行情分析与历史复盘，不构成投资建议。

## 主要入口

- WebUI: `http://localhost:8000`
- API 文档: `http://localhost:8000/docs`
- 健康检查: `http://localhost:8000/health`

## 当前代码结构

```text
app/
  api/        FastAPI 路由层
  core/       配置与基础能力
  db/         MySQL / ClickHouse 访问封装
  services/   2560/2568、报告、早盘确认等业务服务
  static/     原生 HTML/CSS/JS 前端
scripts/      导入、重算、批处理、部署脚本
sql/          MySQL / ClickHouse 表结构
tests/        pytest 测试
docs/         业务规则、部署、数据库、执行计划
reports/      按交易日生成的报告产物
```

## 核心运行方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$PWD
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 常用命令

```bash
# 数据库连通性
PYTHONPATH=$PWD python -c "from app.db.session import ping_database; ping_database()"

# 启动任务 worker
PYTHONPATH=$PWD python scripts/job_worker.py

# 本地小批量验证 2560
JOB_ID=1 MARKET=sh60 LIMIT_CODES=20 PYTHONPATH=$PWD python scripts/progress_run_now.py

# 直接导入 vipdoc
PYTHONPATH=$PWD python scripts/import_vipdoc_clickhouse.py --source-dir /data/vipdoc --market sh60 --workers 4
```

## 文档导航

- 代码结构、文档地图、代理执行计划：`docs/PROJECT_STRUCTURE_AND_AGENT_PLAN.md`
- 业务目标规则源：`docs/2560短线结构算法统一改造方案_v1.2.2_FinalFreeze.md`
- 报告驱动工作流设计：`docs/2560_v1.2.2_报告驱动工作流设计_完整版.md`
- 数据库说明：`docs/DATABASE_SCHEMA.md`
- 部署说明：`docs/DEPLOYMENT.md`

## 当前约定

- `project.md` 不再作为项目主说明入口。
- `docs/superpowers/plans/` 下的文档用于代理执行，不作为项目概览文档。

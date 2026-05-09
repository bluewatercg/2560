# 2560结构分析系统完整项目

本项目是一个完整可启动版本，包含：

- FastAPI 后端
- MySQL 连接与连接池
- 2560 核心计算引擎
- 技术指标计算
- 标签与解释文本生成
- 批次、统计、数据质量 API
- WebUI 单页看板
- 数据库建表脚本

> 本系统仅用于结构化行情分析与历史复盘，不构成任何投资建议。

## 1. 启动步骤

```bash
cd strategy2560_project_complete
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入真实 DB_PASSWORD
export PYTHONPATH=$PWD
python scripts/apply_schema.py
python scripts/run_2560_analysis.py --limit 20
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问：

```text
http://localhost:8000
http://localhost:8000/docs
```

## 2. 常用命令

```bash
# 测试数据库连接
python -c "from app.db.session import ping_database; print(ping_database())"

# 跑少量标的
python scripts/run_2560_analysis.py --limit 20

# 指定代码
python scripts/run_2560_analysis.py --codes 000001,600000

# 启动 WebUI
bash scripts/start_webui.sh
```

rsync -av --progress --prune-empty-dirs \
      --include='*/' \
      --include='sh60*' \
      --include='sh68*' \
      --include='sz00*' \
      --include='sz30*' \
      --exclude='*' \
      /mnt/e/zd_ciccwm/vipdoc/ user@192.168.1.18:/data1/2560/zd_ciccwm/vipdoc/

scp /mnt/c/Users/miller/Downloads/strategy2560_feature-v8-job-queue-ui-ee22b12f.tar.gz user@192.168.1.18:/tmp/

## 3. 目录结构

```text
app/main.py                         FastAPI入口
app/api/strategy2560.py             2560 API
app/api/data_quality.py             数据质量 API
app/db/session.py                   数据库连接
app/db/repository.py                数据访问层
app/services/indicator_engine.py    指标计算
app/services/signal_engine_2560.py  2560核心引擎
app/services/tag_service.py         标签与解释
app/services/statistics_engine.py   统计生成
app/static/                         WebUI
scripts/apply_schema.py             建表
scripts/run_2560_analysis.py        运行引擎
sql/2560_schema_v2.4.sql            数据库DDL
```

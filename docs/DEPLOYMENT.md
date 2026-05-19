# 部署指南

> **更新日期:** 2026-05-19
> **架构:** Docker Compose（1 web + 1 data worker + 4 market lane workers）
> **基础镜像:** python:3.11-slim

---

## 环境要求

| 组件 | 版本/地址 | 说明 |
|------|-----------|------|
| Docker | 24.0+ | 宿主机或 18 服务器 |
| Docker Compose | v2.0+ | `docker compose` 命令 |
| MySQL | `192.168.1.254:3306` | 任务队列/分析结果/配置 |
| ClickHouse | `192.168.1.18:8123` | 行情数据存储 |
| Redis | `192.168.1.160:6379` | 导入进度缓冲（可选）|
| vipdoc | `/data/vipdoc` 或本地挂载 | 通达信行情文件目录 |
| 内存 | ≥ 4GB | 单容器约 200MB，6 容器共 ~1.2GB |
| 磁盘 | ≥ 5GB | 镜像 ~800MB，日志/临时文件 |

---

## 快速部署

### 1. 构建镜像

```bash
cd strategy2560_project_v2_engine
docker build -t strategy2560:latest .
```

### 2. 配置环境

```bash
cp .env.example .env
# 编辑 .env，填入以下关键配置：
```

| 环境变量 | 必填 | 说明 |
|----------|------|------|
| `MYSQL_HOST` | 是 | MySQL 地址，默认 `192.168.1.254` |
| `MYSQL_PORT` | 是 | MySQL 端口，默认 `3306` |
| `MYSQL_USER` | 是 | 数据库用户名 |
| `MYSQL_PASSWORD` | 是 | 数据库密码 |
| `MYSQL_DATABASE` | 是 | 数据库名，默认 `watchlist_decision_support` |
| `CLICKHOUSE_HOST` | 是 | ClickHouse 地址，默认 `192.168.1.18` |
| `CLICKHOUSE_PORT` | 是 | HTTP 端口，默认 `8123` |
| `CLICKHOUSE_USER` | 是 | 用户名，默认 `default` |
| `CLICKHOUSE_PASSWORD` | 是 | 密码 |
| `CLICKHOUSE_DATABASE` | 是 | 数据库名，默认 `strategy2560` |
| `REDIS_HOST` | 否 | Redis 地址（可选，不填则禁用）|
| `REDIS_PORT` | 否 | Redis 端口，默认 `6379` |
| `REDIS_PASSWORD` | 否 | Redis 密码 |
| `APP_PORT` | 否 | Web 端口，默认 `8000` |

### 3. 初始化数据库

首次部署需执行 MySQL 表结构：

```bash
mysql -h 192.168.1.254 -u root -p watchlist_decision_support < sql/recreate_tables.sql
```

初始化 ClickHouse 表结构：

```bash
curl -s "http://192.168.1.18:8123/?password=YOUR_PASSWORD&database=strategy2560" \
  --data-binary @sql/clickhouse_tables.sql
```

### 4. 启动服务

```bash
docker compose up -d
docker compose ps
```

期望输出 6 个容器：

```
NAME                         STATUS
strategy2560-web             Up (healthy)
strategy2560-worker-data     Up
strategy2560-worker-sh60     Up
strategy2560-worker-sh68     Up
strategy2560-worker-sz00     Up
strategy2560-worker-sz30     Up
```

### 5. 验证

```bash
# 健康检查
curl http://localhost:8000/health

# 预期返回: {"status":"ok","mysql":"connected","clickhouse":"connected"}

# WebUI
open http://localhost:8000

# API 文档
open http://localhost:8000/docs
```

---

## 18 服务器更新流程

### 本地构建并传输

```bash
# 本地构建
docker build -t strategy2560:latest .
docker save strategy2560:latest | gzip > /tmp/strategy2560_$(date +%Y%m%d_%H%M%S).tar.gz

# 传输到 18 服务器
scp /tmp/strategy2560_*.tar.gz user@192.168.1.18:/tmp/
```

### 18 服务器加载

```bash
ssh user@192.168.1.18
cd /data1/2560/strategy2560_project_v2_engine

# 加载镜像并重启
./scripts/load_deploy.sh /tmp/strategy2560_xxx.tar.gz

# 验证
docker compose ps
docker compose logs -f web
curl http://127.0.0.1:8000/health
```

### 回滚

```bash
# 加载旧版本镜像
docker load -i /tmp/strategy2560_旧版本.tar.gz
docker tag strategy2560:旧版本 strategy2560:latest

# 重新部署
docker compose down
docker compose up -d
```

---

## Compose 服务架构

| 服务 | 容器名 | 职责 | 市场 | 命令 |
|------|--------|------|------|------|
| `web` | strategy2560-web | FastAPI + WebUI | — | `uvicorn app.main:app` |
| `worker-data` | strategy2560-worker-data | 数据导入 / 30m 构建 / 指标重算 | 无 | `python scripts/job_worker.py` |
| `worker-sh60` | strategy2560-worker-sh60 | 2560 结构扫描 | sh60 | `python scripts/job_worker.py` |
| `worker-sh68` | strategy2560-worker-sh68 | 2560 结构扫描 | sh68 | `python scripts/job_worker.py` |
| `worker-sz00` | strategy2560-worker-sz00 | 2560 结构扫描 | sz00 | `python scripts/job_worker.py` |
| `worker-sz30` | strategy2560-worker-sz30 | 2560 结构扫描 | sz30 | `python scripts/job_worker.py` |

### Market Lane 隔离规则

- 每个 market worker 通过 `WORKER_MARKET` 环境变量绑定单一市场
- 只消费 `market` 字段精确匹配的任务
- `market=all` 的任务不会被任何单个 market worker 消费（需在 API 层拆分为 4 个独立任务）
- 同 market 同一时间只允许一个 `run_2560` 运行（通过 `FOR UPDATE SKIP LOCKED` 实现）

---

## 日志排查

```bash
# 查看特定服务日志
docker compose logs -f web
docker compose logs -f worker-sh60

# 查看最近 100 行
docker compose logs --tail=100 worker-data

# 查看实时 job 执行日志
curl "http://localhost:8000/api/jobs/executions/14/logs?tail=200"

# 进入容器调试
docker exec -it strategy2560-web bash
```

---

## 常用运维命令

```bash
# 停止所有服务
docker compose down

# 停止并清理数据卷
docker compose down -v

# 重建镜像
docker compose build --no-cache

# 查看资源使用
docker stats

# 清理无用镜像
docker image prune -a
```

---

## 数据目录结构

```
strategy2560_project_v2_engine/
├── logs/           # 运行时日志（挂载到容器内 /app/logs）
├── sql/            # 表结构 DDL（挂载到容器内 /app/sql）
├── zd_ciccwm/vipdoc/  # 通达信行情文件（只读挂载到 /data/vipdoc）
└── .env            # 环境变量（不提交到 git）
```

---

## 性能调优

### 导入并发数

在 WebUI 数据导入页面选择并发数，默认每个市场 32 线程。可根据服务器 CPU 核心数调整：

- 4 核: 建议 8-16 并发
- 8 核: 建议 16-32 并发
- 16 核+: 建议 32-64 并发

### 全市场导入吞吐量

4 市场 × 32 并发 = 128 文件并行处理。
单次全市场导入（~2400 个 .day 文件）预计 2-5 分钟完成。

### MySQL 连接池

默认连接池大小 10，最大溢出 20。如遇连接数不足：

```bash
# 在 .env 中调整
MYSQL_POOL_SIZE=20
MYSQL_MAX_OVERFLOW=40
```

# Strategy2560 Docker 部署包

这个包用于把当前 Strategy2560 项目部署到服务器，推荐结构：

- `web`：FastAPI + WebUI
- `worker`：后台任务队列 worker
- `MySQL`：建议外部独立部署
- `cron`：建议宿主机定时入队

## 文件说明

```text
Dockerfile
Dockerfile.prod
compose.yaml
docker-compose.yml
.env.example
.dockerignore
requirements.txt
README_DOCKER_DEPLOY.md
```

其中：

- `compose.yaml` 和 `docker-compose.yml` 内容一致，方便不同 Docker Compose 版本使用。
- `Dockerfile.prod` 和 `Dockerfile` 内容一致，方便后续区分开发/生产镜像。

## 安装步骤

### 1. 复制部署文件到项目根目录

```bash
unzip -o strategy2560_docker_deploy_pack.zip -d /mnt/d/Project/Miller/strategy2560_project_v2_engine
cd /mnt/d/Project/Miller/strategy2560_project_v2_engine
```

### 2. 准备环境变量

```bash
cp .env.example .env
vi .env
```

重点修改：

```env
DATABASE_URL=mysql+pymysql://user:password@host.docker.internal:3306/watchlist_decision_support?charset=utf8mb4
```

### 3. 构建并启动

```bash
docker compose up -d --build
```

### 4. 查看服务

```bash
docker compose ps
docker compose logs -f web
docker compose logs -f worker
```

### 5. 访问 WebUI

```text
http://服务器IP:8000
```

## 数据库初始化

如果新服务器数据库还没初始化，按需执行：

```bash
mysql -u user -p watchlist_decision_support < sql/2560_schema_v2.4.sql
mysql -u user -p watchlist_decision_support < sql/job_queue.sql
mysql -u user -p watchlist_decision_support < sql/job_execution.sql
mysql -u user -p watchlist_decision_support < sql/job_task_item.sql
```

具体 SQL 文件以你项目 `sql/` 目录实际存在为准。

## cron 定时任务建议

建议宿主机 cron 负责定时入队，而不是容器内部跑 cron：

```cron
30 15 * * 1-5 cd /opt/strategy2560 && docker compose exec -T web python scripts/enqueue_job.py --strategy S2560 --priority 3 --market all --shards 4 >> logs/cron_enqueue.log 2>&1
```

## 常见问题

### 1. reportlab 缺失

已经在 `requirements.txt` 中加入：

```txt
reportlab==4.2.0
```

### 2. 容器访问宿主机 MySQL 失败

Compose 已加入：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

`.env` 中可使用：

```env
DATABASE_URL=mysql+pymysql://user:password@host.docker.internal:3306/watchlist_decision_support?charset=utf8mb4
```

### 3. job_queue 一直 pending

检查 worker：

```bash
docker compose logs -f worker
```

如果 worker 没启动，检查：

```bash
scripts/job_worker.py
```

是否存在。

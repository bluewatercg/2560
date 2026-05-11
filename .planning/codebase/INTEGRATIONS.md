# External Integrations

**Analysis Date:** 2026-05-11

## APIs & External Services

**HTTP API Surface:**
- FastAPI serves the application API and WebUI from `app/main.py`.
  - SDK/Client: browser `fetch()` calls in `app/static/*.js`; internal `requests` client in `scripts/progress_run_now.py`.
  - Auth: Not detected.
- Public route groups registered in `app/main.py`:
  - `/api/strategy/2560` from `app/api/strategy2560.py`
  - `/api/strategy/2568` from `app/api/strategy2568.py`
  - `/api/strategy/2568/report.pdf` from `app/api/strategy2568_report.py`
  - `/api/data-quality` from `app/api/data_quality.py`
  - `/api/latest` from `app/api/latest.py`
  - `/api/jobs` from `app/api/jobs.py`
  - `/api/import` from `app/api/import_data.py`
  - `/health` and `/` from `app/main.py`

**Market Data:**
- TongDaXin/CICC local `vipdoc` files are imported by `scripts/import_vipdoc_with_pytdx.py`.
  - SDK/Client: `pytdx.reader.TdxDailyBarReader` and `pytdx.reader.TdxLCMinBarReader`.
  - Auth: none.
  - Data path: request payloads default to `/data/vipdoc` in `app/api/import_data.py`; Docker mounts use `/data/vipdoc` in `docker-compose.yml`.
- TongDaXin HQ service is optionally used by `scripts/fill_recent_with_pytdx_hq.py`.
  - SDK/Client: `pytdx.hq.TdxHq_API`.
  - Auth: none.
  - Network: TCP connection to an IP/port supplied by CLI arguments; defaults are defined in `scripts/fill_recent_with_pytdx_hq.py`.

**Internal Job Runner HTTP Calls:**
- `scripts/progress_run_now.py` calls the local FastAPI endpoint `/api/strategy/2560/run` through `requests.post()`.
  - SDK/Client: `requests`.
  - Auth: none.
  - Base URL: `WEB_BASE_URL`, defaulting to local `http://127.0.0.1:8000` in `scripts/progress_run_now.py` and `app/api/jobs.py`.

## Data Storage

**Databases:**
- MySQL-compatible database.
  - Connection: `DATABASE_URL` or `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.
  - Client: SQLAlchemy engine/session in `app/db/session.py`; standalone workers also create SQLAlchemy engines in `scripts/job_worker.py` and `scripts/progress_run_now.py`.
  - Tables referenced by application logic include `stock_info`, `daily_kline`, `minute_kline_period`, `technical_indicator`, `structure_2560_analysis`, `structure_2560_tag_detail`, `analysis_batch`, `structure_2560_statistics`, `data_quality_check`, `strategy_config`, `job_queue`, `job_execution`, `job_task_item`, `data_import_batch`, and `data_import_file`.
  - Runtime DDL creation exists for job tables in `app/api/jobs.py` and import tables in `app/api/import_data.py`.
  - `scripts/apply_schema.py` expects `sql/2560_schema_v2.4.sql`, but no `sql/` directory is present in the current working tree.

**File Storage:**
- Local filesystem only.
  - Static WebUI files are served from `app/static/`.
  - Runtime logs are written under `logs/` by `app/api/jobs.py`, `scripts/job_worker.py`, and Docker volume mounts.
  - Market-data files are read from local or mounted `vipdoc` directories by `scripts/import_vipdoc_with_pytdx.py`.
  - PDF reports are generated in memory by `app/services/report_2568_pdf.py` and returned through `app/api/strategy2568_report.py`.

**Caching:**
- No external cache detected.
- In-process settings caching uses `functools.lru_cache` in `app/core/config.py`.

## Authentication & Identity

**Auth Provider:**
- Not detected.
  - Implementation: FastAPI routes in `app/api/*.py` use database dependencies but no authentication dependency, middleware, OAuth/JWT, API key, session, or role checks were found.
  - Browser API calls in `app/static/*.js` do not attach authorization headers.

## Monitoring & Observability

**Error Tracking:**
- None detected.

**Logs:**
- Container health is checked through `/health` in `Dockerfile`, `Dockerfile.prod`, and `compose.yaml`.
- Worker and run-now logs are written to local files under `logs/` in `scripts/job_worker.py` and `app/api/jobs.py`.
- Job progress and log tailing are exposed by `/api/jobs/executions/{job_id}/progress`, `/api/jobs/executions/{job_id}/shards`, and `/api/jobs/executions/{job_id}/logs` in `app/api/jobs.py`.
- Docker Compose exposes service logs through Docker logging; no structured log framework is configured.

## CI/CD & Deployment

**Hosting:**
- Docker Compose is the primary deployment path in `compose.yaml`, `docker-compose.yml`, and `README_DOCKER_DEPLOY.md`.
- `web` runs Uvicorn/FastAPI; `worker` runs `python scripts/job_worker.py`.
- Production database hosting is external to the Compose stack; docs recommend a separately deployed MySQL service.

**CI Pipeline:**
- GitHub Actions workflow `.github/workflows/build-docker-image.yml`.
  - Trigger: push to `main` and `feature/v8-job-queue-ui`, plus manual `workflow_dispatch`.
  - Build: Docker Buildx builds `strategy2560` image tags.
  - Artifact: workflow saves a gzipped Docker image tarball and uploads it with `actions/upload-artifact@v4`.
  - Registry push: Not detected.

## Environment Configuration

**Required env vars:**
- Database: `DATABASE_URL` or `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`.
- Database pool: `DB_POOL_SIZE`.
- App server: `APP_HOST`, `APP_PORT`, `APP_ENV`.
- Runtime path: `PYTHONPATH`.
- Worker queue: `JOB_WORKER_POLL_INTERVAL`.
- Run-now worker: `JOB_ID`, `MARKET`, `SHARDS`, `BATCH_SIZE`, `WEB_BASE_URL`, `LOG_FILE`.
- Market-data mount: `VIPDOC_ROOT` in `docker-compose.yml`; request payloads also accept `source_dir` in `app/api/import_data.py`.

**Secrets location:**
- `.env` file present at repository root; contents were not read.
- `.env.example` file present at repository root; contents were not read.
- Compose services load `.env` through `env_file` in `compose.yaml` and `docker-compose.yml`.
- `.dockerignore` excludes `.env` from Docker build context.

## Webhooks & Callbacks

**Incoming:**
- None detected. No webhook-specific route or callback receiver was found in `app/api/`.

**Outgoing:**
- No third-party webhook delivery detected.
- Internal callback-like HTTP work exists in `scripts/progress_run_now.py`, which posts batches to the local FastAPI `/api/strategy/2560/run` endpoint using `WEB_BASE_URL`.

---

*Integration audit: 2026-05-11*

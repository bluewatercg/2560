# Technology Stack

**Analysis Date:** 2026-05-11

## Languages

**Primary:**
- Python 3.11/3.12 - FastAPI backend, analysis engines, import workers, operational scripts in `app/` and `scripts/`. `Dockerfile` uses `python:3.11-slim`; `Dockerfile.prod` and the local `.venv/bin/python` are Python 3.12.3.

**Secondary:**
- JavaScript - Browser-side WebUI modules in `app/static/*.js`; no bundler or Node package manifest detected.
- HTML/CSS - Single-page WebUI in `app/static/index.html` and styles in `app/static/*.css`.
- Bash - Operational scripts in `scripts/*.sh`, including `scripts/start_webui.sh`, `scripts/run_with_path.sh`, and daily update scripts.
- SQL - Runtime DDL strings in `app/api/jobs.py` and `app/api/import_data.py`; schema loader in `scripts/apply_schema.py` expects `sql/2560_schema_v2.4.sql`, but no `sql/` directory is present in the current tree.

## Runtime

**Environment:**
- CPython 3.11 in `Dockerfile` for the main image.
- CPython 3.12 in `Dockerfile.prod` and local `.venv/bin/python`.
- Uvicorn serves `app.main:app` on port 8000 from `Dockerfile`, `Dockerfile.prod`, and `scripts/start_webui.sh`.
- Docker Compose defines separate `web` and `worker` services in `compose.yaml` and `docker-compose.yml`.

**Package Manager:**
- pip via `requirements.txt` and `requirements.backend.txt`.
- Lockfile: missing. Dependencies are pinned in requirements files but there is no generated lockfile.

## Frameworks

**Core:**
- FastAPI 0.111.0 - HTTP API and WebUI host in `app/main.py`; route modules live in `app/api/`.
- Pydantic 2.7.4 - Request/response models in `app/api/*.py` and `app/schemas/common.py`.
- pydantic-settings 2.3.4 - Environment-driven application settings in `app/core/config.py`.
- SQLAlchemy 2.0.30 - Database engine, sessions, and raw SQL execution in `app/db/session.py`, `app/db/repository.py`, `app/api/*.py`, and `scripts/*.py`.
- PyMySQL 1.1.1 - MySQL DBAPI driver used by SQLAlchemy connection URLs in `app/core/config.py`, `scripts/job_worker.py`, and `scripts/progress_run_now.py`.

**Testing:**
- Not detected. No pytest, unittest, coverage, or test config files were found at repository root.

**Build/Dev:**
- Uvicorn 0.30.1 - ASGI development/production server in `Dockerfile`, `Dockerfile.prod`, and `scripts/start_webui.sh`.
- Docker - Image build configured by `Dockerfile`, `Dockerfile.prod`, and `.dockerignore`.
- Docker Compose - Service orchestration in `compose.yaml` and `docker-compose.yml`.
- GitHub Actions - Docker image build and artifact upload in `.github/workflows/build-docker-image.yml`.
- Bash - Local operational wrappers in `scripts/*.sh`.

## Key Dependencies

**Critical:**
- `fastapi==0.111.0` - API routing, dependency injection, OpenAPI docs, and static WebUI hosting.
- `uvicorn[standard]==0.30.1` - Runs `app.main:app`.
- `SQLAlchemy==2.0.30` - Shared database access layer and job/import table management.
- `PyMySQL==1.1.1` - MySQL connectivity through `mysql+pymysql://` URLs.
- `pydantic==2.7.4` - API request validation and common response schemas.
- `pydantic-settings==2.3.4` - Loads `.env`-based configuration for `app/core/config.py`.
- `pandas==2.2.2` - K-line import, transformation, indicator preparation, and tabular analysis in `scripts/import_vipdoc_with_pytdx.py`, `scripts/build_30m_from_5m.py`, and `app/services/*.py`.
- `numpy==1.26.4` - Numeric indicator calculations in `app/services/indicator_engine.py` and `scripts/rebuild_technical_indicator.py`.

**Infrastructure:**
- `python-dotenv==1.0.1` - Explicit `.env` loading for standalone workers in `scripts/job_worker.py` and `scripts/progress_run_now.py`.
- `pytdx==1.72` - TongDaXin market data readers in `scripts/import_vipdoc_with_pytdx.py` and optional live HQ access in `scripts/fill_recent_with_pytdx_hq.py`.
- `reportlab==4.2.0` - PDF report generation in `app/services/report_2568_pdf.py` and `app/api/strategy2568_report.py`.
- `openpyxl==3.1.5` - Optional Excel export/read support; no direct import found in `app/` or `scripts/`.
- `requests==2.32.3` - Internal HTTP calls from `scripts/progress_run_now.py` to the FastAPI API.
- `urllib3==2.2.3` and `charset-normalizer==3.4.0` - HTTP dependency pins for `requests`.

## Configuration

**Environment:**
- Application settings are loaded from `.env` by `app/core/config.py` through `SettingsConfigDict(env_file='.env', extra='ignore')`.
- Worker scripts also call `load_dotenv(PROJECT_ROOT / ".env")` in `scripts/job_worker.py` and `scripts/progress_run_now.py`.
- `.env` and `.env.example` are present. Contents were not read because they are environment/secret files.
- Core environment variables used by the app and scripts: `DATABASE_URL`, `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_POOL_SIZE`, `APP_HOST`, `APP_PORT`, `APP_ENV`, `JOB_WORKER_POLL_INTERVAL`, `JOB_ID`, `MARKET`, `SHARDS`, `BATCH_SIZE`, `WEB_BASE_URL`, `LOG_FILE`, `PYTHONPATH`, and `VIPDOC_ROOT`.

**Build:**
- `Dockerfile` builds from `python:3.11-slim`, installs `requirements.txt`, copies `app/` and `scripts/`, exposes 8000, and runs Uvicorn.
- `Dockerfile.prod` builds from `python:3.12-slim`, installs `requirements.txt`, copies `app/`, `scripts/`, and `sql/`, exposes 8000, and runs Uvicorn.
- `compose.yaml` builds the local image and runs `web` plus `worker`.
- `docker-compose.yml` references `strategy2560:latest` for `web` plus `worker` and mounts `./zd_ciccwm/vipdoc` read-only into `/data/vipdoc`.
- `.dockerignore` excludes `.venv/`, `.git/`, `logs/`, `.env`, archives, Node/build outputs, and editor folders.
- `.github/workflows/build-docker-image.yml` builds `strategy2560` Docker images on pushes to `main` and `feature/v8-job-queue-ui`, saves a gzipped Docker image tarball, and uploads it as a workflow artifact.

## Platform Requirements

**Development:**
- Python virtual environment with `pip install -r requirements.txt`.
- MySQL reachable through either `DATABASE_URL` or `DB_HOST`/`DB_USER`/`DB_NAME` plus optional `DB_PASSWORD`.
- `PYTHONPATH` should point to the project root for local scripts; `scripts/start_webui.sh` and `scripts/run_with_path.sh` set this automatically.
- Optional local TongDaXin/CICC `vipdoc` directory for market-data import through `scripts/import_vipdoc_with_pytdx.py`.
- Uvicorn WebUI runs at `http://localhost:8000` and docs at `/docs` per `README.md`.

**Production:**
- Docker or Docker Compose deployment is documented in `README_DOCKER_DEPLOY.md`.
- `web` service serves FastAPI/WebUI; `worker` service runs `scripts/job_worker.py`.
- MySQL is expected to be external or host-provided; Compose uses `.env` and `host.docker.internal` support.
- Local filesystem volumes are used for `logs/`, optional `sql/`, and optional read-only market-data mounts.
- Host cron is the documented scheduling mechanism in `README_DOCKER_DEPLOY.md`; no in-container cron service is configured.

---

*Stack analysis: 2026-05-11*

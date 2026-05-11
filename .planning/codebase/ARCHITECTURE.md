# Architecture

**Analysis Date:** 2026-05-11

## Pattern Overview

**Overall:** FastAPI service with layered routers, service/engine modules, direct SQL repositories, static single-page WebUI, and operational batch scripts.

**Key Characteristics:**
- `app/main.py` owns the deployed ASGI application, router registration, static asset mounting, `/health`, and `/`.
- `app/api/*.py` modules expose REST endpoints and use `Depends(get_db)` from `app/db/session.py` for request-scoped SQLAlchemy sessions.
- `app/services/*.py` modules hold strategy engines, query services, tagging rules, annotation logic, statistics aggregation, and PDF generation.
- `app/db/repository.py` is the main repository abstraction for 2560 K-line reads and analysis writes; several routers and scripts also execute SQL directly with `sqlalchemy.text`.
- `app/static/index.html` and `app/static/*.js` implement a browser SPA that calls the REST API directly with `fetch`.
- `scripts/*.py` are first-class operational entry points for schema setup, data import, indicator rebuilds, batch analysis, and background job execution.

## Layers

**Application Entry Layer:**
- Purpose: Create the FastAPI app, register routers, serve health checks and static UI.
- Location: `app/main.py`
- Contains: `FastAPI(...)`, `app.include_router(...)`, `StaticFiles`, `/health`, `/` HTML response.
- Depends on: `app/api/strategy2560.py`, `app/api/strategy2568.py`, `app/api/strategy2568_report.py`, `app/api/data_quality.py`, `app/api/latest.py`, `app/api/jobs.py`, `app/api/import_data.py`, `app/db/session.py`.
- Used by: `Dockerfile`, `docker-compose.yml`, `README.md`, and runtime command `uvicorn app.main:app`.

**API Router Layer:**
- Purpose: Define HTTP endpoints, parse request/query models, normalize input, and delegate to services or scripts.
- Location: `app/api/`
- Contains: `app/api/strategy2560.py`, `app/api/strategy2568.py`, `app/api/strategy2568_report.py`, `app/api/data_quality.py`, `app/api/latest.py`, `app/api/jobs.py`, `app/api/import_data.py`.
- Depends on: `app/db/session.py`, `app/schemas/common.py`, `app/services/*.py`, selected `scripts/*.py` functions.
- Used by: `app/main.py` and frontend files under `app/static/`.

**Service and Engine Layer:**
- Purpose: Implement strategy computation, presentation queries, annotations, statistics, tags, and report building.
- Location: `app/services/`
- Contains: `SignalEngine2560` in `app/services/signal_engine_2560.py`, `Strategy2560Service` in `app/services/strategy2560_service.py`, `AnnotationEngine2568` in `app/services/annotation_engine_2568.py`, `Report2568PdfBuilder` in `app/services/report_2568_pdf.py`, `StatisticsEngine` in `app/services/statistics_engine.py`, `ConfigService` in `app/services/config_service.py`, indicator helpers in `app/services/indicator_engine.py`, tag helpers in `app/services/tag_service.py`.
- Depends on: SQLAlchemy sessions from `app/db/session.py`, pandas/numpy, `app/db/repository.py`, and strategy configuration stored in database table `strategy_config`.
- Used by: API routers in `app/api/` and CLI scripts in `scripts/`.

**Database Access Layer:**
- Purpose: Configure DB connectivity, expose sessions, and centralize common K-line and analysis write operations.
- Location: `app/db/`
- Contains: `engine`, `SessionLocal`, `get_db`, and `ping_database` in `app/db/session.py`; `KlineRepository` in `app/db/repository.py`.
- Depends on: `app/core/config.py`, SQLAlchemy, pandas.
- Used by: `app/api/*.py`, `app/services/*.py`, and `scripts/*.py`.

**Configuration Layer:**
- Purpose: Load environment-backed application settings and construct the SQLAlchemy URL.
- Location: `app/core/config.py`
- Contains: `Settings`, `.env` loading via `pydantic-settings`, `get_settings()` with `lru_cache`, and `Settings.sqlalchemy_url`.
- Depends on: `pydantic_settings.BaseSettings`.
- Used by: `app/db/session.py`, `scripts/apply_schema.py`, and DB-dependent scripts.

**Schema/Response Layer:**
- Purpose: Define reusable response models.
- Location: `app/schemas/`
- Contains: `ApiResponse` in `app/schemas/common.py`.
- Depends on: Pydantic.
- Used by: `app/api/strategy2560.py` and `app/api/data_quality.py`.

**Static Frontend Layer:**
- Purpose: Render the WebUI and call backend endpoints.
- Location: `app/static/`
- Contains: Base page `app/static/index.html`, main SPA logic `app/static/app.js`, feature add-ons such as `app/static/job_progress_monitor.js`, `app/static/data_import_page.js`, `app/static/data_import_type_addon.js`, `app/static/annotation2568.js`, `app/static/annotation2568_report.js`, and menu patches in `app/static/nested_menu_reorg.js`.
- Depends on: Browser DOM APIs and backend REST endpoints; no frontend build step is present.
- Used by: `app/main.py` static mount and `/` route.

**Operational Script Layer:**
- Purpose: Run batch work outside request/response paths.
- Location: `scripts/`
- Contains: schema runner `scripts/apply_schema.py`, 2560 runner `scripts/run_2560_analysis.py`, indicator rebuild `scripts/rebuild_technical_indicator.py`, statistics rebuild `scripts/rebuild_statistics.py`, vipdoc import `scripts/import_vipdoc_with_pytdx.py`, 5m-to-30m aggregation `scripts/build_30m_from_5m.py`, recent fill `scripts/fill_recent_with_pytdx_hq.py`, background workers `scripts/job_worker.py` and `scripts/progress_run_now.py`.
- Depends on: `app/db/session.py`, `app/services/*.py`, SQLAlchemy, pandas, requests, pytdx.
- Used by: CLI operators, `app/api/jobs.py`, `app/api/import_data.py`, and the Docker worker service in `docker-compose.yml`.

**Deployment Layer:**
- Purpose: Package and run the web and worker processes.
- Location: `Dockerfile`, `docker-compose.yml`, `.github/workflows/build-docker-image.yml`.
- Contains: Python slim images, `uvicorn app.main:app`, logs and sql volume mounts, worker command `python scripts/job_worker.py`, Docker image build workflow.
- Depends on: `requirements.txt`, `.env` file existence, `app/`, `scripts/`, optional `sql/` directory.
- Used by: local and server deployment workflows.

## Data Flow

**WebUI Query Flow:**

1. Browser loads `app/static/index.html` from `/` in `app/main.py`.
2. `app/static/app.js` and feature scripts call endpoints such as `/health`, `/api/strategy/2560/overview`, `/api/strategy/2560/signals`, `/api/latest/by-stock`, `/api/jobs/executions`, and `/api/import/batches`.
3. FastAPI routers in `app/api/*.py` receive requests and get a SQLAlchemy session from `app/db/session.py`.
4. Routers call services such as `Strategy2560Service` in `app/services/strategy2560_service.py` or execute SQL directly with `sqlalchemy.text`.
5. Results return as JSON directly or wrapped in `ApiResponse` from `app/schemas/common.py`.

**2560 Analysis Flow:**

1. A run starts through `POST /api/strategy/2560/run` in `app/api/strategy2560.py` or `scripts/run_2560_analysis.py`.
2. Requested stock codes are normalized in `app/api/strategy2560.py` or loaded from `stock_info` in `scripts/run_2560_analysis.py`.
3. `SignalEngine2560.run()` in `app/services/signal_engine_2560.py` loads strategy settings through `ConfigService.load_strategy_config()` from `app/services/config_service.py`.
4. `KlineRepository` in `app/db/repository.py` reads `stock_info`, `daily_kline`, `minute_kline_period`, and falls back from `minute_kline_period` to `minute_kline` for `5m`.
5. `enrich_indicators()` in `app/services/indicator_engine.py` computes MA, ATR, volume, deviation, breakout, and data-quality fields.
6. `SignalEngine2560.scan()` applies 30m, daily, and 5m checks, then builds tags via `build_tags()` in `app/services/tag_service.py`.
7. `KlineRepository.upsert_indicators()`, `KlineRepository.upsert_analysis()`, and `KlineRepository.replace_tags()` write `technical_indicator`, `structure_2560_analysis`, and `structure_2560_tag_detail`.
8. `StatisticsEngine.rebuild()` in `app/services/statistics_engine.py` writes `structure_2560_statistics` when the API payload requests statistics rebuild or the CLI does not pass `--skip-statistics`.

**2568 Annotation Flow:**

1. Browser script `app/static/annotation2568.js` calls `/api/strategy/2568/annotations`.
2. Router `app/api/strategy2568.py` delegates to `AnnotationEngine2568.annotations()` in `app/services/annotation_engine_2568.py`.
3. `AnnotationEngine2568` reads `stock_info`, latest daily rows from `technical_indicator`, and recent daily K-lines from `daily_kline`.
4. `AnnotationEngine2568.annotate_one()` emits per-stock labels, A/B/C/D highlight fields, risk tags, and summary stats.
5. Browser script `app/static/annotation2568_report.js` opens `/api/strategy/2568/report.pdf`.
6. Router `app/api/strategy2568_report.py` uses `Report2568PdfBuilder` in `app/services/report_2568_pdf.py` to build a ReportLab PDF response.

**Data Import and Aggregation Flow:**

1. Browser scripts `app/static/data_import_page.js` and `app/static/data_import_type_addon.js` call `/api/import/scan`, `/api/import/run`, `/api/import/build-30m`, `/api/import/batches`, and `/api/import/files`.
2. Router `app/api/import_data.py` validates payloads with `ImportScanRequest`, `ImportRunRequest`, and `Build30mRequest`.
3. `app/api/import_data.py` calls `scan_vipdoc_files()` and `import_vipdoc_files_parallel()` from `scripts/import_vipdoc_with_pytdx.py`.
4. `app/api/import_data.py` calls `build_30m_parallel()` from `scripts/build_30m_from_5m.py`.
5. Import progress writes `data_import_batch` and `data_import_file`; K-line data writes `daily_kline` and `minute_kline_period`.

**Job Queue and Progress Flow:**

1. Browser scripts `app/static/jobs_actions.js`, `app/static/jobs_page_bootstrap.js`, and `app/static/job_progress_monitor.js` call `/api/jobs/*`.
2. Router `app/api/jobs.py` lazily creates `job_queue`, `job_execution`, and `job_task_item` tables in `_ensure_tables()`.
3. `POST /api/jobs/run-now` in `app/api/jobs.py` inserts a `job_execution`, creates `logs/job_{id}_progress.log`, and starts `scripts/progress_run_now.py` with `subprocess.Popen`.
4. `scripts/progress_run_now.py` reads `JOB_ID`, `MARKET`, `SHARDS`, `BATCH_SIZE`, and `WEB_BASE_URL`, creates work items, and uses `ThreadPoolExecutor` to post batched codes to `/api/strategy/2560/run`.
5. `scripts/progress_run_now.py` updates `job_execution` and `job_task_item`; `app/api/jobs.py` exposes progress, shard summaries, item rows, and tailed logs.
6. `scripts/job_worker.py` polls `job_queue`, marks queued jobs running, and executes `scripts/daily_update_incremental_sharded.sh` when present or `scripts/progress_run_now.py` otherwise.

**State Management:**
- Backend request state is per-request SQLAlchemy sessions from `get_db()` in `app/db/session.py`.
- Long-running job state is database-backed in `job_queue`, `job_execution`, and `job_task_item`, with log files under `logs/`.
- Frontend state is in browser memory, primarily the `state` object in `app/static/app.js` plus module-local variables in feature scripts such as `app/static/job_progress_monitor.js`.
- Strategy parameters are database-backed through `strategy_config` with defaults in `DEFAULT_CONFIG` in `app/services/config_service.py`.

## Key Abstractions

**FastAPI Router Modules:**
- Purpose: Group endpoints by feature and prefix.
- Examples: `app/api/strategy2560.py`, `app/api/jobs.py`, `app/api/import_data.py`, `app/api/strategy2568.py`.
- Pattern: Define `router = APIRouter(...)`, request models near the router, endpoint functions with `db: Session = Depends(get_db)`, then register the router in `app/main.py`.

**Service Classes:**
- Purpose: Encapsulate business logic that belongs outside endpoint handlers.
- Examples: `Strategy2560Service` in `app/services/strategy2560_service.py`, `SignalEngine2560` in `app/services/signal_engine_2560.py`, `AnnotationEngine2568` in `app/services/annotation_engine_2568.py`, `StatisticsEngine` in `app/services/statistics_engine.py`, `ConfigService` in `app/services/config_service.py`.
- Pattern: Constructor accepts `db`, methods execute SQL or call repositories/helpers, routers instantiate services per request.

**Repository Class:**
- Purpose: Centralize repeated K-line reads and 2560 analysis writes.
- Examples: `KlineRepository` in `app/db/repository.py`.
- Pattern: Constructor accepts a SQLAlchemy `Session`; methods use `self.db.execute(text(...))` or `pd.read_sql(...)`.

**Pandas Indicator Helpers:**
- Purpose: Transform raw K-line data into technical indicator rows.
- Examples: `slope_pct()`, `atr()`, `enrich_indicators()`, `to_indicator_rows()` in `app/services/indicator_engine.py`; `compute_indicators()` and `make_records()` in `scripts/rebuild_technical_indicator.py`.
- Pattern: Accept pandas `DataFrame`, sort by `date`, coerce numeric columns, add computed columns, convert NaN-like values before MySQL writes.

**Tag Rules:**
- Purpose: Convert boolean signal facts into tag detail rows, structure status, and explanation text.
- Examples: `TAG`, `build_tags()`, `structure_status()`, `explain_text()` in `app/services/tag_service.py`.
- Pattern: Pure functions accepting a row dict and returning serializable dictionaries or strings.

**Background Job Tables:**
- Purpose: Represent queued and running work for WebUI progress.
- Examples: table creation SQL in `_ensure_tables()` in `app/api/jobs.py`, update logic in `scripts/progress_run_now.py`.
- Pattern: API creates/reads status; runner mutates `job_execution` and `job_task_item`; frontend polls progress endpoints.

**Static Feature Add-on Scripts:**
- Purpose: Extend the base SPA without a build system.
- Examples: `app/static/data_import_page.js`, `app/static/data_import_type_addon.js`, `app/static/job_progress_monitor.js`, `app/static/annotation2568.js`, `app/static/nested_menu_reorg.js`.
- Pattern: IIFE modules create DOM nodes if missing, bind buttons, and call REST endpoints with `fetch`.

## Entry Points

**ASGI Web Application:**
- Location: `app/main.py`
- Triggers: `uvicorn app.main:app --host 0.0.0.0 --port 8000` from `Dockerfile`, `docker-compose.yml`, and `README.md`.
- Responsibilities: Serve API routes, static files, `/health`, and `app/static/index.html`.

**Alternate Package App Object:**
- Location: `app/__init__.py`
- Triggers: Importing `app.app` from the package.
- Responsibilities: Defines a smaller FastAPI app with only strategy2560 and data-quality routers.

**2560 CLI Runner:**
- Location: `scripts/run_2560_analysis.py`
- Triggers: `python scripts/run_2560_analysis.py` with optional `--codes`, `--market-type`, `--limit`, `--source`, and `--skip-statistics`.
- Responsibilities: Load a stock universe, run `SignalEngine2560`, optionally rebuild statistics.

**Indicator Rebuild CLI:**
- Location: `scripts/rebuild_technical_indicator.py`
- Triggers: `python scripts/rebuild_technical_indicator.py --start YYYY-MM-DD --end YYYY-MM-DD`.
- Responsibilities: Recompute `technical_indicator` for `daily`, `5m`, and `30m` data by market and date range.

**Schema Apply CLI:**
- Location: `scripts/apply_schema.py`
- Triggers: `python scripts/apply_schema.py`.
- Responsibilities: Read `sql/2560_schema_v2.4.sql`, split statements, execute DDL.

**Vipdoc Import CLI and API Helpers:**
- Location: `scripts/import_vipdoc_with_pytdx.py`
- Triggers: CLI execution or calls from `app/api/import_data.py`.
- Responsibilities: Scan local vipdoc files and import daily or 5m K-line records.

**30m Aggregation CLI and API Helper:**
- Location: `scripts/build_30m_from_5m.py`
- Triggers: CLI execution or calls from `app/api/import_data.py`.
- Responsibilities: Aggregate `5m` rows into `30m` rows in `minute_kline_period`.

**Job Worker:**
- Location: `scripts/job_worker.py`
- Triggers: Docker worker command in `docker-compose.yml`.
- Responsibilities: Poll `job_queue` and run batch work.

**Progress Runner:**
- Location: `scripts/progress_run_now.py`
- Triggers: `subprocess.Popen` from `app/api/jobs.py` or direct process execution with environment variables.
- Responsibilities: Create task items, run batched HTTP analysis requests concurrently, update DB progress, write logs.

**Static WebUI:**
- Location: `app/static/index.html`
- Triggers: Browser request to `/`.
- Responsibilities: Load CSS/JS, render navigation and views, call REST APIs.

## Error Handling

**Strategy:** Local try/except blocks return API warning objects, collect per-code errors, or mark background rows failed; no global FastAPI exception handler is present.

**Patterns:**
- `app/main.py` catches health-check DB exceptions and returns `{"status": "warning", "database": False, "message": ...}`.
- `SignalEngine2560.run()` in `app/services/signal_engine_2560.py` catches exceptions per code, rolls back the current transaction, appends the error to a bounded list, and continues processing.
- `ConfigService.load_strategy_config()` in `app/services/config_service.py` catches configuration query failures and falls back to `DEFAULT_CONFIG`.
- `app/api/jobs.py` returns `{"ok": False, ...}` for missing job tables, missing jobs, and missing log files.
- `scripts/progress_run_now.py` catches batch HTTP errors and marks affected `job_task_item` rows failed; top-level runner exceptions mark `job_execution` failed.
- `scripts/job_worker.py` catches loop exceptions, prints tracebacks, sleeps, and continues polling.
- `app/api/strategy2560.py` raises `HTTPException(status_code=404)` for missing signal and batch detail records.

## Cross-Cutting Concerns

**Logging:** Web request logging is left to Uvicorn/FastAPI. Long-running job output is redirected to files under `logs/` by `app/api/jobs.py`, `scripts/job_worker.py`, and `scripts/progress_run_now.py`.

**Validation:** HTTP payloads use Pydantic models in router files such as `RunAnalysisRequest` in `app/api/strategy2560.py`, `EnqueueJobRequest` and `RunNowRequest` in `app/api/jobs.py`, and import request models in `app/api/import_data.py`. Query bounds use FastAPI `Query(...)`.

**Authentication:** Not detected in `app/main.py`, `app/api/*.py`, `app/static/*.js`, or `docker-compose.yml`. API and WebUI routes are unauthenticated.

**Database Transactions:** Request handlers receive `Session` from `app/db/session.py`; service methods and routers call `commit()` and `rollback()` manually. `scripts/*.py` use either `SessionLocal()` or SQLAlchemy engine transaction contexts.

**Environment Configuration:** `app/core/config.py` loads `.env` through Pydantic settings. Standalone scripts `scripts/job_worker.py` and `scripts/progress_run_now.py` explicitly call `load_dotenv(PROJECT_ROOT / ".env")`.

**SQL Approach:** SQL is primarily hand-written with `sqlalchemy.text` in `app/db/repository.py`, `app/api/*.py`, `app/services/*.py`, and `scripts/*.py`; no ORM model classes or Alembic migrations are present.

---

*Architecture analysis: 2026-05-11*

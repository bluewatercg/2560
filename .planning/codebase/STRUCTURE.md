# Codebase Structure

**Analysis Date:** 2026-05-11

## Directory Layout

```text
strategy2560_project_v2_engine/
├── app/                    # FastAPI application, services, DB access, schemas, static WebUI
│   ├── main.py             # Deployed ASGI app entry point
│   ├── __init__.py         # Package initializer that also defines a smaller app object
│   ├── api/                # HTTP routers grouped by product feature
│   ├── core/               # Settings and app-wide configuration
│   ├── db/                 # SQLAlchemy engine/session and repository helpers
│   ├── schemas/            # Pydantic response schemas
│   ├── services/           # Strategy engines, query services, annotations, reports
│   └── static/             # Plain HTML/CSS/JS single-page WebUI
├── scripts/                # CLI and background operational scripts
├── docs/                   # Project documentation
├── logs/                   # Runtime job logs
├── .github/workflows/      # Docker image build workflow
├── .planning/codebase/     # GSD codebase mapping documents
├── Dockerfile              # Web image build using Python 3.11 slim
├── Dockerfile.prod         # Production image build using Python 3.12 slim
├── compose.yaml            # Build-based web and worker compose file
├── docker-compose.yml      # Image-based web and worker compose file
├── requirements.txt        # Main Python dependency pins
├── requirements.backend.txt# Minimal backend dependency pins
├── README.md               # Startup and command overview
├── README_2560_DAILY_OPS.md# Daily operation guide
├── README_DOCKER_DEPLOY.md # Docker deployment guide
├── README_FINAL_REORG_DEPLOY.md # UI/reorg deployment notes
├── PROJECT_OVERVIEW.md     # Detailed architecture and schema overview
├── BUILD_REPORT.json       # Build metadata
└── PATCH_REPORT.json       # Patch metadata
```

## Directory Purposes

**`app/`:**
- Purpose: Runtime application package for the web service and shared backend logic.
- Contains: `app/main.py`, routers in `app/api/`, settings in `app/core/`, DB access in `app/db/`, service logic in `app/services/`, schemas in `app/schemas/`, frontend files in `app/static/`.
- Key files: `app/main.py`, `app/db/session.py`, `app/db/repository.py`, `app/services/signal_engine_2560.py`, `app/static/index.html`.

**`app/api/`:**
- Purpose: FastAPI router modules and request models.
- Contains: Strategy endpoints, latest-status endpoint, data-quality endpoint, job endpoints, import endpoints, 2568 annotation/report endpoints.
- Key files: `app/api/strategy2560.py`, `app/api/strategy2568.py`, `app/api/strategy2568_report.py`, `app/api/latest.py`, `app/api/jobs.py`, `app/api/import_data.py`, `app/api/data_quality.py`.

**`app/core/`:**
- Purpose: App configuration from environment.
- Contains: `Settings` and `get_settings()`.
- Key files: `app/core/config.py`.

**`app/db/`:**
- Purpose: SQLAlchemy connection setup and reusable data access.
- Contains: `SessionLocal`, `get_db()`, `ping_database()`, and `KlineRepository`.
- Key files: `app/db/session.py`, `app/db/repository.py`.

**`app/schemas/`:**
- Purpose: Shared Pydantic schemas.
- Contains: `ApiResponse`.
- Key files: `app/schemas/common.py`.

**`app/services/`:**
- Purpose: Business logic that is shared by routers and scripts.
- Contains: Analysis engines, annotation engine, PDF builder, strategy query service, config service, statistics engine, tag rules, indicator helpers.
- Key files: `app/services/signal_engine_2560.py`, `app/services/strategy2560_service.py`, `app/services/annotation_engine_2568.py`, `app/services/report_2568_pdf.py`, `app/services/indicator_engine.py`, `app/services/tag_service.py`, `app/services/config_service.py`, `app/services/statistics_engine.py`.

**`app/static/`:**
- Purpose: Browser UI served directly by FastAPI without a build step.
- Contains: `index.html`, CSS files, base SPA logic, feature add-on scripts, UI reorganization scripts, backup HTML files.
- Key files: `app/static/index.html`, `app/static/app.js`, `app/static/styles.css`, `app/static/nested_menu_reorg.js`, `app/static/job_progress_monitor.js`, `app/static/data_import_page.js`, `app/static/data_import_type_addon.js`, `app/static/annotation2568.js`, `app/static/annotation2568_report.js`.

**`scripts/`:**
- Purpose: Command-line operations, background workers, batch data processing, and patch utilities.
- Contains: Schema apply, K-line import, 30m aggregation, technical indicator rebuild, strategy run, job workers, deployment helpers, patch scripts.
- Key files: `scripts/apply_schema.py`, `scripts/import_vipdoc_with_pytdx.py`, `scripts/build_30m_from_5m.py`, `scripts/rebuild_technical_indicator.py`, `scripts/run_2560_analysis.py`, `scripts/progress_run_now.py`, `scripts/job_worker.py`, `scripts/start_webui.sh`.

**`docs/`:**
- Purpose: Versioned project documentation.
- Contains: `docs/README_V2.4.md`.
- Key files: `docs/README_V2.4.md`.

**`logs/`:**
- Purpose: Runtime output for background jobs.
- Contains: job progress logs such as `logs/job_10_progress.log`.
- Key files: `logs/job_2_progress.log`, `logs/job_10_progress.log`.

**`.github/workflows/`:**
- Purpose: CI workflow definitions.
- Contains: Docker build workflow.
- Key files: `.github/workflows/build-docker-image.yml`.

**`.planning/codebase/`:**
- Purpose: GSD-generated codebase mapping documents.
- Contains: architecture and structure docs for the `arch` focus plus other mapper docs when present.
- Key files: `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/STRUCTURE.md`.

## Key File Locations

**Entry Points:**
- `app/main.py`: Deployed ASGI app for Uvicorn, router registration, `/health`, `/`, and `/static`.
- `app/__init__.py`: Package-level alternate FastAPI app object with a smaller router set.
- `scripts/run_2560_analysis.py`: CLI entry for 2560 analysis and optional statistics rebuild.
- `scripts/rebuild_technical_indicator.py`: CLI entry for `technical_indicator` rebuilds.
- `scripts/import_vipdoc_with_pytdx.py`: CLI/API helper for vipdoc file import.
- `scripts/build_30m_from_5m.py`: CLI/API helper for 5m-to-30m aggregation.
- `scripts/apply_schema.py`: CLI entry for applying `sql/2560_schema_v2.4.sql`.
- `scripts/job_worker.py`: Queue worker process used by compose worker service.
- `scripts/progress_run_now.py`: Parallel progress runner spawned by `app/api/jobs.py`.
- `app/static/index.html`: WebUI entry served at `/`.

**Configuration:**
- `app/core/config.py`: Pydantic settings and SQLAlchemy URL construction.
- `requirements.txt`: Main dependency pins used by Docker builds.
- `requirements.backend.txt`: Minimal backend dependency pins.
- `Dockerfile`: Python 3.11 slim image, copies `app/` and `scripts/`, runs `uvicorn app.main:app`.
- `Dockerfile.prod`: Python 3.12 slim image, copies `app/`, `scripts/`, and `sql/`, runs `uvicorn app.main:app`.
- `compose.yaml`: Build-based web and worker services with `.env`, `logs`, and `sql` mounts.
- `docker-compose.yml`: Image-based web and worker services with `.env`, `logs`, `sql`, and vipdoc mounts.
- `.github/workflows/build-docker-image.yml`: Docker image build and artifact upload workflow.
- `.env`: Environment configuration file present; do not read or quote contents.
- `.env.example`: Environment configuration template present.

**Core Logic:**
- `app/services/signal_engine_2560.py`: 2560 signal execution loop, per-code scan, tag/write flow.
- `app/services/indicator_engine.py`: In-request indicator calculation helpers used by `SignalEngine2560`.
- `app/services/tag_service.py`: Tag, structure-status, and explanation rules.
- `app/services/strategy2560_service.py`: Query service for overview, signals, batches, statistics, and data quality.
- `app/services/annotation_engine_2568.py`: 2568 annotation and A/B/C/D highlight logic.
- `app/services/report_2568_pdf.py`: ReportLab PDF builder for 2568 reports.
- `app/services/statistics_engine.py`: Aggregates `structure_2560_statistics`.
- `app/services/config_service.py`: Loads strategy config defaults and database overrides.
- `app/db/repository.py`: `KlineRepository` K-line reads and analysis writes.

**API Surface:**
- `app/api/strategy2560.py`: `/api/strategy/2560/*` routes for stocks, probes, run, signals, complete cases, statistics, and batches.
- `app/api/strategy2568.py`: `/api/strategy/2568/annotations`.
- `app/api/strategy2568_report.py`: `/api/strategy/2568/report.pdf`.
- `app/api/data_quality.py`: `/api/data-quality/summary`.
- `app/api/latest.py`: `/api/latest/by-stock`.
- `app/api/jobs.py`: `/api/jobs/*` queue, execution, item, progress, shard, log, enqueue, and run-now routes.
- `app/api/import_data.py`: `/api/import/*` scan, run, build-30m, batch, and file routes.

**Frontend:**
- `app/static/index.html`: Base markup, navigation, views, script includes.
- `app/static/app.js`: Main SPA state, API helper, overview/stocks/run/probe/signal views.
- `app/static/styles.css`: Base WebUI styles.
- `app/static/nested_menu_reorg.css`: Nested menu styles.
- `app/static/nested_menu_reorg.js`: Navigation grouping and active-group behavior.
- `app/static/jobs_actions.js`: Jobs page action helpers.
- `app/static/jobs_page_bootstrap.js`: Jobs page bootstrap UI.
- `app/static/job_progress_monitor.js`: Run-now progress polling and shard/log rendering.
- `app/static/data_import_page.js`: Data import page creation and API calls.
- `app/static/data_import_type_addon.js`: Import type, date, worker, and build-30m controls.
- `app/static/annotation2568.js`: 2568 annotation page and table rendering.
- `app/static/annotation2568_report.js`: 2568 PDF report button and query string builder.
- `app/static/module_reorg.js`: Text replacement for UI module naming.

**Testing:**
- No dedicated test directory or `*.test.*` / `*.spec.*` files detected in the repository file list.
- No pytest, unittest, or coverage configuration detected in the repository root.

**Database Schema:**
- `scripts/apply_schema.py`: Expects `sql/2560_schema_v2.4.sql`.
- `sql/`: Referenced by `README.md`, `PROJECT_OVERVIEW.md`, `Dockerfile.prod`, `compose.yaml`, `docker-compose.yml`, and `scripts/apply_schema.py`; directory not detected in the current file tree.

## Naming Conventions

**Files:**
- API routers use snake_case feature names: `app/api/strategy2560.py`, `app/api/import_data.py`, `app/api/data_quality.py`, `app/api/strategy2568_report.py`.
- Service modules use snake_case nouns ending in `_service.py` or `_engine.py` when stateful logic is class-based: `app/services/strategy2560_service.py`, `app/services/signal_engine_2560.py`, `app/services/annotation_engine_2568.py`, `app/services/statistics_engine.py`.
- Pure helper modules use domain nouns without class suffixes: `app/services/indicator_engine.py`, `app/services/tag_service.py`.
- Static JS feature files use snake_case names: `app/static/job_progress_monitor.js`, `app/static/data_import_type_addon.js`, `app/static/nested_menu_reorg.js`.
- Operational scripts use verb-first snake_case names: `scripts/run_2560_analysis.py`, `scripts/rebuild_technical_indicator.py`, `scripts/import_vipdoc_with_pytdx.py`, `scripts/build_30m_from_5m.py`, `scripts/apply_schema.py`.
- Patch utilities use `apply_*_patch.py`: `scripts/apply_job_progress_monitor_patch.py`, `scripts/apply_nested_menu_reorg_patch.py`.

**Directories:**
- Runtime app package directories are short, lowercase nouns: `app/api/`, `app/core/`, `app/db/`, `app/schemas/`, `app/services/`, `app/static/`.
- Operational and documentation directories are lowercase nouns: `scripts/`, `docs/`, `logs/`.
- GSD planning docs live under `.planning/codebase/`.

**Python Symbols:**
- Service classes use PascalCase with domain suffixes: `SignalEngine2560`, `Strategy2560Service`, `AnnotationEngine2568`, `Report2568PdfBuilder`, `StatisticsEngine`, `ConfigService`, `KlineRepository`.
- Endpoint functions and helpers use snake_case: `run_analysis`, `build_probe`, `resolve_db_code`, `market_where`, `load_codes`, `build_30m_parallel`.
- Pydantic request models use PascalCase ending in `Request`: `RunAnalysisRequest`, `EnqueueJobRequest`, `RunNowRequest`, `ImportScanRequest`, `ImportRunRequest`, `Build30mRequest`.
- Constants use uppercase: `SUPPORTED_TYPES`, `NORMALIZED_CODE_SQL`, `DEFAULT_CONFIG`, `PROJECT_ROOT`.

**Frontend Symbols:**
- `app/static/app.js` uses camelCase functions and state fields: `loadOverview`, `loadStocks`, `runSelected`, `renderTable`, `state.selected`.
- Add-on scripts define local helpers such as `$`, `apiJson`, `getJson`, `postJson`, `ensureDataImportPage`, `loadImportBatches`.
- DOM IDs use camelCase: `refreshBtn`, `systemBanner`, `pageTitle`, `jobProgressText`, `importBatchTable`.
- View sections use `view-{name}` IDs matching nav `data-view` values: `view-overview`, `view-jobs`, `view-annotation2568`.

## Where to Add New Code

**New API Feature:**
- Primary code: Add a router module under `app/api/`, following `router = APIRouter(prefix=..., tags=[...])` in `app/api/import_data.py` or `app/api/strategy2568.py`.
- Service code: Add business logic under `app/services/` when endpoint handlers need more than request parsing and direct delegation.
- Registration: Import and include the router in `app/main.py`.
- Frontend integration: Add a script under `app/static/` and include it from `app/static/index.html`, or extend `app/static/app.js` for base SPA behavior.

**New 2560 Query Endpoint:**
- Primary code: Add route handlers to `app/api/strategy2560.py` when the route is part of `/api/strategy/2560`.
- Query logic: Add reusable DB query methods to `Strategy2560Service` in `app/services/strategy2560_service.py`.
- Response wrapper: Return `ApiResponse(data=...)` from `app/schemas/common.py` to match existing 2560 route style.

**New 2560 Computation Rule:**
- Primary code: Add signal conditions in `SignalEngine2560.scan()` in `app/services/signal_engine_2560.py`.
- Indicator inputs: Add computed fields in `app/services/indicator_engine.py` and include them in `to_indicator_rows()` when the field is stored in `technical_indicator`.
- Tag outputs: Add tag constants and rule logic in `app/services/tag_service.py`.
- Script parity: Update `scripts/rebuild_technical_indicator.py` if the stored indicator calculation must be available outside `SignalEngine2560`.

**New 2568 Annotation or Report Field:**
- Primary code: Add annotation derivation to `AnnotationEngine2568` in `app/services/annotation_engine_2568.py`.
- API exposure: Keep `/api/strategy/2568/annotations` in `app/api/strategy2568.py` as the JSON boundary.
- PDF exposure: Add PDF field rendering to `Report2568PdfBuilder` in `app/services/report_2568_pdf.py`.
- Frontend display: Update `app/static/annotation2568.js` and `app/static/annotation2568_report.js`.

**New Background Job Behavior:**
- Primary code: Add API-level job creation/status behavior in `app/api/jobs.py`.
- Runner behavior: Add execution logic to `scripts/progress_run_now.py` for run-now tracked jobs.
- Queue worker behavior: Add polling or queued-job execution changes to `scripts/job_worker.py`.
- UI behavior: Add progress or control changes in `app/static/job_progress_monitor.js`, `app/static/jobs_actions.js`, or `app/static/jobs_page_bootstrap.js`.

**New Data Import Path:**
- API code: Add request models and endpoints in `app/api/import_data.py`.
- Import logic: Add file scanning/import functions in `scripts/import_vipdoc_with_pytdx.py` or aggregation helpers in `scripts/build_30m_from_5m.py`.
- UI controls: Add controls in `app/static/data_import_page.js` or `app/static/data_import_type_addon.js`.

**New Configuration Setting:**
- Environment-backed setting: Add field to `Settings` in `app/core/config.py`.
- Strategy runtime setting: Add default to `DEFAULT_CONFIG` in `app/services/config_service.py` and read it where needed in service code.
- Standalone script access: For scripts executed as subprocesses, load `.env` explicitly as in `scripts/progress_run_now.py` or use `app/db/session.py`.

**New Database Access Helper:**
- Reusable K-line or analysis write logic: Add methods to `KlineRepository` in `app/db/repository.py`.
- Feature-specific direct query logic: Keep local helper functions in the owning router or service, matching `app/api/latest.py`, `app/api/jobs.py`, and `app/services/strategy2560_service.py`.
- Schema setup: Place DDL in `sql/2560_schema_v2.4.sql` because `scripts/apply_schema.py` reads that path.

**New Static WebUI View:**
- Base markup: Add a `section` in `app/static/index.html` when the view is core and always present.
- Dynamic add-on page: Add an IIFE script in `app/static/` that creates its own section and navigation entry, matching `app/static/data_import_page.js` and `app/static/annotation2568.js`.
- Navigation grouping: Update `app/static/nested_menu_reorg.js` and `app/static/nested_menu_reorg.css` for menu placement and styles.
- API calls: Use local `fetch` helpers and backend routes; no npm/frontend build pipeline exists.

**New CLI Operation:**
- Implementation: Add a verb-first script under `scripts/`, e.g. `scripts/rebuild_x.py` or `scripts/import_x.py`.
- Shared backend logic: Import from `app/db/session.py` and `app/services/` instead of duplicating service behavior.
- Docker worker use: Update `compose.yaml`, `docker-compose.yml`, or `scripts/job_worker.py` when the command must run as a service.

**Utilities:**
- Shared backend helpers: Place under `app/services/` when business-domain-specific, `app/db/` when database-specific, or the owning script when only a single CLI uses it.
- Shared frontend helpers: Keep in the owning static JS file unless multiple currently loaded scripts need the helper.

## Special Directories

**`.env` and `.env.example`:**
- Purpose: Environment configuration for DB and app settings.
- Generated: No.
- Committed: `.env.example` is present as a template; `.env` is present and must be treated as secret-bearing environment configuration.

**`.venv/`:**
- Purpose: Local Python virtual environment.
- Generated: Yes.
- Committed: No intended source role.

**`logs/`:**
- Purpose: Runtime job logs read by `/api/jobs/executions/{job_id}/logs`.
- Generated: Yes.
- Committed: Present in the working tree with job log files.

**`app/static/*.bak_*`:**
- Purpose: Backup snapshots of `app/static/index.html`.
- Generated: Yes.
- Committed: Present in the working tree.

**`scripts/apply_*_patch.py`:**
- Purpose: Idempotent patch scripts for UI/backend feature additions.
- Generated: No.
- Committed: Present in the working tree.

**`sql/`:**
- Purpose: Database DDL expected by `scripts/apply_schema.py`, Dockerfiles, and compose mounts.
- Generated: No.
- Committed: Directory not detected in the current file tree.

**`__pycache__/`:**
- Purpose: Python bytecode caches under `app/` and `scripts/`.
- Generated: Yes.
- Committed: No intended source role.

---

*Structure analysis: 2026-05-11*

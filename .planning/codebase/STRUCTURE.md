# Codebase Structure

**Analysis Date:** 2026-05-11

## Directory Layout

```text
strategy2560_project_v2_engine/
├── app/                    # FastAPI application, services, DB access, schemas, static WebUI
│   ├── main.py             # Deployed ASGI app entry point
│   ├── __init__.py         # Package initializer
│   ├── api/                # HTTP routers grouped by feature
│   ├── core/               # Settings and app-wide configuration
│   ├── db/                 # SQLAlchemy engine/session and repository helpers
│   ├── schemas/            # Pydantic response schemas
│   ├── services/           # Strategy engines, query services, annotations, reports
│   └── static/             # Plain HTML/CSS/JS single-page WebUI
├── scripts/                # CLI and background operational scripts
├── logs/                   # Runtime job logs
├── .github/workflows/      # Docker image build workflow
├── .planning/codebase/     # GSD codebase mapping documents
├── Dockerfile              # Web image build using Python 3.11 slim
├── docker-compose.yml      # Active web and worker compose file
├── requirements.txt        # Main Python dependency pins
└── README.md               # Current project overview and runbook
```

## Directory Purposes

**`app/`:**
- Runtime application package for the web service and shared backend logic.
- Main runtime entry is `app/main.py`.
- API routers live in `app/api/`, configuration in `app/core/`, DB access in `app/db/`, service logic in `app/services/`, schemas in `app/schemas/`, and frontend assets in `app/static/`.

**`app/api/`:**
- HTTP router modules for strategy endpoints, latest-status endpoints, data-quality endpoints, job endpoints, import endpoints, and 2568 annotation/report endpoints.
- Key files: `app/api/strategy2560.py`, `app/api/strategy2568.py`, `app/api/strategy2568_report.py`, `app/api/latest.py`, `app/api/jobs.py`, `app/api/import_data.py`, `app/api/data_quality.py`.

**`app/core/`:**
- Environment-driven settings and helper accessors.
- Key file: `app/core/config.py`.

**`app/db/`:**
- SQLAlchemy session setup and reusable data access helpers.
- Key files: `app/db/session.py`, `app/db/repository.py`.

**`app/schemas/`:**
- Shared Pydantic schemas.
- Key file: `app/schemas/common.py`.

**`app/services/`:**
- Business logic shared by routers and scripts.
- Contains indicator engines, strategy engines, statistics, tags, annotations, PDF export, and configuration helpers.

**`app/static/`:**
- Browser UI served directly by FastAPI without a build step.
- Current active entry is `app/static/index.html`; the old HTML backup snapshots were removed during cleanup.

**`scripts/`:**
- Command-line operations, background workers, batch data processing, and deployment helpers.
- Key files: `scripts/apply_schema.py`, `scripts/import_vipdoc_with_pytdx.py`, `scripts/build_30m_from_5m.py`, `scripts/rebuild_technical_indicator.py`, `scripts/run_2560_analysis.py`, `scripts/progress_run_now.py`, `scripts/job_worker.py`, `scripts/start_webui.sh`.
- Historical patch scripts were removed in the cleanup pass.

**`logs/`:**
- Runtime output for background jobs and worker runs.

**`.github/workflows/`:**
- CI workflow definitions, primarily Docker image build.

**`.planning/codebase/`:**
- GSD-generated codebase mapping documents.

## Key File Locations

**Entry Points:**
- `app/main.py`: Deployed ASGI app for Uvicorn, router registration, `/health`, and `/`.
- `scripts/run_2560_analysis.py`: CLI entry for 2560 analysis and optional statistics rebuild.
- `scripts/rebuild_technical_indicator.py`: CLI entry for technical indicator rebuilds.
- `scripts/import_vipdoc_with_pytdx.py`: CLI helper for vipdoc import.
- `scripts/build_30m_from_5m.py`: CLI helper for 5m-to-30m aggregation.
- `scripts/apply_schema.py`: CLI entry for applying `sql/2560_schema_v2.4.sql` when that SQL file is present.
- `scripts/job_worker.py`: Queue worker process used by compose worker service.
- `scripts/progress_run_now.py`: Parallel progress runner spawned by `app/api/jobs.py`.
- `app/static/index.html`: WebUI entry served at `/`.

**Configuration:**
- `app/core/config.py`: Pydantic settings and SQLAlchemy URL construction.
- `requirements.txt`: Main dependency pins used by Docker and local installs.
- `Dockerfile`: Python 3.11 slim image, copies `app/` and `scripts/`, runs `uvicorn app.main:app`.
- `docker-compose.yml`: Active compose file defining `web` and `worker`.

## Notes After Cleanup

- `compose.yaml`, `Dockerfile.prod`, `requirements.backend.txt`, and the old deployment README files were removed.
- Historical patch scripts in `scripts/apply_*_patch.py` were removed.
- `PROJECT_OVERVIEW.md` was removed; the current `README.md` is now the primary project overview.

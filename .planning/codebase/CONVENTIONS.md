# Coding Conventions

**Analysis Date:** 2026-05-11

## Naming Patterns

**Files:**
- Use lowercase snake_case for Python modules under `app/` and `scripts/`: `app/api/strategy2560.py`, `app/services/signal_engine_2560.py`, `scripts/rebuild_technical_indicator.py`.
- Use domain suffixes for service modules: `app/services/indicator_engine.py`, `app/services/statistics_engine.py`, `app/services/config_service.py`.
- Use API route modules by feature area: `app/api/jobs.py`, `app/api/import_data.py`, `app/api/data_quality.py`, `app/api/strategy2568_report.py`.
- Use plain browser asset names for WebUI code in `app/static/`: `app/static/app.js`, `app/static/job_progress_monitor.js`, `app/static/styles.css`.
- Patch and migration helper scripts live in `scripts/` with `apply_*_patch.py` names: `scripts/apply_nested_menu_reorg_patch.py`, `scripts/apply_import_backend_full_patch.py`.

**Functions:**
- Use snake_case for Python functions and methods: `normalize_code()` in `app/api/strategy2560.py`, `get_db()` in `app/db/session.py`, `enrich_indicators()` in `app/services/indicator_engine.py`.
- Prefix private helper functions with `_`: `_table_exists()` and `_ensure_tables()` in `app/api/jobs.py`, `_read_daily()` and `_chunks()` in `scripts/import_vipdoc_with_pytdx.py`.
- Use route handler names that match the endpoint concept: `overview()`, `stocks()`, `run_analysis()` in `app/api/strategy2560.py`; `enqueue_job()` and `run_now()` in `app/api/jobs.py`.
- Use verb phrases for CLI/script operations: `load_codes()` in `scripts/run_2560_analysis.py`, `rebuild_period()` in `scripts/rebuild_technical_indicator.py`, `build_30m_parallel()` in `scripts/build_30m_from_5m.py`.
- Use camelCase for browser functions in `app/static/app.js`: `loadOverview()`, `renderTable()`, `runSelected()`, `loadDiagnostics()`.

**Variables:**
- Use snake_case for Python locals and parameters: `market_type`, `batch_id`, `signal_time`, `commit_every` in `app/services/signal_engine_2560.py`.
- Use uppercase constants for module-level static values: `SUPPORTED_TYPES` and `NORMALIZED_CODE_SQL` in `app/api/strategy2560.py`, `PROJECT_ROOT` in `app/api/jobs.py`.
- Use short local aliases for repeated query fragments only inside compact database helpers: `mt`, `q_norm`, `q_code`, `where`, and `params` in `app/api/strategy2560.py`.
- Use camelCase for browser state and DOM variables: `pageSize`, `marketType`, `currentStocks`, and `selectedCodes` in `app/static/app.js`.

**Types:**
- Use Pydantic `BaseModel` classes for request bodies: `RunAnalysisRequest` in `app/api/strategy2560.py`, `EnqueueJobRequest` and `RunNowRequest` in `app/api/jobs.py`, `ImportRunRequest` in `app/api/import_data.py`.
- Name Pydantic request types with a `Request` suffix: `ImportScanRequest`, `Build30mRequest`, `RunNowRequest`.
- Use service classes with domain names: `SignalEngine2560` in `app/services/signal_engine_2560.py`, `Strategy2560Service` in `app/services/strategy2560_service.py`, `ConfigService` in `app/services/config_service.py`.
- Prefer built-in generic annotations for new code: `list[str]`, `dict[str, Any]`, and `str | None` appear in `app/api/jobs.py`, `app/api/strategy2560.py`, and `scripts/rebuild_technical_indicator.py`.
- Preserve `Optional[...]` style when editing modules that already use it heavily: `app/api/import_data.py`, `app/db/repository.py`, and `app/services/signal_engine_2560.py`.

## Code Style

**Formatting:**
- Formatting tool: Not detected. No `.prettierrc`, `.eslintrc*`, `eslint.config.*`, `biome.json`, `pyproject.toml`, `setup.cfg`, or `tox.ini` is present in the repository.
- Indentation is 4 spaces in Python files such as `app/main.py`, `app/api/jobs.py`, and `scripts/rebuild_technical_indicator.py`.
- Keep imports at the top of Python modules, grouped by standard library, third-party, and local imports when the file follows that pattern: `app/api/jobs.py`, `app/api/import_data.py`, and `scripts/rebuild_technical_indicator.py`.
- Maintain the local quote style in the file being edited. Older modules use single quotes heavily (`app/main.py`, `app/api/strategy2560.py`, `app/services/signal_engine_2560.py`); newer modules use double quotes heavily (`app/api/jobs.py`, `app/api/import_data.py`).
- Use multiline SQL strings with `sqlalchemy.text()` for readable DDL and complex queries: `_ensure_tables()` in `app/api/jobs.py`, `_ensure_import_tables()` in `app/api/import_data.py`, `upsert_indicators()` in `app/db/repository.py`.
- Use compact one-line dictionaries only for small API responses or SQL params; split large payloads across lines as in `app/api/jobs.py` and `app/api/import_data.py`.
- Browser JavaScript in `app/static/app.js` uses 2-space indentation, semicolons, `const`/`let`, and template literals.

**Linting:**
- Linting tool: Not detected. No Ruff, Flake8, Black, isort, ESLint, Prettier, Biome, mypy, or TypeScript configuration is present.
- Treat existing runtime validation as the effective quality gate: FastAPI/Pydantic validation in `app/api/strategy2560.py`, `app/api/jobs.py`, and `app/api/import_data.py`.
- For new Python code, keep functions type-annotated where adjacent code is annotated: `app/api/jobs.py`, `app/api/import_data.py`, `scripts/rebuild_technical_indicator.py`.
- For new browser code, match the direct DOM style in `app/static/app.js` instead of adding a frontend framework.

## Import Organization

**Order:**
1. Standard library imports first: `json`, `os`, `subprocess`, `signal`, `sys`, `Path`, `Any` in `app/api/jobs.py`.
2. Third-party imports second: `fastapi`, `pydantic`, `sqlalchemy`, `pandas`, `numpy` in `app/api/jobs.py`, `app/api/import_data.py`, `app/services/indicator_engine.py`.
3. Local application imports last: `app.db.session`, `app.services.*`, `app.schemas.common` in `app/main.py`, `app/api/strategy2560.py`, and `scripts/run_2560_analysis.py`.

**Path Aliases:**
- Use absolute imports rooted at `app`: `from app.db.session import get_db` in `app/api/jobs.py`, `from app.services.signal_engine_2560 import SignalEngine2560` in `app/api/strategy2560.py`.
- Scripts rely on `PYTHONPATH=$PWD` so they can import application modules: `scripts/run_2560_analysis.py`, `scripts/rebuild_technical_indicator.py`, and `README.md`.
- No Python package alias configuration is detected because there is no `pyproject.toml`, `setup.cfg`, or `mypy.ini`.
- Static JavaScript is loaded directly by HTML and does not use ES modules or bundler imports: `app/static/app.js`, `app/static/index.html`.

## Error Handling

**Patterns:**
- API routes usually return structured JSON dictionaries for expected missing state: `execution_progress()` in `app/api/jobs.py` returns `{"ok": False, "message": "job not found"}`; `execution_logs()` returns `{"ok": False, "lines": []}`.
- Use FastAPI `HTTPException` for true resource-not-found API errors: `detail()` and `batch()` in `app/api/strategy2560.py` raise 404 errors.
- Use Pydantic `Field()` bounds for input validation instead of manual checks: `limit`, `priority`, `shards`, `workers`, and `page_size` in `app/api/jobs.py`, `app/api/import_data.py`, and `app/api/strategy2560.py`.
- Database write loops should rollback on per-item failures and continue collecting errors when the operation is batch-oriented: `SignalEngine2560.run()` in `app/services/signal_engine_2560.py`, `import_daily_file()` and `import_lc5_file()` in `scripts/import_vipdoc_with_pytdx.py`.
- CLI scripts fail fast with `RuntimeError` or `SystemExit` for invalid prerequisites: `scripts/rebuild_technical_indicator.py`, `scripts/job_worker.py`, and `scripts/import_vipdoc_with_pytdx.py`.
- Avoid broad silent `except Exception` in new code unless the file already uses best-effort fallback behavior. Existing broad fallbacks appear in `app/db/repository.py`, `app/services/config_service.py`, `app/main.py`, and `scripts/rebuild_technical_indicator.py`.
- Browser code catches request failures at user-facing action boundaries and writes the error message into the page: `loadHealth()`, `runSelected()`, and `runProbe()` in `app/static/app.js`.

## Logging

**Framework:** console/print

**Patterns:**
- No Python `logging` configuration is detected in `app/` or `scripts/`.
- CLI and batch scripts report progress with `print()`: `scripts/run_2560_analysis.py`, `scripts/rebuild_technical_indicator.py`, `scripts/build_30m_from_5m.py`.
- Long-running job execution writes stdout/stderr to log files and exposes tail reads through the API: `run_now()` and `_tail_lines()` in `app/api/jobs.py`.
- The progress runner centralizes script logging in a `log()` helper that flushes output: `scripts/progress_run_now.py`.
- Browser diagnostics use `console.error()` only for background refresh failures: `app/static/job_progress_monitor.js`.
- For new backend code, prefer returning API-visible status fields and job log lines consistent with `app/api/jobs.py` instead of introducing a separate logging framework.

## Comments

**When to Comment:**
- Use comments/docstrings for operational scripts, Chinese domain explanations, and non-obvious data maintenance workflows: `scripts/rebuild_technical_indicator.py`, `scripts/run_2560_analysis.py`, and `README_2560_DAILY_OPS.md`.
- Keep API route code mostly self-explanatory; add comments only when the endpoint has non-obvious operational behavior such as shard progress in `app/api/jobs.py`.
- Use inline comments sparingly in static JavaScript; `app/static/app.js` is primarily readable function names and DOM operations without comments.

**JSDoc/TSDoc:**
- Not used. No JSDoc or TSDoc blocks are present in `app/static/app.js` or other `app/static/*.js` files.
- Python docstrings are used selectively in scripts and not consistently required for every function: `load_codes()` in `scripts/run_2560_analysis.py`, module docstring in `scripts/rebuild_technical_indicator.py`.

## Function Design

**Size:** Keep new route handlers and helpers focused. Existing files contain some large functions for SQL-heavy workflows, but new code should follow smaller helper patterns like `_format_seconds()` and `_tail_lines()` in `app/api/jobs.py`, `normalize_code()` and `market_code()` in `app/api/strategy2560.py`.

**Parameters:** Prefer explicit typed parameters and FastAPI `Query()` constraints for route inputs: `stocks()` and `signals()` in `app/api/strategy2560.py`, `execution_logs()` in `app/api/jobs.py`, `import_files()` in `app/api/import_data.py`.

**Return Values:** Return plain dictionaries/lists from route handlers unless the endpoint already uses `ApiResponse`: `app/api/jobs.py` returns dictionaries and lists; `app/api/strategy2560.py` wraps most strategy endpoints with `ApiResponse` from `app/schemas/common.py`.

**Database Sessions:** Accept `db: Session = Depends(get_db)` in API routes and `with SessionLocal() as db` in CLI scripts: `app/api/strategy2560.py`, `app/api/import_data.py`, `scripts/run_2560_analysis.py`, `scripts/rebuild_statistics.py`.

**Data Frames:** For pandas work, copy and sort before mutation, coerce numeric columns explicitly, and return empty `DataFrame` for missing inputs: `enrich_indicators()` in `app/services/indicator_engine.py`, `compute_indicators()` in `scripts/rebuild_technical_indicator.py`.

## Module Design

**Exports:** Modules expose named classes/functions directly; no `__all__` pattern is used. Examples: `SignalEngine2560` from `app/services/signal_engine_2560.py`, `KlineRepository` from `app/db/repository.py`, `router` from `app/api/jobs.py`.

**Barrel Files:** Package `__init__.py` files are mostly empty and should stay lightweight: `app/api/__init__.py`, `app/services/__init__.py`, `app/db/__init__.py`, `app/core/__init__.py`. Do not add broad re-export barrels unless the codebase adopts that pattern.

**API Modules:** Define `router = APIRouter(...)` near the top, define request models and helpers before route handlers, then register route functions: `app/api/jobs.py`, `app/api/import_data.py`, `app/api/strategy2560.py`.

**Service Modules:** Put business logic in `app/services/` and keep API modules as orchestration layers: `app/services/signal_engine_2560.py`, `app/services/statistics_engine.py`, `app/services/report_2568_pdf.py`.

**Repository Modules:** Keep database read/write primitives in `app/db/repository.py` when shared by services. Direct SQL inside route modules is also used for feature-specific endpoints such as `app/api/jobs.py` and `app/api/import_data.py`.

---

*Convention analysis: 2026-05-11*

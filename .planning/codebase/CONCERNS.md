# Codebase Concerns

**Analysis Date:** 2026-05-11

## Tech Debt

**Schema management split across runtime endpoints, scripts, and missing SQL files:**
- Issue: Runtime API handlers create operational tables directly with `CREATE TABLE IF NOT EXISTS`, while the standalone schema applicator expects a missing SQL file.
- Files: `app/api/jobs.py`, `app/api/import_data.py`, `scripts/apply_schema.py`
- Impact: Fresh environments can start with incomplete schemas, and app-created schemas can drift from production expectations until a committed migration path exists.
- Fix approach: Add a committed migration/schema directory, move all table definitions into versioned migrations, make `scripts/apply_schema.py` apply those migrations, and remove runtime DDL from request paths.

**Frontend is assembled from multiple bootstrap scripts with polling installers:**
- Issue: `app/static/index.html` loads the main app plus several scripts that inject or patch UI sections at runtime; many use `setInterval` to keep reapplying boot logic.
- Files: `app/static/index.html`, `app/static/app.js`, `app/static/jobs_page_bootstrap.js`, `app/static/jobs_actions.js`, `app/static/job_progress_monitor.js`, `app/static/module_reorg.js`, `app/static/nested_menu_reorg.js`, `app/static/data_import_page.js`, `app/static/data_import_type_addon.js`, `app/static/annotation2568.js`
- Impact: UI ownership is fragmented, duplicate IDs and duplicate controls are easy to introduce, and repeated boot checks add avoidable browser work.
- Fix approach: Consolidate the static UI into one module per page/view, bind events once on `DOMContentLoaded`, and remove interval-based installers except for real data polling.

**Duplicate FastAPI application definitions:**
- Issue: `app/main.py` defines the full application while `app/__init__.py` defines a second app with only a subset of routers.
- Files: `app/main.py`, `app/__init__.py`, `Dockerfile`
- Impact: Starting the wrong module exposes a different API surface, which can make deployment and local debugging disagree.
- Fix approach: Keep only `app/main.py` as the application entry point; make `app/__init__.py` package metadata only, or import `app.main.app` explicitly without constructing another app.

**Business rules are hard-coded in service code:**
- Issue: Strategy thresholds, labels, market routing, and annotation categories live directly in service modules.
- Files: `app/services/signal_engine_2560.py`, `app/services/annotation_engine_2568.py`, `app/api/strategy2560.py`, `app/api/latest.py`, `scripts/progress_run_now.py`, `scripts/build_30m_from_5m.py`
- Impact: Changes to strategy definitions require code edits across multiple modules, and market filters can diverge between endpoints and scripts.
- Fix approach: Centralize market normalization and strategy thresholds in shared modules, with database-backed configuration only where validation and defaults are explicit.

**Silent fallback hides configuration and data errors:**
- Issue: Configuration loading and minute data reads swallow exceptions and continue with defaults or empty data.
- Files: `app/services/config_service.py`, `app/db/repository.py`
- Impact: Missing `strategy_config`, schema errors, and read failures can produce normal-looking empty or default-based results.
- Fix approach: Log structured warnings for expected missing optional tables, raise unexpected database errors, and surface configuration source in API responses or batch messages.

## Known Bugs

**`/api/jobs/run-now` writes a `pid` column that the runtime schema does not create:**
- Symptoms: On a fresh database where `job_execution` is created by `app/api/jobs.py`, the endpoint inserts a job execution and then updates `pid`, but `pid` is absent from the `CREATE TABLE` statement.
- Files: `app/api/jobs.py`
- Trigger: Call `POST /api/jobs/run-now` after `_ensure_tables()` creates `job_execution` from the in-code schema.
- Workaround: Manually add `pid` to `job_execution`, or remove the `pid` update until a migration adds the column.

**Queued jobs and immediate jobs use different execution models:**
- Symptoms: `POST /api/jobs/enqueue` creates `job_queue` rows, but `scripts/job_worker.py` runs a legacy shell script when present and does not create or link a `job_execution` row for queue-driven progress tracking.
- Files: `app/api/jobs.py`, `scripts/job_worker.py`, `scripts/progress_run_now.py`
- Trigger: Enqueue a job and run `scripts/job_worker.py` with the legacy script present.
- Workaround: Use `POST /api/jobs/run-now` for tracked executions, or update `scripts/job_worker.py` to create `job_execution` rows and pass `JOB_ID` into `scripts/progress_run_now.py`.

**Future return backfill is a placeholder:**
- Symptoms: Backfill always returns `updated: 0` and does not calculate or persist future returns.
- Files: `app/services/future_return_engine.py`, `scripts/backfill_future_returns.py`
- Trigger: Run the backfill script or call `FutureReturnEngine.backfill()`.
- Workaround: Treat future-return metrics as unavailable until the engine is implemented against a confirmed trading calendar.

## Security Considerations

**No authentication or authorization on operational endpoints:**
- Risk: Any caller that can reach the app can run analysis jobs, enqueue background work, scan/import local data paths, build 30m data, fetch logs, and export reports.
- Files: `app/main.py`, `app/api/jobs.py`, `app/api/import_data.py`, `app/api/strategy2560.py`, `app/api/strategy2568.py`, `app/api/strategy2568_report.py`
- Current mitigation: Not detected in code; no auth dependency, API key check, session middleware, or CORS policy is configured.
- Recommendations: Add an authentication dependency for all `/api/*` routes, separate read-only from mutating endpoints, and restrict operational routes to admin users or local-only deployment.

**Local file path exposure through import scan and file tracking:**
- Risk: Request payloads accept `source_dir` and return scan directories plus file samples. Imported file paths are stored and exposed through API responses.
- Files: `app/api/import_data.py`, `scripts/import_vipdoc_with_pytdx.py`
- Current mitigation: Import type and worker counts have Pydantic limits, but the source directory itself is unrestricted.
- Recommendations: Restrict imports to configured allowlisted roots, reject path traversal and arbitrary absolute paths, and avoid returning full host paths to clients.

**Log endpoint trusts database file paths:**
- Risk: `GET /api/jobs/executions/{job_id}/logs` reads `job_execution.log_file`; absolute paths are used as-is and relative paths are resolved under the project root.
- Files: `app/api/jobs.py`
- Current mitigation: The endpoint only reads paths stored in the database and returns the tail, but there is no path allowlist or auth boundary.
- Recommendations: Store log basenames instead of arbitrary paths, force resolution under `logs/`, reject symlinks and absolute paths, and require authorization.

**Stored and reflected frontend HTML injection:**
- Risk: Static JavaScript writes database/API values into `innerHTML` template strings without escaping. Stock names, tags, reasons, statuses, messages, and annotation fields can become executable markup if tainted data reaches the database.
- Files: `app/static/app.js`, `app/static/annotation2568.js`, `app/static/jobs_page_bootstrap.js`, `app/static/job_progress_monitor.js`, `app/static/data_import_page.js`, `app/static/data_import_type_addon.js`, `app/static/diagnostic_menu_append.js`, `app/static/diagnostic_append.js`
- Current mitigation: Not detected; most table renderers interpolate values directly.
- Recommendations: Use `textContent`/DOM construction for cells, or apply a single HTML escape helper to all interpolated values before assigning `innerHTML`.

**Health endpoint returns raw exception messages:**
- Risk: Database connection failures can expose hostnames, usernames, driver errors, or network details through `/health`.
- Files: `app/main.py`, `app/__init__.py`, `app/db/session.py`, `app/core/config.py`
- Current mitigation: The endpoint catches exceptions and returns status `warning`, but includes `str(exc)`.
- Recommendations: Return a generic health message to clients and log details server-side.

**Default database connection settings include internal host and username:**
- Risk: `Settings` contains a concrete private-network database host and database username as defaults.
- Files: `app/core/config.py`
- Current mitigation: `.env` and `.env.example` exist; `.env` contents were not read.
- Recommendations: Use neutral localhost or empty defaults, require production values through environment variables, and document required env var names without embedding environment-specific identities.

## Performance Bottlenecks

**Strategy run performs per-code pandas reads, indicator recalculation, and database writes:**
- Problem: `SignalEngine2560.run()` loops code-by-code, reads daily/30m/5m data, recalculates indicators, upserts indicators, scans signals, and commits every 50 processed codes.
- Files: `app/services/signal_engine_2560.py`, `app/db/repository.py`, `app/services/indicator_engine.py`
- Cause: The workflow mixes indicator generation and signal scanning in the request path.
- Improvement path: Precompute indicators in dedicated jobs, scan from `technical_indicator`, batch database reads by code groups, and keep API requests as job triggers/status views.

**Immediate job runner uses HTTP calls back into the same app:**
- Problem: `scripts/progress_run_now.py` creates concurrent workers that call `POST /api/strategy/2560/run` on the local web server with up to one-hour request timeouts.
- Files: `app/api/jobs.py`, `scripts/progress_run_now.py`
- Cause: The background worker re-enters FastAPI instead of invoking service code directly.
- Improvement path: Move job execution into an application service that both API and worker call directly, and keep HTTP for user-facing control/status only.

**30m rebuild deletes and reinserts per stock:**
- Problem: `scripts/build_30m_from_5m.py` deletes existing 30m rows for each code/date range and reinserts aggregated rows in parallel sessions.
- Files: `scripts/build_30m_from_5m.py`, `app/api/import_data.py`
- Cause: Rebuild uses destructive replacement rather than idempotent upsert keyed by `(code, period, date)`.
- Improvement path: Use temporary staging plus atomic swap for full rebuilds, or use `ON DUPLICATE KEY UPDATE` for incremental aggregation.

**Annotation endpoint loads recent daily rows into pandas per request:**
- Problem: `AnnotationEngine2568.annotations()` fetches up to 5,000 stocks, reads recent daily data, creates per-code DataFrames, and computes all labels synchronously.
- Files: `app/api/strategy2568.py`, `app/services/annotation_engine_2568.py`, `app/api/strategy2568_report.py`
- Cause: Annotation and PDF generation are request-time computations without caching.
- Improvement path: Cache latest annotation snapshots by market/filter inputs, precompute daily annotations after indicator rebuilds, and paginate expensive views.

**Browser bootstrap intervals run continuously:**
- Problem: Several UI modules call `setInterval` every 1 to 1.5 seconds to ensure sections/buttons exist.
- Files: `app/static/jobs_page_bootstrap.js`, `app/static/jobs_actions.js`, `app/static/job_progress_monitor.js`, `app/static/module_reorg.js`, `app/static/nested_menu_reorg.js`, `app/static/data_import_page.js`, `app/static/data_import_type_addon.js`, `app/static/annotation2568.js`
- Cause: Runtime patching is used instead of deterministic page initialization.
- Improvement path: Initialize each view once, use event delegation for navigation, and reserve intervals for actual progress polling only while a job is active.

## Fragile Areas

**Job queue and progress tracking:**
- Files: `app/api/jobs.py`, `scripts/job_worker.py`, `scripts/progress_run_now.py`, `app/static/job_progress_monitor.js`, `app/static/jobs_page_bootstrap.js`, `app/static/jobs_actions.js`
- Why fragile: Table schemas, process IDs, queue rows, execution rows, log files, and UI polling are coupled across API, scripts, and static JS. Runtime schema lacks columns that some code expects.
- Safe modification: Start by formalizing the job schema migration, then make one execution path authoritative for enqueue/run-now/worker flows.
- Test coverage: No tests detected for job state transitions, failed subprocesses, missing log files, or cancellation semantics.

**Market-code filtering and normalization:**
- Files: `app/api/strategy2560.py`, `app/api/latest.py`, `app/api/jobs.py`, `app/services/annotation_engine_2568.py`, `scripts/progress_run_now.py`, `scripts/build_30m_from_5m.py`, `scripts/import_vipdoc_with_pytdx.py`
- Why fragile: Each module implements its own `sh/sz/sh60/sh68/sz00/sz30/all` logic, with different assumptions about dotted codes and normalized codes.
- Safe modification: Introduce one shared market helper module and migrate callers one at a time with parity tests for representative codes.
- Test coverage: No tests detected for code normalization, market filters, or SQL where-clause generation.

**Static UI table rendering:**
- Files: `app/static/app.js`, `app/static/annotation2568.js`, `app/static/jobs_page_bootstrap.js`, `app/static/data_import_page.js`, `app/static/data_import_type_addon.js`
- Why fragile: Table rendering mixes data formatting, HTML construction, and event binding in long functions with direct DOM IDs.
- Safe modification: Add a small escaped table-rendering helper, migrate one view at a time, and keep existing element IDs stable.
- Test coverage: No browser or DOM tests detected for page bootstrapping, table rendering, navigation, or polling behavior.

**Strategy calculations and explanations:**
- Files: `app/services/signal_engine_2560.py`, `app/services/indicator_engine.py`, `app/services/tag_service.py`, `app/services/config_service.py`, `app/services/statistics_engine.py`
- Why fragile: Numeric logic, tag generation, text explanations, data-quality handling, and persistence are tightly coupled in one pass.
- Safe modification: Extract pure functions for signal qualification and tag generation before changing thresholds or persistence.
- Test coverage: No unit tests detected for indicator math, 2560 scan rules, tag classifications, or statistics rebuild output.

**Data import and aggregation pipeline:**
- Files: `app/api/import_data.py`, `scripts/import_vipdoc_with_pytdx.py`, `scripts/build_30m_from_5m.py`, `scripts/rebuild_technical_indicator.py`, `scripts/fill_recent_with_pytdx_hq.py`
- Why fragile: Imports accept filesystem paths, run parallel database writes, update status tables, and feed downstream indicators without a single orchestration boundary.
- Safe modification: Add explicit import job states, validate allowed source roots, and make each stage idempotent before increasing worker counts.
- Test coverage: No tests detected for malformed vipdoc files, partial imports, duplicate rows, retry behavior, or failed worker futures.

## Scaling Limits

**Database connection pool versus concurrent workers:**
- Current capacity: API default pool size is `DB_POOL_SIZE=20`; job and import requests allow `shards` up to 32 and import/build workers up to 64.
- Limit: Concurrent API requests, job runner threads, import threads, and per-code sessions can exceed MySQL connection limits or saturate the database.
- Scaling path: Cap workers by configured database capacity, add backpressure for long-running jobs, and centralize worker-pool sizing.
- Files: `app/core/config.py`, `app/db/session.py`, `app/api/jobs.py`, `app/api/import_data.py`, `scripts/progress_run_now.py`, `scripts/import_vipdoc_with_pytdx.py`, `scripts/build_30m_from_5m.py`

**Request-time full-market operations:**
- Current capacity: Several endpoints accept limits up to 5,000 or 10,000 rows and perform synchronous database or pandas work.
- Limit: Full-market operations can tie up web workers and make the UI appear hung during analysis, annotation, import, or PDF generation.
- Scaling path: Move full-market operations to background jobs, return job IDs immediately, and paginate or cache read-heavy endpoints.
- Files: `app/api/strategy2560.py`, `app/api/strategy2568.py`, `app/api/strategy2568_report.py`, `app/api/latest.py`, `app/api/import_data.py`

**Log files grow without retention policy:**
- Current capacity: `logs/` contains job progress logs, and scripts append daily or per-job logs.
- Limit: Long-running or repeated jobs can accumulate logs indefinitely in the project directory or container writable layer.
- Scaling path: Add log rotation, retention cleanup, and a bounded log storage directory outside source-controlled paths.
- Files: `logs/`, `app/api/jobs.py`, `scripts/progress_run_now.py`, `scripts/job_worker.py`

## Dependencies at Risk

**`pytdx`:**
- Risk: Market data import depends on `pytdx` readers for vipdoc formats, and the import script raises at runtime if readers are unavailable.
- Impact: Data import endpoints and CLI imports fail for daily or 5m vipdoc files.
- Migration plan: Keep importer boundaries isolated, add fixture-based parser tests, and evaluate a maintained data reader or a local parser for required vipdoc formats.
- Files: `requirements.txt`, `scripts/import_vipdoc_with_pytdx.py`, `app/api/import_data.py`

**Unpinned system-level runtime behavior in Docker images:**
- Risk: The Docker image installs latest `pip`, while local development may use a different Python minor version from the container.
- Impact: Container behavior can differ from the local virtual environment, especially for pandas/numpy wheels and Python minor-version compatibility.
- Migration plan: Pick one Python minor version, pin image digests for production, and run build/test checks for that image.
- Files: `Dockerfile`, `requirements.txt`

## Missing Critical Features

**Automated test suite:**
- Problem: No `pytest`, unittest, browser, or API test suite is detected; only `app/api/latest.py` has `test` in its filename by substring.
- Blocks: Safe changes to strategy rules, SQL generation, job lifecycle, imports, and frontend rendering.
- Files: `app/`, `scripts/`, `requirements.txt`

**Database migrations:**
- Problem: There is no detected migration framework or committed SQL schema directory, while runtime code depends on many MySQL tables.
- Blocks: Reliable fresh installs, production upgrades, and reproducible CI setup.
- Files: `app/api/jobs.py`, `app/api/import_data.py`, `scripts/apply_schema.py`

**Authentication and role separation:**
- Problem: Read, write, import, run-job, and log APIs are all exposed without route-level authorization.
- Blocks: Safe deployment outside a trusted local network.
- Files: `app/main.py`, `app/api/jobs.py`, `app/api/import_data.py`, `app/api/strategy2560.py`, `app/api/strategy2568.py`

**Job cancellation and cooperative shutdown:**
- Problem: The active API has no cancel endpoint and `scripts/progress_run_now.py` does not check a cancellation flag while batches are running.
- Blocks: Operators cannot reliably stop long-running full-market jobs from the UI/API.
- Files: `app/api/jobs.py`, `scripts/progress_run_now.py`, `app/static/job_progress_monitor.js`

## Test Coverage Gaps

**Strategy and indicator math:**
- What's not tested: Moving averages, ATR, volume ratios, signal selection, cooldown behavior, ST filtering, tag generation, and statistics rebuilds.
- Files: `app/services/indicator_engine.py`, `app/services/signal_engine_2560.py`, `app/services/tag_service.py`, `app/services/statistics_engine.py`
- Risk: Small threshold or data-shape changes can silently alter signal output.
- Priority: High

**SQL and schema compatibility:**
- What's not tested: Runtime DDL, expected columns, table existence checks, raw SQL query parameters, and migrations/schema application.
- Files: `app/api/jobs.py`, `app/api/import_data.py`, `app/db/repository.py`, `app/services/strategy2560_service.py`, `scripts/apply_schema.py`
- Risk: Fresh deployments and upgraded databases fail at runtime instead of during CI.
- Priority: High

**Job lifecycle:**
- What's not tested: Enqueue, run-now, subprocess startup failure, progress aggregation, shard summaries, log tailing, failed batches, and missing runner scripts.
- Files: `app/api/jobs.py`, `scripts/job_worker.py`, `scripts/progress_run_now.py`, `app/static/job_progress_monitor.js`
- Risk: Long-running operational workflows can report incorrect status or fail after partial database writes.
- Priority: High

**Import pipeline:**
- What's not tested: File scanning, market matching, pytdx parse failures, date filtering, duplicate-row upserts, import status rows, and 30m aggregation output.
- Files: `app/api/import_data.py`, `scripts/import_vipdoc_with_pytdx.py`, `scripts/build_30m_from_5m.py`
- Risk: Bad or partial market data can propagate into indicators and strategy results.
- Priority: High

**Frontend rendering and XSS safety:**
- What's not tested: Escaping of API values, table rendering, navigation bootstraps, repeated interval installers, and job progress polling UI.
- Files: `app/static/app.js`, `app/static/annotation2568.js`, `app/static/jobs_page_bootstrap.js`, `app/static/job_progress_monitor.js`, `app/static/data_import_page.js`
- Risk: Tainted database values can execute markup, and UI regressions are only detected manually.
- Priority: Medium

---

*Concerns audit: 2026-05-11*

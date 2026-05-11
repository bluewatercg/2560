# Testing Patterns

**Analysis Date:** 2026-05-11

## Test Framework

**Runner:**
- Not detected. No `pytest`, `unittest`, `nose`, `vitest`, `jest`, or Playwright test configuration is present in the repository.
- No `jest.config.*`, `vitest.config.*`, `pytest.ini`, `tox.ini`, `setup.cfg`, or `pyproject.toml` file is present.
- No test files matching `*.test.*`, `*.spec.*`, or `*_test.go` are present.
- Dependencies in `requirements.txt` and `requirements.backend.txt` do not include pytest or coverage tooling.

**Assertion Library:**
- Not detected.
- Runtime validation is provided by Pydantic/FastAPI models in `app/api/strategy2560.py`, `app/api/jobs.py`, and `app/api/import_data.py`, but these are not test assertions.

**Run Commands:**
```bash
# Automated test suite
# Not available: no test runner is configured.

# Existing backend smoke run from README.md
python scripts/run_2560_analysis.py --limit 20

# Existing web smoke run from README.md
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Test File Organization

**Location:**
- Not detected. There is no `tests/` directory and no co-located Python or JavaScript test files.
- Application code lives under `app/`: `app/main.py`, `app/api/strategy2560.py`, `app/services/signal_engine_2560.py`, `app/db/repository.py`.
- Operational scripts live under `scripts/`: `scripts/run_2560_analysis.py`, `scripts/rebuild_technical_indicator.py`, `scripts/import_vipdoc_with_pytdx.py`.

**Naming:**
- No automated test naming pattern exists.
- Use `test_<module>.py` under a new `tests/` directory if tests are added, because the source files use Python modules such as `app/services/indicator_engine.py` and `app/api/jobs.py`.
- Use `test_<behavior>` function names for Python tests to match conventional pytest discovery if pytest is introduced.

**Structure:**
```text
tests/
├── test_indicator_engine.py      # For app/services/indicator_engine.py
├── test_strategy2560_api.py      # For app/api/strategy2560.py with FastAPI TestClient
├── test_jobs_api.py              # For app/api/jobs.py with DB/session overrides
└── test_import_data.py           # For app/api/import_data.py and import orchestration
```

## Test Structure

**Suite Organization:**
```python
def test_enrich_indicators_computes_core_columns():
    df = make_kline_frame()

    result = enrich_indicators(df, "30m", "test", cfg={})

    assert "ma25" in result.columns
    assert "vol_ratio" in result.columns
    assert result["data_quality_status"].notna().all()
```

**Patterns:**
- Unit-test pure calculation helpers first because they have the least infrastructure: `slope_pct()`, `atr()`, `enrich_indicators()`, and `to_indicator_rows()` in `app/services/indicator_engine.py`.
- Unit-test normalization and SQL-fragment helpers with table-free inputs: `normalize_code()`, `type_key_for_code()`, `market_code()`, `board_type()`, `market_type_matches()`, and `in_clause()` in `app/api/strategy2560.py`.
- For API tests, override `get_db()` from `app/db/session.py` instead of connecting to the configured MySQL database.
- For script tests, call helper functions directly instead of shelling out to scripts: `market_where()` and `load_codes()` in `scripts/run_2560_analysis.py`, `clean_scalar()` and `get_period_range()` in `scripts/rebuild_technical_indicator.py`.
- For database write workflows, assert transaction behavior around commits/rollbacks with a fake session or test database because `SignalEngine2560.run()` in `app/services/signal_engine_2560.py` and import functions in `scripts/import_vipdoc_with_pytdx.py` commit throughout processing.

## Mocking

**Framework:** Not detected. Use pytest monkeypatch/unittest.mock if a test framework is introduced.

**Patterns:**
```python
def test_health_reports_database_status(monkeypatch):
    monkeypatch.setattr("app.main.ping_database", lambda: True)

    response = client.get("/health")

    assert response.json()["database"] is True
```

**What to Mock:**
- Mock database sessions for API routes using `get_db()` dependency overrides from `app/db/session.py`.
- Mock filesystem reads and process spawning around `run_now()` in `app/api/jobs.py` because it creates `logs/`, opens a log file, and launches `scripts/progress_run_now.py`.
- Mock `scan_vipdoc_files()`, `import_vipdoc_files_parallel()`, and `build_30m_parallel()` for `app/api/import_data.py` route tests because they touch local market-data files and perform bulk imports.
- Mock `pytdx` readers used by `scripts/import_vipdoc_with_pytdx.py` because `pytdx` is optional and may be unavailable.
- Mock `ConfigService.load_strategy_config()`, `KlineRepository`, and pandas inputs around `SignalEngine2560.run()` in `app/services/signal_engine_2560.py` for unit tests.

**What NOT to Mock:**
- Do not mock pure pandas calculations in `app/services/indicator_engine.py`; use small deterministic `DataFrame` fixtures.
- Do not mock small string normalization helpers in `app/api/strategy2560.py`; test real inputs and outputs directly.
- Do not mock Pydantic request validation in `app/api/jobs.py`, `app/api/import_data.py`, and `app/api/strategy2560.py`; exercise FastAPI request parsing when testing endpoints.

## Fixtures and Factories

**Test Data:**
```python
import pandas as pd

def make_kline_frame(rows=80, code="sh.600000"):
    return pd.DataFrame(
        {
            "code": [code] * rows,
            "date": [20260101093000 + i for i in range(rows)],
            "open": [10.0 + i * 0.01 for i in range(rows)],
            "high": [10.2 + i * 0.01 for i in range(rows)],
            "low": [9.8 + i * 0.01 for i in range(rows)],
            "close": [10.1 + i * 0.01 for i in range(rows)],
            "volume": [1000 + i for i in range(rows)],
            "amount": [10000 + i for i in range(rows)],
            "source": ["test"] * rows,
        }
    )
```

**Location:**
- Not detected. No fixture directory exists.
- Put shared fixtures in `tests/conftest.py` if a pytest suite is introduced.
- Keep small per-module factories near the tests that use them, especially for `app/services/indicator_engine.py` and `app/api/strategy2560.py`.

## Coverage

**Requirements:** None enforced. No coverage configuration, coverage command, or CI coverage gate is present.

**View Coverage:**
```bash
# Not configured.
# If pytest-cov is added later:
pytest --cov=app --cov=scripts
```

## Test Types

**Unit Tests:**
- Not present.
- Highest-value unit-test targets are pure helpers in `app/services/indicator_engine.py`, `app/services/tag_service.py`, `app/api/strategy2560.py`, `scripts/rebuild_technical_indicator.py`, and `scripts/build_30m_from_5m.py`.
- Use deterministic pandas frames and explicit expected values for moving averages, ATR, volume ratios, code normalization, and market filters.

**Integration Tests:**
- Not present.
- Integration targets are FastAPI routes in `app/main.py`, `app/api/strategy2560.py`, `app/api/jobs.py`, and `app/api/import_data.py`.
- Use FastAPI `TestClient` with dependency overrides for `get_db()` from `app/db/session.py`.
- For database-backed tests, prefer a controlled schema fixture over the real configured MySQL connection from `app/core/config.py`.

**E2E Tests:**
- Not used.
- The WebUI is a static single-page interface in `app/static/index.html` and `app/static/app.js`; no browser automation suite is configured.
- If E2E tests are added, cover the route served by `app/main.py`, API calls under `/api/strategy/2560`, job progress under `/api/jobs`, and import pages under `/api/import`.

## Common Patterns

**Async Testing:**
```python
def test_stocks_endpoint_returns_items(client, fake_db):
    response = client.get("/api/strategy/2560/stocks?limit=10&market_type=all")

    assert response.status_code == 200
    assert response.json()["success"] is True
```

- Most backend route handlers are synchronous `def` functions: `app/api/strategy2560.py`, `app/api/jobs.py`, `app/api/import_data.py`.
- Browser functions in `app/static/app.js` are async wrappers around `fetch()`, but no JavaScript test harness is configured.

**Error Testing:**
```python
def test_detail_returns_404_when_signal_missing(client, fake_service):
    fake_service.signal_detail.return_value = None

    response = client.get("/api/strategy/2560/signals/12345")

    assert response.status_code == 404
```

- Test expected 404 behavior in `detail()` and `batch()` from `app/api/strategy2560.py`.
- Test expected `{"ok": False}` behavior in `execution_progress()` and `execution_logs()` from `app/api/jobs.py`.
- Test rollback/error accumulation behavior in `SignalEngine2560.run()` from `app/services/signal_engine_2560.py` and import functions from `scripts/import_vipdoc_with_pytdx.py`.

**Manual Smoke Checks:**
```bash
python -c "from app.db.session import ping_database; print(ping_database())"
python scripts/run_2560_analysis.py --limit 20
bash scripts/start_webui.sh
```

- These commands are documented in `README.md` and `scripts/start_webui.sh`.
- Daily operational checks are documented in `README_2560_DAILY_OPS.md` and use `scripts/import_vipdoc_with_pytdx.py`, `scripts/build_30m_from_5m.py`, `scripts/rebuild_technical_indicator.py`, and `scripts/run_2560_analysis.py`.
- Treat these as smoke checks only; they depend on configured database credentials, local market data paths, and environment variables from `.env`.

---

*Testing analysis: 2026-05-11*

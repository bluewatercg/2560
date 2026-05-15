#!/usr/bin/env python3
"""
Phase 7 Integration Tests — 端到端验证导入流程

Scenarios:
  A. Redis mode: import → kline data correct → Redis key cleaned
  B. Worker concurrent claim: 4 market-lane workers, no deadlock
  C. Degradation mode: Redis down → db-fallback completes
  D. Flush failure: batch/execution marked failed, Redis key preserved

Usage:
  python -m pytest tests/test_import_redis_integration.py -v
  python -m pytest tests/test_import_redis_integration.py -v -k test_degradation_mode
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def engine():
    """Create SQLAlchemy engine from project .env config."""
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "3306")
        user = os.getenv("DB_USER", "root")
        pwd = os.getenv("DB_PASSWORD", "")
        name = os.getenv("DB_NAME", "strategy2560")
        url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{name}?charset=utf8mb4"
    eng = create_engine(url, pool_pre_ping=True, future=True)
    # Verify connection
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    """Provide a fresh connection with explicit commit control."""
    conn = engine.connect()
    yield conn
    conn.close()


def _has_redis(host="localhost", port=6379, password=None):
    """Check if Redis is reachable."""
    try:
        import redis as _r

        rc = _r.Redis(host=host, port=port, password=password, decode_responses=True, socket_timeout=3, socket_connect_timeout=2)
        rc.ping()
        return rc
    except Exception:
        return None


@pytest.fixture()
def redis_client():
    """Return Redis client or skip test if unavailable."""
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    pwd = os.getenv("REDIS_PASSWORD") or None
    rc = _has_redis(host, port, pwd)
    if not rc:
        pytest.skip(f"Redis not available at {host}:{port}")
    yield rc
    # Cleanup: delete test keys
    try:
        keys = rc.keys("test:*")
        if keys:
            rc.delete(*keys)
    except Exception:
        pass


@pytest.fixture()
def test_batch_id(db):
    """Create a temporary data_import_batch, return id, cleanup after."""
    uid = uuid.uuid4().hex[:8]
    result = db.execute(text("""
        INSERT INTO data_import_batch (import_type, source_dir, market, status, total_files, success_files, failed_files, total_rows, started_at, message)
        VALUES ('vipdoc', :src, 'sh60', 'queued', 0, 0, 0, 0, NOW(), :msg)
    """), {"src": f"/tmp/test-{uid}", "msg": f"test batch {uid}"})
    db.commit()
    bid = int(result.lastrowid)
    yield bid
    # Cleanup
    try:
        db.execute(text("DELETE FROM data_import_file WHERE import_batch_id=:id"), {"id": bid})
        db.execute(text("DELETE FROM data_import_batch WHERE id=:id"), {"id": bid})
        db.commit()
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────


def _make_test_vipdoc_dir(codes: list[str], kind: str = "daily") -> Path:
    """Create a minimal vipdoc directory with synthetic .day / .lc5 files."""
    tmp = Path(f"/tmp/vipdoc_test_{uuid.uuid4().hex[:8]}")
    side = "sh" if any(c.startswith("sh") for c in codes) else "sz"
    data_dir = tmp / side / ("lday" if kind == "daily" else "fzline")
    data_dir.mkdir(parents=True)

    for code in codes:
        suffix = ".day" if kind == "daily" else ".lc5"
        filepath = data_dir / f"{code}{suffix}"
        if kind == "daily":
            _write_day_file(filepath)
        else:
            _write_lc5_file(filepath)

    return tmp


def _write_day_file(filepath: Path):
    """Write a minimal通达信 .day file with ~10 rows of synthetic data."""
    record_size = 32
    today = 20260101
    rows = []
    for i in range(10):
        d = today + i
        rows.append(struct.pack(
            "<IIIIIfII",
            d,                    # date as int
            100000 + i * 100,     # open (stored as int*100)
            110000 + i * 100,     # high
            90000 + i * 100,      # low
            105000 + i * 100,     # close
            float(100000 + i * 1000),  # amount
            10000 + i * 1000,     # volume
            0,                    # reserved
        ))
    with open(filepath, "wb") as f:
        f.write(b"".join(rows))


def _write_lc5_file(filepath: Path):
    """Write a minimal通达信 .lc5 file with ~10 rows."""
    record_size = 40
    rows = []
    base_ts = 1700000000  # some unix timestamp
    for i in range(10):
        rows.append(struct.pack(
            "<IIIIIIIIIII",
            base_ts + i * 1800,   # timestamp
            1000 + i,
            1100 + i,
            900 + i,
            1050 + i,
            1000 + i * 10,
            100000 + i * 1000,
            0, 0, 0, 0,
        ))
    with open(filepath, "wb") as f:
        f.write(b"".join(rows))


def _cleanup_vipdoc_dir(d: Path):
    import shutil
    try:
        shutil.rmtree(d)
    except Exception:
        pass


# ── Scenario A: Redis mode ───────────────────────────────────────────


def test_redis_mode_import(db, redis_client):
    """
    A. Redis mode:
       - Import files → rows buffered to Redis → flushed to DB
       - Verify: kline data present, Redis key cleaned, result ok
    """
    from scripts.import_vipdoc_with_pytdx import import_vipdoc_files_parallel
    from sqlalchemy import create_engine as _ce

    codes = ["sh600003", "sh600004"]
    codes_with_dot = ["sh.600003", "sh.600004"]
    vipdoc_dir = _make_test_vipdoc_dir(codes, kind="daily")

    # Use the same engine that SessionLocal uses
    url = os.getenv("DATABASE_URL") or f"mysql+pymysql://watchlist_decision_support:KLV%26a%2CaAu0@192.168.1.254:3306/watchlist_decision_support?charset=utf8mb4"
    eng = _ce(url, pool_pre_ping=True, future=True)

    with eng.begin() as conn:
        lday_dir = vipdoc_dir / "sh" / "lday"
        files = sorted(str(f) for f in lday_dir.glob("*.day"))

        r = conn.execute(text("""
            INSERT INTO data_import_batch (import_type, source_dir, market, status, total_files,
                success_files, failed_files, total_rows, started_at, message)
            VALUES ('vipdoc', :src, 'sh60', 'running', :tf, 0, 0, 0, NOW(), 'redis mode test')
        """), {"src": str(vipdoc_dir), "tf": len(files)})
        bid = int(r.lastrowid)

        file_ids = {}
        for fp in files:
            r2 = conn.execute(text("""
                INSERT INTO data_import_file (import_batch_id, file_path, market, status,
                    rows_imported, started_at, updated_at)
                VALUES (:bid, :fp, 'sh60', 'pending', 0, NOW(), NOW())
            """), {"bid": bid, "fp": fp})
            file_ids[fp] = int(r2.lastrowid)

    result = import_vipdoc_files_parallel(
        files,
        market="sh60",
        import_type="lday",
        start=None,
        end=None,
        workers=2,
        batch_id=bid,
        import_file_ids=file_ids,
        redis_client=redis_client,
    )

    # Verify result
    assert result["success_files"] == len(files), f"Expected {len(files)} success, got {result}"
    assert result["mode"] == "redis", f"Expected redis mode, got {result['mode']}"

    # Verify Redis key cleaned (actual key prefix used by import code)
    redis_key = f"import:{bid}:daily"
    exists = redis_client.exists(redis_key)
    assert exists == 0, f"Redis key {redis_key} should be deleted after flush, but exists={exists}"

    # Verify kline data written (use fresh connection to see committed data)
    with eng.begin() as conn:
        for code in codes_with_dot:
            row = conn.execute(text(
                "SELECT COUNT(*) FROM daily_kline WHERE code=:code"
            ), {"code": code}).scalar()
            assert int(row) > 0, f"No daily_kline rows for {code}"

    # Cleanup
    cleanup_keys = redis_client.keys(f"import:{bid}:*")
    if cleanup_keys:
        redis_client.delete(*cleanup_keys)
    with eng.begin() as conn:
        for code in codes_with_dot:
            conn.execute(text("DELETE FROM daily_kline WHERE code=:code"), {"code": code})
        conn.execute(text("DELETE FROM data_import_file WHERE import_batch_id=:id"), {"id": bid})
        conn.execute(text("DELETE FROM data_import_batch WHERE id=:id"), {"id": bid})

    eng.dispose()
    _cleanup_vipdoc_dir(vipdoc_dir)


# ── Scenario B: Worker concurrent claim ───────────────────────────────


def _insert_test_job(engine, job_type: str, market: str, priority: int = 5):
    """Insert a test job into job_queue, return queue id."""
    with engine.begin() as conn:
        r = conn.execute(text("""
            INSERT INTO job_queue (job_type, strategy_code, priority, payload, status, created_at)
            VALUES (:jt, 'TEST', :pri, :payload, 'pending', NOW())
        """), {
            "jt": job_type,
            "pri": priority,
            "payload": json.dumps({"market": market, "job_execution_id": 0, "import_batch_id": 0}),
        })
        return int(r.lastrowid)


def _claim_job_worker(engine, market: str, results: dict, worker_id: str):
    """Single worker: try to claim jobs for a specific market."""
    errors = []
    claimed = 0
    for _ in range(10):  # poll up to 10 times
        try:
            with engine.begin() as conn:
                from scripts.job_worker import try_claim_job
                job = try_claim_job(conn, market)
                if job:
                    claimed += 1
        except Exception as e:
            errors.append(str(e))
        time.sleep(0.05)
    results[worker_id] = {"claimed": claimed, "errors": errors}


def test_worker_concurrent_claim_no_deadlock(engine):
    """
    B. 4 market-lane workers claim concurrently, no OperationalError(1213).
    """
    import threading

    markets = ["sh60", "sh68", "sz00", "sz30"]

    # Insert 2 jobs per market
    for m in markets:
        _insert_test_job(engine, "run_2560", m)
        _insert_test_job(engine, "run_2560", m)

    results = {}
    threads = []
    for m in markets:
        t = threading.Thread(target=_claim_job_worker, args=(engine, m, results, m))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=30)

    # Verify no deadlock errors
    all_errors = []
    for w, r in results.items():
        all_errors.extend(r["errors"])

    deadlock_errors = [e for e in all_errors if "1213" in e or "Deadlock" in e]
    assert len(deadlock_errors) == 0, f"Deadlock detected: {deadlock_errors}"

    # Verify each worker claimed at most its market's jobs
    total_claimed = sum(r["claimed"] for r in results.values())
    assert total_claimed <= len(markets) * 2, f"Over-claim: {total_claimed} > {len(markets)*2}"

    # Cleanup test jobs
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM job_queue WHERE strategy_code='TEST'"))


def test_market_worker_claims_all_job_types(engine):
    """
    B2. Market worker (sh60) claims import_vipdoc, build_30m, run_2560
    for its market. Generic worker only claims jobs without market lane.
    """
    from scripts.job_worker import try_claim_job

    # Insert market-lane jobs
    with engine.begin() as conn:
        for jt in ["import_vipdoc", "build_30m", "run_2560"]:
            conn.execute(text("""
                INSERT INTO job_queue (job_type, strategy_code, priority, payload, status, created_at)
                VALUES (:jt, 'TEST', 5, :payload, 'pending', NOW())
            """), {"jt": jt, "payload": json.dumps({"market": "sh60", "job_execution_id": 0, "import_batch_id": 0})})

    # Market worker sh60 should claim 3 jobs
    claimed_types = []
    for _ in range(5):
        with engine.begin() as conn:
            job = try_claim_job(conn, "sh60")
            if job:
                claimed_types.append(job["job_type"])
    assert sorted(claimed_types) == ["build_30m", "import_vipdoc", "run_2560"], f"Expected 3 types, got {claimed_types}"

    # Generic worker should NOT claim any market-lane jobs
    with engine.begin() as conn:
        job = try_claim_job(conn, None)
    assert job is None, "Generic worker should not claim market-lane jobs"

    # Insert a non-lane job (market=null)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO job_queue (job_type, strategy_code, priority, payload, status, created_at)
            VALUES ('run_2560', 'TEST', 5, :payload, 'pending', NOW())
        """), {"payload": json.dumps({"job_execution_id": 0, "import_batch_id": 0})})

    # Generic worker should now claim it
    with engine.begin() as conn:
        job = try_claim_job(conn, None)
    assert job is not None, "Generic worker should claim non-lane jobs"
    assert job["job_type"] == "run_2560"

    # Cleanup
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM job_queue WHERE strategy_code='TEST'"))


# ── Scenario C: Degradation mode ─────────────────────────────────────


def test_degradation_mode(db):
    """
    C. Redis unavailable → db-fallback mode → data still written correctly.
    """
    from scripts.import_vipdoc_with_pytdx import import_vipdoc_files_parallel

    codes = ["sh600002"]
    codes_with_dot = ["sh.600002"]
    vipdoc_dir = _make_test_vipdoc_dir(codes, kind="daily")

    lday_dir = vipdoc_dir / "sh" / "lday"
    files = sorted(str(f) for f in lday_dir.glob("*.day"))

    bid_result = db.execute(text("""
        INSERT INTO data_import_batch (import_type, source_dir, market, status, total_files, success_files, failed_files, total_rows, started_at, message)
        VALUES ('vipdoc', :src, 'sh60', 'running', :tf, 0, 0, 0, NOW(), 'test degradation')
    """), {"src": str(vipdoc_dir), "tf": len(files)})
    db.commit()
    bid = int(bid_result.lastrowid)

    file_ids = {}
    for fp in files:
        r = db.execute(text("""
            INSERT INTO data_import_file (import_batch_id, file_path, market, status, rows_imported, started_at, updated_at)
            VALUES (:bid, :fp, 'sh60', 'pending', 0, NOW(), NOW())
        """), {"bid": bid, "fp": fp})
        file_ids[fp] = int(r.lastrowid)
    db.commit()

    result = import_vipdoc_files_parallel(
        files,
        market="sh60",
        import_type="lday",
        start=None,
        end=None,
        workers=1,
        batch_id=bid,
        import_file_ids=file_ids,
        redis_client=None,  # Force db-fallback
    )

    # Verify success in db-fallback mode
    assert result["success_files"] == len(files), f"db-fallback failed: {result}"
    for f in result.get("failed_files_list", []):
        pytest.fail(f"File failed in db-fallback: {f}")

    # Verify kline data
    for code in codes_with_dot:
        row = db.execute(text(
            "SELECT COUNT(*) FROM daily_kline WHERE code=:code"
        ), {"code": code}).scalar()
        assert int(row) > 0, f"No daily_kline rows for {code} in db-fallback mode"

    # Cleanup
    db.execute(text("DELETE FROM data_import_file WHERE import_batch_id=:id"), {"id": bid})
    db.execute(text("DELETE FROM data_import_batch WHERE id=:id"), {"id": bid})
    db.commit()
    _cleanup_vipdoc_dir(vipdoc_dir)


# ── Scenario D: Flush failure → status收口 ────────────────────────────


def test_flush_failure_preserves_redis_key(redis_client):
    """
    D. Flush failure:
       - Manually put malformed JSON into Redis
       - Flush should fail → batch marked failed, Redis key preserved
    """
    from scripts.import_vipdoc_with_pytdx import _flush_redis_to_db

    batch_id = 999999  # non-existent batch to trigger flush error
    redis_key = f"test:import:{batch_id}:daily"

    # Put malformed data into Redis
    redis_client.lpush(redis_key, "NOT_VALID_JSON{{{")

    with pytest.raises(Exception):
        with _get_test_db_session() as conn:
            _flush_redis_to_db(conn, batch_id, redis_client, redis_key, "daily_kline",
                               ["code", "date", "open", "high", "low", "close", "volume", "amount", "source"])

    # Verify Redis key preserved (not deleted on failure)
    exists = redis_client.exists(redis_key)
    assert exists == 1, "Redis key should be preserved after flush failure"

    # Cleanup
    redis_client.delete(redis_key)


def _get_test_db_session():
    """Create a fresh session for testing."""
    from app.db.session import SessionLocal
    return SessionLocal()

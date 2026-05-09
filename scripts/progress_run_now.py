#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
JOB_ID = int(os.getenv("JOB_ID", "0"))
MARKET = os.getenv("MARKET", "all")
SHARDS = int(os.getenv("SHARDS", "1"))
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def log(msg: str):
    print(msg, flush=True)


def db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url: return url
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD", "")
    name = os.getenv("DB_NAME")
    if not host or not user or not name:
        raise RuntimeError("Set DATABASE_URL or DB_HOST/DB_USER/DB_NAME in .env")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


def engine():
    return create_engine(db_url(), pool_pre_ping=True, pool_recycle=3600, future=True)


def market_where(alias: str, market: str) -> str:
    col = f"{alias}.code"
    m = (market or "all").lower()
    if m == "sh": return f"{col} LIKE 'sh.%'"
    if m == "sz": return f"{col} LIKE 'sz.%'"
    if m == "sh60": return f"{col} LIKE 'sh.60%'"
    if m == "sh68": return f"{col} LIKE 'sh.68%'"
    if m == "sz00": return f"{col} LIKE 'sz.00%'"
    if m == "sz30": return f"{col} LIKE 'sz.30%'"
    return f"({col} LIKE 'sh.%' OR {col} LIKE 'sz.%')"


def load_codes(en) -> list[str]:
    sql = f"SELECT code FROM stock_info s WHERE {market_where('s', MARKET)} ORDER BY code"
    with en.connect() as conn:
        return [r[0] for r in conn.execute(text(sql)).all()]


def init_items(en, codes: list[str]):
    with en.begin() as conn:
        conn.execute(text("UPDATE job_execution SET progress_total=:total, message=:msg, updated_at=NOW() WHERE id=:id"),
                     {"id": JOB_ID, "total": len(codes), "msg": f"initialized total={len(codes)}, shards={SHARDS}"})
        for idx, code in enumerate(codes):
            conn.execute(text("""
                INSERT IGNORE INTO job_task_item (job_id, shard_id, code, status, updated_at)
                VALUES (:job_id, :shard_id, :code, 'pending', NOW())
            """), {"job_id": JOB_ID, "shard_id": idx % max(SHARDS, 1), "code": code})


def update_counts(en, current_code=None, message=None):
    with en.begin() as conn:
        c = conn.execute(text("""
            SELECT SUM(CASE WHEN status IN ('success','failed') THEN 1 ELSE 0 END) done,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) success_count,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed_count,
                   COUNT(*) total
            FROM job_task_item WHERE job_id=:job_id
        """), {"job_id": JOB_ID}).mappings().first()
        conn.execute(text("""
            UPDATE job_execution SET progress_current=:done, progress_total=:total,
              success_count=:success_count, failed_count=:failed_count,
              current_code=:current_code, message=COALESCE(:message, message), updated_at=NOW()
            WHERE id=:job_id
        """), {"job_id": JOB_ID, "done": int(c["done"] or 0), "total": int(c["total"] or 0),
                "success_count": int(c["success_count"] or 0), "failed_count": int(c["failed_count"] or 0),
                "current_code": current_code, "message": message})


def process_code(en, code: str, idx: int, total: int):
    t0 = time.time()
    with en.begin() as conn:
        conn.execute(text("UPDATE job_task_item SET status='running', started_at=NOW(), updated_at=NOW() WHERE job_id=:job_id AND code=:code"), {"job_id": JOB_ID, "code": code})
        conn.execute(text("UPDATE job_execution SET current_code=:code, message=:msg, updated_at=NOW() WHERE id=:job_id"), {"job_id": JOB_ID, "code": code, "msg": f"processing {idx}/{total} {code}"})
    try:
        r = requests.post(f"{WEB_BASE_URL}/api/strategy/2560/run", json={"codes": [code], "market_type": MARKET, "rebuild_statistics": False}, timeout=3600)
        ok = r.status_code < 400
        err = "" if ok else f"HTTP {r.status_code}: {r.text[:500]}"
    except Exception as exc:
        ok, err = False, str(exc)
    elapsed_ms = int((time.time() - t0) * 1000)
    with en.begin() as conn:
        conn.execute(text("""
            UPDATE job_task_item SET status=:status, elapsed_ms=:elapsed_ms, last_error=:err,
              finished_at=NOW(), updated_at=NOW() WHERE job_id=:job_id AND code=:code
        """), {"job_id": JOB_ID, "code": code, "status": "success" if ok else "failed", "elapsed_ms": elapsed_ms, "err": err[:2000] if err else None})
    return code, ok, elapsed_ms, err


def main():
    if not JOB_ID: raise RuntimeError("JOB_ID is required")
    en = engine()
    codes = load_codes(en)
    total = len(codes)
    log(f"[progress] job_id={JOB_ID} market={MARKET} shards={SHARDS} total={total}")
    init_items(en, codes)
    update_counts(en, None, f"started total={total}, shards={SHARDS}")
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=max(SHARDS, 1)) as pool:
            futures = [pool.submit(process_code, en, code, idx + 1, total) for idx, code in enumerate(codes)]
            for fut in as_completed(futures):
                done += 1
                code, ok, elapsed_ms, err = fut.result()
                log(f"[{done}/{total}] {code} {'OK' if ok else 'FAIL'} {elapsed_ms}ms {err[:120] if err else ''}")
                update_counts(en, code, f"done {done}/{total}, current={code}")
        with en.begin() as conn:
            failed = int(conn.execute(text("SELECT failed_count FROM job_execution WHERE id=:id"), {"id": JOB_ID}).scalar() or 0)
            conn.execute(text("UPDATE job_execution SET status=:status, message=:msg, finished_at=NOW(), updated_at=NOW() WHERE id=:id"),
                         {"id": JOB_ID, "status": "success" if failed == 0 else "failed", "msg": f"finished done={total}, failed={failed}"})
        log(f"[progress] finished job_id={JOB_ID}")
    except Exception as exc:
        log(traceback.format_exc())
        with en.begin() as conn:
            conn.execute(text("UPDATE job_execution SET status='failed', message=:msg, finished_at=NOW(), updated_at=NOW() WHERE id=:id"), {"id": JOB_ID, "msg": str(exc)[:1000]})
        raise


if __name__ == "__main__":
    main()

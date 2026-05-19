#!/usr/bin/env python3
"""Background job runner: import vipdoc行情 to ClickHouse (not MySQL).
MySQL is used only for job tracking (batch/file/execution tables).
All market data goes to ClickHouse.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import threading
import time

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.job_orchestrator import (
    finalize_data_import_batch,
    update_job_execution,
)
from scripts.import_vipdoc_clickhouse import (
    import_daily_clickhouse,
    import_5m_clickhouse,
    ch_ping,
)


def parse_args():
    p = argparse.ArgumentParser(description="Run vipdoc import as background job (ClickHouse)")
    p.add_argument("--job-id", type=int, default=int(os.getenv("JOB_ID", "0")))
    p.add_argument("--batch-id", type=int, default=int(os.getenv("IMPORT_BATCH_ID", "0")))
    p.add_argument("--market", default=os.getenv("MARKET", "sh60"))
    p.add_argument("--import-type", default=os.getenv("IMPORT_TYPE", "lday"))
    p.add_argument("--source-dir", default=os.getenv("SOURCE_DIR", "/data/vipdoc"))
    p.add_argument("--start", default=os.getenv("START"))
    p.add_argument("--end", default=os.getenv("END"))
    p.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", "4")))
    return p.parse_args()


def main():
    a = parse_args()
    if not a.job_id or not a.batch_id:
        raise RuntimeError("job-id and batch-id are required")

    if not ch_ping():
        raise RuntimeError("ClickHouse not reachable")

    with SessionLocal() as db:
        batch = db.execute(text("""
            SELECT id, source_dir, market, status, message
            FROM data_import_batch
            WHERE id=:id
        """), {"id": a.batch_id}).mappings().first()
        if not batch:
            raise RuntimeError(f"import batch not found: {a.batch_id}")
        file_rows = db.execute(text("""
            SELECT id, file_path
            FROM data_import_file
            WHERE import_batch_id=:id
            ORDER BY id
        """), {"id": a.batch_id}).mappings().all()
        files = [r["file_path"] for r in file_rows]
        # Build path->file_id map for status updates
        file_id_map = {r["file_path"]: r["id"] for r in file_rows}

        db.execute(text("""
            UPDATE data_import_batch
            SET status='running', message=:msg, updated_at=NOW()
            WHERE id=:id
        """), {"id": a.batch_id, "msg": f"running import job #{a.job_id} (ClickHouse)"})
        db.commit()

    market = a.market or batch["market"] or "sh60"
    import_type = a.import_type or "all"

    # Filter files by type
    lday_files = [f for f in files if f.endswith(".day")]
    lc5_files = [f for f in files if f.endswith(".lc5")]
    if import_type in ("lday", "daily"):
        lc5_files = []
    elif import_type in ("5m", "lc5", "fzline"):
        lday_files = []

    all_files = lday_files + lc5_files
    total = len(all_files)

    # Thread-safe counters
    _lock = threading.Lock()
    _done = [0]
    _success = [0]
    _failed = [0]
    _rows = [0]
    _file_results = {}  # filepath -> ('success'|'failed', error_msg)

    def do_import(filepath: str) -> dict:
        if filepath.endswith(".day"):
            return import_daily_clickhouse(filepath, market, a.start, a.end)
        else:
            return import_5m_clickhouse(filepath, market, a.start, a.end)

    def on_done(filepath: str, result: dict):
        with _lock:
            _done[0] += 1
            if result["ok"]:
                _success[0] += 1
                _rows[0] += result["rows"]
                _file_results[filepath] = ("success", None)
            else:
                _failed[0] += 1
                _file_results[filepath] = ("failed", str(result.get("error", ""))[:500])

    # Background reporter: single thread writes MySQL every 2s (zero contention)
    _stop_report = threading.Event()
    _reported_ids = set()  # file_ids already updated in MySQL

    def _reporter():
        while not _stop_report.wait(2):
            with _lock:
                d, s, f, r = _done[0], _success[0], _failed[0], _rows[0]
                pending_updates = {fp: st for fp, st in _file_results.items() if fp not in _reported_ids}

            if not pending_updates and d == 0:
                continue

            try:
                with SessionLocal() as db:
                    # Batch update file statuses
                    if pending_updates:
                        for filepath, (status, err) in pending_updates.items():
                            fid = file_id_map.get(filepath)
                            if not fid:
                                continue
                            db.execute(text("""
                                UPDATE data_import_file
                                SET status=:status,
                                    rows_imported=:rows,
                                    last_error=:err,
                                    finished_at=NOW(),
                                    updated_at=NOW()
                                WHERE id=:id
                            """), {
                                "id": fid,
                                "status": status,
                                "rows": 0,
                                "err": err,
                            })
                        db.commit()

                        # Only mark as reported AFTER commit succeeds
                        with _lock:
                            _reported_ids.update(pending_updates.keys())

                    # Update job_execution progress
                    if d > 0:
                        update_job_execution(
                            db, a.job_id, status="running",
                            progress_current=d, progress_total=total,
                            success_count=s, failed_count=f,
                            message=f"import {d}/{total}",
                        )
                        db.commit()
            except Exception as e:
                print(f"[reporter] MySQL update failed: {e}", flush=True)
                # Don't update _reported_ids — retry on next cycle

    t0 = time.time()
    reporter_thread = threading.Thread(target=_reporter, daemon=True)
    reporter_thread.start()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures = {pool.submit(do_import, f): f for f in all_files}
            for fut in concurrent.futures.as_completed(futures):
                filepath = futures[fut]
                on_done(filepath, fut.result())
    finally:
        _stop_report.set()
        reporter_thread.join(timeout=3)

    # Final flush
    with _lock:
        d, s, f, r = _done[0], _success[0], _failed[0], _rows[0]

    elapsed = time.time() - t0
    print(f"[import_job_runner] done: ok={s} failed={f} rows={r} in {elapsed:.1f}s", flush=True)

    status = "success" if f == 0 else "failed"
    batch_message = f"finished to ClickHouse, workers={a.workers}"
    if f:
        batch_message = f"finished with {f} failed files"

    with SessionLocal() as db:
        # Final batch update for any remaining file statuses
        with _lock:
            remaining = {fp: st for fp, st in _file_results.items() if fp not in _reported_ids}
        for filepath, (fstatus, err) in remaining.items():
            fid = file_id_map.get(filepath)
            if fid:
                db.execute(text("""
                    UPDATE data_import_file
                    SET status=:status, rows_imported=0, last_error=:err,
                        finished_at=NOW(), updated_at=NOW()
                    WHERE id=:id
                """), {"id": fid, "status": fstatus, "err": err})

        finalize_data_import_batch(
            db, a.batch_id, status=status,
            success_files=s, failed_files=f,
            total_rows=r, message=batch_message,
        )
        update_job_execution(
            db, a.job_id, status=status,
            progress_current=total, progress_total=total,
            success_count=s, failed_count=f,
            message=batch_message, finished=True,
        )
        db.commit()


if __name__ == "__main__":
    main()

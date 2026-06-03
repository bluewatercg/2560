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
from functools import partial
from pathlib import Path

from sqlalchemy import text
from pymysql.err import OperationalError

from app.db.session import SessionLocal
from app.services.job_orchestrator import (
    finalize_data_import_batch,
    update_job_execution,
)
from app.services.job_runtime_store import JobProgressReporter, JobRuntimeStore

from scripts.import_vipdoc_clickhouse import (
    read_daily_rows,
    read_5m_rows,
    ch_replace_rows,
    ch_ping,
)


def _read_file_to_rows(filepath: str, market: str, start: str | None, end: str | None) -> dict:
    """Read one vipdoc file into rows dict (no ClickHouse write). Top-level for multiprocessing."""
    if filepath.endswith(".day"):
        return read_daily_rows(filepath, market, start, end)
    else:
        return read_5m_rows(filepath, market, start, end)


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
    runtime_store = JobRuntimeStore(Path(__file__).resolve().parents[1] / "logs")
    progress_reporter = JobProgressReporter(a.job_id, runtime_store)

    if not ch_ping():
        raise RuntimeError("ClickHouse not reachable")

    # Read batch metadata and file list
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
        file_id_map = {r["file_path"]: r["id"] for r in file_rows}

    # Mark batch as running — retry on deadlock (concurrent workers may compete)
    for _attempt in range(3):
        try:
            with SessionLocal() as db:
                db.execute(text("""
                    UPDATE data_import_batch
                    SET status='running', message=:msg, updated_at=NOW()
                    WHERE id=:id
                """), {"id": a.batch_id, "msg": f"running import job #{a.job_id} (ClickHouse)"})
                db.commit()
            break
        except OperationalError as exc:
            if exc.args and exc.args[0] == 1213:
                time.sleep(0.5 * (_attempt + 1))
                continue
            raise

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
    progress_reporter.report(
        {
            "status": "running",
            "done": 0,
            "total": total,
            "success_count": 0,
            "failed_count": 0,
            "message": f"running import job #{a.job_id} (ClickHouse)",
        },
        force_mysql=True,
    )

    # Thread-safe counters
    _lock = threading.Lock()
    _done = [0]
    _success = [0]
    _failed = [0]
    _rows = [0]
    _file_results = {}  # filepath -> ('success'|'failed', error_msg)

    flush_rows = int(os.getenv("IMPORT_FLUSH_ROWS", "100000"))
    _inserted_rows = [0]

    do_read = partial(_read_file_to_rows, market=market, start=a.start, end=a.end)

    def flush_buffer(table: str, rows: list[dict]) -> None:
        if not rows:
            return
        inserted = ch_replace_rows(table, rows)
        with _lock:
            _inserted_rows[0] += inserted
        rows.clear()

    def on_read_done(filepath: str, result: dict) -> tuple[str, list[dict]]:
        with _lock:
            _done[0] += 1
            if result["ok"]:
                _success[0] += 1
                rows = result.get("rows", [])
                _rows[0] += len(rows)
                _file_results[filepath] = ("success", None)
                rtype = result.get("type", "")
                return rtype, rows
            else:
                _failed[0] += 1
                _file_results[filepath] = ("failed", str(result.get("error", ""))[:500])
                return "", []

    # Background reporter: writes runtime snapshots every 2s; MySQL progress is throttled.
    _stop_report = threading.Event()
    _reported_ids = set()  # file_ids already updated in MySQL
    _phase = [1]  # 1=reading, 2=inserting

    def _reporter():
        while not _stop_report.wait(2):
            with _lock:
                d, s, f, r = _done[0], _success[0], _failed[0], _rows[0]
                pending_updates = {fp: st for fp, st in _file_results.items() if fp not in _reported_ids}
                phase = _phase[0]

            msg = f"reading {d}/{total}" if phase == 1 else f"inserting rows to ClickHouse"

            try:
                with SessionLocal() as db:
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
                        with _lock:
                            _reported_ids.update(pending_updates.keys())

                    should_flush_mysql = progress_reporter.report(
                        {
                            "status": "running",
                            "done": d,
                            "total": total,
                            "success_count": s,
                            "failed_count": f,
                            "message": msg,
                        }
                    )
                    if should_flush_mysql:
                        update_job_execution(
                            db, a.job_id, status="running",
                            progress_current=d, progress_total=total,
                            success_count=s, failed_count=f,
                            message=msg,
                        )
                    db.commit()
            except Exception as e:
                print(f"[reporter] MySQL update failed: {e}", flush=True)

    t0 = time.time()
    reporter_thread = threading.Thread(target=_reporter, daemon=True)
    reporter_thread.start()

    # ── Phase 1: parallel read, main process streams batches into ClickHouse ──
    daily_buffer: list[dict] = []
    minute_buffer: list[dict] = []
    phase1_ok = True
    print(f"[import_job_runner] Phase 1: reading {total} files with {a.workers} processes", flush=True)
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
            futures = {pool.submit(do_read, f): f for f in all_files}
            for fut in concurrent.futures.as_completed(futures):
                filepath = futures[fut]
                try:
                    result = fut.result()
                except Exception as exc:
                    result = {"ok": False, "file": filepath, "code": "<unknown>", "rows": [], "type": "unknown", "error": str(exc)}
                rtype, rows = on_read_done(filepath, result)
                try:
                    if rtype == "lday":
                        daily_buffer.extend(rows)
                        if len(daily_buffer) >= flush_rows:
                            flush_buffer("daily_kline", daily_buffer)
                    elif rtype == "5m":
                        minute_buffer.extend(rows)
                        if len(minute_buffer) >= flush_rows:
                            flush_buffer("minute_kline_period", minute_buffer)
                except Exception as exc:
                    phase1_ok = False
                    with _lock:
                        _failed[0] += 1
                        _file_results["__batch_insert__"] = ("failed", str(exc)[:500])
                    print(f"[import_job_runner] streaming INSERT failed: {exc}", flush=True)
                    break
    except Exception as exc:
        phase1_ok = False
        with _lock:
            _failed[0] += 1
            _file_results["__phase1_crash__"] = ("failed", str(exc)[:500])
        print(f"[import_job_runner] Phase 1 CRASH: {exc}", flush=True)
    finally:
        _stop_report.set()
        reporter_thread.join(timeout=3)

    with _lock:
        daily_count = len(daily_buffer)
        minute_count = len(minute_buffer)
        d, s, f = _done[0], _success[0], _failed[0]

    print(f"[import_job_runner] Phase 1 done: {d} files read, {daily_count} daily rows buffered, {minute_count} minute rows buffered, {f} failed", flush=True)

    # ── Phase 2: batch INSERT ──
    _phase[0] = 2  # switch reporter message
    _stop_report.clear()
    reporter_thread = threading.Thread(target=_reporter, daemon=True)
    reporter_thread.start()

    phase2_ok = True
    try:
        if daily_count > 0:
            t_ins = time.time()
            print(f"[import_job_runner] Phase 2: inserting {daily_count} daily rows", flush=True)
            flush_buffer("daily_kline", daily_buffer)
            print(f"[import_job_runner] daily insert done in {time.time()-t_ins:.1f}s", flush=True)

        if minute_count > 0:
            t_ins = time.time()
            print(f"[import_job_runner] Phase 2: inserting {minute_count} minute rows", flush=True)
            flush_buffer("minute_kline_period", minute_buffer)
            print(f"[import_job_runner] minute insert done in {time.time()-t_ins:.1f}s", flush=True)
    except Exception as e:
        phase2_ok = False
        print(f"[import_job_runner] Phase 2 INSERT failed: {e}", flush=True)
        with _lock:
            _failed[0] += 1
            _file_results["__batch_insert__"] = ("failed", str(e)[:500])
    finally:
        _stop_report.set()
        reporter_thread.join(timeout=3)

    with _lock:
        d, s, f, r = _done[0], _success[0], _failed[0], _rows[0]

    elapsed = time.time() - t0
    print(f"[import_job_runner] done: ok={s} failed={f} rows={r} in {elapsed:.1f}s", flush=True)

    status = "success" if f == 0 and phase1_ok and phase2_ok else "failed"
    batch_message = f"finished to ClickHouse (streaming insert), workers={a.workers}, flush_rows={flush_rows}"
    if not phase1_ok:
        batch_message = "finished with read/streaming insert error"
    elif not phase2_ok:
        batch_message = f"finished with ClickHouse batch insert error"
    elif f:
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
        progress_reporter.report(
            {
                "status": status,
                "done": total,
                "total": total,
                "success_count": s,
                "failed_count": f,
                "message": batch_message,
            },
            force_mysql=True,
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

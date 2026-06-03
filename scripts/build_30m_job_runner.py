#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.job_orchestrator import update_job_execution
from app.services.job_runtime_store import JobProgressReporter, JobRuntimeStore
from scripts.build_30m_from_5m import build_30m_parallel


def final_counts(result: dict, state: dict) -> dict:
    """Normalize final code counts for both per-code and ClickHouse SQL modes."""
    result_codes = int(result.get("codes") or 0)
    success = int(state.get("success") or 0)
    failed = int(state.get("failed") or 0)
    if success == 0 and failed == 0 and result_codes:
        if result.get("ok"):
            success = result_codes
        else:
            failed = result_codes
    rows = int(result.get("inserted_30m_rows") or 0)
    return {
        "success": success,
        "failed": failed,
        "message": result.get("error") or f"build_30m finished, {success} codes, {rows} rows",
    }


def is_deadlock(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    return bool(getattr(orig, "args", None) and exc.orig.args[0] == 1213)


def run_with_deadlock_retry(fn, max_retries: int = 5) -> None:
    for attempt in range(max_retries):
        try:
            fn()
            return
        except OperationalError as exc:
            if is_deadlock(exc) and attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise


def mark_batch_running(batch_id: int, job_id: int) -> None:
    def _update():
        with SessionLocal() as db:
            db.execute(text("""
                UPDATE data_import_batch
                SET status='running', message=:msg, updated_at=NOW()
                WHERE id=:id
            """), {"id": batch_id, "msg": f"running build_30m job #{job_id}"})
            db.commit()

    run_with_deadlock_retry(_update)


def mark_batch_finished(batch_id: int, status: str, result: dict, counts: dict, message: str) -> None:
    def _update():
        with SessionLocal() as db:
            db.execute(text("""
                UPDATE data_import_batch
                SET status=:status,
                    total_files=:codes,
                    success_files=:success_files,
                    failed_files=:failed_files,
                    total_rows=:rows,
                    finished_at=NOW(),
                    message=:message,
                    updated_at=NOW()
                WHERE id=:id
            """), {
                "id": batch_id,
                "status": status,
                "codes": result["codes"],
                "success_files": counts["success"],
                "failed_files": counts["failed"],
                "rows": result["inserted_30m_rows"],
                "message": message,
            })
            db.commit()

    run_with_deadlock_retry(_update)


def parse_args():
    p = argparse.ArgumentParser(description="Run 30m build as background job")
    p.add_argument("--job-id", type=int, default=int(os.getenv("JOB_ID", "0")))
    p.add_argument("--batch-id", type=int, default=int(os.getenv("IMPORT_BATCH_ID", "0")))
    p.add_argument("--market", default=os.getenv("MARKET", "all"))
    p.add_argument("--start", default=os.getenv("START"))
    p.add_argument("--end", default=os.getenv("END"))
    p.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", "4")))
    p.add_argument("--limit-codes", type=int, default=int(os.getenv("LIMIT_CODES", "0")) or None)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    a = parse_args()
    if not a.job_id or not a.batch_id:
        raise RuntimeError("job-id and batch-id are required")
    if not a.start:
        raise RuntimeError("start is required")
    progress_reporter = JobProgressReporter(a.job_id, JobRuntimeStore(Path(__file__).resolve().parents[1] / "logs"))

    with SessionLocal() as db:
        batch = db.execute(text("""
            SELECT id, market, status, message
            FROM data_import_batch
            WHERE id=:id
        """), {"id": a.batch_id}).mappings().first()
        if not batch:
            raise RuntimeError(f"build batch not found: {a.batch_id}")
    mark_batch_running(a.batch_id, a.job_id)

    state = {"success": 0, "failed": 0}

    def on_result(result: dict, done: int, total: int):
        if result.get("ok"):
            state["success"] += 1
        else:
            state["failed"] += 1
        should_flush_mysql = progress_reporter.report(
            {
                "status": "running",
                "done": done,
                "total": total,
                "success_count": state["success"],
                "failed_count": state["failed"],
                "current_code": result.get("code"),
                "message": f"build30m {done}/{total}",
            }
        )
        if not should_flush_mysql:
            return
        with SessionLocal() as db:
            update_job_execution(
                db,
                a.job_id,
                status="running",
                progress_current=done,
                progress_total=total,
                success_count=state["success"],
                failed_count=state["failed"],
                current_code=result.get("code"),
                message=f"build30m {done}/{total}",
            )

    with SessionLocal() as db:
        progress_reporter.report(
            {
                "status": "running",
                "done": 0,
                "total": 0,
                "success_count": 0,
                "failed_count": 0,
                "message": "build_30m started",
            },
            force_mysql=True,
        )
        update_job_execution(
            db,
            a.job_id,
            status="running",
            progress_current=0,
            progress_total=0,
            success_count=0,
            failed_count=0,
            message="build_30m started",
        )

    result = build_30m_parallel(
        a.start,
        a.end,
        a.market or batch["market"] or "all",
        a.workers,
        a.limit_codes,
        a.dry_run,
        a.batch_id,
        on_result=on_result,
    )

    status = "success" if result.get("ok") else "failed"
    counts = final_counts(result, state)
    batch_message = counts["message"]
    mark_batch_finished(a.batch_id, status, result, counts, batch_message)
    with SessionLocal() as db:
        progress_reporter.report(
            {
                "status": status,
                "done": result["codes"],
                "total": result["codes"],
                "success_count": counts["success"],
                "failed_count": counts["failed"],
                "message": batch_message,
            },
            force_mysql=True,
        )
        update_job_execution(
            db,
            a.job_id,
            status=status,
            progress_current=result["codes"],
            progress_total=result["codes"],
            success_count=counts["success"],
            failed_count=counts["failed"],
            message=batch_message,
            finished=True,
        )
        db.commit()

    # 更新 workspace_status：构建30m后刷新对应market的30m数据记录
    if status == "success":
        from app.services.workspace_service import refresh_market_from_db
        from app.core.market_scope import SUPPORTED_MARKET_SCOPES as VALID_MARKETS
        from app.db.session import SessionLocal as _DB
        actual_market = a.market or "all"
        if actual_market == "all":
            for m in VALID_MARKETS:
                with _DB() as db:
                    refresh_market_from_db(db, m, periods=["30m"])
        else:
            with _DB() as db:
                refresh_market_from_db(db, actual_market, periods=["30m"])


if __name__ == "__main__":
    main()

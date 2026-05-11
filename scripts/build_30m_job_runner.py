#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.job_orchestrator import update_job_execution
from scripts.build_30m_from_5m import build_30m_parallel


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

    with SessionLocal() as db:
        batch = db.execute(text("""
            SELECT id, market, status, message
            FROM data_import_batch
            WHERE id=:id
        """), {"id": a.batch_id}).mappings().first()
        if not batch:
            raise RuntimeError(f"build batch not found: {a.batch_id}")
        db.execute(text("""
            UPDATE data_import_batch
            SET status='running', message=:msg, updated_at=NOW()
            WHERE id=:id
        """), {"id": a.batch_id, "msg": f"running build_30m job #{a.job_id}"})
        db.commit()

    state = {"success": 0, "failed": 0}

    def on_result(result: dict, done: int, total: int):
        if result.get("ok"):
            state["success"] += 1
        else:
            state["failed"] += 1
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
            "id": a.batch_id,
            "status": status,
            "codes": result["codes"],
            "success_files": state["success"],
            "failed_files": state["failed"],
            "rows": result["inserted_30m_rows"],
            "message": "finished build_30m",
        })
        update_job_execution(
            db,
            a.job_id,
            status=status,
            progress_current=result["codes"],
            progress_total=result["codes"],
            success_count=state["success"],
            failed_count=state["failed"],
            message=f"build_30m finished codes={result['codes']}",
            finished=True,
        )
        db.commit()


if __name__ == "__main__":
    main()

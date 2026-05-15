#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from app.db.session import SessionLocal
from app.core.redis_client import get_redis_client, ping_redis
from app.services.job_orchestrator import (
    finalize_data_import_batch,
    update_job_execution,
)
from scripts.import_vipdoc_with_pytdx import import_vipdoc_files_parallel


def parse_args():
    p = argparse.ArgumentParser(description="Run vipdoc import as background job")
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
        id_map = {r["file_path"]: int(r["id"]) for r in file_rows}

        db.execute(text("""
            UPDATE data_import_batch
            SET status='running', message=:msg, updated_at=NOW()
            WHERE id=:id
        """), {"id": a.batch_id, "msg": f"running import job #{a.job_id}"})
        db.commit()

    state = {"success": 0, "failed": 0}

    def on_result(result: dict, done: int, total: int):
        if result.get("ok"):
            state["success"] += 1
            batch_message = f"import {done}/{total} phase={result.get('phase')}"
        else:
            state["failed"] += 1
            batch_message = f"import {done}/{total} phase={result.get('phase')}"
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
                message=batch_message,
            )

    with SessionLocal() as db:
        update_job_execution(
            db,
            a.job_id,
            status="running",
            progress_current=0,
            progress_total=len(files),
            success_count=0,
            failed_count=0,
            message=f"import started files={len(files)}",
        )

    # Detect Redis availability
    rc = get_redis_client()
    use_redis = ping_redis(rc)
    mode_label = "redis" if use_redis else "db-fallback"

    result = import_vipdoc_files_parallel(
        files,
        a.market or batch["market"] or "sh60",
        a.import_type,
        a.start,
        a.end,
        a.workers,
        batch_id=a.batch_id,
        import_file_ids=id_map,
        on_result=on_result,
        redis_client=rc if use_redis else None,
    )
    print(f"[import_job_runner] mode={mode_label}", flush=True)

    status = "success" if result["failed_files"] == 0 else "failed"
    flush_error = result.get("flush_error")
    with SessionLocal() as db:
        # If flush failed, preserve the specific error message instead of overwriting
        batch_message = flush_error if flush_error else f"finished import_type={a.import_type}, workers={a.workers}"
        finalize_data_import_batch(
            db,
            a.batch_id,
            status=status,
            success_files=result["success_files"],
            failed_files=result["failed_files"],
            total_rows=result["total_rows"],
            message=batch_message,
        )
        update_job_execution(
            db,
            a.job_id,
            status=status,
            progress_current=result["total_files"],
            progress_total=result["total_files"],
            success_count=result["success_files"],
            failed_count=result["failed_files"],
            message=batch_message,
            finished=True,
        )
        db.commit()

    # 更新 workspace_status：仅成功时刷新
    if status == "success":
        from app.services.workspace_service import refresh_market_from_db
        periods = ["daily"] if a.import_type == "lday" else ["5m"]
        markets = ["sh60", "sh68", "sz00", "sz30"] if (a.market or "all") == "all" else [a.market]
        with SessionLocal() as db:
            for m in markets:
                refresh_market_from_db(db, m, periods=periods)


if __name__ == "__main__":
    main()

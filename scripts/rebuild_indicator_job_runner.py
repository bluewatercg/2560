#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.job_orchestrator import update_job_execution

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    p = argparse.ArgumentParser(description="Run technical_indicator rebuild as background job")
    p.add_argument("--job-id", type=int, default=int(os.getenv("JOB_ID", "0")))
    p.add_argument("--batch-id", type=int, default=int(os.getenv("IMPORT_BATCH_ID", "0")))
    p.add_argument("--market", default=os.getenv("MARKET", "sh60"))
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--periods", default=os.getenv("PERIODS", "daily,5m,30m"))
    p.add_argument("--limit-codes", type=int, default=int(os.getenv("LIMIT_CODES", "0")) or None)
    p.add_argument("--commit-every", type=int, default=int(os.getenv("COMMIT_EVERY", "50")))
    p.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", "4")))
    return p.parse_args()


def main():
    a = parse_args()
    if not a.job_id or not a.batch_id:
        raise RuntimeError("job-id and batch-id are required")

    with SessionLocal() as db:
        db.execute(text("""
            UPDATE data_import_batch
            SET status='running', message=:msg, updated_at=NOW()
            WHERE id=:id
        """), {"id": a.batch_id, "msg": f"running rebuild_indicator job #{a.job_id}"})
        update_job_execution(
            db,
            a.job_id,
            status="running",
            progress_current=0,
            progress_total=0,
            success_count=0,
            failed_count=0,
            message=f"rebuild indicators started market={a.market}, periods={a.periods}",
        )

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "rebuild_technical_indicator.py"),
        "--start",
        a.start,
        "--end",
        a.end,
        "--market-type",
        a.market,
        "--periods",
        a.periods,
        "--commit-every",
        str(a.commit_every),
        "--workers",
        str(a.workers),
    ]
    if a.limit_codes:
        cmd.extend(["--limit-codes", str(a.limit_codes)])

    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    status = "success" if proc.returncode == 0 else "failed"
    message = f"rebuild_indicator {status} rc={proc.returncode}, market={a.market}, periods={a.periods}"

    with SessionLocal() as db:
        db.execute(text("""
            UPDATE data_import_batch
            SET status=:status,
                finished_at=NOW(),
                message=:message,
                updated_at=NOW()
            WHERE id=:id
        """), {"id": a.batch_id, "status": status, "message": message})
        update_job_execution(
            db,
            a.job_id,
            status=status,
            message=message,
            finished=True,
        )

    # 更新 workspace_status：指标重建后刷新对应market的指标记录
    if status == "success":
        from app.services.workspace_service import refresh_market_from_db
        from app.db.session import SessionLocal as _DB
        periods = [p.strip() for p in a.periods.split(",") if p.strip()]
        actual_market = a.market or "all"
        if actual_market == "all":
            for m in ["sh60", "sh68", "sz00", "sz30"]:
                with _DB() as db:
                    refresh_market_from_db(db, m, periods=periods)
        else:
            with _DB() as db:
                refresh_market_from_db(db, actual_market, periods=periods)

    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()

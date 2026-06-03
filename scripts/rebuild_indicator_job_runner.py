#!/usr/bin/env python3
"""Runner for rebuild_indicator jobs.

Uses direct function call to rebuild_period with on_result callback.
Realtime progress goes to runtime files; MySQL receives throttled summaries.
"""
from __future__ import annotations

import argparse
import os
import threading
from pathlib import Path

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.job_orchestrator import update_job_execution
from app.services.job_runtime_store import JobProgressReporter, JobRuntimeStore
from scripts.rebuild_technical_indicator import rebuild_period

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
    progress_reporter = JobProgressReporter(a.job_id, JobRuntimeStore(PROJECT_ROOT / "logs"))

    with SessionLocal() as db:
        db.execute(text("""
            UPDATE data_import_batch
            SET status='running', message=:msg, updated_at=NOW()
            WHERE id=:id
        """), {"id": a.batch_id, "msg": f"running rebuild_indicator job #{a.job_id}"})
        update_job_execution(
            db, a.job_id, status="running",
            progress_current=0, progress_total=0,
            success_count=0, failed_count=0,
            message=f"rebuild indicators started market={a.market}, periods={a.periods}",
        )
        db.commit()
    progress_reporter.report(
        {
            "status": "running",
            "done": 0,
            "total": 0,
            "success_count": 0,
            "failed_count": 0,
            "message": f"rebuild indicators started market={a.market}, periods={a.periods}",
        },
        force_mysql=True,
    )

    periods = [p.strip() for p in a.periods.split(",") if p.strip()]
    limit_codes = a.limit_codes

    # Shared state for progress across all periods
    _lock = threading.Lock()
    _state = {
        "success": 0,
        "failed": 0,
        "total_codes_done": 0,
        "total_codes_all": 0,
        "total_inserted": 0,
        "current_period": "",
    }

    _flush_every = 10  # flush MySQL progress every N codes (avoid per-code writes bottleneck)

    def on_result(result: dict, done: int, total: int):
        """Called after each code completes (from worker threads)."""
        with _lock:
            if result.get("ok"):
                _state["success"] += 1
                _state["total_inserted"] += result.get("rows", 0)
            else:
                _state["failed"] += 1
            _state["total_codes_done"] += 1
            _state["current_period"] = result.get("period", "")

            # Throttle MySQL writes: only flush every _flush_every codes or at completion
            if _state["total_codes_done"] % _flush_every != 0 and done < total:
                return

            try:
                msg = f"{result.get('period', '?')}: {_state['total_codes_done']}/{_state['total_codes_all']} (inserted={_state['total_inserted']})"
                should_flush_mysql = progress_reporter.report(
                    {
                        "status": "running",
                        "done": _state["total_codes_done"],
                        "total": _state["total_codes_all"],
                        "success_count": _state["success"],
                        "failed_count": _state["failed"],
                        "current_code": result.get("code", ""),
                        "message": msg,
                    }
                )
                if not should_flush_mysql:
                    return
                with SessionLocal() as db:
                    update_job_execution(
                        db,
                        a.job_id,
                        status="running",
                        progress_current=_state["total_codes_done"],
                        progress_total=_state["total_codes_all"],
                        success_count=_state["success"],
                        failed_count=_state["failed"],
                        current_code=result.get("code", ""),
                        message=msg,
                    )
                    db.commit()
            except Exception as e:
                print(f"[on_result] MySQL update failed: {e}", flush=True)

    # Build total codes count across all periods
    from scripts.rebuild_technical_indicator import get_codes, get_period_range
    total_all = 0
    for p in periods:
        if p not in {"daily", "5m", "30m"}:
            raise SystemExit(f"不支持 period={p}，只能 daily/5m/30m")
        start_i, end_i = get_period_range(p, a.start, a.end)
        codes = get_codes(p, start_i, end_i, a.market, limit_codes)
        total_all += len(codes)

    with _lock:
        _state["total_codes_all"] = total_all

    # Execute rebuild for each period (periods run sequentially, codes within each period run in parallel)
    results = {}
    for p in periods:
        r = rebuild_period(
            p, a.start, a.end, a.market, limit_codes, a.commit_every,
            workers=a.workers, on_result=on_result,
        )
        results[p] = r

    ok = all(r.get("ok") for r in results.values())
    status = "success" if ok else "failed"
    total_inserted = sum(r.get("total_inserted", 0) for r in results.values())
    message = f"rebuild_indicator {status}: market={a.market}, periods={a.periods}, inserted={total_inserted}"

    with SessionLocal() as db:
        db.execute(text("""
            UPDATE data_import_batch
            SET status=:status, finished_at=NOW(), message=:message, updated_at=NOW()
            WHERE id=:id
        """), {"id": a.batch_id, "status": status, "message": message})
        progress_reporter.report(
            {
                "status": status,
                "done": total_all,
                "total": total_all,
                "success_count": _state["success"],
                "failed_count": _state["failed"],
                "message": message,
            },
            force_mysql=True,
        )
        update_job_execution(
            db, a.job_id, status=status,
            progress_current=total_all, progress_total=total_all,
            success_count=_state["success"], failed_count=_state["failed"],
            message=message, finished=True,
        )
        db.commit()

    # 更新 workspace_status：指标重建后刷新对应market的指标记录
    if ok:
        from app.services.workspace_service import refresh_market_from_db
        from app.db.session import SessionLocal as _DB
        actual_market = a.market or "all"
        if actual_market == "all":
            for m in ["sh60", "sh68", "sz00", "sz30"]:
                with _DB() as db:
                    refresh_market_from_db(db, m, periods=periods)
        else:
            with _DB() as db:
                refresh_market_from_db(db, actual_market, periods=periods)


if __name__ == "__main__":
    main()

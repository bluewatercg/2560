from __future__ import annotations

import json
import os
import subprocess
import signal
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.job_orchestrator import create_job_execution
from app.services.job_orchestrator import ensure_job_tables as _ensure_tables

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EnqueueJobRequest(BaseModel):
    strategy_code: str = Field(default="S2560")
    job_type: str = Field(default="run_2560")
    priority: int = Field(default=3, ge=1, le=9)
    market: str = Field(default="all")
    shards: int = Field(default=4, ge=1, le=32)
    limit_codes: int | None = Field(default=None, ge=1)


class RunNowRequest(BaseModel):
    market: str = Field(default="all")
    shards: int = Field(default=4, ge=1, le=32)


def _table_exists(db: Session, table_name: str) -> bool:
    return bool(
        db.execute(
            text("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name=:t
    """),
            {"t": table_name},
        ).scalar()
        or 0
    )


def _market_where(alias: str, market: str) -> str:
    col = f"{alias}.code"
    m = (market or "all").lower()
    if m == "sh":
        return f"{col} LIKE 'sh.%'"
    if m == "sz":
        return f"{col} LIKE 'sz.%'"
    if m == "sh60":
        return f"{col} LIKE 'sh.60%'"
    if m == "sh68":
        return f"{col} LIKE 'sh.68%'"
    if m == "sz00":
        return f"{col} LIKE 'sz.00%'"
    if m == "sz30":
        return f"{col} LIKE 'sz.30%'"
    return f"({col} LIKE 'sh.%' OR {col} LIKE 'sz.%')"


def _count_codes(db: Session, market: str) -> int:
    if not _table_exists(db, "stock_info"):
        return 0
    return int(
        db.execute(
            text(
                f"SELECT COUNT(*) FROM stock_info s WHERE {_market_where('s', market)}"
            )
        ).scalar()
        or 0
    )


@router.get("/queue")
def queue(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    if not _table_exists(db, "job_queue"):
        return []
    return (
        db.execute(
            text("""
        SELECT id, job_type, strategy_code, priority, payload, status,
               created_at, started_at, finished_at, updated_at
        FROM job_queue
        ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                 priority ASC, created_at DESC
        LIMIT :limit
    """),
            {"limit": limit},
        )
        .mappings()
        .all()
    )


@router.get("/executions")
def executions(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    if not _table_exists(db, "job_execution"):
        return []
    return (
        db.execute(
            text("""
        SELECT id, job_type, batch_id, status,
               progress_current, progress_total, success_count, failed_count,
               current_code, market, shards, pid, log_file, message,
               started_at, finished_at, updated_at
        FROM job_execution
        ORDER BY started_at DESC, id DESC
        LIMIT :limit
    """),
            {"limit": limit},
        )
        .mappings()
        .all()
    )


@router.get("/executions/{job_id}/items")
def execution_items(
    job_id: int, limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_db)
):
    if not _table_exists(db, "job_task_item"):
        return []
    return (
        db.execute(
            text("""
        SELECT id, job_id, shard_id, code, status, retry_count, elapsed_ms,
               last_error, started_at, finished_at, updated_at
        FROM job_task_item
        WHERE job_id=:job_id
        ORDER BY shard_id, status, code
        LIMIT :limit
    """),
            {"job_id": job_id, "limit": limit},
        )
        .mappings()
        .all()
    )


@router.get("/executions/{job_id}/progress")
def execution_progress(job_id: int, db: Session = Depends(get_db)):
    if not _table_exists(db, "job_execution"):
        return {"ok": False, "message": "job_execution table not found"}
    row = (
        db.execute(
            text("""
        SELECT id, job_type, status, progress_current, progress_total,
               success_count, failed_count, current_code, market, shards,
               pid, log_file, message, started_at, finished_at, updated_at,
               TIMESTAMPDIFF(SECOND, started_at, COALESCE(finished_at, NOW())) AS elapsed_seconds
        FROM job_execution WHERE id=:id
    """),
            {"id": job_id},
        )
        .mappings()
        .first()
    )
    if not row:
        return {"ok": False, "message": "job not found"}
    d = dict(row)
    done = int(d.get("progress_current") or 0)
    total = int(d.get("progress_total") or 0)
    elapsed = int(d.get("elapsed_seconds") or 0)
    percent = round(done * 100 / total, 2) if total else 0.0
    avg = round(elapsed / done, 3) if done else None
    eta = int((total - done) * avg) if avg and total >= done else None
    d.update(
        {
            "ok": True,
            "done": done,
            "total": total,
            "percent": percent,
            "avg_seconds_per_code": avg,
            "eta_seconds": eta,
            "eta_text": _format_seconds(eta),
            "elapsed_text": _format_seconds(elapsed),
        }
    )
    return d




@router.get("/executions/{job_id}/shards")
def execution_shards(job_id: int, db: Session = Depends(get_db)):
    """
    按并发组 / shard 返回每组进度。
    用于页面展示：同时跑几组，每组各自完成多少、当前代码、成功/失败数量。
    """
    if not _table_exists(db, "job_task_item"):
        return {"ok": False, "items": []}

    rows = db.execute(text("""
        SELECT
            shard_id,
            COUNT(*) AS total,
            SUM(CASE WHEN status IN ('success','failed','cancelled','interrupted') THEN 1 ELSE 0 END) AS done,
            SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count,
            SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running_count,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending_count,
            ROUND(AVG(CASE WHEN elapsed_ms IS NOT NULL THEN elapsed_ms END), 0) AS avg_elapsed_ms,
            MIN(CASE WHEN status='running' THEN code END) AS current_code,
            MAX(updated_at) AS updated_at
        FROM job_task_item
        WHERE job_id=:job_id
        GROUP BY shard_id
        ORDER BY shard_id
    """), {"job_id": job_id}).mappings().all()

    items = []
    total_all = 0
    done_all = 0

    for r in rows:
        d = dict(r)
        total = int(d.get("total") or 0)
        done = int(d.get("done") or 0)

        d["total"] = total
        d["done"] = done
        d["percent"] = round(done * 100 / total, 2) if total else 0.0
        d["success_count"] = int(d.get("success_count") or 0)
        d["failed_count"] = int(d.get("failed_count") or 0)
        d["running_count"] = int(d.get("running_count") or 0)
        d["pending_count"] = int(d.get("pending_count") or 0)

        total_all += total
        done_all += done
        items.append(d)

    return {
        "ok": True,
        "job_id": job_id,
        "total": total_all,
        "done": done_all,
        "percent": round(done_all * 100 / total_all, 2) if total_all else 0.0,
        "items": items,
    }

@router.get("/executions/{job_id}/logs")
def execution_logs(
    job_id: int, tail: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db)
):
    if not _table_exists(db, "job_execution"):
        return {"ok": False, "lines": []}
    row = (
        db.execute(
            text("SELECT log_file FROM job_execution WHERE id=:id"), {"id": job_id}
        )
        .mappings()
        .first()
    )
    if not row or not row.get("log_file"):
        return {"ok": False, "lines": []}
    log_file = Path(str(row["log_file"]))
    if not log_file.is_absolute():
        log_file = PROJECT_ROOT / log_file
    try:
        return {
            "ok": True,
            "job_id": job_id,
            "log_file": str(log_file),
            "lines": _tail_lines(log_file, tail),
        }
    except FileNotFoundError:
        return {"ok": False, "job_id": job_id, "log_file": str(log_file), "lines": []}


@router.post("/enqueue")
def enqueue_job(payload: EnqueueJobRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)
    job_payload: dict[str, Any] = {"market": payload.market, "shards": payload.shards}
    if payload.limit_codes is not None:
        job_payload["limit_codes"] = payload.limit_codes
    if payload.job_type == "run_2560":
        job_execution_id = create_job_execution(
            db,
            payload.job_type,
            market=payload.market,
            shards=payload.shards,
            total=0,
            message="queued",
            status="queued",
        )
        job_payload["job_execution_id"] = job_execution_id
    res = db.execute(
        text("""
        INSERT INTO job_queue (job_type, strategy_code, priority, payload, status, created_at)
        VALUES (:job_type, :strategy_code, :priority, CAST(:payload AS JSON), 'pending', NOW())
    """),
        {
            "job_type": payload.job_type,
            "strategy_code": payload.strategy_code,
            "priority": payload.priority,
            "payload": json.dumps(job_payload, ensure_ascii=False),
        },
    )
    db.commit()
    return {"ok": True, "job_id": res.lastrowid, "payload": job_payload}


@router.post("/run-now")
def run_now(payload: RunNowRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)
    total = _count_codes(db, payload.market)
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    res = db.execute(
        text("""
        INSERT INTO job_execution
        (job_type, status, progress_current, progress_total, success_count, failed_count,
         current_code, market, shards, pid, message, started_at, updated_at)
        VALUES ('run_2560_now', 'running', 0, :total, 0, 0, NULL, :market, :shards, NULL, :message, NOW(), NOW())
    """),
        {
            "total": total,
            "market": payload.market,
            "shards": payload.shards,
            "message": "starting",
        },
    )
    job_id = int(res.lastrowid)
    log_file = log_dir / f"job_{job_id}_progress.log"
    db.execute(
        text("UPDATE job_execution SET log_file=:log_file WHERE id=:id"),
        {"id": job_id, "log_file": str(log_file)},
    )
    db.commit()

    runner = PROJECT_ROOT / "scripts" / "progress_run_now.py"
    if not runner.exists():
        db.execute(
            text(
                "UPDATE job_execution SET status='failed', message=:msg, finished_at=NOW(), updated_at=NOW() WHERE id=:id"
            ),
            {"id": job_id, "msg": f"runner not found: {runner}"},
        )
        db.commit()
        return {"ok": False, "job_id": job_id, "message": f"runner not found: {runner}"}

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["JOB_ID"] = str(job_id)
    env["MARKET"] = payload.market
    env["SHARDS"] = str(payload.shards)
    env["LOG_FILE"] = str(log_file)
    env.setdefault("WEB_BASE_URL", "http://127.0.0.1:8000")

    with open(log_file, "ab") as out:
        proc = subprocess.Popen(
            [sys.executable, str(runner)],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )

    db.execute(
        text("UPDATE job_execution SET pid=:pid, message=:msg, updated_at=NOW() WHERE id=:id"),
        {"id": job_id, "pid": proc.pid, "msg": f"started pid={proc.pid}, total={total}"},
    )
    db.commit()
    return {
        "ok": True,
        "job_id": job_id,
        "pid": proc.pid,
        "total": total,
        "market": payload.market,
        "shards": payload.shards,
        "log_file": str(log_file),
        "progress_url": f"/api/jobs/executions/{job_id}/progress",
        "logs_url": f"/api/jobs/executions/{job_id}/logs?tail=200",
    }


def _format_seconds(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _tail_lines(path: Path, n: int) -> list[str]:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        block = 4096
        data = b""
        while end > 0 and data.count(b"\n") <= n:
            step = min(block, end)
            end -= step
            f.seek(end)
            data = f.read(step) + data
        return data.decode("utf-8", errors="replace").splitlines()[-n:]

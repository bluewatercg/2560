from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EnqueueJobRequest(BaseModel):
    strategy_code: str = Field(default="S2560")
    job_type: str = Field(default="run_2560")
    priority: int = Field(default=3, ge=1, le=9)
    market: str = Field(default="all")
    shards: int = Field(default=4, ge=1, le=32)


class RunNowRequest(BaseModel):
    market: str = Field(default="all")
    shards: int = Field(default=4, ge=1, le=32)


def _table_exists(db: Session, table_name: str) -> bool:
    return db.execute(text("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name=:t
    """), {"t": table_name}).scalar() > 0


def _ensure_tables(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS job_queue (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            job_type VARCHAR(50) NOT NULL,
            strategy_code VARCHAR(20) NOT NULL,
            priority INT NOT NULL DEFAULT 5,
            payload JSON NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_queue (status, priority, created_at),
            KEY idx_strategy (strategy_code)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS job_execution (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            job_type VARCHAR(50) NOT NULL,
            batch_id VARCHAR(100) NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            progress_current INT NOT NULL DEFAULT 0,
            progress_total INT NOT NULL DEFAULT 0,
            success_count INT NOT NULL DEFAULT 0,
            failed_count INT NOT NULL DEFAULT 0,
            current_code VARCHAR(30) NULL,
            market VARCHAR(20) NULL,
            shards INT NULL,
            log_file VARCHAR(500) NULL,
            message TEXT NULL,
            started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_status_started (status, started_at),
            KEY idx_updated (updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS job_task_item (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            job_id BIGINT NOT NULL,
            shard_id INT NOT NULL DEFAULT 0,
            code VARCHAR(30) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            retry_count INT NOT NULL DEFAULT 0,
            elapsed_ms INT NULL,
            last_error TEXT NULL,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_job_code (job_id, code),
            KEY idx_job_status (job_id, status),
            KEY idx_shard (job_id, shard_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))
    db.commit()


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
    sql = f"SELECT COUNT(*) FROM stock_info s WHERE {_market_where('s', market)}"
    return int(db.execute(text(sql)).scalar() or 0)


@router.get("/queue")
def queue(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    if not _table_exists(db, "job_queue"):
        return []
    return db.execute(text("""
        SELECT id, job_type, strategy_code, priority, payload, status,
               created_at, started_at, finished_at, updated_at
        FROM job_queue
        ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                 priority ASC, created_at DESC
        LIMIT :limit
    """), {"limit": limit}).mappings().all()


@router.get("/executions")
def executions(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    if not _table_exists(db, "job_execution"):
        return []
    return db.execute(text("""
        SELECT id, job_type, batch_id, status,
               progress_current, progress_total, success_count, failed_count,
               current_code, market, shards, log_file, message,
               started_at, finished_at, updated_at
        FROM job_execution
        ORDER BY started_at DESC, id DESC
        LIMIT :limit
    """), {"limit": limit}).mappings().all()


@router.get("/executions/{job_id}/items")
def execution_items(job_id: int, limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_db)):
    if not _table_exists(db, "job_task_item"):
        return []
    return db.execute(text("""
        SELECT id, job_id, shard_id, code, status, retry_count, elapsed_ms,
               last_error, started_at, finished_at, updated_at
        FROM job_task_item
        WHERE job_id=:job_id
        ORDER BY shard_id, status, code
        LIMIT :limit
    """), {"job_id": job_id, "limit": limit}).mappings().all()


@router.get("/executions/{job_id}/progress")
def execution_progress(job_id: int, db: Session = Depends(get_db)):
    if not _table_exists(db, "job_execution"):
        return {"ok": False, "message": "job_execution table not found"}
    row = db.execute(text("""
        SELECT id, job_type, status, progress_current, progress_total,
               success_count, failed_count, current_code, market, shards,
               log_file, message, started_at, finished_at, updated_at,
               TIMESTAMPDIFF(SECOND, started_at, COALESCE(finished_at, NOW())) AS elapsed_seconds
        FROM job_execution WHERE id=:id
    """), {"id": job_id}).mappings().first()
    if not row:
        return {"ok": False, "message": "job not found"}
    d = dict(row)
    done = int(d.get("progress_current") or 0)
    total = int(d.get("progress_total") or 0)
    elapsed = int(d.get("elapsed_seconds") or 0)
    percent = round(done * 100 / total, 2) if total else 0.0
    avg = round(elapsed / done, 3) if done else None
    eta = int((total - done) * avg) if avg and total >= done else None
    d.update({
        "ok": True,
        "done": done,
        "total": total,
        "percent": percent,
        "avg_seconds_per_code": avg,
        "eta_seconds": eta,
        "eta_text": _format_seconds(eta),
        "elapsed_text": _format_seconds(elapsed),
    })
    return d


@router.get("/executions/{job_id}/logs")
def execution_logs(job_id: int, tail: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db)):
    if not _table_exists(db, "job_execution"):
        return {"ok": False, "lines": []}
    row = db.execute(text("SELECT log_file FROM job_execution WHERE id=:id"), {"id": job_id}).mappings().first()
    if not row or not row.get("log_file"):
        return {"ok": False, "lines": []}
    log_file = Path(str(row["log_file"]))
    if not log_file.is_absolute():
        log_file = PROJECT_ROOT / log_file
    try:
        lines = _tail_lines(log_file, tail)
        return {"ok": True, "job_id": job_id, "log_file": str(log_file), "lines": lines}
    except FileNotFoundError:
        return {"ok": False, "job_id": job_id, "log_file": str(log_file), "lines": []}


@router.post("/enqueue")
def enqueue_job(payload: EnqueueJobRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)
    job_payload: dict[str, Any] = {"market": payload.market, "shards": payload.shards}
    res = db.execute(text("""
        INSERT INTO job_queue (job_type, strategy_code, priority, payload, status, created_at)
        VALUES (:job_type, :strategy_code, :priority, CAST(:payload AS JSON), 'pending', NOW())
    """), {
        "job_type": payload.job_type,
        "strategy_code": payload.strategy_code,
        "priority": payload.priority,
        "payload": json.dumps(job_payload, ensure_ascii=False),
    })
    db.commit()
    return {"ok": True, "job_id": res.lastrowid, "payload": job_payload}


@router.post("/run-now")
def run_now(payload: RunNowRequest, db: Session = Depends(get_db)):
    """立即执行并跟踪：创建 job_execution，并启动 progress_run_now.py。

    与旧版不同：返回 job_id / total / progress_url / logs_url，前端可实时轮询。
    """
    _ensure_tables(db)
    total = _count_codes(db, payload.market)
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    # 注意：容器部署时 logs 目录需要 appuser 可写。
    res = db.execute(text("""
        INSERT INTO job_execution
        (job_type, status, progress_current, progress_total, success_count, failed_count,
         current_code, market, shards, message, started_at, updated_at)
        VALUES
        ('run_2560_now', 'running', 0, :total, 0, 0, NULL, :market, :shards,
         :message, NOW(), NOW())
    """), {"total": total, "market": payload.market, "shards": payload.shards, "message": "starting"})
    job_id = int(res.lastrowid)
    log_file = log_dir / f"job_{job_id}_progress.log"
    db.execute(text("UPDATE job_execution SET log_file=:log_file WHERE id=:id"), {"id": job_id, "log_file": str(log_file)})
    db.commit()

    runner = PROJECT_ROOT / "scripts" / "progress_run_now.py"
    if not runner.exists():
        db.execute(text("UPDATE job_execution SET status='failed', message=:msg, finished_at=NOW(), updated_at=NOW() WHERE id=:id"),
                   {"id": job_id, "msg": f"runner not found: {runner}"})
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
        proc = subprocess.Popen(["python", str(runner)], cwd=str(PROJECT_ROOT), env=env, stdout=out, stderr=subprocess.STDOUT)

    db.execute(text("UPDATE job_execution SET message=:msg, updated_at=NOW() WHERE id=:id"),
               {"id": job_id, "msg": f"started pid={proc.pid}, total={total}"})
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
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


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
        lines = data.decode("utf-8", errors="replace").splitlines()
        return lines[-n:]

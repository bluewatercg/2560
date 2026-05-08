from __future__ import annotations

import json
import os
import subprocess
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
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name=:t
    """), {"t": table_name}).scalar() > 0


def _ensure_job_queue(db: Session) -> None:
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
    db.commit()


@router.get("/queue")
def queue(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    if not _table_exists(db, "job_queue"):
        return []
    sql = """
    SELECT id, job_type, strategy_code, priority, payload, status,
           created_at, started_at, finished_at, updated_at
    FROM job_queue
    ORDER BY
      CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
      priority ASC,
      created_at DESC
    LIMIT :limit
    """
    return db.execute(text(sql), {"limit": limit}).mappings().all()


@router.get("/executions")
def executions(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    if not _table_exists(db, "job_execution"):
        return []
    sql = """
    SELECT id, job_type, batch_id, status,
           progress_current, progress_total,
           message, started_at, finished_at, updated_at
    FROM job_execution
    ORDER BY started_at DESC, id DESC
    LIMIT :limit
    """
    return db.execute(text(sql), {"limit": limit}).mappings().all()


@router.get("/executions/{job_id}/items")
def execution_items(job_id: int, limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_db)):
    if not _table_exists(db, "job_task_item"):
        return []
    sql = """
    SELECT id, job_id, shard_id, code, status, retry_count, last_error, updated_at
    FROM job_task_item
    WHERE job_id=:job_id
    ORDER BY shard_id, status, code
    LIMIT :limit
    """
    return db.execute(text(sql), {"job_id": job_id, "limit": limit}).mappings().all()


@router.post("/enqueue")
def enqueue_job(payload: EnqueueJobRequest, db: Session = Depends(get_db)):
    _ensure_job_queue(db)
    job_payload: dict[str, Any] = {"market": payload.market, "shards": payload.shards}
    res = db.execute(text("""
        INSERT INTO job_queue
        (job_type, strategy_code, priority, payload, status, created_at)
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
def run_now(payload: RunNowRequest):
    script = PROJECT_ROOT / "scripts" / "daily_update_incremental_sharded.sh"
    if not script.exists():
        return {"ok": False, "message": f"脚本不存在: {script}"}
    env = os.environ.copy()
    env["SHARDS"] = str(payload.shards)
    env["MARKET"] = payload.market
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "daily_update_incremental_sharded.log"
    with open(log_file, "ab") as out:
        proc = subprocess.Popen(["bash", str(script)], cwd=str(PROJECT_ROOT), env=env, stdout=out, stderr=subprocess.STDOUT)
    return {"ok": True, "pid": proc.pid, "log_file": str(log_file), "market": payload.market, "shards": payload.shards}

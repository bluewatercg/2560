from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    return bool(
        db.execute(
            text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = :table_name
                  AND column_name = :column_name
            """),
            {"table_name": table_name, "column_name": column_name},
        ).scalar()
        or 0
    )


def ensure_job_tables(db: Session) -> None:
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
            cancel_requested_at DATETIME NULL,
            progress_current INT NOT NULL DEFAULT 0,
            progress_total INT NOT NULL DEFAULT 0,
            success_count INT NOT NULL DEFAULT 0,
            failed_count INT NOT NULL DEFAULT 0,
            current_code VARCHAR(30) NULL,
            market VARCHAR(20) NULL,
            shards INT NULL,
            pid BIGINT NULL,
            log_file VARCHAR(500) NULL,
            message TEXT NULL,
            started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            KEY idx_status_started (status, started_at),
            KEY idx_updated (updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))
    if not _column_exists(db, "job_execution", "pid"):
        db.execute(text("ALTER TABLE job_execution ADD COLUMN pid BIGINT NULL AFTER shards"))
    if not _column_exists(db, "job_execution", "cancel_requested_at"):
        db.execute(text("ALTER TABLE job_execution ADD COLUMN cancel_requested_at DATETIME NULL AFTER status"))
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
    if not _column_exists(db, "job_task_item", "shard_id"):
        db.execute(text("ALTER TABLE job_task_item ADD COLUMN shard_id INT NOT NULL DEFAULT 0 AFTER job_id"))
        db.execute(text("ALTER TABLE job_task_item ADD KEY idx_shard (job_id, shard_id)"))
    db.commit()


def enqueue_job(db: Session, job_type: str, strategy_code: str, priority: int, payload: dict[str, Any]) -> int:
    ensure_job_tables(db)
    res = db.execute(text("""
        INSERT INTO job_queue (job_type, strategy_code, priority, payload, status, created_at)
        VALUES (:job_type, :strategy_code, :priority, CAST(:payload AS JSON), 'pending', NOW())
    """), {
        "job_type": job_type,
        "strategy_code": strategy_code,
        "priority": priority,
        "payload": json.dumps(payload, ensure_ascii=False),
    })
    db.commit()
    return int(res.lastrowid)


def create_job_execution(
    db: Session,
    job_type: str,
    market: str | None = None,
    shards: int | None = None,
    batch_id: str | None = None,
    total: int = 0,
    message: str = "queued",
    status: str = "queued",
) -> int:
    ensure_job_tables(db)
    res = db.execute(text("""
        INSERT INTO job_execution
        (job_type, batch_id, status, progress_current, progress_total, success_count, failed_count,
         current_code, market, shards, message, started_at, updated_at)
        VALUES (:job_type, :batch_id, :status, 0, :total, 0, 0, NULL, :market, :shards, :message, NOW(), NOW())
    """), {
        "job_type": job_type,
        "batch_id": batch_id,
        "status": status,
        "total": total,
        "market": market,
        "shards": shards,
        "message": message,
    })
    db.commit()
    return int(res.lastrowid)


def update_job_execution(
    db: Session,
    job_id: int,
    *,
    status: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
    success_count: int | None = None,
    failed_count: int | None = None,
    current_code: str | None = None,
    message: str | None = None,
    finished: bool = False,
) -> None:
    ensure_job_tables(db)
    sets = ["updated_at=NOW()"]
    params: dict[str, Any] = {"id": job_id}
    if status is not None:
        sets.append("status=:status")
        params["status"] = status
    if progress_current is not None:
        sets.append("progress_current=:progress_current")
        params["progress_current"] = progress_current
    if progress_total is not None:
        sets.append("progress_total=:progress_total")
        params["progress_total"] = progress_total
    if success_count is not None:
        sets.append("success_count=:success_count")
        params["success_count"] = success_count
    if failed_count is not None:
        sets.append("failed_count=:failed_count")
        params["failed_count"] = failed_count
    if current_code is not None:
        sets.append("current_code=:current_code")
        params["current_code"] = current_code
    if message is not None:
        sets.append("message=:message")
        params["message"] = message
    if finished:
        sets.append("finished_at=NOW()")
    db.execute(text(f"UPDATE job_execution SET {', '.join(sets)} WHERE id=:id"), params)
    db.commit()


def update_data_import_batch_progress(
    db: Session,
    batch_id: int,
    *,
    success_delta: int = 0,
    failed_delta: int = 0,
    total_rows_delta: int = 0,
    message: str | None = None,
) -> None:
    sets = [
        "success_files = success_files + :success_delta",
        "failed_files = failed_files + :failed_delta",
        "total_rows = total_rows + :total_rows_delta",
        "updated_at = NOW()",
    ]
    params: dict[str, Any] = {
        "id": batch_id,
        "success_delta": success_delta,
        "failed_delta": failed_delta,
        "total_rows_delta": total_rows_delta,
    }
    if message is not None:
        sets.append("message = :message")
        params["message"] = message
    db.execute(text(f"UPDATE data_import_batch SET {', '.join(sets)} WHERE id=:id"), params)
    db.commit()


def finalize_data_import_batch(
    db: Session,
    batch_id: int,
    *,
    status: str,
    total_files: int | None = None,
    success_files: int | None = None,
    failed_files: int | None = None,
    total_rows: int | None = None,
    message: str | None = None,
) -> None:
    sets = ["status=:status", "updated_at=NOW()", "finished_at=NOW()"]
    params: dict[str, Any] = {"id": batch_id, "status": status}
    if total_files is not None:
        sets.append("total_files=:total_files")
        params["total_files"] = total_files
    if success_files is not None:
        sets.append("success_files=:success_files")
        params["success_files"] = success_files
    if failed_files is not None:
        sets.append("failed_files=:failed_files")
        params["failed_files"] = failed_files
    if total_rows is not None:
        sets.append("total_rows=:total_rows")
        params["total_rows"] = total_rows
    if message is not None:
        sets.append("message=:message")
        params["message"] = message
    db.execute(text(f"UPDATE data_import_batch SET {', '.join(sets)} WHERE id=:id"), params)
    db.commit()

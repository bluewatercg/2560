from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.job_orchestrator import create_job_execution, enqueue_job, ensure_job_tables
from scripts.import_vipdoc_clickhouse import scan_vipdoc_files
from scripts.import_vipdoc_clickhouse import (
    import_daily_clickhouse, import_5m_clickhouse,
    CH_URL as _CH_URL, ch_ping as _ch_ping,
)

router = APIRouter(prefix="/api/import", tags=["import"])
DEFAULT_VIPDOC_ROOT = os.getenv("VIPDOC_ROOT", "/data/vipdoc")


class ImportScanRequest(BaseModel):
    source_dir: str = Field(default=DEFAULT_VIPDOC_ROOT)
    market: str = Field(default="sh60")
    import_type: str = Field(default="all")


class ImportRunRequest(BaseModel):
    source_dir: str = Field(default=DEFAULT_VIPDOC_ROOT)
    market: str = Field(default="sh60")
    import_type: str = Field(default="lday")
    start: Optional[str] = None
    end: Optional[str] = None
    workers: int = Field(default=4, ge=1, le=128)
    limit_files: Optional[int] = None


class Build30mRequest(BaseModel):
    start: str
    end: Optional[str] = None
    market: str = Field(default="all")
    workers: int = Field(default=4, ge=1, le=128)
    limit_codes: Optional[int] = None
    dry_run: bool = False


class RebuildIndicatorRequest(BaseModel):
    start: str
    end: str
    market: str = Field(default="sh60")
    periods: str = Field(default="daily,5m,30m")
    limit_codes: Optional[int] = None
    commit_every: int = Field(default=50, ge=1, le=1000)


class CancelBatchRequest(BaseModel):
    reason: str = Field(default="用户取消/废弃")


def _table_exists(db: Session, table_name: str) -> bool:
    return bool(db.execute(text("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema=DATABASE() AND table_name=:t
    """), {"t": table_name}).scalar() or 0)


def _ensure_import_tables(db: Session) -> None:
    ensure_job_tables(db)
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS data_import_batch (
          id BIGINT PRIMARY KEY AUTO_INCREMENT,
          import_type VARCHAR(50) NOT NULL DEFAULT 'vipdoc',
          source_dir VARCHAR(500) NULL,
          market VARCHAR(20) NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'queued',
          total_files INT NOT NULL DEFAULT 0,
          success_files INT NOT NULL DEFAULT 0,
          failed_files INT NOT NULL DEFAULT 0,
          total_rows BIGINT NOT NULL DEFAULT 0,
          started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          finished_at DATETIME NULL,
          message TEXT NULL,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          KEY idx_status_started (status, started_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))
    # 修复已存在表缺少 updated_at 默认值的问题
    db.execute(text("""
        ALTER TABLE data_import_batch
        MODIFY COLUMN updated_at DATETIME NOT NULL
            DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS data_import_file (
          id BIGINT PRIMARY KEY AUTO_INCREMENT,
          import_batch_id BIGINT NOT NULL,
          file_path VARCHAR(700) NOT NULL,
          market VARCHAR(20) NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'pending',
          rows_imported INT NOT NULL DEFAULT 0,
          last_error TEXT NULL,
          started_at DATETIME NULL,
          finished_at DATETIME NULL,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          KEY idx_batch (import_batch_id),
          KEY idx_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))
    # 修复已存在表缺少 updated_at 默认值的问题
    db.execute(text("""
        ALTER TABLE data_import_batch
        MODIFY COLUMN updated_at DATETIME NOT NULL
            DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    """))
    db.execute(text("""
        ALTER TABLE data_import_file
        MODIFY COLUMN updated_at DATETIME NOT NULL
            DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    """))
    db.commit()


def _merge_job_progress(batch: dict, job: dict | None) -> dict:
    d = dict(batch)
    total = int(d.get("total_files") or 0)
    batch_success = int(d.get("success_files") or 0)
    batch_failed = int(d.get("failed_files") or 0)
    batch_done = batch_success + batch_failed
    d["batch_done_files"] = batch_done
    d["batch_progress_percent"] = round(batch_done * 100 / total, 2) if total else 0.0

    if job:
        job_id = int(job.get("id") or 0)
        current = int(job.get("progress_current") or 0)
        job_total = int(job.get("progress_total") or 0)
        d.update({
            "job_id": job_id,
            "job_type": job.get("job_type"),
            "progress_url": f"/api/jobs/executions/{job_id}/progress",
            "job_status": job.get("status"),
            "job_progress_current": current,
            "job_progress_total": job_total,
            "job_success_count": int(job.get("success_count") or 0),
            "job_failed_count": int(job.get("failed_count") or 0),
            "workers": int(job.get("shards") or 0),
            "current_code": job.get("current_code"),
            "job_message": job.get("message"),
            "job_started_at": job.get("started_at"),
            "job_finished_at": job.get("finished_at"),
            "job_updated_at": job.get("updated_at"),
            "done_files": current,
            "progress_percent": round(current * 100 / job_total, 2) if job_total else 0.0,
        })
    else:
        d.update({
            "job_id": None,
            "job_type": None,
            "progress_url": None,
            "job_status": None,
            "job_progress_current": None,
            "job_progress_total": None,
            "job_success_count": None,
            "job_failed_count": None,
            "workers": None,
            "current_code": None,
            "job_message": None,
            "job_started_at": None,
            "job_finished_at": None,
            "job_updated_at": None,
            "done_files": batch_done,
            "progress_percent": d["batch_progress_percent"],
        })
    return d


def _merge_data_range(batch: dict, data_range: dict | None) -> dict:
    d = dict(batch)
    start = data_range.get("data_start") if data_range else None
    end = data_range.get("data_end") if data_range else None
    d["data_start"] = int(start) if start is not None else None
    d["data_end"] = int(end) if end is not None else None
    if d["data_start"] is not None and d["data_end"] is not None:
        d["data_range"] = f"{d['data_start']} - {d['data_end']}"
    else:
        d["data_range"] = None
    return d


def _date_range_for_batch(db: Session, batch: dict) -> dict | None:
    if not batch:
        return None
    import_type = str(batch.get("import_type") or "").lower()
    batch_id = int(batch.get("id") or 0)
    if not batch_id:
        return None

    files = db.execute(text("""
        SELECT file_path
        FROM data_import_file
        WHERE import_batch_id=:id AND status='success'
    """), {"id": batch_id}).mappings().all()
    codes = []
    for row in files:
        stem = os.path.basename(str(row["file_path"])).split(".")[0].lower()
        digits = "".join(ch for ch in stem if ch.isdigit())
        if len(digits) < 6:
            continue
        side = "sh" if stem.startswith("sh") else "sz" if stem.startswith("sz") else None
        if side:
            codes.append(f"{side}.{digits[-6:]}")
    codes = sorted(set(codes))
    if not codes:
        return None

    if import_type in ("lday", "daily"):
        table = "daily_kline"
        where_period = ""
        params = {"codes": codes}
    elif import_type in ("5m", "lc5", "fzline"):
        table = "minute_kline_period"
        where_period = " AND period='5m'"
        params = {"codes": codes}
    elif import_type == "build_30m":
        table = "minute_kline_period"
        where_period = " AND period='30m'"
        params = {"codes": codes}
    else:
        return None
    if not _table_exists(db, table):
        return None

    stmt = text(f"""
        SELECT MIN(date) AS data_start, MAX(date) AS data_end
        FROM {table}
        WHERE code IN :codes {where_period}
    """).bindparams(bindparam("codes", expanding=True))
    row = db.execute(stmt, params).mappings().first()
    return dict(row) if row and row.get("data_start") is not None else None

def _latest_job_for_batch(db: Session, batch_id: int) -> dict | None:
    if not _table_exists(db, "job_execution"):
        return None
    row = db.execute(text("""
        SELECT id, job_type, status, cancel_requested_at, progress_current, progress_total,
               success_count, failed_count, current_code, market, shards,
               message, started_at, finished_at, updated_at
        FROM job_execution
        WHERE batch_id = CAST(:batch_id AS CHAR)
          AND job_type IN ('import_vipdoc', 'build_30m', 'rebuild_indicator')
        ORDER BY id DESC
        LIMIT 1
    """), {"batch_id": batch_id}).mappings().first()
    return dict(row) if row else None


def _cancel_import_batch(db: Session, batch_id: int, reason: str) -> dict:
    _ensure_import_tables(db)
    batch = db.execute(text("""
        SELECT id, status, updated_at
        FROM data_import_batch
        WHERE id=:id
    """), {"id": batch_id}).mappings().first()
    if not batch:
        return {"ok": False, "message": f"batch not found: {batch_id}"}

    job = _latest_job_for_batch(db, batch_id)
    job_id = int(job["id"]) if job and job.get("id") else 0
    message = (reason or "用户取消/废弃")[:1000]

    queue_params = {
        "batch_id": str(batch_id),
        "job_id": str(job_id),
    }
    queue_result = db.execute(text("""
        UPDATE job_queue
        SET status='cancelled',
            finished_at=NOW(),
            updated_at=NOW()
        WHERE status IN ('pending','queued')
          AND (
            JSON_UNQUOTE(JSON_EXTRACT(payload, '$.import_batch_id'))=:batch_id
            OR (:job_id <> '0' AND JSON_UNQUOTE(JSON_EXTRACT(payload, '$.job_execution_id'))=:job_id)
          )
    """), queue_params)

    job_rows = 0
    if job_id:
        job_status = str(job.get("status") or "").lower()
        if job_status in ("queued", "pending"):
            result = db.execute(text("""
                UPDATE job_execution
                SET status='cancelled',
                    message=:message,
                    cancel_requested_at=NOW(),
                    finished_at=NOW(),
                    updated_at=NOW()
                WHERE id=:id
            """), {"id": job_id, "message": message})
        elif job_status == "running":
            result = db.execute(text("""
                UPDATE job_execution
                SET status=CASE
                        WHEN updated_at < DATE_SUB(NOW(), INTERVAL 5 MINUTE) THEN 'cancelled'
                        ELSE status
                    END,
                    cancel_requested_at=NOW(),
                    message=:message,
                    finished_at=CASE
                        WHEN updated_at < DATE_SUB(NOW(), INTERVAL 5 MINUTE) THEN NOW()
                        ELSE finished_at
                    END,
                    updated_at=NOW()
                WHERE id=:id
            """), {"id": job_id, "message": "cancel requested: " + message})
        else:
            result = None
        job_rows = int(result.rowcount) if result is not None else 0

    batch_status = str(batch.get("status") or "").lower()
    if batch_status in ("queued", "pending"):
        target_status = "cancelled"
        finished_sql = "finished_at=NOW(),"
    elif batch_status == "running":
        stale = bool(job and job.get("updated_at") and job["updated_at"] < db.execute(text("SELECT DATE_SUB(NOW(), INTERVAL 5 MINUTE)")).scalar())
        target_status = "cancelled" if stale else "cancelling"
        finished_sql = "finished_at=NOW()," if stale else ""
    else:
        target_status = batch_status or "cancelled"
        finished_sql = ""

    batch_result = db.execute(text(f"""
        UPDATE data_import_batch
        SET status=:status,
            message=:message,
            {finished_sql}
            updated_at=NOW()
        WHERE id=:id
          AND status NOT IN ('success','failed','cancelled')
    """), {"id": batch_id, "status": target_status, "message": message})
    db.commit()

    return {
        "ok": True,
        "batch_id": batch_id,
        "job_id": job_id or None,
        "status": target_status,
        "cancelled_queue_rows": int(queue_result.rowcount or 0),
        "updated_job_rows": job_rows,
        "updated_batch_rows": int(batch_result.rowcount or 0),
        "message": message,
    }


def _create_batch_and_files(db: Session, payload: ImportRunRequest, files: list[str]) -> tuple[int, dict[str, int]]:
    _ensure_import_tables(db)
    res = db.execute(text("""
        INSERT INTO data_import_batch
        (import_type, source_dir, market, status, total_files, success_files, failed_files, total_rows, started_at, message)
        VALUES (:import_type, :source_dir, :market, 'queued', :total_files, 0, 0, 0, NOW(), :message)
    """), {
        "import_type": payload.import_type,
        "source_dir": payload.source_dir,
        "market": payload.market,
        "total_files": len(files),
        "message": f"import started, workers={payload.workers}",
    })
    batch_id = int(res.lastrowid)
    id_map: dict[str, int] = {}
    for f in files:
        r = db.execute(text("""
            INSERT INTO data_import_file
            (import_batch_id, file_path, market, status, rows_imported, started_at, updated_at)
            VALUES (:batch_id, :file_path, :market, 'pending', 0, NOW(), NOW())
        """), {"batch_id": batch_id, "file_path": f, "market": payload.market})
        id_map[f] = int(r.lastrowid)
    db.commit()
    return batch_id, id_map


def _batch_detail(db: Session, batch_id: int) -> dict | None:
    batch = db.execute(text("""
        SELECT id, import_type, source_dir, market, status, total_files, success_files, failed_files,
               total_rows, started_at, finished_at, message, updated_at
        FROM data_import_batch
        WHERE id=:id
    """), {"id": batch_id}).mappings().first()
    if not batch:
        return None
    stats = db.execute(text("""
        SELECT
            SUM(status='pending') AS pending_files,
            SUM(status='running') AS running_files,
            SUM(status='success') AS success_files_actual,
            SUM(status='failed') AS failed_files_actual
        FROM data_import_file
        WHERE import_batch_id=:id
    """), {"id": batch_id}).mappings().first() or {}
    d = _merge_job_progress(dict(batch), _latest_job_for_batch(db, batch_id))
    d = _merge_data_range(d, _date_range_for_batch(db, d))
    d.update({
        "pending_files": int(stats.get("pending_files") or 0),
        "running_files": int(stats.get("running_files") or 0),
        "success_files_actual": int(stats.get("success_files_actual") or 0),
        "failed_files_actual": int(stats.get("failed_files_actual") or 0),
    })
    return d


@router.post("/scan")
def scan_import(payload: ImportScanRequest):
    data = scan_vipdoc_files(payload.source_dir, payload.market, payload.import_type)
    return {
        "ok": True,
        "source_dir": data["source_dir"],
        "market": data["market"],
        "import_type": data["import_type"],
        "scan_dirs": data["scan_dirs"],
        "total_files": data["total_files"],
        "file_data_start": data.get("file_data_start"),
        "file_data_end": data.get("file_data_end"),
        "file_data_range": data.get("file_data_range"),
        "files_sample": data["files"][:100],
    }


def _active_import_for_market(db: Session, market: str) -> dict | None:
    """Check if there's already an active import_vipdoc for this market."""
    # 1. Check job_queue for pending/running jobs
    if _table_exists(db, "job_queue"):
        row = db.execute(text("""
            SELECT id, status, job_type, payload,
                   NULL AS batch_id, NULL AS exec_id
            FROM job_queue
            WHERE job_type = 'import_vipdoc'
              AND status IN ('pending','queued','running')
              AND JSON_UNQUOTE(JSON_EXTRACT(payload, '$.market')) = :market
            ORDER BY id ASC
            LIMIT 1
        """), {"market": market}).mappings().first()
        if row:
            return dict(row)

    # 2. Check job_execution for running/queued executions
    if _table_exists(db, "job_execution"):
        row2 = db.execute(text("""
            SELECT id AS exec_id, job_type, status, batch_id,
                   NULL AS id, NULL AS payload
            FROM job_execution
            WHERE job_type = 'import_vipdoc'
              AND market = :market
              AND status IN ('queued','pending','running','cancelling')
            ORDER BY id DESC
            LIMIT 1
        """), {"market": market}).mappings().first()
        if row2:
            return dict(row2)

    # 3. Check data_import_batch for active batches (belt-and-suspenders)
    if _table_exists(db, "data_import_batch"):
        row3 = db.execute(text("""
            SELECT id, status, market, message, started_at
            FROM data_import_batch
            WHERE status IN ('queued','pending','running','cancelling')
              AND market = :market
            ORDER BY id DESC
            LIMIT 1
        """), {"market": market}).mappings().first()
        if row3:
            return dict(row3)

    return None


MARKET_LANES = ["sh60", "sh68", "sz00", "sz30"]

MARKET_LABELS = {
    "sh60": "sh60 沪主板",
    "sh68": "sh68 科创板",
    "sz00": "sz00 深主板",
    "sz30": "sz30 创业板",
}


def _enqueue_single_import(db, payload: ImportRunRequest, market: str, files: list[str], workers: int) -> dict:
    """Create one batch + one job for a single market import."""
    _ensure_import_tables(db)
    batch_id, id_map = _create_batch_and_files(db, payload, files)
    job_id = create_job_execution(
        db,
        "import_vipdoc",
        market=market,
        shards=workers,
        batch_id=str(batch_id),
        total=len(files),
        message=f"queued import batch={batch_id}",
        status="queued",
    )
    enqueue_job(db, "import_vipdoc", "S2560", 3, {
        "job_execution_id": job_id,
        "import_batch_id": batch_id,
        "source_dir": payload.source_dir,
        "market": market,
        "import_type": payload.import_type,
        "start": payload.start,
        "end": payload.end,
        "workers": workers,
    })
    return {
        "import_batch_id": batch_id,
        "job_id": job_id,
        "market": market,
        "total_files": len(files),
        "progress_url": f"/api/jobs/executions/{job_id}/progress",
    }


@router.post("/run")
def run_import(payload: ImportRunRequest, db: Session = Depends(get_db)):
    if not os.path.isdir(payload.source_dir):
        raise HTTPException(
            status_code=400,
            detail=f"源目录不存在: {payload.source_dir}，请先确认 VIPDOC 路径"
        )
    _ensure_import_tables(db)

    # ── market=all: split into 4 lane-specific jobs ──
    if payload.market.lower() == "all":
        jobs = []
        for lane in MARKET_LANES:
            # Check for active import on this lane
            active = _active_import_for_market(db, lane)
            if active:
                jobs.append({
                    "market": lane,
                    "skipped": True,
                    "reason": f"active import already exists: queue #{active['id']} status={active['status']}",
                })
                continue

            scan = scan_vipdoc_files(payload.source_dir, lane, payload.import_type)
            files = scan["files"]
            if not files:
                jobs.append({"market": lane, "skipped": True, "reason": "no files found"})
                continue
            if payload.limit_files:
                files = files[:payload.limit_files]

            job_info = _enqueue_single_import(db, payload, lane, files, payload.workers)
            job_info["scan_dirs"] = scan["scan_dirs"]
            jobs.append(job_info)

        return {"ok": True, "lanes": jobs, "message": "import jobs queued"}

    # ── single market: check for active import ──
    active = _active_import_for_market(db, payload.market)
    if active:
        return {
            "ok": False,
            "duplicate": True,
            "reason": f"active import already exists for {payload.market}: queue #{active['id']}",
            "existing_queue_id": active["id"],
            "existing_status": active["status"],
        }

    scan = scan_vipdoc_files(payload.source_dir, payload.market, payload.import_type)
    files = scan["files"]
    if not files:
        raise HTTPException(
            status_code=400,
            detail=f"源目录中无可用文件: {payload.source_dir}"
        )
    if payload.limit_files:
        files = files[:payload.limit_files]

    job_info = _enqueue_single_import(db, payload, payload.market, files, payload.workers)
    return {
        "ok": True,
        **job_info,
        "scan_dirs": scan["scan_dirs"],
        "message": "import job queued",
    }


@router.post("/build-30m")
def build_30m(payload: Build30mRequest, db: Session = Depends(get_db)):
    _ensure_import_tables(db)

    # ── market=all: split into 4 lane-specific jobs ──
    if payload.market.lower() == "all":
        jobs = []
        for lane in MARKET_LANES:
            range_key = f"%start={payload.start};end={payload.end or ''}%"
            existing = db.execute(text("""
                SELECT b.id, b.status, b.message, b.started_at, b.updated_at, e.id AS job_id
                FROM data_import_batch b
                LEFT JOIN job_execution e ON e.batch_id = CAST(b.id AS CHAR) AND e.job_type='build_30m'
                WHERE b.import_type='build_30m'
                  AND b.market=:market
                  AND b.status IN ('queued','pending','running','cancelling')
                  AND b.message LIKE :range_key
                ORDER BY b.id DESC
                LIMIT 1
            """), {
                "market": lane,
                "range_key": range_key,
            }).mappings().first()
            if existing:
                jobs.append({
                    "market": lane,
                    "skipped": True,
                    "reason": "same build_30m job already queued/running",
                    "import_batch_id": existing["id"],
                    "job_id": existing["job_id"],
                    "status": existing["status"],
                })
                continue
            job_info = _enqueue_single_build30m(db, payload, lane)
            jobs.append({"market": lane, **job_info, "skipped": False})
        return {"ok": True, "lanes": jobs, "message": "build_30m jobs queued"}

    # ── single market ──
    existing = db.execute(text("""
        SELECT b.id, b.status, b.message, b.started_at, b.updated_at, e.id AS job_id
        FROM data_import_batch b
        LEFT JOIN job_execution e ON e.batch_id = CAST(b.id AS CHAR) AND e.job_type='build_30m'
        WHERE b.import_type='build_30m'
          AND b.market=:market
          AND b.status IN ('queued','pending','running','cancelling')
          AND b.message LIKE :range_key
        ORDER BY b.id DESC
        LIMIT 1
    """), {
        "market": payload.market,
        "range_key": f"%start={payload.start};end={payload.end or ''}%",
    }).mappings().first()
    if existing:
        return {
            "ok": False,
            "duplicate": True,
            "import_batch_id": existing["id"],
            "job_id": existing["job_id"],
            "status": existing["status"],
            "message": "same build_30m job already queued/running",
        }
    job_info = _enqueue_single_build30m(db, payload, payload.market)
    return {
        "ok": True,
        **job_info,
        "message": "build_30m job queued",
    }


def _enqueue_single_build30m(db, payload: Build30mRequest, market: str) -> dict:
    """Create one batch + one job for a single market build_30m."""
    _ensure_import_tables(db)
    range_key = f"start={payload.start};end={payload.end or ''}"
    res = db.execute(text("""
        INSERT INTO data_import_batch
        (import_type, source_dir, market, status, total_files, started_at, message)
        VALUES ('build_30m', 'minute_kline_period:5m', :market, 'queued', 0, NOW(), :message)
    """), {"market": market, "message": f"build 30m started, workers={payload.workers}, {range_key}"})
    batch_id = int(res.lastrowid)
    job_id = create_job_execution(
        db,
        "build_30m",
        market=market,
        shards=payload.workers,
        batch_id=str(batch_id),
        total=0,
        message=f"queued build_30m batch={batch_id}",
        status="queued",
    )
    enqueue_job(db, "build_30m", "S2560", 3, {
        "job_execution_id": job_id,
        "import_batch_id": batch_id,
        "start": payload.start,
        "end": payload.end,
        "market": market,
        "workers": payload.workers,
        "limit_codes": payload.limit_codes,
        "dry_run": payload.dry_run,
    })
    return {
        "import_batch_id": batch_id,
        "job_id": job_id,
        "market": market,
        "status": "queued",
        "progress_url": f"/api/jobs/executions/{job_id}/progress",
    }


@router.post("/rebuild-indicators")
def rebuild_indicators(payload: RebuildIndicatorRequest, db: Session = Depends(get_db)):
    _ensure_import_tables(db)
    range_key = f"start={payload.start};end={payload.end};periods={payload.periods}"
    existing = db.execute(text("""
        SELECT b.id, b.status, b.message, b.started_at, b.updated_at, e.id AS job_id
        FROM data_import_batch b
        LEFT JOIN job_execution e ON e.batch_id = CAST(b.id AS CHAR) AND e.job_type='rebuild_indicator'
        WHERE b.import_type='rebuild_indicator'
          AND b.market=:market
          AND b.status IN ('queued','pending','running','cancelling')
          AND b.message LIKE :range_key
        ORDER BY b.id DESC
        LIMIT 1
    """), {"market": payload.market, "range_key": f"%{range_key}%"}).mappings().first()
    if existing:
        return {
            "ok": False,
            "duplicate": True,
            "import_batch_id": existing["id"],
            "job_id": existing["job_id"],
            "status": existing["status"],
            "message": "same rebuild_indicator job already queued/running",
        }

    res = db.execute(text("""
        INSERT INTO data_import_batch
        (import_type, source_dir, market, status, total_files, started_at, message)
        VALUES ('rebuild_indicator', 'technical_indicator', :market, 'queued', 0, NOW(), :message)
    """), {"market": payload.market, "message": f"rebuild indicators queued, {range_key}"})
    batch_id = int(res.lastrowid)
    job_id = create_job_execution(
        db,
        "rebuild_indicator",
        market=payload.market,
        shards=1,
        batch_id=str(batch_id),
        total=0,
        message=f"queued rebuild_indicator batch={batch_id}",
        status="queued",
    )
    enqueue_job(db, "rebuild_indicator", "S2560", 3, {
        "job_execution_id": job_id,
        "import_batch_id": batch_id,
        "start": payload.start,
        "end": payload.end,
        "market": payload.market,
        "periods": payload.periods,
        "limit_codes": payload.limit_codes,
        "commit_every": payload.commit_every,
    })
    return {
        "ok": True,
        "import_batch_id": batch_id,
        "job_id": job_id,
        "status": "queued",
        "message": "rebuild_indicator job queued",
        "progress_url": f"/api/jobs/executions/{job_id}/progress",
    }


@router.get("/batches")
def import_batches(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    if not _table_exists(db, "data_import_batch"):
        return []
    rows = db.execute(text("""
        SELECT id, import_type, source_dir, market, status, total_files, success_files, failed_files,
               total_rows, started_at, finished_at, message, updated_at
        FROM data_import_batch
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).mappings().all()
    out = []
    for r in rows:
        d = _merge_job_progress(dict(r), _latest_job_for_batch(db, int(r["id"])))
        out.append(_merge_data_range(d, _date_range_for_batch(db, d)))
    return out


@router.get("/batches/{batch_id}")
def import_batch_detail(batch_id: int, db: Session = Depends(get_db)):
    if not _table_exists(db, "data_import_batch"):
        return None
    return _batch_detail(db, batch_id)


@router.post("/batches/{batch_id}/cancel")
def cancel_import_batch(batch_id: int, payload: CancelBatchRequest | None = None, db: Session = Depends(get_db)):
    reason = payload.reason if payload else "用户取消/废弃"
    return _cancel_import_batch(db, batch_id, reason)


@router.post("/batches/{batch_id}/redis-cleanup")
def cleanup_batch_redis_keys(batch_id: int, db: Session = Depends(get_db)):
    """Delete leftover Redis keys for a batch (flush failure recovery)."""
    from app.core.redis_client import get_redis_client

    rc = get_redis_client()
    if not rc:
        raise HTTPException(status_code=503, detail="Redis not available")

    daily_key = f"import:{batch_id}:daily"
    minute_key = f"import:{batch_id}:minute"
    deleted = 0
    for key in (daily_key, minute_key):
        if rc.exists(key):
            rc.delete(key)
            deleted += 1

    return {
        "ok": True,
        "batch_id": batch_id,
        "deleted_keys": deleted,
        "keys": [daily_key, minute_key],
    }


@router.get("/files")
def import_files(limit: int = Query(100, ge=1, le=1000), batch_id: Optional[int] = None, db: Session = Depends(get_db)):
    if not _table_exists(db, "data_import_file"):
        return []
    if batch_id:
        return db.execute(text("""
            SELECT id, import_batch_id, file_path, market, status, rows_imported, last_error,
                   started_at, finished_at, updated_at
            FROM data_import_file
            WHERE import_batch_id=:batch_id
            ORDER BY id DESC
            LIMIT :limit
        """), {"batch_id": batch_id, "limit": limit}).mappings().all()
    return db.execute(text("""
        SELECT id, import_batch_id, file_path, market, status, rows_imported, last_error,
               started_at, finished_at, updated_at
        FROM data_import_file
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).mappings().all()


# ── ClickHouse-only import (no MySQL dependency) ─────────────────

@router.get("/latest")
def latest_active_imports(db: Session = Depends(get_db)):
    """返回所有活跃（running/queued/pending/cancelling）的导入批次；
    若无活跃批次，则返回最近已完成的一批（用于页面重载后展示最终状态）。"""
    if not _table_exists(db, "data_import_batch"):
        return {"lanes": []}

    batches = db.execute(text("""
        SELECT id, import_type, market, status, total_files, success_files, failed_files,
               total_rows, started_at, finished_at, message, updated_at
        FROM data_import_batch
        WHERE status IN ('queued', 'pending', 'running', 'cancelling')
          AND import_type IN ('vipdoc', 'lday', 'all')
        ORDER BY id DESC
    """)).mappings().all()

    # Fallback: if no active batches, get most recent completed ones
    if not batches:
        batches = db.execute(text("""
            SELECT id, import_type, market, status, total_files, success_files, failed_files,
                   total_rows, started_at, finished_at, message, updated_at
            FROM data_import_batch
            WHERE status IN ('success', 'failed')
              AND import_type IN ('vipdoc', 'lday', 'all')
            ORDER BY id DESC
            LIMIT 4
        """)).mappings().all()

    lanes = []
    for batch in batches:
        b = dict(batch)
        batch_id = int(b["id"])
        market = str(b.get("market") or "")
        job = _latest_job_for_batch(db, batch_id)

        lane = {
            "import_batch_id": batch_id,
            "job_id": int(job["id"]) if job and job.get("id") else None,
            "market": market,
            "market_label": MARKET_LABELS.get(market, market),
            "status": b["status"],
            "total_files": int(b.get("total_files") or 0),
            "success_files": int(b.get("success_files") or 0),
            "failed_files": int(b.get("failed_files") or 0),
            "total_rows": int(b.get("total_rows") or 0),
            "progress_url": f"/api/jobs/executions/{int(job['id'])}/progress" if job and job.get("id") else None,
            "started_at": b.get("started_at"),
            "updated_at": b.get("updated_at"),
        }
        lanes.append(lane)

    return {"lanes": lanes}


@router.get("/ch/status")
def ch_status():
    """ClickHouse connection status."""
    return {"url": _CH_URL, "ping": _ch_ping()}


@router.get("/ch/tables")
def ch_tables():
    """List tables in strategy2560 database."""
    try:
        from app.db.clickhouse import get_clickhouse
        ch = get_clickhouse()
        result = ch.query("SHOW TABLES")
        return [r.get("name") for r in result]
    except Exception as e:
        return {"error": str(e)}


@router.post("/ch/import")
def ch_import(
    source_dir: str = Query(default=DEFAULT_VIPDOC_ROOT),
    market: str = Query(default="sh60"),
    import_type: str = Query(default="all"),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    workers: int = Query(default=4, ge=1, le=128),
    dry_run: bool = Query(default=False),
):
    """Import vipdoc data into ClickHouse (no MySQL required)."""
    if not _ch_ping():
        raise HTTPException(status_code=503, detail="ClickHouse not reachable")

    scan = scan_vipdoc_files(source_dir, market, import_type)

    if dry_run:
        return {
            "dry_run": True,
            "market": market,
            "total_files": scan["total_files"],
            "scan_dirs": scan["scan_dirs"],
            "file_data_range": scan.get("file_data_range"),
        }

    # Filter files by type
    lday_files = [f for f in scan["files"] if f.endswith(".day")]
    lc5_files = [f for f in scan["files"] if f.endswith(".lc5")]

    if import_type in ("lday", "daily"):
        lc5_files = []
    elif import_type in ("5m", "lc5", "fzline"):
        lday_files = []

    import concurrent.futures
    import time

    t0 = time.time()
    total_rows = 0
    ok_count = 0
    fail_count = 0
    failed_files = []

    all_files = lday_files + lc5_files

    def do_import(filepath: str) -> dict:
        if filepath.endswith(".day"):
            return import_daily_clickhouse(filepath, market, start, end)
        else:
            return import_5m_clickhouse(filepath, market, start, end)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(do_import, f): f for f in all_files}
        for fut in concurrent.futures.as_completed(futures):
            result = fut.result()
            if result["ok"]:
                total_rows += result["rows"]
                ok_count += 1
            else:
                fail_count += 1
                failed_files.append({
                    "file": result.get("file", ""),
                    "error": str(result.get("error", ""))[:200],
                })

    elapsed = time.time() - t0
    return {
        "ok": True,
        "market": market,
        "total_files": len(all_files),
        "success": ok_count,
        "failed": fail_count,
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 1),
        "rows_per_second": round(total_rows / elapsed, 0) if elapsed > 0 else 0,
        "failed_files": failed_files[:20],
    }

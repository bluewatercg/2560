from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.job_orchestrator import create_job_execution, enqueue_job, ensure_job_tables
from scripts.import_vipdoc_with_pytdx import scan_vipdoc_files

router = APIRouter(prefix="/api/import", tags=["import"])
DEFAULT_VIPDOC_ROOT = os.getenv("VIPDOC_ROOT", "/data/vipdoc")


class ImportScanRequest(BaseModel):
    source_dir: str = Field(default=DEFAULT_VIPDOC_ROOT)
    market: str = Field(default="sh")
    import_type: str = Field(default="all")


class ImportRunRequest(BaseModel):
    source_dir: str = Field(default=DEFAULT_VIPDOC_ROOT)
    market: str = Field(default="sh")
    import_type: str = Field(default="lday")
    start: Optional[str] = None
    end: Optional[str] = None
    workers: int = Field(default=4, ge=1, le=64)
    limit_files: Optional[int] = None


class Build30mRequest(BaseModel):
    start: str
    end: Optional[str] = None
    market: str = Field(default="all")
    workers: int = Field(default=4, ge=1, le=64)
    limit_codes: Optional[int] = None
    dry_run: bool = False


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
            "progress_url": f"/api/jobs/executions/{job_id}/progress",
            "job_status": job.get("status"),
            "job_progress_current": current,
            "job_progress_total": job_total,
            "job_success_count": int(job.get("success_count") or 0),
            "job_failed_count": int(job.get("failed_count") or 0),
            "workers": int(job.get("shards") or 0),
            "current_code": job.get("current_code"),
            "done_files": current,
            "progress_percent": round(current * 100 / job_total, 2) if job_total else 0.0,
        })
    else:
        d.update({
            "job_id": None,
            "progress_url": None,
            "job_status": None,
            "job_progress_current": None,
            "job_progress_total": None,
            "job_success_count": None,
            "job_failed_count": None,
            "workers": None,
            "current_code": None,
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
        SELECT id, job_type, status, progress_current, progress_total,
               success_count, failed_count, current_code, market, shards,
               message, started_at, finished_at, updated_at
        FROM job_execution
        WHERE batch_id = CAST(:batch_id AS CHAR)
          AND job_type IN ('import_vipdoc', 'build_30m')
        ORDER BY id DESC
        LIMIT 1
    """), {"batch_id": batch_id}).mappings().first()
    return dict(row) if row else None


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
        "files_sample": data["files"][:100],
    }


@router.post("/run")
def run_import(payload: ImportRunRequest, db: Session = Depends(get_db)):
    scan = scan_vipdoc_files(payload.source_dir, payload.market, payload.import_type)
    files = scan["files"]
    if payload.limit_files:
        files = files[:payload.limit_files]
    _ensure_import_tables(db)
    batch_id, id_map = _create_batch_and_files(db, payload, files)
    job_id = create_job_execution(
        db,
        "import_vipdoc",
        market=payload.market,
        shards=payload.workers,
        batch_id=str(batch_id),
        total=len(files),
        message=f"queued import batch={batch_id}",
        status="queued",
    )
    enqueue_job(db, "import_vipdoc", "S2560", 3, {
        "job_execution_id": job_id,
        "import_batch_id": batch_id,
        "source_dir": payload.source_dir,
        "market": payload.market,
        "import_type": payload.import_type,
        "start": payload.start,
        "end": payload.end,
        "workers": payload.workers,
    })
    db.execute(text("""
        UPDATE data_import_batch
        SET status='queued', message=:message, updated_at=NOW()
        WHERE id=:id
    """), {"id": batch_id, "message": f"queued import job #{job_id}"})
    db.commit()
    return {
        "ok": True,
        "import_batch_id": batch_id,
        "job_id": job_id,
        "status": "queued",
        "scan_dirs": scan["scan_dirs"],
        "total_files": len(files),
        "message": "import job queued",
        "progress_url": f"/api/jobs/executions/{job_id}/progress",
    }


@router.post("/build-30m")
def build_30m(payload: Build30mRequest, db: Session = Depends(get_db)):
    _ensure_import_tables(db)
    res = db.execute(text("""
        INSERT INTO data_import_batch
        (import_type, source_dir, market, status, total_files, started_at, message)
        VALUES ('build_30m', 'minute_kline_period:5m', :market, 'queued', 0, NOW(), :message)
    """), {"market": payload.market, "message": f"build 30m started, workers={payload.workers}"})
    batch_id = int(res.lastrowid)
    job_id = create_job_execution(
        db,
        "build_30m",
        market=payload.market,
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
        "market": payload.market,
        "workers": payload.workers,
        "limit_codes": payload.limit_codes,
        "dry_run": payload.dry_run,
    })
    db.execute(text("""
        UPDATE data_import_batch
        SET status='queued', message=:message, updated_at=NOW()
        WHERE id=:id
    """), {"id": batch_id, "message": f"queued build_30m job #{job_id}"})
    db.commit()
    return {
        "ok": True,
        "import_batch_id": batch_id,
        "job_id": job_id,
        "status": "queued",
        "message": "build_30m job queued",
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

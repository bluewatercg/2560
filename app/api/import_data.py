from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from scripts.import_vipdoc_with_pytdx import scan_vipdoc_files, import_vipdoc_files_parallel
from scripts.build_30m_from_5m import build_30m_parallel

router = APIRouter(prefix="/api/import", tags=["import"])


class ImportScanRequest(BaseModel):
    source_dir: str = Field(default="/data/vipdoc")
    market: str = Field(default="sh")
    import_type: str = Field(default="all")


class ImportRunRequest(BaseModel):
    source_dir: str = Field(default="/data/vipdoc")
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
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS data_import_batch (
          id BIGINT PRIMARY KEY AUTO_INCREMENT,
          import_type VARCHAR(50) NOT NULL DEFAULT 'vipdoc',
          source_dir VARCHAR(500) NULL,
          market VARCHAR(20) NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'running',
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


def _create_batch_and_files(db: Session, payload: ImportRunRequest, files: list[str]) -> tuple[int, dict[str, int]]:
    _ensure_import_tables(db)
    res = db.execute(text("""
        INSERT INTO data_import_batch
        (import_type, source_dir, market, status, total_files, success_files, failed_files, total_rows, started_at, message)
        VALUES (:import_type, :source_dir, :market, 'running', :total_files, 0, 0, 0, NOW(), :message)
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
    batch_id, id_map = _create_batch_and_files(db, payload, files)
    result = import_vipdoc_files_parallel(files, payload.market, payload.import_type, payload.start, payload.end, payload.workers, id_map)
    status = "success" if result["failed_files"] == 0 else "failed"
    db.execute(text("""
        UPDATE data_import_batch
        SET status=:status, success_files=:success_files, failed_files=:failed_files, total_rows=:total_rows,
            finished_at=NOW(), message=:message, updated_at=NOW()
        WHERE id=:id
    """), {
        "id": batch_id,
        "status": status,
        "success_files": result["success_files"],
        "failed_files": result["failed_files"],
        "total_rows": result["total_rows"],
        "message": f"finished import_type={payload.import_type}, workers={payload.workers}",
    })
    db.commit()
    return {"ok": status == "success", "import_batch_id": batch_id, "scan_dirs": scan["scan_dirs"], **{k:v for k,v in result.items() if k != "results"}, "results_sample": result["results"][:20]}


@router.post("/build-30m")
def build_30m(payload: Build30mRequest, db: Session = Depends(get_db)):
    _ensure_import_tables(db)
    res = db.execute(text("""
        INSERT INTO data_import_batch
        (import_type, source_dir, market, status, total_files, started_at, message)
        VALUES ('build_30m', 'minute_kline_period:5m', :market, 'running', 0, NOW(), :message)
    """), {"market": payload.market, "message": f"build 30m started, workers={payload.workers}"})
    batch_id = int(res.lastrowid)
    db.commit()
    result = build_30m_parallel(payload.start, payload.end, payload.market, payload.workers, payload.limit_codes, payload.dry_run)
    status = "success" if result.get("ok") else "failed"
    db.execute(text("""
        UPDATE data_import_batch
        SET status=:status, total_files=:codes, success_files=:codes, total_rows=:rows,
            finished_at=NOW(), message=:message, updated_at=NOW()
        WHERE id=:id
    """), {"id": batch_id, "status": status, "codes": result["codes"], "rows": result["inserted_30m_rows"], "message": "finished build_30m"})
    db.commit()
    return {"ok": result.get("ok"), "import_batch_id": batch_id, **result}


@router.get("/batches")
def import_batches(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    if not _table_exists(db, "data_import_batch"):
        return []
    return db.execute(text("""
        SELECT id, import_type, source_dir, market, status, total_files, success_files, failed_files,
               total_rows, started_at, finished_at, message, updated_at
        FROM data_import_batch
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).mappings().all()


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

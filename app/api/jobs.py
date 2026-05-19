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
from sqlalchemy.sql import bindparam

from app.core.market_scope import market_sql_where
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
    market: str = Field(default="sh60")
    shards: int = Field(default=4, ge=1, le=32)


class CancelJobRequest(BaseModel):
    reason: str = Field(default="用户取消/废弃")


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
    return market_sql_where(f"{alias}.code", market)


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


def _execution_job_type_filter(job_types: list[str | None] | None) -> tuple[str, dict[str, tuple[str, ...]]]:
    clean = tuple(str(t).strip() for t in (job_types or []) if t and str(t).strip())
    if not clean:
        return "", {}
    return "WHERE job_type IN :job_types", {"job_types": clean}


def _queue_job_type_filter(job_types: list[str | None] | None) -> tuple[str, dict[str, tuple[str, ...]]]:
    return _execution_job_type_filter(job_types)


def _execution_order_sql() -> str:
    return "CASE status WHEN 'running' THEN 0 WHEN 'cancelling' THEN 1 WHEN 'queued' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END"


def _queue_order_sql() -> str:
    return "CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'pending' THEN 1 ELSE 2 END, created_at DESC, id DESC"


def _cancel_job_execution(db: Session, job_id: int, reason: str) -> dict[str, Any]:
    _ensure_tables(db)
    row = db.execute(text("""
        SELECT id, status, pid, updated_at
        FROM job_execution
        WHERE id=:id
    """), {"id": job_id}).mappings().first()
    if not row:
        return {"ok": False, "message": f"job not found: {job_id}"}

    status = str(row.get("status") or "").lower()
    message = (reason or "用户取消/废弃")[:1000]
    queue_result = db.execute(text("""
        UPDATE job_queue
        SET status='cancelled',
            finished_at=NOW(),
            updated_at=NOW()
        WHERE status IN ('pending','queued')
          AND JSON_UNQUOTE(JSON_EXTRACT(payload, '$.job_execution_id'))=:job_id
    """), {"job_id": str(job_id)})

    if status in ("queued", "pending"):
        db.execute(text("""
            UPDATE job_execution
            SET status='cancelled',
                message=:message,
                cancel_requested_at=NOW(),
                finished_at=NOW(),
                updated_at=NOW()
            WHERE id=:id
        """), {"id": job_id, "message": message})
        db.commit()
        return {"ok": True, "job_id": job_id, "status": "cancelled", "cancelled_queue_rows": int(queue_result.rowcount or 0)}

    if status == "running":
        stale_cutoff = db.execute(text("SELECT DATE_SUB(NOW(), INTERVAL 5 MINUTE)")).scalar()
        stale = bool(row.get("updated_at") and row["updated_at"] < stale_cutoff)
        db.execute(text("""
            UPDATE job_execution
            SET status=:status,
                cancel_requested_at=NOW(),
                message=:message,
                finished_at=CASE WHEN :status='cancelled' THEN NOW() ELSE finished_at END,
                updated_at=NOW()
            WHERE id=:id
        """), {"id": job_id, "status": "cancelled" if stale else "running", "message": "cancel requested: " + message})
        db.commit()
        return {"ok": True, "job_id": job_id, "status": "cancelled" if stale else "cancelling", "cancelled_queue_rows": int(queue_result.rowcount or 0)}

    db.commit()
    return {"ok": True, "job_id": job_id, "status": status, "message": "job is already finished"}


@router.get("/queue")
def queue(
    limit: int = Query(100, ge=1, le=1000),
    job_type: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if not _table_exists(db, "job_queue"):
        return []
    where_clause, params = _queue_job_type_filter(job_type)
    query = text(f"""
        SELECT id, job_type, strategy_code, priority, payload, status,
               created_at, started_at, finished_at, updated_at
        FROM job_queue
        {where_clause}
        ORDER BY {_queue_order_sql()}
        LIMIT :limit
    """)
    if params:
        query = query.bindparams(bindparam("job_types", expanding=True))
    return (
        db.execute(
            query,
            {"limit": limit, **params},
        )
        .mappings()
        .all()
    )


@router.get("/executions")
def executions(
    limit: int = Query(100, ge=1, le=1000),
    job_type: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if not _table_exists(db, "job_execution"):
        return []
    where_clause, params = _execution_job_type_filter(job_type)
    query = text(f"""
        SELECT id, job_type, batch_id, status,
               progress_current, progress_total, success_count, failed_count,
               current_code, market, shards, pid, log_file, message,
               started_at, finished_at, updated_at
        FROM job_execution
        {where_clause}
        ORDER BY {_execution_order_sql()}, updated_at DESC, started_at DESC, id DESC
        LIMIT :limit
    """)
    if params:
        query = query.bindparams(bindparam("job_types", expanding=True))
    return (
        db.execute(
            query,
            {"limit": limit, **params},
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


@router.post("/executions/{job_id}/cancel")
def cancel_execution(job_id: int, payload: CancelJobRequest | None = None, db: Session = Depends(get_db)):
    reason = payload.reason if payload else "用户取消/废弃"
    return _cancel_job_execution(db, job_id, reason)


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

    Fallback: when job_task_item is empty (import_job_runner.py doesn't populate it),
    use data_import_file status grouped into virtual shards.
    """
    # Try job_task_item first (used by run_2560, build_30m, rebuild_indicator)
    if _table_exists(db, "job_task_item"):
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

        # If we have real task items, return them
        if total_all > 0:
            return {
                "ok": True,
                "job_id": job_id,
                "total": total_all,
                "done": done_all,
                "percent": round(done_all * 100 / total_all, 2) if total_all else 0.0,
                "items": items,
            }

    # Fallback: use data_import_file status (import_job_runner.py doesn't write job_task_item)
    if _table_exists(db, "data_import_batch"):
        # Find the batch_id for this job execution
        exec_row = db.execute(text("""
            SELECT batch_id, shards, progress_current, progress_total, success_count, failed_count
            FROM job_execution WHERE id=:id
        """), {"id": job_id}).mappings().first()

        if exec_row:
            batch_id_str = exec_row.get("batch_id")
            n_shards = int(exec_row.get("shards") or 1)
            prog_current = int(exec_row.get("progress_current") or 0)
            prog_total = int(exec_row.get("progress_total") or 0)
            success_cnt = int(exec_row.get("success_count") or 0)
            failed_cnt = int(exec_row.get("failed_count") or 0)

            try:
                batch_id = int(batch_id_str)
            except (TypeError, ValueError):
                batch_id = 0

            if batch_id:
                # Get actual file status from data_import_file
                file_stats = db.execute(text("""
                    SELECT
                        SUM(status='pending') AS pending_count,
                        SUM(status='running') AS running_count,
                        SUM(status='success') AS success_count,
                        SUM(status='failed') AS failed_count
                    FROM data_import_file
                    WHERE import_batch_id=:id
                """), {"id": batch_id}).mappings().first()

                if file_stats:
                    fs = dict(file_stats)
                    pending = int(fs.get("pending_count") or 0)
                    running = int(fs.get("running_count") or 0)
                    success = int(fs.get("success_count") or 0)
                    failed = int(fs.get("failed_count") or 0)
                    total = pending + running + success + failed
                    done = success + failed

                    if total > 0:
                        # Distribute evenly across virtual shards
                        items = []
                        remaining = total
                        rem_pending = pending
                        rem_running = running
                        rem_success = success
                        rem_failed = failed

                        for s in range(1, n_shards + 1):
                            shard_total = max(1, remaining // (n_shards - s + 1))
                            remaining -= shard_total

                            shard_success = min(rem_success, max(0, shard_total // 2))
                            shard_failed = min(rem_failed, max(0, shard_total // 4))
                            shard_pending = max(0, (shard_total - shard_success - shard_failed) // 2)
                            shard_running = max(0, shard_total - shard_success - shard_failed - shard_pending)

                            rem_success -= shard_success
                            rem_failed -= shard_failed
                            rem_pending -= shard_pending
                            rem_running -= shard_running

                            shard_done = shard_success + shard_failed

                            items.append({
                                "shard_id": s,
                                "total": shard_total,
                                "done": shard_done,
                                "percent": round(shard_done * 100 / shard_total, 2) if shard_total else 0.0,
                                "success_count": shard_success,
                                "failed_count": shard_failed,
                                "running_count": shard_running,
                                "pending_count": shard_pending,
                                "avg_elapsed_ms": None,
                                "current_code": None,
                                "updated_at": None,
                            })

                        return {
                            "ok": True,
                            "job_id": job_id,
                            "total": total,
                            "done": done,
                            "percent": round(done * 100 / total, 2) if total else 0.0,
                            "items": items,
                        }

    return {"ok": True, "job_id": job_id, "total": 0, "done": 0, "percent": 0.0, "items": []}

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


VALID_2560_MARKETS = ["sh60", "sh68", "sz00", "sz30"]


class RunAllMarketsRequest(BaseModel):
    shards: int = Field(default=4, ge=1, le=32)


@router.post("/enqueue")
def enqueue_job(payload: EnqueueJobRequest, db: Session = Depends(get_db)):
    _ensure_tables(db)

    if payload.job_type == "run_2560" and payload.market == "all":
        return {"ok": False, "message": "market=all 不再被支持，请使用“一键运行四类”或选择具体市场（sh60/sh68/sz00/sz30）"}

    # 同 market + 同 job_type 只允许一个 active（running/queued/pending）
    if payload.job_type == "run_2560" and payload.market in VALID_2560_MARKETS:
        existing = db.execute(text("""
            SELECT COUNT(*) FROM job_execution
            WHERE job_type = 'run_2560'
              AND status IN ('running', 'queued', 'pending')
              AND market = :market
        """), {"market": payload.market}).scalar()
        if int(existing or 0) > 0:
            return {"ok": False, "message": f"{payload.market} 已有活跃 2560 任务（running/queued/pending），请勿重复提交"}

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


@router.post("/run-all-markets")
def run_all_markets(payload: RunAllMarketsRequest, db: Session = Depends(get_db)):
    """一次创建 4 个 market 任务（sh60/sh68/sz00/sz30）。"""
    _ensure_tables(db)
    created = []
    skipped = []
    for market in VALID_2560_MARKETS:
        existing = db.execute(text("""
            SELECT COUNT(*) FROM job_execution
            WHERE job_type = 'run_2560'
              AND status IN ('running', 'queued', 'pending')
              AND market = :market
        """), {"market": market}).scalar()
        if int(existing or 0) > 0:
            skipped.append({"market": market, "reason": "已有活跃任务（running/queued/pending）"})
            continue

        job_payload: dict[str, Any] = {"market": market, "shards": payload.shards}
        job_execution_id = create_job_execution(
            db,
            "run_2560",
            market=market,
            shards=payload.shards,
            total=0,
            message="queued",
            status="queued",
        )
        job_payload["job_execution_id"] = job_execution_id
        res = db.execute(
            text("""
            INSERT INTO job_queue (job_type, strategy_code, priority, payload, status, created_at)
            VALUES ('run_2560', 'S2560', 3, CAST(:payload AS JSON), 'pending', NOW())
        """),
            {"payload": json.dumps(job_payload, ensure_ascii=False)},
        )
        db.commit()
        created.append({"ok": True, "job_id": res.lastrowid, "market": market, "execution_id": job_execution_id})

    return {"ok": True, "created": created, "skipped": skipped}


@router.post("/run-now")
def run_now(payload: RunNowRequest, db: Session = Depends(get_db)):
    if payload.market == "all":
        return {"ok": False, "message": "market=all 不再被支持，请使用“一键运行四类”或选择具体市场（sh60/sh68/sz00/sz30）"}
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

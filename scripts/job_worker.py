#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(PROJECT_ROOT / ".env")
STOP = False


def log(msg: str) -> None:
    print(msg, flush=True)


def sig(*_):
    global STOP
    STOP = True


signal.signal(signal.SIGTERM, sig)
signal.signal(signal.SIGINT, sig)


def get_database_url():
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER")
    pwd = os.getenv("DB_PASSWORD", "")
    name = os.getenv("DB_NAME")
    if not host or not user or not name:
        raise RuntimeError("Set DATABASE_URL or DB_HOST/DB_USER/DB_NAME")
    return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{name}?charset=utf8mb4"


def parse_payload(p: Any):
    if isinstance(p, dict):
        return p
    if isinstance(p, (bytes, bytearray)):
        p = p.decode("utf-8", "ignore")
    if isinstance(p, str) and p.strip():
        try:
            return json.loads(p)
        except Exception:
            return {"raw": p}
    return {}


def build_job_command(job_type: str, payload: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    cmd = [sys.executable]
    if job_type == "import_vipdoc":
        cmd.append(str(PROJECT_ROOT / "scripts" / "import_job_runner.py"))
        cmd.extend(["--job-id", str(payload.get("job_execution_id", 0))])
        cmd.extend(["--batch-id", str(payload.get("import_batch_id", 0))])
        if payload.get("source_dir"):
            cmd.extend(["--source-dir", str(payload["source_dir"])])
        if payload.get("market"):
            cmd.extend(["--market", str(payload["market"])])
        if payload.get("import_type"):
            cmd.extend(["--import-type", str(payload["import_type"])])
        if payload.get("workers") is not None:
            cmd.extend(["--workers", str(payload["workers"])])
        if payload.get("start"):
            cmd.extend(["--start", str(payload["start"])])
        if payload.get("end"):
            cmd.extend(["--end", str(payload["end"])])
        return cmd, env
    if job_type == "build_30m":
        cmd.append(str(PROJECT_ROOT / "scripts" / "build_30m_job_runner.py"))
        cmd.extend(["--job-id", str(payload.get("job_execution_id", 0))])
        cmd.extend(["--batch-id", str(payload.get("import_batch_id", 0))])
        if payload.get("market"):
            cmd.extend(["--market", str(payload["market"])])
        if payload.get("workers") is not None:
            cmd.extend(["--workers", str(payload["workers"])])
        if payload.get("start"):
            cmd.extend(["--start", str(payload["start"])])
        if payload.get("end"):
            cmd.extend(["--end", str(payload["end"])])
        if payload.get("limit_codes") is not None:
            cmd.extend(["--limit-codes", str(payload["limit_codes"])])
        if payload.get("dry_run"):
            cmd.append("--dry-run")
        return cmd, env
    if job_type == "run_2560":
        env["MARKET"] = str(payload.get("market", "all"))
        env["SHARDS"] = str(payload.get("shards", 4))
        if payload.get("job_execution_id"):
            env["JOB_ID"] = str(payload["job_execution_id"])
        if payload.get("limit_codes") is not None:
            env["LIMIT_CODES"] = str(payload["limit_codes"])
        runner = PROJECT_ROOT / "scripts" / "progress_run_now.py"
        return [sys.executable, str(runner)], env
    raise ValueError(f"Unsupported job_type: {job_type}")


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def mark_execution_started(en, payload: dict[str, Any], log_file: Path, pid: int) -> None:
    job_execution_id = _payload_int(payload, "job_execution_id")
    if not job_execution_id:
        log("[worker] no job_execution_id in payload; skip execution start update")
        return
    with en.begin() as conn:
        result = conn.execute(
            text("""
                UPDATE job_execution
                SET status='running',
                    pid=:pid,
                    log_file=:log_file,
                    message=:message,
                    updated_at=NOW()
                WHERE id=:id
                  AND status IN ('queued','pending','running')
            """),
            {
                "id": job_execution_id,
                "pid": pid,
                "log_file": str(log_file),
                "message": f"worker started pid={pid}",
            },
        )
    log(f"[worker] marked job_execution #{job_execution_id} running rows={result.rowcount}")


def mark_execution_failed(en, payload: dict[str, Any], message: str) -> None:
    job_execution_id = _payload_int(payload, "job_execution_id")
    import_batch_id = _payload_int(payload, "import_batch_id")
    with en.begin() as conn:
        if job_execution_id:
            result = conn.execute(
                text("""
                    UPDATE job_execution
                    SET status='failed',
                        message=:message,
                        finished_at=NOW(),
                        updated_at=NOW()
                    WHERE id=:id
                      AND status NOT IN ('success','failed')
                """),
                {"id": job_execution_id, "message": message[:1000]},
            )
            log(f"[worker] marked job_execution #{job_execution_id} failed rows={result.rowcount}")
        if import_batch_id:
            result = conn.execute(
                text("""
                    UPDATE data_import_batch
                    SET status='failed',
                        message=:message,
                        finished_at=NOW(),
                        updated_at=NOW()
                    WHERE id=:id
                      AND status NOT IN ('success','failed')
                """),
                {"id": import_batch_id, "message": message[:1000]},
            )
            log(f"[worker] marked data_import_batch #{import_batch_id} failed rows={result.rowcount}")


def main():
    en = create_engine(get_database_url(), pool_pre_ping=True, future=True)
    poll = int(os.getenv("JOB_WORKER_POLL_INTERVAL", "10"))
    once = os.getenv("JOB_WORKER_ONCE", "").lower() in ("1", "true", "yes")
    log("[worker] started")
    while not STOP:
        try:
            with en.begin() as conn:
                row = conn.execute(
                    text("""
                        SELECT * FROM job_queue
                        WHERE status='pending'
                        ORDER BY priority ASC, created_at ASC
                        LIMIT 1 FOR UPDATE
                    """)
                ).mappings().first()
                if not row:
                    if once:
                        break
                    time.sleep(poll)
                    continue
                job = dict(row)
                log(f"[worker] picked queue #{job['id']} type={job['job_type']}")
                conn.execute(
                    text("UPDATE job_queue SET status='running', started_at=NOW(), updated_at=NOW() WHERE id=:id"),
                    {"id": job["id"]},
                )

            payload = parse_payload(job.get("payload"))
            payload.setdefault("job_execution_id", payload.get("job_execution_id"))
            payload.setdefault("import_batch_id", payload.get("import_batch_id"))
            cmd, env = build_job_command(job["job_type"], payload)
            log_path = PROJECT_ROOT / "logs" / f"job_worker_{datetime.now():%Y%m%d}.log"
            log_path.parent.mkdir(exist_ok=True)
            log(f"[worker] command: {' '.join(cmd)}")
            with open(log_path, "ab") as out:
                proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env, stdout=out, stderr=subprocess.STDOUT)
                mark_execution_started(en, payload, log_path, proc.pid)
                rc = proc.wait()
            log(f"[worker] queue #{job['id']} finished rc={rc}")
            if rc != 0:
                mark_execution_failed(en, payload, f"worker command failed rc={rc}: {' '.join(cmd)}")
            with en.begin() as conn:
                conn.execute(
                    text("UPDATE job_queue SET status=:s, finished_at=NOW(), updated_at=NOW() WHERE id=:id"),
                    {"id": job["id"], "s": "success" if rc == 0 else "failed"},
                )
            if once:
                break
        except Exception:
            traceback.print_exc()
            if once:
                break
            time.sleep(poll)
    log("[worker] stopped")


if __name__ == "__main__":
    main()

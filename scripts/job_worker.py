#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Strategy2560 job worker

职责：
1. 轮询 job_queue 表中 status='pending' 的任务
2. 抢占任务并标记 running
3. 写入 job_execution 执行记录
4. 根据 payload 执行 2560 分析脚本
5. 成功后标记 success，失败后标记 failed

设计原则：
- 不依赖 FastAPI 启动
- 不依赖 app.db.session，直接读取 DATABASE_URL
- 适合 Docker worker 容器常驻运行
"""

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

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLL_INTERVAL = int(os.getenv("JOB_WORKER_POLL_INTERVAL", "10"))
WORKER_NAME = os.getenv("JOB_WORKER_NAME", "strategy2560-worker")

STOP = False


def handle_signal(signum, frame):
    global STOP
    print(f"[worker] received signal {signum}, stopping...", flush=True)
    STOP = True


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Please define DATABASE_URL in .env"
        )
    return url


def make_engine() -> Engine:
    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
        pool_recycle=3600,
        future=True,
    )


def table_exists(engine: Engine, table_name: str) -> bool:
    sql = text(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
        """
    )
    with engine.connect() as conn:
        return bool(conn.execute(sql, {"table_name": table_name}).scalar())


def parse_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}

    if isinstance(payload, dict):
        return payload

    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="ignore")

    if isinstance(payload, str):
        payload = payload.strip()
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except Exception:
            return {"raw": payload}

    return {}


def claim_next_job(engine: Engine) -> dict[str, Any] | None:
    """
    抢占一个 pending job。

    注意：
    - MySQL 8 支持 FOR UPDATE SKIP LOCKED
    - 如果数据库不支持，会自动 fallback 到普通 FOR UPDATE
    """

    if not table_exists(engine, "job_queue"):
        print("[worker] job_queue table does not exist, sleep...", flush=True)
        return None

    with engine.begin() as conn:
        try:
            row = (
                conn.execute(
                    text(
                        """
                    SELECT *
                    FROM job_queue
                    WHERE status = 'pending'
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                    )
                )
                .mappings()
                .first()
            )
        except Exception:
            row = (
                conn.execute(
                    text(
                        """
                    SELECT *
                    FROM job_queue
                    WHERE status = 'pending'
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    FOR UPDATE
                    """
                    )
                )
                .mappings()
                .first()
            )

        if not row:
            return None

        job = dict(row)

        conn.execute(
            text(
                """
                UPDATE job_queue
                SET status='running',
                    started_at=NOW(),
                    updated_at=NOW()
                WHERE id=:id
                """
            ),
            {"id": job["id"]},
        )

        print(
            f"[worker] claimed job id={job['id']} type={job.get('job_type')} priority={job.get('priority')}",
            flush=True,
        )

        return job


def create_execution(engine: Engine, job: dict[str, Any]) -> int | None:
    if not table_exists(engine, "job_execution"):
        return None

    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO job_execution
                (job_type, batch_id, status, progress_current, progress_total, message, started_at, updated_at)
                VALUES
                (:job_type, NULL, 'running', 0, 1, :message, NOW(), NOW())
                """
            ),
            {
                "job_type": job.get("job_type") or "unknown",
                "message": f"worker={WORKER_NAME}, job_id={job.get('id')}",
            },
        )
        return int(result.lastrowid)


def update_execution(
    engine: Engine,
    execution_id: int | None,
    status: str,
    message: str,
    progress_current: int | None = None,
    progress_total: int | None = None,
):
    if execution_id is None:
        return

    if not table_exists(engine, "job_execution"):
        return

    sets = [
        "status=:status",
        "message=:message",
        "updated_at=NOW()",
    ]

    params: dict[str, Any] = {
        "id": execution_id,
        "status": status,
        "message": message[:1000] if message else "",
    }

    if progress_current is not None:
        sets.append("progress_current=:progress_current")
        params["progress_current"] = progress_current

    if progress_total is not None:
        sets.append("progress_total=:progress_total")
        params["progress_total"] = progress_total

    if status in {"success", "failed", "cancelled"}:
        sets.append("finished_at=NOW()")

    sql = f"""
    UPDATE job_execution
    SET {", ".join(sets)}
    WHERE id=:id
    """

    with engine.begin() as conn:
        conn.execute(text(sql), params)


def finish_job(engine: Engine, job_id: int, status: str, message: str):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE job_queue
                SET status=:status,
                    finished_at=NOW(),
                    updated_at=NOW()
                WHERE id=:id
                """
            ),
            {
                "id": job_id,
                "status": status,
            },
        )

    print(f"[worker] job id={job_id} finished status={status}: {message}", flush=True)


def run_script(payload: dict[str, Any]) -> tuple[bool, str]:
    """
    优先执行 scripts/daily_update_incremental_sharded.sh

    payload 示例：
    {
      "market": "all",
      "shards": 4
    }
    """

    script = PROJECT_ROOT / "scripts" / "daily_update_incremental_sharded.sh"

    if not script.exists():
        return False, f"script not found: {script}"

    market = str(payload.get("market") or payload.get("market_type") or "all")
    shards = str(payload.get("shards") or 4)

    env = os.environ.copy()
    env["MARKET"] = market
    env["SHARDS"] = shards
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"job_worker_{datetime.now().strftime('%Y%m%d')}.log"

    cmd = ["bash", str(script)]

    print(
        f"[worker] running script: {' '.join(cmd)} MARKET={market} SHARDS={shards}",
        flush=True,
    )

    with open(log_file, "ab") as out:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )

    if proc.returncode == 0:
        return True, f"script success, market={market}, shards={shards}, log={log_file}"

    return False, f"script failed returncode={proc.returncode}, log={log_file}"


def call_web_api(payload: dict[str, Any]) -> tuple[bool, str]:
    """
    如果没有 shell 脚本，也可以用 API 触发 /api/strategy/2560/run。
    默认不开启，只有设置 JOB_WORKER_FALLBACK_API=1 才会用。
    """

    if os.getenv("JOB_WORKER_FALLBACK_API", "0") != "1":
        return False, "fallback api disabled"

    import requests

    base_url = os.getenv("WEB_BASE_URL", "http://web:8000")
    url = f"{base_url.rstrip('/')}/api/strategy/2560/run"

    market = payload.get("market") or payload.get("market_type") or "all"

    body = {
        "codes": payload.get("codes") or [],
        "source": payload.get("source"),
        "limit": payload.get("limit"),
        "rebuild_statistics": payload.get("rebuild_statistics", True),
        "market_type": market,
    }

    print(f"[worker] calling api {url} payload={body}", flush=True)

    try:
        r = requests.post(url, json=body, timeout=3600)
        if r.status_code >= 400:
            return False, f"api failed status={r.status_code}, text={r.text[:500]}"
        return True, f"api success: {r.text[:500]}"
    except Exception as exc:
        return False, f"api exception: {exc}"


def execute_job(engine: Engine, job: dict[str, Any]):
    job_id = int(job["id"])
    job_type = job.get("job_type") or "run_2560"
    payload = parse_payload(job.get("payload"))

    execution_id = create_execution(engine, job)

    update_execution(
        engine,
        execution_id,
        status="running",
        message=f"job_id={job_id}, job_type={job_type}, payload={payload}",
        progress_current=0,
        progress_total=1,
    )

    try:
        if job_type in {"run_2560", "S2560", "strategy2560", "daily_update"}:
            ok, msg = run_script(payload)

            if not ok:
                api_ok, api_msg = call_web_api(payload)
                if api_ok:
                    ok, msg = api_ok, api_msg
                else:
                    msg = f"{msg}; fallback={api_msg}"

        else:
            ok = False
            msg = f"unknown job_type={job_type}"

        if ok:
            update_execution(
                engine,
                execution_id,
                status="success",
                message=msg,
                progress_current=1,
                progress_total=1,
            )
            finish_job(engine, job_id, "success", msg)
        else:
            update_execution(
                engine,
                execution_id,
                status="failed",
                message=msg,
                progress_current=0,
                progress_total=1,
            )
            finish_job(engine, job_id, "failed", msg)

    except Exception as exc:
        err = f"{exc}\n{traceback.format_exc()}"
        update_execution(
            engine,
            execution_id,
            status="failed",
            message=err,
            progress_current=0,
            progress_total=1,
        )
        finish_job(engine, job_id, "failed", err)


def main():
    print(f"[worker] starting {WORKER_NAME} at {now_str()}", flush=True)
    print(f"[worker] project root: {PROJECT_ROOT}", flush=True)

    engine = make_engine()

    poll_interval = int(os.getenv("JOB_WORKER_POLL_INTERVAL", DEFAULT_POLL_INTERVAL))

    while not STOP:
        try:
            job = claim_next_job(engine)

            if job:
                execute_job(engine, job)
            else:
                time.sleep(poll_interval)

        except Exception as exc:
            print("[worker] loop error:", exc, flush=True)
            traceback.print_exc()
            time.sleep(poll_interval)

    print(f"[worker] stopped at {now_str()}", flush=True)


if __name__ == "__main__":
    main()

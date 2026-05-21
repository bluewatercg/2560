#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Strategy2560 高性能并发执行器

设计目标：
- 不再“一只股票一次 HTTP 请求”，改为“每个并发 worker 按批次提交 codes”。
- shards 表示“同时运行的并发任务数”。
- batch_size 表示“每次提交多少只股票给 /api/strategy/2560/run”。
- 每个批次完成后批量更新 job_task_item，页面仍然能看到总量、完成数、失败数、ETA、实时日志。

环境变量：
- JOB_ID: job_execution.id
- MARKET: sh/sz/all/sh60/sh68/sz00/sz30
- SHARDS: 并发任务数
- BATCH_SIZE: 每批股票数量，默认 30
- WEB_BASE_URL: 默认 http://127.0.0.1:8000
"""

import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv
from typing import Iterable

import requests
from sqlalchemy import create_engine, text

from app.core.market_scope import market_sql_where
from app.db.clickhouse import get_clickhouse

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 独立脚本必须主动读取项目根目录 .env，否则 subprocess 子进程拿不到 DB_HOST/DB_USER/DB_NAME。
load_dotenv(PROJECT_ROOT / ".env")
JOB_ID = int(os.getenv("JOB_ID", "0"))
MARKET = os.getenv("MARKET", "all")
SHARDS = int(os.getenv("SHARDS", "1"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "30"))
LIMIT_CODES = int(os.getenv("LIMIT_CODES", "0") or 0)
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def log(msg: str):
    print(msg, flush=True)


def db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD", "")
    name = os.getenv("DB_NAME")
    if not host or not user or not name:
        raise RuntimeError("Set DATABASE_URL or DB_HOST/DB_USER/DB_NAME in .env")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


def engine():
    pool_size = int(os.getenv("DB_POOL_SIZE", "20"))
    return create_engine(
        db_url(),
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=max(pool_size, SHARDS + 4),
        max_overflow=max(10, SHARDS * 2),
        future=True,
    )


def market_where(alias: str, market: str) -> str:
    return market_sql_where(f"{alias}.code", market)


def load_codes(en) -> list[str]:
    sql = f"SELECT code FROM stock_info s WHERE {market_where('s', MARKET)} ORDER BY code"
    with en.connect() as conn:
        codes = [r[0] for r in conn.execute(text(sql)).all()]

    # fallback：如果 stock_info 为空，从 ClickHouse daily_kline 兜底取
    if not codes:
        log(f"[parallel] stock_info empty, falling back to ClickHouse daily_kline for market={MARKET}")
        try:
            where = market_where("code", MARKET)
            rows = get_clickhouse().query(
                f"SELECT DISTINCT code FROM daily_kline WHERE {where} ORDER BY code"
            )
            codes = [r["code"] for r in rows]
            log(f"[parallel] fallback loaded {len(codes)} codes from daily_kline")
        except Exception as e:
            log(f"[parallel] fallback also failed: {e}")
            return []

    return codes[:LIMIT_CODES] if LIMIT_CODES > 0 else codes


def chunks(seq: list[str], size: int) -> Iterable[list[str]]:
    size = max(1, size)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def init_items(en, codes: list[str]):
    with en.begin() as conn:
        conn.execute(
            text("""
            UPDATE job_execution
            SET progress_total=:total,
                message=:msg,
                updated_at=NOW()
            WHERE id=:id
            """),
            {"id": JOB_ID, "total": len(codes), "msg": f"initialized total={len(codes)}, concurrency={SHARDS}, batch_size={BATCH_SIZE}"},
        )
        # 批量插入，避免逐条插入太慢
        rows = [
            {"job_id": JOB_ID, "shard_id": idx % max(SHARDS, 1), "code": code}
            for idx, code in enumerate(codes)
        ]
        if rows:
            conn.execute(
                text("""
                INSERT IGNORE INTO job_task_item (job_id, shard_id, code, status, updated_at)
                VALUES (:job_id, :shard_id, :code, 'pending', NOW())
                """),
                rows,
            )


def update_counts(en, current_code: str | None = None, message: str | None = None):
    with en.begin() as conn:
        c = conn.execute(
            text("""
            SELECT
              SUM(CASE WHEN status IN ('success','failed') THEN 1 ELSE 0 END) AS done,
              SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_count,
              SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_count,
              COUNT(*) AS total
            FROM job_task_item
            WHERE job_id=:job_id
            """),
            {"job_id": JOB_ID},
        ).mappings().first()
        conn.execute(
            text("""
            UPDATE job_execution
            SET progress_current=:done,
                progress_total=:total,
                success_count=:success_count,
                failed_count=:failed_count,
                current_code=:current_code,
                message=COALESCE(:message, message),
                updated_at=NOW()
            WHERE id=:job_id
            """),
            {
                "job_id": JOB_ID,
                "done": int(c["done"] or 0),
                "total": int(c["total"] or 0),
                "success_count": int(c["success_count"] or 0),
                "failed_count": int(c["failed_count"] or 0),
                "current_code": current_code,
                "message": message,
            },
        )


def mark_batch_running(en, batch: list[str], shard_id: int):
    if not batch:
        return
    with en.begin() as conn:
        conn.execute(
            text("""
            UPDATE job_task_item
            SET status='running', shard_id=:shard_id, started_at=COALESCE(started_at, NOW()), updated_at=NOW()
            WHERE job_id=:job_id AND code=:code
            """),
            [{"job_id": JOB_ID, "code": code, "shard_id": shard_id} for code in batch],
        )


def mark_batch_done(en, batch: list[str], ok: bool, elapsed_ms: int, err: str | None = None):
    if not batch:
        return
    per_code_ms = int(elapsed_ms / max(1, len(batch)))
    status = "success" if ok else "failed"
    with en.begin() as conn:
        conn.execute(
            text("""
            UPDATE job_task_item
            SET status=:status,
                elapsed_ms=:elapsed_ms,
                error_message=:err,
                finished_at=NOW(),
                updated_at=NOW()
            WHERE job_id=:job_id AND code=:code
            """),
            [
                {
                    "job_id": JOB_ID,
                    "code": code,
                    "status": status,
                    "elapsed_ms": per_code_ms,
                    "err": (err or "")[:2000] if err else None,
                }
                for code in batch
            ],
        )


def run_batch(en, batch: list[str], shard_id: int, batch_no: int, total_batches: int):
    t0 = time.time()
    mark_batch_running(en, batch, shard_id)
    try:
        payload = {
            "codes": batch,
            "market_type": MARKET,
            "rebuild_statistics": False,
        }
        r = requests.post(f"{WEB_BASE_URL}/api/strategy/2560/run", json=payload, timeout=3600)
        ok = r.status_code < 400
        err = "" if ok else f"HTTP {r.status_code}: {r.text[:800]}"
    except Exception as exc:
        ok = False
        err = str(exc)
    elapsed_ms = int((time.time() - t0) * 1000)
    mark_batch_done(en, batch, ok, elapsed_ms, err)
    return {
        "batch_no": batch_no,
        "total_batches": total_batches,
        "shard_id": shard_id,
        "size": len(batch),
        "first": batch[0] if batch else "-",
        "last": batch[-1] if batch else "-",
        "ok": ok,
        "elapsed_ms": elapsed_ms,
        "err": err,
    }


def main():
    if not JOB_ID:
        raise RuntimeError("JOB_ID is required")
    en = engine()
    codes = load_codes(en)
    total = len(codes)
    batch_list = list(chunks(codes, BATCH_SIZE))
    total_batches = len(batch_list)
    log(f"[parallel] job_id={JOB_ID} market={MARKET} concurrency={SHARDS} batch_size={BATCH_SIZE} total_codes={total} total_batches={total_batches}")
    init_items(en, codes)
    update_counts(en, None, f"started total={total}, concurrency={SHARDS}, batch_size={BATCH_SIZE}")
    done_batches = 0
    try:
        with ThreadPoolExecutor(max_workers=max(SHARDS, 1)) as pool:
            futures = []
            for i, batch in enumerate(batch_list, 1):
                shard_id = (i - 1) % max(SHARDS, 1)
                futures.append(pool.submit(run_batch, en, batch, shard_id, i, total_batches))
            for fut in as_completed(futures):
                done_batches += 1
                info = fut.result()
                ok_txt = "OK" if info["ok"] else "FAIL"
                log(f"[batch {done_batches}/{total_batches}] shard={info['shard_id']} size={info['size']} {info['first']}..{info['last']} {ok_txt} {info['elapsed_ms']}ms {info['err'][:120] if info['err'] else ''}")
                # 每 5 个 batch 才更新 job_execution，避免并发写冲突
                if done_batches % 5 == 0 or done_batches == total_batches:
                    update_counts(en, info["last"], f"batch {done_batches}/{total_batches}")
        with en.begin() as conn:
            failed = int(conn.execute(text("SELECT failed_count FROM job_execution WHERE id=:id"), {"id": JOB_ID}).scalar() or 0)
            conn.execute(
                text("UPDATE job_execution SET status=:status, message=:msg, finished_at=NOW(), updated_at=NOW() WHERE id=:id"),
                {"id": JOB_ID, "status": "success" if failed == 0 else "failed", "msg": f"finished total={total}, failed={failed}, batches={total_batches}"},
            )
        log(f"[parallel] finished job_id={JOB_ID}")
    except Exception as exc:
        log(traceback.format_exc())
        with en.begin() as conn:
            conn.execute(text("UPDATE job_execution SET status='failed', message=:msg, finished_at=NOW(), updated_at=NOW() WHERE id=:id"), {"id": JOB_ID, "msg": str(exc)[:1000]})
        raise


if __name__ == "__main__":
    main()

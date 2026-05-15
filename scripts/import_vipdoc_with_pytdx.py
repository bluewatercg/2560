#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vipdoc 行情导入工具。

支持：
- 通达信/中金 vipdoc 日线 lday -> daily_kline
- 通达信/中金 vipdoc 5m fzline -> minute_kline_period(period='5m')
- 多线程导入
- 写入 data_import_file 明细
- 更新 stock_calc_status.last_import_at

注意：本脚本只导入行情文件，不触发 2560 / 2568 计算。
"""
from __future__ import annotations

import argparse
import struct
import json
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd
from pymysql.err import OperationalError
from sqlalchemy import text

try:
    from pytdx.reader import TdxDailyBarReader, TdxLCMinBarReader
except Exception:  # pragma: no cover
    TdxDailyBarReader = None
    TdxLCMinBarReader = None

from app.core.market_scope import market_file_prefixes, normalize_market_scope
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

SOURCE = "vipdoc"


def _norm_market(market: str) -> str:
    return normalize_market_scope(market)


def _side_from_market(market: str) -> str:
    m = _norm_market(market)
    return "sh" if m.startswith("sh") else "sz" if m.startswith("sz") else m


def _side_from_filename(path: Path, market: str) -> str:
    name = path.name.lower()
    if name.startswith("sh"):
        return "sh"
    if name.startswith("sz"):
        return "sz"
    return _side_from_market(market)


def code_from_filename(path: Path, market: str) -> str:
    name = path.stem.lower()
    digits = "".join(c for c in name if c.isdigit())
    if len(digits) < 6:
        raise ValueError(f"Cannot parse stock code from file name: {path.name}")
    side = _side_from_filename(path, market)
    return f"{side}.{digits[-6:]}"


def _file_match(path: Path, market: str) -> bool:
    name = path.name.lower()
    return any(name.startswith(prefix) for prefix in market_file_prefixes(market))


def _date_int(v) -> int:
    return int(pd.to_datetime(v).strftime("%Y%m%d"))


def _minute_int(v) -> int:
    return int(pd.to_datetime(v).strftime("%Y%m%d%H%M%S"))


def _start_day_i(start: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(start).strftime("%Y%m%d")) if start else None


def _end_day_i(end: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(end).strftime("%Y%m%d")) if end else None


def _start_min_i(start: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(start).strftime("%Y%m%d000000")) if start else None


def _end_min_i(end: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(end).strftime("%Y%m%d235959")) if end else None


def _volume(row) -> float:
    for k in ("volume", "vol", "amount_volume"):
        if k in row and pd.notna(row[k]):
            return float(row[k])
    return 0.0


def _amount(row) -> float:
    for k in ("amount", "money"):
        if k in row and pd.notna(row[k]):
            return float(row[k])
    return 0.0


def _scan_dirs(root: Path, market: str, import_type: str) -> list[Path]:
    m = _norm_market(market)
    if m in ("sh60", "sh68", "sh"):
        sides = ("sh",)
    elif m in ("sz00", "sz30", "sz"):
        sides = ("sz",)
    else:
        sides = ("sh", "sz")
    t = (import_type or "all").lower()
    dirs: list[Path] = []
    for side in sides:
        base = root / side
        if t in ("all", "lday", "daily"):
            dirs.append(base / "lday")
        if t in ("all", "5m", "lc5", "fzline"):
            dirs.append(base / "fzline")
    return [d for d in dirs if d.exists() and d.is_dir()]


def _day_file_edge_dates(path: Path) -> tuple[int | None, int | None]:
    record_size = 32
    size = path.stat().st_size
    if size < record_size:
        return None, None
    with path.open("rb") as f:
        first = f.read(record_size)
        f.seek(size - record_size)
        last = f.read(record_size)
    return struct.unpack("<I", first[:4])[0], struct.unpack("<I", last[:4])[0]


def _scan_file_data_range(files: list[Path]) -> dict:
    starts: list[int] = []
    ends: list[int] = []
    for p in files:
        if p.suffix.lower() != ".day":
            continue
        start, end = _day_file_edge_dates(p)
        if start:
            starts.append(start)
        if end:
            ends.append(end)
    data_start = min(starts) if starts else None
    data_end = max(ends) if ends else None
    return {
        "file_data_start": data_start,
        "file_data_end": data_end,
        "file_data_range": f"{data_start} - {data_end}" if data_start and data_end else None,
    }


def scan_vipdoc_files(source_dir: str, market: str = "sh", import_type: str = "all") -> dict:
    root = Path(source_dir)
    scan_dirs = _scan_dirs(root, market, import_type) if root.exists() else []
    files: list[Path] = []
    for d in scan_dirs:
        dtype = d.name.lower()
        if dtype == "lday":
            candidates = list(d.glob("*.day"))
        elif dtype == "fzline":
            candidates = list(d.glob("*.lc5"))
        else:
            candidates = list(d.iterdir())
        for p in candidates:
            if p.is_file() and _file_match(p, market):
                files.append(p)
    files = sorted(set(files), key=lambda x: str(x))
    data_range = _scan_file_data_range(files)
    return {
        "source_dir": str(root),
        "market": market,
        "import_type": import_type,
        "scan_dirs": [str(x) for x in scan_dirs],
        "total_files": len(files),
        "files": [str(x) for x in files],
        **data_range,
    }


def _read_daily(path: Path) -> pd.DataFrame:
    if path.name.lower().startswith("sh68"):
        df = _read_daily_binary(path)
    elif TdxDailyBarReader is None:
        raise RuntimeError("pytdx is not installed or TdxDailyBarReader unavailable")
    else:
        reader = TdxDailyBarReader()
        try:
            df = reader.get_df(str(path))
        except NotImplementedError:
            df = _read_daily_binary(path)
    if df is None:
        return pd.DataFrame()
    return df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df.copy()


def _read_daily_binary(path: Path) -> pd.DataFrame:
    rows = []
    record_size = 32
    with path.open("rb") as f:
        content = f.read()
    for offset in range(0, len(content) - record_size + 1, record_size):
        date_i, open_i, high_i, low_i, close_i, amount, volume_i, _reserved = struct.unpack(
            "<IIIIIfII",
            content[offset:offset + record_size],
        )
        rows.append({
            "date": pd.to_datetime(str(date_i), format="%Y%m%d"),
            "open": open_i * 0.01,
            "high": high_i * 0.01,
            "low": low_i * 0.01,
            "close": close_i * 0.01,
            "amount": float(amount),
            "volume": volume_i * 0.01,
        })
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "amount", "volume"])
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["date"])
    return df[["open", "high", "low", "close", "amount", "volume"]]


def _read_lc5(path: Path) -> pd.DataFrame:
    if TdxLCMinBarReader is None:
        raise RuntimeError("pytdx is not installed or TdxLCMinBarReader unavailable")
    reader = TdxLCMinBarReader()
    df = reader.get_df(str(path))
    if df is None:
        return pd.DataFrame()
    return df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df.copy()


def _filter_rows_by_date(rows: list[dict], start_i: Optional[int], end_i: Optional[int], key: str = "date") -> list[dict]:
    out = []
    for r in rows:
        d = int(r[key])
        if start_i is not None and d < start_i:
            continue
        if end_i is not None and d > end_i:
            continue
        out.append(r)
    return out


def _chunks(rows: list[dict], size: int = 1000) -> Iterable[list[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _lpush_rows_to_redis(redis_client, batch_id: int, rows: list[dict], redis_key: str) -> bool:
    """Batch LPUSH rows to Redis. Returns True on success."""
    if not redis_client or not rows:
        return False
    try:
        payload = [json.dumps(r, ensure_ascii=False) for r in rows]
        pipe = redis_client.pipeline()
        for item in payload:
            pipe.lpush(redis_key, item)
        pipe.execute()
        return True
    except Exception as exc:
        logger.warning("[mode=redis] LPUSH failed for %s: %s", redis_key, exc)
        return False


def _update_import_file(db, import_file_id: Optional[int], status: str, rows: int = 0, err: Optional[str] = None):
    if not import_file_id:
        return
    db.execute(text("""
        UPDATE data_import_file
        SET status=:status,
            rows_imported=:rows_imported,
            last_error=:err,
            finished_at=NOW(),
            updated_at=NOW()
        WHERE id=:id
    """), {"id": import_file_id, "status": status, "rows_imported": rows, "err": err[:2000] if err else None})


def _mark_import_file_running(db, import_file_id: Optional[int]):
    if not import_file_id:
        return
    db.execute(text("""
        UPDATE data_import_file
        SET status='running',
            started_at=COALESCE(started_at, NOW()),
            updated_at=NOW()
        WHERE id=:id
    """), {"id": import_file_id})


def _touch_stock_import(db, codes: Iterable[str]):
    data = [{"code": c, "strategy_code": "S2560"} for c in sorted(set(codes))]
    if not data:
        return
    db.execute(text("""
        INSERT INTO stock_calc_status (code, strategy_code, last_import_at, updated_at)
        VALUES (:code, :strategy_code, NOW(), NOW())
        ON DUPLICATE KEY UPDATE last_import_at=VALUES(last_import_at), updated_at=NOW()
    """), data)


def _update_import_batch_progress(db, batch_id: Optional[int], rows: int = 0, success_delta: int = 0, failed_delta: int = 0):
    if not batch_id:
        return
    db.execute(text("""
        UPDATE data_import_batch
        SET success_files = success_files + :success_delta,
            failed_files = failed_files + :failed_delta,
            total_rows = total_rows + :rows,
            updated_at = NOW()
        WHERE id=:id
    """), {
        "id": batch_id,
        "rows": rows,
        "success_delta": success_delta,
        "failed_delta": failed_delta,
    })


def _set_import_batch_status(db, batch_id: Optional[int], status: str, message: Optional[str] = None):
    if not batch_id:
        return
    if message is None:
        db.execute(text("""
            UPDATE data_import_batch
            SET status=:status, updated_at=NOW()
            WHERE id=:id
        """), {"id": batch_id, "status": status})
    else:
        db.execute(text("""
            UPDATE data_import_batch
            SET status=:status, message=:message, updated_at=NOW()
            WHERE id=:id
        """), {"id": batch_id, "status": status, "message": message})


def import_daily_file(path: str, market: str, start: Optional[str] = None, end: Optional[str] = None, import_file_id: Optional[int] = None, batch_id: Optional[int] = None, redis_client=None) -> dict:
    p = Path(path)
    try:
        code = code_from_filename(p, market)
        start_i = _start_day_i(start)
        end_i = _end_day_i(end)

        # Parse file outside DB transaction
        df = _read_daily(p)
        rows: list[dict] = []
        for _, row in df.iterrows():
            d = _date_int(row.get("date") if "date" in row else row.iloc[0])
            rows.append({
                "code": code,
                "date": d,
                "open": float(row.get("open", 0) or 0),
                "high": float(row.get("high", 0) or 0),
                "low": float(row.get("low", 0) or 0),
                "close": float(row.get("close", 0) or 0),
                "volume": int(_volume(row)),
                "amount": float(_amount(row)),
                "source": SOURCE,
            })
        rows = _filter_rows_by_date(rows, start_i, end_i, "date")

        mode = "redis" if redis_client else "db-fallback"

        if redis_client:
            # Redis mode: buffer rows to Redis, only update metadata in DB
            redis_key = f"import:{batch_id}:daily"
            ok = _lpush_rows_to_redis(redis_client, batch_id, rows, redis_key)
            if not ok:
                # Redis write failed, fall through to DB retry path
                mode = "db-fallback"

        if mode == "db-fallback":
            # Retry on MySQL deadlock (error 1213)
            last_err = None
            for attempt in range(3):
                if attempt > 0:
                    time.sleep(0.5 * attempt)  # backoff: 0.5s, 1s
                with SessionLocal() as db:
                    try:
                        _mark_import_file_running(db, import_file_id)
                        db.commit()
                        for part in _chunks(rows):
                            db.execute(text("""
                                INSERT INTO daily_kline (code, date, open, high, low, close, volume, amount, source)
                                VALUES (:code, :date, :open, :high, :low, :close, :volume, :amount, :source)
                                ON DUPLICATE KEY UPDATE open=VALUES(open), high=VALUES(high), low=VALUES(low),
                                    close=VALUES(close), volume=VALUES(volume), amount=VALUES(amount)
                            """), part)
                        _touch_stock_import(db, [code])
                        _update_import_file(db, import_file_id, "success", len(rows))
                        _update_import_batch_progress(db, batch_id, rows=len(rows), success_delta=1)
                        db.commit()
                        return {"ok": True, "file": str(p), "code": code, "rows": len(rows), "type": "lday", "mode": mode}
                    except OperationalError as exc:
                        db.rollback()
                        last_err = exc
                        if exc.args and exc.args[0] == 1213:
                            continue  # deadlock, retry
                        break
                    except Exception as exc:
                        db.rollback()
                        err = traceback.format_exc()
                        _update_import_file(db, import_file_id, "failed", 0, err)
                        _update_import_batch_progress(db, batch_id, failed_delta=1)
                        db.commit()
                        return {"ok": False, "file": str(p), "code": code, "rows": 0, "type": "lday", "error": str(exc), "mode": mode}

            # Exhausted retries
            err_str = f"Deadlock after 3 retries: {last_err}"
            with SessionLocal() as db:
                _update_import_file(db, import_file_id, "failed", 0, err_str)
                _update_import_batch_progress(db, batch_id, failed_delta=1)
                db.commit()
            return {"ok": False, "file": str(p), "code": code, "rows": 0, "type": "lday", "error": err_str, "mode": mode}

        # Redis mode success: only update metadata in DB
        with SessionLocal() as db:
            _mark_import_file_running(db, import_file_id)
            _update_import_file(db, import_file_id, "success", len(rows))
            _update_import_batch_progress(db, batch_id, rows=len(rows), success_delta=1)
            db.commit()
        return {"ok": True, "file": str(p), "code": code, "rows": len(rows), "type": "lday", "mode": mode}

    except Exception as exc:
        # File-level catch: parse errors, struct errors, etc.
        # Ensure this file is marked failed even if parsing blows up before any DB work
        err = traceback.format_exc()
        code = "<unknown>"
        try:
            code = code_from_filename(p, market)
        except Exception:
            pass
        with SessionLocal() as db:
            _update_import_file(db, import_file_id, "failed", 0, err)
            _update_import_batch_progress(db, batch_id, failed_delta=1)
            db.commit()
        return {"ok": False, "file": str(p), "code": code, "rows": 0, "type": "lday", "error": str(exc), "mode": "parse-error"}


def import_lc5_file(path: str, market: str, start: Optional[str] = None, end: Optional[str] = None, import_file_id: Optional[int] = None, batch_id: Optional[int] = None, redis_client=None) -> dict:
    p = Path(path)
    try:
        code = code_from_filename(p, market)
        start_i = _start_min_i(start)
        end_i = _end_min_i(end)

        # Parse file outside DB transaction
        df = _read_lc5(p)
        rows: list[dict] = []
        for _, row in df.iterrows():
            dtv = row.get("datetime", None) or row.get("date", None) or row.iloc[0]
            d = _minute_int(dtv)
            rows.append({
                "code": code,
                "date": d,
                "period": "5m",
                "source": SOURCE,
                "open": float(row.get("open", 0) or 0),
                "high": float(row.get("high", 0) or 0),
                "low": float(row.get("low", 0) or 0),
                "close": float(row.get("close", 0) or 0),
                "volume": float(_volume(row)),
                "amount": float(_amount(row)),
            })
        rows = _filter_rows_by_date(rows, start_i, end_i, "date")

        mode = "redis" if redis_client else "db-fallback"

        if redis_client:
            redis_key = f"import:{batch_id}:minute"
            ok = _lpush_rows_to_redis(redis_client, batch_id, rows, redis_key)
            if not ok:
                mode = "db-fallback"

        if mode == "db-fallback":
            # Retry on MySQL deadlock (error 1213)
            last_err = None
            for attempt in range(3):
                if attempt > 0:
                    time.sleep(0.5 * attempt)
                with SessionLocal() as db:
                    try:
                        _mark_import_file_running(db, import_file_id)
                        db.commit()
                        for part in _chunks(rows):
                            db.execute(text("""
                                INSERT INTO minute_kline_period (code, date, period, source, open, high, low, close, volume, amount)
                                VALUES (:code, :date, :period, :source, :open, :high, :low, :close, :volume, :amount)
                                ON DUPLICATE KEY UPDATE open=VALUES(open), high=VALUES(high), low=VALUES(low),
                                    close=VALUES(close), volume=VALUES(volume), amount=VALUES(amount)
                            """), part)
                        _touch_stock_import(db, [code])
                        _update_import_file(db, import_file_id, "success", len(rows))
                        _update_import_batch_progress(db, batch_id, rows=len(rows), success_delta=1)
                        db.commit()
                        return {"ok": True, "file": str(p), "code": code, "rows": len(rows), "type": "5m", "mode": mode}
                    except OperationalError as exc:
                        db.rollback()
                        last_err = exc
                        if exc.args and exc.args[0] == 1213:
                            continue
                        break
                    except Exception as exc:
                        db.rollback()
                        err = traceback.format_exc()
                        _update_import_file(db, import_file_id, "failed", 0, err)
                        _update_import_batch_progress(db, batch_id, failed_delta=1)
                        db.commit()
                        return {"ok": False, "file": str(p), "code": code, "rows": 0, "type": "5m", "error": str(exc), "mode": mode}

            err_str = f"Deadlock after 3 retries: {last_err}"
            with SessionLocal() as db:
                _update_import_file(db, import_file_id, "failed", 0, err_str)
                _update_import_batch_progress(db, batch_id, failed_delta=1)
                db.commit()
            return {"ok": False, "file": str(p), "code": code, "rows": 0, "type": "5m", "error": err_str, "mode": mode}

        # Redis mode success
        with SessionLocal() as db:
            _mark_import_file_running(db, import_file_id)
            _update_import_file(db, import_file_id, "success", len(rows))
            _update_import_batch_progress(db, batch_id, rows=len(rows), success_delta=1)
            db.commit()
        return {"ok": True, "file": str(p), "code": code, "rows": len(rows), "type": "5m", "mode": mode}

    except Exception as exc:
        # File-level catch: parse errors, struct errors, etc.
        err = traceback.format_exc()
        code = "<unknown>"
        try:
            code = code_from_filename(p, market)
        except Exception:
            pass
        with SessionLocal() as db:
            _update_import_file(db, import_file_id, "failed", 0, err)
            _update_import_batch_progress(db, batch_id, failed_delta=1)
            db.commit()
        return {"ok": False, "file": str(p), "code": code, "rows": 0, "type": "5m", "error": str(exc), "mode": "parse-error"}


def _flush_redis_to_db(db, batch_id: int, redis_client, redis_key: str, table: str, columns: list[str]) -> tuple[int, set[str]]:
    """
    Read all rows from Redis and bulk INSERT into DB in smaller transactions.
    Commits every 10 batches to avoid keeping a huge transaction open.
    On failure, the remaining rows stay in Redis for manual retry.
    Returns (rows_flushed, set of affected stock codes).
    """
    total = redis_client.llen(redis_key)
    if total == 0:
        return 0, set()

    batch_size = 5000
    commit_every = 10  # commit DB transaction every N batches (~50k rows)
    cols = ", ".join(columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    on_dup = ", ".join(f"{c}=VALUES({c})" for c in columns if c not in ("code", "date", "period", "source"))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {on_dup}"

    flushed = 0
    codes: set[str] = set()
    batches_since_commit = 0

    try:
        for offset in range(0, total, batch_size):
            raw = redis_client.lrange(redis_key, offset, offset + batch_size - 1)
            if not raw:
                break
            params = [json.loads(r) for r in raw]
            db.execute(text(sql), params)
            flushed += len(params)
            codes.update(p["code"] for p in params)
            batches_since_commit += 1

            if batches_since_commit >= commit_every:
                db.commit()
                batches_since_commit = 0
                logger.info("[flush] batch_id=%s flushed %d/%d so far", batch_id, flushed, total)

        # Final commit for remaining rows
        if flushed > 0:
            db.commit()
            logger.info("[flush] batch_id=%s completed: %d rows total", batch_id, flushed)

    except Exception:
        # Commit whatever succeeded so far, let caller decide what to do
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise

    return flushed, codes


def _file_phase(path: str, import_type: str) -> str:
    p = Path(path)
    parent = p.parent.name.lower()
    suffix = p.suffix.lower()
    if import_type in ("lday", "daily"):
        return "daily"
    if import_type in ("5m", "lc5", "fzline"):
        return "5m"
    if parent == "lday" or suffix == ".day":
        return "daily"
    return "5m"


def import_vipdoc_files_parallel(
    files: list[str],
    market: str,
    import_type: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    workers: int = 4,
    batch_id: Optional[int] = None,
    import_file_ids: Optional[dict[str, int]] = None,
    on_result: Optional[Callable[[dict, int, int], None]] = None,
    redis_client=None,
) -> dict:
    workers = max(1, int(workers or 1))
    results = []
    total_files = len(files)
    completed = 0

    def submit_one(f: str):
        iid = import_file_ids.get(f) if import_file_ids else None

        if _file_phase(f, import_type) == "daily":
            return import_daily_file(f, market, start, end, iid, batch_id=batch_id, redis_client=redis_client)
        return import_lc5_file(f, market, start, end, iid, batch_id=batch_id, redis_client=redis_client)

    def run_phase(phase_name: str, phase_files: list[str]):
        nonlocal completed
        if not phase_files:
            return
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(submit_one, f) for f in phase_files]
            for fut in as_completed(futs):
                r = fut.result()
                r["phase"] = phase_name
                results.append(r)
                completed += 1
                if on_result:
                    on_result(r, completed, total_files)

    daily_files = [f for f in files if _file_phase(f, import_type) == "daily"]
    minute_files = [f for f in files if _file_phase(f, import_type) == "5m"]

    run_phase("daily", daily_files)
    run_phase("5m", minute_files)

    # Flush Redis buffer to DB (Phase 4)
    flush_failed = False
    flush_error = None
    flushed_codes: set[str] = set()
    if redis_client and batch_id:
        daily_key = f"import:{batch_id}:daily"
        minute_key = f"import:{batch_id}:minute"
        with SessionLocal() as db:
            try:
                flushed_daily, daily_codes = _flush_redis_to_db(
                    db, batch_id, redis_client, daily_key, "daily_kline",
                    ["code", "date", "open", "high", "low", "close", "volume", "amount", "source"],
                )
                flushed_minute, minute_codes = _flush_redis_to_db(
                    db, batch_id, redis_client, minute_key, "minute_kline_period",
                    ["code", "date", "period", "source", "open", "high", "low", "close", "volume", "amount"],
                )

                flushed_codes = daily_codes | minute_codes
                if flushed_codes:
                    _touch_stock_import(db, flushed_codes)

                db.commit()
                logger.info("[mode=redis] flushed daily=%d minute=%d", flushed_daily, flushed_minute)

                # Only delete Redis keys AFTER commit succeeds
                if flushed_daily or flushed_minute:
                    redis_client.delete(daily_key, minute_key)
            except Exception as exc:
                db.rollback()
                flush_failed = True
                flush_error = f"flush failed: {exc}"
                logger.error("[mode=redis] flush failed (Redis keys preserved): %s", exc)

    ok = sum(1 for r in results if r.get("ok"))
    failed = len(results) - ok
    if flush_failed:
        failed += 1  # count flush failure as an extra failed "file"
    rows = sum(int(r.get("rows") or 0) for r in results)
    mode = "redis" if redis_client else "db-fallback"
    return {
        "ok": failed == 0 and not flush_failed,
        "total_files": len(results),
        "success_files": ok,
        "failed_files": failed,
        "total_rows": rows,
        "mode": mode,
        "results": results,
        "flush_error": flush_error,
    }


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--market", default="sh")
    ap.add_argument("--import-type", default="lday", choices=["all", "lday", "daily", "5m", "lc5", "fzline"])
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit-files", type=int, default=None)
    return ap.parse_args()


def main():
    a = parse_args()
    scan = scan_vipdoc_files(a.root, a.market, a.import_type)
    files = scan["files"][:a.limit_files] if a.limit_files else scan["files"]
    print(import_vipdoc_files_parallel(files, a.market, a.import_type, a.start, a.end, a.workers))


if __name__ == "__main__":
    main()

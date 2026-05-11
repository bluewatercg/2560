#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 minute_kline_period 中的 5m 数据多线程聚合生成 30m。"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import pandas as pd
from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.job_orchestrator import update_data_import_batch_progress

SOURCE = "build_from_5m"


def start_i(s: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(s).strftime("%Y%m%d000000")) if s else None


def end_i(s: Optional[str]) -> Optional[int]:
    return int(pd.to_datetime(s).strftime("%Y%m%d235959")) if s else None


def date_to_dt(v):
    return pd.to_datetime(str(int(v)), format="%Y%m%d%H%M%S")


def dt_to_int(v):
    return int(pd.to_datetime(v).strftime("%Y%m%d%H%M%S"))


def code_where(market: str) -> str:
    mt = (market or "all").lower()
    if mt == "sh": return "code LIKE 'sh.%'"
    if mt == "sz": return "code LIKE 'sz.%'"
    if mt == "sh60": return "code LIKE 'sh.60%'"
    if mt == "sh68": return "code LIKE 'sh.68%'"
    if mt == "sz00": return "code LIKE 'sz.00%'"
    if mt == "sz30": return "code LIKE 'sz.30%'"
    return "(code LIKE 'sh.%' OR code LIKE 'sz.%')"


def bucket_30m(ts):
    ts = pd.to_datetime(ts)
    d = ts.normalize()
    endpoints = [
        d + pd.Timedelta(hours=10),
        d + pd.Timedelta(hours=10, minutes=30),
        d + pd.Timedelta(hours=11),
        d + pd.Timedelta(hours=11, minutes=30),
        d + pd.Timedelta(hours=13, minutes=30),
        d + pd.Timedelta(hours=14),
        d + pd.Timedelta(hours=14, minutes=30),
        d + pd.Timedelta(hours=15),
    ]
    for ep in endpoints:
        if ts <= ep:
            return ep
    return None


def get_codes(market: str, start: Optional[str], end: Optional[str], limit_codes: Optional[int] = None) -> list[str]:
    si = start_i(start)
    ei = end_i(end)
    where = code_where(market)
    params = {"start": si or 0}
    q = f"""
        SELECT DISTINCT code
        FROM minute_kline_period
        WHERE period='5m' AND date>=:start AND {where}
    """
    if ei:
        q += " AND date<=:end"
        params["end"] = ei
    q += " ORDER BY code"
    with SessionLocal() as db:
        codes = [r[0] for r in db.execute(text(q), params).fetchall()]
    return codes[:limit_codes] if limit_codes else codes


def _chunks(rows: list[dict], size: int = 1000):
    for i in range(0, len(rows), size):
        yield rows[i:i+size]


def build_30m_for_code(code: str, start: Optional[str], end: Optional[str], dry_run: bool = False, batch_id: Optional[int] = None) -> dict:
    try:
        si = start_i(start) or 0
        ei = end_i(end)
        params = {"code": code, "start": si}
        q = """
            SELECT code, date, open, high, low, close, volume, amount
            FROM minute_kline_period
            WHERE code=:code AND period='5m' AND date>=:start
        """
        if ei:
            q += " AND date<=:end"
            params["end"] = ei
        q += " ORDER BY date"
        with SessionLocal() as db:
            rows = db.execute(text(q), params).mappings().all()
            if not rows:
                if batch_id is not None:
                    update_data_import_batch_progress(db, batch_id, success_delta=1)
                return {"ok": True, "code": code, "rows": 0}
            df = pd.DataFrame([dict(r) for r in rows])
            df["dt"] = df["date"].map(date_to_dt)
            df["bucket"] = df["dt"].map(bucket_30m)
            df = df[df["bucket"].notna()]
            out = []
            for bucket, g in df.groupby("bucket"):
                g = g.sort_values("dt")
                out.append({
                    "code": code,
                    "period": "30m",
                    "date": dt_to_int(bucket),
                    "source": SOURCE,
                    "open": float(g.iloc[0]["open"]),
                    "high": float(g["high"].max()),
                    "low": float(g["low"].min()),
                    "close": float(g.iloc[-1]["close"]),
                    "volume": float(g["volume"].sum()),
                    "amount": float(g["amount"].sum()),
                })
            if dry_run:
                if batch_id is not None:
                    update_data_import_batch_progress(
                        db,
                        batch_id,
                        success_delta=1,
                        total_rows_delta=len(out),
                    )
                return {"ok": True, "code": code, "rows": len(out), "dry_run": True}
            dp = {"code": code, "start": si}
            del_sql = "DELETE FROM minute_kline_period WHERE code=:code AND period='30m' AND date>=:start"
            if ei:
                del_sql += " AND date<=:end"
                dp["end"] = ei
            db.execute(text(del_sql), dp)
            for part in _chunks(out):
                db.execute(text("""
                    INSERT INTO minute_kline_period (code, date, period, source, open, high, low, close, volume, amount)
                    VALUES (:code, :date, :period, :source, :open, :high, :low, :close, :volume, :amount)
                """), part)
            db.execute(text("""
                INSERT INTO stock_calc_status (code, strategy_code, last_import_at, updated_at)
                VALUES (:code, 'S2560', NOW(), NOW())
                ON DUPLICATE KEY UPDATE last_import_at=VALUES(last_import_at), updated_at=NOW()
            """), {"code": code})
            if batch_id is not None:
                update_data_import_batch_progress(
                    db,
                    batch_id,
                    success_delta=1,
                    total_rows_delta=len(out),
                )
            db.commit()
            return {"ok": True, "code": code, "rows": len(out)}
    except Exception as exc:
        if batch_id is not None:
            with SessionLocal() as db:
                update_data_import_batch_progress(
                    db,
                    batch_id,
                    failed_delta=1,
                    message=f"build_30m failed code={code}",
                )
        return {"ok": False, "code": code, "rows": 0, "error": str(exc)}


def build_30m_parallel(
    start: Optional[str],
    end: Optional[str],
    market: str = "all",
    workers: int = 4,
    limit_codes: Optional[int] = None,
    dry_run: bool = False,
    batch_id: Optional[int] = None,
    on_result: Optional[Callable[[dict, int, int], None]] = None,
) -> dict:
    codes = get_codes(market, start, end, limit_codes)
    results = []
    total_codes = len(codes)
    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, int(workers or 1))) as pool:
        futs = [pool.submit(build_30m_for_code, code, start, end, dry_run, batch_id) for code in codes]
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception as exc:
                r = {"ok": False, "code": None, "rows": 0, "error": str(exc)}
            results.append(r)
            completed += 1
            if on_result:
                on_result(r, completed, total_codes)
    return {
        "ok": all(r.get("ok") for r in results),
        "codes": len(codes),
        "inserted_30m_rows": sum(int(r.get("rows") or 0) for r in results),
        "dry_run": dry_run,
        "results_sample": results[:20],
    }


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default=None)
    ap.add_argument("--market-type", default="all")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit-codes", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def main():
    a = parse_args()
    print(json.dumps(build_30m_parallel(a.start, a.end, a.market_type, a.workers, a.limit_codes, a.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

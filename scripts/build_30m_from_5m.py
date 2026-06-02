#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 minute_kline_period 中的 5m 数据多线程聚合生成 30m。"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import pandas as pd
from sqlalchemy import text

from app.core.market_scope import market_sql_where
from app.db.clickhouse import get_clickhouse
from app.db.session import SessionLocal
from app.services.job_orchestrator import update_data_import_batch_progress

SOURCE = "build_from_5m"


def code_where(market: str) -> str:
    return market_sql_where("code", market)


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
    start_s = pd.to_datetime(start).strftime("%Y-%m-%d") if start else None
    end_s = pd.to_datetime(end).strftime("%Y-%m-%d") if end else None
    where = code_where(market)
    q = f"SELECT DISTINCT code FROM minute_kline_period WHERE period='5m' AND {where}"
    if start_s:
        q += f" AND date>='{start_s}'"
    if end_s:
        q += f" AND date<='{end_s}'"
    q += " ORDER BY code"
    ch = get_clickhouse()
    rows = ch.query(q)
    codes = [r["code"] for r in rows]
    return codes[:limit_codes] if limit_codes else codes


def build_30m_clickhouse(
    start: Optional[str],
    end: Optional[str],
    market: str = "all",
    limit_codes: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """Build 30m bars with one ClickHouse INSERT SELECT for the normal daily path."""
    if not start:
        raise ValueError("start is required for ClickHouse 30m build")
    ch = get_clickhouse()
    start_s = pd.to_datetime(start).strftime("%Y-%m-%d")
    end_s = pd.to_datetime(end or start).strftime("%Y-%m-%d")
    where = code_where(market)
    code_limit = ""
    if limit_codes:
        code_limit = f" AND code IN (SELECT code FROM (SELECT DISTINCT code FROM minute_kline_period WHERE period='5m' AND {where} ORDER BY code LIMIT {int(limit_codes)}))"
    date_filter = f"date >= toDate('{start_s}') AND date < toDate('{end_s}') + INTERVAL 1 DAY"
    count_q = f"SELECT count() AS rows, uniqExact(code) AS codes FROM minute_kline_period WHERE period='5m' AND {date_filter} AND {where}{code_limit}"
    stats = ch.query_one(count_q) or {"rows": 0, "codes": 0}
    if int(stats.get("rows") or 0) == 0:
        return {
            "ok": False,
            "codes": 0,
            "inserted_30m_rows": 0,
            "dry_run": dry_run,
            "error": f"no 5m data found in ClickHouse for market={market}, date_range={start_s}~{end_s}",
            "results_sample": [],
        }
    if dry_run:
        estimate_q = f"""
        SELECT count() AS rows
        FROM (
            SELECT code, bucket
            FROM (
                SELECT
                    code,
                    multiIf(
                        toHour(date)*60 + toMinute(date) <= 600, toDateTime(toDate(date)) + INTERVAL 10 HOUR,
                        toHour(date)*60 + toMinute(date) <= 630, toDateTime(toDate(date)) + INTERVAL 10 HOUR + INTERVAL 30 MINUTE,
                        toHour(date)*60 + toMinute(date) <= 660, toDateTime(toDate(date)) + INTERVAL 11 HOUR,
                        toHour(date)*60 + toMinute(date) <= 690, toDateTime(toDate(date)) + INTERVAL 11 HOUR + INTERVAL 30 MINUTE,
                        toHour(date)*60 + toMinute(date) <= 810, toDateTime(toDate(date)) + INTERVAL 13 HOUR + INTERVAL 30 MINUTE,
                        toHour(date)*60 + toMinute(date) <= 840, toDateTime(toDate(date)) + INTERVAL 14 HOUR,
                        toHour(date)*60 + toMinute(date) <= 870, toDateTime(toDate(date)) + INTERVAL 14 HOUR + INTERVAL 30 MINUTE,
                        toHour(date)*60 + toMinute(date) <= 900, toDateTime(toDate(date)) + INTERVAL 15 HOUR,
                        NULL
                    ) AS bucket
                FROM minute_kline_period
                WHERE period='5m' AND {date_filter} AND {where}{code_limit}
            )
            WHERE bucket IS NOT NULL
            GROUP BY code, bucket
        )
        """
        est = ch.query_one(estimate_q) or {"rows": 0}
        return {"ok": True, "codes": int(stats.get("codes") or 0), "inserted_30m_rows": int(est.get("rows") or 0), "dry_run": True, "results_sample": []}

    del_q = f"ALTER TABLE {ch.database}.minute_kline_period DELETE WHERE period='30m' AND {date_filter} AND {where}{code_limit}"
    ch.command(del_q)
    insert_q = f"""
    INSERT INTO {ch.database}.minute_kline_period
        (code, date, period, source, open, high, low, close, volume, amount)
    SELECT
        code,
        bucket AS date,
        '30m' AS period,
        '{SOURCE}' AS source,
        argMin(open, date) AS open,
        max(high) AS high,
        min(low) AS low,
        argMax(close, date) AS close,
        sum(volume) AS volume,
        sum(amount) AS amount
    FROM (
        SELECT
            code, date, open, high, low, close, volume, amount,
            multiIf(
                toHour(date)*60 + toMinute(date) <= 600, toDateTime(toDate(date)) + INTERVAL 10 HOUR,
                toHour(date)*60 + toMinute(date) <= 630, toDateTime(toDate(date)) + INTERVAL 10 HOUR + INTERVAL 30 MINUTE,
                toHour(date)*60 + toMinute(date) <= 660, toDateTime(toDate(date)) + INTERVAL 11 HOUR,
                toHour(date)*60 + toMinute(date) <= 690, toDateTime(toDate(date)) + INTERVAL 11 HOUR + INTERVAL 30 MINUTE,
                toHour(date)*60 + toMinute(date) <= 810, toDateTime(toDate(date)) + INTERVAL 13 HOUR + INTERVAL 30 MINUTE,
                toHour(date)*60 + toMinute(date) <= 840, toDateTime(toDate(date)) + INTERVAL 14 HOUR,
                toHour(date)*60 + toMinute(date) <= 870, toDateTime(toDate(date)) + INTERVAL 14 HOUR + INTERVAL 30 MINUTE,
                toHour(date)*60 + toMinute(date) <= 900, toDateTime(toDate(date)) + INTERVAL 15 HOUR,
                NULL
            ) AS bucket
        FROM minute_kline_period
        WHERE period='5m' AND {date_filter} AND {where}{code_limit}
    )
    WHERE bucket IS NOT NULL
    GROUP BY code, bucket
    """
    ch.command(insert_q)
    rows = ch.query_one(f"SELECT count() AS rows, uniqExact(code) AS codes FROM minute_kline_period WHERE period='30m' AND {date_filter} AND {where}{code_limit}") or {"rows": 0, "codes": 0}
    return {
        "ok": True,
        "codes": int(rows.get("codes") or 0),
        "inserted_30m_rows": int(rows.get("rows") or 0),
        "dry_run": False,
        "results_sample": [],
    }


def build_30m_for_code(code: str, start: Optional[str], end: Optional[str], dry_run: bool = False, batch_id: Optional[int] = None) -> dict:
    try:
        start_s = pd.to_datetime(start).strftime("%Y-%m-%d") if start else None
        end_s = pd.to_datetime(end).strftime("%Y-%m-%d") if end else None
        q = f"SELECT code,date,open,high,low,close,volume,amount FROM minute_kline_period WHERE code='{code}' AND period='5m'"
        if start_s:
            q += f" AND date>='{start_s}'"
        if end_s:
            q += f" AND date<='{end_s}'"
        q += " ORDER BY date"
        rows = get_clickhouse().query(q)
        if not rows:
            if batch_id is not None:
                with SessionLocal() as db:
                    update_data_import_batch_progress(db, batch_id, success_delta=1)
            return {"ok": True, "code": code, "rows": 0}
        df = pd.DataFrame(rows)
        df["dt"] = pd.to_datetime(df["date"])
        df["bucket"] = df["dt"].map(bucket_30m)
        df = df[df["bucket"].notna()]
        out = []
        for bucket, g in df.groupby("bucket"):
            g = g.sort_values("dt")
            out.append({
                "code": code,
                "period": "30m",
                "date": bucket.strftime("%Y-%m-%d %H:%M:%S"),
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
                with SessionLocal() as db:
                    update_data_import_batch_progress(
                        db,
                        batch_id,
                        success_delta=1,
                        total_rows_delta=len(out),
                    )
            return {"ok": True, "code": code, "rows": len(out), "dry_run": True}

        # Delete existing 30m for this code + date range in ClickHouse
        del_q = f"ALTER TABLE {get_clickhouse().database}.minute_kline_period DELETE WHERE code='{code}' AND period='30m'"
        if start_s:
            del_q += f" AND date>='{start_s}'"
        if end_s:
            del_q += f" AND date<='{end_s}'"
        get_clickhouse().command(del_q)

        # Insert new 30m rows to ClickHouse
        if out:
            get_clickhouse().insert_batch("minute_kline_period", out)

        # stock_calc_status stays in MySQL
        with SessionLocal() as db:
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
    if os.getenv("BUILD_30M_MODE", "clickhouse").lower() == "clickhouse":
        return build_30m_clickhouse(start, end, market, limit_codes, dry_run)
    codes = get_codes(market, start, end, limit_codes)
    if not codes:
        return {
            "ok": False,
            "codes": 0,
            "inserted_30m_rows": 0,
            "dry_run": dry_run,
            "error": f"no 5m data found in ClickHouse for market={market}, date_range={start}~{end or '∞'}. Please run import_vipdoc with import_type=all/5m first.",
            "results_sample": [],
        }
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

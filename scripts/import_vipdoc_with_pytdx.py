#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_vipdoc_with_pytdx.py

功能：
- 导入中金/通达信 vipdoc 本地数据
- 支持 daily (.day)
- 支持 5m (.lc5, fzline)
- date 使用 BIGINT
- 自动跳过 Unknown security type
- 重复执行 = 覆盖更新（先删后插）

依赖：
pip install pytdx pandas sqlalchemy pymysql
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import pandas as pd
from sqlalchemy import text

from pytdx.reader import TdxDailyBarReader, TdxLCMinBarReader
from app.db.session import SessionLocal


# ------------------------
# 参数解析
# ------------------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, help="vipdoc 根目录")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--daily", action="store_true")
    p.add_argument("--lc5", action="store_true")
    p.add_argument("--markets", default="sh,sz")
    p.add_argument("--limit-files", type=int)
    return p.parse_args()


# ------------------------
# 工具函数
# ------------------------
def code_from_filename(path: Path, market: str) -> str:
    name = path.stem.lower()
    digits = "".join(c for c in name if c.isdigit())
    return f"{market}.{digits[-6:]}"


def day_int(dt) -> int:
    return int(pd.to_datetime(dt).strftime("%Y%m%d"))


def minute_int(dt) -> int:
    return int(pd.to_datetime(dt).strftime("%Y%m%d%H%M%S"))


# ------------------------
# daily 导入
# ------------------------
def import_daily(db, reader, path: Path, market: str, start, end):
    code = code_from_filename(path, market)

    try:
        df = reader.get_df(str(path))
    except Exception as e:
        if "Unknown security type" in str(e):
            print(f"[daily][SKIP] {path.name}: Unknown security type")
            return 0
        print(f"[daily][ERROR] {path.name}: {e}")
        return 0

    if df is None or df.empty:
        return 0

    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    if df.empty:
        return 0

    start_i = day_int(start)
    end_i = day_int(end)

    db.execute(
        text("""
            DELETE FROM daily_kline
            WHERE code=:code AND date BETWEEN :s AND :e
        """),
        {"code": code, "s": start_i, "e": end_i},
    )

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "code": code,
            "date": day_int(r["date"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r.get("volume", 0) or 0),
            "amount": float(r.get("amount", 0) or 0),
            "source": "pytdx_day",
        })

    if rows:
        db.execute(
            text("""
                INSERT INTO daily_kline
                (code,date,open,high,low,close,volume,amount,source)
                VALUES
                (:code,:date,:open,:high,:low,:close,:volume,:amount,:source)
            """),
            rows,
        )

    return len(rows)


# ------------------------
# lc5 导入
# ------------------------
def import_lc5(db, reader, path: Path, market: str, start, end):
    code = code_from_filename(path, market)

    try:
        df = reader.get_df(str(path))
    except Exception as e:
        if "Unknown security type" in str(e):
            print(f"[lc5][SKIP] {path.name}: Unknown security type")
            return 0
        print(f"[lc5][ERROR] {path.name}: {e}")
        return 0

    if df is None or df.empty:
        return 0

    df = df.reset_index()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df[(df["datetime"] >= start) & (df["datetime"] <= end)]
    if df.empty:
        return 0

    start_i = minute_int(pd.to_datetime(start))
    end_i = minute_int(pd.to_datetime(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))

    db.execute(
        text("""
            DELETE FROM minute_kline_period
            WHERE code=:code AND period='5m' AND date BETWEEN :s AND :e
        """),
        {"code": code, "s": start_i, "e": end_i},
    )

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "code": code,
            "period": "5m",
            "date": minute_int(r["datetime"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r.get("volume", 0) or 0),
            "amount": float(r.get("amount", 0) or 0),
            "source": "pytdx_lc5",
        })

    if rows:
        db.execute(
            text("""
                INSERT INTO minute_kline_period
                (code,period,date,open,high,low,close,volume,amount,source)
                VALUES
                (:code,:period,:date,:open,:high,:low,:close,:volume,:amount,:source)
            """),
            rows,
        )

    return len(rows)


# ------------------------
# 主入口
# ------------------------
def main():
    args = parse_args()

    if not args.daily and not args.lc5:
        print("必须指定 --daily 或 --lc5")
        sys.exit(1)

    root = Path(args.root)
    start = pd.to_datetime(args.start)
    end = pd.to_datetime(args.end)

    markets = [m.strip() for m in args.markets.split(",")]

    daily_reader = TdxDailyBarReader()
    lc5_reader = TdxLCMinBarReader()

    total_daily = 0
    total_lc5 = 0

    with SessionLocal() as db:
        for market in markets:
            if args.daily:
                base = root / market / "lday"
                files = sorted(base.glob("*.day"))
                if args.limit_files:
                    files = files[:args.limit_files]

                for f in files:
                    total_daily += import_daily(db, daily_reader, f, market, start, end)

                db.commit()

            if args.lc5:
                base = root / market / "fzline"
                files = sorted(base.glob("*.lc5"))
                if args.limit_files:
                    files = files[:args.limit_files]

                for f in files:
                    total_lc5 += import_lc5(db, lc5_reader, f, market, start, end)

                db.commit()

    print({
        "daily_rows": total_daily,
        "lc5_rows": total_lc5,
    })


if __name__ == "__main__":
    main()

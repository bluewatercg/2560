#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重算 technical_indicator：daily / 5m / 30m

数据流：读 ClickHouse (kline) → 计算指标 → 写 ClickHouse (technical_indicator)
MySQL 仅管理 job/task 表，不存储行情指标数据。

修复点：
1. 彻底把 pandas/numpy 的 NaN / inf 转成 None
2. 按 code 分批读取和写入，避免一次性把全市场 5m/30m 全读进内存
3. 写入 ClickHouse 而非 MySQL，消除多市场并发死锁

用法：
PYTHONPATH=$PWD python scripts/rebuild_technical_indicator.py --start 2025-10-01 --end 2026-05-06 --market-type sh
"""
from __future__ import annotations

import argparse
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from app.core.market_scope import market_sql_where
from app.db.clickhouse import get_clickhouse


def parse_args():
    p = argparse.ArgumentParser(description="Rebuild technical_indicator for daily/5m/30m")
    p.add_argument('--start', required=True, help='YYYY-MM-DD')
    p.add_argument('--end', required=True, help='YYYY-MM-DD')
    p.add_argument('--market-type', default='all', help='all/sh/sz/sh60/sh68/sz00/sz30')
    p.add_argument('--periods', default='daily,5m,30m', help='daily,5m,30m')
    p.add_argument('--workers', type=int, default=4, help='并发线程数')
    p.add_argument('--limit-codes', type=int, default=None, help='调试用：限制每个周期处理前 N 个 code')
    p.add_argument('--commit-every', type=int, default=50, help='每处理 N 个 code commit 一次')
    return p.parse_args()


def market_where(mt: str) -> str:
    return market_sql_where("code", mt)


def daily_start_int(s: str) -> int:
    return int(pd.to_datetime(s).strftime('%Y%m%d'))


def daily_end_int(s: str) -> int:
    return int(pd.to_datetime(s).strftime('%Y%m%d'))


def minute_start_int(s: str) -> int:
    return int(pd.to_datetime(s).strftime('%Y%m%d000000'))


def minute_end_int(s: str) -> int:
    return int(pd.to_datetime(s).strftime('%Y%m%d235959'))


def clean_scalar(v: Any) -> Any:
    """把 pandas/numpy 标量安全转成 MySQL 可接受的 Python 标量。"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, (np.floating, float)):
        vf = float(v)
        if not math.isfinite(vf):
            return None
        return vf
    if isinstance(v, (np.integer, int)):
        return int(v)
    return v


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values('date').copy()
    for c in ['open', 'high', 'low', 'close', 'volume']:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    df['ma25'] = df['close'].rolling(25).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['ma200'] = df['close'].rolling(200).mean()

    df['ma25_slope_3'] = (df['ma25'] - df['ma25'].shift(3)) / df['ma25'].shift(3) * 100
    df['ma60_slope_3'] = (df['ma60'] - df['ma60'].shift(3)) / df['ma60'].shift(3) * 100

    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs(),
    ], axis=1).max(axis=1)
    df['atr14'] = tr.rolling(14).mean()
    df['atr20_avg'] = tr.rolling(20).mean()

    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ma60'] = df['volume'].rolling(60).mean()
    df['vol_ratio'] = df['vol_ma5'] / df['vol_ma60']
    df['vol_ma5_cross_vol_ma60'] = ((df['vol_ma5'] >= df['vol_ma60']) & (df['vol_ma5'].shift(1) < df['vol_ma60'].shift(1))).astype('float')

    df['price_ma25_deviation_pct'] = (df['close'] - df['ma25']) / df['ma25'] * 100
    df['high_20'] = df['high'].rolling(20).max()
    df['low_20'] = df['low'].rolling(20).min()
    df['low_30'] = df['low'].rolling(30).min()
    df['resistance_level'] = df['high_20']

    amplitude = (df['high'] - df['low']) / df['close'].replace(0, np.nan) * 100
    df['is_abnormal_bar'] = (amplitude > 20).astype(int)
    df['data_quality_status'] = 'normal'
    df.loc[df[['open', 'high', 'low', 'close']].isna().any(axis=1), 'data_quality_status'] = 'missing'
    return df


def get_period_range(period: str, start: str, end: str):
    if period == 'daily':
        return daily_start_int(start), daily_end_int(end)
    return minute_start_int(start), minute_end_int(end)


def input_source(period: str) -> str:
    if period == 'daily':
        return 'vipdoc'
    if period == '5m':
        return 'vipdoc'
    if period == '30m':
        return 'build_from_5m'
    raise ValueError(f"unsupported period={period}")


def select_source_rows(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df.empty:
        return df
    if 'source' in df.columns:
        preferred = df[df['source'] == source].copy()
        if not preferred.empty:
            df = preferred
    return df.sort_values(['date']).drop_duplicates(subset=['date'], keep='last').reset_index(drop=True)


def get_codes(period: str, start_i: int, end_i: int, market_type: str, limit_codes: int | None):
    src = input_source(period)
    # Convert int dates to ClickHouse date strings
    start_s = str(start_i)[:4] + '-' + str(start_i)[4:6] + '-' + str(start_i)[6:8]
    end_s = str(end_i)[:4] + '-' + str(end_i)[4:6] + '-' + str(end_i)[6:8]
    if period == 'daily':
        q = f"SELECT DISTINCT code FROM daily_kline WHERE source='{src}' AND date>='{start_s}' AND date<='{end_s}' AND {market_where(market_type)} ORDER BY code"
    else:
        q = f"SELECT DISTINCT code FROM minute_kline_period WHERE period='{period}' AND source='{src}' AND date>='{start_s}' AND date<='{end_s}' AND {market_where(market_type)} ORDER BY code"
    codes = [r['code'] for r in get_clickhouse().query(q)]
    if limit_codes:
        codes = codes[:limit_codes]
    return codes


def load_one_code(period: str, code: str, start_i: int, end_i: int) -> pd.DataFrame:
    src = input_source(period)
    start_s = str(start_i)[:4] + '-' + str(start_i)[4:6] + '-' + str(start_i)[6:8]
    end_s = str(end_i)[:4] + '-' + str(end_i)[4:6] + '-' + str(end_i)[6:8]
    if period == 'daily':
        q = f"SELECT code,date,source,open,high,low,close,volume FROM daily_kline WHERE code='{code}' AND source='{src}' AND date>='{start_s}' AND date<='{end_s}' ORDER BY date"
    else:
        q = f"SELECT code,date,source,open,high,low,close,volume FROM minute_kline_period WHERE code='{code}' AND period='{period}' AND source='{src}' AND date>='{start_s}' AND date<='{end_s}' ORDER BY date"
    rows = get_clickhouse().query(q)
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    # Convert ClickHouse date strings to int matching MySQL schema
    if not df.empty and 'date' in df.columns:
        if period == 'daily':
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d').astype(int)
        else:
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d%H%M%S').astype(int)
    return select_source_rows(df, src)


def make_records_for_clickhouse(code: str, period: str, ind: pd.DataFrame) -> list[dict]:
    """Same as make_records but formats date as ClickHouse DateTime string."""
    cols = [
        'ma25', 'ma60', 'ma200', 'ma25_slope_3', 'ma60_slope_3',
        'atr14', 'atr20_avg', 'vol_ma5', 'vol_ma60', 'vol_ratio',
        'vol_ma5_cross_vol_ma60', 'price_ma25_deviation_pct',
        'high_20', 'low_20', 'low_30', 'resistance_level',
        'is_abnormal_bar', 'data_quality_status'
    ]
    records = []
    for _, r in ind.iterrows():
        date_val = r['date']
        if period == 'daily':
            date_str = str(date_val)  # YYYYMMDD -> ClickHouse needs "YYYY-MM-DD HH:MM:SS"
            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 00:00:00"
        else:
            date_str = str(date_val)  # YYYYMMDDHHMMSS -> YYYY-MM-DD HH:MM:SS
            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {date_str[8:10]}:{date_str[10:12]}:{date_str[12:14]}"
        rec = {
            'code': code,
            'period': period,
            'date': date_str,
            'source': 'rebuild',
            'stock_status': 'NORMAL',
            'is_st': 0,
        }
        for c in cols:
            rec[c] = clean_scalar(r.get(c))
        rec['vol_ma5_cross_vol_ma60'] = None if rec['vol_ma5_cross_vol_ma60'] is None else int(rec['vol_ma5_cross_vol_ma60'])
        rec['is_abnormal_bar'] = 0 if rec['is_abnormal_bar'] is None else int(rec['is_abnormal_bar'])
        records.append(rec)
    return records


def rebuild_for_code(
    code: str,
    period: str,
    start: str,
    end: str,
    market_type: str,
    start_i: int,
    end_i: int,
    start_s: str,
    end_s: str,
) -> dict:
    """Rebuild indicators for a single code. Thread-safe: each call gets its own CH client."""
    try:
        df = load_one_code(period, code, start_i, end_i)
        if df.empty:
            return {"ok": True, "code": code, "rows": 0, "period": period}

        ind = compute_indicators(df)
        records = make_records_for_clickhouse(code, period, ind)

        ch = get_clickhouse()
        del_q = f"ALTER TABLE {ch.database}.technical_indicator DELETE WHERE code='{code}' AND period='{period}' AND date >= '{start_s}' AND date <= '{end_s}'"
        ch.command(del_q)

        total = 0
        if records:
            ch.insert_batch("technical_indicator", records)
            total = len(records)

        return {"ok": True, "code": code, "rows": total, "period": period}
    except Exception as exc:
        return {"ok": False, "code": code, "rows": 0, "period": period, "error": str(exc)}


def rebuild_period(
    period: str,
    start: str,
    end: str,
    market_type: str,
    limit_codes: int | None,
    commit_every: int,
    workers: int = 0,
    on_result: Optional[Callable[[dict, int, int], None]] = None,
):
    ch = get_clickhouse()
    start_i, end_i = get_period_range(period, start, end)
    print(f"\n=== Rebuild {period} technical_indicator: {start_i} ~ {end_i}, market={market_type} ===")
    total = 0
    codes = get_codes(period, start_i, end_i, market_type, limit_codes)
    print(f"codes={len(codes)}")

    start_s = str(start_i)[:4] + '-' + str(start_i)[4:6] + '-' + str(start_i)[6:8]
    end_s = str(end_i)[:4] + '-' + str(end_i)[4:6] + '-' + str(end_i)[6:8]
    if period != 'daily':
        start_s += ' 00:00:00'
        end_s += ' 23:59:59'

    if workers > 0 and len(codes) > 1:
        # Parallel mode
        completed = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(
                    rebuild_for_code, code, period, start, end, market_type,
                    start_i, end_i, start_s, end_s,
                ): code
                for code in codes
            }
            for fut in as_completed(futs):
                r = fut.result()
                if r["ok"]:
                    total += r["rows"]
                completed += 1
                if on_result:
                    on_result(r, completed, len(codes))
                if completed % commit_every == 0:
                    print(f"{period}: processed {completed}/{len(codes)}, inserted={total}")
    else:
        # Sequential mode (original)
        for idx, code in enumerate(codes, 1):
            r = rebuild_for_code(code, period, start, end, market_type, start_i, end_i, start_s, end_s)
            if r["ok"]:
                total += r["rows"]
            if on_result:
                on_result(r, idx, len(codes))
            if idx % commit_every == 0:
                print(f"{period}: processed {idx}/{len(codes)}, inserted={total}")

    print(f"[OK] {period} inserted: {total}")


def main():
    args = parse_args()
    periods = [p.strip() for p in args.periods.split(',') if p.strip()]
    for p in periods:
        if p not in {'daily', '5m', '30m'}:
            raise SystemExit(f"不支持 period={p}，只能 daily/5m/30m")
        rebuild_period(p, args.start, args.end, args.market_type, args.limit_codes, args.commit_every, workers=args.workers)
    print("\nDONE")


if __name__ == '__main__':
    main()

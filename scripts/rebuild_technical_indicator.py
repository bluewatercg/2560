#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重算 technical_indicator：daily / 5m / 30m

修复点：
1. 彻底把 pandas/numpy 的 NaN / inf 转成 None，避免 pymysql: nan can not be used with MySQL
2. 按 code 分批读取和写入，避免一次性把全市场 5m/30m 全读进内存
3. 适配 2560_schema_v2.4：date 为 BIGINT / INT 数值时间

用法：
PYTHONPATH=$PWD python scripts/rebuild_technical_indicator.py --start 2025-10-01 --end 2026-05-06 --market-type sh
"""
from __future__ import annotations

import argparse
import math
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from app.db.session import SessionLocal


def parse_args():
    p = argparse.ArgumentParser(description="Rebuild technical_indicator for daily/5m/30m")
    p.add_argument('--start', required=True, help='YYYY-MM-DD')
    p.add_argument('--end', required=True, help='YYYY-MM-DD')
    p.add_argument('--market-type', default='all', help='all/sh/sz/sh60/sh68/sz00/sz30')
    p.add_argument('--periods', default='daily,5m,30m', help='daily,5m,30m')
    p.add_argument('--limit-codes', type=int, default=None, help='调试用：限制每个周期处理前 N 个 code')
    p.add_argument('--commit-every', type=int, default=50, help='每处理 N 个 code commit 一次')
    return p.parse_args()


def market_where(mt: str) -> str:
    mt = (mt or 'all').lower()
    if mt == 'sh':
        return "code LIKE 'sh.%'"
    if mt == 'sz':
        return "code LIKE 'sz.%'"
    if mt == 'sh60':
        return "code LIKE 'sh.60%'"
    if mt == 'sh68':
        return "code LIKE 'sh.68%'"
    if mt == 'sz00':
        return "code LIKE 'sz.00%'"
    if mt == 'sz30':
        return "code LIKE 'sz.30%'"
    return "(code LIKE 'sh.%' OR code LIKE 'sz.%')"


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


def source_table(period: str) -> str:
    return 'daily_kline' if period == 'daily' else 'minute_kline_period'


def get_codes(db, period: str, start_i: int, end_i: int, market_type: str, limit_codes: int | None):
    if period == 'daily':
        sql = f"""
            SELECT DISTINCT code
            FROM daily_kline
            WHERE date BETWEEN :s AND :e
              AND {market_where(market_type)}
            ORDER BY code
        """
        params = {'s': start_i, 'e': end_i}
    else:
        sql = f"""
            SELECT DISTINCT code
            FROM minute_kline_period
            WHERE period=:period
              AND date BETWEEN :s AND :e
              AND {market_where(market_type)}
            ORDER BY code
        """
        params = {'period': period, 's': start_i, 'e': end_i}
    codes = [r[0] for r in db.execute(text(sql), params).fetchall()]
    if limit_codes:
        codes = codes[:limit_codes]
    return codes


def load_one_code(db, period: str, code: str, start_i: int, end_i: int) -> pd.DataFrame:
    if period == 'daily':
        sql = """
            SELECT code,date,open,high,low,close,volume
            FROM daily_kline
            WHERE code=:code AND date BETWEEN :s AND :e
            ORDER BY date
        """
        params = {'code': code, 's': start_i, 'e': end_i}
    else:
        sql = """
            SELECT code,date,open,high,low,close,volume
            FROM minute_kline_period
            WHERE code=:code AND period=:period AND date BETWEEN :s AND :e
            ORDER BY date
        """
        params = {'code': code, 'period': period, 's': start_i, 'e': end_i}
    rows = db.execute(text(sql), params).mappings().all()
    return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()


def make_records(code: str, period: str, ind: pd.DataFrame) -> list[dict]:
    cols = [
        'ma25', 'ma60', 'ma200', 'ma25_slope_3', 'ma60_slope_3',
        'atr14', 'atr20_avg', 'vol_ma5', 'vol_ma60', 'vol_ratio',
        'vol_ma5_cross_vol_ma60', 'price_ma25_deviation_pct',
        'high_20', 'low_20', 'low_30', 'resistance_level',
        'is_abnormal_bar', 'data_quality_status'
    ]
    records = []
    for _, r in ind.iterrows():
        rec = {
            'code': code,
            'period': period,
            'date': int(r['date']),
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


def rebuild_period(period: str, start: str, end: str, market_type: str, limit_codes: int | None, commit_every: int):
    start_i, end_i = get_period_range(period, start, end)
    print(f"\n=== Rebuild {period} technical_indicator: {start_i} ~ {end_i}, market={market_type} ===")
    total = 0
    with SessionLocal() as db:
        codes = get_codes(db, period, start_i, end_i, market_type, limit_codes)
        print(f"codes={len(codes)}")
        insert_sql = text("""
            INSERT INTO technical_indicator
            (code,period,date,source,stock_status,is_st,
             ma25,ma60,ma200,ma25_slope_3,ma60_slope_3,
             atr14,atr20_avg,vol_ma5,vol_ma60,vol_ratio,vol_ma5_cross_vol_ma60,
             price_ma25_deviation_pct,high_20,low_20,low_30,resistance_level,
             is_abnormal_bar,data_quality_status)
            VALUES
            (:code,:period,:date,:source,:stock_status,:is_st,
             :ma25,:ma60,:ma200,:ma25_slope_3,:ma60_slope_3,
             :atr14,:atr20_avg,:vol_ma5,:vol_ma60,:vol_ratio,:vol_ma5_cross_vol_ma60,
             :price_ma25_deviation_pct,:high_20,:low_20,:low_30,:resistance_level,
             :is_abnormal_bar,:data_quality_status)
        """)
        for idx, code in enumerate(codes, 1):
            df = load_one_code(db, period, code, start_i, end_i)
            if df.empty:
                continue
            ind = compute_indicators(df)
            records = make_records(code, period, ind)
            db.execute(text("""
                DELETE FROM technical_indicator
                WHERE code=:code AND period=:period AND date BETWEEN :s AND :e
            """), {'code': code, 'period': period, 's': start_i, 'e': end_i})
            if records:
                db.execute(insert_sql, records)
                total += len(records)
            if idx % commit_every == 0:
                db.commit()
                print(f"{period}: processed {idx}/{len(codes)}, inserted={total}")
        db.commit()
    print(f"[OK] {period} inserted: {total}")


def main():
    args = parse_args()
    periods = [p.strip() for p in args.periods.split(',') if p.strip()]
    for p in periods:
        if p not in {'daily', '5m', '30m'}:
            raise SystemExit(f"不支持 period={p}，只能 daily/5m/30m")
        rebuild_period(p, args.start, args.end, args.market_type, args.limit_codes, args.commit_every)
    print("\nDONE")


if __name__ == '__main__':
    main()

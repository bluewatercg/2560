#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可选：用 pytdx.hq 补最近 K 线。

默认获取 category=0 的 5m 和 category=2 的 30m，写入 minute_kline_period。

示例：
python scripts/fill_recent_with_pytdx_hq.py --codes sh.600000,sz.000001 --count 800
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable
from sqlalchemy import inspect, text

try:
    from pytdx.hq import TdxHq_API
except Exception as exc:
    print("ERROR: 未安装 pytdx。请先执行：pip install pytdx")
    print(f"原始错误: {exc}")
    sys.exit(1)

from app.db.session import SessionLocal


def parse_args():
    p = argparse.ArgumentParser(description='Fill recent 5m/30m by pytdx.hq')
    p.add_argument('--codes', required=True, help='逗号分隔，如 sh.600000,sz.000001')
    p.add_argument('--ip', default='119.147.212.81')
    p.add_argument('--port', type=int, default=7709)
    p.add_argument('--count', type=int, default=800)
    p.add_argument('--periods', default='5m,30m', help='5m,30m')
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()


def table_columns(db, table_name: str) -> set[str]:
    return {c['name'] for c in inspect(db.bind).get_columns(table_name)}


def parse_code(code: str) -> tuple[int, str, str]:
    c = code.strip().lower()
    if c.startswith('sh.'):
        return 1, c[3:], c
    if c.startswith('sz.'):
        return 0, c[3:], c
    if c.startswith('sh'):
        return 1, c[2:], 'sh.' + c[2:]
    if c.startswith('sz'):
        return 0, c[2:], 'sz.' + c[2:]
    if c.startswith(('6','9')):
        return 1, c, 'sh.' + c
    return 0, c, 'sz.' + c


def insert_rows(db, rows: list[dict], dry_run: bool):
    if not rows: return 0
    cols = table_columns(db, 'minute_kline_period')
    usable = [k for k in rows[0].keys() if k in cols]
    if dry_run: return len(rows)
    sql = text(f"INSERT INTO minute_kline_period ({','.join(usable)}) VALUES ({','.join(':'+c for c in usable)})")
    db.execute(sql, [{k: r.get(k) for k in usable} for r in rows])
    return len(rows)


def main():
    args = parse_args()
    period_map = {'5m': 0, '30m': 2}
    periods = [p.strip() for p in args.periods.split(',') if p.strip()]
    total = 0
    api = TdxHq_API()
    with SessionLocal() as db:
        with api.connect(args.ip, args.port):
            for raw_code in args.codes.split(','):
                market, pure_code, db_code = parse_code(raw_code)
                for period in periods:
                    category = period_map[period]
                    data = api.to_df(api.get_security_bars(category, market, pure_code, 0, args.count))
                    if data is None or data.empty:
                        print(f"empty: {raw_code} {period}")
                        continue
                    rows = []
                    for _, r in data.iterrows():
                        dt = str(r.get('datetime'))
                        rows.append({
                            'code': db_code, 'period': period, 'date': dt,
                            'open': float(r['open']), 'high': float(r['high']), 'low': float(r['low']), 'close': float(r['close']),
                            'volume': float(r.get('vol', r.get('volume', 0)) or 0), 'amount': float(r.get('amount', 0) or 0),
                            'source': 'pytdx_hq',
                        })
                    if not args.dry_run:
                        dates = [x['date'] for x in rows]
                        db.execute(text("DELETE FROM minute_kline_period WHERE code=:code AND period=:period AND date>=:start AND date<=:end"), {'code': db_code, 'period': period, 'start': min(dates), 'end': max(dates)})
                    total += insert_rows(db, rows, args.dry_run)
            if not args.dry_run: db.commit()
    print(json.dumps({'inserted_rows': total, 'dry_run': args.dry_run}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

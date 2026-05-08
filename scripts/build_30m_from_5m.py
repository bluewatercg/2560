#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 5m 数值型 date(YYYYMMDDHHMMSS) 聚合生成 30m。"""
from __future__ import annotations
import argparse, json
import pandas as pd
from sqlalchemy import inspect, text
from app.db.session import SessionLocal

def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument('--start', required=True)
    p.add_argument('--end', default=None)
    p.add_argument('--market-type', default='all')
    p.add_argument('--limit-codes', type=int, default=None)
    p.add_argument('--dry-run', action='store_true')
    return p.parse_args()

def table_columns(db, table): return {c['name'] for c in inspect(db.bind).get_columns(table)}
def start_i(s): return int(pd.to_datetime(s).strftime('%Y%m%d000000'))
def end_i(s): return int(pd.to_datetime(s).strftime('%Y%m%d235959')) if s else None
def date_to_dt(v): return pd.to_datetime(str(int(v)), format='%Y%m%d%H%M%S')
def dt_to_int(v): return int(pd.to_datetime(v).strftime('%Y%m%d%H%M%S'))

def code_where(mt):
    mt=(mt or 'all').lower()
    if mt=='sh': return "code LIKE 'sh.%'"
    if mt=='sz': return "code LIKE 'sz.%'"
    if mt=='sh60': return "code LIKE 'sh.60%'"
    if mt=='sh68': return "code LIKE 'sh.68%'"
    if mt=='sz00': return "code LIKE 'sz.00%'"
    if mt=='sz30': return "code LIKE 'sz.30%'"
    return "(code LIKE 'sh.%' OR code LIKE 'sz.%')"

def bucket_30m(ts):
    ts=pd.to_datetime(ts); d=ts.normalize()
    eps=[d+pd.Timedelta(hours=10),d+pd.Timedelta(hours=10,minutes=30),d+pd.Timedelta(hours=11),d+pd.Timedelta(hours=11,minutes=30),d+pd.Timedelta(hours=13,minutes=30),d+pd.Timedelta(hours=14),d+pd.Timedelta(hours=14,minutes=30),d+pd.Timedelta(hours=15)]
    for ep in eps:
        if ts<=ep: return ep
    return None

def insert_rows(db, rows, dry):
    if not rows: return 0
    cols=table_columns(db,'minute_kline_period'); usable=[k for k in rows[0] if k in cols]
    if dry: return len(rows)
    db.execute(text(f"INSERT INTO minute_kline_period ({','.join(usable)}) VALUES ({','.join(':'+c for c in usable)})"), [{k:r.get(k) for k in usable} for r in rows])
    return len(rows)

def main():
    a=parse_args(); si=start_i(a.start); ei=end_i(a.end); total=0
    with SessionLocal() as db:
        params={'start':si}; ef=''
        if ei: ef=' AND date<=:end'; params['end']=ei
        codes=[r[0] for r in db.execute(text(f"SELECT DISTINCT code FROM minute_kline_period WHERE period='5m' AND date>=:start{ef} AND {code_where(a.market_type)} ORDER BY code"), params).fetchall()]
        if a.limit_codes: codes=codes[:a.limit_codes]
        for i,code in enumerate(codes,1):
            p={'code':code,'start':si}; q="SELECT code,date,open,high,low,close,volume,amount FROM minute_kline_period WHERE code=:code AND period='5m' AND date>=:start"
            if ei: q+=' AND date<=:end'; p['end']=ei
            q+=' ORDER BY date'
            rows=db.execute(text(q),p).mappings().all()
            if not rows: continue
            df=pd.DataFrame([dict(r) for r in rows]); df['dt']=df['date'].map(date_to_dt); df['bucket']=df['dt'].map(bucket_30m); df=df[df['bucket'].notna()]
            out=[]
            for bucket,g in df.groupby('bucket'):
                g=g.sort_values('dt')
                out.append({'code':code,'period':'30m','date':dt_to_int(bucket),'open':float(g.iloc[0]['open']),'high':float(g['high'].max()),'low':float(g['low'].min()),'close':float(g.iloc[-1]['close']),'volume':float(g['volume'].sum()),'amount':float(g['amount'].sum()),'source':'build_from_5m'})
            if not a.dry_run:
                dp={'code':code,'start':si}; del_sql="DELETE FROM minute_kline_period WHERE code=:code AND period='30m' AND date>=:start"
                if ei: del_sql+=' AND date<=:end'; dp['end']=ei
                db.execute(text(del_sql),dp)
            total+=insert_rows(db,out,a.dry_run)
            if i%100==0:
                if not a.dry_run: db.commit()
                print(f"processed code={i}, 30m_rows={total}")
        if not a.dry_run: db.commit()
    print(json.dumps({'codes':len(codes),'inserted_30m_rows':total,'dry_run':a.dry_run}, ensure_ascii=False, indent=2))
if __name__=='__main__': main()

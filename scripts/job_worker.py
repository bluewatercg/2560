#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json, os, signal, time, traceback, subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STOP = False

def sig(*_):
    global STOP; STOP=True
signal.signal(signal.SIGTERM, sig); signal.signal(signal.SIGINT, sig)

def get_database_url():
    url=os.getenv('DATABASE_URL')
    if url: return url
    host=os.getenv('DB_HOST'); port=os.getenv('DB_PORT','3306'); user=os.getenv('DB_USER'); pwd=os.getenv('DB_PASSWORD',''); name=os.getenv('DB_NAME')
    if not host or not user or not name: raise RuntimeError('Set DATABASE_URL or DB_HOST/DB_USER/DB_NAME')
    return f'mysql+pymysql://{user}:{pwd}@{host}:{port}/{name}?charset=utf8mb4'

def parse_payload(p: Any):
    if isinstance(p, dict): return p
    if isinstance(p, (bytes, bytearray)): p=p.decode('utf-8','ignore')
    if isinstance(p, str) and p.strip():
        try: return json.loads(p)
        except Exception: return {'raw':p}
    return {}

def main():
    en=create_engine(get_database_url(), pool_pre_ping=True, future=True)
    poll=int(os.getenv('JOB_WORKER_POLL_INTERVAL','10'))
    print('[worker] started', flush=True)
    while not STOP:
        try:
            with en.begin() as conn:
                row=conn.execute(text("SELECT * FROM job_queue WHERE status='pending' ORDER BY priority ASC, created_at ASC LIMIT 1 FOR UPDATE")).mappings().first()
                if not row:
                    time.sleep(poll); continue
                job=dict(row)
                conn.execute(text("UPDATE job_queue SET status='running', started_at=NOW(), updated_at=NOW() WHERE id=:id"), {'id':job['id']})
            payload=parse_payload(job.get('payload'))
            env=os.environ.copy(); env['PYTHONPATH']=str(PROJECT_ROOT); env['MARKET']=payload.get('market','all'); env['SHARDS']=str(payload.get('shards',4))
            log=PROJECT_ROOT/'logs'/f"job_worker_{datetime.now():%Y%m%d}.log"; log.parent.mkdir(exist_ok=True)
            script=PROJECT_ROOT/'scripts'/'progress_run_now.py'
            # For queued jobs, reuse tracked runner by creating job_execution through run-now is not ideal; fallback to legacy shell if exists.
            legacy=PROJECT_ROOT/'scripts'/'daily_update_incremental_sharded.sh'
            cmd=['bash', str(legacy)] if legacy.exists() else ['python', str(script)]
            with open(log,'ab') as out: rc=subprocess.run(cmd,cwd=str(PROJECT_ROOT),env=env,stdout=out,stderr=subprocess.STDOUT).returncode
            with en.begin() as conn:
                conn.execute(text("UPDATE job_queue SET status=:s, finished_at=NOW(), updated_at=NOW() WHERE id=:id"), {'id':job['id'], 's':'success' if rc==0 else 'failed'})
        except Exception:
            traceback.print_exc(); time.sleep(poll)
    print('[worker] stopped', flush=True)
if __name__=='__main__': main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path

root = Path(__file__).resolve().parents[1]
main = root / 'app' / 'main.py'
index = root / 'app' / 'static' / 'index.html'

# jobs router 通常已经注册；这里做幂等补齐。
text = main.read_text(encoding='utf-8')
if 'from app.api.jobs import router as jobs_router' not in text:
    # 尽量插入在其他 app.api import 附近
    marker = 'from app.api.strategy2560 import router as strategy_router'
    if marker in text:
        text = text.replace(marker, marker + '\nfrom app.api.jobs import router as jobs_router')
    else:
        text = 'from app.api.jobs import router as jobs_router\n' + text
if 'app.include_router(jobs_router)' not in text:
    marker = 'app.include_router(strategy_router)'
    if marker in text:
        text = text.replace(marker, marker + '\napp.include_router(jobs_router)')
    else:
        text += '\napp.include_router(jobs_router)\n'
main.write_text(text, encoding='utf-8')

html = index.read_text(encoding='utf-8')
if '/static/job_progress_monitor.js' not in html:
    html = html.replace('<script src="/static/app.js"></script>', '<script src="/static/app.js"></script>\n  <script src="/static/job_progress_monitor.js?v=progress1"></script>')
index.write_text(html, encoding='utf-8')
print('OK: job progress monitor patched')

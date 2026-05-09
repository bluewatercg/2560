#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
main = root / 'app' / 'main.py'
index = root / 'app' / 'static' / 'index.html'
req = root / 'requirements.txt'

text = main.read_text(encoding='utf-8')
if 'from app.api.jobs import router as jobs_router' not in text:
    marker = 'from app.api.strategy2560 import router as strategy_router'
    text = text.replace(marker, marker + '\nfrom app.api.jobs import router as jobs_router') if marker in text else 'from app.api.jobs import router as jobs_router\n' + text
if 'app.include_router(jobs_router)' not in text:
    marker = 'app.include_router(strategy_router)'
    text = text.replace(marker, marker + '\napp.include_router(jobs_router)') if marker in text else text + '\napp.include_router(jobs_router)\n'
main.write_text(text, encoding='utf-8')

html = index.read_text(encoding='utf-8')
if '/static/job_progress_monitor.js' not in html:
    html = html.replace('<script src="/static/app.js"></script>', '<script src="/static/app.js"></script>\n  <script src="/static/job_progress_monitor.js?v=progress2"></script>')
index.write_text(html, encoding='utf-8')

if req.exists():
    r = req.read_text(encoding='utf-8')
    if 'pydantic-settings' not in r:
        req.write_text(r.rstrip() + '\npydantic-settings==2.3.4\n', encoding='utf-8')
print('OK: job progress monitor v2 applied')

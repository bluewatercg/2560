#!/usr/bin/env python3
from pathlib import Path
root = Path(__file__).resolve().parents[1]
index = root/'app/static/index.html'
req = root/'requirements.txt'
html = index.read_text(encoding='utf-8')
if '/static/job_progress_monitor.js' not in html:
    html = html.replace('<script src="/static/app.js"></script>', '<script src="/static/app.js"></script>\n  <script src="/static/job_progress_monitor.js?v=parallel1"></script>')
index.write_text(html, encoding='utf-8')
if req.exists():
    r=req.read_text(encoding='utf-8')
    if 'pydantic-settings' not in r:
        req.write_text(r.rstrip()+'\npydantic-settings==2.3.4\n', encoding='utf-8')
print('OK: high performance parallel runner and UI labels applied')

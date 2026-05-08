#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Idempotently patch app/main.py and app/static/index.html to load latest/jobs APIs and jobs_actions.js."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
main = root / 'app' / 'main.py'
index = root / 'app' / 'static' / 'index.html'

text = main.read_text(encoding='utf-8')
if 'from app.api.latest import router as latest_router' not in text:
    text = text.replace('from app.api.data_quality import router as quality_router',
        'from app.api.data_quality import router as quality_router\nfrom app.api.latest import router as latest_router\nfrom app.api.jobs import router as jobs_router')
if 'app.include_router(latest_router)' not in text:
    text = text.replace('app.include_router(quality_router)',
        'app.include_router(quality_router)\napp.include_router(latest_router)\napp.include_router(jobs_router)')
main.write_text(text, encoding='utf-8')

html = index.read_text(encoding='utf-8')
if '/static/jobs_actions.js' not in html:
    html = html.replace('<script src="/static/app.js"></script>',
        '<script src="/static/app.js"></script>\n  <script src="/static/jobs_actions.js"></script>')
index.write_text(html, encoding='utf-8')
print('patched main.py and index.html')

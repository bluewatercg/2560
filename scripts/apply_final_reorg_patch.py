#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]
MARKET_OPTIONS = '<option value="sh">sh 上海</option>\n                  <option value="sz">sz 深圳</option>\n                  <option value="sh60">sh60 沪主板60</option>\n                  <option value="sh68">sh68 科创68</option>\n                  <option value="sz00">sz00 深主板00</option>\n                  <option value="sz30">sz30 创业板30</option>'

def patch_static():
    idx = ROOT / 'app/static/index.html'
    if idx.exists():
        html = idx.read_text(encoding='utf-8')
        if '/static/module_reorg.js' not in html:
            html = html.replace('</body>', '  <script src="/static/module_reorg.js?v=final-reorg-1"></script>\n</body>')
            idx.write_text(html, encoding='utf-8')
            print('OK injected module_reorg.js')
    for name in ['app/static/index.html','app/static/app.js','app/static/jobs_actions.js','app/static/jobs_page_bootstrap.js','app/static/job_progress_monitor.js']:
        p = ROOT / name
        if not p.exists(): continue
        s = p.read_text(encoding='utf-8'); old=s
        s = re.sub(r'(<select[^>]*id=["\']jobMarket["\'][^>]*>)([\s\S]*?)(</select>)', lambda m: m.group(1)+'\n                  '+MARKET_OPTIONS+'\n                '+m.group(3), s)
        s = s.replace('<option value="all">all 全市场</option>', '')
        s = s.replace("? $('jobMarket').value : 'all'", "? $('jobMarket').value : 'sh'")
        s = s.replace("$('jobMarket') ? $('jobMarket').value : 'all'", "$('jobMarket') ? $('jobMarket').value : 'sh'")
        if s != old:
            p.write_text(s, encoding='utf-8')
            print('OK patched market options', name)

def patch_jobs_py():
    p = ROOT / 'app/api/jobs.py'
    if not p.exists(): return
    s = p.read_text(encoding='utf-8'); old=s
    if 'import signal' not in s:
        s = s.replace('import subprocess\n', 'import subprocess\nimport signal\n') if 'import subprocess\n' in s else 'import signal\n'+s
    s = s.replace('UPDATE job_execution SET message=:msg, updated_at=NOW() WHERE id=:id', 'UPDATE job_execution SET pid=:pid, message=:msg, updated_at=NOW() WHERE id=:id')
    s = s.replace('{"id": job_id, "msg": f"started pid={proc.pid}, total={total}"}', '{"id": job_id, "pid": proc.pid, "msg": f"started pid={proc.pid}, total={total}"}')
    if s != old:
        p.write_text(s, encoding='utf-8')
        print('OK patched jobs.py pid/signal')

def main():
    patch_static(); patch_jobs_py(); print('OK final reorg patch applied')
if __name__ == '__main__': main()

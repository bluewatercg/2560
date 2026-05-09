#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = STATIC / "index.html"
JS_PATH = STATIC / "data_import_type_addon.js"

JS = r'''
(function(){
  function $(id){ return document.getElementById(id); }
  function all(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }

  async function postJson(url, body){
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body || {})
    });
    return await r.json();
  }

  async function getJson(url){
    const r = await fetch(url);
    return await r.json();
  }

  function ensureControls(){
    const sourceInput = $('importSourceDir');
    const marketSelect = $('importMarket');
    const result = $('importActionResult');

    if(!sourceInput || !marketSelect || !result) return;

    // 已经加过就不重复加
    if(!$('importType')){
      const typeLabel = document.createElement('label');
      typeLabel.innerHTML = `
        导入内容
        <select id="importType">
          <option value="lday">日线 lday（sh/lday、sz/lday，*.day）</option>
          <option value="5m">5分钟线 5m（sh/fzline、sz/fzline，*.lc5）</option>
          <option value="all">日线 + 5分钟线</option>
        </select>
      `;

      const startLabel = document.createElement('label');
      startLabel.innerHTML = `
        开始日期
        <input id="importStartDate" type="date" />
      `;

      const endLabel = document.createElement('label');
      endLabel.innerHTML = `
        结束日期
        <input id="importEndDate" type="date" />
      `;

      const workerLabel = document.createElement('label');
      workerLabel.innerHTML = `
        并发线程
        <input id="importWorkers" type="number" value="8" min="1" max="64" style="width:90px" />
      `;

      const marketLabel = marketSelect.closest('label');
      if(marketLabel){
        marketLabel.insertAdjacentElement('afterend', typeLabel);
        typeLabel.insertAdjacentElement('afterend', startLabel);
        startLabel.insertAdjacentElement('afterend', endLabel);
        endLabel.insertAdjacentElement('afterend', workerLabel);
      }
    }

    if(!$('build30mBtn')){
      const buildBtn = document.createElement('button');
      buildBtn.id = 'build30mBtn';
      buildBtn.type = 'button';
      buildBtn.textContent = '从5m生成30m';

      const refreshBtn = $('refreshImportBtn');
      if(refreshBtn){
        refreshBtn.insertAdjacentElement('beforebegin', buildBtn);
      }else{
        const filters = sourceInput.closest('.filters') || sourceInput.parentElement.parentElement;
        if(filters) filters.appendChild(buildBtn);
      }
    }

    if(!$('importTypeHelp')){
      const help = document.createElement('div');
      help.id = 'importTypeHelp';
      help.style.cssText = 'margin-top:10px;color:#64748b;font-size:13px;line-height:1.7';
      help.innerHTML = `
        <div><b>日线 lday</b>：扫描 <code>sh/lday</code> 或 <code>sz/lday</code>，写入 <code>daily_kline</code></div>
        <div><b>5分钟线 5m</b>：扫描 <code>sh/fzline</code> 或 <code>sz/fzline</code>，写入 <code>minute_kline_period(period='5m')</code></div>
        <div><b>生成30m</b>：从 <code>minute_kline_period(period='5m')</code> 聚合生成 <code>period='30m'</code></div>
      `;
      result.insertAdjacentElement('beforebegin', help);
    }
  }

  function payload(){
    return {
      source_dir: $('importSourceDir') ? $('importSourceDir').value : '/data/vipdoc',
      market: $('importMarket') ? $('importMarket').value : 'sh',
      import_type: $('importType') ? $('importType').value : 'lday',
      start: $('importStartDate') && $('importStartDate').value ? $('importStartDate').value : null,
      end: $('importEndDate') && $('importEndDate').value ? $('importEndDate').value : null,
      workers: $('importWorkers') ? Number($('importWorkers').value || 8) : 8
    };
  }

  async function loadImportBatches(){
    const table = $('importBatchTable');
    if(!table) return;

    try{
      const rows = await getJson('/api/import/batches?limit=50');
      if(!rows || !rows.length){
        table.innerHTML = '<tbody><tr><td>暂无导入批次</td></tr></tbody>';
        return;
      }

      table.innerHTML =
        '<thead><tr>' +
        ['ID','类型','目录','市场','状态','文件数','成功','失败','记录数','开始时间','结束时间','信息']
          .map(c => `<th>${c}</th>`).join('') +
        '</tr></thead><tbody>' +
        rows.map(r => `
          <tr>
            <td>${r.id ?? '-'}</td>
            <td>${r.import_type ?? '-'}</td>
            <td>${r.source_dir ?? '-'}</td>
            <td>${r.market ?? '-'}</td>
            <td>${r.status ?? '-'}</td>
            <td>${r.total_files ?? '-'}</td>
            <td>${r.success_files ?? '-'}</td>
            <td>${r.failed_files ?? '-'}</td>
            <td>${r.total_rows ?? '-'}</td>
            <td>${r.started_at ?? '-'}</td>
            <td>${r.finished_at ?? '-'}</td>
            <td>${r.message ?? '-'}</td>
          </tr>
        `).join('') +
        '</tbody>';
    }catch(e){}
  }

  async function loadImportFiles(){
    const table = $('importFileTable');
    if(!table) return;

    try{
      const rows = await getJson('/api/import/files?limit=100');
      if(!rows || !rows.length){
        table.innerHTML = '<tbody><tr><td>暂无导入文件明细</td></tr></tbody>';
        return;
      }

      table.innerHTML =
        '<thead><tr>' +
        ['ID','批次ID','文件','市场','状态','导入行数','错误','开始时间','结束时间']
          .map(c => `<th>${c}</th>`).join('') +
        '</tr></thead><tbody>' +
        rows.map(r => `
          <tr>
            <td>${r.id ?? '-'}</td>
            <td>${r.import_batch_id ?? '-'}</td>
            <td>${r.file_path ?? '-'}</td>
            <td>${r.market ?? '-'}</td>
            <td>${r.status ?? '-'}</td>
            <td>${r.rows_imported ?? '-'}</td>
            <td>${r.last_error ?? '-'}</td>
            <td>${r.started_at ?? '-'}</td>
            <td>${r.finished_at ?? '-'}</td>
          </tr>
        `).join('') +
        '</tbody>';
    }catch(e){}
  }

  function bindButtons(){
    const scanBtn = $('scanImportDirBtn');
    const runBtn = $('runImportBtn');
    const buildBtn = $('build30mBtn');
    const refreshBtn = $('refreshImportBtn');
    const out = $('importActionResult');

    if(scanBtn){
      scanBtn.onclick = async function(){
        const p = payload();
        if(out) out.textContent = '正在扫描...';
        try{
          const data = await postJson('/api/import/scan', p);
          if(out) out.textContent = JSON.stringify(data, null, 2);
        }catch(e){
          if(out) out.textContent = '扫描失败：' + (e && e.message ? e.message : String(e));
        }
      };
    }

    if(runBtn){
      runBtn.onclick = async function(){
        const p = payload();
        const label = p.import_type === 'lday'
          ? '日线 lday'
          : p.import_type === '5m'
            ? '5分钟线 5m'
            : '日线 + 5分钟线';

        if(!confirm(
          `确认开始导入？\n\n` +
          `导入内容：${label}\n` +
          `目录：${p.source_dir}\n` +
          `市场：${p.market}\n` +
          `开始日期：${p.start || '-'}\n` +
          `结束日期：${p.end || '-'}\n` +
          `并发线程：${p.workers}\n\n` +
          `注意：这里只导入行情数据，不触发 2560 / 2568 计算。`
        )) return;

        if(out) out.textContent = '正在导入，请稍候...';
        try{
          const data = await postJson('/api/import/run', p);
          if(out) out.textContent = JSON.stringify(data, null, 2);
          await loadImportBatches();
          await loadImportFiles();
        }catch(e){
          if(out) out.textContent = '导入失败：' + (e && e.message ? e.message : String(e));
        }
      };
    }

    if(buildBtn){
      buildBtn.onclick = async function(){
        const p = payload();
        if(!p.start){
          alert('从5m生成30m必须填写开始日期');
          return;
        }

        const body = {
          start: p.start,
          end: p.end,
          market: p.market,
          workers: p.workers
        };

        if(!confirm(
          `确认从 5m 生成 30m？\n\n` +
          `市场：${body.market}\n` +
          `开始日期：${body.start}\n` +
          `结束日期：${body.end || '-'}\n` +
          `并发线程：${body.workers}\n\n` +
          `注意：这里只做周期聚合，不触发 2560 / 2568 计算。`
        )) return;

        if(out) out.textContent = '正在从 5m 生成 30m，请稍候...';
        try{
          const data = await postJson('/api/import/build-30m', body);
          if(out) out.textContent = JSON.stringify(data, null, 2);
          await loadImportBatches();
        }catch(e){
          if(out) out.textContent = '生成30m失败：' + (e && e.message ? e.message : String(e));
        }
      };
    }

    if(refreshBtn){
      refreshBtn.onclick = async function(){
        await loadImportBatches();
        await loadImportFiles();
      };
    }
  }

  function boot(){
    ensureControls();
    bindButtons();
  }

  document.addEventListener('DOMContentLoaded', boot);
  setTimeout(boot, 300);
  setInterval(boot, 1000);
})();
'''

def main():
    STATIC.mkdir(parents=True, exist_ok=True)
    JS_PATH.write_text(JS, encoding="utf-8")

    if not INDEX.exists():
        raise SystemExit("ERROR: app/static/index.html 不存在")

    backup = INDEX.with_suffix(".html.bak_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.write_text(INDEX.read_text(encoding="utf-8"), encoding="utf-8")

    html = INDEX.read_text(encoding="utf-8")

    # 用简单方式删除旧 data_import_type_addon.js 引用，避免正则转义问题
    lines = []
    for line in html.splitlines():
        if "data_import_type_addon.js" not in line:
            lines.append(line)
    html = "\n".join(lines)

    script = '  <script src="/static/data_import_type_addon.js?v=2"></script>'

    if "</body>" in html:
        html = html.replace("</body>", script + "\n</body>")
    else:
        html += "\n" + script + "\n"

    INDEX.write_text(html, encoding="utf-8")

    print("OK: 已新增/修复数据导入类型增强脚本")
    print(f"OK: 已备份 index.html -> {backup}")
    print("OK: 已注入 /static/data_import_type_addon.js?v=2")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from datetime import datetime
import re

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = STATIC / "index.html"
JS_PATH = STATIC / "data_import_page.js"

JS = r'''
(function(){
  function $(id){ return document.getElementById(id); }
  function all(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }

  function switchView(viewName){
    all('.nav-item[data-view]').forEach(x => x.classList.remove('active'));
    all('.view').forEach(v => v.classList.remove('active'));

    const btn = document.querySelector(`.nav-item[data-view="${viewName}"]`);
    if(btn) btn.classList.add('active');

    const view = document.getElementById(`view-${viewName}`);
    if(view) view.classList.add('active');

    const group = btn ? btn.closest('.nav-group') : null;
    if(group) group.classList.remove('collapsed');

    if($('pageTitle')) $('pageTitle').textContent = '数据导入';
    if($('pageSubtitle')) $('pageSubtitle').textContent = '只导入文件夹下的数据，不触发 2560 / 2568 计算';
  }

  function ensureDataImportMenu(){
    const nav = document.querySelector('.nav');
    if(!nav) return;

    if(document.getElementById('navGroupDataImport')) return;

    const group = document.createElement('div');
    group.className = 'nav-group';
    group.id = 'navGroupDataImport';

    group.innerHTML = `
      <button type="button" class="nav-group-title">
        <span>数据导入</span>
        <span class="nav-group-arrow">▾</span>
      </button>
      <div class="nav-sub">
        <button class="nav-item nav-sub-item" data-view="data-update">导入目录扫描</button>
        <button class="nav-item nav-sub-item" data-view="data-import-run">行情文件导入</button>
        <button class="nav-item nav-sub-item" data-view="data-import-batches">导入批次</button>
        <button class="nav-item nav-sub-item" data-view="data-import-logs">导入日志</button>
      </div>
    `;

    const title = group.querySelector('.nav-group-title');
    title.onclick = function(){
      group.classList.toggle('collapsed');
    };

    group.querySelectorAll('.nav-item[data-view]').forEach(btn => {
      btn.onclick = function(){
        switchView('data-update');
      };
    });

    // 放在“市场批量任务”后面；找不到就插到“查询分析”前面；再找不到就追加
    const navGroups = all('.nav-group', nav);
    let inserted = false;

    const marketGroup = navGroups.find(g => (g.textContent || '').includes('市场批量任务'));
    const queryGroup = navGroups.find(g => (g.textContent || '').includes('查询分析'));

    if(marketGroup){
      marketGroup.insertAdjacentElement('afterend', group);
      inserted = true;
    }else if(queryGroup){
      queryGroup.insertAdjacentElement('beforebegin', group);
      inserted = true;
    }

    if(!inserted){
      nav.appendChild(group);
    }
  }

  function ensureDataImportPage(){
    const main = document.querySelector('main.main') || document.querySelector('main') || document.body;
    if(!main || $('view-data-update')) return;

    const section = document.createElement('section');
    section.id = 'view-data-update';
    section.className = 'view';

    section.innerHTML = `
      <div class="panel">
        <div class="panel-head split">
          <div>
            <h3>数据导入</h3>
            <p class="muted">只负责导入文件夹下的数据，不触发 2560 / 2568 计算。</p>
          </div>
        </div>

        <div class="filters" style="gap:8px;flex-wrap:wrap">
          <label>
            导入目录
            <input id="importSourceDir" type="text" value="/data/zd_ciccwm/vipdoc" style="min-width:320px" />
          </label>

          <label>
            市场范围
            <select id="importMarket">
              <option value="sh">sh 上海</option>
              <option value="sz">sz 深圳</option>
              <option value="sh60">sh60 沪主板60</option>
              <option value="sh68">sh68 科创68</option>
              <option value="sz00">sz00 深主板00</option>
              <option value="sz30">sz30 创业板30</option>
            </select>
          </label>

          <button id="scanImportDirBtn">扫描导入目录</button>
          <button id="runImportBtn" class="primary">开始导入</button>
          <button id="refreshImportBtn">刷新导入记录</button>
        </div>

        <pre id="importActionResult" class="json-box">等待操作</pre>
      </div>

      <div class="panel">
        <div class="panel-head split">
          <h3>导入批次</h3>
          <button id="refreshImportBatchesBtn">刷新批次</button>
        </div>
        <div class="table-wrap">
          <table id="importBatchTable"></table>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head split">
          <h3>导入文件明细</h3>
          <button id="refreshImportFilesBtn">刷新文件明细</button>
        </div>
        <div class="table-wrap">
          <table id="importFileTable"></table>
        </div>
      </div>
    `;

    const drawer = $('detailDrawer');
    if(drawer && drawer.parentNode){
      main.insertBefore(section, drawer);
    }else{
      main.appendChild(section);
    }
  }

  async function getJson(url){
    const r = await fetch(url);
    return await r.json();
  }

  async function postJson(url, body){
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body || {})
    });
    return await r.json();
  }

  function cell(v){
    return v === null || v === undefined || v === '' ? '-' : v;
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
            <td>${cell(r.id)}</td>
            <td>${cell(r.import_type)}</td>
            <td>${cell(r.source_dir)}</td>
            <td>${cell(r.market)}</td>
            <td>${cell(r.status)}</td>
            <td>${cell(r.total_files)}</td>
            <td>${cell(r.success_files)}</td>
            <td>${cell(r.failed_files)}</td>
            <td>${cell(r.total_rows)}</td>
            <td>${cell(r.started_at)}</td>
            <td>${cell(r.finished_at)}</td>
            <td>${cell(r.message)}</td>
          </tr>
        `).join('') +
        '</tbody>';
    }catch(e){
      table.innerHTML = '<tbody><tr><td>导入批次接口未实现：GET /api/import/batches</td></tr></tbody>';
    }
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
            <td>${cell(r.id)}</td>
            <td>${cell(r.import_batch_id)}</td>
            <td>${cell(r.file_path)}</td>
            <td>${cell(r.market)}</td>
            <td>${cell(r.status)}</td>
            <td>${cell(r.rows_imported)}</td>
            <td>${cell(r.last_error)}</td>
            <td>${cell(r.started_at)}</td>
            <td>${cell(r.finished_at)}</td>
          </tr>
        `).join('') +
        '</tbody>';
    }catch(e){
      table.innerHTML = '<tbody><tr><td>导入文件接口未实现：GET /api/import/files</td></tr></tbody>';
    }
  }

  function bindButtons(){
    const scanBtn = $('scanImportDirBtn');
    if(scanBtn && !scanBtn.dataset.bound){
      scanBtn.dataset.bound = '1';
      scanBtn.onclick = async function(){
        const source_dir = $('importSourceDir') ? $('importSourceDir').value : '';
        const market = $('importMarket') ? $('importMarket').value : 'sh';

        try{
          const data = await postJson('/api/import/scan', {source_dir, market});
          $('importActionResult').textContent = JSON.stringify(data, null, 2);
        }catch(e){
          $('importActionResult').textContent =
            '扫描接口未实现或调用失败：' + (e && e.message ? e.message : String(e)) +
            '\n\n需要后端实现 POST /api/import/scan';
        }
      };
    }

    const runBtn = $('runImportBtn');
    if(runBtn && !runBtn.dataset.bound){
      runBtn.dataset.bound = '1';
      runBtn.onclick = async function(){
        const source_dir = $('importSourceDir') ? $('importSourceDir').value : '';
        const market = $('importMarket') ? $('importMarket').value : 'sh';

        if(!confirm(`确认开始导入？\n\n目录：${source_dir}\n市场：${market}\n\n注意：数据导入只导入文件，不触发计算。`)) return;

        try{
          const data = await postJson('/api/import/run', {source_dir, market});
          $('importActionResult').textContent = JSON.stringify(data, null, 2);
          await loadImportBatches();
          await loadImportFiles();
        }catch(e){
          $('importActionResult').textContent =
            '导入接口未实现或调用失败：' + (e && e.message ? e.message : String(e)) +
            '\n\n需要后端实现 POST /api/import/run';
        }
      };
    }

    const refreshBtn = $('refreshImportBtn');
    if(refreshBtn && !refreshBtn.dataset.bound){
      refreshBtn.dataset.bound = '1';
      refreshBtn.onclick = async function(){
        await loadImportBatches();
        await loadImportFiles();
      };
    }

    const refreshBatchBtn = $('refreshImportBatchesBtn');
    if(refreshBatchBtn && !refreshBatchBtn.dataset.bound){
      refreshBatchBtn.dataset.bound = '1';
      refreshBatchBtn.onclick = loadImportBatches;
    }

    const refreshFilesBtn = $('refreshImportFilesBtn');
    if(refreshFilesBtn && !refreshFilesBtn.dataset.bound){
      refreshFilesBtn.dataset.bound = '1';
      refreshFilesBtn.onclick = loadImportFiles;
    }
  }

  function boot(){
    ensureDataImportMenu();
    ensureDataImportPage();
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

    # 删除旧 data_import_page 引用，重新注入 v=3，避免缓存和顺序问题
    html = re.sub(
        r'\s*<script\s+src="/static/data_import_page\.js[^"]*     '\n',
        html
    )

    script = '  <script src="/static/data_import_page.js?v=3"></script>'

    if "</body>" in html:
      html = html.replace("</body>", script + "\n</body>")
    else:
      html += "\n" + script + "\n"

    INDEX.write_text(html, encoding="utf-8")

    print("OK: 已创建/覆盖 app/static/data_import_page.js")
    print(f"OK: 已备份 index.html -> {backup}")
    print("OK: 已重新注入 /static/data_import_page.js?v=3")

if __name__ == "__main__":
    main()

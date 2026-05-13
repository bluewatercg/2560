
(function(){
  function $(id){ return document.getElementById(id); }
  function all(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }
  let importWatchTimer = null;
  let activeImportBatchId = null;
  let activeImportProgressUrl = null;
  let activeImportMode = 'check';

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

  function switchView(viewName){
    const modeByView = {
      'data-update': 'check',
      'data-import-run': 'run',
      'data-import-batches': 'batches',
      'data-import-logs': 'batches'
    };
    activeImportMode = modeByView[viewName] || 'check';

    all('.nav-item[data-view]').forEach(x => x.classList.remove('active'));
    all('.view').forEach(v => v.classList.remove('active'));

    const navBtn = document.querySelector(`.nav-item[data-view="${viewName}"]`);
    if(navBtn) navBtn.classList.add('active');

    const targetViewName = modeByView[viewName] ? 'data-update' : viewName;
    const view = document.getElementById(`view-${targetViewName}`);
    if(view) view.classList.add('active');

    updateImportMode();
  }

  function ensureDataImportPage(){
    const main = document.querySelector('main.main') || document.querySelector('main') || document.body;
    if(!main || $('view-data-update')) return;

    const section = document.createElement('section');
    section.id = 'view-data-update';
    section.className = 'view';

    section.innerHTML = `
      <div class="panel import-panel import-panel-main">
        <div class="panel-head split">
          <div>
            <h3 id="importPanelTitle">导入前检查</h3>
            <p id="importPanelSubtitle" class="muted">扫描服务器上的 /data/vipdoc 源文件范围，不写数据库。</p>
          </div>
        </div>

        <div class="filters" style="gap:8px;flex-wrap:wrap">
          <label class="import-field import-field-source">
            导入目录
            <input id="importSourceDir" type="text" value="/data/vipdoc" style="min-width:320px" title="Docker 部署默认挂载路径：/data/vipdoc" />
          </label>

          <label class="import-field import-field-market">
            市场范围
            <select id="importMarket">
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

        <div id="fullHistoryGuard" class="full-history-guard" style="display:none">
          <label>
            <input id="confirmFullHistoryImportCheckbox" type="checkbox" />
            我确认执行全量历史导入，可能写入数百万/千万行
          </label>
        </div>

        <pre id="importLiveStatus" class="json-box">暂无选中的导入批次</pre>
        <pre id="importActionResult" class="json-box">等待操作</pre>
      </div>

      <div class="panel import-panel import-panel-batches">
        <div class="panel-head split">
          <h3>导入批次</h3>
          <div class="filters" style="gap:8px;flex-wrap:wrap">
            <label>
              日志类型
              <select id="importBatchTypeFilter">
                <option value="vipdoc">行情导入</option>
                <option value="build_30m">30m 构建</option>
                <option value="rebuild_indicator">指标重算</option>
                <option value="all">全部</option>
              </select>
            </label>
            <button id="refreshImportBatchesBtn">刷新批次</button>
          </div>
        </div>
        <div class="table-wrap">
          <table id="importBatchTable"></table>
        </div>
      </div>

      <div class="panel import-panel import-panel-execution">
        <div class="panel-head split">
          <div>
            <h3>任务执行记录（job_execution）</h3>
            <p class="muted" style="margin:4px 0 0">点选上方批次后，这里只显示该批次对应的后台执行记录。</p>
          </div>
        </div>
        <div class="table-wrap">
          <table id="importExecutionTable"></table>
        </div>
      </div>

      <div class="panel import-panel import-panel-shards">
        <div class="panel-head split">
          <div>
            <h3>Shard 汇总（每行是一组并发线程）</h3>
            <p class="muted" style="margin:4px 0 0">行情导入按文件状态和并发组汇总；30m/指标重算按执行记录进度汇总。</p>
          </div>
        </div>
        <div class="table-wrap">
          <table id="importShardTable"></table>
        </div>
      </div>

      <div id="importFilePanel" class="panel import-panel import-panel-files" style="display:none">
        <div class="panel-head split">
          <div>
            <h3>文件明细 / 失败信息</h3>
            <p class="muted" style="margin:4px 0 0">默认隐藏；只在需要定位失败文件时展开。</p>
          </div>
          <div class="filters" style="gap:8px;flex-wrap:wrap">
            <button id="toggleImportFilesBtn" type="button">隐藏文件明细</button>
            <button id="refreshImportFilesBtn" type="button">刷新文件明细</button>
          </div>
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

  function cell(v){
    return v === null || v === undefined || v === '' ? '-' : v;
  }

  function isDataImportActive(){
    const active = document.querySelector('.nav-item.active[data-view]');
    const activeView = active ? active.dataset.view || '' : '';
    return ['data-update','data-import-run','data-import-batches','data-import-logs'].includes(activeView)
      || Boolean($('view-data-update') && $('view-data-update').classList.contains('active'));
  }

  function updateImportMode(updateChrome){
    const shouldUpdateChrome = updateChrome !== false && isDataImportActive();
    const titleMap = {
      check: ['导入前检查', '扫描 /data/vipdoc 源文件范围，不写数据库。'],
      run: ['发起导入', '选择市场、日线/5m/all、日期范围和并发线程，提交后台导入任务。'],
      batches: ['批次/日志', '查看导入批次，点选后追踪 job_execution 与 Shard 汇总；文件明细按需展开。']
    };
    const [title, subtitle] = titleMap[activeImportMode] || titleMap.check;
    if(shouldUpdateChrome && $('pageTitle')) $('pageTitle').textContent = title;
    if(shouldUpdateChrome && $('pageSubtitle')) $('pageSubtitle').textContent = subtitle;
    if($('importPanelTitle')) $('importPanelTitle').textContent = title;
    if($('importPanelSubtitle')) $('importPanelSubtitle').textContent = subtitle;

    const scanBtn = $('scanImportDirBtn');
    const runBtn = $('runImportBtn');
    const refreshBtn = $('refreshImportBtn');
    const buildBtn = $('build30mBtn');
    const rebuildBtn = $('rebuildIndicatorsBtn');
    const liveStatus = $('importLiveStatus');
    const actionResult = $('importActionResult');
    const fullGuard = $('fullHistoryGuard');

    const showRun = activeImportMode === 'run';
    const showBatches = activeImportMode === 'batches';

    if(scanBtn) scanBtn.style.display = activeImportMode === 'check' ? '' : 'none';
    if(runBtn) runBtn.style.display = showRun ? '' : 'none';
    if(refreshBtn) refreshBtn.style.display = showBatches ? '' : 'none';
    if(buildBtn) buildBtn.style.display = showBatches ? '' : 'none';
    if(rebuildBtn) rebuildBtn.style.display = showBatches ? '' : 'none';
    if(liveStatus) liveStatus.style.display = showBatches ? '' : 'none';
    if(actionResult) actionResult.style.display = showBatches || activeImportMode === 'check' || showRun ? '' : 'none';
    if(fullGuard) fullGuard.style.display = showRun ? '' : 'none';
    const toggleImportFilesBtn = $('toggleImportFilesBtn');
    if(toggleImportFilesBtn) toggleImportFilesBtn.textContent = '查看文件明细';

    all('.import-panel-batches,.import-panel-execution,.import-panel-shards').forEach(el => {
      el.style.display = showBatches ? '' : 'none';
    });
    const importFilePanel = $('importFilePanel');
    if(importFilePanel && !showBatches) importFilePanel.style.display = 'none';

    all('#importType,#importStartDate,#importEndDate,#importWorkers').forEach(el => {
      const label = el.closest('label');
      if(label) label.style.display = showRun || showBatches ? '' : 'none';
    });
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
        ['ID','类型','目录','市场','状态','并发','进度','数据范围','文件数','成功','失败','记录数','开始时间','结束时间','信息']
          .map(c => `<th>${c}</th>`).join('') +
        '</tr></thead><tbody>' +
        rows.map(r => {
          const done = Number(r.success_files || 0) + Number(r.failed_files || 0);
          const total = Number(r.total_files || 0);
          const progress = total ? `${done}/${total} (${((done * 100) / total).toFixed(1)}%)` : '-';
          const selected = String(activeImportBatchId || '') === String(r.id || '');
          return `
          <tr data-import-batch-id="${cell(r.id)}" data-progress-url="${r.progress_url || ''}" style="cursor:pointer;${selected ? 'background:#eff6ff' : ''}" title="点击追踪这个导入批次">
            <td>${cell(r.id)}</td>
            <td>${cell(r.import_type)}</td>
            <td>${cell(r.source_dir)}</td>
            <td>${cell(r.market)}</td>
            <td>${cell(r.status)}</td>
            <td>${cell(r.workers)}</td>
            <td>${progress}</td>
            <td>${cell(r.data_range)}</td>
            <td>${cell(r.total_files)}</td>
            <td>${cell(r.success_files)}</td>
            <td>${cell(r.failed_files)}</td>
            <td>${cell(r.total_rows)}</td>
            <td>${cell(r.started_at)}</td>
            <td>${cell(r.finished_at)}</td>
            <td>${cell(r.message)}</td>
          </tr>
        `;
        }).join('') +
        '</tbody>';
    }catch(e){
      table.innerHTML = '<tbody><tr><td>导入批次接口未实现：GET /api/import/batches</td></tr></tbody>';
    }
  }

  async function loadImportFiles(batchId){
    const table = $('importFileTable');
    if(!table) return;

    try{
      const url = '/api/import/files?limit=100' + (batchId ? '&batch_id=' + encodeURIComponent(batchId) : '');
      const rows = await getJson(url);

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

  function renderLiveStatus(d, job){
    const box = $('importLiveStatus');
    if(!box) return;
    if(!d){
      box.textContent = '暂无正在导入的批次';
      return;
    }
    const total = Number((job && job.total) || d.job_progress_total || d.total_files || 0);
    const done = Number((job && job.done) || d.job_progress_current || d.done_files || 0);
    const percentValue = total ? (done * 100 / total) : Number((job && job.percent) ?? d.progress_percent ?? 0);
    const percent = total ? percentValue.toFixed(2) + '%' : '-';
    const status = (job && job.status) || d.job_status || d.status || '-';
    const workers = (job && job.shards) || d.workers || '-';
    const runningFiles = d.running_files ?? '-';
    box.textContent =
      `当前批次：#${d.id}\n` +
      `任务：#${d.job_id || (job && job.id) || '-'} ${d.progress_url || activeImportProgressUrl || ''}\n` +
      `状态：${status}\n` +
      `并发：${workers}，运行中文件：${runningFiles}\n` +
      `进度：${done}/${total} (${percent})\n` +
      `成功：${(job && job.success_count) ?? d.job_success_count ?? d.success_files ?? 0}，失败：${(job && job.failed_count) ?? d.job_failed_count ?? d.failed_files ?? 0}，当前：${(job && job.current_code) || d.current_code || '-'}\n` +
      `批次结果：成功 ${d.success_files || 0}，失败 ${d.failed_files || 0}，记录数 ${d.total_rows || 0}\n` +
      `数据范围：${d.data_range || '-'}\n` +
      `更新时间：${d.updated_at || '-'}`;
  }

  async function refreshImportWatch(batchId, progressUrl){
    if(!batchId) return;
    const d = await getJson('/api/import/batches/' + encodeURIComponent(batchId));
    const url = progressUrl || (d && d.progress_url);
    let job = null;
    if(url){
      job = await getJson(url);
      activeImportProgressUrl = url;
    }
    renderLiveStatus(d, job);
    await loadImportBatches();
    await loadImportFiles(batchId);
    const status = (job && job.status) || (d && d.job_status) || (d && d.status);
    if(status && !['queued', 'pending', 'running'].includes(status)){
      stopImportWatch();
      loadImportBatches().catch(() => {});
    }
  }

  function startImportWatch(batchOrId, progressUrl){
    if(window.startDataImportWatch && window.startDataImportWatch !== startImportWatch){
      window.startDataImportWatch(batchOrId, progressUrl);
      return;
    }
    stopImportWatch();
    const batchId = typeof batchOrId === 'object' ? batchOrId.import_batch_id : batchOrId;
    activeImportProgressUrl = progressUrl || (typeof batchOrId === 'object' ? batchOrId.progress_url : null);
    activeImportBatchId = batchId;
    refreshImportWatch(batchId, activeImportProgressUrl).catch(() => {});
    importWatchTimer = setInterval(function(){
      refreshImportWatch(batchId, activeImportProgressUrl).catch(() => {});
    }, 5000);
  }

  function stopImportWatch(){
    if(importWatchTimer){
      clearInterval(importWatchTimer);
      importWatchTimer = null;
    }
    activeImportBatchId = null;
    activeImportProgressUrl = null;
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
          const summary =
            `源文件数据范围：${data.file_data_range || '-'}\n` +
            `文件数：${data.total_files || 0}\n` +
            `扫描目录：${(data.scan_dirs || []).join(', ') || '-'}\n\n`;
          $('importActionResult').textContent = summary + JSON.stringify(data, null, 2);
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
        const start = $('importStartDate') && $('importStartDate').value ? $('importStartDate').value : null;
        const end = $('importEndDate') && $('importEndDate').value ? $('importEndDate').value : null;
        const import_type = $('importType') ? $('importType').value : 'lday';
        const rangeText = (start || end) ? `${start || '最早'} 至 ${end || '最新'}` : '全量历史（未填写开始/结束日期）';

        if(!start && !end && !($('confirmFullHistoryImportCheckbox') && $('confirmFullHistoryImportCheckbox').checked)){
          alert('开始日期和结束日期为空时，必须先勾选“我确认执行全量历史导入”。');
          return;
        }
        if(!confirm(`确认开始导入？\n\n目录：${source_dir}\n市场：${market}\n导入内容：${import_type}\n导入范围：${rangeText}\n\n注意：数据导入只导入文件，不触发计算。`)) return;

        try{
          const data = await postJson('/api/import/run', {source_dir, market, import_type, start, end});
          $('importActionResult').textContent = JSON.stringify(data, null, 2);
          if(data && data.import_batch_id){
            startImportWatch(data);
          }else{
            await loadImportBatches();
            await loadImportFiles();
          }
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
        if(activeImportBatchId){
          await refreshImportWatch(activeImportBatchId, activeImportProgressUrl);
        }else{
          await loadImportFiles(activeImportBatchId);
        }
      };
    }

  }

  function boot(){
    ensureDataImportPage();
    bindButtons();
    const active = document.querySelector('.nav-item.active[data-view]');
    if(active && ['data-update','data-import-run','data-import-batches','data-import-logs'].includes(active.dataset.view || '')){
      switchView(active.dataset.view);
    }else{
      updateImportMode(false);
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
  setTimeout(boot, 300);
  window.updateDataImportMode = updateImportMode;
  window.showDataImportView = switchView;
})();

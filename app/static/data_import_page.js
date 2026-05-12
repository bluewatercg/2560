
(function(){
  function $(id){ return document.getElementById(id); }
  function all(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }
  let importWatchTimer = null;
  let activeImportBatchId = null;
  let activeImportProgressUrl = null;

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
    all('.nav-item[data-view]').forEach(x => x.classList.remove('active'));
    all('.view').forEach(v => v.classList.remove('active'));

    const navBtn = document.querySelector(`.nav-item[data-view="${viewName}"]`);
    if(navBtn) navBtn.classList.add('active');

    const view = document.getElementById(`view-${viewName}`);
    if(view) view.classList.add('active');

    if($('pageTitle')) $('pageTitle').textContent = '数据导入';
    if($('pageSubtitle')) $('pageSubtitle').textContent = '只导入文件夹下的数据，不触发 2560 / 2568 计算';
  }

  function makeDataImportGroup(){
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

    const titleBtn = group.querySelector('.nav-group-title');
    titleBtn.onclick = function(){
      group.classList.toggle('collapsed');
    };

    group.querySelectorAll('.nav-item[data-view]').forEach(btn => {
      btn.onclick = function(){
        switchView('data-update');
      };
    });

    // 尽量放在“市场批量任务”后面；找不到就追加
    const groups = all('.nav-group', nav);
    if(groups.length >= 2){
      groups[1].insertAdjacentElement('afterend', group);
    }else{
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
            <p class="muted">先用中金客户端下载并同步到 18 服务器，再扫描源文件日期，按目标交易日导入；这里只导入数据，不触发 2560 / 2568 计算。</p>
          </div>
        </div>

        <div class="filters" style="gap:8px;flex-wrap:wrap">
          <label>
            导入目录
            <input id="importSourceDir" type="text" value="/data/vipdoc" style="min-width:320px" title="Docker 部署默认挂载路径：/data/vipdoc" />
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

        <pre id="importLiveStatus" class="json-box">暂无正在导入的批次</pre>
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
        ['ID','类型','目录','市场','状态','并发','进度','数据范围','文件数','成功','失败','记录数','开始时间','结束时间','信息']
          .map(c => `<th>${c}</th>`).join('') +
        '</tr></thead><tbody>' +
        rows.map(r => {
          const done = Number(r.success_files || 0) + Number(r.failed_files || 0);
          const total = Number(r.total_files || 0);
          const progress = total ? `${done}/${total} (${((done * 100) / total).toFixed(1)}%)` : '-';
          return `
          <tr>
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
    const percentValue = (job && job.percent !== undefined) ? Number(job.percent) : Number(d.progress_percent || 0);
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
    }
  }

  function startImportWatch(batchOrId, progressUrl){
    stopImportWatch();
    const batchId = typeof batchOrId === 'object' ? batchOrId.import_batch_id : batchOrId;
    activeImportProgressUrl = progressUrl || (typeof batchOrId === 'object' ? batchOrId.progress_url : null);
    activeImportBatchId = batchId;
    refreshImportWatch(batchId, activeImportProgressUrl).catch(() => {});
    importWatchTimer = setInterval(function(){
      refreshImportWatch(batchId, activeImportProgressUrl).catch(() => {});
    }, 2000);
  }

  function stopImportWatch(){
    if(importWatchTimer){
      clearInterval(importWatchTimer);
      importWatchTimer = null;
    }
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

        if(!confirm(`确认开始导入？\n\n目录：${source_dir}\n市场：${market}\n导入内容：${import_type}\n导入范围：${rangeText}\n\n注意：数据导入只导入文件，不触发计算。`)) return;
        if(!start && !end && !confirm(`你正在执行全量历史导入。\n\n这会读取源文件中的全部历史记录，可能写入数百万/千万行。\n如果只想导入某个交易日，请先填写开始日期和结束日期。\n\n是否确认继续全量历史导入？`)) return;

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
        await loadImportFiles(activeImportBatchId);
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
      refreshFilesBtn.onclick = function(){ loadImportFiles(activeImportBatchId); };
    }
  }

  function boot(){
    makeDataImportGroup();
    ensureDataImportPage();
    bindButtons();
  }

  document.addEventListener('DOMContentLoaded', boot);
  setTimeout(boot, 300);
  setInterval(boot, 1000);
})();

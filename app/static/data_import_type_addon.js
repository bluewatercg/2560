
(function(){
  function $(id){ return document.getElementById(id); }
  function all(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }
  let importWatchTimer = null;
  let activeImportBatchId = null;
  let activeImportProgressUrl = null;

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
        <div><b>盘后前置</b>：先用 Windows 中金客户端下载到 <code>E:\\zd_ciccwm\\vipdoc</code>，再运行 <code>scripts/sync_vipdoc_to_server.ps1</code> 上传到 18 服务器。</div>
        <div><b>检查日期</b>：点“扫描导入目录”，确认“源文件数据范围”已到目标交易日；导入批次里的“数据范围”表示数据库已导入到哪天。</div>
        <div><b>步骤 1</b>：导入 <code>lday</code> 到 <code>daily_kline</code></div>
        <div><b>步骤 2</b>：导入 <code>fzline/*.lc5</code> 到 <code>minute_kline_period(period='5m')</code></div>
        <div><b>步骤 3</b>：从 <code>5m</code> 聚合生成 <code>period='30m'</code></div>
        <div><b>步骤 4</b>：重算指标，再跑 <code>2560</code> 分析</div>
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
        ['ID','类型','目录','市场','状态','并发','进度','数据范围','文件数','成功','失败','记录数','开始时间','结束时间','信息']
          .map(c => `<th>${c}</th>`).join('') +
        '</tr></thead><tbody>' +
        rows.map(r => {
          const done = Number(r.success_files || 0) + Number(r.failed_files || 0);
          const total = Number(r.total_files || 0);
          const progress = total ? `${done}/${total} (${((done * 100) / total).toFixed(1)}%)` : '-';
          return `
          <tr>
            <td>${r.id ?? '-'}</td>
            <td>${r.import_type ?? '-'}</td>
            <td>${r.source_dir ?? '-'}</td>
            <td>${r.market ?? '-'}</td>
            <td>${r.status ?? '-'}</td>
            <td>${r.workers ?? '-'}</td>
            <td>${progress}</td>
            <td>${r.data_range ?? '-'}</td>
            <td>${r.total_files ?? '-'}</td>
            <td>${r.success_files ?? '-'}</td>
            <td>${r.failed_files ?? '-'}</td>
            <td>${r.total_rows ?? '-'}</td>
            <td>${r.started_at ?? '-'}</td>
            <td>${r.finished_at ?? '-'}</td>
            <td>${r.message ?? '-'}</td>
          </tr>
        `;
        }).join('') +
        '</tbody>';
    }catch(e){}
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
          if(out){
            const summary =
              `源文件数据范围：${data.file_data_range || '-'}\n` +
              `文件数：${data.total_files || 0}\n` +
              `扫描目录：${(data.scan_dirs || []).join(', ') || '-'}\n\n`;
            out.textContent = summary + JSON.stringify(data, null, 2);
          }
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
          if(data && data.import_batch_id){
            startImportWatch(data);
          }else{
            await loadImportBatches();
            await loadImportFiles();
          }
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
          if(data && data.import_batch_id){
            startImportWatch(data);
          }else{
            await loadImportBatches();
          }
        }catch(e){
          if(out) out.textContent = '生成30m失败：' + (e && e.message ? e.message : String(e));
        }
      };
    }

    if(refreshBtn){
      refreshBtn.onclick = async function(){
        await loadImportBatches();
        await loadImportFiles(activeImportBatchId);
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

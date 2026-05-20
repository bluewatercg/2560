
(function(){
  function $(id){ return document.getElementById(id); }
  function all(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }
  let importWatchTimer = null;
  let activeImportLanes = {};  // { sh60: {batchId, jobId, progressUrl}, sh68: {...}, ... }
  let activeImportBatchId = null;
  let activeImportProgressUrl = null;
  let autoWatchBootstrapped = false;

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

  function pad2(n){
    return String(n).padStart(2, '0');
  }

  function dateInputValueFromUtc(d){
    return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
  }

  function defaultChinaMarketDate(now){
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23'
    }).formatToParts(now || new Date()).reduce((acc, p) => {
      if(p.type !== 'literal') acc[p.type] = p.value;
      return acc;
    }, {});
    let d = new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)));
    const minutes = Number(parts.hour || 0) * 60 + Number(parts.minute || 0);
    if(minutes < 15 * 60 + 5){
      d = new Date(d.getTime() - 86400000);
    }
    while([0, 6].includes(d.getUTCDay())){
      d = new Date(d.getTime() - 86400000);
    }
    return dateInputValueFromUtc(d);
  }

  function setImportDateDefaults(){
    const start = $('importStartDate');
    const end = $('importEndDate');
    if(!start || !end || start.dataset.defaulted === '1') return;
    const d = defaultChinaMarketDate();
    if(!start.value) start.value = d;
    if(!end.value) end.value = d;
    start.dataset.defaulted = '1';
    end.dataset.defaulted = '1';
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
          <option value="all">日线 + 5分钟线（不含1分钟线）</option>
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

    if(!$('rebuildIndicatorsBtn')){
      const rebuildBtn = document.createElement('button');
      rebuildBtn.id = 'rebuildIndicatorsBtn';
      rebuildBtn.type = 'button';
      rebuildBtn.textContent = '重算指标';
      const buildBtn = $('build30mBtn');
      if(buildBtn){
        buildBtn.insertAdjacentElement('afterend', rebuildBtn);
      }
    }

    if(!$('importTypeHelp')){
      const help = document.createElement('div');
      help.id = 'importTypeHelp';
      help.style.cssText = 'margin-top:10px;color:#94A3B8;font-size:13px;line-height:1.7';
      help.innerHTML = `
        <div><b>盘后前置</b>：先用 Windows 中金客户端“盘后数据下载”到 <code>E:\\zd_ciccwm\\vipdoc</code>，再执行“中金数据上传服务器”，把 VIPDOC 上传到 18 服务器。</div>
        <div class="muted">本页面只处理服务器上的 <code>/data/vipdoc</code>，不负责下载行情。</div>
        <div><b>检查日期</b>：点“扫描导入目录”，确认“源文件数据范围”已到目标交易日；导入批次里的“数据范围”表示数据库已导入到哪天。</div>
        <div><b>导入内容</b>：<code>all</code> 只表示日线 + 5分钟线，不包含 1分钟线。</div>
        <div><b>日期范围怎么选</b>：默认日期按北京时间盘后交易日预设；平时更新选当天即可，补历史才拉长开始日期。</div>
        <div><b>日线/5m导入：</b>日常增量开始日期=结束日期=目标交易日；补漏时开始日期选缺失第一天，结束日期选目标交易日。</div>
        <div><b>从5m生成30m：日常增量选当天</b>；首次补历史或30m不足25根时，开始日期至少往前覆盖25个以上30m交易段，建议从2026-04-01到目标交易日。</div>
        <div><b>重算指标：时间范围跟30m构建保持一致</b>；如果补了历史30m，就用同一段日期重算 <code>daily,5m,30m</code> 指标。</div>
        <div><b>步骤 1</b>：导入 <code>lday</code> 到 <code>daily_kline</code></div>
        <div><b>步骤 2</b>：导入 <code>fzline/*.lc5</code> 到 <code>minute_kline_period(period='5m')</code></div>
        <div><b>步骤 3</b>：从 <code>5m</code> 聚合生成 <code>period='30m'</code></div>
        <div><b>步骤 4</b>：重算指标；指标完成后，到“计算任务 → 创建批量任务”执行 2560 扫描</div>
      `;
      result.insertAdjacentElement('beforebegin', help);
    }
    setImportDateDefaults();
    renderImportExecution(null, null);
    renderImportShardSummary(null, null, []);
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

  function importRangeText(p){
    if(p.start || p.end){
      return `${p.start || '最早'} 至 ${p.end || '最新'}`;
    }
    return '全量历史（未填写开始/结束日期）';
  }

  function confirmFullHistoryImport(p){
    if(p.start || p.end) return true;
    const checkbox = $('confirmFullHistoryImportCheckbox');
    if(!checkbox || !checkbox.checked){
      alert('开始日期和结束日期为空时，必须先勾选“我确认执行全量历史导入”。');
      return false;
    }
    return true;
  }

  function canCancelImportStatus(status){
    return ['queued', 'pending', 'running', 'cancelling'].includes(String(status || '').toLowerCase());
  }

  function batchTypeFilter(){
    const el = $('importBatchTypeFilter');
    return el ? String(el.value || 'vipdoc') : 'vipdoc';
  }

  function normalizeBatchType(importType){
    const t = String(importType || '').toLowerCase();
    if(['lday', 'daily', '5m', 'lc5', 'fzline', 'all', 'vipdoc'].includes(t)) return 'vipdoc';
    if(t === 'build_30m') return 'build_30m';
    if(t === 'rebuild_indicator') return 'rebuild_indicator';
    return t || 'unknown';
  }

  function batchMatchesFilter(row){
    const filter = batchTypeFilter();
    if(filter === 'all') return true;
    return normalizeBatchType(row && row.import_type) === filter;
  }

  function setBatchTypeFilter(value){
    const el = $('importBatchTypeFilter');
    if(el) el.value = value;
  }

  function batchTypeLabel(importType){
    const normalized = normalizeBatchType(importType);
    if(normalized === 'vipdoc') return importType || '行情导入';
    if(normalized === 'build_30m') return '30m 构建';
    if(normalized === 'rebuild_indicator') return '指标重算';
    return importType || '-';
  }

  function cell(v){
    return v === null || v === undefined || v === '' ? '-' : v;
  }

  function progressBar(done, total){
    const d = Number(done || 0);
    const t = Number(total || 0);
    const percent = t ? Math.min(100, Math.max(0, d * 100 / t)) : 0;
    return `<div style="min-width:220px"><div style="height:8px;background:#334155;border-radius:999px;overflow:hidden"><div style="height:100%;width:${percent.toFixed(1)}%;background:#3B82F6"></div></div><div style="margin-top:4px;font-size:12px;color:#F8FAFC">已完成 ${d} / 总数 ${t || '-'}</div><div style="margin-top:2px;font-size:12px;color:#94A3B8">${t ? percent.toFixed(1) + '%' : '等待后台统计总数'}</div></div>`;
  }

  function renderImportExecution(d, job){
    const table = $('importExecutionTable');
    if(!table) return;
    if(!d || !d.job_id){
      table.innerHTML = '<tbody><tr><td>先点击上方一个导入批次，再查看对应的执行记录</td></tr></tbody>';
      return;
    }
    const progressCurrent = (job && job.done) ?? d.job_progress_current ?? d.done_files;
    const progressTotal = (job && job.total) ?? d.job_progress_total ?? d.total_files;
    table.innerHTML =
      '<thead><tr>' +
      ['执行ID','任务类型','批次ID','市场范围','并发数','状态','完成进度','成功','失败','当前','开始时间','结束时间','信息']
        .map(c => `<th>${c}</th>`).join('') +
      '</tr></thead><tbody>' +
      `<tr>
        <td>${cell(d.job_id)}</td>
        <td>${cell(d.job_type || batchTypeLabel(d.import_type))}</td>
        <td>${cell(d.id)}</td>
        <td>${cell(d.market)}</td>
        <td>${cell((job && job.shards) || d.workers)}</td>
        <td>${cell((job && job.status) || d.job_status || d.status)}</td>
        <td>${progressBar(progressCurrent, progressTotal)}</td>
        <td>${cell((job && job.success_count) ?? d.job_success_count ?? d.success_files)}</td>
        <td>${cell((job && job.failed_count) ?? d.job_failed_count ?? d.failed_files)}</td>
        <td>${cell((job && job.current_code) || d.current_code)}</td>
        <td>${cell(d.job_started_at || d.started_at)}</td>
        <td>${cell(d.job_finished_at || d.finished_at)}</td>
        <td>${cell(d.job_message || d.message)}</td>
      </tr>` +
      '</tbody>';
  }

  function fileShardRows(files, workers){
    const n = Math.max(1, Number(workers || 1));
    const rows = Array.from({length: n}, (_, i) => ({
      shard_id: i + 1,
      total: 0,
      done: 0,
      success_count: 0,
      failed_count: 0,
      running_count: 0,
      pending_count: 0,
      rows_imported: 0,
      current_code: '-',
      last_error: '-'
    }));
    (files || []).forEach((f, idx) => {
      const row = rows[idx % n];
      const status = String(f.status || '').toLowerCase();
      row.total += 1;
      row.rows_imported += Number(f.rows_imported || 0);
      if(status === 'success'){
        row.done += 1;
        row.success_count += 1;
      }else if(status === 'failed'){
        row.done += 1;
        row.failed_count += 1;
        row.last_error = f.last_error || row.last_error;
      }else if(status === 'running'){
        row.running_count += 1;
        row.current_code = String(f.file_path || '').split('/').pop() || '-';
      }else{
        row.pending_count += 1;
      }
    });
    return rows.filter(r => r.total > 0 || n <= 16);
  }

  function renderImportShardSummary(d, job, files){
    const table = $('importShardTable');
    if(!table) return;
    if(!d){
      table.innerHTML = '<tbody><tr><td>先点击上方一个导入批次，再查看线程汇总</td></tr></tbody>';
      return;
    }
    const workers = Number((job && job.shards) || d.workers || 1);
    let rows = [];
    if(files && files.length){
      rows = fileShardRows(files, workers);
    }else{
      const status = String((job && job.status) || d.job_status || d.status || '').toLowerCase();
      const done = Number((job && job.done) ?? d.job_progress_current ?? d.done_files ?? 0);
      const total = Number((job && job.total) ?? d.job_progress_total ?? d.total_files ?? 0);
      rows = [{
        shard_id: 1,
        total,
        done,
        success_count: Number((job && job.success_count) ?? d.job_success_count ?? d.success_files ?? 0),
        failed_count: Number((job && job.failed_count) ?? d.job_failed_count ?? d.failed_files ?? 0),
        running_count: status === 'running' ? 1 : 0,
        pending_count: Math.max(0, total - done),
        rows_imported: Number(d.total_rows || 0),
        current_code: (job && job.current_code) || d.current_code || '-',
        last_error: d.message || '-'
      }];
    }
    table.innerHTML =
      '<thead><tr>' +
      ['Shard','完成进度','成功','失败','运行中','待执行','写入行数','当前文件/代码','失败信息']
        .map(c => `<th>${c}</th>`).join('') +
      '</tr></thead><tbody>' +
      rows.map(r => `
        <tr>
          <td>${cell(r.shard_id)}</td>
          <td>${progressBar(r.done, r.total)}</td>
          <td>${cell(r.success_count)}</td>
          <td>${cell(r.failed_count)}</td>
          <td>${cell(r.running_count)}</td>
          <td>${cell(r.pending_count)}</td>
          <td>${cell(r.rows_imported)}</td>
          <td>${cell(r.current_code)}</td>
          <td>${cell(r.last_error)}</td>
        </tr>
      `).join('') +
      '</tbody>';
  }

  function staleLabel(row){
    const status = String(row && (row.job_status || row.status) || '').toLowerCase();
    if(!['queued', 'pending', 'running', 'cancelling'].includes(status)) return '';
    const raw = row.updated_at || row.started_at;
    if(!raw) return '';
    const t = new Date(String(raw).replace(' ', 'T')).getTime();
    if(!Number.isFinite(t)) return '';
    const minutes = (Date.now() - t) / 60000;
    if(minutes >= 120) return '历史遗留';
    if(minutes >= 30) return '高度疑似中断';
    if(minutes >= 5) return '疑似中断';
    return '';
  }

  async function cancelImportBatch(batchId){
    if(!batchId) return;
    const reason = prompt(`确认取消/废弃导入批次 #${batchId}？\n\nqueued/pending 会直接取消；running 会请求后台停止。`, '用户取消/废弃');
    if(reason === null) return;
    const out = $('importActionResult');
    if(out) out.textContent = `正在取消/废弃批次 #${batchId}...`;
    try{
      const data = await postJson('/api/import/batches/' + encodeURIComponent(batchId) + '/cancel', {reason});
      if(out) out.textContent = JSON.stringify(data, null, 2);
      if(String(activeImportBatchId || '') === String(batchId) && data && data.status === 'cancelled'){
        stopImportWatch(true);
      }
      await loadImportBatches();
      await refreshImportWatch(batchId, activeImportProgressUrl);
    }catch(e){
      if(out) out.textContent = '取消/废弃失败：' + (e && e.message ? e.message : String(e));
    }
  }

  async function loadImportBatches(){
    const table = $('importBatchTable');
    if(!table) return;

    try{
      const rawRows = await getJson('/api/import/batches?limit=100');
      const rows = (Array.isArray(rawRows) ? rawRows : [])
        .filter(batchMatchesFilter)
        .sort((a, b) => activeRank(a) - activeRank(b) || Number(b.id || 0) - Number(a.id || 0));
      if(!rows || !rows.length){
        table.innerHTML = '<tbody><tr><td>当前类型暂无批次</td></tr></tbody>';
        return;
      }

      table.innerHTML =
        '<thead><tr>' +
        ['批次ID','任务类型','市场范围','执行ID','并发数','状态','完成进度','成功/失败','数据范围','记录数','开始时间','更新时间','操作']
          .map(c => `<th>${c}</th>`).join('') +
        '</tr></thead><tbody>' +
        rows.map(r => {
          const done = Number(r.job_progress_current ?? r.done_files ?? (Number(r.success_files || 0) + Number(r.failed_files || 0)));
          const total = Number(r.job_progress_total ?? r.total_files ?? 0);
          const selected = String(activeImportBatchId || '') === String(r.id || '');
          const stale = staleLabel(r);
          const status = r.job_status || r.status;
          const statusText = `${status ?? '-'}${stale ? ' / ' + stale : ''}`;
          const cancelButton = canCancelImportStatus(status)
            ? `<button class="danger cancel-import-batch" data-import-batch-id="${r.id ?? ''}" title="取消 queued/pending；running 请求后台停止">取消/废弃</button>`
            : '-';
          return `
          <tr data-import-batch-id="${r.id ?? ''}" data-progress-url="${r.progress_url || ''}" style="cursor:pointer;${selected ? 'background:rgba(59,130,246,.15)' : ''}" title="点击追踪这个导入批次">
            <td>${r.id ?? '-'}</td>
            <td>${batchTypeLabel(r.import_type)}</td>
            <td>${r.market ?? '-'}</td>
            <td>${r.job_id ?? '-'}</td>
            <td>${r.workers ?? '-'}</td>
            <td>${statusText}</td>
            <td>${progressBar(done, total)}</td>
            <td>${r.success_files ?? 0}/${r.failed_files ?? 0}</td>
            <td>${r.data_range ?? '-'}</td>
            <td>${r.total_rows ?? '-'}</td>
            <td>${r.started_at ?? '-'}</td>
            <td>${r.updated_at ?? r.finished_at ?? '-'}</td>
            <td>${cancelButton}</td>
          </tr>
        `;
        }).join('') +
        '</tbody>';

      bindImportBatchRows(table);
      watchLatestActiveImport(rows);
    }catch(e){}
  }

  function bindImportBatchRows(table){
    table.querySelectorAll('tbody tr[data-import-batch-id]').forEach(tr => {
      tr.onclick = function(){
        const batchId = this.dataset.importBatchId;
        if(!batchId) return;
        startImportWatch(batchId, this.dataset.progressUrl || null);
      };
    });
    table.querySelectorAll('.cancel-import-batch').forEach(btn => {
      btn.onclick = function(ev){
        ev.preventDefault();
        ev.stopPropagation();
        cancelImportBatch(this.dataset.importBatchId);
      };
    });
  }

  function isActiveImportStatus(status){
    return ['queued', 'pending', 'running'].includes(String(status || '').toLowerCase());
  }

  function activeRank(row){
    const status = String(row && row.status || '').toLowerCase();
    if(status === 'running') return 0;
    if(status === 'queued' || status === 'pending') return 1;
    return 2;
  }

  function watchLatestActiveImport(rows){
    if(!Array.isArray(rows)) return;

    // If we already have multi-lane watching, only add lanes that aren't tracked yet
    const activeRows = rows
      .filter(r => isActiveImportStatus(r.status))
      .sort((a, b) => activeRank(a) - activeRank(b) || Number(b.id || 0) - Number(a.id || 0));

    let foundAny = false;
    for(const r of activeRows){
      const market = r.market;
      if(market && !activeImportLanes[market]){
        activeImportLanes[market] = {
          batchId: r.id,
          jobId: r.job_id,
          progressUrl: r.progress_url || null,
          label: r.market || market,
          detail: r,
          job: {},
        };
        foundAny = true;
      }
    }

    // If we found multiple lanes, start multi-lane watch
    if(foundAny && Object.keys(activeImportLanes).length > 1){
      startMultiLaneWatch(Object.values(activeImportLanes).map(l => ({
        import_batch_id: l.batchId,
        job_id: l.jobId,
        market: l.label,
        market_label: l.label,
        progress_url: l.progressUrl,
        skipped: false,
      })));
    } else if(!activeImportBatchId && activeRows.length > 0){
      // Fallback: single batch tracking
      const best = activeRows[0];
      if(best && best.id){
        startImportWatch(best.id, best.progress_url);
      }
    }
  }

  function bootstrapActiveImportWatch(){
    if(autoWatchBootstrapped || activeImportBatchId) return;
    autoWatchBootstrapped = true;
    loadImportBatches().catch(() => {});
  }

  async function loadImportFiles(batchId){
    const table = $('importFileTable');
    if(!table) return;

    try{
      const url = '/api/import/files?limit=100' + (batchId ? '&batch_id=' + encodeURIComponent(batchId) : '');
      const rows = await getJson(url);
      if(!rows || !rows.length){
        table.innerHTML = '<tbody><tr><td>暂无导入文件明细</td></tr></tbody>';
        return [];
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
      return rows;
    }catch(e){
      return [];
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
    renderImportExecution(d, job);
    const files = await loadImportFiles(batchId);
    renderImportShardSummary(d, job, files);
    await loadImportBatches();
    const status = (job && job.status) || (d && d.job_status) || (d && d.status);
    if(status && !['queued', 'pending', 'running'].includes(status)){
      stopImportWatch(true);
      autoWatchBootstrapped = false;
      loadImportBatches().catch(() => {});
    }
  }

  async function refreshMultiLaneWatch(){
    if(window.refreshMultiLaneWatch && window.refreshMultiLaneWatch !== refreshMultiLaneWatch){
      window.refreshMultiLaneWatch();
      return;
    }
    const laneKeys = Object.keys(activeImportLanes);
    if(laneKeys.length === 0) return;

    for(const market of laneKeys){
      const lane = activeImportLanes[market];
      if(!lane.batchId) continue;
      try{
        const d = await getJson('/api/import/batches/' + encodeURIComponent(lane.batchId));
        lane.detail = d || {};
        if(lane.progressUrl){
          lane.job = await getJson(lane.progressUrl) || {};
        }
      }catch(e){}
    }

    // Render multi-lane summary in the base card
    if(window.renderMultiLaneCards) window.renderMultiLaneCards();

    // Keep completed lanes visible — don't auto-remove them.
    // Only stop the polling timer when all lanes reach terminal state.
    const allTerminal = laneKeys.every(k => {
      const lane = activeImportLanes[k];
      const s = ((lane.job && lane.job.status) || (lane.detail && lane.detail.status) || '').toLowerCase();
      return ['success', 'failed', 'cancelled'].includes(s);
    });
    if(allTerminal && laneKeys.length > 0){
      stopImportWatch(true);
      autoWatchBootstrapped = false;
      loadImportBatches().catch(() => {});
    }
  }

  function startMultiLaneWatch(lanes){
    // Delegate to the shared base file version if available
    if(window.startMultiLaneWatch && window.startMultiLaneWatch !== startMultiLaneWatch){
      window.startMultiLaneWatch(lanes);
      return;
    }
    stopImportWatch();
    activeImportLanes = {};

    for(const lane of lanes){
      if(lane.skipped) continue;
      const market = lane.market;
      activeImportLanes[market] = {
        batchId: lane.import_batch_id,
        jobId: lane.job_id,
        progressUrl: lane.progress_url,
        label: lane.market_label || market,
        detail: {},
        job: {},
      };
    }

    if(Object.keys(activeImportLanes).length === 0) return;

    if(window.renderMultiLaneCards) window.renderMultiLaneCards();
    refreshMultiLaneWatch().catch(() => {});
    importWatchTimer = setInterval(function(){
      refreshMultiLaneWatch().catch(() => {});
    }, 5000);
  }

  function startImportWatch(batchOrId, progressUrl){
    stopImportWatch();
    const batchId = typeof batchOrId === 'object' ? batchOrId.import_batch_id : batchOrId;
    activeImportProgressUrl = progressUrl || (typeof batchOrId === 'object' ? batchOrId.progress_url : null);
    activeImportBatchId = batchId;
    refreshImportWatch(batchId, activeImportProgressUrl).catch(() => {});
    importWatchTimer = setInterval(function(){
      refreshImportWatch(batchId, activeImportProgressUrl).catch(() => {});
    }, 5000);
  }

  window.startDataImportWatch = startImportWatch;

  function stopImportWatch(keepSelection){
    if(importWatchTimer){
      clearInterval(importWatchTimer);
      importWatchTimer = null;
    }
    activeImportLanes = {};
    if(!keepSelection){
      activeImportBatchId = null;
      activeImportProgressUrl = null;
    }
  }

  function bindButtons(){
    const scanBtn = $('scanImportDirBtn');
    const runBtn = $('runImportBtn');
    const buildBtn = $('build30mBtn');
    const rebuildIndicatorsBtn = $('rebuildIndicatorsBtn');
    const refreshBtn = $('refreshImportBtn');
    const refreshBatchBtn = $('refreshImportBatchesBtn');
    const refreshFilesBtn = $('refreshImportFilesBtn');
    const toggleFilesBtn = $('toggleImportFilesBtn');
    const out = $('importActionResult');

    if(scanBtn){
      scanBtn.dataset.bound = 'addon';
      scanBtn.onclick = async function(){
        const p = payload();
        const scanOut = $('importScanResult') || out;
        if(scanOut){ scanOut.style.display = ''; scanOut.textContent = '正在扫描...'; }
        try{
          const data = await postJson('/api/import/scan', p);
          if(scanOut){
            const summary =
              `源文件数据范围：${data.file_data_range || '-'}\n` +
              `文件数：${data.total_files || 0}\n` +
              `扫描目录：${(data.scan_dirs || []).join(', ') || '-'}\n\n`;
            scanOut.textContent = summary + JSON.stringify(data, null, 2);
          }
        }catch(e){
          if(scanOut){ scanOut.style.display = ''; scanOut.textContent = '扫描失败：' + (e && e.message ? e.message : String(e)); }
        }
      };
    }

    if(runBtn){
      runBtn.dataset.bound = 'addon';
      runBtn.onclick = async function(){
        const p = payload();
        if(!confirmFullHistoryImport(p)) return;
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
          `导入范围：${importRangeText(p)}\n` +
          `并发线程：${p.workers}\n\n` +
          `注意：这里只导入行情数据，不触发 2560 / 2568 计算。`
        )) return;

        if(out){ out.style.display = ''; out.textContent = '正在导入，请稍候...'; }
        try{
          const data = await postJson('/api/import/run', p);
          if(out) out.textContent = JSON.stringify(data, null, 2);
          if(data && data.lanes){
            setBatchTypeFilter('vipdoc');
            startMultiLaneWatch(data.lanes);
          }else if(data && data.import_batch_id){
            setBatchTypeFilter('vipdoc');
            startImportWatch(data);
          }else{
            await loadImportBatches();
            renderImportExecution(null, null);
            renderImportShardSummary(null, null, []);
          }
        }catch(e){
          if(out){ out.style.display = ''; out.textContent = '导入失败：' + (e && e.message ? e.message : String(e)); }
        }
      };
    }

    if(buildBtn){
      buildBtn.dataset.bound = 'addon';
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
          `时间选择：日常增量选当天；首次补历史或30m不足25根时，开始日期往前拉长，建议从2026-04-01到目标交易日。\n\n` +
          `注意：这里只做周期聚合，不触发 2560 / 2568 计算。`
        )) return;

        if(out){ out.style.display = ''; out.textContent = '正在从 5m 生成 30m，请稍候...'; }
        try{
          buildBtn.disabled = true;
          const data = await postJson('/api/import/build-30m', body);
          if(out) out.textContent = JSON.stringify(data, null, 2);
          if(data && data.duplicate){
            alert(`已有相同 30m 构建任务：批次 #${data.import_batch_id}，状态 ${data.status}`);
            await loadImportBatches();
            return;
          }
          if(data && data.lanes){
            startMultiLaneWatch(data.lanes);
            await loadImportBatches();
          }else if(data && data.import_batch_id){
            setBatchTypeFilter('build_30m');
            startImportWatch(data);
          }else{
            await loadImportBatches();
          }
        }catch(e){
          if(out){ out.style.display = ''; out.textContent = '生成30m失败：' + (e && e.message ? e.message : String(e)); }
        }finally{
          buildBtn.disabled = false;
        }
      };
    }

    if(rebuildIndicatorsBtn){
      rebuildIndicatorsBtn.dataset.bound = 'addon';
      rebuildIndicatorsBtn.onclick = async function(){
        const p = payload();
        if(!p.start || !p.end){
          alert('重算指标必须填写开始日期和结束日期');
          return;
        }
        const body = {
          start: p.start,
          end: p.end,
          market: p.market,
          periods: 'daily,5m,30m',
          commit_every: 50
        };
        if(!confirm(
          `确认重算 technical_indicator？\n\n` +
          `市场：${body.market}\n` +
          `日期：${body.start} 至 ${body.end}\n` +
          `周期：${body.periods}\n\n` +
          `时间选择：重算指标的日期范围应跟30m构建保持一致。\n\n` +
          `注意：这一步应在日线/5m导入和30m构建完成后执行。`
        )) return;

        if(out){ out.style.display = ''; out.textContent = '正在提交指标重算任务...'; }
        try{
          rebuildIndicatorsBtn.disabled = true;
          const data = await postJson('/api/import/rebuild-indicators', body);
          if(out) out.textContent = JSON.stringify(data, null, 2);
          if(data && data.duplicate){
            alert(`已有相同指标重算任务：批次 #${data.import_batch_id}，状态 ${data.status}`);
            await loadImportBatches();
            return;
          }
          if(data && data.lanes){
            startMultiLaneWatch(data.lanes);
            await loadImportBatches();
          }else if(data && data.import_batch_id){
            setBatchTypeFilter('rebuild_indicator');
            startImportWatch(data);
          }else{
            await loadImportBatches();
          }
        }catch(e){
          if(out){ out.style.display = ''; out.textContent = '提交指标重算失败：' + (e && e.message ? e.message : String(e)); }
        }finally{
          rebuildIndicatorsBtn.disabled = false;
        }
      };
    }

    if(refreshBtn){
      refreshBtn.dataset.bound = 'addon';
      refreshBtn.onclick = async function(){
        await loadImportBatches();
        if(activeImportBatchId){
          await refreshImportWatch(activeImportBatchId, activeImportProgressUrl);
        }else{
          renderImportExecution(null, null);
          renderImportShardSummary(null, null, []);
        }
      };
    }

    if(refreshBatchBtn){
      refreshBatchBtn.dataset.bound = 'addon';
      refreshBatchBtn.onclick = loadImportBatches;
    }

    const typeFilter = $('importBatchTypeFilter');
    if(typeFilter){
      typeFilter.dataset.bound = 'addon';
      typeFilter.onchange = loadImportBatches;
    }

    if(refreshFilesBtn){
      refreshFilesBtn.dataset.bound = 'addon';
      refreshFilesBtn.onclick = function(){ loadImportFiles(activeImportBatchId); };
    }

    if(toggleFilesBtn){
      toggleFilesBtn.dataset.bound = 'addon';
      toggleFilesBtn.onclick = function(){
        const importFilePanel = $('importFilePanel');
        if(!importFilePanel) return;
        const isHidden = importFilePanel.style.display === 'none';
        importFilePanel.style.display = isHidden ? '' : 'none';
        toggleFilesBtn.textContent = isHidden ? '隐藏文件明细' : '查看文件明细';
        if(isHidden) loadImportFiles(activeImportBatchId);
      };
    }
  }

  async function boot(){
    ensureControls();
    bindButtons();
    if(window.updateDataImportMode){
      window.updateDataImportMode();
    }

    // Multi-lane boot is handled by the base file via /api/import/latest
    // Only start the batch table auto-watch if base file hasn't started multi-lane
    if(window.activeImportLanes && Object.keys(window.activeImportLanes).length > 0){
      // Multi-lane is already active, just sync to addon's batch table
      loadImportBatches().catch(() => {});
    } else {
      bootstrapActiveImportWatch();
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
  setTimeout(boot, 300);
})();

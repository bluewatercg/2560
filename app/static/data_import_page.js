
(function(){
  function $(id){ return document.getElementById(id); }
  function all(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }
  let importWatchTimer = null;
  let activeImportLanes = {};  // { sh60: {batchId, jobId, progressUrl}, sh68: {...}, ... }
  let activeImportBatchId = null;  // backward compat: single batch for single-market imports
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
    const stepByView = {
      'data-update': 1,
      'data-import-run': 2,
      'data-import-batches': 4,
      'data-import-logs': 4
    };
    const step = stepByView[viewName] || 1;
    setActiveImportStep(step);

    all('.nav-item[data-view]').forEach(x => x.classList.remove('active'));
    all('.view').forEach(v => v.classList.remove('active'));

    const navBtn = document.querySelector(`.nav-item[data-view="${viewName}"]`);
    if(navBtn) navBtn.classList.add('active');

    const view = document.getElementById('view-data-update');
    if(view) view.classList.add('active');
  }

  function ensureDataImportPage(){
    const main = document.querySelector('main.main') || document.querySelector('main') || document.body;
    if(!main || $('view-data-update')) return;

    const section = document.createElement('section');
    section.id = 'view-data-update';
    section.className = 'view';

    section.innerHTML = `
      <!-- 四步流程导航 -->
      <div class="import-steps" style="display:flex;gap:4px;margin-bottom:16px;flex-wrap:wrap">
        <button class="import-step-btn" data-step="1" style="flex:1;min-width:160px;padding:12px 16px;border:1px solid #334155;border-radius:8px;background:#0F172A;color:#F8FAFC;cursor:pointer;text-align:left">
          <div style="font-size:12px;color:#94A3B8">步骤 1</div>
          <div style="font-weight:600;margin-top:2px">扫描检查</div>
          <div style="font-size:11px;color:#64748B;margin-top:2px">确认源文件数据范围</div>
        </button>
        <button class="import-step-btn" data-step="2" style="flex:1;min-width:160px;padding:12px 16px;border:1px solid #334155;border-radius:8px;background:#0F172A;color:#F8FAFC;cursor:pointer;text-align:left">
          <div style="font-size:12px;color:#94A3B8">步骤 2</div>
          <div style="font-weight:600;margin-top:2px">发起导入</div>
          <div style="font-size:11px;color:#64748B;margin-top:2px">日线/5m 写入数据库</div>
        </button>
        <button class="import-step-btn" data-step="3" style="flex:1;min-width:160px;padding:12px 16px;border:1px solid #334155;border-radius:8px;background:#0F172A;color:#F8FAFC;cursor:pointer;text-align:left">
          <div style="font-size:12px;color:#94A3B8">步骤 3</div>
          <div style="font-weight:600;margin-top:2px">构建30m</div>
          <div style="font-size:11px;color:#64748B;margin-top:2px">从5m聚合生成30m</div>
        </button>
        <button class="import-step-btn" data-step="4" style="flex:1;min-width:160px;padding:12px 16px;border:1px solid #334155;border-radius:8px;background:#0F172A;color:#F8FAFC;cursor:pointer;text-align:left">
          <div style="font-size:12px;color:#94A3B8">步骤 4</div>
          <div style="font-weight:600;margin-top:2px">重算指标</div>
          <div style="font-size:11px;color:#64748B;margin-top:2px">计算 technical_indicator</div>
        </button>
      </div>

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
          <button id="build30mBtn">从5m生成30m</button>
          <button id="rebuildIndicatorsBtn">重算指标</button>
          <button id="refreshImportBtn">刷新导入记录</button>
        </div>

        <div id="fullHistoryGuard" class="full-history-guard" style="display:none">
          <label>
            <input id="confirmFullHistoryImportCheckbox" type="checkbox" />
            我确认执行全量历史导入，可能写入数百万/千万行
          </label>
        </div>
      </div>

      <!-- 实时导入进度（独立面板） -->
      <div id="importLiveCards" style="display:none;margin:16px 0"></div>
      <div id="importLiveCard" style="display:none;margin:16px 0">
          <div style="border:1px solid #334155;border-radius:12px;background:#0F172A;padding:20px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
              <div style="display:flex;align-items:center;gap:10px">
                <span id="liveCardStatusIcon" style="font-size:20px"></span>
                <span id="liveCardStatusText" style="font-weight:600;font-size:16px"></span>
              </div>
              <span id="liveCardPercent" style="color:#94A3B8;font-size:14px"></span>
            </div>
            <div style="height:8px;background:#1E293B;border-radius:4px;overflow:hidden;margin-bottom:16px">
              <div id="liveCardProgressBar" style="height:100%;background:linear-gradient(90deg,#3B82F6,#22C55E);border-radius:4px;transition:width 0.5s;width:0%"></div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px">
              <div><div style="color:#64748B;font-size:11px">完成/总数</div><div id="liveCardDone" style="font-size:18px;font-weight:600;margin-top:4px">-</div></div>
              <div><div style="color:#64748B;font-size:11px">成功</div><div id="liveCardSuccess" style="font-size:18px;font-weight:600;color:#22C55E;margin-top:4px">0</div></div>
              <div><div style="color:#64748B;font-size:11px">失败</div><div id="liveCardFailed" style="font-size:18px;font-weight:600;color:#EF4444;margin-top:4px">0</div></div>
              <div><div style="color:#64748B;font-size:11px">记录数</div><div id="liveCardRows" style="font-size:18px;font-weight:600;color:#F59E0B;margin-top:4px">-</div></div>
              <div><div style="color:#64748B;font-size:11px">开始时间</div><div id="liveCardStarted" style="font-size:13px;margin-top:4px">-</div></div>
              <div><div style="color:#64748B;font-size:11px">最近更新</div><div id="liveCardUpdated" style="font-size:13px;margin-top:4px">-</div></div>
            </div>
            <div id="liveCardActions" style="margin-top:16px;display:flex;gap:8px"></div>
          </div>
        </div>
        <div id="importScanResult" class="json-box" style="display:none;margin-top:16px;padding:16px;border:1px solid #334155;border-radius:8px;background:#1E293B;color:#F8FAFC;font-family:monospace;font-size:13px;white-space:pre-wrap"></div>
        <pre id="importActionResult" class="json-box" style="display:none">等待操作</pre>
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

    // 绑定步骤按钮
    all('.import-step-btn').forEach(btn => {
      btn.onclick = function(){
        setActiveImportStep(Number(btn.dataset.step));
      };
    });
  }

  let activeImportStep = 1;

  function setActiveImportStep(step){
    activeImportStep = step;
    all('.import-step-btn').forEach(b => {
      const s = Number(b.dataset.step);
      if(s === step){
        b.style.borderColor = 'var(--blue)';
        b.style.background = 'rgba(59,130,246,.15)';
      } else if(s < step){
        b.style.borderColor = 'var(--green)';
        b.style.background = 'rgba(34,197,94,.08)';
      } else {
        b.style.borderColor = '#334155';
        b.style.background = '#0F172A';
      }
    });

    // 更新面板标题
    const titles = {
      1: ['步骤 1：扫描检查', '扫描 /data/vipdoc 源文件范围，确认数据范围，不写数据库。'],
      2: ['步骤 2：发起导入', '选择市场、日线/5m、日期范围和并发线程，提交后台导入任务。'],
      3: ['步骤 3：构建30m', '从 5m 聚合生成 30m K线数据。'],
      4: ['步骤 4：重算指标', '重算 technical_indicator（daily/5m/30m）。']
    };
    const [title, subtitle] = titles[step] || titles[1];
    if($('importPanelTitle')) $('importPanelTitle').textContent = title;
    if($('importPanelSubtitle')) $('importPanelSubtitle').textContent = subtitle;
    if($('pageTitle')) $('pageTitle').textContent = title;
    if($('pageSubtitle')) $('pageSubtitle').textContent = subtitle;

    // 根据步骤显示/隐藏按钮
    const scanBtn = $('scanImportDirBtn');
    const runBtn = $('runImportBtn');
    const buildBtn = $('build30mBtn');
    const rebuildBtn = $('rebuildIndicatorsBtn');
    const refreshBtn = $('refreshImportBtn');
    const fullGuard = $('fullHistoryGuard');

    if(scanBtn) scanBtn.style.display = step === 1 ? '' : 'none';
    if(runBtn) runBtn.style.display = step === 2 ? '' : 'none';
    if(buildBtn) buildBtn.style.display = step === 3 ? '' : 'none';
    if(rebuildBtn) rebuildBtn.style.display = step === 4 ? '' : 'none';
    if(refreshBtn) refreshBtn.style.display = step === 4 ? '' : 'none';
    if(fullGuard) fullGuard.style.display = step === 2 ? '' : 'none';

    // 步骤1显示扫描结果区，其他步骤隐藏
    const scanResult = $('importScanResult');
    if(scanResult) scanResult.style.display = step === 1 ? '' : 'none';

    // 步骤1不显示导入进度卡片，步骤2+允许显示
    const liveCards = $('importLiveCards');
    const liveCard = $('importLiveCard');
    if(liveCards) liveCards.style.display = step >= 2 ? liveCards.style.display : 'none';
    if(liveCard) liveCard.style.display = step >= 2 ? liveCard.style.display : 'none';
    if(step === 1 && window.activeImportLanes && Object.keys(window.activeImportLanes).length > 0){
      if(liveCards) liveCards.style.display = 'none';
    }

    // 步骤4不再自动显示批次面板（批次/执行/shard 已降级为高级，由折叠按钮控制）
    const importFilePanel = $('importFilePanel');
    if(importFilePanel) importFilePanel.style.display = 'none';

    // 日期/线程等控件：步骤2/3/4显示
    all('#importType,#importStartDate,#importEndDate,#importWorkers').forEach(el => {
      const label = el.closest('label');
      if(label) label.style.display = step >= 2 ? '' : 'none';
    });

    activeImportMode = step === 1 ? 'check' : step === 4 ? 'batches' : 'run';
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
    // 不再按 mode 切换，统一用步骤导航
    if(!activeImportStep) setActiveImportStep(1);
  }

  async function loadImportBatches(){
    try{
      const rows = await getJson('/api/import/batches?limit=50');

      // Auto-detect running batches for multi-lane tracking
      if(rows && rows.length){
        for(const r of rows){
          const market = r.market;
          if(market && r.status === 'running' && !activeImportLanes[market]){
            activeImportLanes[market] = {
              batchId: r.id,
              jobId: r.job_id,
              progressUrl: r.progress_url || null,
              label: r.market || market,
              detail: r,
              job: {},
            };
          }
        }
        // If we found multi-lane, render them
        if(Object.keys(activeImportLanes).length > 1){
          renderMultiLaneCards();
        }
      }
    }catch(e){
      // batch table removed from UI, swallow errors
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
    const card = $('importLiveCard');
    if(!card) return;

    if(!d){
      card.style.display = 'none';
      return;
    }

    card.style.display = '';

    const total = Number((job && job.total) || d.job_progress_total || d.total_files || 0);
    const done = Number((job && job.done) || d.job_progress_current || d.done_files || 0);
    const percentValue = total ? (done * 100 / total) : Number((job && job.percent) ?? d.progress_percent ?? 0);
    const percent = total ? percentValue.toFixed(1) + '%' : '-';
    const status = ((job && job.status) || d.job_status || d.status || '-').toLowerCase();
    const success = (job && job.success_count) ?? d.job_success_count ?? d.success_files ?? 0;
    const failed = (job && job.failed_count) ?? d.job_failed_count ?? d.failed_files ?? 0;
    const rows = d.total_rows || 0;
    const started = d.started_at || '-';
    const updated = d.updated_at || '-';

    // Status icon & text
    const iconMap = { running: '⟳', success: '✓', failed: '✗', queued: '◷', pending: '◷' };
    const colorMap = { running: '#3B82F6', success: '#22C55E', failed: '#EF4444', queued: '#F59E0B', pending: '#94A3B8' };
    const labelMap = { running: '导入中', success: '导入完成', failed: '导入失败', queued: '排队中', pending: '等待中' };
    const icon = iconMap[status] || '●';
    const color = colorMap[status] || '#94A3B8';
    const label = labelMap[status] || status;

    const statusIcon = $('liveCardStatusIcon');
    const statusText = $('liveCardStatusText');
    if(statusIcon){ statusIcon.textContent = icon; statusIcon.style.color = color; }
    if(statusText){ statusText.textContent = `#${d.id} ${label}`; statusText.style.color = color; }

    // Percent
    const pctEl = $('liveCardPercent');
    if(pctEl) pctEl.textContent = percent;

    // Progress bar
    const bar = $('liveCardProgressBar');
    if(bar) bar.style.width = (total ? Math.min(percentValue, 100) : 0) + '%';

    // Stats
    const doneEl = $('liveCardDone');
    if(doneEl) doneEl.textContent = total ? `${done}/${total}` : `${done}/-`;
    const okEl = $('liveCardSuccess');
    if(okEl) okEl.textContent = success;
    const failEl = $('liveCardFailed');
    if(failEl) failEl.textContent = failed;
    const rowsEl = $('liveCardRows');
    if(rowsEl) rowsEl.textContent = rows > 1000000 ? (rows/1000000).toFixed(1)+'M' : rows > 1000 ? (rows/1000).toFixed(0)+'K' : rows;
    const startedEl = $('liveCardStarted');
    if(startedEl) startedEl.textContent = started;
    const updatedEl = $('liveCardUpdated');
    if(updatedEl) updatedEl.textContent = updated;

    // Actions
    const actions = $('liveCardActions');
    if(actions){
      let html = '';
      if(status === 'running'){
        html += `<span style="color:#64748B;font-size:12px;align-self:center">每5秒自动刷新…</span>`;
      } else if(status === 'success' || status === 'failed'){
        html += `<button id="liveCardWatchFilesBtn" style="padding:6px 14px;border:1px solid #334155;border-radius:6px;background:#1E293B;color:#F8FAFC;cursor:pointer;font-size:12px">查看文件明细</button>`;
      }
      actions.innerHTML = html;
      const wfBtn = $('liveCardWatchFilesBtn');
      if(wfBtn) wfBtn.onclick = () => { $('importFilePanel').style.display = ''; loadImportFiles(String(d.id)); };
    }
  }

  function renderMultiLaneCards(){
    // 步骤1（扫描检查）不显示导入进度卡片
    if(activeImportStep === 1) return;

    const container = $('importLiveCards');
    if(!container) return;

    const laneKeys = Object.keys(activeImportLanes);
    if(laneKeys.length === 0){
      container.style.display = 'none';
      return;
    }

    container.style.display = '';

    let html = '';
    for(const market of laneKeys){
      const lane = activeImportLanes[market];
      const d = lane.detail || {};
      const job = lane.job || {};
      const label = lane.label || market;
      const status = ((job && job.status) || d.job_status || d.status || '-').toLowerCase();

      const iconMap = { running: '⟳', success: '✓', failed: '✗', queued: '◷', pending: '◷', cancelled: '✗', cancelling: '⟳' };
      const colorMap = { running: '#3B82F6', success: '#22C55E', failed: '#EF4444', queued: '#F59E0B', pending: '#94A3B8', cancelled: '#EF4444', cancelling: '#F59E0B' };
      const labelMap = { running: '导入中', success: '导入完成', failed: '导入失败', queued: '排队中', pending: '等待中', cancelled: '已取消', cancelling: '取消中' };
      const icon = iconMap[status] || '●';
      const color = colorMap[status] || '#94A3B8';
      const statusLabel = labelMap[status] || status;

      const total = Number((job && job.total) || d.job_progress_total || d.total_files || 0);
      const done = Number((job && job.done) || d.job_progress_current || d.done_files || 0);
      const percentValue = total ? (done * 100 / total) : Number((job && job.percent) ?? d.progress_percent ?? 0);
      const percent = total ? percentValue.toFixed(1) + '%' : '-';
      const success = (job && job.success_count) ?? d.job_success_count ?? d.success_files ?? 0;
      const failed = (job && job.failed_count) ?? d.job_failed_count ?? d.failed_files ?? 0;
      const workers = (job && job.shards) || d.workers || '-';

      const batchId = d.id || lane.batchId;

      html += `<div class="lane-card" data-market="${market}" style="border:1px solid #334155;border-radius:12px;background:#0F172A;padding:16px;margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:20px;color:${color}">${icon}</span>
            <span style="font-weight:600;font-size:15px;color:#F8FAFC">${label}</span>
            <span style="font-weight:600;font-size:14px;color:${color}">#${batchId} ${statusLabel}</span>
            <span style="color:#64748B;font-size:12px;border:1px solid #334155;border-radius:4px;padding:2px 6px">并发 ${workers}</span>
          </div>
          <span style="color:#94A3B8;font-size:14px">${percent}</span>
        </div>
        <div style="height:6px;background:#1E293B;border-radius:3px;overflow:hidden;margin-bottom:12px">
          <div style="height:100%;background:linear-gradient(90deg,#3B82F6,#22C55E);border-radius:3px;transition:width 0.5s;width:${total ? Math.min(percentValue, 100) : 0}%"></div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px">
          <div><div style="color:#64748B;font-size:11px">完成/总数</div><div style="font-size:16px;font-weight:600;margin-top:2px">${total ? done+'/'+total : done+'/-'} </div></div>
          <div><div style="color:#64748B;font-size:11px">成功</div><div style="font-size:16px;font-weight:600;color:#22C55E;margin-top:2px">${success}</div></div>
          <div><div style="color:#64748B;font-size:11px">失败</div><div style="font-size:16px;font-weight:600;color:#EF4444;margin-top:2px">${failed}</div></div>
        </div>
        <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
          ${status === 'running' ? '<span style="color:#64748B;font-size:11px">每5秒自动刷新…</span>' : ''}
          ${status === 'success' || status === 'failed' ? `<button onclick="window.viewLaneFiles('${market}')" style="padding:4px 10px;border:1px solid #334155;border-radius:4px;background:#1E293B;color:#F8FAFC;cursor:pointer;font-size:11px">查看文件</button>` : ''}
        </div>
      </div>`;
    }

    // Summary bar
    const activeCount = laneKeys.filter(k => {
      const s = ((activeImportLanes[k].job && activeImportLanes[k].job.status) || (activeImportLanes[k].detail && activeImportLanes[k].detail.status) || '').toLowerCase();
      return ['running', 'queued', 'pending', 'cancelling'].includes(s);
    }).length;
    const doneCount = laneKeys.filter(k => {
      const s = ((activeImportLanes[k].job && activeImportLanes[k].job.status) || (activeImportLanes[k].detail && activeImportLanes[k].detail.status) || '').toLowerCase();
      return ['success', 'failed', 'cancelled'].includes(s);
    }).length;

    if(activeCount > 0 || doneCount > 0){
      html = `<div style="color:#94A3B8;font-size:12px;margin-bottom:10px">
        导入任务：${laneKeys.length} 个市场 | 进行中 ${activeCount} | 已完成 ${doneCount}
      </div>` + html;
    }

    container.innerHTML = html;
  }

  async function refreshMultiLaneWatch(){
    const laneKeys = Object.keys(activeImportLanes);
    if(laneKeys.length === 0) return;

    for(const market of laneKeys){
      const lane = activeImportLanes[market];
      if(!lane.batchId) continue;

      try{
        const d = await getJson('/api/import/batches/' + encodeURIComponent(lane.batchId));
        lane.detail = d || {};

        if(lane.progressUrl){
          const job = await getJson(lane.progressUrl);
          lane.job = job || {};
        }
      }catch(e){
        // ignore individual lane errors
      }
    }

    renderMultiLaneCards();

    // Keep completed lanes visible — don't auto-remove them.
    // Users need to see final state of all markets, not just active ones.
    // Only stop the polling timer when all lanes reach terminal state.
    const allTerminal = laneKeys.every(k => {
      const lane = activeImportLanes[k];
      const s = ((lane.job && lane.job.status) || (lane.detail && lane.detail.status) || '').toLowerCase();
      return ['success', 'failed', 'cancelled'].includes(s);
    });
    if(allTerminal && laneKeys.length > 0){
      stopImportWatch();
      loadImportBatches().catch(() => {});
    }
  }

  function startMultiLaneWatch(lanes){
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

    renderMultiLaneCards();
    refreshMultiLaneWatch().catch(() => {});
    importWatchTimer = setInterval(function(){
      refreshMultiLaneWatch().catch(() => {});
    }, 5000);
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
    activeImportLanes = {};
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
          $('importActionResult').style.display = '';
          $('importActionResult').textContent = summary + JSON.stringify(data, null, 2);
        }catch(e){
          $('importActionResult').style.display = '';
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
          if(data && data.lanes){
            startMultiLaneWatch(data.lanes);
          }else if(data && data.import_batch_id){
            startImportWatch(data);
          }else{
            await loadImportBatches();
            await loadImportFiles();
            $('importActionResult').style.display = '';
            $('importActionResult').textContent = JSON.stringify(data, null, 2);
          }
        }catch(e){
          $('importActionResult').style.display = '';
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

  async function boot(){
    ensureDataImportPage();
    bindButtons();
    setActiveImportStep(1);
    updateImportMode(false);

    // Auto-detect running multi-lane import on first load
    try{
      const latest = await getJson('/api/import/latest');
      if(latest && latest.lanes && latest.lanes.length > 0){
        startMultiLaneWatch(latest.lanes);
      }
    }catch(e){
      // fallback: try old single-batch detection
    }

    // Fallback: also check batches list for single-market imports
    loadImportBatches().then(function(){
      if(Object.keys(activeImportLanes).length === 0 && activeImportBatchId){
        refreshImportWatch(activeImportBatchId, activeImportProgressUrl).catch(() => {});
      }
    }).catch(() => {});
  }

  document.addEventListener('DOMContentLoaded', boot);
  setTimeout(boot, 300);
  window.viewLaneFiles = function(market){
    const lane = activeImportLanes[market];
    if(lane && lane.batchId){
      $('importFilePanel').style.display = '';
      loadImportFiles(String(lane.batchId));
    }
  };

  // Expose multi-lane API for addon to share the same state
  window.activeImportLanes = activeImportLanes;
  window.startMultiLaneWatch = startMultiLaneWatch;
  window.renderMultiLaneCards = renderMultiLaneCards;
  window.refreshMultiLaneWatch = refreshMultiLaneWatch;

  window.updateDataImportMode = updateImportMode;
  window.showDataImportView = switchView;
})();

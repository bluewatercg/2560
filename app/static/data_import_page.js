
(function(){
  function $(id){ return document.getElementById(id); }
  function all(sel, root=document){ return Array.from(root.querySelectorAll(sel)); }
  let importWatchTimer = null;
  let importFallbackTimer = null;  // slow poll when lanes exist but all terminal
  let activeImportLanes = {};  // { sh60: {batchId, jobId, progressUrl, label, detail, job}, ... }
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
              <option value="all">all 全部市场</option>
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
          <button id="cleanupStuckImportBtn" style="border-color:var(--red, #f87171);color:var(--red, #f87171)">清理僵尸任务</button>
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

      <!-- 导入批次列表（步骤2/3/4 共用，按类型过滤） -->
      <div id="importBatchPanel" class="panel import-panel" style="display:none;margin-top:16px">
        <div class="panel-head split">
          <div>
            <h3>导入批次记录</h3>
            <p class="muted" style="margin:4px 0 0">点击行可追踪该批次进度。</p>
          </div>
          <div class="filters" style="gap:8px;flex-wrap:wrap">
            <select id="importBatchTypeFilter" style="min-width:140px">
              <option value="all">全部类型</option>
              <option value="vipdoc">行情导入</option>
              <option value="build_30m">30m 构建</option>
              <option value="rebuild_indicator">指标重算</option>
            </select>
            <button id="refreshImportBatchesBtn" type="button">刷新批次</button>
          </div>
        </div>
        <div class="table-wrap">
          <table id="importBatchTable"></table>
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
    window.activeImportStep = step;
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
    // 切步骤时立即清空旧卡片，防止上一步骤的数据残留
    const liveCards = $('importLiveCards');
    const liveCard = $('importLiveCard');
    if(liveCards){
      liveCards.innerHTML = '';
      liveCards.style.display = 'none';
    }
    if(liveCard) liveCard.style.display = 'none';

    // 批次列表面板：步骤2/3/4显示，步骤1隐藏
    const importBatchPanel = $('importBatchPanel');
    if(importBatchPanel) importBatchPanel.style.display = step >= 2 ? '' : 'none';

    // 自动同步 importBatchTypeFilter 与当前步骤
    const batchTypeFilter = $('importBatchTypeFilter');
    if(batchTypeFilter){
      if(step === 2) batchTypeFilter.value = 'vipdoc';
      else if(step === 3) batchTypeFilter.value = 'build_30m';
      else if(step === 4) batchTypeFilter.value = 'rebuild_indicator';
      else batchTypeFilter.value = 'all';
    }

    // 文件明细面板默认隐藏
    const importFilePanel = $('importFilePanel');
    if(importFilePanel) importFilePanel.style.display = 'none';

    // 日期/线程等控件：步骤2显示全部，步骤3/4隐藏导入目录和并发线程
    all('#importType,#importStartDate,#importEndDate,#importWorkers').forEach(el => {
      const label = el.closest('label');
      if(label) label.style.display = step >= 2 ? '' : 'none';
    });
    // 导入目录：只在步骤1/2显示
    all('.import-field-source').forEach(el => {
      el.style.display = step <= 2 ? '' : 'none';
    });
    // 并发线程：只在步骤2显示（步骤3/4用后端默认并发数）
    all('#importWorkers').forEach(el => {
      const label = el.closest('label');
      if(label) label.style.display = step === 2 ? '' : 'none';
    });
    // 导入内容：只在步骤2显示
    all('#importType').forEach(el => {
      const label = el.closest('label');
      if(label) label.style.display = step === 2 ? '' : 'none';
    });

    activeImportMode = step === 1 ? 'check' : step === 4 ? 'batches' : 'run';

    // Switching step: clear old lanes and reload for current step type.
    // Filter sync (importBatchTypeFilter) must happen BEFORE calling addon's
    // loadImportBatches so the table renders with the correct type filter.
    stopImportWatch();
    loadImportBatches().catch(() => {});
    // Defer addon call slightly so the DOM filter value is already set
    setTimeout(function(){
      if(window._addonLoadImportBatches && window._addonLoadImportBatches !== loadImportBatches){
        window._addonLoadImportBatches().catch(() => {});
      }
    }, 0);
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

      // Step 2 stores import_type as 'all'/'lday'/'5m', step 3/4 as 'build_30m'/'rebuild_indicator'
      const stepTypeMap = {
        2: ['all', 'lday', '5m', 'vipdoc'],
        3: ['build_30m'],
        4: ['rebuild_indicator']
      };
      const allowed = stepTypeMap[activeImportStep] || null;

      if(rows && rows.length){
        // Build per-market "best" batch map:
        // Rows come DESC by id, so first-seen = newest.
        // running beats any non-running for the same market.
        const latest = {};
        for(const r of rows){
          if(allowed && !allowed.includes(r.import_type)) continue;
          const m = r.market;
          if(!m) continue;
          if(!latest[m]){
            latest[m] = r;
          } else if(['running','queued','pending'].includes(String(r.status||'').toLowerCase())
                    && !['running','queued','pending'].includes(String(latest[m].status||'').toLowerCase())){
            latest[m] = r; // active beats terminal within same market
          }
        }

        for(const [market, r] of Object.entries(latest)){
          const existing = activeImportLanes[market];
          if(!existing){
            // New market — add
            activeImportLanes[market] = {
              batchId: r.id,
              jobId: r.job_id,
              progressUrl: r.progress_url || null,
              label: r.market || market,
              detail: r,
              job: {},
            };
          } else {
            // Existing market — always upgrade to newer batch id.
            // Rows come DESC, so `latest` already has the newest per market.
            const newIsNewer = Number(r.id) > Number(existing.batchId);
            if(newIsNewer){
              existing.batchId    = r.id;
              existing.jobId      = r.job_id;
              existing.progressUrl = r.progress_url || null;
              existing.detail     = r;
              existing.job        = {};
            } else if(Number(r.id) === Number(existing.batchId)) {
              // Same batch: always refresh detail/job data so progress numbers update.
              // Without this, the timer re-query would skip because batchId hasn't changed.
              existing.detail = r;
              existing.job    = {};
            }
          }
        }

        // Always re-render (even when empty) so stale cards from a previous step are cleared
        renderMultiLaneCards();

        // Auto-restart 5s polling if there are active lanes but no timer running
        // (happens after step-switch which calls stopImportWatch first)
        if(!importWatchTimer && Object.keys(activeImportLanes).length > 0){
          const hasActive = Object.values(activeImportLanes).some(l => {
            const s = String((l.detail&&l.detail.status)||(l.job&&l.job.status)||'').toLowerCase();
            return ['running','queued','pending','cancelling'].includes(s);
          });
          if(hasActive){
            refreshMultiLaneWatch().catch(() => {});
            importWatchTimer = setInterval(function(){
              refreshMultiLaneWatch().catch(() => {});
            }, 5000);
            // Cancel fallback — main timer is active
            stopFallbackPoll();
          } else {
            // All lanes terminal — start slow fallback poll to pick up retried batches
            startFallbackPoll();
          }
        }
      } else {
        // No matching batches for this step — clear cards
        renderMultiLaneCards();
      }
    }catch(e){
      // swallow
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
    // #importLiveCard is a legacy single-batch card.
    // It is now permanently hidden: the multi-lane cards (#importLiveCards) show
    // all markets with real-time status, making this card redundant and confusing.
    // We keep the function (for backward compat calls) but never show the card.
    const card = $('importLiveCard');
    if(card) card.style.display = 'none';
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
      const jobId = lane.jobId;
      const progressUrl = lane.progressUrl;

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
        <div id="laneWorker-${market}" style="margin-top:12px"></div>
        <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
          ${status === 'running' ? `<span style="color:#64748B;font-size:11px">每5秒自动刷新…</span><button class="cancel-import-btn" data-market="${market}" data-job-id="${jobId || ''}" style="padding:4px 10px;border:1px solid #EF4444;border-radius:4px;background:transparent;color:#EF4444;cursor:pointer;font-size:11px">取消</button>` : ''}
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
    // Re-query the full batch list every cycle — this picks up retried
    // batches (newer id for same market) automatically via the upgrade
    // logic in loadImportBatches, and already includes job progress data.
    await loadImportBatches();

    // Fetch and render per-worker shard detail for each lane
    const laneKeys = Object.keys(activeImportLanes);
    for(const market of laneKeys){
      const lane = activeImportLanes[market];
      if(!lane.jobId) continue;
      try{
        const shards = await getJson('/api/jobs/executions/' + encodeURIComponent(lane.jobId) + '/shards');
        renderWorkerShards(market, shards);
      }catch(e){
        // ignore
      }
    }
  }

  function renderWorkerShards(market, shards){
    const container = $('laneWorker-' + market);
    if(!container || !shards || !shards.items || !shards.items.length) return;

    let html = '<div style="border-top:1px solid #334155;padding-top:12px"><div style="color:#64748B;font-size:11px;margin-bottom:8px">Worker 进度（最近导入的文件）</div>';
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:8px">';

    for(const s of shards.items){
      const statusColor = s.running_count > 0 ? '#3B82F6' : s.failed_count > 0 ? '#EF4444' : '#22C55E';
      const statusLabel = s.running_count > 0 ? '导入中' : s.pending_count > 0 ? '等待中' : '已完成';
      const code = s.current_code || s.last_file || '-';
      const err = s.last_error ? `<div style="font-size:11px;color:#EF4444;margin-top:4px" title="${s.last_error}">失败：${s.last_error.slice(0, 80)}</div>` : '';

      html += `<div style="border:1px solid #334155;border-radius:6px;padding:8px;background:#1E293B">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-size:12px;font-weight:600;color:${statusColor}">W${s.shard_id}</span>
          <span style="font-size:11px;color:#94A3B8">${s.done}/${s.total} ${statusLabel}</span>
        </div>
        <div style="font-size:11px;color:#94A3B8;margin-top:4px">最后导入：${code}</div>
        ${err}
      </div>`;
    }

    html += '</div></div>';
    container.innerHTML = html;
  }

  function startMultiLaneWatch(lanes){
    stopImportWatch();  // clears activeImportLanes in-place and stops timer

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

  // startImportWatch: single-batch shim — routes through multi-lane cards.
  // importLiveCard (legacy) is permanently hidden; multi-lane handles all display.
  function startImportWatch(batchOrId, progressUrl){
    const batchId  = typeof batchOrId === 'object' ? (batchOrId.import_batch_id || batchOrId.id) : batchOrId;
    const market   = typeof batchOrId === 'object' ? (batchOrId.market || null)     : null;
    const jobId    = typeof batchOrId === 'object' ? (batchOrId.job_id || null)      : null;
    const pUrl     = progressUrl || (typeof batchOrId === 'object' ? (batchOrId.progress_url || null) : null);
    if(!batchId) return;

    if(market){
      // Full info available: create a single-lane multi-lane watch
      startMultiLaneWatch([{ import_batch_id: batchId, job_id: jobId, market, market_label: market, progress_url: pUrl, skipped: false }]);
    } else {
      // No market: fetch batch detail first then start lane
      getJson('/api/import/batches/' + encodeURIComponent(batchId)).then(d => {
        if(d && d.market){
          startMultiLaneWatch([{ import_batch_id: batchId, job_id: d.job_id || null, market: d.market, market_label: d.market, progress_url: d.progress_url || pUrl, skipped: false }]);
        } else {
          loadImportBatches().catch(() => {});
        }
      }).catch(() => loadImportBatches().catch(() => {}));
    }
  }

  function stopFallbackPoll(){
    if(importFallbackTimer){ clearInterval(importFallbackTimer); importFallbackTimer = null; }
  }

  function startFallbackPoll(){
    stopFallbackPoll();
    importFallbackTimer = setInterval(function(){
      loadImportBatches().catch(() => {});
    }, 5000);  // was 30000 — 5s to catch new batches sooner after cancel
  }

  function stopImportWatch(){
    if(importWatchTimer){ clearInterval(importWatchTimer); importWatchTimer = null; }
    stopFallbackPoll();
    // Clear in-place to keep object reference valid (window.activeImportLanes points here)
    Object.keys(activeImportLanes).forEach(k => delete activeImportLanes[k]);
  }

  function bindButtons(){
    const scanBtn = $('scanImportDirBtn');
    if(scanBtn && !scanBtn.dataset.bound){
      scanBtn.dataset.bound = '1';
      scanBtn.onclick = async function(){
        const source_dir = $('importSourceDir') ? $('importSourceDir').value : '';
        const market = $('importMarket') ? $('importMarket').value : 'all';

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
    // Only bind if not already bound by addon (addon sets dataset.bound='addon')
    if(runBtn && !runBtn.dataset.bound){
      runBtn.dataset.bound = '1';
      runBtn.onclick = async function(){
        const source_dir = $('importSourceDir') ? $('importSourceDir').value : '';
        const market = $('importMarket') ? $('importMarket').value : 'all';
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
        if(window._addonLoadImportBatches) window._addonLoadImportBatches().catch(() => {});
      };
    }

    const cleanupBtn = $('cleanupStuckImportBtn');
    if(cleanupBtn && !cleanupBtn.dataset.bound){
      cleanupBtn.dataset.bound = '1';
      cleanupBtn.onclick = async function(){
        const mins = prompt('超过多少分钟没更新的任务算作僵尸任务？', '30');
        if(mins === null) return;
        const staleMinutes = parseInt(mins, 10) || 30;
        const confirmed = confirm(`确认清理超过 ${staleMinutes} 分钟未更新的僵尸任务？`);
        if(!confirmed) return;
        try{
          const data = await postJson(`/api/jobs/admin/cleanup-stuck?stale_minutes=${staleMinutes}&dry_run=false`, {});
          alert(data.message || `清理完成，共 ${data.cleaned || 0} 个僵尸任务已标记为 failed`);
          await loadImportBatches();
        }catch(e){
          alert('清理失败：' + (e && e.message ? e.message : String(e)));
        }
      };
    }

  }

  async function boot(){
    ensureDataImportPage();
    bindButtons();
    setActiveImportStep(1);
    updateImportMode(false);

    // Event delegation: cancel buttons on import live cards (cards re-render on each poll)
    const cardsContainer = $('importLiveCards');
    if(cardsContainer){
      cardsContainer.addEventListener('click', async function(ev){
        const btn = ev.target.closest('.cancel-import-btn');
        if(!btn) return;
        ev.stopPropagation();
        const market = btn.dataset.market;
        const jobId = btn.dataset.jobId;
        const lane = activeImportLanes[market];
        if(!jobId){ alert('任务 job_id 为空，无法取消'); return; }
        if(!confirm(`确认取消 ${market}（#${lane && lane.batchId}）的导入任务？`)) return;
        btn.disabled = true;
        btn.textContent = '取消中…';
        try{
          const data = await postJson(`/api/jobs/executions/${jobId}/cancel`, {
            reason: '用户从数据导入页面取消'
          });
          alert(data.message || `已取消 ${market}`);
          await loadImportBatches();
        }catch(e){
          alert('取消失败：' + (e && e.message ? e.message : String(e)));
        }
      });
    }

    // Step→import_type filter
    const stepTypeMap = {
      2: ['all', 'lday', '5m', 'vipdoc'],
      3: ['build_30m'],
      4: ['rebuild_indicator']
    };

    // Auto-detect running imports on first load, filtered by step type
    // (boot starts at step 1, user may have clicked a step already)
    // We use activeImportStep which may have been changed before boot finishes
    try{
      const latest = await getJson('/api/import/latest');
      if(latest && latest.lanes && latest.lanes.length > 0){
        const allowed = stepTypeMap[activeImportStep] || null;
        const filtered = allowed
          ? latest.lanes.filter(l => allowed.includes(l.import_type))
          : latest.lanes;
        if(filtered.length > 0){
          startMultiLaneWatch(filtered);
        }
      }
    }catch(e){}

    // Fallback: also check batches list
    loadImportBatches().catch(() => {});
  }

  document.addEventListener('DOMContentLoaded', boot);
  // NOTE: do NOT add setTimeout(boot) here — addon.js has its own boot and
  // duplicate calls cause double-binding and step reset conflicts.
  window.viewLaneFiles = function(market){
    const lane = activeImportLanes[market];
    if(lane && lane.batchId){
      $('importFilePanel').style.display = '';
      loadImportFiles(String(lane.batchId));
    }
  };

  // Expose multi-lane API for addon to share the same state
  window.activeImportStep    = activeImportStep;
  window.renderLiveStatus    = renderLiveStatus;
  window.activeImportLanes   = activeImportLanes;
  window.startMultiLaneWatch = startMultiLaneWatch;
  window.startDataImportWatch = startImportWatch;  // addon calls this for single-batch
  window.renderMultiLaneCards  = renderMultiLaneCards;
  window.refreshMultiLaneWatch = refreshMultiLaneWatch;

  window.updateDataImportMode = updateImportMode;
  window.showDataImportView   = switchView;
})();

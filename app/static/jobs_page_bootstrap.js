
(function(){
  function $(id){ return document.getElementById(id); }
  const JOB_EXECUTIONS_LIST_URL = '/api/jobs/executions?job_type=run_2560&job_type=run_2560_now&limit=50';
  const JOB_EXECUTIONS_LATEST_URL = '/api/jobs/executions?job_type=run_2560&job_type=run_2560_now&limit=1';
  const APP_LOAD_JOBS = window.loadJobs;

  function ensureJobsPage(){
    // 1. 创建左侧/顶部菜单按钮
    const nav = document.querySelector('.nav');
    if (nav && !document.querySelector('[data-view="jobs"]')) {
      const btn = document.createElement('button');
      btn.className = 'nav-item';
      btn.dataset.view = 'jobs';
      btn.textContent = '创建批量任务';
      nav.appendChild(btn);

      btn.onclick = function(){
        document.querySelectorAll('.nav-item').forEach(x => x.classList.remove('active'));
        btn.classList.add('active');

        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        const view = $('view-jobs');
        if (view) view.classList.add('active');

        if ($('pageTitle')) $('pageTitle').textContent = '创建批量任务';
        if ($('pageSubtitle')) $('pageSubtitle').textContent = '创建 2560 批量任务、查看执行记录与 Shard 明细';

        if (window.loadJobs) window.loadJobs();
      };
    }

    // 2. 创建 jobs 页面容器
    const main = document.querySelector('main.main') || document.querySelector('main') || document.body;

    if (main && !$('view-jobs')) {
      const section = document.createElement('section');
      section.id = 'view-jobs';
      section.className = 'view';

      section.innerHTML = `
        <div class="panel" id="jobActionPanel">
          <div class="panel-head split">
            <h3>任务操作</h3>
            <div class="filters" style="gap:8px;flex-wrap:wrap">
              <label>
                市场范围
                <select id="jobMarket">
                  <option value="sh60">sh60 沪主板60</option>
                  <option value="sh68">sh68 科创68</option>
                  <option value="sz00">sz00 深主板00</option>
                  <option value="sz30">sz30 创业板30</option>
                </select>
              </label>

              <label>
                同时跑几组（并发数）
                <input id="jobShards" type="number" min="1" max="32" value="1" />
              </label>

              <label>
                任务优先级（数字越小越先跑）
                <input id="jobPriority" type="number" min="1" max="9" value="1" />
              </label>

              <button id="enqueueJobBtn" class="ghost">加入队列后台跑</button>
              <button id="runNowJobBtn" class="primary">立即执行并看进度</button>
              <button id="runAllMarketsBtn" style="border-color:var(--green);color:var(--green)">一键运行四类</button>
              <button id="refreshJobsBtn">刷新任务</button>
            </div>
          </div>

          <pre id="jobActionResult" class="json-box">等待操作</pre>
        </div>

        <div class="panel">
          <div class="panel-head split">
            <h3>当前/待执行任务（running / queued）</h3>
            <div class="filters" style="gap:8px">
              <button id="refreshExecutionsBtn">刷新执行记录</button>
              <button id="cleanupStuckBtn" style="border-color:var(--red, #f87171);color:var(--red, #f87171)">清理僵尸任务</button>
            </div>
          </div>
          <div class="table-wrap">
            <table id="jobActiveExecutionsTable"></table>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head split">
            <h3>历史执行记录（已结束）</h3>
          </div>
          <div class="table-wrap">
            <table id="jobHistoryExecutionsTable"></table>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head split">
            <h3>任务明细（job_task_item）</h3>
            <button id="refreshItemsBtn">刷新明细</button>
          </div>
          <div class="table-wrap">
            <table id="jobItemsTable"></table>
          </div>
        </div>
      `;

      const drawer = $('detailDrawer');
      if (drawer && drawer.parentNode) {
        main.insertBefore(section, drawer);
      } else {
        main.appendChild(section);
      }
    }

    // 3. 绑定基础按钮
    const refreshJobsBtn = $('refreshJobsBtn');
    if (refreshJobsBtn && !refreshJobsBtn.dataset.bound) {
      refreshJobsBtn.dataset.bound = '1';
      refreshJobsBtn.onclick = loadJobs;
    }

    const refreshExecutionsBtn = $('refreshExecutionsBtn');
    if (refreshExecutionsBtn && !refreshExecutionsBtn.dataset.bound) {
      refreshExecutionsBtn.dataset.bound = '1';
      refreshExecutionsBtn.onclick = loadExecutions;
    }

    const cleanupStuckBtn = $('cleanupStuckBtn');
    if (cleanupStuckBtn && !cleanupStuckBtn.dataset.bound) {
      cleanupStuckBtn.dataset.bound = '1';
      cleanupStuckBtn.onclick = cleanupStuckJobs;
    }

    const refreshItemsBtn = $('refreshItemsBtn');
    if (refreshItemsBtn && !refreshItemsBtn.dataset.bound) {
      refreshItemsBtn.dataset.bound = '1';
      refreshItemsBtn.onclick = loadLatestItems;
    }

    const enqueueBtn = $('enqueueJobBtn');
    if (enqueueBtn && !enqueueBtn.dataset.bound) {
      enqueueBtn.dataset.bound = '1';
      enqueueBtn.onclick = enqueueJob;
    }

    const runAllBtn = $('runAllMarketsBtn');
    if (runAllBtn && !runAllBtn.dataset.bound) {
      runAllBtn.dataset.bound = '1';
      runAllBtn.onclick = runAllMarkets;
    }
  }

  async function apiJson(url, opts){
    const r = await fetch(url, opts);
    return await r.json();
  }

  function cell(v){
    return v === null || v === undefined || v === '' ? '-' : v;
  }

  function canCancelJobStatus(status){
    return ['queued', 'pending', 'running', 'cancelling'].includes(String(status || '').toLowerCase());
  }

  function isActiveExecution(row){
    return canCancelJobStatus(row && row.status);
  }

  function staleLabel(row){
    const status = String(row && row.status || '').toLowerCase();
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

  async function cancelExecution(jobId){
    if(!jobId) return;
    const reason = prompt(`确认取消/废弃任务 #${jobId}？\n\nqueued/pending 会直接取消；running 会请求后台停止。`, '用户取消/废弃');
    if(reason === null) return;
    const data = await apiJson(`/api/jobs/executions/${jobId}/cancel`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({reason})
    });
    if ($('jobActionResult')) $('jobActionResult').textContent = JSON.stringify(data, null, 2);
    await loadJobs();
  }

  async function cleanupStuckJobs(){
    const mins = prompt('超过多少分钟没更新的任务算作僵尸任务？', '30');
    if (mins === null) return;
    const staleMinutes = parseInt(mins, 10) || 30;
    const confirmed = confirm(`确认清理超过 ${staleMinutes} 分钟未更新的僵尸任务？`);
    if (!confirmed) return;
    const data = await apiJson(`/api/jobs/admin/cleanup-stuck?stale_minutes=${staleMinutes}&dry_run=false`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'}
    });
    if ($('jobActionResult')) $('jobActionResult').textContent = JSON.stringify(data, null, 2);
    alert(data.message || `清理完成，共 ${data.cleaned || 0} 个僵尸任务已标记为 failed`);
    await loadJobs();
  }

  async function enqueueJob(){
    const market = $('jobMarket') ? $('jobMarket').value : 'sh';
    const shards = $('jobShards') ? Number($('jobShards').value || 1) : 1;
    const priority = $('jobPriority') ? Number($('jobPriority').value || 1) : 1;

    const data = await apiJson('/api/jobs/enqueue', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        strategy_code: 'S2560',
        job_type: 'run_2560',
        priority,
        market,
        shards
      })
    });

    if ($('jobActionResult')) $('jobActionResult').textContent = JSON.stringify(data, null, 2);
    await loadJobs();
  }

  async function runAllMarkets(){
    const shards = $('jobShards') ? Number($('jobShards').value || 1) : 1;
    const data = await apiJson('/api/jobs/run-all-markets', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ shards })
    });
    if ($('jobActionResult')) $('jobActionResult').textContent = JSON.stringify(data, null, 2);
    await loadJobs();
  }

  async function loadJobs(){
    if (typeof APP_LOAD_JOBS === 'function' && $('jobQueueTable')) {
      await APP_LOAD_JOBS();
      return;
    }
    await loadExecutions();
    await loadLatestItems();
  }

  async function loadExecutions(){
    const activeTable = $('jobActiveExecutionsTable');
    const historyTable = $('jobHistoryExecutionsTable');
    if (!activeTable || !historyTable) return;

    const rows = await apiJson(JOB_EXECUTIONS_LIST_URL);
    const activeRows = (rows || []).filter(isActiveExecution);
    const historyRows = (rows || []).filter(r => !isActiveExecution(r));

    renderExecutionTable(activeTable, activeRows, '暂无正在执行或等待执行的 2560 任务');
    renderExecutionTable(historyTable, historyRows, '暂无历史执行记录');
  }

  function renderExecutionTable(table, rows, emptyText){
    if (!rows || !rows.length) {
      table.innerHTML = `<tbody><tr><td>${emptyText}</td></tr></tbody>`;
      return;
    }

    const cols = ['ID','类型','状态','进度','成功','失败','当前代码','市场','并发','信息','开始时间','结束时间','操作'];
    table.innerHTML =
      '<thead><tr>' + cols.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>' +
      rows.map(r => {
        const progress = `${cell(r.progress_current)}/${cell(r.progress_total)}`;
        const stale = staleLabel(r);
        const statusText = `${cell(r.status)}${stale ? ' / ' + stale : ''}`;
        const action = canCancelJobStatus(r.status)
          ? `<button class="danger cancel-job" data-job-id="${r.id}" title="取消 queued/pending；running 请求后台停止">取消/废弃</button>`
          : '-';
        return `
          <tr data-job-id="${r.id}" style="cursor:pointer">
            <td>${cell(r.id)}</td>
            <td>${cell(r.job_type)}</td>
            <td>${statusText}</td>
            <td>${progress}</td>
            <td>${cell(r.success_count)}</td>
            <td>${cell(r.failed_count)}</td>
            <td>${cell(r.current_code)}</td>
            <td>${cell(r.market)}</td>
            <td>${cell(r.shards)}</td>
            <td>${cell(r.message)}</td>
            <td>${cell(r.started_at)}</td>
            <td>${cell(r.finished_at)}</td>
            <td>${action}</td>
          </tr>
        `;
      }).join('') +
      '</tbody>';

    table.querySelectorAll('tr[data-job-id]').forEach(tr => {
      tr.onclick = function(){
        const id = Number(tr.dataset.jobId);
        if (window.setCurrentJobId) {
          window.setCurrentJobId(id);
        } else {
          window.currentJobId = id;
        }
        loadItems(id);
      };
    });
    table.querySelectorAll('.cancel-job').forEach(btn => {
      btn.onclick = function(ev){
        ev.preventDefault();
        ev.stopPropagation();
        cancelExecution(Number(this.dataset.jobId));
      };
    });
  }

  async function loadLatestItems(){
    const rows = await apiJson(JOB_EXECUTIONS_LATEST_URL);
    if (rows && rows.length) {
      await loadItems(rows[0].id);
    }
  }

  async function loadItems(jobId){
    const table = $('jobItemsTable');
    if (!table || !jobId) return;

    const rows = await apiJson(`/api/jobs/executions/${jobId}/items?limit=300`);

    if (!rows || !rows.length) {
      table.innerHTML = '<tbody><tr><td>暂无任务明细</td></tr></tbody>';
      return;
    }

    const cols = ['ID','Job','Shard','代码','状态','重试','耗时ms','错误','更新时间'];
    table.innerHTML =
      '<thead><tr>' + cols.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>' +
      rows.map(r => `
        <tr>
          <td>${cell(r.id)}</td>
          <td>${cell(r.job_id)}</td>
          <td>${cell(r.shard_id)}</td>
          <td>${cell(r.code)}</td>
          <td>${cell(r.status)}</td>
          <td>${cell(r.retry_count)}</td>
          <td>${cell(r.elapsed_ms)}</td>
          <td>${cell(r.last_error)}</td>
          <td>${cell(r.updated_at)}</td>
        </tr>
      `).join('') +
      '</tbody>';
  }

  window.loadJobs = loadJobs;
  window.loadExecutions = loadExecutions;
  window.loadItems = loadItems;

  document.addEventListener('DOMContentLoaded', ensureJobsPage);
  setInterval(ensureJobsPage, 1000);
})();

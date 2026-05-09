
(function(){
  function $(id){ return document.getElementById(id); }

  function ensureJobsPage(){
    // 1. 创建左侧/顶部菜单按钮
    const nav = document.querySelector('.nav');
    if (nav && !document.querySelector('[data-view="jobs"]')) {
      const btn = document.createElement('button');
      btn.className = 'nav-item';
      btn.dataset.view = 'jobs';
      btn.textContent = '任务队列';
      nav.appendChild(btn);

      btn.onclick = function(){
        document.querySelectorAll('.nav-item').forEach(x => x.classList.remove('active'));
        btn.classList.add('active');

        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        const view = $('view-jobs');
        if (view) view.classList.add('active');

        if ($('pageTitle')) $('pageTitle').textContent = '任务队列';
        if ($('pageSubtitle')) $('pageSubtitle').textContent = '任务队列、执行进度、实时日志与后台运行';

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
                  <option value="sh">sh 上海</option>
                  <option value="sz">sz 深圳</option>
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
              <button id="refreshJobsBtn">刷新任务</button>
            </div>
          </div>

          <pre id="jobActionResult" class="json-box">等待操作</pre>
        </div>

        <div class="panel">
          <div class="panel-head split">
            <h3>任务执行记录（job_execution）</h3>
            <button id="refreshExecutionsBtn">刷新执行记录</button>
          </div>
          <div class="table-wrap">
            <table id="jobExecutionsTable"></table>
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
  }

  async function apiJson(url, opts){
    const r = await fetch(url, opts);
    return await r.json();
  }

  function cell(v){
    return v === null || v === undefined || v === '' ? '-' : v;
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

  async function loadJobs(){
    await loadExecutions();
    await loadLatestItems();
  }

  async function loadExecutions(){
    const table = $('jobExecutionsTable');
    if (!table) return;

    const rows = await apiJson('/api/jobs/executions?limit=50');

    if (!rows || !rows.length) {
      table.innerHTML = '<tbody><tr><td>暂无执行记录</td></tr></tbody>';
      return;
    }

    const cols = ['ID','类型','状态','进度','成功','失败','当前代码','市场','并发','信息','开始时间','结束时间'];
    table.innerHTML =
      '<thead><tr>' + cols.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>' +
      rows.map(r => {
        const progress = `${cell(r.progress_current)}/${cell(r.progress_total)}`;
        return `
          <tr data-job-id="${r.id}" style="cursor:pointer">
            <td>${cell(r.id)}</td>
            <td>${cell(r.job_type)}</td>
            <td>${cell(r.status)}</td>
            <td>${progress}</td>
            <td>${cell(r.success_count)}</td>
            <td>${cell(r.failed_count)}</td>
            <td>${cell(r.current_code)}</td>
            <td>${cell(r.market)}</td>
            <td>${cell(r.shards)}</td>
            <td>${cell(r.message)}</td>
            <td>${cell(r.started_at)}</td>
            <td>${cell(r.finished_at)}</td>
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
  }

  async function loadLatestItems(){
    const rows = await apiJson('/api/jobs/executions?limit=1');
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

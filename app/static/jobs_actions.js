
(function(){
  function $(id){ return document.getElementById(id); }

  async function postJson(url, body){
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    return await r.json();
  }

  function ensureJobsActionPanel(){
    const view = $('view-jobs');
    if (!view) return;

    // 修正顶部标题
    const title = $('pageTitle');
    const sub = $('pageSubtitle');
    if (title && document.querySelector('.nav-item.active')?.dataset?.view === 'jobs') {
      title.textContent = '任务队列';
    }
    if (sub && document.querySelector('.nav-item.active')?.dataset?.view === 'jobs') {
      sub.textContent = '任务队列、执行记录、Shard 明细与手动触发';
    }

    if ($('jobActionPanel')) return;

    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.id = 'jobActionPanel';
    panel.innerHTML = `
      <div class="panel-head split">
        <h3>任务操作</h3>
        <span class="probe-note">入队任务 / 立即执行并行脚本</span>
      </div>

      <div class="filters" style="margin-top:12px;gap:14px;flex-wrap:wrap;align-items:flex-end">

        <label style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:#334155">
          市场范围
          <select id="jobMarket" title="选择要执行的股票市场范围">
                  <option value="sh">sh 上海</option>
                  <option value="sz">sz 深圳</option>
                  <option value="sh60">sh60 沪主板60</option>
                  <option value="sh68">sh68 科创68</option>
                  <option value="sz00">sz00 深主板00</option>
                  <option value="sz30">sz30 创业板30</option>
                </select>
        </label>

        <label style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:#334155">
          并行分片数（shards）
          <input id="jobShards" type="number" min="1" max="32" value="4"
                 title="把股票池拆成多少份并行执行，建议 2 / 4 / 6"
                 placeholder="例如 4" />
        </label>

        <label style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:#334155">
          任务优先级（priority）
          <input id="jobPriority" type="number" min="1" max="9" value="3"
                 title="数字越小优先级越高：1最高，3日常，5普通，9最低"
                 placeholder="例如 3" />
        </label>

        <button id="enqueueJobBtn" class="primary" title="写入 job_queue，由 job_worker 后台执行">
          入队执行
        </button>

        <button id="runNowJobBtn" class="probe-btn danger" title="立即后台启动 daily_update_incremental_sharded.sh">
          立即执行并行脚本
        </button>
      </div>

      <pre id="jobActionResult" class="json-box" style="margin-top:12px">等待操作...</pre>
    `;

    view.insertBefore(panel, view.firstChild);

    $('enqueueJobBtn').onclick = async function(){
      $('jobActionResult').textContent = '正在入队...';
      try {
        const data = await postJson('/api/jobs/enqueue', {
          strategy_code: 'S2560',
          job_type: 'run_2560',
          market: $('jobMarket').value,
          shards: Number($('jobShards').value || 4),
          priority: Number($('jobPriority').value || 3)
        });
        $('jobActionResult').textContent = JSON.stringify(data, null, 2);
        if (typeof loadJobs === 'function') await loadJobs();
      } catch(e) {
        $('jobActionResult').textContent = '入队失败：' + e.message;
      }
    };

    $('runNowJobBtn').onclick = async function(){
      if (!confirm('确认立即执行并行脚本？这会在后台启动 daily_update_incremental_sharded.sh')) return;

      $('jobActionResult').textContent = '正在启动后台脚本...';
      try {
        const data = await postJson('/api/jobs/run-now', {
          market: $('jobMarket').value,
          shards: Number($('jobShards').value || 4)
        });
        $('jobActionResult').textContent = JSON.stringify(data, null, 2);
        if (typeof loadJobs === 'function') await loadJobs();
      } catch(e) {
        $('jobActionResult').textContent = '启动失败：' + e.message;
      }
    };
  }

  document.addEventListener('DOMContentLoaded', ensureJobsActionPanel);

  document.addEventListener('click', function(e){
    if (e.target && e.target.dataset && e.target.dataset.view === 'jobs') {
      setTimeout(ensureJobsActionPanel, 80);
      setTimeout(ensureJobsActionPanel, 300);
    }
  });

  setInterval(function(){
    const active = document.querySelector('.nav-item.active');
    if (active && active.dataset.view === 'jobs') {
      ensureJobsActionPanel();
    }
  }, 1000);
})();

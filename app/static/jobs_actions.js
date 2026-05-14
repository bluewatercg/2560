
(function(){
  function $(id){ return document.getElementById(id); }
  function canCancelJobStatus(status){
    return ['queued', 'pending', 'running', 'cancelling'].includes(String(status || '').toLowerCase());
  }

  async function postJson(url, body){
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    return await r.json();
  }

  async function cancelExecution(jobId){
    if(!jobId) return;
    const reason = prompt(`确认取消/废弃任务 #${jobId}？\n\nqueued/pending 会直接取消；running 会请求后台停止。`, '用户取消/废弃');
    if(reason === null) return;
    const out = $('jobActionResult');
    if(out) out.textContent = `正在取消/废弃任务 #${jobId}...`;
    try{
      const data = await postJson(`/api/jobs/executions/${jobId}/cancel`, {reason});
      if(out) out.textContent = JSON.stringify(data, null, 2);
      if(typeof loadJobs === 'function') await loadJobs();
    }catch(e){
      if(out) out.textContent = '取消/废弃失败：' + (e && e.message ? e.message : String(e));
    }
  }

  function ensureJobsActionPanel(){
    const view = $('view-jobs');
    if (!view) return;

    // 修正顶部标题
    const title = $('pageTitle');
    const sub = $('pageSubtitle');
    if (title && document.querySelector('.nav-item.active')?.dataset?.view === 'jobs') {
      title.textContent = '创建批量任务';
    }
    if (sub && document.querySelector('.nav-item.active')?.dataset?.view === 'jobs') {
      sub.textContent = '创建 2560 批量任务、查看执行记录与 Shard 明细';
    }

    if ($('jobActionPanel')) return;

    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.id = 'jobActionPanel';
    panel.innerHTML = `
      <div class="panel-head split">
        <h3>任务操作</h3>
        <span class="probe-note">入队任务 / 立即执行 2560 分析</span>
      </div>

      <div class="filters" style="margin-top:12px;gap:14px;flex-wrap:wrap;align-items:flex-end">

        <label style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:#94A3B8">
          市场范围
          <select id="jobMarket" title="选择要执行的股票市场范围">
                  <option value="sh60">sh60 沪主板60</option>
                  <option value="sh68">sh68 科创68</option>
                  <option value="sz00">sz00 深主板00</option>
                  <option value="sz30">sz30 创业板30</option>
                </select>
        </label>

        <label style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:#94A3B8">
          并行分片数（shards）
          <input id="jobShards" type="number" min="1" max="32" value="4"
                 title="把股票池拆成多少份并行执行，建议 2 / 4 / 6"
                 placeholder="例如 4" />
        </label>

        <label style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:#94A3B8">
          任务优先级（priority）
          <input id="jobPriority" type="number" min="1" max="9" value="3"
                 title="数字越小优先级越高：1最高，3日常，5普通，9最低"
                 placeholder="例如 3" />
        </label>

        <button id="enqueueJobBtn" class="primary" title="写入 job_queue，由 job_worker 后台执行">
          入队执行
        </button>

        <button id="runNowJobBtn" class="probe-btn danger" title="立即后台启动 2560 并行分析任务">
          立即执行 2560
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
      if (!confirm('确认立即执行 2560 并行分析？这会在后台创建 job_execution 并实时刷新进度。')) return;

      $('jobActionResult').textContent = '正在启动 2560 分析...';
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
    if(e.target && e.target.classList && e.target.classList.contains('cancel-job')){
      e.preventDefault();
      e.stopPropagation();
      cancelExecution(Number(e.target.dataset.jobId));
      return;
    }
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

(function(){
  function $(id){ return document.getElementById(id); }
  async function getJson(url){ const r = await fetch(url); return await r.json(); }
  async function postJson(url, body){ const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); return await r.json(); }
  let currentJobId = null;
  let timer = null;

  function ensureMonitorPanel(){
    const view = $('view-jobs');
    if(!view || $('jobProgressPanel')) return;
    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.id = 'jobProgressPanel';
    panel.innerHTML = `<div class="panel-head split"><h3>当前执行状态</h3><button id="jobProgressRefreshBtn">刷新进度</button></div><div id="jobProgressCards" class="cards"></div><div style="margin:12px 0;height:12px;background:#e5e7eb;border-radius:999px;overflow:hidden"><div id="jobProgressBar" style="height:12px;width:0%;background:#2563eb"></div></div><pre id="jobProgressText" class="json-box">暂无执行任务</pre><h3 style="margin-top:12px">实时日志</h3><pre id="jobLiveLog" class="json-box" style="max-height:320px;overflow:auto">暂无日志</pre>`;
    const action = $('jobActionPanel');
    if(action && action.parentNode) action.parentNode.insertBefore(panel, action.nextSibling); else view.insertBefore(panel, view.firstChild);
    $('jobProgressRefreshBtn').onclick = refreshProgress;
  }

  function patchRunNowButton(){
    const btn = $('runNowJobBtn');
    if(!btn || btn.dataset.progressPatched) return;
    btn.dataset.progressPatched = '1';
    btn.onclick = async function(){
      if(!confirm('确认立即执行并跟踪？建议迁移测试用 sh + shards=1。')) return;
      ensureMonitorPanel();
      const market = $('jobMarket') ? $('jobMarket').value : 'sh';
      const shards = $('jobShards') ? Number($('jobShards').value || 1) : 1;
      $('jobProgressText').textContent = '正在创建跟踪任务...';
      const data = await postJson('/api/jobs/run-now', {market, shards});
      if(!data.ok){ $('jobProgressText').textContent = JSON.stringify(data,null,2); return; }
      currentJobId = data.job_id;
      if($('jobActionResult')) $('jobActionResult').textContent = JSON.stringify(data,null,2);
      startPolling();
    };
  }

  function startPolling(){ if(timer) clearInterval(timer); refreshProgress(); timer = setInterval(refreshProgress, 3000); }

  async function refreshProgress(){
    ensureMonitorPanel();
    if(!currentJobId){ try{ const rows = await getJson('/api/jobs/executions?limit=1'); if(rows && rows.length) currentJobId = rows[0].id; }catch(e){} }
    if(!currentJobId) return;
    const p = await getJson(`/api/jobs/executions/${currentJobId}/progress`);
    if(!p.ok){ $('jobProgressText').textContent = JSON.stringify(p,null,2); return; }
    const percent = p.percent || 0;
    $('jobProgressBar').style.width = percent + '%';
    $('jobProgressCards').innerHTML = [['任务ID',p.id],['状态',p.status],['市场',p.market||'-'],['分片',p.shards||'-'],['进度',`${p.done}/${p.total}`],['百分比',`${percent}%`],['成功',p.success_count||0],['失败',p.failed_count||0],['当前代码',p.current_code||'-'],['已运行',p.elapsed_text||'-'],['均耗时',p.avg_seconds_per_code?`${p.avg_seconds_per_code}s/只`:'-'],['预计剩余',p.eta_text||'-']].map(x=>`<div class="card"><span>${x[0]}</span><strong>${x[1]}</strong></div>`).join('');
    $('jobProgressText').textContent = JSON.stringify(p,null,2);
    const logs = await getJson(`/api/jobs/executions/${currentJobId}/logs?tail=200`);
    if(logs && logs.lines) $('jobLiveLog').textContent = logs.lines.join('\n');
    if(['success','failed','cancelled'].includes(p.status) && timer){ clearInterval(timer); timer=null; }
  }

  function boot(){ ensureMonitorPanel(); patchRunNowButton(); }
  document.addEventListener('DOMContentLoaded', boot);
  document.addEventListener('click', function(e){ if(e.target && e.target.dataset && e.target.dataset.view==='jobs') setTimeout(boot,100); });
  setInterval(boot, 1000);
})();

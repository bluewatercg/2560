(function(){
  function $(id){ return document.getElementById(id); }
  async function getJson(url){ const r = await fetch(url); return await r.json(); }
  async function postJson(url, body){ const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); return await r.json(); }
  const JOB_EXECUTIONS_LATEST_URL = '/api/jobs/executions?job_type=run_2560&job_type=run_2560_now&limit=1';
  let currentJobId = null;
  let timer = null;

  function renameLabels(){
    const view = $('view-jobs');
    if(!view) return;
    const textNodes = [];
    const walker = document.createTreeWalker(view, NodeFilter.SHOW_TEXT, null);
    let node; while(node = walker.nextNode()) textNodes.push(node);
    textNodes.forEach(n=>{
      n.nodeValue = n.nodeValue
        .replace('并行分片数（shards）', '同时跑几组（并发数）')
        .replace('任务优先级（priority）', '任务优先级（数字越小越先跑）')
        .replace('入队执行', '加入队列后台跑')
        .replace('立即执行并行脚本', '立即执行并看进度')
        .replace('任务队列，执行记录、Shard 明细与手动触发', '任务队列、执行进度、实时日志与后台运行');
    });
    if($('runNowJobBtn')) $('runNowJobBtn').textContent = '立即执行并看进度';
    const enqueue = $('enqueueJobBtn'); if(enqueue) enqueue.textContent = '加入队列后台跑';
  }

  function ensureMonitorPanel(){
    const view = $('view-jobs');
    if(!view || $('jobProgressPanel')) return;
    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.id = 'jobProgressPanel';
    panel.innerHTML = `<div class="panel-head split"><h3>当前执行进度</h3><button id="jobProgressRefreshBtn">刷新进度</button></div><div id="jobProgressCards" class="cards"></div><div style="margin:12px 0;height:12px;background:#e5e7eb;border-radius:999px;overflow:hidden"><div id="jobProgressBar" style="height:12px;width:0%;background:#2563eb"></div></div><pre id="jobProgressText" class="json-box">暂无执行任务</pre><h3 style="margin-top:12px">每组执行进度</h3><div class="table-wrap"><table id="jobShardProgressTable"></table></div><h3 style="margin-top:12px">实时后台日志</h3><pre id="jobLiveLog" class="json-box" style="max-height:320px;overflow:auto">暂无日志</pre>`;
    const action = $('jobActionPanel');
    if(action && action.parentNode) action.parentNode.insertBefore(panel, action.nextSibling); else view.insertBefore(panel, view.firstChild);
    $('jobProgressRefreshBtn').onclick = refreshProgress;
  }


  function patchRunNowButton(){
    const btn = $('runNowJobBtn');
    if(!btn || btn.dataset.progressPatched) return;

    btn.dataset.progressPatched = '1';
    btn.textContent = '立即执行并看进度';

    btn.onclick = async function(){
      ensureMonitorPanel();

      const market = $('jobMarket') ? $('jobMarket').value : 'sh';
      const shards = $('jobShards') ? Number($('jobShards').value || 1) : 1;

      const ok = confirm(
        `确认立即执行并跟踪？

` +
        `市场范围：${market}
` +
        `同时跑几组：${shards}

` +
        `迁移测试建议：先用 sh + 1；正式运行再逐步提高。`
      );

      if(!ok) return;

      const progressText = $('jobProgressText');
      if(progressText) progressText.textContent = '正在创建跟踪任务...';

      try {
        const data = await postJson('/api/jobs/run-now', {market, shards});

        if(!data.ok){
          if(progressText) progressText.textContent = JSON.stringify(data, null, 2);
          return;
        }

        currentJobId = data.job_id;

        const resultBox = $('jobActionResult');
        if(resultBox) resultBox.textContent = JSON.stringify(data, null, 2);

        startPolling();
      } catch (e) {
        if(progressText) {
          progressText.textContent =
            '启动失败：' + (e && e.message ? e.message : String(e));
        }
        console.error(e);
      }
    };
  }


  function startPolling(){ if(timer) clearInterval(timer); refreshProgress(); timer = setInterval(refreshProgress, 3000); }



  function renderShardProgress(data){
    const table = $('jobShardProgressTable');
    if(!table) return;

    if(!data || !data.ok || !data.items || !data.items.length){
      table.innerHTML = '<tbody><tr><td>暂无分组进度</td></tr></tbody>';
      return;
    }

    const cols = ['组号','进度','百分比','运行中','待处理','成功','失败','当前代码','平均耗时','更新时间'];

    table.innerHTML =
      '<thead><tr>' +
      cols.map(c => `<th>${c}</th>`).join('') +
      '</tr></thead><tbody>' +
      data.items.map(r => {
        const pct = r.percent || 0;
        const avg = r.avg_elapsed_ms ? `${Math.round(r.avg_elapsed_ms)}ms/只` : '-';

        return `
          <tr>
            <td>第 ${Number(r.shard_id) + 1} 组</td>
            <td>${r.done}/${r.total}</td>
            <td style="min-width:140px">
              <div style="height:8px;background:#e5e7eb;border-radius:99px;overflow:hidden">
                <div style="height:8px;width:${pct}%;background:#16a34a"></div>
              </div>
              <small>${pct}%</small>
            </td>
            <td>${r.running_count || 0}</td>
            <td>${r.pending_count || 0}</td>
            <td>${r.success_count || 0}</td>
            <td>${r.failed_count || 0}</td>
            <td>${r.current_code || '-'}</td>
            <td>${avg}</td>
            <td>${r.updated_at || '-'}</td>
          </tr>
        `;
      }).join('') +
      '</tbody>';
  }

  async function refreshProgress(){
    ensureMonitorPanel();

    if(!currentJobId){
      try{
        const rows = await getJson(JOB_EXECUTIONS_LATEST_URL);
        if(rows && rows.length) currentJobId = rows[0].id;
      }catch(e){}
    }

    if(!currentJobId) return;

    try {
      const p = await getJson(`/api/jobs/executions/${currentJobId}/progress`);

      if(!p.ok){
        const progressText = $('jobProgressText');
        if(progressText) progressText.textContent = JSON.stringify(p, null, 2);
        return;
      }

      const percent = p.percent || 0;

      const bar = $('jobProgressBar');
      if(bar) bar.style.width = percent + '%';

      const cards = $('jobProgressCards');
      if(cards){
        cards.innerHTML = [
          ['任务ID', p.id],
          ['状态', p.status],
          ['市场', p.market || '-'],
          ['同时跑几组', p.shards || '-'],
          ['进度', `${p.done}/${p.total}`],
          ['百分比', `${percent}%`],
          ['成功', p.success_count || 0],
          ['失败', p.failed_count || 0],
          ['最近更新代码', p.current_code || '-'],
          ['已运行', p.elapsed_text || '-'],
          ['平均耗时', p.avg_seconds_per_code ? `${p.avg_seconds_per_code}s/只` : '-'],
          ['预计剩余', p.eta_text || '-']
        ].map(x => `<div class="card"><span>${x[0]}</span><strong>${x[1]}</strong></div>`).join('');
      }

      const progressText = $('jobProgressText');
      if(progressText) progressText.textContent = JSON.stringify(p, null, 2);

      // 每组执行进度
      try {
        const shardData = await getJson(`/api/jobs/executions/${currentJobId}/shards`);
        renderShardProgress(shardData);
      } catch(e) {
        console.error('load shard progress failed', e);
      }

      // 实时后台日志
      try {
        const logs = await getJson(`/api/jobs/executions/${currentJobId}/logs?tail=200`);
        if(logs && logs.lines && $('jobLiveLog')){
          $('jobLiveLog').textContent = logs.lines.join('
');
        }
      } catch(e) {
        console.error('load job logs failed', e);
      }

      if(['success','failed','cancelled'].includes(p.status) && timer){
        clearInterval(timer);
        timer = null;
      }

    } catch(e) {
      const progressText = $('jobProgressText');
      if(progressText){
        progressText.textContent = '刷新进度失败：' + (e && e.message ? e.message : String(e));
      }
      console.error(e);
    }
  }

  function boot(){ renameLabels(); ensureMonitorPanel(); patchRunNowButton(); }
  document.addEventListener('DOMContentLoaded', boot);
  document.addEventListener('click', function(e){ if(e.target && e.target.dataset && e.target.dataset.view==='jobs') setTimeout(boot,100); });
  setInterval(boot, 1000);
})();


// Minimal additive diagnostic helper. It keeps existing UI behavior and injects a diagnostic panel on the run page.
(function(){
  function $(id){return document.getElementById(id)}
  async function api(url,opts){const r=await fetch(url,opts);const d=await r.json();if(!r.ok||d.success===false)throw new Error(d.message||r.statusText);return d.data??d}
  function renderDiagTable(items){
    const box=$('diagTable'); if(!box)return;
    if(!items||!items.length){box.innerHTML='<div class="diag-empty">暂无摸底指标数据</div>';return}
    const cols=['代码','名称','类型','日线','30m','5m','最新30m','MA25','斜率','偏离%','量比','贴MA25','斜率OK','量能OK','状态','未命中原因'];
    box.innerHTML='<div class="table-wrap"><table><thead><tr>'+cols.map(x=>`<th>${x}</th>`).join('')+'</tr></thead><tbody>'+items.map(r=>`<tr><td>${r.code||'-'}</td><td>${r.name||'-'}</td><td>${r.board_type||'-'}</td><td>${r.daily_count}</td><td>${r.k30_count}</td><td>${r.k5_count}</td><td>${r.latest_30m_time||'-'}</td><td>${num(r.ma25_30m)}</td><td>${num(r.ma25_slope_3)}</td><td>${num(r.price_ma25_deviation_pct)}</td><td>${num(r.vol_ratio)}</td><td>${bool(r.price_near_ma25)}</td><td>${bool(r.ma25_slope_ok)}</td><td>${bool(r.volume_structure_ok)}</td><td>${r.status}</td><td>${r.reasons}</td></tr>`).join('')+'</tbody></table></div>'
  }
  function num(v){return v===null||v===undefined?'-':Number(v).toFixed(3)}
  function bool(v){return v===true?'是':v===false?'否':'-'}
  function ensureDiagPanel(){
    if($('diagPanel')||!$('view-run'))return;
    const panel=document.createElement('div');panel.id='diagPanel';panel.className='panel diag-panel';
    panel.innerHTML=`<div class="panel-head split"><h3>2560 摸底指标明细</h3><button id="loadDiagBtn" class="ghost">查看当前筛选指标</button></div><div id="diagSummary" class="diag-summary">即使 signals=0，也可查看每只股票的 30m / MA25 / 量能 / 未命中原因。</div><div id="diagTable"></div>`;
    $('view-run').appendChild(panel);
    $('loadDiagBtn').onclick=loadDiagnostics;
  }
  async function loadDiagnostics(){
    const mt=$('marketTypeFilter')?$('marketTypeFilter').value:'all';
    const q=$('stockSearch')?$('stockSearch').value.trim():'';
    const limit=prompt('加载多少只股票的摸底指标？建议先 500，最多 5000。','500')||'500';
    $('diagSummary').textContent='正在加载摸底指标...';
    try{
      const d=await api('/api/strategy/2560/probe-indicators?market_type='+encodeURIComponent(mt)+'&limit='+encodeURIComponent(limit)+(q?'&q='+encodeURIComponent(q):''));
      const s=d.summary||{};
      $('diagSummary').textContent=`总数 ${s.total||0}；缺30m ${s.missing_30m||0}；缺日线 ${s.missing_daily||0}；基础条件满足 ${s.base_ok||0}`;
      renderDiagTable(d.items||[]);
    }catch(e){$('diagSummary').textContent='加载失败：'+e.message}
  }
  const oldRefresh=window.refresh;
  function hook(){ensureDiagPanel()}
  document.addEventListener('click',()=>setTimeout(hook,50));
  setTimeout(hook,500);
})();

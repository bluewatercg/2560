(function(){
  function $(id){ return document.getElementById(id); }
  async function apiJson(url){ const r=await fetch(url); return await r.json(); }
  function cell(v){ return v===null||v===undefined||v==='' ? '-' : v; }

  function ensure2568Page(){
    const nav=document.querySelector('.nav');
    if(nav && !document.querySelector('[data-view="annotation2568"]')){
      const btn=document.createElement('button'); btn.className='nav-item'; btn.dataset.view='annotation2568'; btn.textContent='2568标注'; nav.appendChild(btn);
      btn.onclick=async()=>{document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));$('view-annotation2568')?.classList.add('active'); if($('pageTitle'))$('pageTitle').textContent='2568标注'; if($('pageSubtitle'))$('pageSubtitle').textContent='A/B/C/D亮点分级 + 人工筛选建议'; await load2568Annotations();};
    }
    const main=document.querySelector('main.main');
    if(main && !$('view-annotation2568')){
      const section=document.createElement('section'); section.id='view-annotation2568'; section.className='view';
      section.innerHTML=`<div class="panel"><div class="panel-head split"><h3>2568 A/B/C/D 亮点筛选</h3><div class="filters" style="gap:8px;flex-wrap:wrap"><select id="ann2568Market"><option value="all">全部</option><option value="sh">sh</option><option value="sz">sz</option><option value="sh60">sh60</option><option value="sh68">sh68</option><option value="sz00">sz00</option><option value="sz30">sz30</option></select><select id="ann2568Action"><option value="">全部人工建议</option><option value="强势票｜重点关注">强势票｜重点关注</option><option value="有核心亮点｜可关注">有核心亮点｜可关注</option><option value="中强票｜观察池">中强票｜观察池</option><option value="健康趋势｜可观察">健康趋势｜可观察</option><option value="风险较多｜建议移出">风险较多｜建议移出</option><option value="风险偏多｜谨慎观察">风险偏多｜谨慎观察</option><option value="有风险｜人工确认">有风险｜人工确认</option></select><select id="ann2568MinA"><option value="">A不限</option><option value="1">A≥1</option><option value="2">A≥2</option></select><select id="ann2568MinB"><option value="">B不限</option><option value="2">B≥2</option><option value="3">B≥3</option></select><select id="ann2568MinD"><option value="">D不限</option><option value="1">D≥1</option><option value="2">D≥2</option><option value="3">D≥3</option></select><label class="check-line"><input id="ann2568RiskOnly" type="checkbox" />只看风险</label><input id="ann2568Q" placeholder="代码/名称"/><input id="ann2568Limit" type="number" value="500" min="1" max="5000"/><button id="ann2568LoadBtn" class="primary">加载标注</button></div></div><div id="ann2568SummaryCards" class="cards"></div><div class="table-wrap"><table id="ann2568Table"></table></div></div>`;
      const drawer=$('detailDrawer'); if(drawer) main.insertBefore(section,drawer); else main.appendChild(section); $('ann2568LoadBtn').onclick=load2568Annotations;
    }
  }
  async function load2568Annotations(){
    ensure2568Page(); let url='/api/strategy/2568/annotations?market_type='+encodeURIComponent($('ann2568Market')?.value||'all')+'&limit='+encodeURIComponent($('ann2568Limit')?.value||500)+'&risk_only='+(($('ann2568RiskOnly')?.checked)?1:0);
    const action=$('ann2568Action')?.value||'', minA=$('ann2568MinA')?.value||'', minB=$('ann2568MinB')?.value||'', minD=$('ann2568MinD')?.value||'', q=$('ann2568Q')?.value.trim()||'';
    if(action) url+='&manual_action='+encodeURIComponent(action); if(minA) url+='&min_a='+minA; if(minB) url+='&min_b='+minB; if(minD) url+='&min_d='+minD; if(q) url+='&q='+encodeURIComponent(q);
    const data=await apiJson(url); const s=data.summary||{}, by=s.by_label||{}, act=s.by_action||{};
    if($('ann2568SummaryCards')) $('ann2568SummaryCards').innerHTML=[['总数',s.total||0],['强满足',by['强满足']||0],['临界',by['临界']||0],['弱满足',by['弱满足']||0],['重点关注',act['强势票｜重点关注']||0],['风险较多',act['风险较多｜建议移出']||0]].map(x=>`<div class="card"><span>${x[0]}</span><strong>${x[1]}</strong></div>`).join('');
    const rows=data.items||[], table=$('ann2568Table'); if(!rows.length){table.innerHTML='<tbody><tr><td>暂无数据</td></tr></tbody>';return;}
    const cols=['代码','名称','人工建议','等级','A','B','D','亮点总结','A亮点','B亮点','D风险','总结','风险','MA25','MA60','价格','量能','趋势','回踩'];
    table.innerHTML='<thead><tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>`<tr><td>${cell(r.code)}</td><td>${cell(r.name)}</td><td><b>${cell(r.manual_action_label)}</b></td><td>${cell(r.highlight_level)}</td><td>${cell(r.a_count)}</td><td>${cell(r.b_count)}</td><td>${cell(r.d_count)}</td><td style="min-width:360px">${cell(r.highlight_summary)}</td><td>${cell(r.a_highlights)}</td><td>${cell(r.b_highlights)}</td><td>${cell(r.d_highlights)}</td><td>${cell(r.summary_label)}</td><td>${cell(r.risk_tags)}</td><td>${cell(r.ma25_status)}</td><td>${cell(r.ma60_status)}</td><td>${cell(r.price_status)}</td><td>${cell(r.volume_status)}</td><td>${cell(r.trend_status)}</td><td>${cell(r.pullback_status)}</td></tr>`).join('')+'</tbody>';
  }
  window.load2568Annotations=load2568Annotations; document.addEventListener('DOMContentLoaded',ensure2568Page); setInterval(ensure2568Page,1000);
})();

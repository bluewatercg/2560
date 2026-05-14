(function(){
  function $(id){ return document.getElementById(id); }
  async function apiJson(url){ const r=await fetch(url); return await r.json(); }
  function cell(v){ return v===null||v===undefined||v==='' ? '-' : v; }

  function ensureObservationPoolPage(){
    const nav=document.querySelector('.nav');
    if(nav && !document.querySelector('[data-view="observation-pool"]')){
      const btn=document.createElement('button');
      btn.className='nav-item';
      btn.dataset.view='observation-pool';
      btn.textContent='今日观察池';
      nav.appendChild(btn);
      btn.onclick=async()=>{
        document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
        btn.classList.add('active');
        document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
        $('view-observation-pool')?.classList.add('active');
        if($('pageTitle')) $('pageTitle').textContent='今日观察池';
        if($('pageSubtitle')) $('pageSubtitle').textContent='看什么、为什么看、持有怎么办、没持有怎么买、什么情况跑';
        await loadObservationPool();
      };
    }

    const main=document.querySelector('main.main');
    if(main && !$('view-observation-pool')){
      const section=document.createElement('section');
      section.id='view-observation-pool';
      section.className='view';
      section.innerHTML=`
        <div class="panel">
          <div class="panel-head split">
            <h3>今日观察池</h3>
            <div class="filters" style="gap:8px;flex-wrap:wrap">
              <select id="obsMarket">
                <option value="all">全部四类</option>
                <option value="sh60">sh60</option>
                <option value="sh68">sh68</option>
                <option value="sz00">sz00</option>
                <option value="sz30">sz30</option>
              </select>
              <select id="obsLevel">
                <option value="">全部等级</option>
                <option value="A">A级</option>
                <option value="B">B级</option>
                <option value="C">C级</option>
                <option value="D">D级</option>
              </select>
              <select id="obsAction">
                <option value="">全部人工建议</option>
                <option value="强势票｜重点关注">强势票｜重点关注</option>
                <option value="有核心亮点｜可关注">有核心亮点｜可关注</option>
                <option value="中强票｜观察池">中强票｜观察池</option>
                <option value="健康趋势｜可观察">健康趋势｜可观察</option>
                <option value="风险较多｜建议移出">风险较多｜建议移出</option>
              </select>
              <input id="obsQ" placeholder="代码/名称" style="width:120px"/>
              <button id="obsCopyBtn" class="ghost">复制简版</button>
              <button id="obsCopyDetailBtn" class="ghost">复制详细版</button>
              <button id="obsLoadBtn" class="primary">加载</button>
            </div>
          </div>
          <div id="obsSummaryCards" class="cards"></div>
          <div class="table-wrap" style="overflow-x:auto;white-space:nowrap"><table id="obsTable"></table></div>
        </div>`;
      const drawer=$('detailDrawer');
      if(drawer) main.insertBefore(section,drawer); else main.appendChild(section);
      $('obsLoadBtn').onclick=loadObservationPool;
      $('obsCopyBtn').onclick=copyObservationPool;
      $('obsCopyDetailBtn').onclick=copyObservationPoolDetail;
    }
  }

  async function loadObservationPool(){
    ensureObservationPoolPage();
    let url='/api/strategy/2568/annotations?market_type='+encodeURIComponent($('obsMarket')?.value||'all')
      +'&limit=500'
      +'&risk_only=0';
    const level=$('obsLevel')?.value||'';
    if(level==='A') url+='&min_a=1';
    else if(level==='B') url+='&min_b=2';
    else if(level==='D') url+='&min_d=1';
    const action=$('obsAction')?.value||'';
    if(action) url+='&manual_action='+encodeURIComponent(action);
    const q=$('obsQ')?.value.trim()||'';
    if(q) url+='&q='+encodeURIComponent(q);

    const data=await apiJson(url);
    const s=data.summary||{}, by=s.by_label||{};
    if($('obsSummaryCards')){
      $('obsSummaryCards').innerHTML=[
        ['总数',s.total||0],
        ['强满足',by['强满足']||0],
        ['临界',by['临界']||0],
        ['弱满足',by['弱满足']||0],
      ].map(x=>`<div class="card"><span>${x[0]}</span><strong>${x[1]}</strong></div>`).join('');
    }
    const rows=data.items||[], table=$('obsTable');
    if(!rows.length){
      table.innerHTML='<tbody><tr><td>暂无数据</td></tr></tbody>';
      return;
    }
    const cols=['代码','名称','等级','人工建议','亮点总结','风险标签','MA25','趋势','回踩','2560状态'];
    table.innerHTML=
      '<thead><tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>'+
      rows.map(r=>`
        <tr>
          <td>${cell(r.code)}</td>
          <td>${cell(r.name)}</td>
          <td><b>${cell(r.highlight_level)}</b></td>
          <td>${cell(r.manual_action_label)}</td>
          <td class="muted" style="min-width:180px;white-space:normal;max-width:300px;word-break:break-word">${cell(r.highlight_summary)}</td>
          <td style="min-width:120px;white-space:normal;color:#F87171">${cell(r.risk_tags)}</td>
          <td style="min-width:80px">${cell(r.ma25_status)}</td>
          <td>${cell(r.trend_status)}</td>
          <td>${cell(r.pullback_status)}</td>
          <td>${cell(r.latest_2560_status)}</td>
        </tr>`).join('')+'</tbody>';

    // Store for copy
    window._obsData=rows;
  }

  function copyObservationPool(){
    const rows=window._obsData||[];
    if(!rows.length){ alert('暂无数据可复制'); return; }
    let text='今日观察池\n';
    text+='=' .repeat(50)+'\n';
    rows.forEach(r=>{
      text+=`\n${r.code||'-'} ${r.name||'-'} | ${r.highlight_level||'-'} | ${r.manual_action_label||'-'}\n`;
      if(r.highlight_summary) text+=`  亮点：${r.highlight_summary}\n`;
      if(r.risk_tags) text+=`  风险：${r.risk_tags}\n`;
      text+=`  MA25：${r.ma25_status||'-'} | 趋势：${r.trend_status||'-'} | 回踩：${r.pullback_status||'-'}\n`;
    });
    navigator.clipboard.writeText(text).then(()=>{
      alert('已复制到剪贴板');
    }).catch(()=>{
      prompt('复制以下文本：', text);
    });
  }

  function copyObservationPoolDetail(){
    const rows=window._obsData||[];
    if(!rows.length){ alert('暂无数据可复制'); return; }
    const now=new Date();
    const ts=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
    let text=`今日观察池详细报告\n生成时间：${ts}\n`;
    text+='='.repeat(50)+'\n';
    rows.forEach((r,i)=>{
      text+=`\n【${r.code||'-'}】${r.name||'-'}\n`;
      text+=`等级：${r.highlight_level||'-'}\n`;
      text+=`人工建议：${r.manual_action_label||'-'}\n`;
      if(r.highlight_summary) text+=`亮点总结：${r.highlight_summary}\n`;
      text+=`风险标签：${r.risk_tags||'-'}\n`;
      text+=`MA25状态：${r.ma25_status||'-'}\n`;
      text+=`趋势状态：${r.trend_status||'-'}\n`;
      text+=`回踩状态：${r.pullback_status||'-'}\n`;
      text+=`2560状态：${r.latest_2560_status||'-'}\n`;
      if(i<rows.length-1) text+='\n---\n';
    });
    navigator.clipboard.writeText(text).then(()=>{
      alert('详细版已复制到剪贴板');
    }).catch(()=>{
      prompt('复制以下文本：', text);
    });
  }

  window.loadObservationPool=loadObservationPool;
  document.addEventListener('DOMContentLoaded',ensureObservationPoolPage);
  setInterval(ensureObservationPoolPage,1000);
})();

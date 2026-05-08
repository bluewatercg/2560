(function(){
  function $(id){ return document.getElementById(id); }
  function qs(){
    const mt=$('ann2568Market')?.value||'all';
    const summary=$('ann2568Summary')?.value||'';
    const action=$('ann2568Action')?.value||'';
    const minA=$('ann2568MinA')?.value||'';
    const minB=$('ann2568MinB')?.value||'';
    const minD=$('ann2568MinD')?.value||'';
    const riskOnly=$('ann2568RiskOnly')?.checked?1:0;
    const q=$('ann2568Q')?.value.trim()||'';
    const limit=$('ann2568Limit')?.value||500;
    let url='market_type='+encodeURIComponent(mt)+'&limit='+encodeURIComponent(limit)+'&risk_only='+riskOnly;
    if(summary) url+='&summary='+encodeURIComponent(summary);
    if(action) url+='&manual_action='+encodeURIComponent(action);
    if(minA) url+='&min_a='+encodeURIComponent(minA);
    if(minB) url+='&min_b='+encodeURIComponent(minB);
    if(minD) url+='&min_d='+encodeURIComponent(minD);
    if(q) url+='&q='+encodeURIComponent(q);
    return url;
  }
  function ensurePdfButton(){
    const panel=document.querySelector('#view-annotation2568 .panel-head .filters');
    if(!panel || $('ann2568PdfBtn')) return;
    const btn=document.createElement('button');
    btn.id='ann2568PdfBtn';
    btn.className='ghost';
    btn.textContent='导出PDF解读';
    btn.title='按当前筛选条件导出2568标注报表解读PDF';
    btn.onclick=function(){
      window.open('/api/strategy/2568/report.pdf?'+qs(), '_blank');
    };
    panel.appendChild(btn);
  }
  document.addEventListener('DOMContentLoaded', ensurePdfButton);
  document.addEventListener('click', function(e){ if(e.target && e.target.dataset && e.target.dataset.view==='annotation2568') setTimeout(ensurePdfButton,200); });
  setInterval(ensurePdfButton,1000);
})();

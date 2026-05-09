(function(){
  function replaceText(root){
    if(!root) return;
    const walker=document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    let n; const nodes=[]; while(n=walker.nextNode()) nodes.push(n);
    nodes.forEach(x=>{x.nodeValue=x.nodeValue
      .replace('入库计算','自选股计算')
      .replace('任务队列','市场批量任务')
      .replace('数据更新','数据导入')
      .replace('数据查询','查询分析')
      .replace('摸底指标','数据健康')
      .replace('最新分析结果','最新结果')
      .replace('完整结构','结构详情')
      .replace('结构统计','市场统计')
      .replace('立即执行并行脚本','立即执行并看进度')
      .replace('入队执行','加入队列后台跑')
      .replace('并行分片数（shards）','同时跑几组（并发数）');});
  }
  function boot(){replaceText(document.body);}
  document.addEventListener('DOMContentLoaded', boot); setInterval(boot,1500);
})();

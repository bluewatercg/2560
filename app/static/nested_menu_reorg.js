(function(){
  const DATA_PREP_VIEWS = new Set([
    'data-import',
    'data-maintenance'
  ]);

  const VIRTUAL_VIEWS = new Set([
    'workspace',
    'simple-2560',
    'data-import',
    'data-maintenance',
    'observation-pool',
    'annotation2568'
  ]);

  const DEPRECATED_VIEWS = new Set([
    'diagnostics',
    'diagnostic-indicators',
    'annotation-2568',
    'strategy-2568',
    'complete',
    'run',
    'overview'
  ]);

  const MENU_GROUPS = [
    {
      title: '盘后日常',
      items: [
        ['workspace', '今日工作台'],
        ['workflow', '一键盘后流程'],
        ['quality', '数据质量'],
        ['jobs', '任务进度']
      ]
    },
    {
      title: '数据管理',
      items: [
        ['data-import', '行情导入与日志'],
        ['data-maintenance', '数据构建与维护']
      ]
    },
    {
      title: '结果中心',
      items: [
        ['simple-2560', '简版2560'],
        ['latest', '最新结果'],
        ['signals', '信号中心'],
        ['observation-pool', '今日观察池'],
        ['annotation2568', '2568 标注'],
        ['statistics', '结果统计']
      ]
    },
    {
      title: '系统运维',
      items: [
        ['batches', '分析批次']
      ]
    }
  ];

  const TOP_LEVEL = [];

  function $(sel, root=document){
    return root.querySelector(sel);
  }

  function all(sel, root=document){
    return Array.from(root.querySelectorAll(sel));
  }

  function renameCommonText(){
    const replacements = [
      ['入库计算', '自选股计算'],
      ['数据更新', '数据导入'],
      ['数据导入', '数据导入'],
      ['数据查询', '分析结果'],
      ['查询分析', '分析结果'],
      ['最新分析结果', '最新结果'],
      ['信号列表', '信号中心'],
      ['结构统计', '市场统计'],
      ['并行分片数（shards）', '同时跑几组（并发数）'],
      ['任务优先级（priority）', '优先级（数字越小越先跑）'],
      ['立即执行并行脚本', '立即执行并看进度'],
      ['入队执行', '加入队列后台跑'],
      ['工作流指导', '工作流说明']
    ];

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    const nodes = [];
    let n;
    while(n = walker.nextNode()) nodes.push(n);

    nodes.forEach(node => {
      let text = node.nodeValue;
      replacements.forEach(([a, b]) => {
        text = text.split(a).join(b);
      });
      node.nodeValue = text;
    });
  }

  function makeNavButton(view, label){
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.dataset.view = view;
    btn.textContent = label;
    btn.className = 'nav-item';
    return btn;
  }

  function normalizeButton(btn, label, subItem){
    btn.textContent = label;
    btn.classList.add('nav-item');
    btn.classList.toggle('nav-sub-item', Boolean(subItem));
    return btn;
  }

  function makeCollapsibleGroup(title){
    const wrap = document.createElement('div');
    wrap.className = 'nav-static-group';
    wrap.dataset.groupTitle = title;

    const heading = document.createElement('div');
    heading.className = 'nav-group-title';
    heading.tabIndex = 0;
    heading.innerHTML = `<span>${title}</span><svg class="chevron" width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

    const sub = document.createElement('div');
    sub.className = 'nav-sub';

    wrap.appendChild(heading);
    wrap.appendChild(sub);
    return {wrap, heading, sub};
  }

  function rebuildMenu(){
    const nav = document.querySelector('.nav');
    if(!nav || nav.dataset.staticMenuApplied === '1') return;

    const oldButtons = all('.nav-item[data-view]', nav);
    if(!oldButtons.length) return;

    // Capture which view was active before rebuild
    const activeView = (() => {
      for(const btn of oldButtons){
        if(btn.classList.contains('active')){
          return DEPRECATED_VIEWS.has(btn.dataset.view) ? 'workspace' : btn.dataset.view;
        }
      }
      return 'workspace';
    })();

    const byView = new Map();
    oldButtons.forEach(btn => {
      const view = btn.dataset.view;
      if(DEPRECATED_VIEWS.has(view)) return;
      if(view && !byView.has(view)) byView.set(view, btn);
    });

    const used = new Set();
    nav.innerHTML = '';
    nav.dataset.staticMenuApplied = '1';

    // Top-level items
    TOP_LEVEL.forEach(([view, label]) => {
      const btn = byView.get(view) || makeNavButton(view, label);
      normalizeButton(btn, label, false);
      if(view === activeView) btn.classList.add('active');
      nav.appendChild(btn);
      used.add(view);
    });

    let groupSubs = [];

    // Grouped items
    MENU_GROUPS.forEach(group => {
      const {wrap, heading, sub} = makeCollapsibleGroup(group.title);
      groupSubs.push({heading, sub});

      // Accordion toggle: expand this, collapse all others
      function toggleGroup(){
        const isAlreadyOpen = !sub.classList.contains('collapsed');
        groupSubs.forEach(({heading: h, sub: s}) => {
          s.classList.add('collapsed');
          h.classList.add('collapsed');
        });
        if(!isAlreadyOpen){
          sub.classList.remove('collapsed');
          heading.classList.remove('collapsed');
        }
      }

      heading.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleGroup();
      });
      heading.addEventListener('keydown', (e) => {
        if(e.key === 'Enter' || e.key === ' '){
          e.preventDefault();
          toggleGroup();
        }
      });

      let count = 0;
      group.items.forEach(([view, label]) => {
        const btn = byView.get(view) || (VIRTUAL_VIEWS.has(view) ? makeNavButton(view, label) : null);
        if(!btn) return;
        normalizeButton(btn, label, true);
        if(view === activeView) btn.classList.add('active');
        sub.appendChild(btn);
        used.add(view);
        count += 1;
      });

      // Start collapsed by default in accordion mode
      sub.classList.add('collapsed');
      heading.classList.add('collapsed');

      if(count > 0) nav.appendChild(wrap);
    });

    // Remaining uncategorized items
    const rest = oldButtons.filter(btn => {
      const view = btn.dataset.view;
      return view && !used.has(view);
    });
    if(rest.length){
      const {wrap, heading, sub} = makeCollapsibleGroup('其他');
      groupSubs.push({heading, sub});

      heading.addEventListener('click', (e) => {
        e.stopPropagation();
        const isAlreadyOpen = !sub.classList.contains('collapsed');
        groupSubs.forEach(({heading: h, sub: s}) => {
          s.classList.add('collapsed');
          h.classList.add('collapsed');
        });
        if(!isAlreadyOpen){
          sub.classList.remove('collapsed');
          heading.classList.remove('collapsed');
        }
      });
      heading.addEventListener('keydown', (e) => {
        if(e.key === 'Enter' || e.key === ' '){
          e.preventDefault();
          heading.click();
        }
      });
      // Start collapsed
      sub.classList.add('collapsed');
      heading.classList.add('collapsed');
      rest.forEach(btn => {
        normalizeButton(btn, btn.textContent.trim() || btn.dataset.view, true);
        sub.appendChild(btn);
      });
      nav.appendChild(wrap);
    }

    bindNav(nav, groupSubs);
  }

  function showDataPrepView(view){
    if(window.showDataImportView){
      window.showDataImportView(view);
      return;
    }

    all('.view').forEach(v => v.classList.remove('active'));
    const section = $('#view-data-update');
    if(section) section.classList.add('active');

    const titleMap = {
      'data-import': ['行情导入与日志', '扫描源文件、导入日线/5m，并查看导入批次和失败文件。'],
      'data-maintenance': ['数据构建与维护', '重建 30m、每周指标重算、查看派生任务批次。']
    };
    const [title, subtitle] = titleMap[view] || titleMap['data-import'];
    if($('#pageTitle')) $('#pageTitle').textContent = title;
    if($('#pageSubtitle')) $('#pageSubtitle').textContent = subtitle;
  }

  function bindNav(nav, groupSubs){
    if(nav.dataset.staticMenuBound === '1') return;
    nav.dataset.staticMenuBound = '1';

    nav.addEventListener('click', function(e){
      const item = e.target.closest('.nav-item[data-view]');
      if(!item) return;
      const view = item.dataset.view || '';

      // If the clicked item is inside a collapsed group, expand it and collapse others
      if(groupSubs){
        for(const {heading, sub} of groupSubs){
          if(sub.contains(item) && sub.classList.contains('collapsed')){
            groupSubs.forEach(({heading: h, sub: s}) => {
              s.classList.add('collapsed');
              h.classList.add('collapsed');
            });
            sub.classList.remove('collapsed');
            heading.classList.remove('collapsed');
            break;
          }
        }
      }

      if(DATA_PREP_VIEWS.has(view)){
        e.preventDefault();
        e.stopPropagation();
        showDataPrepView(view);
        return;
      }

      // Delegate all standard navigation to app.js's navigateTo
      if(window.navigateTo){
        e.preventDefault();
        e.stopPropagation();
        window.navigateTo(view);
      }
    });
  }

  function boot(){
    renameCommonText();
    rebuildMenu();
  }

  document.addEventListener('DOMContentLoaded', boot);
  setTimeout(boot, 200);
})();

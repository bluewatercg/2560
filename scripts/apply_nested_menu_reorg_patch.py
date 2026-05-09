#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = STATIC / "index.html"

JS_PATH = STATIC / "nested_menu_reorg.js"
CSS_PATH = STATIC / "nested_menu_reorg.css"

JS = r'''
(function(){
  const MENU_GROUPS = [
    {
      title: '自选股计算',
      items: [
        ['run', '自选股计算'],
        ['watchlist-calc', '自选股计算'],
        ['manual-calc', '手动输入计算'],
        ['calc-result', '本次计算结果']
      ]
    },
    {
      title: '市场批量任务',
      items: [
        ['jobs', '创建批量任务'],
        ['job-progress', '当前执行进度'],
        ['job-history', '历史任务'],
        ['job-items', '任务明细'],
        ['batches', '批次管理']
      ]
    },
    {
      title: '数据导入',
      items: [
        ['data-update', '数据导入'],
        ['import-scan', '导入目录扫描'],
        ['import-run', '行情文件导入'],
        ['import-batches', '导入批次'],
        ['import-logs', '导入日志'],
        ['import-errors', '失败文件']
      ]
    },
    {
      title: '查询分析',
      items: [
        ['latest', '最新结果'],
        ['signals', '信号中心'],
        ['complete', '结构详情'],
        ['statistics', '市场统计'],
        ['quality', '数据健康'],
        ['diagnostic-indicators', '摸底指标'],
        ['annotation2568', '2568 标注'],
        ['annotation-2568', '2568 标注'],
        ['strategy-2568', '2568 标注']
      ]
    },
    {
      title: '系统诊断',
      items: [
        ['diagnostics', '系统诊断'],
        ['db-check', '数据库连接'],
        ['path-check', '行情目录检查'],
        ['table-check', '表结构检查'],
        ['env-check', '运行环境']
      ]
    }
  ];

  const TOP_LEVEL = [
    ['overview', '首页总览'],
    ['workflow', '工作流说明']
  ];

  function $(sel, root=document){
    return root.querySelector(sel);
  }

  function all(sel, root=document){
    return Array.from(root.querySelectorAll(sel));
  }

  function renameCommonText(){
    const replacements = [
      ['入库计算', '自选股计算'],
      ['任务队列', '市场批量任务'],
      ['数据更新', '数据导入'],
      ['数据查询', '查询分析'],
      ['最新分析结果', '最新结果'],
      ['信号列表', '信号中心'],
      ['完整结构', '结构详情'],
      ['结构统计', '市场统计'],
      ['摸底指标', '数据健康'],
      ['并行分片数（shards）', '同时跑几组（并发数）'],
      ['任务优先级（priority）', '优先级（数字越小越先跑）'],
      ['立即执行并行脚本', '立即执行并看进度'],
      ['入队执行', '加入队列后台跑']
    ];

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    const nodes = [];
    let n;
    while(n = walker.nextNode()) nodes.push(n);

    nodes.forEach(node => {
      let text = node.nodeValue;
      replacements.forEach(([a,b]) => {
        text = text.split(a).join(b);
      });
      node.nodeValue = text;
    });
  }

  function makeGroup(title){
    const wrap = document.createElement('div');
    wrap.className = 'nav-group';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nav-group-title';
    btn.innerHTML = `<span>${title}</span><span class="nav-group-arrow">▾</span>`;

    const sub = document.createElement('div');
    sub.className = 'nav-sub';

    btn.addEventListener('click', () => {
      wrap.classList.toggle('collapsed');
    });

    wrap.appendChild(btn);
    wrap.appendChild(sub);

    return {wrap, sub};
  }

  function normalizeButton(btn, label){
    btn.textContent = label;
    btn.classList.add('nav-item');
    btn.classList.add('nav-sub-item');
    return btn;
  }

  function rebuildMenu(){
    const nav = document.querySelector('.nav');
    if(!nav || nav.dataset.nestedMenuApplied === '1') return;

    const oldButtons = all('.nav-item[data-view]', nav);
    if(!oldButtons.length) return;

    const byView = new Map();
    oldButtons.forEach(btn => {
      const view = btn.dataset.view;
      if(view && !byView.has(view)) byView.set(view, btn);
    });

    const used = new Set();

    nav.innerHTML = '';
    nav.dataset.nestedMenuApplied = '1';

    // 顶部一级独立入口
    TOP_LEVEL.forEach(([view, label]) => {
      const btn = byView.get(view);
      if(btn){
        btn.textContent = label;
        btn.classList.remove('nav-sub-item');
        btn.classList.add('nav-item');
        nav.appendChild(btn);
        used.add(view);
      }
    });

    // 分组入口
    MENU_GROUPS.forEach(group => {
      const {wrap, sub} = makeGroup(group.title);
      let count = 0;

      group.items.forEach(([view, label]) => {
        const btn = byView.get(view);
        if(btn){
          normalizeButton(btn, label);
          sub.appendChild(btn);
          used.add(view);
          count += 1;
        }
      });

      if(count > 0){
        nav.appendChild(wrap);
      }
    });

    // 未归类的旧菜单放到“其他”
    const rest = oldButtons.filter(btn => {
      const view = btn.dataset.view;
      return view && !used.has(view);
    });

    if(rest.length){
      const {wrap, sub} = makeGroup('其他');
      rest.forEach(btn => {
        normalizeButton(btn, btn.textContent.trim() || btn.dataset.view);
        sub.appendChild(btn);
      });
      nav.appendChild(wrap);
    }

    bindActiveGroup();
  }

  function bindActiveGroup(){
    const nav = document.querySelector('.nav');
    if(!nav) return;

    nav.addEventListener('click', function(e){
      const item = e.target.closest('.nav-item[data-view]');
      if(!item) return;

      all('.nav-item[data-view]', nav).forEach(x => x.classList.remove('active'));
      item.classList.add('active');

      const group = item.closest('.nav-group');
      if(group){
        group.classList.remove('collapsed');
      }
    });
  }

  function expandGroupForActive(){
    const active = document.querySelector('.nav .nav-item.active[data-view]');
    if(!active) return;

    const group = active.closest('.nav-group');
    if(group){
      group.classList.remove('collapsed');
    }
  }

  function boot(){
    renameCommonText();
    rebuildMenu();
    expandGroupForActive();
  }

  document.addEventListener('DOMContentLoaded', boot);
  setTimeout(boot, 200);
  setInterval(boot, 1500);
})();
'''

CSS = r'''
/* Nested menu reorg */

.nav {
  gap: 4px;
}

.nav-group {
  margin: 6px 0;
  border-top: 1px solid rgba(148, 163, 184, 0.25);
  padding-top: 6px;
}

.nav-group-title {
  width: 100%;
  border: 0;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  border-radius: 8px;
}

.nav-group-title:hover {
  background: rgba(148, 163, 184, 0.12);
  color: #334155;
}

.nav-group-arrow {
  font-size: 11px;
  transition: transform 0.15s ease;
}

.nav-group.collapsed .nav-group-arrow {
  transform: rotate(-90deg);
}

.nav-sub {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-left: 8px;
  padding-left: 8px;
  border-left: 2px solid rgba(148, 163, 184, 0.18);
}

.nav-group.collapsed .nav-sub {
  display: none;
}

.nav-sub-item {
  font-size: 13px;
  padding-left: 14px !important;
}

.nav-sub-item.active {
  font-weight: 700;
}
'''

def inject_once(text: str, snippet: str, marker: str, before: str) -> str:
    if marker in text:
        return text
    if before in text:
        return text.replace(before, snippet + "\n" + before)
    return text + "\n" + snippet + "\n"

def main():
    STATIC.mkdir(parents=True, exist_ok=True)

    JS_PATH.write_text(JS, encoding="utf-8")
    CSS_PATH.write_text(CSS, encoding="utf-8")

    if not INDEX.exists():
        raise SystemExit("ERROR: app/static/index.html 不存在")

    backup = INDEX.with_suffix(".html.bak_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.write_text(INDEX.read_text(encoding="utf-8"), encoding="utf-8")

    html = INDEX.read_text(encoding="utf-8")

    css_link = '  <link rel="stylesheet" href="/static/nested_menu_reorg.css?v=1">'
    js_script = '  <script src="/static/nested_menu_reorg.js?v=1"></script>'

    html = inject_once(
        html,
        css_link,
        "/static/nested_menu_reorg.css",
        "</head>"
    )

    html = inject_once(
        html,
        js_script,
        "/static/nested_menu_reorg.js",
        "</body>"
    )

    INDEX.write_text(html, encoding="utf-8")

    print("OK: 已生成一级/二级菜单重组脚本")
    print(f"OK: 已备份 index.html -> {backup}")
    print("OK: 已注入 nested_menu_reorg.css / nested_menu_reorg.js")

if __name__ == "__main__":
    main()

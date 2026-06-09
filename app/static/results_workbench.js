(function(){
  "use strict";

  function $(id){ return document.getElementById(id); }
  function cell(v){ return v === null || v === undefined || v === "" ? "-" : v; }
  function num(v, digits){ return v === null || v === undefined || v === "" ? "-" : Number(v).toFixed(digits); }
  function fmtTime(v){
    if(!v) return "-";
    const s = String(v);
    return s.includes("T") ? s.replace("T", " ") : s;
  }
  async function getJson(url){
    const r = await fetch(url);
    const d = await r.json();
    if(!r.ok || d.success === false) throw new Error(d.message || d.detail || r.statusText);
    return d.data || d;
  }

  const state = { mode: "watch" };

  function ensureResultWorkbench(){
    const main = document.querySelector("main.main");
    if(!main || $("view-result-workbench")) return;

    const section = document.createElement("section");
    section.id = "view-result-workbench";
    section.className = "view";
    section.innerHTML = `
      <div class="panel result-workbench">
        <div class="panel-head split">
          <div>
            <h3>结果工作台</h3>
            <p class="muted" style="margin:4px 0 0">报告生成后从这里追溯细节；日常默认看今日可看，需要时再切历史信号或标注明细。</p>
          </div>
          <div class="filters result-tabs">
            <button type="button" class="result-tab active" data-result-mode="watch">今日可看</button>
            <button type="button" class="result-tab" data-result-mode="latest">全部最新</button>
            <button type="button" class="result-tab" data-result-mode="signals">历史信号</button>
            <button type="button" class="result-tab" data-result-mode="annotations">标注明细</button>
          </div>
        </div>

        <div class="filters result-filters">
          <select id="rwMarket">
            <option value="all">全部四类</option>
            <option value="sh60">sh60</option>
            <option value="sh68">sh68</option>
            <option value="sz00">sz00</option>
            <option value="sz30">sz30</option>
          </select>
          <select id="rwAction">
            <option value="">全部建议</option>
            <option value="强势票｜重点关注">强势票｜重点关注</option>
            <option value="有核心亮点｜可关注">有核心亮点｜可关注</option>
            <option value="中强票｜观察池">中强票｜观察池</option>
            <option value="健康趋势｜可观察">健康趋势｜可观察</option>
            <option value="风险较多｜建议移出">风险较多｜建议移出</option>
            <option value="风险偏多｜谨慎观察">风险偏多｜谨慎观察</option>
            <option value="有风险｜人工确认">有风险｜人工确认</option>
          </select>
          <select id="rwLevel">
            <option value="">全部等级</option>
            <option value="A">A级</option>
            <option value="B">B级</option>
            <option value="C">C级</option>
            <option value="D">D级</option>
          </select>
          <select id="rwSelection">
            <option value="">全部入选状态</option>
            <option value="focus">focus</option>
            <option value="watch">watch</option>
            <option value="hold">hold</option>
            <option value="reject">reject</option>
          </select>
          <input id="rwQ" placeholder="代码/名称" />
          <input id="rwLimit" type="number" min="1" max="5000" value="500" />
          <button id="rwLoadBtn" class="primary" type="button">加载</button>
        </div>

        <div id="rwSummary" class="cards result-summary"></div>
        <div id="rwHint" class="muted result-hint"></div>
        <div class="table-wrap result-table-wrap"><table id="rwTable"></table></div>
      </div>
    `;

    const drawer = $("detailDrawer");
    if(drawer && drawer.parentNode) main.insertBefore(section, drawer);
    else main.appendChild(section);

    section.querySelectorAll("[data-result-mode]").forEach(btn => {
      btn.addEventListener("click", () => {
        state.mode = btn.dataset.resultMode || "watch";
        section.querySelectorAll(".result-tab").forEach(x => x.classList.remove("active"));
        btn.classList.add("active");
        loadResultWorkbench();
      });
    });
    $("rwLoadBtn").onclick = loadResultWorkbench;
  }

  function queryBase(){
    const market = $("rwMarket") ? $("rwMarket").value : "all";
    const q = $("rwQ") ? $("rwQ").value.trim() : "";
    const limit = $("rwLimit") ? $("rwLimit").value : "500";
    return { market, q, limit };
  }

  function renderSummary(items, extra){
    const total = items.length;
    const focus = items.filter(x => String(x.selection_status || x.manual_action_label || "").includes("focus") || String(x.manual_action_label || "").includes("重点")).length;
    const watch = items.filter(x => String(x.selection_status || x.manual_action_label || "").includes("watch") || String(x.manual_action_label || "").includes("观察")).length;
    const risk = items.filter(x => String(x.risk_tags || x.manual_action_label || "").includes("风险") || Number(x.d_count || 0) > 0).length;
    const summary = [
      ["当前结果", total],
      ["重点", focus],
      ["观察", watch],
      ["风险", risk],
    ];
    if(extra) summary.push(extra);
    $("rwSummary").innerHTML = summary.map(([k, v]) => `<div class="card"><div class="label">${k}</div><div class="value">${v}</div></div>`).join("");
  }

  function renderRows(columns, rows){
    const table = $("rwTable");
    if(!rows.length){
      table.innerHTML = "<tbody><tr><td>暂无数据</td></tr></tbody>";
      return;
    }
    table.innerHTML =
      "<thead><tr>" + columns.map(c => `<th>${c.label}</th>`).join("") + "</tr></thead><tbody>" +
      rows.map(r => "<tr>" + columns.map(c => `<td>${c.render ? c.render(r) : cell(r[c.key])}</td>`).join("") + "</tr>").join("") +
      "</tbody>";
  }

  async function loadWatch(){
    const { market, q, limit } = queryBase();
    let url = `/api/strategy/2568/annotations?market_type=${encodeURIComponent(market)}&limit=${encodeURIComponent(limit)}&risk_only=0&min_b=2`;
    const action = $("rwAction") ? $("rwAction").value : "";
    const level = $("rwLevel") ? $("rwLevel").value : "";
    if(action) url += `&manual_action=${encodeURIComponent(action)}`;
    if(level === "A") url += "&min_a=1";
    if(level === "D") url += "&min_d=1";
    if(q) url += `&q=${encodeURIComponent(q)}`;
    const data = await getJson(url);
    const rows = data.items || [];
    renderSummary(rows);
    $("rwHint").textContent = "今日可看：从 2568 标注中筛出 B≥2 或更强的日常观察清单。";
    renderRows([
      { label: "代码", key: "code" },
      { label: "名称", key: "name" },
      { label: "建议", render: r => `<b>${cell(r.manual_action_label)}</b>` },
      { label: "等级", key: "highlight_level" },
      { label: "A/B/D", render: r => `${cell(r.a_count)}/${cell(r.b_count)}/${cell(r.d_count)}` },
      { label: "亮点总结", render: r => `<span class="muted result-wide">${cell(r.highlight_summary)}</span>` },
      { label: "风险", render: r => `<span style="color:#F87171">${cell(r.risk_tags)}</span>` },
      { label: "2560状态", key: "latest_2560_status" },
      { label: "MA25", key: "ma25_status" },
      { label: "趋势", key: "trend_status" },
      { label: "回踩", key: "pullback_status" },
    ], rows);
  }

  async function loadLatest(){
    const { market, q, limit } = queryBase();
    let url = `/api/latest/by-stock?market_type=${encodeURIComponent(market)}&limit=${encodeURIComponent(limit)}`;
    if(q) url += `&q=${encodeURIComponent(q)}`;
    const rows = await getJson(url);
    const selection = $("rwSelection") ? $("rwSelection").value : "";
    const filtered = selection ? rows.filter(r => String(r.selection_status || "") === selection) : rows;
    renderSummary(filtered);
    $("rwHint").textContent = "全部最新：每只股票在最新成功批次中的标准化评估结果。";
    renderRows([
      { label: "代码", key: "code" },
      { label: "名称", key: "name" },
      { label: "命中", key: "latest_status" },
      { label: "入选状态", key: "selection_status" },
      { label: "最终分", render: r => num(r.final_score, 3) },
      { label: "近3日%", render: r => num(r.recent_3d_pct, 2) },
      { label: "起爆", key: "explode_status" },
      { label: "市场", key: "market_state" },
      { label: "题材强度", key: "hot_topic_strength" },
      { label: "题材地位", key: "position_in_hot_topic" },
      { label: "结构", key: "structure_status" },
      { label: "说明", render: r => `<span class="muted result-wide">${cell(r.explain_text)}</span>` },
    ], filtered);
  }

  async function loadSignals(){
    const { q } = queryBase();
    const p = new URLSearchParams();
    p.set("page", "1");
    p.set("page_size", $("rwLimit") ? $("rwLimit").value : "500");
    if(q) p.set("code", q);
    const data = await getJson(`/api/strategy/2560/signals?${p.toString()}`);
    const rows = data.items || [];
    renderSummary(rows, ["页内", `${data.page || 1}/${Math.ceil((data.total || rows.length) / (data.page_size || rows.length || 1))}`]);
    $("rwHint").textContent = "历史信号：2560 历史事件视角，用来追溯某只股票为什么命中。";
    renderRows([
      { label: "代码", key: "code" },
      { label: "名称", key: "name" },
      { label: "时间", render: r => fmtTime(r.signal_time) },
      { label: "周期", key: "signal_period" },
      { label: "结构", key: "structure_status" },
      { label: "入选", key: "selection_status" },
      { label: "最终分", render: r => num(r.final_score, 3) },
      { label: "缺失标签", key: "missing_tags" },
      { label: "说明", render: r => `<span class="muted result-wide">${cell(r.explain_text)}</span>` },
    ], rows);
  }

  async function loadAnnotations(){
    const { market, q, limit } = queryBase();
    let url = `/api/strategy/2568/annotations?market_type=${encodeURIComponent(market)}&limit=${encodeURIComponent(limit)}&risk_only=0`;
    const action = $("rwAction") ? $("rwAction").value : "";
    const level = $("rwLevel") ? $("rwLevel").value : "";
    if(action) url += `&manual_action=${encodeURIComponent(action)}`;
    if(level === "A") url += "&min_a=1";
    if(level === "B") url += "&min_b=2";
    if(level === "D") url += "&min_d=1";
    if(q) url += `&q=${encodeURIComponent(q)}`;
    const data = await getJson(url);
    const rows = data.items || [];
    renderSummary(rows);
    $("rwHint").textContent = "标注明细：2568 A/B/D 亮点和风险解释，用于人工复核。";
    renderRows([
      { label: "代码", key: "code" },
      { label: "名称", key: "name" },
      { label: "建议", render: r => `<b>${cell(r.manual_action_label)}</b>` },
      { label: "等级", key: "highlight_level" },
      { label: "A", key: "a_count" },
      { label: "B", key: "b_count" },
      { label: "D", key: "d_count" },
      { label: "A亮点", render: r => `<span class="muted result-wide">${cell(r.a_highlights)}</span>` },
      { label: "B亮点", render: r => `<span class="muted result-wide">${cell(r.b_highlights)}</span>` },
      { label: "D风险", render: r => `<span style="color:#F87171" class="result-wide">${cell(r.d_risks || r.risk_tags)}</span>` },
      { label: "2560", key: "latest_2560_status" },
    ], rows);
  }

  async function loadResultWorkbench(){
    ensureResultWorkbench();
    try {
      if(state.mode === "latest") await loadLatest();
      else if(state.mode === "signals") await loadSignals();
      else if(state.mode === "annotations") await loadAnnotations();
      else await loadWatch();
    } catch(e) {
      $("rwHint").textContent = `加载失败：${e.message}`;
      $("rwTable").innerHTML = "<tbody><tr><td>加载失败</td></tr></tbody>";
    }
  }

  window.loadResultWorkbench = loadResultWorkbench;
  document.addEventListener("DOMContentLoaded", ensureResultWorkbench);
})();

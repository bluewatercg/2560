const state = {
  page: 1,
  pageSize: 50,
  view: "overview",
  selected: new Set(),
  marketType: "all",
  currentStocks: [],
};
const $ = (id) => document.getElementById(id);
async function api(url, opts) {
  const r = await fetch(url, opts);
  const d = await r.json();
  if (!r.ok || d.success === false) throw new Error(d.message || r.statusText);
  return d.data ?? d;
}
function fmt(v) {
  return v === null || v === undefined ? "-" : v;
}
function num(v) {
  return v === null || v === undefined ? "-" : Number(v).toFixed(3);
}
function pct(v) {
  return v === null || v === undefined ? "-" : `${Number(v).toFixed(2)}%`;
}
function bool(v) {
  return v === true ? "是" : v === false ? "否" : "-";
}
function badgeStatus(s) {
  const cls =
    s === "结构完整"
      ? "ok"
      : s === "部分满足"
        ? "mid"
        : s === "明显缺失"
          ? "bad"
          : "gray";
  return `<span class="badge ${cls}">${fmt(s)}</span>`;
}
function renderTable(el, cols, rows, onClick, rowClass) {
  if (!rows || !rows.length) {
    el.innerHTML = "<tbody><tr><td>暂无数据</td></tr></tbody>";
    return;
  }
  el.innerHTML =
    `<thead><tr>${cols.map((c) => `<th>${c.label}</th>`).join("")}</tr></thead><tbody>` +
    rows
      .map(
        (r) =>
          `<tr class="${rowClass ? rowClass(r) : ""}" data-id="${r.id || r.code || ""}">${cols.map((c) => `<td>${c.render ? c.render(r) : fmt(r[c.key])}</td>`).join("")}</tr>`,
      )
      .join("") +
    "</tbody>";
  if (onClick)
    el.querySelectorAll("tbody tr").forEach((tr) =>
      tr.addEventListener("click", () => onClick(tr.dataset.id, tr)),
    );
}
function syncSelectedBox() {
  if ($("selectedCodes"))
    $("selectedCodes").value = [...state.selected].join(",");
}
function updateSelectedHint() {
  if ($("selectedCountHint"))
    $("selectedCountHint").textContent = `已选 ${state.selected.size}`;
}
async function loadHealth() {
  try {
    const h = await api("/health");
    $("systemBanner").className = "banner";
    $("systemBanner").textContent =
      `系统状态：${h.status || "ok"} / 数据库：${h.database ? "已连接" : "未连接"}`;
  } catch (e) {
    $("systemBanner").className = "banner warn";
    $("systemBanner").textContent = `系统状态异常：${e.message}`;
  }
}
async function loadOverview() {
  const d = await api("/api/strategy/2560/overview");
  const s = d.summary || {};
  const total = Number(s.total_signals || 0),
    complete = Number(s.complete_count || 0);
  const rate = total ? ((complete / total) * 100).toFixed(1) + "%" : "-";
  $("overviewCards").innerHTML = [
    ["总信号数", total],
    ["结构完整", complete],
    ["部分满足", s.partial_count || 0],
    ["明显缺失", s.missing_count || 0],
    ["完整率", rate],
  ]
    .map(
      ([l, v]) =>
        `<div class="card"><div class="label">${l}</div><div class="value">${v}</div></div>`,
    )
    .join("");
  $("latestBatch").textContent = JSON.stringify(d.latest_batch || {}, null, 2);
  const tags = d.tag_distribution || [],
    max = Math.max(...tags.map((t) => Number(t.count || 0)), 1);
  $("tagChart").innerHTML = tags.length
    ? tags
        .map(
          (t) =>
            `<div class="bar-row"><div>${t.tag_name}</div><div class="bar-bg"><div class="bar-fill" style="width:${(Number(t.count || 0) / max) * 100}%"></div></div><div>${t.count}</div></div>`,
        )
        .join("")
    : "暂无标签数据";
}
async function loadStocks() {
  const q = $("stockSearch").value.trim();
  const mt = $("marketTypeFilter").value;
  state.marketType = mt;
  const d = await api(
    "/api/strategy/2560/stocks?limit=200&market_type=" +
      encodeURIComponent(mt) +
      (q ? "&q=" + encodeURIComponent(q) : ""),
  );
  state.currentStocks = d || [];
  updateSelectedHint();
  renderTable(
    $("stockTable"),
    [
      { label: "选择", render: (r) => (state.selected.has(r.code) ? "✓" : "") },
      { label: "类型", render: (r) => r.board_type || r.market_type || "-" },
      { label: "市场代码", render: (r) => r.market_code || r.code },
      { label: "代码", key: "code" },
      { label: "名称", key: "name" },
      { label: "行业", key: "industry_name" },
    ],
    d || [],
    (code) => {
      if (state.selected.has(code)) state.selected.delete(code);
      else state.selected.add(code);
      syncSelectedBox();
      updateSelectedHint();
      loadStocks();
    },
    (r) => (state.selected.has(r.code) ? "stock-row selected" : "stock-row"),
  );
}
function selectCurrentStocks() {
  (state.currentStocks || []).forEach((r) => {
    if (r.code) state.selected.add(r.code);
  });
  syncSelectedBox();
  updateSelectedHint();
  loadStocks();
}
async function selectByFilterLimit() {
  const mt = $("marketTypeFilter").value;
  const q = $("stockSearch").value.trim();
  const d = await api(
    "/api/strategy/2560/stocks?limit=200&market_type=" +
      encodeURIComponent(mt) +
      (q ? "&q=" + encodeURIComponent(q) : ""),
  );
  (d || []).forEach((r) => {
    if (r.code) state.selected.add(r.code);
  });
  syncSelectedBox();
  updateSelectedHint();
  loadStocks();
}
async function runSelected() {
  const manual = $("selectedCodes")
    .value.split(/[，,\s]+/)
    .map((x) => x.trim())
    .filter(Boolean);
  manual.forEach((c) => state.selected.add(c));
  syncSelectedBox();
  const codes = [...state.selected];
  const limitVal = $("runLimit").value.trim();
  const mt = $("marketTypeFilter").value;
  const payload = {
    codes,
    source: $("runSource").value.trim() || null,
    limit: codes.length ? null : limitVal ? Number(limitVal) : null,
    rebuild_statistics: $("rebuildStats").checked,
    market_type: mt,
  };
  $("runResult").textContent = "正在计算并入库，请稍候...";
  try {
    const d = await api("/api/strategy/2560/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("runResult").textContent = JSON.stringify(d, null, 2);
    await loadOverview();
    await loadBatches();
  } catch (e) {
    $("runResult").textContent = "运行失败：" + e.message;
  }
}
async function runProbe(mt) {
  const limitText = $("probeLimit").value.trim();
  const limit = limitText ? Number(limitText) : null;
  const label = mt === "sh" ? "sh 全部" : mt === "sz" ? "sz 全部" : "全部四类";
  if (
    !confirm(
      `确认开始摸底计算：${label}${limit ? `，limit=${limit}` : "，全量"}？`,
    )
  )
    return;
  $("runResult").textContent = `正在摸底计算 ${label}...`;
  const payload = {
    codes: [],
    source: $("runSource").value.trim() || null,
    limit,
    rebuild_statistics: $("rebuildStats").checked,
    market_type: mt,
  };
  try {
    const d = await api("/api/strategy/2560/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("runResult").textContent = JSON.stringify(d, null, 2);
    await loadOverview();
    await loadBatches();
  } catch (e) {
    $("runResult").textContent = "摸底计算失败：" + e.message;
  }
}
function color(i) {
  return [
    "#2563eb",
    "#dc2626",
    "#d97706",
    "#16a34a",
    "#7c3aed",
    "#0891b2",
    "#be123c",
    "#4b5563",
  ][i % 8];
}
async function loadDiagnostics() {
  const mt = $("diagMarket").value,
    limit = $("diagLimit").value || 500,
    q = $("diagQ").value.trim(),
    near = $("diagNearOnly").checked ? 1 : 0;
  $("diagTable").innerHTML = "正在加载...";
  try {
    const d = await api(
      "/api/strategy/2560/probe-indicators?market_type=" +
        encodeURIComponent(mt) +
        "&limit=" +
        encodeURIComponent(limit) +
        "&near_only=" +
        near +
        (q ? "&q=" + encodeURIComponent(q) : ""),
    );
    renderDiagSummary(d.summary || {});
    renderDiagCharts(d.reason_stats || []);
    renderDiagTable(d.items || []);
  } catch (e) {
    $("diagTable").innerHTML = "加载失败：" + e.message;
  }
}
function renderDiagSummary(s) {
  $("diagSummaryCards").innerHTML = [
    ["加载数量", s.total || 0],
    ["原始数量", s.raw_total || 0],
    ["缺30m", s.missing_30m || 0],
    ["缺日线", s.missing_daily || 0],
    ["接近满足", s.near_count || 0],
  ]
    .map(
      ([l, v]) =>
        `<div class="card"><div class="label">${l}</div><div class="value">${v}</div></div>`,
    )
    .join("");
}
function renderDiagCharts(stats) {
  const max = Math.max(...stats.map((x) => x.count || 0), 1);
  $("diagBar").innerHTML =
    stats
      .slice(0, 12)
      .map(
        (x, i) =>
          `<div class="diag-bar-row"><span>${x.reason}</span><div class="diag-bar-bg"><div style="width:${((x.count / max) * 100).toFixed(1)}%;background:${color(i)}"></div></div><b>${x.count}</b></div>`,
      )
      .join("") || "暂无";
  const total = stats.reduce((a, b) => a + (b.count || 0), 0);
  let acc = 0,
    gs = [];
  stats.slice(0, 8).forEach((x, i) => {
    const start = (acc / total) * 360;
    acc += x.count || 0;
    const end = (acc / total) * 360;
    gs.push(`${color(i)} ${start}deg ${end}deg`);
  });
  $("diagPie").style.background = total
    ? `conic-gradient(${gs.join(",")})`
    : "#e5e7eb";
  $("diagLegend").innerHTML = stats
    .slice(0, 8)
    .map(
      (x, i) =>
        `<div><i style="background:${color(i)}"></i>${x.reason} (${x.count})</div>`,
    )
    .join("");
}
function renderDiagTable(items) {
  if (!items.length) {
    $("diagTable").innerHTML = '<div class="diag-empty">暂无数据</div>';
    return;
  }
  const cols = [
    "代码",
    "名称",
    "类型",
    "日线",
    "30m",
    "5m",
    "最新30m",
    "收盘",
    "MA25",
    "斜率",
    "偏离%",
    "量比",
    "贴MA25",
    "斜率OK",
    "量能OK",
    "状态",
    "未命中原因",
  ];
  $("diagTable").innerHTML =
    '<div class="table-wrap"><table><thead><tr>' +
    cols.map((x) => `<th>${x}</th>`).join("") +
    "</tr></thead><tbody>" +
    items
      .map(
        (r) =>
          `<tr class="${r.near_match ? "diag-near" : ""}"><td>${r.code || "-"}</td><td>${r.name || "-"}</td><td>${r.board_type || "-"}</td><td>${r.daily_count}</td><td>${r.k30_count}</td><td>${r.k5_count}</td><td>${r.latest_30m_time || "-"}</td><td>${num(r.close_30m)}</td><td>${num(r.ma25_30m)}</td><td>${num(r.ma25_slope_3)}</td><td>${num(r.price_ma25_deviation_pct)}</td><td>${num(r.vol_ratio)}</td><td>${bool(r.price_near_ma25)}</td><td>${bool(r.ma25_slope_ok)}</td><td>${bool(r.volume_structure_ok)}</td><td>${r.status}</td><td>${r.reasons}</td></tr>`,
      )
      .join("") +
    "</tbody></table></div>";
}
async function loadSignals() {
  const p = new URLSearchParams({
    page: state.page,
    page_size: state.pageSize,
  });
  if ($("filterCode").value) p.set("code", $("filterCode").value.trim());
  if ($("filterStatus").value)
    p.set("structure_status", $("filterStatus").value);
  if ($("filterTag").value) p.set("tag", $("filterTag").value.trim());
  const d = await api("/api/strategy/2560/signals?" + p.toString());
  $("pageInfo").textContent = `第 ${d.page} 页 / 共 ${d.total} 条`;
  renderTable(
    $("signalsTable"),
    [
      { label: "时间", key: "signal_time" },
      { label: "代码", key: "code" },
      { label: "名称", key: "name" },
      { label: "价格", key: "price" },
      { label: "行业", key: "industry_name" },
      { label: "结构状态", render: (r) => badgeStatus(r.structure_status) },
      { label: "标签", key: "missing_tags" },
      { label: "数据质量", key: "data_quality_status" },
      { label: "说明", key: "explain_text" },
    ],
    d.items || [],
    (id) => id && showDetail(id),
  );
}
async function showDetail(id) {
  const d = await api("/api/strategy/2560/signals/" + id);
  $("detailContent").textContent = JSON.stringify(d, null, 2);
  $("detailDrawer").classList.remove("hidden");
}
async function loadComplete() {
  const d = await api("/api/strategy/2560/complete-cases?limit=20");
  renderTable(
    $("completeTable"),
    [
      { label: "时间", key: "signal_time" },
      { label: "代码", key: "code" },
      { label: "名称", key: "name" },
      { label: "价格", key: "price" },
      { label: "1日", render: (r) => pct(r.future_return_1d) },
      { label: "3日", render: (r) => pct(r.future_return_3d) },
      { label: "5日", render: (r) => pct(r.future_return_5d) },
    ],
    d || [],
  );
}
async function loadStatistics() {
  const type = $("statType").value;
  const d = await api(
    type
      ? "/api/strategy/2560/statistics?stat_type=" + encodeURIComponent(type)
      : "/api/strategy/2560/statistics",
  );
  renderTable(
    $("statsTable"),
    [
      { label: "批次", key: "batch_id" },
      { label: "日期", key: "stat_date" },
      { label: "类型", key: "stat_type" },
      { label: "分组", key: "group_key" },
      { label: "样本", key: "sample_count" },
      { label: "5日均值", render: (r) => pct(r.avg_return_5d) },
    ],
    d || [],
  );
}
async function loadBatches() {
  const d = await api("/api/strategy/2560/batches");
  renderTable(
    $("batchesTable"),
    [
      { label: "批次ID", key: "batch_id" },
      { label: "策略", key: "strategy_code" },
      { label: "版本", key: "strategy_version" },
      { label: "运行时间", key: "run_time" },
      { label: "状态", key: "status" },
      { label: "说明", key: "message" },
    ],
    d || [],
  );
}
async function loadQuality() {
  const d = await api("/api/data-quality/summary");
  renderTable(
    $("qualityTable"),
    [
      { label: "日期", key: "check_date" },
      { label: "周期", key: "period" },
      { label: "数据源", key: "source" },
      { label: "应有标的", key: "total_symbols" },
      { label: "可用标的", key: "available_symbols" },
      { label: "缺失", key: "missing_symbols" },
      { label: "异常K线", key: "abnormal_bar_count" },
      { label: "状态", key: "status" },
    ],
    d || [],
  );
}

async function loadLatest() {
  const mt = $("latestMarket") ? $("latestMarket").value : "all";
  const q = $("latestQ") ? $("latestQ").value.trim() : "";
  const limit = $("latestLimit") ? $("latestLimit").value : 1000;
  const url =
    "/api/latest/by-stock?market_type=" +
    encodeURIComponent(mt) +
    "&limit=" +
    encodeURIComponent(limit) +
    (q ? "&q=" + encodeURIComponent(q) : "");
  const rows = await api(url);
  renderTable(
    $("latestTable"),
    [
      { label: "代码", key: "code" },
      { label: "名称", key: "name" },
      { label: "状态", key: "latest_status" },
      { label: "批次", key: "batch_id" },
      { label: "信号时间", key: "signal_time" },
      { label: "结构状态", key: "structure_status" },
      { label: "缺失标签", key: "missing_tags" },
      { label: "说明", key: "explain_text" },
    ],
    rows || [],
  );
}

async function loadJobs() {
  const queue = await api("/api/jobs/queue");
  renderTable(
    $("jobQueueTable"),
    [
      { label: "ID", key: "id" },
      { label: "任务类型", key: "job_type" },
      { label: "策略", key: "strategy_code" },
      { label: "优先级", key: "priority" },
      { label: "状态", key: "status" },
      { label: "创建时间", key: "created_at" },
      { label: "开始时间", key: "started_at" },
      { label: "结束时间", key: "finished_at" },
    ],
    queue || [],
  );
  const execs = await api("/api/jobs/executions");
  renderTable(
    $("jobExecTable"),
    [
      { label: "ID", key: "id" },
      { label: "类型", key: "job_type" },
      { label: "批次", key: "batch_id" },
      { label: "状态", key: "status" },
      {
        label: "进度",
        render: (r) => `${r.progress_current || 0}/${r.progress_total || 0}`,
      },
      { label: "信息", key: "message" },
      { label: "开始时间", key: "started_at" },
      { label: "结束时间", key: "finished_at" },
    ],
    execs || [],
    async (id) => {
      if (!id) return;
      const items = await api("/api/jobs/executions/" + id + "/items");
      renderTable(
        $("jobItemTable"),
        [
          { label: "ID", key: "id" },
          { label: "Job", key: "job_id" },
          { label: "Shard", key: "shard_id" },
          { label: "代码", key: "code" },
          { label: "状态", key: "status" },
          { label: "重试", key: "retry_count" },
          { label: "错误", key: "last_error" },
          { label: "更新时间", key: "updated_at" },
        ],
        items || [],
      );
    },
  );
}

async function refresh() {
  await loadHealth();
  if (state.view === "overview") await loadOverview();
  if (state.view === "run") await loadStocks();
  if (state.view === "diagnostics") await loadDiagnostics();
  if (state.view === "signals") await loadSignals();
  if (state.view === "latest") await loadLatest();
  if (state.view === "jobs") await loadJobs();
  if (state.view === "complete") await loadComplete();
  if (state.view === "statistics") await loadStatistics();
  if (state.view === "batches") await loadBatches();
  if (state.view === "quality") await loadQuality();
}
const titles = {
  overview: ["总览", "查看最新批次、结构完整率、标签分布与系统状态"],
  workflow: ["工作流指导", "说明系统每天怎么用、各页面分别负责什么"],
  run: ["入库计算", "支持选择股票、全选、sh/sz 全部摸底计算"],
  diagnostics: [
    "摸底指标",
    "查看2560各项指标、未命中原因统计，以及接近满足条件的股票",
  ],
  signals: ["信号列表", "逐条查看2560结构条件、标签与解释"],
  latest: ["最新分析结果", "每只股票在最近一次分析中的最终状态"],
  jobs: ["任务队列", "后台调度与执行情况"],
  complete: ["完整结构", "查看最近结构完整案例及后续表现"],
  statistics: ["结构统计", "按结构状态、标签、行业、板块、概念统计"],
  batches: ["批次管理", "查看分析批次、版本、运行状态"],
  quality: ["数据质量", "查看日线/分钟线完整性与异常情况"],
};
document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", async () => {
    document
      .querySelectorAll(".nav-item")
      .forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    document
      .querySelectorAll(".view")
      .forEach((v) => v.classList.remove("active"));
    state.view = b.dataset.view;
    state.page = 1;
    $("view-" + state.view).classList.add("active");
    $("pageTitle").textContent = titles[state.view][0];
    $("pageSubtitle").textContent = titles[state.view][1];
    await refresh();
  }),
);
$("refreshBtn").onclick = refresh;
$("searchStockBtn").onclick = loadStocks;
$("selectCurrentBtn").onclick = selectCurrentStocks;
$("selectByFilterBtn").onclick = selectByFilterLimit;
$("runSelectedBtn").onclick = runSelected;
$("clearSelectedBtn").onclick = () => {
  state.selected.clear();
  syncSelectedBox();
  updateSelectedHint();
  loadStocks();
  $("runResult").textContent = "等待执行...";
};
$("probeShBtn").onclick = () => runProbe("sh");
$("probeSzBtn").onclick = () => runProbe("sz");
$("probeAllBtn").onclick = () => runProbe("all");
$("diagLoadBtn").onclick = loadDiagnostics;
$("applySignalFilter").onclick = () => {
  state.page = 1;
  loadSignals();
};
$("prevPage").onclick = () => {
  if (state.page > 1) {
    state.page--;
    loadSignals();
  }
};
$("nextPage").onclick = () => {
  state.page++;
  loadSignals();
};
$("statType").onchange = loadStatistics;
$("closeDrawer").onclick = () => $("detailDrawer").classList.add("hidden");
if ($("latestLoadBtn")) $("latestLoadBtn").onclick = loadLatest;
if ($("jobsLoadBtn")) $("jobsLoadBtn").onclick = loadJobs;
refresh();

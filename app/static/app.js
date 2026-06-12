const state = {
  page: 1,
  pageSize: 50,
  view: "workspace",
  selected: new Set(),
  marketType: "all",
  currentStocks: [],
  selectedJobExecutionId: null,
  selectedJobQueueId: null,
  selectedJobAutoRefresh: null,
  workspaceMarketReadiness: {},
  workspaceTargetDate: null,
  workspaceReportPackageResult: null,
  workspaceMorningReportPackageResult: null,
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
function fmtTime(v) {
  if (v === null || v === undefined || v === "") return "-";
  let s = String(v);
  // Handle ISO datetime strings like "2026-05-18T15:00:00"
  if (s.includes("T")) return s.replace("T", " ");
  // Handle ISO date strings like "2026-05-18" (no slicing needed)
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
    return s.length >= 19 ? s : s.slice(0, 10) + (s.length > 10 ? " " + s.slice(11) : "");
  }
  // Handle integer format YYYYMMDDHHMMSS
  if (s.length >= 14) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)} ${s.slice(8, 10)}:${s.slice(10, 12)}:${s.slice(12, 14)}`;
  if (s.length >= 8) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
  return s;
}
function fmtTags(v) {
  if (!v) return "-";
  let tags = v;
  if (typeof v === "string") {
    try { tags = JSON.parse(v); } catch {
      try { tags = JSON.parse(v.replace(/'/g, '"')); } catch { return v; }
    }
  }
  if (Array.isArray(tags)) {
    if (!tags.length) return "-";
    return tags.map(t => {
      const neg = t.startsWith("#缺") || t.startsWith("#未") || t.startsWith("#不") || t.startsWith("#无") || t.startsWith("#高位") || t.startsWith("#低位");
      const cls = neg ? "tag-neg" : "tag-pos";
      return `<span class="mini-tag ${cls}">${t}</span>`;
    }).join(" ");
  }
  return String(v);
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
function parseJobPayload(row) {
  const payload = row && row.payload;
  if (!payload) return {};
  if (typeof payload === "object") return payload;
  try {
    return JSON.parse(payload);
  } catch (e) {
    return {};
  }
}
function jobQueueMarket(row) {
  const data = parseJobPayload(row);
  const market = data && data.market ? data.market : row && row.market;
  return fmt(market);
}
function jobQueueExecutionId(row) {
  const data = parseJobPayload(row);
  return fmt(data && data.job_execution_id);
}
function jobQueueShards(row) {
  const data = parseJobPayload(row);
  return fmt(data && data.shards);
}
function executionSourceLabel(row, queueId) {
  if (row && row.job_type === "run_2560_now") return "立即执行，无队列记录";
  return queueId ? `来自队列 #${queueId}` : "队列执行";
}
function isActiveJobStatus(status) {
  return ["running", "queued", "pending", "cancelling"].includes(
    String(status || "").toLowerCase(),
  );
}
function stopJobAutoRefresh() {
  if (state.selectedJobAutoRefresh) {
    clearInterval(state.selectedJobAutoRefresh);
    state.selectedJobAutoRefresh = null;
  }
}
function startJobAutoRefresh() {
  if (state.selectedJobAutoRefresh || !state.selectedJobExecutionId) return;
  state.selectedJobAutoRefresh = setInterval(refreshSelectedJob, 5000);
}
async function refreshSelectedJob() {
  if (state.view !== "jobs" || !state.selectedJobExecutionId) {
    stopJobAutoRefresh();
    return;
  }
  const execs = await api(
    "/api/jobs/executions?job_type=run_2560&job_type=run_2560_now",
  );
  const row = (execs || []).find(
    (r) => String(r.id) === String(state.selectedJobExecutionId),
  );
  if (!row) {
    stopJobAutoRefresh();
    return;
  }
  renderJobExecutions(execs || [], state.selectedJobExecutionId, state.selectedJobQueueId);
  await loadJobDetails(state.selectedJobExecutionId);
  if (!isActiveJobStatus(row.status)) stopJobAutoRefresh();
}
function renderShardProgress(row) {
  const done = Number(row && row.done ? row.done : 0);
  const total = Number(row && row.total ? row.total : 0);
  const running = Number(row && row.running_count ? row.running_count : 0);
  const pending = Number(row && row.pending_count ? row.pending_count : 0);
  const percent = total ? Math.min(100, Math.max(0, (done * 100) / total)) : 0;
  return `<div style="min-width:220px"><div style="height:8px;background:#334155;border-radius:999px;overflow:hidden"><div style="height:100%;width:${percent.toFixed(1)}%;background:#3B82F6"></div></div><div style="margin-top:4px;font-size:12px;color:#F8FAFC">已完成 ${done} / 该组总数 ${total}</div><div style="margin-top:2px;font-size:12px;color:#94A3B8">运行中 ${running}，待执行 ${pending}</div></div>`;
}
function ensureJobShardPanel() {
  if ($("jobShardTable")) return;
  const itemTable = $("jobItemTable");
  if (!itemTable) return;
  const itemPanel = itemTable.closest(".panel");
  if (!itemPanel || !itemPanel.parentNode) return;
  itemPanel.style.display = "none";
  const panel = document.createElement("div");
  panel.className = "panel";
  panel.innerHTML =
    '<h3>Shard 汇总（每行是一组并发线程）</h3><div class="table-wrap"><table id="jobShardTable"></table></div>';
  itemPanel.parentNode.insertBefore(panel, itemPanel);
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

async function loadWorkspace() {
  try {
    const d = await api("/api/strategy/2560/workspace");
    renderWorkspace(d);
  } catch (e) {
    $("workspaceContent").innerHTML = `<div class="panel"><p class="muted">工作台加载失败：${e.message}</p></div>`;
  }
}

function renderWorkspace(data) {
  // 缓存 readiness 原始数据，供操作按钮取日期
  state.workspaceMarketReadiness = Object.fromEntries(
    (data.market_readiness || []).map((m) => [m.market, m])
  );
  state.workspaceTargetDate = data.target_date || null;

  // 目标交易日
  $("workspaceDate").textContent = `目标交易日：${data.target_date || "-"}`;
  if ($("reportPackageTradeDate")) {
    $("reportPackageTradeDate").value = data.target_date || todayYmd();
  }
  if ($("morningReportTradeDate")) {
    $("morningReportTradeDate").value = data.target_date || todayYmd();
  }
  renderWorkspaceReportPackageResult();
  renderWorkspaceMorningReportPackageResult();
  window.restoreWorkspaceReportPackages();

  // 四市场卡片
  const mr = data.market_readiness || [];
  $("workspaceMarketCards").innerHTML = mr
    .map(
      (m) => `
    <div class="card" style="${m.ready ? "border-left:3px solid var(--green)" : "border-left:3px solid #F59E0B"}">
      <div class="label">${m.market}</div>
      <div class="value" style="font-size:14px">${m.status}</div>
      ${m.missing.length ? `<div class="muted" style="font-size:12px;margin-top:4px">缺：${m.missing.join("、")}</div>` : ""}
      ${m.daily_latest ? `<div class="muted" style="font-size:11px">日线至 ${m.daily_latest}</div>` : ""}
      ${m.k5m_latest ? `<div class="muted" style="font-size:11px">5m至 ${m.k5m_latest}</div>` : ""}
      ${m.k30m_latest ? `<div class="muted" style="font-size:11px">30m至 ${m.k30m_latest}</div>` : ""}
      ${m.missing.includes('30m') || m.missing.includes('5m') ? `<div style="margin-top:8px"><button class="action-btn sm" data-market-action="${m.market}" onclick="window.build30m('${m.market}')">构建30m</button></div>` : ""}
      ${!m.indicators_fresh ? `<div style="margin-top:8px"><button class="action-btn sm" data-market-action="${m.market}" onclick="window.rebuildIndicators('${m.market}')">重算指标</button></div>` : ""}
      ${m.ready ? `<div style="margin-top:8px"><button class="action-btn sm primary" data-market-action="${m.market}" onclick="window.run2560('${m.market}')">运行2560</button></div>` : ""}
    </div>`,
    )
    .join("");

  // 下一步建议
  const sg = data.suggestions || [];
  const sugEl = $("workspaceSuggestions");
  if (sg.length) {
    const viewLabels = {
      "data-update": "行情导入与日志",
      "data-import-batches": "数据构建与维护",
      "data-import": "行情导入与日志",
      "data-maintenance": "数据构建与维护",
      jobs: "任务进度",
    };
    const viewRedirects = {
      "data-update": "data-import",
      "data-import-batches": "data-maintenance",
    };
    sugEl.innerHTML = `
      <div class="panel">
        <h3>下一步建议</h3>
        <ol style="margin:8px 0 0 20px;line-height:2">
          ${sg
            .map(
              (s) =>
                `<li>${s.market} → ${s.action}（${s.reason}） <button class="ghost" onclick="navigateTo('${viewRedirects[s.view] || s.view}')" style="font-size:12px;padding:2px 8px">去${viewLabels[s.view] || s.view}</button></li>`,
            )
            .join("")}
        </ol>
      </div>`;
  } else {
    sugEl.innerHTML = "";
  }

  // 0 命中解释
  const zhe = $("workspaceZeroHit");
  const ze = data.zero_hit_explain;
  if (ze) {
    const severityColors = {
      ok: { border: "var(--green)", bg: "rgba(34,197,94,0.06)", text: "var(--green)" },
      warn: { border: "#F59E0B", bg: "rgba(245,158,11,0.08)", text: "#F59E0B" },
      error: { border: "#EF4444", bg: "rgba(239,68,68,0.08)", text: "#EF4444" },
      info: { border: "#60A5FA", bg: "rgba(96,165,250,0.08)", text: "#60A5FA" },
    };
    const c = severityColors[ze.severity] || severityColors.info;
    zhe.innerHTML = `
      <div class="panel" style="border-left:3px solid ${c.border};background:${c.bg}">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:16px">${ze.severity === "ok" ? "✓" : ze.severity === "warn" ? "⚠" : ze.severity === "error" ? "✗" : "ℹ"}</span>
          <b style="color:${c.text}">${ze.title}</b>
        </div>
        <p style="margin:8px 0 0;font-size:13px;line-height:1.6;color:var(--text)">${ze.detail}</p>
      </div>`;
  } else {
    zhe.innerHTML = "";
  }

  // 正在执行的任务
  const rj = data.running_jobs || [];
  const runEl = $("workspaceRunningJobs");
  if (rj.length) {
    runEl.innerHTML = `
      <div class="panel">
        <h3>正在执行的任务</h3>
        <div class="table-wrap"><table>
          <thead><tr><th>ID</th><th>任务类型</th><th>市场</th><th>状态</th><th>进度</th><th>成功/失败</th><th>信息</th></tr></thead>
          <tbody>
            ${rj
              .map(
                (j) => {
                  const typeLabel = j.job_type === 'run_2560_now' ? '即时重算' : '2560摸底';
                  return `<tr><td>${j.id}</td><td>${typeLabel}</td><td>${j.market || "-"}</td><td>${j.status}</td><td>${j.progress_percent}%</td><td>${j.success_count || 0} / ${j.failed_count || 0}</td><td class="muted">${j.message || "-"}</td></tr>`;
                },
              )
              .join("")}
          </tbody>
        </table></div>
      </div>`;
  } else {
    runEl.innerHTML = `<div class="panel"><h3>正在执行的任务</h3><p class="muted">暂无正在执行的任务</p></div>`;
  }

  // 今日观察池摘要
  const op = data.observation_pool || [];
  const obsEl = $("workspaceObservation");
  if (op.length) {
    obsEl.innerHTML = `
      <div class="panel">
        <div class="panel-head split">
          <h3>今日观察池（top ${op.length}）</h3>
          <button class="ghost" onclick="navigateTo('observation-pool')">查看全部 →</button>
        </div>
        <div class="table-wrap"><table>
          <thead><tr><th>代码</th><th>名称</th><th>等级</th><th>人工建议</th><th>亮点</th><th>2560状态</th></tr></thead>
          <tbody>
            ${op
              .map(
                (s) =>
                  `<tr><td>${s.code || "-"}</td><td>${s.name || "-"}</td><td>${s.highlight_level || "-"}</td><td><b>${s.manual_action_label || "-"}</b></td><td class="muted">${s.highlight_summary || "-"}</td><td>${s.latest_2560_status || "-"}</td></tr>`,
              )
              .join("")}
          </tbody>
        </table></div>
      </div>`;
  } else {
    obsEl.innerHTML = `<div class="panel"><h3>今日观察池</h3><p class="muted">暂无观察池数据，请先完成 2568 标注</p></div>`;
  }

  // 2560 漏斗诊断
  const funnelSection = $("workspaceFunnel");
  const fs = data.funnel_summary || {};
  const funnelKeys = Object.keys(fs);
  if (funnelKeys.length === 0) {
    funnelSection.innerHTML = `<div class="panel"><h3>2560 漏斗诊断</h3><p class="muted">暂无漏斗数据，请先运行 2560 或确保市场数据已就绪</p></div>`;
    return;
  }
  funnelSection.innerHTML = `
    <div class="panel">
      <h3>2560 漏斗诊断 — 基础通过为 0 时，定位卡点</h3>
      <p class="muted" style="margin-top:4px;font-size:12px">每次 2560 跑完后，按 market 输出过滤漏斗。0 命中不是失败，而是需要看卡在哪个阶段。</p>
      ${funnelKeys.map((mkt) => renderFunnelForMarket(mkt, fs[mkt])).join("")}
    </div>`;
}

function renderFunnelForMarket(mkt, funnel) {
  const stages = funnel.stages || [];
  const reasons = funnel.reason_stats || [];
  const total = funnel.total || 0;
  const baseOk = stages.length ? stages[stages.length - 1].count : 0;
  const tiers = funnel.tiers || {};

  // 判断是否零命中
  const zeroHit = baseOk === 0;

  // 找出最大卡点（drop 最大的阶段）
  let bottleneck = null;
  let maxDrop = 0;
  for (const s of stages) {
    if (s.drop > maxDrop) {
      maxDrop = s.drop;
      bottleneck = s;
    }
  }

  return `
    <div style="margin-top:16px;padding:12px;border:1px solid var(--line);border-radius:8px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <div>
          <b style="font-size:14px">${mkt}</b>
          <span class="muted" style="margin-left:8px;font-size:12px">共 ${total} 只</span>
          ${zeroHit ? `<span style="margin-left:8px;font-size:12px;color:#F59E0B">⚠ 基础通过为 0</span>` : `<span style="margin-left:8px;font-size:12px;color:var(--green)">✓ 基础通过 ${baseOk} 只</span>`}
        </div>
        ${bottleneck && maxDrop > 0 ? `<span class="muted" style="font-size:12px">最大卡点：${bottleneck.stage}（-${bottleneck.drop}）</span>` : ""}
      </div>
      ${renderTierBadges(tiers)}
      ${renderFunnelBars(stages)}
      ${zeroHit && reasons.length ? renderBottleneckReasons(reasons) : ""}
    </div>`;
}

function renderTierBadges(tiers) {
  const colors = {
    A: { bg: "rgba(34,197,94,0.15)", border: "rgba(34,197,94,0.3)", text: "#22C55E" },
    B: { bg: "rgba(34,211,238,0.12)", border: "rgba(34,211,238,0.25)", text: "#22D3EE" },
    C: { bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.25)", text: "#F59E0B" },
    D: { bg: "rgba(239,68,68,0.1)", border: "rgba(239,68,68,0.2)", text: "#94A3B8" },
  };
  return `
    <div style="display:flex;gap:8px;margin-bottom:10px">
      ${["A", "B", "C", "D"]
        .map(
          (t) => `
        <span style="padding:3px 10px;border-radius:4px;font-size:12px;background:${colors[t].bg};border:1px solid ${colors[t].border};color:${colors[t].text};font-weight:500">
          ${t} ${tiers[t]?.name || ""} ${tiers[t]?.count ?? "-"}
        </span>`,
        )
        .join("")}
    </div>`;
}

function renderFunnelBars(stages) {
  const maxCount = Math.max(...stages.map((s) => s.count), 1);
  return `
    <div style="display:flex;flex-direction:column;gap:3px;margin-top:8px">
      ${stages
        .map(
          (s) => `
        <div style="display:flex;align-items:center;gap:8px;font-size:12px">
          <span style="width:80px;text-align:right;flex-shrink:0;color:var(--muted)">${s.stage}</span>
          <div style="flex:1;height:18px;background:var(--surface);border-radius:3px;overflow:hidden;position:relative">
            <div style="width:${Math.max((s.count / maxCount) * 100, s.count > 0 ? 3 : 0)}%;height:100%;background:${getFunnelColor(s.pct)};border-radius:3px;transition:width 0.3s"></div>
            <span style="position:absolute;left:8px;top:0;line-height:18px;color:var(--text)">${s.count}</span>
          </div>
          <span style="width:44px;text-align:right;flex-shrink:0;color:var(--muted)">${s.pct}%</span>
          ${s.pass_rate > 0 && s.pass_rate < 100 ? `<span style="width:56px;text-align:left;flex-shrink:0;font-size:11px;color:#F59E0B">↓${s.pass_rate}%</span>` : s.pass_rate >= 100 ? `<span style="width:56px"></span>` : `<span style="width:56px"></span>`}
        </div>`,
        )
        .join("")}
    </div>`;
}

function renderBottleneckReasons(reasons) {
  const top = reasons.slice(0, 5);
  return `
    <div style="margin-top:8px;padding:8px 12px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.2);border-radius:6px;font-size:12px">
      <b style="color:#F59E0B">主要卡点：</b>
      ${top
        .map(
          (r) =>
            `<span style="margin-right:12px">${r.reason} <span class="muted">${r.count} 只</span></span>`,
        )
        .join("")}
    </div>`;
}

function getFunnelColor(pct) {
  if (pct >= 80) return "var(--green)";
  if (pct >= 50) return "#22D3EE";
  if (pct >= 20) return "#F59E0B";
  if (pct > 0) return "#EF4444";
  return "var(--surface)";
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
  const labels = {
    sh60: "sh60 沪主板60",
    sh68: "sh68 科创68",
    sz00: "sz00 深主板00",
    sz30: "sz30 创业板30",
    all: "全部四类",
  };
  const label = labels[mt] || "全部四类";
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
    "#3B82F6",
    "#EF4444",
    "#F59E0B",
    "#22C55E",
    "#8B5CF6",
    "#06B6D4",
    "#F43F5E",
    "#64748B",
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
    : "#334155";
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
      { label: "时间", render: (r) => fmtTime(r.signal_time) },
      { label: "代码", key: "code" },
      { label: "名称", key: "name" },
      { label: "价格", key: "price" },
      { label: "行业", key: "industry_name" },
      { label: "结构状态", render: (r) => badgeStatus(r.structure_status) },
      { label: "标签", render: (r) => fmtTags(r.missing_tags) },
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
      { label: "日期", render: (r) => fmtTime(r.stat_date) },
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
      { label: "运行时间", render: (r) => fmtTime(r.run_time) },
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
      { label: "最新日期", key: "check_date" },
      { label: "数据最新", key: "data_latest_date" },
      { label: "市场", key: "market" },
      { label: "周期", key: "period" },
      { label: "应有标的", key: "total_symbols" },
      { label: "可用标的", key: "available_symbols" },
      { label: "缺标的", key: "missing_symbols" },
      { label: "行数", key: "row_count" },
      { label: "预期行数", key: "expected_rows" },
      { label: "重复key", key: "duplicate_keys" },
      { label: "重复行", key: "duplicate_rows" },
      { label: "条数异常标的", key: "bar_count_bad_symbols" },
      { label: "异常K线", key: "abnormal_bar_count" },
      {
        label: "状态",
        render: (r) => {
          const s = r.status || "-";
          const cls = s === "ok" ? "ok" : s === "missing" ? "bad" : "mid";
          return `<span class="badge ${cls}">${fmt(s)}</span>`;
        },
      },
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
      { label: "计算时间", render: (r) => fmtTime(r.batch_run_time) },
      { label: "信号时间", render: (r) => fmtTime(r.signal_time) },
      { label: "入选状态", key: "selection_status" },
      { label: "最终分", render: (r) => r.final_score == null ? "-" : Number(r.final_score).toFixed(3) },
      { label: "近3日%", render: (r) => r.recent_3d_pct == null ? "-" : Number(r.recent_3d_pct).toFixed(2) },
      { label: "起爆状态", key: "explode_status" },
      { label: "市场状态", key: "market_state" },
      { label: "题材强度", key: "hot_topic_strength" },
      { label: "题材地位", key: "position_in_hot_topic" },
      { label: "结构状态", render: (r) => badgeStatus(r.structure_status) },
      { label: "缺失标签", render: (r) => fmtTags(r.missing_tags) },
      { label: "说明", key: "explain_text" },
    ],
    rows || [],
  );
}

async function loadJobs() {
  ensureJobShardPanel();
  const queue = await api("/api/jobs/queue?job_type=run_2560");
  const execs = await api(
    "/api/jobs/executions?job_type=run_2560&job_type=run_2560_now",
  );
  renderTable(
    $("jobQueueTable"),
    [
      { label: "ID", key: "id" },
      { label: "任务类型", key: "job_type" },
      { label: "市场范围", render: jobQueueMarket },
      { label: "执行ID", render: jobQueueExecutionId },
      { label: "并发数", render: jobQueueShards },
      { label: "策略", key: "strategy_code" },
      { label: "优先级", key: "priority" },
      { label: "状态", key: "status" },
      { label: "创建时间", key: "created_at" },
      { label: "开始时间", key: "started_at" },
      { label: "结束时间", key: "finished_at" },
    ],
    queue || [],
    async (queueId) => {
      const row = (queue || []).find((r) => String(r.id) === String(queueId));
      const execId = jobQueueExecutionId(row);
      renderJobExecutions(execs || [], execId, queueId);
      if (execId && execId !== "-") {
        state.selectedJobExecutionId = execId;
        state.selectedJobQueueId = queueId;
        await loadJobDetails(execId);
        const execRow = (execs || []).find((r) => String(r.id) === String(execId));
        if (execRow && isActiveJobStatus(execRow.status)) startJobAutoRefresh();
        else stopJobAutoRefresh();
      }
    },
  );
  renderJobExecutions(execs || [], null, null);
}

function renderJobExecutions(rows, execId, queueId) {
  let filtered = rows || [];
  if (execId && execId !== "-") {
    filtered = filtered.filter((r) => String(r.id) === String(execId));
  }
  renderTable(
    $("jobExecTable"),
    [
      { label: "ID", key: "id" },
      { label: "类型", key: "job_type" },
      { label: "来源", render: (r) => executionSourceLabel(r, queueId) },
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
    filtered,
    async (id) => {
      if (!id) return;
      state.selectedJobExecutionId = id;
      state.selectedJobQueueId = queueId;
      await loadJobDetails(id);
      const execRow = filtered.find((r) => String(r.id) === String(id));
      if (execRow && isActiveJobStatus(execRow.status)) startJobAutoRefresh();
      else stopJobAutoRefresh();
    },
  );
}

async function loadJobDetails(id) {
  await loadJobShards(id);
}

async function loadJobShards(id) {
  ensureJobShardPanel();
  const table = $("jobShardTable");
  if (!table) return;
  const data = await api("/api/jobs/executions/" + id + "/shards");
  renderTable(
    table,
    [
      { label: "Shard", key: "shard_id" },
      { label: "完成进度", render: renderShardProgress },
      { label: "成功", key: "success_count" },
      { label: "失败", key: "failed_count" },
      { label: "运行中", key: "running_count" },
      { label: "待执行", key: "pending_count" },
      { label: "当前代码", key: "current_code" },
      { label: "平均耗时ms", key: "avg_elapsed_ms" },
      { label: "更新时间", key: "updated_at" },
    ],
    (data && data.items) || [],
  );
}

async function loadJobItems(id) {
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
}

async function refresh() {
  await loadHealth();
  if (state.view === "workspace") await loadWorkspace();
  if (state.view === "result-workbench" && typeof window.loadResultWorkbench === "function") await window.loadResultWorkbench();
  if (state.view === "simple-2560" && typeof window.loadSimple2560Report === "function") await window.loadSimple2560Report();
  if (state.view === "overview") await loadOverview();
  if (state.view === "run") await loadStocks();
  if (state.view === "signals") await loadSignals();
  if (state.view === "latest") await loadLatest();
  if (state.view === "jobs") await loadJobs();
  if (state.view === "statistics") await loadStatistics();
  if (state.view === "batches") await loadBatches();
  if (state.view === "quality") await loadQuality();
}

// 加载 topbar 目标交易日
async function loadTopbarDate() {
  try {
    const d = await api("/api/strategy/2560/workspace");
    const el = $("topbarDate");
    if (el && d.target_date) el.textContent = d.target_date;
  } catch { /* ignore */ }
}

// 统一 POST 检查：HTTP 状态 + 业务 ok/success
async function postJsonChecked(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false || d.success === false) {
    throw new Error(d.message || d.detail || r.statusText);
  }
  return d.data ?? d;
}

// 市场卡片操作函数
async function _marketAction(market, label, fn) {
  const btns = document.querySelectorAll(`[data-market-action="${market}"]`);
  btns.forEach(b => { b.disabled = true; b.textContent = `${label}...`; });
  try {
    await fn();
    btns.forEach(b => { b.disabled = false; b.textContent = label; });
    await loadWorkspace();
  } catch (e) {
    btns.forEach(b => { b.disabled = false; b.textContent = label; });
    alert(`${market} ${label} 失败: ${e.message}`);
  }
}

// 日期工具：int(20260512/20260512150000) → "2026-05-12"
function ymdFromInt(v) {
  if (!v) return null;
  const s = String(v).slice(0, 8);
  if (s.length !== 8) return null;
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
}

function todayYmd() {
  return new Date().toISOString().slice(0, 10);
}

function selectedReportTradeDate() {
  const input = $("reportPackageTradeDate");
  return (input && input.value) || state.workspaceTargetDate || todayYmd();
}

function selectedMorningTradeDate() {
  const input = $("morningReportTradeDate");
  return (input && input.value) || state.workspaceTargetDate || todayYmd();
}

async function reportFileExists(url) {
  try {
    const response = await fetch(url);
    return response.ok;
  } catch (e) {
    return false;
  }
}

function renderWorkspaceReportPackageResult(message) {
  const host = $("workspaceReportPackage");
  if (!host) return;
  const result = state.workspaceReportPackageResult;
  if (!result) {
    host.innerHTML = `<p class="muted">先生成盘后流程报告，再按交易日查看当日报告包。</p>`;
    return;
  }
  if (result.error) {
    host.innerHTML = `<div class="panel"><p style="color:#F87171;margin:0"><b>生成失败</b>：${result.error}</p></div>`;
    return;
  }
  const files = Array.isArray(result.files) ? result.files : [];
  const tradeDate = result.trade_date || selectedReportTradeDate();
  const skillInputUrl = `/api/reports/skill-input.md?trade_date=${encodeURIComponent(tradeDate)}`;
  host.innerHTML = `
    <div class="panel">
      <div style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap">
        <div>
          <p style="margin:0"><b>生成状态</b>：${fmt(result.status || "generated")}</p>
          <p class="muted" style="margin:6px 0 0">交易日：${fmt(tradeDate)}${result.batch_id ? ` · batch_id：${result.batch_id}` : ""}</p>
          ${message ? `<p class="muted" style="margin:6px 0 0">${message}</p>` : ""}
        </div>
        <div>
          <a class="ghost" href="${skillInputUrl}" target="_blank">查看 08_skill_input.md</a>
        </div>
      </div>
      <div style="margin-top:12px">
        <div class="muted" style="margin-bottom:8px">生成文件</div>
        <ul style="margin:0;padding-left:20px;line-height:1.8">
          ${files.map((path) => {
            const filename = String(path || "").split("/").pop() || "";
            const fileUrl = `/api/reports/daily-package/file?trade_date=${encodeURIComponent(tradeDate)}&filename=${encodeURIComponent(filename)}`;
            return `<li><a href="${fileUrl}" target="_blank">${filename}</a></li>`;
          }).join("")}
        </ul>
      </div>
    </div>`;
}

function renderWorkspaceMorningReportPackageResult(message) {
  const host = $("workspaceMorningReportPackage");
  if (!host) return;
  const result = state.workspaceMorningReportPackageResult;
  if (!result) {
    host.innerHTML = `<p class="muted">默认按该日期回看上一个交易日的 focus/watch 清单，生成 09 和 10 两份早盘报告。</p>`;
    return;
  }
  if (result.error) {
    host.innerHTML = `<div class="panel"><p style="color:#F87171;margin:0"><b>生成失败</b>：${result.error}</p></div>`;
    return;
  }
  const files = Array.isArray(result.files) ? result.files : [];
  const tradeDate = result.trade_date || selectedMorningTradeDate();
  const confirmUrl = `/api/reports/morning-confirm.md?trade_date=${encodeURIComponent(tradeDate)}`;
  const skillUrl = `/api/reports/skill-morning-input.md?trade_date=${encodeURIComponent(tradeDate)}`;
  host.innerHTML = `
    <div class="panel">
      <div style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap">
        <div>
          <p style="margin:0"><b>生成状态</b>：${fmt(result.status || "generated")}</p>
          <p class="muted" style="margin:6px 0 0">交易日：${fmt(tradeDate)} · 来源盘后日：${fmt(result.source_trade_date)}</p>
          ${message ? `<p class="muted" style="margin:6px 0 0">${message}</p>` : ""}
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <a class="ghost" href="${confirmUrl}" target="_blank">查看 09_morning_confirm.md</a>
          <a class="ghost" href="${skillUrl}" target="_blank">查看 10_skill_morning_input.md</a>
        </div>
      </div>
      <div style="margin-top:12px">
        <div class="muted" style="margin-bottom:8px">生成文件</div>
        <ul style="margin:0;padding-left:20px;line-height:1.8">
          ${files.map((path) => `<li>${String(path || "").split("/").pop() || ""}</li>`).join("")}
        </ul>
      </div>
    </div>`;
}

async function restoreExistingDailyReportPackage(tradeDate) {
  const skillInputUrl = `/api/reports/skill-input.md?trade_date=${encodeURIComponent(tradeDate)}`;
  if (!await reportFileExists(skillInputUrl)) return false;
  state.workspaceReportPackageResult = {
    status: "generated",
    trade_date: tradeDate,
    files: [
      "01_daily_selection.md",
      "02_focus_full_reports.md",
      "03_watch_lite_reports.md",
      "04_scan_summary.json",
      "05_focus_watch_list.json",
      "06_reject_summary.json",
      "07_field_audit.json",
      "08_skill_input.md",
    ].map((filename) => `reports/${tradeDate}/${filename}`),
  };
  renderWorkspaceReportPackageResult("已检测到现有报告工作区文件");
  return true;
}

async function restoreExistingMorningReportPackage(tradeDate) {
  const confirmUrl = `/api/reports/morning-confirm.md?trade_date=${encodeURIComponent(tradeDate)}`;
  if (!await reportFileExists(confirmUrl)) return false;
  state.workspaceMorningReportPackageResult = {
    status: "generated",
    trade_date: tradeDate,
    source_trade_date: previousWeekday(tradeDate),
    files: [
      "09_morning_confirm.md",
      "10_skill_morning_input.md",
    ].map((filename) => `reports/${tradeDate}/${filename}`),
  };
  renderWorkspaceMorningReportPackageResult("已检测到现有早盘确认文件");
  return true;
}

window.restoreWorkspaceReportPackages = async function() {
  if (!state.workspaceReportPackageResult) {
    await restoreExistingDailyReportPackage(selectedReportTradeDate());
  }
  if (!state.workspaceMorningReportPackageResult) {
    await restoreExistingMorningReportPackage(selectedMorningTradeDate());
  }
};

function dateMinusDays(ymd, days) {
  const d = new Date(`${ymd}T00:00:00`);
  d.setDate(d.getDate() - days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

window.build30m = function(market) {
  _marketAction(market, "构建30m", async () => {
    const mr = state.workspaceMarketReadiness[market] || {};
    const end = ymdFromInt(mr.k5m_latest || mr.daily_latest || mr.k30m_latest) || state.workspaceTargetDate;
    if (!end) throw new Error("无法确定构建30m的结束日期");
    const start = dateMinusDays(end, 5);
    await postJsonChecked("/api/import/build-30m", { market, start, end, workers: 2 });
  });
};

window.rebuildIndicators = function(market) {
  _marketAction(market, "重算指标", async () => {
    const mr = state.workspaceMarketReadiness[market] || {};
    const end = ymdFromInt(mr.k30m_latest || mr.k5m_latest || mr.daily_latest) || state.workspaceTargetDate;
    if (!end) throw new Error("无法确定重算指标的结束日期");
    const start = dateMinusDays(end, 5);
    await postJsonChecked("/api/import/rebuild-indicators", {
      market, start, end,
      periods: "daily,5m,30m",
      commit_every: 100,
    });
  });
};

window.run2560 = function(market) {
  _marketAction(market, "运行2560", async () => {
    await postJsonChecked("/api/jobs/enqueue", { job_type: "run_2560", strategy_code: "S2560", market, shards: 1, priority: 3 });
  });
};

window.startDailyWorkflowFromWorkspace = function() {
  navigateTo("workflow");
  setTimeout(() => {
    if (typeof window.startWorkflow === "function") {
      window.startWorkflow();
    }
  }, 100);
};

window.openLatestResultsFromWorkspace = function() {
  navigateTo("result-workbench");
};

window.generateDailyReportPackageFromWorkspace = async function() {
  const btn = $("dailyGenerateReportPackageBtn");
  const tradeDate = selectedReportTradeDate();
  if (!tradeDate) {
    state.workspaceReportPackageResult = { error: "无法确定交易日" };
    renderWorkspaceReportPackageResult();
    return;
  }
  const originalText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "生成中...";
  }
  try {
    const result = await api(`/api/reports/daily-package/new?trade_date=${encodeURIComponent(tradeDate)}`, {
      method: "POST",
    });
    state.workspaceReportPackageResult = result;
    renderWorkspaceReportPackageResult(`已写入 reports/${tradeDate}/`);
  } catch (e) {
    state.workspaceReportPackageResult = { error: e.message, trade_date: tradeDate };
    renderWorkspaceReportPackageResult();
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText || "生成盘后报告包";
    }
  }
};

window.generateMorningReportPackageFromWorkspace = async function() {
  const btn = $("dailyGenerateMorningReportBtn");
  const tradeDate = selectedMorningTradeDate();
  if (!tradeDate) {
    state.workspaceMorningReportPackageResult = { error: "无法确定交易日" };
    renderWorkspaceMorningReportPackageResult();
    return;
  }
  const sourceTradeDate = previousWeekday(tradeDate);
  const originalText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "生成中...";
  }
  try {
    const result = await api(
      `/api/reports/morning-package/new?trade_date=${encodeURIComponent(tradeDate)}&source_trade_date=${encodeURIComponent(sourceTradeDate)}`,
      { method: "POST" },
    );
    state.workspaceMorningReportPackageResult = result;
    renderWorkspaceMorningReportPackageResult(`已写入 reports/${tradeDate}/`);
  } catch (e) {
    state.workspaceMorningReportPackageResult = {
      error: e.message,
      trade_date: tradeDate,
      source_trade_date: sourceTradeDate,
    };
    renderWorkspaceMorningReportPackageResult();
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText || "生成早盘确认报告";
    }
  }
};

function previousWeekday(ymd) {
  const d = new Date(`${ymd}T00:00:00`);
  d.setDate(d.getDate() - 1);
  while (d.getDay() === 0 || d.getDay() === 6) {
    d.setDate(d.getDate() - 1);
  }
  return d.toISOString().slice(0, 10);
}

const titles = {
  workspace: ["今日工作台", "今天数据齐了吗、缺什么、点哪里、2560跑完了吗、最后看哪几只"],
  overview: ["总览", "查看最新批次、结构完整率、标签分布与系统状态"],
  "result-workbench": ["结果工作台", "报告生成后的追溯入口：默认看今日可看，需要时再切全部最新、历史信号或标注明细"],
  "simple-2560": ["简版2560", "按交易日日期查看简化硬指标计算结果"],
  workflow: ["一键盘后流程", "日常盘后入口：导入、重建30m、fast 2560、观察池"],
  run: ["入库计算", "支持选择股票、全选、四类股票范围摸底计算"],
  signals: ["信号列表", "逐条查看2560结构条件、标签与解释"],
  latest: ["最新分析结果", "每只股票在最近一次分析中的最终状态"],
  jobs: ["任务进度", "后台调度、执行状态和分组进度"],
  statistics: ["结果统计", "按结构状态、标签、行业、板块、概念统计"],
  batches: ["分析批次", "查看分析批次、版本、运行状态"],
  quality: ["数据质量", "查看日线/分钟线完整性与异常情况"],
  "data-import": ["行情导入与日志", "扫描源文件、导入日线/5m，并查看批次和失败文件"],
  "data-maintenance": ["数据构建与维护", "重建30m；周末维护或历史修复时重算指标"],
  "observation-pool": ["今日观察池", "看什么、为什么看、持有怎么办、没持有怎么买、什么情况跑"],
};

// 唯一导航入口：app.js 管理所有 view 切换、标题更新、active 高亮
function navigateTo(view) {
  if (view === "complete") view = "signals";
  if (view === "diagnostics" || view === "diagnostic-indicators") view = "quality";
  if (!view || !titles[view]) return;
  if ((view === "data-import" || view === "data-maintenance") && typeof window.showDataImportView === "function") {
    window.showDataImportView(view);
    return;
  }
  state.view = view;
  state.page = 1;

  // 切换视图
  document
    .querySelectorAll(".view")
    .forEach((v) => v.classList.remove("active"));
  const target = $("view-" + view);
  if (target) target.classList.add("active");

  // 更新标题
  if ($("pageTitle")) $("pageTitle").textContent = titles[view][0];
  if ($("pageSubtitle")) $("pageSubtitle").textContent = titles[view][1];

  // 更新阶段标签
  const phaseMap = {
    "data-update": "数据准备",
    jobs: "任务管理",
    "result-workbench": "结果中心",
    "simple-2560": "结果中心",
    "observation-pool": "观察池",
    latest: "分析结果",
  };
  const phaseEl = $("pagePhase");
  if (phaseEl) {
    if (phaseMap[view]) {
      phaseEl.textContent = phaseMap[view];
      phaseEl.style.display = "";
    } else {
      phaseEl.textContent = "";
      phaseEl.style.display = "none";
    }
  }

  // 更新侧栏 active 状态（兼容原始按钮和重建后的按钮）
  document
    .querySelectorAll(".nav-item[data-view]")
    .forEach((x) => x.classList.remove("active"));
  document
    .querySelectorAll(`.nav-item[data-view="${view}"]`)
    .forEach((x) => x.classList.add("active"));

  // 自动展开包含该 view 的折叠分组
  const activeBtn = document.querySelector(`.nav-item[data-view="${view}"]`);
  if (activeBtn) {
    const collapsedSub = activeBtn.closest(".nav-sub.collapsed");
    if (collapsedSub) {
      // 先折叠其他分组
      document
        .querySelectorAll(".nav-sub.collapsed, .nav-sub:not(.collapsed)")
        .forEach((s) => {
          s.classList.add("collapsed");
          const heading = s.closest(".nav-static-group")?.querySelector(".nav-group-title");
          if (heading) heading.classList.add("collapsed");
        });
      // 再展开目标分组
      collapsedSub.classList.remove("collapsed");
      const heading = collapsedSub.closest(".nav-static-group")?.querySelector(".nav-group-title");
      if (heading) heading.classList.remove("collapsed");
    }
  }

  refresh();
  if (view === "observation-pool" && typeof window.loadObservationPool === "function") {
    window.loadObservationPool();
  }
}

// 原始 HTML 按钮的 click 绑定（nested_menu_reorg.js 重建菜单前生效）
document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => {
    navigateTo(b.dataset.view);
  }),
);
$("refreshBtn").onclick = refresh;
if ($("dailyStartWorkflowBtn")) $("dailyStartWorkflowBtn").onclick = window.startDailyWorkflowFromWorkspace;
if ($("dailyLatestResultsBtn")) $("dailyLatestResultsBtn").textContent = "打开结果工作台";
if ($("dailyLatestResultsBtn")) $("dailyLatestResultsBtn").onclick = window.openLatestResultsFromWorkspace;
if ($("dailyGenerateReportPackageBtn")) $("dailyGenerateReportPackageBtn").onclick = window.generateDailyReportPackageFromWorkspace;
if ($("dailyGenerateMorningReportBtn")) $("dailyGenerateMorningReportBtn").onclick = window.generateMorningReportPackageFromWorkspace;
if ($("reportPackageTradeDate")) $("reportPackageTradeDate").onchange = () => {
  state.workspaceReportPackageResult = null;
  renderWorkspaceReportPackageResult();
  window.restoreWorkspaceReportPackages();
};
if ($("morningReportTradeDate")) $("morningReportTradeDate").onchange = () => {
  state.workspaceMorningReportPackageResult = null;
  renderWorkspaceMorningReportPackageResult();
  window.restoreWorkspaceReportPackages();
};
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
$("probeSh60Btn").onclick = () => runProbe("sh60");
$("probeSh68Btn").onclick = () => runProbe("sh68");
$("probeSz00Btn").onclick = () => runProbe("sz00");
$("probeSz30Btn").onclick = () => runProbe("sz30");
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

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => { refresh(); loadTopbarDate(); });
} else {
  refresh();
  loadTopbarDate();
}

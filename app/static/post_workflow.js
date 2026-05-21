(function(){
  "use strict";

  function $(id){ return document.getElementById(id); }

  // ====== 全局状态 ======
  let workflowState = {
    running: false,
    steps: [],
    currentStepIndex: 0,
    workspace: null,
    timer: null,
  };

  // ====== 步骤定义 ======
  const STEPS = [
    { id: "check",     label: "检查数据就绪",   type: "info" },
    { id: "import",    label: "行情导入",       type: "api" },
    { id: "build30m",  label: "构建30m",        type: "api" },
    { id: "indicators",label: "重算指标",       type: "api" },
    { id: "run2560",   label: "运行2560四类",   type: "api" },
    { id: "pool",      label: "查看观察池",     type: "info" },
  ];

  const ICONS = { pending: "○", running: "▶", done: "✓", skipped: "—", failed: "✗" };

  // ====== 从 workspace readiness 推导执行计划 ======
  function computePlan(ws) {
    const mr = ws.market_readiness || [];
    const anyMissingData = mr.some(m => (m.missing || []).length > 0);
    const anyIndicatorsStale = mr.some(m => !m.indicators_fresh);
    const anyMissing30m = mr.some(m => (m.missing || []).includes("30m"));
    const targetDate = ws.target_date;

    // 推导 import 的 start（取最新已有数据向前推5天，end 始终用 targetDate）
    let latestExisting = targetDate;  // 默认就是今天
    for (const m of mr) {
      const cand = m.k5m_latest || m.daily_latest;
      if (cand) {
        const ymd = ymdFromInt(cand);
        if (ymd && ymd > latestExisting) latestExisting = ymd;
      }
    }
    const importEnd = targetDate;
    const importStart = dateMinusDays(latestExisting, 5);

    const stepLabels = Object.fromEntries(STEPS.map(s => [s.id, s.label]));

    return [
      {
        id: "check", label: stepLabels["check"], status: "done",
        summary: anyMissingData ? "部分市场缺K线数据" : "四市场数据已最新",
        detail: mr.map(m => `${m.market}: ${m.status}`).join(" | "),
      },
      {
        id: "import", label: stepLabels["import"], status: anyMissingData ? "pending" : "skipped",
        endpoint: "/api/import/run",
        reason: anyMissingData ? undefined : "行情数据已齐，无需导入",
        payload: anyMissingData ? { source_dir: "/data/vipdoc", start: importStart, end: importEnd, workers: 2 } : null,
      },
      {
        id: "build30m", label: stepLabels["build30m"], status: anyMissing30m ? "pending" : "skipped",
        endpoint: "/api/import/build-30m",
        reason: anyMissing30m ? undefined : "30m 已跟上",
        payload: anyMissing30m ? { market: "all", start: importStart, end: importEnd, workers: 2 } : null,
      },
      {
        id: "indicators", label: stepLabels["indicators"], status: anyIndicatorsStale ? "pending" : "skipped",
        endpoint: "/api/import/rebuild-indicators",
        reason: anyIndicatorsStale ? undefined : "指标已是最新",
        payload: anyIndicatorsStale ? { market: "all", start: importStart, end: importEnd, periods: "daily,5m,30m", commit_every: 100 } : null,
      },
      {
        id: "run2560", label: stepLabels["run2560"], status: "pending",
        endpoint: "/api/jobs/run-all-markets",
        payload: { shards: 1 },  // run-all-markets 自带 market lane 防重
      },
      {
        id: "pool", label: stepLabels["pool"], status: "pending",
        summary: "加载今日观察池 A/B 级股票",
      },
    ];
  }

  // ====== 日期工具 ======
  function ymdFromInt(v) {
    if (!v) return null;
    const s = String(v).slice(0, 8);
    if (s.length !== 8) return null;
    return `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}`;
  }

  function dateMinusDays(ymd, days) {
    const d = new Date(`${ymd}T00:00:00`);
    d.setDate(d.getDate() - days);
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  }

  // ====== 统一 POST 检查（复用 app.js 的 postJsonChecked 逻辑） ======
  async function postJson(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || d.ok === false || d.success === false) {
      throw new Error(d.message || d.detail || r.statusText || "请求失败");
    }
    return d;
  }

  async function getJson(url) {
    const r = await fetch(url);
    const d = await r.json().catch(() => ({}));
    if (!r.ok || d.ok === false || d.success === false) {
      throw new Error(d.message || d.detail || r.statusText || "GET 请求失败");
    }
    return d;
  }

  // ====== 渲染步骤列表 ======
  function renderSteps() {
    const container = $("workflowSteps");
    if (!container) return;
    container.innerHTML = workflowState.steps.map((s, i) => {
      const icon = ICONS[s.status] || "○";
      const cls = s.status;
      const isActive = i === workflowState.currentStepIndex;
      return `
      <div class="workflow-step${isActive ? ' active' : ''}" data-step-index="${i}">
        <span class="step-icon ${cls}">${icon}</span>
        <span class="step-label">${s.label}</span>
        <span class="step-status">${statusText(s)}</span>
        <span class="step-actions">${actionButtons(s, i)}</span>
      </div>`;
    }).join("");

    // 步骤详情区
    renderStepDetail();
  }

  function statusText(s) {
    if (!s || !s.status) return "";
    if (s.status === "done") return (s.summary != null && s.summary !== "") ? s.summary : "完成";
    if (s.status === "skipped") return (s.reason != null && s.reason !== "") ? s.reason : "已跳过";
    if (s.status === "failed") return (s.error != null && s.error !== "") ? s.error : "失败";
    if (s.status === "running" && s.progress != null) return `${s.progress}%`;
    return "";
  }

  function actionButtons(s, i) {
    if (!s) return "";
    let btns = "";
    if (s.status === "pending") btns += `<button class="ghost wf-step-btn" onclick="window._wfSkip(${i})">跳过</button>`;
    if (s.status === "failed") btns += `<button class="ghost wf-step-btn" onclick="window._wfRetry(${i})">重试</button>`;
    return btns;
  }

  let activeJobsPollTimer = null;

  function renderStepDetail() {
    const container = $("workflowStepDetail");
    if (!container) return;
    const step = workflowState.steps[workflowState.currentStepIndex];
    if (!step) { container.innerHTML = ""; return; }

    let html = `<div class="wf-detail"><h4>${step.label}</h4>`;
    if (step.detail) html += `<p>${step.detail}</p>`;
    if (step.jobId) html += `<p class="muted">任务 #${step.jobId} | <a href="#" onclick="window._wfViewJob(${step.jobId});return false">查看进度</a></p>`;
    if (step.status === "running" && step.log) html += `<pre class="wf-log">${step.log}</pre>`;
    if (step.status === "done" && step.summary) html += `<p style="color:var(--green)">${step.summary}</p>`;

    // 正在运行时，显示所有活跃任务
    if (step.status === "running") {
      html += `<div style="margin-top:12px"><button class="ghost" id="wfActiveJobsBtn">查看所有运行中任务</button></div>`;
      html += `<div id="wfActiveJobs" style="margin-top:8px"></div>`;
    }

    html += `</div>`;
    container.innerHTML = html;

    // 绑定按钮
    if (step.status === "running") {
      const btn = $("wfActiveJobsBtn");
      if (btn) btn.onclick = () => loadActiveJobs(step);
    }
  }

  async function loadActiveJobs(step) {
    const container = $("wfActiveJobs");
    if (!container) return;
    container.innerHTML = `<p class="muted">正在加载...</p>`;

    try {
      const execs = await getJson("/api/jobs/executions?limit=200");
      const runningJobs = (execs || []).filter(j => {
        const s = (j.status || "").toLowerCase();
        return s === "running" || s === "queued" || s === "pending";
      });

      if (!runningJobs.length) {
        container.innerHTML = `<p class="muted">当前无运行中的任务</p>`;
        return;
      }

      container.innerHTML = `<div class="table-wrap"><table>
        <thead><tr><th>ID</th><th>类型</th><th>市场</th><th>进度</th><th>成功/失败</th><th>当前代码</th><th>消息</th><th>操作</th></tr></thead>
        <tbody>${runningJobs.map(j => {
          const pct = j.progress_total > 0 ? Math.round((j.progress_current / j.progress_total) * 100) : 0;
          const typeLabel = {
            import_vipdoc: "导入",
            build_30m: "构建30m",
            rebuild_indicator: "重算指标",
            run_2560: "运行2560",
          }[j.job_type] || j.job_type;
          return `<tr>
            <td>${j.id}</td>
            <td>${typeLabel}</td>
            <td>${j.market || "-"}</td>
            <td><div style="min-width:100px"><div style="height:8px;background:#334155;border-radius:999px;overflow:hidden"><div style="height:100%;width:${pct}%;background:#3B82F6;border-radius:999px"></div></div><div style="font-size:11px;color:#94A3B8">${j.progress_current}/${j.progress_total} (${pct}%)</div></div></td>
            <td style="color:var(--green)">${j.success_count || 0}</td><td style="color:#EF4444">${j.failed_count || 0}</td>
            <td class="muted" style="font-size:12px">${j.current_code || "-"}</td>
            <td class="muted" style="font-size:12px;max-width:200px;overflow:hidden;text-overflow:ellipsis">${j.message || "-"}</td>
            <td><button class="ghost" style="font-size:12px;padding:2px 6px" onclick="window._wfViewJob(${j.id})">详情</button></td>
          </tr>`;
        }).join("")}</tbody>
      </table></div>`;

      // 自动刷新
      if (activeJobsPollTimer) clearInterval(activeJobsPollTimer);
      activeJobsPollTimer = setInterval(async () => {
        const el = $("wfActiveJobs");
        if (!el) { clearInterval(activeJobsPollTimer); return; }
        try {
          const updated = await getJson("/api/jobs/executions?limit=200");
          const updatedJobs = (updated || []).filter(j => {
            const s = (j.status || "").toLowerCase();
            return s === "running" || s === "queued" || s === "pending";
          });
          if (!updatedJobs.length) {
            el.innerHTML = `<p class="muted">所有任务已完成</p>`;
            clearInterval(activeJobsPollTimer);
            return;
          }
          // 更新表格内容（不重建整个 HTML，只更新进度数字）
          el.querySelectorAll("tbody tr").forEach((tr, idx) => {
            const j = updatedJobs[idx];
            if (!j) return;
            const pct = j.progress_total > 0 ? Math.round((j.progress_current / j.progress_total) * 100) : 0;
            const bar = tr.querySelector("td:nth-child(4) .bar-fill, td:nth-child(4) div div");
            if (bar) bar.style.width = pct + "%";
            const text = tr.querySelector("td:nth-child(4) div div:last-child");
            if (text) text.textContent = `${j.progress_current}/${j.progress_total} (${pct}%)`;
            const succ = tr.querySelector("td:nth-child(5)");
            if (succ) succ.textContent = j.success_count || 0;
            const fail = tr.querySelector("td:nth-child(6)");
            if (fail) fail.textContent = j.failed_count || 0;
            const code = tr.querySelector("td:nth-child(7)");
            if (code) code.textContent = j.current_code || "-";
            const msg = tr.querySelector("td:nth-child(8)");
            if (msg) msg.textContent = j.message || "-";
          });
        } catch { /* ignore poll errors */ }
      }, 5000);

    } catch (e) {
      container.innerHTML = `<p class="muted" style="color:#EF4444">加载失败: ${e.message}</p>`;
    }
  }

  // ====== 流程引擎 ======
  async function startWorkflow() {
    if (workflowState.running) return;
    workflowState.running = true;

    const btn = $("workflowStartBtn");
    if (btn) { btn.disabled = true; btn.textContent = "执行中..."; }

    try {
      const ws = await getJson("/api/strategy/2560/workspace");
      workflowState.workspace = ws;
      workflowState.steps = computePlan(ws.data || ws);
      workflowState.currentStepIndex = 0;
      renderSteps();

      // 找到第一个 pending 步骤
      let startIdx = workflowState.steps.findIndex(s => s.status === "pending");
      if (startIdx < 0) {
        workflowState.steps[workflowState.steps.length - 1].status = "done";
        workflowState.steps[workflowState.steps.length - 1].summary = "所有步骤已完成";
        renderSteps();
        return;
      }

      for (let i = startIdx; i < workflowState.steps.length; i++) {
        workflowState.currentStepIndex = i;
        const step = workflowState.steps[i];
        if (step.status === "skipped") continue;
        await executeStep(step, i);
        renderSteps();
        if (step.status === "failed") break;  // 失败后停止
      }
    } catch (e) {
      alert("工作流启动失败: " + e.message);
    } finally {
      workflowState.running = false;
      if (btn) { btn.disabled = false; btn.textContent = "一键盘后流程"; }
    }
  }

  async function executeStep(step, index) {
    if (step.type === "info") {
      step.status = "done";
      if (step.id === "pool") {
        try {
          const ann = await getJson("/api/strategy/2568/annotations?market_type=all&limit=20&min_a=0&min_b=2");
          const total = (ann.summary && ann.summary.total) || 0;
          step.summary = `观察池共 ${total} 只`;
        } catch {
          step.summary = "观察池加载失败";
        }
      }
      return;
    }

    // API 类型
    step.status = "running";
    step.progress = 0;
    renderSteps();

    try {
      let result;

      if (step.id === "import") {
        // 导入分两步：先 lday 再 5m
        const payload = step.payload || {};
        for (const itype of ["lday", "5m"]) {
          result = await postJson(step.endpoint, { ...payload, market: "all", import_type: itype });
          step.jobId = result.job_id;
          step.progressUrl = result.progress_url;
          await pollJobProgress(step);
          if (step.status === "failed") return;
        }
        step.status = "done";
        step.summary = `导入完成 (lday + 5m)`;
        await refreshPlanAfter("import");
      } else if (step.id === "run2560") {
        // 一键运行四类（并行创建4个market任务）
        result = await postJson(step.endpoint, step.payload);
        const created = (result.created || []);
        const skipped = (result.skipped || []).map(s => `${s.market}(${s.reason})`).join(", ");

        if (created.length === 0) {
          if (skipped) {
            step.status = "failed";
            step.error = `四市场已有活跃 2560 任务，未创建新任务：${skipped}`;
          } else {
            step.status = "done";
            step.summary = "无新任务";
          }
          return;
        } else {
          // 等待所有 market lane 完成
          step.summary = `已创建 ${created.length} 个任务，等待完成...`;
          const laneResults = await Promise.allSettled(
            created.map(c => {
              const execId = c.execution_id;
              const market = c.market;
              const progressUrl = `/api/jobs/executions/${execId}/progress`;
              return pollJobProgressForLane(progressUrl, market);
            })
          );
          const failed = laneResults.filter(r => r.status === "rejected" || (r.value && r.value.failed));
          const succeeded = laneResults.filter(r => r.status === "fulfilled" && !r.value?.failed);
          step.status = failed.length > 0 ? "failed" : "done";
          const markets = created.map(c => c.market).join(", ");
          step.summary = `${markets}: ${succeeded.length} 成功, ${failed.length} 失败`;
          if (skipped) step.summary += ` | 跳过: ${skipped}`;
          if (failed.length > 0) {
            step.error = `${failed.length} 个 market lane 失败`;
          }
        }
      } else {
        // build30m / indicators
        result = await postJson(step.endpoint, step.payload);
        step.jobId = result.job_id;
        step.progressUrl = result.progress_url;
        await pollJobProgress(step);
        if (step.status === "failed") return;
        step.status = "done";
        step.summary = step.label + " 完成";
        if (step.id === "build30m") {
          await refreshPlanAfter("build30m");
        }
      }
    } catch (e) {
      step.status = "failed";
      step.error = e.message;
    }
  }

  // ====== Poll 单步进度 ======
  async function pollJobProgress(step) {
    if (!step.progressUrl) return;
    return new Promise((resolve) => {
      const timer = setInterval(async () => {
        try {
          const d = await getJson(step.progressUrl);
          const pct = d.percent != null ? Math.round(d.percent) : 0;
          step.progress = pct;
          step.log = d.message || "";
          renderSteps();

          const status = (d.status || "").toLowerCase();
          if (["success", "failed", "cancelled"].includes(status)) {
            clearInterval(timer);
            if (workflowState.timer === timer) workflowState.timer = null;
            if (status === "failed") {
              step.status = "failed";
              step.error = d.message || "任务失败";
            }
            resolve();
          }
        } catch (e) {
          clearInterval(timer);
          if (workflowState.timer === timer) workflowState.timer = null;
          step.status = "failed";
          step.error = "轮询进度失败: " + e.message;
          resolve();
        }
      }, 3000);
      workflowState.timer = timer;
    });
  }

  // ====== Poll 单个 market lane 进度（run2560 用） ======
  async function pollJobProgressForLane(progressUrl, market) {
    return new Promise((resolve, reject) => {
      const timer = setInterval(async () => {
        try {
          const d = await getJson(progressUrl);
          const status = (d.status || "").toLowerCase();
          if (["success", "failed", "cancelled"].includes(status)) {
            clearInterval(timer);
            if (status === "failed" || status === "cancelled") {
              resolve({ market, failed: true, message: d.message || "" });
            } else {
              resolve({ market, failed: false });
            }
          }
        } catch (e) {
          clearInterval(timer);
          reject(e);
        }
      }, 3000);
    });
  }

  // ====== 关键步骤完成后刷新后续计划 ======
  async function refreshPlanAfter(stepId) {
    try {
      const wsResp = await getJson("/api/strategy/2560/workspace");
      const ws = wsResp.data || wsResp;
      const newPlan = computePlan(ws);

      for (let i = workflowState.currentStepIndex + 1; i < workflowState.steps.length; i++) {
        const oldStep = workflowState.steps[i];
        const freshStep = newPlan.find(s => s.id === oldStep.id);
        if (!freshStep) continue;

        if (oldStep.status === "pending" || oldStep.status === "skipped") {
          workflowState.steps[i] = {
            ...oldStep,
            status: freshStep.status,
            reason: freshStep.reason,
            payload: freshStep.payload,
            endpoint: freshStep.endpoint,
          };
        }
      }

      renderSteps();
    } catch (e) {
      // 刷新失败不阻断流程，保持原计划
      console.warn("refreshPlanAfter failed:", e);
    }
  }

  // ====== 跳过 / 重试 ======
  window._wfSkip = function(index) {
    const step = workflowState.steps[index];
    if (!step || step.status === "running") return;
    step.status = "skipped";
    step.reason = "用户跳过";
    renderSteps();
  };

  window._wfRetry = async function(index) {
    const step = workflowState.steps[index];
    if (!step || step.type !== "api") return;
    step.status = "pending";
    step.error = null;
    step.progress = 0;
    workflowState.currentStepIndex = index;
    renderSteps();
    await executeStep(step, index);
    renderSteps();
  };

  window._wfViewJob = function(jobId) {
    // 导航到任务队列页面并定位到该 job
    if (window.navigateTo) window.navigateTo("jobs");
  };

  // ====== 公开入口 ======
  window.startWorkflow = startWorkflow;

  // ====== 自动绑定按钮 ======
  function bindButton() {
    const checkInterval = setInterval(() => {
      const btn = $("workflowStartBtn");
      if (btn) {
        clearInterval(checkInterval);
        btn.onclick = startWorkflow;
      }
    }, 500);
  }

  document.addEventListener("DOMContentLoaded", bindButton);
  setInterval(bindButton, 1000);
})();

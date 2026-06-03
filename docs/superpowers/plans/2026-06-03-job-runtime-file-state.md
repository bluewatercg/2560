# Job Runtime File State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move realtime job progress and logs away from hot MySQL rows while keeping MySQL as the low-frequency durable task ledger.

**Architecture:** Add a small runtime store that writes per-job progress snapshots and log files under `logs/`. API endpoints read these files first and fall back to MySQL when files are not available. Runners update files frequently and throttle MySQL writes.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest, local filesystem atomic replace.

---

### Task 1: Runtime Store

**Files:**
- Create: `app/services/job_runtime_store.py`
- Test: `tests/test_job_runtime_store.py`

- [ ] Write tests for atomic progress snapshot write/read, missing snapshot fallback, log path helpers, and tail reading.
- [ ] Implement a focused runtime store with `progress_path`, `log_path`, `write_progress`, `read_progress`, `append_log_line`, and `tail_log`.
- [ ] Run runtime store tests.

### Task 2: API Read Path

**Files:**
- Modify: `app/api/jobs.py`
- Test: `tests/test_job_runtime_store.py`

- [ ] Add tests that API helper logic can read progress/log files without requiring MySQL updates.
- [ ] Make `/progress` and `/logs` prefer runtime files and fall back to existing MySQL behavior.

### Task 3: Runner Write Path

**Files:**
- Modify: `scripts/job_worker.py`
- Modify: `scripts/progress_run_now.py`
- Modify: `scripts/import_job_runner.py`
- Modify: `scripts/rebuild_indicator_job_runner.py`
- Modify: `scripts/build_30m_job_runner.py`

- [ ] Switch worker stdout/stderr to per-job `job_{id}.log` when `job_execution_id` is available.
- [ ] Write progress snapshots from runners on high-frequency progress updates.
- [ ] Throttle MySQL progress updates to no more than once every 5 seconds, while preserving final status updates.

### Task 4: Verification

- [ ] Run focused tests for runtime store and job orchestration.
- [ ] Run syntax checks for modified scripts.

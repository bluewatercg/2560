# Workspace Report Package Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a report-package generation entry to the daily workspace so users can generate the after-market `reports/YYYY-MM-DD/01-08` artifacts from the page.

**Architecture:** Keep the existing post-market workflow unchanged and add a separate workspace action that calls the existing reports API. Render a compact result panel in the workspace showing status, trade date, generated files, and a shortcut to `08_skill_input.md`.

**Tech Stack:** FastAPI reports API, vanilla JS frontend, pytest acceptance tests

---

### Task 1: Lock the workspace UI contract with a failing test

**Files:**
- Modify: `tests/test_report_driven_workflow_acceptance.py`
- Test: `tests/test_report_driven_workflow_acceptance.py`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Add the minimal workspace UI markup/hooks**
- [ ] **Step 4: Run the targeted test to verify it passes**

### Task 2: Wire the frontend action to the existing reports endpoint

**Files:**
- Modify: `app/static/app.js`
- Modify: `app/static/index.html`
- Test: `tests/test_report_driven_workflow_acceptance.py`

- [ ] **Step 1: Write or extend a failing test for the expected frontend contract**
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement the button handler, request flow, and result rendering**
- [ ] **Step 4: Run the targeted tests to verify they pass**

### Task 3: Verify end-to-end behavior stays green

**Files:**
- Test: `tests/test_report_driven_workflow_acceptance.py`

- [ ] **Step 1: Run the focused report workflow tests**
- [ ] **Step 2: Fix any regressions**
- [ ] **Step 3: Re-run the focused suite until clean**

# External Evidence Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a post-2560 external evidence layer that enriches only `focus + watch` report candidates with EastMoney hotspot context, cninfo announcement status, and Miaoxiang/Miaomeng stock facts.

**Architecture:** Create a focused `ExternalEvidenceService` that normalizes source results into `external_context` and per-candidate `external_evidence`. Wire it into `DailySelectionReportService.build_report()` after candidate classification and before rendering. Extend report package Markdown rendering to show the normalized evidence without performing external calls in render code.

**Tech Stack:** Python services, existing `ExternalCallService`, existing EastMoney/cninfo service helpers, pytest with importlib-based service tests

---

## File Structure

- Create: `app/services/external_evidence_service.py`
  - Owns query scope filtering, source orchestration, Miaoxiang relevance filtering, normalization, and source status summaries.
- Create: `tests/test_external_evidence_service.py`
  - Unit tests with fake source clients and fake external-call governance.
- Modify: `app/services/daily_selection_report.py`
  - Calls `ExternalEvidenceService` after `focus/watch/reject` are known and attaches normalized evidence to report/candidates.
- Modify: `tests/test_daily_selection_report.py`
  - Adds stubs for the new service and verifies only focus/watch are enriched.
- Modify: `app/services/report_package_service.py`
  - Adds external context and per-candidate evidence rows to package Markdown.
- Modify: `tests/test_report_package_service.py`
  - Verifies rendered report includes external evidence and source status.

## Task 1: External Evidence Service

**Files:**
- Create: `app/services/external_evidence_service.py`
- Create: `tests/test_external_evidence_service.py`

- [ ] **Step 1: Write failing tests for focus/watch filtering and relevance rules**

Test cases:

```python
def test_enrich_queries_only_focus_and_watch_candidates():
    candidates = [
        {"code": "sh.600000", "name": "焦点A", "selection_status": "focus"},
        {"code": "sz.300000", "name": "观察B", "selection_status": "watch"},
        {"code": "sh.600001", "name": "淘汰C", "selection_status": "reject"},
    ]
    service = make_service()
    result = service.enrich(candidates, trade_date="2026-06-10")
    assert service.stock_fact_client.queried_codes == ["sh.600000", "sz.300000"]
    assert result["candidate_evidence"]["sh.600001"]["evidence_quality"] == "not_queried"

def test_miaoxiang_rows_about_other_companies_are_filtered_out():
    rows = [
        {"title": "方正证券：股东拟减持", "content": "方正证券公告"},
        {"title": "金明精机：董事减持", "content": "金明精机 300281 董事减持"},
    ]
    evidence = normalize_stock_facts("sz.300281", "金明精机", rows)
    assert "方正证券" not in evidence["stock_fact_summary"]
    assert "金明精机" in evidence["stock_fact_summary"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/test_external_evidence_service.py -q`

Expected: fail because `external_evidence_service.py` does not exist.

- [ ] **Step 3: Implement minimal service**

Implementation requirements:

- `ExternalEvidenceService.enrich(candidates, trade_date)` returns:
  - `external_context`
  - `candidate_evidence`
- Candidate query scope includes `selection_status in {"focus", "watch"}` and fallback statuses from `bucket in {"可执行", "观察"}`.
- `not_queried` evidence is returned for reject candidates.
- Miaoxiang row relevance requires exact stock code, six-digit code, or stock name in title/content.
- Source failures return `unverified` evidence and do not raise.

- [ ] **Step 4: Run service tests and verify pass**

Run: `pytest tests/test_external_evidence_service.py -q`

Expected: pass.

- [ ] **Step 5: Commit service**

```bash
git add app/services/external_evidence_service.py tests/test_external_evidence_service.py
git commit -m "feat: add external evidence service"
```

## Task 2: Daily Report Integration

**Files:**
- Modify: `app/services/daily_selection_report.py`
- Modify: `tests/test_daily_selection_report.py`

- [ ] **Step 1: Write failing integration test**

Add a stub `ExternalEvidenceService` in `tests/test_daily_selection_report.py` and assert:

- enrichment receives only focus/watch candidates
- each focus/watch item gets `external_evidence`
- reject item does not trigger an external query
- report includes `external_context`

- [ ] **Step 2: Run failing focused test**

Run: `pytest tests/test_daily_selection_report.py -q`

Expected: fail until `DailySelectionReportService` attaches evidence.

- [ ] **Step 3: Wire service into `build_report()`**

Implementation requirements:

- Build `executable`, `watchlist`, and `rejected` before enrichment.
- Call `ExternalEvidenceService(db=self.db).enrich(executable + watchlist, review_trade_date)`.
- Attach per-code evidence to `candidates`, `executable`, `watchlist`, and `core_candidates`.
- Add `report["external_context"]`.
- Preserve existing hotspot and announcement fields for backward compatibility.
- If enrichment fails, set `external_context.source_status.external_evidence = "error"` and keep report generation working.

- [ ] **Step 4: Run report tests**

Run: `pytest tests/test_daily_selection_report.py -q`

Expected: pass.

- [ ] **Step 5: Commit integration**

```bash
git add app/services/daily_selection_report.py tests/test_daily_selection_report.py
git commit -m "feat: enrich daily report with external evidence"
```

## Task 3: Report Package Rendering

**Files:**
- Modify: `app/services/report_package_service.py`
- Modify: `tests/test_report_package_service.py`

- [ ] **Step 1: Write failing rendering test**

Add `external_context` and `external_evidence` to `_sample_report()` and assert generated `01_daily_selection.md` includes:

- `## 【3】外部事实核验`
- EastMoney/cninfo/Miaoxiang source status
- candidate announcement summary
- candidate stock fact summary

- [ ] **Step 2: Run failing rendering test**

Run: `pytest tests/test_report_package_service.py -q`

Expected: fail until report renderer includes external evidence.

- [ ] **Step 3: Implement rendering**

Implementation requirements:

- Add `_external_context_lines(report)`.
- Add `_external_evidence_rows(focus, watch)`.
- Insert after hotspot section and before candidate list.
- Render only normalized fields; do not call external services.
- Empty evidence renders `外部事实未验证`.

- [ ] **Step 4: Run package tests**

Run: `pytest tests/test_report_package_service.py -q`

Expected: pass.

- [ ] **Step 5: Commit rendering**

```bash
git add app/services/report_package_service.py tests/test_report_package_service.py
git commit -m "feat: render external evidence in report package"
```

## Task 4: Focused Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
pytest tests/test_external_evidence_service.py tests/test_daily_selection_report.py tests/test_report_package_service.py tests/test_external_call_service.py tests/test_market_hotspot_service.py tests/test_announcement_risk_service.py -q
```

Expected: pass.

- [ ] **Step 2: Review git status**

Run: `git status --short`

Expected: only unrelated pre-existing workspace changes remain.

- [ ] **Step 3: Summarize implementation**

Summarize:

- files changed
- tests run
- any blocked verification
- remaining implementation caveats such as real provider batch support

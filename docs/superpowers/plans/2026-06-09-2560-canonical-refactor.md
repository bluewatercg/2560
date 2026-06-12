# 2560 Canonical Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `2560短线结构算法统一改造方案 v1.2.2 Final Freeze` by replacing Fast/Slow algorithm divergence with a single canonical 2560 engine, adding market/topic/position scoring, external-call governance, and morning confirmation.

**Architecture:** Build the refactor in dependency order: constants/config/schema first, then external-call infrastructure, then canonical after-market selection, then auction and morning confirmation, then report/API cleanup. Keep existing job, API, and report entry points alive as wrappers while migrating behavior behind them.

**Tech Stack:** Python, FastAPI, SQLAlchemy/MySQL, ClickHouse HTTP client, pandas, pytest.

---

## Current Findings

- `app/services/signal_engine_2560.py` and `app/services/signal_engine_2560_fast.py` are separate algorithm paths today.
- Slow/pandas indicators already compute `high_20` with `shift(1)`, so the current K is excluded.
- Fast SQL currently computes `high_20` with a window ending at `CURRENT ROW`, so it includes the current K and violates v1.2.2.
- Slow 5m confirmation uses `<= signal_time`; the frozen plan says "signal_time 前 6 根", so the target implementation should use strictly before `signal_time`.
- `app/services/config_service.py` already reads `strategy_config`, but defaults and seed SQL still include old keys such as `ma_short`, `vol_short`, `atp_period`, and `high_low_window`.
- `sql/clickhouse_tables.sql` lacks the new KDJ/MACD/recent gain fields and `auction_volume`.
- `sql/recreate_tables.sql` lacks `market_state_daily`, `hot_topic_daily`, `stock_topic_position_daily`, `morning_confirm_daily`, and external-call cache/budget/log tables.
- Existing tests do not yet cover canonical parity, morning confirmation, external-call TTL/budget/log behavior, or report/API forbidden-token checks.

## Target File Structure

- Create `app/services/strategy2560_constants.py`
  - Holds `MissingReason`, `MorningGrade`, `AfterMarketStatus`, display mappings, and `render_missing_reason`.
- Modify `app/services/config_service.py`
  - Add v1.2.2 defaults, old-key migration, and required config validation.
- Modify `sql/recreate_tables.sql`
  - Add MySQL tables and seed new strategy config keys.
- Modify `sql/clickhouse_tables.sql`
  - Add ClickHouse indicator fields and `auction_volume`.
- Create `app/services/external_call_service.py`
  - Implements cache lookup, budget reset/check, logging, and `invalidate_cache`.
- Create `app/services/canonical_signal_engine.py`
  - Single after-market engine for module A.
- Modify `app/services/signal_engine_2560.py`
  - Wrapper around canonical engine.
- Modify `app/services/signal_engine_2560_fast.py`
  - Wrapper around canonical engine or canonical-compatible fast adapter after parity is proven.
- Modify `app/db/repository.py`
  - Add read/write methods for canonical output fields, market/topic/position tables, morning confirmation, and external-call tables where needed.
- Modify `app/services/indicator_engine.py`
  - Add KDJ, MACD, `recent_3d_pct`, `recent_5d_pct`, MA angle/slope fields.
- Create `app/services/market_state_service.py`
  - Computes `market_state_daily`.
- Create `app/services/hot_topic_service.py`
  - Computes `hot_topic_strength` and `stock_topic_position_daily`.
- Create `app/services/auction_volume_service.py`
  - Loads auction volume, computes yesterday auction and avg5.
- Create `app/services/morning_confirm_engine.py`
  - Implements module B.
- Modify `app/api/strategy2560.py`, `app/api/jobs.py`, and relevant scripts
  - Expose canonical run and morning confirmation without breaking old routes.
- Modify `app/services/daily_selection_report.py` and `app/static/*`
  - Remove internal engine names and emoji/symbol tokens from outward-facing output.

---

## Phase 0: Baseline Safety And Fixtures

**Files:**
- Create: `tests/fixtures/strategy2560_canonical/README.md`
- Create: `tests/test_strategy2560_config.py`
- Create: `tests/test_strategy2560_forbidden_output.py`

- [ ] Capture a fixed fixture design for daily, 30m, 5m, market breadth, topic, auction, and external responses.
- [ ] Add config tests proving DB values override defaults for `ma_price_period`, `auction_fallback_to_avg5`, and `avg5_min_valid_days`.
- [ ] Add tests proving deprecated keys do not drive new calculations: `ma_short`, `vol_short`, `atp_period`, `ma_mid`, `ma_long`, `slope_periods`, `high_low_window`.
- [ ] Add initial forbidden-token scan tests for public API/report output.
- [ ] Run: `pytest tests/test_strategy2560_config.py tests/test_strategy2560_forbidden_output.py -q`
- [ ] Commit: `test: add 2560 canonical baseline guards`

## Phase 1: Constants, Config, And Schema

**Files:**
- Create: `app/services/strategy2560_constants.py`
- Modify: `app/services/config_service.py`
- Modify: `sql/recreate_tables.sql`
- Modify: `sql/clickhouse_tables.sql`
- Modify: `docs/DATABASE_SCHEMA.md`
- Test: `tests/test_strategy2560_constants.py`

- [ ] Add `MissingReason` constants:
  - `NO_CANDIDATE = "no_candidate_yesterday"`
  - `FALLBACK_DISABLED = "auction_data_missing_and_fallback_disabled"`
  - `AVG5_INSUFFICIENT = "avg5_insufficient_history"`
  - `AUCTION_MISSING_NO_AVG5 = "auction_data_missing_and_avg5_unavailable"`
- [ ] Add morning grade enum values: `high`, `upgrade_high`, `normal_cautious`, `hold`, `downgrade`, `skipped`.
- [ ] Add after-market status enum values: `focus`, `watch`, `reject`.
- [ ] Add `render_missing_reason(reason)` with warning fallback for unknown values.
- [ ] Add full v1.2.2 config defaults in `ConfigService`.
- [ ] Add compatibility migration so old config rows can be reported but not used as canonical keys.
- [ ] Update `strategy_config` seeds to new keys.
- [ ] Add MySQL tables:
  - `market_state_daily`
  - `hot_topic_daily`
  - `stock_topic_position_daily`
  - `morning_confirm_daily`
  - `external_data_cache`
  - `external_call_budget`
  - `external_call_log`
- [ ] Add `chk_skipped_code` to `morning_confirm_daily`.
- [ ] Add ClickHouse columns for KDJ, MACD, MA slope/angle, recent gains, `adjust_type`.
- [ ] Add ClickHouse `auction_volume` with `avg5_auction_volume Float64`.
- [ ] Run: `pytest tests/test_strategy2560_constants.py tests/test_strategy2560_config.py -q`
- [ ] Commit: `feat: add 2560 frozen config and schema contracts`

## Phase 2: External Call Governance

**Files:**
- Create: `app/services/external_call_service.py`
- Modify: `app/db/repository.py`
- Test: `tests/test_external_call_service.py`

- [ ] Implement cache key lookup where cache hits require `ttl_hours IS NOT NULL AND ttl_hours > 0 AND expire_at > NOW()`.
- [ ] Treat `ttl_hours=NULL` as audit-only cache miss.
- [ ] Treat `ttl_hours=0` as immediately expired cache miss.
- [ ] Reject or normalize any `ttl_hours=-1` usage.
- [ ] Before each external call, reset budget when `reset_at < CURDATE()`.
- [ ] Do not increment budget on cache hits.
- [ ] Log success, error, budget exceeded, and cache miss paths.
- [ ] Implement `invalidate_cache(cache_key)` as the only active invalidation entry point; it sets `ttl_hours=0` and `expire_at=NOW()`.
- [ ] Add tests for TTL three-state behavior, cross-day budget reset, budget exceed, log creation, and invalidation.
- [ ] Run: `pytest tests/test_external_call_service.py -q`
- [ ] Commit: `feat: govern external calls with cache budget and logs`

## Phase 3: Indicator Upgrade

**Files:**
- Modify: `app/services/indicator_engine.py`
- Modify: `app/services/signal_engine_2560_fast.py`
- Modify: `scripts/rebuild_technical_indicator.py`
- Test: `tests/test_indicator_engine.py`

- [ ] Add `recent_3d_pct` and `recent_5d_pct` calculations.
- [ ] Add `classify_explode_status` with thresholds:
  - `<= 12`: `normal`
  - `> 12 and <= 18`: `warm`
  - `> 18 and <= 20`: `acceleration`
  - `> 20`: `overheat`
- [ ] Add tests using 9, 13, 19, and 21 percent examples.
- [ ] Add KDJ K/D/J, J cross-up, and J over-100 calculations.
- [ ] Add MACD DIF/DEA/hist, green-shrink, and red-extend calculations.
- [ ] Add MA25 slope days, MA25 angle, and MA5 slope direction.
- [ ] Keep `high_20` as prior-window only in pandas.
- [ ] Fix fast SQL window to exclude the current K if the fast SQL remains before wrapper removal.
- [ ] Change 5m confirmation to strictly use bars before `signal_time`.
- [ ] Run: `pytest tests/test_indicator_engine.py -q`
- [ ] Commit: `feat: add 2560 right-side indicators`

## Phase 4: Canonical After-Market Engine

**Files:**
- Create: `app/services/canonical_signal_engine.py`
- Modify: `app/services/signal_engine_2560.py`
- Modify: `app/services/signal_engine_2560_fast.py`
- Modify: `app/db/repository.py`
- Modify: `app/api/strategy2560.py`
- Modify: `scripts/progress_run_now.py`
- Test: `tests/test_canonical_signal_engine.py`
- Test: `tests/test_signal_engine_parity.py`

- [ ] Build canonical input assembly for daily, 30m, 5m, market state, hot topic, and topic position.
- [ ] Implement hard gates:
  - price distance to MA within `pullback_max_pct`
  - MA direction not clearly downward
  - 5/60 volume structure or volume-cross fallback
  - not effectively below core MA
  - `explode_status != overheat`
  - when enabled, `hot_topic_strength in {strong, medium}`
- [ ] Implement 30m pressure with current K excluded.
- [ ] Implement 5m confirmation with the six bars strictly before `signal_time`.
- [ ] Include KDJ/MACD only in scores, not hard gates.
- [ ] Implement component scores:
  - structure 30 percent
  - volume 20 percent
  - hot topic 20 percent
  - intraday 10 percent
  - pressure 10 percent
  - environment 10 percent
- [ ] Output `final_score`, status `focus/watch/reject`, and full module A fields.
- [ ] Do not mention auction or morning confirmation in module A display text.
- [ ] Convert slow and fast classes into wrappers or canonical-compatible adapters.
- [ ] Add parity tests comparing normalized business output from slow, fast, and canonical entry points.
- [ ] Run: `pytest tests/test_canonical_signal_engine.py tests/test_signal_engine_parity.py -q`
- [ ] Commit: `feat: unify 2560 selection under canonical engine`

## Phase 5: Market State, Hot Topic, And Position

**Files:**
- Create: `app/services/market_state_service.py`
- Create: `app/services/hot_topic_service.py`
- Modify: `app/services/canonical_signal_engine.py`
- Modify: `app/services/daily_selection_report.py`
- Test: `tests/test_market_state_service.py`
- Test: `tests/test_hot_topic_service.py`

- [ ] Implement `market_state` classification: `rebound`, `oscillation`, `correction`, `risk_off`.
- [ ] Persist `environment_score` in `market_state_daily`.
- [ ] Implement `hot_topic_strength`: `strong`, `medium`, `weak`, `none`.
- [ ] Implement `position_in_hot_topic`: `leader`, `strong`, `follower`, `edge`.
- [ ] Enforce `focus` requires main-line and position conditions when configured.
- [ ] Ensure announcement/research data fetches are batched, never one request per stock.
- [ ] Add boundary tests for rank 5/15 and limit-up count 5/2.
- [ ] Run: `pytest tests/test_market_state_service.py tests/test_hot_topic_service.py -q`
- [ ] Commit: `feat: add market and topic context to 2560`

## Phase 6: Auction Volume Foundation

**Files:**
- Create: `app/services/auction_volume_service.py`
- Modify: `app/db/repository.py`
- Test: `tests/test_auction_volume_service.py`

- [ ] Implement batch loading for 9:25 auction data.
- [ ] Persist current auction volume, amount, open price, previous close, and gap.
- [ ] Compute `yesterday_auction_volume` from prior auction data, not prior full-day volume.
- [ ] Compute `avg5_auction_volume` from the last five valid trading days excluding today.
- [ ] Read `auction_fallback_to_avg5` and `avg5_min_valid_days` from `strategy_config`.
- [ ] Add test where config `avg5_min_valid_days=5` and only four valid days produces insufficient history.
- [ ] Run: `pytest tests/test_auction_volume_service.py -q`
- [ ] Commit: `feat: prepare auction volume for morning confirmation`

## Phase 7: Morning Confirmation Engine

**Files:**
- Create: `app/services/morning_confirm_engine.py`
- Modify: `app/db/repository.py`
- Modify: `app/api/strategy2560.py`
- Modify: `app/api/jobs.py`
- Test: `tests/test_morning_confirm_engine.py`

- [ ] Load yesterday `focus/watch` candidates only.
- [ ] If no candidates exist, do not call any external source.
- [ ] Write one skip row with `code="__skip__"`, `morning_grade="skipped"`, and `MissingReason.NO_CANDIDATE`.
- [ ] Add code-level validation that `skipped` only pairs with `__skip__`.
- [ ] Add code-level validation that `__skip__` only pairs with `skipped`.
- [ ] Implement missing auction handling:
  - fallback disabled -> `hold`, `MissingReason.FALLBACK_DISABLED`
  - avg5 insufficient -> `hold`, `MissingReason.AVG5_INSUFFICIENT`
  - avg5 unavailable -> `hold`, `MissingReason.AUCTION_MISSING_NO_AVG5`
- [ ] Implement grade matrix:
  - focus + amplified + gap 0 to 3 -> `high`
  - focus + amplified + gap > 3 -> `normal_cautious`
  - focus + not amplified -> `hold`
  - focus + gap < -1 -> `downgrade`
  - watch + amplified + gap 0 to 3 -> `upgrade_high`
  - watch + amplified + gap > 3 -> `normal_cautious`
  - watch + not amplified -> `hold`
- [ ] Ensure `normal` is never emitted.
- [ ] Compute `pre_market_state` only as auxiliary state and never read post-9:30 data.
- [ ] Add DB-level constraint tests for illegal skipped combinations.
- [ ] Run: `pytest tests/test_morning_confirm_engine.py -q`
- [ ] Commit: `feat: add 2560 morning confirmation engine`

## Phase 8: API, Jobs, Reports, And UI Cleanup

**Files:**
- Modify: `app/api/strategy2560.py`
- Modify: `app/api/reports.py`
- Modify: `app/services/daily_selection_report.py`
- Modify: `app/services/strategy2560_service.py`
- Modify: `app/static/app.js`
- Modify: `app/static/post_workflow.js`
- Modify: `app/static/strategy2560_workflow_guide.html`
- Test: `tests/test_daily_selection_report.py`
- Test: `tests/test_strategy2560_forbidden_output.py`

- [ ] Keep existing API URLs working, but route computation to canonical services.
- [ ] Add API route or job type for morning confirmation.
- [ ] Remove outward-facing references to `fast`, `slow`, `canonical_signal_engine`, and internal class names.
- [ ] Remove emoji and disallowed symbol tokens from DB/JSON/API/report output.
- [ ] Render `morning_grade` and `missing_reason` through display mappings.
- [ ] Ensure reports do not mention auction in after-market module A output.
- [ ] Update existing report tests to assert new public wording.
- [ ] Run: `pytest tests/test_daily_selection_report.py tests/test_strategy2560_forbidden_output.py -q`
- [ ] Commit: `feat: align 2560 public reports with frozen wording`

## Phase 9: End-To-End Acceptance

**Files:**
- Create: `tests/test_2560_final_freeze_acceptance.py`
- Modify: `docs/DATABASE_SCHEMA.md`
- Modify: `docs/BUSINESS_LOGIC_2560.md`
- Modify: `README.md`

- [ ] Add an acceptance test that walks the 25-item validation checklist from the frozen plan.
- [ ] Add an end-to-end fixture run:
  - T day after-market canonical selection
  - T+1 morning confirmation
  - report/API rendering
- [ ] Verify external daily calls stay within budget and all calls have logs.
- [ ] Verify DB/API/JSON/report output has no emoji and no internal engine names.
- [ ] Verify `render_missing_reason` handles known, unknown, and null values.
- [ ] Run focused suite:
  - `pytest tests/test_indicator_engine.py tests/test_canonical_signal_engine.py tests/test_signal_engine_parity.py tests/test_morning_confirm_engine.py tests/test_external_call_service.py tests/test_2560_final_freeze_acceptance.py -q`
- [ ] Run broader suite:
  - `pytest tests -q`
- [ ] Commit: `test: verify 2560 final freeze acceptance`

---

## Compatibility Rules

- Do not remove old API endpoints during the first migration. Redirect them internally to canonical behavior.
- Treat `SignalEngine2560` and `SignalEngine2560Fast` as compatibility wrappers after Phase 4.
- Preserve `analysis_batch`, `structure_2560_analysis`, and existing report readers until the new fields are added and backfilled.
- Do not change job orchestration semantics in the same phase as algorithm parity.
- Avoid schema changes that require dropping current production tables; prefer `ADD COLUMN IF NOT EXISTS` and create new tables.
- Do not introduce any external call that bypasses `external_call_service.py`.

## High-Risk Decisions

- 5m window should be implemented as strictly before `signal_time`. Current slow code includes `<= signal_time`, but the frozen plan says "前 6 根".
- Fast SQL should either be removed as a true algorithm path or fixed before parity tests. Keeping it as a separate optimized algorithm is the highest drift risk.
- Report/UI text cleanup must be tested because existing code already exposes internal terms and symbol markers.
- DB CHECK constraints need integration coverage; unit tests alone are not enough for `chk_skipped_code`.

## Suggested Execution Strategy

Use subagent-driven development by phase:

- Agent A: config/constants/schema tests and changes.
- Agent B: external-call service and tests.
- Agent C: indicator and canonical calculation fixtures.
- Agent D: morning confirmation and auction tests.
- Agent E: API/report/UI forbidden-output cleanup.

Only run agents in parallel when their write sets are disjoint. Integrate and run focused tests after every phase before moving to the next phase.

# 2560 External Evidence Enrichment Design

Date: 2026-06-10
Status: Draft approved for planning

## Goal

Add a post-2560 external evidence layer for the daily report package. After the 2560 scan produces `focus`, `watch`, and `reject`, enrich only `focus + watch` with external market, hotspot, announcement, and stock-specific evidence. The evidence improves report explanation and risk review without changing the core 2560 technical hit calculation.

## Decisions

- Query scope defaults to `focus + watch`.
- Do not query `reject` by default.
- Keep 2560 technical selection deterministic and local-data driven.
- External evidence may affect report risk wording, priority explanation, and "暂缓/降权" notes when official risk is found.
- News or AI-search results must not directly turn a technical non-hit into a hit.
- Historical reports must use the external snapshot captured at generation time, not a later re-query.

## Data Sources

### EastMoney Hotspot

Use `EastmoneyHotspotDiscoveryService` for:

- market temperature evidence: index movement, turnover, up/down counts, limit-up count when present in returned content
- current hotspot themes
- per-candidate hotspot match: strong, weak, none, unverified
- source fields: `hotspot_source`, `hotspot_status`, `hotspot_summary`, `hotspot_items`

### cninfo Announcements

Use cninfo as the official announcement source for:

- recent official announcements
- high-risk keywords: reduce holdings, investigation, inquiry letter, regulatory letter, penalty, delisting risk, judicial freeze, pledge default
- medium-risk keywords: unlock, profit warning correction, loss, litigation, arbitration, pledge
- official sentiment summary: bullish, bearish, neutral, no announcement, unverified

cninfo results have higher trust than Miaoxiang/Miaomeng search results.

### Miaoxiang / Miaomeng

Use EastMoney AI search / Miaoxiang-Miaomeng style endpoints for:

- company fundamentals summary
- industry and theme tags
- valuation or PE description when available
- capital flow and financing facts when available
- stock diagnosis summary
- fallback announcement context only when cninfo fails or is stale

Miaoxiang results are evidence, not official disclosure.

## Relevance Rules

Miaoxiang/Miaomeng result rows must pass a strict relevance check before becoming stock-level evidence:

- Accept when title or content contains the exact stock code, six-digit code, or stock name.
- Accept official `NOTICE` rows when the row title contains the stock name or code.
- Reject rows about other companies even if they contain generic risk keywords.
- Rows that fail relevance may be kept only as market background, never as that stock's announcement risk.

This prevents false positives such as assigning another company's reduce-holding news to a candidate.

## Data Flow

```text
DailySelectionReportService.build_report()
  -> load latest 2560 candidates
  -> classify candidates into focus/watch/reject
  -> ExternalEvidenceService.enrich(focus + watch, trade_date)
      -> fetch or reuse EastMoney hotspot snapshot
      -> fetch official cninfo announcements by candidate set
      -> fetch Miaoxiang/Miaomeng stock facts by candidate set
      -> apply relevance filters
      -> normalize confidence/source/cache status
  -> attach external_evidence to report and candidates
  -> render 01-08 report package
```

## Report Fields

Add a per-candidate `external_evidence` object:

```json
{
  "hotspot_match_level": "strong|weak|none|unverified",
  "hotspot_theme": "string|null",
  "hotspot_reason": "string",
  "announcement_status": "ok|fallback|unverified|error",
  "announcement_sentiment": "bullish|bearish|neutral|none|unverified",
  "announcement_summary": "string",
  "stock_fact_summary": "string",
  "industry_theme_summary": "string",
  "valuation_summary": "string",
  "capital_flow_summary": "string",
  "evidence_sources": ["eastmoney", "cninfo", "miaoxiang"],
  "evidence_quality": "official|assisted|partial|unverified"
}
```

Add a report-level `external_context` object:

```json
{
  "market_temperature": "string",
  "index_summary": "string",
  "turnover_summary": "string",
  "breadth_summary": "string",
  "hotspot_summary": "string",
  "snapshot_time": "YYYY-MM-DD HH:MM:SS",
  "source_status": {
    "eastmoney": "ok|cache_hit|error|budget_exceeded",
    "cninfo": "ok|cache_hit|error|budget_exceeded",
    "miaoxiang": "ok|cache_hit|error|budget_exceeded"
  }
}
```

## Cache, Budget, And Logging

All external calls must go through the external call governance layer:

- cache hits do not consume budget
- static mappings cache for one week
- daily data caches for one day
- real-time/intraday evidence may be audit-only with `ttl_hours=NULL`
- active invalidation uses `invalidate_cache(cache_key)`
- all calls log status, provider, cache key, error message, and metadata

Suggested cache keys:

- `eastmoney:hotspot:{trade_date}`
- `cninfo:announcements:{trade_date}:{code_hash}`
- `miaoxiang:stock-facts:{trade_date}:{code}`

## Failure Behavior

- External failures must not block 2560 report generation.
- Timeout or budget exhaustion produces `unverified` evidence with source status.
- If cninfo fails but Miaoxiang has relevant rows, report it as assisted evidence and mark source as fallback.
- If EastMoney hotspot is unavailable, preserve existing technical report and mark hotspot evidence as unverified.

## Tests

Add focused tests for:

- only `focus + watch` are sent to external enrichment
- `reject` candidates are not queried
- cninfo official announcement risk overrides Miaoxiang generic news
- Miaoxiang rows about other companies are filtered out
- failed external calls do not fail report generation
- cache hit avoids provider call and budget increment
- report output includes source/status fields
- historical report generation uses stored snapshot data instead of re-querying

## Open Implementation Notes

- `DailySelectionReportService` is already large; implement a separate `ExternalEvidenceService` rather than expanding rendering functions.
- Rendering should consume normalized fields only.
- The current `CninfoAnnouncementRiskService` still supports per-code calls behind an environment flag. The target design should prefer batch candidate-set calls and preserve the existing "no full-market per-code loop" rule.
- The first implementation can enrich the report JSON/Markdown and defer UI work.

from __future__ import annotations

import os
import re
from datetime import datetime
from hashlib import sha1
from typing import Any, Callable

import httpx


MIAOXIANG_SEARCH_NEWS_URL = "https://ai-saas.eastmoney.com/proxy/b/mcp/tool/searchNews"
DEFAULT_STOCK_FACT_SUMMARY = "外部事实未验证"


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\x00", "").strip()
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text.lower() in {"null", "none"} else text


def _six_digit_code(code: str | None) -> str:
    match = re.search(r"(\d{6})", str(code or ""))
    return match.group(1) if match else ""


def is_relevant_stock_fact(code: str | None, name: str | None, row: dict[str, Any]) -> bool:
    stock_name = _clean_text(name)
    compact_code = _six_digit_code(code)
    text = _clean_text(f"{row.get('title') or ''} {row.get('content') or ''} {row.get('summary') or ''}")
    if not text:
        return False
    if stock_name and stock_name in text:
        return True
    if compact_code and compact_code in re.sub(r"\D", "", text):
        return True
    full_code = str(code or "").strip()
    return bool(full_code and full_code in text)


def _first_sentence(text: str, limit: int = 96) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    sentence = re.split(r"[。；;]\s*", cleaned, maxsplit=1)[0]
    if len(sentence) > limit:
        return sentence[:limit].rstrip() + "..."
    return sentence


def _rows_matching_terms(rows: list[dict[str, Any]], terms: tuple[str, ...]) -> str:
    for row in rows:
        text = _clean_text(f"{row.get('title') or ''} {row.get('content') or ''}")
        if any(term in text for term in terms):
            return _first_sentence(text)
    return "-"


def normalize_stock_facts(code: str | None, name: str | None, rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    relevant = [row for row in rows or [] if isinstance(row, dict) and is_relevant_stock_fact(code, name, row)]
    titles = []
    for row in relevant[:3]:
        title = _clean_text(row.get("title"))
        content = _first_sentence(row.get("content") or "")
        if title:
            titles.append(title)
        elif content:
            titles.append(content)
    return {
        "stock_fact_summary": "；".join(titles) if titles else DEFAULT_STOCK_FACT_SUMMARY,
        "industry_theme_summary": _rows_matching_terms(relevant, ("行业", "题材", "概念", "板块")),
        "valuation_summary": _rows_matching_terms(relevant, ("估值", "PE", "市盈率", "市净率")),
        "capital_flow_summary": _rows_matching_terms(relevant, ("主力资金", "资金净", "融资", "融券", "净流入", "净流出")),
        "relevant_fact_count": len(relevant),
    }


class MiaoxiangStockFactClient:
    def __init__(self, api_key: str | None = None, timeout: float = 8.0):
        self.api_key = (api_key if api_key is not None else os.getenv("EM_API_KEY", "")).strip()
        self.timeout = timeout

    def facts_for_candidates(self, candidates: list[dict[str, Any]], trade_date: str | None) -> dict[str, list[dict[str, Any]]]:
        if not self.api_key:
            return {str(item.get("code")): [] for item in candidates if item.get("code")}
        out: dict[str, list[dict[str, Any]]] = {}
        headers = {"Content-Type": "application/json", "em_api_key": self.api_key}
        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            for item in candidates:
                code = str(item.get("code") or "")
                if not code:
                    continue
                name = _clean_text(item.get("name"))
                query = f"{code} {name} {trade_date or ''} 基本面 PE 行业 题材 个股诊断 资金流 最新风险 公告"
                response = client.post(MIAOXIANG_SEARCH_NEWS_URL, json={"query": query, "toolContext": {}})
                response.raise_for_status()
                payload = response.json()
                rows = (((payload.get("data") or {}).get("llmSearchResponse") or {}).get("data") or [])
                out[code] = [row for row in rows if isinstance(row, dict)]
        return out


class ExternalEvidenceService:
    def __init__(
        self,
        *,
        db: Any | None = None,
        hotspot_client: Any | None = None,
        announcement_client: Any | None = None,
        stock_fact_client: Any | None = None,
        external_call_service: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.db = db
        self.hotspot_client = hotspot_client or self._default_hotspot_client()
        self.announcement_client = announcement_client or self._default_announcement_client()
        self.stock_fact_client = stock_fact_client or MiaoxiangStockFactClient()
        self.external_call_service = external_call_service or self._default_external_call_service(db)
        self.clock = clock or datetime.now

    def enrich(self, candidates: list[dict[str, Any]], trade_date: str | None = None) -> dict[str, Any]:
        rows = [dict(item) for item in candidates if item.get("code")]
        query_rows = [item for item in rows if self._should_query_candidate(item)]
        query_codes = [str(item.get("code")) for item in query_rows]
        source_status = {"eastmoney": "unverified", "cninfo": "unverified", "miaoxiang": "unverified"}

        hotspot_snapshot, source_status["eastmoney"] = self._fetch_hotspot_snapshot(trade_date)
        announcement_risks, source_status["cninfo"] = self._fetch_announcement_risks(query_codes, trade_date)
        stock_fact_rows, source_status["miaoxiang"] = self._fetch_stock_facts(query_rows, trade_date)

        candidate_evidence: dict[str, dict[str, Any]] = {}
        query_codes_set = set(query_codes)
        for item in rows:
            code = str(item.get("code") or "")
            if code not in query_codes_set:
                candidate_evidence[code] = self._not_queried_evidence()
                continue
            candidate_evidence[code] = self._candidate_evidence(
                item=item,
                hotspot_snapshot=hotspot_snapshot,
                announcement=announcement_risks.get(code) or {},
                stock_fact_rows=stock_fact_rows.get(code) or [],
                source_status=source_status,
            )

        return {
            "external_context": self._external_context(hotspot_snapshot, source_status),
            "candidate_evidence": candidate_evidence,
        }

    @staticmethod
    def _should_query_candidate(item: dict[str, Any]) -> bool:
        status = str(item.get("selection_status") or "").lower()
        if status in {"focus", "watch"}:
            return True
        return str(item.get("bucket") or "") in {"可执行", "观察"}

    def _fetch_hotspot_snapshot(self, trade_date: str | None) -> tuple[dict[str, Any], str]:
        question = (
            f"{trade_date} A股市场热点主线是什么？请列出热点板块、代表股票和驱动原因。"
            if trade_date
            else None
        )
        return self._call(
            provider="eastmoney",
            cache_key=f"eastmoney:hotspot:{trade_date or 'latest'}",
            ttl_hours=24,
            fetcher=lambda: self.hotspot_client.snapshot(question),
            default={},
        )

    def _fetch_announcement_risks(self, codes: list[str], trade_date: str | None) -> tuple[dict[str, Any], str]:
        if not codes:
            return {}, "skipped"
        code_hash = sha1(",".join(codes).encode("utf-8")).hexdigest()[:12]
        return self._call(
            provider="cninfo",
            cache_key=f"cninfo:announcements:{trade_date or 'latest'}:{code_hash}",
            ttl_hours=24,
            fetcher=lambda: self.announcement_client.risks_for_codes(codes, review_trade_date=trade_date),
            default={},
        )

    def _fetch_stock_facts(
        self, candidates: list[dict[str, Any]], trade_date: str | None
    ) -> tuple[dict[str, list[dict[str, Any]]], str]:
        if not candidates:
            return {}, "skipped"
        code_hash = sha1(",".join(str(x.get("code")) for x in candidates).encode("utf-8")).hexdigest()[:12]
        return self._call(
            provider="miaoxiang",
            cache_key=f"miaoxiang:stock-facts:{trade_date or 'latest'}:{code_hash}",
            ttl_hours=24,
            fetcher=lambda: self.stock_fact_client.facts_for_candidates(candidates, trade_date),
            default={},
        )

    def _call(
        self,
        *,
        provider: str,
        cache_key: str,
        ttl_hours: int | None,
        fetcher: Callable[[], Any],
        default: Any,
    ) -> tuple[Any, str]:
        if self.external_call_service is not None:
            result = self.external_call_service.call(
                provider=provider,
                cache_key=cache_key,
                ttl_hours=ttl_hours,
                daily_limit=10,
                fetcher=fetcher,
            )
            if result.status in {"success", "cache_hit"}:
                return result.data, "cache_hit" if result.from_cache else "ok"
            return default, result.status or "error"
        try:
            return fetcher(), "ok"
        except Exception:
            return default, "error"

    def _candidate_evidence(
        self,
        *,
        item: dict[str, Any],
        hotspot_snapshot: dict[str, Any],
        announcement: dict[str, Any],
        stock_fact_rows: list[dict[str, Any]],
        source_status: dict[str, str],
    ) -> dict[str, Any]:
        hotspot = self._hotspot_match(item, hotspot_snapshot)
        facts = normalize_stock_facts(item.get("code"), item.get("name"), stock_fact_rows)
        announcement_summary = str(
            announcement.get("latest_announcement_summary")
            or announcement.get("announcement_risk_summary")
            or "公告未验证"
        )
        evidence = {
            "hotspot_match_level": hotspot["level"],
            "hotspot_theme": hotspot.get("theme"),
            "hotspot_reason": hotspot.get("reason") or "-",
            "announcement_status": str(announcement.get("announcement_query_status") or "unverified"),
            "announcement_sentiment": self._normalize_sentiment(announcement.get("announcement_sentiment")),
            "announcement_summary": announcement_summary,
            "announcement_source": str(announcement.get("latest_announcement_source") or "cninfo"),
            "stock_fact_summary": facts["stock_fact_summary"],
            "industry_theme_summary": facts["industry_theme_summary"],
            "valuation_summary": facts["valuation_summary"],
            "capital_flow_summary": facts["capital_flow_summary"],
            "evidence_sources": ["eastmoney", "cninfo", "miaoxiang"],
            "evidence_quality": self._evidence_quality(source_status, facts["relevant_fact_count"]),
        }
        return evidence

    @staticmethod
    def _not_queried_evidence() -> dict[str, Any]:
        return {
            "hotspot_match_level": "not_queried",
            "hotspot_theme": None,
            "hotspot_reason": "reject候选默认不查询外部证据",
            "announcement_status": "not_queried",
            "announcement_sentiment": "not_queried",
            "announcement_summary": "未查询",
            "announcement_source": "-",
            "stock_fact_summary": "未查询",
            "industry_theme_summary": "-",
            "valuation_summary": "-",
            "capital_flow_summary": "-",
            "evidence_sources": [],
            "evidence_quality": "not_queried",
        }

    @staticmethod
    def _hotspot_match(item: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        if not snapshot or snapshot.get("hotspot_status") != "available":
            return {"level": "unverified", "theme": None, "reason": "热点主线未验证"}
        try:
            from app.services.market_hotspot_service import match_candidate_to_hotspots

            match = match_candidate_to_hotspots(item, snapshot)
        except Exception:
            match = _fallback_hotspot_match(item, snapshot)
        return {
            "level": _normalize_hotspot_level(match.get("hotspot_match_level")),
            "theme": match.get("hotspot_theme") or match.get("hotspot_direction"),
            "reason": match.get("hotspot_match_summary") or match.get("hotspot_match_reason") or "-",
        }

    @staticmethod
    def _normalize_sentiment(value: Any) -> str:
        text = str(value or "")
        if "利空" in text:
            return "bearish"
        if "利好" in text:
            return "bullish"
        if "中性" in text:
            return "neutral"
        if "无公告" in text:
            return "none"
        if "未验证" in text:
            return "unverified"
        return text or "unverified"

    @staticmethod
    def _evidence_quality(source_status: dict[str, str], fact_count: int) -> str:
        if source_status.get("cninfo") in {"ok", "cache_hit"}:
            return "official"
        if fact_count:
            return "assisted"
        if any(status in {"ok", "cache_hit"} for status in source_status.values()):
            return "partial"
        return "unverified"

    def _external_context(self, hotspot_snapshot: dict[str, Any], source_status: dict[str, str]) -> dict[str, Any]:
        content = _clean_text(hotspot_snapshot.get("hotspot_content"))
        return {
            "market_temperature": _first_sentence(content) if content else "外部市场温度未验证",
            "index_summary": _rows_text_or_default(content, ("沪指", "深成指", "创业板指", "科创50"), "指数表现未验证"),
            "turnover_summary": _rows_text_or_default(content, ("成交", "成交额"), "成交额未验证"),
            "breadth_summary": _rows_text_or_default(content, ("上涨", "下跌", "涨停"), "涨跌家数未验证"),
            "hotspot_summary": hotspot_snapshot.get("hotspot_summary") or "热点主线未验证",
            "snapshot_time": self.clock().strftime("%Y-%m-%d %H:%M:%S"),
            "source_status": dict(source_status),
        }

    @staticmethod
    def _default_hotspot_client() -> Any:
        try:
            from app.services.market_hotspot_service import EastmoneyHotspotDiscoveryService

            return EastmoneyHotspotDiscoveryService()
        except Exception:
            return _UnavailableClient("eastmoney hotspot client unavailable")

    @staticmethod
    def _default_announcement_client() -> Any:
        try:
            from app.services.announcement_risk_service import CninfoAnnouncementRiskService

            return CninfoAnnouncementRiskService()
        except Exception:
            return _UnavailableClient("announcement client unavailable")

    @staticmethod
    def _default_external_call_service(db: Any | None) -> Any | None:
        if db is None:
            return None
        try:
            from app.db.repository import KlineRepository
            from app.services.external_call_service import ExternalCallService

            return ExternalCallService(KlineRepository(db))
        except Exception:
            return None


class _UnavailableClient:
    def __init__(self, message: str):
        self.message = message

    def snapshot(self, question: str | None = None):
        raise RuntimeError(self.message)

    def risks_for_codes(self, codes, review_trade_date=None):
        raise RuntimeError(self.message)

    def facts_for_candidates(self, candidates, trade_date):
        raise RuntimeError(self.message)


def _normalize_hotspot_level(value: Any) -> str:
    text = str(value or "")
    if text in {"strong", "weak", "none", "unverified", "not_queried"}:
        return text
    if "强" in text:
        return "strong"
    if "弱" in text:
        return "weak"
    if "未验证" in text:
        return "unverified"
    if "未匹配" in text or "none" in text.lower():
        return "none"
    return "unverified"


def _fallback_hotspot_match(item: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    code = str(item.get("code") or "")
    name = _clean_text(item.get("name"))
    for hotspot in snapshot.get("hotspot_items") or []:
        if code and hotspot.get("code") == code:
            return {
                "hotspot_match_level": "strong",
                "hotspot_theme": hotspot.get("theme"),
                "hotspot_match_summary": f"热点强匹配：{hotspot.get('theme') or '-'}",
            }
        if name and hotspot.get("name") == name:
            return {
                "hotspot_match_level": "strong",
                "hotspot_theme": hotspot.get("theme"),
                "hotspot_match_summary": f"热点强匹配：{hotspot.get('theme') or '-'}",
            }
    return {"hotspot_match_level": "none", "hotspot_theme": None, "hotspot_match_summary": "未匹配今日热点主线"}


def _rows_text_or_default(content: str, terms: tuple[str, ...], default: str) -> str:
    if not content:
        return default
    for sentence in re.split(r"[。\n；;]", content):
        if any(term in sentence for term in terms):
            return _first_sentence(sentence)
    return default

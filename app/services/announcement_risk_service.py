from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import os
from typing import Any

import httpx


CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC_BASE = "https://static.cninfo.com.cn/"
MIAOXIANG_SEARCH_NEWS_URL = "https://ai-saas.eastmoney.com/proxy/b/mcp/tool/searchNews"

HIGH_RISK_KEYWORDS = ("减持", "立案", "监管函", "问询函", "处罚", "退市风险", "司法冻结", "质押违约")
MEDIUM_RISK_KEYWORDS = ("解禁", "业绩预告修正", "亏损", "诉讼", "仲裁", "股份质押")
BULLISH_KEYWORDS = ("增持", "回购", "提前终止减持", "终止减持", "未减持", "中标", "重大合同", "投产", "签订合同")
BEARISH_KEYWORDS = HIGH_RISK_KEYWORDS + MEDIUM_RISK_KEYWORDS


def _unverified_result(code: str, error: Any | None = None) -> dict[str, Any]:
    result = {
        "code": code,
        "announcement_risk_level": "unverified",
        "announcement_risk_summary": "公告联网受限，暂未验证",
        "announcement_risk_items": [],
        "announcement_risk_source": "cninfo",
        "announcement_sentiment": "未验证",
        "latest_announcement_summary": "公告联网受限，暂未验证",
        "latest_announcement_items": [],
        "latest_announcement_source": "cninfo",
        "announcement_query_status": "error",
    }
    if error is not None:
        result["announcement_risk_error"] = str(error)
        result["latest_announcement_error"] = str(error)
    return result


def _announcement_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        n = int(value)
        if n > 10_000_000_000:
            return datetime.fromtimestamp(n / 1000).strftime("%Y-%m-%d")
        if n > 10_000_000:
            return datetime.fromtimestamp(n).strftime("%Y-%m-%d")
    except Exception:
        pass
    return str(value)[:10]


def _announcement_url(item: dict[str, Any]) -> str | None:
    url = item.get("adjunctUrl") or item.get("announcementUrl")
    if not url:
        return None
    url = str(url)
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return CNINFO_STATIC_BASE + url.lstrip("/")


def _sentiment_for_title(title: str) -> tuple[str, list[str], str]:
    bullish_hits = [kw for kw in BULLISH_KEYWORDS if kw in title]
    bearish_hits = [kw for kw in BEARISH_KEYWORDS if kw in title]
    if any(kw in title for kw in ("提前终止减持", "终止减持", "未减持")):
        return "利好", bullish_hits, "none"
    if bullish_hits and not any(kw in title for kw in ("拟减持", "计划减持")):
        return "利好", bullish_hits, "none"
    high_hits = [kw for kw in HIGH_RISK_KEYWORDS if kw in title]
    if high_hits:
        return "利空", high_hits, "high"
    medium_hits = [kw for kw in MEDIUM_RISK_KEYWORDS if kw in title]
    if medium_hits:
        return "利空", medium_hits, "medium"
    if bullish_hits:
        return "利好", bullish_hits, "none"
    return "中性", [], "none"


def classify_latest_announcement(code: str, announcements: list[dict[str, Any]], source: str = "cninfo") -> dict[str, Any]:
    items = []
    highest = "none"
    for item in announcements:
        title = str(item.get("announcementTitle") or item.get("title") or "")
        if not title:
            continue
        sentiment, hits, level = _sentiment_for_title(title)

        if level == "high":
            highest = "high"
        elif level == "medium" and highest != "high":
            highest = "medium"
        items.append({
            "title": title,
            "date": _announcement_date(item.get("announcementTime") or item.get("date")),
            "url": _announcement_url(item),
            "risk_level": level,
            "risk_keywords": hits,
            "sentiment": sentiment,
            "sentiment_keywords": hits,
        })

    if not items:
        return {
            "code": code,
            "announcement_risk_level": "none",
            "announcement_risk_summary": "无公告风险命中",
            "announcement_risk_items": [],
            "announcement_risk_source": "cninfo",
            "announcement_sentiment": "无公告",
            "latest_announcement_summary": "近期无公告",
            "latest_announcement_items": [],
            "latest_announcement_source": source,
            "announcement_query_status": "ok",
        }

    latest_item = sorted(items, key=lambda x: str(x.get("date") or ""), reverse=True)[0]
    keywords = []
    for item in items:
        for kw in item["risk_keywords"]:
            if kw not in keywords:
                keywords.append(kw)
    risk_summary = "无公告风险命中" if highest == "none" else "公告风险：" + " / ".join(keywords)
    return {
        "code": code,
        "announcement_risk_level": highest,
        "announcement_risk_summary": risk_summary,
        "announcement_risk_items": items,
        "announcement_risk_source": source,
        "announcement_sentiment": latest_item["sentiment"],
        "latest_announcement_summary": f"最新公告：{latest_item['sentiment']}｜{latest_item['title']}",
        "latest_announcement_items": items,
        "latest_announcement_source": source,
        "announcement_query_status": "ok",
    }


def classify_announcement_risk(code: str, announcements: list[dict[str, Any]]) -> dict[str, Any]:
    return classify_latest_announcement(code, announcements)


def parse_miaoxiang_search_news(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    response = data.get("llmSearchResponse") if isinstance(data, dict) else None
    rows = response.get("data") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        return []

    announcements = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        information_type = str(row.get("informationType") or "")
        title = str(row.get("title") or "")
        if information_type != "NOTICE" and "公告" not in title:
            continue
        announcements.append({
            "announcementTitle": title,
            "announcementTime": row.get("date"),
            "announcementUrl": row.get("jumpUrl"),
            "content": row.get("content"),
            "source": row.get("source") or "东方财富",
            "informationType": information_type,
        })
    return announcements


class CninfoAnnouncementRiskService:
    def __init__(self, timeout: float = 3.0, max_workers: int = 6, api_key: str | None = None):
        self.timeout = timeout
        self.max_workers = max_workers
        self.api_key = (api_key if api_key is not None else os.environ.get("EM_API_KEY", "")).strip()

    def risks_for_codes(
        self,
        codes: list[str],
        review_trade_date: str | None = None,
        lookback_days: int = 7,
    ) -> dict[str, dict[str, Any]]:
        unique_codes = list(dict.fromkeys(codes))
        if not unique_codes:
            return {}
        if os.getenv("ANNOUNCEMENT_ALLOW_PER_CODE_CALLS", "0").strip().lower() not in {"1", "true", "yes", "y"}:
            return {
                code: _unverified_result(code, "per-code announcement calls disabled; batch provider required")
                for code in unique_codes
            }
        end = self._parse_date(review_trade_date) or datetime.now()
        start = end - timedelta(days=lookback_days)
        start_s = start.strftime("%Y-%m-%d")
        end_s = end.strftime("%Y-%m-%d")
        out: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(unique_codes))) as pool:
            futures = {pool.submit(self.risk_for_code, code, start_s, end_s): code for code in unique_codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    out[code] = future.result()
                except Exception as exc:
                    out[code] = _unverified_result(code, exc)
        return out

    def risk_for_code(self, code: str, start_date: str, end_date: str) -> dict[str, Any]:
        cninfo_error = None
        try:
            announcements = self._query_cninfo(code, start_date, end_date)
        except Exception as exc:
            cninfo_error = exc
            announcements = []

        if announcements:
            return classify_latest_announcement(code, announcements, source="cninfo")

        fallback_announcements = []
        try:
            fallback_announcements = self._query_miaoxiang(code, start_date, end_date)
        except Exception:
            fallback_announcements = []
        if fallback_announcements:
            result = classify_latest_announcement(code, fallback_announcements, source="miaoxiang")
            result["announcement_query_status"] = "fallback"
            if cninfo_error is not None:
                result["cninfo_error"] = str(cninfo_error)
            return result

        if cninfo_error is not None:
            return _unverified_result(code, cninfo_error)
        return classify_latest_announcement(code, [], source="cninfo")

    def _query_cninfo(self, code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        market_code = code.split(".")[-1]
        column = "sse" if code.startswith("sh.") else "szse"
        data = {
            "pageNum": "1",
            "pageSize": "30",
            "column": column,
            "tabName": "fulltext",
            "plate": "",
            "stock": market_code,
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{start_date}~{end_date}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
        }
        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            response = client.post(CNINFO_QUERY_URL, data=data)
            response.raise_for_status()
            payload = response.json()
        return list(payload.get("announcements") or [])

    def _query_miaoxiang(self, code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        query = f"{code} {start_date} 至 {end_date} 最新公告 减持 立案 问询函 增持 回购"
        payload = {"query": query, "toolContext": {}}
        headers = {
            "Content-Type": "application/json",
            "em_api_key": self.api_key,
        }
        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            response = client.post(MIAOXIANG_SEARCH_NEWS_URL, json=payload)
            response.raise_for_status()
            data = response.json()
        return parse_miaoxiang_search_news(data if isinstance(data, dict) else {})

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d")
        except Exception:
            return None

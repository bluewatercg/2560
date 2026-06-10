from __future__ import annotations

import os
import re
from typing import Any

import httpx


HOTSPOT_DISCOVERY_URL = (
    "https://ai-saas.eastmoney.com/proxy/"
    "app-robo-advisor-api/assistant/hotspot-discovery"
)
DEFAULT_HOTSPOT_QUESTION = "今日A股热点主线及题材"
STOP_THEME_WORDS = {"行业板块", "板块", "概念股", "个股", "股票", "A股", "三大指数"}


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\x00", "").strip()
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text.lower() == "null" or text == "-":
        return ""
    return text


def _normalize_stock_code(raw: str) -> str | None:
    code = re.sub(r"\D", "", raw or "")
    if len(code) != 6:
        return None
    if code.startswith(("60", "68", "90")):
        return f"sh.{code}"
    if code.startswith(("00", "30", "20")):
        return f"sz.{code}"
    if code.startswith(("43", "83", "87", "92")):
        return f"bj.{code}"
    return code


def _theme_from_hotspot(text: str) -> str:
    first_line = re.split(r"<br\s*/?>", str(text or ""), maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned = _clean_text(first_line)
    if not cleaned:
        return "-"
    first = re.split(r"[。；;]", cleaned, maxsplit=1)[0].strip()
    return first or cleaned


def _extract_industry_themes_from_news(title: str, content: str) -> list[str]:
    text = _clean_text(f"{title}。{content}")
    candidates: list[str] = []
    patterns = [
        r"([\u4e00-\u9fa5A-Za-z0-9、]+?)板块涨幅居前",
        r"([\u4e00-\u9fa5A-Za-z0-9、]+?)板块表现活跃",
        r"([\u4e00-\u9fa5A-Za-z0-9、]+?)概念股表现活跃",
        r"([\u4e00-\u9fa5A-Za-z0-9、]+?)概念股逆市大涨",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            segment = match.group(1)
            if "，" in segment:
                segment = segment.split("，")[-1]
            for part in re.split(r"[、,，/ ]+", segment):
                part = _clean_text(part)
                part = re.sub(r"(板块|概念股|行业)$", "", part)
                if not part or part in STOP_THEME_WORDS:
                    continue
                if 2 <= len(part) <= 12 and part not in candidates:
                    candidates.append(part)
    return candidates


def _extract_content(raw: dict[str, Any]) -> str:
    if not isinstance(raw, dict):
        return ""
    data = raw.get("data")
    if isinstance(data, dict):
        display_data = data.get("displayData")
        if isinstance(display_data, str) and display_data.strip():
            return display_data.strip()
        if isinstance(display_data, (list, dict)):
            return str(display_data)
        for key in ("content", "answer", "summary"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("displayData", "content", "answer", "summary"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def parse_hotspot_display_data(display_data: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    headers: list[str] = []
    for line in (display_data or "").splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [x.strip() for x in line.strip("|").split("|")]
        if "热度排名" in line:
            headers = cells
            continue
        if len(cells) < 4:
            continue
        try:
            rank = int(re.sub(r"\D", "", cells[0]))
        except Exception:
            continue

        if "资讯标题" in headers and "资讯内容" in headers:
            title = _clean_text(cells[1])
            content = _clean_text(cells[2])
            themes = _extract_industry_themes_from_news(title, content)
            for idx, theme in enumerate(themes):
                items.append({
                    "rank": rank + idx,
                    "code": None,
                    "name": "",
                    "theme": theme,
                    "related_hotspot": f"{title}：{content}",
                    "source_type": "news",
                })
            continue

        stock_text = _clean_text(cells[1])
        match = re.search(r"(.+?)\((\d{6})\)", stock_text)
        if match:
            name = _clean_text(match.group(1))
            code = _normalize_stock_code(match.group(2))
        else:
            name = stock_text
            code = None

        theme = _theme_from_hotspot(cells[3])
        related_hotspot = _clean_text(cells[3])
        items.append({
            "rank": rank,
            "code": code,
            "name": name,
            "theme": theme,
            "related_hotspot": related_hotspot,
            "source_type": "stock",
        })
    return items


def build_hotspot_snapshot(raw: dict[str, Any] | None, source: str = "eastmoney") -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _unverified_snapshot(source=source)
    code = raw.get("code")
    status = raw.get("status")
    if (code is not None and code != 200) or (isinstance(status, int) and status < 0):
        return _unverified_snapshot(source=source)

    content = _extract_content(raw)
    items = parse_hotspot_display_data(content)
    if not items:
        themes = _extract_industry_themes_from_news("", content)
        items = [
            {
                "rank": idx + 1,
                "code": None,
                "name": "",
                "theme": theme,
                "related_hotspot": _clean_text(content),
                "source_type": "news_fallback",
            }
            for idx, theme in enumerate(themes)
        ]
    if not items:
        return _unverified_snapshot(source=source)

    themes = []
    for item in items:
        theme = item.get("theme")
        if theme and theme != "-" and theme not in themes:
            themes.append(theme)
    return {
        "hotspot_status": "available",
        "hotspot_source": source,
        "hotspot_summary": " / ".join(themes[:5]) if themes else "热点主线已获取",
        "hotspot_content": content,
        "hotspot_items": items,
    }


def _unverified_snapshot(source: str = "eastmoney", error: Any | None = None) -> dict[str, Any]:
    result = {
        "hotspot_status": "unverified",
        "hotspot_source": source,
        "hotspot_summary": "热点主线未验证",
        "hotspot_items": [],
    }
    if error is not None:
        result["hotspot_error"] = str(error)
    return result


def match_candidate_to_hotspots(candidate: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    if not snapshot or snapshot.get("hotspot_status") != "available":
        return {
            "hotspot_match_level": "未验证",
            "hotspot_match_summary": "热点主线未验证",
            "hotspot_theme": None,
            "hotspot_rank": None,
        }

    code = str(candidate.get("code") or "")
    name = _clean_text(candidate.get("name"))
    industry = _clean_text(candidate.get("industry_name"))
    board = _clean_text(candidate.get("board_name"))
    items = snapshot.get("hotspot_items") or []

    for item in items:
        if code and item.get("code") == code:
            theme = item.get("theme") or "-"
            return {
                "hotspot_match_level": "强匹配",
                "hotspot_match_summary": f"热点强匹配：{theme}",
                "hotspot_theme": theme,
                "hotspot_rank": item.get("rank"),
            }
        if name and item.get("name") == name:
            theme = item.get("theme") or "-"
            return {
                "hotspot_match_level": "强匹配",
                "hotspot_match_summary": f"热点强匹配：{theme}",
                "hotspot_theme": theme,
                "hotspot_rank": item.get("rank"),
            }

    weak_terms = [x for x in (industry, board) if x]
    for item in items:
        text = _clean_text(f"{item.get('theme') or ''} {item.get('related_hotspot') or ''}")
        if any(term and term in text for term in weak_terms):
            theme = item.get("theme") or "-"
            return {
                "hotspot_match_level": "弱匹配",
                "hotspot_match_summary": f"热点弱匹配：{theme}",
                "hotspot_theme": theme,
                "hotspot_rank": item.get("rank"),
            }

    return {
        "hotspot_match_level": "未匹配",
        "hotspot_match_summary": "未匹配今日热点主线",
        "hotspot_theme": None,
        "hotspot_rank": None,
    }


class EastmoneyHotspotDiscoveryService:
    def __init__(self, api_key: str | None = None, timeout: float = 5.0):
        self.api_key = (api_key if api_key is not None else os.environ.get("EM_API_KEY", "")).strip()
        self.timeout = timeout

    def snapshot(self, question: str | None = None) -> dict[str, Any]:
        if not self.api_key:
            return _unverified_snapshot()
        primary_question = question or DEFAULT_HOTSPOT_QUESTION
        try:
            raw = self._query(primary_question)
            snapshot = build_hotspot_snapshot(raw)
            if snapshot.get("hotspot_status") == "available" or primary_question == DEFAULT_HOTSPOT_QUESTION:
                return snapshot
            fallback_raw = self._query(DEFAULT_HOTSPOT_QUESTION)
            return build_hotspot_snapshot(fallback_raw)
        except Exception as exc:
            return _unverified_snapshot(error=exc)

    def _query(self, question: str) -> dict[str, Any]:
        payload = {"question": question}
        headers = {
            "Content-Type": "application/json",
            "em_api_key": self.api_key,
        }
        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            response = client.post(HOTSPOT_DISCOVERY_URL, json=payload)
            response.raise_for_status()
            data = response.json()
        return data if isinstance(data, dict) else {"data": data}

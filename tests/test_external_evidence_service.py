from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "app/services/external_evidence_service.py"
SPEC = importlib.util.spec_from_file_location("external_evidence_service", MODULE_PATH)
external_evidence_service = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(external_evidence_service)

ExternalEvidenceService = external_evidence_service.ExternalEvidenceService
normalize_stock_facts = external_evidence_service.normalize_stock_facts


class FakeHotspotClient:
    def __init__(self, *, raises: Exception | None = None):
        self.raises = raises
        self.questions = []

    def snapshot(self, question: str | None = None):
        self.questions.append(question)
        if self.raises is not None:
            raise self.raises
        return {
            "hotspot_status": "available",
            "hotspot_source": "eastmoney",
            "hotspot_summary": "机器人 / 算力",
            "hotspot_items": [
                {
                    "rank": 1,
                    "code": "sh.600000",
                    "name": "焦点A",
                    "theme": "机器人",
                    "related_hotspot": "机器人板块表现活跃",
                }
            ],
        }


class FakeAnnouncementClient:
    def __init__(self):
        self.queried_codes = []

    def risks_for_codes(self, codes, review_trade_date=None):
        self.queried_codes = list(codes)
        return {
            "sh.600000": {
                "announcement_query_status": "ok",
                "announcement_sentiment": "利空",
                "latest_announcement_summary": "最新公告：利空｜焦点A股东拟减持",
                "latest_announcement_source": "cninfo",
                "announcement_risk_level": "high",
            },
            "sz.300000": {
                "announcement_query_status": "ok",
                "announcement_sentiment": "无公告",
                "latest_announcement_summary": "近期无公告",
                "latest_announcement_source": "cninfo",
                "announcement_risk_level": "none",
            },
        }


class FakeStockFactClient:
    def __init__(self):
        self.queried_codes = []

    def facts_for_candidates(self, candidates, trade_date):
        self.queried_codes = [item.get("code") for item in candidates]
        return {
            "sh.600000": [
                {"title": "焦点A：主力资金净流入", "content": "焦点A 600000 主力资金净流入"},
                {"title": "其他公司：拟减持", "content": "其他公司公告"},
            ],
            "sz.300000": [
                {"title": "观察B：行业为通信设备", "content": "观察B 300000 行业题材通信设备"},
            ],
        }


def make_service(*, hotspot_client=None):
    return ExternalEvidenceService(
        hotspot_client=hotspot_client or FakeHotspotClient(),
        announcement_client=FakeAnnouncementClient(),
        stock_fact_client=FakeStockFactClient(),
    )


def test_enrich_queries_only_focus_and_watch_candidates():
    candidates = [
        {"code": "sh.600000", "name": "焦点A", "selection_status": "focus"},
        {"code": "sz.300000", "name": "观察B", "selection_status": "watch"},
        {"code": "sh.600001", "name": "淘汰C", "selection_status": "reject"},
    ]

    service = make_service()
    result = service.enrich(candidates, trade_date="2026-06-10")

    assert service.announcement_client.queried_codes == ["sh.600000", "sz.300000"]
    assert service.stock_fact_client.queried_codes == ["sh.600000", "sz.300000"]
    assert result["candidate_evidence"]["sh.600001"]["evidence_quality"] == "not_queried"
    assert result["candidate_evidence"]["sh.600000"]["announcement_summary"] == "最新公告：利空｜焦点A股东拟减持"
    assert result["candidate_evidence"]["sh.600000"]["hotspot_match_level"] == "strong"


def test_miaoxiang_rows_about_other_companies_are_filtered_out():
    rows = [
        {"title": "方正证券：股东拟减持", "content": "方正证券公告"},
        {"title": "金明精机：董事减持", "content": "金明精机 300281 董事减持"},
    ]

    evidence = normalize_stock_facts("sz.300281", "金明精机", rows)

    assert "方正证券" not in evidence["stock_fact_summary"]
    assert "金明精机" in evidence["stock_fact_summary"]


def test_hotspot_failure_does_not_block_candidate_evidence():
    candidates = [{"code": "sh.600000", "name": "焦点A", "selection_status": "focus"}]
    service = make_service(hotspot_client=FakeHotspotClient(raises=RuntimeError("network down")))

    result = service.enrich(candidates, trade_date="2026-06-10")

    assert result["external_context"]["source_status"]["eastmoney"] == "error"
    assert result["candidate_evidence"]["sh.600000"]["hotspot_match_level"] == "unverified"
    assert result["candidate_evidence"]["sh.600000"]["announcement_summary"] == "最新公告：利空｜焦点A股东拟减持"

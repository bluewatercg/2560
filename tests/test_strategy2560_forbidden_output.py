from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_TERMS = [
    "fast",
    "slow",
    "canonical_signal_engine",
    "SignalEngine2560Fast",
    "内部算法",
]
FORBIDDEN_SYMBOLS = ["✓", "✗", "⚠", "▶", "○", "🔥", "✅", "❌"]


def _install_import_stubs() -> None:
    sqlalchemy = types.ModuleType("sqlalchemy")

    class _Text(str):
        def bindparams(self, *args, **kwargs):
            return self

    sqlalchemy.text = lambda value: _Text(value)
    sqlalchemy.bindparam = lambda *args, **kwargs: object()
    sqlalchemy_orm = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm.Session = object
    sys.modules.setdefault("sqlalchemy", sqlalchemy)
    sys.modules.setdefault("sqlalchemy.orm", sqlalchemy_orm)

    app = types.ModuleType("app")
    app.__path__ = []
    core = types.ModuleType("app.core")
    core.__path__ = []
    db = types.ModuleType("app.db")
    db.__path__ = []
    services = types.ModuleType("app.services")
    services.__path__ = []
    sys.modules.setdefault("app", app)
    sys.modules.setdefault("app.core", core)
    sys.modules.setdefault("app.db", db)
    sys.modules.setdefault("app.services", services)

    market_scope = types.ModuleType("app.core.market_scope")
    market_scope.market_sql_where = lambda *args, **kwargs: "1=1"
    sys.modules.setdefault("app.core.market_scope", market_scope)

    clickhouse = types.ModuleType("app.db.clickhouse")
    clickhouse.get_clickhouse = lambda: types.SimpleNamespace(query=lambda *args, **kwargs: [])
    sys.modules.setdefault("app.db.clickhouse", clickhouse)

    announcement = types.ModuleType("app.services.announcement_risk_service")
    announcement.CninfoAnnouncementRiskService = object
    sys.modules.setdefault("app.services.announcement_risk_service", announcement)

    annotation = types.ModuleType("app.services.annotation_engine_2568")
    annotation.AnnotationEngine2568 = object
    sys.modules.setdefault("app.services.annotation_engine_2568", annotation)

    external_evidence = types.ModuleType("app.services.external_evidence_service")

    class ExternalEvidenceService:
        def __init__(self, *args, **kwargs):
            pass

        def enrich(self, *args, **kwargs):
            return {"candidate_evidence": {}, "external_context": {}}

    external_evidence.ExternalEvidenceService = ExternalEvidenceService
    sys.modules.setdefault("app.services.external_evidence_service", external_evidence)

    hotspot = types.ModuleType("app.services.market_hotspot_service")
    hotspot.DEFAULT_HOTSPOT_QUESTION = "test"
    hotspot.EastmoneyHotspotDiscoveryService = object
    hotspot.match_candidate_to_hotspots = lambda item, snapshot: {}
    sys.modules.setdefault("app.services.market_hotspot_service", hotspot)


def _load_report_module():
    _install_import_stubs()
    spec = importlib.util.spec_from_file_location(
        "daily_selection_report_under_test",
        PROJECT_ROOT / "app/services/daily_selection_report.py",
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _forbidden_hits(text: str) -> list[str]:
    return [item for item in FORBIDDEN_TERMS + FORBIDDEN_SYMBOLS if item in text]


def test_daily_selection_report_outputs_do_not_leak_internal_names_or_symbols():
    report_module = _load_report_module()

    class DummyDailySelectionReportService(report_module.DailySelectionReportService):
        def __init__(self):
            pass

        def _latest_batch(self):
            return {"batch_id": "canonical_signal_engine", "run_time": datetime(2026, 6, 8, 18, 0, 0)}

        def _latest_selected_signals(self, latest_batch, limit):
            return [
                {
                    "code": "sh.600000",
                    "name": "fast slow 内部算法 ✓",
                    "price": 10.5,
                    "structure_status": "SignalEngine2560Fast ▶",
                    "missing_tags": '["⚠"]',
                    "industry_name": "canonical_signal_engine",
                    "board_name": "slow ○",
                }
            ]

        def _annotations_for_codes(self, codes):
            return {
                "sh.600000": {
                    "manual_action_label": "canonical_signal_engine ✅",
                    "highlight_level": "SignalEngine2560Fast",
                    "highlight_summary": "内部算法",
                    "risk_tags": "🔥",
                    "ma25_direction": "向上",
                    "close": 10.5,
                    "ma25": 10,
                    "vol_ma5": 1500,
                    "vol_ma60": 1000,
                    "vol_ma5_gt_vol_ma60": True,
                    "price_ma25_deviation_pct": 1.1,
                }
            }

        def _daily_volume_profiles(self, codes):
            return {
                "sh.600000": {
                    "buy_point_type": "二类做量",
                    "volume_compression_label": "slow ○",
                    "current_volume_ratio_5": 0.8,
                }
            }

        def _data_validation(self, latest_batch, market_model):
            return {
                "confidence": "中",
                "latest_batch_id": "SignalEngine2560Fast",
                "verified_items": ["canonical_signal_engine", "fast", "✓"],
                "unverified_items": ["内部算法", "slow", "❌"],
                "data_scope": "内部算法 ⚠",
            }

        def _volume_pullback_candidates(self, limit):
            return [
                {
                    "code": "sz.300000",
                    "name": "SignalEngine2560Fast",
                    "close": 20.5,
                    "price_ma25_deviation_pct": 0.7,
                    "pressure_pattern": "fast slow ▶",
                    "volume_ratio": 0.6,
                    "recent_3day_gain_pct": 2.2,
                    "recent_3day_trend": "震荡上行",
                    "burst_filter_status": "通过 ✅",
                    "buy_point_type": "缩量回踩25日线",
                }
            ]

        def _announcement_risks_for_codes(self, codes, review_trade_date):
            return {
                code: {
                    "announcement_risk_level": "high",
                    "latest_announcement_summary": "canonical_signal_engine ⚠",
                    "announcement_sentiment": "内部算法",
                    "announcement_risk_items": [],
                }
                for code in codes
            }

        def _market_hotspot_snapshot(self, review_trade_date):
            return {
                "hotspot_status": "available",
                "hotspot_summary": "fast slow 🔥",
                "hotspot_items": [
                    {
                        "rank": 1,
                        "code": "sh.600000",
                        "name": "内部算法",
                        "theme": "SignalEngine2560Fast",
                        "related_hotspot": "canonical_signal_engine",
                    }
                ],
            }

    report = DummyDailySelectionReportService().build_report(limit=5)
    outputs = {
        "markdown": report["markdown"],
        "html": report_module.render_html_report(report),
        "json": json.dumps(report, ensure_ascii=False, sort_keys=True),
    }

    leaks = {name: _forbidden_hits(text) for name, text in outputs.items() if _forbidden_hits(text)}

    assert leaks == {}

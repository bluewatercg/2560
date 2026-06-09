from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


def _load_service_module():
    saved = {
        name: sys.modules.get(name)
        for name in [
            "app",
            "app.db",
            "app.db.clickhouse",
            "app.services",
            "app.services.config_service",
            "app.services.strategy2560_constants",
            "app.services.morning_confirm_engine",
            "app.services.morning_confirm_report",
        ]
    }
    app = types.ModuleType("app")
    app.__path__ = []
    db = types.ModuleType("app.db")
    db.__path__ = []
    services = types.ModuleType("app.services")
    services.__path__ = []
    clickhouse = types.ModuleType("app.db.clickhouse")
    clickhouse.get_clickhouse = lambda: None
    config_service = types.ModuleType("app.services.config_service")

    class _ConfigService:
        def __init__(self, db):
            self.db = db

        def load_strategy_config(self, strategy_code: str = "S2560"):
            return {}

    config_service.ConfigService = _ConfigService

    sys.modules["app"] = app
    sys.modules["app.db"] = db
    sys.modules["app.db.clickhouse"] = clickhouse
    sys.modules["app.services"] = services
    sys.modules["app.services.config_service"] = config_service

    try:
        _load_module("app.services.strategy2560_constants", "app/services/strategy2560_constants.py")
        _load_module("app.services.morning_confirm_engine", "app/services/morning_confirm_engine.py")
        _load_module("app.services.morning_confirm_report", "app/services/morning_confirm_report.py")
        return _load_module(
            "app.services.morning_report_package_service",
            "app/services/morning_report_package_service.py",
        )
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


morning_report_package_service = _load_service_module()
MorningReportPackageService = morning_report_package_service.MorningReportPackageService


class _FakeClickHouse:
    def query(self, query: str, fmt: str = "JSONEachRow"):
        if "FROM auction_volume" not in query:
            return []
        return [
            {
                "code": "sh.600000",
                "trade_date": "2026-06-10",
                "auction_volume": 1200,
                "yesterday_auction_volume": 1000,
                "avg5_auction_volume": 950,
                "auction_amplify_ratio": 1.2,
                "open_gap_pct": 2.1,
                "auction_open_price": 10.21,
                "prev_close": 10.0,
            }
        ]


class _FakeConfigService:
    def __init__(self, db):
        self.db = db

    def load_strategy_config(self, strategy_code: str = "S2560"):
        return {
            "auction_amplify_ratio": 1.0,
            "auction_fallback_to_avg5": True,
            "avg5_min_valid_days": 3,
        }


def test_morning_report_package_service_generates_09_and_10_from_previous_package(
    tmp_path: Path,
    monkeypatch,
):
    source_dir = tmp_path / "2026-06-09"
    source_dir.mkdir(parents=True)
    (source_dir / "05_focus_watch_list.json").write_text(
        """
        {
          "trade_date": "2026-06-09",
          "items": [
            {"code": "sh.600000", "name": "浦发银行", "selection_status": "focus"},
            {"code": "sz.000001", "name": "平安银行", "selection_status": "watch"}
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(morning_report_package_service, "get_clickhouse", lambda: _FakeClickHouse())
    monkeypatch.setattr(morning_report_package_service, "ConfigService", _FakeConfigService)

    result = MorningReportPackageService(db=object(), output_root=tmp_path).generate_morning_package(
        trade_date="2026-06-10",
        source_trade_date="2026-06-09",
    )

    target_dir = tmp_path / "2026-06-10"
    assert result["trade_date"] == "2026-06-10"
    assert result["source_trade_date"] == "2026-06-09"
    assert result["status"] == "generated"
    assert [path.name for path in sorted(target_dir.iterdir())] == [
        "09_morning_confirm.md",
        "10_skill_morning_input.md",
    ]

    confirm = (target_dir / "09_morning_confirm.md").read_text(encoding="utf-8")
    skill = (target_dir / "10_skill_morning_input.md").read_text(encoding="utf-8")

    assert "# 2560 早盘确认报告" in confirm
    assert "sh.600000 | 浦发银行 | focus | high" in confirm
    assert "sz.000001 | 平安银行 | watch | hold" in confirm
    assert "# 2560 早盘 Skill 输入报告" in skill
    assert "- high: sh.600000 浦发银行" in skill
    assert "- hold: sz.000001 平安银行" in skill

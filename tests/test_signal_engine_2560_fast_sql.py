import importlib.util
import sys
import types
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FakeRepository:
    def __init__(self, _db):
        pass


class _FakeConfigService:
    def __init__(self, _db):
        pass


class _FakeClickHouse:
    def query_one(self, _sql):
        return {"d": "2026-06-09"}

    def query(self, _sql):
        return []


def _install_fast_engine_stubs():
    for name in [
        "pymysql",
        "pymysql.err",
        "sqlalchemy",
        "sqlalchemy.exc",
        "sqlalchemy.orm",
        "app",
        "app.core",
        "app.core.market_scope",
        "app.db",
        "app.db.clickhouse",
        "app.db.repository",
        "app.services",
        "app.services.config_service",
        "app.services.tag_service",
    ]:
        sys.modules[name] = types.ModuleType(name)

    sys.modules["pymysql.err"].OperationalError = RuntimeError
    sys.modules["sqlalchemy.exc"].OperationalError = RuntimeError
    sys.modules["sqlalchemy"].bindparam = lambda *args, **kwargs: None
    sys.modules["sqlalchemy"].text = lambda value: value
    sys.modules["sqlalchemy.orm"].Session = object
    sys.modules["app.core.market_scope"].market_sql_where = lambda column, market: f"{column} LIKE '{market}%'"
    sys.modules["app.db.clickhouse"].get_clickhouse = lambda: _FakeClickHouse()
    sys.modules["app.db.repository"].KlineRepository = _FakeRepository
    sys.modules["app.services.config_service"].ConfigService = _FakeConfigService
    sys.modules["app.services.tag_service"].build_tags = lambda *args, **kwargs: []
    sys.modules["app.services.tag_service"].explain_text = lambda *args, **kwargs: ""
    sys.modules["app.services.tag_service"].structure_status = lambda *args, **kwargs: ""
    canonical = types.ModuleType("app.services.canonical_signal_engine")
    canonical.build_canonical_fields_from_legacy_signal = lambda row, indicator, context, cfg: {
        "selection_status": "focus",
        "final_score": 0.88,
    }
    canonical.legacy_volume_structure_ok = lambda indicator, cfg, base_ratio=1.0: (
        float(indicator.get("vol_ratio") or 0.0) >= float(base_ratio)
        or (
            bool(cfg.get("volume_cross_fallback_enabled", True))
            and bool(indicator.get("vol_ma5_cross_vol_ma60"))
            and float(indicator.get("vol_ratio") or 0.0) >= float(cfg.get("volume_cross_confirm_ratio", 0.9))
        )
    )
    sys.modules["app.services.canonical_signal_engine"] = canonical


def _load_fast_engine():
    names = [
        "pymysql",
        "pymysql.err",
        "sqlalchemy",
        "sqlalchemy.exc",
        "sqlalchemy.orm",
        "app",
        "app.core",
        "app.core.market_scope",
        "app.db",
        "app.db.clickhouse",
        "app.db.repository",
        "app.services",
        "app.services.config_service",
        "app.services.tag_service",
        "app.services.canonical_signal_engine",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    _install_fast_engine_stubs()
    try:
        spec = importlib.util.spec_from_file_location(
            "signal_engine_2560_fast_under_test",
            PROJECT_ROOT / "app/services/signal_engine_2560_fast.py",
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module.SignalEngine2560Fast
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_fast_sql_high_20_window_excludes_current_k():
    SignalEngine2560Fast = _load_fast_engine()
    sql = SignalEngine2560Fast(db=None)._candidate_sql(
        "sh60",
        "2026-06-09",
        {
            "pullback_threshold_pct": 5.0,
            "min_volume_ratio": 1.0,
            "ma_slope_medium_threshold": 0.0,
            "atr_weak_ratio": 0.85,
            "breakout_threshold": 1.0,
            "resistance_threshold": 0.95,
        },
        None,
    )

    assert "w20 AS (PARTITION BY code ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)" in sql


def test_fast_analysis_row_includes_canonical_fields():
    SignalEngine2560Fast = _load_fast_engine()
    row = SignalEngine2560Fast(db=None)._analysis_row(
        2026060901,
        {},
        {"sh.600000": "样例"},
        {
            "code": "sh.600000",
            "signal_time": "2026-06-09 10:00:00",
            "price": 10.5,
            "source": "clickhouse_fast",
            "price_near_ma25": True,
            "ma25_slope_ok": True,
            "volume_structure_ok": True,
            "abnormal_filter_ok": True,
            "trend_price_ok": True,
            "trend_slope_ok": True,
            "volatility_ok": True,
            "breakout_ok": True,
            "volume_ok": True,
            "near_resistance": False,
            "pullback_ok": True,
            "bullish_confirm": True,
        },
    )

    assert row["selection_status"] == "focus"
    assert row["final_score"] == 0.88


def test_fast_signal_window_confirmation_uses_only_bars_before_signal_time():
    SignalEngine2560Fast = _load_fast_engine()
    engine = SignalEngine2560Fast(db=None)
    rows = [
        {
            "code": "sh.600000",
            "signal_time": "2026-06-09 10:00:00",
            "pullback_ok": True,
            "bullish_confirm": True,
        }
    ]
    minute_rows = [
        {
            "code": "sh.600000",
            "date": "2026-06-09 09:50:00",
            "open": 10.00,
            "close": 9.99,
            "ma25": 10.00,
            "price_ma25_deviation_pct": 0.1,
        },
        {
            "code": "sh.600000",
            "date": "2026-06-09 09:55:00",
            "open": 10.01,
            "close": 10.00,
            "ma25": 10.00,
            "price_ma25_deviation_pct": 0.1,
        },
        {
            "code": "sh.600000",
            "date": "2026-06-09 10:00:00",
            "open": 10.00,
            "close": 10.30,
            "ma25": 10.00,
            "price_ma25_deviation_pct": 0.1,
        },
    ]

    engine._apply_signal_window_confirmation(
        rows,
        minute_rows,
        {
            "confirm_5m_bars": 2,
            "pullback_threshold_pct": 5.0,
        },
    )

    assert rows[0]["pullback_ok"] is True
    assert rows[0]["bullish_confirm"] is False


def test_fast_sql_volume_gate_uses_cross_fallback_in_where_clause():
    SignalEngine2560Fast = _load_fast_engine()
    sql = SignalEngine2560Fast(db=None)._candidate_sql(
        "sh60",
        "2026-06-09",
        {
            "pullback_threshold_pct": 5.0,
            "min_volume_ratio": 1.0,
            "volume_cross_confirm_ratio": 0.9,
            "ma_slope_medium_threshold": 0.0,
            "atr_weak_ratio": 0.85,
            "breakout_threshold": 1.0,
            "resistance_threshold": 0.95,
        },
        None,
    )

    assert "m.vol_ma5_cross_vol_ma60" in sql
    assert "AND (m.vol_ratio >= 1.0 OR (m.vol_ma5_cross_vol_ma60 = 1 AND m.vol_ratio >= 0.9))" in sql


def test_load_signal_window_rows_quotes_codes_without_name_error(monkeypatch):
    SignalEngine2560Fast = _load_fast_engine()
    captured = {}

    class _QuoteCaptureClickHouse:
        def query(self, sql):
            captured["sql"] = sql
            return []

    monkeypatch.setitem(
        SignalEngine2560Fast._load_signal_window_rows.__globals__,
        "get_clickhouse",
        lambda: _QuoteCaptureClickHouse(),
    )

    rows = SignalEngine2560Fast(db=None)._load_signal_window_rows(
        ["sh.600000", "sz.000001"],
        "2026-06-09",
    )

    assert rows == []
    assert "m.code IN ('sh.600000','sz.000001')" in captured["sql"]

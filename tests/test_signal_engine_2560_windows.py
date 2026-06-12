import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _install_signal_engine_stubs():
    app = types.ModuleType("app")
    db = types.ModuleType("app.db")
    repository = types.ModuleType("app.db.repository")
    services = types.ModuleType("app.services")
    config_service = types.ModuleType("app.services.config_service")
    indicator_engine = types.ModuleType("app.services.indicator_engine")
    tag_service = types.ModuleType("app.services.tag_service")
    canonical_signal_engine = types.ModuleType("app.services.canonical_signal_engine")

    class KlineRepository:
        def __init__(self, _db):
            pass

    class ConfigService:
        def __init__(self, _db):
            pass

    repository.KlineRepository = KlineRepository
    config_service.ConfigService = ConfigService
    indicator_engine.enrich_indicators = lambda *args, **kwargs: None
    indicator_engine.to_indicator_rows = lambda *args, **kwargs: []
    tag_service.build_tags = lambda *args, **kwargs: []
    tag_service.structure_status = lambda *args, **kwargs: ""
    tag_service.explain_text = lambda *args, **kwargs: ""
    canonical_signal_engine.build_canonical_fields_from_legacy_signal = lambda *args, **kwargs: {
        "selection_status": "focus",
        "final_score": 0.91,
    }
    canonical_signal_engine.legacy_volume_structure_ok = lambda indicator, cfg, base_ratio=1.0: (
        float(indicator.get("vol_ratio") or 0.0) >= float(base_ratio)
        or (
            bool(cfg.get("volume_cross_fallback_enabled", True))
            and bool(indicator.get("vol_ma5_cross_vol_ma60"))
            and float(indicator.get("vol_ratio") or 0.0) >= float(cfg.get("volume_cross_confirm_ratio", 0.9))
        )
    )

    sys.modules["app"] = app
    sys.modules["app.db"] = db
    sys.modules["app.db.repository"] = repository
    sys.modules["app.services"] = services
    sys.modules["app.services.config_service"] = config_service
    sys.modules["app.services.indicator_engine"] = indicator_engine
    sys.modules["app.services.tag_service"] = tag_service
    sys.modules["app.services.canonical_signal_engine"] = canonical_signal_engine


def _load_signal_engine():
    names = [
        "app",
        "app.db",
        "app.db.repository",
        "app.services",
        "app.services.config_service",
        "app.services.indicator_engine",
        "app.services.tag_service",
        "app.services.canonical_signal_engine",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    _install_signal_engine_stubs()
    try:
        spec = importlib.util.spec_from_file_location(
            "signal_engine_2560_under_test",
            PROJECT_ROOT / "app/services/signal_engine_2560.py",
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module.SignalEngine2560
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_confirm5_uses_six_bars_strictly_before_signal_time():
    SignalEngine2560 = _load_signal_engine()
    engine = SignalEngine2560(db=None)
    signal_time = 20260609100000
    rows = []
    for idx, minute in enumerate([925, 930, 935, 940, 945, 950]):
        close = 10.0 + idx * 0.01
        rows.append(
            {
                "date": int(f"20260609{minute:04d}00"),
                "open": close,
                "close": close - 0.01,
                "ma25": 10.0,
                "price_ma25_deviation_pct": 0.5,
            }
        )
    rows.append(
        {
            "date": signal_time,
            "open": 10.0,
            "close": 11.0,
            "ma25": 10.0,
            "price_ma25_deviation_pct": 0.5,
        }
    )

    pullback, bullish = engine.confirm5(pd.DataFrame(rows), signal_time, {"confirm_5m_bars": 6})

    assert pullback is True
    assert bullish is False


def test_scan_passes_canonical_fields_to_repository():
    SignalEngine2560 = _load_signal_engine()
    engine = SignalEngine2560(db=None)
    captured = {}

    class Repo:
        def upsert_analysis(self, row):
            captured.update(row)
            return 1

        def replace_tags(self, *args, **kwargs):
            return None

    engine.repo = Repo()
    daily_i = pd.DataFrame(
        [
            {
                "date": 20260608,
                "close": 10.0,
                "ma60": 9.0,
                "ma25": 9.5,
                "ma60_slope_3": 1.0,
                "ma25_slope_3": 1.0,
                "atr14": 1.0,
                "atr20_avg": 1.0,
            }
        ]
    )
    m30_i = pd.DataFrame(
        [
            {
                "date": 20260609100000,
                "close": 10.5,
                "ma25": 10.0,
                "vol_ma60": 1000,
                "price_ma25_deviation_pct": 1.0,
                "ma25_slope_3": 1.0,
                "vol_ratio": 1.2,
                "vol_ma5_cross_vol_ma60": 0,
                "is_abnormal_bar": 0,
                "high_20": 10.2,
                "source": "test",
            }
        ]
    )
    m5_i = pd.DataFrame(
        [
            {
                "date": 20260609095500,
                "open": 10.2,
                "close": 10.3,
                "ma25": 10.0,
                "price_ma25_deviation_pct": 1.0,
            }
        ]
    )

    count = engine.scan(
        "sh.600000",
        {"name": "样例"},
        daily_i,
        m30_i,
        m5_i,
        {"pullback_threshold_pct": 5.0, "min_volume_ratio": 1.0, "ma_slope_medium_threshold": 0.0},
        2026060901,
        "test",
    )

    assert count == 1
    assert captured["selection_status"] == "focus"
    assert captured["final_score"] == 0.91

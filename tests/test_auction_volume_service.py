from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


compute_avg5_auction_volume = _load_module(
    "auction_volume_service_under_test",
    "app/services/auction_volume_service.py",
).compute_avg5_auction_volume


def _auction_row(trade_date: int, volume: float | None) -> dict:
    return {"trade_date": trade_date, "auction_volume": volume}


def test_avg5_auction_volume_uses_recent_five_valid_days_excluding_today():
    result = compute_avg5_auction_volume(
        [
            _auction_row(20260601, 100),
            _auction_row(20260602, 200),
            _auction_row(20260603, None),
            _auction_row(20260604, 400),
            _auction_row(20260605, 500),
            _auction_row(20260606, 600),
            _auction_row(20260607, 700),
            _auction_row(20260608, 9999),
        ],
        current_trade_date=20260608,
        cfg={"avg5_min_valid_days": 3},
    )

    assert result.avg5_auction_volume == 480.0
    assert result.valid_days == 5
    assert result.insufficient_history is False


def test_avg5_min_valid_days_comes_from_config_not_hardcoded_three():
    result = compute_avg5_auction_volume(
        [
            _auction_row(20260602, 200),
            _auction_row(20260603, 300),
            _auction_row(20260604, 400),
            _auction_row(20260605, 500),
        ],
        current_trade_date=20260608,
        cfg={"avg5_min_valid_days": 5},
    )

    assert result.avg5_auction_volume == 350.0
    assert result.valid_days == 4
    assert result.required_valid_days == 5
    assert result.insufficient_history is True


def test_avg5_auction_volume_reports_unavailable_when_no_valid_history():
    result = compute_avg5_auction_volume(
        [
            _auction_row(20260606, 0),
            _auction_row(20260607, None),
            _auction_row(20260608, 1000),
        ],
        current_trade_date=20260608,
        cfg={"avg5_min_valid_days": 3},
    )

    assert result.avg5_auction_volume is None
    assert result.valid_days == 0
    assert result.unavailable is True

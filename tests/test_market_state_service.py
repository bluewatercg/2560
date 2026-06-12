import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "app/services/market_state_service.py"
SPEC = importlib.util.spec_from_file_location("market_state_service", MODULE_PATH)
market_state_service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(market_state_service)

classify_market_state = market_state_service.classify_market_state
environment_score = market_state_service.environment_score
market_state_snapshot = market_state_service.market_state_snapshot


def test_classify_market_state_marks_rebound_only_when_all_rebound_conditions_hold():
    assert classify_market_state(index_pct=0.5, limit_up_count=30, up_ratio=0.6) == "rebound"
    assert classify_market_state(index_pct=0.7, limit_up_count=29, up_ratio=0.7) == "oscillation"
    assert classify_market_state(index_pct=0.7, limit_up_count=35, up_ratio=0.59) == "oscillation"


def test_classify_market_state_marks_risk_off_when_index_falls_more_than_one_point_five_percent():
    assert classify_market_state(index_pct=-1.51, limit_up_count=40, up_ratio=0.8) == "risk_off"
    assert classify_market_state(index_pct=-1.5, limit_up_count=5, up_ratio=0.2) == "correction"


def test_classify_market_state_marks_oscillation_for_flat_or_mildly_positive_breadth():
    assert classify_market_state(index_pct=0.49, limit_up_count=30, up_ratio=0.6) == "oscillation"
    assert classify_market_state(index_pct=-0.3, limit_up_count=18, up_ratio=0.48) == "oscillation"


def test_classify_market_state_marks_correction_for_weak_non_panic_market():
    assert classify_market_state(index_pct=-0.6, limit_up_count=12, up_ratio=0.3) == "correction"
    assert classify_market_state(index_pct=0.1, limit_up_count=8, up_ratio=0.24) == "correction"


def test_environment_score_maps_market_state_to_phase5_scores():
    assert environment_score("rebound") == 1.0
    assert environment_score("oscillation") == 0.7
    assert environment_score("correction") == 0.4
    assert environment_score("risk_off") == 0.1
    assert environment_score("unknown") == 0.4


def test_market_state_snapshot_returns_state_score_and_inputs():
    result = market_state_snapshot(index_pct=0.62, limit_up_count=42, up_ratio=0.68)

    assert result == {
        "market_state": "rebound",
        "environment_score": 1.0,
        "index_pct": 0.62,
        "limit_up_count": 42,
        "up_ratio": 0.68,
    }

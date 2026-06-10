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


canonical = _load_module(
    "canonical_signal_engine_under_test",
    "app/services/canonical_signal_engine.py",
)


def _cfg(**overrides):
    base = {
        "pullback_max_pct": 5.0,
        "volume_cross_fallback_enabled": True,
        "volume_cross_confirm_ratio": 0.9,
        "hot_topic_required": True,
        "hot_topic_strength_required": "medium",
        "position_required_for_focus": "strong",
        "focus_score_min": 0.75,
        "watch_score_min": 0.45,
    }
    base.update(overrides)
    return base


def _metrics(**overrides):
    base = {
        "price_ma_deviation_pct": 2.0,
        "ma_direction": "up",
        "volume_ratio": 1.1,
        "volume_crossed": False,
        "below_core_ma": False,
        "explode_status": "normal",
        "hot_topic_strength": "strong",
        "position_in_hot_topic": "strong",
        "structure_score": 0.9,
        "volume_score": 0.8,
        "hot_topic_score": 0.8,
        "intraday_score": 0.7,
        "pressure_score": 0.6,
        "environment_score": 1.0,
    }
    base.update(overrides)
    return base


def test_compute_final_score_uses_frozen_weights():
    score = canonical.compute_final_score(
        {
            "structure_score": 1.0,
            "volume_score": 0.5,
            "hot_topic_score": 0.5,
            "intraday_score": 0.0,
            "pressure_score": 1.0,
            "environment_score": 1.0,
        }
    )

    assert score == 0.7


def test_overheat_candidate_is_rejected_even_when_other_scores_are_good():
    result = canonical.evaluate_after_market_signal(
        _metrics(explode_status="overheat"),
        _cfg(),
    )

    assert result["status"] == "reject"
    assert "explode_overheat" in result["reject_reasons"]


def test_volume_cross_fallback_allows_volume_ratio_below_one():
    result = canonical.evaluate_after_market_signal(
        _metrics(volume_ratio=0.92, volume_crossed=True),
        _cfg(volume_cross_confirm_ratio=0.9),
    )

    assert "volume_structure" not in result["reject_reasons"]
    assert result["status"] == "focus"


def test_hot_topic_required_rejects_weak_topic():
    result = canonical.evaluate_after_market_signal(
        _metrics(hot_topic_strength="weak"),
        _cfg(hot_topic_required=True),
    )

    assert result["status"] == "reject"
    assert "hot_topic_strength" in result["reject_reasons"]


def test_focus_requires_configured_topic_position():
    result = canonical.evaluate_after_market_signal(
        _metrics(position_in_hot_topic="follower"),
        _cfg(position_required_for_focus="strong"),
    )

    assert result["status"] == "watch"
    assert "position_for_focus" in result["watch_reasons"]


def test_candidate_with_passing_gates_and_score_becomes_focus():
    result = canonical.evaluate_after_market_signal(_metrics(), _cfg())

    assert result["status"] == "focus"
    assert result["final_score"] == canonical.compute_final_score(_metrics())


def test_build_canonical_fields_from_legacy_signal_maps_required_output_fields():
    row = {
        "price_near_ma25": 1,
        "ma25_slope_ok": 1,
        "volume_structure_ok": 1,
        "pullback_ok": 1,
        "bullish_confirm": 1,
        "near_resistance": 0,
        "breakout_ok": 1,
    }
    indicator = {
        "price_ma25_deviation_pct": 1.2,
        "vol_ratio": 1.3,
        "vol_ma5_cross_vol_ma60": 0,
        "recent_3d_pct": 9.0,
    }
    context = {
        "market_state": "rebound",
        "environment_score": 1.0,
        "hot_topic_strength": "strong",
        "position_in_hot_topic": "leader",
    }

    fields = canonical.build_canonical_fields_from_legacy_signal(
        row,
        indicator,
        context,
        _cfg(),
    )

    assert fields["selection_status"] == "focus"
    assert fields["final_score"] > 0.75
    assert fields["recent_3d_pct"] == 9.0
    assert fields["explode_status"] == "normal"
    assert fields["market_state"] == "rebound"
    assert fields["hot_topic_strength"] == "strong"
    assert fields["position_in_hot_topic"] == "leader"
    assert fields["structure_score"] == 1.0

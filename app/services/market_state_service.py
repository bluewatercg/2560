from __future__ import annotations

from typing import Any


MARKET_STATE_SCORES = {
    "rebound": 1.0,
    "oscillation": 0.7,
    "correction": 0.4,
    "risk_off": 0.1,
}


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def classify_market_state(index_pct: Any, limit_up_count: Any, up_ratio: Any) -> str:
    index_pct_value = _to_float(index_pct)
    limit_up_count_value = _to_int(limit_up_count)
    up_ratio_value = _to_float(up_ratio)

    if index_pct_value < -1.5:
        return "risk_off"
    if (
        index_pct_value >= 0.5
        and limit_up_count_value >= 30
        and up_ratio_value >= 0.6
    ):
        return "rebound"
    if index_pct_value <= -0.5 and up_ratio_value <= 0.45:
        return "correction"
    if up_ratio_value < 0.35 or limit_up_count_value < 10:
        return "correction"
    return "oscillation"


def environment_score(market_state: str) -> float:
    return MARKET_STATE_SCORES.get(market_state, MARKET_STATE_SCORES["correction"])


def market_state_snapshot(index_pct: Any, limit_up_count: Any, up_ratio: Any) -> dict[str, Any]:
    state = classify_market_state(index_pct, limit_up_count, up_ratio)
    return {
        "market_state": state,
        "environment_score": environment_score(state),
        "index_pct": index_pct,
        "limit_up_count": limit_up_count,
        "up_ratio": up_ratio,
    }

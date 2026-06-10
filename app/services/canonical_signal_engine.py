from __future__ import annotations

from typing import Any


SCORE_WEIGHTS = {
    "structure_score": 0.30,
    "volume_score": 0.20,
    "hot_topic_score": 0.20,
    "intraday_score": 0.10,
    "pressure_score": 0.10,
    "environment_score": 0.10,
}

HOT_TOPIC_RANK = {
    "none": 0,
    "weak": 1,
    "medium": 2,
    "strong": 3,
}

POSITION_RANK = {
    "edge": 0,
    "follower": 1,
    "strong": 2,
    "leader": 3,
}


def compute_final_score(metrics: dict[str, Any]) -> float:
    score = 0.0
    for key, weight in SCORE_WEIGHTS.items():
        score += _float(metrics.get(key), 0.0) * weight
    return round(score, 4)


def evaluate_after_market_signal(metrics: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    reject_reasons = _hard_gate_failures(metrics, cfg)
    final_score = compute_final_score(metrics)
    watch_reasons: list[str] = []

    if reject_reasons:
        status = "reject"
    elif not _position_satisfies_focus(metrics.get("position_in_hot_topic"), cfg.get("position_required_for_focus", "strong")):
        status = "watch"
        watch_reasons.append("position_for_focus")
    elif final_score >= _float(cfg.get("focus_score_min"), 0.75):
        status = "focus"
    elif final_score >= _float(cfg.get("watch_score_min"), 0.45):
        status = "watch"
    else:
        status = "reject"
        reject_reasons.append("final_score")

    return {
        "status": status,
        "final_score": final_score,
        "reject_reasons": reject_reasons,
        "watch_reasons": watch_reasons,
    }


def build_canonical_fields_from_legacy_signal(
    row: dict[str, Any],
    indicator: dict[str, Any],
    context: dict[str, Any] | None,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    context = context or {}
    recent_3d_pct = _float(indicator.get("recent_3d_pct"), 0.0)
    explode_status = classify_explode_status(recent_3d_pct, cfg)
    structure_score = _average_flags(
        row,
        ["price_near_ma25", "ma25_slope_ok", "pullback_ok", "bullish_confirm"],
    )
    volume_score = 1.0 if bool(row.get("volume_structure_ok")) else 0.0
    hot_topic_strength = str(context.get("hot_topic_strength", "none"))
    position = str(context.get("position_in_hot_topic", "edge"))
    hot_topic_score = HOT_TOPIC_RANK.get(hot_topic_strength, 0) / HOT_TOPIC_RANK["strong"]
    intraday_score = _average_flags(row, ["pullback_ok", "bullish_confirm"])
    pressure_score = 1.0 if bool(row.get("breakout_ok")) else (0.5 if not bool(row.get("near_resistance")) else 0.2)
    environment_score = _float(context.get("environment_score"), 0.4)
    metrics = {
        "price_ma_deviation_pct": indicator.get("price_ma25_deviation_pct", 999.0),
        "ma_direction": "up" if bool(row.get("ma25_slope_ok")) else "down",
        "volume_ratio": indicator.get("vol_ratio", 0.0),
        "volume_crossed": bool(indicator.get("vol_ma5_cross_vol_ma60")),
        "below_core_ma": not bool(row.get("price_near_ma25")),
        "explode_status": explode_status,
        "hot_topic_strength": hot_topic_strength,
        "position_in_hot_topic": position,
        "structure_score": structure_score,
        "volume_score": volume_score,
        "hot_topic_score": hot_topic_score,
        "intraday_score": intraday_score,
        "pressure_score": pressure_score,
        "environment_score": environment_score,
    }
    evaluation = evaluate_after_market_signal(metrics, cfg)
    return {
        "selection_status": evaluation["status"],
        "final_score": evaluation["final_score"],
        "recent_3d_pct": recent_3d_pct,
        "explode_status": explode_status,
        "market_state": context.get("market_state"),
        "environment_score": environment_score,
        "hot_topic_strength": hot_topic_strength,
        "position_in_hot_topic": position,
        "hot_topic_score": hot_topic_score,
        "volume_score": volume_score,
        "structure_score": structure_score,
        "intraday_score": intraday_score,
        "pressure_score": pressure_score,
    }


def legacy_volume_structure_ok(
    indicator: dict[str, Any],
    cfg: dict[str, Any],
    base_ratio: float = 1.0,
) -> bool:
    volume_ratio = _float(indicator.get("vol_ratio"), 0.0)
    if volume_ratio >= _float(base_ratio, 1.0):
        return True
    if not bool(cfg.get("volume_cross_fallback_enabled", True)):
        return False
    return bool(indicator.get("vol_ma5_cross_vol_ma60")) and volume_ratio >= _float(cfg.get("volume_cross_confirm_ratio"), 0.9)


def classify_explode_status(gain: float, cfg: dict[str, Any]) -> str:
    if gain > _float(cfg.get("recent_3d_overheat_min"), 20.0):
        return "overheat"
    if gain <= _float(cfg.get("recent_3d_normal_max"), 12.0):
        return "normal"
    if gain <= _float(cfg.get("recent_3d_warm_max"), 18.0):
        return "warm"
    return "acceleration"


def _hard_gate_failures(metrics: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if abs(_float(metrics.get("price_ma_deviation_pct"), 999.0)) > _float(cfg.get("pullback_max_pct"), 5.0):
        reasons.append("price_distance")
    if str(metrics.get("ma_direction", "")).lower() in {"down", "falling", "weak_down"}:
        reasons.append("ma_direction")
    if not _volume_structure_ok(metrics, cfg):
        reasons.append("volume_structure")
    if bool(metrics.get("below_core_ma")):
        reasons.append("below_core_ma")
    if str(metrics.get("explode_status", "")).lower() == "overheat":
        reasons.append("explode_overheat")
    if bool(cfg.get("hot_topic_required", True)) and not _hot_topic_satisfies(
        metrics.get("hot_topic_strength"),
        cfg.get("hot_topic_strength_required", "medium"),
    ):
        reasons.append("hot_topic_strength")
    return reasons


def _volume_structure_ok(metrics: dict[str, Any], cfg: dict[str, Any]) -> bool:
    return legacy_volume_structure_ok(
        {
            "vol_ratio": metrics.get("volume_ratio"),
            "vol_ma5_cross_vol_ma60": metrics.get("volume_crossed"),
        },
        cfg,
        base_ratio=1.0,
    )


def _hot_topic_satisfies(actual: Any, required: Any) -> bool:
    return HOT_TOPIC_RANK.get(str(actual or "none"), 0) >= HOT_TOPIC_RANK.get(str(required or "medium"), 2)


def _position_satisfies_focus(actual: Any, required: Any) -> bool:
    return POSITION_RANK.get(str(actual or "edge"), 0) >= POSITION_RANK.get(str(required or "strong"), 2)


def _average_flags(row: dict[str, Any], keys: list[str]) -> float:
    if not keys:
        return 0.0
    return round(sum(1 for key in keys if bool(row.get(key))) / len(keys), 4)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

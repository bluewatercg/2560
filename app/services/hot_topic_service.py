from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def classify_hot_topic_strength(topic_pct_rank: Any, limit_up_count: Any) -> str:
    rank = _to_float(topic_pct_rank)
    if rank is None or rank <= 0:
        return "none"

    limit_ups = _to_int(limit_up_count)
    if rank <= 5 and limit_ups >= 5:
        return "strong"
    if rank <= 15 and limit_ups >= 2:
        return "medium"
    return "weak"


def position_in_hot_topic(is_leader: bool = False, rank_pct: Any = None) -> str:
    if is_leader:
        return "leader"

    rank = _to_float(rank_pct)
    if rank is None:
        return "edge"
    if rank <= 0.2:
        return "strong"
    if rank <= 0.7:
        return "follower"
    return "edge"


def hot_topic_snapshot(
    topic_pct_rank: Any,
    limit_up_count: Any,
    is_leader: bool = False,
    rank_pct: Any = None,
) -> dict[str, Any]:
    return {
        "hot_topic_strength": classify_hot_topic_strength(topic_pct_rank, limit_up_count),
        "position_in_hot_topic": position_in_hot_topic(is_leader=is_leader, rank_pct=rank_pct),
        "topic_pct_rank": topic_pct_rank,
        "topic_limit_up_count": limit_up_count,
        "rank_pct": rank_pct,
        "is_leader": is_leader,
    }

from __future__ import annotations

from enum import Enum
from typing import Any


class SelectionStatus(str, Enum):
    FOCUS = "focus"
    WATCH = "watch"
    REJECT = "reject"


class ExplodeStatus(str, Enum):
    NORMAL = "normal"
    WARM = "warm"
    ACCELERATION = "acceleration"
    OVERHEAT = "overheat"


class HotTopicStrength(str, Enum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    NONE = "none"


class PositionInHotTopic(str, Enum):
    LEADER = "leader"
    STRONG = "strong"
    FOLLOWER = "follower"
    EDGE = "edge"


def classify_recent_3d_pct(gain: float, cfg: dict[str, Any]) -> ExplodeStatus:
    overheat_min = float(cfg.get("recent_3d_overheat_min", 20.0))
    normal_max = float(cfg.get("recent_3d_normal_max", 12.0))
    warm_max = float(cfg.get("recent_3d_warm_max", 18.0))

    if gain >= overheat_min:
        return ExplodeStatus.OVERHEAT
    if gain <= normal_max:
        return ExplodeStatus.NORMAL
    if gain <= warm_max:
        return ExplodeStatus.WARM
    return ExplodeStatus.ACCELERATION

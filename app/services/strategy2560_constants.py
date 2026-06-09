from __future__ import annotations

import logging
from enum import Enum


logger = logging.getLogger(__name__)


class AfterMarketStatus(str, Enum):
    FOCUS = "focus"
    WATCH = "watch"
    REJECT = "reject"


class MorningGrade(str, Enum):
    HIGH = "high"
    UPGRADE_HIGH = "upgrade_high"
    NORMAL_CAUTIOUS = "normal_cautious"
    HOLD = "hold"
    DOWNGRADE = "downgrade"
    SKIPPED = "skipped"


class MissingReason(str, Enum):
    NO_CANDIDATE = "no_candidate_yesterday"
    FALLBACK_DISABLED = "auction_data_missing_and_fallback_disabled"
    AVG5_INSUFFICIENT = "avg5_insufficient_history"
    AUCTION_MISSING_NO_AVG5 = "auction_data_missing_and_avg5_unavailable"


MISSING_REASON_DISPLAY = {
    MissingReason.NO_CANDIDATE.value: "昨日无候选",
    MissingReason.AUCTION_MISSING_NO_AVG5.value: "竞价数据缺失",
    MissingReason.AVG5_INSUFFICIENT.value: "竞价历史不足",
    MissingReason.FALLBACK_DISABLED.value: "竞价缺失且兜底关闭",
}


def render_missing_reason(reason: str | None) -> str:
    if reason is None:
        return ""
    if reason in MISSING_REASON_DISPLAY:
        return MISSING_REASON_DISPLAY[reason]
    logger.warning("未知 missing_reason 取值: %s", reason)
    return f"未知原因（{reason}）"

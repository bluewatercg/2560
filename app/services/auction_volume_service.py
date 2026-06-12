from __future__ import annotations

from typing import Any, NamedTuple


class Avg5AuctionVolumeResult(NamedTuple):
    avg5_auction_volume: float | None
    valid_days: int
    required_valid_days: int
    insufficient_history: bool
    unavailable: bool


def compute_avg5_auction_volume(
    auction_rows: list[dict[str, Any]],
    *,
    current_trade_date: int | str,
    cfg: dict[str, Any],
) -> Avg5AuctionVolumeResult:
    required_valid_days = int(cfg["avg5_min_valid_days"])
    current_key = _trade_date_key(current_trade_date)

    valid_rows = []
    for row in auction_rows:
        row_date = row.get("trade_date", row.get("date"))
        if row_date is None or _trade_date_key(row_date) >= current_key:
            continue

        volume = _positive_float_or_none(row.get("auction_volume"))
        if volume is None:
            continue

        valid_rows.append((_trade_date_key(row_date), volume))

    recent_five = sorted(valid_rows, key=lambda item: item[0], reverse=True)[:5]
    valid_days = len(recent_five)
    if valid_days == 0:
        return Avg5AuctionVolumeResult(
            avg5_auction_volume=None,
            valid_days=0,
            required_valid_days=required_valid_days,
            insufficient_history=required_valid_days > 0,
            unavailable=True,
        )

    avg5 = sum(volume for _, volume in recent_five) / valid_days
    return Avg5AuctionVolumeResult(
        avg5_auction_volume=float(avg5),
        valid_days=valid_days,
        required_valid_days=required_valid_days,
        insufficient_history=valid_days < required_valid_days,
        unavailable=False,
    )


def _trade_date_key(value: int | str) -> int:
    return int(str(value).replace("-", ""))


def _positive_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number <= 0:
        return None
    return number

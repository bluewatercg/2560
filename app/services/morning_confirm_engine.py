from __future__ import annotations

from typing import Any

from app.services.strategy2560_constants import MissingReason, MorningGrade


SKIP_CODE = "__skip__"


def validate_morning_confirm_row(row: dict[str, Any]) -> None:
    code = row.get("code")
    morning_grade = _enum_value(row.get("morning_grade"))

    if morning_grade == MorningGrade.SKIPPED.value and code != SKIP_CODE:
        raise ValueError("morning_grade=skipped is only allowed for code=__skip__")
    if code == SKIP_CODE and morning_grade != MorningGrade.SKIPPED.value:
        raise ValueError("code=__skip__ must use morning_grade=skipped")
    if morning_grade == "normal":
        raise ValueError("morning_grade=normal is forbidden")


def build_morning_confirm_rows(
    *,
    yesterday_candidates: list[dict[str, Any]],
    cfg: dict[str, Any],
    auction_rows_by_code: dict[str, dict[str, Any]] | None = None,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    candidates = [
        candidate
        for candidate in yesterday_candidates
        if _candidate_status(candidate) in {"focus", "watch"}
    ]
    if not candidates:
        row = {
            "code": SKIP_CODE,
            "morning_grade": MorningGrade.SKIPPED.value,
            "missing_reason": MissingReason.NO_CANDIDATE.value,
        }
        validate_morning_confirm_row(row)
        return [row]

    codes = [str(candidate["code"]) for candidate in candidates]
    auction_rows = auction_rows_by_code
    if auction_rows is None:
        if client is None:
            raise ValueError("auction_rows_by_code or client is required when candidates exist")
        auction_rows = client.load_auction_rows(codes)

    pre_market_state = None
    if client is not None and hasattr(client, "load_pre_market_state"):
        pre_market_state = client.load_pre_market_state()

    rows = []
    for candidate in candidates:
        code = str(candidate["code"])
        row = _build_candidate_row(
            code=code,
            yesterday_status=_candidate_status(candidate),
            auction_row=auction_rows.get(code, {}),
            cfg=cfg,
            pre_market_state=pre_market_state,
        )
        validate_morning_confirm_row(row)
        rows.append(row)
    return rows


def classify_morning_grade(
    *,
    yesterday_status: str,
    today_auction_volume: float,
    base_auction_volume: float,
    open_gap_pct: float,
    cfg: dict[str, Any],
) -> str:
    status = str(yesterday_status)
    amplify_threshold = float(cfg.get("auction_amplify_ratio", 1.0))
    amplified = float(today_auction_volume) >= float(base_auction_volume) * amplify_threshold
    gap_pct = float(open_gap_pct)

    if status == "focus" and gap_pct < -1.0:
        return MorningGrade.DOWNGRADE.value
    if not amplified:
        return MorningGrade.HOLD.value
    if gap_pct > 3.0:
        return MorningGrade.NORMAL_CAUTIOUS.value
    if status == "focus" and 0.0 <= gap_pct <= 3.0:
        return MorningGrade.HIGH.value
    if status == "watch" and 0.0 <= gap_pct <= 3.0:
        return MorningGrade.UPGRADE_HIGH.value
    return MorningGrade.HOLD.value


def _build_candidate_row(
    *,
    code: str,
    yesterday_status: str,
    auction_row: dict[str, Any],
    cfg: dict[str, Any],
    pre_market_state: str | None,
) -> dict[str, Any]:
    today_volume = _positive_float_or_none(auction_row.get("auction_volume"))
    base_volume, missing_reason = _base_auction_volume(auction_row, cfg)
    open_gap_pct = _open_gap_pct(auction_row)

    row: dict[str, Any] = {
        "code": code,
        "missing_reason": missing_reason,
        "today_auction_volume": today_volume,
        "yesterday_auction_volume": _positive_float_or_none(
            auction_row.get("yesterday_auction_volume")
        ),
        "avg5_auction_volume": _positive_float_or_none(
            auction_row.get("avg5_auction_volume")
        ),
        "open_gap_pct": open_gap_pct,
        "pre_market_state": pre_market_state,
    }

    if today_volume is None or base_volume is None or missing_reason is not None:
        row["morning_grade"] = MorningGrade.HOLD.value
        row["auction_amplify_ratio"] = None
        return row

    row["auction_amplify_ratio"] = today_volume / base_volume
    row["morning_grade"] = classify_morning_grade(
        yesterday_status=yesterday_status,
        today_auction_volume=today_volume,
        base_auction_volume=base_volume,
        open_gap_pct=open_gap_pct,
        cfg=cfg,
    )
    return row


def _base_auction_volume(
    auction_row: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[float | None, str | None]:
    yesterday_volume = _positive_float_or_none(auction_row.get("yesterday_auction_volume"))
    if yesterday_volume is not None:
        return yesterday_volume, None

    if not bool(cfg.get("auction_fallback_to_avg5", True)):
        return None, MissingReason.FALLBACK_DISABLED.value

    avg5_volume = _positive_float_or_none(auction_row.get("avg5_auction_volume"))
    avg5_valid_days = auction_row.get("avg5_valid_days")
    if avg5_valid_days is not None and int(avg5_valid_days) < int(cfg["avg5_min_valid_days"]):
        return None, MissingReason.AVG5_INSUFFICIENT.value
    if avg5_volume is None:
        return None, MissingReason.AUCTION_MISSING_NO_AVG5.value
    return avg5_volume, None


def _candidate_status(candidate: dict[str, Any]) -> str:
    return str(_enum_value(candidate.get("yesterday_status", candidate.get("status", ""))))


def _open_gap_pct(auction_row: dict[str, Any]) -> float:
    if auction_row.get("open_gap_pct") is not None:
        return float(auction_row["open_gap_pct"])

    open_price = _positive_float_or_none(
        auction_row.get("auction_open_price", auction_row.get("open_price"))
    )
    previous_close = _positive_float_or_none(auction_row.get("previous_close"))
    if open_price is None or previous_close is None:
        return 0.0
    return (open_price / previous_close - 1.0) * 100.0


def _positive_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number <= 0:
        return None
    return number


def _enum_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return value

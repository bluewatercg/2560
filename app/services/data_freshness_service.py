def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_gap(source_latest, db_latest) -> tuple[str, int | None]:
    source = _to_int(source_latest)
    db = _to_int(db_latest)
    if source is None or db is None:
        return "unknown", None

    gap = max(0, source - db)
    if gap == 0:
        return "current", 0
    return "missing", gap


def can_run_2560(
    target_date,
    daily_latest,
    minute_5m_latest,
    minute_30m_latest,
) -> bool:
    target = _to_int(target_date)
    daily = _to_int(daily_latest)
    min_5m = _to_int(minute_5m_latest)
    min_30m = _to_int(minute_30m_latest)
    if None in (daily, target, min_5m, min_30m):
        return False

    return daily >= target and min_5m >= min_30m and min_30m >= target * 1000000

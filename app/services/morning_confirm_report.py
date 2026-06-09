from __future__ import annotations

from typing import Any

try:
    from app.services.strategy2560_constants import render_missing_reason
except Exception:  # pragma: no cover - keeps this renderer importable in isolated tests
    _MISSING_REASON_DISPLAY = {
        "no_candidate_yesterday": "昨日无候选",
        "auction_data_missing_and_avg5_unavailable": "竞价数据缺失",
        "avg5_insufficient_history": "竞价历史不足",
        "auction_data_missing_and_fallback_disabled": "竞价缺失且兜底关闭",
    }

    def render_missing_reason(reason: str | None) -> str:
        if reason is None:
            return ""
        return _MISSING_REASON_DISPLAY.get(reason, reason)


MORNING_CONFIRM_FILENAME = "09_morning_confirm.md"
SKILL_MORNING_INPUT_FILENAME = "10_skill_morning_input.md"

MORNING_GRADES = [
    "high",
    "upgrade_high",
    "normal_cautious",
    "hold",
    "downgrade",
    "skipped",
]


def render_morning_confirm_markdown(
    *,
    rows: list[dict[str, Any]],
    trade_date: str | None = None,
    source_trade_date: str | None = None,
) -> str:
    resolved_trade_date = _resolve_date(rows, "trade_date", trade_date)
    resolved_source_trade_date = _resolve_date(rows, "source_trade_date", source_trade_date)
    lines = [
        "# 2560 早盘确认报告",
        "",
        f"- trade_date: {_text(resolved_trade_date)}",
        f"- source_trade_date: {_text(resolved_source_trade_date)}",
        "",
        "| source_trade_date | trade_date | code | name | yesterday_status | morning_grade | pre_market_state | missing_reason | today_auction_volume | base_auction_volume | auction_amplify_ratio | open_gap_pct |",
        "|---|---|---|---|---|---|---|---|---:|---:|---:|---:|",
    ]

    for row in rows:
        lines.append(_render_confirm_table_row(row, resolved_trade_date, resolved_source_trade_date))

    if not rows:
        lines.append(
            f"| {_text(resolved_source_trade_date)} | {_text(resolved_trade_date)} | __skip__ |  |  | skipped |  | {render_missing_reason('no_candidate_yesterday')} |  |  |  |  |"
        )

    return "\n".join(lines) + "\n"


def render_skill_morning_input_markdown(
    *,
    rows: list[dict[str, Any]],
    trade_date: str | None = None,
    source_trade_date: str | None = None,
    market_environment: dict[str, Any] | None = None,
) -> str:
    resolved_trade_date = _resolve_date(rows, "trade_date", trade_date)
    resolved_source_trade_date = _resolve_date(rows, "source_trade_date", source_trade_date)
    environment = market_environment or {}
    grouped = _group_rows_by_grade(rows)
    missing_notes = _missing_notes(rows)

    lines = [
        "# 2560 早盘 Skill 输入报告",
        "",
        f"- trade_date: {_text(resolved_trade_date)}",
        f"- source_trade_date: {_text(resolved_source_trade_date)}",
        "",
        "## 1. 早盘市场环境",
        f"- pre_market_state: {_text(environment.get('pre_market_state', _first_value(rows, 'pre_market_state')))}",
        f"- 集合竞价指数涨幅: {_pct(environment.get('index_auction_gain_pct'))}",
        "",
        "## 2. 昨日候选池早盘确认结果",
    ]

    for grade in MORNING_GRADES:
        lines.append(
            f"- {grade}: {_render_grouped_grade(grade, grouped[grade], resolved_trade_date, resolved_source_trade_date)}"
        )

    lines.extend(["", "## 3. 数据缺失说明"])
    if missing_notes:
        lines.extend(missing_notes)
    else:
        lines.append("- 数据完整，无缺失降级说明。")

    lines.extend(
        [
            "",
            "## 4. 建议操作",
            f"- 高度关注: {_join_labels(grouped['high'])}",
            f"- 升级关注: {_join_labels(grouped['upgrade_high'])}",
            f"- 暂时观望: {_join_labels(grouped['normal_cautious'] + grouped['hold'])}",
            f"- 放弃: {_join_labels(grouped['downgrade'])}",
        ]
    )

    return "\n".join(lines) + "\n"


def render_morning_report_package(
    *,
    rows: list[dict[str, Any]],
    trade_date: str | None = None,
    source_trade_date: str | None = None,
    market_environment: dict[str, Any] | None = None,
) -> dict[str, str]:
    return {
        MORNING_CONFIRM_FILENAME: render_morning_confirm_markdown(
            rows=rows,
            trade_date=trade_date,
            source_trade_date=source_trade_date,
        ),
        SKILL_MORNING_INPUT_FILENAME: render_skill_morning_input_markdown(
            rows=rows,
            trade_date=trade_date,
            source_trade_date=source_trade_date,
            market_environment=market_environment,
        ),
    }


def _render_confirm_table_row(
    row: dict[str, Any],
    trade_date: str | None,
    source_trade_date: str | None,
) -> str:
    return (
        f"| {_text(row.get('source_trade_date', source_trade_date))} "
        f"| {_text(row.get('trade_date', trade_date))} "
        f"| {_text(row.get('code'))} "
        f"| {_text(row.get('name'))} "
        f"| {_text(row.get('yesterday_status', row.get('status')))} "
        f"| {_text(row.get('morning_grade'))} "
        f"| {_text(row.get('pre_market_state'))} "
        f"| {render_missing_reason(_maybe_str(row.get('missing_reason')))} "
        f"| {_number(row.get('today_auction_volume'))} "
        f"| {_number(_base_auction_volume(row))} "
        f"| {_number(row.get('auction_amplify_ratio'), digits=2)} "
        f"| {_pct(row.get('open_gap_pct'))} |"
    )


def _group_rows_by_grade(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {grade: [] for grade in MORNING_GRADES}
    for row in rows:
        grade = _maybe_str(row.get("morning_grade"))
        if grade in grouped:
            grouped[grade].append(row)
    return grouped


def _render_grouped_grade(
    grade: str,
    rows: list[dict[str, Any]],
    trade_date: str | None,
    source_trade_date: str | None,
) -> str:
    if rows:
        if grade == "skipped" and any(row.get("code") == "__skip__" for row in rows):
            return (
                "昨日无候选"
                f"（source_trade_date={_text(source_trade_date)}, trade_date={_text(trade_date)}）"
            )
        return _join_labels(rows)
    return "无"


def _missing_notes(rows: list[dict[str, Any]]) -> list[str]:
    notes = []
    for row in rows:
        reason = _maybe_str(row.get("missing_reason"))
        if not reason or reason == "no_candidate_yesterday":
            continue
        notes.append(
            f"- {_label(row)}: {render_missing_reason(reason)}，morning_grade={_text(row.get('morning_grade'))}"
        )
    return notes


def _join_labels(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "无"
    return "、".join(_label(row) for row in rows if row.get("code") != "__skip__") or "无"


def _label(row: dict[str, Any]) -> str:
    code = _text(row.get("code"))
    name = _text(row.get("name"))
    return f"{code} {name}".strip()


def _resolve_date(rows: list[dict[str, Any]], key: str, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return _first_value(rows, key)


def _first_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _base_auction_volume(row: dict[str, Any]) -> Any:
    if row.get("yesterday_auction_volume") not in (None, ""):
        return row.get("yesterday_auction_volume")
    return row.get("avg5_auction_volume")


def _number(value: Any, *, digits: int | None = None) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    if digits is not None:
        return f"{number:.{digits}f}"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _pct(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return _text(value)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _maybe_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)

from __future__ import annotations

from pathlib import Path
from typing import Any
import os

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.clickhouse import get_clickhouse


SIMPLE_HARD_METRICS_FILENAME = "09_simple_2560_hard_metrics.md"


def build_simple_hard_metric_rows(
    *,
    daily_rows: list[dict[str, Any]],
    names: dict[str, str | None] | None = None,
    trade_date: str,
) -> list[dict[str, Any]]:
    names = names or {}
    by_code: dict[str, dict[str, dict[str, Any]]] = {}
    for row in daily_rows:
        code = str(row.get("code") or "")
        day = str(row.get("d") or row.get("date") or "")[:10]
        if not code or not day:
            continue
        by_code.setdefault(code, {})[day] = dict(row, d=day)

    items: list[dict[str, Any]] = []
    for code, date_rows in by_code.items():
        ordered = sorted(date_rows.values(), key=lambda item: str(item.get("d") or ""))
        if len(ordered) < 60:
            continue
        latest = ordered[-1]
        if str(latest.get("d") or "")[:10] != trade_date:
            continue

        closes = [_to_float(row.get("close")) for row in ordered]
        volumes = [_to_float(row.get("volume")) for row in ordered]
        if any(value is None for value in closes[-25:]) or any(value is None for value in volumes[-60:]):
            continue

        close = float(closes[-1])
        ma25 = sum(float(value) for value in closes[-25:]) / 25
        mavol5 = sum(float(value) for value in volumes[-5:]) / 5
        mavol60 = sum(float(value) for value in volumes[-60:]) / 60
        recent_3day_gain_pct = _recent_3day_gain_pct(closes)
        if ma25 == 0 or mavol60 == 0:
            continue
        if recent_3day_gain_pct is None or recent_3day_gain_pct > 20.0:
            continue
        if not (close > ma25 and mavol5 > mavol60):
            continue

        items.append(
            {
                "code": code,
                "name": names.get(code) or code,
                "trade_date": trade_date,
                "close": close,
                "ma25": ma25,
                "close_vs_ma25_pct": (close - ma25) / ma25 * 100,
                "recent_3day_gain_pct": recent_3day_gain_pct,
                "mavol5": mavol5,
                "mavol60": mavol60,
                "mavol_ratio": mavol5 / mavol60,
            }
        )

    items.sort(key=lambda item: (-float(item["mavol_ratio"]), -float(item["close_vs_ma25_pct"]), str(item["code"])))
    return items


def render_simple_hard_metrics_report(*, trade_date: str, batch_id: Any, items: list[dict[str, Any]]) -> str:
    lines = [
        f"# 2560 简化硬指标盘后报告 - {trade_date}",
        "",
        f"- batch_id: {_v(batch_id)}",
        "- 只显示：收盘价高于25日均价、5日平均成交量高于60日平均成交量、近3日涨幅不超过20%",
        "- 短期量能倍数说明：例如 1.55 表示最近5日平均成交量是60日平均成交量的1.55倍",
        f"- 命中数量: {len(items)}",
        "",
    ]
    if not items:
        lines.append("无满足条件标的。")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| 代码 | 名称 | 收盘价 | 25日均价 | 高于25日均价幅度 | 近3日涨幅 | 5日平均成交量 | 60日平均成交量 | 短期量能倍数 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in items:
        lines.append(
            f"| {_v(item.get('code'))} | {_v(item.get('name'))} | "
            f"{_fmt_num(item.get('close'))} | {_fmt_num(item.get('ma25'))} | "
            f"{_fmt_num(item.get('close_vs_ma25_pct'))}% | "
            f"{_fmt_num(item.get('recent_3day_gain_pct'))}% | "
            f"{_fmt_num(item.get('mavol5'), 0)} | {_fmt_num(item.get('mavol60'), 0)} | "
            f"{_fmt_num(item.get('mavol_ratio'))} |"
        )
    return "\n".join(lines) + "\n"


class Simple2560HardMetricsReportService:
    def __init__(self, db: Session, output_root: str | Path | None = None, clickhouse_client: Any | None = None):
        self.db = db
        self.output_root = Path(output_root or os.getenv("REPORT_PACKAGE_DIR", "reports"))
        self.clickhouse = clickhouse_client or get_clickhouse()

    def generate_for_batch(self, *, trade_date: str, batch_id: Any) -> dict[str, Any]:
        items = self.build_for_batch(trade_date=trade_date, batch_id=batch_id)
        package_dir = self.output_root / trade_date
        package_dir.mkdir(parents=True, exist_ok=True)
        path = package_dir / SIMPLE_HARD_METRICS_FILENAME
        path.write_text(
            render_simple_hard_metrics_report(trade_date=trade_date, batch_id=batch_id, items=items),
            encoding="utf-8",
        )
        return {
            "trade_date": trade_date,
            "batch_id": batch_id,
            "status": "generated",
            "file": str(path),
            "count": len(items),
        }

    def build_for_batch(self, *, trade_date: str, batch_id: Any) -> list[dict[str, Any]]:
        names = self._signal_names(batch_id)
        daily_rows = self._daily_rows(list(names), trade_date)
        return build_simple_hard_metric_rows(
            daily_rows=daily_rows,
            names=names,
            trade_date=trade_date,
        )

    def _signal_names(self, batch_id: Any) -> dict[str, str | None]:
        rows = self.db.execute(
            text(
                """
                SELECT code, MAX(name) AS name
                FROM structure_2560_analysis
                WHERE CAST(batch_id AS CHAR)=CAST(:batch_id AS CHAR)
                GROUP BY code
                ORDER BY code
                """
            ),
            {"batch_id": str(batch_id)},
        ).mappings().all()
        return {str(row["code"]): row.get("name") for row in rows if row.get("code")}

    def _daily_rows(self, codes: list[str], trade_date: str) -> list[dict[str, Any]]:
        if not codes:
            return []
        rows: list[dict[str, Any]] = []
        for chunk in _chunks(codes, 500):
            quoted_codes = ",".join(_quote(code) for code in chunk)
            rows.extend(
                self.clickhouse.query(
                    f"""
                    SELECT
                        code,
                        toString(date) AS d,
                        any(open) AS open,
                        any(high) AS high,
                        any(low) AS low,
                        any(close) AS close,
                        any(volume) AS volume,
                        any(amount) AS amount
                    FROM daily_kline
                    WHERE code IN ({quoted_codes})
                      AND date <= toDate('{trade_date}')
                      AND date >= toDate('{trade_date}') - INTERVAL 120 DAY
                    GROUP BY code, date
                    ORDER BY code, date
                    """
                )
            )
        return rows


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _quote(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _recent_3day_gain_pct(closes: list[float | None]) -> float | None:
    if len(closes) < 4:
        return None
    current = closes[-1]
    base = closes[-4]
    if current is None or base in (None, 0):
        return None
    return (float(current) - float(base)) / float(base) * 100


def _fmt_num(value: Any, digits: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    if digits <= 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _v(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("\x00", "").strip()

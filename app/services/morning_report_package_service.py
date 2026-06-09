from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.db.clickhouse import get_clickhouse
from app.services.config_service import ConfigService
from app.services.morning_confirm_engine import build_morning_confirm_rows
from app.services.morning_confirm_report import render_morning_report_package


MORNING_PACKAGE_FILENAMES = (
    "09_morning_confirm.md",
    "10_skill_morning_input.md",
)


class MorningReportPackageService:
    def __init__(self, db: Any, output_root: str | Path | None = None):
        self.db = db
        self.output_root = Path(output_root or os.getenv("REPORT_PACKAGE_DIR", "reports"))

    def generate_morning_package(
        self,
        *,
        trade_date: str,
        source_trade_date: str | None = None,
    ) -> dict[str, Any]:
        resolved_source_trade_date = source_trade_date or _previous_weekday(trade_date)
        candidates = self._load_yesterday_candidates(resolved_source_trade_date)
        cfg = ConfigService(self.db).load_strategy_config()
        client = _MorningMarketDataClient(trade_date=trade_date)
        rows = build_morning_confirm_rows(
            yesterday_candidates=candidates,
            cfg=cfg,
            client=client,
        )
        enriched_rows = _enrich_rows(
            rows=rows,
            candidates=candidates,
            trade_date=trade_date,
            source_trade_date=resolved_source_trade_date,
        )
        package = render_morning_report_package(
            rows=enriched_rows,
            trade_date=trade_date,
            source_trade_date=resolved_source_trade_date,
            market_environment={"pre_market_state": client.load_pre_market_state()},
        )

        package_dir = self.output_root / trade_date
        package_dir.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        for filename in MORNING_PACKAGE_FILENAMES:
            path = package_dir / filename
            path.write_text(package[filename], encoding="utf-8")
            files.append(str(path))

        return {
            "trade_date": trade_date,
            "source_trade_date": resolved_source_trade_date,
            "status": "generated",
            "files": files,
        }

    def _load_yesterday_candidates(self, source_trade_date: str) -> list[dict[str, Any]]:
        path = self.output_root / source_trade_date / "05_focus_watch_list.json"
        if not path.is_file():
            raise FileNotFoundError(f"focus/watch package not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            items = payload.get("items") or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            status = row.get("selection_status") or row.get("yesterday_status") or row.get("status")
            if status is not None:
                row["yesterday_status"] = status
                row["status"] = status
            normalized.append(row)
        return normalized


class _MorningMarketDataClient:
    def __init__(self, *, trade_date: str):
        self.trade_date = trade_date

    def load_auction_rows(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}
        quoted_codes = ",".join(_quote(code) for code in codes)
        rows = get_clickhouse().query(
            f"""
            SELECT code, trade_date, auction_volume, yesterday_auction_volume,
                   avg5_auction_volume, auction_amplify_ratio, open_gap_pct,
                   auction_open_price, prev_close
            FROM auction_volume
            WHERE trade_date = '{self.trade_date}'
              AND code IN ({quoted_codes})
            """
        )
        return {
            str(row.get("code")): dict(row)
            for row in rows
            if row.get("code")
        }

    def load_pre_market_state(self) -> str | None:
        return None


def _enrich_rows(
    *,
    rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    trade_date: str,
    source_trade_date: str,
) -> list[dict[str, Any]]:
    candidate_by_code = {str(item.get("code")): item for item in candidates if item.get("code")}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        current = dict(row)
        current["trade_date"] = trade_date
        current["source_trade_date"] = source_trade_date
        code = str(current.get("code") or "")
        source = candidate_by_code.get(code, {})
        if source:
            current["name"] = source.get("name")
            current["yesterday_status"] = source.get("selection_status") or source.get("yesterday_status") or source.get("status")
        enriched.append(current)
    return enriched


def _previous_weekday(value: str) -> str:
    current = _parse_date(value)
    previous = current - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous.isoformat()


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _quote(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"

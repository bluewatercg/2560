from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from typing import Any

from pymysql.err import OperationalError as PyMySQLOperationalError
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.market_scope import market_sql_where
from app.db.clickhouse import get_clickhouse
from app.db.repository import KlineRepository
from app.services.canonical_signal_engine import build_canonical_fields_from_legacy_signal
from app.services.config_service import ConfigService
from app.services.tag_service import build_tags, explain_text, structure_status


class SignalEngine2560Fast:
    """ClickHouse-first daily 2560 scanner.

    This path is optimized for the normal 4pm workflow: today's daily and 5m
    bars have just arrived, 30m bars exist or are built in ClickHouse, and we
    only need signals for the target trading day.
    """

    def __init__(self, db: Session, strategy_version: str = "2.5.0-fast"):
        self.db = db
        self.repo = KlineRepository(db)
        self.strategy_version = strategy_version

    def uid(self, code: str, signal_time: str) -> str:
        return hashlib.md5(f"{code}|{signal_time}|30m|{self.strategy_version}".encode()).hexdigest()

    def latest_trade_date(self, market: str) -> str | None:
        where = market_sql_where("code", market)
        row = get_clickhouse().query_one(f"SELECT max(date) AS d FROM daily_kline WHERE {where}")
        return row["d"] if row and row.get("d") else None

    def _candidate_sql(self, market: str, trade_date: str, cfg: dict[str, Any], limit_codes: int | None) -> str:
        where = market_sql_where("code", market)
        threshold = float(cfg.get("pullback_threshold_pct", 2.0))
        min_volume = float(cfg.get("min_volume_ratio", 1.0))
        volume_cross_ratio = float(cfg.get("volume_cross_confirm_ratio", min_volume))
        slope_threshold = float(cfg.get("ma_slope_medium_threshold", 0.0))
        atr_weak_ratio = float(cfg.get("atr_weak_ratio", 0.85))
        breakout_threshold = float(cfg.get("breakout_threshold", 1.0))
        resistance_threshold = float(cfg.get("resistance_threshold", 0.95))
        code_limit = f" AND code IN (SELECT code FROM (SELECT DISTINCT code FROM minute_kline_period WHERE {where} ORDER BY code LIMIT {int(limit_codes)}))" if limit_codes else ""
        return f"""
WITH
    toDate('{trade_date}') AS target_day,
    m30_src AS (
        SELECT code, date, open, high, low, close, volume, amount, source
        FROM minute_kline_period
        WHERE period='30m'
          AND date >= target_day - INTERVAL 80 DAY
          AND date < target_day + INTERVAL 1 DAY
          AND {where}
          {code_limit}
    ),
    m30_ind AS (
        SELECT
            code, date, open, high, low, close, volume, amount, source,
            avg(close) OVER w25 AS ma25,
            avg(volume) OVER w5 AS vol_ma5,
            avg(volume) OVER w60 AS vol_ma60,
            (avg(volume) OVER w5) > (avg(volume) OVER w60) AS vol_ma5_cross_vol_ma60,
            avg(close) OVER w25_prev AS ma25_prev3,
            max(high) OVER w20 AS high_20,
            ((high - low) / nullIf(close, 0)) * 100 AS amplitude
        FROM m30_src
        WINDOW
            w5 AS (PARTITION BY code ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
            w20 AS (PARTITION BY code ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
            w25 AS (PARTITION BY code ORDER BY date ROWS BETWEEN 24 PRECEDING AND CURRENT ROW),
            w25_prev AS (PARTITION BY code ORDER BY date ROWS BETWEEN 27 PRECEDING AND 3 PRECEDING),
            w60 AS (PARTITION BY code ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
    ),
    m30_signal AS (
        SELECT
            *,
            (close - ma25) / nullIf(ma25, 0) * 100 AS price_ma25_deviation_pct,
            (ma25 - ma25_prev3) / nullIf(ma25_prev3, 0) * 100 AS ma25_slope_3,
            vol_ma5 / nullIf(vol_ma60, 0) AS vol_ratio,
            amplitude > 20 AS is_abnormal_bar
        FROM m30_ind
        WHERE toDate(date)=target_day
    ),
    daily_src AS (
        SELECT code, date, open, high, low, close, volume
        FROM daily_kline
        WHERE date <= target_day
          AND date >= target_day - INTERVAL 360 DAY
          AND {where}
          {code_limit}
    ),
    daily_ind AS (
        SELECT
            code, date, close,
            avg(close) OVER d25 AS ma25,
            avg(close) OVER d60 AS ma60,
            avg(close) OVER d60_prev AS ma60_prev3,
            avg(tr) OVER d14 AS atr14,
            avg(tr) OVER d20 AS atr20_avg
        FROM (
            SELECT
                code, date, close,
                greatest(
                    high - low,
                    abs(high - lagInFrame(close, 1, close) OVER (PARTITION BY code ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)),
                    abs(low - lagInFrame(close, 1, close) OVER (PARTITION BY code ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING))
                ) AS tr
            FROM daily_src
        )
        WINDOW
            d14 AS (PARTITION BY code ORDER BY date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
            d20 AS (PARTITION BY code ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
            d25 AS (PARTITION BY code ORDER BY date ROWS BETWEEN 24 PRECEDING AND CURRENT ROW),
            d60 AS (PARTITION BY code ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
            d60_prev AS (PARTITION BY code ORDER BY date ROWS BETWEEN 62 PRECEDING AND 3 PRECEDING)
    ),
    daily_latest AS (
        SELECT
            code,
            argMax(close, date) AS daily_close,
            argMax(coalesce(ma60, ma25), date) AS daily_ma,
            argMax((ma60 - ma60_prev3) / nullIf(ma60_prev3, 0) * 100, date) AS daily_slope,
            argMax(atr14, date) AS atr14,
            argMax(atr20_avg, date) AS atr20_avg
        FROM daily_ind
        WHERE date <= target_day
        GROUP BY code
    ),
    m5_recent AS (
        SELECT
            code,
            max(date) AS last_5m_time,
            argMax(close, date) AS last_5m_close,
            argMax(open, date) AS last_5m_open,
            avg(close) AS ma25_approx,
            max(close > open) AS has_bullish
        FROM minute_kline_period
        WHERE period='5m'
          AND date >= target_day
          AND date < target_day + INTERVAL 1 DAY
          AND {where}
          {code_limit}
        GROUP BY code
    )
SELECT
    m.code AS code,
    toString(m.date) AS signal_time,
    m.close AS price,
    m.source AS source,
    abs(m.price_ma25_deviation_pct) <= {threshold} AS price_near_ma25,
    m.ma25_slope_3 >= {slope_threshold} AS ma25_slope_ok,
    (m.vol_ratio >= {min_volume} OR (m.vol_ma5_cross_vol_ma60 = 1 AND m.vol_ratio >= {volume_cross_ratio})) AS volume_structure_ok,
    (NOT m.is_abnormal_bar) AS abnormal_filter_ok,
    d.daily_close > d.daily_ma AS trend_price_ok,
    d.daily_slope > {slope_threshold} AS trend_slope_ok,
    d.atr14 > d.atr20_avg * {atr_weak_ratio} AS volatility_ok,
    m.close > m.high_20 * {breakout_threshold} AS breakout_ok,
    (m.vol_ratio >= {min_volume} OR (m.vol_ma5_cross_vol_ma60 = 1 AND m.vol_ratio >= {volume_cross_ratio})) AS volume_ok,
    m.close >= m.high_20 * {resistance_threshold} AS near_resistance,
    (f.last_5m_close >= f.ma25_approx OR abs((f.last_5m_close - f.ma25_approx) / nullIf(f.ma25_approx, 0) * 100) <= {threshold}) AS pullback_ok,
    f.has_bullish AS bullish_confirm,
    m.price_ma25_deviation_pct,
    m.ma25_slope_3,
    m.vol_ratio
FROM m30_signal m
INNER JOIN daily_latest d ON d.code=m.code
LEFT JOIN m5_recent f ON f.code=m.code
WHERE abs(m.price_ma25_deviation_pct) <= {threshold}
  AND m.ma25_slope_3 >= {slope_threshold}
  AND (m.vol_ratio >= {min_volume} OR (m.vol_ma5_cross_vol_ma60 = 1 AND m.vol_ratio >= {volume_cross_ratio}))
  AND NOT m.is_abnormal_bar
  AND d.daily_close > d.daily_ma
  AND d.daily_slope > {slope_threshold}
ORDER BY m.date DESC, m.code
"""

    def _load_signal_window_rows(self, codes: list[str], trade_date: str) -> list[dict[str, Any]]:
        if not codes:
            return []
        quoted_codes = ",".join(_quote(code) for code in codes)
        return get_clickhouse().query(
            f"""
            SELECT
                m.code AS code,
                toString(m.date) AS date,
                m.open AS open,
                m.close AS close,
                t.ma25 AS ma25,
                t.price_ma25_deviation_pct AS price_ma25_deviation_pct
            FROM minute_kline_period m
            LEFT JOIN technical_indicator t
              ON t.code = m.code
             AND t.period = '5m'
             AND t.date = m.date
            WHERE m.period='5m'
              AND m.code IN ({quoted_codes})
              AND m.date >= toDateTime('{trade_date} 00:00:00')
              AND m.date < toDateTime('{trade_date} 23:59:59') + INTERVAL 1 SECOND
            ORDER BY m.code, m.date
            """
        )

    def _apply_signal_window_confirmation(
        self,
        rows: list[dict[str, Any]],
        minute_rows: list[dict[str, Any]],
        cfg: dict[str, Any],
    ) -> None:
        threshold = float(cfg.get("pullback_threshold_pct", 2.0))
        confirm_bars = int(cfg.get("confirm_5m_bars", 6))
        by_code: dict[str, list[dict[str, Any]]] = {}
        for minute in minute_rows:
            code = str(minute.get("code") or "")
            if not code:
                continue
            by_code.setdefault(code, []).append(minute)
        for window_rows in by_code.values():
            window_rows.sort(key=lambda item: str(item.get("date") or ""))

        for row in rows:
            code = str(row.get("code") or "")
            signal_time = str(row.get("signal_time") or "")
            history = [
                item for item in by_code.get(code, [])
                if str(item.get("date") or "") < signal_time
            ][-confirm_bars:]
            if not history:
                row["pullback_ok"] = False
                row["bullish_confirm"] = False
                continue
            last = history[-1]
            ma25 = last.get("ma25")
            deviation = last.get("price_ma25_deviation_pct")
            close = last.get("close")
            pullback_ok = False
            if ma25 not in (None, "") and close not in (None, ""):
                pullback_ok = float(close) >= float(ma25)
            if not pullback_ok and deviation not in (None, ""):
                pullback_ok = abs(float(deviation)) <= threshold
            bullish_confirm = any(
                item.get("close") not in (None, "")
                and item.get("open") not in (None, "")
                and float(item["close"]) > float(item["open"])
                for item in history[-2:]
            )
            row["pullback_ok"] = bool(pullback_ok)
            row["bullish_confirm"] = bool(bullish_confirm)

    def _load_stock_names(self, codes: list[str]) -> dict[str, str | None]:
        if not codes:
            return {}
        rows = self.db.execute(
            text("SELECT code, name FROM stock_info WHERE code IN :codes").bindparams(bindparam("codes", expanding=True)),
            {"codes": tuple(codes)},
        ).mappings().all()
        return {r["code"]: r["name"] for r in rows}

    def _analysis_row(self, batch_id: int, cfg: dict[str, Any], names: dict[str, str | None], r: dict[str, Any]) -> dict[str, Any]:
        code = r["code"]
        signal_time = r["signal_time"]
        row = {
            "signal_uid": self.uid(code, signal_time),
            "batch_id": batch_id,
            "strategy_code": "S2560",
            "strategy_version": self.strategy_version,
            "code": code,
            "name": names.get(code),
            "signal_time": signal_time,
            "signal_period": "30m",
            "price": float(r["price"]),
            "source": r.get("source") or "clickhouse_fast",
            "stock_status": "NORMAL",
            "has_2560_signal": 1,
            "price_near_ma25": int(bool(r["price_near_ma25"])),
            "ma25_slope_ok": int(bool(r["ma25_slope_ok"])),
            "volume_structure_ok": int(bool(r["volume_structure_ok"])),
            "abnormal_filter_ok": int(bool(r["abnormal_filter_ok"])),
            "trend_price_ok": int(bool(r["trend_price_ok"])),
            "trend_slope_ok": int(bool(r["trend_slope_ok"])),
            "volatility_ok": int(bool(r["volatility_ok"])),
            "breakout_ok": int(bool(r["breakout_ok"])),
            "volume_ok": int(bool(r["volume_ok"])),
            "near_resistance": int(bool(r["near_resistance"])),
            "pullback_ok": int(bool(r["pullback_ok"])),
            "bullish_confirm": int(bool(r["bullish_confirm"])),
            "data_quality_status": "normal",
            "is_duplicate_signal": 0,
            "selected_signal": 1,
            "structure_status": "",
            "strength_score_raw": 0,
            "missing_tags": "",
            "missing_tag_count": 0,
            "explain_text": "",
        }
        canonical_context = {
            "market_state": "unknown",
            "environment_score": 0.4,
            "hot_topic_strength": "none",
            "position_in_hot_topic": "edge",
        }
        row.update(build_canonical_fields_from_legacy_signal(row, r, canonical_context, cfg))
        tags = build_tags(row)
        row["structure_status"] = structure_status(tags)
        row["missing_tags"] = json.dumps([t["tag_name"] for t in tags], ensure_ascii=False)
        row["missing_tag_count"] = len([t for t in tags if t.get("tag_type") == "negative"])
        row["explain_text"] = explain_text(row, tags, row["structure_status"])
        row["strength_score_raw"] = max(0, 2.0 - row["missing_tag_count"] * 0.2)
        return row

    @staticmethod
    def _is_deadlock(exc: Exception) -> bool:
        if isinstance(exc, SQLAlchemyOperationalError):
            orig = getattr(exc, "orig", None)
            return isinstance(orig, PyMySQLOperationalError) and orig.args and orig.args[0] == 1213
        return isinstance(exc, PyMySQLOperationalError) and exc.args and exc.args[0] == 1213

    def _write_signal_with_retry(self, batch_id: int, analysis: dict[str, Any], max_retries: int = 5) -> None:
        tags = build_tags(analysis)
        signal_time_i = int(analysis["signal_time"].replace("-", "").replace(":", "").replace(" ", "")[:14])
        for attempt in range(1, max_retries + 1):
            try:
                analysis_id = self.repo.upsert_analysis(analysis)
                self.repo.replace_tags(
                    analysis_id,
                    batch_id,
                    analysis["code"],
                    signal_time_i,
                    tags,
                )
                self.db.commit()
                return
            except Exception as exc:
                self.db.rollback()
                if self._is_deadlock(exc) and attempt < max_retries:
                    time.sleep(0.1 * (2 ** (attempt - 1)))
                    continue
                raise

    def _write_signal_batch_with_retry(self, batch_id: int, analyses: list[dict[str, Any]], max_retries: int = 5) -> None:
        if not analyses:
            return
        for attempt in range(1, max_retries + 1):
            try:
                for analysis in analyses:
                    tags = build_tags(analysis)
                    signal_time_i = int(analysis["signal_time"].replace("-", "").replace(":", "").replace(" ", "")[:14])
                    analysis_id = self.repo.upsert_analysis(analysis)
                    self.repo.replace_tags(
                        analysis_id,
                        batch_id,
                        analysis["code"],
                        signal_time_i,
                        tags,
                    )
                self.db.commit()
                return
            except Exception as exc:
                self.db.rollback()
                if self._is_deadlock(exc) and attempt < max_retries:
                    time.sleep(0.1 * (2 ** (attempt - 1)))
                    continue
                raise

    def run(self, market: str = "all", trade_date: str | None = None, limit_codes: int | None = None) -> dict[str, Any]:
        cfg = ConfigService(self.db).load_strategy_config()
        trade_date = trade_date or self.latest_trade_date(market)
        if not trade_date:
            return {"ok": False, "processed": 0, "signals": 0, "errors": ["no daily data"]}

        batch_id = int(time.strftime("%Y%m%d%H%M%S"))
        self.repo.insert_batch({
            "batch_id": batch_id,
            "batch_name": f"S2560-fast-{batch_id}",
            "run_time": datetime.now(),
            "data_source": "clickhouse_fast",
            "strategy_code": "S2560",
            "strategy_version": self.strategy_version,
            "param_snapshot": json.dumps(cfg, ensure_ascii=False),
            "status": "running",
            "message": f"fast scan started market={market} trade_date={trade_date}",
        })
        self.db.commit()

        t0 = time.time()
        rows = get_clickhouse().query(self._candidate_sql(market, trade_date, cfg, limit_codes))
        self._apply_signal_window_confirmation(
            rows,
            self._load_signal_window_rows([r["code"] for r in rows], trade_date),
            cfg,
        )
        names = self._load_stock_names([r["code"] for r in rows])
        write_batch_size = max(1, int(os.getenv("FAST_2560_WRITE_BATCH_SIZE", "250")))
        pending: list[dict[str, Any]] = []
        for r in rows:
            pending.append(self._analysis_row(batch_id, cfg, names, r))
            if len(pending) >= write_batch_size:
                self._write_signal_batch_with_retry(batch_id, pending)
                pending = []
        self._write_signal_batch_with_retry(batch_id, pending)
        self.repo.update_batch_status(batch_id, "success", f"fast market={market}, trade_date={trade_date}, signals={len(rows)}, elapsed={time.time()-t0:.1f}s")
        self.db.commit()
        return {
            "ok": True,
            "batch_id": batch_id,
            "market": market,
            "trade_date": trade_date,
            "processed": len(rows),
            "signals": len(rows),
            "elapsed_seconds": round(time.time() - t0, 1),
            "errors": [],
        }

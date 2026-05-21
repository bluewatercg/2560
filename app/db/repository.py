from __future__ import annotations
from typing import Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.clickhouse import get_clickhouse


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    return bool(db.execute(text("""
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND column_name = :column_name
    """), {"table_name": table_name, "column_name": column_name}).scalar() or 0)


def ensure_analysis_batch_columns(db: Session) -> None:
    columns = {
        "batch_name": "ALTER TABLE analysis_batch ADD COLUMN batch_name VARCHAR(255) NULL AFTER batch_id",
        "data_source": "ALTER TABLE analysis_batch ADD COLUMN data_source VARCHAR(100) NULL AFTER run_time",
        "param_snapshot": "ALTER TABLE analysis_batch ADD COLUMN param_snapshot JSON NULL AFTER strategy_version",
    }
    for column, ddl in columns.items():
        if not _column_exists(db, "analysis_batch", column):
            db.execute(text(ddl))
    db.commit()


class KlineRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_codes(self, source: Optional[str] = None, limit: Optional[int] = None) -> list[str]:
        sql = 'SELECT code FROM stock_info'
        params = {}
        if source:
            sql += ' WHERE source=:source'
            params['source'] = source
        sql += ' ORDER BY code'
        if limit:
            sql += ' LIMIT :limit'
            params['limit'] = limit
        return [r[0] for r in self.db.execute(text(sql), params).all()]

    def get_stock_info(self, code: str) -> dict:
        row = self.db.execute(text('SELECT * FROM stock_info WHERE code=:code'), {'code': code}).mappings().first()
        return dict(row) if row else {'code': code, 'name': None}

    def read_daily(self, code: str, source: Optional[str] = None, lookback: Optional[int] = None) -> pd.DataFrame:
        sf = f" AND source='{source}'" if source else ""
        rows = get_clickhouse().query(
            f"SELECT code,date,open,high,low,close,volume,amount,source FROM daily_kline WHERE code='{code}'{sf} ORDER BY date"
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        # Convert ClickHouse Date strings to int YYYYMMDD
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d').astype(int)
        return df.tail(lookback).reset_index(drop=True) if lookback else df.reset_index(drop=True)

    def read_minute(self, code: str, period: str, source: Optional[str] = None, lookback: Optional[int] = None) -> pd.DataFrame:
        sf = f" AND source='{source}'" if source else ""
        rows = get_clickhouse().query(
            f"SELECT code,date,open,high,low,close,volume,amount,source FROM minute_kline_period WHERE code='{code}' AND period='{period}'{sf} ORDER BY date"
        )
        if not rows:
            df = pd.DataFrame()
        else:
            df = pd.DataFrame(rows)
            # Convert ClickHouse DateTime64 strings to int YYYYMMDDHHMMSS
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d%H%M%S').astype(int)
        return df.tail(lookback).reset_index(drop=True) if lookback and not df.empty else df.reset_index(drop=True)

    def upsert_indicators(self, rows: list[dict]) -> None:
        """Batch insert indicators. Assumes stale data was already deleted by delete_indicators_for_code()."""
        if not rows:
            return
        ch = get_clickhouse()
        ch.insert_batch("technical_indicator", rows)

    def delete_indicators_for_code(self, code: str) -> None:
        """Delete all indicators for one stock across all periods — one mutation per period instead of one per row."""
        ch = get_clickhouse()
        for period in ("daily", "30m", "5m"):
            try:
                ch.command(f"ALTER TABLE {ch.database}.technical_indicator DELETE WHERE code='{code}' AND period='{period}'")
            except Exception:
                pass  # Some periods may not have data for this stock

    def insert_batch(self, batch: dict) -> None:
        ensure_analysis_batch_columns(self.db)
        self.db.execute(text("""
            INSERT INTO analysis_batch (batch_id,batch_name,run_time,data_source,strategy_code,strategy_version,param_snapshot,status,message)
            VALUES (:batch_id,:batch_name,:run_time,:data_source,:strategy_code,:strategy_version,:param_snapshot,:status,:message)
            ON DUPLICATE KEY UPDATE status=VALUES(status), message=VALUES(message), updated_at=CURRENT_TIMESTAMP
        """), batch)

    def update_batch_status(self, batch_id: int, status: str, message: str = '') -> None:
        self.db.execute(text('UPDATE analysis_batch SET status=:status,message=:message WHERE batch_id=:batch_id'), {'batch_id': batch_id, 'status': status, 'message': message})

    def upsert_analysis(self, row: dict) -> int:
        self.db.execute(text("""
            INSERT INTO structure_2560_analysis
            (signal_uid,batch_id,strategy_code,strategy_version,code,name,signal_time,signal_period,price,source,stock_status,has_2560_signal,price_near_ma25,ma25_slope_ok,volume_structure_ok,abnormal_filter_ok,trend_price_ok,trend_slope_ok,volatility_ok,breakout_ok,volume_ok,near_resistance,pullback_ok,bullish_confirm,structure_status,strength_score_raw,missing_tags,missing_tag_count,explain_text,data_quality_status,is_duplicate_signal,selected_signal)
            VALUES
            (:signal_uid,:batch_id,:strategy_code,:strategy_version,:code,:name,:signal_time,:signal_period,:price,:source,:stock_status,:has_2560_signal,:price_near_ma25,:ma25_slope_ok,:volume_structure_ok,:abnormal_filter_ok,:trend_price_ok,:trend_slope_ok,:volatility_ok,:breakout_ok,:volume_ok,:near_resistance,:pullback_ok,:bullish_confirm,:structure_status,:strength_score_raw,:missing_tags,:missing_tag_count,:explain_text,:data_quality_status,:is_duplicate_signal,:selected_signal)
            ON DUPLICATE KEY UPDATE
            batch_id=VALUES(batch_id),name=VALUES(name),price=VALUES(price),structure_status=VALUES(structure_status),strength_score_raw=VALUES(strength_score_raw),missing_tags=VALUES(missing_tags),missing_tag_count=VALUES(missing_tag_count),explain_text=VALUES(explain_text),data_quality_status=VALUES(data_quality_status),updated_at=CURRENT_TIMESTAMP
        """), row)
        return int(self.db.execute(text('SELECT id FROM structure_2560_analysis WHERE signal_uid=:uid'), {'uid': row['signal_uid']}).scalar_one())

    def replace_tags(self, analysis_id: int, batch_id: int, code: str, signal_time: int, tags: list[dict]) -> None:
        # Use INSERT IGNORE instead of DELETE+INSERT to avoid deadlocks on concurrent batch runs.
        # For fresh batches tags are always new; for re-runs IGNORE skips duplicates.
        if not tags:
            return
        rows = [{'analysis_id': analysis_id, 'batch_id': batch_id, 'code': code, 'signal_time': signal_time, **t} for t in tags]
        self.db.execute(text("""
            INSERT IGNORE INTO structure_2560_tag_detail (analysis_id,batch_id,code,signal_time,tag_code,tag_name,tag_type)
            VALUES (:analysis_id,:batch_id,:code,:signal_time,:tag_code,:tag_name,:tag_type)
        """), rows)

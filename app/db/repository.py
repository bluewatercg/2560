from __future__ import annotations
from typing import Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session


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
        sql = 'SELECT code,date,open,high,low,close,volume,amount,source FROM daily_kline WHERE code=:code'
        params = {'code': code}
        if source:
            sql += ' AND source=:source'
            params['source'] = source
        sql += ' ORDER BY date'
        df = pd.read_sql(text(sql), self.db.bind, params=params)
        return df.tail(lookback).reset_index(drop=True) if lookback else df.reset_index(drop=True)

    def read_minute(self, code: str, period: str, source: Optional[str] = None, lookback: Optional[int] = None) -> pd.DataFrame:
        params = {'code': code, 'period': period}
        sf = ''
        if source:
            params['source'] = source
            sf = ' AND source=:source'
        try:
            df = pd.read_sql(text(f"""
                SELECT code,date,period,open,high,low,close,volume,amount,source
                FROM minute_kline_period
                WHERE code=:code AND period=:period {sf}
                ORDER BY date
            """), self.db.bind, params=params)
        except Exception:
            df = pd.DataFrame()
        if df.empty and period == '5m':
            params = {'code': code}
            sf = ''
            if source:
                params['source'] = source
                sf = ' AND source=:source'
            df = pd.read_sql(text(f"""
                SELECT code,date,'5m' AS period,open,high,low,close,volume,amount,source
                FROM minute_kline
                WHERE code=:code {sf}
                ORDER BY date
            """), self.db.bind, params=params)
        return df.tail(lookback).reset_index(drop=True) if lookback and not df.empty else df.reset_index(drop=True)

    def upsert_indicators(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.db.execute(text("""
            INSERT INTO technical_indicator
            (code,period,date,source,stock_status,is_st,ma25,ma60,ma200,ma25_slope_3,ma60_slope_3,atr14,atr20_avg,vol_ma5,vol_ma60,vol_ratio,vol_ma5_cross_vol_ma60,price_ma25_deviation_pct,high_20,low_20,low_30,resistance_level,is_abnormal_bar,data_quality_status)
            VALUES
            (:code,:period,:date,:source,:stock_status,:is_st,:ma25,:ma60,:ma200,:ma25_slope_3,:ma60_slope_3,:atr14,:atr20_avg,:vol_ma5,:vol_ma60,:vol_ratio,:vol_ma5_cross_vol_ma60,:price_ma25_deviation_pct,:high_20,:low_20,:low_30,:resistance_level,:is_abnormal_bar,:data_quality_status)
            ON DUPLICATE KEY UPDATE
            ma25=VALUES(ma25),ma60=VALUES(ma60),ma200=VALUES(ma200),ma25_slope_3=VALUES(ma25_slope_3),ma60_slope_3=VALUES(ma60_slope_3),atr14=VALUES(atr14),atr20_avg=VALUES(atr20_avg),vol_ma5=VALUES(vol_ma5),vol_ma60=VALUES(vol_ma60),vol_ratio=VALUES(vol_ratio),vol_ma5_cross_vol_ma60=VALUES(vol_ma5_cross_vol_ma60),price_ma25_deviation_pct=VALUES(price_ma25_deviation_pct),high_20=VALUES(high_20),low_20=VALUES(low_20),low_30=VALUES(low_30),resistance_level=VALUES(resistance_level),is_abnormal_bar=VALUES(is_abnormal_bar),data_quality_status=VALUES(data_quality_status),updated_at=CURRENT_TIMESTAMP
        """), rows)

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
        self.db.execute(text('DELETE FROM structure_2560_tag_detail WHERE analysis_id=:id'), {'id': analysis_id})
        if not tags:
            return
        rows = [{'analysis_id': analysis_id, 'batch_id': batch_id, 'code': code, 'signal_time': signal_time, **t} for t in tags]
        self.db.execute(text("""
            INSERT INTO structure_2560_tag_detail (analysis_id,batch_id,code,signal_time,tag_code,tag_name,tag_type)
            VALUES (:analysis_id,:batch_id,:code,:signal_time,:tag_code,:tag_name,:tag_type)
        """), rows)

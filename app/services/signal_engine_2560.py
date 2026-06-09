import hashlib
import json
import time
from datetime import datetime
from typing import Optional
import pandas as pd
from app.db.repository import KlineRepository
from app.services.config_service import ConfigService
from app.services.canonical_signal_engine import build_canonical_fields_from_legacy_signal, legacy_volume_structure_ok
from app.services.indicator_engine import enrich_indicators, to_indicator_rows
from app.services.tag_service import build_tags, structure_status, explain_text

class SignalEngine2560:
    def __init__(self, db, strategy_version: str = '2.4.0'):
        self.db = db
        self.repo = KlineRepository(db)
        self.strategy_version = strategy_version

    @staticmethod
    def day(value: int) -> int:
        return int(str(int(value))[:8])

    def uid(self, code: str, signal_time: int, period: str) -> str:
        return hashlib.md5(f'{code}|{signal_time}|{period}|{self.strategy_version}'.encode()).hexdigest()

    def run(self, codes: Optional[list[str]] = None, source: Optional[str] = None, limit: Optional[int] = None, commit_every: int = 50) -> dict:
        cfg = ConfigService(self.db).load_strategy_config()
        batch_id = int(time.strftime('%Y%m%d%H%M%S'))
        self.repo.insert_batch({'batch_id': batch_id, 'batch_name': f'S2560-{batch_id}', 'run_time': datetime.now(), 'data_source': source, 'strategy_code': 'S2560', 'strategy_version': self.strategy_version, 'param_snapshot': json.dumps(cfg, ensure_ascii=False), 'status': 'running', 'message': 'started'})
        self.db.commit()
        all_codes = codes or self.repo.list_codes(source=source, limit=limit)
        processed = 0
        signals = 0
        errors = []
        for code in all_codes:
            try:
                info = self.repo.get_stock_info(code)
                name = (info.get('name') or '').upper()
                if 'ST' in name:
                    processed += 1
                    continue
                daily = self.repo.read_daily(code, source=source, lookback=320)
                m30 = self.repo.read_minute(code, '30m', source=source, lookback=3000)
                m5 = self.repo.read_minute(code, '5m', source=source, lookback=6000)
                if daily.empty or m30.empty:
                    processed += 1
                    continue
                daily_i = enrich_indicators(daily, 'daily', source, cfg)
                m30_i = enrich_indicators(m30, '30m', source, cfg)
                m5_i = enrich_indicators(m5, '5m', source, cfg) if not m5.empty else pd.DataFrame()
                # Delete old indicators once per stock (1 mutation per period), then insert fresh ones
                self.repo.delete_indicators_for_code(code)
                self.repo.upsert_indicators(to_indicator_rows(daily_i.tail(260)))
                self.repo.upsert_indicators(to_indicator_rows(m30_i.tail(1200)))
                if not m5_i.empty:
                    self.repo.upsert_indicators(to_indicator_rows(m5_i.tail(1200)))
                signals += self.scan(code, info, daily_i, m30_i, m5_i, cfg, batch_id, source)
                processed += 1
                if processed % commit_every == 0:
                    self.db.commit()
            except Exception as exc:
                self.db.rollback()
                errors.append(f'{code}: {exc}')
                processed += 1
        self.repo.update_batch_status(batch_id, 'success', f'processed={processed}, signals={signals}, errors={len(errors)}')
        self.db.commit()
        return {'batch_id': batch_id, 'processed': processed, 'signals': signals, 'errors': errors[:20]}

    def prev_daily(self, daily_i: pd.DataFrame, signal_time: int):
        subset = daily_i[daily_i['date'] < self.day(signal_time)]
        return None if subset.empty else subset.iloc[-1]

    def confirm5(self, m5_i: pd.DataFrame, signal_time: int, cfg: dict):
        if m5_i.empty:
            return False, False
        confirm_bars = int(cfg.get('confirm_5m_bars', 6))
        window = m5_i[m5_i['date'] < signal_time].tail(confirm_bars)
        if window.empty:
            return False, False
        last = window.iloc[-1]
        pull = bool(pd.notna(last.get('ma25')) and (last['close'] >= last['ma25'] or abs(last.get('price_ma25_deviation_pct', 999)) <= float(cfg.get('pullback_threshold_pct', 2.0))))
        bullish = bool((window.tail(2)['close'] > window.tail(2)['open']).any())
        return pull, bullish

    def scan(self, code, info, daily_i, m30_i, m5_i, cfg, batch_id, source):
        count = 0
        threshold = float(cfg.get('pullback_threshold_pct', 2.0))
        min_volume = float(cfg.get('min_volume_ratio', 1.0))
        slope_threshold = float(cfg.get('ma_slope_medium_threshold', 0.0))
        cooldown = int(cfg.get('signal_cooldown_days', 3))
        last_day = None
        for _, r in m30_i.tail(600).iterrows():
            if pd.isna(r.get('ma25')) or pd.isna(r.get('vol_ma60')):
                continue
            signal_time = int(r['date'])
            signal_day = self.day(signal_time)
            if last_day and signal_day - last_day < cooldown:
                continue
            price_near = abs(r.get('price_ma25_deviation_pct', 999)) <= threshold
            slope_ok = (r.get('ma25_slope_3') if pd.notna(r.get('ma25_slope_3')) else -999) >= slope_threshold
            volume_ok = legacy_volume_structure_ok(dict(r), cfg, base_ratio=min_volume)
            abnormal_ok = r.get('is_abnormal_bar', 1) == 0
            if not (price_near and slope_ok and volume_ok and abnormal_ok):
                continue
            daily_prev = self.prev_daily(daily_i, signal_time)
            trend_price = trend_slope = volatility = False
            data_quality = 'missing'
            if daily_prev is not None:
                ma = daily_prev.get('ma60') if pd.notna(daily_prev.get('ma60')) else daily_prev.get('ma25')
                sl = daily_prev.get('ma60_slope_3') if pd.notna(daily_prev.get('ma60_slope_3')) else daily_prev.get('ma25_slope_3')
                trend_price = bool(pd.notna(ma) and daily_prev['close'] > ma)
                trend_slope = bool(pd.notna(sl) and sl > slope_threshold)
                volatility = bool(pd.notna(daily_prev.get('atr14')) and pd.notna(daily_prev.get('atr20_avg')) and daily_prev['atr14'] > daily_prev['atr20_avg'] * float(cfg.get('atr_weak_ratio', 0.85)))
                data_quality = 'normal'
            pullback, bullish = self.confirm5(m5_i, signal_time, cfg)
            breakout = bool(pd.notna(r.get('high_20')) and r['close'] > r['high_20'] * float(cfg.get('breakout_threshold', 1.0)))
            near = bool(pd.notna(r.get('high_20')) and r['close'] >= r['high_20'] * float(cfg.get('resistance_threshold', 0.95)))
            row = {'signal_uid': self.uid(code, signal_time, '30m'), 'batch_id': batch_id, 'strategy_code': 'S2560', 'strategy_version': self.strategy_version, 'code': code, 'name': info.get('name'), 'signal_time': signal_time, 'signal_period': '30m', 'price': float(r['close']), 'source': source or r.get('source'), 'stock_status': 'NORMAL', 'has_2560_signal': 1, 'price_near_ma25': int(price_near), 'ma25_slope_ok': int(slope_ok), 'volume_structure_ok': int(volume_ok), 'abnormal_filter_ok': int(abnormal_ok), 'trend_price_ok': int(trend_price), 'trend_slope_ok': int(trend_slope), 'volatility_ok': int(volatility), 'breakout_ok': int(breakout), 'volume_ok': int(volume_ok), 'near_resistance': int(near), 'pullback_ok': int(pullback), 'bullish_confirm': int(bullish), 'data_quality_status': data_quality, 'is_duplicate_signal': 0, 'selected_signal': 1, 'structure_status': '', 'strength_score_raw': 0, 'missing_tags': '', 'missing_tag_count': 0, 'explain_text': ''}
            canonical_context = {'market_state': 'unknown', 'environment_score': 0.4, 'hot_topic_strength': 'none', 'position_in_hot_topic': 'edge'}
            row.update(build_canonical_fields_from_legacy_signal(row, dict(r), canonical_context, cfg))
            tags = build_tags(row)
            row['structure_status'] = structure_status(tags)
            row['missing_tags'] = json.dumps([t['tag_name'] for t in tags])
            row['missing_tag_count'] = len([t for t in tags if t.get('tag_type') == 'negative'])
            row['explain_text'] = explain_text(row, tags, row['structure_status'])
            row['strength_score_raw'] = max(0, 2.0 - row['missing_tag_count'] * 0.2)
            analysis_id = self.repo.upsert_analysis(row)
            self.repo.replace_tags(analysis_id, batch_id, code, signal_time, tags)
            last_day = signal_day
            count += 1
        return count

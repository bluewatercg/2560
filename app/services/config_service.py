from __future__ import annotations
from typing import Any

try:
    from sqlalchemy import text
except ModuleNotFoundError:
    def text(statement: str) -> str:
        return statement

try:
    from sqlalchemy.orm import Session
except ModuleNotFoundError:
    Session = Any

DEFAULT_CONFIG: dict[str, Any] = {
    'ma_price_period': 25,
    'vol_short_period': 5,
    'vol_long_period': 60,
    'atr_period': 14,
    'atr_compare_period': 20,
    'breakout_period': 20,
    'core_pullback_pct': 3.0,
    'pullback_max_pct': 5.0,
    'recent_3d_normal_max': 12.0,
    'recent_3d_warm_max': 18.0,
    'recent_3d_acceleration_max': 20.0,
    'recent_3d_overheat_min': 20.0,
    'high_window_30m': 20,
    'confirm_5m_bars': 6,
    'volume_cross_fallback_enabled': True,
    'volume_cross_confirm_ratio': 0.9,
    'market_state_enabled': True,
    'rebound_index_pct_min': 0.5,
    'rebound_limitup_min': 30,
    'rebound_up_ratio_min': 0.6,
    'hot_topic_required': True,
    'hot_topic_strength_required': 'medium',
    'position_required_for_focus': 'strong',
    'focus_score_min': 0.75,
    'watch_score_min': 0.45,
    'auction_amplify_ratio': 1.0,
    'auction_gap_pct_max': 3.0,
    'auction_fallback_to_avg5': True,
    'avg5_min_valid_days': 3,
    'display_emoji_enabled': False,
    'pullback_threshold_pct': 5.0,
    'min_volume_ratio': 0.9,
    'resistance_threshold': 0.95,
    'breakout_threshold': 1.0,
    'atr_weak_ratio': 0.85,
    'signal_cooldown_days': 3,
    'ma_slope_medium_threshold': 0.0,
}

DEPRECATED_DB_KEYS = {
    'ma_short',
    'ma_mid',
    'ma_long',
    'slope_periods',
    'vol_short',
    'vol_long',
    'atp_period',
    'high_low_window',
}

CANONICAL_COMPAT_KEYS = {
    'pullback_threshold_pct': 'pullback_max_pct',
    'min_volume_ratio': 'volume_cross_confirm_ratio',
}


def _cast(value: str, value_type: str):
    if value_type == 'int':
        return int(float(value))
    if value_type == 'double':
        return float(value)
    if value_type == 'bool':
        return str(value).lower() in {'1','true','yes','y'}
    return value


def _apply_compat_mappings(cfg: dict[str, Any]) -> None:
    for compat_key, canonical_key in CANONICAL_COMPAT_KEYS.items():
        cfg[compat_key] = cfg[canonical_key]


class ConfigService:
    def __init__(self, db: Session):
        self.db = db

    def load_strategy_config(self, strategy_code: str = 'S2560') -> dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG)
        try:
            rows = self.db.execute(text('SELECT config_key,config_value,value_type FROM strategy_config WHERE strategy_code=:s AND enabled=1'), {'s': strategy_code}).mappings().all()
            for r in rows:
                if r['config_key'] in DEPRECATED_DB_KEYS:
                    continue
                cfg[r['config_key']] = _cast(r['config_value'], r['value_type'])
        except Exception:
            pass
        _apply_compat_mappings(cfg)
        return cfg

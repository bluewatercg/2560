from __future__ import annotations
from typing import Any, Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_CONFIG: dict[str, Any] = {
    'ma_price_period': 25,
    'vol_short_period': 5,
    'vol_long_period': 60,
    'pullback_threshold_pct': 2.0,
    'min_volume_ratio': 1.0,
    'resistance_threshold': 0.95,
    'breakout_threshold': 1.0,
    'atr_period': 14,
    'atr_compare_period': 20,
    'atr_weak_ratio': 0.85,
    'breakout_period': 20,
    'signal_cooldown_days': 3,
    'ma_slope_medium_threshold': 0.0,
}

def _cast(value: str, value_type: str):
    if value_type == 'int':
        return int(float(value))
    if value_type == 'double':
        return float(value)
    if value_type == 'bool':
        return str(value).lower() in {'1','true','yes','y'}
    return value

class ConfigService:
    def __init__(self, db: Session):
        self.db = db

    def load_strategy_config(self, strategy_code: str = 'S2560') -> dict[str, Any]:
        cfg = dict(DEFAULT_CONFIG)
        try:
            rows = self.db.execute(text('SELECT config_key,config_value,value_type FROM strategy_config WHERE strategy_code=:s AND enabled=1'), {'s': strategy_code}).mappings().all()
            for r in rows:
                cfg[r['config_key']] = _cast(r['config_value'], r['value_type'])
        except Exception:
            pass
        return cfg

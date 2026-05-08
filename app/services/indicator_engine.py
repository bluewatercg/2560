import numpy as np
import pandas as pd

def slope_pct(series: pd.Series, periods: int = 3) -> pd.Series:
    prev = series.shift(periods)
    return (series - prev) / prev.replace(0, np.nan) * 100.0

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df['close'].shift(1)
    tr = pd.concat([(df['high']-df['low']), (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def enrich_indicators(df: pd.DataFrame, period: str, source: str | None, cfg: dict, stock_status: str = 'NORMAL', is_st: int = 0) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy().sort_values('date').reset_index(drop=True)
    out['period'] = period
    if 'source' not in out.columns:
        out['source'] = source or 'default'
    for col in ['open','high','low','close','volume','amount']:
        out[col] = pd.to_numeric(out[col], errors='coerce')
    ma_period = int(cfg.get('ma_price_period', 25))
    vol_short = int(cfg.get('vol_short_period', 5))
    vol_long = int(cfg.get('vol_long_period', 60))
    atr_period = int(cfg.get('atr_period', 14))
    atr_compare = int(cfg.get('atr_compare_period', 20))
    breakout_period = int(cfg.get('breakout_period', 20))
    out['ma25'] = out['close'].rolling(ma_period, min_periods=ma_period).mean()
    out['ma60'] = out['close'].rolling(60, min_periods=60).mean()
    out['ma200'] = out['close'].rolling(200, min_periods=200).mean()
    out['ma25_slope_3'] = slope_pct(out['ma25'])
    out['ma60_slope_3'] = slope_pct(out['ma60'])
    out['atr14'] = atr(out, atr_period)
    out['atr20_avg'] = out['atr14'].rolling(atr_compare, min_periods=atr_compare).mean()
    out['vol_ma5'] = out['volume'].rolling(vol_short, min_periods=vol_short).mean()
    out['vol_ma60'] = out['volume'].rolling(vol_long, min_periods=vol_long).mean()
    out['vol_ratio'] = out['vol_ma5'] / out['vol_ma60'].replace(0, np.nan)
    out['vol_ma5_cross_vol_ma60'] = ((out['vol_ratio'].shift(1) <= 1.0) & (out['vol_ratio'] > 1.0)).astype('Int64')
    out['price_ma25_deviation_pct'] = (out['close'] - out['ma25']) / out['ma25'].replace(0, np.nan) * 100.0
    out['high_20'] = out['high'].shift(1).rolling(breakout_period, min_periods=breakout_period).max()
    out['low_20'] = out['low'].shift(1).rolling(20, min_periods=20).min()
    out['low_30'] = out['low'].shift(1).rolling(30, min_periods=30).min()
    out['resistance_level'] = out['high_20']
    out['is_abnormal_bar'] = (out[['open','high','low','close','volume']].isna().any(axis=1) | ((out['open']==out['high']) & (out['high']==out['low']) & (out['low']==out['close'])) | (out['volume'].fillna(0)<=0)).astype(int)
    out['data_quality_status'] = np.where(out['is_abnormal_bar'] == 1, 'abnormal', 'normal')
    out['stock_status'] = stock_status
    out['is_st'] = is_st
    return out

def to_indicator_rows(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    cols = ['code','period','date','source','stock_status','is_st','ma25','ma60','ma200','ma25_slope_3','ma60_slope_3','atr14','atr20_avg','vol_ma5','vol_ma60','vol_ratio','vol_ma5_cross_vol_ma60','price_ma25_deviation_pct','high_20','low_20','low_30','resistance_level','is_abnormal_bar','data_quality_status']
    return df[cols].replace({np.nan: None}).to_dict('records')

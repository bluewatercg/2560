import numpy as np
import pandas as pd


def _indicator_datetime(value, period: str):
    if pd.isna(value):
        return None
    if isinstance(value, (np.integer, int)):
        text = str(int(value))
    elif isinstance(value, (np.floating, float)) and np.isfinite(value) and float(value).is_integer():
        text = str(int(value))
    else:
        text = str(value)

    if text.isdigit():
        if period == 'daily':
            text = text[:8]
            return f'{text[:4]}-{text[4:6]}-{text[6:8]} 00:00:00'
        text = text[:14].ljust(14, '0')
        return f'{text[:4]}-{text[4:6]}-{text[6:8]} {text[8:10]}:{text[10:12]}:{text[12:14]}'

    dt = pd.to_datetime(value)
    if period == 'daily':
        return dt.strftime('%Y-%m-%d 00:00:00')
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def slope_pct(series: pd.Series, periods: int = 3) -> pd.Series:
    prev = series.shift(periods)
    return (series - prev) / prev.replace(0, np.nan) * 100.0

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df['close'].shift(1)
    tr = pd.concat([(df['high']-df['low']), (df['high']-prev_close).abs(), (df['low']-prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _rising_streak(series: pd.Series) -> pd.Series:
    streak = []
    current = 0
    for value in series.fillna(False):
        current = current + 1 if bool(value) else 0
        streak.append(current)
    return pd.Series(streak, index=series.index, dtype="int64")


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
    out['recent_3d_pct'] = (out['close'] - out['close'].shift(3)) / out['close'].shift(3).replace(0, np.nan) * 100.0
    out['recent_5d_pct'] = (out['close'] - out['close'].shift(5)) / out['close'].shift(5).replace(0, np.nan) * 100.0
    out['ma25_slope_days'] = _rising_streak(out['ma25'].diff() > 0)
    out['ma25_angle_deg'] = np.degrees(np.arctan(out['ma25'].diff() / out['ma25'].shift(1).replace(0, np.nan) * 100.0))
    out['ma5_slope_dir'] = np.sign(out['close'].rolling(5, min_periods=5).mean().diff()).fillna(0).astype(int)
    low_n = out['low'].rolling(9, min_periods=9).min()
    high_n = out['high'].rolling(9, min_periods=9).max()
    rsv = (out['close'] - low_n) / (high_n - low_n).replace(0, np.nan) * 100.0
    out['kdj_k'] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    out['kdj_d'] = out['kdj_k'].ewm(alpha=1 / 3, adjust=False).mean()
    out['kdj_j'] = 3 * out['kdj_k'] - 2 * out['kdj_d']
    out['kdj_j_cross_up'] = ((out['kdj_j'].shift(1) <= out['kdj_d'].shift(1)) & (out['kdj_j'] > out['kdj_d'])).astype(int)
    out['kdj_j_over_100'] = (out['kdj_j'] > 100).astype(int)
    ema12 = out['close'].ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = out['close'].ewm(span=26, adjust=False, min_periods=26).mean()
    out['macd_dif'] = ema12 - ema26
    out['macd_dea'] = out['macd_dif'].ewm(span=9, adjust=False, min_periods=9).mean()
    out['macd_hist'] = (out['macd_dif'] - out['macd_dea']) * 2
    out['macd_hist_green_shrink'] = ((out['macd_hist'] < 0) & (out['macd_hist'] > out['macd_hist'].shift(1))).astype(int)
    out['macd_hist_red_extend'] = ((out['macd_hist'] > 0) & (out['macd_hist'] > out['macd_hist'].shift(1))).astype(int)
    out['is_abnormal_bar'] = (out[['open','high','low','close','volume']].isna().any(axis=1) | ((out['open']==out['high']) & (out['high']==out['low']) & (out['low']==out['close'])) | (out['volume'].fillna(0)<=0)).astype(int)
    out['data_quality_status'] = np.where(out['is_abnormal_bar'] == 1, 'abnormal', 'normal')
    out['stock_status'] = stock_status
    out['is_st'] = is_st
    return out

def to_indicator_rows(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    cols = ['code','period','date','source','stock_status','is_st','ma25','ma60','ma200','ma25_slope_3','ma60_slope_3','atr14','atr20_avg','vol_ma5','vol_ma60','vol_ratio','vol_ma5_cross_vol_ma60','price_ma25_deviation_pct','high_20','low_20','low_30','resistance_level','kdj_k','kdj_d','kdj_j','kdj_j_cross_up','kdj_j_over_100','macd_dif','macd_dea','macd_hist','macd_hist_green_shrink','macd_hist_red_extend','ma25_slope_days','ma25_angle_deg','ma5_slope_dir','recent_3d_pct','recent_5d_pct','is_abnormal_bar','data_quality_status']
    out = df[cols].replace({np.nan: None}).copy()
    out['date'] = [_indicator_datetime(row.date, row.period) for row in out.itertuples(index=False)]
    return out.to_dict('records')

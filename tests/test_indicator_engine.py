import importlib.util
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_indicator_engine():
    spec = importlib.util.spec_from_file_location(
        "indicator_engine_under_test",
        PROJECT_ROOT / "app/services/indicator_engine.py",
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_indicator_engine = _load_indicator_engine()
enrich_indicators = _indicator_engine.enrich_indicators
to_indicator_rows = _indicator_engine.to_indicator_rows


def _indicator_bar(idx: int, close: float | None = None, high: float | None = None) -> dict:
    price = float(close if close is not None else 10 + idx * 0.1)
    return {
        "code": "sh.600000",
        "date": 20260501 + idx,
        "open": price - 0.05,
        "high": float(high if high is not None else price + 0.1),
        "low": price - 0.1,
        "close": price,
        "volume": 1000 + idx * 10,
        "amount": price * (1000 + idx * 10),
        "source": "vipdoc",
    }


def test_enrich_indicators_high_20_excludes_current_bar():
    rows = [_indicator_bar(idx, high=10 + idx) for idx in range(25)]
    rows[-1]["high"] = 999

    out = enrich_indicators(pd.DataFrame(rows), "30m", "vipdoc", {"breakout_period": 20})

    assert out.iloc[-1]["high_20"] == max(row["high"] for row in rows[-21:-1])


def test_enrich_indicators_adds_recent_gain_fields():
    rows = [_indicator_bar(idx, close=10.0) for idx in range(8)]
    rows[-6]["close"] = 9.5
    rows[-4]["close"] = 10.0
    rows[-1]["close"] = 11.9

    out = enrich_indicators(pd.DataFrame(rows), "daily", "vipdoc", {})

    assert round(out.iloc[-1]["recent_3d_pct"], 2) == 19.0
    assert round(out.iloc[-1]["recent_5d_pct"], 2) == 25.26


def test_enrich_indicators_adds_kdj_and_macd_fields():
    rows = [_indicator_bar(idx) for idx in range(40)]

    out = enrich_indicators(pd.DataFrame(rows), "daily", "vipdoc", {})
    last = out.iloc[-1]

    for field in [
        "kdj_k",
        "kdj_d",
        "kdj_j",
        "kdj_j_cross_up",
        "kdj_j_over_100",
        "macd_dif",
        "macd_dea",
        "macd_hist",
        "macd_hist_green_shrink",
        "macd_hist_red_extend",
        "ma25_slope_days",
        "ma25_angle_deg",
        "ma5_slope_dir",
    ]:
        assert field in out.columns

    assert pd.notna(last["kdj_k"])
    assert pd.notna(last["macd_dif"])
    assert last["kdj_j_cross_up"] in (0, 1)
    assert last["macd_hist_green_shrink"] in (0, 1)


def test_to_indicator_rows_formats_daily_date_for_clickhouse_datetime64():
    df = pd.DataFrame(
        [
            {
                "code": "sh.600000",
                "period": "daily",
                "date": 20260519,
                "source": "vipdoc",
                "stock_status": "NORMAL",
                "is_st": 0,
                "ma25": 10.0,
                "ma60": 9.0,
                "ma200": None,
                "ma25_slope_3": None,
                "ma60_slope_3": None,
                "atr14": None,
                "atr20_avg": None,
                "vol_ma5": None,
                "vol_ma60": None,
                "vol_ratio": None,
                "vol_ma5_cross_vol_ma60": 0,
                "price_ma25_deviation_pct": None,
                "high_20": None,
                "low_20": None,
                "low_30": None,
                "resistance_level": None,
                "is_abnormal_bar": 0,
                "data_quality_status": "normal",
                "kdj_k": None,
                "kdj_d": None,
                "kdj_j": None,
                "kdj_j_cross_up": 0,
                "kdj_j_over_100": 0,
                "macd_dif": None,
                "macd_dea": None,
                "macd_hist": None,
                "macd_hist_green_shrink": 0,
                "macd_hist_red_extend": 0,
                "ma25_slope_days": 0,
                "ma25_angle_deg": None,
                "ma5_slope_dir": 0,
                "recent_3d_pct": None,
                "recent_5d_pct": None,
            }
        ]
    )

    rows = to_indicator_rows(df)

    assert rows[0]["date"] == "2026-05-19 00:00:00"


def test_to_indicator_rows_formats_minute_date_for_clickhouse_datetime64():
    df = pd.DataFrame(
        [
            {
                "code": "sh.600000",
                "period": "30m",
                "date": 20260519103000,
                "source": "build_from_5m",
                "stock_status": "NORMAL",
                "is_st": 0,
                "ma25": 10.0,
                "ma60": 9.0,
                "ma200": None,
                "ma25_slope_3": None,
                "ma60_slope_3": None,
                "atr14": None,
                "atr20_avg": None,
                "vol_ma5": None,
                "vol_ma60": None,
                "vol_ratio": None,
                "vol_ma5_cross_vol_ma60": 0,
                "price_ma25_deviation_pct": None,
                "high_20": None,
                "low_20": None,
                "low_30": None,
                "resistance_level": None,
                "is_abnormal_bar": 0,
                "data_quality_status": "normal",
                "kdj_k": None,
                "kdj_d": None,
                "kdj_j": None,
                "kdj_j_cross_up": 0,
                "kdj_j_over_100": 0,
                "macd_dif": None,
                "macd_dea": None,
                "macd_hist": None,
                "macd_hist_green_shrink": 0,
                "macd_hist_red_extend": 0,
                "ma25_slope_days": 0,
                "ma25_angle_deg": None,
                "ma5_slope_dir": 0,
                "recent_3d_pct": None,
                "recent_5d_pct": None,
            }
        ]
    )

    rows = to_indicator_rows(df)

    assert rows[0]["date"] == "2026-05-19 10:30:00"

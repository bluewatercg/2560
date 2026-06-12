from __future__ import annotations

from datetime import date, timedelta

from app.services.simple_2560_hard_metrics_report import (
    SIMPLE_HARD_METRICS_FILENAME,
    build_simple_hard_metric_rows,
    render_simple_hard_metrics_report,
)


def _daily_rows(code: str, *, closes: list[float], volumes: list[float], start: date) -> list[dict]:
    rows = []
    for idx, (close, volume) in enumerate(zip(closes, volumes)):
        day = start + timedelta(days=idx)
        rows.append(
            {
                "code": code,
                "d": day.isoformat(),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": volume,
                "amount": close * volume,
            }
        )
    return rows


def test_build_simple_hard_metric_rows_keeps_only_close_above_ma25_mavol5_above_mavol60_and_recent_gain_not_overheated():
    start = date(2026, 4, 12)
    trade_date = "2026-06-10"
    rows = []
    rows.extend(_daily_rows("sh.600001", closes=[10.0] * 34 + [12.0] * 25 + [13.0], volumes=[100.0] * 55 + [200.0] * 5, start=start))
    rows.extend(_daily_rows("sh.600002", closes=[10.0] * 59 + [8.0], volumes=[100.0] * 55 + [200.0] * 5, start=start))
    rows.extend(_daily_rows("sh.600003", closes=[10.0] * 35 + [12.0] * 24 + [13.0], volumes=[200.0] * 55 + [100.0] * 5, start=start))
    rows.extend(_daily_rows("sh.600004", closes=[10.0] * 56 + [10.0, 10.5, 11.0, 13.0], volumes=[100.0] * 55 + [200.0] * 5, start=start))
    rows.extend(_daily_rows("sh.600005", closes=[10.0] * 35 + [12.0] * 24 + [13.0], volumes=[100.0] * 55 + [200.0] * 5, start=start))
    rows.extend(_daily_rows("sh.600006", closes=[10.0] * 34 + [14.0] + [12.0] * 21 + [12.5, 12.7, 12.9, 13.0], volumes=[100.0] * 55 + [200.0] * 5, start=start))
    rows.extend(_daily_rows("sh.600007", closes=[10.0] * 34 + [13.0] + [12.0] * 21 + [12.5, 12.7, 12.9, 13.0], volumes=[100.0] * 55 + [200.0] * 5, start=start))
    rows.extend(_daily_rows("sh.600008", closes=[10.0] * 34 + [12.0] * 22 + [13.5, 13.4, 13.2, 13.0], volumes=[100.0] * 55 + [200.0] * 5, start=start))

    result = build_simple_hard_metric_rows(
        daily_rows=rows,
        names={
            "sh.600001": "通过A",
            "sh.600002": "未站上",
            "sh.600003": "量能弱",
            "sh.600004": "三日过热",
            "sh.600005": "25日过热",
            "sh.600006": "25日负涨幅",
            "sh.600007": "25日零涨幅",
            "sh.600008": "3日负涨幅",
        },
        trade_date=trade_date,
    )

    assert [item["code"] for item in result] == ["sh.600001"]
    assert result[0]["name"] == "通过A"
    assert result[0]["close"] == 13.0
    assert result[0]["close"] > result[0]["ma25"]
    assert result[0]["mavol5"] == 200.0
    assert result[0]["mavol60"] > 100.0
    assert result[0]["mavol_ratio"] > 1.0
    assert result[0]["recent_3day_gain_pct"] <= 20.0
    assert result[0]["recent_3day_gain_pct"] > 0
    assert round(result[0]["recent_25day_gain_pct"], 2) == 8.33
    assert result[0]["recent_25day_gain_pct"] <= 10.0
    assert result[0]["recent_25day_gain_pct"] > 0


def test_render_simple_hard_metrics_report_displays_only_metric_rows():
    markdown = render_simple_hard_metrics_report(
        trade_date="2026-06-10",
        batch_id="20260610082318",
        items=[
            {
                "code": "sh.600001",
                "name": "通过A",
                "close": 12.0,
                "ma25": 11.2,
                "close_vs_ma25_pct": 7.1429,
                "recent_3day_gain_pct": 8.3333,
                "recent_25day_gain_pct": 9.5238,
                "mavol5": 200.0,
                "mavol60": 120.0,
                "mavol_ratio": 1.6667,
            }
        ],
    )

    assert SIMPLE_HARD_METRICS_FILENAME == "09_simple_2560_hard_metrics.md"
    assert "# 2560 简化硬指标盘后报告 - 2026-06-10" in markdown
    assert "只显示：收盘价高于25日均价、5日平均成交量高于60日平均成交量、近3日涨幅不超过20%、近25日涨幅不超过10%" in markdown
    assert "短期量能倍数说明：例如 1.55 表示最近5日平均成交量是60日平均成交量的1.55倍" in markdown
    assert "| 代码 | 名称 | 收盘价 | 25日均价 | 高于25日均价幅度 | 近3日涨幅 | 近25日涨幅 | 5日平均成交量 | 60日平均成交量 | 短期量能倍数 |" in markdown
    assert "MA25" not in markdown
    assert "MAVOL5" not in markdown
    assert "MAVOL60" not in markdown
    assert "| sh.600001 | 通过A | 12.00 | 11.20 | 7.14% | 8.33% | 9.52% | 200 | 120 | 1.67 |" in markdown

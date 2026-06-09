from __future__ import annotations

import json
import html
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.market_scope import market_sql_where
from app.db.clickhouse import get_clickhouse
from app.services.announcement_risk_service import CninfoAnnouncementRiskService
from app.services.annotation_engine_2568 import AnnotationEngine2568
from app.services.market_hotspot_service import DEFAULT_HOTSPOT_QUESTION, EastmoneyHotspotDiscoveryService, match_candidate_to_hotspots


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _market_from_code(code: str | None) -> str:
    c = (code or "").lower()
    if c.startswith("sh.60"):
        return "sh60"
    if c.startswith("sh.68"):
        return "sh68"
    if c.startswith("sz.00"):
        return "sz00"
    if c.startswith("sz.30"):
        return "sz30"
    return "unknown"


def classify_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    ann = candidate.get("annotation") or {}
    structure_status = candidate.get("structure_status") or ""
    a_count = _int(ann.get("a_count"))
    b_count = _int(ann.get("b_count"))
    d_count = _int(ann.get("d_count"))
    action = ann.get("manual_action_label") or ""
    hard_failures = _hard_condition_failures(candidate)
    buy_point_type = candidate.get("buy_point_type") or "未分类"

    if not hard_failures and buy_point_type in {"二类做量", "三类缩量"}:
        bucket = "可执行"
        trade_type = buy_point_type
    elif not hard_failures and buy_point_type == "一类冲量":
        bucket = "观察"
        trade_type = "一类冲量"
    elif not hard_failures:
        bucket = "观察"
        trade_type = "仅观察"
    else:
        bucket = "淘汰"
        trade_type = "放弃"

    reject_reason = ""
    if bucket == "淘汰":
        reasons = list(hard_failures)
        if action:
            reasons.append(f"2568原始标注：{action}")
        if d_count >= 3:
            reasons.append(f"D项较多({d_count})")
        reject_reason = "；".join(reasons) or "不符合2560基础条件"

    if bucket == "可执行":
        report_action_label = f"可执行｜{trade_type}"
    elif bucket == "观察":
        report_action_label = f"仅观察｜{trade_type}"
    elif hard_failures:
        report_action_label = f"不符合2560买点｜{hard_failures[0]}"
    else:
        report_action_label = "不符合2560买点｜淘汰"

    logic_parts = []
    logic_parts.append(f"基础条件{'通过' if not hard_failures else '未通过'}")
    if buy_point_type:
        logic_parts.append(f"买点类型{buy_point_type}")
    if structure_status:
        logic_parts.append(f"原2560结构{structure_status}")
    if action:
        if hard_failures and ("重点关注" in action or "可关注" in action):
            logic_parts.append(f"2568 原始标注{action}，但硬条件未通过")
        else:
            logic_parts.append(f"2568原始标注{action}")
    if d_count:
        logic_parts.append(f"风险项{d_count}个")

    return {
        "hard_condition_status": "通过" if not hard_failures else "未通过",
        "hard_condition_failures": hard_failures,
        "objective_sort_reason": _objective_sort_reason(candidate),
        "bucket": bucket,
        "trade_type": trade_type,
        "report_action_label": report_action_label,
        "reject_reason": reject_reason,
        "logic": "，".join(logic_parts) + "。",
    }


def build_internal_market_model(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    signal_count = len(candidates)
    executable_count = sum(1 for x in candidates if x.get("bucket") == "可执行")
    watch_count = sum(1 for x in candidates if x.get("bucket") == "观察")
    rejected_count = sum(1 for x in candidates if x.get("bucket") == "淘汰")
    complete_count = sum(1 for x in candidates if x.get("structure_status") == "结构完整")
    partial_count = sum(1 for x in candidates if x.get("structure_status") == "部分满足")
    type_counts: dict[str, int] = {}
    for x in candidates:
        t = x.get("buy_point_type") or "未分类"
        type_counts[t] = type_counts.get(t, 0) + 1

    market_distribution: dict[str, int] = {}
    for x in candidates:
        market = _market_from_code(x.get("code"))
        market_distribution[market] = market_distribution.get(market, 0) + 1

    temperature = min(100, round(signal_count * 2 + executable_count * 14 + watch_count * 5))
    if temperature >= 75 and executable_count >= 3:
        risk_state = "风险可控"
    elif temperature >= 45 and executable_count:
        risk_state = "中性偏谨慎"
    elif signal_count:
        risk_state = "弱机会"
    else:
        risk_state = "没有明确交易机会"

    return {
        "temperature": temperature,
        "crowding": None,
        "risk_state": risk_state,
        "signal_count": signal_count,
        "complete_count": complete_count,
        "partial_count": partial_count,
        "executable_count": executable_count,
        "watch_count": watch_count,
        "rejected_count": rejected_count,
        "buy_point_type_counts": type_counts,
        "market_distribution": market_distribution,
        "basis": "内部机会温度：仅基于2560基础条件、买点类型、可执行/观察/淘汰数量",
    }


def _compact_missing_tags(v: Any) -> str:
    if not v:
        return ""
    if isinstance(v, list):
        return " / ".join(_clean_text(str(x)) for x in v)
    if isinstance(v, str):
        s = _clean_text(v)
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return " / ".join(_clean_text(str(x)) for x in parsed)
        except Exception:
            pass
        return s
    return _clean_text(str(v))


_TAG_DETAILS = {
    "#缺量": "#缺量：5日均量/量比未达到2560量能要求",
    "#高位": "#高位：接近30m近20周期高点压力区",
    "#震荡": "#震荡：ATR波动强度不足",
    "#未突破": "#未突破：未突破30m近20周期高点/压力位",
    "#逆势": "#逆势：日线价格趋势未站上核心均线",
    "#趋势走弱": "#趋势走弱：日线趋势斜率不足",
    "#未确认": "#未确认：5m回踩或阳线确认不足",
    "#偏离MA25": "#偏离MA25：价格不在MA25有效回踩区",
    "#MA25走弱": "#MA25走弱：30m MA25斜率不足",
    "#数据不足": "#数据不足：行情或指标窗口不足",
}


def _expand_missing_tags(v: Any, row: dict[str, Any] | None = None) -> str:
    text_value = _compact_missing_tags(v)
    if not text_value:
        return ""
    parts = [x.strip() for x in text_value.split("/") if x.strip()]
    details = []
    for tag in parts:
        details.append(_TAG_DETAILS.get(tag, tag))
    return " / ".join(details)


def _ma25_deviation_bucket(v: Any) -> str:
    n = _num(v, default=None)
    if n is None:
        return "无法验证"
    distance = abs(n)
    if distance <= 3:
        return "≤3% 有效回踩区"
    if distance <= 5:
        return "3%-5% 观察区"
    return ">5% 非回踩买点"


def _price_ma25_deviation(close: Any, ma25: Any) -> float | None:
    c = _num(close, default=None)
    m = _num(ma25, default=None)
    if c is None or m in (None, 0):
        return None
    return (c - m) / m * 100


def _recent_3day_gain(closes: list[Any]) -> float | None:
    if len(closes) < 4:
        return None
    current = _num(closes[-1], default=None)
    base = _num(closes[-4], default=None)
    if current is None or base in (None, 0):
        return None
    return (current - base) / base * 100


def _recent_3day_trend(closes: list[Any]) -> str:
    if len(closes) < 4:
        return "无法验证"
    values = [_num(x, default=None) for x in closes[-4:]]
    if any(v is None for v in values):
        return "无法验证"
    deltas = [values[idx] - values[idx - 1] for idx in range(1, len(values))]
    if all(x > 0 for x in deltas):
        return "连续上行"
    if all(x < 0 for x in deltas):
        return "连续下行"
    net = values[-1] - values[0]
    if net > 0:
        return "震荡上行"
    if net < 0:
        return "震荡下行"
    return "震荡"


def _short_term_heat_status(gain: Any) -> str:
    n = _num(gain, default=None)
    if n is None:
        return "无法验证"
    if n <= 5:
        return "正常"
    if n <= 8:
        return "偏热，观察"
    if n <= 20:
        return "高位，谨慎"
    return "超过20%，过滤"


def _burst_filter_status(gain: Any) -> str:
    n = _num(gain, default=None)
    if n is None:
        return "无法验证"
    if n <= 5:
        return "通过"
    if n <= 8:
        return "偏热，观察"
    if n <= 20:
        return "高位，谨慎"
    return "起爆加速，过滤"


def _burst_filter_text(candidate: dict[str, Any]) -> str:
    status = candidate.get("burst_filter_status")
    if status:
        return str(status)
    return _burst_filter_status(candidate.get("recent_3day_gain_pct"))


def _recent_trend_text(candidate: dict[str, Any]) -> str:
    trend = candidate.get("recent_3day_trend")
    if trend:
        return str(trend)
    return "无法验证"


def _hard_condition_failures(candidate: dict[str, Any]) -> list[str]:
    failures = []
    direction = candidate.get("ma25_direction") or ""
    ma25_status = candidate.get("ma25_status") or ""
    if direction != "向上" and "上行" not in ma25_status:
        failures.append("25日均线未上行")

    vol_ok = candidate.get("vol_ma5_gt_vol_ma60")
    vol_ma5 = _num(candidate.get("vol_ma5"), default=None)
    vol_ma60 = _num(candidate.get("vol_ma60"), default=None)
    if vol_ok is not True:
        if vol_ma5 is None or vol_ma60 is None:
            failures.append("5日/60日均量线无法验证")
        elif vol_ma5 <= vol_ma60:
            failures.append("5日均量线未站上60日均量线")

    deviation = _num(candidate.get("price_ma25_deviation_pct"), default=None)
    if deviation is None:
        failures.append("25日线位置无法验证")
    elif deviation < -1.0:
        failures.append("跌破25日线未收回")
    elif abs(deviation) > 5.0:
        failures.append("25日线位置超过5%")

    recent_3day_gain_pct = _num(candidate.get("recent_3day_gain_pct"), default=None)
    if recent_3day_gain_pct is not None and recent_3day_gain_pct > 20:
        failures.append("近3日涨幅超过20%，起爆加速段过滤")
    if candidate.get("recent_3day_trend") == "连续下行":
        failures.append("近3日连续下行，右侧未确认")
    return failures


def _objective_sort_reason(candidate: dict[str, Any]) -> str:
    return (
        f"买点类型={candidate.get('buy_point_type') or '未分类'}；"
        f"25日线位置={_fmt_num(candidate.get('price_ma25_deviation_pct'))}%；"
        f"压量={candidate.get('volume_compression_label') or '无法验证'}；"
        f"MAVOL5/60={_fmt_num(candidate.get('vol_ratio'))}"
    )


def _volume_profile_from_daily_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda x: _date_sort_key(x.get("date")))
    closes = [_num(x.get("close"), default=None) for x in ordered]
    recent_3day_gain_pct = _recent_3day_gain(closes)
    recent_3day_trend = _recent_3day_trend(closes)
    short_term_heat_status = _short_term_heat_status(recent_3day_gain_pct)
    burst_filter_status = _burst_filter_status(recent_3day_gain_pct)

    if len(rows) < 60:
        return {
            "buy_point_type": "未分类",
            "volume_compression_label": "日线窗口不足",
            "volume_sort_rank": 9,
            "recent_3day_gain_pct": recent_3day_gain_pct,
            "recent_3day_trend": recent_3day_trend,
            "short_term_heat_status": short_term_heat_status,
            "burst_filter_status": burst_filter_status,
        }

    volumes = [_num(x.get("volume"), default=None) for x in ordered]
    opens = [_num(x.get("open"), default=None) for x in ordered]
    highs = [_num(x.get("high"), default=None) for x in ordered]
    lows = [_num(x.get("low"), default=None) for x in ordered]
    if any(v is None for v in volumes[-60:]):
        return {
            "buy_point_type": "未分类",
            "volume_compression_label": "成交量无法验证",
            "volume_sort_rank": 9,
            "recent_3day_gain_pct": recent_3day_gain_pct,
            "recent_3day_trend": recent_3day_trend,
            "short_term_heat_status": short_term_heat_status,
            "burst_filter_status": burst_filter_status,
        }

    vol_ma5_series = [_rolling_avg(volumes, i, 5) for i in range(len(volumes))]
    vol_ma60_series = [_rolling_avg(volumes, i, 60) for i in range(len(volumes))]
    previous_5day_avg_volume = sum(float(v) for v in volumes[-6:-1]) / 5 if len(volumes) >= 6 and not any(v is None for v in volumes[-6:-1]) else None
    current_volume_ratio_5 = volumes[-1] / previous_5day_avg_volume if previous_5day_avg_volume not in (None, 0) else None
    diff_series = [
        (v5 - v60) / v60 if v5 is not None and v60 not in (None, 0) else None
        for v5, v60 in zip(vol_ma5_series, vol_ma60_series)
    ]
    current_diff = diff_series[-1]
    previous_diff = diff_series[-2] if len(diff_series) >= 2 else None
    recent_before = [x for x in diff_series[-15:-1] if x is not None]
    had_positive_before = any(x > 0 for x in diff_series[-30:-5] if x is not None)
    stayed_positive_recently = all((x is not None and x > 0) for x in diff_series[-15:])
    compressed_recently = len(volumes) >= 3 and volumes[-1] < volumes[-2] < volumes[-3]
    latest_below_ma60 = vol_ma60_series[-1] not in (None, 0) and volumes[-1] < vol_ma60_series[-1]
    small_k = False
    if closes[-1] not in (None, 0) and None not in (opens[-1], highs[-1], lows[-1], closes[-1]):
        body_pct = abs(closes[-1] - opens[-1]) / closes[-1] * 100
        amplitude_pct = (highs[-1] - lows[-1]) / closes[-1] * 100
        small_k = body_pct <= 1.5 and amplitude_pct <= 4.0

    prior_positive = any(x > 0 for x in diff_series[:-1] if x is not None)
    if current_diff is None:
        buy_point_type = "未分类"
    elif current_diff > 0 and ((previous_diff is not None and previous_diff <= 0) or not prior_positive):
        buy_point_type = "一类冲量"
    elif had_positive_before and recent_before and min(abs(x) for x in recent_before[-8:]) <= 0.08 and current_diff > 0:
        buy_point_type = "二类做量"
    elif stayed_positive_recently and (compressed_recently or latest_below_ma60):
        buy_point_type = "三类缩量"
    elif current_diff > 0:
        buy_point_type = "趋势量能"
    else:
        buy_point_type = "未分类"

    compression_parts = []
    if compressed_recently:
        compression_parts.append("连续缩量")
    if latest_below_ma60:
        compression_parts.append("当日量低于60日均量")
    if small_k:
        compression_parts.append("小K线")
    compression_label = " / ".join(compression_parts) if compression_parts else "无明显压量"
    volume_sort_rank = 0 if latest_below_ma60 and compressed_recently else (1 if compressed_recently or latest_below_ma60 else 2)

    return {
        "buy_point_type": buy_point_type,
        "volume_compression_label": compression_label,
        "volume_sort_rank": volume_sort_rank,
        "daily_vol_ma5": vol_ma5_series[-1],
        "daily_vol_ma60": vol_ma60_series[-1],
        "daily_vol_ma5_ma60_diff_pct": current_diff * 100 if current_diff is not None else None,
        "latest_volume_below_ma60": bool(latest_below_ma60),
        "previous_5day_avg_volume": previous_5day_avg_volume,
        "current_volume_ratio_5": current_volume_ratio_5,
        "recent_3day_gain_pct": recent_3day_gain_pct,
        "recent_3day_trend": recent_3day_trend,
        "short_term_heat_status": short_term_heat_status,
        "burst_filter_status": burst_filter_status,
    }


def build_volume_pullback_candidates_from_rows(
    rows: list[dict[str, Any]],
    names: dict[str, str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    names = names or {}
    by_code: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        code = row.get("code")
        date = row.get("date")
        if not code or date is None:
            continue
        by_code.setdefault(str(code), {})[str(date)] = dict(row)

    latest_key = None
    for date_rows in by_code.values():
        for row in date_rows.values():
            key = _date_sort_key(row.get("date"))
            latest_key = key if latest_key is None or key > latest_key else latest_key
    if latest_key is None:
        return []

    candidates: list[dict[str, Any]] = []
    for code, date_rows in by_code.items():
        ordered = sorted(date_rows.values(), key=lambda x: _date_sort_key(x.get("date")))
        if len(ordered) < 60 or _date_sort_key(ordered[-1].get("date")) != latest_key:
            continue

        latest = ordered[-1]
        closes = [_num(x.get("close"), default=None) for x in ordered]
        volumes = [_num(x.get("volume"), default=None) for x in ordered]
        if any(v is None for v in closes[-28:]) or any(v is None for v in volumes[-60:]):
            continue

        ma25 = sum(float(v) for v in closes[-25:]) / 25
        ma25_prev3 = sum(float(v) for v in closes[-28:-3]) / 25
        vol_ma5 = sum(float(v) for v in volumes[-5:]) / 5
        vol_ma60 = sum(float(v) for v in volumes[-60:]) / 60
        previous_5day_avg_volume = sum(float(v) for v in volumes[-6:-1]) / 5
        close = _num(latest.get("close"), default=None)
        volume = _num(latest.get("volume"), default=None)
        open_price = _num(latest.get("open"), default=None)
        high = _num(latest.get("high"), default=None)
        low = _num(latest.get("low"), default=None)
        if close is None or volume is None or ma25 == 0 or ma25_prev3 == 0 or vol_ma60 == 0:
            continue

        recent_3day_gain_pct = _recent_3day_gain(closes)
        recent_3day_trend = _recent_3day_trend(closes)
        short_term_heat_status = _short_term_heat_status(recent_3day_gain_pct)
        burst_filter_status = _burst_filter_status(recent_3day_gain_pct)
        if recent_3day_gain_pct is not None and recent_3day_gain_pct > 20:
            continue

        distance = (close - ma25) / ma25 * 100
        if not (ma25 > ma25_prev3 and vol_ma5 > vol_ma60 and close >= ma25 and distance <= 3):
            continue

        body_pct = None
        amplitude_pct = None
        if open_price not in (None, 0):
            body_pct = abs(close - open_price) / open_price * 100
        if close and high is not None and low is not None:
            amplitude_pct = (high - low) / close * 100
        small_k = body_pct is not None and amplitude_pct is not None and body_pct <= 1.5 and amplitude_pct <= 4.0
        small_body = body_pct is not None and body_pct <= 2.0
        volume_shrink = volume < vol_ma60
        if not (small_k or small_body or volume_shrink):
            continue

        pattern_parts = []
        if small_k:
            pattern_parts.append("小K线")
        if small_body:
            pattern_parts.append("小阴小阳")
        if volume_shrink:
            pattern_parts.append("缩量")

        volume_ratio = volume / previous_5day_avg_volume if previous_5day_avg_volume else None
        candidates.append({
            "code": code,
            "name": _clean_text(names.get(code) or code),
            "trade_date": latest.get("date"),
            "close": close,
            "ma25": ma25,
            "ma25_direction": "向上",
            "price_ma25_deviation_pct": distance,
            "vol_ma5": vol_ma5,
            "vol_ma60": vol_ma60,
            "vol_ma5_gt_vol_ma60": True,
            "volume": volume,
            "previous_5day_avg_volume": previous_5day_avg_volume,
            "volume_ratio": volume_ratio,
            "recent_3day_gain_pct": recent_3day_gain_pct,
            "recent_3day_trend": recent_3day_trend,
            "short_term_heat_status": short_term_heat_status,
            "burst_filter_status": burst_filter_status,
            "pressure_pattern": " / ".join(pattern_parts),
            "buy_point_type": "缩量回踩25日线",
        })

    candidates.sort(key=lambda x: (_num(x.get("price_ma25_deviation_pct"), 999), _num(x.get("volume_ratio"), 999), x.get("code") or ""))
    return candidates[:limit]


def _rolling_avg(values: list[float | None], idx: int, window: int) -> float | None:
    if idx + 1 < window:
        return None
    subset = values[idx - window + 1 : idx + 1]
    if any(v is None for v in subset):
        return None
    return sum(float(v) for v in subset) / window


def _date_sort_key(v: Any) -> tuple[int, str]:
    if isinstance(v, (int, float)):
        return (0, f"{int(v):020d}")
    return (1, str(v or ""))


def _technical_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    type_rank = {"二类做量": 0, "三类缩量": 1, "一类冲量": 2, "趋势量能": 3, "未分类": 4}
    return (
        _bucket_rank(candidate.get("bucket")),
        type_rank.get(candidate.get("buy_point_type") or "未分类", 9),
        _hotspot_sort_rank(candidate.get("hotspot_match_level")),
        abs(_num(candidate.get("price_ma25_deviation_pct"), default=999)),
        _int(candidate.get("volume_sort_rank"), 9),
        -_num(candidate.get("vol_ratio"), default=0),
        str(candidate.get("code") or ""),
    )


def _hotspot_sort_rank(level: Any) -> int:
    return {"强匹配": 0, "弱匹配": 1, "未匹配": 2, "未验证": 3}.get(str(level or ""), 9)


def _hotspot_direction_text(candidate: dict[str, Any]) -> str:
    theme = candidate.get("hotspot_theme") or candidate.get("hotspot_direction")
    if theme:
        return str(theme)
    return str(candidate.get("hotspot_match_summary") or "-")


def _latest_announcement_text(candidate: dict[str, Any]) -> str:
    return str(candidate.get("latest_announcement_summary") or candidate.get("announcement_risk_summary") or "-")


def _execution_condition(x: dict[str, Any]) -> str:
    if x.get("bucket") != "可执行":
        return "当前不符合开仓条件；下个交易日仅继续观察，不触发则不交易。"
    ma25 = _num(x.get("ma25"), default=None)
    close = _num(x.get("close"), default=None)
    vol_ma5 = _num(x.get("vol_ma5"), default=None)
    vol_ma60 = _num(x.get("vol_ma60"), default=None)
    price_part = "价格保持在25日线有效回踩区"
    if ma25 is not None:
        price_part = f"价格保持在25日线附近 {ma25 * 0.97:.2f}-{ma25 * 1.03:.2f}"
    volume_part = "5日均量继续大于60日均量"
    if vol_ma5 is not None and vol_ma60 is not None:
        volume_part = f"5日均量({vol_ma5:.0f})继续大于60日均量({vol_ma60:.0f})"
    close_part = "且不跌破前一交易日收盘价"
    if close is not None:
        close_part = f"且不有效跌破当前收盘参考价 {close:.2f}"
    return f"下个交易日若{price_part}，{volume_part}，{close_part}，并出现右侧确认，则按报告仓位执行；否则不交易。"


def _position_metrics_note(x: dict[str, Any], next_trade_plan_date: str | None = None) -> str:
    date_label = f"（{next_trade_plan_date}）" if next_trade_plan_date else ""
    return f"待观察日{date_label}收盘确认后计算"


def _right_side_confirmation(x: dict[str, Any]) -> str:
    close = _num(x.get("close"), default=None)
    ma25 = _num(x.get("ma25"), default=None)
    volume = _num(x.get("volume"), default=None)
    previous_5day_avg_volume = _num(x.get("previous_5day_avg_volume"), default=None)
    parts = ["日线右侧确认需次日收盘验证"]
    if close is not None:
        parts.append(f"不有效跌破报告日收盘价{close:.2f}")
    if ma25 is not None:
        parts.append(f"收盘站稳25日线{ma25:.2f}上方")
    else:
        parts.append("收盘站稳25日线上方")
    if volume is not None and previous_5day_avg_volume is not None:
        parts.append(f"若放量阳线，成交量需高于前5日均量{previous_5day_avg_volume:.0f}")
    else:
        parts.append("若放量阳线，成交量需高于前5日均量")
    parts.append("盘后报告不使用5m信号直接开仓")
    return "；".join(parts)


def _clean_text(v: Any) -> str:
    return str(v or "").replace("\x00", "").strip()


_PUBLIC_REPORT_REPLACEMENTS = (
    ("SignalEngine2560Fast", "选股计算模块"),
    ("canonical_signal_engine", "选股计算模块"),
    ("内部算法", "计算方法"),
    ("fast", "标准"),
    ("slow", "稳态"),
    ("✓", "是"),
    ("✗", "否"),
    ("⚠", "注意"),
    ("▶", "-"),
    ("○", "-"),
    ("🔥", "热度较高"),
    ("✅", "是"),
    ("❌", "否"),
)


def _sanitize_public_report_text(value: str) -> str:
    text_value = value
    for old, new in _PUBLIC_REPORT_REPLACEMENTS:
        text_value = text_value.replace(old, new)
    return text_value


def _sanitize_public_report_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_public_report_text(value)
    if isinstance(value, list):
        return [_sanitize_public_report_payload(x) for x in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_public_report_payload(x) for x in value)
    if isinstance(value, dict):
        return {
            _sanitize_public_report_payload(k) if isinstance(k, str) else k: _sanitize_public_report_payload(v)
            for k, v in value.items()
        }
    return value


class DailySelectionReportService:
    def __init__(self, db: Session):
        self.db = db

    def build_report(self, limit: int = 50) -> dict[str, Any]:
        now = datetime.now()
        latest_batch = self._latest_batch()
        signals = self._latest_selected_signals(latest_batch, limit) if latest_batch else []
        annotations = self._annotations_for_codes([s["code"] for s in signals])
        volume_profiles = self._daily_volume_profiles([s["code"] for s in signals])
        candidates = []
        for s in signals:
            ann = annotations.get(s["code"], {})
            volume_profile = volume_profiles.get(s["code"], {})
            item = {
                **s,
                **volume_profile,
                "market": _market_from_code(s.get("code")),
                "name": _clean_text(s.get("name")),
                "missing_tags_text": _compact_missing_tags(s.get("missing_tags")),
                "missing_tags_detail": _expand_missing_tags(s.get("missing_tags"), s),
                "annotation": ann,
                "highlight_level": ann.get("highlight_level"),
                "manual_action_label": ann.get("manual_action_label"),
                "highlight_summary": ann.get("highlight_summary"),
                "risk_tags": ann.get("risk_tags"),
                "ma25_status": ann.get("ma25_status"),
                "ma60_status": ann.get("ma60_status"),
                "volume_status": ann.get("volume_status"),
                "trend_status": ann.get("trend_status"),
                "close": ann.get("close") if ann.get("close") is not None else s.get("price"),
                "volume": ann.get("volume"),
                "amount": ann.get("amount"),
                "ma25": ann.get("ma25"),
                "ma60": ann.get("ma60"),
                "ma25_direction": ann.get("ma25_direction"),
                "ma60_direction": ann.get("ma60_direction"),
                "price_ma25_deviation_pct": ann.get("price_ma25_deviation_pct"),
                "vol_ma5": ann.get("vol_ma5"),
                "vol_ma60": ann.get("vol_ma60"),
                "vol_ma5_gt_vol_ma60": ann.get("vol_ma5_gt_vol_ma60"),
                "vol_ratio": volume_profile.get("current_volume_ratio_5") or ann.get("vol_ratio"),
                "previous_5day_avg_volume": volume_profile.get("previous_5day_avg_volume"),
            }
            if item["price_ma25_deviation_pct"] is None:
                item["price_ma25_deviation_pct"] = _price_ma25_deviation(item.get("close"), item.get("ma25"))
            item["ma25_deviation_bucket"] = _ma25_deviation_bucket(item.get("price_ma25_deviation_pct"))
            item.update(classify_candidate(item))
            candidates.append(item)

        candidates = self._dedupe_candidates(candidates)
        candidates.sort(key=_technical_sort_key)
        market_model = build_internal_market_model(candidates)
        data_validation = self._data_validation(latest_batch, market_model)
        volume_pullback_candidates = self._volume_pullback_candidates(limit)
        review_trade_date = self._review_trade_date(latest_batch, now)
        announcement_risks = self._announcement_risks_for_codes(
            [x.get("code") for x in candidates + volume_pullback_candidates if x.get("code")],
            review_trade_date,
        )
        self._attach_announcement_risks(candidates, announcement_risks)
        self._attach_announcement_risks(volume_pullback_candidates, announcement_risks)
        hotspot_snapshot = self._market_hotspot_snapshot(review_trade_date)
        self._attach_hotspot_matches(candidates, hotspot_snapshot)
        self._attach_hotspot_matches(volume_pullback_candidates, hotspot_snapshot)
        self._apply_hotspot_validation(data_validation, hotspot_snapshot)
        candidates.sort(key=_technical_sort_key)
        executable = [x for x in candidates if x["bucket"] == "可执行"]
        watchlist = [x for x in candidates if x["bucket"] == "观察"]
        rejected = [x for x in candidates if x["bucket"] == "淘汰"]
        final_advice = self._final_advice(market_model)
        selection_counts = _selection_status_counts(candidates)
        final_advice["summary"] = (
            f"内部2560候选{len(candidates)}只，"
            f"focus{selection_counts['focus']}只，"
            f"watch{selection_counts['watch']}只，"
            f"reject{selection_counts['reject']}只。"
        )

        report = {
            "title": "内部数据版 2560 盘后选股报告",
            "system_version": "v5.1-internal",
            "technical_metadata": {
                "skill_parse_version": "daily-selection-skill-v1",
                "strategy_contract": "2560标准候选口径",
                "canonical_fields": [
                    "selection_status",
                    "final_score",
                    "recent_3d_pct",
                    "explode_status",
                    "market_state",
                    "environment_score",
                    "hot_topic_strength",
                    "position_in_hot_topic",
                    "hot_topic_score",
                    "volume_score",
                    "structure_score",
                    "intraday_score",
                    "pressure_score",
                ],
                "announcement_policy": "默认禁止逐票联网公告/研报调用；未显式开启时按 unverified 审计。",
            },
            "report_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "review_trade_date": review_trade_date,
            "next_trade_plan_date": self._next_plan_date(now),
            "data_validation": data_validation,
            "market_model": market_model,
            "core_candidates": candidates[:5],
            "candidates": candidates,
            "executable": executable,
            "watchlist": watchlist,
            "rejected": rejected,
            "volume_pullback_candidates": volume_pullback_candidates,
            "hotspot_snapshot": hotspot_snapshot,
            "final_advice": final_advice,
        }
        report = _sanitize_public_report_payload(report)
        report["markdown"] = render_markdown_report(report)
        return report

    @staticmethod
    def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for item in candidates:
            code = item.get("code")
            if not code:
                continue
            current = best.get(code)
            if current is None:
                best[code] = item
                continue
            item_sort = _technical_sort_key(item)
            cur_sort = _technical_sort_key(current)
            if item_sort < cur_sort:
                best[code] = item
                continue
            if item_sort == cur_sort and str(item.get("signal_time") or "") > str(current.get("signal_time") or ""):
                best[code] = item
        return list(best.values())

    def _latest_batch(self) -> dict[str, Any] | None:
        row = self.db.execute(text("""
            SELECT batch_id, run_time, strategy_code, strategy_version, status, message
            FROM analysis_batch
            WHERE strategy_code='S2560' AND status='success'
            ORDER BY run_time DESC
            LIMIT 1
        """)).mappings().first()
        return dict(row) if row else None

    def _latest_selected_signals(self, latest_batch: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        sql = text("""
            SELECT a.id, a.batch_id, a.code, a.name, a.signal_time, a.signal_period,
                   a.price, a.structure_status, a.strength_score_raw, a.missing_tags,
                   a.missing_tag_count, a.explain_text, a.data_quality_status,
                   a.selected_signal, a.price_near_ma25, a.ma25_slope_ok,
                   a.volume_structure_ok, a.abnormal_filter_ok, a.trend_price_ok,
                   a.trend_slope_ok, a.volatility_ok, a.breakout_ok, a.volume_ok,
                   a.near_resistance, a.pullback_ok, a.bullish_confirm,
                   a.selection_status, a.final_score, a.recent_3d_pct,
                   a.explode_status, a.market_state, a.environment_score,
                   a.hot_topic_strength, a.position_in_hot_topic, a.hot_topic_score,
                   a.volume_score, a.structure_score, a.intraday_score, a.pressure_score,
                   s.industry_name, s.board_name
            FROM structure_2560_analysis a
            LEFT JOIN stock_info s ON s.code=a.code
            WHERE CAST(a.batch_id AS CHAR)=CAST(:batch_id AS CHAR)
              AND a.selected_signal=1
            ORDER BY a.signal_time DESC, a.id DESC
            LIMIT :limit
        """)
        rows = self.db.execute(sql, {"batch_id": latest_batch["batch_id"], "limit": limit}).mappings().all()
        return [dict(r) for r in rows]

    def _annotations_for_codes(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}
        engine = AnnotationEngine2568(self.db)
        return {x.get("code"): x for x in engine.annotations_for_codes(codes).get("items", [])}

    def _daily_volume_profiles(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if not codes:
            return out
        ch = get_clickhouse()
        for code in dict.fromkeys(codes):
            try:
                rows = ch.query(
                    f"""
                    SELECT date,open,high,low,close,volume
                    FROM daily_kline
                    WHERE code='{code}'
                    ORDER BY date DESC
                    LIMIT 90
                    """
                )
            except Exception:
                rows = []
            out[code] = _volume_profile_from_daily_rows([dict(r) for r in rows])
        return out

    def _stock_names_for_codes(self, codes: list[str]) -> dict[str, str]:
        unique_codes = list(dict.fromkeys(codes))
        if not unique_codes:
            return {}
        try:
            sql = text("""
                SELECT code, name
                FROM stock_info
                WHERE code IN :codes
            """).bindparams(bindparam("codes", expanding=True))
            rows = self.db.execute(sql, {"codes": unique_codes}).mappings().all()
            return {r["code"]: _clean_text(r.get("name")) for r in rows}
        except Exception:
            return {}

    def _volume_pullback_candidates(self, limit: int) -> list[dict[str, Any]]:
        try:
            rows = get_clickhouse().query(f"""
                SELECT code,date,open,high,low,close,volume
                FROM daily_kline
                WHERE date >= (
                    SELECT max(date) FROM daily_kline WHERE {market_sql_where("code", "all")}
                ) - INTERVAL 180 DAY
                  AND {market_sql_where("code", "all")}
                ORDER BY code, date
            """)
        except Exception:
            rows = []
        codes = [str(r.get("code")) for r in rows if r.get("code")]
        names = self._stock_names_for_codes(codes)
        return build_volume_pullback_candidates_from_rows([dict(r) for r in rows], names=names, limit=limit)

    @staticmethod
    def _attach_announcement_risks(items: list[dict[str, Any]], risks: dict[str, dict[str, Any]]) -> None:
        for item in items:
            risk = risks.get(item.get("code")) or {
                "announcement_risk_level": "unverified",
                "announcement_risk_summary": "公告联网受限，暂未验证",
                "announcement_risk_items": [],
                "announcement_risk_source": "cninfo",
                "announcement_sentiment": "未验证",
                "latest_announcement_summary": "公告联网受限，暂未验证",
                "latest_announcement_items": [],
                "latest_announcement_source": "cninfo",
                "announcement_query_status": "error",
            }
            item.update(risk)

    def _announcement_risks_for_codes(self, codes: list[str], review_trade_date: str | None) -> dict[str, dict[str, Any]]:
        try:
            return CninfoAnnouncementRiskService().risks_for_codes(codes, review_trade_date=review_trade_date)
        except Exception as exc:
            return {
                code: {
                    "code": code,
                    "announcement_risk_level": "unverified",
                    "announcement_risk_summary": "公告联网受限，暂未验证",
                    "announcement_risk_items": [],
                    "announcement_risk_source": "cninfo",
                    "announcement_sentiment": "未验证",
                    "latest_announcement_summary": "公告联网受限，暂未验证",
                    "latest_announcement_items": [],
                    "latest_announcement_source": "cninfo",
                    "announcement_query_status": "error",
                    "latest_announcement_error": str(exc),
                }
                for code in dict.fromkeys(codes)
            }

    def _market_hotspot_snapshot(self, review_trade_date: str | None) -> dict[str, Any]:
        return EastmoneyHotspotDiscoveryService().snapshot(DEFAULT_HOTSPOT_QUESTION)

    @staticmethod
    def _attach_hotspot_matches(items: list[dict[str, Any]], snapshot: dict[str, Any]) -> None:
        for item in items:
            item.update(match_candidate_to_hotspots(item, snapshot))

    @staticmethod
    def _apply_hotspot_validation(data_validation: dict[str, Any], snapshot: dict[str, Any]) -> None:
        if snapshot.get("hotspot_status") != "available":
            return
        verified = list(data_validation.get("verified_items") or [])
        unverified = list(data_validation.get("unverified_items") or [])
        if "热点主线" not in verified:
            verified.append("热点主线")
        unverified = [x for x in unverified if x != "热点主线"]
        data_validation["verified_items"] = verified
        data_validation["unverified_items"] = unverified

    def _data_validation(self, latest_batch: dict[str, Any] | None, market_model: dict[str, Any]) -> dict[str, Any]:
        readiness = []
        try:
            rows = self.db.execute(text("""
                SELECT market, daily_latest, k5m_latest, k30m_latest,
                       daily_status, k5m_status, k30m_status
                FROM workspace_status
                ORDER BY market
            """)).mappings().all()
            readiness = [dict(r) for r in rows]
        except Exception:
            readiness = []

        missing_markets = [
            r.get("market")
            for r in readiness
            if not (r.get("daily_latest") and r.get("k5m_latest") and r.get("k30m_latest"))
        ]
        unverified_items = ["指数锚点", "市场涨跌停宽度", "热点主线", "账户风控", "北向/两融", "个股公告"]
        if not latest_batch:
            confidence = "低"
        elif missing_markets:
            confidence = "中"
        elif market_model.get("signal_count", 0) <= 0:
            confidence = "中"
        else:
            confidence = "高"

        return {
            "confidence": confidence,
            "latest_batch_id": latest_batch.get("batch_id") if latest_batch else None,
            "latest_batch_run_time": latest_batch.get("run_time") if latest_batch else None,
            "market_readiness": readiness,
            "missing_markets": missing_markets,
            "verified_items": ["日线", "5m", "30m", "2560核心", "2568标注", "代码名称校验"],
            "unverified_items": unverified_items,
            "data_scope": "内部数据版：不含外部指数、账户、北向、两融、公告联网校验",
        }

    @staticmethod
    def _review_trade_date(latest_batch: dict[str, Any] | None, now: datetime) -> str:
        run_time = latest_batch.get("run_time") if latest_batch else None
        try:
            return run_time.strftime("%Y-%m-%d")
        except Exception:
            return now.strftime("%Y-%m-%d")

    @staticmethod
    def _next_plan_date(now: datetime) -> str:
        d = now + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    @staticmethod
    def _final_advice(model: dict[str, Any]) -> dict[str, str]:
        if model["executable_count"] >= 3 and model["temperature"] >= 70:
            strategy = "主线交易"
            open_new = "是"
        elif model["executable_count"] > 0:
            strategy = "震荡"
            open_new = "是，但必须满足次日条件"
        elif model["watch_count"] > 0:
            strategy = "等待"
            open_new = "否，仅观察"
        else:
            strategy = "防守"
            open_new = "否"
        return {
            "strategy": strategy,
            "open_new_position": open_new,
            "summary": f"内部2560候选{model['signal_count']}只，可执行{model['executable_count']}只，观察{model['watch_count']}只，淘汰{model['rejected_count']}只。",
        }


def _bucket_rank(bucket: str | None) -> int:
    return {"可执行": 0, "观察": 1, "淘汰": 2}.get(bucket or "", 9)


def render_markdown_report(report: dict[str, Any]) -> str:
    report = _sanitize_public_report_payload(report)
    dv = report.get("data_validation") or {}
    mm = report.get("market_model") or {}
    hotspot = report.get("hotspot_snapshot") or {}
    final = report.get("final_advice") or {}
    meta = report.get("technical_metadata") or {}
    candidates = report.get("candidates") or []
    core = report.get("core_candidates") or []
    selection_counts = _selection_status_counts(candidates)
    lines = [
        "# 【2560职业短线交易系统 v5.1】盘后复盘与候选说明",
        "",
        f"> 报告生成时间：{report.get('report_time', '-')}",
        "> 报告类型：内部数据版",
        f"> Skill解析版本：{meta.get('skill_parse_version') or 'daily-selection-skill-v1'}",
        f"> 策略口径：{meta.get('strategy_contract') or '2560标准候选口径'}",
        f"> 数据截止：复盘交易日 {report.get('review_trade_date', '-')}",
        f"> 观察日期：下一个A股交易日 {report.get('next_trade_plan_date', '-')}",
        "",
        "## 【0】数据核验摘要",
        "",
        "| 项目 | 结果 |",
        "|------|------|",
        f"| 最新2560批次 | {dv.get('latest_batch_id') or '-'} |",
        f"| 数据置信度 | {dv.get('confidence') or '-'} |",
        f"| 已验证项目 | {' / '.join(dv.get('verified_items') or [])} |",
        f"| 无法验证项目 | {' / '.join(dv.get('unverified_items') or [])} |",
        f"| 数据范围 | {dv.get('data_scope') or '-'} |",
        f"| 公告/研报策略 | {meta.get('announcement_policy') or '默认禁止逐票联网公告/研报调用'} |",
        f"| 核心评估字段 | {' / '.join(meta.get('canonical_fields') or [])} |",
        "",
        "## 【1】市场量化模型",
        "",
        "| 指标 | 数值 | 依据 |",
        "|------|------|------|",
        f"| 内部机会温度 | {mm.get('temperature', '-')} | {mm.get('basis', '-')} |",
        f"| 真实市场温度 | 无外部数据 | 需要指数、成交额、涨跌停、上涨家数等外部/全市场宽度数据，当前暂不计算 |",
        f"| 市场拥挤度 | 无外部数据 | 当前暂不计算 |",
        f"| 风险状态 | {mm.get('risk_state', '-')} | 内部候选与淘汰比例 |",
        f"| 2560候选数量 | {mm.get('signal_count', 0)} | 最新 selected_signal |",
        f"| 买点类型分布 | {_format_distribution(mm.get('buy_point_type_counts') or {})} | 日线MAVOL5/60节奏 |",
        f"| 市场分布 | {_format_distribution(mm.get('market_distribution') or {})} | 代码前缀 |",
        "",
        "## 【2】今日热点主线",
        "",
        "| 项目 | 结果 |",
        "|------|------|",
        f"| 热点状态 | {hotspot.get('hotspot_status') or 'unverified'} |",
        f"| 热点摘要 | {hotspot.get('hotspot_summary') or '热点主线未验证'} |",
        f"| 数据源 | {hotspot.get('hotspot_source') or '-'} |",
        "",
        "## 【3】核心评估字段审计",
        "",
        "| 项目 | 结果 | 说明 |",
        "|------|------|------|",
        f"| selection_status 分布 | {_distribution_for_key(candidates, 'selection_status')} | canonical 入选状态 |",
        f"| explode_status 分布 | {_distribution_for_key(candidates, 'explode_status')} | recent_3d_pct 起爆段分层 |",
        f"| market_state 分布 | {_distribution_for_key(candidates, 'market_state')} | 市场环境状态 |",
        f"| hot_topic_strength 分布 | {_distribution_for_key(candidates, 'hot_topic_strength')} | 热点主线强度 |",
        f"| position_in_hot_topic 分布 | {_distribution_for_key(candidates, 'position_in_hot_topic')} | 个股题材地位 |",
        f"| 公告逐票联网 | 禁用 | {meta.get('announcement_policy') or '-'} |",
        "",
    ]
    if core:
        lines.extend([
            "| 代码 | 名称 | selection_status | final_score | recent_3d_pct | explode_status | market_state | hot_topic_strength | position_in_hot_topic | score_components |",
            "|------|------|------------------|-------------|---------------|----------------|--------------|--------------------|-----------------------|------------------|",
        ])
        for x in core:
            lines.append(
                f"| {x.get('code','-')} | {x.get('name','-')} | {x.get('selection_status') or '-'} | "
                f"{_fmt_num(x.get('final_score'))} | {_fmt_num(x.get('recent_3d_pct'))} | "
                f"{x.get('explode_status') or '-'} | {x.get('market_state') or '-'} | "
                f"{x.get('hot_topic_strength') or '-'} | {x.get('position_in_hot_topic') or '-'} | "
                f"{_score_triplet(x)} |"
            )
        lines.append("")
    lines.extend([
        "## 【4】缩量回踩25日线候选池",
        "",
    ])
    pullbacks = report.get("volume_pullback_candidates") or []
    if pullbacks:
        lines.extend([
            "| 代码 | 名称 | 收盘价 | 25日线位置% | 近3日涨幅% | 近3日走势 | 起爆段过滤 | 压量形态 | 量比 | 买点类型 | 行业热点方向 | 最新公告 |",
            "|------|------|--------|-------------|------------|------------|--------------|----------|------|----------|----------|----------|",
        ])
        for x in pullbacks:
            lines.append(
                f"| {x.get('code','-')} | {x.get('name','-')} | {_fmt_num(x.get('close'))} | "
                f"{_fmt_num(x.get('price_ma25_deviation_pct'))} | {_fmt_num(x.get('recent_3day_gain_pct'))} | "
                f"{_recent_trend_text(x)} | {_burst_filter_text(x)} | {x.get('pressure_pattern') or '-'} | "
                f"{_fmt_num(x.get('volume_ratio'))} | {x.get('buy_point_type') or '-'} | "
                f"{_hotspot_direction_text(x)} | "
                f"{_latest_announcement_text(x)} |"
            )
    else:
        lines.append("无符合“25日向上 + 5量>60量 + 缩量回踩25日线”条件的标的。")

    lines.extend([
        "",
        "## 【5】核心候选清单",
        "",
    ])
    core = report.get("core_candidates") or []
    if core:
        lines.extend([
            "| 代码 | 名称 | 分组 | selection_status | final_score | recent_3d_pct | explode_status | hot_topic_strength | position_in_hot_topic | 报告执行判断 | 基础条件 | 买点类型 | 收盘价 | 25日线 | 25日线位置% | 近3日涨幅% | 近3日走势 | 起爆段过滤 | 行业热点方向 | 25线区间 | 25日方向 | 当日成交量 | 5日均量线 | 60日均量线 | 5量>60量 | 压量 | 排序依据 | 2568原始标注 |",
            "|------|------|------|------------------|-------------|---------------|----------------|--------------------|-----------------------|--------------|----------|----------|--------|--------|-------------|------------|------------|--------------|----------|----------|----------|------------|------------|-------------|----------|------|----------|--------------|",
        ])
        for x in core:
            lines.append(
                f"| {x.get('code','-')} | {x.get('name','-')} | {x.get('bucket','-')} | "
                f"{x.get('selection_status') or '-'} | {_fmt_num(x.get('final_score'))} | "
                f"{_fmt_num(x.get('recent_3d_pct'))} | {x.get('explode_status') or '-'} | "
                f"{x.get('hot_topic_strength') or '-'} | {x.get('position_in_hot_topic') or '-'} | "
                f"{x.get('report_action_label','-')} | {x.get('hard_condition_status','-')} | {x.get('buy_point_type','-')} | "
                f"{_fmt_num(x.get('close'))} | {_fmt_num(x.get('ma25'))} | "
                f"{_fmt_num(x.get('price_ma25_deviation_pct'))} | {_fmt_num(x.get('recent_3day_gain_pct'))} | "
                f"{_recent_trend_text(x)} | {_burst_filter_text(x)} | {_hotspot_direction_text(x)} | "
                f"{x.get('ma25_deviation_bucket') or '-'} | {x.get('ma25_direction') or '-'} | "
                f"{_fmt_num(x.get('volume'), 0)} | {_fmt_num(x.get('vol_ma5'), 0)} | {_fmt_num(x.get('vol_ma60'), 0)} | "
                f"{_fmt_bool(x.get('vol_ma5_gt_vol_ma60'))} | {x.get('volume_compression_label') or '-'} | "
                f"{x.get('objective_sort_reason') or '-'} | {x.get('manual_action_label','-')} |"
            )
    else:
        lines.append("无符合内部 2560 候选条件的标的。")

    lines.extend(["", "## 【6】2560准量化候选明细", ""])
    for x in core:
        lines.extend([
            f"### 标的：{x.get('name','-')}（{x.get('code','-')}）",
            "",
            "| 项目 | 内容 |",
            "|------|------|",
            f"| 所属行业/板块 | {x.get('industry_name') or '-'} / {x.get('board_name') or '-'} |",
            f"| 2560状态 | {x.get('structure_status') or '-'} |",
            f"| 策略评估状态 | {x.get('selection_status') or '-'} |",
            f"| 策略总分 | {_fmt_num(x.get('final_score'))} |",
            f"| 分项得分 | {_score_triplet(x)} |",
            f"| 近3日涨幅 / 起爆状态 | {_fmt_num(x.get('recent_3d_pct'))} / {x.get('explode_status') or '-'} |",
            f"| 市场环境 / 环境分 | {x.get('market_state') or '-'} / {_fmt_num(x.get('environment_score'))} |",
            f"| 题材强度 / 题材地位 | {x.get('hot_topic_strength') or '-'} / {x.get('position_in_hot_topic') or '-'} |",
            f"| 基础条件 | {x.get('hard_condition_status') or '-'} |",
            f"| 基础条件不通过原因 | {'；'.join(x.get('hard_condition_failures') or []) or '-'} |",
            f"| 买点类型 | {x.get('buy_point_type') or '-'} |",
            f"| 客观排序依据 | {x.get('objective_sort_reason') or '-'} |",
            f"| 缺失条件 | {x.get('missing_tags_text') or '-'} |",
            f"| 缺失条件明细 | {x.get('missing_tags_detail') or '-'} |",
            f"| 收盘价 | {_fmt_num(x.get('close'))} |",
            f"| 25日价格均线 | {_fmt_num(x.get('ma25'))} |",
            f"| 25日方向 | {x.get('ma25_direction') or '-'} |",
            f"| 25日线位置% | {_fmt_num(x.get('price_ma25_deviation_pct'))} |",
            f"| 近3日涨幅% | {_fmt_num(x.get('recent_3day_gain_pct'))} |",
            f"| 近3日走势 | {_recent_trend_text(x)} |",
            f"| 起爆段过滤 | {_burst_filter_text(x)} |",
            f"| 行业热点方向 | {_hotspot_direction_text(x)} |",
            f"| 25线区间判断 | {x.get('ma25_deviation_bucket') or '无法验证'} |",
            f"| 当日成交量 | {_fmt_num(x.get('volume'), 0)} |",
            f"| 5日均量线 | {_fmt_num(x.get('vol_ma5'), 0)} |",
            f"| 60日均量线 | {_fmt_num(x.get('vol_ma60'), 0)} |",
            f"| 5日均量线是否在60日均量线上方 | {_fmt_bool(x.get('vol_ma5_gt_vol_ma60'))} |",
            f"| 量比 | {_fmt_num(x.get('vol_ratio'))} |",
            f"| 压量形态 | {x.get('volume_compression_label') or '-'} |",
            f"| 最新公告 | {_latest_announcement_text(x)} |",
            f"| 2568等级 | {x.get('highlight_level') or '-'} |",
            f"| 2568原始标注 | {x.get('manual_action_label') or '-'} |",
            f"| 报告候选判断 | {x.get('report_action_label') or '-'} |",
            f"| MA25/MA60 | {x.get('ma25_status') or '-'} / {x.get('ma60_status') or '-'} |",
            f"| 量能/趋势 | {x.get('volume_status') or '-'} / {x.get('trend_status') or '-'} |",
            f"| 右侧确认 | {_right_side_confirmation(x)} |",
            f"| 胜率/盈亏比/Kelly | {_position_metrics_note(x, report.get('next_trade_plan_date'))} |",
            f"| 风险标签 | {x.get('risk_tags') or '-'} |",
            f"| 候选类型 | {x.get('trade_type') or '-'} |",
            f"| 纳入条件 | {_execution_condition(x)} |",
            f"| 失效条件 | 跌破25日均线或回踩平台低点；若数据无法验证，该候选作废。 |",
            f"| 候选分组 | {x.get('bucket') or '-'} |",
            f"| 逻辑 | {x.get('logic') or '-'} |",
            "",
        ])

    lines.extend([
        "## 【7】重点候选与淘汰原因",
        "",
        "### 重点候选（全部符合条件）",
        "",
    ])
    executable = report.get("executable") or []
    if executable:
        for x in executable:
            lines.append(f"- {x.get('code')} {x.get('name')}：{x.get('logic')}")
    else:
        lines.append("无符合二类/三类观察条件的标的。")

    lines.extend(["", "### 淘汰原因", "", "| 股票 | 淘汰原因 |", "|------|----------|"])
    rejected = report.get("rejected") or []
    if rejected:
        for x in rejected:
            lines.append(f"| {x.get('code','-')} {x.get('name','-')} | {x.get('reject_reason') or x.get('logic') or '-'} |")
    else:
        lines.append("| - | 无 |")

    lines.extend([
        "",
        "## 【10】最终复盘结论",
        "",
        "| 项目 | 结论 |",
        "|------|------|",
        f"| 最终策略 | {final.get('strategy','-')} |",
        f"| 是否继续跟踪 | {final.get('open_new_position','-')} |",
        f"| 重点候选数量 | {selection_counts['focus']} |",
        f"| 一句话结论 | {final.get('summary','-')} |",
        "",
        "## 【合规声明】",
        "",
        "本报告依据内部 2560/2568 数据生成，仅用于盘后复盘与下一观察日条件核验；若条件未触发，则不纳入候选。",
        "",
        "**报告结束**",
    ])
    return "\n".join(lines)


def render_html_report(report: dict[str, Any]) -> str:
    report = _sanitize_public_report_payload(report)
    dv = report.get("data_validation") or {}
    mm = report.get("market_model") or {}
    hotspot = report.get("hotspot_snapshot") or {}
    final = report.get("final_advice") or {}
    pullbacks = report.get("volume_pullback_candidates") or []
    core = report.get("core_candidates") or []
    rejected = report.get("rejected") or []

    def e(v: Any) -> str:
        return html.escape(str(v if v is not None and v != "" else "-"))

    def risk_class(v: Any) -> str:
        level = str(v or "").lower()
        if level == "high":
            return "risk-high"
        if level == "medium":
            return "risk-medium"
        if level == "none":
            return "risk-none"
        return "risk-unknown"

    def pullback_rows() -> str:
        if not pullbacks:
            return '<tr><td colspan="11" class="empty">无符合“25日向上 + 5量&gt;60量 + 缩量回踩25日线”条件的标的</td></tr>'
        rows = []
        for x in pullbacks:
            rows.append(
                "<tr>"
                f"<td><strong>{e(x.get('code'))}</strong><span>{e(x.get('name'))}</span></td>"
                f"<td class='num'>{_fmt_num(x.get('close'))}</td>"
                f"<td class='num accent'>{_fmt_num(x.get('price_ma25_deviation_pct'))}</td>"
                f"<td class='num'>{_fmt_num(x.get('recent_3day_gain_pct'))}</td>"
                f"<td>{e(_recent_trend_text(x))}</td>"
                f"<td>{e(_burst_filter_text(x))}</td>"
                f"<td>{e(x.get('pressure_pattern'))}</td>"
                f"<td class='num'>{_fmt_num(x.get('volume_ratio'))}</td>"
                f"<td>{e(x.get('buy_point_type'))}</td>"
                f"<td>{e(_hotspot_direction_text(x))}</td>"
                f"<td><span class='pill {risk_class(x.get('announcement_risk_level'))}'>{e(_latest_announcement_text(x))}</span></td>"
                "</tr>"
            )
        return "".join(rows)

    def core_rows() -> str:
        if not core:
            return '<tr><td colspan="13" class="empty">无核心交易候选</td></tr>'
        rows = []
        for x in core:
            rows.append(
                "<tr>"
                f"<td><strong>{e(x.get('code'))}</strong><span>{e(x.get('name'))}</span></td>"
                f"<td><span class='pill bucket'>{e(x.get('bucket'))}</span></td>"
                f"<td>{e(x.get('report_action_label'))}</td>"
                f"<td>{e(x.get('buy_point_type'))}</td>"
                f"<td class='num'>{_fmt_num(x.get('close'))}</td>"
                f"<td class='num accent'>{_fmt_num(x.get('price_ma25_deviation_pct'))}</td>"
                f"<td class='num'>{_fmt_num(x.get('recent_3day_gain_pct'))}</td>"
                f"<td>{e(_recent_trend_text(x))}</td>"
                f"<td>{e(_burst_filter_text(x))}</td>"
                f"<td>{e(_hotspot_direction_text(x))}</td>"
                f"<td>{e(x.get('ma25_direction'))}</td>"
                f"<td>{_fmt_bool(x.get('vol_ma5_gt_vol_ma60'))}</td>"
                f"<td><span class='pill {risk_class(x.get('announcement_risk_level'))}'>{e(_latest_announcement_text(x))}</span></td>"
                "</tr>"
            )
        return "".join(rows)

    def detail_blocks() -> str:
        if not core:
            return '<div class="empty block">暂无交易明细</div>'
        blocks = []
        for x in core:
            blocks.append(
                "<section class='detail'>"
                f"<h3>{e(x.get('name'))} <span>{e(x.get('code'))}</span></h3>"
                "<dl>"
                f"<dt>25日线位置%</dt><dd>{_fmt_num(x.get('price_ma25_deviation_pct'))}</dd>"
                f"<dt>近3日涨幅%</dt><dd>{_fmt_num(x.get('recent_3day_gain_pct'))}</dd>"
                f"<dt>近3日走势</dt><dd>{e(_recent_trend_text(x))}</dd>"
                f"<dt>起爆段过滤</dt><dd>{e(_burst_filter_text(x))}</dd>"
                f"<dt>行业热点方向</dt><dd>{e(_hotspot_direction_text(x))}</dd>"
                f"<dt>右侧确认</dt><dd>{e(_right_side_confirmation(x))}</dd>"
                f"<dt>胜率/盈亏比/Kelly</dt><dd>{e(_position_metrics_note(x, report.get('next_trade_plan_date')))}</dd>"
                f"<dt>最新公告</dt><dd>{e(_latest_announcement_text(x))}</dd>"
                f"<dt>执行逻辑</dt><dd>{e(x.get('logic'))}</dd>"
                "</dl>"
                "</section>"
            )
        return "".join(blocks)

    def rejected_rows() -> str:
        if not rejected:
            return '<tr><td colspan="2" class="empty">无淘汰交易</td></tr>'
        return "".join(
            f"<tr><td>{e(x.get('code'))} {e(x.get('name'))}</td><td>{e(x.get('reject_reason') or x.get('logic'))}</td></tr>"
            for x in rejected
        )

    def hotspot_rows() -> str:
        items = hotspot.get("hotspot_items") or []
        if not items:
            return '<tr><td colspan="4" class="empty">热点主线未验证</td></tr>'
        return "".join(
            "<tr>"
            f"<td class='num'>{e(x.get('rank'))}</td>"
            f"<td><strong>{e(x.get('code'))}</strong><span>{e(x.get('name'))}</span></td>"
            f"<td>{e(x.get('theme'))}</td>"
            f"<td>{e(x.get('related_hotspot'))}</td>"
            "</tr>"
            for x in items[:10]
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>2560盘后选股报告</title>
  <style>
    :root {{
      color-scheme: light;
      --bg:#f5f7fb; --panel:#ffffff; --line:#d9e1ec; --text:#172033; --muted:#68758a;
      --blue:#2764d8; --green:#16875d; --red:#c93636; --amber:#9a6700; --slate:#334155;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); }}
    .shell {{ max-width:1440px; margin:0 auto; padding:24px; }}
    header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-end; padding:8px 0 18px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:0; font-size:28px; line-height:1.2; letter-spacing:0; }}
    .meta {{ color:var(--muted); font-size:13px; display:flex; gap:12px; flex-wrap:wrap; margin-top:8px; }}
    .summary {{ display:grid; grid-template-columns:repeat(5,minmax(150px,1fr)); gap:12px; margin:18px 0; }}
    .metric {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }}
    .metric span {{ display:block; color:var(--muted); font-size:12px; }}
    .metric strong {{ display:block; margin-top:6px; font-size:22px; }}
    section.band {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; margin:16px 0; overflow:hidden; }}
    .section-head {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:16px 18px; border-bottom:1px solid var(--line); }}
    h2 {{ margin:0; font-size:18px; letter-spacing:0; }}
    .hint {{ color:var(--muted); font-size:13px; }}
    table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
    th, td {{ padding:12px 14px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); text-align:center; vertical-align:middle; font-size:13px; }}
    th:first-child, td:first-child {{ text-align:left; }}
    th:last-child, td:last-child {{ border-right:0; }}
    th {{ color:#475569; background:#f8fafc; font-weight:650; }}
    td strong {{ display:block; font-size:13px; }}
    td span {{ display:block; color:var(--muted); margin-top:3px; }}
    .num {{ text-align:center; font-variant-numeric:tabular-nums; }}
    .accent {{ color:var(--blue); font-weight:700; }}
    .pill {{ display:inline-block; border-radius:999px; padding:4px 8px; font-size:12px; line-height:1.2; white-space:normal; }}
    .bucket {{ color:#1d4ed8; background:#dbeafe; }}
    .risk-high {{ color:#991b1b; background:#fee2e2; }}
    .risk-medium {{ color:#92400e; background:#fef3c7; }}
    .risk-none {{ color:#166534; background:#dcfce7; }}
    .risk-unknown {{ color:#475569; background:#e2e8f0; }}
    .details {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:14px; padding:16px; }}
    .detail {{ border:1px solid var(--line); border-radius:8px; padding:14px; background:#fbfdff; }}
    .detail h3 {{ margin:0 0 12px; font-size:16px; }}
    .detail h3 span {{ color:var(--muted); font-weight:500; }}
    dl {{ display:grid; grid-template-columns:120px 1fr; gap:8px 12px; margin:0; }}
    dt {{ color:var(--muted); }}
    dd {{ margin:0; }}
    .empty {{ color:var(--muted); text-align:center; padding:22px; }}
    .block {{ border:1px dashed var(--line); border-radius:8px; }}
    @media (max-width:900px) {{
      .shell {{ padding:14px; }}
      header {{ align-items:flex-start; flex-direction:column; }}
      .summary {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
      table {{ table-layout:auto; min-width:900px; }}
      .table-scroll {{ overflow-x:auto; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div>
        <h1>2560盘后选股报告</h1>
        <div class="meta">
          <span>生成时间：{e(report.get('report_time'))}</span>
          <span>复盘交易日：{e(report.get('review_trade_date'))}</span>
          <span>下一交易日：{e(report.get('next_trade_plan_date'))}</span>
        </div>
      </div>
      <div class="hint">内部数据版 · 条件触发才交易</div>
    </header>

    <div class="summary">
      <div class="metric"><span>数据置信度</span><strong>{e(dv.get('confidence'))}</strong></div>
      <div class="metric"><span>机会温度</span><strong>{e(mm.get('temperature'))}</strong></div>
      <div class="metric"><span>风险状态</span><strong>{e(mm.get('risk_state'))}</strong></div>
      <div class="metric"><span>候选数量</span><strong>{e(mm.get('signal_count'))}</strong></div>
      <div class="metric"><span>是否开新仓</span><strong>{e(final.get('open_new_position'))}</strong></div>
    </div>

    <section class="band">
      <div class="section-head"><h2>今日热点主线</h2><span class="hint">{e(hotspot.get('hotspot_summary') or '热点主线未验证')}</span></div>
      <div class="table-scroll">
        <table>
          <thead><tr><th>排名</th><th>代表股票</th><th>匹配主线</th><th>驱动摘要</th></tr></thead>
          <tbody>{hotspot_rows()}</tbody>
        </table>
      </div>
    </section>

    <section class="band">
      <div class="section-head"><h2>缩量回踩25日线候选池</h2><span class="hint">0%-3% 为标准有效回踩区</span></div>
      <div class="table-scroll">
        <table>
          <thead><tr><th>标的</th><th>收盘价</th><th>25日线位置%</th><th>近3日涨幅%</th><th>近3日走势</th><th>起爆段过滤</th><th>压量形态</th><th>量比</th><th>买点类型</th><th>行业热点方向</th><th>最新公告</th></tr></thead>
          <tbody>{pullback_rows()}</tbody>
        </table>
      </div>
    </section>

    <section class="band">
      <div class="section-head"><h2>核心交易候选</h2><span class="hint">最新公告和右侧确认优先于技术信号</span></div>
      <div class="table-scroll">
        <table>
          <thead><tr><th>标的</th><th>分组</th><th>执行判断</th><th>买点类型</th><th>收盘价</th><th>25日线位置%</th><th>近3日涨幅%</th><th>近3日走势</th><th>起爆段过滤</th><th>行业热点方向</th><th>25日方向</th><th>5量&gt;60量</th><th>最新公告</th></tr></thead>
          <tbody>{core_rows()}</tbody>
        </table>
      </div>
    </section>

    <section class="band">
      <div class="section-head"><h2>交易明细</h2><span class="hint">胜率/Kelly 先验值需回测样本库，次日确认后修正</span></div>
      <div class="details">{detail_blocks()}</div>
    </section>

    <section class="band">
      <div class="section-head"><h2>淘汰交易</h2><span class="hint">{e(final.get('summary'))}</span></div>
      <div class="table-scroll">
        <table><thead><tr><th>标的</th><th>原因</th></tr></thead><tbody>{rejected_rows()}</tbody></table>
      </div>
    </section>
  </main>
</body>
</html>"""


def _format_distribution(dist: dict[str, int]) -> str:
    if not dist:
        return "-"
    return " / ".join(f"{k}:{v}" for k, v in sorted(dist.items()))


def _distribution_for_key(items: list[dict[str, Any]], key: str) -> str:
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(key)
        label = "-" if value in (None, "") else str(value)
        counts[label] = counts.get(label, 0) + 1
    return _format_distribution(counts)


def _selection_status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"focus": 0, "watch": 0, "reject": 0}
    for item in items:
        status = str(item.get("selection_status") or "").lower()
        if status in counts:
            counts[status] += 1
    return counts


def _score_triplet(x: dict[str, Any]) -> str:
    return (
        f"final={_fmt_num(x.get('final_score'))}; "
        f"structure={_fmt_num(x.get('structure_score'))}; "
        f"volume={_fmt_num(x.get('volume_score'))}; "
        f"topic={_fmt_num(x.get('hot_topic_score'))}; "
        f"intraday={_fmt_num(x.get('intraday_score'))}; "
        f"pressure={_fmt_num(x.get('pressure_score'))}; "
        f"env={_fmt_num(x.get('environment_score'))}"
    )


def _fmt_num(v: Any, digits: int = 2) -> str:
    n = _num(v, default=None)
    if n is None:
        return "-"
    if digits <= 0:
        return str(int(round(n)))
    return f"{n:.{digits}f}"


def _fmt_bool(v: Any) -> str:
    if v is True:
        return "是"
    if v is False:
        return "否"
    return "无法验证"


def _boolish(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    try:
        return bool(int(v))
    except Exception:
        s = str(v).strip().lower()
        if s in ("true", "yes", "是", "1"):
            return True
        if s in ("false", "no", "否", "0"):
            return False
        return None

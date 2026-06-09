from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _install_report_stubs():
    for name in [
        "sqlalchemy",
        "sqlalchemy.orm",
        "app",
        "app.core",
        "app.core.market_scope",
        "app.db",
        "app.db.clickhouse",
        "app.services",
        "app.services.announcement_risk_service",
        "app.services.annotation_engine_2568",
        "app.services.market_hotspot_service",
    ]:
        sys.modules[name] = types.ModuleType(name)

    class _Text(str):
        def bindparams(self, *args, **kwargs):
            return self

    sys.modules["sqlalchemy"].text = lambda value: _Text(value)
    sys.modules["sqlalchemy"].bindparam = lambda *args, **kwargs: None
    sys.modules["sqlalchemy.orm"].Session = object
    sys.modules["app.core.market_scope"].market_sql_where = lambda column, market: "1=1"
    sys.modules["app.db.clickhouse"].get_clickhouse = lambda: None
    sys.modules["app.services.announcement_risk_service"].CninfoAnnouncementRiskService = object
    sys.modules["app.services.annotation_engine_2568"].AnnotationEngine2568 = object
    hotspot = sys.modules["app.services.market_hotspot_service"]
    hotspot.DEFAULT_HOTSPOT_QUESTION = ""
    hotspot.EastmoneyHotspotDiscoveryService = object

    def _match_candidate_to_hotspots(candidate, snapshot):
        for item in snapshot.get("hotspot_items") or []:
            if item.get("code") == candidate.get("code"):
                return {
                    "hotspot_match_level": "强匹配",
                    "hotspot_direction": item.get("theme") or item.get("name"),
                    "hotspot_match_reason": "代码命中热点池",
                }
        return {"hotspot_match_level": "未匹配", "hotspot_direction": "未匹配今日热点主线"}

    hotspot.match_candidate_to_hotspots = _match_candidate_to_hotspots


def _load_report_module():
    names = [
        "sqlalchemy",
        "sqlalchemy.orm",
        "app",
        "app.core",
        "app.core.market_scope",
        "app.db",
        "app.db.clickhouse",
        "app.services",
        "app.services.announcement_risk_service",
        "app.services.annotation_engine_2568",
        "app.services.market_hotspot_service",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    _install_report_stubs()
    try:
        spec = importlib.util.spec_from_file_location(
            "daily_selection_report_under_test",
            PROJECT_ROOT / "app/services/daily_selection_report.py",
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


_report = _load_report_module()
DailySelectionReportService = _report.DailySelectionReportService
build_volume_pullback_candidates_from_rows = _report.build_volume_pullback_candidates_from_rows
build_internal_market_model = _report.build_internal_market_model
classify_candidate = _report.classify_candidate
_clean_text = _report._clean_text
render_markdown_report = _report.render_markdown_report
render_html_report = _report.render_html_report
_compact_missing_tags = _report._compact_missing_tags
_expand_missing_tags = _report._expand_missing_tags
_ma25_deviation_bucket = _report._ma25_deviation_bucket
_recent_3day_trend = _report._recent_3day_trend
_technical_sort_key = _report._technical_sort_key
_volume_profile_from_daily_rows = _report._volume_profile_from_daily_rows


def _bar(code: str, date: int, close: float, volume: float, open_price: float | None = None) -> dict:
    open_value = close if open_price is None else open_price
    return {
        "code": code,
        "date": date,
        "open": open_value,
        "high": max(open_value, close) * 1.01,
        "low": min(open_value, close) * 0.99,
        "close": close,
        "volume": volume,
    }


def test_volume_pullback_candidates_require_hard_filters_and_sort_by_ma25_distance():
    rows = []
    for idx in range(64):
        rows.append(_bar("sh.600000", 20260401 + idx, 10 + idx * 0.02, 1000))
        rows.append(_bar("sz.300000", 20260401 + idx, 20 + idx * 0.01, 1000))
        rows.append(_bar("sh.600001", 20260401 + idx, 10 - idx * 0.03, 1000))

    for idx in range(59, 64):
        rows[idx * 3]["volume"] = 1600
        rows[idx * 3 + 1]["volume"] = 1550

    rows[-3] = {**rows[-3], "open": rows[-3]["close"] * 1.005, "volume": 700}
    rows[-2] = {**rows[-2], "open": rows[-2]["close"] * 1.001, "volume": 800}
    rows[-1] = {**rows[-1], "close": rows[-1]["close"] * 0.97, "volume": 700}

    out = build_volume_pullback_candidates_from_rows(
        rows,
        names={"sh.600000": "样例A", "sz.300000": "样例B", "sh.600001": "下行票"},
        limit=10,
    )

    assert [x["code"] for x in out] == ["sz.300000", "sh.600000"]
    assert out[0]["name"] == "样例B"
    assert out[0]["buy_point_type"] == "缩量回踩25日线"
    assert out[0]["price_ma25_deviation_pct"] <= out[1]["price_ma25_deviation_pct"]
    assert "小K线" in out[0]["pressure_pattern"]
    assert "缩量" in out[0]["pressure_pattern"]
    assert out[0]["volume_ratio"] == out[0]["volume"] / out[0]["previous_5day_avg_volume"]
    assert out[0]["recent_3day_gain_pct"] <= 5
    assert out[0]["recent_3day_trend"] == "连续上行"
    assert out[0]["short_term_heat_status"] == "正常"
    assert out[0]["burst_filter_status"] == "通过"


def test_volume_pullback_candidates_keep_high_but_under_20_pct_three_day_gain():
    rows = []
    for idx in range(64):
        rows.append(_bar("sh.600000", 20260401 + idx, 10.0, 1000))
    for idx in range(39, 64):
        rows[idx]["close"] = 11.65
        rows[idx]["open"] = 11.65
        rows[idx]["high"] = 11.75
        rows[idx]["low"] = 11.55
    for idx in range(59, 64):
        rows[idx]["volume"] = 1600
    rows[-4]["close"] = 10.0
    rows[-4]["open"] = 10.0
    rows[-4]["high"] = 10.1
    rows[-4]["low"] = 9.9
    rows[-1] = {**rows[-1], "close": 11.9, "open": 11.85, "high": 12.0, "low": 11.8, "volume": 700}

    out = build_volume_pullback_candidates_from_rows(rows, names={"sh.600000": "偏热票"}, limit=10)

    assert round(out[0]["recent_3day_gain_pct"], 2) == 19
    assert out[0]["recent_3day_trend"] == "震荡上行"
    assert out[0]["short_term_heat_status"] == "高位，谨慎"
    assert out[0]["burst_filter_status"] == "高位，谨慎"


def test_volume_pullback_candidates_filter_over_20_pct_three_day_gain():
    rows = []
    for idx in range(64):
        rows.append(_bar("sh.600000", 20260401 + idx, 10.0, 1000))
    for idx in range(39, 64):
        rows[idx]["close"] = 11.85
        rows[idx]["open"] = 11.85
        rows[idx]["high"] = 11.95
        rows[idx]["low"] = 11.75
    for idx in range(59, 64):
        rows[idx]["volume"] = 1600
    rows[-4]["close"] = 10.0
    rows[-4]["open"] = 10.0
    rows[-4]["high"] = 10.1
    rows[-4]["low"] = 9.9
    rows[-1] = {**rows[-1], "close": 12.1, "open": 12.05, "high": 12.2, "low": 12.0, "volume": 700}

    out = build_volume_pullback_candidates_from_rows(rows, names={"sh.600000": "过热票"}, limit=10)

    assert out == []


def test_daily_report_includes_volume_pullback_candidates_in_json_and_markdown():
    class DummyDailySelectionReportService(DailySelectionReportService):
        def __init__(self):
            pass

        def _latest_batch(self):
            return None

        def _data_validation(self, latest_batch, market_model):
            return {"confidence": "中", "verified_items": [], "unverified_items": [], "data_scope": "test"}

        def _volume_pullback_candidates(self, limit):
            return [
                {
                    "code": "sh.600000",
                    "name": "样例A",
                    "close": 10.5,
                    "price_ma25_deviation_pct": 0.8,
                        "pressure_pattern": "小K线 / 缩量",
                        "volume_ratio": 0.72,
                        "recent_3day_gain_pct": 3.2,
                        "recent_3day_trend": "震荡上行",
                        "burst_filter_status": "通过",
                        "buy_point_type": "缩量回踩25日线",
                }
            ]

        def _announcement_risks_for_codes(self, codes, review_trade_date):
            return {
                "sh.600000": {
                    "announcement_risk_level": "high",
                    "latest_announcement_summary": "最新公告：利空｜控股股东拟减持股份预披露公告",
                    "announcement_sentiment": "利空",
                    "announcement_risk_items": [
                        {"title": "控股股东拟减持股份预披露公告", "risk_keywords": ["减持"]}
                    ],
                }
            }

        def _market_hotspot_snapshot(self, review_trade_date):
            return {
                "hotspot_status": "available",
                "hotspot_summary": "玻璃基板 / AI算力",
                "hotspot_items": [
                    {
                        "rank": 3,
                        "code": "sh.600000",
                        "name": "样例A",
                        "theme": "玻璃基板或成下一代先进封装核心材料",
                    }
                ],
            }

    report = DummyDailySelectionReportService().build_report(limit=5)

    assert report["volume_pullback_candidates"][0]["code"] == "sh.600000"
    assert report["volume_pullback_candidates"][0]["announcement_risk_level"] == "high"
    assert report["volume_pullback_candidates"][0]["announcement_sentiment"] == "利空"
    assert report["volume_pullback_candidates"][0]["hotspot_match_level"] == "强匹配"
    assert report["hotspot_snapshot"]["hotspot_summary"] == "玻璃基板 / AI算力"
    assert "## 【4】缩量回踩25日线候选池" in report["markdown"]
    assert "## 【2】今日热点主线" in report["markdown"]
    assert "行业热点方向" in report["markdown"]
    assert "最新公告：利空" in report["markdown"]
    assert "公告风险" not in report["markdown"]
    assert "| sh.600000 | 样例A | 10.50 | 0.80 | 3.20 | 震荡上行 | 通过 | 小K线 / 缩量 | 0.72 | 缩量回踩25日线 | 玻璃基板或成下一代先进封装核心材料 | 最新公告：利空｜控股股东拟减持股份预披露公告 |" in report["markdown"]


def test_daily_report_lists_all_executable_candidates_without_three_item_cap():
    class DummyDailySelectionReportService(DailySelectionReportService):
        def __init__(self):
            pass

        def _latest_batch(self):
            return {"batch_id": "test", "run_time": None}

        def _latest_selected_signals(self, latest_batch, limit):
            return [
                {
                    "code": f"sh.60000{i}",
                    "name": f"样例{i}",
                    "price": 10 + i * 0.1,
                    "structure_status": "结构完整",
                    "missing_tags": "",
                }
                for i in range(4)
            ]

        def _annotations_for_codes(self, codes):
            return {
                code: {
                    "manual_action_label": "强势票｜重点关注",
                    "close": 10 + idx * 0.1,
                    "ma25": 10,
                    "ma25_direction": "向上",
                    "vol_ma5": 1500,
                    "vol_ma60": 1000,
                    "vol_ma5_gt_vol_ma60": True,
                    "vol_ratio": 1.5,
                }
                for idx, code in enumerate(codes)
            }

        def _daily_volume_profiles(self, codes):
            return {code: {"buy_point_type": "二类做量", "volume_compression_label": "小K线"} for code in codes}

        def _data_validation(self, latest_batch, market_model):
            return {"confidence": "中", "verified_items": [], "unverified_items": [], "data_scope": "test"}

        def _volume_pullback_candidates(self, limit):
            return []

        def _announcement_risks_for_codes(self, codes, review_trade_date):
            return {}

        def _market_hotspot_snapshot(self, review_trade_date):
            return {"hotspot_status": "unverified", "hotspot_items": []}

    report = DummyDailySelectionReportService().build_report(limit=10)

    assert [x["code"] for x in report["executable"]] == ["sh.600000", "sh.600001", "sh.600002", "sh.600003"]
    assert "### 重点候选（全部符合条件）" in report["markdown"]
    assert "最多3只" not in report["markdown"]
    assert "- sh.600003 样例3：" in report["markdown"]


def test_html_report_renders_daily_selection_workspace():
    report = {
        "report_time": "2026-06-03 18:00:00",
        "review_trade_date": "2026-06-03",
        "next_trade_plan_date": "2026-06-04",
        "data_validation": {"confidence": "中"},
        "market_model": {"temperature": 62, "risk_state": "中性偏谨慎", "signal_count": 1, "executable_count": 1},
        "volume_pullback_candidates": [
            {
                "code": "sh.600000",
                "name": "样例A",
                "close": 10.5,
                "price_ma25_deviation_pct": 0.8,
                "pressure_pattern": "小K线 / 缩量",
                "volume_ratio": 0.72,
                "recent_3day_gain_pct": 3.2,
                "recent_3day_trend": "震荡上行",
                "short_term_heat_status": "正常",
                "burst_filter_status": "通过",
                "hotspot_match_summary": "热点强匹配：玻璃基板或成下一代先进封装核心材料",
                "hotspot_match_level": "强匹配",
                "hotspot_theme": "玻璃基板或成下一代先进封装核心材料",
                "buy_point_type": "缩量回踩25日线",
                "latest_announcement_summary": "最新公告：利空｜控股股东拟减持股份预披露公告",
                "announcement_sentiment": "利空",
                "announcement_risk_level": "high",
            }
        ],
        "core_candidates": [
            {
                "code": "sh.600000",
                "name": "样例A",
                "bucket": "可执行",
                "report_action_label": "可执行｜二类做量",
                "buy_point_type": "二类做量",
                "close": 10.5,
                "price_ma25_deviation_pct": 0.8,
                "ma25_direction": "向上",
                "vol_ma5_gt_vol_ma60": True,
                "recent_3day_gain_pct": 3.2,
                "recent_3day_trend": "震荡上行",
                "short_term_heat_status": "正常",
                "burst_filter_status": "通过",
                "hotspot_match_summary": "热点强匹配：玻璃基板或成下一代先进封装核心材料",
                "hotspot_match_level": "强匹配",
                "hotspot_theme": "玻璃基板或成下一代先进封装核心材料",
                "latest_announcement_summary": "最新公告：利空｜控股股东拟减持股份预披露公告",
                "announcement_sentiment": "利空",
                "announcement_risk_level": "high",
            }
        ],
        "executable": [],
        "rejected": [],
        "hotspot_snapshot": {
            "hotspot_status": "available",
            "hotspot_summary": "玻璃基板 / AI算力",
            "hotspot_items": [
                {"rank": 1, "code": "sz.000725", "name": "京东方Ａ", "theme": "玻璃基板或成下一代先进封装核心材料"}
            ],
        },
        "final_advice": {"strategy": "震荡", "open_new_position": "是", "summary": "测试"},
    }

    html = render_html_report(report)

    assert "<!doctype html>" in html
    assert "缩量回踩25日线候选池" in html
    assert "25日线位置%" in html
    assert "近3日涨幅%" in html
    assert "近3日走势" in html
    assert "起爆段过滤" in html
    assert "短线过热状态" not in html
    assert "今日热点主线" in html
    assert "行业热点方向" in html
    assert "玻璃基板或成下一代先进封装核心材料" in html
    assert "最新公告" in html
    assert "最新公告：利空" in html
    assert "日线右侧确认需次日收盘验证" in html
    assert "border-right:1px solid var(--line)" in html
    assert ".num { text-align:center" in html


def test_classify_candidate_uses_hard_2560_conditions_not_2568_score():
    strong = {
        "structure_status": "部分满足",
        "missing_tag_count": 1,
        "missing_tags_text": "#未突破",
        "ma25_direction": "向上",
        "vol_ma5": 1200,
        "vol_ma60": 1000,
        "vol_ma5_gt_vol_ma60": True,
        "price_ma25_deviation_pct": 1.2,
        "buy_point_type": "二类做量",
        "annotation": {
            "highlight_level": "D3+",
            "manual_action_label": "风险较多｜建议移出",
            "a_count": 2,
            "b_count": 1,
            "d_count": 5,
        },
    }
    risky = {
        "structure_status": "结构完整",
        "missing_tag_count": 0,
        "ma25_direction": "向上",
        "vol_ma5": 900,
        "vol_ma60": 1000,
        "vol_ma5_gt_vol_ma60": False,
        "price_ma25_deviation_pct": 1.2,
        "buy_point_type": "二类做量",
        "annotation": {
            "highlight_level": "A2+",
            "manual_action_label": "强势票｜重点关注",
            "a_count": 0,
            "b_count": 0,
            "d_count": 0,
        },
    }

    assert classify_candidate(strong)["bucket"] == "可执行"
    assert classify_candidate(strong)["trade_type"] == "二类做量"
    assert "未突破" not in classify_candidate(strong)["reject_reason"]
    assert classify_candidate(risky)["bucket"] == "淘汰"
    assert "5日均量线未站上60日均量线" in classify_candidate(risky)["reject_reason"]


def test_recent_3day_trend_classifies_direction_sequence():
    assert _recent_3day_trend([10, 10.2, 10.5, 10.8]) == "连续上行"
    assert _recent_3day_trend([10, 10.5, 10.2, 10.4]) == "震荡上行"
    assert _recent_3day_trend([10, 9.8, 10.1, 9.9]) == "震荡下行"
    assert _recent_3day_trend([10, 9.8, 9.6, 9.4]) == "连续下行"
    assert _recent_3day_trend([10, 10, 10, 10]) == "震荡"


def test_classify_candidate_filters_burst_acceleration_over_20_pct_three_day_gain():
    candidate = {
        "structure_status": "结构完整",
        "ma25_direction": "向上",
        "vol_ma5": 1200,
        "vol_ma60": 1000,
        "vol_ma5_gt_vol_ma60": True,
        "price_ma25_deviation_pct": 1.2,
        "recent_3day_gain_pct": 21.5,
        "burst_filter_status": "起爆加速，过滤",
        "buy_point_type": "二类做量",
        "annotation": {
            "highlight_level": "A2+",
            "manual_action_label": "强势票｜重点关注",
        },
    }

    result = classify_candidate(candidate)

    assert result["bucket"] == "淘汰"
    assert "近3日涨幅超过20%，起爆加速段过滤" in result["reject_reason"]
    assert result["report_action_label"] == "不符合2560买点｜近3日涨幅超过20%，起爆加速段过滤"


def test_classify_candidate_filters_continuous_three_day_downtrend():
    candidate = {
        "structure_status": "结构完整",
        "ma25_direction": "向上",
        "vol_ma5": 1200,
        "vol_ma60": 1000,
        "vol_ma5_gt_vol_ma60": True,
        "price_ma25_deviation_pct": 1.2,
        "recent_3day_gain_pct": -3.1,
        "recent_3day_trend": "连续下行",
        "burst_filter_status": "通过",
        "buy_point_type": "二类做量",
        "annotation": {
            "highlight_level": "A2+",
            "manual_action_label": "强势票｜重点关注",
        },
    }

    result = classify_candidate(candidate)

    assert result["bucket"] == "淘汰"
    assert "近3日连续下行，右侧未确认" in result["reject_reason"]
    assert result["report_action_label"] == "不符合2560买点｜近3日连续下行，右侧未确认"


def test_report_action_downgrades_strong_2568_when_hard_conditions_fail():
    candidate = {
        "structure_status": "结构完整",
        "missing_tag_count": 0,
        "ma25_direction": "向下",
        "vol_ma5": 1200,
        "vol_ma60": 1000,
        "vol_ma5_gt_vol_ma60": True,
        "price_ma25_deviation_pct": 1.2,
        "buy_point_type": "二类做量",
        "annotation": {
            "highlight_level": "A2+",
            "manual_action_label": "强势票｜重点关注",
            "a_count": 2,
            "b_count": 1,
            "d_count": 0,
        },
    }

    result = classify_candidate(candidate)

    assert result["bucket"] == "淘汰"
    assert result["report_action_label"] == "不符合2560买点｜25日均线未上行"
    assert "强势票｜重点关注" not in result["report_action_label"]


def test_missing_tags_are_expanded_to_actionable_2560_reasons():
    row = {"breakout_ok": 0, "near_resistance": 1}

    assert _compact_missing_tags('["#未突破"]') == "#未突破"
    assert _expand_missing_tags('["#未突破", "#高位"]', row) == (
        "#未突破：未突破30m近20周期高点/压力位 / "
        "#高位：接近30m近20周期高点压力区"
    )


def test_ma25_deviation_bucket_labels_retrace_zone():
    assert _ma25_deviation_bucket(1.22) == "≤3% 有效回踩区"
    assert _ma25_deviation_bucket(4.2) == "3%-5% 观察区"
    assert _ma25_deviation_bucket(7.0) == ">5% 非回踩买点"
    assert _ma25_deviation_bucket(None) == "无法验证"


def test_volume_profile_classifies_three_market_buy_points():
    first_cross_rows = [{"date": i, "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000} for i in range(60)]
    first_cross_rows[-5:] = [
        {**first_cross_rows[-5], "volume": 900},
        {**first_cross_rows[-4], "volume": 900},
        {**first_cross_rows[-3], "volume": 900},
        {**first_cross_rows[-2], "volume": 900},
        {**first_cross_rows[-1], "volume": 2600},
    ]
    profile = _volume_profile_from_daily_rows(first_cross_rows)
    assert profile["buy_point_type"] == "一类冲量"

    touch_rows = [{"date": i, "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000} for i in range(70)]
    for idx, vol in zip(range(50, 70), [1500, 1500, 1450, 1400, 1350, 1300, 1250, 1200, 1150, 1080, 1040, 1030, 1020, 1040, 1060, 1100, 1180, 1260, 1360, 1500]):
        touch_rows[idx]["volume"] = vol
    profile = _volume_profile_from_daily_rows(touch_rows)
    assert profile["buy_point_type"] == "二类做量"

    shrink_rows = [{"date": i, "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000} for i in range(80)]
    for idx in range(60, 77):
        shrink_rows[idx]["volume"] = 1800
    shrink_rows[-3]["volume"] = 1600
    shrink_rows[-2]["volume"] = 900
    shrink_rows[-1]["volume"] = 800
    profile = _volume_profile_from_daily_rows(shrink_rows)
    assert profile["buy_point_type"] == "三类缩量"


def test_volume_profile_reports_current_volume_ratio_against_previous_five_days():
    rows = [{"date": i, "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000} for i in range(65)]
    rows[-1]["volume"] = 2000

    profile = _volume_profile_from_daily_rows(rows)

    assert profile["current_volume_ratio_5"] == 2.0
    assert round(profile["daily_vol_ma5"] / profile["daily_vol_ma60"], 2) != 2.0


def test_technical_sort_prefers_second_then_third_then_first_and_near_ma25():
    second = {"bucket": "可执行", "buy_point_type": "二类做量", "price_ma25_deviation_pct": 2.5}
    third = {"bucket": "可执行", "buy_point_type": "三类缩量", "price_ma25_deviation_pct": 0.8}
    first = {"bucket": "可执行", "buy_point_type": "一类冲量", "price_ma25_deviation_pct": 0.2}
    rejected = {"bucket": "淘汰", "buy_point_type": "二类做量", "price_ma25_deviation_pct": 0.1}

    ordered = sorted([first, rejected, third, second], key=_technical_sort_key)

    assert ordered == [second, third, first, rejected]


def test_technical_sort_uses_hotspot_match_as_same_tier_tiebreaker():
    hot = {"bucket": "可执行", "buy_point_type": "二类做量", "price_ma25_deviation_pct": 1.8, "hotspot_match_level": "强匹配"}
    cold = {"bucket": "可执行", "buy_point_type": "二类做量", "price_ma25_deviation_pct": 0.2, "hotspot_match_level": "未匹配"}

    ordered = sorted([cold, hot], key=_technical_sort_key)

    assert ordered == [hot, cold]


def test_markdown_report_renders_internal_a_b_scope_without_external_claims():
    report = {
        "title": "内部数据版 2560 盘后选股报告",
        "technical_metadata": {
            "skill_parse_version": "daily-selection-skill-v1",
            "strategy_contract": "2560_v1.2.2_FinalFreeze",
            "canonical_fields": ["selection_status", "final_score", "recent_3d_pct"],
            "announcement_policy": "默认禁止逐票联网公告/研报调用；未显式开启时按 unverified 审计。",
        },
        "report_time": "2026-06-03 18:00:00",
        "review_trade_date": "2026-06-03",
        "next_trade_plan_date": "2026-06-04",
        "data_validation": {
            "confidence": "中",
            "latest_batch_id": "20260603",
            "market_readiness": [],
            "unverified_items": ["指数锚点", "账户风控"],
        },
        "market_model": {
            "temperature": 62,
            "risk_state": "中性偏谨慎",
            "signal_count": 2,
            "executable_count": 1,
            "watch_count": 0,
            "rejected_count": 1,
            "market_distribution": {"sh60": 1, "sz30": 1},
        },
        "core_candidates": [
            {
                "code": "sh.600000",
                "name": "样例股份",
                "bucket": "可执行",
                "structure_status": "结构完整",
                "selection_status": "focus",
                "final_score": 0.8123,
                "recent_3d_pct": 9.5,
                "explode_status": "warm",
                "market_state": "rebound",
                "environment_score": 0.7,
                "hot_topic_strength": "strong",
                "position_in_hot_topic": "leader",
                "hot_topic_score": 1.0,
                "volume_score": 0.8,
                "structure_score": 0.9,
                "intraday_score": 0.6,
                "pressure_score": 0.5,
                "buy_point_type": "二类做量",
                "missing_tags_text": "#未突破",
                "missing_tags_detail": "#未突破：未突破30m近20周期高点/压力位",
                "manual_action_label": "强势票｜重点关注",
                "report_action_label": "可执行｜二类做量",
                "close": 10.5,
                "ma25": 10.0,
                "ma25_direction": "向上",
                "price_ma25_deviation_pct": 5.0,
                "ma25_deviation_bucket": "3%-5% 观察区",
                "volume": 1200000,
                "vol_ma5": 1500000,
                "vol_ma60": 1000000,
                "vol_ma5_gt_vol_ma60": True,
                "pullback_ok": 1,
                "bullish_confirm": 0,
                "logic": "结构完整，2568 标注强势票｜重点关注。",
            }
        ],
        "candidates": [],
        "executable": [],
        "watchlist": [],
        "rejected": [{"code": "sz.300000", "name": "风险样例", "reject_reason": "风险较多｜建议移出"}],
        "final_advice": {
            "strategy": "震荡",
            "open_new_position": "是",
            "summary": "内部候选存在机会，但仍需次日条件触发。",
        },
    }

    markdown = render_markdown_report(report)

    assert "【2560职业短线交易系统 v5.1】盘后复盘与候选说明" in markdown
    assert "Skill解析版本：daily-selection-skill-v1" in markdown
    assert "策略冻结版本：2560_v1.2.2_FinalFreeze" in markdown
    assert "## 【3】v1.2.2 Final Freeze 字段审计" in markdown
    assert "selection_status 分布" in markdown
    assert "focus" in markdown
    assert "score_components" in markdown
    assert "final=0.81; structure=0.90; volume=0.80" in markdown
    assert "内部数据版" in markdown
    assert "## 【5】核心候选清单" in markdown
    assert "## 【7】重点候选与淘汰原因" in markdown
    assert "5日均量线" in markdown
    assert "60日均量线" in markdown
    assert "当日成交量" in markdown
    assert "25日线位置%" in markdown
    assert "距离25日线%" not in markdown
    assert "25日方向" in markdown
    assert "买点类型" in markdown
    assert "二类做量" in markdown
    assert "| 策略评估状态 | focus |" in markdown
    assert "| 策略总分 | 0.81 |" in markdown
    assert "| 分项得分 | final=0.81; structure=0.90; volume=0.80; topic=1.00; intraday=0.60; pressure=0.50; env=0.70 |" in markdown
    assert "| 近3日涨幅 / 起爆状态 | 9.50 / warm |" in markdown
    assert "| 市场环境 / 环境分 | rebound / 0.70 |" in markdown
    assert "| 题材强度 / 题材地位 | strong / leader |" in markdown
    assert "v1.2.2 selection_status" not in markdown
    assert "| 缺失条件 | #未突破 |" in markdown
    assert "| 缺失条件明细 | #未突破：未突破30m近20周期高点/压力位 |" in markdown
    assert "3%-5% 观察区" in markdown
    assert "可执行｜二类做量" in markdown
    assert "右侧确认 | 日线右侧确认需次日收盘验证" in markdown
    assert "5m回踩确认=是" not in markdown
    assert "胜率/盈亏比/Kelly | 待观察日（2026-06-04）收盘确认后计算" in markdown
    assert "指数锚点" in markdown
    assert "交易预案" not in markdown
    assert "核心交易候选" not in markdown
    assert "可执行交易与淘汰交易" not in markdown
    assert "是否开新仓" not in markdown


def test_internal_market_model_counts_buckets_and_distribution():
    candidates = [
        {"code": "sh.600000", "bucket": "可执行", "structure_status": "结构完整"},
        {"code": "sz.300000", "bucket": "观察", "structure_status": "部分满足"},
        {"code": "sh.688000", "bucket": "淘汰", "structure_status": "部分满足"},
    ]

    model = build_internal_market_model(candidates)

    assert model["signal_count"] == 3
    assert model["executable_count"] == 1
    assert model["watch_count"] == 1
    assert model["rejected_count"] == 1
    assert model["market_distribution"] == {"sh60": 1, "sz30": 1, "sh68": 1}
    assert 0 <= model["temperature"] <= 100


def test_report_cleans_nul_names_and_json_missing_tags():
    assert _clean_text("多浦乐\x00\x00") == "多浦乐"
    assert _compact_missing_tags('["#未突破", "#高位"]') == "#未突破 / #高位"

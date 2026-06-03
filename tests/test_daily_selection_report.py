from __future__ import annotations

from app.services.daily_selection_report import (
    build_internal_market_model,
    classify_candidate,
    _clean_text,
    render_markdown_report,
    _compact_missing_tags,
    _expand_missing_tags,
    _ma25_deviation_bucket,
)


def test_classify_candidate_uses_2560_signal_and_2568_risk_annotation():
    strong = {
        "structure_status": "结构完整",
        "missing_tag_count": 0,
        "strength_score_raw": 82,
        "annotation": {
            "highlight_level": "A2+",
            "manual_action_label": "强势票｜重点关注",
            "a_count": 2,
            "b_count": 1,
            "d_count": 0,
        },
    }
    risky = {
        "structure_status": "部分满足",
        "missing_tag_count": 3,
        "strength_score_raw": 55,
        "annotation": {
            "highlight_level": "D3+",
            "manual_action_label": "风险较多｜建议移出",
            "a_count": 0,
            "b_count": 0,
            "d_count": 5,
        },
    }

    assert classify_candidate(strong)["bucket"] == "可执行"
    assert classify_candidate(strong)["trade_type"] == "轻仓试错"
    assert classify_candidate(risky)["bucket"] == "淘汰"
    assert "风险较多" in classify_candidate(risky)["reject_reason"]


def test_report_action_downgrades_strong_2568_when_2560_score_is_not_qualified():
    candidate = {
        "structure_status": "部分满足",
        "missing_tag_count": 1,
        "strength_score_raw": 30,
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
    assert result["report_action_label"] == "不符合2560买点｜评分不足"
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


def test_markdown_report_renders_internal_a_b_scope_without_external_claims():
    report = {
        "title": "内部数据版 2560 盘后选股报告",
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
                "report_score": 0,
                "structure_status": "结构完整",
                "missing_tags_text": "#未突破",
                "missing_tags_detail": "#未突破：未突破30m近20周期高点/压力位",
                "manual_action_label": "强势票｜重点关注",
                "report_action_label": "可执行｜轻仓试错",
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

    assert "【2560职业短线交易系统 v5.1】盘后复盘与交易预案" in markdown
    assert "内部数据版" in markdown
    assert "## 【5】核心交易候选" in markdown
    assert "## 【7】可执行交易与淘汰交易" in markdown
    assert "5日均量线" in markdown
    assert "60日均量线" in markdown
    assert "当日成交量" in markdown
    assert "距离25日线%" in markdown
    assert "25日方向" in markdown
    assert "| 2560评分 | 0 |" in markdown
    assert "| 缺失条件 | #未突破 |" in markdown
    assert "| 缺失条件明细 | #未突破：未突破30m近20周期高点/压力位 |" in markdown
    assert "3%-5% 观察区" in markdown
    assert "可执行｜轻仓试错" in markdown
    assert "右侧确认 | 5m回踩确认=是；5m阳线确认=否；KDJ/MACD暂无，暂不计算" in markdown
    assert "胜率/盈亏比/Kelly | 需结合次日右侧确认、止损价和目标价后计算" in markdown
    assert "指数锚点" in markdown


def test_internal_market_model_counts_buckets_and_distribution():
    candidates = [
        {"code": "sh.600000", "bucket": "可执行", "report_score": 82, "structure_status": "结构完整"},
        {"code": "sz.300000", "bucket": "观察", "report_score": 66, "structure_status": "部分满足"},
        {"code": "sh.688000", "bucket": "淘汰", "report_score": 42, "structure_status": "部分满足"},
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

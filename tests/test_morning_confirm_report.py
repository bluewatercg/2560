from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_report_module():
    path = PROJECT_ROOT / "app/services/morning_confirm_report.py"
    if not path.exists():
        pytest.fail("app/services/morning_confirm_report.py is required")
    spec = importlib.util.spec_from_file_location(
        "morning_confirm_report_under_test",
        path,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _rows() -> list[dict]:
    return [
        {
            "code": "sh.600000",
            "name": "浦发银行",
            "yesterday_status": "focus",
            "source_trade_date": "2026-06-08",
            "trade_date": "2026-06-09",
            "morning_grade": "high",
            "pre_market_state": "pre_rebound",
            "missing_reason": None,
            "today_auction_volume": 1200,
            "yesterday_auction_volume": 1000,
            "auction_amplify_ratio": 1.2,
            "open_gap_pct": 2.1,
        },
        {
            "code": "sz.000001",
            "name": "平安银行",
            "yesterday_status": "watch",
            "source_trade_date": "2026-06-08",
            "trade_date": "2026-06-09",
            "morning_grade": "hold",
            "pre_market_state": "pre_rebound",
            "missing_reason": "avg5_insufficient_history",
            "today_auction_volume": 900,
            "yesterday_auction_volume": None,
            "avg5_auction_volume": 850,
            "auction_amplify_ratio": None,
            "open_gap_pct": -0.4,
        },
    ]


def test_morning_confirm_markdown_renders_required_table_and_dates():
    module = _load_report_module()

    markdown = module.render_morning_confirm_markdown(
        rows=_rows(),
        trade_date="2026-06-09",
        source_trade_date="2026-06-08",
    )

    assert markdown.startswith("# 2560 早盘确认报告\n")
    assert "- trade_date: 2026-06-09" in markdown
    assert "- source_trade_date: 2026-06-08" in markdown
    assert "| source_trade_date | trade_date | code | name | yesterday_status | morning_grade | pre_market_state | missing_reason | today_auction_volume | base_auction_volume | auction_amplify_ratio | open_gap_pct |" in markdown
    assert "| 2026-06-08 | 2026-06-09 | sh.600000 | 浦发银行 | focus | high | pre_rebound |  | 1200 | 1000 | 1.20 | 2.10% |" in markdown
    assert "| 2026-06-08 | 2026-06-09 | sz.000001 | 平安银行 | watch | hold | pre_rebound | 竞价历史不足 | 900 | 850 |  | -0.40% |" in markdown


def test_skill_morning_input_groups_results_missing_notes_and_actions():
    module = _load_report_module()

    markdown = module.render_skill_morning_input_markdown(
        rows=_rows(),
        trade_date="2026-06-09",
        source_trade_date="2026-06-08",
        market_environment={
            "pre_market_state": "pre_rebound",
            "index_auction_gain_pct": 0.35,
        },
    )

    assert markdown.startswith("# 2560 早盘 Skill 输入报告\n")
    assert "- trade_date: 2026-06-09" in markdown
    assert "- source_trade_date: 2026-06-08" in markdown
    assert "## 1. 早盘市场环境" in markdown
    assert "- pre_market_state: pre_rebound" in markdown
    assert "- 集合竞价指数涨幅: 0.35%" in markdown
    assert "## 2. 昨日候选池早盘确认结果" in markdown
    assert "- high: sh.600000 浦发银行" in markdown
    assert "- hold: sz.000001 平安银行" in markdown
    assert "- skipped: 无" in markdown
    assert "## 3. 数据缺失说明" in markdown
    assert "- sz.000001 平安银行: 竞价历史不足，morning_grade=hold" in markdown
    assert "## 4. 建议操作" in markdown
    assert "- 高度关注: sh.600000 浦发银行" in markdown
    assert "- 暂时观望: sz.000001 平安银行" in markdown


def test_report_package_helper_returns_standard_morning_filenames():
    module = _load_report_module()

    package = module.render_morning_report_package(
        rows=_rows(),
        trade_date="2026-06-09",
        source_trade_date="2026-06-08",
        market_environment={"pre_market_state": "pre_rebound"},
    )

    assert set(package) == {"09_morning_confirm.md", "10_skill_morning_input.md"}
    assert package["09_morning_confirm.md"].startswith("# 2560 早盘确认报告")
    assert package["10_skill_morning_input.md"].startswith("# 2560 早盘 Skill 输入报告")


def test_skip_row_is_rendered_without_candidate_ambiguity():
    module = _load_report_module()
    rows = [
        {
            "code": "__skip__",
            "morning_grade": "skipped",
            "missing_reason": "no_candidate_yesterday",
        }
    ]

    confirm = module.render_morning_confirm_markdown(
        rows=rows,
        trade_date="2026-06-09",
        source_trade_date="2026-06-08",
    )
    skill = module.render_skill_morning_input_markdown(
        rows=rows,
        trade_date="2026-06-09",
        source_trade_date="2026-06-08",
    )

    assert "| 2026-06-08 | 2026-06-09 | __skip__ |  |  | skipped |  | 昨日无候选 |" in confirm
    assert "- skipped: 昨日无候选（source_trade_date=2026-06-08, trade_date=2026-06-09）" in skill
    assert "- 数据完整，无缺失降级说明。" in skill
    assert "- 暂时观望: 无" in skill

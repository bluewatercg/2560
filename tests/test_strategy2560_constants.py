import logging
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_constants():
    spec = importlib.util.spec_from_file_location(
        "strategy2560_constants_under_test",
        PROJECT_ROOT / "app/services/strategy2560_constants.py",
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_morning_grade_contract_excludes_normal():
    constants = _load_constants()
    MorningGrade = constants.MorningGrade

    values = {item.value for item in MorningGrade}

    assert values == {
        "high",
        "upgrade_high",
        "normal_cautious",
        "hold",
        "downgrade",
        "skipped",
    }
    assert "normal" not in values


def test_missing_reason_values_are_frozen_contract():
    constants = _load_constants()
    MissingReason = constants.MissingReason

    assert MissingReason.NO_CANDIDATE.value == "no_candidate_yesterday"
    assert MissingReason.FALLBACK_DISABLED.value == "auction_data_missing_and_fallback_disabled"
    assert MissingReason.AVG5_INSUFFICIENT.value == "avg5_insufficient_history"
    assert MissingReason.AUCTION_MISSING_NO_AVG5.value == "auction_data_missing_and_avg5_unavailable"


def test_after_market_status_values_are_module_a_only():
    constants = _load_constants()
    AfterMarketStatus = constants.AfterMarketStatus

    assert {item.value for item in AfterMarketStatus} == {"focus", "watch", "reject"}


def test_render_missing_reason_known_unknown_and_none(caplog):
    constants = _load_constants()
    MissingReason = constants.MissingReason
    render_missing_reason = constants.render_missing_reason

    assert render_missing_reason(None) == ""
    assert render_missing_reason(MissingReason.NO_CANDIDATE.value) == "昨日无候选"

    with caplog.at_level(logging.WARNING):
        assert render_missing_reason("new_reason") == "未知原因（new_reason）"

    assert "未知 missing_reason 取值: new_reason" in caplog.text

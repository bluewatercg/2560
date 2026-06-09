from __future__ import annotations

import importlib.util
from enum import Enum
from pathlib import Path
import sys
import types

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _restore_modules(saved):
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _load_morning_confirm_engine():
    names = [
        "app",
        "app.services",
        "app.services.strategy2560_constants",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    app = types.ModuleType("app")
    services = types.ModuleType("app.services")
    constants = _load_module(
        "app.services.strategy2560_constants",
        "app/services/strategy2560_constants.py",
    )
    sys.modules["app"] = app
    sys.modules["app.services"] = services
    sys.modules["app.services.strategy2560_constants"] = constants
    try:
        return _load_module(
            "morning_confirm_engine_under_test",
            "app/services/morning_confirm_engine.py",
        )
    finally:
        _restore_modules(saved)


morning_confirm_engine = _load_morning_confirm_engine()
MissingReason = morning_confirm_engine.MissingReason
MorningGrade = morning_confirm_engine.MorningGrade
build_morning_confirm_rows = morning_confirm_engine.build_morning_confirm_rows
classify_morning_grade = morning_confirm_engine.classify_morning_grade
validate_morning_confirm_row = morning_confirm_engine.validate_morning_confirm_row


class FakeMorningClient:
    def __init__(self, auction_rows: dict[str, dict] | None = None):
        self.auction_rows = auction_rows or {}
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def load_auction_rows(self, codes: list[str]) -> dict[str, dict]:
        self.calls.append(("load_auction_rows", tuple(codes)))
        return self.auction_rows

    def load_pre_market_state(self) -> str:
        self.calls.append(("load_pre_market_state", ()))
        return "pre_rebound"

    def load_intraday_bars_after_930(self, _codes: list[str]) -> dict:
        self.calls.append(("load_intraday_bars_after_930", ()))
        raise AssertionError("post-9:30 data must not be read")

    def load_realtime_quotes_after_930(self, _codes: list[str]) -> dict:
        self.calls.append(("load_realtime_quotes_after_930", ()))
        raise AssertionError("post-9:30 data must not be read")


def _candidate(code: str, status: str) -> dict:
    return {"code": code, "yesterday_status": status}


class CandidateStatus(str, Enum):
    FOCUS = "focus"
    WATCH = "watch"


def _auction(
    today_volume: float,
    yesterday_volume: float | None,
    gap_pct: float,
    *,
    avg5: float | None = None,
    avg5_valid_days: int | None = None,
) -> dict:
    row = {
        "auction_volume": today_volume,
        "yesterday_auction_volume": yesterday_volume,
        "open_gap_pct": gap_pct,
    }
    if avg5 is not None:
        row["avg5_auction_volume"] = avg5
    if avg5_valid_days is not None:
        row["avg5_valid_days"] = avg5_valid_days
    return row


def test_validate_morning_confirm_row_enforces_skipped_code_pairing():
    validate_morning_confirm_row(
        {"code": "__skip__", "morning_grade": MorningGrade.SKIPPED.value}
    )

    with pytest.raises(ValueError, match="skipped"):
        validate_morning_confirm_row(
            {"code": "sh.600000", "morning_grade": MorningGrade.SKIPPED.value}
        )

    with pytest.raises(ValueError, match="__skip__"):
        validate_morning_confirm_row(
            {"code": "__skip__", "morning_grade": MorningGrade.HOLD.value}
        )


def test_no_yesterday_focus_or_watch_candidates_writes_skip_row_without_external_calls():
    client = FakeMorningClient()

    rows = build_morning_confirm_rows(
        yesterday_candidates=[],
        cfg={"auction_fallback_to_avg5": True, "avg5_min_valid_days": 3},
        client=client,
    )

    assert rows == [
        {
            "code": "__skip__",
            "morning_grade": MorningGrade.SKIPPED.value,
            "missing_reason": MissingReason.NO_CANDIDATE.value,
        }
    ]
    assert client.calls == []


@pytest.mark.parametrize(
    ("auction_row", "cfg", "expected_reason"),
    [
        (
            _auction(1000, None, 1.0),
            {"auction_fallback_to_avg5": False, "avg5_min_valid_days": 3},
            MissingReason.FALLBACK_DISABLED.value,
        ),
        (
            _auction(1000, None, 1.0, avg5=900, avg5_valid_days=4),
            {"auction_fallback_to_avg5": True, "avg5_min_valid_days": 5},
            MissingReason.AVG5_INSUFFICIENT.value,
        ),
        (
            _auction(1000, None, 1.0),
            {"auction_fallback_to_avg5": True, "avg5_min_valid_days": 3},
            MissingReason.AUCTION_MISSING_NO_AVG5.value,
        ),
    ],
)
def test_missing_yesterday_auction_volume_degrades_to_hold_with_specific_reason(
    auction_row: dict,
    cfg: dict,
    expected_reason: str,
):
    rows = build_morning_confirm_rows(
        yesterday_candidates=[_candidate("sh.600000", "focus")],
        auction_rows_by_code={"sh.600000": auction_row},
        cfg=cfg,
    )

    assert rows[0]["morning_grade"] == MorningGrade.HOLD.value
    assert rows[0]["missing_reason"] == expected_reason


@pytest.mark.parametrize(
    ("status", "today_volume", "base_volume", "gap_pct", "expected"),
    [
        ("focus", 1200, 1000, 0.0, MorningGrade.HIGH.value),
        ("focus", 1200, 1000, 3.0, MorningGrade.HIGH.value),
        ("focus", 1200, 1000, 3.1, MorningGrade.NORMAL_CAUTIOUS.value),
        ("focus", 900, 1000, 1.0, MorningGrade.HOLD.value),
        ("focus", 1200, 1000, -1.1, MorningGrade.DOWNGRADE.value),
        ("watch", 1200, 1000, 2.0, MorningGrade.UPGRADE_HIGH.value),
        ("watch", 1200, 1000, 3.1, MorningGrade.NORMAL_CAUTIOUS.value),
        ("watch", 900, 1000, 2.0, MorningGrade.HOLD.value),
        ("watch", 1200, 1000, -1.1, MorningGrade.HOLD.value),
    ],
)
def test_morning_grade_matrix_never_emits_normal(
    status: str,
    today_volume: float,
    base_volume: float,
    gap_pct: float,
    expected: str,
):
    grade = classify_morning_grade(
        yesterday_status=status,
        today_auction_volume=today_volume,
        base_auction_volume=base_volume,
        open_gap_pct=gap_pct,
        cfg={"auction_amplify_ratio": 1.0},
    )

    assert grade == expected
    assert grade != "normal"


def test_morning_confirmation_uses_only_auction_and_pre_market_client_methods():
    client = FakeMorningClient(
        {
            "sh.600000": _auction(1200, 1000, 2.0),
            "sz.000001": _auction(900, 1000, 1.0),
        }
    )

    rows = build_morning_confirm_rows(
        yesterday_candidates=[
            _candidate("sh.600000", "focus"),
            _candidate("sz.000001", "watch"),
        ],
        cfg={"auction_fallback_to_avg5": True, "avg5_min_valid_days": 3},
        client=client,
    )

    assert [row["morning_grade"] for row in rows] == [
        MorningGrade.HIGH.value,
        MorningGrade.HOLD.value,
    ]
    assert client.calls == [
        ("load_auction_rows", ("sh.600000", "sz.000001")),
        ("load_pre_market_state", ()),
    ]
    assert {row["pre_market_state"] for row in rows} == {"pre_rebound"}


def test_yesterday_candidate_status_accepts_string_enum_values():
    rows = build_morning_confirm_rows(
        yesterday_candidates=[_candidate("sh.600000", CandidateStatus.FOCUS)],
        auction_rows_by_code={"sh.600000": _auction(1200, 1000, 2.0)},
        cfg={"auction_fallback_to_avg5": True, "avg5_min_valid_days": 3},
    )

    assert rows[0]["morning_grade"] == MorningGrade.HIGH.value

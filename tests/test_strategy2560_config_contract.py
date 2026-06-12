import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ConfigService = _load_module(
    "config_service_under_test",
    "app/services/config_service.py",
).ConfigService


class _FakeResult:
    def __init__(self, rows: list[dict[str, str]]):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[tuple[str, str, str]]):
        self._rows = [
            {"config_key": key, "config_value": value, "value_type": value_type}
            for key, value, value_type in rows
        ]

    def execute(self, _query, _params):
        return _FakeResult(self._rows)


def _session_with_config(rows: list[tuple[str, str, str]]) -> _FakeSession:
    return _FakeSession(rows)


def test_strategy2560_config_defaults_include_after_market_contract_keys():
    cfg = ConfigService(_session_with_config([])).load_strategy_config()

    assert cfg["ma_price_period"] == 25
    assert cfg["vol_short_period"] == 5
    assert cfg["vol_long_period"] == 60
    assert cfg["atr_period"] == 14
    assert cfg["atr_compare_period"] == 20
    assert cfg["breakout_period"] == 20
    assert cfg["core_pullback_pct"] == 3.0
    assert cfg["pullback_max_pct"] == 5.0
    assert cfg["recent_3d_normal_max"] == 12.0
    assert cfg["recent_3d_warm_max"] == 18.0
    assert cfg["recent_3d_acceleration_max"] == 20.0
    assert cfg["recent_3d_overheat_min"] == 20.0
    assert cfg["high_window_30m"] == 20
    assert cfg["confirm_5m_bars"] == 6
    assert cfg["volume_cross_fallback_enabled"] is True
    assert cfg["volume_cross_confirm_ratio"] == 0.9
    assert cfg["market_state_enabled"] is True
    assert cfg["rebound_index_pct_min"] == 0.5
    assert cfg["rebound_limitup_min"] == 30
    assert cfg["rebound_up_ratio_min"] == 0.6
    assert cfg["hot_topic_required"] is True
    assert cfg["hot_topic_strength_required"] == "medium"
    assert cfg["position_required_for_focus"] == "strong"
    assert cfg["focus_score_min"] == 0.75
    assert cfg["watch_score_min"] == 0.45
    assert cfg["auction_fallback_to_avg5"] is True
    assert cfg["avg5_min_valid_days"] == 3
    assert cfg["display_emoji_enabled"] is False


def test_strategy2560_config_db_overrides_new_keys():
    cfg = ConfigService(
        _session_with_config(
            [
                ("ma_price_period", "30", "int"),
                ("hot_topic_required", "false", "bool"),
                ("avg5_min_valid_days", "5", "int"),
                ("focus_score_min", "0.82", "double"),
                ("watch_score_min", "0.51", "double"),
            ]
        )
    ).load_strategy_config()

    assert cfg["ma_price_period"] == 30
    assert cfg["hot_topic_required"] is False
    assert cfg["avg5_min_valid_days"] == 5
    assert cfg["focus_score_min"] == 0.82
    assert cfg["watch_score_min"] == 0.51


def test_deprecated_db_keys_do_not_override_canonical_keys():
    cfg = ConfigService(
        _session_with_config(
            [
                ("ma_short", "99", "int"),
                ("vol_short", "88", "int"),
                ("atp_period", "77", "int"),
                ("high_low_window", "66", "int"),
            ]
        )
    ).load_strategy_config()

    assert cfg["ma_price_period"] == 25
    assert cfg["vol_short_period"] == 5
    assert cfg["atr_period"] == 14
    assert cfg["high_window_30m"] == 20


def test_classify_recent_3d_pct_uses_config_thresholds():
    contract = _load_module(
        "strategy2560_contract_under_test",
        "app/services/strategy2560_contract.py",
    )
    ExplodeStatus = contract.ExplodeStatus
    classify_recent_3d_pct = contract.classify_recent_3d_pct

    cfg = ConfigService(_session_with_config([])).load_strategy_config()

    assert classify_recent_3d_pct(9, cfg) == ExplodeStatus.NORMAL
    assert classify_recent_3d_pct(13, cfg) == ExplodeStatus.WARM
    assert classify_recent_3d_pct(19, cfg) == ExplodeStatus.ACCELERATION
    assert classify_recent_3d_pct(21, cfg) == ExplodeStatus.OVERHEAT

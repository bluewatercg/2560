import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CANONICAL_ANALYSIS_FIELDS = [
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
]


def test_structure_2560_analysis_schema_contains_canonical_fields():
    sql = (PROJECT_ROOT / "sql/recreate_tables.sql").read_text(encoding="utf-8")

    for field in CANONICAL_ANALYSIS_FIELDS:
        assert field in sql


class _Scalar:
    def scalar_one(self):
        return 1


class _FakeDb:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))
        return _Scalar()

    def commit(self):
        return None


def _install_repository_stubs():
    sqlalchemy = types.ModuleType("sqlalchemy")
    sqlalchemy.text = lambda value: value
    sqlalchemy_orm = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm.Session = object
    app = types.ModuleType("app")
    app.__path__ = []
    db = types.ModuleType("app.db")
    db.__path__ = []
    clickhouse = types.ModuleType("app.db.clickhouse")
    clickhouse.get_clickhouse = lambda: None

    saved = {
        name: sys.modules.get(name)
        for name in ["sqlalchemy", "sqlalchemy.orm", "app", "app.db", "app.db.clickhouse"]
    }
    sys.modules["sqlalchemy"] = sqlalchemy
    sys.modules["sqlalchemy.orm"] = sqlalchemy_orm
    sys.modules["app"] = app
    sys.modules["app.db"] = db
    sys.modules["app.db.clickhouse"] = clickhouse
    return saved


def _restore_modules(saved):
    for name, previous in saved.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def _load_repository():
    saved = _install_repository_stubs()
    try:
        spec = importlib.util.spec_from_file_location(
            "repository_under_test",
            PROJECT_ROOT / "app/db/repository.py",
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module.KlineRepository
    finally:
        _restore_modules(saved)


def _base_row():
    return {
        "signal_uid": "uid-1",
        "batch_id": 1,
        "strategy_code": "S2560",
        "strategy_version": "test",
        "code": "sh.600000",
        "name": "样例",
        "signal_time": 20260609100000,
        "signal_period": "30m",
        "price": 10.5,
        "source": "test",
        "stock_status": "NORMAL",
        "has_2560_signal": 1,
        "price_near_ma25": 1,
        "ma25_slope_ok": 1,
        "volume_structure_ok": 1,
        "abnormal_filter_ok": 1,
        "trend_price_ok": 1,
        "trend_slope_ok": 1,
        "volatility_ok": 1,
        "breakout_ok": 1,
        "volume_ok": 1,
        "near_resistance": 0,
        "pullback_ok": 1,
        "bullish_confirm": 1,
        "structure_status": "结构完整",
        "strength_score_raw": 1.8,
        "missing_tags": "[]",
        "missing_tag_count": 0,
        "explain_text": "",
        "data_quality_status": "normal",
        "is_duplicate_signal": 0,
        "selected_signal": 1,
    }


def test_upsert_analysis_accepts_rows_without_canonical_fields():
    KlineRepository = _load_repository()
    fake_db = _FakeDb()

    analysis_id = KlineRepository(fake_db).upsert_analysis(_base_row())

    insert_sql, params = fake_db.calls[0]
    assert analysis_id == 1
    for field in CANONICAL_ANALYSIS_FIELDS:
        assert field in insert_sql
        assert field in params
        assert params[field] is None


def test_upsert_analysis_writes_canonical_fields_when_present():
    KlineRepository = _load_repository()
    fake_db = _FakeDb()
    row = _base_row()
    row.update(
        {
            "selection_status": "focus",
            "final_score": 0.88,
            "recent_3d_pct": 9.0,
            "explode_status": "normal",
            "market_state": "rebound",
            "environment_score": 1.0,
            "hot_topic_strength": "strong",
            "position_in_hot_topic": "leader",
            "hot_topic_score": 1.0,
            "volume_score": 0.8,
            "structure_score": 0.9,
            "intraday_score": 0.7,
            "pressure_score": 0.6,
        }
    )

    KlineRepository(fake_db).upsert_analysis(row)

    _, params = fake_db.calls[0]
    assert params["selection_status"] == "focus"
    assert params["final_score"] == 0.88
    assert params["hot_topic_strength"] == "strong"


def test_repository_exposes_external_call_storage_helpers():
    KlineRepository = _load_repository()
    fake_db = _FakeDb()
    repo = KlineRepository(fake_db)

    repo.upsert_cache(
        "eastmoney:topics",
        "eastmoney",
        {"topics": ["AI"]},
        4,
        "2026-06-09 14:30:00",
        "2026-06-09 10:30:00",
    )
    repo.update_cache_ttl(
        "eastmoney:topics",
        ttl_hours=0,
        expire_at="2026-06-09 10:30:00",
        now="2026-06-09 10:30:00",
    )
    repo.upsert_budget(
        "eastmoney",
        daily_limit=20,
        today_used=3,
        reset_at="2026-06-09",
        now="2026-06-09 10:30:00",
    )
    repo.write_log(
        "eastmoney",
        "eastmoney:topics",
        "success",
        message="ok",
        meta={"scope": "topic"},
        now="2026-06-09 10:30:00",
    )

    sql_calls = [call[0] for call in fake_db.calls]
    params_calls = [call[1] for call in fake_db.calls]

    assert any("external_data_cache" in sql for sql in sql_calls)
    assert any("external_call_budget" in sql for sql in sql_calls)
    assert any("external_call_log" in sql for sql in sql_calls)
    assert params_calls[0]["cache_key"] == "eastmoney:topics"
    assert params_calls[0]["provider"] == "eastmoney"
    assert params_calls[0]["payload"] == '{"topics": ["AI"]}'
    assert params_calls[2]["budget_key"] == "eastmoney"
    assert params_calls[3]["status"] == "success"

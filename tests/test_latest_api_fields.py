from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_latest_module():
    names = [
        "fastapi",
        "sqlalchemy",
        "sqlalchemy.orm",
        "app",
        "app.core",
        "app.core.market_scope",
        "app.db",
        "app.db.session",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules[name] = types.ModuleType(name)

    class _Router:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            def _decorator(fn):
                return fn

            return _decorator

    fastapi = sys.modules["fastapi"]
    fastapi.APIRouter = _Router
    fastapi.Depends = lambda dependency=None: dependency
    fastapi.Query = lambda default, **kwargs: default
    sys.modules["sqlalchemy"].text = lambda value: value
    sys.modules["sqlalchemy.orm"].Session = object
    sys.modules["app.core.market_scope"].market_sql_where = lambda field, market: f"{field} LIKE 'sh.60%'"
    sys.modules["app.db.session"].get_db = lambda: object()

    try:
        spec = importlib.util.spec_from_file_location(
            "latest_api_under_test",
            PROJECT_ROOT / "app/api/latest.py",
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


class _FakeRows:
    def mappings(self):
        return self

    def all(self):
        return [
            {
                "code": "sh.600000",
                "selection_status": "focus",
                "final_score": 0.88,
                "recent_3d_pct": 6.5,
                "explode_status": "normal",
                "market_state": "rebound",
                "environment_score": 1.0,
                "hot_topic_strength": "strong",
                "position_in_hot_topic": "leader",
                "hot_topic_score": 0.9,
            }
        ]


class _FakeDb:
    def __init__(self):
        self.sql = ""
        self.params = {}

    def execute(self, sql, params):
        self.sql = str(sql)
        self.params = params
        return _FakeRows()


def test_latest_by_stock_exposes_v122_selection_and_context_fields():
    module = _load_latest_module()
    db = _FakeDb()

    rows = module.latest_by_stock(market_type="sh60", limit=50, q=None, db=db)

    for field in [
        "selection_status",
        "final_score",
        "recent_3d_pct",
        "explode_status",
        "market_state",
        "environment_score",
        "hot_topic_strength",
        "position_in_hot_topic",
        "hot_topic_score",
    ]:
        assert f"a.{field}" in db.sql
        assert field in rows[0]
    assert db.params == {"limit": 50}

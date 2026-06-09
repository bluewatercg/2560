from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_service_module():
    names = [
        "sqlalchemy",
        "app",
        "app.core",
        "app.core.market_scope",
        "app.db",
        "app.db.clickhouse",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules[name] = types.ModuleType(name)

    sqlalchemy = sys.modules["sqlalchemy"]
    sqlalchemy.text = lambda sql: sql
    sys.modules["app.core.market_scope"].SUPPORTED_MARKET_SCOPES = ("all",)
    sys.modules["app.core.market_scope"].market_sql_where = lambda field, market: f"{field} LIKE '%'"
    sys.modules["app.db.clickhouse"].get_clickhouse = lambda: None

    try:
        spec = importlib.util.spec_from_file_location(
            "strategy2560_service_under_test",
            PROJECT_ROOT / "app/services/strategy2560_service.py",
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


class _FakeRow:
    def __init__(self, mapping):
        self._mapping = mapping


class _FakeResult:
    def __init__(self, mappings=None, scalar=None):
        self._mappings = mappings or []
        self._scalar = scalar

    def __iter__(self):
        for item in self._mappings:
            yield _FakeRow(item)

    def scalar_one(self):
        return self._scalar


class _FakeDB:
    def __init__(self):
        self.items = [
            {
                "id": 1,
                "batch_id": 20260609084520,
                "code": "sh.600000",
                "name": "浦发银行",
                "signal_time": "2026-06-09 10:00:00",
                "signal_period": "30m",
                "price": 12.3,
                "structure_status": "结构完整",
                "missing_tags": "",
                "missing_tag_count": 0,
                "explain_text": "demo",
                "data_quality_status": "ok",
                "selected_signal": 1,
                "industry_name": "银行",
                "board_name": "主板",
            }
        ]

    def execute(self, sql, params):
        sql_text = str(sql)
        filtered = self._filter_items(sql_text, params)
        if "COUNT(*)" in sql_text:
            return _FakeResult(scalar=len(filtered))
        return _FakeResult(mappings=filtered)

    def _filter_items(self, sql_text, params):
        code = params.get("code")
        normalized_code = params.get("normalized_code")
        if not code:
            return list(self.items)

        if "normalized_code" in sql_text:
            return [
                item
                for item in self.items
                if item["code"] == code or item["code"].split(".")[-1] == normalized_code
            ]

        return [item for item in self.items if item["code"] == code]


def test_list_signals_accepts_plain_six_digit_code_filter():
    module = _load_service_module()
    db = _FakeDB()

    result = module.Strategy2560Service(db).list_signals(code="600000")

    assert result["total"] == 1
    assert [item["code"] for item in result["items"]] == ["sh.600000"]

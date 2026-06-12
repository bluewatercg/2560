from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_reports_module():
    names = [
        "fastapi",
        "fastapi.responses",
        "sqlalchemy",
        "sqlalchemy.orm",
        "app",
        "app.db",
        "app.db.session",
        "app.services",
        "app.services.daily_selection_report",
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

        def post(self, *args, **kwargs):
            def _decorator(fn):
                return fn

            return _decorator

    class _HTTPException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class _ReportService:
        def __init__(self, db):
            self.db = db

        def build_report(self, limit: int = 50):
            return {"markdown": f"generated limit={limit}"}

    fastapi = sys.modules["fastapi"]
    fastapi.APIRouter = _Router
    fastapi.Depends = lambda dependency=None: dependency
    fastapi.HTTPException = _HTTPException
    fastapi.Query = lambda default, **kwargs: default
    sys.modules["fastapi.responses"].HTMLResponse = str
    sys.modules["fastapi.responses"].PlainTextResponse = str
    sys.modules["sqlalchemy.orm"].Session = object
    sys.modules["app.db.session"].get_db = lambda: object()
    report_service = sys.modules["app.services.daily_selection_report"]
    report_service.DailySelectionReportService = _ReportService
    report_service.render_html_report = lambda report: "<html></html>"

    try:
        spec = importlib.util.spec_from_file_location(
            "reports_api_under_test",
            PROJECT_ROOT / "app/api/reports.py",
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


def test_daily_selection_markdown_reads_cache_without_regeneration(tmp_path, monkeypatch):
    module = _load_reports_module()
    monkeypatch.setenv("REPORT_CACHE_DIR", str(tmp_path))
    (tmp_path / "daily-selection.md").write_text("cached report", encoding="utf-8")

    assert module.daily_selection_report_markdown() == "cached report"


def test_daily_selection_markdown_new_generates_and_overwrites_cache(tmp_path, monkeypatch):
    module = _load_reports_module()
    monkeypatch.setenv("REPORT_CACHE_DIR", str(tmp_path))
    cache_file = tmp_path / "daily-selection.md"
    cache_file.write_text("old report", encoding="utf-8")

    generated = module.daily_selection_report_markdown_new(limit=7, db=object())

    assert generated == "generated limit=7"
    assert cache_file.read_text(encoding="utf-8") == "generated limit=7"


def test_daily_selection_markdown_returns_404_when_cache_missing(tmp_path, monkeypatch):
    module = _load_reports_module()
    monkeypatch.setenv("REPORT_CACHE_DIR", str(tmp_path))

    try:
        module.daily_selection_report_markdown()
    except module.HTTPException as exc:
        assert exc.status_code == 404
        assert "/api/reports/daily-selection.md/new" in exc.detail
    else:
        raise AssertionError("expected cache-missing HTTPException")

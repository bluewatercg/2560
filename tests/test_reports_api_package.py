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
        "app.services.report_package_service",
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
    package_service = sys.modules["app.services.report_package_service"]
    package_service.DailyReportPackageService = None
    package_service.report_package_file_path = None

    try:
        spec = importlib.util.spec_from_file_location(
            "reports_api_package_under_test",
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


def test_daily_package_new_generates_package_with_service_contract(monkeypatch):
    module = _load_reports_module()
    calls = []

    class _PackageService:
        def __init__(self, db):
            self.db = db

        def generate_daily_package(self, *, trade_date: str):
            calls.append((self.db, trade_date))
            return {
                "trade_date": trade_date,
                "batch_id": "20260609042344",
                "status": "generated",
                "files": [
                    "reports/2026-06-09/01_daily_selection.md",
                    "reports/2026-06-09/08_skill_input.md",
                ],
            }

    monkeypatch.setattr(module, "DailyReportPackageService", _PackageService)
    db = object()

    result = module.daily_report_package_new(trade_date="2026-06-09", db=db)

    assert result == {
        "trade_date": "2026-06-09",
        "batch_id": "20260609042344",
        "status": "generated",
        "files": [
            "reports/2026-06-09/01_daily_selection.md",
            "reports/2026-06-09/08_skill_input.md",
        ],
    }
    assert calls == [(db, "2026-06-09")]


def test_daily_package_new_supports_report_package_service_contract(monkeypatch):
    module = _load_reports_module()
    calls = []

    class _PackageService:
        def generate_after_market_package_from_db(self, db, trade_date: str):
            calls.append((db, trade_date))
            return {
                "trade_date": trade_date,
                "batch_id": "20260609042344",
                "status": "generated",
                "files": ["reports/2026-06-09/08_skill_input.md"],
            }

    monkeypatch.setattr(module, "DailyReportPackageService", None)
    monkeypatch.setattr(module, "ReportPackageService", _PackageService)
    db = object()

    result = module.daily_report_package_new(trade_date="2026-06-09", db=db)

    assert result["trade_date"] == "2026-06-09"
    assert result["status"] == "generated"
    assert calls == [(db, "2026-06-09")]


def test_skill_input_reads_08_skill_input_as_plain_text(tmp_path, monkeypatch):
    module = _load_reports_module()
    package_dir = tmp_path / "reports" / "2026-06-09"
    package_dir.mkdir(parents=True)
    skill_input = package_dir / "08_skill_input.md"
    skill_input.write_text("skill input body", encoding="utf-8")
    calls = []

    def _fake_path(*, trade_date: str, filename: str):
        calls.append((trade_date, filename))
        return skill_input

    monkeypatch.setattr(module, "report_package_file_path", _fake_path)

    result = module.skill_input_report_markdown(trade_date="2026-06-09")

    assert result == "skill input body"
    assert calls == [("2026-06-09", "08_skill_input.md")]


def test_daily_package_file_reads_allowed_exact_basename(tmp_path, monkeypatch):
    module = _load_reports_module()
    package_dir = tmp_path / "reports" / "2026-06-09"
    package_dir.mkdir(parents=True)
    report_file = package_dir / "04_scan_summary.json"
    report_file.write_text('{"count": 3}', encoding="utf-8")

    def _fake_path(*, trade_date: str, filename: str):
        return report_file

    monkeypatch.setattr(module, "report_package_file_path", _fake_path)

    result = module.daily_report_package_file(
        trade_date="2026-06-09",
        filename="04_scan_summary.json",
    )

    assert result == '{"count": 3}'


def test_daily_package_file_allows_simple_2560_hard_metrics_report(tmp_path, monkeypatch):
    module = _load_reports_module()
    package_dir = tmp_path / "reports" / "2026-06-09"
    package_dir.mkdir(parents=True)
    report_file = package_dir / "09_simple_2560_hard_metrics.md"
    report_file.write_text("# simple metrics", encoding="utf-8")

    def _fake_path(*, trade_date: str, filename: str):
        return report_file

    monkeypatch.setattr(module, "report_package_file_path", _fake_path)

    result = module.daily_report_package_file(
        trade_date="2026-06-09",
        filename="09_simple_2560_hard_metrics.md",
    )

    assert result == "# simple metrics"


def test_daily_package_file_rejects_path_traversal_before_service(monkeypatch):
    module = _load_reports_module()

    def _unexpected_path(*, trade_date: str, filename: str):
        raise AssertionError("path traversal must be rejected before service lookup")

    monkeypatch.setattr(module, "report_package_file_path", _unexpected_path)

    try:
        module.daily_report_package_file(
            trade_date="2026-06-09",
            filename="../08_skill_input.md",
        )
    except module.HTTPException as exc:
        assert exc.status_code == 400
        assert "filename" in exc.detail
    else:
        raise AssertionError("expected filename validation HTTPException")


def test_daily_package_file_returns_404_when_missing(tmp_path, monkeypatch):
    module = _load_reports_module()

    def _fake_path(*, trade_date: str, filename: str):
        return tmp_path / "reports" / trade_date / filename

    monkeypatch.setattr(module, "report_package_file_path", _fake_path)

    try:
        module.daily_report_package_file(
            trade_date="2026-06-09",
            filename="08_skill_input.md",
        )
    except module.HTTPException as exc:
        assert exc.status_code == 404
        assert "not found" in exc.detail
    else:
        raise AssertionError("expected missing package file HTTPException")

from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.daily_selection_report import DailySelectionReportService, render_html_report

try:
    _report_package_service = import_module("app.services.report_package_service")
except ModuleNotFoundError as exc:
    if exc.name != "app.services.report_package_service":
        raise
    DailyReportPackageService = None
    ReportPackageService = None
    _service_report_package_file_path = None
else:
    DailyReportPackageService = getattr(_report_package_service, "DailyReportPackageService", None)
    ReportPackageService = getattr(_report_package_service, "ReportPackageService", None)
    _service_report_package_file_path = getattr(_report_package_service, "report_package_file_path", None)

try:
    _morning_report_package_service = import_module("app.services.morning_report_package_service")
except ModuleNotFoundError as exc:
    if exc.name != "app.services.morning_report_package_service":
        raise
    MorningReportPackageService = None
else:
    MorningReportPackageService = getattr(_morning_report_package_service, "MorningReportPackageService", None)


def report_package_file_path(*, trade_date: str, filename: str) -> Path:
    if _service_report_package_file_path is not None:
        return Path(_service_report_package_file_path(trade_date=trade_date, filename=filename))
    return Path(os.getenv("REPORT_PACKAGE_DIR", "reports")) / trade_date / filename


router = APIRouter(prefix="/api/reports", tags=["reports"])


ALLOWED_DAILY_PACKAGE_FILENAMES = {
    "01_daily_selection.md",
    "02_focus_full_reports.md",
    "03_watch_lite_reports.md",
    "04_scan_summary.json",
    "05_focus_watch_list.json",
    "06_reject_summary.json",
    "07_field_audit.json",
    "08_skill_input.md",
    "09_morning_confirm.md",
    "10_skill_morning_input.md",
}


def _report_cache_path() -> Path:
    cache_dir = Path(os.getenv("REPORT_CACHE_DIR", "logs/reports"))
    return cache_dir / "daily-selection.md"


def _write_report_cache(markdown: str) -> Path:
    path = _report_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(markdown, encoding="utf-8")
    tmp.replace(path)
    return path


def _validate_daily_package_filename(filename: str) -> str:
    if (
        not filename
        or filename != Path(filename).name
        or "/" in filename
        or "\\" in filename
        or filename not in ALLOWED_DAILY_PACKAGE_FILENAMES
    ):
        raise HTTPException(status_code=400, detail="invalid report package filename")
    return filename


def _read_daily_package_file(trade_date: str, filename: str) -> str:
    safe_filename = _validate_daily_package_filename(filename)
    path = Path(report_package_file_path(trade_date=trade_date, filename=safe_filename))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="report package file not found")
    return path.read_text(encoding="utf-8")


@router.get("/daily-selection")
def daily_selection_report(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return DailySelectionReportService(db).build_report(limit=limit)


@router.get("/daily-selection.md", response_class=PlainTextResponse)
def daily_selection_report_markdown(
):
    path = _report_cache_path()
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="daily-selection.md cache not found; call /api/reports/daily-selection.md/new first",
        )
    return path.read_text(encoding="utf-8")


@router.get("/daily-selection.md/new", response_class=PlainTextResponse)
def daily_selection_report_markdown_new(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    report = DailySelectionReportService(db).build_report(limit=limit)
    markdown = report["markdown"]
    _write_report_cache(markdown)
    return markdown


@router.get("/daily-selection.html", response_class=HTMLResponse)
def daily_selection_report_html(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    report = DailySelectionReportService(db).build_report(limit=limit)
    return render_html_report(report)


@router.post("/daily-package/new")
def daily_report_package_new(
    trade_date: str = Query(...),
    db: Session = Depends(get_db),
):
    if DailyReportPackageService is not None:
        return DailyReportPackageService(db).generate_daily_package(trade_date=trade_date)
    if ReportPackageService is not None:
        return ReportPackageService().generate_after_market_package_from_db(
            db,
            trade_date=trade_date,
        )
    else:
        raise HTTPException(status_code=503, detail="report package service unavailable")


@router.post("/morning-package/new")
def morning_report_package_new(
    trade_date: str = Query(...),
    source_trade_date: str | None = Query(None),
    db: Session = Depends(get_db),
):
    if MorningReportPackageService is None:
        raise HTTPException(status_code=503, detail="morning report package service unavailable")
    try:
        return MorningReportPackageService(db).generate_morning_package(
            trade_date=trade_date,
            source_trade_date=source_trade_date,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/skill-input.md", response_class=PlainTextResponse)
def skill_input_report_markdown(
    trade_date: str = Query(...),
):
    return _read_daily_package_file(trade_date=trade_date, filename="08_skill_input.md")


@router.get("/morning-confirm.md", response_class=PlainTextResponse)
def morning_confirm_report_markdown(
    trade_date: str = Query(...),
):
    return _read_daily_package_file(trade_date=trade_date, filename="09_morning_confirm.md")


@router.get("/skill-morning-input.md", response_class=PlainTextResponse)
def skill_morning_input_report_markdown(
    trade_date: str = Query(...),
):
    return _read_daily_package_file(trade_date=trade_date, filename="10_skill_morning_input.md")


@router.get("/daily-package/file", response_class=PlainTextResponse)
def daily_report_package_file(
    trade_date: str = Query(...),
    filename: str = Query(...),
):
    return _read_daily_package_file(trade_date=trade_date, filename=filename)

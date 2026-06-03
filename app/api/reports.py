from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.daily_selection_report import DailySelectionReportService


router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/daily-selection")
def daily_selection_report(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return DailySelectionReportService(db).build_report(limit=limit)


@router.get("/daily-selection.md", response_class=PlainTextResponse)
def daily_selection_report_markdown(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    report = DailySelectionReportService(db).build_report(limit=limit)
    return report["markdown"]

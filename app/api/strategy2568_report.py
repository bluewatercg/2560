from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.annotation_engine_2568 import AnnotationEngine2568
from app.services.report_2568_pdf import Report2568PdfBuilder

router = APIRouter(prefix="/api/strategy/2568", tags=["strategy-2568-report"])


@router.get("/report.pdf")
def export_report_pdf(
    market_type: str = Query("all"),
    limit: int = Query(500, ge=1, le=5000),
    q: str | None = Query(None),
    summary: str | None = Query(None),
    risk_only: int = Query(0, ge=0, le=1),
    manual_action: str | None = Query(None),
    min_a: int | None = Query(None, ge=0, le=10),
    min_b: int | None = Query(None, ge=0, le=10),
    min_d: int | None = Query(None, ge=0, le=10),
    db: Session = Depends(get_db),
):
    data = AnnotationEngine2568(db).annotations(
        market_type=market_type,
        limit=limit,
        q=q,
        summary=summary,
        risk_only=bool(risk_only),
        manual_action=manual_action,
        min_a=min_a,
        min_b=min_b,
        min_d=min_d,
    )
    pdf = Report2568PdfBuilder(
        data,
        params={
            "market_type": market_type,
            "limit": limit,
            "q": q,
            "summary": summary,
            "risk_only": risk_only,
            "manual_action": manual_action,
            "min_a": min_a,
            "min_b": min_b,
            "min_d": min_d,
        },
    ).build()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=strategy2568_report.pdf"},
    )

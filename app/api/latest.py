from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.session import get_db

router = APIRouter(prefix="/api/latest", tags=["latest"])


def _market_where(market_type: str) -> str:
    mt = (market_type or "all").lower()
    if mt == "sh":
        return "s.code LIKE 'sh.%'"
    if mt == "sz":
        return "s.code LIKE 'sz.%'"
    if mt == "sh60":
        return "s.code LIKE 'sh.60%'"
    if mt == "sh68":
        return "s.code LIKE 'sh.68%'"
    if mt == "sz00":
        return "s.code LIKE 'sz.00%'"
    if mt == "sz30":
        return "s.code LIKE 'sz.30%'"
    return "(s.code LIKE 'sh.%' OR s.code LIKE 'sz.%')"


@router.get("/by-stock")
def latest_by_stock(
    market_type: str = Query("all"),
    limit: int = Query(1000, ge=1, le=10000),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    where = [_market_where(market_type)]
    params = {"limit": limit}
    if q:
        where.append("(s.code LIKE :kw OR s.name LIKE :kw)")
        params["kw"] = f"%{q.strip()}%"
    where_sql = " AND ".join(where)
    sql = f"""
    WITH latest_batch AS (
        SELECT batch_id
        FROM analysis_batch
        WHERE strategy_code='S2560' AND status='success'
        ORDER BY run_time DESC
        LIMIT 1
    ), latest_signal AS (
        SELECT a.*
        FROM structure_2560_analysis a
        JOIN latest_batch b ON a.batch_id=b.batch_id
    )
    SELECT
        s.code,
        s.name,
        CASE WHEN a.id IS NULL THEN 'no_signal' ELSE 'signal' END AS latest_status,
        a.batch_id,
        a.signal_time,
        a.signal_period,
        a.price,
        a.structure_status,
        a.missing_tags,
        a.missing_tag_count,
        a.explain_text
    FROM stock_info s
    LEFT JOIN latest_signal a ON a.code=s.code
    WHERE {where_sql}
    ORDER BY s.code
    LIMIT :limit
    """
    return db.execute(text(sql), params).mappings().all()

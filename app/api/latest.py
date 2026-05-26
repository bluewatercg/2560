from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.market_scope import market_sql_where
from app.db.session import get_db

router = APIRouter(prefix="/api/latest", tags=["latest"])


def _market_where(market_type: str) -> str:
    return market_sql_where("s.code", market_type)


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
    LEFT JOIN structure_2560_analysis a ON a.code=s.code
        AND a.batch_id = (
            SELECT CAST(batch_id AS CHAR)
            FROM analysis_batch
            WHERE strategy_code='S2560' AND status='success'
            ORDER BY run_time DESC
            LIMIT 1
        )
    WHERE {where_sql}
    ORDER BY s.code
    LIMIT :limit
    """
    return db.execute(text(sql), params).mappings().all()

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
    WITH latest_batch AS (
        SELECT batch_id, run_time
        FROM analysis_batch
        WHERE strategy_code='S2560' AND status='success'
        ORDER BY run_time DESC
        LIMIT 1
    )
    SELECT
        s.code,
        s.name,
        CASE WHEN a.id IS NULL THEN '未命中' ELSE '命中' END AS latest_status,
        lb.batch_id,
        lb.run_time AS batch_run_time,
        a.signal_time,
        a.signal_period,
        a.price,
        COALESCE(a.structure_status, '-') AS structure_status,
        a.selection_status,
        a.final_score,
        a.recent_3d_pct,
        a.explode_status,
        a.market_state,
        a.environment_score,
        a.hot_topic_strength,
        a.position_in_hot_topic,
        a.hot_topic_score,
        a.missing_tags,
        a.missing_tag_count,
        CASE WHEN a.id IS NULL THEN '最新成功批次已计算，该股票未命中2560结构。' ELSE a.explain_text END AS explain_text
    FROM stock_info s
    CROSS JOIN latest_batch lb
    LEFT JOIN structure_2560_analysis a ON a.code=s.code
        AND CAST(a.batch_id AS CHAR) = CAST(lb.batch_id AS CHAR)
    WHERE {where_sql}
    ORDER BY s.code
    LIMIT :limit
    """
    return db.execute(text(sql), params).mappings().all()
